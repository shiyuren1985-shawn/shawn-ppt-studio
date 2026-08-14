#!/usr/bin/env python3
"""Recover one unbound imagegen PNG without guessing the newest file.

The script only returns ``recovered`` when exactly one valid, unbound PNG was
written inside the supplied tool-call interval.  Multiple candidates are
reported as ambiguous and must never be resolved by selecting the newest file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOOL_ID_RE = re.compile(r"^(exec-[0-9a-fA-F-]{36})\.png$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def parse_time(value: str) -> float:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise SystemExit(f"JSON 根节点必须是对象：{path}")
    return value


def collect_bound_paths(value: Any, output: set[str], key: str | None = None) -> None:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            collect_bound_paths(child_value, output, child_key)
        return
    if isinstance(value, list):
        for child in value:
            collect_bound_paths(child, output, key)
        return
    if not isinstance(value, str):
        return
    if key not in {"selected_source", "attempt_sources", "final_path", "output_path"}:
        return
    if value.lower().endswith(".png"):
        output.add(str(Path(value).resolve()).casefold())


def png_metadata(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            if handle.read(8) != PNG_SIGNATURE:
                return None
            length = struct.unpack(">I", handle.read(4))[0]
            chunk_type = handle.read(4)
            if chunk_type != b"IHDR" or length < 8:
                return None
            width, height = struct.unpack(">II", handle.read(8))
    except (OSError, struct.error):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def candidate_record(path: Path) -> dict[str, Any] | None:
    match = TOOL_ID_RE.match(path.name)
    if not match:
        return None
    dimensions = png_metadata(path)
    if dimensions is None:
        return None
    stat = path.stat()
    width, height = dimensions
    return {
        "tool_call_id": match.group(1),
        "selected_source": str(path.resolve()),
        "source_size_bytes": stat.st_size,
        "source_sha256": sha256(path),
        "width": width,
        "height": height,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在图片工具时间窗内确定性恢复唯一、尚未绑定的 imagegen PNG。"
    )
    parser.add_argument("--generated-root", required=True)
    parser.add_argument("--tool-started-at", required=True)
    parser.add_argument("--tool-finished-at", required=True)
    parser.add_argument("--state", help="用于排除已经绑定到其他页面的 PNG")
    parser.add_argument(
        "--session-dir",
        help="可选：若已知当前 Agent 的 generated_images 会话目录，只在该目录搜索",
    )
    parser.add_argument(
        "--tolerance-seconds", type=float, default=5.0, help="时间窗前后容差，默认 5 秒"
    )
    args = parser.parse_args()

    root = Path(args.session_dir or args.generated_root).resolve()
    if not root.is_dir():
        raise SystemExit(f"搜索目录不存在：{root}")

    started = parse_time(args.tool_started_at) - max(args.tolerance_seconds, 0)
    finished = parse_time(args.tool_finished_at) + max(args.tolerance_seconds, 0)
    if finished < started:
        raise SystemExit("工具结束时间早于开始时间")

    bound: set[str] = set()
    if args.state:
        state_path = Path(args.state).resolve()
        collect_bound_paths(read_json(state_path), bound)

    records: list[dict[str, Any]] = []
    for path in root.rglob("*.png"):
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if not (started <= modified <= finished):
            continue
        if str(path.resolve()).casefold() in bound:
            continue
        record = candidate_record(path)
        if record is not None:
            records.append(record)

    records.sort(key=lambda item: (item["mtime_utc"], item["selected_source"]))
    if len(records) == 1:
        output = {
            "status": "recovered",
            "recovery_basis": "unique_unbound_valid_png_in_tool_interval",
            "candidate_count": 1,
            **records[0],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    status = "not_found" if not records else "ambiguous"
    print(
        json.dumps(
            {
                "status": status,
                "recovery_basis": "no_guessing",
                "candidate_count": len(records),
                "candidates": records,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
