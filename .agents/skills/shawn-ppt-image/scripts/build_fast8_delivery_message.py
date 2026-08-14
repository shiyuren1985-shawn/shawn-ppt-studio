#!/usr/bin/env python3
"""Build the deterministic link-only Fast8 delivery message from formal state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


STYLES = tuple("ABCDEFGH")
ALLOWED_MODES = {"fast_8x1_diverse", "quick_8x1"}


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"无法读取状态：{path}：{exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("状态文件必须是 JSON 对象")
    return value


def require_project_file(value: object, project_dir: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise SystemExit(f"缺少 {label} 路径")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(project_dir)
    except ValueError as exc:
        raise SystemExit(f"{label} 不在当前 project_dir：{path}") from exc
    if not path.is_file():
        raise SystemExit(f"{label} 文件不存在：{path}")
    return path


def build_message(state: dict, state_path: Path) -> tuple[Path, str]:
    if state.get("run_mode") not in ALLOWED_MODES:
        raise SystemExit("link-only 交付生成器只适用于 Fast8 或 Quick8")
    project_dir = Path(str(state.get("project_dir") or state_path.parents[1])).resolve()
    page_id = str(state.get("anchor_page_id") or "")
    if not page_id:
        raise SystemExit("状态缺少 anchor_page_id")
    overview = require_project_file(
        (state.get("overview") or {}).get("final_path"), project_dir, "正式总览"
    )
    links = [("总览", overview)]
    styles = state.get("styles") or {}
    for style in STYLES:
        record = (((styles.get(style) or {}).get("pages") or {}).get(page_id) or {})
        if record.get("status") != "candidate_ready":
            raise SystemExit(f"style_{style}/{page_id} 尚未 candidate_ready")
        candidate = require_project_file(record.get("final_path"), project_dir, f"style_{style}")
        links.append((style, candidate))
    overview_link = f"[{links[0][0]}](<{links[0][1]}>)"
    candidate_links = " ".join(
        f"[{label}](<{path}>)" for label, path in links[1:]
    )
    text = f"{overview_link}\n{candidate_links}\n"
    output = project_dir / "state" / "delivery_message.md"
    output.write_text(text, encoding="utf-8")
    return output, text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    state_path = Path(args.state).expanduser().resolve()
    output, text = build_message(read_json(state_path), state_path)
    print(
        json.dumps(
            {"status": "ok", "delivery_message": str(output), "link_count": 9, "bytes": len(text.encode("utf-8"))},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
