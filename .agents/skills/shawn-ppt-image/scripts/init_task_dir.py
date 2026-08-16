#!/usr/bin/env python3
"""为 Shawn-PPT-image 新运行创建独立、分类清晰的任务目录。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import hashlib
from pathlib import Path

import pipeline_control as pipeline


STANDARD_DIRS = (
    "overview",
    "origin_image",
    "style_jobs",
    "style_jobs/results",
    "visual_qa_jobs",
    "visual_qa_jobs/results",
    "content_contracts",
    "references",
    "state",
)
SELECTED_STYLE_EXPANSION_DIRS = (
    "page_jobs",
    "page_jobs/repair_jobs",
    "state/director_inputs",
)
TASK_INIT_CONTRACT_VERSION = 1
FAST8_PREFLIGHT_MANIFEST_VERSION = 1
FAST8_STARTUP_CONTRACT_VERSION = 1
FAST8_IMAGEGEN_SLOT_POLICY = "worker_jit_v1"
MONITORING_CONFIG_VERSION = 1
MONITORING_CONFIG_FILENAME = ".shawn-ppt-image-monitoring.json"
USER_MONITORING_CONFIG = Path.home() / ".codex" / "shawn-ppt-image-monitoring.json"
SELECTED_STYLE_EXPANSION_MODE = "selected_style_expansion"
SELECTED_STYLE_STARTUP_CONTRACT_VERSION = 1
SELECTED_STYLE_PACKET_CONTRACT_VERSION = 2


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def normalize_task_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    chars = [ch if ch.isalnum() or ch in "-_" else "_" for ch in normalized]
    slug = re.sub(r"_+", "_", "".join(chars)).strip("_-")
    if not slug:
        raise SystemExit("task-name 规范化后为空")
    return slug[:120]


def validate_task_name(value: str) -> None:
    required = {
        "页码或页码范围（如 P16、P02-P08）": r"(?i)(?:^|[_-])P\d{1,3}(?:-P?\d{1,3})?(?:[_-]|$)",
        "任务类型（4x3 或 8x1）": r"(?i)(?:^|[_-])(?:4x3|8x1)(?:[_-]|$)",
        "8 位日期（YYYYMMDD）": r"(?:^|[_-])\d{8}(?:[_-]|$)",
    }
    missing = [label for label, pattern in required.items() if not re.search(pattern, value)]
    if missing:
        raise SystemExit("task-name 缺少：" + "、".join(missing))


def next_available_path(output_root: Path, task_name: str) -> Path:
    candidate = output_root / task_name
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = output_root / f"{task_name}_{index:02d}"
        if not candidate.exists():
            return candidate
        index += 1


def create_standard_dirs(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    for relative in STANDARD_DIRS:
        (project_dir / relative).mkdir(parents=True, exist_ok=True)


def create_selected_style_dirs(project_dir: Path) -> None:
    for relative in SELECTED_STYLE_EXPANSION_DIRS:
        (project_dir / relative).mkdir(parents=True, exist_ok=True)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_fast8_overview_python(value: str) -> Path:
    """Bind the one Pillow-capable runtime before a formal Fast8 directory exists."""

    python = Path(value).expanduser().resolve()
    if not python.is_file():
        raise SystemExit(f"Fast8 总览 Python 不存在：{python}")
    check = subprocess.run(
        [str(python), "-c", "from PIL import Image"],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if check.returncode != 0:
        raise SystemExit(
            "Fast8 总览 Python 未通过 Pillow 预检："
            + (check.stderr.strip() or check.stdout.strip() or str(python))
        )
    return python


def atomic_write_json(path: Path, value: dict[str, object]) -> None:
    """Create one immutable JSON artifact without exposing a partial write."""

    if path.exists():
        raise SystemExit(f"拒绝覆盖既有文件：{path}")
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def normalize_selected_style(value: str | None, *, allow_anchorless_default: bool = False) -> str:
    style = str(value or "").strip().upper()
    if not style and allow_anchorless_default:
        return "A"
    if style not in tuple("ABCDEFGH"):
        raise SystemExit("--selected-style 必须是 A-H")
    return style


def normalize_expansion_page_ids(value: str | None) -> list[str]:
    raw = [item.strip() for item in str(value or "").split(",") if item.strip()]
    if not raw:
        raise SystemExit("--page-ids 必须是非空的逗号分隔页码列表")
    normalized: list[str] = []
    for item in raw:
        match = re.fullmatch(
            r"(?i)(?:p(?:age)?|slide)?[-_ ]*0*(\d+)", item
        )
        if not match or int(match.group(1)) < 1:
            raise SystemExit(f"--page-ids 包含无效页码：{item}")
        normalized.append(f"{int(match.group(1)):02d}")
    if len(normalized) != len(set(normalized)):
        raise SystemExit("--page-ids 规范化后包含重复页码")
    return normalized


def validate_expansion_source(value: str | None) -> Path:
    if not value:
        raise SystemExit("selected_style_expansion 必须传入 --source-file")
    source = Path(value).expanduser()
    if not source.is_absolute():
        raise SystemExit("--source-file 必须是绝对路径")
    source = source.resolve()
    if not source.is_file():
        raise SystemExit(f"扩页权威源不存在：{source}")
    if source.suffix.lower() not in {".md", ".markdown", ".json", ".pptx"}:
        raise SystemExit("--source-file 只接受 Markdown、JSON 或 PPTX")
    return source


EXPANSION_SCOPE_PAGE_LIST_KEYS = {
    "include_page_ids", "exclude_page_ids", "applies_to_page_ids", "page_ids"
}
EXPANSION_PAGE_TOKEN = re.compile(r"(?i)\bP(?:age)?[-_ ]*0*(\d+)\b")


def expansion_page_alias(value: object) -> str | None:
    match = re.fullmatch(
        r"(?i)(?:p(?:age)?|slide)?[-_ ]*0*(\d+)", str(value).strip()
    )
    if not match or int(match.group(1)) < 1:
        return None
    return f"{int(match.group(1)):02d}"


def project_deck_contract_value(value: object, target_page_ids: list[str]) -> object:
    """Narrow deck JSON scope mechanically without interpreting title semantics."""

    target = set(target_page_ids)
    if isinstance(value, list):
        return [project_deck_contract_value(item, target_page_ids) for item in value]
    if not isinstance(value, dict):
        return value
    keys = list(value)
    if keys and all(expansion_page_alias(key) is not None for key in keys):
        return {
            key: project_deck_contract_value(item, target_page_ids)
            for key, item in value.items()
            if expansion_page_alias(key) in target
        }
    projected: dict[str, object] = {}
    for key, item in value.items():
        page_key = expansion_page_alias(key)
        if page_key is not None:
            if page_key in target:
                projected[key] = project_deck_contract_value(item, target_page_ids)
            continue
        if key in EXPANSION_SCOPE_PAGE_LIST_KEYS:
            if not isinstance(item, list):
                raise SystemExit(f"deck contract {key} 必须是页码数组")
            projected[key] = [
                raw for raw in item
                if expansion_page_alias(raw) in target
            ]
            continue
        if key == "scope" and isinstance(item, dict):
            scoped: dict[str, object] = {}
            for scope_key, scope_item in item.items():
                if scope_key in EXPANSION_SCOPE_PAGE_LIST_KEYS:
                    if not isinstance(scope_item, list):
                        raise SystemExit(f"deck contract scope.{scope_key} 必须是页码数组")
                    scoped[scope_key] = [
                        raw for raw in scope_item
                        if expansion_page_alias(raw) in target
                    ]
                elif not any(
                    f"{int(match.group(1)):02d}" not in target
                    for match in EXPANSION_PAGE_TOKEN.finditer(
                        json.dumps(scope_item, ensure_ascii=False)
                    )
                ):
                    scoped[scope_key] = project_deck_contract_value(
                        scope_item, target_page_ids
                    )
            projected[key] = scoped
            continue
        projected[key] = project_deck_contract_value(item, target_page_ids)
    return projected


def freeze_expansion_supporting_text(
    path: Path, source_scope: str, page_ids: list[str]
) -> tuple[str, str | None]:
    try:
        exact_text = (
            path.read_text(encoding="utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
    except UnicodeError as exc:
        raise SystemExit(f"扩页补充来源必须是 UTF-8 文本：{path}") from exc
    projection_sha256 = None
    if source_scope == "deck" and path.suffix.lower() == ".json":
        try:
            source_value = json.loads(exact_text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"deck JSON contract 无法解析：{path}") from exc
        projected = project_deck_contract_value(source_value, page_ids)
        exact_text = json.dumps(projected, ensure_ascii=False, indent=2) + "\n"
        projection_sha256 = hashlib.sha256(exact_text.encode("utf-8")).hexdigest()
    if source_scope == "deck":
        leaked = sorted({
            f"{int(match.group(1)):02d}"
            for match in EXPANSION_PAGE_TOKEN.finditer(exact_text)
            if f"{int(match.group(1)):02d}" not in set(page_ids)
        })
        if leaked:
            raise SystemExit(
                "deck shared source 投影后仍含未请求页 ID：" + ",".join(leaked)
            )
    return exact_text, projection_sha256


def validate_expansion_supporting_sources(
    values: list[str] | None,
    authoritative_source: Path,
    page_ids: list[str],
) -> list[dict[str, object]]:
    """Freeze explicitly scoped text evidence without broadcasting page notes."""

    records: list[dict[str, object]] = []
    seen = {str(authoritative_source.resolve())}
    for index, value in enumerate(values or []):
        if "::" not in value:
            raise SystemExit(
                f"--supporting-source[{index}] 必须显式使用 "
                "绝对路径::P02,P05 或 绝对路径::deck"
            )
        path_value, scope_value = value.rsplit("::", 1)
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            raise SystemExit(f"--supporting-source[{index}] 必须是绝对路径")
        path = path.resolve()
        if not path.is_file():
            raise SystemExit(f"扩页补充来源不存在：{path}")
        if path.suffix.lower() not in {".md", ".markdown", ".txt", ".json"}:
            raise SystemExit("--supporting-source 只接受可冻结文本的 Markdown、TXT 或 JSON")
        if str(path) in seen:
            raise SystemExit("--supporting-source 不得重复或等于 --source-file")
        seen.add(str(path))
        scope = scope_value.strip()
        if scope.lower() == "deck":
            source_scope = "deck"
            applies_to_page_ids = list(page_ids)
        else:
            source_scope = "page"
            applies_to_page_ids = normalize_expansion_page_ids(scope)
            if any(page_id not in page_ids for page_id in applies_to_page_ids):
                raise SystemExit(
                    f"--supporting-source[{index}] applies_to_page_ids 超出本轮 page_order"
                )
        exact_text, projection_sha256 = freeze_expansion_supporting_text(
            path, source_scope, page_ids
        )
        records.append({
            "path": str(path), "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path), "exact_text": exact_text,
            "source_scope": source_scope,
            "applies_to_page_ids": applies_to_page_ids,
            "source_role": (
                "deck_shared_rule" if source_scope == "deck"
                else "page_supporting_evidence"
            ),
            **({
                "projection_kind": "target_page_scope_intersection_v1",
                "projection_sha256": projection_sha256,
            } if projection_sha256 else {}),
        })
    return records


def validate_expansion_anchors(values: list[str] | None) -> list[dict[str, object]]:
    raw = values or []
    if len(raw) > 2:
        raise SystemExit("selected_style_expansion 最多传入 2 个 --anchor")
    if not raw:
        return []
    anchors: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if "::" not in item:
            raise SystemExit(
                f"--anchor[{index}] 格式必须为绝对路径::primary|supporting"
            )
        path_value, role_value = item.rsplit("::", 1)
        role = role_value.strip().lower()
        if role not in {"primary", "supporting"}:
            raise SystemExit(f"--anchor[{index}] role 必须是 primary|supporting")
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            raise SystemExit(f"--anchor[{index}] 必须使用绝对路径")
        path = path.resolve()
        if not path.is_file():
            raise SystemExit(f"扩页锚点不存在：{path}")
        key = str(path)
        if key in seen:
            raise SystemExit("--anchor 不得重复使用同一路径")
        seen.add(key)
        anchors.append(
            {
                "path": key,
                "role": role,
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    if sum(item["role"] == "primary" for item in anchors) != 1:
        raise SystemExit("--anchor 必须且只能包含一个 primary")
    return sorted(anchors, key=lambda item: 0 if item["role"] == "primary" else 1)


def extract_expansion_pages(source: Path, page_ids: list[str]) -> dict[str, object]:
    """Reuse the shared source extractor; do not create a second page parser."""

    from pipeline_control import extract_relevant_source_content

    return extract_relevant_source_content(source, page_ids, include_exact=True)


def resolve_expansion_overview_python(value: str | None) -> Path:
    """Use the current interpreter only when it already has Pillow."""

    candidate = value or sys.executable
    try:
        return validate_fast8_overview_python(candidate)
    except SystemExit as exc:
        if value:
            raise
        raise SystemExit(
            "当前 Python 无法导入 Pillow；请显式传入可用的 --overview-python"
        ) from exc


def write_selected_style_initial_artifacts(
    project_dir: Path,
    *,
    selected_style: str,
    page_ids: list[str],
    source: Path,
    extracted: dict[str, object],
    supporting_sources: list[dict[str, object]],
    anchors: list[dict[str, object]],
    anchor_approval_scope: str,
    overview_python: Path,
    process_started_at: str,
    preflight_resolved_at: str,
) -> tuple[Path, Path]:
    packet_path = (
        project_dir
        / "state"
        / "director_inputs"
        / "authoritative_expansion_packet.json"
    )
    source_record = {
        "path": str(source),
        "size_bytes": source.stat().st_size,
        "sha256": file_sha256(source),
    }
    page_supporting = [
        item for item in supporting_sources if item["source_scope"] == "page"
    ]
    deck_shared_sources = [
        item for item in supporting_sources if item["source_scope"] == "deck"
    ]
    packet_pages = []
    for page in extracted["pages"]:
        page_id = str(page["page_id"])
        packet_pages.append({
            **page,
            "supporting_sources": [
                item for item in page_supporting
                if page_id in item["applies_to_page_ids"]
            ],
        })
    packet = {
        "selected_style_expansion_packet_contract_version": (
            SELECTED_STYLE_PACKET_CONTRACT_VERSION
        ),
        "run_mode": SELECTED_STYLE_EXPANSION_MODE,
        "project_dir": str(project_dir.resolve()),
        "page_order": page_ids,
        "selected_style": selected_style,
        "visual_family_source": (
            "raster_anchor" if anchors else "director_defined_text_family"
        ),
        "anchor_approval_scope": anchor_approval_scope,
        "authoritative_source": source_record,
        "page_extractor": {
            key: value
            for key, value in extracted.items()
            if key not in {"pages", "normalized_text", "deck_context"}
        },
        "deck_context": extracted.get("deck_context"),
        "pages": packet_pages,
        "deck_shared_sources": deck_shared_sources,
        "style_anchors": anchors,
        "frozen_at": preflight_resolved_at,
    }
    atomic_write_json(packet_path, packet)
    packet_sha256 = file_sha256(packet_path)
    run_seed = "\n".join(
        (
            str(project_dir.resolve()),
            process_started_at,
            selected_style,
            ",".join(page_ids),
            source_record["sha256"],
            packet_sha256,
        )
    )
    run_id = "selected-style-" + hashlib.sha256(
        run_seed.encode("utf-8")
    ).hexdigest()[:20]

    def event(sequence: int, name: str, occurred_at: str) -> dict[str, object]:
        return {
            "sequence": sequence,
            "name": name,
            "occurred_at": occurred_at,
            "recorded_at": preflight_resolved_at,
            "style": selected_style,
            "page_id": None,
            "action": None,
            "details": {
                "source": "init_task_dir",
                "startup_contract_version": (
                    SELECTED_STYLE_STARTUP_CONTRACT_VERSION
                ),
            },
        }

    page_records = {
        item["page_id"]: {
            "page_id": item["page_id"],
            "status": "pending",
            "qa_stage": None,
            "attempts": [],
            "selected_source": None,
            "source_record": item,
        }
        for item in extracted["pages"]
    }
    state_path = project_dir / "state" / "selected_style_run_state.json"
    state = {
        "run_id": run_id,
        "run_mode": SELECTED_STYLE_EXPANSION_MODE,
        "selected_style_startup_contract_version": (
            SELECTED_STYLE_STARTUP_CONTRACT_VERSION
        ),
        "phase": SELECTED_STYLE_EXPANSION_MODE,
        "status": "running",
        "project_dir": str(project_dir.resolve()),
        "selected_style": selected_style,
        "visual_family_source": (
            "raster_anchor" if anchors else "director_defined_text_family"
        ),
        "anchor_approval_scope": anchor_approval_scope,
        "page_order": page_ids,
        "pages": page_records,
        "source_packet_path": str(packet_path),
        "source_packet_sha256": packet_sha256,
        "source": {
            **source_record,
            "page_content_sha256": extracted["sha256"],
            "extractor": extracted["extractor"],
            "extractor_version": extracted["extractor_version"],
        },
        "supporting_sources": [
            {key: value for key, value in item.items() if key != "exact_text"}
            for item in supporting_sources
        ],
        "style_anchors": anchors,
        "style_anchors_sha256": hashlib.sha256(
            json.dumps(
                anchors,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "preflight": {
            "status": "resolved",
            "source_packet_path": str(packet_path),
            "source_packet_sha256": packet_sha256,
        },
        "overview_runtime": {
            "python": str(overview_python),
            "pillow_preflight": "pass",
            "binding_policy": "startup_bound_reuse_for_formal_overview",
        },
        "timing": {
            "process_started_at": process_started_at,
            "preflight_resolved_at": preflight_resolved_at,
        },
        "events": [
            event(1, "process_started", process_started_at),
            event(2, "preflight_resolved", preflight_resolved_at),
        ],
        "scheduler": {
            "imagegen_slot_policy": FAST8_IMAGEGEN_SLOT_POLICY,
            "active_child_limit": 8,
            "active_actions": [],
            "ready_queue": [],
            "recovery_queue": [],
        },
        "overview": {"status": "pending", "path": None},
    }
    atomic_write_json(state_path, state)
    return packet_path, state_path


def write_fast8_initial_state(
    project_dir: Path,
    preflight_manifest: dict[str, object],
    overview_python: Path,
    process_started_at: str,
    preflight_resolved_at: str,
) -> Path:
    """Atomically create the complete pre-job Fast8 state once."""

    page_ids = preflight_manifest.get("page_ids")
    if not isinstance(page_ids, list) or len(page_ids) != 1:
        raise SystemExit("新 Fast8 单页探索的预备清单必须且只能包含一个 page_id")
    page_id = str(page_ids[0])
    state_path = project_dir / "state" / "style_run_state.json"
    if state_path.exists():
        raise SystemExit(f"拒绝覆盖既有 Fast8 初始状态：{state_path}")
    run_seed = f"{project_dir.resolve()}\n{process_started_at}\n{page_id}"
    run_id = "fast8-" + hashlib.sha256(run_seed.encode("utf-8")).hexdigest()[:20]
    request_started_at = str(
        preflight_manifest.get("request_started_at") or process_started_at
    )
    tone_overrides = preflight_manifest.get("tone_overrides")

    def event(sequence: int, name: str, occurred_at: str) -> dict[str, object]:
        return {
            "sequence": sequence,
            "name": name,
            "occurred_at": occurred_at,
            "recorded_at": preflight_resolved_at,
            "style": None,
            "page_id": None,
            "action": None,
            "details": {
                "source": "init_task_dir",
                "startup_contract_version": FAST8_STARTUP_CONTRACT_VERSION,
            },
        }

    state = {
        "run_id": run_id,
        "run_mode": "fast_8x1_diverse",
        "fast8_startup_contract_version": FAST8_STARTUP_CONTRACT_VERSION,
        "fast8_imagegen_slot_policy": FAST8_IMAGEGEN_SLOT_POLICY,
        "status": "running",
        **(
            {"tone_overrides": tone_overrides}
            if tone_overrides is not None
            else {}
        ),
        "anchor_page_id": page_id,
        "follower_page_ids": [],
        "deferred_pages": [],
        "preflight": {
            "status": "resolved",
            "manifest_path": preflight_manifest.get("source_manifest_path"),
            "manifest_sha256": preflight_manifest.get("source_manifest_sha256"),
        },
        "overview_runtime": {
            "python": str(overview_python),
            "pillow_preflight": "pass",
            "binding_policy": "startup_bound_reuse_for_formal_overview",
        },
        "timing": {
            "request_started_at": request_started_at,
            "process_started_at": process_started_at,
            "preflight_resolved_at": preflight_resolved_at,
        },
        "events": [
            event(1, "process_started", process_started_at),
            event(2, "preflight_resolved", preflight_resolved_at),
        ],
        "scheduler": {
            "imagegen_slot_policy": FAST8_IMAGEGEN_SLOT_POLICY,
            "active_actions": [],
            "ready_queue": [],
            "recovery_queue": [],
        },
    }
    payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{state_path.name}.", suffix=".tmp", dir=state_path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, state_path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return state_path


def validate_fast8_preflight_manifest(
    path: Path, expected_task_name: str
) -> dict[str, object]:
    """Validate all source paths before allocating the one formal run directory."""

    path = path.expanduser().resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Fast8 预备清单无法读取：{path}：{exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("Fast8 预备清单根节点必须是对象")
    if value.get("fast8_preflight_manifest_version") != FAST8_PREFLIGHT_MANIFEST_VERSION:
        raise SystemExit("fast8_preflight_manifest_version 必须为 1")
    if value.get("run_mode") != "fast_8x1_diverse":
        raise SystemExit("Fast8 预备清单 run_mode 必须为 fast_8x1_diverse")
    manifest_task_name = value.get("task_name")
    if manifest_task_name is not None and normalize_task_name(str(manifest_task_name)) != expected_task_name:
        raise SystemExit("Fast8 预备清单 task_name 与命令行任务名不一致")
    if value.get("timestamp_policy") != "script_owned":
        raise SystemExit("Fast8 预备清单 timestamp_policy 必须为 script_owned")
    request_started_at = value.get("request_started_at")
    if request_started_at is not None:
        if not isinstance(request_started_at, str) or not request_started_at.strip():
            raise SystemExit("Fast8 预备清单 request_started_at 必须是 ISO 时间字符串")
        normalized_started_at = request_started_at.strip()
        if normalized_started_at.endswith(("Z", "z")):
            normalized_started_at = normalized_started_at[:-1] + "+00:00"
        try:
            datetime.fromisoformat(normalized_started_at)
        except ValueError as exc:
            raise SystemExit("Fast8 预备清单 request_started_at 不是合法 ISO 时间") from exc
    page_ids = value.get("page_ids")
    if (
        not isinstance(page_ids, list)
        or not page_ids
        or not all(isinstance(item, str) and item.strip() for item in page_ids)
        or len(set(page_ids)) != len(page_ids)
    ):
        raise SystemExit("Fast8 预备清单 page_ids 必须是不重复的非空字符串数组")
    tone_overrides = value.get("tone_overrides")
    if tone_overrides is not None:
        if not isinstance(tone_overrides, dict):
            raise SystemExit("Fast8 预备清单 tone_overrides 必须是对象")
        expected_styles = set("ABCDEFGH")
        if set(tone_overrides) != expected_styles:
            raise SystemExit("Fast8 预备清单 tone_overrides 必须完整包含 A-H")
        if any(tone not in {"light", "dark"} for tone in tone_overrides.values()):
            raise SystemExit("Fast8 预备清单 tone_overrides 只允许 light|dark")

    def normalized_files(field: str, required: bool) -> list[dict[str, object]]:
        raw = value.get(field, [])
        if not isinstance(raw, list):
            raise SystemExit(f"Fast8 预备清单 {field} 必须是数组")
        result: list[dict[str, object]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, str) or not item.strip():
                raise SystemExit(f"Fast8 预备清单 {field}[{index}] 必须是非空路径")
            resolved = Path(item).expanduser()
            if not resolved.is_absolute():
                raise SystemExit(f"Fast8 预备清单 {field}[{index}] 必须是绝对路径")
            resolved = resolved.resolve()
            exists = resolved.is_file()
            if required and not exists:
                raise SystemExit(f"Fast8 必需来源文件不存在：{resolved}")
            result.append(
                {
                    "path": str(resolved),
                    "exists": exists,
                    "sha256": file_sha256(resolved) if exists else None,
                }
            )
        return result

    required_files = normalized_files("required_files", True)
    optional_files = normalized_files("optional_files", False)
    identity_required_files: list[Path] = []
    for record in required_files:
        required_path = Path(str(record["path"]))
        if pipeline.slide_identity_from_file(required_path, list(page_ids)) is not None:
            identity_required_files.append(required_path)
    if len(identity_required_files) > 1:
        raise SystemExit(
            "Fast8 必需来源中存在多个启用的 slide identity 权威文件；"
            "每次新运行只能有一份权威原大纲"
        )
    raw_assets = value.get("asset_items", [])
    if not isinstance(raw_assets, list):
        raise SystemExit("Fast8 预备清单 asset_items 必须是数组")
    assets: list[dict[str, object]] = []
    for index, item in enumerate(raw_assets):
        if not isinstance(item, dict):
            raise SystemExit(f"Fast8 预备清单 asset_items[{index}] 必须是对象")
        asset_path = item.get("path")
        role = item.get("role")
        if not isinstance(asset_path, str) or not asset_path.strip():
            raise SystemExit(f"Fast8 预备清单 asset_items[{index}].path 缺失")
        if not isinstance(role, str) or not role.strip():
            raise SystemExit(f"Fast8 预备清单 asset_items[{index}].role 缺失")
        resolved = Path(asset_path).expanduser()
        if not resolved.is_absolute():
            raise SystemExit(f"Fast8 预备清单 asset_items[{index}].path 必须是绝对路径")
        resolved = resolved.resolve()
        if not resolved.is_file():
            raise SystemExit(f"Fast8 实际输入资产不存在：{resolved}")
        assets.append(
            {"path": str(resolved), "role": role.strip(), "sha256": file_sha256(resolved)}
        )
    all_paths = [
        item["path"] for item in [*required_files, *optional_files, *assets]
    ]
    if len(all_paths) != len(set(all_paths)):
        raise SystemExit(
            "Fast8 预备清单路径重复；来源文件与实际 ImageGen 输入资产必须分开登记"
        )
    slide_identity_file = value.get("slide_identity_file")
    slide_identity_record = None
    if slide_identity_file is not None:
        if not isinstance(slide_identity_file, str) or not slide_identity_file.strip():
            raise SystemExit("Fast8 预备清单 slide_identity_file 必须是非空绝对路径")
        identity_path = Path(slide_identity_file).expanduser()
        if not identity_path.is_absolute():
            raise SystemExit("Fast8 预备清单 slide_identity_file 必须是绝对路径")
        identity_path = identity_path.resolve()
        if not identity_path.is_file():
            raise SystemExit(f"Fast8 slide identity 文件不存在：{identity_path}")
        slide_identity_record = {
            "path": str(identity_path),
            "sha256": file_sha256(identity_path),
        }
    if identity_required_files:
        authoritative_identity_path = identity_required_files[0]
        if (
            slide_identity_record is not None
            and slide_identity_record["path"] != str(authoritative_identity_path)
        ):
            raise SystemExit(
                "Fast8 预备清单 slide_identity_file 必须与启用身份的权威原大纲一致"
            )
        slide_identity_record = {
            "path": str(authoritative_identity_path),
            "sha256": file_sha256(authoritative_identity_path),
        }
    return {
        "fast8_preflight_manifest_version": FAST8_PREFLIGHT_MANIFEST_VERSION,
        "run_mode": "fast_8x1_diverse",
        "task_name": expected_task_name,
        "page_ids": page_ids,
        "timestamp_policy": "script_owned",
        "request_started_at": request_started_at,
        "required_files": required_files,
        "optional_files": optional_files,
        "asset_items": assets,
        **(
            {"tone_overrides": dict(tone_overrides)}
            if tone_overrides is not None
            else {}
        ),
        **(
            {"slide_identity_file": slide_identity_record}
            if slide_identity_record is not None
            else {}
        ),
        "validated_at": now_iso(),
        "source_manifest_path": str(path),
        "source_manifest_sha256": file_sha256(path),
    }


def read_monitoring_config(path: Path) -> Path | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"监测配置无法读取：{path}：{exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"监测配置根节点必须是对象：{path}")
    version = value.get("monitoring_config_version", MONITORING_CONFIG_VERSION)
    if version != MONITORING_CONFIG_VERSION:
        raise SystemExit(f"不支持的监测配置版本：{path}")
    root = value.get("monitoring_root")
    if not isinstance(root, str) or not root.strip():
        raise SystemExit(f"监测配置缺少 monitoring_root：{path}")
    resolved = Path(root).expanduser()
    if not resolved.is_absolute():
        resolved = (path.parent / resolved).resolve()
    return resolved.resolve()


def resolve_monitoring_root(output_root: Path, explicit: str | None = None) -> Path:
    """Resolve one project-level registry without making it a pipeline gate."""

    if explicit:
        return Path(explicit).expanduser().resolve()
    configured_env = os.environ.get("SHAWN_PPT_MONITORING_ROOT")
    if configured_env:
        return Path(configured_env).expanduser().resolve()
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        configured = read_monitoring_config(directory / MONITORING_CONFIG_FILENAME)
        if configured is not None:
            return configured
    configured = read_monitoring_config(USER_MONITORING_CONFIG)
    if configured is not None:
        return configured
    return (output_root / "_skill_monitoring" / "shawn-ppt-image").resolve()


def write_task_init_contract(
    project_dir: Path,
    timestamp: str | None = None,
    monitoring_root: Path | None = None,
    preflight_manifest: dict[str, object] | None = None,
    slide_identity_file: dict[str, str] | None = None,
) -> Path:
    """Mark a newly created task as requiring a sealed source snapshot."""

    project_dir = project_dir.resolve()
    path = project_dir / "state" / "task_init.json"
    if path.exists():
        raise SystemExit(f"拒绝覆盖既有新任务初始化合同：{path}")
    value = {
        "task_init_contract_version": TASK_INIT_CONTRACT_VERSION,
        "project_dir": str(project_dir),
        "source_snapshot_required": True,
        "monitoring_contract_version": 1,
        "monitoring_root": str(
            (
                monitoring_root
                or (project_dir / "state" / "_monitoring" / "shawn-ppt-image")
            )
            .expanduser()
            .resolve()
        ),
        "monitoring_mode": "background_non_blocking",
        "created_at": timestamp or now_iso(),
    }
    if preflight_manifest is not None:
        preflight_path = project_dir / "state" / "preflight_manifest.json"
        preflight_payload = json.dumps(
            preflight_manifest, ensure_ascii=False, indent=2
        ) + "\n"
        preflight_path.write_text(preflight_payload, encoding="utf-8")
        value.update(
            {
                "preflight_manifest_path": str(preflight_path),
                "preflight_manifest_sha256": hashlib.sha256(
                    preflight_payload.encode("utf-8")
                ).hexdigest(),
                "formal_directory_allocation_policy": "after_preflight_pass",
                "timestamp_policy": "script_owned",
            }
        )
    if slide_identity_file is not None:
        value["slide_identity_file"] = slide_identity_file
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="创建一个任务一个文件夹的 Shawn-PPT-image 标准目录。"
    )
    parser.add_argument("--output-root", required=True, help="共享 output 根目录")
    parser.add_argument("--task-name", required=True, help="本次任务的简短可识别名称")
    parser.add_argument(
        "--run-mode",
        choices=(SELECTED_STYLE_EXPANSION_MODE,),
        help="显式创建选定风格扩页运行；省略时保持既有初始化行为",
    )
    parser.add_argument(
        "--selected-style",
        help=(
            "有锚点扩页时选中的规范席位 A-H；无锚点逐页制作时可省略，"
            "控制面使用内部机械席位 A"
        ),
    )
    parser.add_argument(
        "--page-ids",
        help="扩页完整页面范围，逗号分隔；仅用于 selected_style_expansion",
    )
    parser.add_argument(
        "--source-file",
        help="扩页权威 Markdown、JSON 或 PPTX 的绝对路径",
    )
    parser.add_argument(
        "--supporting-source",
        action="append",
        help=(
            "扩页需冻结的 UTF-8 Markdown、TXT 或 JSON，格式为"
            "绝对路径::P02,P05 或绝对路径::deck；可重复传入"
        ),
    )
    parser.add_argument(
        "--anchor",
        action="append",
        help=(
            "扩页风格锚点，格式为绝对路径::primary|supporting；"
            "可不传；传 1-2 次时必须恰有一个 primary"
        ),
    )
    parser.add_argument(
        "--anchor-approval-scope",
        choices=("style_anchor_only", "final_page_and_anchor"),
        default=None,
        help="锚点批准范围；仅用于 selected_style_expansion",
    )
    parser.add_argument(
        "--monitoring-root",
        help=(
            "项目级集中监测目录；省略时依次读取项目配置、用户配置，"
            "最后回退到 output_root/_skill_monitoring/shawn-ppt-image"
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "恢复同名已有任务；接受探索或选定风格扩页状态，"
            "包括 state/ 子目录和旧版顶层位置"
        ),
    )
    parser.add_argument(
        "--preflight-manifest",
        help=(
            "Fast8 可选的正式目录分配前清单；验证权威来源、可选来源和实际输入资产，"
            "通过后才创建唯一正式目录"
        ),
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="只验证任务名、监测路径和 Fast8 预备清单，不创建正式目录",
    )
    parser.add_argument(
        "--overview-python",
        help=(
            "正式创建 Fast8 目录时必填：一次验证并绑定可导入 Pillow 的 Python；"
            "预检-only 阶段不需要"
        ),
    )
    parser.add_argument(
        "--slide-identity-file",
        help=(
            "可选的独立内容 UID 文件；只写入任务初始化合同，供 source snapshot/handoff "
            "绑定，不进入作图提示词或审核逻辑"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    process_started_at = now_iso()
    output_root = Path(args.output_root).expanduser().resolve()
    task_name = normalize_task_name(args.task_name)
    expansion_mode = args.run_mode == SELECTED_STYLE_EXPANSION_MODE
    if expansion_mode:
        if args.resume:
            raise SystemExit(
                "--run-mode selected_style_expansion 用于创建新运行，不得与 --resume 同时使用"
            )
        if args.preflight_manifest or args.preflight_only:
            raise SystemExit(
                "selected_style_expansion 不接受 Fast8 --preflight-manifest/--preflight-only"
            )
        page_ids = normalize_expansion_page_ids(args.page_ids)
        source_file = validate_expansion_source(args.source_file)
        supporting_sources = validate_expansion_supporting_sources(
            args.supporting_source, source_file, page_ids
        )
        anchors = validate_expansion_anchors(args.anchor)
        selected_style = normalize_selected_style(
            args.selected_style, allow_anchorless_default=not anchors
        )
        anchor_approval_scope = args.anchor_approval_scope or "style_anchor_only"
        if not anchors and anchor_approval_scope == "final_page_and_anchor":
            raise SystemExit("无锚点逐页制作不能使用 final_page_and_anchor")
        overview_python = resolve_expansion_overview_python(args.overview_python)
        extracted_pages = extract_expansion_pages(source_file, page_ids)
        preflight_resolved_at = now_iso()
    else:
        expansion_only_args = (
            args.selected_style,
            args.page_ids,
            args.source_file,
            args.supporting_source,
            args.anchor,
            args.anchor_approval_scope,
        )
        if any(value is not None for value in expansion_only_args):
            raise SystemExit(
                "扩页参数必须与 --run-mode selected_style_expansion 一起使用"
            )
        validate_task_name(task_name)
    output_root.mkdir(parents=True, exist_ok=True)
    monitoring_root = resolve_monitoring_root(output_root, args.monitoring_root)
    task_init_contract: Path | None = None
    preflight_manifest = (
        validate_fast8_preflight_manifest(
            Path(args.preflight_manifest), task_name
        )
        if args.preflight_manifest
        else None
    )
    explicit_slide_identity = None
    if args.slide_identity_file:
        identity_path = Path(args.slide_identity_file).expanduser()
        if not identity_path.is_absolute():
            raise SystemExit("--slide-identity-file 必须是绝对路径")
        identity_path = identity_path.resolve()
        if not identity_path.is_file():
            raise SystemExit(f"slide identity 文件不存在：{identity_path}")
        if not expansion_mode or identity_path != source_file:
            raise SystemExit(
                "新运行不接受独立 slide identity 文件；"
                "请把 deck_uid/slide_uids 直接写入权威原大纲"
            )
    manifest_slide_identity = (
        preflight_manifest.get("slide_identity_file")
        if isinstance(preflight_manifest, dict)
        else None
    )
    if (
        explicit_slide_identity is not None
        and manifest_slide_identity is not None
        and explicit_slide_identity != manifest_slide_identity
    ):
        raise SystemExit(
            "--slide-identity-file 与 Fast8 预备清单中的 slide_identity_file 不一致"
        )
    effective_slide_identity = explicit_slide_identity or manifest_slide_identity
    overview_python: Path | None = overview_python if expansion_mode else None
    preflight_resolved_at: str | None = (
        preflight_resolved_at if expansion_mode else None
    )
    if args.overview_python and preflight_manifest is None and not expansion_mode:
        raise SystemExit("--overview-python 只用于带 --preflight-manifest 的新 Fast8")
    if preflight_manifest is not None and not args.preflight_only:
        if not args.overview_python:
            raise SystemExit(
                "正式创建新 Fast8 目录必须传入 --overview-python；"
                "运行时不得推迟到 prepare 或收口阶段发现"
            )
        overview_python = validate_fast8_overview_python(args.overview_python)
        preflight_resolved_at = now_iso()

    if args.preflight_only:
        if args.resume:
            raise SystemExit("--preflight-only 不得与 --resume 同时使用")
        if args.overview_python:
            raise SystemExit("--preflight-only 不接受 --overview-python")
        print(
            json.dumps(
                {
                    "status": "preflight_pass",
                    "output_root": str(output_root),
                    "task_name": task_name,
                    "monitoring_root": str(monitoring_root),
                    "formal_directory_created": False,
                    "preflight_manifest": preflight_manifest,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.resume:
        if args.preflight_manifest or args.overview_python:
            raise SystemExit("--resume 不得重新传入 Fast8 预备清单或总览 Python")
        project_dir = output_root / task_name
        state_paths = (
            project_dir / "state" / "style_run_state.json",
            project_dir / "state" / "selected_style_run_state.json",
            project_dir / "style_run_state.json",
            project_dir / "selected_style_run_state.json",
        )
        if not any(path.is_file() for path in state_paths):
            raise SystemExit(
                "无法恢复：缺少 " + " 或 ".join(str(path) for path in state_paths)
            )
        create_standard_dirs(project_dir)
        marker_path = project_dir / "state" / "task_init.json"
        if marker_path.is_file():
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            configured_root = marker.get("monitoring_root") if isinstance(marker, dict) else None
            if isinstance(configured_root, str) and configured_root:
                monitoring_root = Path(configured_root).expanduser().resolve()
        created = False
    else:
        project_dir = next_available_path(output_root, task_name)
        create_standard_dirs(project_dir)
        if expansion_mode:
            create_selected_style_dirs(project_dir)
        task_init_contract = write_task_init_contract(
            project_dir,
            monitoring_root=monitoring_root,
            preflight_manifest=preflight_manifest,
            slide_identity_file=effective_slide_identity,
        )
        if expansion_mode:
            assert overview_python is not None and preflight_resolved_at is not None
            write_selected_style_initial_artifacts(
                project_dir,
                selected_style=selected_style,
                page_ids=page_ids,
                source=source_file,
                extracted=extracted_pages,
                supporting_sources=supporting_sources,
                anchors=anchors,
                anchor_approval_scope=anchor_approval_scope,
                overview_python=overview_python,
                process_started_at=process_started_at,
                preflight_resolved_at=preflight_resolved_at,
            )
        elif preflight_manifest is not None:
            assert overview_python is not None and preflight_resolved_at is not None
            write_fast8_initial_state(
                project_dir,
                preflight_manifest,
                overview_python,
                process_started_at,
                preflight_resolved_at,
            )
        created = True

    result = {
        "status": "created" if created else "resumed",
        "output_root": str(output_root),
        "task_name": project_dir.name,
        "project_dir": str(project_dir),
        "monitoring_root": str(monitoring_root),
        "standard_dirs": [
            str(project_dir / relative)
            for relative in (
                *STANDARD_DIRS,
                *(SELECTED_STYLE_EXPANSION_DIRS if expansion_mode else ()),
            )
        ],
        "task_init_contract": str(task_init_contract) if task_init_contract else None,
        "state": (
            str(project_dir / "state" / "selected_style_run_state.json")
            if (project_dir / "state" / "selected_style_run_state.json").is_file()
            else (
                str(project_dir / "state" / "style_run_state.json")
                if (project_dir / "state" / "style_run_state.json").is_file()
                else None
            )
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
