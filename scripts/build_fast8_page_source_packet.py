#!/usr/bin/env python3
"""Freeze one Fast8 page and its applicable shared rules into a stable packet.

The live outline may continue changing while a Fast8 run is executing.  Image
directors should therefore consume one immutable, page-scoped packet instead of
re-reading the whole live outline.  For Markdown table outlines, this script
keeps all non-page prose (including shared/global rules), the table header, and
only the requested page row.  Other supported source formats fall back to the
existing deterministic page extractor.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Union

import pipeline_control as pipeline


IMAGE_STAGE_EXCLUSION_MARKERS = (
    "作图准备、内容合同编译、图片生成和视觉审核阶段不得读取、引用、封存或传递本文件",
)


def existing_absolute_file(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SystemExit(f"{label} 必须是绝对路径：{value}")
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"{label} 不存在：{path}")
    return path


def markdown_pages_packet(
    text: str, page_ids: list[str]
) -> tuple[str, dict[str, str | None]]:
    """Primary shared packet filter used by Fast8 and the 4x3 adapter."""

    if not page_ids or len(set(page_ids)) != len(page_ids):
        raise SystemExit("页面来源包 page_ids 必须为不重复的非空列表")
    # Validate uniqueness and extractability with the same parser used by the
    # formal source snapshot before doing lossless page filtering.
    pipeline.extract_markdown_pages(text, page_ids)
    outline = pipeline.markdown_heading_outline(text)
    if outline["sections"]:
        canonical_titles: dict[str, str | None] = {}
        selected_ranges: list[tuple[int, int]] = []
        for page_id in page_ids:
            matches = [
                section for section in outline["sections"]
                if pipeline.page_ids_match(section["page_id"], page_id)
            ]
            if len(matches) != 1:
                raise SystemExit(f"权威文本源中页面记录不唯一：{page_id}")
            section = matches[0]
            selected_ranges.append((section["start"], section["end"]))
            canonical_titles[page_id] = section["title"]
        all_page_indexes = {
            index
            for section in outline["sections"]
            for index in range(section["start"], section["end"])
        }
        selected_indexes = {
            index for start, end in selected_ranges for index in range(start, end)
        }
        kept = [
            line
            for index, line in enumerate(outline["lines"])
            if index not in all_page_indexes or index in selected_indexes
        ]
        normalized = pipeline.normalize_source_text("\n".join(kept))
        if not normalized:
            raise SystemExit("页面来源包内容为空")
        return normalized, canonical_titles

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    target_rows: dict[str, tuple[list[str], list[str]]] = {}
    current_header: list[str] | None = None
    for line in lines:
        cells = pipeline.split_markdown_table_row(line)
        if cells is None:
            kept.append(line)
            current_header = None
            continue
        if pipeline.markdown_table_separator(cells):
            kept.append(line)
            continue
        if current_header is None:
            current_header = cells
            kept.append(line)
            continue
        first = cells[0] if cells else ""
        if pipeline.page_id_number(first) is None:
            kept.append(line)
            continue
        matches = [
            page_id
            for page_id in page_ids
            if pipeline.page_ids_match(first, page_id)
        ]
        if matches:
            if len(matches) != 1 or matches[0] in target_rows:
                raise SystemExit(f"权威文本源中页面记录不唯一：{first}")
            target_rows[matches[0]] = (cells, current_header)
            kept.append(line)
        # Other page rows are intentionally omitted from the frozen packet.

    missing = set(page_ids) - set(target_rows)
    if missing:
        raise SystemExit(f"权威文本源中缺少页面记录：{sorted(missing)}")
    canonical_titles: dict[str, str | None] = {}
    for page_id in page_ids:
        target_cells, target_header = target_rows[page_id]
        canonical_title: str | None = None
        if len(target_cells) == len(target_header):
            for index, heading in enumerate(target_header):
                normalized = pipeline.normalize_signature_text(heading)
                if "title" in normalized or "标题" in heading:
                    canonical_title = target_cells[index].strip(" *") or None
                    break
        canonical_titles[page_id] = canonical_title
    normalized = pipeline.normalize_source_text("\n".join(kept))
    if not normalized:
        raise SystemExit("页面来源包内容为空")
    return normalized, canonical_titles


def markdown_page_packet(text: str, page_id: str) -> tuple[str, str | None]:
    body, titles = markdown_pages_packet(text, [page_id])
    return body, titles[page_id]


def markdown_shared_packet(text: str, page_ids: Union[str, list[str]]) -> str:
    """Keep shared prose while removing table rows for unrelated pages."""

    selected = [page_ids] if isinstance(page_ids, str) else page_ids

    outline = pipeline.markdown_heading_outline(text)
    if outline["sections"]:
        kept: list[str] = []
        for index, line in enumerate(outline["lines"]):
            owner = next((
                section for section in outline["sections"]
                if section["start"] <= index < section["end"]
            ), None)
            if owner is None or any(
                pipeline.page_ids_match(owner["page_id"], page_id)
                for page_id in selected
            ):
                kept.append(line)
        return pipeline.normalize_source_text("\n".join(kept))

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    current_header: list[str] | None = None
    for line in lines:
        cells = pipeline.split_markdown_table_row(line)
        if cells is None:
            kept.append(line)
            current_header = None
            continue
        if pipeline.markdown_table_separator(cells):
            kept.append(line)
            continue
        if current_header is None:
            current_header = cells
            kept.append(line)
            continue
        first = cells[0] if cells else ""
        if pipeline.page_id_number(first) is None or any(
            pipeline.page_ids_match(first, page_id) for page_id in selected
        ):
            kept.append(line)
    return pipeline.normalize_source_text("\n".join(kept))


def build_packet(source: Path, page_id: str, include_files: list[Path]) -> tuple[str, str | None]:
    suffix = source.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        body, canonical_title = markdown_page_packet(
            source.read_text(encoding="utf-8"), page_id
        )
    else:
        extracted = pipeline.extract_relevant_source_content(source, [page_id])
        body = str(extracted["normalized_text"])
        canonical_title = None
    sections = [
        "# Fast8 frozen authoritative page packet",
        f"page_id: {page_id}",
        "",
        body,
    ]
    for path in include_files:
        if path.suffix.lower() not in {".md", ".markdown", ".txt", ".json"}:
            raise SystemExit(f"Fast8 附加来源包只支持文本或 JSON：{path}")
        raw_content = path.read_text(encoding="utf-8")
        if any(marker in raw_content for marker in IMAGE_STAGE_EXCLUSION_MARKERS):
            # Respect a source file's own explicit audience boundary. Keeping
            # it in preflight provenance is harmless; sending it to three
            # image-stage directors is both incorrect and slow.
            continue
        if path.suffix.lower() in {".md", ".markdown"}:
            content = markdown_shared_packet(raw_content, page_id)
        else:
            content = pipeline.normalize_source_text(raw_content)
        if not content:
            raise SystemExit(f"Fast8 附加来源文件为空：{path}")
        sections.extend(["", f"## Included source: {path.name}", "", content])
    return "\n".join(sections).rstrip() + "\n", canonical_title


def atomic_write_once(path: Path, payload: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == payload:
            return "already_frozen"
        raise SystemExit(
            "Fast8 页面来源包已经存在且内容不同；当前运行不得随上游变化重写，"
            "请为新内容建立新运行"
        )
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
    return "frozen"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--include-file", action="append", default=[])
    args = parser.parse_args()

    source = existing_absolute_file(args.source, "Fast8 权威来源")
    page_id = args.page_id.strip()
    if not page_id:
        raise SystemExit("--page-id 不能为空")
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        raise SystemExit("--output 必须是绝对路径")
    output = output.resolve()
    include_files = [
        existing_absolute_file(value, "Fast8 附加来源")
        for value in args.include_file
    ]
    if source in include_files or len(include_files) != len(set(include_files)):
        raise SystemExit("Fast8 页面来源与附加来源不得重复")

    payload, canonical_title = build_packet(source, page_id, include_files)
    status = atomic_write_once(output, payload)
    print(
        json.dumps(
            {
                "status": status,
                "output": str(output),
                "page_id": page_id,
                "canonical_title": canonical_title,
                "sha256": pipeline.file_sha256(output),
                "directors_must_read_live_source": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
