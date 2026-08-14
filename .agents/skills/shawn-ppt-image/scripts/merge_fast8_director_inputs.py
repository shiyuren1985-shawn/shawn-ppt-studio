#!/usr/bin/env python3
"""Merge sol/high visual intent into a factual Fast8 content contract.

The source-contract compiler and visual portfolio director run in parallel.
This script is the only merge point: it copies a small allow-list of creative
fields, never rewrites facts, display obligations, brand authorization or
source status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import pipeline_control as pipeline


CREATIVE_FIELDS = (
    "relationship_thesis",
    "visual_quality_intent",
    "visual_support_goal",
    "craft_ambition",
)

UNIFIED_SPATIAL_QA_CONTRACT = (
    "按统一空间标准检查整齐度、隐形网格、对齐、聚拢、重复、对比、阅读路径和"
    "有效负空间；确认组内紧、组间松，边缘有缓冲，页面在当前信息密度下自然、有"
    "呼吸感，并且没有退化为等重卡片墙。"
)

PROMPT_ITEM_LIMITS = {
    "prompt_semantic_guardrails": {"items": 3, "item_chars": 120, "total_chars": 300},
    "prompt_user_constraints": {"items": 3, "item_chars": 120, "total_chars": 240},
}


def read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"{label} 不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} JSON 无法解析：{path}：{exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} 根节点必须是对象：{path}")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value.rstrip() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def split_bounded_prompt_text(text: str, item_chars: int) -> list[str]:
    """Split without truncation, preferring semantic punctuation boundaries."""

    remaining = text.strip()
    chunks: list[str] = []
    while len(remaining) > item_chars:
        window = remaining[: item_chars + 1]
        preferred = [
            match.end()
            for match in re.finditer(r"[。！？!?；;：:]|\s+", window)
            if 1 <= match.end() <= item_chars
        ]
        cut = preferred[-1] if preferred else item_chars
        piece = remaining[:cut].strip()
        if not piece:
            cut = item_chars
            piece = remaining[:cut]
        chunks.append(piece)
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def normalize_prompt_items(
    merged: dict, field: str
) -> tuple[list[str], dict | None]:
    limits = PROMPT_ITEM_LIMITS[field]
    raw = merged.get(field, [])
    if not isinstance(raw, list) or len(raw) > limits["items"]:
        raise SystemExit(f"content_contract.{field} 必须是 0–{limits['items']} 条字符串")
    values: list[str] = []
    for index, value in enumerate(raw):
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"content_contract.{field}[{index}] 必须是非空字符串")
        values.append(value.strip())
    if sum(map(len, values)) > limits["total_chars"]:
        raise SystemExit(
            f"content_contract.{field} 合计超过 {limits['total_chars']} 字；"
            "确定性脚本不会截断事实或用户要求"
        )
    if all(len(value) <= limits["item_chars"] for value in values):
        return values, None

    # The old model repair round existed only because one fact-complete item
    # crossed a transport limit. Reflow it here; never paraphrase or truncate.
    flattened = "\n".join(values)
    chunks = split_bounded_prompt_text(flattened, limits["item_chars"])
    if len(chunks) > limits["items"] or any(
        len(value) > limits["item_chars"] for value in chunks
    ):
        raise SystemExit(
            f"content_contract.{field} 无法无损规范化为 "
            f"{limits['items']}×{limits['item_chars']} 字"
        )
    return chunks, {
        "owner": "merge_fast8_director_inputs.py",
        "mode": "deterministic_reflow_without_truncation",
        "original_item_count": len(values),
        "normalized_item_count": len(chunks),
    }


def normalize_page_id_alias(value: dict, label: str) -> dict:
    """Accept the harmless canonical_page_id alias without model repair."""

    normalized = dict(value)
    page_id = str(normalized.get("page_id") or "").strip()
    canonical_page_id = str(normalized.get("canonical_page_id") or "").strip()
    if page_id and canonical_page_id and page_id != canonical_page_id:
        raise SystemExit(
            f"{label}.page_id 与 {label}.canonical_page_id 冲突"
        )
    if not page_id and canonical_page_id:
        normalized["page_id"] = canonical_page_id
        normalized.setdefault("director_input_normalization", {})[
            "page_id_alias"
        ] = "canonical_page_id_to_page_id"
    normalized.pop("canonical_page_id", None)
    return normalized


def project_content_load_review(merged: dict, locale: str) -> dict:
    """Project QA-only load risks without asking a model to restate facts."""

    relationship = str(merged.get("relationship_thesis") or "").strip()
    density = str(merged.get("information_density_target") or "medium").strip()
    supporting = merged.get("display_supporting") or []
    if locale == "zh":
        attention = (
            "辅助事实不得与主关系争夺同等注意力。"
            if supporting
            else "多个信息组不得等权争夺主关系。"
        )
        return {
            "semantic_structure": relationship,
            "focus_relationship": relationship,
            "attention_risks": [attention],
            "edge_and_takeaway_risks": [
                "Takeaway 仅在提供新结论时使用，不以额外底栏重复主结论。"
            ],
            "duplication_risks": [
                "逐字锚点、内容故事与视觉解释不得完整重复同一事实。"
            ],
            "reason": (
                f"脚本依据关系命题、{density} 内容密度及辅助信息存在性生成；"
                "不改变事实、显示义务或视觉方向。"
            ),
        }
    attention = (
        "Supporting facts must not compete with the primary relationship."
        if supporting
        else "Multiple information groups must not compete at equal priority."
    )
    return {
        "semantic_structure": relationship,
        "focus_relationship": relationship,
        "attention_risks": [attention],
        "edge_and_takeaway_risks": [
            "Use a takeaway only for a new conclusion; do not repeat the main claim in a footer band."
        ],
        "duplication_risks": [
            "Literal anchors, the content story and visual explanation must not fully repeat the same fact."
        ],
        "reason": (
            f"Script-projected from the relationship thesis, {density} content density "
            "and supporting-content presence; facts, display duties and visual direction are unchanged."
        ),
    }


def project_overall_requirements(merged: dict, locale: str) -> str:
    """Create legacy metadata that v4 ImageGen deliberately does not consume."""

    if locale == "zh":
        return (
            "按合并后的内容合同、当前用户要求与已授权参考生成正式成品页；"
            "保持原文语言、事实与来源状态、品牌边界和显示义务，不新增未经授权内容。"
        )
    return (
        "Create a finished presentation page from the merged content contract, current user "
        "requirements and authorized references; preserve source language, factual and source "
        "status, brand boundaries and display duties without adding unauthorized content."
    )


def merge_contracts(content: dict, intent: dict, intent_path: Path) -> dict:
    content = normalize_page_id_alias(content, "content_contract")
    intent = normalize_page_id_alias(intent, "creative_intent")
    if intent.get("creative_intent_contract_version") != 1:
        raise SystemExit("creative_intent_contract_version 必须为 1")
    content_page = str(content.get("page_id") or "")
    intent_page = str(intent.get("page_id") or "")
    if not content_page or content_page != intent_page:
        raise SystemExit(
            "content_contract 与 creative_intent 必须使用完全相同的规范页码"
        )
    merged = dict(content)
    # These are universal pipeline mechanics, not page facts or creative
    # choices.  Script-own them so a factual director cannot create a model
    # repair round by omitting or paraphrasing a fixed QA contract.
    locale = pipeline.content_contract_prompt_locale(merged)
    merged["spatial_standard_version"] = pipeline.CURRENT_SPATIAL_STANDARD_VERSION
    merged["spatial_feasibility"] = "pass"
    merged["spatial_generation_brief"] = pipeline.UNIFIED_SPATIAL_PROMPT_CUES[
        locale
    ]
    merged["spatial_qa_contract"] = UNIFIED_SPATIAL_QA_CONTRACT
    merged["spatial_contract_provenance"] = {
        "owner": "merge_fast8_director_inputs.py",
        "script_owned": True,
        "locale": locale,
    }
    prompt_normalizations: dict[str, dict] = {}
    for field in PROMPT_ITEM_LIMITS:
        normalized_items, provenance = normalize_prompt_items(merged, field)
        merged[field] = normalized_items
        if provenance is not None:
            prompt_normalizations[field] = provenance
    if prompt_normalizations:
        merged["prompt_item_normalization"] = prompt_normalizations
    for field in CREATIVE_FIELDS:
        value = intent.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"creative_intent 缺少非空字段 {field}")
        normalized = value.strip()
        if len(normalized) > 500:
            raise SystemExit(f"creative_intent.{field} 超过 500 字")
        merged[field] = normalized
    if not isinstance(merged.get("content_load_review"), dict):
        merged["content_load_review"] = project_content_load_review(merged, locale)
        merged["content_load_review_provenance"] = {
            "owner": "merge_fast8_director_inputs.py",
            "mode": "deterministic_qa_projection",
            "facts_or_display_obligations_modified": False,
        }
    merged["creative_intent_provenance"] = {
        "merge_contract_version": 1,
        "path": str(intent_path.resolve()),
        "sha256": file_sha256(intent_path),
        "merged_fields": list(CREATIVE_FIELDS),
        "facts_or_brand_fields_modified": False,
    }
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--content-contract", required=True)
    parser.add_argument("--creative-intent", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--overall-requirements-output")
    args = parser.parse_args()

    content_path = Path(args.content_contract).expanduser().resolve()
    intent_path = Path(args.creative_intent).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    merged = merge_contracts(
        read_object(content_path, "content_contract"),
        read_object(intent_path, "creative_intent"),
        intent_path,
    )
    atomic_write(output_path, merged)
    overall_path = None
    if args.overall_requirements_output:
        overall_path = Path(args.overall_requirements_output).expanduser().resolve()
        atomic_write_text(
            overall_path,
            project_overall_requirements(
                merged, pipeline.content_contract_prompt_locale(merged)
            ),
        )
    print(
        json.dumps(
            {
                "status": "ok",
                "page_id": merged["page_id"],
                "output": str(output_path),
                "merged_fields": list(CREATIVE_FIELDS),
                "facts_or_brand_fields_modified": False,
                "script_owned_spatial_contract": True,
                "script_owned_content_load_review": bool(
                    (merged.get("content_load_review_provenance") or {}).get(
                        "owner"
                    )
                ),
                "overall_requirements_output": str(overall_path) if overall_path else None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
