#!/usr/bin/env python3
"""Normalize only mechanical Fast8 director output fields.

Semantic content decisions and visual directions remain model-owned.  This
compiler hardcodes version fields, accepts one lossless container alias, and
fails closed on unknown or invalid semantic fields.  Raw director JSON is
never overwritten.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import pipeline_control as pipeline


STYLES = tuple("ABCDEFGH")
CONTENT_VERSIONS = {
    "content_contract_version": 2,
    "prompt_contract_version": 4,
}
LAYOUT_VERSIONS = {
    "layout_portfolio_contract_version": 7,
    "art_direction_contract_version": 1,
    "visual_activity_portfolio_version": 1,
    "spatial_topology_portfolio_version": 1,
}
CONTENT_REQUIRED = {
    "page_id",
    "language",
    "source_facts",
    "display_required",
    "display_flexible",
    "display_supporting",
    "flexible_story",
    "information_density_target",
    "semantic_invariants",
    "forbidden_interpretations",
    "prompt_semantic_guardrails",
    "prompt_user_constraints",
    "content_resolution",
}
CONTENT_ALLOWED = CONTENT_REQUIRED | set(CONTENT_VERSIONS)
LAYOUT_ALLOWED = {
    *LAYOUT_VERSIONS,
    "page_id",
    "director_rationale",
    "styles",
    "directions",
}
STYLE_ALLOWED = {
    "direction_id",
    "first_impression",
    "visual_thesis",
    "craft_axis",
    "visual_activity_mode",
    "attention_strategy",
    "relationship_representation_family",
    "spatial_topology",
}
STYLE_REQUIRED = STYLE_ALLOWED - {"first_impression"}
TOPOLOGY_ALLOWED = {
    "primary_entry",
    "region_logic",
    "evidence_attachment",
    "spatial_topology_intent",
}
CONTENT_RESOLUTION_STATUSES = {
    "not_needed",
    "confirmed",
    "needs_user_decision",
}


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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_raw_input(path: Path, label: str) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise SystemExit(f"{label} 必须是绝对路径")
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"{label} 不存在：{path}")
    return path


def require_normalized_output(path: Path, input_paths: set[Path], label: str) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise SystemExit(f"{label} 必须是绝对路径")
    path = path.resolve()
    if path in input_paths:
        raise SystemExit(f"{label} 不得覆盖原始导演 JSON")
    if not path.name.endswith(".normalized.json"):
        raise SystemExit(f"{label} 文件名必须以 .normalized.json 结尾")
    return path


def reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SystemExit(f"{label} 包含未知字段：{', '.join(unknown)}")


def require_nonempty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{label} 必须是非空字符串")


def normalize_content(raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reject_unknown(raw, CONTENT_ALLOWED, "content_contract")
    missing = sorted(CONTENT_REQUIRED - set(raw))
    if missing:
        raise SystemExit(f"content_contract 缺少字段：{', '.join(missing)}")
    resolution = raw.get("content_resolution")
    if not isinstance(resolution, dict):
        raise SystemExit("content_contract.content_resolution 必须是对象")
    reject_unknown(resolution, {"status", "reason"}, "content_resolution")
    if resolution.get("status") not in CONTENT_RESOLUTION_STATUSES:
        raise SystemExit(
            "content_resolution.status 只允许 "
            "not_needed|confirmed|needs_user_decision；不会猜测近义值"
        )
    require_nonempty_string(resolution.get("reason"), "content_resolution.reason")
    normalized = copy.deepcopy(raw)
    changes: list[dict[str, Any]] = []
    for field, fixed in CONTENT_VERSIONS.items():
        previous = normalized.get(field)
        normalized[field] = fixed
        if previous != fixed:
            changes.append(
                {"field": field, "mode": "script_owned_constant", "from": previous, "to": fixed}
            )
    return normalized, changes


def validate_style(style: str, raw: Any) -> None:
    if not isinstance(raw, dict):
        raise SystemExit(f"styles.{style} 必须是对象")
    reject_unknown(raw, STYLE_ALLOWED, f"styles.{style}")
    missing = sorted(STYLE_REQUIRED - set(raw))
    if missing:
        raise SystemExit(f"styles.{style} 缺少字段：{', '.join(missing)}")
    for field in (
        "direction_id",
        "visual_thesis",
        "craft_axis",
        "attention_strategy",
        "relationship_representation_family",
    ):
        require_nonempty_string(raw.get(field), f"styles.{style}.{field}")
    if raw.get("visual_activity_mode") not in pipeline.VISUAL_ACTIVITY_MODES:
        raise SystemExit(
            f"styles.{style}.visual_activity_mode 只允许 restrained|balanced|expressive"
        )
    topology = raw.get("spatial_topology")
    if not isinstance(topology, dict):
        raise SystemExit(f"styles.{style}.spatial_topology 必须是对象")
    reject_unknown(topology, TOPOLOGY_ALLOWED, f"styles.{style}.spatial_topology")
    missing_topology = sorted(TOPOLOGY_ALLOWED - set(topology))
    if missing_topology:
        raise SystemExit(
            f"styles.{style}.spatial_topology 缺少字段：{', '.join(missing_topology)}"
        )
    if topology.get("primary_entry") not in pipeline.SPATIAL_TOPOLOGY_PRIMARY_ENTRIES:
        raise SystemExit(f"styles.{style}.spatial_topology.primary_entry 无效")
    if topology.get("region_logic") not in pipeline.SPATIAL_TOPOLOGY_REGION_LOGICS:
        raise SystemExit(f"styles.{style}.spatial_topology.region_logic 无效")
    if topology.get("evidence_attachment") not in pipeline.SPATIAL_TOPOLOGY_EVIDENCE_MODES:
        raise SystemExit(f"styles.{style}.spatial_topology.evidence_attachment 无效")
    require_nonempty_string(
        topology.get("spatial_topology_intent"),
        f"styles.{style}.spatial_topology.spatial_topology_intent",
    )


def normalize_layout(raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reject_unknown(raw, LAYOUT_ALLOWED, "layout_portfolio")
    if "styles" in raw and "directions" in raw:
        raise SystemExit("layout_portfolio 不得同时包含 styles 与 directions")
    normalized = copy.deepcopy(raw)
    changes: list[dict[str, Any]] = []
    if "styles" not in normalized:
        directions = normalized.get("directions")
        if not isinstance(directions, dict) or set(directions) != set(STYLES):
            raise SystemExit("仅当 directions 是恰好包含 A-H 的对象时才允许无损改名")
        before = copy.deepcopy(directions)
        normalized["styles"] = normalized.pop("directions")
        if normalized["styles"] != before:
            raise SystemExit("directions→styles 深相等校验失败")
        changes.append(
            {
                "field": "directions",
                "mode": "lossless_container_alias",
                "to": "styles",
                "per_seat_deep_equal": {style: normalized["styles"][style] == before[style] for style in STYLES},
            }
        )
    styles = normalized.get("styles")
    if not isinstance(styles, dict) or set(styles) != set(STYLES):
        raise SystemExit("layout_portfolio.styles 必须且只能包含 A-H")
    require_nonempty_string(normalized.get("page_id"), "layout_portfolio.page_id")
    require_nonempty_string(
        normalized.get("director_rationale"), "layout_portfolio.director_rationale"
    )
    for style in STYLES:
        validate_style(style, styles[style])
    for field, fixed in LAYOUT_VERSIONS.items():
        previous = normalized.get(field)
        normalized[field] = fixed
        if previous != fixed:
            changes.append(
                {"field": field, "mode": "script_owned_constant", "from": previous, "to": fixed}
            )
    return normalized, changes


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--content-input", required=True)
    parser.add_argument("--layout-input", required=True)
    parser.add_argument("--content-output", required=True)
    parser.add_argument("--layout-output", required=True)
    parser.add_argument("--provenance-output", required=True)
    args = parser.parse_args()

    content_input = require_raw_input(Path(args.content_input), "--content-input")
    layout_input = require_raw_input(Path(args.layout_input), "--layout-input")
    raw_paths = {content_input, layout_input}
    content_output = require_normalized_output(
        Path(args.content_output), raw_paths, "--content-output"
    )
    layout_output = require_normalized_output(
        Path(args.layout_output), raw_paths, "--layout-output"
    )
    provenance_output = require_normalized_output(
        Path(args.provenance_output), raw_paths, "--provenance-output"
    )
    if len({content_output, layout_output, provenance_output}) != 3:
        raise SystemExit("三个输出路径必须互不相同")

    content, content_changes = normalize_content(
        read_object(content_input, "raw content_contract")
    )
    layout, layout_changes = normalize_layout(
        read_object(layout_input, "raw layout_portfolio")
    )
    if content.get("page_id") != layout.get("page_id"):
        raise SystemExit("content_contract 与 layout_portfolio page_id 不一致")

    atomic_write_json(content_output, content)
    atomic_write_json(layout_output, layout)
    provenance = {
        "normalizer": "normalize_fast8_director_outputs.py",
        "schema_only": True,
        "semantic_mapping_performed": False,
        "raw_inputs_preserved": True,
        "page_id": content["page_id"],
        "content": {
            "input": str(content_input),
            "input_sha256": file_sha256(content_input),
            "output": str(content_output),
            "output_sha256": file_sha256(content_output),
            "changes": content_changes,
        },
        "layout": {
            "input": str(layout_input),
            "input_sha256": file_sha256(layout_input),
            "output": str(layout_output),
            "output_sha256": file_sha256(layout_output),
            "changes": layout_changes,
        },
    }
    atomic_write_json(provenance_output, provenance)
    print(
        json.dumps(
            {
                "status": "normalized",
                "page_id": content["page_id"],
                "content_output": str(content_output),
                "layout_output": str(layout_output),
                "provenance_output": str(provenance_output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
