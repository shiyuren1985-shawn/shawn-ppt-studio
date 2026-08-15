#!/usr/bin/env python3
"""Build the minimal Fast8 preflight manifest deterministically.

This keeps startup JSON syntax and page-id handling out of the model's critical
path.  Source hashing and formal validation remain owned by init_task_dir.py.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

import pipeline_control as pipeline


def existing_absolute_file(value: str, label: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SystemExit(f"{label} 必须是绝对路径：{value}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise SystemExit(f"{label} 不存在：{resolved}")
    return str(resolved)


def optional_absolute_path(value: str, label: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SystemExit(f"{label} 必须是绝对路径：{value}")
    return str(path.resolve())


def parse_asset(value: str) -> dict[str, str]:
    try:
        path_value, role = value.rsplit("::", 1)
    except ValueError as exc:
        raise SystemExit("--asset 必须使用 /absolute/path::role") from exc
    role = role.strip()
    if not role:
        raise SystemExit("--asset role 不能为空")
    return {
        "path": existing_absolute_file(path_value, "Fast8 实际输入资产"),
        "role": role,
    }


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


def validate_page_source(path: Path, page_id: str) -> None:
    """Fail before formal directory creation when an outline lacks the page."""

    if path.suffix.lower() in {".md", ".markdown", ".txt"}:
        pipeline.extract_markdown_pages(path.read_text(encoding="utf-8"), [page_id])
    else:
        pipeline.extract_relevant_source_content(path, [page_id])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--required-file", action="append", default=[])
    parser.add_argument("--optional-file", action="append", default=[])
    parser.add_argument(
        "--asset",
        action="append",
        default=[],
        help="Actual ImageGen input asset as /absolute/path::role",
    )
    parser.add_argument("--request-started-at")
    parser.add_argument(
        "--tone",
        choices=("light", "dark"),
        help=(
            "Optional explicit user background-tone override for all A-H seats. "
            "Omit to keep the default mixed dark/light Fast8 matrix."
        ),
    )
    parser.add_argument(
        "--page-source",
        help=(
            "Authoritative multi-page source whose requested page must exist; "
            "must also be listed with --required-file"
        ),
    )
    parser.add_argument(
        "--slide-identity-file",
        help=(
            "Optional independent deck/slide UID file. It is recorded for source "
            "snapshot metadata only and is not an ImageGen input asset."
        ),
    )
    args = parser.parse_args()

    task_name = args.task_name.strip()
    page_id = args.page_id.strip()
    if not task_name:
        raise SystemExit("--task-name 不能为空")
    if not page_id:
        raise SystemExit("--page-id 不能为空")

    required = [
        existing_absolute_file(value, "Fast8 必需来源文件")
        for value in args.required_file
    ]
    optional = [
        optional_absolute_path(value, "Fast8 可选来源文件")
        for value in args.optional_file
    ]
    assets = [parse_asset(value) for value in args.asset]
    all_paths = [*required, *optional, *[item["path"] for item in assets]]
    if len(all_paths) != len(set(all_paths)):
        raise SystemExit("来源文件与实际 ImageGen 输入资产不得重复登记")
    page_source = None
    if args.page_source:
        page_source = Path(
            existing_absolute_file(args.page_source, "Fast8 页码权威来源")
        )
        if str(page_source) not in required:
            raise SystemExit("--page-source 必须同时作为 --required-file 登记")
        validate_page_source(page_source, page_id)

    identity_sources = []
    for required_path in required:
        identity = pipeline.slide_identity_from_file(Path(required_path), [page_id])
        if identity is not None:
            identity_sources.append(Path(required_path).resolve())
    if len(identity_sources) > 1:
        raise SystemExit(
            "Fast8 必需来源中存在多个启用的 slide identity 权威文件；"
            "每次新运行只能有一份权威原大纲"
        )
    authoritative_identity_source = identity_sources[0] if identity_sources else None
    if authoritative_identity_source is not None:
        if page_source is None:
            page_source = authoritative_identity_source
            validate_page_source(page_source, page_id)
        elif page_source.resolve() != authoritative_identity_source:
            raise SystemExit(
                "--page-source 必须与启用 slide_identity_required 的权威原大纲一致"
            )

    started_at = args.request_started_at
    if started_at is None:
        started_at = datetime.now(timezone.utc).isoformat()
    else:
        started_at = started_at.strip()
        normalized = started_at[:-1] + "+00:00" if started_at.endswith("Z") else started_at
        try:
            datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise SystemExit("--request-started-at 不是合法 ISO 时间") from exc

    output = Path(args.output).expanduser()
    if not output.is_absolute():
        raise SystemExit("--output 必须是绝对路径")
    output = output.resolve()
    manifest = {
        "fast8_preflight_manifest_version": 1,
        "run_mode": "fast_8x1_diverse",
        "task_name": task_name,
        "timestamp_policy": "script_owned",
        "request_started_at": started_at,
        "page_ids": [page_id],
        "required_files": required,
        "optional_files": optional,
        "asset_items": assets,
    }
    if args.tone:
        manifest["tone_overrides"] = {
            style: args.tone for style in "ABCDEFGH"
        }
    if args.slide_identity_file:
        identity_file = Path(
            existing_absolute_file(
                args.slide_identity_file, "Fast8 slide identity 文件"
            )
        ).resolve()
        if page_source is None or identity_file != page_source:
            raise SystemExit(
                "新运行不接受独立 slide identity 文件；"
                "请把 deck_uid/slide_uids 直接写入 --page-source 原大纲"
            )
        manifest["slide_identity_file"] = str(identity_file)
    elif authoritative_identity_source is not None:
        manifest["slide_identity_file"] = str(authoritative_identity_source)
    atomic_write(output, manifest)
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(output),
                "task_name": task_name,
                "page_id": page_id,
                "request_started_at": started_at,
                "tone": args.tone,
                "page_source_validated": page_source is not None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
