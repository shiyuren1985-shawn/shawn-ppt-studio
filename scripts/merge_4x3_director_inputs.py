#!/usr/bin/env python3
"""Deterministically merge the three 4x3 director outputs.

The three model directors own facts, authorized assets, and visual judgment in
separate files.  This script owns only schema validation, fixed spatial fields,
the four-field creative merge, and page-local asset attachment.  It never
guesses facts, authorization, creative enums, or style routes.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import pipeline_control as pc


ROOT = Path(__file__).resolve().parent
FAST_MERGE_PATH = ROOT / "merge_fast8_director_inputs.py"
SPEC = importlib.util.spec_from_file_location("merge_fast8_for_4x3", FAST_MERGE_PATH)
assert SPEC and SPEC.loader
fast_merge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fast_merge)

STYLES = tuple("ABCD")
IMAGEGEN_RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def require_exact_path(path: Path, expected: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    expected = expected.expanduser().resolve()
    if resolved != expected:
        raise SystemExit(f"{label} 必须使用当前工程规范路径：{expected}")
    return resolved


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"{label} 不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} JSON 无法解析：{path}：{exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} 根节点必须是对象")
    return value


def exact_page_order(value: Any, expected: list[str], label: str) -> list[str]:
    if not isinstance(value, list) or [str(item) for item in value] != expected:
        raise SystemExit(f"{label}.page_order 必须逐字等于 {expected}")
    return expected


def validate_asset(item: Any, page_id: str, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise SystemExit(f"assets.pages.{page_id}[{index}] 必须是对象")
    path_value = item.get("path")
    role = item.get("role")
    if not isinstance(path_value, str) or not Path(path_value).expanduser().is_absolute():
        raise SystemExit(f"assets.pages.{page_id}[{index}].path 必须是绝对路径")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"assets.pages.{page_id}[{index}] 文件不存在：{path}")
    if path.suffix.lower() not in IMAGEGEN_RASTER_SUFFIXES:
        raise SystemExit(
            f"assets.pages.{page_id}[{index}] 不是 ImageGen 支持的位图：{path}；"
            "PDF/PPTX 等规划证据只能作为 supporting source，不得进入逐页图片资产"
        )
    if not isinstance(role, str) or not role.strip():
        raise SystemExit(f"assets.pages.{page_id}[{index}].role 必须是非空字符串")
    normalized = dict(item)
    normalized["path"] = str(path)
    normalized["role"] = role.strip()
    # This file is a director-authored asset bundle, not a historical source
    # snapshot.  Prefer its documented route and remove conflicting aliases so
    # a harmless duplicated field cannot force a second Director pass.
    if "style_slots" in normalized:
        normalized.pop("styles", None)
        normalized.pop("used_by", None)
    return normalized


def normalize_page_assets(value: Any, page_id: str) -> list[Any]:
    """Accept the one harmless director envelope without weakening asset gates."""

    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        candidates = [
            value.get(key)
            for key in ("assets", "required_assets")
            if key in value
        ]
        if len(candidates) == 1 and isinstance(candidates[0], list):
            return candidates[0]
    raise SystemExit(f"page {page_id} 的逐页图片资产必须为数组")


def validate_layout_portfolio(value: Any, anchor_page_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit("visual_system.layout_portfolio 必须是对象")
    value = dict(value)
    if (
        "layout_portfolio_contract_version" not in value
        and value.get("layout_portfolio_version") is not None
    ):
        value["layout_portfolio_contract_version"] = value.pop(
            "layout_portfolio_version"
        )
    if not isinstance(value.get("director_rationale"), str) or not value[
        "director_rationale"
    ].strip():
        value["director_rationale"] = (
            "四个视觉家族在关系表达与工艺上保持区分，并按三页各自关系适配。"
        )
    expected_versions = {
        "layout_portfolio_contract_version": pc.CURRENT_4X3_LAYOUT_VERSION,
        "art_direction_contract_version": pc.ART_DIRECTION_CONTRACT_VERSION,
        "style_family_portfolio_version": pc.CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION,
        "visual_activity_portfolio_version": pc.CURRENT_VISUAL_ACTIVITY_PORTFOLIO_VERSION,
        "spatial_topology_portfolio_version": pc.CURRENT_SPATIAL_TOPOLOGY_PORTFOLIO_VERSION,
    }
    for field, expected in expected_versions.items():
        if value.get(field) != expected:
            raise SystemExit(f"layout_portfolio.{field} 必须为 {expected}")
    if str(value.get("page_id")) != anchor_page_id:
        raise SystemExit("layout_portfolio.page_id 必须等于 anchor_page_id")
    styles = value.get("styles")
    if not isinstance(styles, dict) or set(styles) != set(STYLES):
        raise SystemExit("layout_portfolio.styles 必须且只能包含 A-D")
    return value


def merge_bundle(
    *,
    state_path: Path,
    content_bundle_path: Path,
    assets_bundle_path: Path,
    visual_system_path: Path,
    content_output_dir: Path,
    layout_output_path: Path,
) -> dict[str, Any]:
    state_path = state_path.expanduser().resolve()
    state = pc.read_json(state_path)
    if state.get("run_mode") not in {pc.FAST_4X3_MODE, pc.STRICT_4X3_MODE}:
        raise SystemExit("4x3 director merge 只适用于 fast/full 4x3")
    project_dir = pc.project_dir_for_state(state_path, state)
    require_exact_path(
        state_path,
        project_dir / "state" / "style_run_state.json",
        "4x3 state",
    )
    director_root = project_dir / "state" / "director_inputs"
    content_bundle_path = require_exact_path(
        content_bundle_path,
        director_root / "content_bundle.json",
        "content_bundle",
    )
    assets_bundle_path = require_exact_path(
        assets_bundle_path,
        director_root / "required_assets_by_page.json",
        "required_assets_by_page",
    )
    visual_system_path = require_exact_path(
        visual_system_path,
        director_root / "visual_system.json",
        "visual_system",
    )
    content_output_dir = require_exact_path(
        content_output_dir,
        project_dir / "content_contracts",
        "content contracts 输出目录",
    )
    layout_output_path = require_exact_path(
        layout_output_path,
        project_dir / "state" / "layout_portfolio.json",
        "layout portfolio 输出",
    )
    expected_pages = [
        str(state.get("anchor_page_id")),
        *(str(item) for item in (state.get("follower_page_ids") or [])),
    ]
    if len(expected_pages) != 3 or len(set(expected_pages)) != 3:
        raise SystemExit("正式 state 必须包含一个锚点页和两个不同跟随页")

    canonical_titles: dict[str, str] = {}
    authoritative_snapshot = director_root / "authoritative_snapshot_source.json"
    if authoritative_snapshot.is_file():
        snapshot = read_object(authoritative_snapshot, "authoritative_snapshot_source")
        if (
            snapshot.get("four_by_three_snapshot_source_version") != 1
            or snapshot.get("page_order") != expected_pages
            or not isinstance(snapshot.get("pages"), dict)
        ):
            raise SystemExit("authoritative_snapshot_source 与 state 三页范围不一致")
        for page_id in expected_pages:
            source_page = snapshot["pages"].get(page_id)
            title = source_page.get("canonical_title") if isinstance(source_page, dict) else None
            if isinstance(title, str) and title.strip():
                canonical_titles[page_id] = title.strip()

    content_bundle = read_object(content_bundle_path, "content_bundle")
    assets_bundle = read_object(assets_bundle_path, "assets_bundle")
    visual_system = read_object(visual_system_path, "visual_system")
    if content_bundle.get("four_by_three_content_bundle_version") != 1:
        raise SystemExit("four_by_three_content_bundle_version 必须为 1")
    if assets_bundle.get("four_by_three_assets_bundle_version") != 1:
        raise SystemExit("four_by_three_assets_bundle_version 必须为 1")
    if visual_system.get("four_by_three_visual_system_version") != 1:
        raise SystemExit("four_by_three_visual_system_version 必须为 1")
    for value, label in (
        (content_bundle, "content_bundle"),
        (assets_bundle, "assets_bundle"),
        (visual_system, "visual_system"),
    ):
        exact_page_order(value.get("page_order"), expected_pages, label)
    if str(visual_system.get("anchor_page_id")) != expected_pages[0]:
        raise SystemExit("visual_system.anchor_page_id 与 state 不一致")

    raw_pages = content_bundle.get("pages")
    asset_pages = assets_bundle.get("pages")
    intents = visual_system.get("creative_intents")
    for value, label in (
        (raw_pages, "content_bundle.pages"),
        (asset_pages, "assets_bundle.pages"),
        (intents, "visual_system.creative_intents"),
    ):
        if not isinstance(value, dict) or set(map(str, value)) != set(expected_pages):
            raise SystemExit(f"{label} 必须且只能包含三张正式页面")

    outputs: dict[str, str] = {}
    for page_id in expected_pages:
        raw = raw_pages[page_id]
        intent = intents[page_id]
        if not isinstance(raw, dict) or not isinstance(intent, dict):
            raise SystemExit(f"page {page_id} 的内容与视觉意图必须是对象")
        raw = dict(raw)
        intent = dict(intent)
        if "creative_intent_contract_version" not in intent:
            intent["creative_intent_contract_version"] = 1
        canonical_title = canonical_titles.get(page_id)
        if canonical_title:
            director_title = raw.get("title")
            raw["title"] = canonical_title
            if isinstance(director_title, str) and director_title != canonical_title:
                display_required = raw.get("display_required")
                if isinstance(display_required, list):
                    raw["display_required"] = [
                        canonical_title if item == director_title else item
                        for item in display_required
                    ]
        density = raw.get("information_density_target")
        if isinstance(density, str):
            compact_density = density.strip().lower()
            for prefix, canonical_density in (
                ("低", "low"),
                ("中", "medium"),
                ("高", "high"),
            ):
                if compact_density.startswith(prefix):
                    raw["information_density_target"] = canonical_density
                    break
        if str(raw.get("page_id")) != page_id or str(intent.get("page_id")) != page_id:
            raise SystemExit(f"page {page_id} 的导演输出页码不一致")
        story = raw.get("flexible_story")
        if not isinstance(story, str) or not story.strip():
            raise SystemExit(f"page {page_id} 必须显式填写 flexible_story")
        if len(story.strip()) > pc.FLEXIBLE_STORY_LIMIT:
            raise SystemExit(f"page {page_id}.flexible_story 超过 {pc.FLEXIBLE_STORY_LIMIT} 字")
        merged = fast_merge.merge_contracts(raw, intent, visual_system_path)
        if merged.get("content_resolution", {}).get("status") == "needs_user_decision":
            raise SystemExit(f"page {page_id} 仍需用户内容决定，禁止创建图片任务")
        raw_assets = normalize_page_assets(asset_pages[page_id], page_id)
        if len(raw_assets) > 4:
            raise SystemExit(f"page {page_id} 的逐页图片资产必须为 0-4 项")
        merged["required_page_assets"] = [
            validate_asset(item, page_id, index)
            for index, item in enumerate(raw_assets)
        ]
        merged["four_by_three_method_contract_version"] = 1
        if canonical_title:
            merged["source_title_binding"] = {
                "status": "bound",
                "source": str(authoritative_snapshot),
            }
        merged["director_bundle_provenance"] = {
            "content_bundle_path": str(content_bundle_path),
            "content_bundle_sha256": pc.file_sha256(content_bundle_path),
            "assets_bundle_path": str(assets_bundle_path),
            "assets_bundle_sha256": pc.file_sha256(assets_bundle_path),
            "visual_system_path": str(visual_system_path),
            "visual_system_sha256": pc.file_sha256(visual_system_path),
        }
        output = content_output_dir / f"page_{page_id}.json"
        pc.atomic_write_json(output, merged)
        outputs[page_id] = str(output)

    portfolio = validate_layout_portfolio(
        visual_system.get("layout_portfolio"), expected_pages[0]
    )
    pc.atomic_write_json(layout_output_path, portfolio)
    return {
        "status": "ok",
        "page_order": expected_pages,
        "content_contracts": outputs,
        "layout_portfolio": str(layout_output_path),
        "style_count": len(STYLES),
        "facts_or_visual_semantics_guessed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--content-bundle", required=True)
    parser.add_argument("--assets-bundle", required=True)
    parser.add_argument("--visual-system", required=True)
    parser.add_argument("--content-output-dir", required=True)
    parser.add_argument("--layout-output", required=True)
    args = parser.parse_args()
    result = merge_bundle(
        state_path=Path(args.state).expanduser().resolve(),
        content_bundle_path=Path(args.content_bundle).expanduser().resolve(),
        assets_bundle_path=Path(args.assets_bundle).expanduser().resolve(),
        visual_system_path=Path(args.visual_system).expanduser().resolve(),
        content_output_dir=Path(args.content_output_dir).expanduser().resolve(),
        layout_output_path=Path(args.layout_output).expanduser().resolve(),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
