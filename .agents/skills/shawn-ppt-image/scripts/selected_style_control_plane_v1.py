#!/usr/bin/env python3
"""Thin selected-style adapter over the shared Shawn-PPT-image mainline."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pipeline_control as pc
import normalize_fast8_chrome_contract as normalize_chrome


CONTROL_VERSION = 1
CONTENT_BUNDLE_VERSION = 1
ASSETS_BUNDLE_VERSION = 1
VISUAL_PLAN_VERSION = 1
STYLE_CONTRACT_VERSION = 3
JUDGE_JOB_VERSION = 1
JUDGE_REPORT_VERSION = 1
GLOBAL_IMAGEGEN_CAPACITY = pc.FAST8_JIT_STABLE_IMAGEGEN_SLOT_LIMIT
EXECUTOR_AGENT_ID = "selected-style-mechanical-executor-v1"
SCRIPT_PATH = Path(__file__).resolve()


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False))


def capture(function, **kwargs: Any) -> dict[str, Any]:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        function(argparse.Namespace(**kwargs))
    raw = stream.getvalue().strip()
    return json.loads(raw) if raw else {}


def require_run(state_path: Path) -> tuple[dict[str, Any], Path]:
    state_path = state_path.expanduser().resolve()
    state = pc.read_json(state_path)
    if state.get("run_mode") != pc.SELECTED_STYLE_EXPANSION_MODE:
        raise SystemExit("selected-style control plane 只适用于 selected_style_expansion")
    project_dir = pc.project_dir_for_state(state_path, state)
    expected = (project_dir / "state" / "selected_style_run_state.json").resolve()
    if state_path != expected:
        raise SystemExit(f"扩页 state 必须使用规范路径：{expected}")
    page_order = state.get("page_order")
    pages = state.get("pages")
    if not isinstance(page_order, list) or not page_order or not isinstance(pages, dict):
        raise SystemExit("扩页状态缺少 page_order/pages")
    if set(str(item) for item in page_order) != set(str(key) for key in pages):
        raise SystemExit("扩页 page_order 与 pages 不一致")
    if pc.normalize_style(state.get("selected_style")) is None:
        raise SystemExit("扩页状态缺少 selected_style")
    return state, project_dir


def canonical_paths(project_dir: Path) -> dict[str, Path]:
    raw = project_dir / "state" / "director_inputs"
    return {
        "raw": raw,
        "source_packet": raw / "authoritative_expansion_packet.json",
        "content_raw": raw / "content_bundle.raw.json",
        "assets_raw": raw / "chrome_assets_bundle.raw.json",
        "visual_raw": raw / "visual_family_plan.raw.json",
        "chrome": raw / "global_chrome_contract.normalized.json",
        "style_contract": project_dir / "selected_style_contract.json",
        "content_dir": project_dir / "content_contracts",
        "jobs_dir": project_dir / "page_jobs",
        "manifests": project_dir / "state" / "selected_style_manifests",
        "claims": project_dir / "state" / "selected_style_claims",
        "receipts": project_dir / "style_jobs" / "results",
        "judge_job": project_dir / "visual_qa_jobs" / "selected_style_judge.json",
        "judge_results": project_dir / "visual_qa_jobs" / "results",
    }


def exact_page_map(value: Any, page_order: list[str], label: str) -> dict[str, dict[str, Any]]:
    if isinstance(value, list):
        values = value
    elif isinstance(value, dict):
        values = []
        for key, item in value.items():
            if not isinstance(item, dict):
                raise SystemExit(f"{label}.{key} 必须是对象")
            values.append({**item, "page_id": item.get("page_id", key)})
    else:
        raise SystemExit(f"{label} 必须是页对象或页数组")
    result: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict) or item.get("page_id") is None:
            raise SystemExit(f"{label} 页面记录缺少 page_id")
        matches = [page for page in page_order if pc.page_ids_match(page, item["page_id"])]
        if len(matches) != 1 or matches[0] in result:
            raise SystemExit(f"{label} page_id 不在规范范围或重复：{item.get('page_id')}")
        result[matches[0]] = dict(item)
        result[matches[0]]["page_id"] = matches[0]
    if set(result) != set(page_order):
        raise SystemExit(f"{label} 必须恰好覆盖 page_order")
    return result


def normalize_asset_items(items: Any, label: str) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise SystemExit(f"{label} 必须是数组")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        value = dict(item) if isinstance(item, dict) else None
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            raise SystemExit(f"{label}[{index}] 缺少 path")
        usage = str(value.get("asset_usage") or "")
        if usage not in {"render_asset", "planning_evidence"}:
            raise SystemExit(
                f"{label}[{index}] 必须显式声明 asset_usage=render_asset|planning_evidence"
            )
        path = Path(value["path"]).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise SystemExit(f"{label}[{index}] 必须是存在的绝对路径")
        path = path.resolve()
        if usage == "render_asset" and path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise SystemExit(f"{label}[{index}] 不是可传给 ImageGen 的光栅图片")
        role = str(value.get("role") or "").strip()
        use = str(value.get("use") or "").strip()
        if not role or not use:
            raise SystemExit(f"{label}[{index}] 必须显式声明 role 与 use")
        key = (str(path), usage)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            **value,
            "path": str(path),
            "asset_usage": usage,
            "role": role,
            "use": use,
            "sha256": pc.file_sha256(path),
            "size_bytes": path.stat().st_size,
        })
    return result


def split_asset_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        [dict(item) for item in items if item.get("asset_usage") == "render_asset"],
        [dict(item) for item in items if item.get("asset_usage") == "planning_evidence"],
    )


def normalize_representation_disclosure(plan: dict[str, Any], page_id: str) -> dict[str, Any]:
    raw = plan.get("representation_disclosure")
    if not isinstance(raw, dict):
        raise SystemExit(f"页 {page_id} 必须显式声明 representation_disclosure")
    mode = str(raw.get("mode") or "")
    if mode not in {"none", "visible"}:
        raise SystemExit(f"页 {page_id} representation_disclosure.mode 只允许 none|visible")
    if mode == "none":
        if raw.get("visible_text") not in {None, ""}:
            raise SystemExit(f"页 {page_id} disclosure=none 时不得保留 visible_text")
        return {"mode": "none"}
    visible_text = str(raw.get("visible_text") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    if not visible_text or not reason:
        raise SystemExit(f"页 {page_id} disclosure=visible 时必须提供 visible_text 与 reason")
    if len(visible_text) > 120:
        raise SystemExit(f"页 {page_id} representation_disclosure.visible_text 过长")
    return {"mode": "visible", "visible_text": visible_text, "reason": reason}


def style_anchor_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("style_anchors") or []
    if not isinstance(raw, list) or len(raw) > 2:
        raise SystemExit("扩页 style_anchors 必须是零至两个对象")
    if not raw:
        return []
    normalized: list[dict[str, Any]] = []
    primary = 0
    for item in raw:
        if not isinstance(item, dict):
            raise SystemExit("style_anchors 只能包含对象")
        role = str(item.get("role") or "")
        if role not in {"primary", "supporting"}:
            raise SystemExit("style_anchor.role 只允许 primary|supporting")
        primary += role == "primary"
        path = Path(str(item.get("path") or "")).expanduser().resolve()
        if not path.is_file() or pc.file_sha256(path) != item.get("sha256"):
            raise SystemExit(f"style_anchor 不存在或 SHA 已变化：{path}")
        normalized.append({
            "path": str(path),
            "role": "primary_style_anchor" if role == "primary" else "supporting_style_anchor",
            "reference_intent": {
                "borrow": ["色彩与明暗、字体气质、材质、图像工艺和完成度"],
                "do_not_copy": ["具体内容、物体、原文和单页构图"],
            },
        })
    if primary != 1:
        raise SystemExit("style_anchors 必须且只能有一张 primary")
    return normalized


def normalize_global_chrome_from_assets(
    *,
    assets_raw: dict[str, Any],
    content_pages: dict[str, dict[str, Any]],
    page_order: list[str],
    source_packet: Path,
    output_path: Path,
) -> Path | None:
    """Compile the title director's one raw decision without inferring authorization."""

    authorized = assets_raw.get("global_chrome_authorized")
    raw = assets_raw.get("global_chrome_contract_raw")
    if not isinstance(authorized, bool):
        raise SystemExit("chrome_assets_bundle.raw.json 缺少 global_chrome_authorized=true|false")
    if not authorized:
        if raw is not None:
            raise SystemExit("global_chrome_authorized=false 时 global_chrome_contract_raw 必须为 null")
        if output_path.exists():
            raise SystemExit("未授权 global chrome，但规范化合同已存在")
        return None
    if not isinstance(raw, dict):
        raise SystemExit("global_chrome_authorized=true 时必须提供 global_chrome_contract_raw")
    raw_deck = raw.get("deck_title_system") or {}
    raw_scope = raw_deck.get("scope") if isinstance(raw_deck, dict) else None
    raw_includes = (
        raw_scope.get("include_page_ids")
        if isinstance(raw_scope, dict)
        else None
    ) or page_order
    if not isinstance(raw_includes, list) or not raw_includes:
        raise SystemExit("global chrome include_page_ids 必须是非空数组")
    included: list[str] = []
    for value in raw_includes:
        matches = [page for page in page_order if pc.page_ids_match(page, value)]
        if len(matches) != 1 or matches[0] in included:
            raise SystemExit(f"global chrome include_page_ids 越界或重复：{value}")
        included.append(matches[0])
    title_map: dict[str, str] = {}
    packet = pc.read_json(source_packet)
    packet_pages = exact_page_map(packet.get("pages"), page_order, "source packet pages")
    deck_shared = packet.get("deck_shared_sources") or []
    if not isinstance(deck_shared, list):
        raise SystemExit("source packet deck_shared_sources 必须是数组")
    for page_id in included:
        title = str(content_pages[page_id].get("title") or "").strip()
        if not title:
            raise SystemExit(f"global chrome 页 {page_id} 的事实内容合同缺少逐字 title")
        title_map[page_id] = title
        page_sources = packet_pages[page_id].get("supporting_sources") or []
        if not isinstance(page_sources, list):
            raise SystemExit(f"source packet 页 {page_id} supporting_sources 必须是数组")
        exact_title_corpus = "\n".join(
            [str(packet_pages[page_id].get("exact_text") or "")]
            + [str(item.get("exact_text") or "") for item in page_sources if isinstance(item, dict)]
            + [str(item.get("exact_text") or "") for item in deck_shared if isinstance(item, dict)]
        )
        if title_map[page_id] not in exact_title_corpus:
            raise SystemExit(
                f"global chrome 页 {page_id} 标题必须逐字出现于冻结 packet 文本；"
                "不得改写标点或措辞"
            )
    normalized = normalize_chrome.normalize_contract(
        raw,
        page_id=included[0],
        canonical_title=title_map[included[0]],
        source_packet=source_packet,
        page_title_map=title_map,
    )
    normalize_chrome.validated_atomic_write(output_path, normalized)
    return output_path


def compile_selected_render_prompt(
    *,
    page: dict[str, Any],
    layout: dict[str, Any],
    tone: str,
    language: Any,
    reference_images: list[dict[str, Any]],
    required_assets: list[dict[str, Any]],
    required_page_assets: list[dict[str, Any]],
    chrome_projection: dict[str, Any] | None,
    disclosure: dict[str, Any],
) -> tuple[str, list[str]]:
    prompt_job: dict[str, Any] = {
        "run_mode": pc.SELECTED_STYLE_EXPANSION_MODE,
        "tone": tone,
        "language": language,
        "anchor_page": page,
        "layout_direction": layout,
        "reference_images": reference_images,
        "required_assets": [*required_assets, *required_page_assets],
    }
    if chrome_projection is not None:
        prompt_job["global_chrome"] = chrome_projection
    referenced = pc.extract_input_paths(
        reference_images + required_assets + required_page_assets
    )
    prompt = pc.compile_minimal_prompt_v4(prompt_job)
    render_assets = [*required_assets, *required_page_assets]
    if render_assets:
        path_to_index = {path: index + 1 for index, path in enumerate(referenced)}
        role_lines = []
        for item in render_assets:
            if pc.normalized_asset_role_key(item.get("role")) in pc.EVIDENCE_ASSET_ROLES:
                continue
            index = path_to_index.get(str(Path(item["path"]).resolve()))
            if index is not None:
                role_lines.append(f"- 附件 {index}：{item['role']}；用途：{item['use']}")
        if role_lines:
            prompt += "\n\n真实渲染资产（只按声明的正向用途呈现）：\n" + "\n".join(role_lines)
    if disclosure.get("mode") == "visible":
        prompt += (
            "\n\n本页采用正向声明的情境重建表达；页面必须清楚可见呈现："
            f"{disclosure['visible_text']}"
        )
    return pc.finalize_imagegen_prompt(prompt), referenced


def compile_selected_bundle(
    *,
    state: dict[str, Any],
    project_dir: Path,
    page: dict[str, Any],
    plan: dict[str, Any],
    style_contract: dict[str, Any],
    page_assets: list[dict[str, Any]],
    page_planning_evidence: list[dict[str, Any]],
    chrome_contract_path: Path | None,
) -> dict[str, Any]:
    if page.get("content_contract_version") != 2 or page.get("prompt_contract_version") != 4:
        raise SystemExit("新扩页必须使用 content v2 / prompt v4")
    anchor_mode = plan.get("anchor_input_mode")
    if anchor_mode not in {"raster", "text_family"}:
        raise SystemExit(f"页 {page.get('page_id')} anchor_input_mode 无效")
    if not (state.get("style_anchors") or []):
        anchor_mode = "text_family"
    style = pc.normalize_style(state.get("selected_style"))
    tone = str(style_contract.get("tone") or "")
    if tone not in pc.TONE_PROMPT_LABELS:
        raise SystemExit("selected style family contract 缺少 dark|light tone")

    shared_assets = normalize_asset_items(style_contract.get("required_assets") or [], "required_assets")
    shared_planning = normalize_asset_items(
        style_contract.get("planning_evidence") or [], "planning_evidence"
    )
    page_assets = normalize_asset_items(page_assets, "required_page_assets")
    page_planning_evidence = normalize_asset_items(
        page_planning_evidence, "page_planning_evidence"
    )
    chrome_projection = None
    if chrome_contract_path is not None:
        chrome_path, chrome, chrome_sha = pc.read_global_chrome_contract(
            str(chrome_contract_path), verify_authorization_source=False
        )
        chrome_projection = pc.global_chrome_projection(
            chrome,
            contract_path=chrome_path,
            contract_sha256=chrome_sha,
            page_id=page["page_id"],
            style=style,
            tone=tone,
            language=page.get("language"),
        )
        pc.validate_page_global_chrome_compatibility(
            page, chrome_projection, f"selected-style/{page['page_id']}"
        )
        if isinstance(chrome_projection.get("logo_asset"), dict):
            logo_asset = {
                **chrome_projection["logo_asset"],
                "asset_usage": "render_asset",
                "role": "authorized_global_chrome_logo",
                "use": "按已授权的全稿标题外壳呈现官方 Logo",
            }
            shared_assets = pc.merge_attachment_items(
                shared_assets, normalize_asset_items([logo_asset], "global chrome logo")
            )

    required_assets = pc.merge_attachment_items(shared_assets)
    required_page_assets = pc.merge_attachment_items(page_assets)
    required_paths = set(pc.extract_input_paths(required_assets))
    required_page_assets = [
        item for item in required_page_assets
        if str(Path(item["path"]).expanduser().resolve()) not in required_paths
    ]
    required_count = len(required_assets) + len(required_page_assets)
    if anchor_mode == "raster" and required_count + 1 > pc.IMAGEGEN_MAX_REFERENCED_PATHS:
        anchor_mode = "text_family"
    anchors = style_anchor_items(state) if anchor_mode == "raster" else []
    if anchors and required_count + len(anchors) > pc.IMAGEGEN_MAX_REFERENCED_PATHS:
        anchors = anchors[:1]
    reference_images = anchors

    layout = {
        "layout_contract_version": pc.SELECTED_STYLE_LAYOUT_VERSION,
        "art_direction_contract_version": pc.ART_DIRECTION_CONTRACT_VERSION,
        "style_family_thesis": style_contract["style_family_thesis"],
        "craft_axis": plan["craft_axis"],
        "visual_activity_mode": plan["visual_activity_mode"],
        "attention_strategy": plan["attention_strategy"],
        "relationship_representation_family": plan.get("relationship_representation_family") or "content-led adaptation",
        "spatial_topology": {
            "spatial_topology_intent": plan["spatial_topology_intent"]
        },
        "adaptation_principle": plan["page_adaptation_brief"],
        "continuity_invariants": style_contract["continuity_invariants"],
        "representation_disclosure": plan["representation_disclosure"],
    }
    disclosure = plan["representation_disclosure"]
    prompt, referenced = compile_selected_render_prompt(
        page=page,
        layout=layout,
        tone=tone,
        language=page.get("language"),
        reference_images=reference_images,
        required_assets=required_assets,
        required_page_assets=required_page_assets,
        chrome_projection=chrome_projection,
        disclosure=disclosure,
    )
    projection = pc.build_creative_brief_projection(page, layout)
    projection.update({
        "page_adaptation_brief": plan["page_adaptation_brief"],
        "anchor_input_mode": anchor_mode,
        "anchor_approval_scope": state.get("anchor_approval_scope"),
        "representation_disclosure": disclosure,
    })
    normalized_paths, manifest = pc.build_input_manifest(referenced)
    if len(normalized_paths) > pc.IMAGEGEN_MAX_REFERENCED_PATHS:
        raise SystemExit(f"页 {page['page_id']} 附件超过共享上限 5")
    fingerprint = hashlib.sha256(json.dumps(
        {"prompt": prompt, "inputs": manifest}, ensure_ascii=False, sort_keys=True
    ).encode("utf-8")).hexdigest()
    return {
        "imagegen_prompt_contract_version": 4,
        "anchor_input_mode": anchor_mode,
        "layout_direction": layout,
        "reference_images": reference_images,
        "required_assets": required_assets,
        "required_page_assets": required_page_assets,
        "planning_evidence": pc.merge_attachment_items(shared_planning, page_planning_evidence),
        **({"global_chrome": chrome_projection} if chrome_projection is not None else {}),
        "imagegen_prompt": prompt,
        "imagegen_prompt_fingerprint": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "creative_brief_projection": projection,
        "imagegen_referenced_paths": normalized_paths,
        "imagegen_input_manifest": manifest,
        "imagegen_input_fingerprint": fingerprint,
    }


def frozen_file_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"冻结文件不存在：{path}")
    return {"path": str(path), "sha256": pc.file_sha256(path), "size_bytes": path.stat().st_size}


def validate_prepare_identity(identity: Any) -> None:
    if not isinstance(identity, dict) or identity.get("selected_style_prepare_identity_version") != 1:
        raise SystemExit("selected_style_prepare_identity 格式无效")
    records = identity.get("frozen_files")
    if not isinstance(records, list) or not records:
        raise SystemExit("selected_style_prepare_identity 缺少 frozen_files")
    for record in records:
        if not isinstance(record, dict):
            raise SystemExit("selected_style_prepare_identity 文件记录无效")
        path = Path(str(record.get("path") or "")).expanduser().resolve()
        if not path.is_file() or pc.file_sha256(path) != record.get("sha256"):
            raise SystemExit(f"已准备运行的冻结文件已变化：{path}")


def prepare_directors(state_path: Path) -> dict[str, Any]:
    state, project_dir = require_run(state_path)
    paths = canonical_paths(project_dir)
    prepare_identity = state.get("selected_style_prepare_identity")
    if prepare_identity is not None:
        validate_prepare_identity(prepare_identity)
        return {
            "status": "already_prepared",
            "state": str(state_path),
            "state_status": state.get("status"),
            "page_jobs": len(state.get("page_order") or []),
        }
    if state.get("status") == "completed":
        return {"status": "already_completed", "state": str(state_path)}
    for key in ("source_packet", "content_raw", "assets_raw", "visual_raw"):
        if not paths[key].is_file():
            raise SystemExit(f"扩页三导演输入缺失：{paths[key]}")
    content_raw = pc.read_json(paths["content_raw"])
    assets_raw = pc.read_json(paths["assets_raw"])
    visual_raw = pc.read_json(paths["visual_raw"])
    source_packet = pc.read_json(paths["source_packet"])
    if source_packet.get("selected_style_expansion_packet_contract_version") != 2:
        raise SystemExit("新扩页 prepare-directors 只接受 target-page-only packet v2；旧运行原样恢复")
    page_order = [str(item) for item in state["page_order"]]
    if content_raw.get("selected_style_content_bundle_version") != CONTENT_BUNDLE_VERSION:
        raise SystemExit("content_bundle.raw.json 版本必须为 1")
    if assets_raw.get("selected_style_assets_bundle_version") != ASSETS_BUNDLE_VERSION:
        raise SystemExit("chrome_assets_bundle.raw.json 版本必须为 1")
    if visual_raw.get("selected_style_visual_plan_version") != VISUAL_PLAN_VERSION:
        raise SystemExit("visual_family_plan.raw.json 版本必须为 1")
    content_pages = exact_page_map(content_raw.get("pages"), page_order, "content pages")
    pc.validate_language_presentation_bundle(
        content_pages, "selected-style content pages"
    )
    chrome_contract_path = normalize_global_chrome_from_assets(
        assets_raw=assets_raw,
        content_pages=content_pages,
        page_order=page_order,
        source_packet=paths["source_packet"],
        output_path=paths["chrome"],
    )
    asset_pages = exact_page_map(assets_raw.get("pages") or {page: {} for page in page_order}, page_order, "asset pages")
    visual_pages = exact_page_map(visual_raw.get("pages"), page_order, "visual pages")
    family = visual_raw.get("style_family")
    if not isinstance(family, dict):
        raise SystemExit("visual_family_plan.raw.json 缺少 style_family")
    required_family = (
        "style_family_thesis", "tone", "palette_and_light", "typography_character",
        "material_character", "image_craft", "finish_quality", "continuity_invariants",
    )
    if any(not family.get(key) for key in required_family):
        raise SystemExit("selected style family contract 字段不完整")
    if not isinstance(family.get("continuity_invariants"), list) or len(family["continuity_invariants"]) < 2:
        raise SystemExit("style family 至少需要两条 continuity_invariants")
    shared_assets_all = normalize_asset_items(
        assets_raw.get("shared_required_assets") or [], "shared_required_assets"
    )
    shared_render_assets, shared_planning_evidence = split_asset_items(shared_assets_all)
    style_contract = {
        "style_contract_version": STYLE_CONTRACT_VERSION,
        "run_id": state["run_id"],
        "selected_style": f"style_{pc.normalize_style(state['selected_style'])}",
        "visual_family_source": state.get("visual_family_source") or (
            "raster_anchor" if state.get("style_anchors") else "director_defined_text_family"
        ),
        "language": content_raw.get("language") or "source",
        "anchor_approval_scope": state.get("anchor_approval_scope"),
        "anchors": state.get("style_anchors"),
        "anchor_policy": {
            "default_primary_count": 1 if state.get("style_anchors") else 0,
            "supporting_optional": True,
            "style_only_unless_final_page_and_anchor": True,
            "no_cumulative_learning": True,
            "anchorless_forces_text_family": not bool(state.get("style_anchors")),
        },
        **{key: family[key] for key in required_family},
        "required_assets": shared_render_assets,
        "planning_evidence": shared_planning_evidence,
        "global_chrome_contract_path": str(chrome_contract_path) if chrome_contract_path else None,
        "open_dimensions": ["信息密度", "内容区拓扑", "图文比例", "视觉媒介", "抽象程度"],
    }
    pc.write_idempotent(paths["style_contract"], style_contract)

    contract_paths: list[Path] = []
    job_paths: list[Path] = []
    snapshot_assets: list[dict[str, Any]] = []
    planning_source_paths: list[Path] = []
    for anchor in state.get("style_anchors") or []:
        snapshot_assets.append({
            "path": anchor["path"], "asset_type": "style_family_source", "role": "style_anchor",
            "styles": [pc.normalize_style(state["selected_style"])],
        })
    for page_id in page_order:
        page = dict(content_pages[page_id])
        plan = visual_pages[page_id]
        for key in (
            "relationship_thesis", "visual_quality_intent", "craft_axis",
            "visual_activity_mode", "attention_strategy", "spatial_topology_intent",
            "page_adaptation_brief", "anchor_input_mode",
        ):
            if not plan.get(key):
                raise SystemExit(f"页 {page_id} 视觉计划缺少 {key}")
        if plan["visual_activity_mode"] not in pc.VISUAL_ACTIVITY_MODES:
            raise SystemExit(f"页 {page_id} visual_activity_mode 无效")
        disclosure = normalize_representation_disclosure(plan, page_id)
        plan["representation_disclosure"] = disclosure
        page.update({
            "content_contract_version": 2,
            "prompt_contract_version": 4,
            "page_id": page_id,
            "relationship_thesis": plan["relationship_thesis"],
            "visual_quality_intent": plan["visual_quality_intent"],
            "visual_support_goal": plan.get("visual_support_goal") or "帮助观众理解本页主关系",
            "craft_ambition": plan.get("craft_ambition") or "与选定视觉家族相当的成品完成度",
            "spatial_standard_version": 1,
            "spatial_generation_brief": pc.UNIFIED_SPATIAL_PROMPT_CUES[
                pc.content_contract_prompt_locale(page)
            ],
            "spatial_qa_contract": "按统一空间标准检查对齐、聚拢、层级、阅读路径、有效负空间与边缘安全",
            "spatial_feasibility": "pass",
            "content_load_review": page.get("content_load_review") or {
                "must_render_groups": [], "dense_relationships": [], "visual_channels": [],
                "semantic_structure": "content-directed", "focus_relationship": plan["relationship_thesis"],
                "attention_risks": [], "edge_and_takeaway_risks": [], "duplication_risks": [],
                "reason": "fact director confirmed page feasibility",
            },
            "creative_freedom": "在事实与视觉家族不变的前提下按本页内容自由适配",
        })
        page.setdefault("language", "source")
        page.setdefault("source_facts", [])
        page.setdefault("display_required", [])
        if disclosure.get("mode") == "visible" and disclosure["visible_text"] not in page["display_required"]:
            page["display_required"].append(disclosure["visible_text"])
        page.setdefault("display_flexible", [])
        page.setdefault("display_supporting", [])
        if not str(page.get("flexible_story") or "").strip():
            page.pop("flexible_story", None)
        page.setdefault("information_density_target", "medium")
        page.setdefault("semantic_invariants", [])
        page.setdefault("forbidden_interpretations", [])
        page.setdefault("prompt_semantic_guardrails", [])
        page.setdefault("prompt_user_constraints", [])
        page.setdefault("content_resolution", {"status": "not_needed", "reason": "source is sufficient"})
        pc.validate_dispatchable_content_contract(page, f"selected-style page {page_id}")
        contract_path = paths["content_dir"] / f"page_{page_id}.json"
        pc.write_idempotent(contract_path, page)
        contract_paths.append(contract_path.resolve())
        per_page_assets_all = normalize_asset_items(
            asset_pages[page_id].get("required_page_assets") or [], f"page {page_id} assets"
        )
        per_page_assets, per_page_planning_evidence = split_asset_items(per_page_assets_all)
        bundle = compile_selected_bundle(
            state=state, project_dir=project_dir, page=page, plan=plan,
            style_contract=style_contract, page_assets=per_page_assets,
            page_planning_evidence=per_page_planning_evidence,
            chrome_contract_path=chrome_contract_path,
        )
        job = {
            "selected_style_job_version": 1,
            "style_slot": pc.normalize_style(state["selected_style"]),
            "action": "generate_page",
            "attempt": 1,
            "run_mode": pc.SELECTED_STYLE_EXPANSION_MODE,
            "page_id": page_id,
            "language": page["language"],
            "content_contract_version": 2,
            "prompt_contract_version": 4,
            "source_content_contract_path": str(contract_path.resolve()),
            "source_content_contract_sha256": pc.file_sha256(contract_path),
            "anchor_approval_scope": state.get("anchor_approval_scope"),
            "anchor_input_mode": plan["anchor_input_mode"],
            "style_family_contract_path": str(paths["style_contract"].resolve()),
            "style_family_contract_sha256": pc.file_sha256(paths["style_contract"]),
            "page_adaptation_brief": plan["page_adaptation_brief"],
            "representation_disclosure": disclosure,
            "output_target": str(pc.origin_image_target(project_dir, state["selected_style"], page_id).resolve()),
            **bundle,
        }
        job_path = paths["jobs_dir"] / f"page_{page_id}.json"
        pc.write_idempotent(job_path, job)
        pc.validate_generation_job_inputs(
            job_path, internal_sources=set(), expected_task={
                "style": state["selected_style"], "page_id": page_id,
                "action": "generate_page", "attempt": 1,
            }, state=state, project_dir=project_dir,
        )
        job_paths.append(job_path.resolve())
        for item in bundle["imagegen_input_manifest"]:
            snapshot_assets.append({
                "path": item["path"], "asset_type": "generation_asset",
                "role": next((x.get("role") for x in bundle["reference_images"] + bundle["required_assets"] + bundle["required_page_assets"] if x.get("path") == item["path"]), "generation_asset"),
                "styles": [pc.normalize_style(state["selected_style"])],
            })
        for item in bundle["planning_evidence"]:
            planning_source_paths.append(Path(item["path"]).resolve())

    snapshot_assets_by_path: dict[str, dict[str, Any]] = {}
    for item in snapshot_assets:
        snapshot_assets_by_path.setdefault(str(Path(item["path"]).resolve()), item)
    snapshot = pc.create_source_snapshot(
        project_dir=project_dir,
        state_path=state_path,
        source_path=paths["source_packet"],
        page_ids=page_order,
        content_contract_paths=contract_paths,
        asset_items=list(snapshot_assets_by_path.values()),
        supporting_source_paths=planning_source_paths,
        fragment_path=paths["source_packet"],
        fragment_authority="authoritative_page_fragment",
    )
    state = pc.read_json(state_path)
    scheduler = state.setdefault("scheduler", {})
    scheduler["dispatch_policy"] = "single_mechanical_executor_rolling_cap5"
    scheduler["active_child_limit"] = 8
    scheduler["ready_queue"] = [{
        "style": pc.normalize_style(state["selected_style"]),
        "page_id": page_id, "action": "generate_page", "attempt": 1,
        "generation_job_path": str(paths["jobs_dir"] / f"page_{page_id}.json"),
        "generation_job_sha256": pc.file_sha256(paths["jobs_dir"] / f"page_{page_id}.json"),
    } for page_id in page_order]
    scheduler.setdefault("active_actions", [])
    scheduler.setdefault("recovery_queue", [])
    now = pc.now_iso()
    state["selected_style_method"] = {
        "version": 1, "three_director_method": True,
        "content_contract_version": 2, "prompt_contract_version": 4,
        "executor_agents": 1, "imagegen_capacity": GLOBAL_IMAGEGEN_CAPACITY,
        "judge_agents": 1, "no_cumulative_learning": True,
    }
    state["selected_style_contract_path"] = str(paths["style_contract"].resolve())
    state["selected_style_contract_sha256"] = pc.file_sha256(paths["style_contract"])
    frozen_files = [
        frozen_file_record(paths[key])
        for key in ("source_packet", "content_raw", "assets_raw", "visual_raw", "style_contract")
    ]
    frozen_files.extend(frozen_file_record(path) for path in contract_paths)
    frozen_files.extend(frozen_file_record(path) for path in job_paths)
    frozen_files.append(frozen_file_record(project_dir / "state" / "source_snapshot.json"))
    state["selected_style_prepare_identity"] = {
        "selected_style_prepare_identity_version": 1,
        "created_at": now,
        "frozen_files": frozen_files,
    }
    state.setdefault("timing", {})["style_jobs_created_at"] = now
    state["timing"]["task_package_completed_at"] = now
    pc.append_event(state, "style_jobs_created", now, details={"page_job_count": len(job_paths), "source": "selected_style_control_plane_v1"})
    pc.append_event(state, "task_package_completed", now, details={"ready_queue_count": len(page_order)})
    for page_id in page_order:
        pc.append_event(state, "queued", now, style=state["selected_style"], page_id=page_id, action="generate_page", details={"source": "prepare-directors"})
    pc.atomic_write_json(state_path, state)
    return {
        "status": "prepared", "state": str(state_path),
        "style_contract": str(paths["style_contract"]),
        "content_contracts": len(contract_paths), "page_jobs": len(job_paths),
        "source_snapshot": str((project_dir / "state" / "source_snapshot.json").resolve()),
        "executor_agents": 1, "imagegen_capacity": GLOBAL_IMAGEGEN_CAPACITY,
    }


def task_key(task: dict[str, Any]) -> str:
    return f"{task['style']}/{task['page_id']}/{task['action']}/{int(task.get('attempt') or 1)}"


def safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def control_paths(project_dir: Path, key: str) -> tuple[Path, Path]:
    paths = canonical_paths(project_dir)
    stem = safe_key(key)
    return paths["claims"] / f"claim_{stem}.json", paths["receipts"] / f"selected_receipt_{stem}.json"


def validate_manifest_item(state_path: Path, manifest_path: Path, key: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    state, project_dir = require_run(state_path)
    paths = canonical_paths(project_dir)
    manifest_path = manifest_path.expanduser().resolve()
    pc.require_path_within(manifest_path, paths["manifests"], "selected-style manifest")
    manifest, manifest_sha = pc.read_json_with_sha256(manifest_path)
    if manifest.get("selected_style_control_plane_version") != CONTROL_VERSION or manifest.get("run_id") != state.get("run_id"):
        raise SystemExit("selected-style manifest 版本或 run_id 错绑")
    matches = [item for item in manifest.get("tasks") or [] if isinstance(item, dict) and item.get("task_key") == key]
    if len(matches) != 1:
        raise SystemExit("selected-style manifest task_key 不唯一")
    item = dict(matches[0])
    active = [x for x in (state.get("scheduler") or {}).get("active_actions") or [] if isinstance(x, dict) and task_key(x) == key]
    if len(active) != 1:
        raise SystemExit("selected-style task 没有唯一 active_action")
    job_path = Path(item["generation_job_path"]).resolve()
    if not job_path.is_file() or pc.file_sha256(job_path) != item.get("generation_job_sha256"):
        raise SystemExit("selected-style generation job 已变化")
    pc.validate_generation_job_inputs(
        job_path, internal_sources=pc.allowed_internal_sources_for_task(state, item),
        expected_task=item, state=state, project_dir=project_dir,
    )
    item["manifest_sha256"] = manifest_sha
    return state, active[0], item, project_dir


def claim(state_path: Path, manifest_path: Path, key: str, wait_seconds: float) -> dict[str, Any]:
    state, active, item, project_dir = validate_manifest_item(state_path, manifest_path, key)
    claim_path, receipt_path = control_paths(project_dir, key)
    if receipt_path.is_file():
        return {"status": "receipt_exists", "receipt_path": str(receipt_path)}
    if claim_path.is_file():
        raise SystemExit("selected-style duplicate claim 被拒绝")
    deadline = time.monotonic() + max(0.0, wait_seconds)
    lease_task = {
        "style": item["style"], "page_id": item["page_id"], "action": item["action"],
        "attempt": item["attempt"], "lease_kind": "selected_style_direct_v1",
        "worker_session_id": active.get("worker_agent_id"),
        "worker_ticket_sha256": item["manifest_sha256"],
    }
    while True:
        acquired, _deferred, lease_ids, _remaining = pc.acquire_shared_imagegen_slots(
            state_path, state, [lease_task], timestamp=pc.now_iso(), capacity_limit=GLOBAL_IMAGEGEN_CAPACITY
        )
        if acquired:
            break
        if time.monotonic() >= deadline:
            return {"status": "slot_wait_timeout", "task_key": key}
        time.sleep(0.5)
        state = pc.read_json(state_path)
    lease_id = lease_ids[task_key(lease_task)]
    value = {
        "selected_style_claim_version": CONTROL_VERSION, "task_key": key,
        "manifest_sha256": item["manifest_sha256"], "generation_job_sha256": item["generation_job_sha256"],
        "imagegen_input_fingerprint": item["imagegen_input_fingerprint"], "lease_id": lease_id,
        "claimed_at": pc.now_iso(), "contains_image_payload": False,
    }
    try:
        pc.write_idempotent(claim_path, value)
    except BaseException:
        pc.release_shared_imagegen_slots(state_path, state, [lease_id])
        raise
    return {"status": "claimed", "claim_path": str(claim_path), "receipt_path": str(receipt_path), "lease_id": lease_id}


def release(state_path: Path, manifest_path: Path, key: str) -> dict[str, Any]:
    state, _active, _item, project_dir = validate_manifest_item(state_path, manifest_path, key)
    claim_path, _receipt_path = control_paths(project_dir, key)
    if not claim_path.is_file():
        return {"status": "already_released", "released": 0}
    claim_value = pc.read_json(claim_path)
    released = pc.release_shared_imagegen_slots(state_path, state, [str(claim_value.get("lease_id") or "")])
    return {"status": "released" if released else "already_released", "released": released}


def write_receipt(state_path: Path, manifest_path: Path, key: str, result: dict[str, Any]) -> dict[str, Any]:
    state, active, item, project_dir = validate_manifest_item(state_path, manifest_path, key)
    claim_path, receipt_path = control_paths(project_dir, key)
    if not claim_path.is_file():
        raise SystemExit("selected-style receipt 缺少 claim")
    claim_value = pc.read_json(claim_path)
    result = pc.normalize_fast8_artifact_fields(result)
    started = str(result.get("tool_started_at") or pc.now_iso())
    finished = str(result.get("tool_finished_at") or pc.now_iso())
    saved = result.get("savedPath")
    error = result.get("error")
    if error in {None, ""}:
        path = Path(str(saved or "")).expanduser().resolve()
        try:
            pc.require_path_within(path, pc.GENERATED_IMAGES_ROOT, "selected-style ImageGen 输出")
            pc.png_metadata(path)
            saved = str(path)
        except (SystemExit, OSError):
            saved = None
            error = "artifact_handoff_unresolved"
    receipt = {
        "selected_style_direct_receipt_version": CONTROL_VERSION,
        "style": item["style"], "page_id": item["page_id"], "action": item["action"], "attempt": item["attempt"],
        "worker_agent_id": active.get("worker_agent_id") or EXECUTOR_AGENT_ID,
        "agent_action_started_at": started, "agent_action_finished_at": finished,
        "tool_call_id": str(result.get("tool_call_id") or f"selected_{safe_key(key)}"),
        "savedPath": saved if error in {None, ""} else None,
        "tool_started_at": started, "tool_finished_at": finished,
        "tool_status": result.get("tool_status") or ("failed" if error else "completed"),
        "failure_class": result.get("failure_class") if error else None,
        "tool_error_code": result.get("tool_error_code") if error else None,
        "error": error, "manifest_sha256": item["manifest_sha256"],
        "generation_job_sha256": item["generation_job_sha256"], "contains_image_payload": False,
    }
    pc.write_idempotent(receipt_path, receipt)
    pc.release_shared_imagegen_slots(state_path, state, [str(claim_value.get("lease_id") or "")])
    return {"status": "receipt_written", "receipt_path": str(receipt_path), "error": error}


def settle_receipt(state_path: Path, receipt_path: Path) -> dict[str, Any]:
    state, project_dir = require_run(state_path)
    receipt_path = receipt_path.expanduser().resolve()
    pc.require_path_within(receipt_path, canonical_paths(project_dir)["receipts"], "selected-style receipt")
    receipt = pc.read_json(receipt_path)
    result = {key: receipt.get(key) for key in (
        "style", "page_id", "action", "attempt", "worker_agent_id", "agent_action_started_at",
        "agent_action_finished_at", "tool_call_id", "savedPath", "tool_started_at", "tool_finished_at",
        "error", "tool_status", "failure_class", "tool_error_code",
    )}
    results_path = receipt_path.with_name(receipt_path.stem + ".settle.json")
    pc.write_idempotent(results_path, {"results": [result]})
    settled = capture(pc.command_settle_wave, state=str(state_path), results_file=str(results_path), expected_styles=str(receipt["style"]), timestamp=None)
    return {"status": "settled", "task_key": task_key(receipt), "settle": settled, "contains_image_payload": False}


def prepare_next(state_path: Path, *, recover_orphans: bool = False) -> dict[str, Any]:
    state, project_dir = require_run(state_path)
    paths = canonical_paths(project_dir)
    if state.get("status") == "blocked":
        return {
            "status": "blocked",
            "reason": state.get("terminal_reason") or state.get("failure_reason"),
            "contains_image_payload": False,
        }
    scheduler = state.get("scheduler") or {}
    recovery = [item for item in scheduler.get("recovery_queue") or [] if isinstance(item, dict)]
    active = [item for item in scheduler.get("active_actions") or [] if isinstance(item, dict)]
    ready = [item for item in scheduler.get("ready_queue") or [] if isinstance(item, dict)]
    restored_retries: list[dict[str, Any]] = []
    remaining_recovery: list[dict[str, Any]] = []
    for item in recovery:
        can_restore = (
            item.get("status") == "page_input_mismatch"
            and item.get("technical_retry") is True
            and item.get("action") == "generate_page"
            and int(item.get("attempt") or 1) > 1
            and item.get("error") == "正式 generation job SHA 已变化"
        )
        if not can_restore:
            remaining_recovery.append(item)
            continue
        candidate = {
            key: value
            for key, value in item.items()
            if key not in {"status", "error", "regenerate_allowed"}
        }
        job_path = pc.generation_job_path_for_task(
            project_dir, candidate, pc.SELECTED_STYLE_EXPANSION_MODE
        )
        if job_path is None or not job_path.is_file():
            remaining_recovery.append(item)
            continue
        candidate["generation_job_path"] = str(job_path.resolve())
        candidate["generation_job_sha256"] = pc.file_sha256(job_path)
        try:
            pc.validate_generation_job_inputs(
                job_path,
                internal_sources=pc.allowed_internal_sources_for_task(state, candidate),
                expected_task=candidate,
                state=state,
                project_dir=project_dir,
            )
        except (SystemExit, OSError):
            remaining_recovery.append(item)
            continue
        restored_retries.append(candidate)
    if restored_retries:
        existing_keys = {task_key(item) for item in ready}
        for item in restored_retries:
            if task_key(item) not in existing_keys:
                ready.append(item)
                existing_keys.add(task_key(item))
            state["pages"][str(item["page_id"])]["status"] = "retry_pending"
        state["scheduler"]["ready_queue"] = ready
        state["scheduler"]["recovery_queue"] = remaining_recovery
        pc.append_event(
            state,
            "selected_style_retry_binding_restored",
            pc.now_iso(),
            details={
                "pages": [str(item["page_id"]) for item in restored_retries],
                "policy": "immutable_initial_generate_page_job",
            },
        )
        pc.atomic_write_json(state_path, state)
        state = pc.read_json(state_path)
        scheduler = state.get("scheduler") or {}
        recovery = [
            item
            for item in scheduler.get("recovery_queue") or []
            if isinstance(item, dict)
        ]
        active = [
            item
            for item in scheduler.get("active_actions") or []
            if isinstance(item, dict)
        ]
    if recover_orphans and active:
        pending = []
        unclaimed: list[dict[str, Any]] = []
        for item in active:
            claim_path, receipt_path = control_paths(project_dir, task_key(item))
            if not claim_path.exists() and not receipt_path.exists():
                unclaimed.append(item)
                continue
            pending.append({
                "task_key": task_key(item),
                "claim_path": str(claim_path) if claim_path.exists() else None,
                "receipt_path": str(receipt_path) if receipt_path.exists() else None,
            })
        if unclaimed:
            unclaimed_keys = {task_key(item) for item in unclaimed}
            state["scheduler"]["active_actions"] = [
                item
                for item in active
                if task_key(item) not in unclaimed_keys
            ]
            restored_ready = state["scheduler"].setdefault("ready_queue", [])
            ready_keys = {
                task_key(item)
                for item in restored_ready
                if isinstance(item, dict)
            }
            for item in unclaimed:
                restored = {
                    key: value
                    for key, value in item.items()
                    if key not in {
                        "dispatch_requested_at",
                        "dispatch_authorized_at",
                        "worker_start_status",
                        "worker_agent_id",
                    }
                }
                if task_key(restored) not in ready_keys:
                    restored_ready.append(restored)
                    ready_keys.add(task_key(restored))
            pc.append_event(
                state,
                "selected_style_unclaimed_dispatch_requeued",
                pc.now_iso(),
                details={
                    "tasks": [task_key(item) for item in unclaimed],
                    "policy": "no_claim_no_receipt",
                },
            )
            pc.atomic_write_json(state_path, state)
            state = pc.read_json(state_path)
            scheduler = state.get("scheduler") or {}
            active = [
                item
                for item in scheduler.get("active_actions") or []
                if isinstance(item, dict)
            ]
        return {
            "status": "recovery_required",
            "reason": "existing_claim_or_receipt_must_close_before_dispatch",
            "recovery_tasks": pending,
            "contains_image_payload": False,
        } if pending else prepare_next(state_path, recover_orphans=False)
    if len(active) > GLOBAL_IMAGEGEN_CAPACITY:
        raise SystemExit("已有 selected-style active_actions 超过共享 ImageGen 上限")
    available = max(0, GLOBAL_IMAGEGEN_CAPACITY - len(active))
    ready = [item for item in scheduler.get("ready_queue") or [] if isinstance(item, dict)]
    valid_ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in ready:
        try:
            job_path = pc.generation_job_path_for_task(
                project_dir, item, pc.SELECTED_STYLE_EXPANSION_MODE
            )
            if job_path is None or not job_path.is_file():
                raise SystemExit("正式 generation job 不存在")
            expected_sha = item.get("generation_job_sha256")
            if not isinstance(expected_sha, str) or pc.file_sha256(job_path) != expected_sha:
                raise SystemExit("正式 generation job SHA 已变化")
            pc.validate_generation_job_inputs(
                job_path,
                internal_sources=pc.allowed_internal_sources_for_task(state, item),
                expected_task=item,
                state=state,
                project_dir=project_dir,
            )
        except (SystemExit, OSError) as exc:
            failure = {
                **item, "status": "page_input_mismatch",
                "error": str(exc), "regenerate_allowed": False,
            }
            blocked.append(failure)
            state["pages"][str(item["page_id"])]["status"] = "attention_required"
        else:
            valid_ready.append(item)
    if blocked:
        blocked_keys = {task_key(item) for item in blocked}
        state["scheduler"]["ready_queue"] = [
            item for item in ready if task_key(item) not in blocked_keys
        ]
        recovery = state["scheduler"].setdefault("recovery_queue", [])
        for item in blocked:
            if not any(task_key(existing) == task_key(item) for existing in recovery if isinstance(existing, dict)):
                recovery.append(item)
        pc.append_event(state, "selected_style_page_input_blocked", pc.now_iso(), details={
            "pages": [str(item["page_id"]) for item in blocked],
            "unaffected_pages_continued": [str(item["page_id"]) for item in valid_ready],
        })
        pc.atomic_write_json(state_path, state)
    started: list[dict[str, Any]] = []
    wave_id = None
    if valid_ready and available:
        requested = [{
            "style": item["style"], "page_id": str(item["page_id"]),
            "action": item["action"], "attempt": int(item.get("attempt") or 1),
        } for item in valid_ready[:available]]
        agent_map = {task_key(item): EXECUTOR_AGENT_ID for item in requested}
        dispatched = capture(
            pc.command_record_dispatch_wave, state=str(state_path), styles=None,
            tasks_json=json.dumps(requested, ensure_ascii=False), page_id=None,
            action="generate_page", attempt=1, timestamp=None,
            agent_map_json=json.dumps(agent_map, ensure_ascii=False),
            backpressure_reason=(
                "page_input_mismatch" if blocked else
                "shared_imagegen_capacity" if len(valid_ready) > available else None
            ),
        )
        started = dispatched.get("tasks") or []
        wave_id = dispatched.get("wave_id")
        state = pc.read_json(state_path)
    if started:
        items = []
        for task in started:
            job_path = Path(task["generation_job_path"]).resolve()
            job = pc.read_json(job_path)
            items.append({
                "style": task["style"], "page_id": str(task["page_id"]),
                "action": task["action"], "attempt": int(task.get("attempt") or 1),
                "technical_retry": task.get("technical_retry") is True,
                "task_key": task_key(task), "generation_job_path": str(job_path),
                "generation_job_sha256": pc.file_sha256(job_path),
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "prompt": job["imagegen_prompt"],
                "referenced_image_paths": job["imagegen_referenced_paths"],
                "contains_image_payload": False,
            })
        manifest = {
            "selected_style_control_plane_version": CONTROL_VERSION,
            "run_id": state["run_id"], "state_path": str(state_path.resolve()),
            "wave_id": wave_id, "shared_imagegen_capacity": GLOBAL_IMAGEGEN_CAPACITY,
            "executor_agents": 1, "executor_agent_id": EXECUTOR_AGENT_ID,
            "tasks": items, "created_at": pc.now_iso(), "contains_image_payload": False,
        }
        paths["manifests"].mkdir(parents=True, exist_ok=True)
        manifest_path = paths["manifests"] / f"wave_{safe_key(str(wave_id or pc.now_iso()))}.json"
        pc.write_idempotent(manifest_path, manifest)
        return {
            "status": "started", "manifest_path": str(manifest_path.resolve()),
            "tasks": [{"task_key": item["task_key"]} for item in items],
            "active_count": len((state.get("scheduler") or {}).get("active_actions") or []),
            "executor_agents": 1, "imagegen_capacity": GLOBAL_IMAGEGEN_CAPACITY,
            "contains_image_payload": False,
        }
    state = pc.read_json(state_path)
    scheduler = state.get("scheduler") or {}
    active_count = len(scheduler.get("active_actions") or [])
    ready_count = len(scheduler.get("ready_queue") or [])
    recovery_count = len(scheduler.get("recovery_queue") or [])
    completed = sum(
        1 for page_id in state["page_order"]
        if isinstance(state["pages"][page_id].get("selected_source"), str)
        and Path(state["pages"][page_id]["selected_source"]).is_file()
    )
    if recovery_count and not active_count and not ready_count:
        return {
            "status": "recovery_required", "recovery_tasks": scheduler["recovery_queue"],
            "contains_image_payload": False,
        }
    return {
        "status": "complete" if completed == len(state["page_order"]) else "waiting" if active_count else "idle",
        "completed": completed, "active_count": active_count, "ready_count": ready_count,
        "contains_image_payload": False,
    }


def render_action(state_path: Path) -> str:
    require_run(state_path)
    script = shlex.quote(str(SCRIPT_PATH))
    state_q = shlex.quote(str(state_path.resolve()))
    return f'''(async () => {{
  const sh = value => "'" + String(value).replace(/'/g, "'\\\"'\\\"'") + "'";
  const run = async cmd => {{
    const out = await tools.exec_command({{cmd,yield_time_ms:30000,max_output_tokens:4000}});
    if (out.session_id) {{
      let current = out;
      while (current.session_id) current = await tools.write_stdin({{session_id:current.session_id,chars:"",yield_time_ms:30000,max_output_tokens:4000}});
      out.output = current.output; out.exit_code = current.exit_code;
    }}
    if (out.exit_code!==0 && out.exit_code!==undefined) throw new Error(out.output||"command failed");
    return JSON.parse((out.output||"{{}}").trim());
  }};
  const base = {json.dumps(f"{sys.executable} {script} ")};
  const stateArg = {json.dumps(f" --state {state_q}")};
  const findPath = value => {{ const seen=new Set(); const walk=v=>{{if(v==null||seen.has(v))return null;if(typeof v==="string")return v.includes("/exec-")&&v.includes(".png")?v:null;if(typeof v!=="object")return null;seen.add(v);for(const k of ["savedPath","saved_path","output_hint","path"])if(k in v){{const p=walk(v[k]);if(p)return p;}}for(const [k,c] of Object.entries(v))if(!["data","image_url"].includes(k)){{const p=walk(c);if(p)return p;}}return null;}};return walk(value);}};
  const running = new Map();
  let fatalError = null;
  const launch = (manifestPath, summary) => {{
   const promise=(async()=>{{
    const common=stateArg+" --manifest "+sh(manifestPath);
    const input = await run(base+"_task-input"+common+" --task-key "+sh(summary.task_key));
    const claimed = await run(base+"_claim"+common+" --task-key "+sh(summary.task_key)+" --wait-seconds 1200");
    if (claimed.status==="receipt_exists") return claimed.receipt_path;
    if (claimed.status!=="claimed") throw new Error("ImageGen slot wait failed");
    const started = new Date().toISOString(); let result;
    try {{ const payload={{prompt:input.prompt}}; if(input.referenced_image_paths.length) payload.referenced_image_paths=input.referenced_image_paths; const generated=await tools.image_gen__imagegen(payload); result={{savedPath:findPath(generated),tool_started_at:started,tool_finished_at:new Date().toISOString(),error:null,tool_status:"completed"}}; }}
    catch(error){{result={{savedPath:null,tool_started_at:started,tool_finished_at:new Date().toISOString(),error:"imagegen_backend_failed",tool_status:"failed",failure_class:"backend_failed",tool_error_code:String(error).slice(0,240)}};}}
    const receipt=await run(base+"_receipt"+common+" --task-key "+sh(summary.task_key)+" --result-json "+sh(JSON.stringify(result)));
    return receipt.receipt_path;
   }})().finally(async()=>{{try{{await run(base+"_release"+stateArg+" --manifest "+sh(manifestPath)+" --task-key "+sh(summary.task_key));}}catch(_){{}}}});
   running.set(summary.task_key,promise);
  }};
  while(true){{
    let prepared={{status:"draining_after_error"}}; let stopResult=null;
    if(!fatalError){{try{{prepared=await run(base+"_prepare-next"+stateArg+(running.size===0?" --recover-orphans":""));}}catch(error){{fatalError=error;}}}}
    if(!fatalError&&(prepared.status==="recovery_required"||prepared.status==="blocked"))stopResult=prepared;
    if(!fatalError&&!stopResult&&prepared.status==="started")for(const item of prepared.tasks)if(!running.has(item.task_key))launch(prepared.manifest_path,item);
    if(!running.size){{if(fatalError)throw fatalError;if(stopResult){{text(JSON.stringify(stopResult));return;}}if(prepared.status==="complete"){{text(JSON.stringify(prepared));return;}}throw new Error("selected-style runner has unfinished state but no runnable task");}}
    const completed=await Promise.race([...running.entries()].map(async([key,promise])=>{{try{{return[key,await promise,null];}}catch(error){{return[key,null,error];}}}}));
    running.delete(completed[0]);
    if(completed[2]){{fatalError=completed[2];continue;}}
    await run(base+"_settle"+stateArg+" --receipt "+sh(completed[1]));
  }}
}})()'''


def candidate_set(state: dict[str, Any]) -> list[dict[str, Any]]:
    values = []
    for page_id in state["page_order"]:
        record = state["pages"][page_id]
        source = record.get("selected_source")
        if not isinstance(source, str) or not Path(source).is_file():
            raise SystemExit(f"页 {page_id} 尚无已结算候选")
        path = Path(source).resolve()
        width, height, size, sha = pc.png_metadata(path)
        values.append({"page_id": page_id, "path": str(path), "width": width, "height": height, "size_bytes": size, "sha256": sha})
    return values


def candidate_set_sha256(values: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps([{"page_id": x["page_id"], "sha256": x["sha256"]} for x in values], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def ensure_judge_job(state_path: Path, state: dict[str, Any], project_dir: Path, values: list[dict[str, Any]]) -> tuple[Path, Path, Path]:
    paths = canonical_paths(project_dir)
    round_value = int((state.get("selected_style_judge") or {}).get("round") or 1)
    suffix = "" if round_value == 1 else f"_round_{round_value}"
    overview = project_dir / "overview" / f"style_{state['selected_style']}_{'-'.join(state['page_order'])}_overview{suffix}.png"
    source_state_path = project_dir / "state" / f"selected_style_overview_sources{suffix}.json"
    pc.atomic_write_json(source_state_path, {"pages": {item["page_id"]: {"selected_source": item["path"]} for item in values}})
    python = Path(str((state.get("overview_runtime") or {}).get("python") or "")).resolve()
    if not python.is_file():
        raise SystemExit("扩页状态缺少已绑定 overview Python")
    command = [str(python), str(Path(__file__).with_name("build_page_overview.py")), "--project-dir", str(project_dir), "--style-id", f"style_{state['selected_style']}", "--pages", ",".join(state["page_order"]), "--output", str(overview), "--source-state", str(source_state_path)]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip() or "扩页总览生成失败")
    job_path = paths["judge_job"] if round_value == 1 else paths["judge_job"].with_name(f"selected_style_judge_round_{round_value}.json")
    report_path = paths["judge_results"] / ("selected_style_judge_report.json" if round_value == 1 else f"selected_style_judge_report_round_{round_value}.json")
    candidates: list[dict[str, Any]] = []
    for item in values:
        page_id = item["page_id"]
        record = state["pages"][page_id]
        attempt = int(record.get("attempt_count") or 1)
        action = str(
            record.get("selected_action")
            or ("repair_page" if attempt > 1 else "generate_page")
        )
        if action not in {"generate_page", "repair_page"}:
            raise SystemExit(f"页 {page_id} 的 selected_action 无效")
        generation_job = pc.generation_job_path_for_task(
            project_dir,
            {
                "style": state["selected_style"], "page_id": page_id,
                "action": action, "attempt": attempt,
            },
            pc.SELECTED_STYLE_EXPANSION_MODE,
        )
        if generation_job is None or not generation_job.is_file():
            raise SystemExit(f"页 {page_id} 缺少正式 generation job")
        content_contract = project_dir / "content_contracts" / f"page_{page_id}.json"
        content_value = pc.read_json(content_contract)
        generation_value = pc.read_json(generation_job)
        projected_title = (
            (generation_value.get("global_chrome") or {}).get("main_title") or {}
        )
        expected_main_title = str(
            content_value.get("title")
            or content_value.get("page_title")
            or (projected_title.get("text") if isinstance(projected_title, dict) else "")
            or ""
        ).strip()
        expected_subtitle = str(content_value.get("subtitle") or "").strip()
        candidates.append({
            **item,
            "content_contract_path": str(content_contract.resolve()),
            "content_contract_sha256": pc.file_sha256(content_contract),
            "generation_job_path": str(generation_job.resolve()),
            "generation_job_sha256": pc.file_sha256(generation_job),
            "anchor_input_mode": generation_value.get("anchor_input_mode"),
            "expected_main_title": expected_main_title,
            "expected_subtitle": expected_subtitle or None,
            "title_review_policy": {
                "visually_dominant_title_must_match_current_page": bool(expected_main_title),
                "forbid_attachment_or_anchor_subtitle_when_unspecified": not bool(expected_subtitle),
                "allow_harmless_terminal_punctuation_difference": True,
            },
            "page_adaptation_brief": generation_value.get("page_adaptation_brief"),
            "representation_disclosure": generation_value.get("representation_disclosure"),
            "global_chrome": generation_value.get("global_chrome"),
            "required_assets": generation_value.get("required_assets") or [],
            "required_page_assets": generation_value.get("required_page_assets") or [],
            "planning_evidence": generation_value.get("planning_evidence") or [],
        })
    report_template = {
        "selected_style_judge_report_version": JUDGE_REPORT_VERSION,
        "run_id": state["run_id"],
        "candidate_set_sha256": candidate_set_sha256(values),
        "review_kind": "delta_review" if round_value > 1 else "initial",
        "decision": "pass|repair|best_effort",
        "technical_health": {"status": "pass|fail", "issues": []},
        "visual_correctness": {"status": "pass|fail|needs_content_decision", "issues": []},
        "style_family": {"status": "pass|fail", "summary": ""},
        "pages": {page_id: {
            "status": "pass|fail|needs_content_decision",
            "observable_issues": [], "must_change": [], "invariants": [],
            "content_gate": {"status": "pass|fail|needs_content_decision", "reason": ""},
            "spatial_gate": {"status": "pass|fail", "reason": ""},
            "craft_gate": {"status": "pass|fail", "reason": ""},
        } for page_id in state["page_order"]},
        "repair_pages": [], "needs_content_decision_pages": [], "summary": "",
    }
    job = {
        "selected_style_judge_job_version": JUDGE_JOB_VERSION, "run_id": state["run_id"],
        "round": round_value, "candidate_set_sha256": candidate_set_sha256(values),
        "review_kind": "delta_review" if round_value > 1 else "initial",
        "review_scope": (
            {"repaired_page_ids": (state.get("selected_style_judge") or {}).get("repair_page_ids") or [], "compare_family_and_adjacent_only": True}
            if round_value > 1 else {"page_ids": state["page_order"]}
        ),
        "overview_path": str(overview.resolve()), "candidates": candidates,
        "selected_style_contract_path": state["selected_style_contract_path"],
        "selected_style_contract_sha256": state["selected_style_contract_sha256"],
        "global_chrome_contract_path": pc.read_json(Path(state["selected_style_contract_path"])).get("global_chrome_contract_path"),
        "anchor_approval_scope": state.get("anchor_approval_scope"),
        "report_output_path": str(report_path.resolve()),
        "report_template": report_template,
        "checks": ["facts_and_relationships", "display_required", "current_page_main_title", "logo_and_title_when_authorized", "semantic_pollution", "same_visual_family", "mechanical_cross_page_repetition", "severe_composition_or_craft_regression", "crop_garbled_text_wrong_asset"],
        "repair_policy": {
            "only_clear_failures": True,
            "max_targeted_rounds": 1,
            "input_policies": {
                "preserve_candidate": "local visual edit",
                "regenerate_without_candidate": "semantic failure; omit failed candidate",
                "regenerate_text_family": "raster-anchor semantic pollution; omit failed candidate and raster anchor",
            },
        },
        "media_policy": "isolated_judge_only_no_parent_image_payload",
    }
    pc.write_idempotent(job_path, job)
    return job_path, report_path, overview


def prepare_repairs(state_path: Path, state: dict[str, Any], project_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    judge = state.setdefault("selected_style_judge", {})
    if int(judge.get("repair_rounds_used") or 0) >= 1:
        raise SystemExit("扩页定向修复预算已耗尽")
    repair_pages = report.get("repair_pages") or []
    if not isinstance(repair_pages, list) or not repair_pages:
        raise SystemExit("Judge repair 决定缺少 repair_pages")
    queued = []
    for item in repair_pages:
        if not isinstance(item, dict):
            raise SystemExit("repair_pages 项必须是对象")
        matches = [page for page in state["page_order"] if pc.page_ids_match(page, item.get("page_id"))]
        if len(matches) != 1:
            raise SystemExit("Judge repair page_id 不在本轮范围")
        page_id = matches[0]
        record = state["pages"][page_id]
        attempt = int(record.get("attempt_count") or 1) + 1
        source_job = project_dir / "page_jobs" / f"page_{page_id}.json"
        original = pc.read_json(source_job)
        current = str(Path(record["selected_source"]).resolve())
        repair_input_policy = str(item.get("repair_input_policy") or "preserve_candidate")
        if repair_input_policy not in {
            "preserve_candidate",
            "regenerate_without_candidate",
            "regenerate_text_family",
        }:
            raise SystemExit("repair_input_policy 无效")
        original_refs = list(original.get("reference_images") or [])
        if repair_input_policy == "preserve_candidate":
            refs = [
                {"path": current, "role": "repair_source_candidate"},
                *original_refs,
            ]
        elif repair_input_policy == "regenerate_without_candidate":
            refs = original_refs
        else:
            refs = []
        declared = refs + list(original.get("required_assets") or []) + list(original.get("required_page_assets") or [])
        deduped = pc.merge_attachment_items(declared)
        if len(deduped) > pc.IMAGEGEN_MAX_REFERENCED_PATHS:
            supporting_paths = {a["path"] for a in state.get("style_anchors") or [] if a.get("role") == "supporting"}
            deduped = [entry for entry in deduped if entry.get("path") not in supporting_paths]
        if len(deduped) > pc.IMAGEGEN_MAX_REFERENCED_PATHS:
            raise SystemExit(f"页 {page_id} 修复输入超过 5 附件")
        repair_refs = [
            entry for entry in deduped
            if entry.get("role") in {
                "repair_source_candidate", "primary_style_anchor", "supporting_style_anchor"
            }
        ]
        repair_required_assets = [
            entry for entry in deduped
            if entry.get("role") not in {
                "repair_source_candidate", "primary_style_anchor", "supporting_style_anchor",
                "required_page_asset",
            }
        ]
        repair_page_assets = [
            entry for entry in deduped if entry.get("role") == "required_page_asset"
        ]
        content_contract = pc.read_json(Path(original["source_content_contract_path"]))
        style_family_contract = pc.read_json(Path(original["style_family_contract_path"]))
        prompt, _ = compile_selected_render_prompt(
            page=content_contract,
            layout=original["layout_direction"],
            tone=str(style_family_contract["tone"]),
            language=original.get("language"),
            reference_images=repair_refs,
            required_assets=repair_required_assets,
            required_page_assets=repair_page_assets,
            chrome_projection=original.get("global_chrome"),
            disclosure=original.get("representation_disclosure") or {"mode": "none"},
        )
        repair_instruction = (
            "Targeted edit of the supplied candidate"
            if repair_input_policy == "preserve_candidate"
            else "Fresh regeneration from the current-page contract"
        )
        prompt += (
            f"\n\n{repair_instruction}: "
            + str(item.get("must_change") or "Fix the explicit Judge failure only.")
            + " Preserve: "
            + "; ".join(str(x) for x in item.get("invariants") or [])
        )
        prompt = pc.finalize_imagegen_prompt(prompt)
        paths_value, manifest = pc.build_input_manifest(pc.extract_input_paths(deduped))
        repair = dict(original)
        repair.update({
            "action": "repair_page", "attempt": attempt,
            "repair_source": current if repair_input_policy == "preserve_candidate" else None,
            "repair_input_policy": repair_input_policy,
            "anchor_input_mode": (
                "text_family"
                if repair_input_policy == "regenerate_text_family"
                else original.get("anchor_input_mode")
            ),
            "must_change": item.get("must_change"), "invariants": item.get("invariants") or [],
            "reference_images": repair_refs,
            "required_assets": repair_required_assets,
            "required_page_assets": repair_page_assets,
            "imagegen_prompt": prompt, "imagegen_prompt_fingerprint": hashlib.sha256(prompt.encode()).hexdigest(),
            "imagegen_referenced_paths": paths_value, "imagegen_input_manifest": manifest,
            "imagegen_input_fingerprint": hashlib.sha256(json.dumps({"prompt": prompt, "inputs": manifest}, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        })
        target = project_dir / "page_jobs" / "repair_jobs" / f"page_{page_id}_attempt_{attempt}.json"
        pc.write_idempotent(target, repair)
        queued.append({"style": state["selected_style"], "page_id": page_id, "action": "repair_page", "attempt": attempt, "generation_job_path": str(target), "generation_job_sha256": pc.file_sha256(target)})
        record["status"] = "retry_pending"
    state["scheduler"]["ready_queue"] = queued
    judge["repair_rounds_used"] = 1
    judge["round"] = 2
    judge["repair_page_ids"] = [item["page_id"] for item in queued]
    judge["status"] = "repair_pending"
    pc.append_event(state, "selected_style_repair_queued", pc.now_iso(), details={"pages": [item["page_id"] for item in queued]})
    pc.atomic_write_json(state_path, state)
    return {"status": "repair_required", "pages": [item["page_id"] for item in queued], "jobs": [item["generation_job_path"] for item in queued]}


def reapply_completed_judge_report(state_path: Path) -> dict[str, Any]:
    """Reopen an incorrectly finalized run after the same Judge replaces its report.

    The operation is deliberately narrow: the replacement must be a valid repair
    report for the exact same run and candidate set. Existing sealed delivery
    sidecars are backed up before the single repair round is queued.
    """

    state, project_dir = require_run(state_path)
    if state.get("status") != "completed":
        raise SystemExit("reapply-judge-report 只接受已被提前收口的 completed 运行")
    judge = state.get("selected_style_judge") or {}
    report_path = Path(str(judge.get("report_path") or "")).expanduser().resolve()
    expected_report = (
        canonical_paths(project_dir)["judge_results"]
        / "selected_style_judge_report.json"
    ).resolve()
    if report_path != expected_report or not report_path.is_file():
        raise SystemExit("completed 运行缺少规范首轮 Judge 报告")
    old_sha = str(judge.get("report_sha256") or "")
    new_sha = pc.file_sha256(report_path)
    if not old_sha or old_sha == new_sha:
        raise SystemExit("Judge 报告未发生替换，无需重开")
    report = pc.read_json(report_path)
    current_set_sha = candidate_set_sha256(candidate_set(state))
    expected_set_sha = str(judge.get("candidate_set_sha256") or "")
    if (
        report.get("selected_style_judge_report_version") != JUDGE_REPORT_VERSION
        or report.get("run_id") != state.get("run_id")
        or report.get("candidate_set_sha256") != expected_set_sha
        or current_set_sha != expected_set_sha
    ):
        raise SystemExit("替换后的 Judge 报告未绑定同一 run/candidate set")
    if report.get("decision") != "repair":
        raise SystemExit("已完成运行只允许用同一 Judge 的明确 repair 报告重开")

    backup_dir = project_dir / "state" / "judge_reapply_backups" / old_sha[:12]
    backup_dir.mkdir(parents=True, exist_ok=True)
    sidecars = (
        state_path,
        project_dir / "state" / "handoff.json",
        project_dir / "state" / "handoff.md",
        project_dir / "state" / "delivery_message.md",
    )
    for source in sidecars:
        if source.is_file():
            target = backup_dir / source.name
            if not target.exists():
                shutil.copy2(source, target)
    for stale in sidecars[1:]:
        if stale.is_file():
            stale.unlink()

    state["status"] = "running"
    state.setdefault("scheduler", {})["phase"] = "selected_style_repair"
    timing = state.setdefault("timing", {})
    timing.pop("formal_overview_completed_at", None)
    timing.pop("process_completed_at", None)
    judge.update({
        "status": "report_replaced_reopen",
        "decision": "repair",
        "report_sha256": new_sha,
    })
    state["selected_style_judge"] = judge
    pc.append_event(
        state,
        "selected_style_completed_run_reopened",
        pc.now_iso(),
        details={
            "old_report_sha256": old_sha,
            "new_report_sha256": new_sha,
            "backup_dir": str(backup_dir),
            "policy": "same_judge_same_candidate_set_repair_only",
        },
    )
    pc.atomic_write_json(state_path, state)
    return prepare_repairs(state_path, state, project_dir, report)


def finalize_content_decision_partial(
    state_path: Path,
    state: dict[str, Any],
    project_dir: Path,
    report: dict[str, Any],
    values: list[dict[str, Any]],
    report_path: Path,
) -> dict[str, Any]:
    """Deliver unaffected accepted pages while keeping only decision pages open."""

    raw_pages = report.get("needs_content_decision_pages") or []
    if not isinstance(raw_pages, list) or not raw_pages:
        raise SystemExit("needs_content_decision 状态缺少 needs_content_decision_pages")
    decision_pages: list[str] = []
    for value in raw_pages:
        page_value = value.get("page_id") if isinstance(value, dict) else value
        matches = [page for page in state["page_order"] if pc.page_ids_match(page, page_value)]
        if len(matches) != 1 or matches[0] in decision_pages:
            raise SystemExit("needs_content_decision_pages 页码越界或重复")
        decision_pages.append(matches[0])
    accepted: list[str] = []
    now = pc.now_iso()
    page_reports = report.get("pages") or {}
    for item in values:
        page_id = item["page_id"]
        record = state["pages"][page_id]
        review = page_reports.get(page_id) or {}
        if page_id in decision_pages:
            record.update({
                "status": "needs_content_decision",
                "qa_stage": "selected_style_judge",
                "qa_scope": "content_decision_pending",
                "content_gate": review.get("content_gate") or {
                    "status": "needs_content_decision", "reason": "Judge requires a content decision"
                },
            })
            continue
        if review.get("status") != "pass":
            raise SystemExit(f"非待决定页 {page_id} 必须由 Judge 明确标为 pass")
        target = pc.origin_image_target(project_dir, state["selected_style"], page_id).resolve()
        pc.atomic_copy_candidate(Path(item["path"]), target)
        width, height, size, sha = pc.png_metadata(target)
        record.update({
            "status": "accepted", "final_path": str(target), "selected_source": str(target),
            "source_width": width, "source_height": height, "source_size_bytes": size,
            "source_sha256": sha, "qa_stage": "selected_style_judge",
            "qa_scope": "full_visual", "content_gate": review.get("content_gate"),
            "spatial_gate": review.get("spatial_gate"), "craft_gate": review.get("craft_gate"),
            "overview_qa_at": now, "completed_at": now,
        })
        accepted.append(page_id)
        pc.append_event(state, "page_completed", now, style=state["selected_style"], page_id=page_id, action="generate_page", details={"judge_decision": "best_effort"})
    state["status"] = "attention_required"
    state["selected_style_judge"] = {
        **(state.get("selected_style_judge") or {}),
        "status": "needs_content_decision", "decision": "best_effort",
        "report_path": str(report_path), "report_sha256": pc.file_sha256(report_path),
        "needs_content_decision_pages": decision_pages,
    }
    pc.append_event(state, "selected_style_content_decision_required", now, details={
        "pages": decision_pages, "accepted_pages": accepted,
    })
    pc.atomic_write_json(state_path, state)
    partial = project_dir / "state" / "partial_handoff.json"
    pc.atomic_write_json(partial, {
        "selected_style_partial_handoff_version": 1,
        "run_id": state["run_id"], "status": "needs_content_decision",
        "accepted_pages": {page: state["pages"][page]["final_path"] for page in accepted},
        "needs_content_decision_pages": decision_pages,
        "judge_report_path": str(report_path),
    })
    return {
        "status": "needs_content_decision", "accepted_pages": accepted,
        "needs_content_decision_pages": decision_pages, "partial_handoff": str(partial),
    }


def lean_finalize(state_path: Path) -> dict[str, Any]:
    state, project_dir = require_run(state_path)
    if state.get("status") == "completed":
        return {"status": "already_completed", "overview": (state.get("overview") or {}).get("final_path")}
    scheduler = state.get("scheduler") or {}
    if scheduler.get("active_actions") or scheduler.get("ready_queue") or scheduler.get("recovery_queue"):
        raise SystemExit("lean-finalize 前调度队列必须为空")
    values = candidate_set(state)
    job_path, report_path, overview = ensure_judge_job(state_path, state, project_dir, values)
    set_sha = candidate_set_sha256(values)
    if not report_path.is_file():
        state.setdefault("selected_style_judge", {}).update({"status": "waiting_for_report", "round": int((state.get("selected_style_judge") or {}).get("round") or 1), "job_path": str(job_path), "candidate_set_sha256": set_sha})
        pc.atomic_write_json(state_path, state)
        return {"status": "waiting_for_judge", "judge_job": str(job_path), "report_output_path": str(report_path), "overview": str(overview)}
    report = pc.read_json(report_path)
    if report.get("selected_style_judge_report_version") != JUDGE_REPORT_VERSION or report.get("run_id") != state["run_id"] or report.get("candidate_set_sha256") != set_sha:
        raise SystemExit("扩页 Judge 报告版本、run_id 或候选集合哈希不匹配")
    decision = report.get("decision")
    if decision == "repair":
        return prepare_repairs(state_path, state, project_dir, report)
    if decision not in {"pass", "best_effort"}:
        raise SystemExit("扩页 Judge decision 只允许 pass|repair|best_effort")
    technical = report.get("technical_health") or {}
    visual = report.get("visual_correctness") or {}
    if technical.get("status") != "pass" or visual.get("status") not in {"pass", "best_effort", "needs_content_decision"}:
        raise SystemExit("扩页 Judge 报告与 pass/best_effort 决定矛盾")
    if report.get("needs_content_decision_pages"):
        if decision != "best_effort" or visual.get("status") != "needs_content_decision":
            raise SystemExit("待内容决定页必须使用 best_effort + needs_content_decision 状态")
        return finalize_content_decision_partial(
            state_path, state, project_dir, report, values, report_path
        )
    now = pc.now_iso()
    for item in values:
        page_id = item["page_id"]
        target = pc.origin_image_target(project_dir, state["selected_style"], page_id).resolve()
        pc.atomic_copy_candidate(Path(item["path"]), target)
        width, height, size, sha = pc.png_metadata(target)
        record = state["pages"][page_id]
        page_review = ((report.get("pages") or {}).get(page_id) or {})
        record.update({
            "status": "accepted", "final_path": str(target), "selected_source": str(target),
            "source_width": width, "source_height": height, "source_size_bytes": size, "source_sha256": sha,
            "qa_stage": "visual_worker", "qa_scope": "full_visual",
            "content_gate": page_review.get("content_gate") or {"status": "pass", "reason": "Judge pass"},
            "spatial_gate": page_review.get("spatial_gate") or {"status": "pass", "reason": "Judge pass"},
            "craft_gate": page_review.get("craft_gate") or {"status": "pass", "reason": "Judge pass"},
            "overview_qa_at": now, "completed_at": now,
        })
    final_overview = project_dir / "overview" / f"style_{state['selected_style']}_{'-'.join(state['page_order'])}_overview.png"
    python = Path(state["overview_runtime"]["python"])
    command = [str(python), str(Path(__file__).with_name("build_page_overview.py")), "--project-dir", str(project_dir), "--style-id", f"style_{state['selected_style']}", "--pages", ",".join(state["page_order"]), "--output", str(final_overview)]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip() or "正式扩页总览失败")
    ow, oh, osize, osha = pc.raw_png_metadata(final_overview)
    state["overview"] = {"status": "completed", "final_path": str(final_overview), "width": ow, "height": oh, "size_bytes": osize, "sha256": osha}
    state["selected_style_judge"] = {
        **(state.get("selected_style_judge") or {}), "status": "passed", "decision": decision,
        "report_path": str(report_path), "report_sha256": pc.file_sha256(report_path), "candidate_set_sha256": set_sha,
    }
    state["status"] = "completed"
    state["scheduler"]["phase"] = "completed"
    state["timing"]["formal_overview_completed_at"] = now
    state["timing"]["process_completed_at"] = now
    pc.append_event(state, "overview_qa", now, details={"judge_report_path": str(report_path), "candidate_set_sha256": set_sha})
    for page_id in state["page_order"]:
        pc.append_event(state, "page_completed", now, style=state["selected_style"], page_id=page_id, action="generate_page", details={"judge_decision": decision})
    pc.append_event(state, "formal_overview_completed", now, details={"overview": str(final_overview)})
    pc.append_event(state, "process_completed", now, details={"source": "selected_style_control_plane_v1"})
    pc.atomic_write_json(state_path, state)
    handoff = capture(pc.command_write_handoff, state=str(state_path), timestamp=None, refresh_state_ref=False)
    delivery = project_dir / "state" / "delivery_message.md"
    pc.atomic_write_text(delivery, f"[打开扩页总览]({final_overview})\n")
    return {"status": "completed", "overview": str(final_overview), "state": str(state_path), "handoff": handoff.get("handoff_json"), "delivery_message": str(delivery)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="selected-style expansion thin control plane v1")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "prepare-directors",
        "render-action",
        "lean-finalize",
        "reapply-judge-report",
    ):
        command = sub.add_parser(name)
        command.add_argument("--state", required=True)
    prepare_next_p = sub.add_parser("_prepare-next", help=argparse.SUPPRESS)
    prepare_next_p.add_argument("--state", required=True)
    prepare_next_p.add_argument("--recover-orphans", action="store_true")
    task_input = sub.add_parser("_task-input", help=argparse.SUPPRESS)
    task_input.add_argument("--state", required=True); task_input.add_argument("--manifest", required=True); task_input.add_argument("--task-key", required=True)
    claim_p = sub.add_parser("_claim", help=argparse.SUPPRESS)
    claim_p.add_argument("--state", required=True); claim_p.add_argument("--manifest", required=True); claim_p.add_argument("--task-key", required=True); claim_p.add_argument("--wait-seconds", type=float, default=1200)
    receipt = sub.add_parser("_receipt", help=argparse.SUPPRESS)
    receipt.add_argument("--state", required=True); receipt.add_argument("--manifest", required=True); receipt.add_argument("--task-key", required=True); receipt.add_argument("--result-json", required=True)
    release_p = sub.add_parser("_release", help=argparse.SUPPRESS)
    release_p.add_argument("--state", required=True); release_p.add_argument("--manifest", required=True); release_p.add_argument("--task-key", required=True)
    settle = sub.add_parser("_settle", help=argparse.SUPPRESS)
    settle.add_argument("--state", required=True); settle.add_argument("--receipt", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    state_path = Path(args.state)
    if args.command == "prepare-directors": emit(prepare_directors(state_path))
    elif args.command == "render-action": print(render_action(state_path))
    elif args.command == "lean-finalize": emit(lean_finalize(state_path))
    elif args.command == "reapply-judge-report": emit(reapply_completed_judge_report(state_path))
    elif args.command == "_prepare-next": emit(prepare_next(state_path, recover_orphans=args.recover_orphans))
    elif args.command == "_task-input":
        _state, _active, item, _project = validate_manifest_item(state_path, Path(args.manifest), args.task_key)
        emit({"task_key": args.task_key, "prompt": item["prompt"], "referenced_image_paths": item["referenced_image_paths"], "contains_image_payload": False})
    elif args.command == "_claim": emit(claim(state_path, Path(args.manifest), args.task_key, args.wait_seconds))
    elif args.command == "_receipt": emit(write_receipt(state_path, Path(args.manifest), args.task_key, json.loads(args.result_json)))
    elif args.command == "_release": emit(release(state_path, Path(args.manifest), args.task_key))
    elif args.command == "_settle": emit(settle_receipt(state_path, Path(args.receipt)))


if __name__ == "__main__":
    main()
