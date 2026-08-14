#!/usr/bin/env python3
"""Freeze exactly three representative pages for the new 4x3 directors."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_control as pc


FAST_PACKET_PATH = Path(__file__).resolve().parent / "build_fast8_page_source_packet.py"
SPEC = importlib.util.spec_from_file_location("fast8_packet_for_4x3", FAST_PACKET_PATH)
assert SPEC and SPEC.loader
fast_packet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fast_packet)


def markdown_packet(text: str, page_ids: list[str]) -> str:
    body, _titles = fast_packet.markdown_pages_packet(text, page_ids)
    return body


def build_packet(source: Path, page_ids: list[str], include_files: list[Path]) -> str:
    if source.suffix.lower() in {".md", ".markdown", ".txt"}:
        body = markdown_packet(source.read_text(encoding="utf-8"), page_ids)
    else:
        body = str(pc.extract_relevant_source_content(source, page_ids)["normalized_text"])
    sections = [
        "# 4x3 frozen authoritative three-page packet",
        "page_order: " + ",".join(page_ids),
        f"anchor_page_id: {page_ids[0]}",
        f"follower_page_ids: {page_ids[1]},{page_ids[2]}",
        "",
        body,
    ]
    for path in include_files:
        if path.suffix.lower() not in {".md", ".markdown", ".txt", ".json"}:
            raise SystemExit(f"4x3 附加来源只支持文本或 JSON：{path}")
        raw = path.read_text(encoding="utf-8")
        if any(marker in raw for marker in fast_packet.IMAGE_STAGE_EXCLUSION_MARKERS):
            continue
        content = (
            fast_packet.markdown_shared_packet(raw, page_ids)
            if path.suffix.lower() in {".md", ".markdown"}
            else pc.normalize_source_text(raw)
        )
        if content:
            sections.extend(["", f"## Included source: {path.name}", "", content])
    return "\n".join(sections).rstrip() + "\n"


def include_page_numbers(path: Path) -> set[int]:
    """Return explicit Pxx tokens from a supporting filename, never bare years."""

    return {
        int(value)
        for value in re.findall(
            r"(?i)(?:^|[^A-Za-z0-9])P0*(\d+)(?=[^0-9]|$)", path.stem
        )
    }


def build_snapshot_source(
    source: Path, page_ids: list[str], include_files: list[Path]
) -> dict:
    """Build one unique JSON record per page from the same frozen inputs.

    The Markdown packet is optimized for the three directors and may mention a
    page in both the outline row and its supporting page note.  The source
    guard deliberately rejects that ambiguity.  JSON records preserve both
    texts inside one explicit page object without weakening uniqueness checks.
    """

    pages: dict[str, dict[str, str]] = {}
    for page_id in page_ids:
        number = pc.page_id_number(page_id)
        applicable = [
            path
            for path in include_files
            if not include_page_numbers(path)
            or number in include_page_numbers(path)
        ]
        body, canonical_title = fast_packet.build_packet(
            source, page_id, applicable
        )
        pages[page_id] = {
            "page_id": page_id,
            "canonical_title": canonical_title or "",
            "normalized_source": body,
        }
    return {
        "four_by_three_snapshot_source_version": 1,
        "page_order": page_ids,
        "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--page-id", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--snapshot-output",
        required=True,
        help="新 4x3 正式运行必用：恰好三条记录的 source snapshot JSON",
    )
    parser.add_argument("--include-file", action="append", default=[])
    args = parser.parse_args()
    source = fast_packet.existing_absolute_file(args.source, "4x3 权威来源")
    page_ids = [str(value).strip() for value in args.page_id]
    if len(page_ids) != 3 or len(set(page_ids)) != 3 or any(not value for value in page_ids):
        raise SystemExit("4x3 --page-id 必须恰好提供三个不同非空页码，首个为锚点")
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        raise SystemExit("--output 必须是绝对路径")
    include_files = [
        fast_packet.existing_absolute_file(value, "4x3 附加来源")
        for value in args.include_file
    ]
    if source in include_files or len(include_files) != len(set(include_files)):
        raise SystemExit("4x3 权威来源与附加来源不得重复")
    output = output.resolve()
    status = fast_packet.atomic_write_once(
        output, build_packet(source, page_ids, include_files)
    )
    snapshot_output = Path(args.snapshot_output).expanduser()
    if not snapshot_output.is_absolute():
        raise SystemExit("--snapshot-output 必须是绝对路径")
    snapshot_output = snapshot_output.resolve()
    if snapshot_output == output:
        raise SystemExit("--output 与 --snapshot-output 必须是两个不同文件")
    snapshot_payload = (
        json.dumps(
            build_snapshot_source(source, page_ids, include_files),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    snapshot_status = fast_packet.atomic_write_once(
        snapshot_output, snapshot_payload
    )
    print(
        json.dumps(
            {
                "status": status,
                "output": str(output),
                "page_order": page_ids,
                "sha256": pc.file_sha256(output),
                "snapshot_output": str(snapshot_output),
                "snapshot_status": snapshot_status,
                "snapshot_sha256": pc.file_sha256(snapshot_output),
                "directors_must_read_live_source": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
