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

import materialize_visual_asset as visual_assets
import pipeline_control as pipeline


RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


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


def require_raster(path_value: str, label: str) -> str:
    path = Path(existing_absolute_file(path_value, label))
    if path.suffix.lower() not in RASTER_SUFFIXES:
        raise SystemExit(
            f"{label} 必须是 PNG/JPG/JPEG/WEBP；PDF 等文档不能直接传给 ImageGen。"
            "指定 PDF 页请使用 --document-page-asset /absolute/file.pdf::页码::role"
        )
    return str(path)


def parse_asset(value: str) -> dict[str, str]:
    try:
        path_value, role = value.rsplit("::", 1)
    except ValueError as exc:
        raise SystemExit("--asset 必须使用 /absolute/path::role") from exc
    role = role.strip()
    if not role:
        raise SystemExit("--asset role 不能为空")
    return {
        "path": require_raster(path_value, "Fast8 实际输入资产"),
        "role": role,
    }


def parse_document_page_asset(value: str) -> dict[str, object]:
    try:
        path_value, page_value, role = value.rsplit("::", 2)
    except ValueError as exc:
        raise SystemExit(
            "--document-page-asset 必须使用 /absolute/file.pdf::页码::role"
        ) from exc
    source = Path(existing_absolute_file(path_value, "Fast8 文档页来源"))
    if source.suffix.lower() != ".pdf":
        raise SystemExit("--document-page-asset 当前只接受 PDF")
    try:
        page_number = int(page_value)
    except ValueError as exc:
        raise SystemExit("--document-page-asset 页码必须是正整数") from exc
    if page_number < 1:
        raise SystemExit("--document-page-asset 页码必须是正整数")
    role = role.strip()
    if not role:
        raise SystemExit("--document-page-asset role 不能为空")
    return {
        "source": str(source),
        "role": role,
        "locator": {"page": page_number},
    }


def parse_source_asset_spec(value: str) -> dict[str, object]:
    return visual_assets.parse_spec_json(value)


def global_chrome_assets(
    contract_value: str, page_id: str
) -> tuple[str, list[dict[str, str]]]:
    contract_path = Path(
        existing_absolute_file(contract_value, "Fast8 全稿标题合同")
    )
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Fast8 全稿标题合同无法读取：{contract_path}：{exc}") from exc
    if not isinstance(contract, dict) or contract.get(
        "global_chrome_contract_version"
    ) != 1:
        raise SystemExit("Fast8 全稿标题合同必须为 global_chrome_contract_version=1")
    if (contract.get("authorization") or {}).get("status") != "authorized":
        raise SystemExit("Fast8 全稿标题合同必须已有 status=authorized 的来源授权")
    deck = contract.get("deck_title_system") or {}
    scope = deck.get("scope") or {}
    includes = scope.get("include_page_ids") or []
    excludes = scope.get("exclude_page_ids") or []
    applies = (
        deck.get("enabled") is True
        and (not includes or any(pipeline.page_ids_match(page_id, item) for item in includes))
        and not any(pipeline.page_ids_match(page_id, item) for item in excludes)
    )
    if not applies or (deck.get("logo") or {}).get("required") is not True:
        return str(contract_path), []
    assets_by_tone = ((deck.get("logo") or {}).get("assets_by_tone") or {})
    if not isinstance(assets_by_tone, dict):
        raise SystemExit("Fast8 全稿标题合同要求 Logo，但缺少 assets_by_tone")
    assets: list[dict[str, str]] = []
    for tone in ("dark", "light"):
        item = assets_by_tone.get(tone)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise SystemExit(f"Fast8 全稿标题合同缺少 {tone} Logo 路径")
        assets.append(
            {
                "path": require_raster(item["path"], f"Fast8 {tone} 标题 Logo"),
                "role": f"global_chrome_logo_{tone}",
            }
        )
    return str(contract_path), assets


def append_unique_path(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def append_unique_asset(
    values: list[dict[str, str]], item: dict[str, str]
) -> None:
    if not any(existing["path"] == item["path"] for existing in values):
        values.append(item)


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
    parser.add_argument(
        "--document-page-asset",
        action="append",
        default=[],
        help=(
            "Render one frozen PDF page before manifest creation, as "
            "/absolute/file.pdf::page_number::role"
        ),
    )
    parser.add_argument(
        "--source-asset-spec",
        action="append",
        default=[],
        help=(
            "Generic visual source JSON, for example "
            "{\"source\":\"/a/file.pptx\",\"role\":\"source_slide\","
            "\"locator\":{\"slide\":3}}"
        ),
    )
    parser.add_argument(
        "--global-chrome-contract",
        help=(
            "Existing authorized deck title contract; applicable tone-specific "
            "Logo assets are frozen automatically"
        ),
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

    output = Path(args.output).expanduser()
    if not output.is_absolute():
        raise SystemExit("--output 必须是绝对路径")
    output = output.resolve()

    required = [
        existing_absolute_file(value, "Fast8 必需来源文件")
        for value in args.required_file
    ]
    optional = [
        optional_absolute_path(value, "Fast8 可选来源文件")
        for value in args.optional_file
    ]
    assets = [parse_asset(value) for value in args.asset]
    explicit_paths = [*required, *optional, *[item["path"] for item in assets]]
    if len(explicit_paths) != len(set(explicit_paths)):
        raise SystemExit("来源文件与实际 ImageGen 输入资产不得重复登记")
    source_specs = [
        parse_source_asset_spec(value) for value in args.source_asset_spec
    ]
    source_specs.extend(
        parse_document_page_asset(value) for value in args.document_page_asset
    )
    for spec in source_specs:
        materialized = visual_assets.materialize_visual_asset(
            spec, output.parent / f"{output.stem}.assets"
        )
        source_file = materialized.get("source_file")
        output_path = str(materialized["output_path"])
        if isinstance(source_file, str) and source_file != output_path:
            append_unique_path(required, source_file)
        append_unique_path(required, str(materialized["receipt_path"]))
        append_unique_asset(
            assets,
            {"path": output_path, "role": str(materialized["role"])},
        )
    if args.global_chrome_contract:
        contract_path, contract_assets = global_chrome_assets(
            args.global_chrome_contract, page_id
        )
        append_unique_path(required, contract_path)
        for item in contract_assets:
            append_unique_asset(assets, item)
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
                "page_source_validated": bool(args.page_source),
                "document_pages_materialized": len(args.document_page_asset),
                "source_assets_materialized": len(source_specs),
                "global_chrome_bound": bool(args.global_chrome_contract),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
