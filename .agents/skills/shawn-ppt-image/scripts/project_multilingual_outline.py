#!/usr/bin/env python3
"""Project one multilingual outline into isolated run-local physical page records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pipeline_control as pc


HEADER_ALIASES = {
    "page_id": ("页码", "page id"),
    "zh_title": ("客户钩子／页面标题", "中文标题", "中文页面标题"),
    "zh_core": ("核心命题", "中文核心命题"),
    "density": ("信息密度／上屏层级", "信息密度"),
    "zh_content": ("页面必讲内容", "中文页面内容"),
    "en_content": ("english page content", "英文完整页面内容"),
    "strategy": ("双语交付策略",),
    "pairs": ("同页双语配对",),
    "visual": ("视觉表达目标／用户硬约束", "视觉表达目标", "用户硬约束"),
}


def compact_markup(value: str) -> str:
    value = re.sub(r"[*_`]", "", str(value or ""))
    return re.sub(r"\s+", " ", value).strip().lower()


def requested_page_ids(value: str) -> list[str]:
    result: list[str] = []
    for item in (part.strip() for part in value.split(",")):
        if not item:
            continue
        number = pc.page_id_number(item)
        if number is None or number < 1:
            raise SystemExit(f"--page-ids 包含无效逻辑页码：{item}")
        result.append(f"{number:02d}")
    if not result or len(result) != len(set(result)):
        raise SystemExit("--page-ids 必须是非空、不重复的逻辑页码列表")
    return result


def table_cells(exact_text: str, logical_page_id: str) -> tuple[list[str], list[str]]:
    rows = [
        pc.split_markdown_table_row(line)
        for line in exact_text.splitlines()
        if pc.split_markdown_table_row(line)
    ]
    rows = [row for row in rows if row is not None]
    if len(rows) < 3:
        raise SystemExit(f"页面 {logical_page_id} 必须来自带表头的 Markdown 表格")
    header = rows[0]
    body_rows = [row for row in rows[1:] if not pc.markdown_table_separator(row)]
    if len(body_rows) != 1:
        raise SystemExit(f"页面 {logical_page_id} 必须恰好对应一个表格记录")
    row = body_rows[0]
    if len(header) != len(row):
        raise SystemExit(f"页面 {logical_page_id} 表头与内容列数不一致")
    return header, row


def column_map(header: list[str], logical_page_id: str) -> dict[str, int]:
    normalized = [compact_markup(item) for item in header]
    result: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        matches = [
            index
            for index, item in enumerate(normalized)
            if any(compact_markup(alias) == item for alias in aliases)
        ]
        if len(matches) != 1:
            raise SystemExit(
                f"页面 {logical_page_id} 缺少或重复多语言字段：{aliases[0]}"
            )
        result[field] = matches[0]
    return result


def parse_strategy(value: str, logical_page_id: str) -> str:
    match = re.search(r"(?i)\b(same_page|split_zh_en)\b", value)
    if not match:
        raise SystemExit(
            f"页面 {logical_page_id} 双语交付策略必须明确写 same_page 或 split_zh_en"
        )
    return match.group(1).lower()


def nonempty(value: str, label: str, logical_page_id: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise SystemExit(f"页面 {logical_page_id} 缺少 {label}")
    return cleaned


def parse_same_page_pairs(value: str, logical_page_id: str) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for item in re.split(r"(?i)<br\s*/?>|\n+", value):
        if "⇄" not in item:
            continue
        left, right = item.split("⇄", 1)
        left = re.sub(
            r"(?i)^\s*(?:\*\*)?(?:summary\s+)?pair\s*\d+[^:：]*[:：]\s*",
            "",
            left,
        )
        left = re.sub(r"[*_`]", "", left).strip()
        right = re.sub(r"[*_`]", "", right).strip()
        if left and right:
            pairs.append({"primary": left, "secondary": right})
    if not pairs:
        raise SystemExit(f"页面 {logical_page_id} 同页双语配对无法解析为中英对象")
    return pairs


def physical_page(
    *,
    page_id: str,
    logical_page_id: str,
    language_variant: str,
    strategy: str,
    source_sha256: str,
    display_source: dict[str, str],
    density: str,
    visual_constraints: str,
    pairs: list[dict[str, str]] | None = None,
    peer_page_id: str | None = None,
) -> dict[str, Any]:
    delivery = "same_page" if language_variant == "mixed" else (
        "split_peer" if peer_page_id else "single"
    )
    mode = {
        "zh": "zh_only",
        "en": "en_only",
        "mixed": "bilingual",
    }[language_variant]
    presentation: dict[str, Any] = {
        "mode": mode,
        "delivery": delivery,
        "logical_page_id": logical_page_id,
        "peer_page_id": peer_page_id,
        "pairing": "paired" if language_variant == "mixed" else "none",
    }
    record: dict[str, Any] = {
        "page_id": page_id,
        "logical_page_id": logical_page_id,
        "language_variant": language_variant,
        "bilingual_strategy": strategy,
        "source_page_sha256": source_sha256,
        "language_presentation_seed": presentation,
        "display_source": display_source,
        "information_density": density,
        "planning_only_visual_constraints": visual_constraints,
        "projection_boundary": (
            "Only display_source and same_page_pairs authorize visible copy. "
            "Planning fields are not display copy. Do not translate or borrow from another page."
        ),
    }
    if pairs is not None:
        record["same_page_pairs"] = pairs
    return record


def project_page(
    page: dict[str, str], output_mode: str
) -> list[dict[str, Any]]:
    logical_page_id = f"{pc.page_id_number(page['page_id']):02d}"
    header, row = table_cells(page["exact_text"], logical_page_id)
    columns = column_map(header, logical_page_id)
    values = {field: row[index] for field, index in columns.items()}
    strategy = parse_strategy(values["strategy"], logical_page_id)
    zh_source = {
        "title": nonempty(values["zh_title"], "中文标题", logical_page_id),
        "core_thesis": nonempty(values["zh_core"], "中文核心命题", logical_page_id),
        "page_content": nonempty(values["zh_content"], "中文页面内容", logical_page_id),
    }
    density = nonempty(values["density"], "信息密度", logical_page_id)
    visual = nonempty(values["visual"], "视觉约束", logical_page_id)
    source_sha256 = str(page["exact_sha256"])

    if output_mode == "zh":
        return [physical_page(
            page_id=logical_page_id,
            logical_page_id=logical_page_id,
            language_variant="zh",
            strategy=strategy,
            source_sha256=source_sha256,
            display_source=zh_source,
            density=density,
            visual_constraints=visual,
        )]

    en_source = {
        "page_content": nonempty(
            values["en_content"], "English Page Content", logical_page_id
        )
    }
    if output_mode == "en":
        return [physical_page(
            page_id=logical_page_id,
            logical_page_id=logical_page_id,
            language_variant="en",
            strategy=strategy,
            source_sha256=source_sha256,
            display_source=en_source,
            density=density,
            visual_constraints=visual,
        )]

    if strategy == "same_page":
        pairs = parse_same_page_pairs(
            nonempty(values["pairs"], "同页双语配对", logical_page_id),
            logical_page_id,
        )
        return [physical_page(
            page_id=logical_page_id,
            logical_page_id=logical_page_id,
            language_variant="mixed",
            strategy=strategy,
            source_sha256=source_sha256,
            display_source=zh_source,
            density=density,
            visual_constraints=visual,
            pairs=pairs,
        )]

    zh_page_id = f"{logical_page_id}-ZH"
    en_page_id = f"{logical_page_id}-EN"
    return [
        physical_page(
            page_id=zh_page_id,
            logical_page_id=logical_page_id,
            language_variant="zh",
            strategy=strategy,
            source_sha256=source_sha256,
            display_source=zh_source,
            density=density,
            visual_constraints=visual,
            peer_page_id=en_page_id,
        ),
        physical_page(
            page_id=en_page_id,
            logical_page_id=logical_page_id,
            language_variant="en",
            strategy=strategy,
            source_sha256=source_sha256,
            display_source=en_source,
            density=density,
            visual_constraints=visual,
            peer_page_id=zh_page_id,
        ),
    ]


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
        Path(temp_name).replace(path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把单一多语言 Markdown 大纲投影为当前运行的隔离物理页面 JSON"
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--page-ids", required=True)
    parser.add_argument("--output-mode", choices=("zh", "en", "bilingual"), required=True)
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {".md", ".markdown"}:
        raise SystemExit("--source 必须是存在的 Markdown 文件")
    if output == source:
        raise SystemExit("--output 不得覆盖权威大纲")
    logical_page_ids = requested_page_ids(args.page_ids)
    extracted = pc.extract_relevant_source_content(
        source, logical_page_ids, include_exact=True
    )
    pages = [
        physical
        for page in extracted["pages"]
        for physical in project_page(page, args.output_mode)
    ]
    page_order = [str(item["page_id"]) for item in pages]
    if len(page_order) != len(set(page_order)):
        raise SystemExit("语言投影后物理页码重复")
    result = {
        "multilingual_projection_contract_version": 1,
        "authoritative_outline": {
            "path": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "output_mode": args.output_mode,
        "logical_page_order": logical_page_ids,
        "page_order": page_order,
        "pages": pages,
    }
    atomic_write_json(output, result)
    print(json.dumps({
        "status": "projected",
        "output": str(output),
        "output_mode": args.output_mode,
        "logical_pages": len(logical_page_ids),
        "physical_pages": len(pages),
        "page_order": page_order,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
