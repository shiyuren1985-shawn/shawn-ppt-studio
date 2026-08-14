#!/usr/bin/env python3
"""Normalize one model-authored Fast8 chrome decision into formal v1 JSON.

The model decides whether the frozen page packet authorizes a title system.
This script owns only schema, canonical page/title projection, file identity,
and validation.  It never infers Logo authorization from an asset library,
historical page, or the mere presence of a Logo file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Optional

import pipeline_control as pipeline


DEFAULT_QA_CHECKS = (
    "logo_presence",
    "official_logo_fidelity",
    "title_structure",
    "title_alignment_safe_margin",
    "chrome_weight",
)


def read_object(path: Path, label: str) -> dict[str, Any]:
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


def required_absolute_file(value: Any, label: str) -> Path:
    if isinstance(value, Path):
        raw = str(value)
    elif isinstance(value, str):
        raw = value
    else:
        raw = ""
    if not raw.strip():
        raise SystemExit(f"{label} 缺少非空绝对路径")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise SystemExit(f"{label} 必须是绝对路径：{raw}")
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"{label} 不存在：{path}")
    return path


def explicit_required_flag(
    item: dict[str, Any],
    *,
    policy_sources: list[dict[str, Any]],
    policy_name: str,
    label: str,
) -> bool:
    value = item.get("required")
    if isinstance(value, bool):
        explicit = value
    elif value is not None:
        raise SystemExit(f"{label}.required 必须是 true|false")
    else:
        explicit = None

    policy_value: Any = None
    for source in policy_sources:
        if policy_name in source:
            policy_value = source.get(policy_name)
            break
    mapping = {
        "required": True,
        "optional": False,
        "prohibited": False,
        "not_applicable": False,
    }
    policy_flag: bool | None = None
    if policy_value is not None:
        if not isinstance(policy_value, str) or policy_value not in mapping:
            raise SystemExit(
                f"{policy_name} 只允许 required|optional|prohibited|not_applicable"
            )
        policy_flag = mapping[policy_value]
    if explicit is not None and policy_flag is not None and explicit != policy_flag:
        raise SystemExit(f"{label}.required 与 {policy_name} 冲突")
    result = explicit if explicit is not None else policy_flag
    if result is None:
        raise SystemExit(
            f"{label}.required 缺失；规范化器不会根据资产存在或历史页面猜测授权"
        )
    return result


def normalize_logo_assets(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise SystemExit("标题系统要求 Logo 时必须提供 assets_by_tone")
    result: dict[str, dict[str, Any]] = {}
    for tone in ("dark", "light"):
        item = raw.get(tone)
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict):
            raise SystemExit(
                f"logo.assets_by_tone.{tone} 必须是路径字符串或对象"
            )
        path = required_absolute_file(item.get("path"), f"{tone} 标题 Logo")
        actual_sha = file_sha256(path)
        supplied_sha = item.get("sha256")
        if supplied_sha is not None and supplied_sha != actual_sha:
            raise SystemExit(f"{tone} 标题 Logo SHA-256 不匹配：{path}")
        result[tone] = {
            **item,
            "path": str(path),
            "sha256": actual_sha,
        }
    return result


def normalize_contract(
    raw: dict[str, Any],
    *,
    page_id: str,
    canonical_title: str,
    source_packet: Path,
    page_title_map: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    authorization = raw.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("status") != "authorized":
        raise SystemExit(
            "只有模型明确输出 authorization.status=authorized 时才允许建立标题合同"
        )
    raw_deck = raw.get("deck_title_system")
    if raw_deck is None:
        raw_deck = {}
    if not isinstance(raw_deck, dict):
        raise SystemExit("deck_title_system 必须是对象")
    deck = dict(raw_deck)
    # Accept the common compact/loose compiler shape, but keep semantic
    # authorization explicit.  Shape can be repaired by script; policy cannot.
    for field in (
        "logo",
        "main_title",
        "subtitle_policy",
        "prompt_briefs",
        "qa_required",
        "qa_reference_path",
        "qa_checks",
    ):
        if field not in deck and field in raw:
            deck[field] = raw[field]

    enabled = deck.get("enabled", True)
    if enabled is not True:
        raise SystemExit(
            "不适用当前页的标题系统不应创建 global_chrome_contract"
        )
    scope = deck.get("scope") or {}
    if not isinstance(scope, dict):
        raise SystemExit("deck_title_system.scope 必须是对象")
    includes = scope.get("include_page_ids") or (
        list(page_title_map) if page_title_map else [page_id]
    )
    excludes = scope.get("exclude_page_ids") or []
    if not isinstance(includes, list) or not isinstance(excludes, list):
        raise SystemExit("deck_title_system.scope include/exclude 必须是数组")
    page_key = pipeline.canonical_page_id(page_id)
    if page_key not in {pipeline.canonical_page_id(value) for value in includes}:
        raise SystemExit("标题合同 scope 未命中当前页")
    if page_key in {pipeline.canonical_page_id(value) for value in excludes}:
        raise SystemExit("标题合同 scope 明确排除了当前页")
    normalized_page_title_map: Optional[dict[str, str]] = None
    if page_title_map is not None:
        if not page_title_map or not all(
            isinstance(key, str)
            and key.strip()
            and isinstance(value, str)
            and value.strip()
            for key, value in page_title_map.items()
        ):
            raise SystemExit("--page-title-map-json 必须是非空页码到标题字符串对象")
        normalized_page_title_map = {
            str(key).strip(): str(value).strip()
            for key, value in page_title_map.items()
        }
        mapped_keys = {
            pipeline.canonical_page_id(value) for value in normalized_page_title_map
        }
        included_keys = {pipeline.canonical_page_id(value) for value in includes}
        if mapped_keys != included_keys:
            raise SystemExit("页级标题映射必须逐页等于标题合同 include_page_ids")
        if page_key not in mapped_keys:
            raise SystemExit("页级标题映射未包含当前锚点页")

    semantic_basis = raw.get("title_authorization") or raw.get(
        "normalization_basis"
    )
    if semantic_basis is None:
        semantic_basis = deck.get("title_authorization") or {}
    if not isinstance(semantic_basis, dict):
        raise SystemExit("title_authorization/normalization_basis 必须是对象")
    policy_sources = [semantic_basis, raw, deck]

    logo = deck.get("logo") or {}
    title = deck.get("main_title") or {}
    if not isinstance(logo, dict) or not isinstance(title, dict):
        raise SystemExit("deck_title_system.logo/main_title 必须是对象")
    logo_required = explicit_required_flag(
        logo,
        policy_sources=policy_sources,
        policy_name="logo_policy",
        label="deck_title_system.logo",
    )
    title_required = explicit_required_flag(
        title,
        policy_sources=policy_sources,
        policy_name="main_title_policy",
        label="deck_title_system.main_title",
    )

    normalized_logo: dict[str, Any] = {"required": logo_required}
    if logo_required:
        normalized_logo["assets_by_tone"] = normalize_logo_assets(
            logo.get("assets_by_tone")
        )
    # When Logo is optional/prohibited, do not carry unused library assets into
    # the formal contract.  Presence is not authorization.
    for field in ("position", "alignment", "safe_margin", "size_policy"):
        if field in logo:
            normalized_logo[field] = logo[field]

    normalized_title = dict(title)
    normalized_title["required"] = title_required
    normalized_title["match_mode"] = "approximate"
    if title_required:
        if normalized_page_title_map is not None:
            anchor_matches = [
                value
                for key, value in normalized_page_title_map.items()
                if pipeline.page_ids_match(key, page_id)
            ]
            if len(anchor_matches) != 1:
                raise SystemExit("页级标题映射必须唯一命中当前锚点页")
            if canonical_title.strip() and canonical_title.strip() != anchor_matches[0]:
                raise SystemExit("canonical_title 与页级标题映射中的锚点标题冲突")
            normalized_title.pop("text", None)
            normalized_title["text_by_page"] = normalized_page_title_map
        else:
            if not canonical_title.strip():
                raise SystemExit("标题系统要求主标题时 canonical_title 不能为空")
            normalized_title["text"] = canonical_title.strip()
    else:
        normalized_title.pop("text", None)
        normalized_title.pop("text_by_page", None)

    briefs = deck.get("prompt_briefs") or {}
    if not isinstance(briefs, dict):
        raise SystemExit("deck_title_system.prompt_briefs 必须是对象")
    normalized_briefs: dict[str, str] = {}
    for locale in ("zh", "en"):
        value = briefs.get(locale)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"prompt_briefs.{locale} 必须是非空字符串")
        value = " ".join(value.split())
        if len(value) > 360:
            raise SystemExit(f"prompt_briefs.{locale} 超过 360 字")
        normalized_briefs[locale] = value

    qa_required = deck.get("qa_required", True)
    if not isinstance(qa_required, bool):
        raise SystemExit("deck_title_system.qa_required 必须是 true|false")
    if (logo_required or title_required) and not qa_required:
        raise SystemExit("标题或 Logo 为必需时 qa_required 不能为 false")
    checks = deck.get("qa_checks") or list(DEFAULT_QA_CHECKS)
    if not isinstance(checks, list) or not checks or not all(
        isinstance(item, str) and item.strip() for item in checks
    ):
        raise SystemExit("deck_title_system.qa_checks 必须是非空字符串数组")

    normalized_deck: dict[str, Any] = {
        "enabled": True,
        "scope": {
            "include_page_ids": (
                list(normalized_page_title_map)
                if normalized_page_title_map is not None
                else [page_id]
            ),
            "exclude_page_ids": [],
            "special_page_ids": [],
        },
        "logo": normalized_logo,
        "main_title": normalized_title,
        "subtitle_policy": deck.get("subtitle_policy", "source_exact_only_optional"),
        "prompt_briefs": normalized_briefs,
        "qa_required": qa_required,
        "qa_checks": [str(item).strip() for item in checks],
    }
    if "hierarchy" in deck:
        normalized_deck["hierarchy"] = deck["hierarchy"]
    qa_reference = deck.get("qa_reference_path")
    if isinstance(qa_reference, str) and qa_reference.strip():
        candidate = Path(qa_reference).expanduser()
        if (
            candidate.is_absolute()
            and candidate.is_file()
            and candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ):
            normalized_deck["qa_reference_path"] = str(candidate.resolve())

    source_packet = required_absolute_file(source_packet, "Fast8 frozen packet")
    normalized: dict[str, Any] = {
        "global_chrome_contract_version": pipeline.GLOBAL_CHROME_CONTRACT_VERSION,
        "authorization": {
            "status": "authorized",
            "source_kind": "authoritative_outline",
            "source_path": str(source_packet),
            "source_sha256": file_sha256(source_packet),
            **(
                {"basis": authorization["basis"]}
                if isinstance(authorization.get("basis"), str)
                and authorization.get("basis").strip()
                else {}
            ),
        },
        "deck_title_system": normalized_deck,
        "normalization_provenance": {
            "owner": "normalize_fast8_chrome_contract.py",
            "schema_only": True,
            "authorization_inferred_from_asset_presence": False,
            "page_id": page_id,
            **(
                {"page_ids": list(normalized_page_title_map)}
                if normalized_page_title_map is not None
                else {}
            ),
        },
    }
    if isinstance(raw.get("contract_id"), str) and raw.get("contract_id").strip():
        normalized["contract_id"] = raw["contract_id"].strip()
    return normalized


def validated_atomic_write(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == payload:
        pipeline.read_global_chrome_contract(path)
        return "already_normalized"
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        pipeline.read_global_chrome_contract(temporary_path)
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return "normalized"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--canonical-title", required=True)
    parser.add_argument(
        "--page-title-map-json",
        help=(
            "可选：多页标题系统的页码到逐字标题对象；提供后 scope 必须逐页匹配，"
            "并保留一个共享 chrome 合同"
        ),
    )
    parser.add_argument("--source-packet", required=True)
    args = parser.parse_args()

    input_path = required_absolute_file(args.input, "raw global chrome contract")
    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        raise SystemExit("--output 必须是绝对路径")
    output_path = output_path.resolve()
    page_id = args.page_id.strip()
    if not page_id:
        raise SystemExit("--page-id 不能为空")
    page_title_map = None
    if args.page_title_map_json:
        try:
            page_title_map = json.loads(args.page_title_map_json)
        except json.JSONDecodeError as exc:
            raise SystemExit("--page-title-map-json 不是有效 JSON") from exc
        if not isinstance(page_title_map, dict):
            raise SystemExit("--page-title-map-json 必须是对象")
    normalized = normalize_contract(
        read_object(input_path, "raw global chrome contract"),
        page_id=page_id,
        canonical_title=args.canonical_title,
        source_packet=Path(args.source_packet),
        page_title_map=page_title_map,
    )
    status = validated_atomic_write(output_path, normalized)
    print(
        json.dumps(
            {
                "status": status,
                "output": str(output_path),
                "sha256": file_sha256(output_path),
                "page_id": page_id,
                "logo_required": normalized["deck_title_system"]["logo"]["required"],
                "main_title_required": normalized["deck_title_system"]["main_title"]["required"],
                "live_outline_read": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
