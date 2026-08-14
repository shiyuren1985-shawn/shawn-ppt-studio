#!/usr/bin/env python3
"""Thin direct control plane for the Fast 4x3 dependency graph.

The module owns no creative or quality policy.  It only joins the existing
pipeline state transitions with one mechanical ImageGen runner:

    style anchor -> the same style's two followers

State writes remain in pipeline_control.py.  This file adds immutable wave
manifests, exact claims/receipts, and the shared cross-task ImageGen ceiling.
"""

from __future__ import annotations

import argparse
import copy
import contextlib
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Optional, Tuple

import pipeline_control as pc
import merge_4x3_director_inputs as merge4x3
import normalize_fast8_chrome_contract as normalize_chrome


CONTROL_VERSION = 1
STYLES = tuple("ABCD")
GLOBAL_IMAGEGEN_CAPACITY = 5
CLAIM_WAIT_SECONDS = 600
SCRIPT_PATH = Path(__file__).resolve()
EXECUTOR_AGENT_ID = "four_by_three_burst_executor_v1"
OVERALL_REQUIREMENTS = (
    "四套成品级 16:9 PPT 页面候选；保持事实准确、视觉家族分离与跨页一致。"
)


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False))


def capture(function, **kwargs: Any) -> dict[str, Any]:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        function(argparse.Namespace(**kwargs))
    raw = stream.getvalue().strip()
    return json.loads(raw) if raw else {}


def require_run(
    state_path: Path, *, require_three_director_method: bool = True
) -> tuple[dict[str, Any], Path]:
    state_path = state_path.expanduser().resolve()
    state = pc.read_json(state_path)
    if state.get("run_mode") != pc.FAST_4X3_MODE:
        raise SystemExit("4x3 control plane v1 只适用于 fast_4x3_anchored")
    if require_three_director_method:
        policy = state.get("fast4x3_candidate_policy") or {}
        if policy.get("version") != 3 or policy.get("three_director_method") is not True:
            raise SystemExit("4x3 control plane v1 只接受三导演方法合同的新运行")
    project_dir = pc.project_dir_for_state(state_path, state)
    expected_state = (project_dir / "state" / "style_run_state.json").resolve()
    if state_path != expected_state:
        raise SystemExit(f"4x3 state 必须使用当前工程规范路径：{expected_state}")
    return state, project_dir


def canonical_paths(
    state_path: Path, *, require_three_director_method: bool = True
) -> tuple[dict[str, Any], Path, dict[str, Path]]:
    state, project_dir = require_run(
        state_path, require_three_director_method=require_three_director_method
    )
    director_root = project_dir / "state" / "director_inputs"
    paths = {
        "director_root": director_root,
        "content_bundle": director_root / "content_bundle.json",
        "assets_bundle": director_root / "required_assets_by_page.json",
        "visual_system": director_root / "visual_system.json",
        "source_packet": director_root / "authoritative_three_page_packet.md",
        "snapshot_source": director_root / "authoritative_snapshot_source.json",
        "global_chrome_raw": director_root / "global_chrome_contract.raw.json",
        "global_chrome": director_root / "global_chrome_contract.normalized.json",
        "content_dir": project_dir / "content_contracts",
        "layout_portfolio": project_dir / "state" / "layout_portfolio.json",
        "overview": project_dir / "overview" / "ABCD_4x3.png",
    }
    return state, project_dir, paths


def canonical_content_dir(
    state_path: Path, supplied: Path | None = None
) -> tuple[dict[str, Any], Path, Path]:
    state, project_dir, paths = canonical_paths(state_path)
    expected = paths["content_dir"].resolve()
    if supplied is not None and supplied.expanduser().resolve() != expected:
        raise SystemExit(f"content_contracts 必须使用当前工程规范路径：{expected}")
    return state, project_dir, expected


def preflight_style_references(project_dir: Path) -> list[dict[str, Any]]:
    """Reuse only explicitly routed style references from the frozen preflight."""

    manifest_path = project_dir / "state" / "preflight_manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = pc.read_json(manifest_path)
    items = manifest.get("asset_items") or []
    if not isinstance(items, list):
        raise SystemExit("4x3 preflight asset_items 必须是数组")
    references: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise SystemExit(f"4x3 preflight asset_items[{index}] 必须是对象")
        role = str(item.get("role") or "").strip().lower()
        if role not in pc.FAST8_STYLE_REFERENCE_ROLES:
            continue
        path_value = item.get("path")
        if not isinstance(path_value, str):
            raise SystemExit(f"4x3 preflight style reference[{index}] 缺少 path")
        path = Path(path_value).expanduser()
        if not path.is_absolute() or not path.resolve().is_file():
            raise SystemExit(f"4x3 preflight style reference[{index}] 不是现存绝对文件")
        references.append({**item, "path": str(path.resolve()), "role": role})
    return references


def resolve_overview_python(state: dict[str, Any]) -> Path:
    """Resolve one Pillow-capable Python and reuse it for the formal overview."""

    configured = (state.get("overview_runtime") or {}).get("python")
    candidates = [
        Path(configured).expanduser() if isinstance(configured, str) else None,
        Path(sys.executable),
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        candidate = candidate.resolve()
        if str(candidate) in seen or not candidate.is_file():
            continue
        seen.add(str(candidate))
        checked = subprocess.run(
            [str(candidate), "-c", "import PIL"],
            text=True,
            capture_output=True,
            check=False,
        )
        if checked.returncode == 0:
            return candidate
    raise SystemExit("4x3 总览缺少可用的 Pillow Python")


def validate_follower_attachment_budget(
    state_path: Path, state: dict[str, Any], project_dir: Path, content_dir: Path
) -> dict[str, int]:
    """Prove every future follower stays within the shared five-image ceiling."""

    page_ids = [str(value) for value in (state.get("follower_page_ids") or [])]
    if len(page_ids) != 2:
        raise SystemExit("Fast 4x3 必须包含两个跟随页")
    tones = pc.tones_for_run(state, pc.FAST_4X3_MODE, list(STYLES))
    chrome_path_value = state.get("global_chrome_contract_path")
    chrome_path: Path | None = None
    chrome: dict[str, Any] | None = None
    chrome_sha: str | None = None
    if isinstance(chrome_path_value, str) and chrome_path_value:
        chrome_path, chrome, chrome_sha = pc.read_global_chrome_contract(
            chrome_path_value, verify_authorization_source=False
        )
        if chrome_sha != state.get("global_chrome_contract_sha256"):
            raise SystemExit("4x3 global chrome contract SHA-256 与 state 不一致")
    counts: dict[str, int] = {}
    for style in STYLES:
        anchor_job = pc.read_json(project_dir / "style_jobs" / f"style_{style}.json")
        tone = str(anchor_job.get("tone") or tones[style])
        shared_assets = pc.merge_attachment_items(
            pc.filter_required_assets(
                pc.follower_shared_asset_items(
                    pc.non_global_chrome_assets(anchor_job.get("required_assets") or [])
                ),
                style,
                tone,
            )
        )
        for page_id in page_ids:
            contract_path = content_dir / f"page_{page_id}.json"
            contract = pc.read_json(contract_path)
            page_assets = pc.merge_attachment_items(
                pc.filter_required_assets(
                    pc.content_contract_asset_items(contract), style, tone
                )
            )
            projected_shared = list(shared_assets)
            if chrome_path is not None and chrome is not None and chrome_sha is not None:
                projection = pc.global_chrome_projection(
                    chrome,
                    contract_path=chrome_path,
                    contract_sha256=chrome_sha,
                    page_id=page_id,
                    style=style,
                    tone=tone,
                    language=contract.get("language") or state.get("language") or "source",
                )
                pc.validate_page_global_chrome_compatibility(
                    contract, projection, f"style_{style}/{page_id}"
                )
                logo_asset = projection.get("logo_asset")
                if isinstance(logo_asset, dict):
                    projected_shared = pc.merge_attachment_items(
                        projected_shared, [logo_asset]
                    )
            actual_assets = pc.merge_attachment_items(projected_shared, page_assets)
            current_family = (
                isinstance(anchor_job.get("layout_direction"), dict)
                and anchor_job["layout_direction"].get(
                    "style_family_portfolio_version"
                )
                == pc.CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
            )
            asset_count = len(pc.extract_input_paths(actual_assets))
            # New v5 followers use the raster anchor unless required page/brand
            # inputs already consume the full attachment budget.  The fallback
            # is deterministic and does not add another review step.
            use_anchor_raster = not (
                current_family and asset_count >= pc.IMAGEGEN_MAX_REFERENCED_PATHS
            )
            count = asset_count + (1 if use_anchor_raster else 0)
            counts[f"{style}/{page_id}"] = count
            if count > pc.IMAGEGEN_MAX_REFERENCED_PATHS:
                raise SystemExit(
                    f"style_{style}/{page_id} 跟随页将使用 {count} 个图片输入；"
                    f"上限为 {pc.IMAGEGEN_MAX_REFERENCED_PATHS}"
                )
    return counts


def prepare_director_inputs(state_path: Path) -> dict[str, Any]:
    """Merge the three canonical director outputs and prepare A-D once."""

    state, project_dir, paths = canonical_paths(
        state_path, require_three_director_method=False
    )
    existing_jobs = sorted((project_dir / "style_jobs").glob("style_[A-D].json"))
    if existing_jobs:
        return {
            "status": "failed",
            "failed_stage": "precheck",
            "error": "style_jobs 已存在；prepare-directors 只用于首次准备",
            "style_job_count": len(existing_jobs),
        }
    required = (
        "content_bundle",
        "assets_bundle",
        "visual_system",
        "source_packet",
        "snapshot_source",
    )
    missing = [str(paths[name]) for name in required if not paths[name].is_file()]
    if missing:
        return {
            "status": "failed",
            "failed_stage": "precheck",
            "error": "缺少规范输入：" + ", ".join(missing),
            "style_job_count": 0,
        }
    if paths["global_chrome"].is_file() and not paths["global_chrome_raw"].is_file():
        return {
            "status": "failed",
            "failed_stage": "precheck",
            "error": "global chrome normalized 合同存在时必须保留 raw 授权合同",
            "style_job_count": 0,
        }
    # Run the existing cheap state audit before any snapshot or generation job
    # is written.  This catches malformed startup metadata (for example a
    # rounded preflight timestamp that sorts before process_started_at) while a
    # deterministic correction is still harmless, instead of failing only
    # after twelve expensive ImageGen calls during lean-finalize.
    audit_output = io.StringIO()
    try:
        with contextlib.redirect_stdout(audit_output):
            pc.command_validate_state(
                argparse.Namespace(state=str(state_path), complete=False)
            )
    except SystemExit:
        detail = audit_output.getvalue().strip()
        return {
            "status": "failed",
            "failed_stage": "precheck",
            "error": "4x3 初始状态审计失败：" + (detail or "unknown error"),
            "style_job_count": 0,
        }
    page_ids = [
        str(state.get("anchor_page_id")),
        *(str(value) for value in (state.get("follower_page_ids") or [])),
    ]
    snapshot_state_before = {
        key: state.get(key)
        for key in (
            "source_guard_contract_version",
            "source_snapshot_path",
            "source_snapshot_sha256",
            "source_integrity",
        )
        if key in state
    }
    formal_snapshot = project_dir / "state" / "source_snapshot.json"
    snapshot_existed_before = formal_snapshot.is_file()
    snapshot_source = pc.read_json(paths["snapshot_source"])
    if (
        snapshot_source.get("four_by_three_snapshot_source_version") != 1
        or snapshot_source.get("page_order") != page_ids
    ):
        return {
            "status": "failed",
            "failed_stage": "precheck",
            "error": "authoritative_snapshot_source.json 与 state 三页范围不一致",
            "style_job_count": 0,
        }
    if paths["global_chrome_raw"].is_file():
        source_pages = snapshot_source.get("pages") or {}
        raw_chrome = pc.read_json(paths["global_chrome_raw"])
        raw_deck = raw_chrome.get("deck_title_system") or {}
        raw_scope = raw_deck.get("scope") if isinstance(raw_deck, dict) else {}
        include_page_ids = (
            raw_scope.get("include_page_ids")
            if isinstance(raw_scope, dict)
            else None
        ) or page_ids
        title_map: dict[str, str] = {}
        for page_id in page_ids:
            if not any(pc.page_ids_match(page_id, value) for value in include_page_ids):
                continue
            source_page = source_pages.get(page_id) if isinstance(source_pages, dict) else None
            title = source_page.get("canonical_title") if isinstance(source_page, dict) else None
            if not isinstance(title, str) or not title.strip():
                return {
                    "status": "failed",
                    "failed_stage": "precheck",
                    "error": f"page {page_id} 缺少 canonical_title，无法确定性编译标题合同",
                    "style_job_count": 0,
                }
            title_map[page_id] = title.strip()
        try:
            scoped_raw_chrome = copy.deepcopy(raw_chrome)
            scoped_deck = scoped_raw_chrome.get("deck_title_system")
            if isinstance(scoped_deck, dict):
                scoped_scope = scoped_deck.get("scope")
                if not isinstance(scoped_scope, dict):
                    scoped_scope = {}
                    scoped_deck["scope"] = scoped_scope
                # A 4x3 run only owns its three frozen pages. Project a broader
                # authorized deck contract to that run before normalization;
                # do not ask a Director to rewrite the same policy just to
                # narrow an include list.
                scoped_scope["include_page_ids"] = list(title_map)
                scoped_scope["exclude_page_ids"] = []
            normalized_chrome = normalize_chrome.normalize_contract(
                scoped_raw_chrome,
                page_id=page_ids[0],
                canonical_title=title_map.get(page_ids[0], ""),
                source_packet=paths["source_packet"],
                page_title_map=title_map,
            )
            normalize_chrome.validated_atomic_write(
                paths["global_chrome"], normalized_chrome
            )
        except SystemExit as exc:
            return {
                "status": "failed",
                "failed_stage": "precheck",
                "error": str(exc),
                "style_job_count": 0,
            }
    try:
        merged = merge4x3.merge_bundle(
            state_path=state_path,
            content_bundle_path=paths["content_bundle"],
            assets_bundle_path=paths["assets_bundle"],
            visual_system_path=paths["visual_system"],
            content_output_dir=paths["content_dir"],
            layout_output_path=paths["layout_portfolio"],
        )
        content_paths = [paths["content_dir"] / f"page_{page_id}.json" for page_id in page_ids]
        prepared = capture(
            pc.command_prepare_anchors,
            project_dir=str(project_dir),
            state=str(state_path),
            content_contract=str(content_paths[0]),
            overall_requirements=OVERALL_REQUIREMENTS,
            reference_images_json=json.dumps(
                preflight_style_references(project_dir), ensure_ascii=False
            ),
            required_assets_json="[]",
            required_assets_file=None,
            global_chrome_contract=(
                str(paths["global_chrome"]) if paths["global_chrome"].is_file() else None
            ),
            source_file=str(paths["snapshot_source"]),
            source_page_ids=",".join(page_ids),
            source_fragment_file=None,
            source_fragment_authority="extractor_aid",
            snapshot_content_contracts_json=json.dumps(
                [str(path) for path in content_paths], ensure_ascii=False
            ),
            source_snapshot_timestamp=None,
            layout_portfolio=str(paths["layout_portfolio"]),
            overview_python=None,
        )
        prepared_state = pc.read_json(state_path)
        attachment_counts = validate_follower_attachment_budget(
            state_path, prepared_state, project_dir, paths["content_dir"]
        )
        overview_python = resolve_overview_python(prepared_state)
        prepared_state["overview_runtime"] = {
            "python": str(overview_python),
            "pillow_preflight": "pass",
            "binding_policy": "prepare_directors_bound_reuse_for_formal_overview",
        }
        pc.atomic_write_json(state_path, prepared_state)
    except SystemExit as exc:
        style_job_count = len(
            list((project_dir / "style_jobs").glob("style_[A-D].json"))
        )
        if style_job_count == 0 and not snapshot_existed_before:
            try:
                formal_snapshot.unlink()
            except FileNotFoundError:
                pass
            rolled_back_state = pc.read_json(state_path)
            for key in (
                "source_guard_contract_version",
                "source_snapshot_path",
                "source_snapshot_sha256",
                "source_integrity",
            ):
                if key in snapshot_state_before:
                    rolled_back_state[key] = snapshot_state_before[key]
                else:
                    rolled_back_state.pop(key, None)
            pc.atomic_write_json(state_path, rolled_back_state)
        return {
            "status": "failed",
            "failed_stage": "merge_or_prepare",
            "error": str(exc),
            "style_job_count": style_job_count,
            "source_snapshot_rolled_back": (
                style_job_count == 0 and not snapshot_existed_before
            ),
        }
    return {
        "status": "ok",
        "page_order": page_ids,
        "merge": merged,
        "prepare": prepared,
        "style_job_count": 4,
        "content_contract_dir": str(paths["content_dir"]),
        "layout_portfolio": str(paths["layout_portfolio"]),
        "snapshot_source": str(paths["snapshot_source"]),
        "follower_attachment_counts": attachment_counts,
        "overview_python": str(overview_python),
        "executor_agents": 1,
        "imagegen_capacity": GLOBAL_IMAGEGEN_CAPACITY,
    }


def task_key(task: dict[str, Any]) -> str:
    return (
        f"{task['style']}/{task['page_id']}/{task['action']}/"
        f"{int(task.get('attempt') or 1)}"
    )


def safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def control_paths(project_dir: Path, key: str) -> tuple[Path, Path]:
    stem = safe_key(key)
    claims = project_dir / "state" / "four_by_three_claims"
    receipts = project_dir / "style_jobs" / "results"
    return claims / f"claim_{stem}.json", receipts / f"direct_receipt_{stem}.json"


def task_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Return only scheduler identity; prompts stay in the immutable manifest."""

    return {
        key: item[key]
        for key in ("style", "page_id", "action", "attempt", "task_key")
    }


def resumable_active_manifest(
    project_dir: Path, active: list[dict[str, Any]]
) -> Optional[Tuple[Path, list[dict[str, Any]]]]:
    """Recover a pre-claim controller crash without redispatch or regeneration."""

    if not active:
        return None
    active_keys = {task_key(item) for item in active}
    for key in active_keys:
        claim_path, receipt_path = control_paths(project_dir, key)
        if claim_path.is_file() or receipt_path.is_file():
            return None
    matches: list[tuple[Path, list[dict[str, Any]]]] = []
    manifest_root = project_dir / "state" / "four_by_three_manifests"
    for path in sorted(manifest_root.glob("wave_*.json")):
        value = pc.read_json(path)
        items = [item for item in (value.get("tasks") or []) if isinstance(item, dict)]
        if {str(item.get("task_key")) for item in items} != active_keys:
            continue
        matches.append((path.resolve(), items))
    if len(matches) > 1:
        raise SystemExit("同一组 4x3 active actions 匹配多个 manifest，拒绝猜测")
    return matches[0] if matches else None


def active_control_recovery(
    project_dir: Path, active: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Describe claimed or receipted active work without authorizing regeneration."""

    recovery: list[dict[str, Any]] = []
    for item in active:
        key = task_key(item)
        claim_path, receipt_path = control_paths(project_dir, key)
        if receipt_path.is_file():
            recovery.append(
                {
                    **task_summary({**item, "task_key": key}),
                    "reason": "existing_receipt_must_be_settled",
                    "receipt_path": str(receipt_path.resolve()),
                }
            )
        elif claim_path.is_file():
            recovery.append(
                {
                    **task_summary({**item, "task_key": key}),
                    "reason": "claim_without_receipt_requires_artifact_recovery",
                    "claim_path": str(claim_path.resolve()),
                }
            )
    return recovery


def active_task(
    state: dict[str, Any], style: str, page_id: str, action: str, attempt: int
) -> dict[str, Any]:
    matches = [
        item
        for item in ((state.get("scheduler") or {}).get("active_actions") or [])
        if isinstance(item, dict)
        and item.get("style") == style
        and str(item.get("page_id")) == page_id
        and item.get("action") == action
        and int(item.get("attempt") or 1) == attempt
    ]
    if len(matches) != 1:
        raise SystemExit("4x3 direct task 没有唯一 active_action")
    return matches[0]


def validate_manifest_item(
    state_path: Path, manifest_path: Path, key: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    state, project_dir = require_run(state_path)
    manifest_path = manifest_path.expanduser().resolve()
    pc.require_path_within(
        manifest_path,
        project_dir / "state" / "four_by_three_manifests",
        "4x3 direct manifest",
    )
    manifest, manifest_sha = pc.read_json_with_sha256(manifest_path)
    if manifest.get("four_by_three_control_plane_version") != CONTROL_VERSION:
        raise SystemExit("不支持的 4x3 direct manifest")
    if manifest.get("run_id") != state.get("run_id"):
        raise SystemExit("4x3 direct manifest run_id 错绑")
    if manifest.get("state_path") != str(state_path.resolve()):
        raise SystemExit("4x3 direct manifest state_path 错绑")
    items = manifest.get("tasks") or []
    matches = [item for item in items if isinstance(item, dict) and item.get("task_key") == key]
    if len(matches) != 1:
        raise SystemExit("4x3 direct manifest task_key 不唯一")
    item = matches[0]
    style = pc.normalize_style(item.get("style"))
    page_id = str(item.get("page_id"))
    action = str(item.get("action"))
    attempt = int(item.get("attempt") or 0)
    if style not in STYLES or page_id not in {
        str(state.get("anchor_page_id")),
        *(str(value) for value in (state.get("follower_page_ids") or [])),
    }:
        raise SystemExit("4x3 direct manifest 席位或页码错绑")
    active = active_task(state, style, page_id, action, attempt)
    job_path = Path(str(item.get("generation_job_path"))).expanduser().resolve()
    job_sha = str(item.get("generation_job_sha256") or "")
    if (
        active.get("generation_job_path") != str(job_path)
        or active.get("generation_job_sha256") != job_sha
        or not job_path.is_file()
        or pc.file_sha256(job_path) != job_sha
    ):
        raise SystemExit("4x3 direct generation job 已变化或错绑")
    job = pc.read_json(job_path)
    if job.get("imagegen_input_fingerprint") != item.get("imagegen_input_fingerprint"):
        raise SystemExit("4x3 direct 图片输入指纹已变化")
    item = dict(item)
    item["manifest_sha256"] = manifest_sha
    return state, active, item, project_dir


def _task_manifest_item(
    state_path: Path, state: dict[str, Any], project_dir: Path, task: dict[str, Any]
) -> dict[str, Any]:
    normalized = {
        "style": pc.normalize_style(task.get("style")),
        "page_id": str(task.get("page_id")),
        "action": str(task.get("action")),
        "attempt": int(task.get("attempt") or 1),
    }
    job_path = Path(str(task.get("generation_job_path"))).expanduser().resolve()
    if not job_path.is_file() or pc.file_sha256(job_path) != task.get(
        "generation_job_sha256"
    ):
        raise SystemExit("4x3 direct 派发结果缺少稳定 generation job")
    pc.validate_generation_job_inputs(
        job_path,
        internal_sources=set(),
        expected_task={**normalized, "technical_retry": task.get("technical_retry")},
        state=state,
        project_dir=project_dir,
    )
    job = pc.read_json(job_path)
    prompt = job.get("imagegen_prompt")
    references = job.get("imagegen_referenced_paths")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SystemExit("4x3 direct generation job 缺少最终图片提示")
    if not isinstance(references, list) or not all(
        isinstance(path, str) for path in references
    ):
        raise SystemExit("4x3 direct generation job 缺少规范附件清单")
    key = task_key(normalized)
    claim_path, receipt_path = control_paths(project_dir, key)
    return {
        **normalized,
        "task_key": key,
        "worker_agent_id": task.get("worker_agent_id"),
        "generation_job_path": str(job_path),
        "generation_job_sha256": pc.file_sha256(job_path),
        "imagegen_input_fingerprint": job.get("imagegen_input_fingerprint"),
        "prompt": prompt,
        "referenced_image_paths": references,
        "claim_path": str(claim_path.resolve()),
        "receipt_path": str(receipt_path.resolve()),
        "contains_image_payload": False,
    }


def prepare_next(
    state_path: Path,
    content_contract_dir: Path | None = None,
    *,
    recover_orphans: bool = False,
) -> dict[str, Any]:
    state, project_dir, _content_dir = canonical_content_dir(
        state_path, content_contract_dir
    )
    if state.get("status") == "blocked":
        return {
            "status": "blocked",
            "reason": state.get("terminal_reason") or state.get("failure_reason"),
            "contains_image_payload": False,
        }
    scheduler = state.get("scheduler") or {}
    recovery = [item for item in (scheduler.get("recovery_queue") or []) if isinstance(item, dict)]
    if recovery:
        return {
            "status": "recovery_required",
            "reason": "existing_artifact_must_be_recovered_before_regeneration",
            "recovery_tasks": recovery,
            "contains_image_payload": False,
        }
    active = [item for item in (scheduler.get("active_actions") or []) if isinstance(item, dict)]
    if recover_orphans and active:
        pending = active_control_recovery(project_dir, active)
        if pending:
            return {
                "status": "recovery_required",
                "reason": "existing_claim_or_receipt_must_close_before_dispatch",
                "recovery_tasks": pending,
                "contains_image_payload": False,
            }
    # active_actions are generation graph nodes, not child Agents.  The single
    # executor may keep at most five ImageGen RPCs in flight through the shared
    # registry; the legacy active_child_limit field is compatibility-only here.
    effective_limit = GLOBAL_IMAGEGEN_CAPACITY
    if len(active) > effective_limit:
        raise SystemExit("已有 4x3 active_actions 超过共享 ImageGen 上限，需先结算")
    available = max(0, effective_limit - len(active))
    ready = [
        item
        for item in (scheduler.get("ready_queue") or [])
        if isinstance(item, dict)
        and item.get("style") in STYLES
        and item.get("action") in pc.GENERATION_ACTIONS
    ]
    retry_ready = [
        item
        for item in ready
        if item.get("technical_retry") is True or int(item.get("attempt") or 1) > 1
    ]
    normal_ready = [item for item in ready if item not in retry_ready]
    if active:
        # Failure-path retries never overlap existing RPCs. A retry that
        # exhausts its budget terminalizes the run, so overlapping it with
        # useful work would create cancelled-but-still-running ImageGen calls.
        ready = normal_ready
    elif retry_ready:
        # Serialize only the exceptional retry path. The normal 12-node path
        # keeps its five-way ImageGen ceiling and full rolling concurrency.
        ready = retry_ready[:1]
    if active and not ready:
        resumable = resumable_active_manifest(project_dir, active)
        if resumable is not None:
            manifest_path, items = resumable
            return {
                "status": "resuming_preclaim",
                "manifest_path": str(manifest_path),
                "tasks": [task_summary(item) for item in items],
                "active_count": len(active),
                "contains_image_payload": False,
            }
    started: list[dict[str, Any]] = []
    wave_id = None
    if ready and available:
        requested = [
            {
                "style": item["style"],
                "page_id": str(item["page_id"]),
                "action": item["action"],
                "attempt": int(item.get("attempt") or 1),
            }
            for item in ready[:available]
        ]
        agent_map = {task_key(item): EXECUTOR_AGENT_ID for item in requested}
        backpressure_reason = (
            "shared_imagegen_capacity"
            if len(ready) > available
            else None
        )
        dispatched = capture(
            pc.command_record_dispatch_wave,
            state=str(state_path),
            styles=None,
            tasks_json=json.dumps(requested, ensure_ascii=False),
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp=None,
            agent_map_json=json.dumps(agent_map, ensure_ascii=False),
            backpressure_reason=backpressure_reason,
        )
        started = dispatched.get("tasks") or []
        wave_id = dispatched.get("wave_id")
        state = pc.read_json(state_path)
    if started:
        items = [
            _task_manifest_item(state_path, state, project_dir, item)
            for item in started
        ]
        manifest = {
            "four_by_three_control_plane_version": CONTROL_VERSION,
            "run_id": state.get("run_id"),
            "state_path": str(state_path.resolve()),
            "wave_id": wave_id,
            "shared_imagegen_capacity": GLOBAL_IMAGEGEN_CAPACITY,
            "executor_agents": 1,
            "executor_agent_id": EXECUTOR_AGENT_ID,
            "tasks": items,
            "created_at": pc.now_iso(),
            "contains_image_payload": False,
        }
        manifest_path = (
            project_dir
            / "state"
            / "four_by_three_manifests"
            / f"wave_{safe_key(str(wave_id or pc.now_iso()))}.json"
        )
        pc.write_idempotent(manifest_path, manifest)
        return {
            "status": "started",
            "manifest_path": str(manifest_path.resolve()),
            "tasks": [task_summary(item) for item in items],
            "active_count": len(((state.get("scheduler") or {}).get("active_actions") or [])),
            "executor_agents": 1,
            "imagegen_capacity": GLOBAL_IMAGEGEN_CAPACITY,
            "contains_image_payload": False,
        }
    state = pc.read_json(state_path)
    scheduler = state.get("scheduler") or {}
    active_count = len(scheduler.get("active_actions") or [])
    ready_count = len(scheduler.get("ready_queue") or [])
    page_ids = [str(state.get("anchor_page_id")), *(str(value) for value in (state.get("follower_page_ids") or []))]
    completed = 0
    for style in STYLES:
        pages = (((state.get("styles") or {}).get(style) or {}).get("pages") or {})
        for page_id in page_ids:
            record = pages.get(page_id)
            if not isinstance(record, dict):
                continue
            source = record.get("selected_source")
            if (
                record.get("file_validated_at")
                and isinstance(source, str)
                and Path(source).is_file()
            ):
                completed += 1
    return {
        "status": "complete" if completed == 12 else "waiting" if active_count else "idle",
        "completed": completed,
        "active_count": active_count,
        "ready_count": ready_count,
        "contains_image_payload": False,
    }


def claim(
    state_path: Path, manifest_path: Path, key: str, wait_seconds: float
) -> dict[str, Any]:
    state, active, item, project_dir = validate_manifest_item(
        state_path, manifest_path, key
    )
    claim_path, receipt_path = control_paths(project_dir, key)
    if receipt_path.is_file():
        return {"status": "receipt_exists", "receipt_path": str(receipt_path)}
    if claim_path.is_file():
        raise SystemExit("4x3 direct task 已有 claim；拒绝不明重入或重复生图")
    deadline = time.monotonic() + max(0.0, wait_seconds)
    lease_task = {
        "style": item["style"],
        "page_id": item["page_id"],
        "action": item["action"],
        "attempt": item["attempt"],
        "lease_kind": "four_by_three_direct_v1",
        "worker_session_id": active.get("worker_agent_id"),
        "worker_ticket_sha256": item["manifest_sha256"],
    }
    while True:
        acquired, _deferred, lease_ids, _remaining = pc.acquire_shared_imagegen_slots(
            state_path,
            state,
            [lease_task],
            timestamp=pc.now_iso(),
            capacity_limit=GLOBAL_IMAGEGEN_CAPACITY,
        )
        if acquired:
            break
        if time.monotonic() >= deadline:
            return {"status": "slot_wait_timeout", "task_key": key}
        time.sleep(0.5)
    lease_id = lease_ids[task_key(lease_task)]
    claim_value = {
        "four_by_three_claim_version": CONTROL_VERSION,
        "task_key": key,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": item["manifest_sha256"],
        "generation_job_path": item["generation_job_path"],
        "generation_job_sha256": item["generation_job_sha256"],
        "imagegen_input_fingerprint": item["imagegen_input_fingerprint"],
        "worker_agent_id": active.get("worker_agent_id"),
        "lease_id": lease_id,
        "claimed_at": pc.now_iso(),
        "contains_image_payload": False,
    }
    try:
        pc.write_idempotent(claim_path, claim_value)
    except BaseException:
        pc.release_shared_imagegen_slots(state_path, state, [lease_id])
        raise
    return {
        "status": "claimed",
        "task_key": key,
        "claim_path": str(claim_path),
        "receipt_path": str(receipt_path),
        "lease_id": lease_id,
    }


def task_input(state_path: Path, manifest_path: Path, key: str) -> dict[str, Any]:
    """Read one exact prompt/input after the compact scheduler handoff."""

    _state, _active, item, _project_dir = validate_manifest_item(
        state_path, manifest_path, key
    )
    return {
        "style": item["style"],
        "page_id": item["page_id"],
        "action": item["action"],
        "attempt": item["attempt"],
        "task_key": key,
        "prompt": item["prompt"],
        "referenced_image_paths": item["referenced_image_paths"],
        "imagegen_input_fingerprint": item["imagegen_input_fingerprint"],
        "contains_image_payload": False,
    }


def release(state_path: Path, manifest_path: Path, key: str) -> dict[str, Any]:
    state, _active, _item, project_dir = validate_manifest_item(
        state_path, manifest_path, key
    )
    claim_path, _receipt_path = control_paths(project_dir, key)
    if not claim_path.is_file():
        return {"status": "already_released", "released": 0}
    claim_value = pc.read_json(claim_path)
    released = pc.release_shared_imagegen_slots(
        state_path, state, [str(claim_value.get("lease_id") or "")]
    )
    return {"status": "released", "released": released}


def write_receipt(
    state_path: Path, manifest_path: Path, key: str, result: dict[str, Any]
) -> dict[str, Any]:
    state, active, item, project_dir = validate_manifest_item(
        state_path, manifest_path, key
    )
    claim_path, receipt_path = control_paths(project_dir, key)
    if not claim_path.is_file():
        raise SystemExit("4x3 direct receipt 缺少 claim")
    claim_value = pc.read_json(claim_path)
    if claim_value.get("manifest_sha256") != item["manifest_sha256"]:
        raise SystemExit("4x3 direct claim 与 manifest 错绑")
    # Reuse the Fast8 mainline's canonical output_hint parser.  ImageGen may
    # return prose containing one exact exec-*.png path rather than a bare
    # path; treating that prose as a filesystem path loses an otherwise valid
    # artifact and creates an avoidable recovery queue.
    result = pc.normalize_fast8_artifact_fields(result)
    started_at = str(result.get("tool_started_at") or pc.now_iso())
    finished_at = str(result.get("tool_finished_at") or pc.now_iso())
    saved = result.get("savedPath")
    error = result.get("error")
    if error in {None, ""}:
        if not isinstance(saved, str) or not saved:
            error = "artifact_handoff_unresolved"
        else:
            path = Path(saved).expanduser().resolve()
            pc.require_path_within(path, pc.GENERATED_IMAGES_ROOT, "4x3 ImageGen 输出")
            if not path.is_file():
                error = "artifact_handoff_unresolved"
            else:
                pc.png_metadata(path)
                saved = str(path)
    worker_id = str(active.get("worker_agent_id") or item.get("worker_agent_id") or "")
    receipt = {
        "four_by_three_direct_receipt_version": CONTROL_VERSION,
        "style": item["style"],
        "page_id": item["page_id"],
        "action": item["action"],
        "attempt": item["attempt"],
        "worker_agent_id": worker_id,
        "agent_action_started_at": started_at,
        "agent_action_finished_at": finished_at,
        "tool_call_id": str(result.get("tool_call_id") or f"four_by_three_{safe_key(key)}"),
        "savedPath": saved if error in {None, ""} else None,
        "tool_started_at": started_at,
        "tool_finished_at": finished_at,
        "tool_status": result.get("tool_status") or (
            "failed" if error not in {None, ""} else "completed"
        ),
        "failure_class": result.get("failure_class") if error not in {None, ""} else None,
        "tool_error_code": result.get("tool_error_code") if error not in {None, ""} else None,
        "error": error,
        "manifest_sha256": item["manifest_sha256"],
        "generation_job_sha256": item["generation_job_sha256"],
        "contains_image_payload": False,
    }
    pc.write_idempotent(receipt_path, receipt)
    released = pc.release_shared_imagegen_slots(
        state_path, state, [str(claim_value.get("lease_id") or "")]
    )
    return {
        "status": "receipt_written",
        "receipt_path": str(receipt_path),
        "error": error,
        "released": released,
    }


def settle_receipt(
    state_path: Path,
    receipt_path: Path,
    content_contract_dir: Path | None = None,
) -> dict[str, Any]:
    state, project_dir, content_contract_dir = canonical_content_dir(
        state_path, content_contract_dir
    )
    receipt_path = receipt_path.expanduser().resolve()
    pc.require_path_within(
        receipt_path, project_dir / "style_jobs" / "results", "4x3 direct receipt"
    )
    receipt = pc.read_json(receipt_path)
    allowed = {
        "four_by_three_direct_receipt_version", "style", "page_id", "action",
        "attempt", "worker_agent_id", "agent_action_started_at",
        "agent_action_finished_at", "tool_call_id", "savedPath", "tool_started_at",
        "tool_finished_at", "error", "manifest_sha256", "generation_job_sha256",
        "tool_status", "failure_class", "tool_error_code", "contains_image_payload",
    }
    if set(receipt) - allowed or receipt.get("contains_image_payload") is not False:
        raise SystemExit("4x3 direct receipt 含未授权字段")
    result = {key: receipt.get(key) for key in (
        "style", "page_id", "action", "attempt", "worker_agent_id",
        "agent_action_started_at", "agent_action_finished_at", "tool_call_id",
        "savedPath", "tool_started_at", "tool_finished_at", "error",
        "tool_status", "failure_class", "tool_error_code",
    )}
    results_path = receipt_path.with_name(receipt_path.stem + ".settle.json")
    pc.write_idempotent(results_path, {"results": [result]})
    settled = capture(
        pc.command_settle_wave,
        state=str(state_path),
        results_file=str(results_path),
        expected_styles=str(receipt["style"]),
        timestamp=None,
    )
    if (
        receipt.get("action") in {"generate_anchor", "repair_anchor"}
        and receipt.get("error") in {None, ""}
    ):
        capture(
            pc.command_prepare_fast_followers,
            project_dir=str(project_dir),
            state=str(state_path),
            content_contract_dir=str(content_contract_dir.resolve()),
            styles=str(receipt["style"]),
        )
    return {
        "status": "settled",
        "task_key": task_key(receipt),
        "settle": settled,
        "contains_image_payload": False,
    }


def render_action(
    state_path: Path, content_contract_dir: Path | None = None
) -> str:
    _state_value, _project_dir, _content_dir = canonical_content_dir(
        state_path, content_contract_dir
    )
    script = shlex.quote(str(SCRIPT_PATH))
    state = shlex.quote(str(state_path.resolve()))
    # One mechanical expression.  State transitions are serialized by the
    # coordinator; only ImageGen RPCs run concurrently.
    return f'''(async () => {{
  const sh = value => "'" + String(value).replace(/'/g, "'\\\"'\\\"'") + "'";
  const run = async cmd => {{
    const out = await tools.exec_command({{cmd, yield_time_ms:30000, max_output_tokens:4000}});
    if (out.session_id) {{
      let current = out;
      while (current.session_id) current = await tools.write_stdin({{session_id:current.session_id, chars:"", yield_time_ms:30000, max_output_tokens:4000}});
      out.output = current.output;
      out.exit_code = current.exit_code;
    }}
    if (out.exit_code !== 0 && out.exit_code !== undefined) throw new Error(out.output || "command failed");
    return JSON.parse((out.output || "{{}}").trim());
  }};
  const base = {json.dumps(f"{sys.executable} {script} ")};
  const stateArg = {json.dumps(f" --state {state}")};
  const findPath = value => {{
    const seen = new Set();
    const walk = v => {{
      if (v == null || seen.has(v)) return null;
      if (typeof v === "string") return v.includes("/exec-") && v.includes(".png") ? v : null;
      if (typeof v !== "object") return null;
      seen.add(v);
      for (const key of ["savedPath", "saved_path", "output_hint", "path"]) {{ if (key in v) {{ const p=walk(v[key]); if (p) return p; }} }}
      for (const [key, child] of Object.entries(v)) {{ if (!['data','image_url'].includes(key)) {{ const p=walk(child); if (p) return p; }} }}
      return null;
    }};
    return walk(value);
  }};
  const running = new Map();
  let fatalError = null;
  const launch = (manifestPath, summary) => {{
    const promise = (async () => {{
      const item = await run(base + "task-input" + stateArg + " --manifest " + sh(manifestPath) + " --task-key " + sh(summary.task_key));
      const claimCmd = base + "claim" + stateArg + " --manifest " + sh(manifestPath) + " --task-key " + sh(item.task_key) + " --wait-seconds {CLAIM_WAIT_SECONDS}";
      const claim = await run(claimCmd);
      if (claim.status === "receipt_exists") return {{item, receipt_path:claim.receipt_path}};
      if (claim.status !== "claimed") throw new Error("ImageGen slot wait timed out");
      const started = new Date().toISOString();
      let result;
      try {{
        const input = {{prompt:item.prompt}};
        if (item.referenced_image_paths.length) input.referenced_image_paths = item.referenced_image_paths;
        const generated = await tools.image_gen__imagegen(input);
        result = {{savedPath:findPath(generated), tool_started_at:started, tool_finished_at:new Date().toISOString(), error:null, tool_status:"completed", failure_class:null, tool_error_code:null}};
      }} catch (error) {{
        const errorText = String((error && (error.message || error.code || error.name)) || error || "unknown_imagegen_error").replace(/\s+/g, " ").slice(0, 240);
        result = {{savedPath:null, tool_started_at:started, tool_finished_at:new Date().toISOString(), error:"imagegen_backend_failed", tool_status:"failed", failure_class:"backend_failed", tool_error_code:errorText}};
      }}
      const receiptCmd = base + "receipt" + stateArg + " --manifest " + sh(manifestPath) + " --task-key " + sh(item.task_key) + " --result-json " + sh(JSON.stringify(result));
      const receipt = await run(receiptCmd);
      return {{item, receipt_path:receipt.receipt_path}};
    }})().finally(async () => {{
      try {{ await run(base + "release" + stateArg + " --manifest " + sh(manifestPath) + " --task-key " + sh(summary.task_key)); }} catch (_) {{}}
    }});
    running.set(summary.task_key, promise);
  }};
  while (true) {{
    let prepared = {{status:"draining_after_error"}};
    let stopResult = null;
    if (!fatalError) {{
      try {{
        prepared = await run(base + "prepare-next" + stateArg + (running.size === 0 ? " --recover-orphans" : ""));
      }} catch (error) {{
        fatalError = error;
      }}
    }}
    if (!fatalError && (prepared.status === "recovery_required" || prepared.status === "blocked")) stopResult = prepared;
    if (!fatalError && !stopResult && (prepared.status === "started" || prepared.status === "resuming_preclaim")) for (const item of prepared.tasks) if (!running.has(item.task_key)) launch(prepared.manifest_path, item);
    if (!running.size) {{
      if (fatalError) throw fatalError;
      if (stopResult) {{ text(JSON.stringify(stopResult)); return; }}
      if (prepared.status === "complete") {{ text(JSON.stringify(prepared)); return; }}
      throw new Error("4x3 direct runner has unfinished state but no runnable task");
    }}
    const completed = await Promise.race([...running.entries()].map(async ([key, promise]) => {{
      try {{ return [key, await promise, null]; }}
      catch (error) {{ return [key, null, error]; }}
    }}));
    running.delete(completed[0]);
    if (completed[2]) {{ fatalError = completed[2]; continue; }}
    await run(base + "settle" + stateArg + " --receipt " + sh(completed[1].receipt_path));
  }}
}})()'''


def lean_finalize(state_path: Path) -> dict[str, Any]:
    """Finalize twelve settled Fast 4x3 candidates without adding a Judge."""

    state, project_dir, paths = canonical_paths(state_path)
    if state.get("status") == "blocked":
        raise SystemExit("blocked 4x3 运行不得 finalize")
    if state.get("status") == "completed":
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                pc.command_validate_state(
                    argparse.Namespace(state=str(state_path), complete=True)
                )
        except SystemExit as exc:
            raise SystemExit(
                "既有 4x3 完整状态审计失败：" + captured.getvalue().strip()
            ) from exc
        return {
            "status": "already_completed",
            "state": str(state_path),
            "overview": (state.get("overview") or {}).get("final_path"),
            "handoff": str(project_dir / "state" / "handoff.json"),
            "contains_image_payload": False,
        }
    scheduler = state.get("scheduler") or {}
    nonempty = [
        name
        for name in ("active_actions", "ready_queue", "recovery_queue")
        if scheduler.get(name)
    ]
    if nonempty:
        raise SystemExit("lean-finalize 前调度队列必须为空：" + ", ".join(nonempty))
    page_ids = [
        str(state.get("anchor_page_id")),
        *(str(value) for value in (state.get("follower_page_ids") or [])),
    ]
    if len(page_ids) != 3 or len(set(page_ids)) != 3:
        raise SystemExit("lean-finalize 必须绑定一个锚点页和两个不同跟随页")
    finalized: dict[str, str] = {}
    gate_reason = {
        "content_gate": {
            "status": "not_applicable",
            "reason": "Fast 4x3 selection-stage candidate; no blocking visual QA claimed",
        },
        "spatial_gate": {
            "status": "not_applicable",
            "reason": "Fast 4x3 selection-stage candidate; no blocking visual QA claimed",
        },
        "craft_gate": {
            "status": "not_applicable",
            "reason": "Fast 4x3 selection-stage candidate; no blocking visual QA claimed",
        },
    }
    for style in STYLES:
        for page_id in page_ids:
            state = pc.read_json(state_path)
            record = pc.page_record(state, style, page_id)
            source_value = record.get("selected_source")
            if (
                not record.get("file_validated_at")
                or not isinstance(source_value, str)
                or not Path(source_value).expanduser().is_file()
            ):
                raise SystemExit(f"style_{style}/{page_id} 缺少已结算并校验的候选")
            source = Path(source_value).expanduser().resolve()
            _width, _height, size_bytes, source_sha = pc.png_metadata(source)
            target = pc.origin_image_target(project_dir, style, page_id).resolve()
            pc.atomic_copy_candidate(source, target)
            finalized[f"{style}/{page_id}"] = str(target)
            if record.get("status") == "candidate_ready":
                if record.get("final_path") != str(target):
                    raise SystemExit(
                        f"style_{style}/{page_id} 既有 final_path 与规范路径不一致"
                    )
                continue
            event_at = pc.now_iso()
            pc.run_record_event_silently(
                state=str(state_path),
                event="overview_qa",
                style=style,
                page_id=page_id,
                action=None,
                timestamp=event_at,
                details_json=json.dumps(
                    {"qa_stage": "filesystem", "qa_scope": "filesystem_only"},
                    ensure_ascii=False,
                ),
            )
            pc.run_record_event_silently(
                state=str(state_path),
                event="page_completed",
                style=style,
                page_id=page_id,
                action=None,
                timestamp=event_at,
                details_json=json.dumps(
                    {
                        "completion_status": "candidate_ready",
                        "final_path": str(target),
                        "source_sha256": source_sha,
                        "source_size_bytes": size_bytes,
                        "qa_stage": "filesystem",
                        "qa_scope": "filesystem_only",
                        **gate_reason,
                    },
                    ensure_ascii=False,
                ),
            )
    overview_path = paths["overview"]
    matrix_python = resolve_overview_python(pc.read_json(state_path))
    matrix = subprocess.run(
        [
            str(matrix_python),
            str(SCRIPT_PATH.parent / "build_style_matrix.py"),
            "--project-dir",
            str(project_dir),
            "--pages",
            ",".join(page_ids),
            "--styles",
            ",".join(STYLES),
            "--output",
            str(overview_path),
            "--source-state",
            str(state_path),
            "--cell-width",
            "1280",
            "--header-height",
            "120",
            "--row-label-width",
            "180",
            "--gap",
            "24",
            "--ratio-tolerance",
            "0.02",
        ],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if matrix.returncode != 0 or not overview_path.is_file():
        raise SystemExit(
            "Fast 4x3 正式总览生成失败："
            + (matrix.stderr.strip() or matrix.stdout.strip() or "unknown error")
        )
    overview_details = {
        "output_path": str(overview_path),
        "candidate_count": 12,
        "layout": "4x3",
    }
    state = pc.read_json(state_path)
    previous_overviews = [
        event
        for event in (state.get("events") or [])
        if isinstance(event, dict) and event.get("name") == "formal_overview_completed"
    ]
    if previous_overviews:
        if (previous_overviews[-1].get("details") or {}) != overview_details:
            raise SystemExit("既有 formal_overview_completed 与当前 4x3 总览不一致")
    else:
        pc.run_record_event_silently(
            state=str(state_path),
            event="formal_overview_completed",
            style=None,
            page_id=None,
            action=None,
            timestamp=pc.now_iso(),
            details_json=json.dumps(overview_details, ensure_ascii=False),
        )
    completion = pc.run_record_event_silently(
        state=str(state_path),
        event="process_completed",
        style=None,
        page_id=None,
        action=None,
        timestamp=pc.now_iso(),
        details_json=json.dumps(
            {
                "formal_candidate_count": 12,
                "overview_layout": "4x3",
                "unresolved_issues": [],
            },
            ensure_ascii=False,
        ),
    )
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            pc.command_validate_state(
                argparse.Namespace(state=str(state_path), complete=True)
            )
    except SystemExit as exc:
        raise SystemExit(
            "lean-finalize 完整状态审计失败：" + captured.getvalue().strip()
        ) from exc
    validation = json.loads(captured.getvalue())
    return {
        "status": "completed",
        "state": str(state_path),
        "overview": str(overview_path),
        "handoff": str(project_dir / "state" / "handoff.json"),
        "formal_candidates": finalized,
        "validate_state": validation.get("status"),
        "monitoring": completion.get("monitoring"),
        "contains_image_payload": False,
    }


def terminalize(state_path: Path, reason: str) -> dict[str, Any]:
    """Close one blocked 4x3 state and release every claim-backed lease."""

    state, project_dir = require_run(state_path)
    if state.get("status") == "completed":
        raise SystemExit("已完成的 4x3 运行不得改写为 blocked")
    already_blocked = state.get("status") == "blocked"
    blocked_tasks = []
    page_ids = [
        str(state.get("anchor_page_id")),
        *(str(value) for value in (state.get("follower_page_ids") or [])),
    ]
    for style in STYLES:
        pages = (((state.get("styles") or {}).get(style) or {}).get("pages") or {})
        for page_id in page_ids:
            record = pages.get(page_id)
            if isinstance(record, dict) and record.get("status") == "blocked":
                blocked_tasks.append(
                    {
                        "style": style,
                        "page_id": page_id,
                        "reason": record.get("failure_reason") or reason,
                    }
                )
    if already_blocked:
        scheduler = state.setdefault("scheduler", {})
        lease_ids = [
            str(item.get("global_imagegen_lease_id"))
            for item in (scheduler.get("active_actions") or [])
            if isinstance(item, dict)
            and isinstance(item.get("global_imagegen_lease_id"), str)
        ]
        scheduler["active_actions"] = []
        scheduler["ready_queue"] = []
        scheduler["recovery_queue"] = []
        scheduler["phase"] = "terminal"
    else:
        lease_ids = pc.terminalize_blocked_run_state(
            state,
            timestamp=pc.now_iso(),
            reason=reason,
            blocked_tasks=blocked_tasks,
        )
    claims_dir = project_dir / "state" / "four_by_three_claims"
    for path in sorted(claims_dir.glob("claim_*.json")):
        value = pc.read_json(path)
        lease_id = value.get("lease_id")
        if isinstance(lease_id, str) and lease_id:
            lease_ids.append(lease_id)
    pc.atomic_write_json(state_path, state)
    released = pc.release_shared_imagegen_slots(
        state_path, state, list(dict.fromkeys(lease_ids))
    )
    return {
        "status": "already_blocked" if already_blocked else "blocked",
        "reason": reason,
        "blocked_tasks": blocked_tasks,
        "released_leases": released,
        "contains_image_payload": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    director_prepare = sub.add_parser("prepare-directors")
    director_prepare.add_argument("--state", required=True)
    prepare = sub.add_parser("prepare-next")
    prepare.add_argument("--state", required=True)
    prepare.add_argument("--recover-orphans", action="store_true")
    claim_parser = sub.add_parser("claim")
    claim_parser.add_argument("--state", required=True)
    claim_parser.add_argument("--manifest", required=True)
    claim_parser.add_argument("--task-key", required=True)
    claim_parser.add_argument("--wait-seconds", type=float, default=0)
    task_parser = sub.add_parser("task-input")
    task_parser.add_argument("--state", required=True)
    task_parser.add_argument("--manifest", required=True)
    task_parser.add_argument("--task-key", required=True)
    release_parser = sub.add_parser("release")
    release_parser.add_argument("--state", required=True)
    release_parser.add_argument("--manifest", required=True)
    release_parser.add_argument("--task-key", required=True)
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--state", required=True)
    receipt.add_argument("--manifest", required=True)
    receipt.add_argument("--task-key", required=True)
    receipt.add_argument("--result-json", required=True)
    settle = sub.add_parser("settle")
    settle.add_argument("--state", required=True)
    settle.add_argument("--receipt", required=True)
    action = sub.add_parser("render-action")
    action.add_argument("--state", required=True)
    finalize = sub.add_parser("lean-finalize")
    finalize.add_argument("--state", required=True)
    stop = sub.add_parser("terminalize")
    stop.add_argument("--state", required=True)
    stop.add_argument("--reason", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    state_path = Path(args.state).resolve()
    if args.command == "prepare-directors":
        result = prepare_director_inputs(state_path)
        emit(result)
        if result.get("status") != "ok":
            raise SystemExit(1)
    elif args.command == "prepare-next":
        emit(prepare_next(state_path, recover_orphans=args.recover_orphans))
    elif args.command == "claim":
        emit(claim(state_path, Path(args.manifest), args.task_key, args.wait_seconds))
    elif args.command == "task-input":
        emit(task_input(state_path, Path(args.manifest), args.task_key))
    elif args.command == "release":
        emit(release(state_path, Path(args.manifest), args.task_key))
    elif args.command == "receipt":
        raw = json.loads(args.result_json)
        if not isinstance(raw, dict):
            raise SystemExit("--result-json 必须是对象")
        emit(write_receipt(state_path, Path(args.manifest), args.task_key, raw))
    elif args.command == "settle":
        emit(settle_receipt(state_path, Path(args.receipt)))
    elif args.command == "render-action":
        print(render_action(state_path))
    elif args.command == "lean-finalize":
        emit(lean_finalize(state_path))
    elif args.command == "terminalize":
        emit(terminalize(state_path, args.reason))


if __name__ == "__main__":
    main()
