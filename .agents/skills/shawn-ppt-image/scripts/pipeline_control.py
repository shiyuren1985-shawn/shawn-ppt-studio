#!/usr/bin/env python3
"""shawn-ppt-image 的确定性状态、阶段转换与失败路由工具。"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
import zlib
from datetime import datetime
from datetime import timedelta
from typing import Any
from xml.etree import ElementTree


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


FULL_STYLES = ("A", "B", "C", "D")
QUICK_STYLES = ("A", "B", "C", "D", "E", "F", "G", "H")
ALL_STYLES = QUICK_STYLES
STRICT_4X3_MODE = "full_4x3_anchored"
FAST_4X3_MODE = "fast_4x3_anchored"
QUICK_8X1_MODE = "quick_8x1"
FAST8_MODE = "fast_8x1_diverse"
CURRENT_QUICK_LAYOUT_VERSION = 5
CURRENT_FAST8_LAYOUT_VERSION = 7
CURRENT_4X3_LAYOUT_VERSION = 6
CURRENT_FAST8_IMAGEGEN_PROMPT_VERSION = 6
LEGACY_FAST8_IMAGEGEN_PROMPT_VERSION = 5
CURRENT_SPATIAL_STANDARD_VERSION = 1
CURRENT_VISUAL_ACTIVITY_PORTFOLIO_VERSION = 1
CURRENT_SPATIAL_TOPOLOGY_PORTFOLIO_VERSION = 1
CURRENT_FAST8_CANDIDATE_POLICY_VERSION = 2
LEGACY_FAST8_CANDIDATE_POLICY_VERSION = 1
CURRENT_FAST8_JUDGE_CONTRACT_VERSION = 2
LEGACY_FAST8_JUDGE_CONTRACT_VERSION = 1
ONE_SHOT_QUICK_LAYOUT_VERSIONS = {4, 5}
FAST_DIVERSITY_QUICK_LAYOUT_VERSIONS = {7}
CURRENT_STATE_AUDIT_VERSION = 2
QUICK8_ACTIVE_CHILD_LIMIT = 8
FAST8_ACTIVE_CHILD_LIMIT = 9
FOUR_BY_THREE_ACTIVE_CHILD_LIMIT = 9
FOUR_BY_THREE_FOLLOWER_TASK_COUNT = len(FULL_STYLES) * 2
SOURCE_SNAPSHOT_CONTRACT_VERSION = 1
HANDOFF_CONTRACT_VERSION = 1
RUN_HEALTH_CONTRACT_VERSION = 1
MONITORING_ENTRY_CONTRACT_VERSION = 1
MONITORING_INDEX_CONTRACT_VERSION = 1
MONITORING_CONFIG_VERSION = 1
GLOBAL_CHROME_CONTRACT_VERSION = 1
GLOBAL_CHROME_REVIEW_CONTRACT_VERSION = 1
FAST8_WORKER_RECEIPT_CONTRACT_VERSION = 1
FAST8_WORKER_TICKET_CONTRACT_VERSION = 2
FAST8_WORKER_TICKET_SUPPORTED_VERSIONS = {1, 2}
FAST8_STARTUP_CONTRACT_VERSION = 1
FAST8_GLOBAL_IMAGEGEN_SLOT_CONTRACT_VERSION = 1
# Legacy dispatch-prelease runs keep their original eight-seat semantics.
FAST8_GLOBAL_IMAGEGEN_SLOT_LIMIT = 8
# Real JIT runs showed that eight near-simultaneous RPCs can amplify backend
# tail latency even though eight Agent workers are available.  Keep all eight
# workers/jobs, but shape only new JIT ImageGen RPCs through a reversible
# central semaphore.  The override does not enter any quality fingerprint.
FAST8_JIT_STABLE_IMAGEGEN_SLOT_LIMIT = 5
FAST8_GLOBAL_IMAGEGEN_SLOT_TTL_SECONDS = 45 * 60
# A successful ImageGen call writes its session PNG before the Worker releases
# the JIT lease. If the RPC is terminal, the lease is released, and the exact
# bound session still has no PNG after this short grace period, waiting minutes
# for model-authored failure prose adds no evidence.
FAST8_TERMINAL_SLOT_ARTIFACT_GRACE_SECONDS = 5
LEGACY_FAST8_IMAGEGEN_SLOT_POLICY = "dispatch_prelease_v1"
CURRENT_FAST8_IMAGEGEN_SLOT_POLICY = "worker_jit_v1"
FAST8_IMAGEGEN_SLOT_POLICIES = {
    LEGACY_FAST8_IMAGEGEN_SLOT_POLICY,
    CURRENT_FAST8_IMAGEGEN_SLOT_POLICY,
}
FAST8_JUDGE_REQUIRED_MODEL = "gpt-5.6-terra"
FAST8_JUDGE_REQUIRED_REASONING = "low"
FAST8_JUDGE_REQUIRED_FORK_TURNS = "none"
FAST8_WORKER_REQUIRED_MODEL = "gpt-5.6-terra"
FAST8_WORKER_REQUIRED_REASONING = "low"
FAST8_WORKER_REQUIRED_FORK_TURNS = "none"
IMAGEGEN_MAX_REFERENCED_PATHS = 5
SOURCE_FRAGMENT_EXTRACTOR_VERSION = 1
TASK_INIT_CONTRACT_VERSION = 1
LEGACY_SOURCE_CONFIRMATION_CONTRACT_VERSION = 1
LEGACY_SOURCE_GUARDED_ACTIONS = {
    "prepare_or_resume_anchors",
    "generation_dispatch",
    "targeted_candidate_repair",
    "continue_following_pages",
    "selected_style_expansion",
    "candidate_delivery",
    "downstream_handoff",
}
QA_STAGES = {None, "filesystem", "visual_worker", "worker"}
QA_SCOPES = {None, "filesystem_only", "content_only", "full_visual"}
GENERATION_ACTIONS = {
    "generate_anchor",
    "repair_anchor",
    "generate_follower",
    "generate_page",
    "repair_page",
}
SELECTED_STYLE_EXPANSION_MODE = "selected_style_expansion"
SELECTED_STYLE_LAYOUT_VERSION = 1
IMAGEGEN_TOOL_ID_RE = re.compile(r"^(exec-[0-9a-fA-F-]{36})\.png$")
IMAGEGEN_TOOL_CALL_ID_RE = re.compile(r"^exec-[0-9a-fA-F-]{36}$")
CODEX_AGENT_THREAD_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
EMBEDDED_IMAGEGEN_PNG_RE = re.compile(
    r"(?P<path>/[^\s\"'<>]+/exec-[0-9a-fA-F-]{36}\.png)"
)
GENERATED_IMAGES_ROOT = (Path.home() / ".codex" / "generated_images").resolve()
SPATIAL_PROMPT_CUES = {
    "low": (
        "低视觉压力；在准确呈现必显内容的前提下，优先保留明显、连续、"
        "参与分组的有效留白，不为填满版面增加元素。"
    ),
    "default": "常规视觉压力；入口清楚、层级有序、组间有停顿。",
}
GROUPING_PROMPT_CUE = (
    "网格只用于对齐；等权并列优先通过空间关系表达，不默认使用边框或底板。"
)
QUICK8_BREATHING_PROMPT_CUES = {
    "zh": {
        "low": "保持清晰层级和有意义的留白，让页面疏朗、有呼吸感，同时完整呈现必要信息。",
        "default": "保持清晰层级和自然停顿，让页面易读、有节奏，同时完整呈现必要信息。",
    },
    "en": {
        "low": (
            "Maintain clear hierarchy and purposeful negative space so the slide feels "
            "open and breathable while preserving all required information."
        ),
        "default": (
            "Maintain clear hierarchy and natural pauses so the slide feels readable "
            "and well paced while preserving all required information."
        ),
    },
}
UNIFIED_SPATIAL_PROMPT_CUES = {
    "zh": (
        "建立清楚、整齐但不机械的版面秩序。使用隐形网格形成一致的对齐轴、基线、"
        "边界和间距节奏，避免无意漂浮或近似对齐。将相关内容聚拢成组，做到组内紧、"
        "组间松；重复少量关键设计规则，并以明确对比建立层级和阅读路径。让有效负空间"
        "承担聚焦、分组、停顿和边缘缓冲，使页面在当前信息密度下自然、有呼吸感，同时"
        "完整呈现必要信息。不要画出网格，也不要机械铺成等重卡片墙；具体构图和视觉形式"
        "保持开放。"
    ),
    "en": (
        "Establish a clear, orderly but non-mechanical layout. Use an invisible grid to "
        "create consistent alignment axes, baselines, boundaries, and spacing rhythm, "
        "avoiding accidental floating or near-alignment. Group related content through "
        "proximity, with tighter spacing within groups and looser spacing between them; "
        "repeat a small set of key design rules and use clear contrast to establish hierarchy "
        "and reading flow. Use functional negative space for focus, grouping, pauses, and edge "
        "breathing so the slide feels balanced and breathable at its actual information density "
        "while preserving all required information. Do not render the grid or default to an "
        "equal-weight card wall; keep composition and visual form open."
    ),
}
PRE_RENDER_SUBTRACTION_CHECK = (
    "Before rendering, remove boundaries whose absence leaves grouping, state and "
    "reading order clear; keep necessary panels."
)
NARRATIVE_COMPRESSION_PROMPT_CUES = {
    "zh": (
        "叙事收束：让一个主导视觉动作或关系承担整页的第一层叙事，其余必要信息作为"
        "从属证据支持它，而不是再叠加一套等权解释系统。内容确实需要流程或多节点时，"
        "仍应由一个清楚的主导结构统领；不要机械拼成标题、数字、流程带和注释带的完整套件。"
    ),
    "en": (
        "Narrative compression: let one dominant visual action or relationship carry the "
        "slide's first-level story, with all other necessary information acting as subordinate "
        "evidence rather than a second equal-weight explanatory system. When the content truly "
        "needs a process or multiple nodes, keep one clear governing structure; do not mechanically "
        "assemble a complete title-number-process-strip-annotation package."
    ),
}
CONTENT_VISUAL_INTEGRATION_PROMPT_CUES = {
    "zh": (
        "图文整合：让逐字锚点与说明性故事共同服务于本候选的主导关系，"
        "不要把内容合同的字段边界直接翻译成默认的左右分区、等重条目、卡片墙或箭头流程。"
        "如果内容本身确实要求这些结构，可以使用，但必须由一个清楚的关系和阅读入口统领。"
    ),
    "en": (
        "Content-visual integration: make literal anchors and the explanatory story serve the "
        "candidate's governing relationship together. Do not translate content-contract field "
        "boundaries directly into a default left-right split, equal-weight list, card wall, or "
        "arrow process. These structures remain valid when the content genuinely calls for them, "
        "but one clear relationship and reading entry must govern the result."
    ),
}
FAST8_SAME_WORKER_RECOVERY_SOFT_ESCALATION_SECONDS = 0
FAST8_OPTIONAL_EFFECT_REVIEW_SOFT_TIMEOUT_SECONDS = 180

FAST8_STYLE_REFERENCE_ROLES = {
    "primary_style_reference",
    "supporting_style_reference",
    "style_reference",
    "style_anchor",
}
EVIDENCE_ASSET_ROLES = {
    "project_visual_evidence",
    "source_slide",
    "source_page",
    "case_evidence",
    "evidence_reference",
}
GLOBAL_CHROME_ASSET_ROLE = "deck_title_system_logo"
GLOBAL_CHROME_AUTHORIZATION_KINDS = {
    "current_user_requirement",
    "authoritative_outline",
    "confirmed_deck_design_system",
    "specified_master_reference",
}
FAST8_JUDGE_SCOPES = {
    LEGACY_FAST8_JUDGE_CONTRACT_VERSION: "diversity_only",
    CURRENT_FAST8_JUDGE_CONTRACT_VERSION: "diversity_and_minimum_craft",
}
FAST8_CRAFT_RED_FLAG_TYPES = {
    "competing_first_level_zones",
    "decorative_node_overload",
    "default_component_assembly",
    "crude_container_dominance",
    "edge_pressure_without_pause",
    "explanatory_module_overload",
    "generic_iconography",
    "inconsistent_microcraft",
    "weak_image_integration",
    "unfinished_visual_hierarchy",
}
RELATIONSHIP_REPRESENTATION_FAMILY_LIMIT = 80
SPATIAL_TOPOLOGY_INTENT_LIMIT = 140
SPATIAL_TOPOLOGY_PRIMARY_ENTRIES = {
    "single_focus",
    "paired_contrast",
    "path",
    "network",
    "field",
    "hierarchy",
    "radial",
    "evidence_hero",
}
SPATIAL_TOPOLOGY_REGION_LOGICS = {
    "unified_field",
    "asymmetric_split",
    "staged_path",
    "distributed_nodes",
    "layered_depth",
    "annotated_object",
    "geographic_spread",
    "editorial_sequence",
}
SPATIAL_TOPOLOGY_EVIDENCE_MODES = {
    "integrated",
    "annotated",
    "satellite",
    "quiet_band",
    "none",
}


def normalized_asset_role_key(value: Any) -> str:
    """Return the machine role before any human-readable role description."""

    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    return re.split(r"\s*[:：]\s*", normalized, maxsplit=1)[0]

VISUAL_ACTIVITY_MODES = {"restrained", "balanced", "expressive"}
VISUAL_ACTIVITY_PROMPT_CUES = {
    "zh": {
        "restrained": (
            "视觉活跃度：克制。使用少量高价值视觉元素和果断的有效负空间，"
            "不为每个名词分配节点、图标、标签或容器。"
        ),
        "balanced": (
            "视觉活跃度：平衡。允许必要的支撑信息，但只能有一个主导关系或一组"
            "由内容决定的共同入口；装饰与次级证据必须明显安静。"
        ),
        "expressive": (
            "视觉活跃度：有表现力。可以使用强烈动势或丰富材质，但第一层注意力"
            "仍须集中，边缘和组间必须保留可感知的停顿与释放。"
        ),
    },
    "en": {
        "restrained": (
            "Visual activity: restrained. Use a small number of high-value visual elements "
            "and decisive functional negative space; do not assign a node, icon, label, or "
            "container to every noun."
        ),
        "balanced": (
            "Visual activity: balanced. Allow necessary supporting information, but keep one "
            "governing relationship or one content-driven group of co-primary entries; decoration "
            "and secondary evidence must remain visibly quiet."
        ),
        "expressive": (
            "Visual activity: expressive. Strong motion or rich material treatment is allowed, "
            "but first-level attention must stay concentrated, with perceptible pauses and release "
            "between groups and around the edges."
        ),
    },
}
ATTENTION_CONSOLIDATION_PROMPT_CUES = {
    "zh": (
        "支撑证据收束：除非内容关系确实要求多组并列，次级信息优先聚成一个安静的"
        "证据层，并保留一处明确叙事停顿；不要再叠加独立底部总结带、并列说明卡或"
        "第二个强入口。"
    ),
    "en": (
        "Supporting-evidence consolidation: unless the content genuinely requires several "
        "co-primary groups, gather secondary information into one quiet evidence layer and "
        "preserve one deliberate narrative pause. Do not add a separate bottom summary band, "
        "parallel explainer cards, or a second strong entry point."
    ),
}


def active_child_limit_for_mode(mode: str) -> int:
    if mode in {STRICT_4X3_MODE, FAST_4X3_MODE}:
        return FOUR_BY_THREE_ACTIVE_CHILD_LIMIT
    if mode == FAST8_MODE:
        return FAST8_ACTIVE_CHILD_LIMIT
    return QUICK8_ACTIVE_CHILD_LIMIT


def fast8_imagegen_slot_policy(state: dict[str, Any]) -> str:
    """Return the versioned ImageGen slot policy; missing means legacy prelease."""

    policy = state.get(
        "fast8_imagegen_slot_policy",
        (state.get("scheduler") or {}).get(
            "imagegen_slot_policy", LEGACY_FAST8_IMAGEGEN_SLOT_POLICY
        ),
    )
    if policy not in FAST8_IMAGEGEN_SLOT_POLICIES:
        raise SystemExit(f"Fast8 ImageGen 槽位策略无效：{policy!r}")
    return str(policy)


LEGACY_SPATIAL_PROMPT_CUES = {
    "low": "低视觉压力；入口清楚、组间有停顿、边缘开放。",
    "default": SPATIAL_PROMPT_CUES["default"],
}
TONE_PROMPT_LABELS = {"dark": "深色背景", "light": "浅色背景"}
DENSITY_PROMPT_LABELS = {"low": "低", "medium": "中等", "high": "高"}
GLOBAL_EVENTS = {
    "process_started": "process_started_at",
    "preflight_decision_received": "preflight_decision_received_at",
    "preflight_resolved": "preflight_resolved_at",
    "style_jobs_created": "style_jobs_created_at",
    "task_package_completed": "task_package_completed_at",
    "initial_anchor_dispatch": "initial_anchor_dispatch_at",
    # 以下两个事件名只保留用于验收旧运行状态；新运行不得继续写入。
    "first_three_way_dispatch": "first_three_way_dispatch_at",
    "style_D_first_active": "style_D_first_active_at",
    "all_anchor_tools_completed": "all_anchor_tools_completed_at",
    "anchor_qa_completed": "anchor_qa_completed_at",
    "contracts_completed": "contracts_completed_at",
    "follower_tasks_ready": "follower_tasks_ready_at",
    "follower_generation_started": "follower_generation_started_at",
    "milestone_9_of_12": "milestone_9_of_12_at",
    "milestone_overview_completed": "milestone_overview_completed_at",
    "first_round_completed": "first_round_completed_at",
    "formal_overview_completed": "formal_overview_completed_at",
    "process_completed": "process_completed_at",
}
PAGE_EVENTS = {
    "queued": "queued_at",
    "agent_action_started": "agent_action_started_at",
    "tool_started": "tool_started_at",
    "tool_finished": "tool_finished_at",
    "artifact_recovery_started": "artifact_recovery_started_at",
    "artifact_recovery_finished": "artifact_recovery_finished_at",
    "file_validated": "file_validated_at",
    "agent_action_finished": "agent_action_finished_at",
    "overview_qa": "overview_qa_at",
    "page_completed": "completed_at",
}


def state_audit_version(state: dict[str, Any]) -> int:
    """Return the explicit state audit contract; missing means legacy v1."""

    version = state.get("state_audit_contract_version", 1)
    if version not in {1, CURRENT_STATE_AUDIT_VERSION}:
        raise SystemExit(
            "state_audit_contract_version 只允许 1|2；"
            f"当前值为 {version!r}"
        )
    return int(version)


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def read_json_value(path: Path) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 无法解析：{path}：{exc}") from exc
    return value


def read_json(path: Path) -> dict[str, Any]:
    value = read_json_value(path)
    if not isinstance(value, dict):
        raise SystemExit(f"JSON 根节点必须是对象：{path}")
    return value


def read_json_with_sha256(path: Path) -> tuple[dict[str, Any], str]:
    """Read one JSON byte snapshot and hash those exact bytes."""

    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise SystemExit(f"文件不存在：{path}") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"JSON 无法解析：{path}：{exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON 根节点必须是对象：{path}")
    return value, hashlib.sha256(payload).hexdigest()


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
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_idempotent(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        current = read_json(path)
        if current != value:
            raise SystemExit(f"拒绝覆盖内容不同的既有文件：{path}")
        return
    atomic_write_json(path, value)


def resolve_imagegen_artifact_hint(value: Any) -> tuple[Path | None, str | None]:
    """Resolve an exact path or one safe exec-*.png embedded in output_hint prose."""

    if not isinstance(value, str) or not value.strip():
        return None, None
    text = value.strip()
    # A formal Worker may return an exact absolute artifact outside the default
    # generated_images tree (for example a test fixture or a future backend).
    exact = Path(text).expanduser()
    try:
        if exact.is_absolute() and exact.is_file():
            resolved = exact.resolve()
            match = IMAGEGEN_TOOL_ID_RE.match(resolved.name)
            return resolved, match.group(1) if match else None
    except OSError:
        pass

    # Explanatory output_hint text is less trusted.  Only accept one existing,
    # canonical exec artifact from Codex's generated_images root; ambiguity is
    # deliberately routed to recovery instead of guessing the newest file.
    candidates: dict[str, tuple[Path, str]] = {}
    for match in EMBEDDED_IMAGEGEN_PNG_RE.finditer(text):
        candidate = Path(match.group("path")).expanduser().resolve()
        try:
            candidate.relative_to(GENERATED_IMAGES_ROOT)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        tool_match = IMAGEGEN_TOOL_ID_RE.match(candidate.name)
        if tool_match is None:
            continue
        candidates[str(candidate)] = (candidate, tool_match.group(1))
    if len(candidates) != 1:
        return None, None
    return next(iter(candidates.values()))


def normalize_fast8_artifact_fields(value: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize a Fast8 savedPath/output_hint without trusting prose as a path."""

    normalized = dict(value)
    path, derived_tool_id = resolve_imagegen_artifact_hint(normalized.get("savedPath"))
    if path is None:
        path, derived_tool_id = resolve_imagegen_artifact_hint(
            normalized.get("output_hint")
        )
    if path is None:
        return normalized
    normalized["savedPath"] = str(path)
    tool_call_id = normalized.get("tool_call_id")
    if not isinstance(tool_call_id, str) or not IMAGEGEN_TOOL_CALL_ID_RE.fullmatch(
        tool_call_id
    ):
        if derived_tool_id:
            normalized["tool_call_id"] = derived_tool_id
    if normalized.get("error") == "artifact_handoff_unresolved":
        normalized["error"] = None
    return normalized


def normalize_style(style: str | None) -> str | None:
    if style is None:
        return None
    value = style.removeprefix("style_").upper()
    if value not in ALL_STYLES:
        raise SystemExit(f"无效风格席位：{style}")
    return value


def origin_image_target(project_dir: Path, style: str, page_id: str) -> Path:
    """Return the flat canonical path used by every new image task."""

    normalized_style = normalize_style(style)
    if normalized_style is None:
        raise SystemExit("生成原图路径时缺少风格席位")
    return project_dir / "origin_image" / f"style_{normalized_style}_page_{page_id}.png"


def fast8_worker_receipt_path(
    project_dir: Path,
    style: str,
    page_id: str,
    action: str,
    attempt: int,
) -> Path:
    """Return the unique non-formal receipt path written by one Fast8 worker."""

    normalized_style = normalize_style(style)
    if normalized_style is None:
        raise SystemExit("生成 Fast8 Worker 回执路径时缺少席位")
    safe_action = re.sub(r"[^a-z0-9_]+", "_", action.lower()).strip("_")
    return (
        project_dir
        / "style_jobs"
        / "results"
        / (
            f"worker_receipt_{normalized_style}_page_{page_id}_"
            f"{safe_action}_attempt_{attempt}.json"
        )
    )


def fast8_worker_ticket_path(
    project_dir: Path,
    style: str,
    page_id: str,
    action: str,
    attempt: int,
) -> Path:
    """Return one deterministic, state-bound Worker dispatch ticket path."""

    normalized_style = normalize_style(style)
    if normalized_style is None:
        raise SystemExit("生成 Fast8 Worker ticket 路径时缺少席位")
    safe_action = re.sub(r"[^a-z0-9_]+", "_", action.lower()).strip("_")
    return (
        project_dir
        / "style_jobs"
        / "dispatch_tickets"
        / (
            f"ticket_{normalized_style}_page_{page_id}_"
            f"{safe_action}_attempt_{attempt}.json"
        )
    )


def fast8_worker_session_artifact(
    active_item: dict[str, Any],
) -> tuple[Path | None, str | None]:
    """Resolve the sole exec PNG from one exact, controller-bound Worker session."""

    session_id = active_item.get("worker_session_id")
    if (
        not isinstance(session_id, str)
        or CODEX_AGENT_THREAD_ID_RE.fullmatch(session_id.strip().lower()) is None
    ):
        return None, None
    session_dir = (GENERATED_IMAGES_ROOT / session_id.strip().lower()).resolve()
    try:
        session_dir.relative_to(GENERATED_IMAGES_ROOT)
    except ValueError:
        return None, None
    if not session_dir.is_dir():
        return None, None
    candidates: list[tuple[Path, str]] = []
    for path in sorted(session_dir.glob("exec-*.png")):
        if not path.is_file():
            continue
        match = IMAGEGEN_TOOL_ID_RE.fullmatch(path.name)
        if match is None:
            continue
        candidates.append((path.resolve(), match.group(1)))
    if len(candidates) != 1:
        return None, None
    dispatch_at = active_item.get("dispatch_authorized_at") or active_item.get(
        "dispatch_requested_at"
    )
    if isinstance(dispatch_at, str):
        try:
            file_time = datetime.fromtimestamp(
                candidates[0][0].stat().st_mtime
            ).astimezone()
            if file_time < parse_time(dispatch_at):
                return None, None
        except (OSError, TypeError, ValueError):
            return None, None
    return candidates[0]


def fast8_terminal_slot_failure_without_artifact(
    state_path: Path,
    state: dict[str, Any],
    active_item: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a deterministic backend failure after a terminal empty RPC."""

    telemetry_path = fast8_imagegen_slot_telemetry_path(
        state_path, state, active_item
    )
    if not telemetry_path.is_file():
        return None
    try:
        telemetry = read_json(telemetry_path)
    except SystemExit:
        return None
    expected = {
        "imagegen_slot_telemetry_version": 1,
        "run_id": state.get("run_id"),
        "style": normalize_style(active_item.get("style")),
        "page_id": str(active_item.get("page_id") or state.get("anchor_page_id")),
        "action": str(active_item.get("action") or "generate_anchor"),
        "attempt": int(active_item.get("attempt") or 1),
        "worker_session_id": active_item.get("worker_session_id"),
        "worker_ticket_sha256": active_item.get("worker_ticket_sha256"),
    }
    if any(telemetry.get(key) != value for key, value in expected.items()):
        return None
    if telemetry.get("rpc_terminal") is not True or telemetry.get("status") not in {
        "released",
        "already_released",
    }:
        return None
    acquired_at = telemetry.get("acquired_at")
    released_at = telemetry.get("released_at")
    if not isinstance(acquired_at, str) or not isinstance(released_at, str):
        return None
    try:
        elapsed = (parse_time(now_iso()) - parse_time(released_at)).total_seconds()
        if elapsed < FAST8_TERMINAL_SLOT_ARTIFACT_GRACE_SECONDS:
            return None
    except (TypeError, ValueError):
        return None
    session_path, _ = fast8_worker_session_artifact(active_item)
    if session_path is not None:
        return None
    return {
        "style": expected["style"],
        "page_id": expected["page_id"],
        "action": expected["action"],
        "attempt": expected["attempt"],
        "worker_agent_id": active_item.get("worker_agent_id"),
        "agent_action_started_at": acquired_at,
        "agent_action_finished_at": released_at,
        "tool_call_id": None,
        "savedPath": None,
        "tool_started_at": acquired_at,
        "tool_finished_at": released_at,
        "binding_source": "controller_terminal_slot_without_artifact",
        "timing_capture": "controller_terminal_slot_without_artifact",
        "tool_status": "failed",
        "failure_class": "backend_failed",
        "tool_error_code": None,
        "error": "imagegen_backend_failed",
    }


def styles_for_mode(mode: str | None) -> tuple[str, ...]:
    """返回当前运行实际使用的席位；quick_4x1 只保留旧运行兼容。"""

    if mode in {STRICT_4X3_MODE, FAST_4X3_MODE}:
        return FULL_STYLES
    if mode in {QUICK_8X1_MODE, FAST8_MODE}:
        return QUICK_STYLES
    if mode == "quick_4x1":
        return FULL_STYLES
    raise SystemExit(f"无法识别运行模式：{mode}")


def tone_for_style(mode: str | None, style: str) -> str:
    if mode in {QUICK_8X1_MODE, FAST8_MODE}:
        return "dark" if style in {"A", "B", "C", "D"} else "light"
    return "dark" if style in {"A", "B"} else "light"


def tones_for_run(
    state: dict[str, Any], mode: str | None, styles: tuple[str, ...]
) -> dict[str, str]:
    """Return default tones, honoring explicit per-run user overrides."""

    tones = {style: tone_for_style(mode, style) for style in styles}
    overrides = state.get("tone_overrides")
    if overrides is None:
        return tones
    if not isinstance(overrides, dict):
        raise SystemExit("tone_overrides 必须是席位到 dark|light 的对象")
    unknown = sorted(set(overrides) - set(styles))
    if unknown:
        raise SystemExit(f"tone_overrides 包含当前模式未使用的席位：{','.join(unknown)}")
    for style, tone in overrides.items():
        if tone not in TONE_PROMPT_LABELS:
            raise SystemExit(f"tone_overrides.{style} 只允许 dark|light")
        tones[style] = tone
    return tones


def apply_background_tone_policy(
    state: dict[str, Any],
    policy: Any,
    styles: tuple[str, ...],
    *,
    label: str,
) -> bool:
    """Apply one pre-generation background-tone decision to every seat.

    Existing tone overrides without this helper's provenance are treated as an
    earlier explicit user/preflight decision and remain authoritative.  A
    visual Director may otherwise select either the pipeline default matrix or
    one uniform dark/light tone, for example after inspecting a style anchor.
    """

    previous_policy = state.get("background_tone_policy")
    existing_overrides = state.get("tone_overrides")
    director_owned_existing = bool(
        isinstance(previous_policy, dict)
        and previous_policy.get("applied_by") == "visual_director"
    )
    if existing_overrides is not None and not director_owned_existing:
        # Preflight/user overrides outrank the anchor-derived Director choice.
        return False
    if policy is None:
        return False
    if not isinstance(policy, dict):
        raise SystemExit(f"{label} 必须是对象")
    allowed = {"mode", "tone", "source"}
    unknown = sorted(set(policy) - allowed)
    if unknown:
        raise SystemExit(f"{label} 包含未知字段：{', '.join(unknown)}")
    mode = policy.get("mode")
    source = policy.get("source")
    tone = policy.get("tone")
    if mode not in {"default_mixed", "uniform"}:
        raise SystemExit(f"{label}.mode 只允许 default_mixed|uniform")
    if source not in {
        "pipeline_default",
        "primary_style_reference",
        "user_explicit",
    }:
        raise SystemExit(
            f"{label}.source 只允许 pipeline_default|primary_style_reference|user_explicit"
        )
    if mode == "default_mixed":
        if tone not in {None, ""} or source not in {
            "pipeline_default",
            "user_explicit",
        }:
            raise SystemExit(
                f"{label} 使用 default_mixed 时 tone 必须为空，source 只允许 "
                "pipeline_default|user_explicit"
            )
        if director_owned_existing:
            state.pop("tone_overrides", None)
    else:
        if tone not in TONE_PROMPT_LABELS:
            raise SystemExit(f"{label}.tone 在 uniform 模式下只允许 dark|light")
        state["tone_overrides"] = {style: tone for style in styles}
    state["background_tone_policy"] = {
        "mode": mode,
        "tone": tone if mode == "uniform" else None,
        "source": source,
        "applied_by": "visual_director",
    }
    return True


def page_record(state: dict[str, Any], style: str | None, page_id: str) -> dict[str, Any]:
    try:
        if (
            style is None
            or (state.get("run_mode") or state.get("mode"))
            == SELECTED_STYLE_EXPANSION_MODE
        ):
            record = state["pages"][page_id]
        else:
            record = state["styles"][style]["pages"][page_id]
    except (KeyError, TypeError) as exc:
        target = f"style_{style}/{page_id}" if style else page_id
        raise SystemExit(f"状态中找不到页面：{target}") from exc
    if not isinstance(record, dict):
        raise SystemExit(f"页面状态不是对象：{page_id}")
    return record


def append_event(
    state: dict[str, Any],
    name: str,
    occurred_at: str,
    style: str | None = None,
    page_id: str | None = None,
    action: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    events = state.setdefault("events", [])
    if not isinstance(events, list):
        raise SystemExit("state.events 必须是数组")
    event = {
        "sequence": len(events) + 1,
        "name": name,
        "occurred_at": occurred_at,
        "recorded_at": now_iso(),
        "style": style,
        "page_id": page_id,
        "action": action,
        "details": details or {},
    }
    events.append(event)


def apply_page_event_effects(
    record: dict[str, Any],
    event: str,
    action: str | None,
    details: dict[str, Any],
) -> None:
    """在同一次原子写入中同步页面结果元数据，避免事件与页面状态分叉。"""

    attempt = details.get("attempt")
    if isinstance(attempt, int) and attempt > 0:
        record["attempt_count"] = max(int(record.get("attempt_count") or 0), attempt)

    backend = details.get("backend_used", details.get("backend"))
    if isinstance(backend, str) and backend:
        record["backend_used"] = backend

    tool_call_id = details.get("tool_call_id")
    if isinstance(tool_call_id, str) and tool_call_id:
        record["tool_call_id"] = tool_call_id

    agent_id = details.get("worker_agent_id", details.get("agent_id"))
    if isinstance(agent_id, str) and agent_id:
        record["worker_agent_id"] = agent_id

    selected_source = details.get("selected_source")
    if isinstance(selected_source, str) and selected_source:
        record["selected_source"] = selected_source
        if isinstance(attempt, int) and attempt > 0:
            record["selected_attempt"] = attempt
        sources = record.setdefault("attempt_sources", [])
        if not isinstance(sources, list):
            raise SystemExit("页面 attempt_sources 必须是数组")
        if selected_source not in sources:
            sources.append(selected_source)

    attempt_sources = details.get("attempt_sources")
    if isinstance(attempt_sources, list):
        normalized = [item for item in attempt_sources if isinstance(item, str) and item]
        record["attempt_sources"] = list(dict.fromkeys(normalized))

    output_path = details.get("final_path", details.get("output_path"))
    if isinstance(output_path, str) and output_path:
        record["final_path"] = output_path

    source_size = details.get("source_size_bytes")
    if isinstance(source_size, int) and source_size >= 0:
        record["source_size_bytes"] = source_size

    source_sha256 = details.get("source_sha256")
    if isinstance(source_sha256, str) and source_sha256:
        record["source_sha256"] = source_sha256

    content_gate = details.get("content_gate")
    if isinstance(content_gate, dict):
        record["content_gate"] = content_gate

    spatial_gate = details.get("spatial_gate")
    if isinstance(spatial_gate, dict):
        record["spatial_gate"] = spatial_gate

    craft_gate = details.get("craft_gate")
    if isinstance(craft_gate, dict):
        record["craft_gate"] = craft_gate

    qa_note = details.get("qa_note", details.get("qa_reason"))
    if isinstance(qa_note, str) and qa_note:
        record["qa_note"] = qa_note

    qa_stage = details.get("qa_stage")
    if isinstance(qa_stage, str) and qa_stage:
        record["qa_stage"] = qa_stage

    qa_scope = details.get("qa_scope")
    if isinstance(qa_scope, str) and qa_scope:
        record["qa_scope"] = qa_scope

    recovery_method = details.get("recovery_method")
    if isinstance(recovery_method, str) and recovery_method:
        record["artifact_recovery_method"] = recovery_method

    binding_source = details.get("binding_source")
    if isinstance(binding_source, str) and binding_source:
        record["artifact_binding_source"] = binding_source

    timing_capture = details.get("timing_capture")
    if isinstance(timing_capture, str) and timing_capture:
        record["timing_capture"] = timing_capture

    failure_reason = details.get("failure_reason")
    if isinstance(failure_reason, str):
        record["failure_reason"] = failure_reason or None

    if event == "queued":
        record.setdefault("status", "pending")
    elif (
        event == "agent_action_started"
        and action
        and (action.startswith("generate") or action.startswith("repair"))
    ):
        record["status"] = (
            "retrying"
            if action.startswith("repair")
            or "retry" in action
            or (isinstance(attempt, int) and attempt > 1)
            else "generating"
        )
    elif (
        event == "agent_action_finished"
        and action
        and (action.startswith("generate") or action.startswith("repair"))
    ):
        record["status"] = "generated"
    elif event == "file_validated":
        record["status"] = "generated"
    elif event == "artifact_recovery_started":
        record["recovery_required"] = True
        record["recovery_status"] = "running"
        record["recovery_attempt_count"] = int(
            record.get("recovery_attempt_count") or 0
        ) + 1
        record["failure_reason"] = "artifact_handoff_unresolved"
    elif event == "artifact_recovery_finished":
        recovery_status = details.get("recovery_status", details.get("status"))
        if recovery_status not in {"recovered", "not_found", "ambiguous", "failed"}:
            raise SystemExit(
                "artifact_recovery_finished.recovery_status 只允许 "
                "recovered|not_found|ambiguous|failed"
            )
        record["recovery_required"] = True
        record["recovery_status"] = recovery_status
        if recovery_status == "recovered" and record.get("selected_source"):
            record["status"] = "generated"
            record["failure_reason"] = None
    elif event == "overview_qa":
        record["qa_stage"] = details.get("qa_stage", "visual_worker")
        if details.get("qa_scope"):
            record["qa_scope"] = details["qa_scope"]
    elif event == "page_completed":
        completion_status = details.get("completion_status", "accepted")
        if completion_status not in {"accepted", "candidate_ready"}:
            raise SystemExit("page_completed.completion_status 只允许 accepted|candidate_ready")
        if completion_status == "candidate_ready" and not record.get("qa_stage"):
            record["qa_stage"] = "filesystem"
            record["qa_scope"] = "filesystem_only"
            for gate_name in ("content_gate", "spatial_gate", "craft_gate"):
                if record.get(gate_name) is None:
                    record[gate_name] = {
                        "status": "not_applicable",
                        "reason": "选择前只完成确定性文件检查",
                    }
        record["status"] = completion_status


def refresh_style_workflow_status(
    state: dict[str, Any], style: str | None
) -> None:
    if style is None:
        return
    style_state = (state.get("styles") or {}).get(style)
    if not isinstance(style_state, dict):
        return
    pages = style_state.get("pages") or {}
    page_records = [value for value in pages.values() if isinstance(value, dict)]
    mode = state.get("run_mode") or state.get("mode")
    expected_page_ids = {
        str(state.get("anchor_page_id")),
        *(str(page_id) for page_id in (state.get("follower_page_ids") or [])),
    }
    has_complete_style_scope = (
        mode != FAST_4X3_MODE or set(map(str, pages)) == expected_page_ids
    )
    if page_records and has_complete_style_scope and all(
        page.get("status") in {"accepted", "candidate_ready"}
        for page in page_records
    ):
        style_state["workflow_status"] = "ready_for_overview"
        return
    anchor_page_id = str(state.get("anchor_page_id"))
    anchor = pages.get(anchor_page_id)
    if (
        isinstance(anchor, dict)
        and anchor.get("selected_source")
        and style_state.get("workflow_status") == "anchor_pending"
    ):
        style_state["workflow_status"] = "anchor_generated"


def apply_global_event_effects(
    state: dict[str, Any], event: str, details: dict[str, Any]
) -> None:
    """同步少量顶层阶段状态；事件时间与状态只写一次。"""

    if event == "process_started":
        state["status"] = "running"
    elif event == "preflight_resolved":
        preflight = state.setdefault("preflight", {})
        if isinstance(preflight, dict):
            preflight["status"] = "resolved"
    elif event == "formal_overview_completed":
        output_path = details.get("output_path")
        if isinstance(output_path, str) and output_path:
            overview = state.setdefault("overview", {})
            if isinstance(overview, dict):
                overview["final_path"] = output_path
        if state.get("run_mode") == FAST8_MODE and (
            (state.get("timing_target") or {}).get("scope")
            in {None, "initial_anchor_dispatch_to_formal_overview"}
        ):
            target = state.setdefault(
                "timing_target",
                {"target_minutes": 30, "hard_deadline": False},
            )
            started_at = (state.get("timing") or {}).get(
                "initial_anchor_dispatch_at"
            )
            target["started_at"] = started_at
            target["ended_at"] = details.get("completed_at")
            if not target["ended_at"]:
                target["ended_at"] = (state.get("timing") or {}).get(
                    "formal_overview_completed_at"
                )
            try:
                elapsed_seconds = (
                    parse_time(target["ended_at"]) - parse_time(started_at)
                ).total_seconds()
            except (TypeError, ValueError):
                target["elapsed_minutes"] = None
                target["met"] = None
            else:
                target["elapsed_minutes"] = round(elapsed_seconds / 60, 3)
                target["met"] = elapsed_seconds <= int(
                    target.get("target_minutes") or 30
                ) * 60
            target["soft_target_missed"] = target.get("met") is False
    elif event == "process_completed":
        state["status"] = "completed"
        if state.get("run_mode") == FAST8_MODE:
            target = state.setdefault(
                "timing_target",
                {
                    "target_minutes": 15,
                    "hard_deadline": False,
                    "scope": "request_started_at_to_delivery_ready",
                },
            )
            if target.get("scope") in {
                "request_started_at_to_process_completed",
                "request_started_at_to_delivery_ready",
            }:
                timing = state.get("timing") or {}
                started_at = timing.get("request_started_at") or timing.get(
                    "process_started_at"
                )
                ended_at = details.get("completed_at") or timing.get(
                    "process_completed_at"
                )
                target["started_at"] = started_at
                target["ended_at"] = ended_at
                try:
                    elapsed_seconds = (
                        parse_time(ended_at) - parse_time(started_at)
                    ).total_seconds()
                except (TypeError, ValueError):
                    target["elapsed_minutes"] = None
                    target["met"] = None
                else:
                    target["elapsed_minutes"] = round(elapsed_seconds / 60, 3)
                    target["met"] = elapsed_seconds <= int(
                        target.get("target_minutes") or 15
                    ) * 60
                target["soft_target_missed"] = target.get("met") is False
        if state_audit_version(state) >= CURRENT_STATE_AUDIT_VERSION:
            scheduler = state.setdefault("scheduler", {})
            scheduler["phase"] = "completed"
            for style in (state.get("styles") or {}):
                refresh_style_workflow_status(state, style)


def _matching_active_recovery(
    state: dict[str, Any], style: str | None, page_id: str
) -> dict[str, Any] | None:
    scheduler = state.get("scheduler") or {}
    active = scheduler.get("active_actions") or []
    matches = [
        item
        for item in active
        if isinstance(item, dict)
        and item.get("style") == style
        and str(item.get("page_id")) == page_id
        and item.get("action") == "recover_artifact"
    ]
    if len(matches) > 1:
        raise SystemExit(
            f"style_{style}/{page_id} 存在多个 active recover_artifact，状态损坏"
        )
    return matches[0] if matches else None


def _recovery_event_context(
    state: dict[str, Any],
    style: str | None,
    page_id: str,
    event: str,
    details: dict[str, Any],
) -> dict[str, Any] | None:
    """校验无文件恢复事件，并从 active action 补齐不可猜测的来源元数据。"""

    if event not in {"artifact_recovery_started", "artifact_recovery_finished"}:
        return None
    active = _matching_active_recovery(state, style, page_id)
    if active is None:
        if state_audit_version(state) >= CURRENT_STATE_AUDIT_VERSION:
            raise SystemExit(
                f"style_{style}/{page_id} 没有匹配的 active recover_artifact，"
                "拒绝记录未派发恢复事件"
            )
        return None
    source_action = active.get("source_action")
    if source_action not in GENERATION_ACTIONS:
        raise SystemExit(
            f"style_{style}/{page_id} active recover_artifact 缺少合法 source_action"
        )
    active_attempt = int(active.get("attempt") or 1)
    supplied_attempt = details.get("attempt")
    if supplied_attempt not in {None, active_attempt}:
        raise SystemExit(
            f"style_{style}/{page_id} 恢复事件 attempt 与 active_action 不一致"
        )
    supplied_source_action = details.get("source_action")
    if supplied_source_action not in {None, source_action}:
        raise SystemExit(
            f"style_{style}/{page_id} 恢复事件 source_action 与 active_action 不一致"
        )
    record = page_record(state, style, page_id)
    if state_audit_version(state) >= CURRENT_STATE_AUDIT_VERSION:
        recovery_method = details.get("recovery_method")
        if recovery_method not in {"same_worker", "deterministic_script"}:
            raise SystemExit(
                f"v2 {event} 必须显式记录 "
                "recovery_method=same_worker|deterministic_script"
            )
        required_method = active.get("required_recovery_method")
        if required_method and recovery_method != required_method:
            raise SystemExit(
                f"style_{style}/{page_id} 本轮恢复必须使用 {required_method}，"
                f"实际为 {recovery_method}"
            )
        if (
            event == "artifact_recovery_finished"
            and record.get("artifact_recovery_method") not in {None, recovery_method}
        ):
            raise SystemExit(
                f"style_{style}/{page_id} recovery started/finished 方法不一致"
            )
    if event == "artifact_recovery_started" and record.get("recovery_status") == "running":
        raise SystemExit(f"style_{style}/{page_id} 恢复已经开始，拒绝重复 started")
    if event == "artifact_recovery_finished" and record.get("recovery_status") != "running":
        raise SystemExit(
            f"style_{style}/{page_id} 必须先记录 artifact_recovery_started"
        )
    details.setdefault("source_action", source_action)
    details.setdefault("attempt", active_attempt)
    details.setdefault("worker_agent_id", active.get("worker_agent_id"))
    details.setdefault(
        "recovery_worker_agent_id", active.get("recovery_worker_agent_id")
    )
    for field in (
        "tool_call_id",
        "tool_started_at",
        "tool_finished_at",
        "savedPath",
    ):
        details.setdefault(field, active.get(field))
    return active


def _archive_unbound_attempt(
    record: dict[str, Any],
    active: dict[str, Any],
    recovery_status: str,
    *,
    clear_current: bool = True,
) -> None:
    attempt = int(active.get("attempt") or record.get("attempt_count") or 1)
    history = record.setdefault("attempt_history", [])
    if not isinstance(history, list):
        raise SystemExit("页面 attempt_history 必须是数组")
    active_tool = active.get("tool_call_id")
    same_as_current = bool(active_tool and active_tool == record.get("tool_call_id"))
    archived = {
        "attempt": attempt,
        "action": active.get("source_action"),
        "outcome": f"artifact_recovery_{recovery_status}",
        "worker_agent_id": active.get("worker_agent_id")
        or (record.get("worker_agent_id") if same_as_current else None),
        "tool_call_id": active_tool
        or (record.get("tool_call_id") if same_as_current else None),
        "selected_source": record.get("selected_source") if same_as_current else None,
        "source_sha256": record.get("source_sha256") if same_as_current else None,
        "agent_action_started_at": active.get("agent_action_started_at")
        or (record.get("agent_action_started_at") if same_as_current else None),
        "tool_started_at": active.get("tool_started_at")
        or (record.get("tool_started_at") if same_as_current else None),
        "tool_finished_at": active.get("tool_finished_at")
        or (record.get("tool_finished_at") if same_as_current else None),
        "agent_action_finished_at": active.get("agent_action_finished_at")
        or (record.get("agent_action_finished_at") if same_as_current else None),
    }
    duplicate = any(
        isinstance(item, dict)
        and item.get("attempt") == archived["attempt"]
        and item.get("action") == archived["action"]
        and item.get("tool_call_id") == archived["tool_call_id"]
        for item in history
    )
    if not duplicate:
        history.append(archived)
    if not clear_current:
        return
    for field in (
        "worker_agent_id",
        "backend_used",
        "tool_call_id",
        "selected_source",
        "selected_attempt",
        "selected_action",
        "source_size_bytes",
        "source_sha256",
        "agent_action_started_at",
        "tool_started_at",
        "tool_finished_at",
        "file_validated_at",
        "agent_action_finished_at",
    ):
        record[field] = None


def incumbent_candidate_snapshot(record: dict[str, Any]) -> dict[str, Any] | None:
    """Freeze the candidate that a repair is allowed to replace."""

    if not (record.get("selected_source") or record.get("source_sha256")):
        return None
    snapshot_fields = (
        "worker_agent_id",
        "backend_used",
        "tool_call_id",
        "selected_source",
        "selected_attempt",
        "selected_action",
        "source_size_bytes",
        "source_sha256",
        "agent_action_started_at",
        "tool_started_at",
        "tool_finished_at",
        "file_validated_at",
        "agent_action_finished_at",
        "status",
        "qa_stage",
        "qa_scope",
        "content_gate",
        "spatial_gate",
        "craft_gate",
        "qa_note",
        "failure_reason",
        "overview_qa_at",
        "completed_at",
        "final_path",
    )
    snapshot = {field: record.get(field) for field in snapshot_fields}
    snapshot["attempt"] = int(
        record.get("selected_attempt")
        or record.get("attempt_count")
        or 1
    )
    return snapshot


def _transition_unsuccessful_recovery(
    state_path: Path,
    state: dict[str, Any],
    style: str | None,
    page_id: str,
    timestamp: str,
    details: dict[str, Any],
    active_recovery: dict[str, Any] | None,
) -> dict[str, Any]:
    """关闭 recover action，并原子排入再次恢复、技术重试或明确阻塞。"""

    recovery_status = details.get("recovery_status", details.get("status"))
    if recovery_status == "recovered":
        raise SystemExit(
            "有文件的 recovered 结果必须交给 settle-wave 原子绑定，"
            "不得只记录 artifact_recovery_finished"
        )
    if recovery_status not in {"not_found", "ambiguous", "failed"}:
        return {"next_action": None, "queued_task": None}
    if active_recovery is None:
        return {"next_action": None, "queued_task": None}

    scheduler = state.setdefault("scheduler", {})
    active = scheduler.setdefault("active_actions", [])
    ready = scheduler.setdefault("ready_queue", [])
    recovery_queue = scheduler.setdefault("recovery_queue", [])
    source_action = str(active_recovery["source_action"])
    source_attempt = int(active_recovery.get("attempt") or 1)
    record = page_record(state, style, page_id)

    active[:] = [
        item
        for item in active
        if not (
            item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == "recover_artifact"
        )
    ]
    recovery_queue[:] = [
        item
        for item in recovery_queue
        if not (
            item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == "recover_artifact"
        )
    ]

    finished_events = [
        event
        for event in state.get("events", [])
        if isinstance(event, dict)
        and event.get("style") == style
        and str(event.get("page_id")) == page_id
        and event.get("name") == "artifact_recovery_finished"
    ]
    scoped_finished = [
        event
        for event in finished_events
        if (event.get("details") or {}).get("source_action") == source_action
        and int((event.get("details") or {}).get("attempt") or 1) == source_attempt
    ]
    same_outcome_count = sum(
        (event.get("details") or {}).get(
            "recovery_status", (event.get("details") or {}).get("status")
        )
        == recovery_status
        for event in scoped_finished
    )
    not_found_methods = {
        (event.get("details") or {}).get("recovery_method")
        for event in scoped_finished
        if (event.get("details") or {}).get(
            "recovery_status", (event.get("details") or {}).get("status")
        )
        == "not_found"
    }
    retry_authorized = (
        recovery_status == "not_found"
        and {"same_worker", "deterministic_script"}.issubset(not_found_methods)
    ) or (
        recovery_status == "failed"
        and same_outcome_count >= 2
    ) or (
        # Fast 4x3's thin adapter can prove a legacy handoff is unmappable in
        # one deterministic pass: multiple unbound artifacts exist, but none
        # carries a task/session key that can bind it to the active claims.
        # This exact evidence authorizes the existing attempt-2 budget; it
        # never guesses an artifact and is deliberately scoped away from the
        # Fast8 mainline and all other ambiguous recovery outcomes.
        recovery_status == "ambiguous"
        and state.get("run_mode") == FAST_4X3_MODE
        and details.get("recovery_method") == "deterministic_script"
        and details.get("recovery_basis")
        == "official_script_and_nonpixel_metadata_unbound"
        and isinstance(details.get("candidate_count"), int)
        and int(details.get("candidate_count")) >= 1
    )

    if not retry_authorized:
        queued_task = {
            key: value
            for key, value in active_recovery.items()
            if key
            not in {
                "dispatch_requested_at",
                "recovery_worker_agent_id",
            }
        }
        queued_task.update(
            {
                "style": style,
                "page_id": page_id,
                "action": "recover_artifact",
                "source_action": source_action,
                "attempt": source_attempt,
                "previous_recovery_status": recovery_status,
                "recovery_cycle": int(record.get("recovery_attempt_count") or 0) + 1,
            }
        )
        if recovery_status == "not_found":
            if "same_worker" not in not_found_methods:
                queued_task["required_recovery_method"] = "same_worker"
            elif "deterministic_script" not in not_found_methods:
                queued_task["required_recovery_method"] = "deterministic_script"
        recovery_queue.append(queued_task)
        record["status"] = "recovery_pending"
        record["failure_reason"] = f"artifact_recovery_{recovery_status}"
        append_event(
            state,
            "queued",
            timestamp,
            style=style,
            page_id=page_id,
            action="recover_artifact",
            details={
                "source": "artifact_recovery_finished",
                "source_action": source_action,
                "attempt": source_attempt,
                "previous_recovery_status": recovery_status,
            },
        )
        return {"next_action": "recover_artifact", "queued_task": queued_task}

    max_source_attempt = 3 if source_action in {"repair_anchor", "repair_page"} else 2
    if source_attempt >= max_source_attempt:
        failed_fast8_replacement = (
            state.get("run_mode") == FAST8_MODE
            and source_action == "repair_anchor"
            and active_recovery.get("diversity_replacement") is True
            and isinstance(active_recovery.get("incumbent_candidate"), dict)
        )
        if failed_fast8_replacement:
            incumbent = dict(active_recovery["incumbent_candidate"])
            for field, value in incumbent.items():
                if field != "attempt":
                    record[field] = value
            record["selected_attempt"] = int(incumbent.get("attempt") or 1)
            record["attempt_count"] = max(
                int(record.get("attempt_count") or 0), source_attempt
            )
            failures = record.setdefault("diversity_replacement_failures", [])
            failures.append(
                {
                    "attempt": source_attempt,
                    "recovery_status": recovery_status,
                    "failed_at": timestamp,
                    "reason": "technical_retry_budget_exhausted",
                }
            )
            review = state.setdefault("diversity_review", {})
            review["status"] = "recheck_required"
            review["final_candidate_set_sha256"] = None
            append_event(
                state,
                "diversity_replacement_failed",
                timestamp,
                style=style,
                page_id=page_id,
                action=source_action,
                details={
                    "attempt": source_attempt,
                    "recovery_status": recovery_status,
                    "incumbent_restored": True,
                    "reason": "technical_retry_budget_exhausted",
                },
            )
            return {"next_action": "recheck_diversity", "queued_task": None}
        record["status"] = "blocked"
        record["failure_reason"] = "technical_retry_budget_exhausted"
        append_event(
            state,
            "technical_retry_blocked",
            timestamp,
            style=style,
            page_id=page_id,
            action=source_action,
            details={
                "attempt": source_attempt,
                "recovery_status": recovery_status,
                "reason": "technical_retry_budget_exhausted",
            },
        )
        return {"next_action": "blocked", "queued_task": None}

    incumbent_is_expected = source_action in {"repair_anchor", "repair_page"}
    if (
        (record.get("selected_source") or record.get("source_sha256"))
        and not incumbent_is_expected
    ):
        raise SystemExit(
            f"style_{style}/{page_id} 已有可用产物，禁止授权技术重试"
        )
    duplicate = any(
        item.get("style") == style
        and str(item.get("page_id")) == page_id
        and item.get("action") == source_action
        for item in ready + active
    )
    if duplicate:
        raise SystemExit(
            f"style_{style}/{page_id}/{source_action} 已在队列或 active，"
            "拒绝重复技术重试"
        )
    next_attempt = source_attempt + 1
    retry_job_path = clone_guarded_repair_job_for_technical_retry(
        state_path,
        state,
        style=style,
        page_id=page_id,
        action=source_action,
        source_attempt=source_attempt,
        next_attempt=next_attempt,
    )
    _archive_unbound_attempt(
        record,
        active_recovery,
        recovery_status,
        clear_current=not incumbent_is_expected,
    )
    queued_task = {
        "style": style,
        "page_id": page_id,
        "action": source_action,
        "attempt": next_attempt,
        "technical_retry": True,
        "retry_reason": f"artifact_recovery_{recovery_status}",
        "authorized_at": timestamp,
    }
    incumbent = active_recovery.get("incumbent_candidate")
    if isinstance(incumbent, dict):
        queued_task["incumbent_candidate"] = incumbent
    if active_recovery.get("diversity_replacement") is True:
        queued_task["diversity_replacement"] = True
    if retry_job_path is not None:
        queued_task["generation_job_path"] = str(retry_job_path)
        queued_task["generation_job_sha256"] = file_sha256(retry_job_path)
    ready.append(queued_task)
    record["status"] = "retry_pending"
    record["failure_reason"] = f"technical_retry_after_{recovery_status}"
    record["technical_retry_count"] = int(record.get("technical_retry_count") or 0) + 1
    append_event(
        state,
        "queued",
        timestamp,
        style=style,
        page_id=page_id,
        action=source_action,
        details={
            "source": "artifact_recovery_finished",
            "attempt": next_attempt,
            "technical_retry": True,
            "recovery_status": recovery_status,
        },
    )
    return {"next_action": source_action, "queued_task": queued_task}


def _transition_fast8_backend_failure(
    state_path: Path,
    state: dict[str, Any],
    item: dict[str, Any],
    active_item: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    """Skip artifact recovery when a fast pipeline gets an ImageGen call failure."""

    if state.get("run_mode") not in {
        FAST8_MODE,
        FAST_4X3_MODE,
        SELECTED_STYLE_EXPANSION_MODE,
    }:
        raise SystemExit(
            "ImageGen 后端失败直转只适用于 Fast8、Fast 4x3 或选定风格扩页"
        )
    style = normalize_style(item.get("style"))
    page_id = str(item.get("page_id"))
    action = str(item.get("action"))
    attempt = int(item.get("attempt") or 1)
    if style is None or action not in GENERATION_ACTIONS:
        raise SystemExit("ImageGen 后端失败记录缺少合法任务身份")
    scheduler = state.setdefault("scheduler", {})
    active = scheduler.setdefault("active_actions", [])
    ready = scheduler.setdefault("ready_queue", [])
    recovery_queue = scheduler.setdefault("recovery_queue", [])
    record = page_record(state, style, page_id)
    if any(
        entry.get("style") == style
        and str(entry.get("page_id")) == page_id
        and entry.get("action") == "recover_artifact"
        for entry in recovery_queue
    ):
        raise SystemExit(
            f"style_{style}/{page_id} 后端失败不得同时进入 artifact recovery"
        )
    active[:] = [
        entry
        for entry in active
        if not (
            entry.get("style") == style
            and str(entry.get("page_id")) == page_id
            and entry.get("action") == action
            and int(entry.get("attempt") or 1) == attempt
        )
    ]
    record["attempt_count"] = max(int(record.get("attempt_count") or 0), attempt)
    for field in (
        "worker_agent_id",
        "agent_action_started_at",
        "agent_action_finished_at",
        "tool_call_id",
        "tool_started_at",
        "tool_finished_at",
    ):
        value = item.get(field)
        if value not in {None, ""} and not record.get(field):
            record[field] = value
    history = record.setdefault("attempt_history", [])
    if not isinstance(history, list):
        raise SystemExit("页面 attempt_history 必须是数组")
    archive = {
        "attempt": attempt,
        "action": action,
        "outcome": "imagegen_backend_failed",
        "failure_class": item.get("failure_class") or "backend_failed",
        "tool_error_code": item.get("tool_error_code"),
        "worker_agent_id": item.get("worker_agent_id"),
        "tool_call_id": item.get("tool_call_id"),
        "agent_action_started_at": item.get("agent_action_started_at"),
        "tool_started_at": item.get("tool_started_at"),
        "tool_finished_at": item.get("tool_finished_at"),
        "agent_action_finished_at": item.get("agent_action_finished_at"),
    }
    if not any(
        isinstance(entry, dict)
        and int(entry.get("attempt") or 0) == attempt
        and entry.get("action") == action
        and entry.get("outcome") == "imagegen_backend_failed"
        for entry in history
    ):
        history.append(archive)
    append_event(
        state,
        "imagegen_backend_failed",
        timestamp,
        style=style,
        page_id=page_id,
        action=action,
        details={
            "attempt": attempt,
            "failure_class": archive["failure_class"],
            "tool_error_code": archive["tool_error_code"],
            "artifact_recovery_skipped": True,
        },
    )

    max_attempt = 3 if action in {"repair_anchor", "repair_page"} else 2
    incumbent = active_item.get("incumbent_candidate")
    if attempt >= max_attempt:
        if isinstance(incumbent, dict):
            for field, value in incumbent.items():
                if field != "attempt":
                    record[field] = value
            record["selected_attempt"] = int(incumbent.get("attempt") or 1)
            record["status"] = "candidate_ready"
            record["failure_reason"] = None
            next_action = "recheck_diversity"
        else:
            record["status"] = "blocked"
            record["failure_reason"] = "technical_retry_budget_exhausted"
            next_action = "blocked"
        append_event(
            state,
            "technical_retry_blocked",
            timestamp,
            style=style,
            page_id=page_id,
            action=action,
            details={
                "attempt": attempt,
                "reason": "imagegen_backend_failed",
                "incumbent_restored": isinstance(incumbent, dict),
            },
        )
        if state.get("run_mode") != SELECTED_STYLE_EXPANSION_MODE:
            refresh_style_workflow_status(state, style)
        return {"next_action": next_action, "queued_task": None}

    if any(
        entry.get("style") == style
        and str(entry.get("page_id")) == page_id
        and entry.get("action") == action
        for entry in ready + active
    ):
        raise SystemExit(f"style_{style}/{page_id}/{action} 已存在重复技术重试")
    next_attempt = attempt + 1
    retry_job_path = clone_guarded_repair_job_for_technical_retry(
        state_path,
        state,
        style=style,
        page_id=page_id,
        action=action,
        source_attempt=attempt,
        next_attempt=next_attempt,
    )
    queued_task = {
        "style": style,
        "page_id": page_id,
        "action": action,
        "attempt": next_attempt,
        "technical_retry": True,
        "retry_reason": "imagegen_backend_failed",
        "authorized_at": timestamp,
    }
    if isinstance(incumbent, dict):
        queued_task["incumbent_candidate"] = incumbent
    if active_item.get("diversity_replacement") is True:
        queued_task["diversity_replacement"] = True
    if retry_job_path is not None:
        queued_task["generation_job_path"] = str(retry_job_path)
        queued_task["generation_job_sha256"] = file_sha256(retry_job_path)
    ready.append(queued_task)
    record["status"] = "retry_pending"
    record["failure_reason"] = "technical_retry_after_imagegen_backend_failed"
    record["technical_retry_count"] = int(record.get("technical_retry_count") or 0) + 1
    append_event(
        state,
        "queued",
        timestamp,
        style=style,
        page_id=page_id,
        action=action,
        details={
            "source": "imagegen_backend_failed",
            "attempt": next_attempt,
            "technical_retry": True,
            "artifact_recovery_skipped": True,
        },
    )
    if state.get("run_mode") != SELECTED_STYLE_EXPANSION_MODE:
        refresh_style_workflow_status(state, style)
    return {"next_action": action, "queued_task": queued_task}


def selected_expansion_event_inputs(
    state_path: Path,
    state: dict[str, Any],
    page_id: str | None,
    action: str | None,
    details: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the formal expansion page job; details only identifies that file."""

    if action not in {"generate_page", "repair_page"}:
        raise SystemExit(
            "选定风格扩页只允许 generate_page 或 repair_page 图片动作"
        )
    attempt = details.get("attempt")
    if not isinstance(attempt, int) or attempt < 1:
        raise SystemExit("扩页任务事件必须提供正整数 attempt")

    job_raw = details.get("generation_job_path")
    if not isinstance(job_raw, str) or not job_raw.strip():
        raise SystemExit(
            "新扩页 agent_action_started.details 缺少 generation_job_path"
        )
    job_path = Path(job_raw).expanduser()
    if not job_path.is_absolute() or not job_path.is_file():
        raise SystemExit(f"扩页 generation_job_path 必须是存在的绝对路径：{job_raw}")
    job_path = job_path.resolve()
    project_dir = project_dir_for_state(state_path, state)
    jobs_root = (project_dir / "page_jobs").resolve()
    try:
        job_path.relative_to(jobs_root)
    except ValueError as exc:
        raise SystemExit(f"扩页任务文件必须位于正式 page_jobs 目录：{job_path}") from exc
    job = read_json(job_path)
    if page_id is None:
        raise SystemExit(f"扩页任务缺少目标 page_id：{job_path}")
    expected_job_path = (
        jobs_root / f"page_{page_id}.json"
        if action == "generate_page"
        else jobs_root
        / "repair_jobs"
        / f"page_{page_id}_attempt_{attempt}.json"
    ).resolve()
    if job_path != expected_job_path:
        raise SystemExit(
            f"扩页 action={action} 的 generation_job_path 与 page/attempt 正式路径不一致："
            f"expected={expected_job_path} actual={job_path}"
        )
    if page_id is not None and not page_ids_match(job.get("page_id"), page_id):
        raise SystemExit(f"扩页任务 page_id 与事件不一致：{job_path}")
    selected_style = normalize_style(state.get("selected_style"))
    if selected_style is None:
        raise SystemExit("扩页状态缺少 selected_style")
    if job.get("style_slot") is not None and normalize_style(
        str(job.get("style_slot"))
    ) != selected_style:
        raise SystemExit(f"扩页任务 style_slot 与已选风格不一致：{job_path}")
    job_action = job.get("action")
    if job_action != action:
        raise SystemExit(f"扩页任务 action 与事件不一致：{job_path}")
    if int(job.get("attempt") or 0) != attempt:
        raise SystemExit(f"扩页任务 attempt 与事件不一致：{job_path}")
    page_record_value = (
        (state.get("pages") or {}).get(str(page_id)) if page_id is not None else None
    )
    current_page_source = selected_source_for_record(page_record_value)
    internal_sources = (
        {current_page_source}
        if action == "repair_page" and current_page_source
        else set()
    )
    if action == "repair_page":
        referenced = job.get("imagegen_referenced_paths") or []
        normalized_referenced = {
            str(Path(item).expanduser().resolve())
            for item in referenced
            if isinstance(item, str) and Path(item).expanduser().is_absolute()
        }
        if not current_page_source or current_page_source not in normalized_referenced:
            raise SystemExit(
                f"扩页修复任务必须引用本页当前候选作为 repair source：{job_path}"
            )
    contract, external_assets = validate_generation_job_inputs(
        job_path,
        internal_sources=internal_sources,
        require_prompt_fingerprint=False,
        expected_task={
            "style": selected_style,
            "page_id": str(page_id),
            "action": action,
            "attempt": attempt,
        },
        state=state,
        project_dir=project_dir,
    )
    contract_value = read_json(Path(str(contract["path"])))
    if not page_ids_match(contract_value.get("page_id"), page_id):
        raise SystemExit(f"扩页任务绑定内容合同的 page_id 不一致：{job_path}")
    expected_output = origin_image_target(
        project_dir_for_state(state_path, state), selected_style, str(page_id)
    ).resolve()
    output_raw = job.get("output_target")
    output_path = Path(output_raw).expanduser() if isinstance(output_raw, str) else None
    if (
        output_path is None
        or not output_path.is_absolute()
        or output_path.resolve() != expected_output
    ):
        raise SystemExit(f"扩页任务 output_target 与规范原图路径不一致：{job_path}")
    for item in external_assets:
        item["used_by"] = [selected_style]
    return ([contract], external_assets)


def enforce_selected_expansion_job_guard(
    state_path: Path,
    state: dict[str, Any],
    *,
    page_id: str,
    action: str,
    attempt: int,
    generation_job_path: str,
) -> dict[str, Any]:
    """Guard one formal expansion job before a page Agent is started."""

    base_result = enforce_source_guard(
        state_path,
        state,
        action="selected_style_expansion",
        page_ids=[page_id],
    )
    if base_result is None:
        raise SystemExit(
            "legacy_snapshot_missing：旧扩页任务缺少历史 source snapshot；"
            "请先确认风险或建立新运行目录"
        )
    operation_contracts, operation_assets = selected_expansion_event_inputs(
        state_path,
        state,
        page_id,
        action,
        {
            "generation_job_path": generation_job_path,
            "attempt": attempt,
        },
    )
    if base_result.get("operation_authorized") is True:
        return base_result
    snapshot_path = source_snapshot_path_for_state(state_path, state)
    if snapshot_path is None or not snapshot_path.is_file():
        raise SystemExit("扩页来源门禁缺少已绑定的 source snapshot")
    snapshot = read_json(snapshot_path)
    page_snapshot = dict(snapshot)
    page_snapshot["content_contracts"] = [
        item
        for item in (snapshot.get("content_contracts") or [])
        if page_ids_match(
            read_json(Path(str(item.get("path")))).get("page_id"), page_id
        )
    ]
    page_snapshot["assets"] = [
        item
        for item in (snapshot.get("assets") or [])
        if any(
            page_ids_match(value, page_id)
            for value in (item.get("used_by_pages") or [])
        )
    ]
    if len(page_snapshot["content_contracts"]) != 1:
        raise SystemExit("扩页 source snapshot 缺少本页唯一内容合同路由")
    if not page_snapshot["assets"]:
        raise SystemExit("扩页 source snapshot 缺少本页实际资产路由")
    operation_result = apply_operation_manifest_coverage(
        base_result,
        page_snapshot,
        content_contract_paths=operation_contracts,
        asset_items=operation_assets,
        exact_content_contracts=True,
        exact_assets=True,
        required_asset_roles={"style_anchor"},
        page_ids=[page_id],
    )
    return finalize_source_guard_result(state_path, state, operation_result)


def command_record_event(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    timestamp = args.timestamp or now_iso()
    details = json.loads(args.details_json) if args.details_json else {}
    if not isinstance(details, dict):
        raise SystemExit("--details-json 必须是 JSON 对象")
    timing = state.get("timing") or {}
    scheduler = state.get("scheduler") or {}
    if state_audit_version(state) >= CURRENT_STATE_AUDIT_VERSION and (
        state.get("status") == "completed" or timing.get("process_completed_at")
    ):
        raise SystemExit(
            "process_completed 后正式状态已封存；不得再追加页面、QA 或全局事件"
        )
    if (
        state.get("run_mode") == FAST8_MODE
        and args.event == "page_completed"
        and details.get("completion_status", "accepted") != "candidate_ready"
    ):
        raise SystemExit(
            "Fast8 探索运行的 page_completed 只允许 candidate_ready；"
            "accepted 必须留给用户选定后的独立扩页或下游流程"
        )
    if state.get("run_mode") == FAST8_MODE and (
        args.event in {"formal_overview_completed", "process_completed"}
        or args.event == "page_completed"
    ):
        review = state.get("diversity_review") or {}
        if review.get("status") not in {"pass", "best_effort"}:
            raise SystemExit(
                "Fast8 必须先完成覆盖当前 A-H 的最终差异裁判，"
                "才能标记 candidate_ready 或生成正式总览"
            )
        manifest = fast8_candidate_manifest(state)
        current_set_sha = fast8_candidate_set_sha256(manifest)
        if review.get("final_candidate_set_sha256") != current_set_sha:
            raise SystemExit("Fast8 最终差异报告未绑定当前八张候选，禁止交付")
    is_selected_expansion = (
        state.get("phase") == "selected_style_expansion"
        or state.get("run_mode") == "selected_style_expansion"
    )
    if (
        is_selected_expansion
        and args.event == "agent_action_started"
        and isinstance(args.action, str)
        and args.action != "recover_artifact"
        and (args.action.startswith("generate") or args.action.startswith("repair"))
    ):
        if args.page_id is None:
            raise SystemExit("扩页生成或修复事件必须提供 --page-id")
        job_path = details.get("generation_job_path")
        if not isinstance(job_path, str) or not job_path:
            raise SystemExit(
                "新扩页 agent_action_started.details 缺少 generation_job_path"
            )
        enforce_selected_expansion_job_guard(
            state_path,
            state,
            page_id=str(args.page_id),
            action=args.action,
            attempt=details.get("attempt"),
            generation_job_path=job_path,
        )
    delivery_drift_result: dict[str, Any] | None = None
    style = normalize_style(args.style)
    audit_version = state_audit_version(state)
    recovery_context: dict[str, Any] | None = None

    if audit_version >= CURRENT_STATE_AUDIT_VERSION and args.event == "overview_qa":
        qa_stage = details.get("qa_stage")
        qa_scope = details.get("qa_scope")
        if qa_stage not in QA_STAGES - {None}:
            raise SystemExit("v2 overview_qa 必须显式使用合法 qa_stage")
        if qa_scope not in QA_SCOPES - {None}:
            raise SystemExit("v2 overview_qa 必须显式使用合法 qa_scope")
    if (
        audit_version >= CURRENT_STATE_AUDIT_VERSION
        and args.event in {"artifact_recovery_started", "artifact_recovery_finished"}
        and args.action != "recover_artifact"
    ):
        raise SystemExit("v2 产物恢复事件必须使用 --action recover_artifact")
    if audit_version >= CURRENT_STATE_AUDIT_VERSION and args.event == "process_completed":
        scheduler = state.get("scheduler") or {}
        nonempty = [
            name
            for name in ("active_actions", "ready_queue", "recovery_queue")
            if scheduler.get(name)
        ]
        if nonempty:
            raise SystemExit(
                "process_completed 前调度队列必须为空："
                + ", ".join(nonempty)
            )
        if state.get("run_mode") == FAST8_MODE:
            readiness_errors = fast8_precompletion_errors(state, state_path)
            if readiness_errors:
                raise SystemExit(
                    "Fast8 process_completed 前完整性检查失败："
                    + "；".join(readiness_errors)
                )
    if args.event in {"formal_overview_completed", "process_completed"}:
        delivery_drift_result = enforce_source_guard(
            state_path, state, action="candidate_delivery"
        )

    if args.event in GLOBAL_EVENTS:
        if args.page_id or style:
            raise SystemExit(f"全局事件 {args.event} 不接受 --style 或 --page-id")
        state.setdefault("timing", {})[GLOBAL_EVENTS[args.event]] = timestamp
        apply_global_event_effects(state, args.event, details)
    elif args.event in PAGE_EVENTS:
        if not args.page_id:
            raise SystemExit(f"页面事件 {args.event} 必须提供 --page-id")
        recovery_context = _recovery_event_context(
            state, style, str(args.page_id), args.event, details
        )
        record = page_record(state, style, args.page_id)
        if args.event == "artifact_recovery_started":
            original_finished = (recovery_context or {}).get("tool_finished_at")
            if isinstance(original_finished, str):
                try:
                    if parse_time(original_finished) > parse_time(timestamp):
                        raise SystemExit(
                            f"style_{style}/{args.page_id} 恢复开始早于原图片工具结束"
                        )
                except (TypeError, ValueError) as exc:
                    raise SystemExit(str(exc)) from exc
        elif args.event == "artifact_recovery_finished":
            recovery_started = record.get("artifact_recovery_started_at")
            if not isinstance(recovery_started, str):
                raise SystemExit(
                    f"style_{style}/{args.page_id} 缺少恢复开始时间"
                )
            try:
                if parse_time(recovery_started) > parse_time(timestamp):
                    raise SystemExit(
                        f"style_{style}/{args.page_id} 恢复结束早于恢复开始"
                    )
            except (TypeError, ValueError) as exc:
                raise SystemExit(str(exc)) from exc
        record[PAGE_EVENTS[args.event]] = timestamp
        apply_page_event_effects(record, args.event, args.action, details)
        if args.event in {"file_validated", "page_completed"}:
            refresh_style_workflow_status(state, style)
    else:
        raise SystemExit(f"未知事件：{args.event}")

    append_event(
        state,
        args.event,
        timestamp,
        style=style,
        page_id=args.page_id,
        action=args.action,
        details=details,
    )
    transition = {"next_action": None, "queued_task": None}
    if args.event == "artifact_recovery_finished":
        transition = _transition_unsuccessful_recovery(
            state_path,
            state,
            style,
            str(args.page_id),
            timestamp,
            details,
            recovery_context,
        )
    pending_handoff: tuple[Path, Path, dict[str, Any], str] | None = None
    if (
        args.event == "process_completed"
        and delivery_drift_result is not None
        and source_guard_enabled(state_path, state)
    ):
        project_dir = project_dir_for_state(state_path, state)
        handoff = build_handoff_document(
            project_dir=project_dir,
            state_path=state_path,
            state=state,
            timestamp=timestamp,
            drift_result=delivery_drift_result,
            state_sha256=json_payload_sha256(state),
        )
        markdown = render_handoff_markdown(handoff)
        pending_handoff = (
            project_dir / "state" / "handoff.json",
            project_dir / "state" / "handoff.md",
            handoff,
            markdown,
        )
    atomic_write_json(state_path, state)
    if pending_handoff is not None:
        handoff_json_path, handoff_md_path, handoff, markdown = pending_handoff
        atomic_write_json(handoff_json_path, handoff)
        atomic_write_text(handoff_md_path, markdown)
    monitoring_result: dict[str, Any] | None = None
    if args.event == "process_completed":
        try:
            monitoring_result = write_run_health_report(
                state_path=state_path,
                state=state,
                timestamp=timestamp,
                best_effort_registry=True,
            )
        except (Exception, SystemExit) as exc:
            # Monitoring is deliberately downstream of the sealed state and handoff.
            # A report/index failure must be visible but must never roll back or block
            # an otherwise valid delivery.
            monitoring_result = {
                "status": "warning",
                "health_status": "unknown",
                "report_json": None,
                "report_md": None,
                "registry_warning": str(exc),
            }
    print(
        json.dumps(
            {
                "status": "ok",
                "event": args.event,
                "occurred_at": timestamp,
                "monitoring": monitoring_result,
                **transition,
            },
            ensure_ascii=False,
        )
    )


def require_keys(value: dict[str, Any], keys: list[str], context: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise SystemExit(f"{context} 缺少字段：{', '.join(missing)}")


def uses_unified_spatial_standard(contract: dict[str, Any]) -> bool:
    return contract.get("spatial_standard_version") == CURRENT_SPATIAL_STANDARD_VERSION


def content_contract_prompt_locale(contract: dict[str, Any]) -> str:
    """Choose the control-language locale from the actual required copy.

    `language=source|mixed|multilingual` means preserve the supplied copy; it does
    not mean English.  Validation and prompt compilation must therefore make the
    same deterministic Chinese/English choice from the contract text.
    """

    language = normalize_output_language(contract.get("language"))
    if language.lower().startswith("zh"):
        return "zh"
    if language.lower() not in {"source", "mixed", "multilingual"}:
        return "en"
    text_items = [
        *normalize_prompt_items(contract.get("display_required") or []),
        *normalize_prompt_items(contract.get("display_flexible") or []),
    ]
    flexible_story = str(contract.get("flexible_story") or "").strip()
    if flexible_story:
        text_items.append(flexible_story)
    control_source = " ".join(text_items)
    han_count = len(re.findall(r"[\u3400-\u9fff]", control_source))
    latin_count = len(re.findall(r"[A-Za-z]", control_source))
    return "zh" if han_count >= 12 and han_count * 3 >= latin_count else "en"


def validate_language_presentation(contract: dict[str, Any], context: str) -> None:
    """Validate the optional page-level language presentation without forcing it on old runs."""

    value = contract.get("language_presentation")
    if value is None:
        return
    if not isinstance(value, dict):
        raise SystemExit(f"{context} language_presentation 必须是对象")
    mode = value.get("mode")
    if mode not in {"source", "zh_only", "en_only", "bilingual"}:
        raise SystemExit(
            f"{context} language_presentation.mode 只允许 "
            "source|zh_only|en_only|bilingual"
        )
    pairing = value.get("pairing", "none")
    if pairing not in {"none", "paired", "summary"}:
        raise SystemExit(
            f"{context} language_presentation.pairing 只允许 none|paired|summary"
        )
    pairs = value.get("pairs", [])
    if not isinstance(pairs, list):
        raise SystemExit(f"{context} language_presentation.pairs 必须是数组")
    authorized_signatures = {
        normalize_signature_text(item)
        for item in [
            *normalize_prompt_items(contract.get("display_required") or []),
            contract.get("title"),
            contract.get("subtitle"),
        ]
        if item
    }
    normalized_pairs: list[tuple[str, str]] = []
    for index, item in enumerate(pairs):
        if not isinstance(item, dict):
            raise SystemExit(
                f"{context} language_presentation.pairs[{index}] 必须是对象"
            )
        primary = item.get("primary")
        secondary = item.get("secondary")
        if not isinstance(primary, str) or not primary.strip():
            raise SystemExit(
                f"{context} language_presentation.pairs[{index}].primary 必须是非空字符串"
            )
        if not isinstance(secondary, str) or not secondary.strip():
            raise SystemExit(
                f"{context} language_presentation.pairs[{index}].secondary 必须是非空字符串"
            )
        for role, text in (("primary", primary), ("secondary", secondary)):
            if normalize_signature_text(text) not in authorized_signatures:
                raise SystemExit(
                    f"{context} language_presentation.pairs[{index}].{role} "
                    "必须同时存在于 title/subtitle/display_required"
                )
        normalized_pairs.append((primary.strip(), secondary.strip()))
    delivery = value.get("delivery", "single")
    if delivery not in {"single", "same_page", "split_peer"}:
        raise SystemExit(
            f"{context} language_presentation.delivery 只允许 "
            "single|same_page|split_peer"
        )
    logical_page_id = value.get("logical_page_id")
    peer_page_id = value.get("peer_page_id")
    if logical_page_id is not None and (
        not isinstance(logical_page_id, str) or not logical_page_id.strip()
    ):
        raise SystemExit(f"{context} logical_page_id 必须是非空字符串")
    if delivery == "same_page" and mode != "bilingual":
        raise SystemExit(f"{context} same_page 必须使用 mode=bilingual")
    if delivery == "split_peer":
        if mode not in {"zh_only", "en_only"}:
            raise SystemExit(
                f"{context} split_peer 必须使用 mode=zh_only|en_only"
            )
        if not isinstance(logical_page_id, str) or not logical_page_id.strip():
            raise SystemExit(f"{context} split_peer 必须提供 logical_page_id")
        if not isinstance(peer_page_id, str) or not peer_page_id.strip():
            raise SystemExit(f"{context} split_peer 必须提供 peer_page_id")
        if normalize_signature_text(peer_page_id) == normalize_signature_text(
            contract.get("page_id")
        ):
            raise SystemExit(f"{context} split_peer 不得指向自身")
    elif peer_page_id not in {None, ""}:
        raise SystemExit(f"{context} 非 split_peer 不得提供 peer_page_id")
    if mode == "bilingual":
        if pairing not in {"paired", "summary"} or not normalized_pairs:
            raise SystemExit(
                f"{context} bilingual 必须提供 pairing=paired|summary 和至少一组 pairs"
            )
    elif pairing != "none" or normalized_pairs:
        raise SystemExit(
            f"{context} 非 bilingual 页面必须使用 pairing=none 且 pairs=[]"
        )


def validate_language_presentation_bundle(
    contracts: dict[str, dict[str, Any]], context: str
) -> None:
    """Require both isolated physical pages for every split bilingual logical page."""

    split_pages: dict[str, dict[str, Any]] = {}
    for page_id, contract in contracts.items():
        presentation = contract.get("language_presentation")
        if not isinstance(presentation, dict):
            continue
        if presentation.get("delivery") == "split_peer":
            split_pages[str(page_id)] = presentation
    for page_id, presentation in split_pages.items():
        peer_page_id = str(presentation["peer_page_id"])
        if peer_page_id not in split_pages:
            raise SystemExit(
                f"{context} split_peer {page_id} 缺少兄弟物理页 {peer_page_id}"
            )
        peer = split_pages[peer_page_id]
        if str(peer.get("peer_page_id")) != page_id:
            raise SystemExit(
                f"{context} split_peer {page_id}/{peer_page_id} 必须互相引用"
            )
        if normalize_signature_text(peer.get("logical_page_id")) != normalize_signature_text(
            presentation.get("logical_page_id")
        ):
            raise SystemExit(
                f"{context} split_peer {page_id}/{peer_page_id} logical_page_id 不一致"
            )
        modes = {presentation.get("mode"), peer.get("mode")}
        if modes != {"zh_only", "en_only"}:
            raise SystemExit(
                f"{context} split_peer {page_id}/{peer_page_id} 必须恰有一中一英"
            )


def spatial_contract_required_keys(contract: dict[str, Any]) -> list[str]:
    if uses_unified_spatial_standard(contract):
        return ["spatial_standard_version", "spatial_feasibility"]
    return ["spatial_pressure_profile", "low_pressure_feasibility"]


def validate_dispatchable_content_contract(
    contract: dict[str, Any], context: str, *, soft_spatial_preference: bool = False
) -> None:
    """阻止未完成空间预检或仍待用户决定的页面进入图片队列。"""
    require_keys(
        contract,
        [
            "content_load_review",
            "content_resolution",
            *spatial_contract_required_keys(contract),
        ],
        context,
    )
    if contract.get("content_contract_version") != 2:
        raise SystemExit(f"{context} 必须使用 content_contract_version=2")
    validate_language_presentation(contract, context)

    prompt_version = contract.get("prompt_contract_version")
    if uses_unified_spatial_standard(contract) and prompt_version != 4:
        raise SystemExit(
            f"{context} 统一空间标准必须配套 prompt_contract_version=4"
        )
    if prompt_version in {2, 3, 4}:
        require_keys(
            contract,
            ["spatial_generation_brief", "spatial_qa_contract"],
            context,
        )
        for field in ("spatial_generation_brief", "spatial_qa_contract"):
            value = contract.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SystemExit(f"{context} 缺少非空 {field}")
        if prompt_version in {3, 4}:
            if prompt_version == 4:
                locale = content_contract_prompt_locale(contract)
                if uses_unified_spatial_standard(contract):
                    expected_brief = UNIFIED_SPATIAL_PROMPT_CUES[locale]
                else:
                    profile = contract.get("spatial_pressure_profile")
                    if profile not in {"default", "low"}:
                        raise SystemExit(
                            f"{context} legacy spatial_pressure_profile 只允许 default|low"
                        )
                    expected_brief = QUICK8_BREATHING_PROMPT_CUES[locale][profile]
            else:
                profile = contract.get("spatial_pressure_profile")
                if profile not in {"default", "low"}:
                    raise SystemExit(
                        f"{context} legacy spatial_pressure_profile 只允许 default|low"
                    )
                expected_brief = SPATIAL_PROMPT_CUES[profile]
            supplied_brief = contract.get("spatial_generation_brief", "").strip()
            accepted_briefs = {expected_brief}
            if prompt_version == 3:
                accepted_briefs.add(LEGACY_SPATIAL_PROMPT_CUES[profile])
            if supplied_brief not in accepted_briefs:
                raise SystemExit(
                    f"{context} v{prompt_version} spatial_generation_brief 必须使用统一短句："
                    f"{expected_brief}"
                )
            require_keys(
                contract,
                [
                    "prompt_semantic_guardrails",
                    "prompt_user_constraints",
                    "information_density_target",
                ],
                context,
            )
            for field, max_chars in (
                ("prompt_semantic_guardrails", 300),
                ("prompt_user_constraints", 240),
            ):
                values = contract.get(field)
                if not isinstance(values, list) or len(values) > 3:
                    raise SystemExit(f"{context} {field} 必须是 0–3 条字符串")
                normalized = []
                for index, value in enumerate(values):
                    if not isinstance(value, str) or not value.strip():
                        raise SystemExit(f"{context} {field}[{index}] 必须是非空字符串")
                    value = value.strip()
                    if len(value) > 120:
                        raise SystemExit(f"{context} {field}[{index}] 超过 120 字")
                    normalized.append(value)
                if sum(map(len, normalized)) > max_chars:
                    raise SystemExit(f"{context} {field} 合计超过 {max_chars} 字")
            density = contract.get("information_density_target")
            if density not in DENSITY_PROMPT_LABELS:
                raise SystemExit(
                    f"{context} information_density_target 只允许 low|medium|high"
                )
            if prompt_version == 4:
                if "display_flexible" not in contract:
                    raise SystemExit(f"{context} v4 缺少 display_flexible（允许空数组）")
                flexible = contract.get("display_flexible")
                if not isinstance(flexible, list):
                    raise SystemExit(f"{context} display_flexible 必须是字符串数组")
                for index, value in enumerate(flexible):
                    if not isinstance(value, str) or not value.strip():
                        raise SystemExit(
                            f"{context} display_flexible[{index}] 必须是非空字符串"
                        )
                for field, limit in (
                    ("visual_quality_intent", VISUAL_QUALITY_INTENT_LIMIT),
                    ("relationship_thesis", RELATIONSHIP_SYNTHESIS_BRIEF_LIMIT),
                    ("flexible_story", FLEXIBLE_STORY_LIMIT),
                    (
                        "relationship_synthesis_brief",
                        RELATIONSHIP_SYNTHESIS_BRIEF_LIMIT,
                    ),
                ):
                    value = contract.get(field)
                    if value is None:
                        continue
                    if not isinstance(value, str) or not value.strip():
                        raise SystemExit(f"{context} {field} 若提供必须是非空字符串")
                    if len(value.strip()) > limit:
                        raise SystemExit(
                            f"{context} {field} 过长：{len(value.strip())} > {limit}"
                        )
                if contract.get("relationship_thesis") and contract.get(
                    "relationship_synthesis_brief"
                ):
                    raise SystemExit(
                        f"{context} relationship_thesis 与旧别名 "
                        "relationship_synthesis_brief 不得同时填写"
                    )
    else:
        breathing = contract.get("spatial_breathing_contract")
        if not isinstance(breathing, str) or not breathing.strip():
            raise SystemExit(f"{context} 缺少非空 spatial_breathing_contract")

    resolution = contract.get("content_resolution")
    if not isinstance(resolution, dict):
        raise SystemExit(f"{context} content_resolution 必须是对象")
    resolution_status = resolution.get("status")
    if resolution_status not in {"not_needed", "confirmed"}:
        raise SystemExit(
            f"{context} content_resolution.status={resolution_status!r}，"
            "仍待内容决定，不得派发"
        )

    if uses_unified_spatial_standard(contract):
        if contract.get("spatial_feasibility") != "pass":
            raise SystemExit(
                f"{context} 统一空间标准页面必须 spatial_feasibility=pass，"
                f"当前为 {contract.get('spatial_feasibility')!r}"
            )
        if "spatial_pressure_profile" in contract or "low_pressure_feasibility" in contract:
            raise SystemExit(
                f"{context} 统一空间标准不得继续写入 low/default 档位或 Low 可行性字段"
            )
    else:
        profile = contract.get("spatial_pressure_profile")
        if profile not in {"default", "low"}:
            raise SystemExit(f"{context} legacy spatial_pressure_profile 只允许 default|low")
        feasibility = contract.get("low_pressure_feasibility")
        if profile == "low" and soft_spatial_preference:
            if feasibility not in {"pass", "soft_target_unmet"}:
                raise SystemExit(
                    f"{context} legacy Fast 4x3 的 Low 软目标只允许 "
                    "low_pressure_feasibility=pass|soft_target_unmet，"
                    f"当前为 {feasibility!r}"
                )
        elif profile == "low" and feasibility != "pass":
            raise SystemExit(
                f"{context} legacy Low 页面必须 low_pressure_feasibility=pass，"
                f"当前为 {feasibility!r}"
            )
        if profile == "default" and feasibility != "not_applicable":
            raise SystemExit(
                f"{context} legacy Default 页面必须 low_pressure_feasibility=not_applicable，"
                f"当前为 {feasibility!r}"
            )

    review = contract.get("content_load_review")
    if not isinstance(review, dict):
        raise SystemExit(f"{context} content_load_review 必须是对象")
    require_keys(
        review,
        [
            "semantic_structure",
            "focus_relationship",
            "attention_risks",
            "edge_and_takeaway_risks",
            "duplication_risks",
            "reason",
        ],
        f"{context}.content_load_review",
    )
    if not isinstance(review.get("semantic_structure"), str) or not review[
        "semantic_structure"
    ].strip():
        raise SystemExit(f"{context} 空间预检缺少 semantic_structure")
    if not isinstance(review.get("focus_relationship"), str) or not review[
        "focus_relationship"
    ].strip():
        raise SystemExit(f"{context} 空间预检缺少 focus_relationship")


def accepted_anchor(state: dict[str, Any], style: str, page_id: str) -> dict[str, Any]:
    record = page_record(state, style, page_id)
    if record.get("status") != "accepted":
        raise SystemExit(f"style_{style}/{page_id} 锚点尚未 accepted")
    if (record.get("content_gate") or {}).get("status") != "pass":
        raise SystemExit(f"style_{style}/{page_id} content_gate 尚未通过")
    if (record.get("spatial_gate") or {}).get("status") != "pass":
        raise SystemExit(f"style_{style}/{page_id} spatial_gate 尚未通过")
    if state.get("quality_contract_version") == 2:
        if (record.get("craft_gate") or {}).get("status") != "pass":
            raise SystemExit(f"style_{style}/{page_id} craft_gate 尚未通过")
    source = record.get("selected_source")
    if not isinstance(source, str) or not Path(source).is_file():
        raise SystemExit(f"style_{style}/{page_id} 缺少可读 selected_source")
    return record


def candidate_anchor(state: dict[str, Any], style: str, page_id: str) -> dict[str, Any]:
    """Fast 4x3 只要求锚点产物有效，不伪装成通过三道正式质量门。"""

    record = page_record(state, style, page_id)
    if record.get("status") not in {"generated", "candidate_ready", "accepted"}:
        raise SystemExit(f"style_{style}/{page_id} 锚点尚无可用候选")
    if not record.get("file_validated_at") or not record.get("tool_call_id"):
        raise SystemExit(f"style_{style}/{page_id} 锚点尚未完成文件校验")
    source = record.get("selected_source")
    if not isinstance(source, str) or not Path(source).is_file():
        raise SystemExit(f"style_{style}/{page_id} 缺少可读 selected_source")
    return record


def build_contract(
    state: dict[str, Any], style: str, seed: dict[str, Any], anchor: dict[str, Any]
) -> dict[str, Any]:
    if seed.get("style_contract_version") == 2:
        unified_spatial = (
            seed.get("project_spatial_standard_version")
            == CURRENT_SPATIAL_STANDARD_VERSION
        )
        required_v2 = [
            "tone",
            "reference_intent",
            "visual_invariants",
            "page_shell_contract",
            "information_density_target",
            *(
                ["project_spatial_standard_version"]
                if unified_spatial
                else ["project_spatial_pressure_default"]
            ),
            "project_spatial_generation_brief",
            "project_spatial_qa_contract",
            "visual_support_brief",
            "craft_ambition",
            "open_dimensions",
        ]
        require_keys(seed, required_v2, f"style_{style} contract seed")
        contract = {
            "run_id": state.get("run_id"),
            "style_contract_version": 2,
            "style_slot": style,
            "tone": seed["tone"],
            **(
                {
                    "language": normalize_output_language(
                        seed.get("language") or state.get("language")
                    )
                }
                if seed.get("language") or state.get("language")
                else {}
            ),
            "image_backend": seed.get("image_backend", "built-in image_gen"),
            "anchor": {
                "index": 1,
                "path": anchor["selected_source"],
                "role": "primary_style_anchor",
            },
            "required_assets": non_global_chrome_assets(seed.get("required_assets", [])),
            "anchor_policy": {
                "fixed_input_order": True,
                "style_only": True,
                "no_layout_copy": True,
                "no_cumulative_learning": True,
                "anchor_image_has_visual_priority": True,
            },
            "reference_intent": seed["reference_intent"],
            "visual_invariants": seed["visual_invariants"],
            "page_shell_contract": seed["page_shell_contract"],
            "information_density_target": seed["information_density_target"],
            **(
                {
                    "project_spatial_standard_version": CURRENT_SPATIAL_STANDARD_VERSION
                }
                if unified_spatial
                else {
                    "project_spatial_pressure_default": seed[
                        "project_spatial_pressure_default"
                    ]
                }
            ),
            "project_spatial_generation_brief": seed[
                "project_spatial_generation_brief"
            ],
            "project_spatial_qa_contract": seed["project_spatial_qa_contract"],
            "visual_support_brief": seed["visual_support_brief"],
            "craft_ambition": seed["craft_ambition"],
            "open_dimensions": seed["open_dimensions"],
            "generation_rules": {
                "quality": "final",
                "aspect_ratio": "16:9",
                "max_total_attempts_per_page": 3,
                "craft_gate_required": True,
                "subjective_alternative_retry": False,
                "overview_qa_required": True,
            },
        }
        if state.get("global_chrome_contract_path"):
            contract["global_chrome_contract_path"] = state[
                "global_chrome_contract_path"
            ]
            contract["global_chrome_contract_sha256"] = state.get(
                "global_chrome_contract_sha256"
            )
        return contract

    required = [
        "tone",
        "visual_identity",
        "page_shell_contract",
        "information_density_contract",
        "project_spatial_pressure_default",
        "project_spatial_breathing_default",
        "visual_support_contract",
    ]
    require_keys(seed, required, f"style_{style} contract seed")
    contract = {
        "run_id": state.get("run_id"),
        "style_slot": style,
        "tone": seed["tone"],
        **(
            {
                "language": normalize_output_language(
                    seed.get("language") or state.get("language")
                )
            }
            if seed.get("language") or state.get("language")
            else {}
        ),
        "image_backend": seed.get("image_backend", "built-in image_gen"),
        "anchor": {
            "index": 1,
            "path": anchor["selected_source"],
            "role": "primary_style_anchor",
        },
        "required_assets": non_global_chrome_assets(seed.get("required_assets", [])),
        "anchor_policy": {
            "fixed_input_order": True,
            "style_only": True,
            "no_layout_copy": True,
            "no_cumulative_learning": True,
        },
        "visual_identity": seed["visual_identity"],
        "page_shell_contract": seed["page_shell_contract"],
        "information_density_contract": seed["information_density_contract"],
        "project_spatial_pressure_default": seed["project_spatial_pressure_default"],
        "project_spatial_breathing_default": seed["project_spatial_breathing_default"],
        "visual_support_contract": seed["visual_support_contract"],
        "generation_rules": {
            "quality": "final",
            "aspect_ratio": "16:9",
            "max_total_attempts_per_page": 3,
            "subjective_aesthetic_retry": False,
            "overview_qa_required": True,
        },
    }
    if state.get("global_chrome_contract_path"):
        contract["global_chrome_contract_path"] = state["global_chrome_contract_path"]
        contract["global_chrome_contract_sha256"] = state.get(
            "global_chrome_contract_sha256"
        )
    return contract


def build_fast_candidate_contract(
    state: dict[str, Any],
    style: str,
    anchor: dict[str, Any],
    anchor_job: dict[str, Any],
) -> dict[str, Any]:
    """从实际锚点和轻量探索方向直接建立 Fast 4x3 跟随合同。"""

    direction = anchor_job.get("layout_direction") or {}
    layout_version = direction.get("layout_contract_version")
    if layout_version == CURRENT_4X3_LAYOUT_VERSION:
        family_version = direction.get("style_family_portfolio_version")
        direction_field = "first_impression"
        direction_value = direction.get(direction_field)
        contract_version = (
            5
            if family_version == CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
            else 4
        )
    else:
        # 旧 Fast v4 项目按原 creative_direction 恢复，不重编历史任务。
        direction_field = "creative_direction"
        direction_value = direction.get(direction_field)
        contract_version = 3
        if not isinstance(direction_value, str) or not direction_value.strip():
            raise SystemExit(
                f"style_{style} 旧 Fast 4x3 锚点任务缺少 creative_direction"
            )
    anchor_page = anchor_job.get("anchor_page") or {}
    reference_intent = []
    for item in anchor_job.get("reference_images") or []:
        if isinstance(item, dict) and item.get("reference_intent"):
            reference_intent.append(item["reference_intent"])
    contract = {
        "run_id": state.get("run_id"),
        "style_contract_version": contract_version,
        "candidate_contract": True,
        "style_slot": style,
        "tone": anchor_job.get("tone"),
        "language": normalize_output_language(
            anchor_job.get("language") or state.get("language")
        ),
        "image_backend": "built-in image_gen",
        "anchor": {
            "index": 1,
            "path": anchor["selected_source"],
            "role": "primary_style_anchor",
        },
        "required_assets": non_global_chrome_assets(
            anchor_job.get("required_assets", [])
        ),
        "anchor_policy": {
            "fixed_input_order": True,
            "style_only": True,
            "no_layout_copy": True,
            "no_cumulative_learning": True,
            "anchor_image_has_visual_priority": True,
        },
        **(
            {direction_field: direction_value.strip()}
            if isinstance(direction_value, str) and direction_value.strip()
            else {}
        ),
        "direction_id": direction.get("direction_id"),
        "layout_contract_version": layout_version,
        **(
            {
                "art_direction_contract_version": ART_DIRECTION_CONTRACT_VERSION,
                "style_family_portfolio_version": (
                    CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
                ),
                "style_family_thesis": direction.get("style_family_thesis"),
                "relationship_representation_family": direction.get(
                    "relationship_representation_family"
                ),
                "craft_axis": direction.get("craft_axis"),
                "visual_activity_mode": direction.get("visual_activity_mode"),
                "attention_strategy": direction.get("attention_strategy"),
                "spatial_topology": direction.get("spatial_topology"),
                "adaptation_principle": direction.get("adaptation_principle"),
                "continuity_invariants": direction.get("continuity_invariants"),
                "anchor_visual_thesis": direction.get("visual_thesis"),
            }
            if contract_version == 5
            else {}
        ),
        "reference_intent": reference_intent,
        "visual_invariants": [
            "实际锚点图片是视觉家族的第一证据",
            "延续锚点的明暗、色彩、字体气质、材质与图像工艺",
            "具体内容区构图随当前页面变化，不把锚点复制成模板",
        ],
        "page_shell_contract": {
            "brand_and_header": "继承锚点的品牌与标题气质，不锁定像素坐标",
            "content_zone": "保持完整 16:9 安全区，内容构图开放",
            "takeaway": "仅在产生新结论时使用",
            "geometry_note": "继承视觉家族，不复制锚点的具体布局",
        },
        **(
            {
                "project_spatial_standard_version": CURRENT_SPATIAL_STANDARD_VERSION,
                "project_spatial_qa_contract": anchor_page.get("spatial_qa_contract"),
            }
            if uses_unified_spatial_standard(anchor_page)
            else {
                "project_spatial_pressure_default": anchor_page.get(
                    "spatial_pressure_profile", "low"
                ),
                "spatial_preference_mode": "soft",
            }
        ),
        "project_spatial_generation_brief": anchor_page.get(
            "spatial_generation_brief",
            UNIFIED_SPATIAL_PROMPT_CUES["zh"]
            if uses_unified_spatial_standard(anchor_page)
            else SPATIAL_PROMPT_CUES["low"],
        ),
        "candidate_policy": {
            "mode": "one_shot_final_quality",
            "automatic_visual_retries_before_selection": 0,
            "max_technical_retries_after_missing_or_invalid_artifact": 1,
            "selected_candidate_max_targeted_edits": 1,
            "precompiled_follower_prompt": contract_version in {4, 5},
            "three_page_visual_family_method": contract_version == 5,
        },
        "generation_rules": {
            "quality": "final",
            "aspect_ratio": "16:9",
            "max_total_attempts_per_page": 1,
            "craft_gate_required": False,
            "overview_qa_required": False,
            "automatic_visual_retry_before_selection": False,
            "subjective_alternative_retry": False,
        },
    }
    if anchor_job.get("global_chrome"):
        contract["global_chrome_contract_path"] = (
            anchor_job["global_chrome"].get("contract_path")
        )
        contract["global_chrome_contract_sha256"] = (
            anchor_job["global_chrome"].get("contract_sha256")
        )
    return contract


def initial_page_state(role: str, queued_at: str) -> dict[str, Any]:
    return {
        "role": role,
        "status": "pending",
        "qa_stage": None,
        "qa_scope": None,
        "content_gate": None,
        "spatial_gate": None,
        "craft_gate": None,
        "worker_agent_id": None,
        "backend_used": None,
        "tool_call_id": None,
        "selected_source": None,
        "selected_attempt": None,
        "selected_action": None,
        "source_size_bytes": None,
        "source_sha256": None,
        "attempt_count": 0,
        "attempt_sources": [],
        "final_path": None,
        "qa_note": None,
        "failure_reason": None,
        "queued_at": queued_at,
        "agent_action_started_at": None,
        "tool_started_at": None,
        "tool_finished_at": None,
        "recovery_required": False,
        "recovery_status": None,
        "recovery_attempt_count": 0,
        "artifact_recovery_method": None,
        "artifact_recovery_started_at": None,
        "artifact_recovery_finished_at": None,
        "file_validated_at": None,
        "agent_action_finished_at": None,
        "overview_qa_at": None,
        "completed_at": None,
    }


def parse_json_array(value: str, flag: str) -> list[Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{flag} 不是有效 JSON：{exc}") from exc
    if not isinstance(parsed, list):
        raise SystemExit(f"{flag} 必须是 JSON 数组")
    return parsed


def normalize_director_required_assets(
    payload: Any,
    *,
    expected_page_id: str,
    source_label: str,
) -> list[Any]:
    """Normalize a content-director asset envelope without creative rewriting.

    The stable runtime contract remains a top-level array.  A constrained
    director may emit the documented v1 envelope while carrying authorization
    and routing metadata.  This adapter only projects those existing fields to
    the runtime aliases; it never selects, drops, reorders or invents assets.
    """

    envelope = False
    if isinstance(payload, list):
        raw_assets = payload
    elif isinstance(payload, dict):
        page_value = payload.get("canonical_page_id", payload.get("page_id"))
        if page_value is not None and str(page_value) != str(expected_page_id):
            raise SystemExit(
                f"{source_label} 页码与当前运行不一致："
                f"{page_value!r} != {expected_page_id!r}"
            )
        if isinstance(payload.get("assets"), list):
            version = payload.get("asset_contract_version")
            if version != 1:
                raise SystemExit(
                    f"{source_label}.asset_contract_version 必须为 1"
                )
            raw_assets = payload["assets"]
            envelope = True
        elif isinstance(payload.get("required_assets"), list):
            version = payload.get("required_assets_contract_version", 1)
            if version != 1:
                raise SystemExit(
                    f"{source_label}.required_assets_contract_version 必须为 1"
                )
            raw_assets = payload["required_assets"]
            envelope = True
        else:
            raise SystemExit(
                f"{source_label} 必须是顶层数组，或包含 v1 assets/required_assets 数组"
            )
    else:
        raise SystemExit(f"{source_label} 必须是 JSON 数组或受支持的 v1 对象")

    normalized: list[Any] = []
    for index, item in enumerate(raw_assets):
        if isinstance(item, str):
            raw_path = item
            projected: Any = item
        elif isinstance(item, dict):
            projected = dict(item)
            raw_path = projected.get("path")
            if envelope:
                if not isinstance(projected.get("role"), str) or not str(
                    projected.get("role")
                ).strip():
                    raw_role = projected.get("type")
                    if isinstance(raw_role, str) and raw_role.strip():
                        projected["role"] = raw_role.strip()
                projected.setdefault("asset_type", "required_asset")
                if "use" not in projected and isinstance(
                    projected.get("requirements"), str
                ):
                    projected["use"] = projected["requirements"]
                if "tones" not in projected and isinstance(
                    projected.get("required_when"), str
                ):
                    tone_map = {
                        "light_background": ["light"],
                        "dark_background": ["dark"],
                    }
                    required_when = projected["required_when"].strip().lower()
                    if required_when not in tone_map:
                        raise SystemExit(
                            f"{source_label}[{index}].required_when 不受支持："
                            f"{projected['required_when']}"
                        )
                    projected["tones"] = tone_map[required_when]
        else:
            raise SystemExit(f"{source_label}[{index}] 必须是路径字符串或对象")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise SystemExit(f"{source_label}[{index}] 缺少非空 path")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise SystemExit(f"{source_label}[{index}].path 必须是绝对路径")
        path = path.resolve()
        if not path.is_file():
            raise SystemExit(f"{source_label}[{index}].path 不存在：{path}")
        path_key = str(path)
        if isinstance(projected, dict):
            projected["path"] = path_key
            declared_sha = projected.get("sha256")
            actual_sha = file_sha256(path)
            if isinstance(declared_sha, str) and declared_sha != actual_sha:
                raise SystemExit(f"{source_label}[{index}].sha256 与文件不一致：{path}")
            # The director chooses an authorized path and routing role. File
            # identity is deterministic plumbing, so never require a model to
            # calculate it or trigger a repair round for an omitted hash.
            projected["sha256"] = actual_sha
        else:
            projected = path_key
        normalized.append(projected)
    return normalized


def read_required_assets_input(
    *,
    json_value: str | None,
    file_value: str | None,
    expected_page_id: str,
) -> list[Any]:
    if json_value is not None and file_value is not None:
        raise SystemExit("--required-assets-json 与 --required-assets-file 只能使用一个")
    if file_value is not None:
        path = Path(file_value).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SystemExit(f"--required-assets-file 不存在：{path}") from exc
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--required-assets-file 不是有效 JSON：{path}：{exc}") from exc
        return normalize_director_required_assets(
            payload,
            expected_page_id=expected_page_id,
            source_label=str(path),
        )
    if json_value is None:
        return []
    try:
        payload = json.loads(json_value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--required-assets-json 不是有效 JSON：{exc}") from exc
    return normalize_director_required_assets(
        payload,
        expected_page_id=expected_page_id,
        source_label="--required-assets-json",
    )


def routed_style_values(
    item: dict[str, Any], field_name: str, index: int
) -> list[str] | None:
    """Read attachment routing from the accepted input aliases.

    ``style_slots`` is the documented authoring field. ``styles`` is retained for
    source-snapshot compatibility, while ``used_by`` lets a previously emitted
    snapshot record be reused without silently losing its routing.  If callers
    provide more than one alias they must agree.
    """

    routed_fields: list[tuple[str, list[str]]] = []
    for routing_field in ("style_slots", "styles", "used_by"):
        raw = item.get(routing_field)
        if raw is None:
            continue
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raise SystemExit(
                f"{field_name}[{index}].{routing_field} 必须是数组或字符串"
            )
        normalized: list[str] = []
        for value in raw:
            style = normalize_style(str(value))
            if style is None:
                raise SystemExit(
                    f"{field_name}[{index}].{routing_field} 包含无效席位：{value}"
                )
            if style not in normalized:
                normalized.append(style)
        # source_snapshot 输出的空 used_by 表示没有显式路由，而不是禁用资产。
        if routing_field == "used_by" and not normalized:
            continue
        routed_fields.append((routing_field, normalized))
    if not routed_fields:
        return None
    canonical = routed_fields[0][1]
    for routing_field, values in routed_fields[1:]:
        if set(values) != set(canonical):
            names = ", ".join(name for name, _ in routed_fields)
            raise SystemExit(
                f"{field_name}[{index}] 的路由字段冲突：{names} 必须表达同一席位集合"
            )
    return canonical


def filter_routed_attachments(
    items: list[Any], style: str, tone: str, field_name: str
) -> list[Any]:
    """只把明确适用于当前席位或明暗方向的附件写入任务。"""

    normalized_style = style.upper().removeprefix("STYLE_")
    normalized_tone = tone.lower()
    filtered: list[Any] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            if not item.strip():
                raise SystemExit(f"{field_name}[{index}] 路径不能为空")
            filtered.append(item)
            continue
        if not isinstance(item, dict):
            raise SystemExit(f"{field_name}[{index}] 必须是路径字符串或对象")
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise SystemExit(f"{field_name}[{index}] 缺少非空 path")

        slots = routed_style_values(item, field_name, index)
        if slots is not None:
            if normalized_style not in slots:
                continue

        tones = item.get("tones")
        if tones is not None:
            if not isinstance(tones, list):
                raise SystemExit(f"{field_name}[{index}].tones 必须是数组")
            normalized_tones = {str(value).lower() for value in tones}
            if normalized_tone not in normalized_tones:
                continue

        filtered.append(item)
    return filtered


def filter_reference_images(
    reference_images: list[Any], style: str, tone: str
) -> list[Any]:
    return filter_routed_attachments(reference_images, style, tone, "reference_images")


def validate_new_fast8_style_references(reference_images: list[Any]) -> None:
    """Keep Fast8 style references distinct from page evidence and required assets."""

    for index, item in enumerate(reference_images):
        if not isinstance(item, dict):
            raise SystemExit(
                f"Fast8 reference_images[{index}] 必须是带显式 role 的对象；"
                "风格图使用 primary_style_reference/supporting_style_reference，"
                "项目证据、源页面、产品和 Logo 请移入 required_assets"
            )
        role = item.get("role")
        normalized_role = (
            role.strip().lower() if isinstance(role, str) else ""
        )
        if normalized_role not in FAST8_STYLE_REFERENCE_ROLES:
            role_label = role if isinstance(role, str) and role.strip() else "<missing>"
            raise SystemExit(
                f"Fast8 reference_images[{index}].role={role_label!r} 不是风格参考角色；"
                "项目视觉证据、源页面、照片、产品和 Logo 请移入 required_assets，"
                "真正的风格图请标为 primary_style_reference 或 "
                "supporting_style_reference"
            )


def filter_required_assets(
    required_assets: list[Any], style: str, tone: str
) -> list[Any]:
    return filter_routed_attachments(required_assets, style, tone, "required_assets")


def snapshot_tagged_asset(
    item: Any, *, asset_type: str, style: str
) -> dict[str, Any]:
    """Write one already-filtered asset with a single canonical snapshot route."""

    if not isinstance(item, dict):
        return {"path": item, "asset_type": asset_type, "styles": [style]}
    tagged = {
        key: value
        for key, value in item.items()
        if key not in {"style_slots", "styles", "used_by"}
    }
    tagged["asset_type"] = asset_type
    tagged["styles"] = [style]
    return tagged


DIRECTOR_DIRECTION_FIELDS = (
    "direction_id",
    "mother_structure",
    "layout_variant",
    "reading_path",
    "visual_emphasis",
    "image_text_strategy",
    "difference_key",
)
DIRECTOR_CONTRAST_AXES = {
    "geometry",
    "reading_path",
    "visual_emphasis",
    "image_text_relation",
    "narrative_device",
    "scale_rhythm",
    "container_logic",
}
DIRECTOR_FIELD_LIMITS = {
    "direction_id": 64,
    "mother_structure": 32,
    "layout_variant": 180,
    "reading_path": 80,
    "visual_emphasis": 80,
    "image_text_strategy": 100,
    "difference_key": 64,
    "layout_specific_guardrail": 120,
}

QUICK_CREATIVE_DIRECTION_LIMIT = 180
QUICK_FIRST_IMPRESSION_LIMIT = 96
QUICK_CREATIVE_IMPULSE_LIMIT = 120
FAST_FIRST_IMPRESSION_LIMIT = 96
ART_DIRECTION_CONTRACT_VERSION = 1
CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION = 1
VISUAL_QUALITY_INTENT_LIMIT = 180
RELATIONSHIP_SYNTHESIS_BRIEF_LIMIT = 300
FLEXIBLE_STORY_LIMIT = 320
VISUAL_THESIS_LIMIT = 220
CRAFT_AXIS_LIMIT = 180
ATTENTION_STRATEGY_LIMIT = 160
STYLE_FAMILY_THESIS_LIMIT = 220
STYLE_ADAPTATION_PRINCIPLE_LIMIT = 220
STYLE_CONTINUITY_INVARIANT_LIMIT = 120


def normalize_signature_text(value: str) -> str:
    return "".join(value.lower().split())


def validate_spatial_topology(raw: Any, label: str) -> dict[str, str]:
    """Validate a positive, coarse topology signature without prescribing pixels."""

    if not isinstance(raw, dict):
        raise SystemExit(f"{label}.spatial_topology 必须是对象")
    allowed = {
        "primary_entry",
        "region_logic",
        "evidence_attachment",
        "spatial_topology_intent",
    }
    unexpected = set(raw) - allowed
    if unexpected:
        raise SystemExit(
            f"{label}.spatial_topology 包含未知字段：{', '.join(sorted(unexpected))}"
        )
    primary_entry = raw.get("primary_entry")
    if primary_entry not in SPATIAL_TOPOLOGY_PRIMARY_ENTRIES:
        raise SystemExit(
            f"{label}.spatial_topology.primary_entry 无效：{primary_entry!r}"
        )
    region_logic = raw.get("region_logic")
    if region_logic not in SPATIAL_TOPOLOGY_REGION_LOGICS:
        raise SystemExit(
            f"{label}.spatial_topology.region_logic 无效：{region_logic!r}"
        )
    evidence_attachment = raw.get("evidence_attachment")
    if evidence_attachment not in SPATIAL_TOPOLOGY_EVIDENCE_MODES:
        raise SystemExit(
            f"{label}.spatial_topology.evidence_attachment 无效："
            f"{evidence_attachment!r}"
        )
    intent = raw.get("spatial_topology_intent")
    if not isinstance(intent, str) or not intent.strip():
        raise SystemExit(
            f"{label}.spatial_topology.spatial_topology_intent 必须是非空字符串"
        )
    intent = intent.strip()
    if len(intent) > SPATIAL_TOPOLOGY_INTENT_LIMIT:
        raise SystemExit(
            f"{label}.spatial_topology.spatial_topology_intent 超过 "
            f"{SPATIAL_TOPOLOGY_INTENT_LIMIT} 字"
        )
    return {
        "primary_entry": str(primary_entry),
        "region_logic": str(region_logic),
        "evidence_attachment": str(evidence_attachment),
        "spatial_topology_intent": intent,
    }


def validate_director_direction(
    raw: Any, label: str, seen_ids: set[str], seen_keys: set[str], seen_signatures: set[tuple[str, ...]]
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SystemExit(f"{label} 必须是对象")
    direction = dict(raw)
    for field in DIRECTOR_DIRECTION_FIELDS:
        value = direction.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"{label}.{field} 必须是非空字符串")
        value = value.strip()
        if len(value) > DIRECTOR_FIELD_LIMITS[field]:
            raise SystemExit(
                f"{label}.{field} 过长：{len(value)} > {DIRECTOR_FIELD_LIMITS[field]}；"
                "导演方向必须短而可执行"
            )
        direction[field] = value
    optional_guardrail = direction.get("layout_specific_guardrail")
    if optional_guardrail is not None:
        if not isinstance(optional_guardrail, str) or not optional_guardrail.strip():
            raise SystemExit(f"{label}.layout_specific_guardrail 必须是非空字符串或省略")
        optional_guardrail = optional_guardrail.strip()
        if len(optional_guardrail) > DIRECTOR_FIELD_LIMITS["layout_specific_guardrail"]:
            raise SystemExit(f"{label}.layout_specific_guardrail 过长")
        direction["layout_specific_guardrail"] = optional_guardrail

    axes = direction.get("contrast_axes")
    if not isinstance(axes, list) or not 2 <= len(axes) <= 4:
        raise SystemExit(f"{label}.contrast_axes 必须包含 2–4 个差异轴")
    normalized_axes = []
    for axis in axes:
        if axis not in DIRECTOR_CONTRAST_AXES:
            raise SystemExit(
                f"{label}.contrast_axes 含无效值 {axis!r}；允许值为 {sorted(DIRECTOR_CONTRAST_AXES)}"
            )
        if axis not in normalized_axes:
            normalized_axes.append(axis)
    if len(normalized_axes) < 2:
        raise SystemExit(f"{label}.contrast_axes 去重后必须至少有两个差异轴")
    direction["contrast_axes"] = normalized_axes

    direction_id = normalize_signature_text(direction["direction_id"])
    difference_key = normalize_signature_text(direction["difference_key"])
    signature = tuple(
        normalize_signature_text(direction[field])
        for field in (
            "mother_structure",
            "layout_variant",
            "reading_path",
            "visual_emphasis",
            "image_text_strategy",
        )
    )
    if direction_id in seen_ids:
        raise SystemExit(f"{label}.direction_id 与其他方向重复")
    if difference_key in seen_keys:
        raise SystemExit(f"{label}.difference_key 与其他方向重复")
    if signature in seen_signatures:
        raise SystemExit(f"{label} 与其他方向的可观察版式签名完全重复")
    seen_ids.add(direction_id)
    seen_keys.add(difference_key)
    seen_signatures.add(signature)

    guidance_chars = sum(
        len(direction[field])
        for field in (
            "layout_variant",
            "reading_path",
            "visual_emphasis",
            "image_text_strategy",
        )
    ) + len(direction.get("layout_specific_guardrail", ""))
    if guidance_chars > 400:
        raise SystemExit(f"{label} 的单图导演指令合计 {guidance_chars} 字，超过 400 字预算")
    return direction


def validate_quick_creative_direction(
    raw: Any, label: str, seen_ids: set[str], seen_directions: set[str]
) -> dict[str, Any]:
    """校验 quick8 v4 的软性创意方向，不把建议升级为版式合同。"""

    if not isinstance(raw, dict):
        raise SystemExit(f"{label} 必须是对象")
    direction_id = raw.get("direction_id")
    creative_direction = raw.get("creative_direction")
    if not isinstance(direction_id, str) or not direction_id.strip():
        raise SystemExit(f"{label}.direction_id 必须是非空字符串")
    if not isinstance(creative_direction, str) or not creative_direction.strip():
        raise SystemExit(f"{label}.creative_direction 必须是非空字符串")
    direction_id = direction_id.strip()
    creative_direction = creative_direction.strip()
    if len(direction_id) > DIRECTOR_FIELD_LIMITS["direction_id"]:
        raise SystemExit(f"{label}.direction_id 过长")
    if len(creative_direction) > QUICK_CREATIVE_DIRECTION_LIMIT:
        raise SystemExit(
            f"{label}.creative_direction 过长：{len(creative_direction)} > "
            f"{QUICK_CREATIVE_DIRECTION_LIMIT}；请只保留一个软性方向"
        )
    normalized_id = normalize_signature_text(direction_id)
    normalized_direction = normalize_signature_text(creative_direction)
    if normalized_id in seen_ids:
        raise SystemExit(f"{label}.direction_id 与其他方向重复")
    if normalized_direction in seen_directions:
        raise SystemExit(f"{label}.creative_direction 与其他方向完全重复")
    seen_ids.add(normalized_id)
    seen_directions.add(normalized_direction)
    return {
        "direction_id": direction_id,
        "creative_direction": creative_direction,
        "guidance_level": "soft",
    }


def validate_quick_first_impression(
    raw: Any, label: str, seen_ids: set[str]
) -> dict[str, Any]:
    """校验 quick8 v5 的语义首感；不扫描或禁止任何视觉形式关键词。"""

    if not isinstance(raw, dict):
        raise SystemExit(f"{label} 必须是对象")
    unexpected = set(raw) - {"direction_id", "first_impression"}
    if unexpected:
        raise SystemExit(
            f"{label} v5 只允许 direction_id 与可选 first_impression；"
            f"发现多余字段：{', '.join(sorted(unexpected))}"
        )
    direction_id = raw.get("direction_id")
    if not isinstance(direction_id, str) or not direction_id.strip():
        raise SystemExit(f"{label}.direction_id 必须是非空字符串")
    direction_id = direction_id.strip()
    if len(direction_id) > DIRECTOR_FIELD_LIMITS["direction_id"]:
        raise SystemExit(f"{label}.direction_id 过长")
    normalized_id = normalize_signature_text(direction_id)
    if normalized_id in seen_ids:
        raise SystemExit(f"{label}.direction_id 与其他方向重复")
    seen_ids.add(normalized_id)

    result = {
        "direction_id": direction_id,
        "guidance_level": "open",
    }
    first_impression = raw.get("first_impression")
    if first_impression is None:
        return result
    if not isinstance(first_impression, str) or not first_impression.strip():
        raise SystemExit(f"{label}.first_impression 若提供必须是非空字符串")
    first_impression = first_impression.strip()
    if len(first_impression) > QUICK_FIRST_IMPRESSION_LIMIT:
        raise SystemExit(
            f"{label}.first_impression 过长：{len(first_impression)} > "
            f"{QUICK_FIRST_IMPRESSION_LIMIT}；只描述观众首先应感受到或理解什么"
        )
    result.update(
        {
            "first_impression": first_impression,
            "guidance_level": "semantic_first_impression",
        }
    )
    return result


def validate_fast8_creative_impulse(
    raw: Any,
    label: str,
    seen_ids: set[str],
    seen_impulses: set[str],
) -> dict[str, Any]:
    """校验 Fast8 v7 的短创作启发，不把它升级为固定版式合同。"""

    if not isinstance(raw, dict):
        raise SystemExit(f"{label} 必须是对象")
    unexpected = set(raw) - {
        "direction_id",
        "first_impression",
        "creative_impulse",
    }
    if unexpected:
        raise SystemExit(
            f"{label} v7 只允许 direction_id、可选 first_impression 与 "
            f"creative_impulse；发现多余字段：{', '.join(sorted(unexpected))}"
        )
    direction_id = raw.get("direction_id")
    if not isinstance(direction_id, str) or not direction_id.strip():
        raise SystemExit(f"{label}.direction_id 必须是非空字符串")
    direction_id = direction_id.strip()
    if len(direction_id) > DIRECTOR_FIELD_LIMITS["direction_id"]:
        raise SystemExit(f"{label}.direction_id 过长")
    normalized_id = normalize_signature_text(direction_id)
    if normalized_id in seen_ids:
        raise SystemExit(f"{label}.direction_id 与其他方向重复")
    seen_ids.add(normalized_id)

    creative_impulse = raw.get("creative_impulse")
    if not isinstance(creative_impulse, str) or not creative_impulse.strip():
        raise SystemExit(f"{label}.creative_impulse 必须是非空字符串")
    creative_impulse = creative_impulse.strip()
    if len(creative_impulse) > QUICK_CREATIVE_IMPULSE_LIMIT:
        raise SystemExit(
            f"{label}.creative_impulse 过长：{len(creative_impulse)} > "
            f"{QUICK_CREATIVE_IMPULSE_LIMIT}；请只保留一个开放性启发"
        )
    normalized_impulse = normalize_signature_text(creative_impulse)
    if normalized_impulse in seen_impulses:
        raise SystemExit(f"{label}.creative_impulse 与其他席位完全重复")
    seen_impulses.add(normalized_impulse)

    result = {
        "direction_id": direction_id,
        "creative_impulse": creative_impulse,
        "guidance_level": "open_creative_impulse",
    }
    first_impression = raw.get("first_impression")
    if first_impression is None:
        return result
    if not isinstance(first_impression, str) or not first_impression.strip():
        raise SystemExit(f"{label}.first_impression 若提供必须是非空字符串")
    first_impression = first_impression.strip()
    if len(first_impression) > QUICK_FIRST_IMPRESSION_LIMIT:
        raise SystemExit(
            f"{label}.first_impression 过长：{len(first_impression)} > "
            f"{QUICK_FIRST_IMPRESSION_LIMIT}；只描述观众首先应感受到或理解什么"
        )
    result["first_impression"] = first_impression
    return result


def validate_art_directed_direction(
    raw: Any,
    label: str,
    seen_ids: set[str],
    seen_theses: set[str],
    seen_craft_axes: set[str],
    seen_impressions: set[str],
    *,
    require_attention_contract: bool = False,
    require_topology_contract: bool = False,
) -> dict[str, Any]:
    """校验候选级关系命题与工艺轴；它们是开放导演信息，不是版式合同。"""

    if not isinstance(raw, dict):
        raise SystemExit(f"{label} 必须是对象")
    unexpected = set(raw) - {
        "direction_id",
        "first_impression",
        "visual_thesis",
        "style_family_thesis",
        "craft_axis",
        "visual_activity_mode",
        "attention_strategy",
        "relationship_representation_family",
        "spatial_topology",
        "adaptation_principle",
        "continuity_invariants",
    }
    if unexpected:
        raise SystemExit(
            f"{label} art direction v1 只允许 direction_id、可选 first_impression、"
            "visual_thesis、可选 style_family_thesis、craft_axis、visual_activity_mode、"
            "attention_strategy、relationship_representation_family、可选 spatial_topology、"
            "adaptation_principle 与 continuity_invariants；"
            f"发现多余字段：{', '.join(sorted(unexpected))}"
        )

    direction_id = raw.get("direction_id")
    if not isinstance(direction_id, str) or not direction_id.strip():
        raise SystemExit(f"{label}.direction_id 必须是非空字符串")
    direction_id = direction_id.strip()
    if len(direction_id) > DIRECTOR_FIELD_LIMITS["direction_id"]:
        raise SystemExit(f"{label}.direction_id 过长")
    normalized_id = normalize_signature_text(direction_id)
    if normalized_id in seen_ids:
        raise SystemExit(f"{label}.direction_id 与其他方向重复")
    seen_ids.add(normalized_id)

    visual_thesis = raw.get("visual_thesis")
    if not isinstance(visual_thesis, str) or not visual_thesis.strip():
        raise SystemExit(f"{label}.visual_thesis 必须是非空字符串")
    visual_thesis = visual_thesis.strip()
    if len(visual_thesis) > VISUAL_THESIS_LIMIT:
        raise SystemExit(
            f"{label}.visual_thesis 过长：{len(visual_thesis)} > {VISUAL_THESIS_LIMIT}"
        )
    normalized_thesis = normalize_signature_text(visual_thesis)
    if normalized_thesis in seen_theses:
        raise SystemExit(f"{label}.visual_thesis 与其他方向完全重复")
    seen_theses.add(normalized_thesis)

    craft_axis = raw.get("craft_axis")
    if not isinstance(craft_axis, str) or not craft_axis.strip():
        raise SystemExit(f"{label}.craft_axis 必须是非空字符串")
    craft_axis = craft_axis.strip()
    if len(craft_axis) > CRAFT_AXIS_LIMIT:
        raise SystemExit(
            f"{label}.craft_axis 过长：{len(craft_axis)} > {CRAFT_AXIS_LIMIT}"
        )
    normalized_craft = normalize_signature_text(craft_axis)
    if normalized_craft in seen_craft_axes:
        raise SystemExit(f"{label}.craft_axis 与其他方向完全重复")
    seen_craft_axes.add(normalized_craft)

    result = {
        "direction_id": direction_id,
        "visual_thesis": visual_thesis,
        "craft_axis": craft_axis,
        "art_direction_contract_version": ART_DIRECTION_CONTRACT_VERSION,
        "guidance_level": "relationship_and_craft_art_direction",
    }
    family_thesis = raw.get("style_family_thesis")
    adaptation = raw.get("adaptation_principle")
    continuity = raw.get("continuity_invariants")
    family_fields_present = any(
        value is not None for value in (family_thesis, adaptation, continuity)
    )
    if family_fields_present:
        if not isinstance(family_thesis, str) or not family_thesis.strip():
            raise SystemExit(f"{label}.style_family_thesis 必须是非空字符串")
        family_thesis = family_thesis.strip()
        if len(family_thesis) > STYLE_FAMILY_THESIS_LIMIT:
            raise SystemExit(f"{label}.style_family_thesis 过长")
        if not isinstance(adaptation, str) or not adaptation.strip():
            raise SystemExit(f"{label}.adaptation_principle 必须是非空字符串")
        adaptation = adaptation.strip()
        if len(adaptation) > STYLE_ADAPTATION_PRINCIPLE_LIMIT:
            raise SystemExit(f"{label}.adaptation_principle 过长")
        if not isinstance(continuity, list) or not 2 <= len(continuity) <= 4:
            raise SystemExit(f"{label}.continuity_invariants 必须是 2-4 条字符串")
        normalized_continuity: list[str] = []
        for index, item in enumerate(continuity):
            if not isinstance(item, str) or not item.strip():
                raise SystemExit(
                    f"{label}.continuity_invariants[{index}] 必须是非空字符串"
                )
            item = item.strip()
            if len(item) > STYLE_CONTINUITY_INVARIANT_LIMIT:
                raise SystemExit(
                    f"{label}.continuity_invariants[{index}] 过长"
                )
            normalized_continuity.append(item)
        result.update(
            {
                "style_family_thesis": family_thesis,
                "adaptation_principle": adaptation,
                "continuity_invariants": normalized_continuity,
                "style_family_portfolio_version": (
                    CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
                ),
            }
        )
    activity_mode = raw.get("visual_activity_mode")
    attention_strategy = raw.get("attention_strategy")
    representation_family = raw.get("relationship_representation_family")
    if require_attention_contract or activity_mode is not None or attention_strategy is not None:
        if activity_mode not in VISUAL_ACTIVITY_MODES:
            raise SystemExit(
                f"{label}.visual_activity_mode 必须是 restrained|balanced|expressive"
            )
        if not isinstance(attention_strategy, str) or not attention_strategy.strip():
            raise SystemExit(f"{label}.attention_strategy 必须是非空字符串")
        attention_strategy = attention_strategy.strip()
        if len(attention_strategy) > ATTENTION_STRATEGY_LIMIT:
            raise SystemExit(
                f"{label}.attention_strategy 过长：{len(attention_strategy)} > "
                f"{ATTENTION_STRATEGY_LIMIT}"
            )
        result.update(
            {
                "visual_activity_mode": activity_mode,
                "attention_strategy": attention_strategy,
                "guidance_level": "relationship_craft_and_attention_art_direction",
            }
        )
        if not isinstance(representation_family, str) or not representation_family.strip():
            raise SystemExit(
                f"{label}.relationship_representation_family 必须是非空字符串"
            )
        representation_family = representation_family.strip()
        if len(representation_family) > RELATIONSHIP_REPRESENTATION_FAMILY_LIMIT:
            raise SystemExit(
                f"{label}.relationship_representation_family 超过 "
                f"{RELATIONSHIP_REPRESENTATION_FAMILY_LIMIT} 字"
            )
        result["relationship_representation_family"] = representation_family
    topology = raw.get("spatial_topology")
    if require_topology_contract or topology is not None:
        result["spatial_topology"] = validate_spatial_topology(raw.get("spatial_topology"), label)
    first_impression = raw.get("first_impression")
    if first_impression is None:
        return result
    if not isinstance(first_impression, str) or not first_impression.strip():
        raise SystemExit(f"{label}.first_impression 若提供必须是非空字符串")
    first_impression = first_impression.strip()
    if len(first_impression) > QUICK_FIRST_IMPRESSION_LIMIT:
        raise SystemExit(
            f"{label}.first_impression 过长：{len(first_impression)} > "
            f"{QUICK_FIRST_IMPRESSION_LIMIT}"
        )
    normalized_impression = normalize_signature_text(first_impression)
    if normalized_impression in seen_impressions:
        raise SystemExit(f"{label}.first_impression 与其他方向完全重复")
    seen_impressions.add(normalized_impression)
    result["first_impression"] = first_impression
    return result


def validate_4x3_first_impression(
    raw: Any,
    label: str,
    seen_ids: set[str],
    seen_impressions: set[str],
) -> dict[str, Any]:
    """校验 4x3 v6 的轻量首感；开放席位真正不带单席位提示。"""

    if not isinstance(raw, dict):
        raise SystemExit(f"{label} 必须是对象")
    unexpected = set(raw) - {"direction_id", "first_impression"}
    if unexpected:
        raise SystemExit(
            f"{label} v6 只允许 direction_id 与可选 first_impression；"
            f"发现多余字段：{', '.join(sorted(unexpected))}"
        )
    direction_id = raw.get("direction_id")
    if not isinstance(direction_id, str) or not direction_id.strip():
        raise SystemExit(f"{label}.direction_id 必须是非空字符串")
    direction_id = direction_id.strip()
    if len(direction_id) > DIRECTOR_FIELD_LIMITS["direction_id"]:
        raise SystemExit(f"{label}.direction_id 过长")
    normalized_id = normalize_signature_text(direction_id)
    if normalized_id in seen_ids:
        raise SystemExit(f"{label}.direction_id 与其他方向重复")
    seen_ids.add(normalized_id)

    result = {
        "direction_id": direction_id,
        "guidance_level": "open",
    }
    first_impression = raw.get("first_impression")
    if first_impression is None:
        return result
    if not isinstance(first_impression, str) or not first_impression.strip():
        raise SystemExit(f"{label}.first_impression 若提供必须是非空字符串")
    first_impression = first_impression.strip()
    if len(first_impression) > FAST_FIRST_IMPRESSION_LIMIT:
        raise SystemExit(
            f"{label}.first_impression 过长：{len(first_impression)} > "
            f"{FAST_FIRST_IMPRESSION_LIMIT}；只保留一个高层感知结果"
        )
    normalized_impression = normalize_signature_text(first_impression)
    if normalized_impression in seen_impressions:
        raise SystemExit(f"{label}.first_impression 与其他方向完全重复")
    seen_impressions.add(normalized_impression)
    result.update(
        {
            "first_impression": first_impression,
            "guidance_level": "semantic_first_impression",
        }
    )
    return result


def load_layout_portfolio(
    path: Path,
    state: dict[str, Any],
    content: dict[str, Any],
    expected_styles: tuple[str, ...] = QUICK_STYLES,
) -> dict[str, Any]:
    """读取主 Agent 针对当前页面编排的方向组合，并只做确定性校验。"""

    portfolio = read_json(path)
    contract_version = portfolio.get("layout_portfolio_contract_version")
    if contract_version not in {3, 4, 5, 6, 7}:
        raise SystemExit(
            "layout_portfolio_contract_version 必须为 7（Fast8）、5（经典 Quick8）"
            "或 6（4x3）；"
            "4/3 仅供旧项目恢复"
        )
    if str(portfolio.get("page_id")) != str(content.get("page_id")):
        raise SystemExit("layout_portfolio.page_id 与内容合同 page_id 不一致")
    rationale = portfolio.get("director_rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise SystemExit("layout_portfolio.director_rationale 必须是非空字符串")
    rationale_limit = 240 if contract_version in {4, 5, 6, 7} else 600
    if len(rationale.strip()) > rationale_limit:
        raise SystemExit(
            f"layout_portfolio.director_rationale 超过 {rationale_limit} 字；请保留关键判断"
        )

    if content.get("prompt_contract_version") in {3, 4}:
        guardrails = content.get("prompt_semantic_guardrails", [])
    else:
        guardrails = portfolio.get("shared_prompt_guardrails")
        if not isinstance(guardrails, list) or not 1 <= len(guardrails) <= 3:
            raise SystemExit(
                "旧版 layout_portfolio.shared_prompt_guardrails 必须包含 1–3 条提示级语义护栏"
            )
    if not isinstance(guardrails, list) or len(guardrails) > 3:
        raise SystemExit("提示级语义护栏必须是 0–3 条字符串")
    normalized_guardrails: list[str] = []
    for index, value in enumerate(guardrails):
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"shared_prompt_guardrails[{index}] 必须是非空字符串")
        value = value.strip()
        if len(value) > 120:
            raise SystemExit(f"shared_prompt_guardrails[{index}] 超过 120 字")
        normalized_guardrails.append(value)
    if sum(map(len, normalized_guardrails)) > 300:
        raise SystemExit("shared_prompt_guardrails 合计超过 300 字")

    raw_styles = portfolio.get("styles")
    if not isinstance(raw_styles, dict) or set(raw_styles) != set(expected_styles):
        expected_label = "–".join((expected_styles[0], expected_styles[-1]))
        raise SystemExit(
            f"layout_portfolio.styles 必须且只能包含 {expected_label}"
        )
    if contract_version == 7:
        if expected_styles != QUICK_STYLES:
            raise SystemExit("layout_portfolio v7 仅用于 fast_8x1_diverse 的 A-H 八席位")
        if (state.get("run_mode") or state.get("mode")) != FAST8_MODE:
            raise SystemExit("layout_portfolio v7 只能绑定 run_mode=fast_8x1_diverse")
        if content.get("prompt_contract_version") != 4:
            raise SystemExit("Fast8 v7 必须配套 prompt_contract_version=4 内容合同")
        if "repair_directions" in portfolio:
            raise SystemExit(
                "Fast8 v7 不预设固定备用方向；差异裁判只对实际撞车席位给出开放替代启发"
            )
        art_direction_version = portfolio.get("art_direction_contract_version")
        if art_direction_version not in {None, ART_DIRECTION_CONTRACT_VERSION}:
            raise SystemExit("Fast8 art_direction_contract_version 只允许 1")
        activity_portfolio_version = portfolio.get(
            "visual_activity_portfolio_version"
        )
        if activity_portfolio_version not in {
            None,
            CURRENT_VISUAL_ACTIVITY_PORTFOLIO_VERSION,
        }:
            raise SystemExit("Fast8 visual_activity_portfolio_version 只允许 1")
        if activity_portfolio_version is not None and art_direction_version is None:
            raise SystemExit(
                "Fast8 visual_activity_portfolio_version 必须配套 art direction v1"
            )
        topology_portfolio_version = portfolio.get(
            "spatial_topology_portfolio_version"
        )
        if topology_portfolio_version not in {
            None,
            CURRENT_SPATIAL_TOPOLOGY_PORTFOLIO_VERSION,
        }:
            raise SystemExit("Fast8 spatial_topology_portfolio_version 只允许 1")
        if topology_portfolio_version is not None and activity_portfolio_version is None:
            raise SystemExit(
                "Fast8 spatial_topology_portfolio_version 必须配套 visual activity v1"
            )
        already_prepared = bool(
            state.get("layout_portfolio_path")
            or (state.get("timing") or {}).get("style_jobs_created_at")
        )
        if (
            art_direction_version == ART_DIRECTION_CONTRACT_VERSION
            and activity_portfolio_version is None
            and not already_prepared
        ):
            raise SystemExit(
                "新 Fast8 art direction v1 必须使用 visual_activity_portfolio_version=1；"
                "只有已创建 style_jobs 的旧任务可继续按原提示恢复"
            )
        if (
            art_direction_version == ART_DIRECTION_CONTRACT_VERSION
            and activity_portfolio_version is not None
            and topology_portfolio_version is None
            and not already_prepared
        ):
            raise SystemExit(
                "新 Fast8 必须使用 spatial_topology_portfolio_version=1；"
                "已创建 style_jobs 的旧任务可继续按原方向恢复"
            )
        seen_ids: set[str] = set()
        styles: dict[str, dict[str, Any]] = {}
        guided_count = 0
        if art_direction_version == ART_DIRECTION_CONTRACT_VERSION:
            if not isinstance(content.get("visual_quality_intent"), str) or not content[
                "visual_quality_intent"
            ].strip():
                raise SystemExit(
                    "Fast8 art direction v1 内容合同缺少非空 visual_quality_intent"
                )
            if not page_relationship_thesis(content):
                raise SystemExit(
                    "Fast8 art direction v1 内容合同缺少非空 relationship_thesis"
                )
            if activity_portfolio_version is not None:
                flexible_story = content.get("flexible_story")
                if not isinstance(flexible_story, str) or not flexible_story.strip():
                    raise SystemExit(
                        "Fast8 visual activity v1 内容合同缺少非空 flexible_story"
                    )
            seen_theses: set[str] = set()
            seen_craft_axes: set[str] = set()
            seen_impressions: set[str] = set()
            activity_counts = {mode: 0 for mode in VISUAL_ACTIVITY_MODES}
            representation_families: list[str] = []
            topology_signatures: list[tuple[str, str, str]] = []
            topology_primary_counts: dict[str, int] = {}
            topology_region_logics: set[str] = set()
            integrated_evidence_count = 0
            quiet_band_count = 0
            for style in expected_styles:
                raw_direction = raw_styles[style]
                if isinstance(raw_direction, dict) and "style_slot" in raw_direction:
                    raw_direction = dict(raw_direction)
                    supplied_style = normalize_style(raw_direction.pop("style_slot"))
                    if supplied_style != style:
                        raise SystemExit(
                            f"styles.{style}.style_slot 与外层席位键不一致"
                        )
                direction = validate_art_directed_direction(
                    raw_direction,
                    f"styles.{style}",
                    seen_ids,
                    seen_theses,
                    seen_craft_axes,
                    seen_impressions,
                    require_attention_contract=activity_portfolio_version is not None,
                    require_topology_contract=topology_portfolio_version is not None,
                )
                if direction.get("first_impression"):
                    guided_count += 1
                if direction.get("visual_activity_mode"):
                    activity_counts[direction["visual_activity_mode"]] += 1
                if direction.get("relationship_representation_family"):
                    representation_families.append(
                        normalize_signature_text(
                            direction["relationship_representation_family"]
                        )
                    )
                topology = direction.get("spatial_topology")
                if isinstance(topology, dict):
                    signature = (
                        str(topology["primary_entry"]),
                        str(topology["region_logic"]),
                        str(topology["evidence_attachment"]),
                    )
                    topology_signatures.append(signature)
                    topology_primary_counts[signature[0]] = (
                        topology_primary_counts.get(signature[0], 0) + 1
                    )
                    topology_region_logics.add(signature[1])
                    if signature[2] in {"integrated", "annotated"}:
                        integrated_evidence_count += 1
                    if signature[2] == "quiet_band":
                        quiet_band_count += 1
                direction["layout_contract_version"] = 7
                direction["seed_version"] = 8
                direction["style_slot"] = style
                direction["shared_prompt_guardrails"] = normalized_guardrails
                styles[style] = direction
            if activity_portfolio_version is not None:
                if len(set(representation_families)) < 6:
                    raise SystemExit(
                        "Fast8 八席至少需要 6 个互异的 relationship_representation_family，"
                        "避免只换材质或措辞而共享同一关系骨架"
                    )
                if activity_counts["restrained"] < 3:
                    raise SystemExit(
                        "Fast8 visual activity v1 至少需要 3 个 restrained 席位"
                    )
                if activity_counts["expressive"] > 2:
                    raise SystemExit(
                        "Fast8 visual activity v1 最多允许 2 个 expressive 席位"
                    )
            if topology_portfolio_version is not None:
                if len(topology_signatures) != len(expected_styles):
                    raise SystemExit("Fast8 spatial topology v1 必须覆盖 A-H 全部席位")
                if len(set(topology_signatures)) != len(expected_styles):
                    raise SystemExit(
                        "Fast8 A-H 的 spatial_topology 完整签名必须逐席互异"
                    )
                if len(topology_primary_counts) < 4:
                    raise SystemExit(
                        "Fast8 spatial topology 至少需要 4 种 primary_entry，"
                        "避免只在双栏或横向流程内换皮"
                    )
                overloaded = sorted(
                    key for key, count in topology_primary_counts.items() if count > 2
                )
                if overloaded:
                    raise SystemExit(
                        "Fast8 每种 spatial_topology.primary_entry 最多 2 席："
                        + ", ".join(overloaded)
                    )
                if len(topology_region_logics) < 5:
                    raise SystemExit(
                        "Fast8 spatial topology 至少需要 5 种 region_logic"
                    )
                if quiet_band_count > 2:
                    raise SystemExit(
                        "Fast8 最多允许 2 席使用 quiet_band 作为证据附着方式"
                    )
                if integrated_evidence_count < 3:
                    raise SystemExit(
                        "Fast8 至少 3 席必须把次级证据 integrated|annotated 到主关系中"
                    )
        else:
            # 已创建的 Fast8 v7 继续按旧 creative_impulse 合同恢复。
            seen_impulses: set[str] = set()
            for style in expected_styles:
                direction = validate_fast8_creative_impulse(
                    raw_styles[style],
                    f"styles.{style}",
                    seen_ids,
                    seen_impulses,
                )
                if direction.get("first_impression"):
                    guided_count += 1
                direction["layout_contract_version"] = 7
                direction["seed_version"] = 7
                direction["style_slot"] = style
                direction["shared_prompt_guardrails"] = normalized_guardrails
                styles[style] = direction
            if not 4 <= guided_count <= 6:
                raise SystemExit(
                    "旧 Fast8 v7 必须有 4–6 个席位填写 first_impression；"
                    "所有八席都必须另有互不重复的 creative_impulse"
                )
        return {
            "layout_portfolio_contract_version": 7,
            "art_direction_contract_version": art_direction_version,
            "visual_activity_portfolio_version": activity_portfolio_version,
            "spatial_topology_portfolio_version": topology_portfolio_version,
            "run_id": state.get("run_id"),
            "page_id": content.get("page_id"),
            "director_rationale": rationale.strip(),
            "shared_prompt_guardrails": normalized_guardrails,
            "styles": styles,
            "guided_seat_count": guided_count,
            "open_seat_count": len(expected_styles) - guided_count,
            "candidate_policy": (
                "art_directed_relationship_topology_portfolio"
                if topology_portfolio_version is not None
                else "art_directed_relationship_attention_portfolio"
                if activity_portfolio_version is not None
                else "art_directed_relationship_portfolio"
                if art_direction_version == ART_DIRECTION_CONTRACT_VERSION
                else "fast_diversity_v2"
            ),
            "diversity_policy": {
                "contract_version": CURRENT_FAST8_JUDGE_CONTRACT_VERSION,
                "checkpoints": [8],
                "scheduling_policy": "final_only_after_same_wave",
                "replacement_recheck_policy": "delta_review_evidence_first",
                "max_replacements": 2,
                "max_replacement_rounds": 1,
                "review_scope": FAST8_JUDGE_SCOPES[
                    CURRENT_FAST8_JUDGE_CONTRACT_VERSION
                ],
            },
            "portfolio_rule": (
                "A-H 每席获得本页临时且互异的可见关系命题与图像工艺轴；它们只负责"
                "建立视觉解释和完成度。新 spatial topology 组合只控制主入口、区域逻辑"
                "与证据附着的跨席分离，不规定像素或组件清单。跨席位裁判检查"
                "实质同构与严重的最低工艺退化，但不执行内容、空间或完整工艺三门验收。"
                if art_direction_version == ART_DIRECTION_CONTRACT_VERSION
                else (
                    "A-H 每席获得一个本页临时、开放且互异的创作启发；它只扩张视觉性格、"
                    "空间节奏、图像处理或图文张力，不规定具体版式、媒介或视觉流派。"
                    "跨席位裁判检查实质同构与严重的最低工艺退化，但不执行内容、空间或"
                    "完整工艺三门验收。"
                )
            ),
        }
    if contract_version == 6:
        if expected_styles != FULL_STYLES:
            raise SystemExit("layout_portfolio v6 仅用于 4x3 的 A-D 四席位")
        if content.get("prompt_contract_version") != 4:
            raise SystemExit("4x3 v6 必须配套 prompt_contract_version=4 内容合同")
        if "repair_directions" in portfolio:
            raise SystemExit(
                "4x3 v6 不预设固定备用风格；需要修复时只针对可观察问题定向处理"
            )
        art_direction_version = portfolio.get("art_direction_contract_version")
        if art_direction_version not in {None, ART_DIRECTION_CONTRACT_VERSION}:
            raise SystemExit("4x3 art_direction_contract_version 只允许 1")
        family_portfolio_version = portfolio.get("style_family_portfolio_version")
        if family_portfolio_version not in {
            None,
            CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION,
        }:
            raise SystemExit("4x3 style_family_portfolio_version 只允许 1")
        activity_portfolio_version = portfolio.get(
            "visual_activity_portfolio_version"
        )
        topology_portfolio_version = portfolio.get(
            "spatial_topology_portfolio_version"
        )
        if family_portfolio_version is not None and (
            art_direction_version != ART_DIRECTION_CONTRACT_VERSION
            or activity_portfolio_version != CURRENT_VISUAL_ACTIVITY_PORTFOLIO_VERSION
            or topology_portfolio_version != CURRENT_SPATIAL_TOPOLOGY_PORTFOLIO_VERSION
        ):
            raise SystemExit(
                "4x3 style family v1 必须同时使用 art direction、visual activity "
                "与 spatial topology v1"
            )
        seen_ids: set[str] = set()
        seen_impressions: set[str] = set()
        styles: dict[str, dict[str, Any]] = {}
        guided_count = 0
        if art_direction_version == ART_DIRECTION_CONTRACT_VERSION:
            if not isinstance(content.get("visual_quality_intent"), str) or not content[
                "visual_quality_intent"
            ].strip():
                raise SystemExit(
                    "4x3 art direction v1 内容合同缺少非空 visual_quality_intent"
                )
            if not page_relationship_thesis(content):
                raise SystemExit(
                    "4x3 art direction v1 内容合同缺少非空 relationship_thesis"
                )
            if family_portfolio_version is not None:
                flexible_story = content.get("flexible_story")
                if not isinstance(flexible_story, str) or not flexible_story.strip():
                    raise SystemExit(
                        "4x3 style family v1 内容合同缺少显式 flexible_story"
                    )
            seen_theses: set[str] = set()
            seen_craft_axes: set[str] = set()
            topology_signatures: list[tuple[str, str, str]] = []
            primary_entries: set[str] = set()
            region_logics: set[str] = set()
            activity_counts = {mode: 0 for mode in VISUAL_ACTIVITY_MODES}
            for style in expected_styles:
                direction = validate_art_directed_direction(
                    raw_styles[style],
                    f"styles.{style}",
                    seen_ids,
                    seen_theses,
                    seen_craft_axes,
                    seen_impressions,
                    require_attention_contract=family_portfolio_version is not None,
                    require_topology_contract=family_portfolio_version is not None,
                )
                if family_portfolio_version is not None and direction.get(
                    "style_family_portfolio_version"
                ) != CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION:
                    raise SystemExit(
                        f"styles.{style} 缺少完整可迁移视觉家族字段"
                    )
                if direction.get("first_impression"):
                    guided_count += 1
                if direction.get("visual_activity_mode"):
                    activity_counts[direction["visual_activity_mode"]] += 1
                topology = direction.get("spatial_topology")
                if isinstance(topology, dict):
                    signature = (
                        str(topology["primary_entry"]),
                        str(topology["region_logic"]),
                        str(topology["evidence_attachment"]),
                    )
                    topology_signatures.append(signature)
                    primary_entries.add(signature[0])
                    region_logics.add(signature[1])
                direction["layout_contract_version"] = 6
                direction["seed_version"] = (
                    8 if family_portfolio_version is not None else 7
                )
                direction["style_slot"] = style
                direction["shared_prompt_guardrails"] = normalized_guardrails
                styles[style] = direction
            if family_portfolio_version is not None:
                if len(set(topology_signatures)) != 4:
                    raise SystemExit("4x3 A-D 的 spatial_topology 完整签名必须逐席互异")
                if len(primary_entries) < 3 or len(region_logics) < 3:
                    raise SystemExit(
                        "4x3 style family v1 至少需要 3 种 primary_entry 和 3 种 region_logic"
                    )
                if activity_counts["restrained"] < 1:
                    raise SystemExit("4x3 style family v1 至少需要 1 个 restrained 席位")
                if activity_counts["expressive"] > 1:
                    raise SystemExit("4x3 style family v1 最多允许 1 个 expressive 席位")
        else:
            # 已创建的 4x3 v6 继续按首感/开放席位合同恢复。
            for style in expected_styles:
                direction = validate_4x3_first_impression(
                    raw_styles[style],
                    f"styles.{style}",
                    seen_ids,
                    seen_impressions,
                )
                if direction.get("first_impression"):
                    guided_count += 1
                direction["layout_contract_version"] = 6
                direction["seed_version"] = 6
                direction["style_slot"] = style
                direction["shared_prompt_guardrails"] = normalized_guardrails
                styles[style] = direction
            if not 2 <= guided_count <= 3:
                raise SystemExit(
                    "旧 4x3 v6 必须有 2–3 个席位填写 first_impression，"
                    "其余 1–2 个席位保持完全开放"
                )
        return {
            "layout_portfolio_contract_version": 6,
            "art_direction_contract_version": art_direction_version,
            "style_family_portfolio_version": family_portfolio_version,
            "visual_activity_portfolio_version": activity_portfolio_version,
            "spatial_topology_portfolio_version": topology_portfolio_version,
            "run_id": state.get("run_id"),
            "page_id": content.get("page_id"),
            "director_rationale": rationale.strip(),
            "shared_prompt_guardrails": normalized_guardrails,
            "styles": styles,
            "guided_seat_count": guided_count,
            "open_seat_count": len(expected_styles) - guided_count,
            "candidate_policy": "one_shot_final_quality",
            "portfolio_rule": (
                "A-D 是本次运行的四次独立探索；每席使用本页临时且互异的可见关系命题"
                "与图像工艺轴，不建立跨运行固定风格映射，也不预分配固定版式或组件。"
                if art_direction_version == ART_DIRECTION_CONTRACT_VERSION
                else (
                    "A-D 是本次运行的四次独立探索；2–3 个席位只获得内容层面的第一印象，"
                    "1–2 个席位不设单席位方向。不得建立跨运行固定风格映射，"
                    "也不预分配版式、媒介或视觉流派。"
                )
            ),
        }
    if contract_version == 5:
        if expected_styles != QUICK_STYLES:
            raise SystemExit("layout_portfolio v5 仅用于 quick_8x1；新 4x3 使用 v6")
        if (state.get("run_mode") or state.get("mode")) == FAST8_MODE:
            raise SystemExit("Fast8 新运行不得使用经典 Quick8 v5 布局合同")
        if content.get("prompt_contract_version") != 4:
            raise SystemExit("quick8 v5 必须配套 prompt_contract_version=4 内容合同")
        if "repair_directions" in portfolio:
            raise SystemExit(
                "quick8 v5 不预设 repair_directions；首轮直接展示，用户选中后才定向修复"
            )
        seen_ids: set[str] = set()
        styles: dict[str, dict[str, Any]] = {}
        guided_count = 0
        for style in expected_styles:
            direction = validate_quick_first_impression(
                raw_styles[style], f"styles.{style}", seen_ids
            )
            if direction.get("first_impression"):
                guided_count += 1
            direction["layout_contract_version"] = 5
            direction["seed_version"] = 5
            direction["style_slot"] = style
            direction["shared_prompt_guardrails"] = normalized_guardrails
            styles[style] = direction
        if not 4 <= guided_count <= 6:
            raise SystemExit(
                "quick8 v5 必须有 4–6 个席位填写 first_impression，"
                "其余 2–4 个席位保持自由探索"
            )
        return {
            "layout_portfolio_contract_version": 5,
            "run_id": state.get("run_id"),
            "page_id": content.get("page_id"),
            "director_rationale": rationale.strip(),
            "shared_prompt_guardrails": normalized_guardrails,
            "styles": styles,
            "guided_seat_count": guided_count,
            "open_seat_count": len(expected_styles) - guided_count,
            "candidate_policy": "one_shot_final_quality",
            "portfolio_rule": (
                "4–6 个席位只获得内容层面的第一印象提示，2–4 个席位不设单席位方向；"
                "不预分配版式、媒介或视觉流派，也不建立视觉形式黑名单。"
            ),
        }

    if contract_version == 4:
        if "repair_directions" in portfolio:
            raise SystemExit(
                "quick8 v4 不预设 repair_directions；首轮直接展示，用户选中后才定向修复"
            )
        seen_ids: set[str] = set()
        seen_directions: set[str] = set()
        styles: dict[str, dict[str, Any]] = {}
        for style in expected_styles:
            direction = validate_quick_creative_direction(
                raw_styles[style], f"styles.{style}", seen_ids, seen_directions
            )
            direction["layout_contract_version"] = 4
            direction["seed_version"] = 4
            direction["style_slot"] = style
            direction["shared_prompt_guardrails"] = normalized_guardrails
            styles[style] = direction
        return {
            "layout_portfolio_contract_version": 4,
            "run_id": state.get("run_id"),
            "page_id": content.get("page_id"),
            "director_rationale": rationale.strip(),
            "shared_prompt_guardrails": normalized_guardrails,
            "styles": styles,
            "candidate_policy": "one_shot_final_quality",
            "portfolio_rule": (
                f"{len(expected_styles)} 个方向由主 Agent 根据当前页面给出软性创意建议；"
                "图片模型可自由选择具体版式、媒介与构图，只需让候选呈现可感知的方向差异。"
            ),
        }

    # v3 仅用于恢复已经按强导演合同启动的旧项目。
    if expected_styles != QUICK_STYLES:
        raise SystemExit("layout_portfolio v3 只供旧 quick_8x1 项目恢复")
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    seen_signatures: set[tuple[str, ...]] = set()
    styles: dict[str, dict[str, Any]] = {}
    for style in expected_styles:
        direction = validate_director_direction(
            raw_styles[style], f"styles.{style}", seen_ids, seen_keys, seen_signatures
        )
        direction["layout_contract_version"] = 3
        direction["seed_version"] = 3
        direction["style_slot"] = style
        direction["shared_prompt_guardrails"] = normalized_guardrails
        styles[style] = direction

    raw_repairs = portfolio.get("repair_directions")
    if not isinstance(raw_repairs, list) or len(raw_repairs) < 4:
        raise SystemExit(
            "layout_portfolio.repair_directions 至少准备 4 个本页专属备用方向，"
            "以便撞车时无需重新规划"
        )
    repair_directions = []
    for index, raw in enumerate(raw_repairs):
        direction = validate_director_direction(
            raw,
            f"repair_directions[{index}]",
            seen_ids,
            seen_keys,
            seen_signatures,
        )
        direction["layout_contract_version"] = 3
        direction["seed_version"] = 3
        direction["shared_prompt_guardrails"] = normalized_guardrails
        repair_directions.append(direction)

    return {
        "layout_portfolio_contract_version": 3,
        "run_id": state.get("run_id"),
        "page_id": content.get("page_id"),
        "director_rationale": rationale.strip(),
        "shared_prompt_guardrails": normalized_guardrails,
        "styles": styles,
        "repair_directions": repair_directions,
        "portfolio_rule": (
            "八方向由主 Agent 按当前页面内容编排；允许共享母结构（例如多个双栏），"
            "但每个席位必须拥有不同的可观察版式签名。"
        ),
    }


def layout_portfolio_contract_version(state: dict[str, Any]) -> int | None:
    embedded = state.get("layout_portfolio_contract_version")
    if isinstance(embedded, int):
        return embedded
    path_value = state.get("layout_portfolio_path")
    if not isinstance(path_value, str):
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    return read_json(path).get("layout_portfolio_contract_version")


def active_child_limit_for_state(state: dict[str, Any]) -> int:
    mode = str(state.get("run_mode") or "")
    if mode == FAST8_MODE:
        return FAST8_ACTIVE_CHILD_LIMIT
    if (
        mode in {STRICT_4X3_MODE, FAST_4X3_MODE}
        and layout_portfolio_contract_version(state) == CURRENT_4X3_LAYOUT_VERSION
    ):
        return FOUR_BY_THREE_ACTIVE_CHILD_LIMIT
    return QUICK8_ACTIVE_CHILD_LIMIT


def extract_input_paths(items: list[Any]) -> list[str]:
    paths: list[str] = []
    for item in items:
        path = item if isinstance(item, str) else item.get("path")
        if isinstance(path, str) and path.strip() and path not in paths:
            paths.append(path)
    return paths


def build_input_manifest(paths: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    normalized: list[str] = []
    manifest: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"图片参考或必要资产不存在：{path}")
        stat = path.stat()
        value = str(path)
        normalized.append(value)
        manifest.append(
            {
                "path": value,
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
                "sha256": file_sha256(path),
            }
        )
    return normalized, manifest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_payload_sha256(value: Any) -> str:
    """Return the hash of the exact UTF-8 representation used by atomic_write_json."""

    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    return sha256_text(payload)


def canonical_manifest_sha256(items: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        items,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(payload)


def normalize_source_text(value: str) -> str:
    """Normalize source text without changing its semantic order."""

    value = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace(
        "\r", "\n"
    )
    lines = []
    for line in value.split("\n"):
        normalized = re.sub(r"[\t\f\v ]+", " ", line).strip()
        if normalized:
            lines.append(normalized)
    return "\n".join(lines)


def normalize_page_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple)):
        raw = [str(item).strip() for item in value]
    else:
        raw = []
    page_ids = [item for item in raw if item]
    if not page_ids or len(page_ids) != len(set(page_ids)):
        raise SystemExit("页码必须是非空、不重复的列表")
    return page_ids


def discover_sibling_slide_identity_file(source_path: Path) -> Path | None:
    """Legacy-only lookup for already recorded runs; new flows do not call it.

    Identity for every new run must live in the authoritative outline itself.
    This helper remains only so older state/tests can be audited without
    rewriting their historical contract.
    """

    source_path = source_path.expanduser().resolve()
    candidates = [
        source_path.with_name(
            f"{source_path.stem}_饱和式UID版{source_path.suffix}"
        ),
        source_path.with_name(
            f"{source_path.stem}_slide_identity{source_path.suffix}"
        ),
    ]
    matches: list[Path] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        opted_in = False
        if candidate.suffix.lower() == ".json":
            with contextlib.suppress(Exception):
                value = read_json(candidate)
                opted_in = value.get("slide_identity_required") is True or (
                    isinstance(value.get("slide_identity"), dict)
                    and value["slide_identity"].get("required") is True
                )
        else:
            with contextlib.suppress(UnicodeDecodeError):
                text = candidate.read_text(encoding="utf-8")
                if text.startswith("---\n"):
                    end = text.find("\n---\n", 4)
                    if end >= 0:
                        opted_in = bool(
                            re.search(
                                r"^slide_identity_required:\s*true\s*$",
                                text[4:end],
                                re.MULTILINE | re.IGNORECASE,
                            )
                        )
        if opted_in:
            matches.append(candidate.resolve())
    if len(matches) > 1:
        raise SystemExit(
            "同时发现多个确定性 slide identity 侧车文件，"
            "请用 --slide-identity-file 显式指定："
            + "、".join(str(path) for path in matches)
        )
    return matches[0] if matches else None


def slide_identity_from_file(
    path: Path,
    page_ids: list[str],
    *,
    visited: set[Path] | None = None,
) -> dict[str, Any] | None:
    """Read an opt-in immutable deck/slide UID map from an outline or packet."""

    path = path.expanduser().resolve()
    visited = visited or set()
    if path in visited or not path.is_file():
        return None
    visited.add(path)
    if path.suffix.lower() == ".json":
        with contextlib.suppress(Exception):
            value = read_json(path)
            embedded = value.get("slide_identity")
            if isinstance(embedded, dict) and embedded.get("required") is True:
                deck_uid = embedded.get("deck_uid")
                raw_map = embedded.get("slide_uids")
                if isinstance(deck_uid, str) and isinstance(raw_map, dict):
                    return validate_slide_identity(deck_uid, raw_map, page_ids, path)
            if value.get("slide_identity_required") is True:
                deck_uid = value.get("deck_uid")
                raw_map = value.get("slide_uids")
                if not isinstance(deck_uid, str) or not isinstance(raw_map, dict):
                    raise SystemExit(f"UID 文件的 deck_uid/slide_uids 不完整：{path}")
                return validate_slide_identity(deck_uid, raw_map, page_ids, path)
            authoritative = value.get("authoritative_source")
            authoritative_path = (
                authoritative.get("path") if isinstance(authoritative, dict) else None
            )
            if isinstance(authoritative_path, str) and authoritative_path.strip():
                nested = slide_identity_from_file(
                    Path(authoritative_path), page_ids, visited=visited
                )
                if nested is not None:
                    return nested
    with contextlib.suppress(UnicodeDecodeError):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return None
        end = text.find("\n---\n", 4)
        if end < 0:
            return None
        frontmatter = text[4:end]
        deck_match = re.search(
            r"^deck_uid:\s*(\S.+?)\s*$", frontmatter, re.MULTILINE
        )
        map_matches = re.findall(
            r"^\s{2}(P\d+):\s*(\S.+?)\s*$", frontmatter, re.MULTILINE
        )
        required = bool(
            re.search(
                r"^slide_identity_required:\s*true\s*$",
                frontmatter,
                re.MULTILINE | re.IGNORECASE,
            )
        )
        if not required:
            return None
        if not deck_match or not map_matches:
            raise SystemExit(f"UID 大纲的 deck_uid/slide_uids 不完整：{path}")
        return validate_slide_identity(
            deck_match.group(1).strip(), dict(map_matches), page_ids, path
        )
    return None


def validate_slide_identity(
    deck_uid: str,
    raw_map: dict[Any, Any],
    page_ids: list[str],
    source_path: Path,
) -> dict[str, Any]:
    if not deck_uid.strip():
        raise SystemExit(f"deck_uid 必须是非空的永久描述 UID：{source_path}")
    naming_warnings: list[str] = []
    if re.search(r"\d", deck_uid):
        naming_warnings.append("deck_uid 含数字，建议改用简短内容描述以免与页码混淆")
    normalized: dict[str, str] = {}
    for raw_page_id, raw_slide_uid in raw_map.items():
        if not isinstance(raw_slide_uid, str) or not raw_slide_uid.strip():
            raise SystemExit(f"slide_uid 必须是非空字符串：{source_path}")
        slide_uid = raw_slide_uid.strip()
        if re.search(r"\d", slide_uid):
            naming_warnings.append(
                f"slide_uid 含数字，建议改用简短内容描述以免与页码混淆：{slide_uid}"
            )
        key = canonical_page_id(raw_page_id)
        if key in normalized:
            raise SystemExit(f"UID 大纲存在重复语义页码：{raw_page_id}")
        normalized[key] = slide_uid
    if len(set(normalized.values())) != len(normalized):
        raise SystemExit(f"UID 大纲存在重复 slide_uid：{source_path}")
    projected: dict[str, str] = {}
    for page_id in page_ids:
        slide_uid = normalized.get(canonical_page_id(page_id))
        if slide_uid is None:
            raise SystemExit(f"UID 大纲缺少正式页面 {page_id} 的 slide_uid：{source_path}")
        projected[str(page_id)] = slide_uid
    return {
        "slide_identity_contract_version": 1,
        "required": True,
        "deck_uid": deck_uid.strip(),
        "slide_uids": projected,
        "source_path": str(source_path.resolve()),
        "source_sha256": file_sha256(source_path.resolve()),
        "identity_rule": "immutable_content_identity_not_page_or_title",
        **({"naming_warnings": naming_warnings} if naming_warnings else {}),
    }


def resolve_slide_identity(
    state: dict[str, Any],
    state_path: Path,
    source_path: Path,
    page_ids: list[str],
    slide_identity_path: Path | None = None,
) -> dict[str, Any] | None:
    def configured_identity_file() -> tuple[Path | None, str | None]:
        records: list[Any] = []
        if slide_identity_path is not None:
            records.append(str(slide_identity_path))
        records.append(state.get("slide_identity_file"))
        task_init = validated_task_init_contract(state_path, state, required=False)
        if isinstance(task_init, dict):
            records.append(task_init.get("slide_identity_file"))
        for record in records:
            expected_sha256 = None
            if isinstance(record, dict):
                value = record.get("path")
                expected_sha256 = record.get("sha256")
            else:
                value = record
            if not isinstance(value, str) or not value.strip():
                continue
            path = Path(value).expanduser().resolve()
            if not path.is_file():
                raise SystemExit(f"显式 slide identity 文件不存在：{path}")
            if (
                isinstance(expected_sha256, str)
                and expected_sha256
                and file_sha256(path) != expected_sha256
            ):
                raise SystemExit(f"显式 slide identity 文件在任务初始化后发生变化：{path}")
            return path, expected_sha256
        return None, None

    configured_path, _ = configured_identity_file()
    if configured_path is not None:
        identity = slide_identity_from_file(configured_path, page_ids)
        if identity is None:
            raise SystemExit(
                "显式 slide identity 文件必须声明 slide_identity_required: true，"
                f"并提供完整 deck_uid/slide_uids：{configured_path}"
            )
        return identity

    candidates: list[Path] = []
    state_source = state.get("source")
    if isinstance(state_source, dict) and isinstance(state_source.get("path"), str):
        candidates.append(Path(state_source["path"]))
    candidates.append(source_path)
    identities = []
    for candidate in candidates:
        identity = slide_identity_from_file(candidate, page_ids)
        if identity is not None:
            identities.append(identity)
    if not identities:
        return None
    canonical = {
        (
            item["deck_uid"],
            tuple(sorted(item["slide_uids"].items())),
        )
        for item in identities
    }
    if len(canonical) != 1:
        raise SystemExit("正式状态与权威来源中的 deck_uid/slide_uid 不一致")
    return identities[0]


def attach_slide_identity_to_candidates(
    candidates: list[dict[str, Any]], slide_identity: Any
) -> None:
    """Bind every future handoff candidate to its immutable content identity."""

    if not isinstance(slide_identity, dict):
        return
    deck_uid = slide_identity.get("deck_uid")
    slide_uids = slide_identity.get("slide_uids") or {}
    if not isinstance(deck_uid, str) or not deck_uid or not isinstance(slide_uids, dict):
        raise SystemExit("source snapshot 的 slide_identity 不完整")
    for candidate in candidates:
        matched_uid = next(
            (
                slide_uid
                for identity_page_id, slide_uid in slide_uids.items()
                if page_ids_match(identity_page_id, candidate["page_id"])
            ),
            None,
        )
        if not isinstance(matched_uid, str) or not matched_uid:
            raise SystemExit(f"handoff 候选缺少 slide_uid：{candidate['page_id']}")
        candidate["deck_uid"] = deck_uid
        candidate["slide_uid"] = matched_uid


def page_id_number(value: Any) -> int | None:
    match = re.fullmatch(r"(?i)(?:p(?:age)?|slide)?[-_ ]*0*(\d+)", str(value).strip())
    return int(match.group(1)) if match else None


def page_ids_match(left: Any, right: Any) -> bool:
    left_number = page_id_number(left)
    right_number = page_id_number(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return normalize_signature_text(str(left)) == normalize_signature_text(str(right))


def canonical_page_id(value: Any) -> str:
    number = page_id_number(value)
    if number is not None:
        return f"page:{number}"
    return f"label:{normalize_signature_text(str(value))}"


def page_id_sets_match(left: Any, right: Any) -> bool:
    left_ids = normalize_page_ids(left)
    right_ids = normalize_page_ids(right)
    left_keys = {canonical_page_id(item) for item in left_ids}
    right_keys = {canonical_page_id(item) for item in right_ids}
    return (
        len(left_ids) == len(left_keys)
        and len(right_ids) == len(right_keys)
        and left_keys == right_keys
    )


def heading_page_marker(title: str) -> str | None:
    value = unicodedata.normalize("NFKC", title).strip()
    patterns = (
        r"(?i)^\[?\s*(?:p(?:age)?|slide)\s*[-_:#： ]*0*(\d+)\b",
        r"^\[?\s*第\s*0*(\d+)\s*页",
        r"(?i)^\[?\s*ppt\s*第?\s*0*(\d+)\s*页?",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return str(int(match.group(1)))
    return None


def heading_page_title(title: str) -> str | None:
    """Return the title after a supported page marker, if one is present."""

    value = unicodedata.normalize("NFKC", title).strip()
    patterns = (
        r"(?i)^\[?\s*(?:p(?:age)?|slide)\s*[-_:#： ]*0*\d+\b\s*\]?\s*[|｜:：—–-]*\s*",
        r"^\[?\s*第\s*0*\d+\s*页\s*\]?\s*[|｜:：—–-]*\s*",
        r"(?i)^\[?\s*ppt\s*第?\s*0*\d+\s*页?\s*\]?\s*[|｜:：—–-]*\s*",
    )
    for pattern in patterns:
        if re.search(pattern, value):
            stripped = re.sub(pattern, "", value, count=1).strip()
            return stripped or None
    return None


def markdown_heading_outline(text: str) -> dict[str, Any]:
    """Split heading-style outlines into page sections and deck-level prose."""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    headings: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        title = match.group(2)
        headings.append({
            "index": index,
            "level": len(match.group(1)),
            "title": title,
            "page_id": heading_page_marker(title),
        })

    sections: list[dict[str, Any]] = []
    for position, heading in enumerate(headings):
        if heading["page_id"] is None:
            continue
        end = len(lines)
        for later in headings[position + 1:]:
            if later["page_id"] is not None or later["level"] <= heading["level"]:
                end = later["index"]
                break
        sections.append({
            "page_id": heading["page_id"],
            "title": heading_page_title(heading["title"]),
            "start": heading["index"],
            "end": end,
            "lines": lines[heading["index"]:end],
        })

    page_line_indexes = {
        index
        for section in sections
        for index in range(int(section["start"]), int(section["end"]))
    }
    return {
        "lines": lines,
        "sections": sections,
        "deck_lines": [
            line for index, line in enumerate(lines) if index not in page_line_indexes
        ],
    }


def extract_markdown_deck_context(text: str) -> dict[str, str] | None:
    """Extract prose that applies to the deck rather than one numbered page."""

    outline = markdown_heading_outline(text)
    if outline["sections"]:
        exact_text = "\n".join(outline["deck_lines"]).strip("\n")
    else:
        deck_lines: list[str] = []
        for line in outline["lines"]:
            cells = split_markdown_table_row(line)
            if (
                cells
                and not markdown_table_separator(cells)
                and cells[0]
                and page_id_number(cells[0]) is not None
            ):
                continue
            deck_lines.append(line)
        exact_text = "\n".join(deck_lines).strip("\n")
    normalized = normalize_source_text(exact_text)
    if not normalized:
        return None
    return {
        "normalized_text": normalized,
        "sha256": sha256_text(normalized),
        "exact_text": exact_text,
        "exact_sha256": sha256_text(exact_text),
    }


def split_markdown_table_row(line: str) -> list[str] | None:
    """Return normalized cells for a pipe table row, preserving escaped pipes."""

    stripped = line.strip()
    if not stripped.startswith("|") or "|" not in stripped[1:]:
        return None
    body = stripped[1:-1] if stripped.endswith("|") else stripped[1:]
    cells: list[str] = []
    buffer: list[str] = []
    escaped = False
    for character in body:
        if escaped:
            if character != "|":
                buffer.append("\\")
            buffer.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            cells.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(character)
    if escaped:
        buffer.append("\\")
    cells.append("".join(buffer).strip())
    return cells if len(cells) >= 2 else None


def markdown_table_separator(cells: list[str] | None) -> bool:
    if not cells:
        return False
    return all(
        re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) is not None
        for cell in cells
    )


def markdown_table_header_lines(lines: list[str], row_index: int) -> list[str]:
    """Return the nearest table header and separator for one body row."""

    block_start = row_index
    while block_start > 0 and split_markdown_table_row(lines[block_start - 1]):
        block_start -= 1
    for index in range(block_start, row_index):
        cells = split_markdown_table_row(lines[index])
        if markdown_table_separator(cells) and index > block_start:
            header_cells = split_markdown_table_row(lines[index - 1])
            if header_cells and not markdown_table_separator(header_cells):
                return [lines[index - 1], lines[index]]
    return []


def extract_markdown_pages(
    text: str, page_ids: list[str], *, include_exact: bool = False
) -> list[dict[str, str]]:
    outline = markdown_heading_outline(text)
    lines = outline["lines"]
    sections = outline["sections"]

    extracted: list[dict[str, str]] = []
    for page_id in page_ids:
        matches = [
            section["lines"]
            for section in sections
            if page_ids_match(section["page_id"], page_id)
        ]
        if len(matches) > 1:
            raise SystemExit(
                f"权威文本源中页面 {page_id} 出现多个标题段落；"
                "无法确定哪一段是当前权威内容"
            )
        if matches:
            match = matches[0]
        else:
            table_matches: list[tuple[int, str]] = []
            for index, line in enumerate(lines):
                cells = split_markdown_table_row(line)
                if (
                    cells
                    and not markdown_table_separator(cells)
                    and cells[0]
                    and page_ids_match(cells[0], page_id)
                ):
                    table_matches.append((index, line))
            if not table_matches:
                raise SystemExit(
                    f"权威文本源中找不到页面 {page_id} 的稳定标题段落或表格记录"
                )
            if len(table_matches) > 1:
                raise SystemExit(
                    f"权威文本源中页面 {page_id} 出现多个表格记录；"
                    "无法确定哪一行是当前权威内容"
                )
            row_index, row_line = table_matches[0]
            match = markdown_table_header_lines(lines, row_index) + [row_line]
        exact_text = "\n".join(match).strip("\n")
        normalized = normalize_source_text(exact_text)
        if not normalized:
            raise SystemExit(f"权威文本源中页面 {page_id} 的规范化内容为空")
        record = {
            "page_id": page_id,
            "normalized_text": normalized,
            "sha256": sha256_text(normalized),
        }
        if include_exact:
            record["exact_text"] = exact_text
            record["exact_sha256"] = sha256_text(exact_text)
        extracted.append(record)
    return extracted


def find_json_pages(value: Any, page_id: str) -> list[Any]:
    if isinstance(value, dict):
        for field in ("page_id", "page", "slide_id", "slide", "id"):
            candidate = value.get(field)
            if candidate is not None and page_ids_match(candidate, page_id):
                return [value]
        matches: list[Any] = []
        for key, item in value.items():
            if page_ids_match(key, page_id):
                matches.append(item)
            else:
                matches.extend(find_json_pages(item, page_id))
        return matches
    elif isinstance(value, list):
        matches = []
        for item in value:
            matches.extend(find_json_pages(item, page_id))
        return matches
    return []


def extract_json_pages(
    value: Any, page_ids: list[str], *, include_exact: bool = False
) -> list[dict[str, str]]:
    pages: list[dict[str, str]] = []
    for page_id in page_ids:
        matches = find_json_pages(value, page_id)
        if not matches:
            raise SystemExit(f"权威 JSON 源中找不到页面 {page_id}")
        if len(matches) > 1:
            raise SystemExit(
                f"权威 JSON 源中页面 {page_id} 出现多个记录；"
                "无法确定哪一项是当前权威内容"
            )
        found = matches[0]
        exact_text = json.dumps(found, ensure_ascii=False, sort_keys=True, indent=2)
        normalized = normalize_source_text(
            json.dumps(found, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        record = {
            "page_id": page_id,
            "normalized_text": normalized,
            "sha256": sha256_text(normalized),
        }
        if include_exact:
            record["exact_text"] = exact_text
            record["exact_sha256"] = sha256_text(exact_text)
        pages.append(record)
    return pages


def pptx_slide_members(archive: zipfile.ZipFile) -> list[str]:
    presentation_name = "ppt/presentation.xml"
    rels_name = "ppt/_rels/presentation.xml.rels"
    if presentation_name not in archive.namelist() or rels_name not in archive.namelist():
        return []
    presentation = ElementTree.fromstring(archive.read(presentation_name))
    relationships = ElementTree.fromstring(archive.read(rels_name))
    rel_targets = {
        item.attrib.get("Id"): item.attrib.get("Target")
        for item in relationships
        if item.attrib.get("Id") and item.attrib.get("Target")
    }
    relationship_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    members: list[str] = []
    for slide_id in presentation.findall(
        ".//{http://schemas.openxmlformats.org/presentationml/2006/main}sldId"
    ):
        target = rel_targets.get(slide_id.attrib.get(relationship_namespace))
        if not isinstance(target, str):
            continue
        normalized = posixpath.normpath(posixpath.join("ppt", target.replace("\\", "/")))
        normalized = normalized.lstrip("/")
        members.append(normalized)
    return members


def extract_pptx_pages(
    path: Path, page_ids: list[str], *, include_exact: bool = False
) -> list[dict[str, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            members = pptx_slide_members(archive)
            if not members:
                members = sorted(
                    (
                        name
                        for name in archive.namelist()
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
                    ),
                    key=lambda name: int(re.search(r"(\d+)", Path(name).stem).group(1)),
                )
            pages: list[dict[str, str]] = []
            for page_id in page_ids:
                slide_number = page_id_number(page_id)
                if slide_number is None or slide_number < 1 or slide_number > len(members):
                    raise SystemExit(f"PPTX 中找不到页面 {page_id}")
                member = members[slide_number - 1]
                if member not in archive.namelist():
                    raise SystemExit(f"PPTX 页面成员不存在：{member}")
                root = ElementTree.fromstring(archive.read(member))
                texts = [
                    node.text or ""
                    for node in root.iter(
                        "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
                    )
                ]
                exact_text = "\n".join(texts)
                normalized = normalize_source_text(exact_text)
                if not normalized:
                    raise SystemExit(f"PPTX 页面 {page_id} 没有可规范化的文字")
                record = {
                    "page_id": page_id,
                    "normalized_text": normalized,
                    "sha256": sha256_text(normalized),
                }
                if include_exact:
                    record["exact_text"] = exact_text
                    record["exact_sha256"] = sha256_text(exact_text)
                pages.append(record)
            return pages
    except zipfile.BadZipFile as exc:
        raise SystemExit(f"PPTX 无法解析：{path}") from exc


def extract_explicit_fragment(
    path: Path, page_ids: list[str], *, include_exact: bool = False
) -> list[dict[str, str]]:
    if path.suffix.lower() == ".json":
        return extract_json_pages(
            read_json_value(path), page_ids, include_exact=include_exact
        )
    if len(page_ids) != 1:
        raise SystemExit("纯文本 source fragment 只允许绑定一个页面；多页请使用 JSON")
    exact_text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalize_source_text(exact_text)
    if not normalized:
        raise SystemExit("source fragment 的规范化内容为空")
    record = {
        "page_id": page_ids[0],
        "normalized_text": normalized,
        "sha256": sha256_text(normalized),
    }
    if include_exact:
        record["exact_text"] = exact_text
        record["exact_sha256"] = sha256_text(exact_text)
    return [record]


def extract_relevant_source_content(
    source_path: Path,
    page_ids: list[str],
    fragment_path: Path | None = None,
    *,
    include_exact: bool = False,
) -> dict[str, Any]:
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise SystemExit(f"权威源文件不存在：{source_path}")
    extractor = ""
    if fragment_path is not None:
        fragment_path = fragment_path.resolve()
        if not fragment_path.is_file():
            raise SystemExit(f"source fragment 不存在：{fragment_path}")
        pages = extract_explicit_fragment(
            fragment_path, page_ids, include_exact=include_exact
        )
        extractor = "explicit_fragment"
    elif source_path.suffix.lower() in {".md", ".markdown", ".txt"}:
        markdown_text = source_path.read_text(encoding="utf-8")
        pages = extract_markdown_pages(markdown_text, page_ids, include_exact=include_exact)
        extractor = "page_heading_sections"
    elif source_path.suffix.lower() == ".json":
        pages = extract_json_pages(
            read_json_value(source_path), page_ids, include_exact=include_exact
        )
        extractor = "json_page_records"
    elif source_path.suffix.lower() in {".pptx", ".pptm"}:
        pages = extract_pptx_pages(
            source_path, page_ids, include_exact=include_exact
        )
        extractor = "pptx_slide_text"
    else:
        raise SystemExit(
            "权威源格式无法稳定提取当前页；请提供 Markdown/文本/JSON/PPTX，"
            "或显式传入独立 source fragment 文件"
        )
    aggregate = "\n\n".join(
        f"[[page_id:{item['page_id']}]]\n{item['normalized_text']}" for item in pages
    )
    result = {
        "extractor": extractor,
        "extractor_version": SOURCE_FRAGMENT_EXTRACTOR_VERSION,
        "fragment_source_path": str(fragment_path) if fragment_path else None,
        "pages": pages,
        "normalized_text": aggregate,
        "sha256": sha256_text(aggregate),
    }
    if fragment_path is None and source_path.suffix.lower() in {".md", ".markdown", ".txt"}:
        result["deck_context"] = extract_markdown_deck_context(markdown_text)
    return result


def file_record(path_value: str | Path, label: str) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"{label}不存在：{path}")
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": stat.st_size,
        "sha256": file_sha256(path),
    }


def manifest_hash(records: list[dict[str, Any]]) -> str:
    stable = [
        {"path": str(item.get("path")), "sha256": str(item.get("sha256"))}
        for item in sorted(records, key=lambda value: str(value.get("path")))
    ]
    return canonical_manifest_sha256(stable)


def normalize_asset_records(items: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        if isinstance(item, str):
            raw_path = item
            metadata: dict[str, Any] = {}
        elif isinstance(item, dict):
            raw_path = item.get("path")
            metadata = item
        else:
            raise SystemExit(f"assets[{index}] 必须是路径字符串或对象")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise SystemExit(f"assets[{index}] 缺少 path")
        record = file_record(raw_path, "实际使用资产")
        existing = grouped.get(record["path"])
        if existing is None:
            existing = {
                **record,
                "asset_types": [],
                "roles": [],
                "used_by": [],
            }
            grouped[record["path"]] = existing
        asset_type = metadata.get("asset_type") or "reference_asset"
        role = metadata.get("role") or "reference_asset"
        for field, value in (("asset_types", asset_type), ("roles", role)):
            if isinstance(value, str) and value and value not in existing[field]:
                existing[field].append(value)
        routed = routed_style_values(metadata, "assets", index)
        if routed is not None:
            for style in routed:
                if style not in existing["used_by"]:
                    existing["used_by"].append(style)
    records = list(grouped.values())
    for item in records:
        for field in ("asset_types", "roles", "used_by"):
            item[field] = sorted(item[field])
    return sorted(records, key=lambda item: item["path"])


def source_snapshot_path_for_state(
    state_path: Path, state: dict[str, Any]
) -> Path | None:
    configured = state.get("source_snapshot_path")
    if isinstance(configured, str) and configured:
        return Path(configured).expanduser().resolve()
    state_parent = state_path.resolve().parent
    project_dir = state_parent.parent if state_parent.name == "state" else state_parent
    candidate = project_dir / "state" / "source_snapshot.json"
    return candidate if candidate.is_file() else None


def task_init_contract_path_for_state(state_path: Path, state: dict[str, Any]) -> Path:
    state_parent = state_path.resolve().parent
    project_dir = state_parent.parent if state_parent.name == "state" else state_parent
    return project_dir / "state" / "task_init.json"


def validated_task_init_contract(
    state_path: Path, state: dict[str, Any], *, required: bool
) -> dict[str, Any] | None:
    marker_path = task_init_contract_path_for_state(state_path, state)
    if not marker_path.is_file():
        if required:
            raise SystemExit(
                "旧任务或未标记任务不得补写 source snapshot；"
                "请由 init_task_dir.py 创建新运行目录"
            )
        return None
    marker = read_json(marker_path)
    if marker.get("task_init_contract_version") != TASK_INIT_CONTRACT_VERSION:
        raise SystemExit(f"不支持的 task init contract version：{marker_path}")
    expected_project_dir = str(project_dir_for_state(state_path, state))
    if marker.get("project_dir") != expected_project_dir:
        raise SystemExit(f"task_init.json 的 project_dir 与正式状态不一致：{marker_path}")
    if marker.get("source_snapshot_required") is not True:
        raise SystemExit(f"task_init.json 必须声明 source_snapshot_required=true：{marker_path}")
    return marker


def source_snapshot_required_for_state(
    state_path: Path, state: dict[str, Any]
) -> bool:
    if (
        state.get("source_guard_contract_version") == SOURCE_SNAPSHOT_CONTRACT_VERSION
        or state.get("source_snapshot_path")
        or state.get("source_snapshot_sha256")
    ):
        validated_task_init_contract(state_path, state, required=False)
        return True
    return validated_task_init_contract(state_path, state, required=False) is not None


def source_guard_enabled(state_path: Path, state: dict[str, Any]) -> bool:
    return (
        source_snapshot_required_for_state(state_path, state)
        or source_snapshot_path_for_state(state_path, state) is not None
    )


def resolved_run_mode(state: dict[str, Any]) -> str:
    mode = state.get("run_mode") or state.get("mode")
    if not mode and state.get("phase") == "selected_style_expansion":
        mode = "selected_style_expansion"
    if not isinstance(mode, str) or not mode.strip():
        raise SystemExit("正式状态缺少非空 run_mode")
    return mode.strip()


def required_snapshot_page_scope(
    state: dict[str, Any], run_mode: str
) -> list[str] | None:
    """Return the complete page scope a fresh run is allowed to seal."""

    if run_mode in {QUICK_8X1_MODE, FAST8_MODE}:
        anchor = state.get("anchor_page_id")
        if anchor is None:
            raise SystemExit(f"{run_mode} 状态缺少 anchor_page_id")
        return [str(anchor)]
    if run_mode in {FAST_4X3_MODE, STRICT_4X3_MODE}:
        anchor = state.get("anchor_page_id")
        followers = state.get("follower_page_ids")
        if anchor is None or not isinstance(followers, list) or len(followers) != 2:
            raise SystemExit("4×3 source snapshot 必须绑定一个锚点和两个 follower")
        return [str(anchor), *(str(item) for item in followers)]
    if run_mode == "selected_style_expansion":
        page_order = state.get("page_order")
        if not isinstance(page_order, list) or not page_order:
            raise SystemExit("选定风格扩页 source snapshot 缺少完整 page_order")
        return [str(item) for item in page_order]
    return None


def selected_expansion_snapshot_job_union(
    project_dir: Path,
    state: dict[str, Any],
    page_ids: list[str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, list[str]],
]:
    """Return the exact contract/asset union of sealed expansion page jobs."""

    selected_style = normalize_style(state.get("selected_style"))
    if selected_style is None:
        raise SystemExit("选定风格扩页 source snapshot 缺少 selected_style")
    jobs_root = (project_dir / "page_jobs").resolve()
    if not jobs_root.is_dir():
        raise SystemExit("扩页 source snapshot 前必须先定稿全部 page_jobs")
    expected_keys = {canonical_page_id(item) for item in page_ids}
    jobs_by_page: dict[str, tuple[Path, dict[str, Any]]] = {}
    for job_path in sorted(jobs_root.glob("page_*.json"), key=str):
        job = read_json(job_path)
        job_page_id = job.get("page_id")
        if job_page_id is None:
            raise SystemExit(f"扩页正式页面任务缺少 page_id：{job_path}")
        page_key = canonical_page_id(str(job_page_id))
        if page_key not in expected_keys:
            raise SystemExit(f"扩页 page_jobs 包含页面范围外任务：{job_path}")
        if page_key in jobs_by_page:
            raise SystemExit(
                f"扩页 page_jobs 对同一语义页存在多个正式任务：{job_path}"
            )
        jobs_by_page[page_key] = (job_path.resolve(), job)
    missing = sorted(expected_keys - set(jobs_by_page))
    if missing:
        raise SystemExit(
            "扩页 source snapshot 前缺少正式页面任务：" + ", ".join(missing)
        )

    contracts_by_path: dict[str, dict[str, Any]] = {}
    assets_by_path: dict[str, dict[str, Any]] = {}
    asset_pages: dict[str, set[str]] = {}
    hash_cache: dict[str, str] = {}
    for page_id in page_ids:
        page_key = canonical_page_id(page_id)
        job_path, job = jobs_by_page[page_key]
        if job.get("action") != "generate_page":
            raise SystemExit(f"扩页初始 page_job 必须声明 action=generate_page：{job_path}")
        if normalize_style(job.get("style_slot")) != selected_style:
            raise SystemExit(f"扩页初始 page_job 的 style_slot 不一致：{job_path}")
        if not page_ids_match(job.get("page_id"), page_id):
            raise SystemExit(f"扩页初始 page_job 的 page_id 不一致：{job_path}")
        contract, job_assets = validate_generation_job_inputs(
            job_path,
            internal_sources=set(),
            hash_cache=hash_cache,
            require_prompt_fingerprint=False,
        )
        contract_value = read_json(Path(str(contract["path"])))
        if not page_ids_match(contract_value.get("page_id"), page_id):
            raise SystemExit(f"扩页 page_job 绑定了其他页面的内容合同：{job_path}")
        expected_output = origin_image_target(
            project_dir, selected_style, str(page_id)
        ).resolve()
        output_raw = job.get("output_target")
        output_path = (
            Path(output_raw).expanduser()
            if isinstance(output_raw, str)
            else None
        )
        if (
            output_path is None
            or not output_path.is_absolute()
            or output_path.resolve() != expected_output
        ):
            raise SystemExit(f"扩页 page_job 的 output_target 不规范：{job_path}")
        contracts_by_path[contract["path"]] = contract
        for item in job_assets:
            assets_by_path[item["path"]] = item
            asset_pages.setdefault(item["path"], set()).add(str(page_id))
    # New selected-style runs may deliberately use text_family on every page.
    # The selected raster remains the frozen source of the textual family even
    # when it is not an ImageGen attachment, so bind it once at run scope.
    for raw_anchor in state.get("style_anchors") or []:
        if not isinstance(raw_anchor, dict):
            raise SystemExit("扩页 style_anchors 只能包含对象")
        raw_path = raw_anchor.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise SystemExit("扩页 style_anchor 缺少路径")
        anchor_path = Path(raw_path).expanduser().resolve()
        if not anchor_path.is_file():
            raise SystemExit(f"扩页 style_anchor 不存在：{anchor_path}")
        declared_sha = str(raw_anchor.get("sha256") or "").lower()
        actual_sha = cached_file_sha256(anchor_path, hash_cache)
        if declared_sha and declared_sha != actual_sha:
            raise SystemExit(f"扩页 style_anchor SHA-256 已变化：{anchor_path}")
        path_value = str(anchor_path)
        existing = assets_by_path.get(path_value)
        if existing is None:
            assets_by_path[path_value] = {
                "path": path_value,
                "sha256": actual_sha,
                "size_bytes": anchor_path.stat().st_size,
                "asset_type": "style_family_source",
                "role": "style_anchor",
            }
        else:
            existing["asset_type"] = existing.get("asset_type") or "style_anchor"
            existing["role"] = existing.get("role") or "style_anchor"
        asset_pages.setdefault(path_value, set()).update(str(item) for item in page_ids)
    return (
        list(contracts_by_path.values()),
        list(assets_by_path.values()),
        {path: sorted(values) for path, values in asset_pages.items()},
    )


def preflight_supporting_source_paths(
    project_dir: Path,
    *,
    authoritative_source: Path,
    content_contract_paths: list[Path],
    asset_items: list[Any],
) -> list[Path]:
    """Derive planning/evidence dependencies without treating them as ImageGen assets."""

    manifest_path = project_dir.resolve() / "state" / "preflight_manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = read_json(manifest_path)
    required_files = manifest.get("required_files") or []
    if not isinstance(required_files, list):
        raise SystemExit(f"preflight required_files 必须是数组：{manifest_path}")
    excluded = {
        str(authoritative_source.expanduser().resolve()),
        *(str(path.expanduser().resolve()) for path in content_contract_paths),
    }
    for item in asset_items:
        raw = item.get("path") if isinstance(item, dict) else item
        if isinstance(raw, str) and raw.strip():
            excluded.add(str(Path(raw).expanduser().resolve()))
    paths: set[Path] = set()
    for index, raw in enumerate(required_files):
        recorded_exists: bool | None = None
        recorded_sha256: str | None = None
        if isinstance(raw, dict):
            path_value = raw.get("path")
            recorded_exists = raw.get("exists")
            recorded_sha256 = raw.get("sha256")
        else:
            path_value = raw
        if not isinstance(path_value, str) or not path_value.strip():
            raise SystemExit(
                f"preflight required_files[{index}] 必须是非空绝对路径：{manifest_path}"
            )
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            raise SystemExit(
                f"preflight required_files[{index}] 必须是绝对路径：{path_value}"
            )
        path = path.resolve()
        if isinstance(raw, dict):
            if recorded_exists is not True or not path.is_file():
                raise SystemExit(
                    f"preflight required_files[{index}] 已解析文件不存在：{path}"
                )
            if (
                not isinstance(recorded_sha256, str)
                or not recorded_sha256
                or file_sha256(path) != recorded_sha256
            ):
                raise SystemExit(
                    f"preflight required_files[{index}] SHA-256 与预检结果不一致：{path}"
                )
        if str(path) not in excluded:
            paths.add(path)
    return sorted(paths, key=str)


def create_source_snapshot(
    *,
    project_dir: Path,
    state_path: Path,
    source_path: Path,
    page_ids: list[str],
    content_contract_paths: list[Path],
    asset_items: list[Any],
    supporting_source_paths: list[Path] | None = None,
    fragment_path: Path | None = None,
    slide_identity_path: Path | None = None,
    fragment_authority: str = "extractor_aid",
    timestamp: str | None = None,
) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    state_path = state_path.resolve()
    state = read_json(state_path)
    if project_dir_for_state(state_path, state) != project_dir:
        raise SystemExit("--project-dir 与正式状态所属任务目录不一致")
    validated_task_init_contract(state_path, state, required=True)
    snapshot_path = project_dir / "state" / "source_snapshot.json"
    existing_snapshot = read_json(snapshot_path) if snapshot_path.exists() else None
    existing_is_bound = bool(
        state.get("source_snapshot_path") or state.get("source_snapshot_sha256")
    )
    if existing_snapshot is not None and existing_is_bound:
        raise SystemExit(
            f"source_snapshot.json 已封存，拒绝覆盖：{snapshot_path}；请改用漂移检测"
        )
    generation_history_events = {
        "style_jobs_created",
        "task_package_completed",
        "initial_anchor_dispatch",
        "dispatch_wave",
        "agent_action_started",
        "tool_started",
        "tool_finished",
        "file_validated",
        "page_completed",
    }
    if any(
        isinstance(event, dict) and event.get("name") in generation_history_events
        for event in (state.get("events") or [])
    ) or (state.get("timing") or {}).get("style_jobs_created_at"):
        raise SystemExit(
            "旧任务或已开始生成的任务不得补写 source snapshot；"
            "当前哈希不能冒充历史基线，请建立新运行目录"
        )
    page_groups: list[dict[str, Any]] = []
    for style_state in (state.get("styles") or {}).values():
        if not isinstance(style_state, dict):
            continue
        pages = style_state.get("pages") or {}
        if isinstance(pages, dict):
            page_groups.append(pages)
    if isinstance(state.get("pages"), dict):
        page_groups.append(state["pages"])
    for pages in page_groups:
        for record in pages.values():
            if not isinstance(record, dict):
                continue
            if (
                record.get("selected_source")
                or record.get("tool_call_id")
                or int(record.get("attempt_count") or 0) > 0
            ):
                raise SystemExit(
                    "已有候选或生成尝试的任务不得补写 source snapshot；"
                    "请建立新运行目录"
                )
    page_ids = normalize_page_ids(page_ids)
    if len({canonical_page_id(item) for item in page_ids}) != len(page_ids):
        raise SystemExit("source snapshot 页码包含语义重复项")
    run_mode = resolved_run_mode(state)
    slide_identity = resolve_slide_identity(
        state,
        state_path,
        source_path,
        page_ids,
        slide_identity_path=slide_identity_path,
    )
    required_scope = required_snapshot_page_scope(state, run_mode)
    if required_scope is not None and not page_id_sets_match(page_ids, required_scope):
        raise SystemExit(
            "source snapshot 页面范围必须与运行模式的完整正式范围一致："
            f"expected={required_scope} actual={page_ids}"
        )
    source = file_record(source_path, "权威源文件")
    source_file = Path(source["path"])
    source_stat = source_file.stat()
    source["modified_ns"] = source_stat.st_mtime_ns
    page_content = extract_relevant_source_content(
        source_file,
        page_ids,
        fragment_path.resolve() if fragment_path else None,
    )
    if fragment_authority not in {"extractor_aid", "authoritative_page_fragment"}:
        raise SystemExit(
            "source fragment authority 只允许 extractor_aid|authoritative_page_fragment"
        )
    if fragment_path is None and fragment_authority == "authoritative_page_fragment":
        raise SystemExit("authoritative_page_fragment 必须同时提供 source fragment 文件")
    page_content["authority_mode"] = (
        fragment_authority if fragment_path is not None else "source_extract"
    )
    contracts = [
        file_record(path, "内容合同")
        for path in sorted(
            {Path(item).expanduser().resolve() for item in content_contract_paths},
            key=str,
        )
    ]
    if not contracts:
        raise SystemExit("source snapshot 至少需要一个内容合同")
    contract_page_ids: list[str] = []
    for item in contracts:
        contract_value = read_json(Path(str(item["path"])))
        if (
            contract_value.get("content_contract_version") == 2
            and contract_value.get("prompt_contract_version") == 4
        ):
            validate_dispatchable_content_contract(
                contract_value,
                f"source snapshot 内容合同 {item['path']}",
                soft_spatial_preference=run_mode == FAST_4X3_MODE,
            )
        contract_page_id = contract_value.get("page_id")
        if contract_page_id is None:
            raise SystemExit(f"内容合同缺少 page_id：{item['path']}")
        contract_page_ids.append(str(contract_page_id))
    if (
        len({canonical_page_id(item) for item in contract_page_ids})
        != len(contract_page_ids)
        or not page_id_sets_match(contract_page_ids, page_ids)
    ):
        raise SystemExit(
            "source snapshot 必须为正式页面范围逐页绑定且只绑定一个内容合同："
            f"pages={page_ids} contracts={contract_page_ids}"
        )
    assets = normalize_asset_records(asset_items)
    excluded_supporting_paths = {
        str(source_file.resolve()),
        *(str(Path(item["path"]).expanduser().resolve()) for item in assets),
        *(str(Path(item["path"]).expanduser().resolve()) for item in contracts),
    }
    supporting_sources: list[dict[str, Any]] = []
    for path in sorted(
        {
            Path(item).expanduser().resolve()
            for item in (supporting_source_paths or [])
        },
        key=str,
    ):
        if str(path) in excluded_supporting_paths:
            continue
        supporting_sources.append(file_record(path, "内容规划来源"))
    if run_mode == "selected_style_expansion":
        job_contracts, job_assets, job_asset_pages = selected_expansion_snapshot_job_union(
            project_dir, state, page_ids
        )
        declared_contract_paths = operation_path_set(
            contracts, "source_snapshot.content_contracts"
        )
        job_contract_paths = operation_path_set(
            job_contracts, "selected_expansion.page_jobs.content_contracts"
        )
        if declared_contract_paths != job_contract_paths:
            raise SystemExit(
                "扩页 source snapshot 的内容合同必须精确等于全部 page_jobs 合同并集"
            )
        declared_asset_paths = operation_path_set(
            assets, "source_snapshot.assets"
        )
        job_asset_paths = operation_path_set(
            job_assets, "selected_expansion.page_jobs.assets"
        )
        if declared_asset_paths != job_asset_paths:
            raise SystemExit(
                "扩页 source snapshot 的资产必须精确等于全部 page_jobs 外部输入并集"
            )
        anchorless_text_family = (
            state.get("visual_family_source") == "director_defined_text_family"
            and not (state.get("style_anchors") or [])
        )
        if (
            not anchorless_text_family
            and not any("style_anchor" in (item.get("roles") or []) for item in assets)
        ):
            raise SystemExit(
                "扩页 source snapshot 必须把实际使用的选中锚点标记为 style_anchor"
            )
        for item in assets:
            item["used_by_pages"] = job_asset_pages[item["path"]]
            if selected_style := normalize_style(state.get("selected_style")):
                item["used_by"] = sorted(
                    {*(item.get("used_by") or []), selected_style}
                )
    snapshot = {
        "source_snapshot_contract_version": SOURCE_SNAPSHOT_CONTRACT_VERSION,
        "run_id": state.get("run_id"),
        "project_dir": str(project_dir),
        "run_mode": run_mode,
        "page_ids": page_ids,
        "authoritative_source": source,
        "page_content": page_content,
        "content_contracts": contracts,
        "content_contract_sha256": manifest_hash(contracts),
        "supporting_sources": supporting_sources,
        "supporting_sources_sha256": manifest_hash(supporting_sources),
        "assets": assets,
        "assets_sha256": manifest_hash(assets),
        "snapshot_at": timestamp or now_iso(),
    }
    if slide_identity is not None:
        snapshot["slide_identity"] = slide_identity
    state["project_dir"] = str(project_dir)
    state["run_mode"] = run_mode
    state["source_guard_contract_version"] = SOURCE_SNAPSHOT_CONTRACT_VERSION
    state["source_snapshot_path"] = str(snapshot_path)
    if existing_snapshot is not None:
        validated_task_init_contract(state_path, state, required=True)
        existing_comparable = dict(existing_snapshot)
        requested_comparable = dict(snapshot)
        existing_comparable.pop("snapshot_at", None)
        requested_comparable.pop("snapshot_at", None)
        if existing_comparable != requested_comparable:
            raise SystemExit(
                "发现未绑定的 source_snapshot.json，但本次输入与孤儿快照不一致；"
                "拒绝覆盖，请建立新运行目录"
            )
        snapshot = existing_snapshot
        snapshot_sha256 = file_sha256(snapshot_path)
    else:
        atomic_write_json(snapshot_path, snapshot)
        snapshot_sha256 = file_sha256(snapshot_path)
    state["source_snapshot_sha256"] = snapshot_sha256
    state["source_integrity"] = {
        "status": "snapshot_sealed",
        "snapshot_path": str(snapshot_path),
        "checked_at": snapshot["snapshot_at"],
    }
    try:
        atomic_write_json(state_path, state)
    except Exception:
        if existing_snapshot is None:
            try:
                snapshot_path.unlink()
            except FileNotFoundError:
                pass
        raise
    return snapshot


def legacy_source_drift_result(
    state_path: Path, state: dict[str, Any], action: str, *, missing_required: bool
) -> dict[str, Any]:
    status = "source_snapshot_missing" if missing_required else "legacy_snapshot_missing"
    return {
        "source_drift_contract_version": 1,
        "checked_at": now_iso(),
        "checked_action": action,
        "state_path": str(state_path.resolve()),
        "status": status,
        "can_continue": False,
        "warning": not missing_required,
        "requires_user_confirmation": True,
        "whole_source_changed": None,
        "relevant_page_content_changed": None,
        "content_contract_changed": None,
        "used_asset_changed": None,
        "source_snapshot_changed": None,
        "changes": [],
        "warnings": [
            (
                "该新版本状态声明了 source guard，但 source_snapshot.json 缺失；"
                "禁止降级为 legacy 继续。"
                if missing_required
                else "旧任务没有 source_snapshot.json；无法证明旧候选仍匹配当前来源，且不得补写伪历史哈希。"
            )
        ],
        "next_allowed_actions": [
            "inspect_existing_state_read_only",
            "validate_existing_artifact_metadata",
            "request_user_confirmation_or_create_new_run_directory",
        ],
    }


def legacy_source_confirmation_path(
    state_path: Path, state: dict[str, Any]
) -> Path:
    return project_dir_for_state(state_path, state) / "state" / "legacy_source_confirmation.json"


def legacy_source_identity(
    state_path: Path, state: dict[str, Any]
) -> dict[str, Any]:
    run_mode = resolved_run_mode(state)
    page_ids = required_snapshot_page_scope(state, run_mode)
    return {
        "state_path": str(state_path.resolve()),
        "run_id": state.get("run_id"),
        "project_dir": str(project_dir_for_state(state_path, state)),
        "run_mode": run_mode,
        "page_ids": normalize_page_ids(page_ids) if page_ids is not None else [],
        "selected_style": normalize_style(state.get("selected_style")),
    }


def legacy_source_confirmation_allows(
    state_path: Path, state: dict[str, Any], action: str
) -> bool:
    confirmation_path = legacy_source_confirmation_path(state_path, state)
    if not confirmation_path.is_file():
        return False
    confirmation = read_json(confirmation_path)
    if (
        confirmation.get("legacy_source_confirmation_contract_version")
        != LEGACY_SOURCE_CONFIRMATION_CONTRACT_VERSION
        or confirmation.get("confirmed") is not True
        or confirmation.get("risk_code") != "legacy_source_snapshot_missing"
        or not isinstance(confirmation.get("confirmed_at"), str)
        or not confirmation.get("confirmed_at")
    ):
        return False
    identity = legacy_source_identity(state_path, state)
    if confirmation.get("run_identity") != identity:
        return False
    identity_sha = sha256_text(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    if confirmation.get("run_identity_sha256") != identity_sha:
        return False
    confirmation_payload = dict(confirmation)
    confirmation_id = confirmation_payload.pop("confirmation_id", None)
    expected_confirmation_id = sha256_text(
        json.dumps(
            confirmation_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )[:24]
    if confirmation_id != expected_confirmation_id:
        return False
    actions = confirmation.get("allowed_actions")
    return isinstance(actions, list) and action in actions


def confirmed_legacy_source_result(
    result: dict[str, Any], action: str
) -> dict[str, Any]:
    confirmed = dict(result)
    confirmed.update(
        {
            "status": "legacy_snapshot_missing",
            "can_continue": False,
            "warning": True,
            "requires_user_confirmation": False,
            "source_integrity_verified": False,
            "operation_authorized": True,
            "checked_action": action,
            "warnings": [
                *(result.get("warnings") or []),
                "用户已明确接受旧任务缺少历史来源快照的风险；"
                "本次兼容继续不构成来源未漂移的证明。",
            ],
            "next_allowed_actions": ["continue_confirmed_legacy_action"],
        }
    )
    return confirmed


def evaluate_source_drift(
    state_path: Path,
    state: dict[str, Any] | None = None,
    *,
    action: str = "resume",
    timestamp: str | None = None,
) -> dict[str, Any]:
    state_path = state_path.resolve()
    state = state if state is not None else read_json(state_path)
    snapshot_path = source_snapshot_path_for_state(state_path, state)
    if snapshot_path is None or not snapshot_path.is_file():
        return legacy_source_drift_result(
            state_path,
            state,
            action,
            missing_required=source_snapshot_required_for_state(state_path, state),
        )
    fast8_initial_dispatch_locked = bool(
        resolved_run_mode(state) == FAST8_MODE
        and any(
            isinstance(event, dict) and event.get("name") == "dispatch_wave"
            for event in (state.get("events") or [])
        )
    )
    if fast8_initial_dispatch_locked:
        # New Fast8 validates the frozen packet, contract and actual assets once
        # at the first formal dispatch. After that point the generation jobs are
        # the run's immutable inputs. Re-reading or re-hashing source material at
        # Judge/finalize/recovery boundaries creates failure modes without making
        # an already-generated image more correct.
        return {
            "source_drift_contract_version": 1,
            "checked_at": timestamp or now_iso(),
            "checked_action": action,
            "state_path": str(state_path),
            "status": "fast8_inputs_locked_at_initial_dispatch",
            "can_continue": True,
            "warning": False,
            "requires_user_confirmation": False,
            "source_integrity_verified": True,
            "operation_authorized": True,
            "whole_source_changed": False,
            "relevant_page_content_changed": False,
            "content_contract_changed": False,
            "used_asset_changed": False,
            "source_snapshot_changed": False,
            "changes": [],
            "warnings": [],
            "checks_skipped": [
                "live_outline",
                "post_dispatch_packet_rehash",
                "post_dispatch_contract_rehash",
                "post_dispatch_asset_rehash",
            ],
            "next_allowed_actions": ["continue_with_locked_generation_jobs"],
        }
    snapshot, snapshot_file_sha = read_json_with_sha256(snapshot_path)
    require_keys(
        snapshot,
        [
            "source_snapshot_contract_version",
            "project_dir",
            "page_ids",
            "authoritative_source",
            "page_content",
            "content_contracts",
            "content_contract_sha256",
            "assets",
            "assets_sha256",
            "snapshot_at",
        ],
        str(snapshot_path),
    )
    if snapshot.get("source_snapshot_contract_version") != SOURCE_SNAPSHOT_CONTRACT_VERSION:
        raise SystemExit("不支持的 source snapshot contract version")

    changes: list[dict[str, Any]] = []
    expected_snapshot_sha = state.get("source_snapshot_sha256")
    if not isinstance(expected_snapshot_sha, str) or not expected_snapshot_sha:
        changes.append(
            {
                "component": "source_snapshot",
                "reason": "state_binding_missing",
                "path": str(snapshot_path),
                "actual_sha256": snapshot_file_sha,
            }
        )
    expected_project_dir = str(project_dir_for_state(state_path, state))
    if snapshot.get("project_dir") != expected_project_dir:
        changes.append(
            {
                "component": "source_snapshot",
                "reason": "project_dir_mismatch",
                "path": str(snapshot_path),
                "expected_project_dir": expected_project_dir,
                "actual_project_dir": snapshot.get("project_dir"),
            }
        )
    if snapshot.get("run_id") != state.get("run_id"):
        changes.append(
            {
                "component": "source_snapshot",
                "reason": "run_id_mismatch",
                "path": str(snapshot_path),
                "expected_run_id": state.get("run_id"),
                "actual_run_id": snapshot.get("run_id"),
            }
        )
    expected_run_mode = resolved_run_mode(state)
    if snapshot.get("run_mode") != expected_run_mode:
        changes.append(
            {
                "component": "source_snapshot",
                "reason": "run_mode_mismatch",
                "path": str(snapshot_path),
                "expected_run_mode": expected_run_mode,
                "actual_run_mode": snapshot.get("run_mode"),
            }
        )
    try:
        current_scope = required_snapshot_page_scope(state, expected_run_mode)
        normalized_current_scope = (
            normalize_page_ids(current_scope) if current_scope is not None else None
        )
        snapshot_scope = normalize_page_ids(snapshot.get("page_ids"))
    except SystemExit as exc:
        changes.append(
            {
                "component": "source_snapshot",
                "reason": "state_page_scope_invalid",
                "path": str(snapshot_path),
                "detail": str(exc),
            }
        )
    else:
        if normalized_current_scope is not None:
            current_scope_keys = [
                canonical_page_id(item) for item in normalized_current_scope
            ]
            snapshot_scope_keys = [
                canonical_page_id(item) for item in snapshot_scope
            ]
            if (
                len(set(current_scope_keys)) != len(current_scope_keys)
                or len(set(snapshot_scope_keys)) != len(snapshot_scope_keys)
                or set(current_scope_keys) != set(snapshot_scope_keys)
            ):
                changes.append(
                    {
                        "component": "source_snapshot",
                        "reason": "state_page_scope_mismatch",
                        "path": str(snapshot_path),
                        "expected_page_ids": snapshot_scope,
                        "actual_page_ids": normalized_current_scope,
                    }
                )
    if expected_snapshot_sha != snapshot_file_sha:
        changes.append(
            {
                "component": "source_snapshot",
                "reason": "sha256_changed",
                "path": str(snapshot_path),
                "expected_sha256": expected_snapshot_sha,
                "actual_sha256": snapshot_file_sha,
            }
        )
    warnings: list[str] = []
    source = snapshot.get("authoritative_source") or {}
    source_value = source.get("path")
    source_path = Path(source_value).expanduser() if isinstance(source_value, str) else None
    current_source_sha: str | None = None
    current_page_content: dict[str, Any] | None = None
    frozen_fast8_packet = bool(
        expected_run_mode == FAST8_MODE
        and (snapshot.get("page_content") or {}).get("extractor")
        == "explicit_fragment"
        and (snapshot.get("page_content") or {}).get("authority_mode")
        == "authoritative_page_fragment"
    )
    if frozen_fast8_packet:
        # A Fast8 run deliberately freezes the requested page once.  The user
        # may continue editing the live deck outline while images are running;
        # that upstream file is provenance only and must not trigger hashing,
        # warnings, or a restart.  We still verify the frozen packet itself.
        fragment_value = (snapshot.get("page_content") or {}).get(
            "fragment_source_path"
        )
        fragment_path = (
            Path(fragment_value).expanduser().resolve()
            if isinstance(fragment_value, str) and fragment_value
            else None
        )
        try:
            if fragment_path is None:
                raise SystemExit("Fast8 冻结页面输入包缺失")
            current_page_content = {
                "extractor": "explicit_fragment",
                "pages": extract_explicit_fragment(
                    fragment_path, normalize_page_ids(snapshot.get("page_ids"))
                ),
            }
            aggregate = "\n\n".join(
                f"[[page_id:{item['page_id']}]]\n{item['normalized_text']}"
                for item in current_page_content["pages"]
            )
            current_page_content["normalized_text"] = aggregate
            current_page_content["sha256"] = sha256_text(aggregate)
        except SystemExit as exc:
            changes.append(
                {
                    "component": "page_content",
                    "reason": "extraction_failed",
                    "path": str(fragment_path) if fragment_path else fragment_value,
                    "detail": str(exc),
                }
            )
        else:
            expected_page_sha = (snapshot.get("page_content") or {}).get("sha256")
            if current_page_content["sha256"] != expected_page_sha:
                changes.append(
                    {
                        "component": "page_content",
                        "reason": "sha256_changed",
                        "path": str(fragment_path),
                        "expected_sha256": expected_page_sha,
                        "actual_sha256": current_page_content["sha256"],
                    }
                )
    elif source_path is None or not source_path.is_absolute() or not source_path.is_file():
        changes.append(
            {
                "component": "authoritative_source",
                "reason": "missing_or_non_absolute",
                "path": source_value,
            }
        )
    else:
        source_path = source_path.resolve()
        current_source_sha = file_sha256(source_path)
        fragment_value = (snapshot.get("page_content") or {}).get(
            "fragment_source_path"
        )
        fragment_path = (
            Path(fragment_value).expanduser().resolve()
            if isinstance(fragment_value, str) and fragment_value
            else None
        )
        try:
            current_page_content = extract_relevant_source_content(
                source_path,
                normalize_page_ids(snapshot.get("page_ids")),
                fragment_path,
            )
        except SystemExit as exc:
            changes.append(
                {
                    "component": "page_content",
                    "reason": "extraction_failed",
                    "path": str(source_path),
                    "detail": str(exc),
                }
            )
        else:
            expected_page_sha = (snapshot.get("page_content") or {}).get("sha256")
            if current_page_content["sha256"] != expected_page_sha:
                changes.append(
                    {
                        "component": "page_content",
                        "reason": "sha256_changed",
                        "path": str(source_path),
                        "expected_sha256": expected_page_sha,
                        "actual_sha256": current_page_content["sha256"],
                    }
                )

    current_contracts: list[dict[str, Any]] = []
    for item in snapshot.get("content_contracts") or []:
        path_value = item.get("path") if isinstance(item, dict) else None
        path = Path(path_value).expanduser() if isinstance(path_value, str) else None
        if path is None or not path.is_absolute() or not path.is_file():
            changes.append(
                {
                    "component": "content_contract",
                    "reason": "missing_or_non_absolute",
                    "path": path_value,
                }
            )
            continue
        current = file_record(path, "内容合同")
        current_contracts.append(current)
        if current["sha256"] != item.get("sha256"):
            changes.append(
                {
                    "component": "content_contract",
                    "reason": "sha256_changed",
                    "path": current["path"],
                    "expected_sha256": item.get("sha256"),
                    "actual_sha256": current["sha256"],
                }
            )

    current_supporting_sources: list[dict[str, Any]] = []
    for item in snapshot.get("supporting_sources") or []:
        path_value = item.get("path") if isinstance(item, dict) else None
        path = Path(path_value).expanduser() if isinstance(path_value, str) else None
        if path is None or not path.is_absolute() or not path.is_file():
            changes.append(
                {
                    "component": "supporting_source",
                    "reason": "missing_or_non_absolute",
                    "path": path_value,
                }
            )
            continue
        current = file_record(path, "内容规划来源")
        current_supporting_sources.append(current)
        if current["sha256"] != item.get("sha256"):
            changes.append(
                {
                    "component": "supporting_source",
                    "reason": "sha256_changed",
                    "path": current["path"],
                    "expected_sha256": item.get("sha256"),
                    "actual_sha256": current["sha256"],
                }
            )

    current_assets: list[dict[str, Any]] = []
    for item in snapshot.get("assets") or []:
        path_value = item.get("path") if isinstance(item, dict) else None
        path = Path(path_value).expanduser() if isinstance(path_value, str) else None
        if path is None or not path.is_absolute() or not path.is_file():
            changes.append(
                {
                    "component": "used_asset",
                    "reason": "missing_or_non_absolute",
                    "path": path_value,
                }
            )
            continue
        current = file_record(path, "实际使用资产")
        current_assets.append(current)
        if current["sha256"] != item.get("sha256"):
            changes.append(
                {
                    "component": "used_asset",
                    "reason": "sha256_changed",
                    "path": current["path"],
                    "expected_sha256": item.get("sha256"),
                    "actual_sha256": current["sha256"],
                }
            )

    whole_source_changed = False if frozen_fast8_packet else (
        current_source_sha is None
        or current_source_sha != source.get("sha256")
    )
    if (
        whole_source_changed
        and (snapshot.get("page_content") or {}).get("extractor")
        == "explicit_fragment"
        and (snapshot.get("page_content") or {}).get("authority_mode")
        != "authoritative_page_fragment"
        and not any(item["component"] == "page_content" for item in changes)
    ):
        changes.append(
            {
                "component": "page_content",
                "reason": "source_change_unverifiable_with_external_fragment",
                "path": str(source_path) if source_path else source_value,
                "fragment_source_path": (snapshot.get("page_content") or {}).get(
                    "fragment_source_path"
                ),
            }
        )
    relevant_changed = any(item["component"] == "page_content" for item in changes)
    contract_changed = any(item["component"] == "content_contract" for item in changes)
    supporting_source_changed = any(
        item["component"] == "supporting_source" for item in changes
    )
    asset_changed = any(item["component"] == "used_asset" for item in changes)
    snapshot_changed = any(item["component"] == "source_snapshot" for item in changes)
    source_missing = any(
        item["component"] == "authoritative_source" for item in changes
    )
    blocked = (
        relevant_changed
        or contract_changed
        or supporting_source_changed
        or asset_changed
        or source_missing
        or snapshot_changed
    )
    if blocked:
        status = "source_drift_detected"
        next_actions = [
            "stop_reusing_existing_candidates",
            "reconfirm_content_contract_or_create_new_run_directory",
        ]
    elif whole_source_changed:
        status = "warning_unrelated_source_change"
        warnings.append(
            "整个权威源文件 SHA-256 已变化，但本次页面规范化内容、内容合同和实际使用资产均未变化。"
        )
        next_actions = ["continue_requested_action"]
    else:
        status = "unchanged"
        next_actions = ["continue_requested_action"]
    return {
        "source_drift_contract_version": 1,
        "checked_at": timestamp or now_iso(),
        "checked_action": action,
        "state_path": str(state_path),
        "snapshot_path": str(snapshot_path),
        "status": status,
        "can_continue": not blocked,
        "warning": status == "warning_unrelated_source_change",
        "upstream_source_check_skipped": frozen_fast8_packet,
        "requires_user_confirmation": blocked,
        "whole_source_changed": whole_source_changed,
        "relevant_page_content_changed": relevant_changed,
        "content_contract_changed": contract_changed,
        "supporting_source_changed": supporting_source_changed,
        "used_asset_changed": asset_changed,
        "source_snapshot_changed": snapshot_changed,
        "changes": changes,
        "warnings": warnings,
        "expected": {
            "source_sha256": source.get("sha256"),
            "page_content_sha256": (snapshot.get("page_content") or {}).get("sha256"),
            "content_contract_sha256": snapshot.get("content_contract_sha256"),
            "supporting_sources_sha256": snapshot.get("supporting_sources_sha256"),
            "assets_sha256": snapshot.get("assets_sha256"),
        },
        "current": {
            "source_sha256": current_source_sha,
            "page_content_sha256": (
                current_page_content.get("sha256") if current_page_content else None
            ),
            "page_content_pages": (
                [
                    {"page_id": item["page_id"], "sha256": item["sha256"]}
                    for item in current_page_content.get("pages", [])
                ]
                if current_page_content
                else []
            ),
            "content_contract_sha256": (
                manifest_hash(current_contracts)
                if len(current_contracts) == len(snapshot.get("content_contracts") or [])
                else None
            ),
            "supporting_sources_sha256": (
                manifest_hash(current_supporting_sources)
                if len(current_supporting_sources)
                == len(snapshot.get("supporting_sources") or [])
                else None
            ),
            "assets_sha256": (
                manifest_hash(current_assets)
                if len(current_assets) == len(snapshot.get("assets") or [])
                else None
            ),
        },
        "next_allowed_actions": next_actions,
    }


def operation_path_set(items: list[Any], label: str) -> set[str]:
    values: set[str] = set()
    for index, item in enumerate(items):
        raw = item.get("path") if isinstance(item, dict) else item
        if isinstance(raw, Path):
            raw = str(raw)
        if not isinstance(raw, str) or not raw.strip():
            raise SystemExit(f"{label}[{index}] 缺少 path")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise SystemExit(f"{label}[{index}] 必须使用绝对路径：{raw}")
        values.add(str(path.resolve()))
    return values


def apply_operation_manifest_coverage(
    result: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    content_contract_paths: list[Any] | None = None,
    asset_items: list[Any] | None = None,
    exact_content_contracts: bool = False,
    exact_assets: bool = False,
    required_asset_roles: set[str] | None = None,
    page_ids: list[str] | None = None,
    exact_page_scope: bool = False,
    source_path: Path | None = None,
    fragment_path: Path | None = None,
) -> dict[str, Any]:
    """Bind the current operation's actual input paths to the sealed manifest."""

    changes = list(result.get("changes") or [])
    expected_contract_records = {
        str(Path(item["path"]).expanduser().resolve()): item
        for item in (snapshot.get("content_contracts") or [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    expected_asset_records = {
        str(Path(item["path"]).expanduser().resolve()): item
        for item in (snapshot.get("assets") or [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    expected_contracts = operation_path_set(
        snapshot.get("content_contracts") or [], "snapshot.content_contracts"
    )
    expected_assets = operation_path_set(snapshot.get("assets") or [], "snapshot.assets")

    def add_path_changes(
        component: str,
        actual: set[str],
        expected: set[str],
        *,
        exact: bool,
    ) -> None:
        for path in sorted(actual - expected):
            changes.append(
                {
                    "component": component,
                    "reason": "operation_path_not_in_snapshot",
                    "path": path,
                }
            )
        if exact:
            for path in sorted(expected - actual):
                changes.append(
                    {
                        "component": component,
                        "reason": "snapshot_path_not_used_by_operation",
                        "path": path,
                    }
                )

    if content_contract_paths is not None:
        actual_contracts = operation_path_set(
            content_contract_paths, "operation.content_contracts"
        )
        add_path_changes(
            "content_contract",
            actual_contracts,
            expected_contracts,
            exact=exact_content_contracts,
        )
        for item in content_contract_paths:
            if not isinstance(item, dict) or not item.get("sha256"):
                continue
            path = str(Path(str(item.get("path"))).expanduser().resolve())
            expected = expected_contract_records.get(path)
            if expected and item.get("sha256") != expected.get("sha256"):
                changes.append(
                    {
                        "component": "content_contract",
                        "reason": "operation_declared_sha256_mismatch",
                        "path": path,
                        "expected_sha256": expected.get("sha256"),
                        "actual_sha256": item.get("sha256"),
                    }
                )
    if asset_items is not None:
        actual_assets = operation_path_set(asset_items, "operation.assets")
        add_path_changes(
            "used_asset", actual_assets, expected_assets, exact=exact_assets
        )
        for item in asset_items:
            if not isinstance(item, dict) or not item.get("sha256"):
                continue
            path = str(Path(str(item.get("path"))).expanduser().resolve())
            expected = expected_asset_records.get(path)
            if expected and item.get("sha256") != expected.get("sha256"):
                changes.append(
                    {
                        "component": "used_asset",
                        "reason": "operation_declared_sha256_mismatch",
                        "path": path,
                        "expected_sha256": expected.get("sha256"),
                        "actual_sha256": item.get("sha256"),
                    }
                )
            expected_used_by = {
                normalize_style(str(style))
                for style in ((expected or {}).get("used_by") or [])
            }
            actual_used_by = {
                normalize_style(str(style))
                for style in (item.get("used_by") or [])
            }
            if (
                expected_used_by
                and actual_used_by
                and not actual_used_by.issubset(expected_used_by)
            ):
                changes.append(
                    {
                        "component": "used_asset",
                        "reason": "operation_style_not_in_snapshot_routing",
                        "path": path,
                        "expected_used_by": sorted(expected_used_by),
                        "actual_used_by": sorted(actual_used_by),
                    }
                )
        if required_asset_roles:
            for path, expected in expected_asset_records.items():
                roles = expected.get("roles") or []
                if (
                    isinstance(roles, list)
                    and required_asset_roles.intersection(
                        str(role) for role in roles
                    )
                    and path not in actual_assets
                ):
                    changes.append(
                        {
                            "component": "used_asset",
                            "reason": "required_asset_role_not_used_by_operation",
                            "path": path,
                            "required_roles": sorted(required_asset_roles),
                        }
                    )
    if page_ids is not None:
        actual_page_ids = normalize_page_ids(page_ids)
        expected_page_ids = normalize_page_ids(snapshot.get("page_ids"))
        actual_keys = {canonical_page_id(item) for item in actual_page_ids}
        expected_keys = {canonical_page_id(item) for item in expected_page_ids}
        scope_matches = (
            actual_keys == expected_keys
            if exact_page_scope
            else actual_keys.issubset(expected_keys)
        )
        if not scope_matches:
            changes.append(
                {
                    "component": "page_content",
                    "reason": "operation_page_scope_mismatch",
                    "expected_page_ids": expected_page_ids,
                    "actual_page_ids": actual_page_ids,
                }
            )
    if source_path is not None:
        expected_source = (snapshot.get("authoritative_source") or {}).get("path")
        actual_source = str(source_path.expanduser().resolve())
        if actual_source != expected_source:
            changes.append(
                {
                    "component": "authoritative_source",
                    "reason": "operation_source_path_mismatch",
                    "expected_path": expected_source,
                    "actual_path": actual_source,
                }
            )
    if fragment_path is not None:
        expected_fragment = (snapshot.get("page_content") or {}).get(
            "fragment_source_path"
        )
        actual_fragment = str(fragment_path.expanduser().resolve())
        if actual_fragment != expected_fragment:
            changes.append(
                {
                    "component": "page_content",
                    "reason": "operation_fragment_path_mismatch",
                    "expected_path": expected_fragment,
                    "actual_path": actual_fragment,
                }
            )

    if len(changes) == len(result.get("changes") or []):
        return result
    result = dict(result)
    result["changes"] = changes
    result["status"] = "source_drift_detected"
    result["can_continue"] = False
    result["warning"] = False
    result["requires_user_confirmation"] = True
    result["relevant_page_content_changed"] = any(
        item.get("component") == "page_content" for item in changes
    )
    result["content_contract_changed"] = any(
        item.get("component") == "content_contract" for item in changes
    )
    result["used_asset_changed"] = any(
        item.get("component") == "used_asset" for item in changes
    )
    result["next_allowed_actions"] = [
        "stop_reusing_existing_candidates",
        "reconfirm_content_contract_or_create_new_run_directory",
    ]
    return result


def persist_source_drift_result(
    state_path: Path, state: dict[str, Any], result: dict[str, Any]
) -> None:
    state_path = state_path.resolve()
    state_parent = state_path.parent
    project_dir = state_parent.parent if state_parent.name == "state" else state_parent
    report_path = project_dir / "state" / "source_drift_status.json"
    atomic_write_json(report_path, result)
    state["source_integrity"] = {
        "status": result["status"],
        "checked_action": result.get("checked_action"),
        "checked_at": result.get("checked_at"),
        "report_path": str(report_path),
    }
    state["source_drift_detected"] = not bool(result.get("can_continue"))
    atomic_write_json(state_path, state)


def finalize_source_guard_result(
    state_path: Path,
    state: dict[str, Any],
    result: dict[str, Any],
    *,
    persist_state: bool = True,
) -> dict[str, Any]:
    """Persist warnings/blocks and raise only after the complete guard result exists."""

    previous_integrity = state.get("source_integrity") or {}
    should_persist = (
        result.get("warning")
        or not result.get("can_continue")
        or state.get("source_drift_detected") is True
        or previous_integrity.get("status")
        not in {None, "snapshot_sealed", "unchanged"}
    )
    if should_persist and persist_state:
        persist_source_drift_result(state_path, state, result)
    elif should_persist:
        project_dir = project_dir_for_state(state_path, state)
        atomic_write_json(project_dir / "state" / "source_drift_status.json", result)
    if not result.get("can_continue"):
        raise SystemExit(
            f"{result['status']}：禁止继续沿用旧候选；请重新确认内容合同或建立新运行目录"
        )
    return result


def enforce_source_guard(
    state_path: Path,
    state: dict[str, Any],
    *,
    action: str,
    content_contract_paths: list[Any] | None = None,
    asset_items: list[Any] | None = None,
    exact_content_contracts: bool = False,
    exact_assets: bool = False,
    required_asset_roles: set[str] | None = None,
    page_ids: list[str] | None = None,
    exact_page_scope: bool = False,
    source_path: Path | None = None,
    fragment_path: Path | None = None,
    persist_state: bool = True,
) -> dict[str, Any]:
    """Enforce drift, with an explicit auditable decision for legacy runs."""

    if not source_guard_enabled(state_path, state):
        result = legacy_source_drift_result(
            state_path, state, action, missing_required=False
        )
        if legacy_source_confirmation_allows(state_path, state, action):
            return confirmed_legacy_source_result(result, action)
        raise SystemExit(
            "legacy_snapshot_missing：旧任务缺少历史 source snapshot；"
            "必须先由用户明确确认本次兼容动作，或建立新运行目录"
        )
    result = evaluate_source_drift(state_path, state, action=action)
    snapshot_path = source_snapshot_path_for_state(state_path, state)
    if (
        result.get("status") != "fast8_inputs_locked_at_initial_dispatch"
        and snapshot_path is not None
        and snapshot_path.is_file()
    ):
        result = apply_operation_manifest_coverage(
            result,
            read_json(snapshot_path),
            content_contract_paths=content_contract_paths,
            asset_items=asset_items,
            exact_content_contracts=exact_content_contracts,
            exact_assets=exact_assets,
            required_asset_roles=required_asset_roles,
            page_ids=page_ids,
            exact_page_scope=exact_page_scope,
            source_path=source_path,
            fragment_path=fragment_path,
        )
    return finalize_source_guard_result(
        state_path, state, result, persist_state=persist_state
    )


def project_dir_for_state(state_path: Path, state: dict[str, Any]) -> Path:
    configured = state.get("project_dir")
    if isinstance(configured, str) and configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise SystemExit("state.project_dir 必须是绝对路径")
        return path.resolve()
    state_parent = state_path.resolve().parent
    return state_parent.parent if state_parent.name == "state" else state_parent


def require_formal_file_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{label}缺少路径")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise SystemExit(f"{label}路径包含禁止的控制字符")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SystemExit(f"{label}必须使用绝对路径：{value}")
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"{label}不存在：{path}")
    return path


def require_path_within(path: Path, directory: Path, label: str) -> None:
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError as exc:
        raise SystemExit(f"{label}必须位于正式目录：{directory.resolve()}") from exc


def handoff_page_scope(state: dict[str, Any]) -> list[str]:
    mode = state.get("run_mode") or state.get("mode")
    if isinstance(state.get("pages"), dict) and state.get("phase") == "selected_style_expansion":
        order = state.get("page_order")
        if isinstance(order, list) and order:
            return [str(item) for item in order]
        return sorted(str(item) for item in state["pages"])
    anchor = state.get("anchor_page_id")
    if anchor is None:
        raise SystemExit("状态缺少 anchor_page_id")
    if mode in {QUICK_8X1_MODE, FAST8_MODE}:
        return [str(anchor)]
    followers = state.get("follower_page_ids") or []
    return [str(anchor), *(str(item) for item in followers)]


def handoff_state_records(
    state: dict[str, Any], page_ids: list[str]
) -> list[tuple[str, str, dict[str, Any]]]:
    if isinstance(state.get("pages"), dict) and state.get("phase") == "selected_style_expansion":
        selected = normalize_style(state.get("selected_style"))
        if selected is None:
            raise SystemExit("扩页状态缺少 selected_style")
        records = []
        for page_id in page_ids:
            record = state["pages"].get(page_id)
            if not isinstance(record, dict):
                raise SystemExit(f"扩页状态缺少页面 {page_id}")
            records.append((selected, page_id, record))
        return records
    mode = state.get("run_mode") or state.get("mode")
    records = []
    for style in styles_for_mode(mode):
        style_state = (state.get("styles") or {}).get(style)
        if not isinstance(style_state, dict):
            raise SystemExit(f"状态缺少 style_{style}")
        pages = style_state.get("pages") or {}
        for page_id in page_ids:
            record = pages.get(page_id)
            if not isinstance(record, dict):
                raise SystemExit(f"状态缺少 style_{style}/page_{page_id}")
            records.append((style, page_id, record))
    return records


def handoff_candidate_record(
    style: str, page_id: str, record: dict[str, Any]
) -> dict[str, Any]:
    status = record.get("status")
    if status not in {"candidate_ready", "accepted"}:
        raise SystemExit(
            f"style_{style}/page_{page_id} 尚未 candidate_ready 或 accepted"
        )
    path_kind = "final_path" if record.get("final_path") else "selected_source"
    path = require_formal_file_path(record.get(path_kind), "正式候选图片")
    width, height, size, sha256 = png_metadata(path)
    recorded_sha = record.get("source_sha256")
    if isinstance(recorded_sha, str) and recorded_sha and recorded_sha != sha256:
        raise SystemExit(
            f"style_{style}/page_{page_id} 当前文件 SHA-256 与状态记录不一致"
        )
    role = record.get("role") or "page"
    return {
        "candidate_id": f"{style}-{page_id}",
        "style_slot": style,
        "page_id": page_id,
        "role": role,
        "path": str(path),
        "path_kind": path_kind,
        "width": width,
        "height": height,
        "size_bytes": size,
        "sha256": sha256,
        "status": status,
        "qa_stage": record.get("qa_stage"),
        "qa_scope": record.get("qa_scope"),
    }


def collect_user_selection(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("user_selection")
    if isinstance(raw, dict):
        candidate = raw.get("candidate_id") or raw.get("selected_candidate")
        style = raw.get("selected_style")
        selected = bool(raw.get("selected", candidate or style))
        return {
            "selected": selected,
            "candidate_id": candidate,
            "selected_style": style,
            "selected_page_id": raw.get("selected_page_id"),
            "recorded_at": raw.get("recorded_at"),
        }
    style = state.get("selected_style")
    candidate = state.get("selected_candidate")
    return {
        "selected": bool(style or candidate),
        "candidate_id": candidate,
        "selected_style": style,
        "selected_page_id": state.get("selected_page_id"),
        "recorded_at": state.get("selection_recorded_at"),
    }


def validate_user_selection(
    selection: dict[str, Any], candidates: list[dict[str, Any]]
) -> None:
    selected = selection.get("selected")
    if not isinstance(selected, bool):
        raise SystemExit("handoff.user_selection.selected 必须是布尔值")
    supplied = {}
    for key in ("candidate_id", "selected_style", "selected_page_id"):
        value = selection.get(key)
        if value is not None and value != "":
            supplied[key] = value
    if not selected:
        if supplied:
            raise SystemExit("用户未选定候选时不得同时记录候选、风格或页码")
        return
    if not selection.get("candidate_id") and not selection.get("selected_style"):
        raise SystemExit("用户已选定候选时必须记录 candidate_id 或 selected_style")

    by_id = {str(item["candidate_id"]): item for item in candidates}
    candidate = None
    candidate_id = selection.get("candidate_id")
    if candidate_id:
        candidate = by_id.get(str(candidate_id))
        if candidate is None:
            raise SystemExit(f"用户选定的 candidate_id 不在正式候选中：{candidate_id}")

    selected_style = selection.get("selected_style")
    normalized_style = normalize_style(str(selected_style)) if selected_style else None
    candidate_styles = {item["style_slot"] for item in candidates}
    if normalized_style and normalized_style not in candidate_styles:
        raise SystemExit(f"用户选定的风格不在正式候选中：{selected_style}")
    if candidate and normalized_style and candidate["style_slot"] != normalized_style:
        raise SystemExit("用户选择的 candidate_id 与 selected_style 不一致")

    selected_page_id = selection.get("selected_page_id")
    if selected_page_id:
        matching_pages = [
            item for item in candidates if page_ids_match(item["page_id"], selected_page_id)
        ]
        if not matching_pages:
            raise SystemExit(f"用户选定的页码不在正式候选中：{selected_page_id}")
        if candidate and not page_ids_match(candidate["page_id"], selected_page_id):
            raise SystemExit("用户选择的 candidate_id 与 selected_page_id 不一致")
        if normalized_style and not any(
            item["style_slot"] == normalized_style for item in matching_pages
        ):
            raise SystemExit("用户选择的 selected_style 与 selected_page_id 不一致")


def infer_next_allowed_actions(
    state: dict[str, Any], selection: dict[str, Any]
) -> list[str]:
    explicit = state.get("next_allowed_actions")
    if isinstance(explicit, list) and all(isinstance(item, str) for item in explicit):
        return list(dict.fromkeys(item for item in explicit if item))
    if not selection["selected"]:
        return [
            "await_user_candidate_selection",
            "check_source_drift_before_selected_style_expansion",
        ]
    return [
        "check_source_drift_before_selected_style_expansion_or_pptx_handoff",
        "continue_only_with_the_recorded_selection",
    ]


def infer_unresolved_issues(state: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("unresolved_issues", "open_issues"):
        raw = state.get(field)
        if isinstance(raw, list):
            values.extend(str(item).strip() for item in raw if str(item).strip())
    for field in ("blocked_reason", "failure_reason"):
        raw = state.get(field)
        if isinstance(raw, str) and raw.strip():
            values.append(raw.strip())
    return list(dict.fromkeys(values))


def validate_handoff_text_list(
    values: list[str], label: str, *, max_items: int, max_chars: int
) -> list[str]:
    if len(values) > max_items:
        raise SystemExit(f"{label} 项目过多；请先压缩为必要交接说明")
    normalized: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise SystemExit(f"{label} 必须只包含非空字符串")
        text_value = item.strip()
        if len(text_value) > max_chars:
            raise SystemExit(f"{label} 含大段文字；请先压缩为必要交接说明")
        normalized.append(text_value)
    return list(dict.fromkeys(normalized))


def assert_safe_handoff_text(value: str, label: str) -> None:
    forbidden = (
        ("markdown_image", r"!\s*\["),
        ("html_media", r"<\s*(?:img|picture|svg|object|embed|source)\b"),
        ("image_data_uri", r"data\s*:\s*image\s*/"),
        ("base64_marker", r";\s*base64\s*,"),
        (
            "known_image_base64",
            r"(?:iVBORw0KGgo|/9j/|R0lGOD(?:lh|dh)|UklGR)[A-Za-z0-9+/=]{24,}",
        ),
    )
    for rule, pattern in forbidden:
        if re.search(pattern, value, re.IGNORECASE):
            raise SystemExit(f"{label} 包含禁止的媒体嵌入或编码：{rule}")
    if re.search(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{256,}={0,2}", value):
        raise SystemExit(f"{label} 疑似包含大段 Base64")


def assert_safe_handoff_value(value: Any, label: str = "handoff.json") -> None:
    if isinstance(value, str):
        assert_safe_handoff_text(value, label)
    elif isinstance(value, dict):
        for item in value.values():
            assert_safe_handoff_value(item, label)
    elif isinstance(value, list):
        for item in value:
            assert_safe_handoff_value(item, label)


def build_handoff_document(
    *,
    project_dir: Path,
    state_path: Path,
    state: dict[str, Any] | None = None,
    unresolved_issues: list[str] | None = None,
    next_allowed_actions: list[str] | None = None,
    timestamp: str | None = None,
    drift_result: dict[str, Any] | None = None,
    state_sha256: str | None = None,
) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    state_path = state_path.resolve()
    if not project_dir.is_dir():
        raise SystemExit(f"项目目录不存在：{project_dir}")
    state = state if state is not None else read_json(state_path)
    if not source_guard_enabled(state_path, state):
        raise SystemExit(
            "legacy_snapshot_missing：旧任务不能生成具备历史完整性声明的正式 handoff；"
            "请由用户确认后建立新运行目录"
        )
    # A caller-provided result is only a scheduling hint.  Recompute against the
    # current files at the final handoff boundary so a stale pass cannot be used
    # after a contract, source fragment, or asset changes.
    drift_result = evaluate_source_drift(
        state_path, state, action="candidate_delivery"
    )
    if not drift_result.get("can_continue"):
        raise SystemExit(
            f"{drift_result.get('status')}：源材料未通过交接前漂移检测"
        )
    snapshot_path = source_snapshot_path_for_state(state_path, state)
    if snapshot_path is None:
        raise SystemExit("source snapshot 路径缺失")
    snapshot_path = require_formal_file_path(str(snapshot_path), "source snapshot")
    snapshot, snapshot_file_sha = read_json_with_sha256(snapshot_path)
    if state.get("source_snapshot_sha256") != snapshot_file_sha:
        raise SystemExit("source snapshot 在交接构建期间发生变化")
    if snapshot.get("project_dir") != str(project_dir):
        raise SystemExit("source snapshot 的 project_dir 与 handoff 项目目录不一致")
    if snapshot.get("run_id") != state.get("run_id"):
        raise SystemExit("source snapshot 的 run_id 与正式状态不一致")
    run_mode = resolved_run_mode(state)
    if snapshot.get("run_mode") != run_mode:
        raise SystemExit("source snapshot 的 run_mode 与正式状态不一致")
    source_path = require_formal_file_path(
        (snapshot.get("authoritative_source") or {}).get("path"), "权威源文件"
    )
    page_ids = handoff_page_scope(state)
    snapshot_page_ids = snapshot.get("page_ids")
    if not page_id_sets_match(page_ids, snapshot_page_ids):
        raise SystemExit("handoff 页面范围与 source snapshot.page_ids 不一致")
    snapshot_page_records = (snapshot.get("page_content") or {}).get("pages") or []
    snapshot_content_page_ids = [
        str(item.get("page_id"))
        for item in snapshot_page_records
        if isinstance(item, dict) and item.get("page_id") is not None
    ]
    if not page_id_sets_match(page_ids, snapshot_content_page_ids):
        raise SystemExit("handoff 页面范围与 source snapshot.page_content.pages 不一致")
    records = handoff_state_records(state, page_ids)
    candidates = [
        handoff_candidate_record(style, page_id, record)
        for style, page_id, record in records
    ]
    slide_identity = snapshot.get("slide_identity")
    attach_slide_identity_to_candidates(candidates, slide_identity)
    for candidate in candidates:
        require_path_within(
            Path(candidate["path"]), project_dir / "origin_image", "正式候选图片"
        )
    overview_state = state.get("overview") or {}
    overview_path = require_formal_file_path(
        overview_state.get("final_path"), "正式总览图"
    )
    overview_width, overview_height, overview_size, overview_sha = raw_png_metadata(
        overview_path
    )
    require_path_within(overview_path, project_dir / "overview", "正式总览图")
    selection = collect_user_selection(state)
    validate_user_selection(selection, candidates)
    issues = validate_handoff_text_list(
        (
            unresolved_issues
            if unresolved_issues is not None
            else infer_unresolved_issues(state)
        ),
        "handoff.unresolved_issues",
        max_items=20,
        max_chars=500,
    )
    actions = validate_handoff_text_list(
        (
            next_allowed_actions
            if next_allowed_actions is not None
            else infer_next_allowed_actions(state, selection)
        ),
        "handoff.next_allowed_actions",
        max_items=20,
        max_chars=160,
    )
    if not actions:
        raise SystemExit("handoff.next_allowed_actions 不得为空")
    contracts = []
    for item in snapshot.get("content_contracts") or []:
        path = require_formal_file_path(item.get("path"), "内容合同")
        contracts.append({**item, "path": str(path), "sha256": file_sha256(path)})
    assets = []
    for item in snapshot.get("assets") or []:
        path = require_formal_file_path(item.get("path"), "实际使用参考资产")
        assets.append({**item, "path": str(path), "sha256": file_sha256(path)})
    if manifest_hash(contracts) != snapshot.get("content_contract_sha256"):
        raise SystemExit("内容合同在交接构建期间发生变化")
    if manifest_hash(assets) != snapshot.get("assets_sha256"):
        raise SystemExit("实际使用资产在交接构建期间发生变化")
    drift_result = evaluate_source_drift(
        state_path, state, action="candidate_delivery"
    )
    if not drift_result.get("can_continue"):
        raise SystemExit(
            f"{drift_result.get('status')}：源材料未通过交接前最终漂移检测"
        )
    candidate_status = (
        "candidate_ready"
        if any(item["status"] == "candidate_ready" for item in candidates)
        else "accepted"
    )
    pipeline_phase = state.get("phase") or (state.get("scheduler") or {}).get("phase")
    current_page_hashes = {
        str(item.get("page_id")): item.get("sha256")
        for item in ((drift_result.get("current") or {}).get("page_content_pages") or [])
        if isinstance(item, dict)
    }
    page_hashes = [
        {
            "page_id": str(item.get("page_id")),
            "snapshot_sha256": item.get("sha256"),
            "current_sha256": current_page_hashes.get(str(item.get("page_id"))),
        }
        for item in ((snapshot.get("page_content") or {}).get("pages") or [])
        if isinstance(item, dict)
    ]
    diversity_handoff: dict[str, Any] | None = None
    if run_mode == FAST8_MODE:
        review = state.get("diversity_review") or {}
        final_report = next(
            (
                item
                for item in reversed(review.get("reports") or [])
                if isinstance(item, dict)
                and item.get("decision") in {"pass", "best_effort"}
                and item.get("candidate_set_sha256")
                == review.get("final_candidate_set_sha256")
            ),
            None,
        )
        if not isinstance(final_report, dict):
            raise SystemExit("Fast8 handoff 缺少绑定最终候选集合的差异报告")
        final_report_path = require_formal_file_path(
            final_report.get("report_path"), "Fast8 最终差异报告"
        )
        require_path_within(
            final_report_path,
            project_dir / "visual_qa_jobs" / "results",
            "Fast8 最终差异报告",
        )
        if file_sha256(final_report_path) != final_report.get("report_sha256"):
            raise SystemExit("Fast8 最终差异报告 SHA-256 与状态不一致")
        diversity_handoff = {
            "required": True,
            "contract_version": review.get("contract_version"),
            "scope": review.get("scope"),
            "final_report_path": str(final_report_path),
            "final_report_sha256": final_report["report_sha256"],
            "decision": review.get("status"),
            "review_kind": final_report.get("review_kind"),
            "candidate_set_sha256": review.get("final_candidate_set_sha256"),
            "replacement_styles": review.get("replacement_styles") or [],
            "replacement_rounds_used": int(
                review.get("replacement_rounds_used") or 0
            ),
        }
    handoff = {
        "handoff_contract_version": HANDOFF_CONTRACT_VERSION,
        "project_dir": str(project_dir),
        "run_id": state.get("run_id"),
        "run_mode": run_mode,
        "page_scope": {
            "page_ids": page_ids,
            "label": ",".join(page_ids),
        },
        "current_stage": (
            "selected_style_expansion"
            if state.get("phase") == "selected_style_expansion"
            else "candidate_delivery"
        ),
        "status": candidate_status,
        "pipeline_status": state.get("status"),
        "pipeline_phase": pipeline_phase,
        "state_ref": {
            "path": str(state_path),
            "sha256": state_sha256 or file_sha256(state_path),
            "state_audit_contract_version": state_audit_version(state),
        },
        "source_snapshot_ref": {
            "path": str(snapshot_path),
            "sha256": snapshot_file_sha,
            "source_snapshot_contract_version": snapshot.get(
                "source_snapshot_contract_version"
            ),
        },
        "slide_identity": slide_identity,
        "authoritative_source": {
            "path": str(source_path),
            "snapshot_sha256": (snapshot.get("authoritative_source") or {}).get(
                "sha256"
            ),
            "current_sha256": (drift_result.get("current") or {}).get(
                "source_sha256"
            ),
        },
        "current_page_content": {
            "snapshot_sha256": (snapshot.get("page_content") or {}).get("sha256"),
            "current_sha256": (drift_result.get("current") or {}).get(
                "page_content_sha256"
            ),
            "extractor": (snapshot.get("page_content") or {}).get("extractor"),
            "pages": page_hashes,
        },
        "content_contracts": contracts,
        "content_contract_sha256": manifest_hash(contracts),
        "reference_assets": assets,
        "reference_assets_sha256": manifest_hash(assets),
        "candidates": candidates,
        "overview": {
            "path": str(overview_path),
            "width": overview_width,
            "height": overview_height,
            "size_bytes": overview_size,
            "sha256": overview_sha,
            "status": "ready",
        },
        "user_selection": selection,
        "unresolved_issues": issues,
        "source_drift": {
            "status": drift_result.get("status"),
            "warning": bool(drift_result.get("warning")),
            "checked_at": drift_result.get("checked_at"),
            "warnings": drift_result.get("warnings") or [],
        },
        "next_allowed_actions": actions,
        "media_policy": {
            "root_task_access": "paths_hashes_dimensions_and_status_only",
            "embedded_media_allowed": False,
            "visual_review_requires_isolated_worker": True,
        },
        "generated_at": timestamp or now_iso(),
    }
    if diversity_handoff is not None:
        handoff["diversity_review"] = diversity_handoff
    assert_safe_handoff_value(handoff)
    return handoff


def markdown_file_link(label: str, path_value: str) -> str:
    if not isinstance(path_value, str) or not path_value.strip():
        raise SystemExit(f"{label}缺少路径")
    if any(character in path_value for character in ("\x00", "\r", "\n")):
        raise SystemExit(f"{label}路径包含禁止的控制字符")
    path = Path(path_value)
    if not path.is_absolute():
        raise SystemExit(f"{label}必须使用绝对路径：{path_value}")
    safe_label = label.replace("[", "(").replace("]", ")")
    return f"[{safe_label}](<{path_value}>)"


def render_handoff_markdown(handoff: dict[str, Any]) -> str:
    require_keys(
        handoff,
        [
            "handoff_contract_version",
            "project_dir",
            "run_mode",
            "page_scope",
            "current_stage",
            "status",
            "state_ref",
            "source_snapshot_ref",
            "authoritative_source",
            "current_page_content",
            "content_contracts",
            "reference_assets",
            "candidates",
            "overview",
            "user_selection",
            "unresolved_issues",
            "source_drift",
            "next_allowed_actions",
            "generated_at",
        ],
        "handoff.json",
    )
    if handoff.get("handoff_contract_version") != HANDOFF_CONTRACT_VERSION:
        raise SystemExit("不支持的 handoff contract version")
    assert_safe_handoff_value(handoff)
    project_dir = Path(str(handoff["project_dir"])).expanduser()
    if not project_dir.is_absolute():
        raise SystemExit("handoff.project_dir 必须是绝对目录")
    if not isinstance(handoff.get("run_mode"), str) or not handoff["run_mode"].strip():
        raise SystemExit("handoff.run_mode 必须是非空字符串")
    selection = handoff.get("user_selection") or {}
    lines = [
        "# Shawn PPT 图片任务交接",
        "",
        "本文件由 `handoff.json` 确定性生成。新对话无需读取旧聊天或旧 JSONL；"
        "请以本交接、正式状态文件和源快照为准，并在任何继续动作前重新执行源材料漂移检测。",
        "",
        f"- 项目目录：`{project_dir}`",
        f"- 运行模式：`{handoff['run_mode']}`",
        f"- 页面范围：`{(handoff.get('page_scope') or {}).get('label')}`",
        f"- 当前阶段：`{handoff['current_stage']}`",
        f"- 当前状态：`{handoff['status']}`（管线状态：`{handoff.get('pipeline_status')}`）",
        f"- 生成时间：`{handoff['generated_at']}`",
        "",
        "## 权威输入",
        "",
        "- " + markdown_file_link("权威源文件", handoff["authoritative_source"]["path"]),
        f"  - 源文件 SHA-256（快照）：`{handoff['authoritative_source'].get('snapshot_sha256')}`",
        f"  - 源文件 SHA-256（当前）：`{handoff['authoritative_source'].get('current_sha256')}`",
        f"  - 本页内容 SHA-256：`{handoff['current_page_content'].get('current_sha256')}`",
        "- " + markdown_file_link("正式状态", handoff["state_ref"]["path"]),
        "- " + markdown_file_link("源材料快照", handoff["source_snapshot_ref"]["path"]),
        "",
        "### 内容合同",
        "",
    ]
    for index, item in enumerate(handoff.get("content_contracts") or [], start=1):
        lines.append(
            f"- {markdown_file_link(f'合同 {index}', item['path'])} — SHA-256 `{item['sha256']}`"
        )
    lines.extend(["", "### 实际使用的参考资产", ""])
    assets = handoff.get("reference_assets") or []
    if assets:
        for index, item in enumerate(assets, start=1):
            lines.append(
                f"- {markdown_file_link(f'资产 {index}', item['path'])} — SHA-256 `{item['sha256']}`"
            )
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "## 候选与总览",
            "",
            "| 候选 | 页面 | 状态 | 尺寸 | SHA-256 | 原图 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in handoff.get("candidates") or []:
        lines.append(
            "| {style} | {page} | `{status}` | {width}×{height} | `{sha}` | {link} |".format(
                style=item["style_slot"],
                page=item["page_id"],
                status=item["status"],
                width=item["width"],
                height=item["height"],
                sha=item["sha256"],
                link=markdown_file_link(
                    f"打开 {item['style_slot']}-{item['page_id']}", item["path"]
                ),
            )
        )
    overview = handoff["overview"]
    lines.extend(
        [
            "",
            "- "
            + markdown_file_link("打开总览", overview["path"])
            + f" — {overview['width']}×{overview['height']}，SHA-256 `{overview['sha256']}`",
            "- 媒体隔离：根任务只读取路径、哈希、尺寸和状态，不直接打开原图或总览。",
            "",
            "## 用户选择",
            "",
            f"- 已选定候选：`{str(bool(selection.get('selected'))).lower()}`",
            f"- 选定候选：`{selection.get('candidate_id') or selection.get('selected_style') or '无'}`",
        ]
    )
    diversity = handoff.get("diversity_review")
    if isinstance(diversity, dict):
        lines.extend(
            [
                "",
                "## Fast8 组合裁判收口",
                "",
                f"- 合同版本：`{diversity.get('contract_version')}`",
                f"- 范围：`{diversity.get('scope')}`",
                f"- 决定：`{diversity.get('decision')}`",
                f"- 复核类型：`{diversity.get('review_kind')}`",
                f"- 当前候选集合 SHA-256：`{diversity.get('candidate_set_sha256')}`",
                "- "
                + markdown_file_link(
                    "最终差异报告", diversity.get("final_report_path")
                ),
            ]
        )
    lines.extend(["", "## 尚未解决的问题", ""])
    issues = handoff.get("unresolved_issues") or []
    lines.extend(f"- {item}" for item in issues)
    if not issues:
        lines.append("- 无")
    drift = handoff.get("source_drift") or {}
    lines.extend(
        [
            "",
            "## 源材料漂移检查",
            "",
            f"- 状态：`{drift.get('status')}`",
            f"- 检查时间：`{drift.get('checked_at')}`",
            "- 警告：",
        ]
    )
    drift_warnings = drift.get("warnings") or []
    if drift_warnings:
        lines.extend(f"  - {item}" for item in drift_warnings)
    else:
        lines.append("  - 无")
    lines.extend(["", "## 下一步允许执行的动作", ""])
    lines.extend(f"- `{item}`" for item in handoff["next_allowed_actions"])
    lines.extend(
        [
            "",
            "继续前请运行：",
            "",
            "```text",
            "python3 scripts/pipeline_control.py check-source-drift "
            f"--state \"{handoff['state_ref']['path']}\" --action resume",
            "```",
            "",
        ]
    )
    rendered = "\n".join(lines)
    assert_safe_handoff_text(rendered, "handoff.md")
    return rendered


def health_page_records(
    state: dict[str, Any],
) -> list[tuple[str | None, str, dict[str, Any]]]:
    records: list[tuple[str | None, str, dict[str, Any]]] = []
    if (
        state.get("phase") == "selected_style_expansion"
        or state.get("run_mode") == "selected_style_expansion"
    ):
        for page_id, record in (state.get("pages") or {}).items():
            if isinstance(record, dict):
                records.append((None, str(page_id), record))
        return records
    for style, style_state in (state.get("styles") or {}).items():
        if not isinstance(style_state, dict):
            continue
        for page_id, record in (style_state.get("pages") or {}).items():
            if isinstance(record, dict):
                records.append((str(style), str(page_id), record))
    return records


def health_generation_job_paths(project_dir: Path) -> list[Path]:
    paths = [
        *project_dir.glob("style_jobs/style_*.json"),
        *project_dir.glob("style_page_jobs/style_*/page_*.json"),
        *project_dir.glob("page_jobs/page_*.json"),
    ]
    return sorted({path.resolve() for path in paths if path.is_file()}, key=str)


def health_duration_seconds(start: Any, end: Any) -> float | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        return (parse_time(end) - parse_time(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def health_summary(values: list[float]) -> dict[str, float | int | None]:
    clean = sorted(value for value in values if value >= 0)
    if not clean:
        return {"count": 0, "min_seconds": None, "max_seconds": None, "avg_seconds": None}
    return {
        "count": len(clean),
        "min_seconds": round(clean[0], 3),
        "max_seconds": round(clean[-1], 3),
        "avg_seconds": round(sum(clean) / len(clean), 3),
    }


def normalized_prompt_blocks(prompt: str) -> list[str]:
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", prompt):
        normalized = " ".join(unicodedata.normalize("NFKC", block).split())
        if len(normalized) >= 48:
            blocks.append(normalized)
    return blocks


def monitoring_root_for_state(
    state_path: Path,
    state: dict[str, Any],
    override: str | None = None,
) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    configured = ((state.get("monitoring") or {}).get("root"))
    if isinstance(configured, str) and configured:
        return Path(configured).expanduser().resolve()
    marker_path = task_init_contract_path_for_state(state_path, state)
    if marker_path.is_file():
        marker = read_json(marker_path)
        marker_root = marker.get("monitoring_root")
        if isinstance(marker_root, str) and marker_root:
            return Path(marker_root).expanduser().resolve()
        # A legacy/manual marker predating monitoring must stay self-contained.
        # Do not let tests or resumed historical runs silently write into the
        # current user's global registry.
        project_dir = project_dir_for_state(state_path, state)
        return (project_dir / "state" / "_monitoring" / "shawn-ppt-image").resolve()
    project_dir = project_dir_for_state(state_path, state)
    system_temp = Path(tempfile.gettempdir()).resolve()
    try:
        project_dir.relative_to(system_temp)
    except ValueError:
        pass
    else:
        # Unmarked test fixtures and disposable diagnostics must not pollute the
        # user's durable cross-conversation registry.
        return (project_dir / "state" / "_monitoring" / "shawn-ppt-image").resolve()
    user_config = Path.home() / ".codex" / "shawn-ppt-image-monitoring.json"
    if user_config.is_file():
        config = read_json(user_config)
        version = config.get("monitoring_config_version", MONITORING_CONFIG_VERSION)
        if version != MONITORING_CONFIG_VERSION:
            raise SystemExit(f"不支持的监测配置版本：{user_config}")
        root = config.get("monitoring_root")
        if not isinstance(root, str) or not root:
            raise SystemExit(f"监测配置缺少 monitoring_root：{user_config}")
        return Path(root).expanduser().resolve()
    return (project_dir.parent / "_skill_monitoring" / "shawn-ppt-image").resolve()


def fast8_global_imagegen_slot_paths(
    state_path: Path, state: dict[str, Any]
) -> tuple[Path, Path]:
    """Return the cross-task ImageGen lease registry and its advisory lock."""

    override = os.environ.get("SHAWN_PPT_IMAGE_GLOBAL_SLOT_STATE")
    if isinstance(override, str) and override.strip():
        registry = Path(override).expanduser().resolve()
    else:
        registry = (
            monitoring_root_for_state(state_path, state)
            / "runtime"
            / "imagegen_slots.json"
        ).resolve()
    return registry, registry.with_suffix(".lock")


def fast8_global_imagegen_lease_key(
    state_path: Path, state: dict[str, Any], task: dict[str, Any]
) -> str:
    identity = {
        "state_path": str(state_path.expanduser().resolve()),
        "run_id": state.get("run_id"),
        "style": normalize_style(task.get("style")),
        "page_id": str(task.get("page_id")),
        "action": str(task.get("action")),
        "attempt": int(task.get("attempt") or 1),
    }
    # Legacy dispatch-prelease runs deliberately retain their old identity.
    # JIT leases bind the scarce resource to the exact live Worker session and
    # immutable dispatch ticket, so an authorized-but-not-running task cannot
    # occupy ImageGen capacity.
    if task.get("lease_kind") is not None:
        identity["lease_kind"] = str(task.get("lease_kind"))
    if task.get("worker_session_id") is not None:
        identity["worker_session_id"] = str(task.get("worker_session_id"))
    if task.get("worker_ticket_sha256") is not None:
        identity["worker_ticket_sha256"] = str(task.get("worker_ticket_sha256"))
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]


@contextlib.contextmanager
def locked_fast8_global_imagegen_registry(
    state_path: Path,
    state: dict[str, Any],
    *,
    capacity_limit: int | None = None,
):
    """Serialize central lease mutations without putting image payloads in state."""

    registry_path, lock_path = fast8_global_imagegen_slot_paths(state_path, state)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            if registry_path.is_file():
                registry = read_json(registry_path)
            else:
                registry = {
                    "fast8_global_imagegen_slot_contract_version": (
                        FAST8_GLOBAL_IMAGEGEN_SLOT_CONTRACT_VERSION
                    ),
                    "capacity": FAST8_GLOBAL_IMAGEGEN_SLOT_LIMIT,
                    "leases": [],
                }
            if registry.get("fast8_global_imagegen_slot_contract_version") != (
                FAST8_GLOBAL_IMAGEGEN_SLOT_CONTRACT_VERSION
            ):
                raise SystemExit(f"不支持的 Fast8 全局 ImageGen 槽位表：{registry_path}")
            leases = registry.get("leases")
            if not isinstance(leases, list):
                raise SystemExit(f"Fast8 全局 ImageGen 槽位表 leases 无效：{registry_path}")
            now = datetime.now().astimezone()
            live: list[dict[str, Any]] = []
            for lease in leases:
                if not isinstance(lease, dict):
                    continue
                expires_at = lease.get("expires_at")
                try:
                    if isinstance(expires_at, str) and parse_time(expires_at) > now:
                        live.append(lease)
                except (TypeError, ValueError):
                    continue
            if capacity_limit is not None:
                requested_capacity = int(capacity_limit)
                current_capacity = int(
                    registry.get("capacity") or FAST8_GLOBAL_IMAGEGEN_SLOT_LIMIT
                )
                if live and requested_capacity != current_capacity:
                    raise SystemExit(
                        "已有 live ImageGen lease，禁止切换全局容量："
                        f"{current_capacity} -> {requested_capacity}"
                    )
                registry["capacity"] = requested_capacity
            else:
                registry["capacity"] = int(
                    registry.get("capacity") or FAST8_GLOBAL_IMAGEGEN_SLOT_LIMIT
                )
            registry["leases"] = live
            yield registry, registry_path
            registry["updated_at"] = now_iso()
            atomic_write_json(registry_path, registry)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def acquire_fast8_global_imagegen_slots(
    state_path: Path,
    state: dict[str, Any],
    tasks: list[dict[str, Any]],
    *,
    timestamp: str,
    capacity_limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str], int]:
    """Lease the currently available cross-task ImageGen slots in task order."""

    if not tasks:
        return [], [], {}, FAST8_GLOBAL_IMAGEGEN_SLOT_LIMIT
    acquired: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    lease_ids: dict[str, str] = {}
    with locked_fast8_global_imagegen_registry(
        state_path, state, capacity_limit=capacity_limit
    ) as (
        registry,
        _registry_path,
    ):
        leases = registry["leases"]
        capacity = int(registry["capacity"])
        existing_by_id = {
            str(item.get("lease_id")): item
            for item in leases
            if isinstance(item, dict) and item.get("lease_id")
        }
        available = max(0, capacity - len(existing_by_id))
        acquired_at = parse_time(timestamp)
        expires_at = (
            acquired_at + timedelta(seconds=FAST8_GLOBAL_IMAGEGEN_SLOT_TTL_SECONDS)
        ).isoformat(timespec="microseconds")
        for task in tasks:
            lease_id = fast8_global_imagegen_lease_key(state_path, state, task)
            task_key = (
                f"{task['style']}/{task['page_id']}/{task['action']}/"
                f"{int(task.get('attempt') or 1)}"
            )
            if lease_id in existing_by_id:
                acquired.append(task)
                lease_ids[task_key] = lease_id
                continue
            if available <= 0:
                deferred.append(task)
                continue
            lease = {
                "lease_id": lease_id,
                "run_id": state.get("run_id"),
                "state_path": str(state_path.resolve()),
                "style": task["style"],
                "page_id": str(task["page_id"]),
                "action": task["action"],
                "attempt": int(task.get("attempt") or 1),
                "acquired_at": timestamp,
                "expires_at": expires_at,
            }
            for optional_key in (
                "lease_kind",
                "worker_session_id",
                "worker_ticket_sha256",
            ):
                if task.get(optional_key) is not None:
                    lease[optional_key] = task.get(optional_key)
            leases.append(lease)
            existing_by_id[lease_id] = lease
            acquired.append(task)
            lease_ids[task_key] = lease_id
            available -= 1
        remaining = max(0, capacity - len(leases))
    return acquired, deferred, lease_ids, remaining


def release_fast8_global_imagegen_slots(
    state_path: Path,
    state: dict[str, Any],
    lease_ids: list[str],
) -> int:
    """Release settled ImageGen leases; missing or expired leases are idempotent."""

    normalized = {str(value) for value in lease_ids if isinstance(value, str) and value}
    if not normalized:
        return 0
    released = 0
    with locked_fast8_global_imagegen_registry(state_path, state) as (
        registry,
        _registry_path,
    ):
        kept = []
        for lease in registry["leases"]:
            if str(lease.get("lease_id")) in normalized:
                released += 1
            else:
                kept.append(lease)
        registry["leases"] = kept
    return released


# Compatibility-neutral names for consumers outside Fast8.  Fast8 remains the
# primary implementation owner; 4x3 reuses the same registry and lock instead
# of maintaining a second concurrency mechanism.
acquire_shared_imagegen_slots = acquire_fast8_global_imagegen_slots
release_shared_imagegen_slots = release_fast8_global_imagegen_slots
shared_imagegen_slot_paths = fast8_global_imagegen_slot_paths


def fast8_jit_imagegen_task_context(
    state_path: Path,
    state: dict[str, Any],
    ticket_path: Path,
    *,
    require_active: bool,
) -> dict[str, Any]:
    """Resolve one exact session-bound JIT ImageGen task from durable state."""

    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("Fast8 JIT ImageGen 槽位只适用于 fast_8x1_diverse")
    if fast8_imagegen_slot_policy(state) != CURRENT_FAST8_IMAGEGEN_SLOT_POLICY:
        raise SystemExit("当前运行不是 Worker JIT ImageGen 槽位策略")
    project_dir = project_dir_for_state(state_path, state)
    require_path_within(
        ticket_path,
        project_dir / "style_jobs" / "dispatch_tickets",
        "Fast8 Worker ticket",
    )
    if not ticket_path.is_file():
        raise SystemExit("Fast8 Worker ticket 不存在")
    ticket = read_json(ticket_path)
    if ticket.get("fast8_worker_ticket_contract_version") not in (
        FAST8_WORKER_TICKET_SUPPORTED_VERSIONS
    ):
        raise SystemExit("Fast8 Worker ticket 合同版本无效")
    if ticket.get("run_id") != state.get("run_id"):
        raise SystemExit("Fast8 Worker ticket 的 run_id 与状态不一致")
    if str(Path(str(ticket.get("state_path"))).expanduser().resolve()) != str(
        state_path
    ):
        raise SystemExit("Fast8 Worker ticket 的 state_path 与当前状态不一致")

    style = normalize_style(ticket.get("style"))
    page_id = str(ticket.get("page_id"))
    action = str(ticket.get("action"))
    attempt = int(ticket.get("attempt") or 0)
    ticket_sha = file_sha256(ticket_path)
    task_match = lambda item: (
        isinstance(item, dict)
        and item.get("style") == style
        and str(item.get("page_id")) == page_id
        and item.get("action") == action
        and int(item.get("attempt") or 1) == attempt
        and item.get("worker_ticket_path") == str(ticket_path)
    )

    active_item = next(
        (
            item
            for item in ((state.get("scheduler") or {}).get("active_actions") or [])
            if task_match(item)
        ),
        None,
    )
    if require_active and not isinstance(active_item, dict):
        raise SystemExit("Fast8 JIT ImageGen 槽位没有匹配的 active_action")
    if isinstance(active_item, dict) and active_item.get(
        "worker_ticket_sha256"
    ) != ticket_sha:
        raise SystemExit("Fast8 Worker ticket SHA-256 与 active_action 不一致")

    binding_task: dict[str, Any] | None = None
    for binding in (state.get("scheduler") or {}).get("worker_session_bindings", []):
        if not isinstance(binding, dict):
            continue
        binding_task = next(
            (item for item in (binding.get("tasks") or []) if task_match(item)),
            None,
        )
        if isinstance(binding_task, dict):
            break
    if not isinstance(binding_task, dict):
        raise SystemExit("Fast8 Worker ticket 尚未绑定真实 Worker session")
    session_id = binding_task.get("worker_session_id")
    if not isinstance(session_id, str) or CODEX_AGENT_THREAD_ID_RE.fullmatch(
        session_id
    ) is None:
        raise SystemExit("Fast8 Worker session UUID 无效")
    if isinstance(active_item, dict) and (
        active_item.get("worker_session_id") != session_id
        or active_item.get("worker_start_status") != "worker_started_confirmed"
    ):
        raise SystemExit("Fast8 Worker session 与 active_action 绑定不一致")

    dispatch_task: dict[str, Any] | None = None
    for event in reversed(state.get("events") or []):
        if not isinstance(event, dict) or event.get("name") != "dispatch_wave":
            continue
        dispatch_task = next(
            (
                item
                for item in ((event.get("details") or {}).get("started_tasks") or [])
                if task_match(item)
            ),
            None,
        )
        if isinstance(dispatch_task, dict):
            break
    if not isinstance(dispatch_task, dict) or dispatch_task.get(
        "worker_ticket_sha256"
    ) != ticket_sha:
        raise SystemExit("Fast8 Worker ticket 缺少正式 dispatch 绑定")

    return {
        "style": style,
        "page_id": page_id,
        "action": action,
        "attempt": attempt,
        "lease_kind": "imagegen_inflight",
        "worker_session_id": session_id,
        "worker_ticket_sha256": ticket_sha,
    }


def fast8_imagegen_slot_telemetry_path(
    state_path: Path, state: dict[str, Any], task: dict[str, Any]
) -> Path:
    """Return one collision-free, image-free timing sidecar per Worker attempt."""

    project_dir = project_dir_for_state(state_path, state)
    style = normalize_style(task.get("style"))
    page_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(task.get("page_id")))
    action = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(task.get("action")))
    attempt = int(task.get("attempt") or 1)
    return (
        project_dir
        / "style_jobs"
        / "results"
        / f"imagegen_slot_{style}_page_{page_id}_{action}_attempt_{attempt}.json"
    )


def write_fast8_imagegen_slot_telemetry(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    updates: dict[str, Any],
) -> Path:
    """Atomically persist control-plane timing without touching formal state."""

    path = fast8_imagegen_slot_telemetry_path(state_path, state, task)
    if path.is_file():
        telemetry = read_json(path)
    else:
        telemetry = {
            "imagegen_slot_telemetry_version": 1,
            "run_id": state.get("run_id"),
            "style": task.get("style"),
            "page_id": str(task.get("page_id")),
            "action": task.get("action"),
            "attempt": int(task.get("attempt") or 1),
            "worker_session_id": task.get("worker_session_id"),
            "worker_ticket_sha256": task.get("worker_ticket_sha256"),
        }
    telemetry.update(updates)
    atomic_write_json(path, telemetry)
    return path


def command_acquire_fast8_imagegen_slot(args: argparse.Namespace) -> None:
    """Acquire one scarce slot immediately before the Worker calls ImageGen."""

    state_path = Path(args.state).expanduser().resolve()
    ticket_path = Path(args.ticket).expanduser().resolve()
    slice_value = getattr(args, "slice_seconds", None)
    slice_mode = slice_value is not None
    wait_seconds = float(
        slice_value if slice_mode else (getattr(args, "wait_seconds", 0) or 0)
    )
    hard_wait_seconds = float(
        getattr(args, "hard_wait_seconds", 1200) or 1200
    )
    poll_interval = float(getattr(args, "poll_interval", 0.5) or 0.5)
    if wait_seconds < 0 or wait_seconds > 1200:
        raise SystemExit("槽位等待切片必须在 0–1200 秒之间")
    if hard_wait_seconds < 1 or hard_wait_seconds > 1200:
        raise SystemExit("--hard-wait-seconds 必须在 1–1200 秒之间")
    if slice_mode and wait_seconds > 25:
        raise SystemExit("--slice-seconds 必须在 0–25 秒之间，避免产生后台 exec session")
    if poll_interval < 0.2 or poll_interval > 5:
        raise SystemExit("--poll-interval 必须在 0.2–5 秒之间")
    state = read_json(state_path)
    task = fast8_jit_imagegen_task_context(
        state_path, state, ticket_path, require_active=True
    )
    active_item = next(
        (
            item
            for item in ((state.get("scheduler") or {}).get("active_actions") or [])
            if isinstance(item, dict)
            and item.get("style") == task["style"]
            and str(item.get("page_id")) == task["page_id"]
            and item.get("action") == task["action"]
            and int(item.get("attempt") or 1) == task["attempt"]
        ),
        None,
    )
    ticket = read_json(ticket_path)
    receipt_value = ticket.get("worker_receipt_path")
    receipt_path = (
        Path(receipt_value).expanduser().resolve()
        if isinstance(receipt_value, str) and receipt_value
        else None
    )
    existing_artifact, _existing_tool_id = (
        fast8_worker_session_artifact(active_item)
        if isinstance(active_item, dict)
        else (None, None)
    )
    if (receipt_path is not None and receipt_path.is_file()) or existing_artifact:
        print(
            json.dumps(
                {
                    "status": "imagegen_result_already_exists",
                    "worker_session_id": task["worker_session_id"],
                    "receipt_path": (
                        str(receipt_path)
                        if receipt_path is not None and receipt_path.is_file()
                        else None
                    ),
                    "artifact_path": (
                        str(existing_artifact) if existing_artifact else None
                    ),
                },
                ensure_ascii=False,
            )
        )
        return
    telemetry_path = fast8_imagegen_slot_telemetry_path(state_path, state, task)
    existing_telemetry = (
        read_json(telemetry_path) if telemetry_path.is_file() else {}
    )
    if existing_telemetry.get("rpc_terminal") is True:
        print(
            json.dumps(
                {
                    "status": "imagegen_attempt_already_terminal",
                    "worker_session_id": task["worker_session_id"],
                    "telemetry_path": str(telemetry_path),
                },
                ensure_ascii=False,
            )
        )
        return
    now = now_iso()
    requested_at = (
        existing_telemetry.get("requested_at")
        if slice_mode and isinstance(existing_telemetry.get("requested_at"), str)
        else now
    )
    elapsed_before = health_duration_seconds(requested_at, now) or 0.0
    if slice_mode:
        remaining_hard_wait = max(0.0, hard_wait_seconds - elapsed_before)
        wait_seconds = min(wait_seconds, remaining_hard_wait)
    jit_capacity = int(
        os.environ.get(
            "SHAWN_PPT_IMAGE_GLOBAL_SLOT_LIMIT",
            FAST8_JIT_STABLE_IMAGEGEN_SLOT_LIMIT,
        )
    )
    if jit_capacity < 1 or jit_capacity > FAST8_GLOBAL_IMAGEGEN_SLOT_LIMIT:
        raise SystemExit(
            "SHAWN_PPT_IMAGE_GLOBAL_SLOT_LIMIT 必须在 1–8 之间"
        )
    started = time.monotonic()
    deadline = started + wait_seconds
    while True:
        state = read_json(state_path)
        task = fast8_jit_imagegen_task_context(
            state_path, state, ticket_path, require_active=True
        )
        timestamp = now_iso()
        acquired, deferred, lease_ids, remaining = acquire_fast8_global_imagegen_slots(
            state_path,
            state,
            [task],
            timestamp=timestamp,
            capacity_limit=jit_capacity,
        )
        if acquired:
            task_key = (
                f"{task['style']}/{task['page_id']}/{task['action']}/"
                f"{task['attempt']}"
            )
            slice_waited = time.monotonic() - started
            waited_seconds = round(elapsed_before + slice_waited, 3)
            acquired_at = (
                existing_telemetry.get("acquired_at")
                if isinstance(existing_telemetry.get("acquired_at"), str)
                else timestamp
            )
            telemetry_path = write_fast8_imagegen_slot_telemetry(
                state_path,
                state,
                task,
                {
                    "status": "acquired",
                    "requested_at": requested_at,
                    "acquired_at": acquired_at,
                    "wait_seconds": waited_seconds,
                    "lease_id": lease_ids[task_key],
                    "observed_global_cap": jit_capacity,
                    "global_imagegen_available_slots_after_acquire": remaining,
                },
            )
            print(
                json.dumps(
                    {
                        "status": "acquired",
                        "lease_id": lease_ids[task_key],
                        "lease_kind": "imagegen_inflight",
                        "worker_session_id": task["worker_session_id"],
                        "waited_seconds": waited_seconds,
                        "global_imagegen_available_slots": remaining,
                        "acquired_at": acquired_at,
                        "telemetry_path": str(telemetry_path),
                    },
                    ensure_ascii=False,
                )
            )
            return
        if not deferred or time.monotonic() >= deadline:
            slice_waited = time.monotonic() - started
            waited_seconds = round(elapsed_before + slice_waited, 3)
            total_timed_out = (not slice_mode) or waited_seconds >= hard_wait_seconds
            status = "slot_wait_timeout" if total_timed_out else "slot_waiting"
            telemetry_path = write_fast8_imagegen_slot_telemetry(
                state_path,
                state,
                task,
                {
                    "status": status,
                    "requested_at": requested_at,
                    "wait_finished_at": now_iso(),
                    "wait_seconds": waited_seconds,
                    "observed_global_cap": jit_capacity,
                },
            )
            print(
                json.dumps(
                    {
                        "status": status,
                        "lease_kind": "imagegen_inflight",
                        "worker_session_id": task["worker_session_id"],
                        "waited_seconds": waited_seconds,
                        "retry_after_seconds": max(1, round(poll_interval)),
                        "hard_wait_seconds": hard_wait_seconds,
                        "telemetry_path": str(telemetry_path),
                    },
                    ensure_ascii=False,
                )
            )
            return
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


def command_release_fast8_imagegen_slot(args: argparse.Namespace) -> None:
    """Idempotently release one session-bound slot after the ImageGen call."""

    state_path = Path(args.state).expanduser().resolve()
    ticket_path = Path(args.ticket).expanduser().resolve()
    state = read_json(state_path)
    task = fast8_jit_imagegen_task_context(
        state_path, state, ticket_path, require_active=False
    )
    expected_lease_id = fast8_global_imagegen_lease_key(state_path, state, task)
    lease_id = str(args.lease_id)
    if lease_id != expected_lease_id:
        raise SystemExit("Fast8 JIT ImageGen lease_id 与 ticket/session 不一致")
    released = release_fast8_global_imagegen_slots(
        state_path, state, [lease_id]
    )
    released_at = now_iso()
    telemetry_path = fast8_imagegen_slot_telemetry_path(state_path, state, task)
    telemetry = read_json(telemetry_path) if telemetry_path.is_file() else {}
    if telemetry.get("rpc_terminal") is True:
        print(
            json.dumps(
                {
                    "status": "already_released",
                    "lease_id": lease_id,
                    "telemetry_path": str(telemetry_path),
                    "released": 0,
                    "released_at": telemetry.get("released_at"),
                },
                ensure_ascii=False,
            )
        )
        return
    acquired_at = telemetry.get("acquired_at")
    rpc_seconds = health_duration_seconds(acquired_at, released_at)
    telemetry_path = write_fast8_imagegen_slot_telemetry(
        state_path,
        state,
        task,
        {
            "status": "released" if released else "already_released",
            "released_at": released_at,
            "imagegen_rpc_seconds": (
                round(rpc_seconds, 3)
                if isinstance(rpc_seconds, (int, float)) and rpc_seconds >= 0
                else None
            ),
            "lease_id": lease_id,
            "rpc_terminal": True,
        },
    )
    print(
        json.dumps(
            {
                "status": "released" if released else "already_released",
                "lease_id": lease_id,
                "telemetry_path": str(telemetry_path),
                "released": released,
                "released_at": now_iso(),
            },
            ensure_ascii=False,
        )
    )


def terminalize_blocked_run_state(
    state: dict[str, Any],
    *,
    timestamp: str,
    reason: str,
    blocked_tasks: list[dict[str, Any]],
) -> list[str]:
    """Stop one uncompletable run and return every recorded lease to release."""

    scheduler = state.setdefault("scheduler", {})
    active = [item for item in scheduler.get("active_actions") or [] if isinstance(item, dict)]
    ready = [item for item in scheduler.get("ready_queue") or [] if isinstance(item, dict)]
    recovery = [
        item for item in scheduler.get("recovery_queue") or [] if isinstance(item, dict)
    ]
    cancelled = []
    for item in active + ready + recovery:
        cancelled.append(
            {
                "style": item.get("style"),
                "page_id": str(item.get("page_id")),
                "action": item.get("action"),
                "attempt": int(item.get("attempt") or 1),
                "worker_task_name": item.get("worker_agent_id"),
                "worker_session_id": item.get("worker_session_id"),
            }
        )
    lease_ids = [
        str(item.get("global_imagegen_lease_id"))
        for item in active
        if isinstance(item.get("global_imagegen_lease_id"), str)
    ]
    scheduler["active_actions"] = []
    scheduler["ready_queue"] = []
    scheduler["recovery_queue"] = []
    scheduler["phase"] = "terminal"
    scheduler["terminal_outcome"] = "blocked"
    scheduler["terminal_reason"] = reason
    scheduler["terminalized_at"] = timestamp
    scheduler["cancelled_after_terminal"] = cancelled
    state["status"] = "blocked"
    state["terminal_outcome"] = "blocked"
    state["terminal_reason"] = reason
    state.setdefault("timing", {})["terminal_at"] = timestamp
    append_event(
        state,
        "run_terminalized",
        timestamp,
        details={
            "outcome": "blocked",
            "reason": reason,
            "blocked_tasks": blocked_tasks,
            "blocked_styles": sorted(
                {
                    str(item.get("style"))
                    for item in blocked_tasks
                    if item.get("style") is not None
                }
            ),
            "cancelled_task_count": len(cancelled),
            "automatic_full_rerun_allowed": False,
        },
    )
    return lease_ids


def terminalize_blocked_fast8_state(
    state: dict[str, Any], *, timestamp: str, blocked_styles: list[str]
) -> list[str]:
    """Compatibility wrapper for the existing Fast8 blocked-seat contract."""

    blocked_tasks = [
        {
            "style": style,
            "page_id": str(state.get("anchor_page_id")),
            "reason": "required_fast8_seat_exhausted",
        }
        for style in sorted(set(blocked_styles))
    ]
    return terminalize_blocked_run_state(
        state,
        timestamp=timestamp,
        reason="required_fast8_seat_exhausted",
        blocked_tasks=blocked_tasks,
    )


def build_run_health_report(
    *,
    state_path: Path,
    state: dict[str, Any],
    timestamp: str | None = None,
    run_outcome: str | None = None,
    outcome_reason: str | None = None,
) -> dict[str, Any]:
    """Build a non-visual, read-only technical report from formal run evidence."""

    state_path = state_path.expanduser().resolve()
    project_dir = project_dir_for_state(state_path, state)
    generated_at = timestamp or now_iso()
    completed = state.get("status") == "completed"
    allowed_terminal_outcomes = {"superseded", "aborted", "blocked"}
    if completed:
        if run_outcome not in {None, "completed"}:
            raise SystemExit("completed 运行的 run_outcome 只能是 completed")
        normalized_outcome = "completed"
        record_kind = "completed_run"
    elif run_outcome in allowed_terminal_outcomes:
        if not isinstance(outcome_reason, str) or not outcome_reason.strip():
            raise SystemExit("终止运行进入中央索引前必须提供 outcome_reason")
        normalized_outcome = str(run_outcome)
        record_kind = "terminal_incomplete_run"
    elif run_outcome in {None, "diagnostic_snapshot"}:
        normalized_outcome = "diagnostic_snapshot"
        record_kind = "diagnostic_snapshot"
    else:
        raise SystemExit(
            "未完成运行的 run_outcome 只能是 superseded、aborted、blocked 或 diagnostic_snapshot"
        )
    terminal_incomplete = record_kind == "terminal_incomplete_run"
    completion_severity = "warning" if terminal_incomplete else "error"
    findings: list[dict[str, Any]] = []

    def finding(
        code: str,
        severity: str,
        stage: str,
        summary: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        findings.append(
            {
                "code": code,
                "severity": severity,
                "stage": stage,
                "summary": summary,
                "evidence": evidence or {},
            }
        )

    records = health_page_records(state)
    candidate_paths: dict[str, str] = {}
    candidate_hashes: dict[str, list[str]] = {}
    tool_ids: dict[str, list[str]] = {}
    tool_durations: list[float] = []
    validation_delays: list[float] = []
    agent_tails: list[float] = []
    imagegen_slot_waits: list[float] = []
    imagegen_rpc_durations: list[float] = []
    imagegen_slot_intervals: list[tuple[datetime, datetime]] = []
    imagegen_slot_caps: list[int] = []
    timing_capture_counts: dict[str, int] = {}
    total_attempts = 0
    technical_retry_count = 0
    settled_records_without_worker_id = 0
    for style, page_id, record in records:
        label = f"style_{style}/{page_id}" if style else page_id
        attempts = int(record.get("attempt_count") or 0)
        total_attempts += attempts
        technical_retry_count += int(record.get("technical_retry_count") or 0)
        if attempts and not record.get("worker_agent_id"):
            settled_records_without_worker_id += 1
        capture = record.get("timing_capture")
        if isinstance(capture, str) and capture:
            timing_capture_counts[capture] = timing_capture_counts.get(capture, 0) + 1
        if terminal_incomplete and attempts == 0:
            continue
        final_path_value = record.get("final_path")
        if not isinstance(final_path_value, str) or not final_path_value:
            finding(
                "candidate_final_path_missing",
                completion_severity,
                "artifact",
                f"{label} 缺少正式候选路径",
            )
        else:
            final_path = Path(final_path_value).expanduser()
            if not final_path.is_absolute() or not final_path.is_file():
                finding(
                    "candidate_artifact_unreadable",
                    "error",
                    "artifact",
                    f"{label} 的正式候选不可读",
                    {"path": str(final_path)},
                )
            else:
                resolved = str(final_path.resolve())
                if resolved in candidate_paths:
                    finding(
                        "duplicate_candidate_path",
                        "error",
                        "artifact",
                        f"{label} 与 {candidate_paths[resolved]} 绑定同一正式文件",
                        {"path": resolved},
                    )
                candidate_paths[resolved] = label
                digest = file_sha256(final_path)
                candidate_hashes.setdefault(digest, []).append(label)
                expected_digest = record.get("source_sha256")
                if isinstance(expected_digest, str) and expected_digest and digest != expected_digest:
                    finding(
                        "candidate_hash_mismatch",
                        "error",
                        "artifact",
                        f"{label} 的正式文件与已登记来源哈希不一致",
                        {"path": resolved},
                    )
        tool_call_id = record.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            tool_ids.setdefault(tool_call_id, []).append(label)
        else:
            finding(
                "tool_call_id_missing",
                "warning",
                "artifact",
                f"{label} 缺少图片工具调用 ID",
            )
        tool_duration = health_duration_seconds(
            record.get("tool_started_at"), record.get("tool_finished_at")
        )
        if tool_duration is not None:
            if tool_duration < 0:
                finding(
                    "negative_tool_duration",
                    "error",
                    "timing",
                    f"{label} 的图片工具结束时间早于开始时间",
                )
            else:
                tool_durations.append(tool_duration)
        validation_delay = health_duration_seconds(
            record.get("tool_finished_at"), record.get("file_validated_at")
        )
        if validation_delay is not None and validation_delay >= 0:
            validation_delays.append(validation_delay)
        agent_tail = health_duration_seconds(
            record.get("tool_finished_at"), record.get("agent_action_finished_at")
        )
        if agent_tail is not None and agent_tail >= 0:
            agent_tails.append(agent_tail)

    slot_sidecars = sorted(
        (project_dir / "style_jobs" / "results").glob("imagegen_slot_*.json")
    )
    for sidecar_path in slot_sidecars:
        try:
            slot_record = read_json(sidecar_path)
        except SystemExit as exc:
            finding(
                "imagegen_slot_telemetry_unreadable",
                "warning",
                "timing",
                "ImageGen 槽位遥测无法解析",
                {"path": str(sidecar_path), "error": str(exc)},
            )
            continue
        wait_seconds = slot_record.get("wait_seconds")
        if isinstance(wait_seconds, (int, float)) and wait_seconds >= 0:
            imagegen_slot_waits.append(float(wait_seconds))
            if wait_seconds > 360:
                finding(
                    "imagegen_slot_wait_over_soft_threshold",
                    "warning",
                    "timing",
                    "ImageGen 槽位等待超过 6 分钟软阈值",
                    {
                        "style": slot_record.get("style"),
                        "wait_seconds": wait_seconds,
                    },
                )
        rpc_seconds = slot_record.get("imagegen_rpc_seconds")
        if isinstance(rpc_seconds, (int, float)) and rpc_seconds >= 0:
            imagegen_rpc_durations.append(float(rpc_seconds))
        cap = slot_record.get("observed_global_cap")
        if isinstance(cap, int) and cap > 0:
            imagegen_slot_caps.append(cap)
        if slot_record.get("status") == "slot_wait_timeout":
            finding(
                "imagegen_slot_wait_timeout",
                "warning",
                "timing",
                "ImageGen 槽位达到硬等待上限，候选仍应保留为可恢复状态",
                {
                    "style": slot_record.get("style"),
                    "wait_seconds": slot_record.get("wait_seconds"),
                },
            )
        acquired_at = slot_record.get("acquired_at")
        released_at = slot_record.get("released_at")
        if isinstance(acquired_at, str) and isinstance(released_at, str):
            try:
                acquired_time = parse_time(acquired_at)
                released_time = parse_time(released_at)
            except (TypeError, ValueError):
                continue
            if released_time >= acquired_time:
                imagegen_slot_intervals.append((acquired_time, released_time))

    imagegen_peak_inflight = 0
    imagegen_current_inflight = 0
    interval_events: list[tuple[datetime, int]] = []
    for acquired_time, released_time in imagegen_slot_intervals:
        interval_events.append((acquired_time, 1))
        interval_events.append((released_time, -1))
    # Release before acquire at an identical timestamp to avoid a false peak.
    for _event_time, delta in sorted(interval_events, key=lambda item: (item[0], item[1])):
        imagegen_current_inflight += delta
        imagegen_peak_inflight = max(
            imagegen_peak_inflight, imagegen_current_inflight
        )

    for digest, labels in candidate_hashes.items():
        if len(labels) > 1:
            finding(
                "duplicate_candidate_bytes",
                "error",
                "artifact",
                "多个候选的正式文件字节完全相同",
                {"sha256": digest, "candidates": labels},
            )
    for tool_call_id, labels in tool_ids.items():
        if len(labels) > 1:
            finding(
                "duplicate_tool_call_binding",
                "error",
                "artifact",
                "同一图片工具调用被绑定到多个候选",
                {"tool_call_id": tool_call_id, "candidates": labels},
            )

    jobs = health_generation_job_paths(project_dir)
    prompt_lengths: list[int] = []
    prompt_fingerprints: dict[str, list[str]] = {}
    prompt_duplicate_block_count = 0
    style_reference_job_count = 0
    referenced_path_count = 0
    for job_path in jobs:
        try:
            job = read_json(job_path)
        except SystemExit as exc:
            finding(
                "generation_job_unreadable",
                "error",
                "prompt",
                "生成任务无法解析",
                {"path": str(job_path), "error": str(exc)},
            )
            continue
        prompt = job.get("imagegen_prompt")
        if not isinstance(prompt, str) or not prompt:
            finding(
                "imagegen_prompt_missing",
                "error",
                "prompt",
                "生成任务缺少预编译图片提示",
                {"path": str(job_path)},
            )
            continue
        prompt_lengths.append(len(prompt))
        fingerprint = job.get("imagegen_prompt_fingerprint")
        actual_fingerprint = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if fingerprint is None and state.get("run_mode") == FAST8_MODE:
            finding(
                "prompt_fingerprint_missing",
                "error",
                "prompt",
                "Fast8 生成任务缺少独立图片提示指纹",
                {"path": str(job_path)},
            )
        elif fingerprint is not None and fingerprint != actual_fingerprint:
            finding(
                "prompt_fingerprint_mismatch",
                "error",
                "prompt",
                "图片提示指纹与实际文本不一致",
                {"path": str(job_path)},
            )
        prompt_fingerprints.setdefault(actual_fingerprint, []).append(str(job_path))
        blocks = normalized_prompt_blocks(prompt)
        duplicate_blocks = len(blocks) - len(set(blocks))
        if duplicate_blocks > 0:
            prompt_duplicate_block_count += duplicate_blocks
            finding(
                "duplicate_prompt_block",
                "warning",
                "prompt",
                "同一图片提示内存在完全重复的长段落",
                {"path": str(job_path), "duplicate_block_count": duplicate_blocks},
            )
        references = job.get("reference_images") or []
        if references:
            style_reference_job_count += 1
        if state.get("run_mode") == FAST8_MODE:
            receipt_contract = job.get("worker_receipt") or {}
            if receipt_contract.get("required") is True:
                receipt_value = receipt_contract.get("path")
                receipt_path = (
                    Path(receipt_value).expanduser()
                    if isinstance(receipt_value, str) and receipt_value
                    else None
                )
                if receipt_path is None or not receipt_path.is_file():
                    finding(
                        "worker_receipt_missing",
                        "info",
                        "artifact",
                        "Fast8 机器回执未落盘；候选已由绑定 session 的唯一 PNG 确认",
                        {"job": str(job_path), "receipt_path": receipt_value},
                    )
                else:
                    try:
                        receipt = read_json(receipt_path)
                    except SystemExit as exc:
                        finding(
                            "worker_receipt_unreadable",
                            "warning",
                            "artifact",
                            "Fast8 同次调用机器回执无法解析",
                            {"job": str(job_path), "error": str(exc)},
                        )
                    else:
                        normalized_receipt = normalize_fast8_artifact_fields(receipt)
                        normalized_saved_path = normalized_receipt.get("savedPath")
                        normalized_error = normalized_receipt.get("error")
                        success_receipt = bool(
                            normalized_error in {None, ""}
                            and isinstance(normalized_saved_path, str)
                            and Path(normalized_saved_path).is_file()
                        )
                        unresolved_receipt = bool(
                            normalized_error == "artifact_handoff_unresolved"
                            and normalized_saved_path in {None, ""}
                        )
                        backend_failure_receipt = bool(
                            normalized_error == "imagegen_backend_failed"
                            and normalized_saved_path in {None, ""}
                            and receipt.get("tool_status") == "failed"
                            and receipt.get("failure_class")
                            in {"backend_network", "backend_failed"}
                        )
                        if (
                            receipt.get("worker_receipt_contract_version")
                            != FAST8_WORKER_RECEIPT_CONTRACT_VERSION
                            or receipt.get("contains_image_payload") is not False
                            or not (
                                success_receipt
                                or unresolved_receipt
                                or backend_failure_receipt
                            )
                        ):
                            finding(
                                "worker_receipt_invalid",
                                "warning",
                                "artifact",
                                "Fast8 同次调用机器回执缺少有效路径/失败分类或违反轻量合同",
                                {"job": str(job_path), "receipt_path": str(receipt_path)},
                            )
            for item in references:
                role = item.get("role") if isinstance(item, dict) else None
                if role not in FAST8_STYLE_REFERENCE_ROLES:
                    finding(
                        "invalid_fast8_style_reference_role",
                        "error",
                        "reference_routing",
                        "Fast8 风格参考槽包含不允许的角色",
                        {"path": str(job_path), "role": role},
                    )
            if job.get("imagegen_prompt_contract_version") == CURRENT_FAST8_IMAGEGEN_PROMPT_VERSION:
                projection = job.get("creative_brief_projection") or {}
                required_projection = {
                    "relationship_thesis",
                    "visual_quality_intent",
                    "literal_anchors",
                    "flexible_story",
                    "visual_thesis",
                    "craft_axis",
                    "visual_activity_mode",
                    "attention_strategy",
                }
                if (state.get("fast8_candidate_policy") or {}).get(
                    "relationship_representation_family_required"
                ) is True:
                    required_projection.add("relationship_representation_family")
                missing_projection = sorted(
                    key for key in required_projection if not projection.get(key)
                )
                if missing_projection:
                    finding(
                        "creative_brief_projection_incomplete",
                        "error",
                        "prompt",
                        "Fast8 页面导演中间产物未完整进入正式任务",
                        {"path": str(job_path), "missing": missing_projection},
                    )
        referenced_paths = job.get("imagegen_referenced_paths") or []
        if not isinstance(referenced_paths, list):
            referenced_paths = []
            finding(
                "referenced_paths_not_list",
                "error",
                "reference_routing",
                "imagegen_referenced_paths 不是数组",
                {"path": str(job_path)},
            )
        referenced_path_count += len(referenced_paths)
        if len(referenced_paths) > 5:
            finding(
                "too_many_image_inputs",
                "error",
                "reference_routing",
                "单个图片任务传入超过 5 个图片路径",
                {"path": str(job_path), "count": len(referenced_paths)},
            )
        if len(referenced_paths) != len(set(referenced_paths)):
            finding(
                "duplicate_image_input_path",
                "error",
                "reference_routing",
                "同一图片任务重复传入相同图片路径",
                {"path": str(job_path)},
            )
        for value in referenced_paths:
            path = Path(str(value)).expanduser()
            if not path.is_absolute() or not path.is_file():
                finding(
                    "image_input_unreadable",
                    "error",
                    "reference_routing",
                    "图片任务的参考或资产路径不可读",
                    {"job": str(job_path), "path": str(path)},
                )
        manifest = job.get("imagegen_input_manifest") or []
        manifest_paths = [
            item.get("path") for item in manifest if isinstance(item, dict)
        ]
        if manifest_paths != referenced_paths:
            finding(
                "image_input_manifest_mismatch",
                "error",
                "reference_routing",
                "图片输入清单与正式引用路径不一致",
                {"path": str(job_path)},
            )

    if state.get("run_mode") == FAST8_MODE:
        for fingerprint, paths in prompt_fingerprints.items():
            if len(paths) > 1:
                finding(
                    "duplicate_fast8_prompt_fingerprint",
                    "error",
                    "prompt",
                    "Fast8 多个席位得到完全相同的图片提示",
                    {"fingerprint": fingerprint, "jobs": paths},
                )

    events = [item for item in (state.get("events") or []) if isinstance(item, dict)]
    event_counts: dict[str, int] = {}
    dispatch_authorized_count = 0
    for event in events:
        name = str(event.get("name") or "unknown")
        event_counts[name] = event_counts.get(name, 0) + 1
        if name == "dispatch_wave":
            details = event.get("details") or {}
            started_tasks = details.get("started_tasks") or []
            if isinstance(started_tasks, list):
                dispatch_authorized_count += sum(
                    1 for item in started_tasks if isinstance(item, dict)
                )
    expected_sequences = list(range(1, len(events) + 1))
    actual_sequences = [event.get("sequence") for event in events]
    if actual_sequences != expected_sequences:
        finding(
            "event_sequence_gap",
            completion_severity,
            "state",
            "运行事件 sequence 不连续或顺序异常",
        )

    active_authorizations = [
        item
        for item in ((state.get("scheduler") or {}).get("active_actions") or [])
        if isinstance(item, dict)
    ]
    if terminal_incomplete and active_authorizations:
        finding(
            "dispatch_authorization_unsettled",
            "warning",
            "dispatch",
            "终止批次仍有已授权但未结算的图片动作；授权记录不应解读为全部 Worker 已真实启动",
            {
                "authorized_but_unsettled_count": len(active_authorizations),
                "semantics": "authorization_not_worker_start_proof",
            },
        )
    if settled_records_without_worker_id:
        finding(
            "settled_worker_identity_missing",
            "warning",
            "dispatch",
            "部分已结算图片动作缺少 Worker 身份，无法独立证明真实启动者",
            {"count": settled_records_without_worker_id},
        )
    if terminal_incomplete:
        finding(
            "terminal_incomplete_run",
            "warning",
            "state",
            f"运行已明确终止为 {normalized_outcome}，并作为真实任务记录进入中央索引",
            {"outcome_reason": outcome_reason.strip()},
        )

    recovery_count = event_counts.get("artifact_recovery_started", 0)
    fallback_count = sum(
        count
        for name, count in timing_capture_counts.items()
        if name.startswith("controller_")
    )
    if recovery_count:
        finding(
            "artifact_recovery_used",
            "warning",
            "artifact",
            "本次运行使用了无生图产物恢复",
            {"recovery_started_count": recovery_count},
        )
    if fallback_count:
        finding(
            "controller_timing_fallback_used",
            "info",
            "timing",
            "部分图片由控制器边界补齐遥测；不影响候选绑定与交付",
            {"count": fallback_count, "captures": timing_capture_counts},
        )

    timing = state.get("timing") or {}
    scheduler = state.get("scheduler") or {}
    diversity_reports = [
        item
        for item in ((state.get("diversity_review") or {}).get("reports") or [])
        if isinstance(item, dict) and isinstance(item.get("applied_at"), str)
    ]
    final_initial_report = next(
        (
            item
            for item in diversity_reports
            if item.get("review_kind") == "final_initial"
        ),
        None,
    )
    diversity_closed_at = (
        diversity_reports[-1].get("applied_at") if diversity_reports else None
    )
    package_completed_at = timing.get("task_package_completed_at")
    initial_dispatch_at = timing.get("initial_anchor_dispatch_at")
    package_to_dispatch = health_duration_seconds(
        package_completed_at,
        initial_dispatch_at,
    )
    capacity_wait_started_at: str | None = None
    if isinstance(package_completed_at, str) and isinstance(initial_dispatch_at, str):
        try:
            package_dt = parse_time(package_completed_at)
            dispatch_dt = parse_time(initial_dispatch_at)
        except (TypeError, ValueError):
            package_dt = None
            dispatch_dt = None
        if package_dt is not None and dispatch_dt is not None:
            eligible_backpressure = []
            for row in scheduler.get("runtime_backpressure") or []:
                if not isinstance(row, dict):
                    continue
                if row.get("reason") != "global_imagegen_capacity":
                    continue
                if int(row.get("started") or 0) != 0:
                    continue
                occurred_at = row.get("occurred_at")
                if not isinstance(occurred_at, str):
                    continue
                try:
                    occurred_dt = parse_time(occurred_at)
                except (TypeError, ValueError):
                    continue
                if package_dt <= occurred_dt < dispatch_dt:
                    eligible_backpressure.append((occurred_dt, occurred_at))
            if eligible_backpressure:
                capacity_wait_started_at = min(eligible_backpressure)[1]
    pre_dispatch_capacity_wait = health_duration_seconds(
        capacity_wait_started_at,
        initial_dispatch_at,
    )
    active_dispatch_preparation = None
    if package_to_dispatch is not None:
        active_dispatch_preparation = max(
            0.0,
            package_to_dispatch - float(pre_dispatch_capacity_wait or 0.0),
        )

    worker_binding_after_tool: list[dict[str, Any]] = []
    page_record_by_task: dict[tuple[str, str, int], dict[str, Any]] = {}
    for style, page_id, record in records:
        if style is None:
            continue
        selected_attempt = int(
            record.get("selected_attempt") or record.get("attempt_count") or 1
        )
        page_record_by_task[(style, page_id, selected_attempt)] = record
    for binding in scheduler.get("worker_session_bindings") or []:
        if not isinstance(binding, dict):
            continue
        bound_at = binding.get("bound_at")
        for task in binding.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            key = (
                str(task.get("style")),
                str(task.get("page_id")),
                int(task.get("attempt") or 1),
            )
            record = page_record_by_task.get(key)
            if not isinstance(record, dict):
                continue
            if str(record.get("timing_capture") or "").startswith("controller_"):
                continue
            delay = health_duration_seconds(record.get("tool_started_at"), bound_at)
            if delay is not None and delay > 0:
                worker_binding_after_tool.append(
                    {
                        "style": key[0],
                        "page_id": key[1],
                        "attempt": key[2],
                        "seconds": round(delay, 3),
                    }
                )

    observed_tool_finishes = [
        record.get("tool_finished_at")
        for _style, _page_id, record in records
        if isinstance(record.get("tool_finished_at"), str)
    ]
    try:
        observed_last_tool_finished_at = max(
            observed_tool_finishes, key=parse_time
        )
    except (TypeError, ValueError):
        observed_last_tool_finished_at = timing.get(
            "all_anchor_tools_completed_at"
        )

    stage_durations = {
        "end_to_end_to_process_completed": health_duration_seconds(
            timing.get("request_started_at") or timing.get("process_started_at"),
            timing.get("process_completed_at"),
        ),
        "preflight_before_process": health_duration_seconds(
            timing.get("request_started_at"), timing.get("process_started_at")
        ),
        "process_total": health_duration_seconds(
            timing.get("process_started_at"), timing.get("process_completed_at")
        ),
        "process_to_package": health_duration_seconds(
            timing.get("process_started_at"),
            timing.get("task_package_completed_at")
            or timing.get("style_jobs_created_at"),
        ),
        "package_to_dispatch": package_to_dispatch,
        "active_dispatch_preparation": active_dispatch_preparation,
        "pre_dispatch_capacity_wait": pre_dispatch_capacity_wait,
        "dispatch_to_first_worker_batch_bound": health_duration_seconds(
            timing.get("initial_anchor_dispatch_at"),
            timing.get("first_worker_batch_bound_at"),
        ),
        "worker_batch_bind_window": health_duration_seconds(
            timing.get("first_worker_batch_bound_at"),
            timing.get("last_worker_batch_bound_at"),
        ),
        "dispatch_to_overview": health_duration_seconds(
            timing.get("initial_anchor_dispatch_at"),
            timing.get("formal_overview_completed_at"),
        ),
        "tools_complete_to_overview": health_duration_seconds(
            observed_last_tool_finished_at,
            timing.get("formal_overview_completed_at"),
        ),
        "overview_to_complete": health_duration_seconds(
            timing.get("formal_overview_completed_at"),
            timing.get("process_completed_at"),
        ),
        "initial_tools_to_final_initial_judge": health_duration_seconds(
            observed_last_tool_finished_at,
            (final_initial_report or {}).get("applied_at"),
        ),
        "final_initial_judge_to_diversity_close": health_duration_seconds(
            (final_initial_report or {}).get("applied_at"),
            diversity_closed_at,
        ),
        "diversity_close_to_overview": health_duration_seconds(
            diversity_closed_at,
            timing.get("formal_overview_completed_at"),
        ),
    }
    if (state.get("timing_target") or {}).get("soft_target_missed") is True:
        timing_target = state.get("timing_target") or {}
        finding(
            "soft_timing_target_missed",
            "warning",
            "timing",
            f"Fast8 未达到 {timing_target.get('target_minutes') or 15} 分钟软目标",
            {
                "elapsed_minutes": timing_target.get("elapsed_minutes"),
                "scope": timing_target.get("scope"),
            },
        )
    if (stage_durations.get("active_dispatch_preparation") or 0) > 120:
        finding(
            "dispatch_preparation_delay",
            "warning",
            "timing",
            "扣除已确认的全局 ImageGen 容量等待后，任务包完成到首轮派发仍超过 2 分钟",
            {
                "package_to_dispatch_seconds": round(
                    float(stage_durations["package_to_dispatch"]), 3
                ),
                "pre_dispatch_capacity_wait_seconds": round(
                    float(stage_durations["pre_dispatch_capacity_wait"] or 0), 3
                ),
                "active_preparation_seconds": round(
                    float(stage_durations["active_dispatch_preparation"]), 3
                ),
            },
        )
    if worker_binding_after_tool:
        finding(
            "worker_session_bound_after_tool_start",
            "warning",
            "dispatch",
            "部分 Fast8 Worker 在真实 session 绑定完成前已经开始图片工具调用",
            {
                "count": len(worker_binding_after_tool),
                "max_seconds": max(item["seconds"] for item in worker_binding_after_tool),
                "tasks": worker_binding_after_tool,
            },
        )
    validation_summary = health_summary(validation_delays)
    if (validation_summary.get("max_seconds") or 0) > 180:
        finding(
            "artifact_validation_delay",
            "warning",
            "timing",
            "至少一个图片工具完成后超过 3 分钟才完成文件绑定或校验",
            {"max_seconds": validation_summary.get("max_seconds")},
        )
    agent_tail_summary = health_summary(agent_tails)
    if (agent_tail_summary.get("max_seconds") or 0) > 180:
        finding(
            "agent_tail_after_tool",
            "warning",
            "timing",
            "至少一个 Agent 在图片工具完成后仍长时间占用回合",
            {"max_seconds": agent_tail_summary.get("max_seconds")},
        )
    if (stage_durations.get("tools_complete_to_overview") or 0) > 600:
        replacement_count = int(
            (state.get("diversity_review") or {}).get("replacement_count") or 0
        )
        if replacement_count == 0:
            finding(
                "post_generation_long_tail",
                "warning",
                "timing",
                "初始图片工具完成后超过 10 分钟才生成正式总览，且没有差异替代可解释该跨度",
                {
                    "seconds": round(
                        float(stage_durations["tools_complete_to_overview"]), 3
                    )
                },
            )
        elif (stage_durations.get("diversity_close_to_overview") or 0) > 180:
            finding(
                "post_review_overview_delay",
                "warning",
                "timing",
                "差异 Judge 与替代复核收口后超过 3 分钟才生成正式总览",
                {
                    "seconds": round(
                        float(stage_durations["diversity_close_to_overview"]), 3
                    ),
                    "replacement_count": replacement_count,
                },
            )

    nonempty_queues = [
        name
        for name in ("active_actions", "ready_queue", "recovery_queue")
        if scheduler.get(name)
    ]
    if nonempty_queues:
        finding(
            "scheduler_not_closed",
            completion_severity,
            "state",
            (
                "终止快照仍保留未结算的调度队列"
                if terminal_incomplete
                else "完成态仍存在未清空的调度队列"
            ),
            {"queues": nonempty_queues},
        )
    if state.get("status") != "completed":
        finding(
            "run_not_completed",
            completion_severity,
            "state",
            (
                "正式运行未达到 completed；监测层以明确终止结果记录本次真实任务"
                if terminal_incomplete
                else "运行尚未达到 completed，报告只代表当前快照"
            ),
            {"status": state.get("status")},
        )

    overview_value = ((state.get("overview") or {}).get("final_path"))
    overview_path = Path(str(overview_value)).expanduser() if overview_value else None
    if overview_path is None or not overview_path.is_absolute() or not overview_path.is_file():
        finding(
            "formal_overview_missing",
            completion_severity,
            "artifact",
            "缺少可读的正式总览文件",
            {"path": str(overview_path) if overview_path else None},
        )

    handoff_path = project_dir / "state" / "handoff.json"
    if source_guard_enabled(state_path, state):
        if not handoff_path.is_file():
            finding(
                "formal_handoff_missing",
                completion_severity,
                "handoff",
                (
                    "终止运行没有正式 handoff.json；不得伪造成已交付完成"
                    if terminal_incomplete
                    else "现代运行完成后缺少正式 handoff.json"
                ),
            )
        else:
            try:
                handoff = read_json(handoff_path)
                current_state_sha = file_sha256(state_path)
                if (handoff.get("state_ref") or {}).get("sha256") != current_state_sha:
                    finding(
                        "handoff_state_hash_mismatch",
                        "error",
                        "handoff",
                        "handoff 未绑定当前最终状态哈希",
                    )
            except SystemExit as exc:
                finding(
                    "formal_handoff_unreadable",
                    "error",
                    "handoff",
                    "正式 handoff 无法解析",
                    {"error": str(exc)},
                )

    severity_counts = {"error": 0, "warning": 0}
    for item in findings:
        severity = item.get("severity")
        if severity in severity_counts:
            severity_counts[severity] += 1
    health_status = (
        "defect"
        if severity_counts["error"]
        else "attention"
        if severity_counts["warning"]
        else "healthy"
    )
    prompt_length_summary = {
        "count": len(prompt_lengths),
        "min_chars": min(prompt_lengths) if prompt_lengths else None,
        "max_chars": max(prompt_lengths) if prompt_lengths else None,
        "avg_chars": (
            round(sum(prompt_lengths) / len(prompt_lengths), 3)
            if prompt_lengths
            else None
        ),
    }
    report = {
        "run_health_contract_version": RUN_HEALTH_CONTRACT_VERSION,
        "report_kind": "technical_pipeline_health",
        "scope": "non_visual",
        "blocking": False,
        "generated_at": generated_at,
        "health_status": health_status,
        "review_recommended": bool(findings),
        "run": {
            "run_id": state.get("run_id"),
            "run_mode": state.get("run_mode") or state.get("mode"),
            "project_dir": str(project_dir),
            "page_ids": handoff_page_scope(state),
            "status": state.get("status"),
            "record_kind": record_kind,
            "run_outcome": normalized_outcome,
            "outcome_reason": outcome_reason.strip() if isinstance(outcome_reason, str) else None,
            "terminal_at": generated_at if terminal_incomplete else None,
            "completed_at": timing.get("process_completed_at"),
            "state_path": str(state_path),
            "state_sha256": file_sha256(state_path) if state_path.is_file() else None,
            "overview_path": str(overview_path.resolve()) if overview_path and overview_path.is_file() else None,
            "overview_sha256": file_sha256(overview_path) if overview_path and overview_path.is_file() else None,
            "handoff_path": str(handoff_path.resolve()) if handoff_path.is_file() else None,
        },
        "counts": {
            "page_record_count": len(records),
            "candidate_artifact_count": len(candidate_paths),
            "estimated_imagegen_calls": total_attempts,
            "estimated_extra_imagegen_calls": max(0, total_attempts - len(records)),
            "technical_retry_count": technical_retry_count,
            "recovery_started_count": recovery_count,
            "recovery_finished_count": event_counts.get("artifact_recovery_finished", 0),
            "runtime_backpressure_count": event_counts.get("runtime_backpressure", 0),
            "generation_job_count": len(jobs),
            "style_reference_job_count": style_reference_job_count,
            "referenced_path_count": referenced_path_count,
            "prompt_duplicate_block_count": prompt_duplicate_block_count,
            "dispatch_authorized_count": dispatch_authorized_count,
            "settled_action_count": total_attempts,
            "settled_records_without_worker_id": settled_records_without_worker_id,
            "authorized_but_unsettled_count": len(active_authorizations),
        },
        "prompt_health": {
            "job_count": len(jobs),
            "unique_prompt_fingerprint_count": len(prompt_fingerprints),
            "prompt_length_chars": prompt_length_summary,
            "raw_prompts_stored_in_report": False,
        },
        "timing": {
            "observed_last_tool_finished_at": observed_last_tool_finished_at,
            "stage_seconds": {
                key: round(value, 3) if isinstance(value, (int, float)) else None
                for key, value in stage_durations.items()
            },
            "tool_duration": health_summary(tool_durations),
            "imagegen_slot_wait": health_summary(imagegen_slot_waits),
            "imagegen_rpc_duration": health_summary(imagegen_rpc_durations),
            "imagegen_peak_inflight": imagegen_peak_inflight,
            "imagegen_observed_global_caps": sorted(set(imagegen_slot_caps)),
            "tool_to_file_validation": validation_summary,
            "agent_tail_after_tool": agent_tail_summary,
            "timing_target": state.get("timing_target"),
        },
        "signals": {
            "event_count": len(events),
            "event_counts": event_counts,
            "timing_capture_counts": timing_capture_counts,
            "imagegen_slot_telemetry_count": len(slot_sidecars),
            "diversity_review_status": (state.get("diversity_review") or {}).get("status"),
            "diversity_replacement_count": (state.get("diversity_review") or {}).get("replacement_count", 0),
        },
        "severity_counts": severity_counts,
        "findings": findings,
        "aesthetic_review": {
            "status": "not_run",
            "reason": "第一阶段只记录非视觉技术健康；深度审美复盘由独立审查任务按批次执行",
        },
    }
    return report


def render_run_health_markdown(report: dict[str, Any]) -> str:
    run = report.get("run") or {}
    counts = report.get("counts") or {}
    timing = report.get("timing") or {}
    stage = timing.get("stage_seconds") or {}
    lines = [
        "# Shawn PPT 图片运行健康报告",
        "",
        "本报告只检查管线、提示合同、引用路由、产物、恢复和计时证据；"
        "不打开图片、不判断审美，也不阻断已完成的正式交付。",
        "",
        f"- 运行：`{run.get('run_id')}`",
        f"- 模式：`{run.get('run_mode')}`",
        f"- 页面：`{', '.join(run.get('page_ids') or [])}`",
        f"- 记录类型：`{run.get('record_kind')}`",
        f"- 运行结果：`{run.get('run_outcome')}`",
        f"- 技术健康：`{report.get('health_status')}`",
        f"- 错误：`{(report.get('severity_counts') or {}).get('error', 0)}`",
        f"- 警告：`{(report.get('severity_counts') or {}).get('warning', 0)}`",
        f"- 估算图片调用：`{counts.get('estimated_imagegen_calls')}`",
        f"- 无生图恢复：`{counts.get('recovery_started_count')}`",
        "",
        "## 关键路径",
        "",
        "- " + markdown_file_link("正式状态", str(run.get("state_path"))),
    ]
    if run.get("outcome_reason"):
        lines.extend(["", f"终止原因：{run.get('outcome_reason')}", ""])
    if run.get("overview_path"):
        lines.append("- " + markdown_file_link("正式总览", str(run["overview_path"])))
    if run.get("handoff_path"):
        lines.append("- " + markdown_file_link("正式交接", str(run["handoff_path"])))
    lines.extend(
        [
            "",
            "## 阶段耗时",
            "",
            "| 阶段 | 秒 |",
            "|---|---:|",
        ]
    )
    for key in (
        "process_total",
        "process_to_package",
        "package_to_dispatch",
        "active_dispatch_preparation",
        "pre_dispatch_capacity_wait",
        "dispatch_to_overview",
        "tools_complete_to_overview",
        "initial_tools_to_final_initial_judge",
        "final_initial_judge_to_diversity_close",
        "diversity_close_to_overview",
        "overview_to_complete",
    ):
        lines.append(f"| `{key}` | {stage.get(key)} |")
    lines.extend(["", "## 技术发现", ""])
    findings = report.get("findings") or []
    if findings:
        for item in findings:
            lines.append(
                f"- **{item.get('severity')} · `{item.get('code')}`**：{item.get('summary')}"
            )
    else:
        lines.append("- 未发现需要进入后续技术复盘的异常。")
    lines.extend(
        [
            "",
            "## 后续审查边界",
            "",
            "- 本报告不包含原始提示词或图片载荷。",
            "- 审美、空间与参考图命中情况留给独立批次 Review。",
            "- 后续审查应从集中索引选择最近 10 次或尚未复盘的运行。",
            "",
        ]
    )
    return "\n".join(lines)


def monitoring_entry_from_report(
    report: dict[str, Any], report_json_path: Path, report_md_path: Path
) -> dict[str, Any]:
    run = report.get("run") or {}
    entry_id = hashlib.sha256(
        f"{run.get('run_id')}\0{run.get('project_dir')}".encode("utf-8")
    ).hexdigest()[:20]
    return {
        "monitoring_entry_contract_version": MONITORING_ENTRY_CONTRACT_VERSION,
        "entry_id": entry_id,
        "run_id": run.get("run_id"),
        "run_mode": run.get("run_mode"),
        "project_dir": run.get("project_dir"),
        "page_ids": run.get("page_ids") or [],
        "record_kind": run.get("record_kind") or "completed_run",
        "run_outcome": run.get("run_outcome") or "completed",
        "status": run.get("status"),
        "outcome_reason": run.get("outcome_reason"),
        "terminal_at": run.get("terminal_at"),
        "completed_at": run.get("completed_at"),
        "health_status": report.get("health_status"),
        "severity_counts": report.get("severity_counts") or {},
        "issue_codes": list(
            dict.fromkeys(item.get("code") for item in (report.get("findings") or []))
        ),
        "counts": report.get("counts") or {},
        "timing": {
            "stage_seconds": (report.get("timing") or {}).get("stage_seconds") or {},
            "timing_target": (report.get("timing") or {}).get("timing_target"),
        },
        "has_style_reference": bool((report.get("counts") or {}).get("style_reference_job_count")),
        "aesthetic_review_status": (report.get("aesthetic_review") or {}).get("status"),
        "report_json_path": str(report_json_path.resolve()),
        "report_md_path": str(report_md_path.resolve()),
        "state_path": run.get("state_path"),
        "overview_path": run.get("overview_path"),
        "overview_sha256": run.get("overview_sha256"),
        "handoff_path": run.get("handoff_path"),
        "recorded_at": report.get("generated_at"),
        "contains_raw_prompt": False,
        "contains_image_payload": False,
    }


def render_monitoring_index_markdown(index: dict[str, Any]) -> str:
    summary = index.get("summary") or {}
    lines = [
        "# Shawn PPT 图片集中监测索引",
        "",
        "该索引由各运行的非视觉技术健康报告自动汇总；不会触发 ImageGen、"
        "不会修改正式运行状态，也不会阻塞正常交付。",
        "",
        f"- 已记录运行：`{index.get('run_count', 0)}`",
        f"- 已完成运行：`{summary.get('completed_run_count', 0)}`",
        f"- 明确终止运行：`{summary.get('terminal_incomplete_run_count', 0)}`",
        f"- 待批次审查：`{summary.get('pending_review_count', 0)}`",
        f"- 待处理复盘结论：`{summary.get('deferred_resolution_count', 0)}`",
        f"- 无效 Review：`{summary.get('invalid_review_count', 0)}`",
        f"- 技术健康：`{summary.get('health_status_counts', {})}`",
        f"- 常见问题：`{summary.get('issue_code_counts', {})}`",
        "",
        "## 增量待审队列",
        "",
        "默认批次审查只读取 `index.json.pending_reviews`；已经标为 "
        "`review_status=completed` 的运行不会再次进入该队列。",
        "",
        "| 记录时间 | 运行 | 结果 | 模式 | 页面 | 健康 | 报告 |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in index.get("pending_reviews") or []:
        report_link = markdown_file_link("打开", str(item["report_md_path"]))
        run_id = str(item.get("run_id") or "").replace("|", "/")
        page_ids = ",".join(str(value) for value in (item.get("page_ids") or [])).replace("|", "/")
        lines.append(
            f"| {item.get('completed_at') or item.get('terminal_at')} | `{run_id}` | "
            f"`{item.get('run_outcome')}` | `{item.get('run_mode')}` | "
            f"`{page_ids}` | `{item.get('health_status')}` | {report_link} |"
        )
    if not index.get("pending_reviews"):
        lines.append("| - | - | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## 最近 10 次运行",
            "",
            "| 记录时间 | 运行 | 结果 | 模式 | 页面 | 健康 | 报告 | Review |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for item in index.get("recent_10") or []:
        report_link = markdown_file_link("打开", str(item["report_md_path"]))
        run_id = str(item.get("run_id") or "").replace("|", "/")
        page_ids = ",".join(str(value) for value in (item.get("page_ids") or [])).replace("|", "/")
        lines.append(
            f"| {item.get('completed_at') or item.get('terminal_at')} | `{run_id}` | "
            f"`{item.get('run_outcome')}` | `{item.get('run_mode')}` | "
            f"`{page_ids}` | `{item.get('health_status')}` | {report_link} | "
            f"`{item.get('review_status')}` |"
        )
    if not index.get("recent_10"):
        lines.append("| - | - | - | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "`recent_10` 和 `runs` 只用于浏览、统计或显式历史对照，不是默认审查队列。"
            "批次审查先读取 `pending_reviews`，再按报告路径读取具体运行；"
            "无需扫描聊天记录或原始图片目录。已完成 Review 只有在用户明确要求历史重审、"
            "Review 文件失效，或作为回归基线参与新旧对照时才再次读取；作为基线不生成第二份 Review。",
            "",
        ]
    )
    return "\n".join(lines)


def monitoring_review_validation(
    review_path: Path, entry: dict[str, Any]
) -> tuple[str, list[str]]:
    """Validate a lightweight review sidecar before marking an entry reviewed."""

    if not review_path.is_file():
        return "pending", []
    try:
        review = read_json(review_path)
    except SystemExit as exc:
        return "invalid", [str(exc)]
    errors: list[str] = []
    if review.get("review_contract_version") != 1:
        errors.append("review_contract_version 必须为 1")
    if review.get("entry_id") != entry.get("entry_id"):
        errors.append("entry_id 与索引条目不一致")
    if review.get("run_id") != entry.get("run_id"):
        errors.append("run_id 与索引条目不一致")
    if not isinstance(review.get("review_kind"), str) or not review.get("review_kind"):
        errors.append("缺少 review_kind")
    overview_sha = review.get("overview_sha256")
    expected_sha = entry.get("overview_sha256")
    terminal_without_overview = (
        entry.get("record_kind") == "terminal_incomplete_run" and not expected_sha
    )
    if terminal_without_overview:
        if overview_sha is not None:
            errors.append("没有正式总览的终止任务必须使用 overview_sha256=null")
    else:
        if not isinstance(overview_sha, str) or re.fullmatch(r"[0-9a-f]{64}", overview_sha) is None:
            errors.append("overview_sha256 不是 64 位小写 SHA-256")
        if expected_sha and overview_sha != expected_sha:
            errors.append("overview_sha256 与正式总览不一致")
    for key in ("technical_findings", "visual_findings", "speed_assessment"):
        if not isinstance(review.get(key), dict):
            errors.append(f"缺少对象字段 {key}")
    if not isinstance(review.get("recommended_actions"), list):
        errors.append("recommended_actions 必须是数组")
    if not isinstance(review.get("reviewed_at"), str) or not review.get("reviewed_at"):
        errors.append("缺少 reviewed_at")
    resolution = review.get("resolution")
    if resolution is not None:
        if not isinstance(resolution, dict):
            errors.append("resolution 必须是对象")
        else:
            resolution_status = resolution.get("status")
            if resolution_status not in {
                "applied",
                "no_change_needed",
                "deferred",
                "superseded",
            }:
                errors.append("resolution.status 无效")
            if not isinstance(resolution.get("resolved_at"), str) or not resolution.get(
                "resolved_at"
            ):
                errors.append("resolution 缺少 resolved_at")
            evidence_paths = resolution.get("evidence_paths", [])
            if not isinstance(evidence_paths, list) or not all(
                isinstance(item, str) and item for item in evidence_paths
            ):
                errors.append("resolution.evidence_paths 必须是字符串数组")
    privacy = review.get("privacy") if isinstance(review.get("privacy"), dict) else {}
    image_payload_flag = review.get(
        "contains_image_payload", privacy.get("contains_image_payload")
    )
    raw_prompt_flag = review.get(
        "contains_raw_prompt", privacy.get("contains_raw_prompt")
    )
    if image_payload_flag is not False:
        errors.append("必须显式声明 contains_image_payload=false")
    if raw_prompt_flag is not False:
        errors.append("必须显式声明 contains_raw_prompt=false")
    return ("invalid", errors) if errors else ("completed", [])


def rebuild_monitoring_index(
    monitoring_root: Path, timestamp: str | None = None
) -> tuple[Path, Path, dict[str, Any]]:
    root = monitoring_root.expanduser().resolve()
    entries_dir = root / "entries"
    reviews_dir = root / "reviews"
    entries_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for path in sorted(entries_dir.glob("entry_*.json")):
        try:
            entry = read_json(path)
        except SystemExit:
            continue
        if entry.get("monitoring_entry_contract_version") != MONITORING_ENTRY_CONTRACT_VERSION:
            continue
        entry_id = entry.get("entry_id")
        review_path = reviews_dir / f"review_{entry_id}.json"
        copied = dict(entry)
        copied.setdefault("record_kind", "completed_run")
        copied.setdefault("run_outcome", "completed")
        review_status, review_errors = monitoring_review_validation(review_path, entry)
        copied["review_status"] = review_status
        copied["review_path"] = str(review_path) if review_path.is_file() else None
        copied["review_validation_errors"] = review_errors
        copied["reviewed_at"] = None
        copied["review_kind"] = None
        copied["review_resolution_status"] = "not_reviewed"
        if review_status == "completed":
            review_payload = read_json(review_path)
            copied["reviewed_at"] = review_payload.get("reviewed_at")
            copied["review_kind"] = review_payload.get("review_kind")
            resolution = review_payload.get("resolution") or {}
            copied["review_resolution_status"] = resolution.get("status") or "untracked"
        elif review_status == "invalid":
            copied["review_resolution_status"] = "invalid_review"
        entries.append(copied)
    entries.sort(
        key=lambda item: str(
            item.get("completed_at")
            or item.get("terminal_at")
            or item.get("recorded_at")
            or ""
        ),
        reverse=True,
    )
    health_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    for entry in entries:
        health = str(entry.get("health_status") or "unknown")
        health_counts[health] = health_counts.get(health, 0) + 1
        mode = str(entry.get("run_mode") or "unknown")
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        for code in entry.get("issue_codes") or []:
            issue_counts[str(code)] = issue_counts.get(str(code), 0) + 1
    pending_reviews = [
        entry for entry in entries if entry.get("review_status") == "pending"
    ]
    deferred_resolutions = [
        entry
        for entry in entries
        if entry.get("review_status") == "completed"
        and entry.get("review_resolution_status") == "deferred"
    ]
    index = {
        "monitoring_index_contract_version": MONITORING_INDEX_CONTRACT_VERSION,
        "monitoring_root": str(root),
        "updated_at": timestamp or now_iso(),
        "run_count": len(entries),
        "summary": {
            "health_status_counts": dict(sorted(health_counts.items())),
            "run_mode_counts": dict(sorted(mode_counts.items())),
            "issue_code_counts": dict(
                sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))
            ),
            "pending_review_count": sum(
                1 for entry in entries if entry.get("review_status") == "pending"
            ),
            "completed_review_count": sum(
                1 for entry in entries if entry.get("review_status") == "completed"
            ),
            "deferred_resolution_count": len(deferred_resolutions),
            "invalid_review_count": sum(
                1 for entry in entries if entry.get("review_status") == "invalid"
            ),
            "completed_run_count": sum(
                1 for entry in entries if entry.get("record_kind") == "completed_run"
            ),
            "terminal_incomplete_run_count": sum(
                1
                for entry in entries
                if entry.get("record_kind") == "terminal_incomplete_run"
            ),
        },
        "review_selection_policy": {
            "default_queue": "pending_reviews",
            "completed_reviews_are_reopened_automatically": False,
            "recent_10_is_navigation_only": True,
            "historical_rereview_requires": [
                "explicit_user_request",
                "invalid_or_hash_mismatched_review",
            ],
            "regression_policy": "review new runs; old completed runs may be read-only baselines without creating a second review",
        },
        "pending_reviews": pending_reviews,
        "deferred_resolutions": deferred_resolutions,
        "recent_10": entries[:10],
        "runs": entries,
        "privacy": {
            "raw_prompts_in_index": False,
            "image_payloads_in_index": False,
            "local_paths_only": True,
        },
    }
    json_path = root / "index.json"
    markdown_path = root / "index.md"
    atomic_write_json(json_path, index)
    atomic_write_text(markdown_path, render_monitoring_index_markdown(index))
    return json_path, markdown_path, index


def write_run_health_report(
    *,
    state_path: Path,
    state: dict[str, Any] | None = None,
    monitoring_root: str | None = None,
    timestamp: str | None = None,
    best_effort_registry: bool = False,
    register_central: bool = True,
    run_outcome: str | None = None,
    outcome_reason: str | None = None,
) -> dict[str, Any]:
    state_path = state_path.expanduser().resolve()
    state = state or read_json(state_path)
    project_dir = project_dir_for_state(state_path, state)
    report = build_run_health_report(
        state_path=state_path,
        state=state,
        timestamp=timestamp,
        run_outcome=run_outcome,
        outcome_reason=outcome_reason,
    )
    report_json_path = project_dir / "state" / "run_health_report.json"
    report_md_path = project_dir / "state" / "run_health_report.md"
    atomic_write_json(report_json_path, report)
    atomic_write_text(report_md_path, render_run_health_markdown(report))
    if not register_central:
        return {
            "status": "ok",
            "health_status": report.get("health_status"),
            "report_json": str(report_json_path),
            "report_md": str(report_md_path),
            "monitoring_root": None,
            "entry": None,
            "index_json": None,
            "index_md": None,
            "registry_warning": None,
        }
    root = monitoring_root_for_state(state_path, state, monitoring_root)
    entry = monitoring_entry_from_report(report, report_json_path, report_md_path)
    entry_path = root / "entries" / f"entry_{entry['entry_id']}.json"
    registry_warning: str | None = None
    index_json_path: Path | None = None
    index_md_path: Path | None = None
    try:
        atomic_write_json(entry_path, entry)
        index_json_path, index_md_path, _ = rebuild_monitoring_index(root, timestamp)
    except (Exception, SystemExit) as exc:
        if not best_effort_registry:
            raise
        registry_warning = str(exc)
    return {
        "status": "warning" if registry_warning else "ok",
        "health_status": report.get("health_status"),
        "report_json": str(report_json_path),
        "report_md": str(report_md_path),
        "monitoring_root": str(root),
        "entry": str(entry_path) if entry_path.is_file() else None,
        "index_json": str(index_json_path) if index_json_path else None,
        "index_md": str(index_md_path) if index_md_path else None,
        "registry_warning": registry_warning,
    }


def write_handoff_files(
    *,
    project_dir: Path,
    state_path: Path,
    state: dict[str, Any] | None = None,
    unresolved_issues: list[str] | None = None,
    next_allowed_actions: list[str] | None = None,
    timestamp: str | None = None,
    drift_result: dict[str, Any] | None = None,
    state_sha256: str | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    document = build_handoff_document(
        project_dir=project_dir,
        state_path=state_path,
        state=state,
        unresolved_issues=unresolved_issues,
        next_allowed_actions=next_allowed_actions,
        timestamp=timestamp,
        drift_result=drift_result,
        state_sha256=state_sha256,
    )
    markdown = render_handoff_markdown(document)
    state_dir = project_dir.resolve() / "state"
    json_path = state_dir / "handoff.json"
    markdown_path = state_dir / "handoff.md"
    atomic_write_json(json_path, document)
    atomic_write_text(markdown_path, markdown)
    return json_path, markdown_path, document


def command_snapshot_source(args: argparse.Namespace) -> None:
    project_dir = Path(args.project_dir).resolve()
    state_path = Path(args.state).resolve()
    page_ids = normalize_page_ids(args.page_ids)
    raw_contracts = getattr(args, "content_contract", None) or []
    contracts_json = getattr(args, "content_contracts_json", None)
    if contracts_json:
        parsed = parse_json_array(contracts_json, "--content-contracts-json")
        raw_contracts = [*raw_contracts, *parsed]
    assets = parse_json_array(getattr(args, "assets_json", "[]"), "--assets-json")
    supporting_sources = parse_json_array(
        getattr(args, "supporting_sources_json", "[]"),
        "--supporting-sources-json",
    )
    fragment = getattr(args, "source_fragment_file", None)
    snapshot = create_source_snapshot(
        project_dir=project_dir,
        state_path=state_path,
        source_path=Path(args.source_file),
        page_ids=page_ids,
        content_contract_paths=[Path(item) for item in raw_contracts],
        asset_items=assets,
        supporting_source_paths=[
            Path(item.get("path") if isinstance(item, dict) else item)
            for item in supporting_sources
        ],
        fragment_path=Path(fragment) if fragment else None,
        slide_identity_path=(
            Path(args.slide_identity_file)
            if getattr(args, "slide_identity_file", None)
            else None
        ),
        fragment_authority=getattr(args, "source_fragment_authority", "extractor_aid"),
        timestamp=getattr(args, "timestamp", None),
    )
    snapshot_path = project_dir / "state" / "source_snapshot.json"
    print(
        json.dumps(
            {
                "status": "ok",
                "source_snapshot": str(snapshot_path),
                "sha256": file_sha256(snapshot_path),
                "page_content_sha256": snapshot["page_content"]["sha256"],
            },
            ensure_ascii=False,
        )
    )


def command_check_source_drift(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    result = evaluate_source_drift(
        state_path,
        state,
        action=args.action,
        timestamp=getattr(args, "timestamp", None),
    )
    if source_guard_enabled(state_path, state):
        completed = state.get("status") == "completed" or bool(
            (state.get("timing") or {}).get("process_completed_at")
        )
        if completed and result.get("can_continue"):
            project_dir = project_dir_for_state(state_path, state)
            atomic_write_json(
                project_dir / "state" / "source_drift_status.json", result
            )
        else:
            persist_source_drift_result(state_path, state, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("can_continue") and not getattr(args, "report_only", False):
        raise SystemExit(2)


def command_confirm_legacy_source_risk(args: argparse.Namespace) -> None:
    """Record a user-authorized, hash-free compatibility decision for a legacy run."""

    if getattr(args, "user_confirmed", False) is not True:
        raise SystemExit("必须在用户明确确认后传入 --user-confirmed")
    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    if source_guard_enabled(state_path, state):
        raise SystemExit("该任务已声明 source guard，不适用 legacy 兼容确认")
    actions = [item.strip() for item in str(args.actions).split(",") if item.strip()]
    if not actions:
        raise SystemExit("--actions 至少包含一个正式动作")
    unknown = sorted(set(actions) - LEGACY_SOURCE_GUARDED_ACTIONS)
    if unknown:
        raise SystemExit("legacy 兼容确认包含未知动作：" + ", ".join(unknown))
    identity = legacy_source_identity(state_path, state)
    identity_sha = sha256_text(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    confirmation = {
        "legacy_source_confirmation_contract_version": (
            LEGACY_SOURCE_CONFIRMATION_CONTRACT_VERSION
        ),
        "confirmed": True,
        "confirmed_at": args.timestamp or now_iso(),
        "allowed_actions": list(dict.fromkeys(actions)),
        "historical_hashes_available": False,
        "decision": "user_explicitly_accepted_legacy_source_risk",
        "risk_code": "legacy_source_snapshot_missing",
        "confirmed_by": getattr(args, "confirmed_by", None)
        or "user_via_current_codex_task",
        "confirmation_text": getattr(args, "confirmation_text", None)
        or "User explicitly accepted continuing the listed legacy actions without historical source hashes.",
        "state_sha256_at_confirmation": file_sha256(state_path),
        "event_count_at_confirmation": len(state.get("events") or []),
        "run_identity": identity,
        "run_identity_sha256": identity_sha,
    }
    confirmation["confirmation_id"] = sha256_text(
        json.dumps(
            confirmation,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )[:24]
    confirmation_path = legacy_source_confirmation_path(state_path, state)
    atomic_write_json(confirmation_path, confirmation)
    print(
        json.dumps(
            {
                "status": "legacy_user_confirmed",
                "state": str(state_path),
                "confirmation_path": str(confirmation_path),
                "allowed_actions": confirmation["allowed_actions"],
            },
            ensure_ascii=False,
        )
    )


def command_check_expansion_job(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    if not (
        state.get("phase") == "selected_style_expansion"
        or state.get("run_mode") == "selected_style_expansion"
    ):
        raise SystemExit("check-expansion-job 只适用于 selected_style_expansion")
    result = enforce_selected_expansion_job_guard(
        state_path,
        state,
        page_id=str(args.page_id),
        action=str(args.action),
        attempt=int(args.attempt),
        generation_job_path=str(args.generation_job),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def parse_optional_string_array(value: str | None, flag: str) -> list[str] | None:
    if value is None:
        return None
    parsed = parse_json_array(value, flag)
    if not all(isinstance(item, str) and item.strip() for item in parsed):
        raise SystemExit(f"{flag} 必须是非空字符串数组")
    return [item.strip() for item in parsed]


def command_write_handoff(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    if not (
        state.get("status") == "completed"
        and (state.get("timing") or {}).get("process_completed_at")
    ):
        raise SystemExit(
            "正式 handoff 只允许在 process_completed 封存最终状态后生成；"
            "较早阶段不得写 draft handoff"
        )
    project_dir = (
        Path(args.project_dir).resolve()
        if getattr(args, "project_dir", None)
        else project_dir_for_state(state_path, state)
    )
    unresolved = parse_optional_string_array(
        getattr(args, "unresolved_issues_json", None), "--unresolved-issues-json"
    )
    actions = parse_optional_string_array(
        getattr(args, "next_allowed_actions_json", None),
        "--next-allowed-actions-json",
    )
    json_path = project_dir / "state" / "handoff.json"
    markdown_path = project_dir / "state" / "handoff.md"
    if markdown_path.exists() and not json_path.exists():
        raise SystemExit(
            "检测到 handoff.md 但缺少 handoff.json；不得从 Markdown 反推正式交接"
        )
    if json_path.exists():
        if unresolved is not None or actions is not None:
            raise SystemExit("正式 handoff 已存在，不得用覆盖参数改写已封存交接")
        document = read_json(json_path)
        state_ref = document.get("state_ref") or {}
        state_path_matches = state_ref.get("path") == str(state_path)
        state_sha_matches = state_ref.get("sha256") == file_sha256(state_path)
        if not state_path_matches:
            raise SystemExit("现有 handoff.json 未绑定当前状态路径，拒绝覆盖")
        if not state_sha_matches and not getattr(args, "refresh_state_ref", False):
            raise SystemExit(
                "现有 handoff.json 未绑定当前最终状态；如已确认状态改动只来自旧版完成态"
                "验证的副作用，可显式使用 --refresh-state-ref 安全重建"
            )
        if not state_sha_matches:
            if document.get("run_id") != state.get("run_id") or document.get(
                "project_dir"
            ) != str(project_dir):
                raise SystemExit("handoff 与当前运行身份不一致，禁止 refresh")
            old_sha = file_sha256(json_path)
            backup_path = json_path.with_name(f"handoff.before_refresh_{old_sha[:12]}.json")
            if backup_path.exists():
                if file_sha256(backup_path) != old_sha:
                    raise SystemExit("handoff refresh 备份路径已存在但内容不一致")
            else:
                atomic_write_json(backup_path, document)
            drift_result = evaluate_source_drift(
                state_path, state, action="candidate_delivery"
            )
            atomic_write_json(
                project_dir / "state" / "source_drift_status.json", drift_result
            )
            if not drift_result.get("can_continue"):
                raise SystemExit(
                    f"{drift_result.get('status')}：源材料未通过 handoff refresh 漂移检测"
                )
            json_path, markdown_path, refreshed = write_handoff_files(
                project_dir=project_dir,
                state_path=state_path,
                state=state,
                unresolved_issues=document.get("unresolved_issues") or [],
                next_allowed_actions=document.get("next_allowed_actions") or [],
                timestamp=getattr(args, "timestamp", None),
                drift_result=drift_result,
            )
            print(
                json.dumps(
                    {
                        "status": "refreshed",
                        "handoff_json": str(json_path),
                        "handoff_md": str(markdown_path),
                        "backup_json": str(backup_path),
                        "state_sha256": (refreshed.get("state_ref") or {}).get(
                            "sha256"
                        ),
                    },
                    ensure_ascii=False,
                )
            )
            return
        markdown = render_handoff_markdown(document)
        if not markdown_path.exists() or markdown_path.read_text(
            encoding="utf-8"
        ) != markdown:
            atomic_write_text(markdown_path, markdown)
        print(
            json.dumps(
                {
                    "status": "already_exists",
                    "handoff_json": str(json_path),
                    "handoff_md": str(markdown_path),
                },
                ensure_ascii=False,
            )
        )
        return
    drift_result = evaluate_source_drift(
        state_path, state, action="candidate_delivery"
    )
    atomic_write_json(project_dir / "state" / "source_drift_status.json", drift_result)
    if not drift_result.get("can_continue"):
        raise SystemExit(
            f"{drift_result.get('status')}：源材料未通过正式 handoff 前漂移检测"
        )
    json_path, markdown_path, document = write_handoff_files(
        project_dir=project_dir,
        state_path=state_path,
        state=state,
        unresolved_issues=unresolved,
        next_allowed_actions=actions,
        timestamp=getattr(args, "timestamp", None),
        drift_result=drift_result,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "handoff_json": str(json_path),
                "handoff_md": str(markdown_path),
            },
            ensure_ascii=False,
        )
    )


def command_rebuild_handoff_markdown(args: argparse.Namespace) -> None:
    json_path = require_formal_file_path(args.handoff_json, "handoff.json")
    handoff = read_json(json_path)
    markdown = render_handoff_markdown(handoff)
    output_value = getattr(args, "output", None)
    output = Path(output_value).expanduser() if output_value else json_path.with_suffix(".md")
    if not output.is_absolute():
        raise SystemExit("handoff.md 输出必须是绝对路径")
    output = output.resolve()
    atomic_write_text(output, markdown)
    print(
        json.dumps(
            {"status": "ok", "handoff_md": str(output), "sha256": file_sha256(output)},
            ensure_ascii=False,
        )
    )


def command_write_run_health(args: argparse.Namespace) -> None:
    state_path = Path(args.state).expanduser().resolve()
    state = read_json(state_path)
    if state.get("status") != "completed" and not args.allow_incomplete:
        raise SystemExit(
            "正式运行健康报告默认只为 completed 状态生成；"
            "诊断中断任务时显式使用 --allow-incomplete"
        )
    terminal_outcome = getattr(args, "terminal_outcome", None)
    outcome_reason = getattr(args, "outcome_reason", None)
    if state.get("status") == "completed" and terminal_outcome:
        raise SystemExit("completed 运行不得指定 --terminal-outcome")
    if terminal_outcome and not args.allow_incomplete:
        raise SystemExit("--terminal-outcome 必须与 --allow-incomplete 同时使用")
    if terminal_outcome and not isinstance(outcome_reason, str):
        raise SystemExit("--terminal-outcome 必须同时提供 --outcome-reason")
    result = write_run_health_report(
        state_path=state_path,
        state=state,
        monitoring_root=args.monitoring_root,
        timestamp=args.timestamp,
        best_effort_registry=False,
        register_central=state.get("status") == "completed" or bool(terminal_outcome),
        run_outcome=terminal_outcome,
        outcome_reason=outcome_reason,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def command_rebuild_monitoring_index(args: argparse.Namespace) -> None:
    root = Path(args.monitoring_root).expanduser().resolve()
    json_path, markdown_path, index = rebuild_monitoring_index(root, args.timestamp)
    print(
        json.dumps(
            {
                "status": "ok",
                "monitoring_root": str(root),
                "run_count": index.get("run_count"),
                "pending_review_count": (index.get("summary") or {}).get(
                    "pending_review_count"
                ),
                "index_json": str(json_path),
                "index_md": str(markdown_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def compact_prompt_value(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return "；".join(
            f"{key}:{item}" for key, item in value.items() if str(item).strip()
        )
    return str(value).strip() if value is not None else ""


def normalize_prompt_items(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item).strip() if item is not None else ""
        signature = normalize_signature_text(text)
        if text and signature not in seen:
            normalized.append(text)
            seen.add(signature)
    return normalized


def dedupe_prompt_items(value: Any, seen: set[str]) -> list[str]:
    normalized: list[str] = []
    for item in normalize_prompt_items(value):
        signature = normalize_signature_text(item)
        if signature in seen:
            continue
        normalized.append(item)
        seen.add(signature)
    return normalized


def page_relationship_thesis(page: dict[str, Any]) -> str:
    """Return the preferred page-level relationship thesis with legacy alias support."""

    return str(
        page.get("relationship_thesis")
        or page.get("relationship_synthesis_brief")
        or ""
    ).strip()


def build_creative_brief_projection(
    page: dict[str, Any], seed: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Make the planner-to-image intermediate brief explicit and testable."""

    seed = seed or {}
    literal_anchors = normalize_prompt_items(
        page.get("display_required", page.get("required_content", []))
    )
    flexible_items = normalize_prompt_items(page.get("display_flexible", []))
    explicit_flexible_story = str(page.get("flexible_story") or "").strip()
    return {
        "creative_brief_projection_version": 1,
        "relationship_thesis": page_relationship_thesis(page),
        "visual_quality_intent": str(page.get("visual_quality_intent") or "").strip(),
        "literal_anchors": literal_anchors,
        "flexible_story": explicit_flexible_story or " ".join(flexible_items),
        "flexible_story_source": (
            "explicit_director_story"
            if explicit_flexible_story
            else "display_flexible_join"
        ),
        "language_presentation": dict(page.get("language_presentation") or {}),
        "visual_thesis": str(seed.get("visual_thesis") or "").strip(),
        "style_family_thesis": str(
            seed.get("style_family_thesis") or ""
        ).strip(),
        "craft_axis": str(seed.get("craft_axis") or "").strip(),
        "visual_activity_mode": str(
            seed.get("visual_activity_mode") or ""
        ).strip(),
        "attention_strategy": str(seed.get("attention_strategy") or "").strip(),
        "narrative_layer_budget": {
            "primary_relationships": 1,
            "supporting_evidence_layers_max": 1,
            "independent_explainer_bands_max": 0,
            "merge_secondary_systems": True,
        },
        "relationship_representation_family": str(
            seed.get("relationship_representation_family") or ""
        ).strip(),
        "spatial_topology": dict(seed.get("spatial_topology") or {}),
        "adaptation_principle": str(
            seed.get("adaptation_principle") or ""
        ).strip(),
        "continuity_invariants": list(seed.get("continuity_invariants") or []),
    }


def language_presentation_prompt(
    page: dict[str, Any], *, use_chinese_control: bool
) -> str:
    """Compile a small, explicit language-layout instruction for ImageGen."""

    value = page.get("language_presentation")
    if not isinstance(value, dict):
        return ""
    mode = value.get("mode")
    delivery = value.get("delivery", "single")
    pairing = value.get("pairing", "none")
    pairs = value.get("pairs") or []
    if mode == "zh_only":
        if delivery == "split_peer":
            return (
                "这是复杂逻辑页的中文兄弟页：只上屏本任务已授权中文。英文兄弟页另行生成；不得补入、概述或引用其英文显示文案。"
                if use_chinese_control
                else "This is the Chinese sibling of a split bilingual logical page. Show only the authorized Chinese copy; the English sibling is generated separately and must not leak into this image."
            )
        return (
            "本页只上屏已授权中文；英文源文只用于理解，不形成英文正文或第二语言版式。"
            if use_chinese_control
            else "Show only the authorized Chinese copy; do not create a separate English text system."
        )
    if mode == "en_only":
        if delivery == "split_peer":
            return (
                "这是复杂逻辑页的英文兄弟页：只上屏本任务已授权英文。中文兄弟页另行生成；不得补入、概述或引用其中文显示文案。"
                if use_chinese_control
                else "This is the English sibling of a split bilingual logical page. Show only the authorized English copy; the Chinese sibling is generated separately and must not leak into this image."
            )
        return (
            "本页只上屏已授权英文；中文源文只用于理解，不形成中文正文或第二语言版式。"
            if use_chinese_control
            else "Show only the authorized English copy; do not create a separate Chinese text system."
        )
    if mode != "bilingual" or not pairs:
        return ""
    pair_lines = [
        f"- {str(item['primary']).strip()} ⇄ {str(item['secondary']).strip()}"
        for item in pairs
    ]
    if pairing == "summary":
        intro = (
            "本页采用克制的同页双语摘要：中文为主、英文为辅。以下英文短摘要必须贴近对应中文主结论并共享同一信息单元；不得集中成独立底栏、侧栏、第二段落系统或第二套版式。只显示列出的已授权英文，不临场补译："
            if use_chinese_control
            else (
                "Use restrained same-slide bilingual summaries: Chinese is primary and English secondary. "
                "Keep each English summary next to its Chinese statement in the same information unit; "
                "do not create a separate footer, sidebar, paragraph system, or second layout. "
                "Show only the listed authorized English copy and do not translate anything else:"
            )
        )
    else:
        intro = (
            "本页采用同页双语配对：中文为主、英文为辅。以下每组中英必须就近相邻，共享同一信息单元、对齐与关系位置；不得把英文集中成独立底栏、侧栏、第二段落系统或第二套版式。只显示列出的已授权英文，不临场补译："
            if use_chinese_control
            else (
                "Use paired bilingual copy on the same slide: Chinese is primary and English secondary. "
                "Keep every pair adjacent in the same information unit, alignment, and relationship position; "
                "do not create a separate footer, sidebar, paragraph system, or second layout. "
                "Show only the listed authorized English copy and do not translate anything else:"
            )
        )
    return intro + "\n" + "\n".join(pair_lines)


def normalize_output_language(value: Any) -> str:
    """Normalize common language labels without imposing a default language."""

    raw = str(value).strip() if value is not None else ""
    if not raw:
        return "source"
    aliases = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "chinese": "zh-CN",
        "中文": "zh-CN",
        "en": "en-US",
        "en-us": "en-US",
        "english": "en-US",
        "英文": "en-US",
        "auto": "source",
        "preserve": "source",
        "original": "source",
        "原文": "source",
        "多语言": "mixed",
    }
    return aliases.get(raw.lower(), raw)


def resolve_job_language(job: dict[str, Any]) -> str:
    page = job.get("anchor_page") or {}
    return normalize_output_language(job.get("language") or page.get("language"))


def resolve_visual_artifact_kind(job: dict[str, Any], language: str) -> tuple[str, str]:
    """Select a neutral presentation-slide or poster opening from explicit page intent."""

    page = job.get("anchor_page") or {}
    intent_text = " ".join(
        str(value or "")
        for value in (
            page.get("visual_quality_intent"),
            page.get("visual_intent"),
            page.get("user_constraints"),
            job.get("visual_quality_intent"),
            job.get("user_constraints"),
        )
    ).lower()
    is_poster = any(token in intent_text for token in ("海报", "poster", "zine", "节目单"))
    if language.lower().startswith("zh"):
        return ("16:9 横版文化海报", "16:9 商务 PPT 页面") if is_poster else ("16:9 商务 PPT 页面", "")
    return ("16:9 horizontal cultural poster", "16:9 business presentation slide") if is_poster else ("16:9 business presentation slide", "")


def slide_prompt_opening(job: dict[str, Any], polished: bool = False) -> str:
    quality = "complete, polished, and ready-to-use" if polished else "complete and production-ready"
    language = resolve_job_language(job)
    artifact_kind, _legacy_kind = resolve_visual_artifact_kind(job, language)
    lowered = language.lower()
    if lowered.startswith("zh"):
        quality_zh = "完整、成熟、精致、可直接使用" if polished else "完整、成品级"
        return (
            f"生成{quality_zh}的 {artifact_kind}；页面文字使用中文。"
            "逐字保留必显文案，不翻译、不补充其他语言标签。"
        )
    if lowered.startswith("en"):
        return (
            f"Create a {quality} {artifact_kind}. "
            "All on-slide copy must be in English. Reproduce the required copy exactly; "
            "do not translate it or add labels in another language."
        )
    if lowered in {"source", "mixed", "multilingual"}:
        return (
            f"Create a {quality} {artifact_kind}. "
            "Use exactly the language or languages present in the required on-slide copy. "
            "Do not translate the copy or add labels in another language."
        )
    return (
        f"Create a {quality} {artifact_kind}. "
        f"All on-slide copy must use {language}. Reproduce the required copy exactly; "
        "do not translate it or add labels in another language."
    )


def slide_prompt_opening_v4(job: dict[str, Any], has_exact_copy: bool) -> str:
    """Quick8 v5 的本地化开头；允许把说明性文案从逐字文案中分离。"""

    quality = "complete, polished, and ready-to-use"
    language = resolve_job_language(job)
    artifact_kind, _legacy_kind = resolve_visual_artifact_kind(job, language)
    lowered = language.lower()
    if lowered.startswith("zh"):
        exact_note = "逐字保留指定文案，" if has_exact_copy else ""
        return (
            f"生成完整、成熟、精致、可直接使用的 {artifact_kind}；页面文字使用中文。"
            f"{exact_note}不翻译、不补充其他语言标签。"
        )
    if lowered.startswith("en"):
        exact_note = " Reproduce the specified exact copy verbatim;" if has_exact_copy else ""
        return (
            f"Create a {quality} {artifact_kind}. "
            f"All on-slide copy must be in English.{exact_note} "
            "do not translate it or add labels in another language."
        )
    if lowered in {"source", "mixed", "multilingual"}:
        exact_note = " Reproduce the specified exact copy verbatim." if has_exact_copy else ""
        return (
            f"Create a {quality} {artifact_kind}. "
            "Use exactly the language or languages present in the required on-slide copy. "
            f"Do not translate the copy or add labels in another language.{exact_note}"
        )
    exact_note = " Reproduce the specified exact copy verbatim;" if has_exact_copy else ""
    return (
        f"Create a {quality} {artifact_kind}. "
        f"All on-slide copy must use {language}.{exact_note} "
        "do not translate it or add labels in another language."
    )


def finalize_imagegen_prompt(prompt: str) -> str:
    """Place the shared pre-render subtraction check exactly once at prompt end."""

    sections = [
        section
        for section in prompt.strip().split("\n\n")
        if section.strip() != PRE_RENDER_SUBTRACTION_CHECK
    ]
    finalized = "\n\n".join([*sections, PRE_RENDER_SUBTRACTION_CHECK])
    if finalized.count(PRE_RENDER_SUBTRACTION_CHECK) != 1:
        raise SystemExit("最终 ImageGen prompt 的构图减法检查必须且只能出现一次")
    return finalized


def compile_minimal_prompt_v4(job: dict[str, Any]) -> str:
    """把 Quick8 v5 / Fast8 v7 / 4x3 v6 编译为最小开放图片提示。"""

    page = job["anchor_page"]
    seed = job.get("layout_direction") or job.get("exploration_seed") or {}
    if seed.get("layout_contract_version") not in {
        CURRENT_QUICK_LAYOUT_VERSION,
        CURRENT_FAST8_LAYOUT_VERSION,
        CURRENT_4X3_LAYOUT_VERSION,
        SELECTED_STYLE_LAYOUT_VERSION,
    }:
        raise SystemExit(
            "最小图片提示必须配套 Quick8 layout v5、Fast8 layout v7、"
            "4x3 layout v6 或 selected-style layout v1"
        )
    exact_items = normalize_prompt_items(
        page.get("display_required", page.get("required_content", []))
    )
    global_chrome = job.get("global_chrome") or {}
    page_title = str(page.get("title") or page.get("page_title") or "").strip()
    required_main_title = page_title
    required_subtitle = str(page.get("subtitle") or "").strip()
    if global_chrome.get("applies") is True:
        projected_title = global_chrome.get("main_title") or {}
        if not isinstance(projected_title, dict):
            raise SystemExit("global chrome main_title 必须是对象")
        main_title_required = (
            global_chrome.get("main_title_required") is True
            or projected_title.get("required") is True
        )
        if main_title_required:
            title_text = projected_title.get("text")
            if not isinstance(title_text, str) or not title_text.strip():
                raise SystemExit("global chrome 要求主标题但当前页缺少逐字 main_title.text")
            projected_title_text = title_text.strip()
            if (
                required_main_title
                and normalize_signature_text(required_main_title)
                != normalize_signature_text(projected_title_text)
            ):
                raise SystemExit("当前页 title 与 global chrome main_title.text 冲突")
            required_main_title = projected_title_text
    title_signatures = {
        normalize_signature_text(value)
        for value in (required_main_title, required_subtitle)
        if value
    }
    exact_items = [
        item for item in exact_items
        if normalize_signature_text(item) not in title_signatures
    ]
    flexible_items = normalize_prompt_items(page.get("display_flexible", []))
    explicit_flexible_story = str(page.get("flexible_story") or "").strip()
    flexible_story = explicit_flexible_story or " ".join(flexible_items)
    visual_quality_intent = str(page.get("visual_quality_intent") or "").strip()
    relationship_synthesis_brief = page_relationship_thesis(page)
    art_directed = (
        seed.get("art_direction_contract_version")
        == ART_DIRECTION_CONTRACT_VERSION
    )
    relationship_directed = bool(relationship_synthesis_brief)

    seen_prompt_items = {
        normalize_signature_text(item) for item in exact_items + flexible_items
    }
    # These are already the content director's short ImageGen-facing semantic
    # invariants, not the full compliance contract. Keep them even for
    # art-directed pages: flexible_story preserves meaning, but it cannot
    # replace exact hierarchy, causality, or exclusion constraints.
    semantic_guardrails = dedupe_prompt_items(
        page.get("prompt_semantic_guardrails") or [], seen_prompt_items
    )
    user_constraints = dedupe_prompt_items(
        page.get("prompt_user_constraints") or [], seen_prompt_items
    )

    language = resolve_job_language(job)
    locale_contract = dict(page)
    locale_contract["language"] = language
    use_chinese_control = content_contract_prompt_locale(locale_contract) == "zh"
    compact_fast8 = (
        job.get("run_mode") == FAST8_MODE
        and (job.get("worker_receipt") or {}).get("contract_version")
        == FAST8_WORKER_RECEIPT_CONTRACT_VERSION
    )
    opening = slide_prompt_opening_v4(
        job, has_exact_copy=bool(exact_items or required_main_title)
    )
    opening += (
        "视觉手段自由选择，只保留真正帮助理解内容的部分。"
        if use_chinese_control
        else " Choose visual methods freely and retain only what helps explain the content."
    )
    sections = [opening]
    if required_main_title:
        sections.append(
            (
                "逐字主标题（当前页唯一主标题，不得用附件、参考图或正文中的其他文字替换）："
                + required_main_title
                if use_chinese_control
                else (
                    "Exact main title (the sole main title for this page; do not replace it "
                    "with copy from attachments, references, or body content): "
                    + required_main_title
                )
            )
        )
    if required_subtitle:
        sections.append(
            (
                "逐字副标题（仅作为当前页副标题）：" + required_subtitle
                if use_chinese_control
                else "Exact subtitle (use only as this page's subtitle): " + required_subtitle
            )
        )
    else:
        sections.append(
            (
                "当前页没有授权副标题；不得从附件或参考图补写、复制副标题。"
                if use_chinese_control
                else (
                    "No subtitle is authorized for this page; do not add or copy one from "
                    "attachments or references."
                )
            )
        )
    if visual_quality_intent:
        sections.append(
            (
                "审美与完成度意图：" + visual_quality_intent
                if use_chinese_control
                else "Aesthetic and finish intent: " + visual_quality_intent
            )
        )
    language_brief = language_presentation_prompt(
        page, use_chinese_control=use_chinese_control
    )
    if language_brief:
        sections.append(
            ("语言呈现：" if use_chinese_control else "Language presentation: ")
            + language_brief
        )
    if exact_items:
        if relationship_directed or art_directed:
            required_label = (
                "文字锚点（逐字准确，仅用于命名，不代表组件清单）"
                if use_chinese_control
                else (
                    "Exact text anchors (for naming only; not a component list)"
                )
            )
            separator = "；" if use_chinese_control else "; "
            sections.append(required_label + ": " + separator.join(exact_items))
        else:
            required_label = (
                "需逐字准确上屏" if use_chinese_control else "Exact on-slide copy"
            )
            sections.append(required_label + ":\n- " + "\n- ".join(exact_items))
    if flexible_story:
        if relationship_directed or art_directed:
            flexible_label = (
                "内容简报（完整传达原意；优先由视觉关系承担解释，文字可适度压缩）"
                if use_chinese_control
                else (
                    "Content brief (preserve all meaning; prefer visual relationships, "
                    "with concise wording)"
                )
            )
            sections.append(flexible_label + ": " + flexible_story)
        else:
            flexible_label = (
                "说明性内容（保持原意，可适度压缩措辞）"
                if use_chinese_control
                else "Required meaning (may be concisely rephrased)"
            )
            sections.append(flexible_label + ":\n- " + flexible_story)
    if semantic_guardrails:
        label = (
            "最高优先级语义护栏"
            if use_chinese_control
            else "Highest-priority semantic guardrails"
        )
        separator = "；" if use_chinese_control else "; "
        guardrail_text = (
            label
            + ": "
            + separator.join(
                item.rstrip("。.;；") or item for item in semantic_guardrails
            )
        )
        guardrail_text += (
            "。这些护栏优先于视觉命题；不得用连线、箭头、树枝、嵌套或空间从属补出来源未明确给出的关系。"
            if use_chinese_control
            else (
                ". These guardrails override the visual thesis; do not invent an unstated "
                "relationship through lines, arrows, branches, nesting, or spatial subordination."
            )
        )
        sections.append(guardrail_text)
    if user_constraints:
        label = "用户约束" if use_chinese_control else "User constraints"
        separator = "；" if use_chinese_control else "; "
        sections.append(
            label
            + ": "
            + separator.join(
                item.rstrip("。.;；") or item for item in user_constraints
            )
        )

    if global_chrome.get("applies") is True:
        brief = global_chrome.get("prompt_brief")
        if not isinstance(brief, str) or not brief.strip():
            raise SystemExit("global chrome 已启用但缺少短编译 prompt_brief")
        sections.append(
            ("全稿标题系统：" if use_chinese_control else "Deck title system: ")
            + brief.strip()
        )

    if use_chinese_control:
        tone = TONE_PROMPT_LABELS.get(job.get("tone"), str(job.get("tone", "")))
    else:
        tone = {
            "dark": "dark background",
            "light": "light background",
        }.get(job.get("tone"), str(job.get("tone", "")))
    locale = "zh" if use_chinese_control else "en"
    if uses_unified_spatial_standard(page):
        breathing = UNIFIED_SPATIAL_PROMPT_CUES[locale]
    else:
        profile = page["spatial_pressure_profile"]
        breathing = QUICK8_BREATHING_PROMPT_CUES[locale][profile]
    sections.append(
        f"视觉设定：{tone}；{breathing}"
        if use_chinese_control
        else f"Visual setting: {tone}; {breathing}"
    )

    if relationship_synthesis_brief and not compact_fast8:
        sections.append(
            (
                "关系综合：先让观众看见页级关系，再安放文字；视觉负责解释，文字负责"
                "命名。除非内容确实要求逐项并列，不要把合同条目默认映射为等权组件。页级关系："
                + relationship_synthesis_brief
                if use_chinese_control
                else (
                    "Relationship synthesis: make the page relationship visible before placing "
                    "copy; let the visual explain and use text mainly for naming. Unless the content "
                    "truly requires item-by-item parity, do not default contract entries to equal "
                    "components. Page relationship: "
                    + relationship_synthesis_brief
                )
            )
        )

    if seed.get("first_impression") and not compact_fast8:
        impression = seed["first_impression"]
        impression_terminal = (
            ""
            if impression.endswith(("。", ".", "！", "!", "？", "?"))
            else ("。" if use_chinese_control else ".")
        )
        sections.append(
            (
                f"第一印象：{impression}{impression_terminal}"
                "它只说明观众首先应感受到或理解什么，不规定版式、媒介或构图。"
                if use_chinese_control
                else (
                    f"First impression: {impression}{impression_terminal} "
                    "This only states what the audience should feel or understand first; "
                    "it does not prescribe layout, medium, or composition."
                )
            )
        )

    if art_directed and compact_fast8:
        visual_thesis = str(seed.get("visual_thesis") or "").strip()
        craft_axis = str(seed.get("craft_axis") or "").strip()
        visual_activity_mode = str(seed.get("visual_activity_mode") or "").strip()
        attention_strategy = str(seed.get("attention_strategy") or "").strip()
        representation_family = str(
            seed.get("relationship_representation_family") or ""
        ).strip()
        spatial_topology = seed.get("spatial_topology") or {}
        topology_intent = str(
            spatial_topology.get("spatial_topology_intent") or ""
        ).strip() if isinstance(spatial_topology, dict) else ""
        if (
            not relationship_synthesis_brief
            or not visual_thesis
            or not craft_axis
            or visual_activity_mode not in VISUAL_ACTIVITY_MODES
            or not attention_strategy
            or not representation_family
        ):
            raise SystemExit("新 Fast8 紧凑导演提示缺少关系、表达家族、视觉命题、注意力或工艺轴")
        activity_label = {
            "restrained": "克制",
            "balanced": "平衡",
            "expressive": "有表现力",
        }[visual_activity_mode]
        sections.append(
            (
                "页面导演：页级关系=" + relationship_synthesis_brief
                + "；关系表达家族=" + representation_family
                + ("；空间关系=" + topology_intent if topology_intent else "")
                + "；本候选的可见命题=" + visual_thesis
                + "；注意力=" + attention_strategy
                + "；视觉活跃度=" + activity_label
                + "；图像工艺=" + craft_axis
                + "。用一个主导关系统领；叙事层数控制为一条主关系加一层安静证据；若同时存在系统清单、"
                "流程、KPI 或案例说明，必须整合进这同一证据层，不能并列争抢。"
                "不要把合同字段翻译成等权卡片、逐行清单或独立底部说明带。"
                "这些是开放导演要求，不规定固定版式；具象事实必须有来源支持。"
            )
            if use_chinese_control
            else (
                "Page direction: page relationship=" + relationship_synthesis_brief
                + "; relationship representation family=" + representation_family
                + ("; spatial relationship=" + topology_intent if topology_intent else "")
                + "; visible thesis=" + visual_thesis
                + "; attention=" + attention_strategy
                + "; visual activity=" + visual_activity_mode
                + "; image craft=" + craft_axis
                + ". Use one governing relationship and integrate other required information "
                "as one quiet evidence layer. If systems, process, KPIs, or case notes all exist, "
                "merge them into that same subordinate layer instead of giving them competing "
                "narrative chains. Do not translate contract fields into equal cards, row lists, "
                "or a separate bottom explainer band. These are open art-direction requirements, "
                "not a fixed layout; concrete facts require source support."
            )
        )
    elif art_directed:
        visual_thesis = str(seed.get("visual_thesis") or "").strip()
        style_family_thesis = str(seed.get("style_family_thesis") or "").strip()
        adaptation_principle = str(seed.get("adaptation_principle") or "").strip()
        continuity_invariants = normalize_prompt_items(
            seed.get("continuity_invariants") or []
        )
        craft_axis = str(seed.get("craft_axis") or "").strip()
        family_mode = bool(style_family_thesis)
        if (not visual_thesis and not family_mode) or not craft_axis:
            raise SystemExit(
                "art direction v1 图片提示缺少 visual_thesis/style_family_thesis 或 craft_axis"
            )
        if visual_thesis:
            sections.append(
                (
                    "本候选的可见视觉命题：" + visual_thesis
                    if use_chinese_control
                    else "Candidate visual thesis: " + visual_thesis
                )
            )
        if family_mode:
            if not adaptation_principle or len(continuity_invariants) < 2:
                raise SystemExit(
                    "4x3 视觉家族提示缺少 adaptation_principle 或 continuity_invariants"
                )
            family_text = (
                "视觉家族：" + style_family_thesis
                + "；跨页适配：" + adaptation_principle
                + "；连续性不变量：" + "；".join(continuity_invariants)
                + "。视觉家族负责色彩、字体气质、材质、图像工艺与完成度；"
                "当前页 relationship_thesis 负责本页关系。继承家族但不得复制锚点构图。"
                if use_chinese_control
                else (
                    "Visual family: " + style_family_thesis
                    + "; cross-page adaptation: " + adaptation_principle
                    + "; continuity invariants: " + "; ".join(continuity_invariants)
                    + ". The family governs color, typographic character, material treatment, "
                    "image craft and finish; the current page relationship thesis governs this "
                    "page. Preserve the family without copying the anchor composition."
                )
            )
            sections.append(family_text)
        visual_activity_mode = str(seed.get("visual_activity_mode") or "").strip()
        attention_strategy = str(seed.get("attention_strategy") or "").strip()
        if visual_activity_mode or attention_strategy:
            if visual_activity_mode not in VISUAL_ACTIVITY_MODES or not attention_strategy:
                raise SystemExit(
                    "art direction v1 注意力合同必须同时包含有效 visual_activity_mode "
                    "与 attention_strategy"
                )
            sections.append(VISUAL_ACTIVITY_PROMPT_CUES[locale][visual_activity_mode])
            sections.append(
                (
                    "注意力策略：" + attention_strategy
                    if use_chinese_control
                    else "Attention strategy: " + attention_strategy
                )
            )
            sections.append(ATTENTION_CONSOLIDATION_PROMPT_CUES[locale])
        representation_family = str(
            seed.get("relationship_representation_family") or ""
        ).strip()
        spatial_topology = seed.get("spatial_topology") or {}
        topology_intent = (
            str(spatial_topology.get("spatial_topology_intent") or "").strip()
            if isinstance(spatial_topology, dict)
            else ""
        )
        if representation_family:
            sections.append(
                (
                    "关系表达家族：" + representation_family
                    + ("；空间关系意图：" + topology_intent if topology_intent else "")
                    if use_chinese_control
                    else "Relationship representation family: " + representation_family
                    + ("; spatial relationship intent: " + topology_intent if topology_intent else "")
                )
            )
        sections.append(NARRATIVE_COMPRESSION_PROMPT_CUES[locale])
        sections.append(CONTENT_VISUAL_INTEGRATION_PROMPT_CUES[locale])
        sections.append(
            (
                "图像工艺与材质导演：" + craft_axis
                if use_chinese_control
                else "Image craft and material direction: " + craft_axis
            )
        )
        sections.append(
            (
                "视觉命题、视觉家族与工艺轴都是开放启发，不是固定版式或组件清单；具体构图由你决定。"
                "不得让视觉隐喻暗示未提供的真实产品、项目或交付事实；具有特定事实指向的"
                "具象对象只在来源或附件支持时使用。"
                if use_chinese_control
                else (
                    "The visual thesis and craft axis are open prompts, not a fixed layout or component "
                    "list; decide the composition freely. Do not let visual metaphors imply unsupported "
                    "real products, projects, or delivery facts; use concrete subjects with specific "
                    "factual implications only when supported by sources or attachments."
                )
            )
        )
    elif seed.get("layout_contract_version") == CURRENT_FAST8_LAYOUT_VERSION:
        impulse = seed.get("creative_impulse")
        if not isinstance(impulse, str) or not impulse.strip():
            raise SystemExit("Fast8 v7 图片提示缺少 creative_impulse")
        impulse = impulse.strip()
        impulse_terminal = (
            ""
            if impulse.endswith(("。", ".", "！", "!", "？", "?"))
            else ("。" if use_chinese_control else ".")
        )
        sections.append(
            (
                f"开放性创作启发：{impulse}{impulse_terminal}"
                "把它作为扩张视觉性格与空间节奏的起点；不要把它理解为固定版式、"
                "组件清单或必须复刻的构图。"
                if use_chinese_control
                else (
                    f"Open creative impulse: {impulse}{impulse_terminal} "
                    "Use it to expand the slide's visual character and spatial rhythm; "
                    "do not treat it as a fixed layout, component list, or composition to copy."
                )
            )
        )
    reference_images = job.get("reference_images", [])
    if reference_images:
        borrow_items: list[str] = []
        avoid_items: list[str] = []
        borrow_seen: set[str] = set()
        avoid_seen: set[str] = set()
        for item in reference_images:
            if not isinstance(item, dict):
                continue
            raw_intent = item.get("reference_intent")
            if isinstance(raw_intent, dict):
                raw_borrow = raw_intent.get("borrow")
                raw_avoid = raw_intent.get("do_not_copy")
            else:
                raw_borrow = raw_intent or item.get("borrow")
                raw_avoid = item.get("do_not_copy")
            for value in normalize_prompt_items(raw_borrow):
                signature = normalize_signature_text(value)
                if signature not in borrow_seen and len(borrow_items) < 3:
                    borrow_items.append(value)
                    borrow_seen.add(signature)
            for value in normalize_prompt_items(raw_avoid):
                signature = normalize_signature_text(value)
                if signature not in avoid_seen and len(avoid_items) < 2:
                    avoid_items.append(value)
                    avoid_seen.add(signature)
        separator = "、" if use_chinese_control else ", "
        borrow = separator.join(borrow_items)
        avoid = separator.join(avoid_items)
        attachment_range = (
            "附件1" if len(reference_images) == 1 else f"附件1–{len(reference_images)}"
        )
        attachment_range_en = (
            "attachment 1"
            if len(reference_images) == 1
            else f"attachments 1–{len(reference_images)}"
        )
        if use_chinese_control:
            line = f"风格参考（{attachment_range}）：只借鉴核心感觉——{borrow or '整体视觉气质'}"
            line += "；不要继承具体构图、版式、信息结构或原文内容"
            if avoid:
                line += f"；另外避免复制{avoid}"
            line += "；本页标题、事实、对象和关系只来自当前页内容合同"
        else:
            line = (
                f"Style references ({attachment_range_en}): borrow only "
                f"the core feel—{borrow or 'overall visual character'}; do not inherit "
                "specific composition, layout, information structure, or original content"
            )
            if avoid:
                line += f"; also avoid copying {avoid}"
            line += (
                "; take this page's title, facts, subjects, and relationships only from "
                "the current-page content contract"
            )
        sections.append(line + ".")
    elif (
        job.get("run_mode") == FAST8_MODE
        and job.get("imagegen_prompt_contract_version")
        == CURRENT_FAST8_IMAGEGEN_PROMPT_VERSION
    ):
        sections.append(
            (
                "没有风格参考图时，自主建立成熟、有鲜明视觉签名的设计语言，"
                "使整体工艺与细节达到高水平成品，而不是默认企业信息图组件的简单拼装。"
            )
            if use_chinese_control
            else (
                "With no style reference, establish a mature design language with a distinct "
                "visual signature and highly finished craft, rather than a simple assembly "
                "of default corporate-infographic components."
            )
        )

    asset_lines = []
    evidence_lines = []
    asset_start = len(reference_images) + 1
    for offset, item in enumerate(job.get("required_assets", [])):
        role = None if isinstance(item, str) else item.get("role")
        attachment_number = asset_start + offset
        normalized_role = normalized_asset_role_key(role)
        if normalized_role in EVIDENCE_ASSET_ROLES:
            evidence_use = (
                str(item.get("use") or "").strip()
                if isinstance(item, dict)
                else ""
            )
            evidence_lines.append(
                (
                    f"附件{attachment_number}={role}。"
                    "角色中明确要求保留的事实、品牌、对象与关系优先于通用版式规则；"
                    + (
                        f"只用于以下证据用途：{evidence_use}；"
                        if evidence_use
                        else "只用于内容合同明确要求的事实、品牌、对象与关系；"
                    )
                    + "不得继承附件标题、正文、页面结论、构图、容器、底栏或视觉风格。"
                    "若关系约束收紧了空间自由，仍须用本候选的主入口、证据依附方式和"
                    "视觉重心形成可见差异，不把证据页当作风格模板。"
                )
                if use_chinese_control
                else (
                    f"Attachment {attachment_number}={role}. "
                    "Explicitly required facts, brand elements, subjects, and relationships "
                    "take priority over generic layout rules; "
                    + (
                        f"Use it only for this evidence purpose: {evidence_use}; "
                        if evidence_use
                        else (
                            "use it only for facts, brand elements, subjects, and relationships "
                            "explicitly required by the content contract; "
                        )
                    )
                    + "do not inherit its title, body copy, page conclusion, composition, "
                    "containers, bottom band, or visual style. If those relationships narrow "
                    "spatial freedom, preserve them while making this candidate's entry, "
                    "evidence attachment, and visual emphasis visibly distinct. Do not treat "
                    "the evidence page as a style template."
                )
            )
        else:
            asset_use = (
                str(item.get("use") or "").strip()
                if isinstance(item, dict)
                else ""
            )
            asset_line = (
                f"附件{attachment_number}={role or '必要资产'}"
                if use_chinese_control
                else f"Attachment {attachment_number}={role or 'required asset'}"
            )
            if asset_use:
                asset_line += (
                    f"；用途：{asset_use}"
                    if use_chinese_control
                    else f"; use: {asset_use}"
                )
            asset_lines.append(asset_line)
    if asset_lines:
        sections.append(
            (
                "资产：" + "；".join(asset_lines) + "；按角色原样使用，不重绘、不变形。"
                if use_chinese_control
                else (
                    "Assets: " + "; ".join(asset_lines)
                    + "; use them faithfully in their stated roles without redrawing or distortion."
                )
            )
        )
    if evidence_lines:
        sections.append(
            ("证据附件：" if use_chinese_control else "Evidence attachments: ")
            + (" ".join(evidence_lines))
        )

    sections.append(
        "其余视觉决策保持开放。"
        if use_chinese_control
        else "Keep all other visual decisions open."
    )
    prompt = finalize_imagegen_prompt("\n\n".join(sections))
    if required_main_title and required_main_title not in prompt:
        raise SystemExit("逐字主标题未进入最终 ImageGen prompt")
    if required_subtitle and required_subtitle not in prompt:
        raise SystemExit("逐字副标题未进入最终 ImageGen prompt")
    return prompt


def compile_quick8_v5_prompt(job: dict[str, Any]) -> str:
    """兼容旧调用名；新代码统一使用 compile_minimal_prompt_v4。"""

    return compile_minimal_prompt_v4(job)


def compile_compact_prompt_v3(job: dict[str, Any]) -> str:
    """保留既有 v3 提示语义，供 Fast/Strict 与旧 Quick8 恢复。"""

    page = job["anchor_page"]
    raw_display = page.get("display_required", page.get("required_content", []))
    display_items = raw_display if isinstance(raw_display, list) else [raw_display]
    display_items = [str(item).strip() for item in display_items if str(item).strip()]
    seed = job.get("layout_direction") or job.get("exploration_seed")

    semantic_guardrails = list(page.get("prompt_semantic_guardrails") or [])
    if seed and seed.get("layout_specific_guardrail"):
        semantic_guardrails.append(seed["layout_specific_guardrail"])
    semantic_guardrails = list(dict.fromkeys(item.strip() for item in semantic_guardrails))
    user_constraints = list(
        dict.fromkeys(
            item.strip() for item in (page.get("prompt_user_constraints") or [])
        )
    )

    language = resolve_job_language(job)
    use_chinese_control = language.lower().startswith("zh")
    opening = slide_prompt_opening(
        job, polished=bool(seed and seed.get("layout_contract_version") == 4)
    )
    if seed and seed.get("layout_contract_version") == 4:
        opening += (
            "视觉手段自由选择，只保留真正帮助理解内容的部分。"
            if use_chinese_control
            else " Choose visual methods freely and retain only what helps explain the content."
        )
    required_label = "准确上屏" if use_chinese_control else "Required on-slide copy"
    sections = [opening, required_label + ":\n- " + "\n- ".join(display_items)]
    if semantic_guardrails:
        label = "语义护栏" if use_chinese_control else "Semantic guardrails"
        sections.append(label + ": " + "；".join(semantic_guardrails))
    if user_constraints:
        label = "用户约束" if use_chinese_control else "User constraints"
        sections.append(label + ": " + "；".join(user_constraints))

    tone = TONE_PROMPT_LABELS.get(job.get("tone"), str(job.get("tone", "")))
    profile = page["spatial_pressure_profile"]
    sections.append(
        f"视觉设定：{tone}；{SPATIAL_PROMPT_CUES[profile]}{GROUPING_PROMPT_CUE}"
    )
    if (job.get("candidate_policy") or {}).get("low_spatial_preference_is_soft"):
        sections.append(
            "空间偏好是软目标：信息较密时，以完整准确、清晰可读和层级有序为先，"
            "不得为追求 Low 留白而删减、缩小或弱化必显内容。"
        )

    if seed and seed.get("layout_contract_version") == 3:
        sections.append(
            "导演方向："
            f"版式—{seed['layout_variant']}；"
            f"动线—{seed['reading_path']}；"
            f"重心—{seed['visual_emphasis']}；"
            f"图文—{seed['image_text_strategy']}。"
        )
    elif seed and seed.get("layout_contract_version") == 4:
        sections.append(
            f"创意方向：{seed['creative_direction']}。"
            "这是软性启发，不是必须复刻的版式合同。"
        )

    reference_lines = []
    reference_images = job.get("reference_images", [])
    for index, item in enumerate(reference_images, start=1):
        if not isinstance(item, dict):
            reference_lines.append(f"附件{index}仅作视觉参考，不复刻内容或版式")
            continue
        raw_intent = item.get("reference_intent")
        if isinstance(raw_intent, dict):
            intent = compact_prompt_value(raw_intent.get("borrow"))
            do_not_copy = compact_prompt_value(raw_intent.get("do_not_copy"))
        else:
            intent = compact_prompt_value(raw_intent or item.get("borrow"))
            do_not_copy = compact_prompt_value(item.get("do_not_copy"))
        line = f"附件{index}"
        line += f"借鉴{intent}" if intent else "仅作视觉参考"
        line += f"，不复刻{do_not_copy}" if do_not_copy else "，不复刻内容或版式"
        reference_lines.append(line)
    if reference_lines:
        sections.append("参考：" + "；".join(reference_lines) + "。")

    asset_lines = []
    asset_start = len(reference_images) + 1
    for offset, item in enumerate(job.get("required_assets", [])):
        role = None if isinstance(item, str) else item.get("role")
        asset_lines.append(f"附件{asset_start + offset}={role or '必要资产'}")
    if asset_lines:
        sections.append(
            "资产：" + "；".join(asset_lines) + "；按角色原样使用，不重绘、不变形。"
        )

    sections.append(
        "除上述要求外，媒介、材质、细节与局部尺度自由；"
        "Takeaway仅在提供新结论时使用。"
    )
    return "\n\n".join(sections)


def compile_anchor_imagegen_prompt(job: dict[str, Any]) -> str:
    """把推理合同压缩成图片模型需要的最终提示，Worker 不再二次编译。"""

    page = job["anchor_page"]
    if page.get("prompt_contract_version") == 4:
        seed = job.get("layout_direction") or job.get("exploration_seed") or {}
        if seed.get("layout_contract_version") not in {
            CURRENT_QUICK_LAYOUT_VERSION,
            CURRENT_FAST8_LAYOUT_VERSION,
            CURRENT_4X3_LAYOUT_VERSION,
        }:
            raise SystemExit(
                "prompt_contract_version=4 只允许配套 Quick8 layout v5、"
                "Fast8 layout v7 或 4x3 layout v6"
            )
        return compile_minimal_prompt_v4(job)
    if page.get("prompt_contract_version") == 3:
        return compile_compact_prompt_v3(job)

    display = page.get("display_required", page.get("required_content"))
    semantic = page.get("semantic_invariants") or []
    forbidden = page.get("forbidden_interpretations") or []
    brief = page.get("spatial_generation_brief", page.get("spatial_breathing", ""))
    support = page.get("visual_support_goal", page.get("display_supporting", ""))
    reference_intents = []
    for item in job.get("reference_images", []):
        if not isinstance(item, dict):
            continue
        intent = {
            key: item.get(key)
            for key in ("reference_intent", "borrow", "do_not_copy")
            if item.get(key)
        }
        if intent:
            reference_intents.append(intent)
    seed = job.get("layout_direction") or job.get("exploration_seed")
    asset_roles = [
        {
            "path": item if isinstance(item, str) else item.get("path"),
            "role": None if isinstance(item, str) else item.get("role"),
        }
        for item in job.get("required_assets", [])
    ]
    if seed and seed.get("layout_contract_version") == 3:
        display_items = display if isinstance(display, list) else [display]
        guardrails = list(seed.get("shared_prompt_guardrails") or [])
        if seed.get("layout_specific_guardrail"):
            guardrails.append(seed["layout_specific_guardrail"])
        sections = [
            (
                slide_prompt_opening(job)
                + "随请求提供的品牌/Logo 资产必须原样使用，不得重绘、变形或替换。"
            ),
            "必须准确上屏：\n- " + "\n- ".join(str(item) for item in display_items),
        ]
        if guardrails:
            sections.append("关键语义护栏：\n- " + "\n- ".join(guardrails))
        direction = [
            f"背景：{job['tone']}",
            f"用户要求：{job['overall_requirements']}",
            f"母结构：{seed['mother_structure']}；本席位变体：{seed['layout_variant']}",
            f"阅读路径：{seed['reading_path']}",
            f"视觉重心：{seed['visual_emphasis']}",
            f"图文关系：{seed['image_text_strategy']}",
        ]
        if reference_intents:
            direction.append("参考图只借鉴：" + json.dumps(reference_intents, ensure_ascii=False))
        if job.get("reference_images"):
            direction.append("参考图只提供画风、质感和工艺证据，不复制其单页骨架。")
        if asset_roles:
            direction.append("必要资产及角色：" + json.dumps(asset_roles, ensure_ascii=False))
        sections.append("导演方向：\n- " + "\n- ".join(direction))
        sections.append(
            "严格实现本席位的版式变体，但不要把方向扩写成更多模板规则。"
            "其余媒介、材质、细节、局部尺度和视觉隐喻可自由发挥；"
            "Takeaway 仅在产生新增结论时出现，不默认添加底栏。"
        )
        return "\n\n".join(sections)

    sections = [
        slide_prompt_opening(job)
        + "严格使用随请求提供的品牌/Logo 资产，不得重绘、变形或替换。",
    ]
    if seed and seed.get("layout_contract_version") == 2:
        sections.append(
            "本席位强制构图基因（优先于常规商务 PPT 版式习惯）：\n"
            f"- 构图家族：{seed['family_name']}（{seed['family_id']}）\n"
            f"- 构图拓扑：{seed['composition_topology']}\n"
            f"- 阅读入口：{seed['reading_entry']}\n"
            f"- 空间分布：{seed['spatial_distribution']}\n"
            f"- 容器策略：{seed['container_policy']}\n"
            f"- 视觉语言：{seed['visual_language']}\n"
            f"- 必须避让：{seed['must_avoid']}\n"
            f"- 语义转译：{seed['semantic_translation_rule']}\n"
            f"- 组合覆盖：本轮其他候选会覆盖 {json.dumps(seed['portfolio_context'], ensure_ascii=False)}；"
            "你必须坚持当前构图家族，不得漂移到其中其他家族或常见双栏模板。\n"
            f"- 防收敛规则：{seed['anti_convergence']}"
        )
    sections.append(
        "必须准确呈现以下文字与内容义务：\n" + json.dumps(display, ensure_ascii=False)
    )
    if semantic:
        sections.append("必须保持的事实关系：" + json.dumps(semantic, ensure_ascii=False))
    if forbidden:
        sections.append("不得误解为：" + json.dumps(forbidden, ensure_ascii=False))
    direction = [
        f"背景明暗：{job['tone']}",
        f"总体要求：{job['overall_requirements']}",
        f"空间要求：{brief}",
        f"视觉支持目标：{support}",
        f"工艺目标：{page.get('craft_ambition', job.get('craft_ambition', '成品级、细节统一、避免粗糙草稿感'))}",
    ]
    if reference_intents:
        direction.append("参考图借鉴意图：" + json.dumps(reference_intents, ensure_ascii=False))
    if job.get("reference_images"):
        direction.append(
            "参考图使用边界：借鉴整体视觉语言、质感、密度和工艺；除非用户明确要求复刻版式，"
            "不得复制参考图的单页构图，且本席位 v2 构图基因优先于参考图的空间骨架。"
        )
    if asset_roles:
        direction.append("必要资产及角色：" + json.dumps(asset_roles, ensure_ascii=False))
    if seed and seed.get("layout_contract_version") == 2:
        direction.extend(
            [
                f"本席位构图家族：{seed['family_name']}",
                f"本席位视觉语言：{seed['visual_language']}",
                f"再次强调必须避让：{seed['must_avoid']}",
            ]
        )
    elif seed:
        direction.extend(
            [
                f"本席位阅读入口：{seed['reading_entry']}",
                f"本席位空间性格：{seed['spatial_character']}",
                f"本席位工艺性格：{seed['craft_character']}",
                seed["anti_convergence"],
            ]
        )
    sections.append("视觉方向：\n- " + "\n- ".join(direction))
    sections.append(
        "内容区的具体构图、媒介、尺度、图像表达、关系可视化与阅读路径由你自主决定。"
        "但必须服从本席位的构图拓扑。语义等权不要求几何对称，严格网格不要求左右分栏。"
        "追求精致、成熟、有辨识度、非模板化的单页；Takeaway 只在确有新增结论价值时出现，不默认制作底栏。"
    )
    return "\n\n".join(sections)


def merge_attachment_items(*groups: Any) -> list[Any]:
    """按首次出现顺序合并附件，避免同一路径重复传给图片后端。"""

    merged: list[Any] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            path = item if isinstance(item, str) else item.get("path")
            if not isinstance(path, str) or not path.strip():
                continue
            normalized = str(Path(path).expanduser().resolve())
            if normalized in seen:
                continue
            seen.add(normalized)
            if isinstance(item, str):
                merged.append(normalized)
            else:
                normalized_item = dict(item)
                normalized_item["path"] = normalized
                merged.append(normalized_item)
    return merged


def global_chrome_applies(contract: dict[str, Any], page_id: Any) -> bool:
    """Return whether a source-authorized deck chrome contract governs this page."""

    deck = contract.get("deck_title_system") or {}
    if deck.get("enabled") is not True:
        return False
    scope = deck.get("scope") or {}
    raw_include = scope.get("include_page_ids") or []
    raw_exclude = scope.get("exclude_page_ids") or []
    include = normalize_page_ids(raw_include) if raw_include else []
    exclude = normalize_page_ids(raw_exclude) if raw_exclude else []
    page_key = canonical_page_id(page_id)
    if page_key in {canonical_page_id(value) for value in exclude}:
        return False
    return not include or page_key in {canonical_page_id(value) for value in include}


def read_global_chrome_contract(
    path_value: str | Path,
    *,
    verify_authorization_source: bool = True,
) -> tuple[Path, dict[str, Any], str]:
    """Load a deck-wide chrome contract and optionally verify its live authority.

    The live authorization source is checked when the compiled contract is first bound.
    Downstream stages may skip that second live-file check only when their caller also
    verifies the already-bound contract SHA. Page/supporting-source drift remains a
    separate gate, so unrelated edits cannot invalidate an immutable compiled contract.
    """

    path = Path(path_value).expanduser().resolve()
    contract = read_json(path)
    if contract.get("global_chrome_contract_version") != GLOBAL_CHROME_CONTRACT_VERSION:
        raise SystemExit(
            f"global chrome contract 必须为 v{GLOBAL_CHROME_CONTRACT_VERSION}：{path}"
        )
    authorization = contract.get("authorization") or {}
    if authorization.get("status") != "authorized":
        raise SystemExit("global chrome contract 缺少 status=authorized 的来源授权")
    source_kind = authorization.get("source_kind")
    if source_kind not in GLOBAL_CHROME_AUTHORIZATION_KINDS:
        raise SystemExit(
            "global chrome authorization.source_kind 必须来自当前用户要求、权威大纲、"
            "已确认全稿设计系统或指定 master/reference image"
        )
    source_path_value = authorization.get("source_path")
    source_sha = authorization.get("source_sha256")
    if source_kind != "current_user_requirement":
        if not isinstance(source_path_value, str) or not source_path_value.strip():
            raise SystemExit("global chrome 来源授权缺少 source_path")
        source_path = Path(source_path_value).expanduser().resolve()
        if verify_authorization_source:
            if not source_path.is_file():
                raise SystemExit(f"global chrome 授权来源不存在：{source_path}")
            if not isinstance(source_sha, str) or file_sha256(source_path) != source_sha:
                raise SystemExit("global chrome 授权来源 SHA-256 不匹配")
    elif not isinstance(authorization.get("authorization_text"), str) or not str(
        authorization.get("authorization_text")
    ).strip():
        raise SystemExit("current_user_requirement 必须记录非空 authorization_text")

    deck = contract.get("deck_title_system")
    if not isinstance(deck, dict):
        raise SystemExit("global chrome contract 缺少 deck_title_system")
    require_keys(
        deck,
        [
            "enabled",
            "scope",
            "logo",
            "main_title",
            "subtitle_policy",
            "prompt_briefs",
            "qa_required",
            "qa_checks",
        ],
        "deck_title_system",
    )
    if not isinstance(deck.get("scope"), dict):
        raise SystemExit("deck_title_system.scope 必须是对象")
    for field in ("include_page_ids", "exclude_page_ids"):
        values = (deck.get("scope") or {}).get(field, [])
        if not isinstance(values, list):
            raise SystemExit(f"deck_title_system.scope.{field} 必须是数组")
    logo = deck.get("logo") or {}
    if not isinstance(logo, dict) or not isinstance(logo.get("required"), bool):
        raise SystemExit("deck_title_system.logo.required 必须显式为 true|false")
    if logo.get("required") is True:
        assets = logo.get("assets_by_tone")
        if not isinstance(assets, dict):
            raise SystemExit("标题系统要求 Logo 时必须提供 assets_by_tone")
        for tone in ("dark", "light"):
            item = assets.get(tone)
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise SystemExit(f"deck_title_system.logo.assets_by_tone.{tone} 缺少 path")
            if not Path(item["path"]).expanduser().resolve().is_file():
                raise SystemExit(f"标题系统 {tone} Logo 不存在：{item['path']}")
    main_title = deck.get("main_title") or {}
    if not isinstance(main_title, dict) or not isinstance(
        main_title.get("required"), bool
    ):
        raise SystemExit(
            "deck_title_system.main_title.required 必须显式为 true|false"
        )
    if main_title.get("required") is True:
        title_text = main_title.get("text")
        title_map = main_title.get("text_by_page")
        has_default = isinstance(title_text, str) and bool(title_text.strip())
        has_page_map = (
            isinstance(title_map, dict)
            and bool(title_map)
            and all(
                isinstance(key, str)
                and key.strip()
                and isinstance(value, str)
                and value.strip()
                for key, value in title_map.items()
            )
        )
        if not has_default and not has_page_map:
            raise SystemExit(
                "标题系统要求主标题时 main_title.text 或 text_by_page "
                "必须提供非空标题"
            )
        if has_page_map:
            include_ids = (deck.get("scope") or {}).get("include_page_ids") or []
            exclude_ids = (deck.get("scope") or {}).get("exclude_page_ids") or []
            uncovered = [
                str(page_id)
                for page_id in include_ids
                if not any(page_ids_match(page_id, excluded) for excluded in exclude_ids)
                and not has_default
                and not any(page_ids_match(page_id, key) for key in title_map)
            ]
            if uncovered:
                raise SystemExit(
                    "main_title.text_by_page 未覆盖适用页：" + ",".join(uncovered)
                )
    briefs = deck.get("prompt_briefs") or {}
    if not isinstance(briefs, dict):
        raise SystemExit("deck_title_system.prompt_briefs 必须是对象")
    for locale in ("zh", "en"):
        brief = briefs.get(locale)
        if not isinstance(brief, str) or not brief.strip() or len(brief.strip()) > 360:
            raise SystemExit(
                f"deck_title_system.prompt_briefs.{locale} 必须是 1–360 字的短编译模块"
            )
    checks = deck.get("qa_checks")
    if not isinstance(checks, list) or not checks or not all(
        isinstance(item, str) and item.strip() for item in checks
    ):
        raise SystemExit("deck_title_system.qa_checks 必须是非空字符串数组")
    return path, contract, file_sha256(path)


def global_chrome_projection(
    contract: dict[str, Any],
    *,
    contract_path: Path,
    contract_sha256: str,
    page_id: Any,
    style: str,
    tone: str,
    language: str,
) -> dict[str, Any]:
    """Compile one short page/job projection from a centrally authorized contract."""

    applies = global_chrome_applies(contract, page_id)
    deck = contract.get("deck_title_system") or {}
    locale = "zh" if normalize_output_language(language).lower().startswith("zh") else "en"
    result: dict[str, Any] = {
        "global_chrome_contract_version": GLOBAL_CHROME_CONTRACT_VERSION,
        "contract_path": str(contract_path),
        "contract_sha256": contract_sha256,
        "contract_id": contract.get("contract_id"),
        "applies": applies,
        "page_id": str(page_id),
        "style_slot": style,
        "tone": tone,
        "qa_required": bool(deck.get("qa_required")) and applies,
        "match_mode": "approximate",
        "logo_required": bool((deck.get("logo") or {}).get("required")),
        "main_title_required": bool((deck.get("main_title") or {}).get("required")),
    }
    if not applies:
        return result
    result["prompt_brief"] = str((deck.get("prompt_briefs") or {})[locale]).strip()
    result["qa_checks"] = list(deck.get("qa_checks") or [])
    projected_title = dict(deck.get("main_title") or {})
    title_map = projected_title.pop("text_by_page", None)
    if projected_title.get("required") is True and isinstance(title_map, dict):
        matched = [
            str(value).strip()
            for key, value in title_map.items()
            if page_ids_match(key, page_id)
            and isinstance(value, str)
            and value.strip()
        ]
        if len(matched) > 1:
            raise SystemExit(f"global chrome 页级标题重复匹配：{page_id}")
        if matched:
            projected_title["text"] = matched[0]
        elif not (
            isinstance(projected_title.get("text"), str)
            and projected_title["text"].strip()
        ):
            raise SystemExit(f"global chrome 缺少页 {page_id} 的主标题")
    result["main_title"] = projected_title
    result["subtitle_policy"] = deck.get("subtitle_policy")
    logo = deck.get("logo") or {}
    if logo.get("required") is True:
        item = dict((logo.get("assets_by_tone") or {})[tone])
        item["path"] = str(Path(item["path"]).expanduser().resolve())
        item["asset_type"] = "required_asset"
        item["role"] = GLOBAL_CHROME_ASSET_ROLE
        item["tones"] = [tone]
        item["styles"] = [style]
        result["logo_asset"] = item
    return result


def validate_page_global_chrome_compatibility(
    page: dict[str, Any], projection: dict[str, Any], context: str
) -> None:
    """Fail closed on page constraints that restate or contradict global deck chrome."""

    if projection.get("applies") is not True:
        return
    expected_title = page.get("page_title", page.get("title"))
    projected_title = (projection.get("main_title") or {}).get("text")
    if (
        projection.get("main_title_required") is True
        and isinstance(expected_title, str)
        and expected_title.strip()
        and isinstance(projected_title, str)
        and projected_title.strip()
        and projected_title.strip() != expected_title.strip()
    ):
        raise SystemExit(
            f"{context} 的 global chrome 主标题与内容合同标题不一致"
        )
    values = normalize_prompt_items(page.get("prompt_user_constraints") or [])
    joined = " ".join(values).lower()
    contradiction_patterns = (
        r"不(?:添加|使用|出现|要).*logo",
        r"不要.*logo",
        r"no\s+logo",
        r"without\s+(?:an?\s+)?logo",
    )
    if projection.get("logo_required") is True and any(
        re.search(pattern, joined, flags=re.IGNORECASE)
        for pattern in contradiction_patterns
    ):
        raise SystemExit(f"{context} 与已授权 global chrome contract 冲突：禁止删除必需 Logo")
    duplicate_markers = ("全稿标准标题区", "deck-wide title", "global chrome")
    if any(marker in joined for marker in duplicate_markers):
        raise SystemExit(
            f"{context} 不得在 prompt_user_constraints 重复全稿标题系统；"
            "请只保留 global_chrome_contract 的一次短编译"
        )


def non_global_chrome_assets(items: Any) -> list[Any]:
    """Keep deck-title assets out of shared page assets; they are re-routed per page."""

    result: list[Any] = []
    for item in items or []:
        role = item.get("role") if isinstance(item, dict) else None
        if isinstance(role, str) and role.strip().lower() == GLOBAL_CHROME_ASSET_ROLE:
            continue
        result.append(item)
    return result


def content_contract_asset_items(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Return page-local assets that the current page-job compilers actually route."""

    assets: list[dict[str, Any]] = []
    for field, asset_type in (("required_page_assets", "required_page_asset"),):
        values = contract.get(field) or []
        if not isinstance(values, list):
            raise SystemExit(f"内容合同字段 {field} 必须是数组")
        for item in values:
            if isinstance(item, str):
                assets.append({"path": item, "asset_type": asset_type, "role": field})
            elif isinstance(item, dict):
                assets.append(
                    {
                        **item,
                        "asset_type": item.get("asset_type") or asset_type,
                        "role": item.get("role") or field,
                    }
                )
            else:
                raise SystemExit(f"内容合同字段 {field} 只能包含路径字符串或对象")
    return assets


def follower_shared_asset_items(items: Any) -> list[Any]:
    """Keep anchor-page evidence out of follower style transfer inputs.

    Page-specific evidence must come from each follower's own content contract;
    carrying the anchor page's evidence into every follower both weakens source
    semantics and can exceed ImageGen's shared attachment ceiling.
    """

    result: list[Any] = []
    for item in items or []:
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower()
            asset_type = str(item.get("asset_type") or "").strip().lower()
            if role in {"required_source_evidence", "required_page_assets"}:
                continue
            if asset_type == "required_page_asset":
                continue
        result.append(item)
    return result


def compile_follower_prompt_bundle_v4(
    page_job: dict[str, Any], style_contract: dict[str, Any]
) -> dict[str, Any]:
    """为新 4x3 跟随页预编译短提示、附件顺序和输入指纹。"""

    if page_job.get("prompt_contract_version") != 4:
        raise SystemExit("v4 跟随提示必须配套 prompt_contract_version=4 页面合同")
    language = normalize_output_language(
        page_job.get("language") or style_contract.get("language")
    )
    use_chinese_control = language.lower().startswith("zh")
    family_contract = (
        style_contract.get("style_contract_version") == 5
        and style_contract.get("style_family_portfolio_version")
        == CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
    )
    anchor = style_contract.get("anchor") or {}
    anchor_path = anchor.get("path")
    if not isinstance(anchor_path, str) or not Path(anchor_path).is_file():
        raise SystemExit("v4/v5 跟随提示缺少可读的正式锚点图片")
    anchor_reference: dict[str, Any] = {
        "path": anchor_path,
        "role": "primary_style_anchor",
        "reference_intent": {
            "borrow": [
                (
                    "整体视觉气质、色彩与字体性格、材质、图像工艺和完成度"
                    if use_chinese_control
                    else (
                        "overall visual character, color and typographic personality, "
                        "material treatment, image craft, and finish"
                    )
                )
            ],
            "do_not_copy": [
                (
                    "锚点的标题、正文、事实、对象和具体构图"
                    if use_chinese_control
                    else (
                        "the anchor's title, body copy, facts, objects, or specific "
                        "composition"
                    )
                )
            ],
        },
    }
    style = normalize_style(
        style_contract.get("style_slot") or page_job.get("style_slot")
    )
    tone = str(style_contract.get("tone") or page_job.get("tone") or "").lower()
    if style is None or tone not in TONE_PROMPT_LABELS:
        raise SystemExit("v4 跟随提示缺少可路由资产的 style_slot 或 tone")
    shared_required_assets = merge_attachment_items(
        filter_required_assets(
            follower_shared_asset_items(style_contract.get("required_assets") or []),
            style,
            tone,
        )
    )
    chrome_projection: dict[str, Any] | None = None
    chrome_contract_path_value = style_contract.get("global_chrome_contract_path")
    if isinstance(chrome_contract_path_value, str) and chrome_contract_path_value:
        chrome_path, chrome_contract, chrome_sha = read_global_chrome_contract(
            chrome_contract_path_value,
            verify_authorization_source=False,
        )
        if chrome_sha != style_contract.get("global_chrome_contract_sha256"):
            raise SystemExit("跟随页 global chrome contract SHA-256 与风格合同不一致")
        chrome_projection = global_chrome_projection(
            chrome_contract,
            contract_path=chrome_path,
            contract_sha256=chrome_sha,
            page_id=page_job.get("page_id"),
            style=style,
            tone=tone,
            language=language,
        )
        validate_page_global_chrome_compatibility(
            page_job, chrome_projection, f"style_{style}/{page_job.get('page_id')}"
        )
        logo_asset = chrome_projection.get("logo_asset")
        if isinstance(logo_asset, dict):
            shared_required_assets = merge_attachment_items(
                shared_required_assets, [logo_asset]
            )
    required_page_assets = merge_attachment_items(
        filter_required_assets(
            page_job.get("required_page_assets") or [], style, tone
        )
    )
    shared_paths = set(extract_input_paths(shared_required_assets))
    if shared_paths:
        required_page_assets = [
            item
            for item in required_page_assets
            if not (
                isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and str(Path(item["path"]).expanduser().resolve()) in shared_paths
            )
        ]
    prompt_required_assets = merge_attachment_items(
        shared_required_assets,
        required_page_assets,
    )
    non_anchor_count = len(extract_input_paths(prompt_required_assets))
    if non_anchor_count > IMAGEGEN_MAX_REFERENCED_PATHS:
        raise SystemExit(
            f"跟随页事实/品牌附件为 {non_anchor_count} 个；"
            f"上限为 {IMAGEGEN_MAX_REFERENCED_PATHS}"
        )
    # The raster anchor is the default carrier of the visual family.  When the
    # current page already consumes the full ImageGen attachment budget, fall
    # back mechanically to the locked text family instead of adding a review
    # loop or dropping required factual/brand assets.
    use_anchor_raster = not (
        family_contract and non_anchor_count >= IMAGEGEN_MAX_REFERENCED_PATHS
    )
    effective_anchor_reference = anchor_reference if use_anchor_raster else None
    layout_direction = {
        "layout_contract_version": CURRENT_4X3_LAYOUT_VERSION,
    }
    if family_contract:
        layout_direction.update(
            {
                "art_direction_contract_version": ART_DIRECTION_CONTRACT_VERSION,
                "style_family_portfolio_version": (
                    CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
                ),
                "style_family_thesis": style_contract.get("style_family_thesis"),
                "craft_axis": style_contract.get("craft_axis"),
                "visual_activity_mode": style_contract.get("visual_activity_mode"),
                "attention_strategy": (
                    "只让当前页 relationship_thesis 定义的主关系承担第一层注意力；"
                    "其余必要证据按本页层级从属，不继承锚点页的对象、分支或动线。"
                    if use_chinese_control
                    else (
                        "Let only the current page relationship_thesis define the primary "
                        "attention structure; keep required evidence subordinate to this page "
                        "and do not inherit anchor-page objects, branches, or paths."
                    )
                ),
                "adaptation_principle": style_contract.get("adaptation_principle"),
                "continuity_invariants": style_contract.get(
                    "continuity_invariants"
                ),
            }
        )
    prompt_job = {
        "tone": style_contract.get("tone"),
        "language": language,
        "anchor_page": page_job,
        "layout_direction": layout_direction,
        "reference_images": (
            [effective_anchor_reference] if effective_anchor_reference else []
        ),
        "required_assets": prompt_required_assets,
    }
    if chrome_projection is not None:
        prompt_job["global_chrome"] = chrome_projection
    prompt = compile_minimal_prompt_v4(prompt_job)
    creative_brief_projection = build_creative_brief_projection(
        page_job, prompt_job["layout_direction"]
    )
    if chrome_projection is not None:
        creative_brief_projection["global_chrome_contract_ref"] = {
            "path": chrome_projection["contract_path"],
            "sha256": chrome_projection["contract_sha256"],
            "applies": chrome_projection["applies"],
        }
        if chrome_projection.get("applies") is True:
            creative_brief_projection["global_chrome_brief"] = chrome_projection.get(
                "prompt_brief"
            )
    referenced_paths = extract_input_paths(
        ([effective_anchor_reference] if effective_anchor_reference else [])
        + shared_required_assets
        + required_page_assets
    )
    normalized_paths, input_manifest = build_input_manifest(referenced_paths)
    fingerprint = hashlib.sha256(
        json.dumps(
            {"prompt": prompt, "inputs": input_manifest},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "imagegen_prompt_contract_version": 4,
        "anchor_input_mode": "raster" if effective_anchor_reference else "text_family",
        "layout_direction": layout_direction,
        "reference_images": (
            [effective_anchor_reference] if effective_anchor_reference else []
        ),
        "required_assets": shared_required_assets,
        "required_page_assets": required_page_assets,
        **({"global_chrome": chrome_projection} if chrome_projection is not None else {}),
        "imagegen_prompt": prompt,
        "creative_brief_projection": creative_brief_projection,
        "imagegen_referenced_paths": normalized_paths,
        "imagegen_input_manifest": input_manifest,
        "imagegen_input_fingerprint": fingerprint,
    }


def command_prepare_anchors(args: argparse.Namespace) -> None:
    project_dir = Path(args.project_dir).resolve()
    state_path = Path(args.state).resolve()
    content_path = Path(args.content_contract).resolve()
    state = read_json(state_path)
    content = read_json(content_path)
    if (state.get("preflight") or {}).get("status") != "resolved":
        raise SystemExit("预检尚未 resolved，不得创建锚点任务")
    mode = state.get("run_mode") or state.get("mode")
    if mode not in {
        STRICT_4X3_MODE,
        FAST_4X3_MODE,
        QUICK_8X1_MODE,
        FAST8_MODE,
        "quick_4x1",
    }:
        raise SystemExit(
            "prepare-anchors 只适用于 full_4x3_anchored、fast_4x3_anchored、"
            "fast_8x1_diverse 或 quick_8x1；"
            "quick_4x1 仅供旧运行恢复"
        )
    overview_python_value = getattr(args, "overview_python", None)
    task_init = validated_task_init_contract(state_path, state, required=False)
    preflight_allocated_fast8 = bool(
        mode == FAST8_MODE
        and isinstance(task_init, dict)
        and task_init.get("formal_directory_allocation_policy")
        == "after_preflight_pass"
    )
    startup_fast8 = bool(
        mode == FAST8_MODE
        and state.get("fast8_startup_contract_version")
        == FAST8_STARTUP_CONTRACT_VERSION
    )
    if startup_fast8:
        timing = state.get("timing") or {}
        events = state.get("events") or []
        runtime = state.get("overview_runtime") or {}
        if not timing.get("process_started_at") or not timing.get(
            "preflight_resolved_at"
        ):
            raise SystemExit("新 Fast8 启动状态缺少脚本写入的开始或预检时间")
        if [item.get("name") for item in events[:2] if isinstance(item, dict)] != [
            "process_started",
            "preflight_resolved",
        ]:
            raise SystemExit("新 Fast8 启动状态必须先包含连续的开始与预检事件")
        if runtime.get("pillow_preflight") != "pass" or not runtime.get("python"):
            raise SystemExit("新 Fast8 启动状态缺少已验证并绑定的总览 Python")
        if state.get("follower_page_ids") or state.get("deferred_pages"):
            raise SystemExit("新 Fast8 是单页探索，不得创建未请求的 follower/deferred 页面")
        if overview_python_value and Path(overview_python_value).expanduser().resolve() != Path(
            runtime["python"]
        ).expanduser().resolve():
            raise SystemExit("prepare-anchors 不得替换启动阶段绑定的总览 Python")
    elif (
        preflight_allocated_fast8
        and not overview_python_value
        and not (state.get("overview_runtime") or {}).get("python")
    ):
        raise SystemExit(
            "旧版预检分配 Fast8 必须在 prepare-anchors 传入已通过 Pillow 预检的 "
            "--overview-python；新运行应由 init_task_dir 一次绑定"
        )
    if mode == FAST8_MODE and overview_python_value and not startup_fast8:
        overview_python = Path(overview_python_value).expanduser().resolve()
        if not overview_python.is_file():
            raise SystemExit(f"Fast8 总览 Python 不存在：{overview_python}")
        check = subprocess.run(
            [str(overview_python), "-c", "from PIL import Image"],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if check.returncode != 0:
            raise SystemExit(
                "Fast8 总览 Python 未通过 Pillow 预检："
                + (check.stderr.strip() or check.stdout.strip() or str(overview_python))
            )
        existing_runtime = state.get("overview_runtime") or {}
        existing_python = existing_runtime.get("python")
        if existing_python and Path(existing_python).expanduser().resolve() != overview_python:
            raise SystemExit("恢复运行不得替换已经绑定的 Fast8 总览 Python")
        state["overview_runtime"] = {
            "python": str(overview_python),
            "pillow_preflight": "pass",
            "binding_policy": "reuse_for_formal_overview",
        }
    active_styles = styles_for_mode(mode)
    anchor_page_id = state.get("anchor_page_id") or content.get("page_id")
    if str(content.get("page_id")) != str(anchor_page_id):
        raise SystemExit("内容合同 page_id 与 anchor_page_id 不一致")
    require_keys(
        content,
        [
            "content_contract_version",
            "source_facts",
            "display_required",
            "display_supporting",
            "content_resolution",
            *spatial_contract_required_keys(content),
        ],
        str(content_path),
    )
    validate_dispatchable_content_contract(
        content,
        str(content_path),
        soft_spatial_preference=mode == FAST_4X3_MODE,
    )
    reference_images = parse_json_array(args.reference_images_json, "--reference-images-json")
    required_assets = read_required_assets_input(
        json_value=getattr(args, "required_assets_json", None),
        file_value=getattr(args, "required_assets_file", None),
        expected_page_id=str(anchor_page_id),
    )
    global_chrome_path_value = getattr(args, "global_chrome_contract", None)
    state_global_chrome_path = state.get("global_chrome_contract_path")
    if global_chrome_path_value and isinstance(state_global_chrome_path, str):
        if Path(global_chrome_path_value).expanduser().resolve() != Path(
            state_global_chrome_path
        ).expanduser().resolve():
            raise SystemExit("恢复运行不得替换已经绑定的 global chrome contract")
    elif not global_chrome_path_value and isinstance(state_global_chrome_path, str):
        global_chrome_path_value = state_global_chrome_path
    global_chrome_path: Path | None = None
    global_chrome_contract: dict[str, Any] | None = None
    global_chrome_sha256: str | None = None
    if global_chrome_path_value:
        (
            global_chrome_path,
            global_chrome_contract,
            global_chrome_sha256,
        ) = read_global_chrome_contract(
            global_chrome_path_value,
            verify_authorization_source=not bool(
                isinstance(state_global_chrome_path, str)
                and isinstance(state.get("global_chrome_contract_sha256"), str)
            ),
        )
        recorded_sha = state.get("global_chrome_contract_sha256")
        if isinstance(recorded_sha, str) and recorded_sha != global_chrome_sha256:
            raise SystemExit("恢复运行的 global chrome contract SHA-256 已变化")
    fast8_already_prepared = any(
        isinstance(event, dict) and event.get("name") == "style_jobs_created"
        for event in state.get("events", [])
    ) or any(
        (project_dir / "style_jobs" / f"style_{style}.json").is_file()
        for style in QUICK_STYLES
    )
    if mode == FAST8_MODE and not fast8_already_prepared:
        validate_new_fast8_style_references(reference_images)
    source_file_value = getattr(args, "source_file", None)
    source_page_ids_value = getattr(args, "source_page_ids", None)
    if mode in {FAST_4X3_MODE, STRICT_4X3_MODE} and len(
        state.get("follower_page_ids") or []
    ) != 2:
        raise SystemExit("4x3 source snapshot 必须绑定恰好两个 follower_page_ids")
    if source_page_ids_value:
        source_page_ids = normalize_page_ids(source_page_ids_value)
    elif mode in {QUICK_8X1_MODE, FAST8_MODE, "quick_4x1"}:
        source_page_ids = [str(anchor_page_id)]
    else:
        source_page_ids = [
            str(anchor_page_id),
            *(str(item) for item in (state.get("follower_page_ids") or [])),
        ]
    guarded_scope_required = bool(
        source_file_value
        or source_snapshot_path_for_state(state_path, state) is not None
        or source_snapshot_required_for_state(state_path, state)
    )
    if guarded_scope_required:
        required_source_page_ids = (
            [str(anchor_page_id)]
            if mode in {QUICK_8X1_MODE, FAST8_MODE, "quick_4x1"}
            else [
                str(anchor_page_id),
                *(str(item) for item in (state.get("follower_page_ids") or [])),
            ]
        )
        if not page_id_sets_match(source_page_ids, required_source_page_ids):
            raise SystemExit(
                f"{mode} source snapshot 页面范围必须精确为 "
                f"{required_source_page_ids}，实际为 {source_page_ids}"
            )
    contracts_value = getattr(args, "snapshot_content_contracts_json", None)
    if contracts_value:
        contract_paths = [
            Path(item).expanduser().resolve()
            for item in parse_json_array(
                contracts_value, "--snapshot-content-contracts-json"
            )
        ]
    elif (
        source_file_value
        or source_snapshot_path_for_state(state_path, state) is not None
        or source_snapshot_required_for_state(state_path, state)
    ):
        contract_paths = [content_path]
        for page_id in source_page_ids:
            if page_ids_match(page_id, anchor_page_id):
                continue
            sibling = content_path.parent / f"page_{page_id}.json"
            if not sibling.is_file():
                raise SystemExit(
                    "创建或复核 4x3 source snapshot 前必须准备全部相关页面内容合同；"
                    f"缺少：{sibling}"
                )
            contract_paths.append(sibling.resolve())
    else:
        # 未迁移的旧运行继续沿用原有锚点准备语义；不补造三页历史清单。
        contract_paths = [content_path]
    snapshot_asset_items: list[Any] = []
    snapshot_tones = tones_for_run(state, mode, active_styles)
    if global_chrome_path is not None and global_chrome_contract is not None:
        representative_style = active_styles[0]
        for contract_path in contract_paths:
            contract_value = content if contract_path == content_path else read_json(contract_path)
            projection = global_chrome_projection(
                global_chrome_contract,
                contract_path=global_chrome_path,
                contract_sha256=str(global_chrome_sha256),
                page_id=contract_value.get("page_id"),
                style=representative_style,
                tone=snapshot_tones[representative_style],
                language=contract_value.get("language") or state.get("language") or "source",
            )
            validate_page_global_chrome_compatibility(
                contract_value, projection, str(contract_path)
            )
        snapshot_asset_items.append(
            {
                "path": str(global_chrome_path),
                "asset_type": "global_chrome_contract",
                "role": "global_chrome_contract",
                "styles": list(active_styles),
            }
        )
        # The authorization source proves why the compiled chrome contract may
        # exist; it is not itself a page-generation asset.  Tracking the whole
        # outline again as a used asset would turn unrelated page edits into a
        # false hard block.  The compiled contract hash is the blocking input,
        # while authoritative_source/page_content keep source provenance.
        qa_reference_path = (
            global_chrome_contract.get("deck_title_system") or {}
        ).get("qa_reference_path")
        if isinstance(qa_reference_path, str) and qa_reference_path.strip():
            snapshot_asset_items.append(
                {
                    "path": qa_reference_path,
                    "asset_type": "global_chrome_qa_reference",
                    "role": "global_chrome_qa_reference",
                    "styles": list(active_styles),
                }
            )
        for style in active_styles:
            projection = global_chrome_projection(
                global_chrome_contract,
                contract_path=global_chrome_path,
                contract_sha256=str(global_chrome_sha256),
                page_id=anchor_page_id,
                style=style,
                tone=snapshot_tones[style],
                language=content.get("language") or state.get("language") or "source",
            )
            logo_asset = projection.get("logo_asset")
            if isinstance(logo_asset, dict):
                snapshot_asset_items.append(logo_asset)
    for style in active_styles:
        for item in filter_reference_images(
            reference_images, style, snapshot_tones[style]
        ):
            snapshot_asset_items.append(
                snapshot_tagged_asset(
                    item, asset_type="reference_image", style=style
                )
            )
        for item in filter_required_assets(
            required_assets, style, snapshot_tones[style]
        ):
            snapshot_asset_items.append(
                snapshot_tagged_asset(
                    item, asset_type="required_asset", style=style
                )
            )
    for contract_path in contract_paths:
        contract_value = content if contract_path == content_path else read_json(contract_path)
        contract_assets = content_contract_asset_items(contract_value)
        for style in active_styles:
            for item in filter_required_assets(
                contract_assets, style, snapshot_tones[style]
            ):
                snapshot_asset_items.append(
                    snapshot_tagged_asset(
                        item,
                        asset_type=(
                            item.get("asset_type")
                            if isinstance(item, dict) and item.get("asset_type")
                            else "required_page_asset"
                        ),
                        style=style,
                    )
                )
    fragment_value = getattr(args, "source_fragment_file", None)
    snapshot_before = source_snapshot_path_for_state(state_path, state)
    snapshot_bound = bool(
        state.get("source_snapshot_path") and state.get("source_snapshot_sha256")
    )
    if source_file_value and (snapshot_before is None or not snapshot_bound):
        source_path = Path(source_file_value).expanduser().resolve()
        frozen_fast8_packet = bool(
            state.get("run_mode") == FAST8_MODE
            and fragment_value
            and getattr(args, "source_fragment_authority", "extractor_aid")
            == "authoritative_page_fragment"
        )
        supporting_source_paths = (
            []
            if frozen_fast8_packet
            else preflight_supporting_source_paths(
                project_dir,
                authoritative_source=source_path,
                content_contract_paths=contract_paths,
                asset_items=snapshot_asset_items,
            )
        )
        create_source_snapshot(
            project_dir=project_dir,
            state_path=state_path,
            source_path=source_path,
            page_ids=source_page_ids,
            content_contract_paths=contract_paths,
            asset_items=snapshot_asset_items,
            supporting_source_paths=supporting_source_paths,
            fragment_path=Path(fragment_value) if fragment_value else None,
            slide_identity_path=(
                Path(args.slide_identity_file)
                if getattr(args, "slide_identity_file", None)
                else None
            ),
            fragment_authority=getattr(
                args, "source_fragment_authority", "extractor_aid"
            ),
            timestamp=getattr(args, "source_snapshot_timestamp", None),
        )
        state = read_json(state_path)
    if source_guard_enabled(state_path, state):
        enforce_source_guard(
            state_path,
            state,
            action="prepare_or_resume_anchors",
            content_contract_paths=contract_paths,
            asset_items=snapshot_asset_items,
            exact_content_contracts=True,
            exact_assets=True,
            page_ids=source_page_ids,
            exact_page_scope=True,
            source_path=Path(source_file_value) if source_file_value else None,
            fragment_path=Path(fragment_value) if fragment_value else None,
        )
    elif any(
        (project_dir / "style_jobs" / f"style_{style}.json").is_file()
        for style in active_styles
    ):
        enforce_source_guard(
            state_path,
            state,
            action="prepare_or_resume_anchors",
        )
    previous_event = next(
        (
            event
            for event in state.get("events", [])
            if isinstance(event, dict) and event.get("name") == "style_jobs_created"
        ),
        None,
    )
    timestamp = (
        previous_event.get("occurred_at")
        if isinstance(previous_event, dict) and previous_event.get("occurred_at")
        else now_iso()
    )
    if previous_event is not None:
        existing_jobs = [
            project_dir / "style_jobs" / f"style_{style}.json" for style in active_styles
        ]
        missing_jobs = [str(path) for path in existing_jobs if not path.is_file()]
        if missing_jobs:
            raise SystemExit(
                "既有运行已记录 style_jobs_created，但任务文件缺失："
                + ", ".join(missing_jobs)
            )
        print(
            json.dumps(
                {
                    "status": "already_prepared",
                    "style_jobs": len(existing_jobs),
                    "prepared_at": timestamp,
                },
                ensure_ascii=False,
            )
        )
        return
    if mode != "quick_4x1":
        state["state_audit_contract_version"] = CURRENT_STATE_AUDIT_VERSION
    state["anchor_content_contract_path"] = str(content_path)
    state["anchor_content_contract_sha256"] = file_sha256(content_path)
    if global_chrome_path is not None and global_chrome_contract is not None:
        state["global_chrome_contract_path"] = str(global_chrome_path)
        state["global_chrome_contract_sha256"] = str(global_chrome_sha256)
        state["global_chrome_contract_version"] = GLOBAL_CHROME_CONTRACT_VERSION
        chrome_applies = global_chrome_applies(
            global_chrome_contract, anchor_page_id
        )
        integrated_review_required = bool(
            mode == FAST8_MODE
            and (global_chrome_contract.get("deck_title_system") or {}).get(
                "qa_required"
            )
            and chrome_applies
        )
        state["global_chrome_review"] = {
            "required": integrated_review_required,
            "review_mode": (
                "integrated_fast8_judge"
                if integrated_review_required
                else "integrated_existing_visual_qa"
            ),
            "status": (
                "pending"
                if integrated_review_required
                else "integrated_existing_visual_qa"
                if chrome_applies
                else "not_applicable"
            ),
            "contract_path": str(global_chrome_path),
            "contract_sha256": str(global_chrome_sha256),
        }
    tones = tones_for_run(state, mode, active_styles)
    language = normalize_output_language(content.get("language") or state.get("language"))
    content.setdefault("language", language)
    state["language"] = language
    if content.get("prompt_contract_version") in {2, 3, 4}:
        state.setdefault("quality_contract_version", 2)
    layout_bundle = None
    layout_directions: dict[str, dict[str, Any]] = {}
    if mode in {QUICK_8X1_MODE, FAST8_MODE, FAST_4X3_MODE, STRICT_4X3_MODE}:
        raw_portfolio_path = getattr(args, "layout_portfolio", None)
        if not raw_portfolio_path:
            raise SystemExit(
                f"{mode} 必须先由主 Agent 针对当前页面编写 layout_portfolio.json，"
                "再通过 --layout-portfolio 传入；脚本不再从固定构图库自动抽签"
            )
        portfolio_path = Path(raw_portfolio_path).resolve()
        layout_bundle = load_layout_portfolio(
            portfolio_path,
            state,
            content,
            expected_styles=(
                QUICK_STYLES
                if mode in {QUICK_8X1_MODE, FAST8_MODE}
                else FULL_STYLES
            ),
        )
        layout_version = layout_bundle.get("layout_portfolio_contract_version")
        if mode == QUICK_8X1_MODE and layout_version != CURRENT_QUICK_LAYOUT_VERSION:
            raise SystemExit(
                "新 quick_8x1 必须使用 layout_portfolio_contract_version=5；"
                "v4/v3 仅恢复已创建 style_jobs 的旧任务"
            )
        if mode == FAST8_MODE and layout_version != CURRENT_FAST8_LAYOUT_VERSION:
            raise SystemExit(
                "新 fast_8x1_diverse 必须使用 layout_portfolio_contract_version=7"
            )
        if (
            mode == FAST8_MODE
            and not fast8_already_prepared
            and layout_bundle.get("art_direction_contract_version")
            != ART_DIRECTION_CONTRACT_VERSION
        ):
            raise SystemExit(
                "新 fast_8x1_diverse 必须使用 art_direction_contract_version=1；"
                "无艺术导演版本的 v7 只允许恢复已经创建的旧 style_jobs"
            )
        if mode in {FAST_4X3_MODE, STRICT_4X3_MODE} and layout_version != CURRENT_4X3_LAYOUT_VERSION:
            raise SystemExit(
                "新 4x3 必须使用 layout_portfolio_contract_version=6；"
                "v4 仅恢复已经创建 style_jobs 的旧 Fast 项目"
            )
        layout_directions = layout_bundle["styles"]
        state["layout_portfolio_path"] = str(portfolio_path)
        state["layout_portfolio_contract_version"] = layout_version
        if layout_bundle.get("art_direction_contract_version") is not None:
            state["art_direction_contract_version"] = layout_bundle[
                "art_direction_contract_version"
            ]
        if layout_bundle.get("style_family_portfolio_version") is not None:
            state["style_family_portfolio_version"] = layout_bundle[
                "style_family_portfolio_version"
            ]
        if layout_bundle.get("visual_activity_portfolio_version") is not None:
            state["visual_activity_portfolio_version"] = layout_bundle[
                "visual_activity_portfolio_version"
            ]
        if layout_bundle.get("spatial_topology_portfolio_version") is not None:
            state["spatial_topology_portfolio_version"] = layout_bundle[
                "spatial_topology_portfolio_version"
            ]
    jobs: list[str] = []
    pending_job_documents: list[tuple[Path, dict[str, Any]]] = []
    prompt_fingerprints: dict[str, str] = {}
    styles_state = state.setdefault("styles", {})
    for style in active_styles:
        anchor_page = dict(content)
        if anchor_page.get("prompt_contract_version") not in {2, 3, 4}:
            breathing = anchor_page.pop("spatial_breathing_contract", None)
            if breathing is not None:
                anchor_page["spatial_breathing"] = breathing
        anchor_page["output_target"] = str(
            origin_image_target(project_dir, style, anchor_page_id)
        )
        chrome_projection: dict[str, Any] | None = None
        chrome_assets: list[Any] = []
        if global_chrome_path is not None and global_chrome_contract is not None:
            chrome_projection = global_chrome_projection(
                global_chrome_contract,
                contract_path=global_chrome_path,
                contract_sha256=str(global_chrome_sha256),
                page_id=anchor_page_id,
                style=style,
                tone=tones[style],
                language=language,
            )
            validate_page_global_chrome_compatibility(
                anchor_page, chrome_projection, str(content_path)
            )
            if isinstance(chrome_projection.get("logo_asset"), dict):
                chrome_assets.append(chrome_projection["logo_asset"])
        job = {
            "run_mode": mode,
            "style_slot": style,
            "action": "generate_anchor",
            "attempt": 1,
            "tone": tones[style],
            "language": language,
            "overall_requirements": args.overall_requirements,
            "reference_images": filter_reference_images(
                reference_images, style, tones[style]
            ),
            "required_assets": merge_attachment_items(
                chrome_assets,
                filter_required_assets(required_assets, style, tones[style]),
                filter_required_assets(
                    content.get("required_page_assets") or [], style, tones[style]
                ),
            ),
            "anchor_page_id": anchor_page_id,
            "source_content_contract_path": str(content_path),
            "source_content_contract_sha256": file_sha256(content_path),
            "follower_page_ids": state.get("follower_page_ids", []),
            "deferred_pages": state.get("deferred_pages", []),
            "anchor_page": anchor_page,
            "generation_rules": {
                "quality": "final",
                "aspect_ratio": "16:9",
                "anchor_gate_required": True,
                "worker_qa_enabled": False,
                "max_total_attempts_per_page": 3,
                "max_same_bad_request_attempts": 2,
                "max_anchor_craft_retries": 1,
                "craft_gate_required": True,
                "subjective_alternative_retry": False,
                "no_programmatic_slide_rendering": True,
                "no_text_overlay_pipeline": True,
            },
        }
        if chrome_projection is not None:
            job["global_chrome"] = chrome_projection
        if mode in {
            QUICK_8X1_MODE,
            FAST8_MODE,
            FAST_4X3_MODE,
            STRICT_4X3_MODE,
        }:
            job["layout_direction"] = layout_directions[style]
            if page_relationship_thesis(anchor_page) or job["layout_direction"].get(
                "art_direction_contract_version"
            ) == ART_DIRECTION_CONTRACT_VERSION:
                job["creative_brief_projection"] = build_creative_brief_projection(
                    anchor_page, job["layout_direction"]
                )
                if chrome_projection is not None:
                    job["creative_brief_projection"]["global_chrome_contract_ref"] = {
                        "path": chrome_projection["contract_path"],
                        "sha256": chrome_projection["contract_sha256"],
                        "applies": chrome_projection["applies"],
                    }
                    if chrome_projection.get("applies") is True:
                        job["creative_brief_projection"]["global_chrome_brief"] = (
                            chrome_projection.get("prompt_brief")
                        )
            if mode in {QUICK_8X1_MODE, FAST8_MODE, FAST_4X3_MODE} and layout_bundle.get(
                "layout_portfolio_contract_version"
            ) in {4, 5, CURRENT_FAST8_LAYOUT_VERSION, CURRENT_4X3_LAYOUT_VERSION}:
                job["candidate_policy"] = {
                    "mode": (
                        "fast_diversity_initial"
                        if mode == FAST8_MODE
                        else "one_shot_final_quality"
                    ),
                    "max_initial_image_calls": 1,
                    "automatic_visual_retries_before_selection": 0,
                    "run_level_diversity_replacement": mode == FAST8_MODE,
                    **(
                        {"unified_spatial_standard_applies": True}
                        if uses_unified_spatial_standard(anchor_page)
                        else {
                            "low_spatial_preference_is_soft": mode == FAST_4X3_MODE
                        }
                    ),
                    "max_technical_retries_after_missing_or_invalid_artifact": 1,
                    "selected_candidate_max_targeted_edits": 1,
                }
                job["generation_rules"].update(
                    {
                        "anchor_gate_required": False,
                        "max_total_attempts_per_page": (
                            3
                            if mode == FAST8_MODE
                            else 2
                            if mode == FAST_4X3_MODE
                            else 1
                        ),
                        "max_anchor_craft_retries": 0,
                        "craft_gate_required": False,
                        "automatic_visual_retry_before_selection": False,
                        "automatic_spatial_retry_before_selection": False,
                    }
                )
        if layout_bundle and layout_bundle.get(
            "layout_portfolio_contract_version"
        ) == CURRENT_FAST8_LAYOUT_VERSION:
            job["imagegen_prompt_contract_version"] = (
                CURRENT_FAST8_IMAGEGEN_PROMPT_VERSION
            )
        elif layout_bundle and layout_bundle.get("layout_portfolio_contract_version") in {
            CURRENT_QUICK_LAYOUT_VERSION,
            CURRENT_4X3_LAYOUT_VERSION,
        }:
            job["imagegen_prompt_contract_version"] = 4
        elif anchor_page.get("prompt_contract_version") == 3:
            job["imagegen_prompt_contract_version"] = 3
        else:
            job["imagegen_prompt_contract_version"] = (
                2 if mode in {QUICK_8X1_MODE, FAST8_MODE} else 1
            )
        if mode == FAST8_MODE:
            receipt_path = fast8_worker_receipt_path(
                project_dir, style, anchor_page_id, "generate_anchor", 1
            )
            job["worker_runtime_contract"] = {
                "required_model": FAST8_WORKER_REQUIRED_MODEL,
                "required_reasoning_effort": FAST8_WORKER_REQUIRED_REASONING,
                "required_fork_turns": FAST8_WORKER_REQUIRED_FORK_TURNS,
                "session_binding_required": True,
                "imagegen_prompt_must_be_verbatim": True,
            }
            job["worker_receipt"] = {
                "contract_version": FAST8_WORKER_RECEIPT_CONTRACT_VERSION,
                "path": str(receipt_path),
                "required": True,
                "write_after_imagegen_in_same_exec": True,
                "write_on_success_or_unresolved": True,
                "controller_settles_without_worker_final_text": True,
                "contains_image_payload": False,
            }
        job["imagegen_prompt"] = compile_anchor_imagegen_prompt(job)
        if mode == FAST8_MODE:
            job["imagegen_prompt_fingerprint"] = hashlib.sha256(
                job["imagegen_prompt"].encode("utf-8")
            ).hexdigest()
        referenced_paths = extract_input_paths(
            job["reference_images"] + job["required_assets"]
        )
        normalized_paths, input_manifest = build_input_manifest(referenced_paths)
        job["imagegen_referenced_paths"] = normalized_paths
        job["imagegen_input_manifest"] = input_manifest
        job["imagegen_input_fingerprint"] = hashlib.sha256(
            json.dumps(
                {"prompt": job["imagegen_prompt"], "inputs": input_manifest},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        job_path = project_dir / "style_jobs" / f"style_{style}.json"
        pending_job_documents.append((job_path, job))
        if mode == FAST8_MODE:
            prompt_fingerprints[style] = job["imagegen_prompt_fingerprint"]
        jobs.append(str(job_path))
        if style not in styles_state:
            styles_state[style] = {
                "tone": tones[style],
                "anchor_agent_id": None,
                "contract_path": None,
                "workflow_status": "anchor_pending",
                "pages": {anchor_page_id: initial_page_state("anchor", timestamp)},
            }

    if mode == FAST8_MODE and len(set(prompt_fingerprints.values())) != len(
        active_styles
    ):
        duplicates: dict[str, list[str]] = {}
        for style, fingerprint in prompt_fingerprints.items():
            duplicates.setdefault(fingerprint, []).append(style)
        repeated = [styles for styles in duplicates.values() if len(styles) > 1]
        raise SystemExit(
            "Fast8 v7 的八份最终图片提示必须逐份唯一；重复席位："
            + ", ".join("/".join(styles) for styles in repeated)
        )
    for job_path, job in pending_job_documents:
        write_idempotent(job_path, job)

    ready_queue = [
        {"style": style, "action": "generate_anchor", "page_id": anchor_page_id}
        for style in active_styles
    ]
    scheduler = state.setdefault("scheduler", {})
    scheduler["phase"] = "anchor_generation"
    scheduler["active_child_limit"] = active_child_limit_for_mode(mode)
    scheduler["requested_initial_wave"] = len(active_styles)
    if mode == FAST8_MODE:
        scheduler["dispatch_policy"] = "direct_fanout"
        scheduler["root_dispatch_wave"] = 8
        scheduler["image_child_limit"] = 8
        scheduler["diversity_judge_child_limit"] = 1
        scheduler.pop("dispatch_groups", None)
        state["fast8_candidate_policy"] = {
            "version": CURRENT_FAST8_CANDIDATE_POLICY_VERSION,
            "mode": "fast_diversity",
            **(
                {
                    "art_direction_contract_version": ART_DIRECTION_CONTRACT_VERSION,
                    "creative_brief_projection_version": 1,
                    "relationship_thesis_required": True,
                    "visual_activity_portfolio_version": layout_bundle.get(
                        "visual_activity_portfolio_version"
                    ),
                    "explicit_flexible_story_required": bool(
                        layout_bundle.get("visual_activity_portfolio_version")
                    ),
                    "semantic_guardrails_qa_only_with_explicit_story": True,
                    "relationship_representation_family_required": True,
                    "spatial_topology_portfolio_version": layout_bundle.get(
                        "spatial_topology_portfolio_version"
                    ),
                    "spatial_topology_required": bool(
                        layout_bundle.get("spatial_topology_portfolio_version")
                    ),
                }
                if layout_bundle
                and layout_bundle.get("art_direction_contract_version")
                == ART_DIRECTION_CONTRACT_VERSION
                else {}
            ),
            "initial_image_worker_count": 8,
            "image_worker_runtime_contract": {
                "required_model": FAST8_WORKER_REQUIRED_MODEL,
                "required_reasoning_effort": FAST8_WORKER_REQUIRED_REASONING,
                "required_fork_turns": FAST8_WORKER_REQUIRED_FORK_TURNS,
                "imagegen_prompt_must_be_verbatim": True,
                "imagegen_input_fingerprint_is_quality_invariant": True,
            },
            "diversity_judge_worker_count": 1,
            "max_parallel_diversity_replacements": 2,
            "max_total_diversity_replacements": 2,
            "max_replacement_rounds": 1,
            "full_visual_qa_before_selection": False,
            "same_worker_recovery_soft_escalation_seconds": (
                FAST8_SAME_WORKER_RECOVERY_SOFT_ESCALATION_SECONDS
            ),
            "deterministic_recovery_may_race_after_soft_escalation": True,
            "optional_effect_review_policy": {
                "preferred_model": "gpt-5.6-terra",
                "reasoning_effort": "low",
                "max_overview_view_calls": 1,
                "soft_timeout_seconds": (
                    FAST8_OPTIONAL_EFFECT_REVIEW_SOFT_TIMEOUT_SECONDS
                ),
                "max_retries_same_overview_sha256": 1,
                "formal_timing_excluded": True,
            },
            "selected_candidate_max_targeted_edits": 1,
        }
        state["diversity_review"] = {
            "contract_version": CURRENT_FAST8_JUDGE_CONTRACT_VERSION,
            "status": "waiting_for_candidates",
            "scope": FAST8_JUDGE_SCOPES[CURRENT_FAST8_JUDGE_CONTRACT_VERSION],
            "checkpoints": [8],
            "scheduling_policy": "final_only_after_same_wave",
            "deduplicate_unchanged_full_set": True,
            "replacement_recheck_policy": "delta_review_evidence_first",
            "replacement_budget_total": 2,
            "replacement_count": 0,
            "replacement_rounds_used": 0,
            "replacement_styles": [],
            "review_jobs": [],
            "reports": [],
            "final_candidate_set_sha256": None,
        }
        state["timing_target"] = {
            "target_minutes": 15,
            "hard_deadline": False,
            "scope": "request_started_at_to_delivery_ready",
            "started_at": None,
            "ended_at": None,
            "elapsed_minutes": None,
            "met": None,
            "soft_target_missed": False,
        }
    elif mode == QUICK_8X1_MODE:
        if layout_bundle.get("layout_portfolio_contract_version") in {4, 5}:
            scheduler["dispatch_policy"] = "direct_fanout"
            scheduler["root_dispatch_wave"] = 8
            scheduler.pop("dispatch_groups", None)
            state["quick8_candidate_policy"] = {
                "version": (
                    2
                    if layout_bundle.get("layout_portfolio_contract_version") == 5
                    else 1
                ),
                "mode": "one_shot_final_quality",
                "automatic_visual_retries_before_selection": 0,
                "lightweight_overview_review_only": True,
                "selected_candidate_max_targeted_edits": 1,
            }
        else:
            scheduler["dispatch_policy"] = "two_branch_fanout"
            scheduler["root_dispatch_wave"] = 2
            scheduler["dispatch_groups"] = {
                "dark": ["A", "B", "C", "D"],
                "light": ["E", "F", "G", "H"],
            }
    elif mode == FAST_4X3_MODE:
        scheduler["dispatch_policy"] = "direct_fanout"
        scheduler["root_dispatch_wave"] = 4
        scheduler.pop("dispatch_groups", None)
        state["fast4x3_candidate_policy"] = {
            "version": (
                3
                if layout_bundle.get("style_family_portfolio_version")
                == CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
                else 2
            ),
            "mode": "one_shot_final_quality",
            "automatic_visual_retries_before_selection": 0,
            "automatic_spatial_retries_before_selection": 0,
            **(
                {"unified_spatial_standard_applies": True}
                if uses_unified_spatial_standard(content)
                else {"low_spatial_preference_is_soft": True}
            ),
            "material_anchor_collision_max_targeted_repairs": 1,
            "progressive_style_unlock": True,
            "guided_seat_count": layout_bundle.get("guided_seat_count"),
            "open_seat_count": layout_bundle.get("open_seat_count"),
            "precompiled_follower_prompts": True,
            "three_director_method": bool(
                layout_bundle.get("style_family_portfolio_version")
                == CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
            ),
            "explicit_flexible_story_required_for_all_pages": bool(
                layout_bundle.get("style_family_portfolio_version")
                == CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
            ),
            "style_family_portfolio_version": layout_bundle.get(
                "style_family_portfolio_version"
            ),
            "requested_follower_concurrency": FOUR_BY_THREE_FOLLOWER_TASK_COUNT,
            "selected_candidate_max_targeted_edits": 1,
        }
    else:
        scheduler["dispatch_policy"] = "single_wave"
    scheduler["active_actions"] = []
    scheduler["ready_queue"] = ready_queue
    timing = state.setdefault("timing", {})
    timing["style_jobs_created_at"] = timestamp
    timing["task_package_completed_at"] = timestamp
    append_event(
        state,
        "style_jobs_created",
        timestamp,
        details={
            "style_job_count": len(active_styles),
            "content_contract": str(content_path),
            "requested_initial_wave": len(active_styles),
            "dispatch_policy": scheduler["dispatch_policy"],
            "root_dispatch_wave": scheduler.get("root_dispatch_wave"),
        },
    )
    append_event(
        state,
        "task_package_completed",
        timestamp,
        details={
            "style_job_count": len(active_styles),
            "ready_queue_count": len(ready_queue),
        },
    )
    for item in ready_queue:
        append_event(
            state,
            "queued",
            timestamp,
            style=item["style"],
            page_id=item["page_id"],
            action=item["action"],
            details={"source": "prepare-anchors"},
        )
    atomic_write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "ok",
                "style_jobs": len(active_styles),
                "ready_queue": len(ready_queue),
                "prepared_at": timestamp,
            },
            ensure_ascii=False,
        )
    )


def parse_style_csv(value: str) -> list[str]:
    styles = [normalize_style(item.strip()) for item in value.split(",") if item.strip()]
    normalized = [item for item in styles if item is not None]
    if not normalized or len(normalized) != len(set(normalized)):
        raise SystemExit("--styles 必须是非空、不重复的席位列表")
    return normalized


def selected_source_path_set(state: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    page_groups: list[dict[str, Any]] = []
    for style_state in (state.get("styles") or {}).values():
        if isinstance(style_state, dict) and isinstance(style_state.get("pages"), dict):
            page_groups.append(style_state["pages"])
    if isinstance(state.get("pages"), dict):
        page_groups.append(state["pages"])
    for pages in page_groups:
        for record in pages.values():
            if not isinstance(record, dict):
                continue
            value = record.get("selected_source") or record.get("final_path")
            if isinstance(value, str) and Path(value).is_absolute():
                paths.add(str(Path(value).expanduser().resolve()))
    return paths


def selected_source_for_record(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    value = record.get("selected_source") or record.get("final_path")
    if not isinstance(value, str):
        return None
    path = Path(value).expanduser()
    return str(path.resolve()) if path.is_absolute() else None


def allowed_internal_sources_for_task(
    state: dict[str, Any], task: dict[str, Any]
) -> set[str]:
    """Allow only the generated inputs that the exact style/page action may reuse."""

    style = normalize_style(task.get("style"))
    page_id = str(task.get("page_id"))
    action = task.get("action")
    selected_expansion = (
        (state.get("run_mode") or state.get("mode"))
        == SELECTED_STYLE_EXPANSION_MODE
    )
    style_state = ((state.get("styles") or {}).get(style) or {}) if style else {}
    pages = (state.get("pages") or {}) if selected_expansion else (style_state.get("pages") or {})
    allowed: set[str] = set()

    if action in {"repair_anchor", "repair_page"}:
        current = selected_source_for_record(pages.get(page_id))
        if current:
            allowed.add(current)
    if action in {"generate_follower", "repair_page"} and not selected_expansion:
        anchor_id = str(state.get("anchor_page_id"))
        anchor = selected_source_for_record(pages.get(anchor_id))
        if anchor:
            allowed.add(anchor)
    return allowed


def generation_job_path_for_task(
    project_dir: Path, task: dict[str, Any], mode: str | None = None
) -> Path | None:
    style = task["style"]
    page_id = str(task["page_id"])
    action = task["action"]
    attempt = int(task.get("attempt") or 1)
    if mode == SELECTED_STYLE_EXPANSION_MODE:
        if action == "generate_page":
            return project_dir / "page_jobs" / f"page_{page_id}.json"
        if action == "repair_page":
            return (
                project_dir
                / "page_jobs"
                / "repair_jobs"
                / f"page_{page_id}_attempt_{attempt}.json"
            )
        return None
    if action == "generate_anchor":
        return project_dir / "style_jobs" / f"style_{style}.json"
    if action == "generate_follower":
        return (
            project_dir
            / "style_page_jobs"
            / f"style_{style}"
            / f"page_{page_id}.json"
        )
    if action == "repair_anchor":
        generic = (
            project_dir
            / "style_jobs"
            / "repair_jobs"
            / f"style_{style}_page_{page_id}_attempt_{attempt}.json"
        )
        fast = (
            project_dir
            / "style_jobs"
            / "repair_jobs"
            / f"style_{style}_page_{page_id}_attempt_{attempt}_fast.json"
        )
        fast8 = (
            project_dir
            / "style_jobs"
            / "repair_jobs"
            / f"style_{style}_page_{page_id}_attempt_{attempt}_fast8.json"
        )
        diversity = (
            project_dir
            / "repair_jobs"
            / f"style_{style}_attempt_{attempt}_diversity.json"
        )
        candidates = (
            [fast, generic]
            if mode == FAST_4X3_MODE
            else [fast8, generic]
            if mode == FAST8_MODE
            else [generic]
            if mode == STRICT_4X3_MODE
            else [diversity, generic]
        )
        existing = [path for path in candidates if path.is_file()]
        if len(existing) > 1:
            raise SystemExit(
                f"style_{style}/{page_id}/repair_anchor 存在多个候选任务文件"
            )
        return existing[0] if existing else candidates[0]
    if action == "repair_page":
        candidates = [
            project_dir
            / "style_page_jobs"
            / f"style_{style}"
            / "repair_jobs"
            / f"page_{page_id}_attempt_{attempt}.json",
            project_dir
            / "repair_jobs"
            / f"style_{style}_page_{page_id}_attempt_{attempt}.json",
        ]
        existing = [path for path in candidates if path.is_file()]
        if len(existing) > 1:
            raise SystemExit(
                f"style_{style}/{page_id}/repair_page 存在多个候选任务文件"
            )
        return existing[0] if existing else candidates[0]
    return None


def clone_guarded_repair_job_for_technical_retry(
    state_path: Path,
    state: dict[str, Any],
    *,
    style: str | None,
    page_id: str,
    action: str,
    source_attempt: int,
    next_attempt: int,
) -> Path | None:
    """Create the next formal repair job without changing its sealed inputs."""

    if action not in {"repair_anchor", "repair_page"}:
        return None
    if not source_guard_enabled(state_path, state):
        return None
    project_dir = project_dir_for_state(state_path, state)
    mode = state.get("run_mode") or state.get("mode")
    selected_expansion = (
        state.get("phase") == "selected_style_expansion"
        or mode == "selected_style_expansion"
    )
    normalized_style = normalize_style(
        state.get("selected_style") if selected_expansion else style
    )
    if normalized_style is None:
        raise SystemExit("技术重试缺少规范风格席位")
    source_task = {
        "style": normalized_style,
        "page_id": page_id,
        "action": action,
        "attempt": source_attempt,
    }
    target_task = {**source_task, "attempt": next_attempt}
    if selected_expansion:
        if action != "repair_page":
            raise SystemExit("选定风格扩页只支持 repair_page 技术重试")
        source_job_path = (
            project_dir
            / "page_jobs"
            / "repair_jobs"
            / f"page_{page_id}_attempt_{source_attempt}.json"
        )
        target_job_path = (
            project_dir
            / "page_jobs"
            / "repair_jobs"
            / f"page_{page_id}_attempt_{next_attempt}.json"
        )
    else:
        source_job_path = generation_job_path_for_task(project_dir, source_task, mode)
        target_job_path = generation_job_path_for_task(project_dir, target_task, mode)
    if source_job_path is None or not source_job_path.is_file():
        raise SystemExit(
            f"技术重试缺少上一尝试的正式修复任务：style_{normalized_style}/"
            f"{page_id}/"
            f"{action}/attempt_{source_attempt}"
        )
    if target_job_path is None or target_job_path.resolve() == source_job_path.resolve():
        raise SystemExit(
            f"无法为技术重试确定独立任务路径：style_{normalized_style}/"
            f"{page_id}/{action}"
        )
    source_job = read_json(source_job_path)
    if source_job.get("style_slot") is not None and normalize_style(
        source_job.get("style_slot")
    ) != normalized_style:
        raise SystemExit(f"上一修复任务 style_slot 不匹配：{source_job_path}")
    source_page_id = source_job.get("page_id", source_job.get("anchor_page_id"))
    if not page_ids_match(source_page_id, page_id):
        raise SystemExit(f"上一修复任务 page_id 不匹配：{source_job_path}")
    if source_job.get("action") != action:
        raise SystemExit(f"上一修复任务 action 不匹配：{source_job_path}")
    if int(source_job.get("attempt") or 0) != source_attempt:
        raise SystemExit(f"上一修复任务 attempt 不匹配：{source_job_path}")
    retry_job = dict(source_job)
    retry_job["attempt"] = next_attempt
    generation_rules = retry_job.get("generation_rules")
    if isinstance(generation_rules, dict):
        generation_rules = dict(generation_rules)
        generation_rules["max_total_attempts_per_page"] = max(
            int(generation_rules.get("max_total_attempts_per_page") or 0),
            next_attempt,
        )
        retry_job["generation_rules"] = generation_rules
    write_idempotent(target_job_path, retry_job)
    return target_job_path.resolve()


def cached_file_sha256(path: Path, cache: dict[str, str]) -> str:
    resolved = str(path.resolve())
    if resolved not in cache:
        cache[resolved] = file_sha256(path)
    return cache[resolved]


def validate_generation_job_inputs(
    job_path: Path,
    *,
    internal_sources: set[str],
    hash_cache: dict[str, str] | None = None,
    require_prompt_fingerprint: bool = True,
    expected_task: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    project_dir: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read one formal job and bind its exact prompt inputs to files on disk."""

    job_path = job_path.resolve()
    if not job_path.is_file():
        raise SystemExit(f"生成任务文件不存在：{job_path}")
    job = read_json(job_path)
    cache = hash_cache if hash_cache is not None else {}
    if expected_task is not None:
        expected_style = normalize_style(expected_task.get("style"))
        expected_page_id = str(expected_task.get("page_id"))
        expected_action = str(expected_task.get("action"))
        expected_attempt = int(expected_task.get("attempt") or 1)
        if normalize_style(job.get("style_slot")) != expected_style:
            raise SystemExit(f"生成任务 style_slot 与派发任务不一致：{job_path}")
        job_page_id = job.get("page_id", job.get("anchor_page_id"))
        if not page_ids_match(job_page_id, expected_page_id):
            raise SystemExit(f"生成任务 page_id 与派发任务不一致：{job_path}")
        if job.get("action") != expected_action:
            raise SystemExit(f"生成任务 action 与派发任务不一致：{job_path}")
        job_attempt = int(job.get("attempt") or 0)
        immutable_initial_job_retry = (
            expected_task.get("technical_retry") is True
            and expected_action in {
                "generate_anchor",
                "generate_follower",
                "generate_page",
            }
            and expected_attempt > 1
            and job_attempt == 1
        )
        if job_attempt != expected_attempt and not immutable_initial_job_retry:
            raise SystemExit(f"生成任务 attempt 与派发任务不一致：{job_path}")
    contract_raw = job.get("source_content_contract_path")
    contract_sha = job.get("source_content_contract_sha256")
    if not isinstance(contract_raw, str) or not isinstance(contract_sha, str):
        raise SystemExit(f"新生成任务缺少内容合同来源绑定：{job_path}")
    contract_path = Path(contract_raw).expanduser()
    if not contract_path.is_absolute() or not contract_path.is_file():
        raise SystemExit(f"生成任务内容合同必须是存在的绝对路径：{job_path}")
    contract_path = contract_path.resolve()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", contract_sha):
        raise SystemExit(f"生成任务内容合同 SHA-256 无效：{job_path}")
    contract_sha = contract_sha.lower()
    if cached_file_sha256(contract_path, cache) != contract_sha:
        raise SystemExit(f"生成任务内容合同 SHA-256 与当前文件不一致：{contract_path}")
    if expected_task is not None:
        contract_value = read_json(contract_path)
        expected_page_id = str(expected_task.get("page_id"))
        if not page_ids_match(contract_value.get("page_id"), expected_page_id):
            raise SystemExit(f"绑定内容合同 page_id 与派发任务不一致：{contract_path}")
        anchor_page = job.get("anchor_page")
        if isinstance(anchor_page, dict) and not page_ids_match(
            anchor_page.get("page_id"), expected_page_id
        ):
            raise SystemExit(f"生成任务 anchor_page.page_id 与派发任务不一致：{job_path}")
        if project_dir is None:
            raise SystemExit("生成任务身份校验缺少 project_dir")
        expected_output = origin_image_target(
            project_dir,
            str(expected_task.get("style")),
            expected_page_id,
        ).resolve()
        expected_action = str(expected_task.get("action"))
        anchor_page = job.get("anchor_page")
        output_raw = (
            anchor_page.get("output_target")
            if expected_action in {"generate_anchor", "repair_anchor"}
            and isinstance(anchor_page, dict)
            and isinstance(anchor_page.get("output_target"), str)
            else job.get("output_target")
        )
        output_path = Path(output_raw).expanduser() if isinstance(output_raw, str) else None
        if (
            output_path is None
            or not output_path.is_absolute()
            or output_path.resolve() != expected_output
        ):
            raise SystemExit(f"生成任务 output_target 与规范原图路径不一致：{job_path}")

    manifest = job.get("imagegen_input_manifest")
    if not isinstance(manifest, list):
        raise SystemExit(f"图片输入清单必须是数组：{job_path}")
    referenced_paths = job.get("imagegen_referenced_paths")
    if not isinstance(referenced_paths, list):
        raise SystemExit(f"新生成任务缺少 imagegen_referenced_paths：{job_path}")
    normalized_referenced: list[str] = []
    for index, raw_path in enumerate(referenced_paths):
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise SystemExit(
                f"imagegen_referenced_paths[{index}] 不是非空路径：{job_path}"
            )
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise SystemExit(
                f"imagegen_referenced_paths[{index}] 必须是绝对路径：{job_path}"
            )
        normalized_referenced.append(str(path.resolve()))
    if len(set(normalized_referenced)) != len(normalized_referenced):
        raise SystemExit(f"imagegen_referenced_paths 不得包含重复附件：{job_path}")
    if len(normalized_referenced) > IMAGEGEN_MAX_REFERENCED_PATHS:
        raise SystemExit(
            "图片任务在派发前必须满足 ImageGen 附件上限："
            f"最多 {IMAGEGEN_MAX_REFERENCED_PATHS} 个 imagegen_referenced_paths，"
            f"实际 {len(normalized_referenced)} 个：{job_path}"
        )
    manifest_paths = [
        str(Path(str(item.get("path"))).expanduser().resolve())
        for item in manifest
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]
    if len(manifest_paths) != len(manifest) or normalized_referenced != manifest_paths:
        raise SystemExit(
            "imagegen_referenced_paths 与 imagegen_input_manifest 路径或顺序不一致："
            f"{job_path}"
        )
    if expected_task is not None:
        expected_action = str(expected_task.get("action"))
        text_family_follower = (
            expected_action == "generate_follower"
            and isinstance(job.get("layout_direction"), dict)
            and job["layout_direction"].get("style_family_portfolio_version")
            == CURRENT_4X3_STYLE_FAMILY_PORTFOLIO_VERSION
            and job.get("reference_images") == []
        )
        selected_style_regeneration_repair = (
            expected_action == "repair_page"
            and job.get("repair_input_policy") in {
                "regenerate_without_candidate",
                "regenerate_text_family",
            }
        )
        required_internal = (
            set()
            if text_family_follower
            or selected_style_regeneration_repair
            or (
                expected_action == "repair_anchor"
                and isinstance(job.get("diversity_replacement"), dict)
                and job["diversity_replacement"].get(
                    "reuse_source_candidate_as_image_input"
                )
                is False
            )
            else internal_sources
            if expected_action in {"generate_follower", "repair_anchor", "repair_page"}
            else set()
        )
        missing_internal = sorted(required_internal - set(normalized_referenced))
        if missing_internal:
            raise SystemExit(
                f"生成任务缺少当前动作必须引用的锚点或待修复候选：{job_path}；"
                + ", ".join(missing_internal)
            )
        if state is None:
            raise SystemExit("生成任务附件校验缺少正式状态")
        declared_items: list[Any] = []
        for field in ("reference_images", "required_assets", "required_page_assets"):
            field_value = job.get(field) or []
            if not isinstance(field_value, list):
                raise SystemExit(f"生成任务 {field} 必须是数组：{job_path}")
            declared_items.extend(field_value)
        declared_paths: list[str] = []
        for index, item in enumerate(declared_items):
            raw_path = item if isinstance(item, str) else item.get("path") if isinstance(item, dict) else None
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise SystemExit(
                    f"生成任务正式附件字段[{index}] 缺少非空 path：{job_path}"
                )
            declared_path = Path(raw_path).expanduser()
            if not declared_path.is_absolute():
                raise SystemExit(
                    f"生成任务正式附件字段[{index}] 必须是绝对路径：{job_path}"
                )
            declared_paths.append(str(declared_path.resolve()))
        if len(set(declared_paths)) != len(declared_paths):
            raise SystemExit(f"生成任务正式附件字段不得包含重复路径：{job_path}")
        if normalized_referenced != declared_paths:
            raise SystemExit(
                "生成任务正式附件字段与 imagegen_referenced_paths 的路径或顺序不一致："
                f"{job_path}"
            )
    if require_prompt_fingerprint:
        prompt = job.get("imagegen_prompt")
        fingerprint = job.get("imagegen_input_fingerprint")
        if not isinstance(prompt, str) or not isinstance(fingerprint, str):
            raise SystemExit(f"新生成任务缺少提示词或输入指纹：{job_path}")
        expected_fingerprint = hashlib.sha256(
            json.dumps(
                {"prompt": prompt, "inputs": manifest},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if fingerprint != expected_fingerprint:
            raise SystemExit(f"图片提示或输入清单指纹不一致：{job_path}")
        prompt_fingerprint = job.get("imagegen_prompt_fingerprint")
        if prompt_fingerprint is not None:
            expected_prompt_fingerprint = hashlib.sha256(
                prompt.encode("utf-8")
            ).hexdigest()
            if prompt_fingerprint != expected_prompt_fingerprint:
                raise SystemExit(f"图片提示独立指纹不一致：{job_path}")

    assets: list[dict[str, Any]] = []
    for item in manifest:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", str(item.get("sha256")))
        ):
            raise SystemExit(f"图片输入清单记录无效：{job_path}")
        resolved = str(Path(item["path"]).expanduser().resolve())
        resolved_path = Path(resolved)
        if not resolved_path.is_file():
            raise SystemExit(f"图片输入清单文件不存在：{resolved}")
        declared_sha = str(item["sha256"]).lower()
        if cached_file_sha256(resolved_path, cache) != declared_sha:
            raise SystemExit(f"图片输入清单 SHA-256 与当前文件不一致：{resolved}")
        if resolved in internal_sources:
            continue
        normalized = dict(item)
        normalized["path"] = resolved
        normalized["sha256"] = declared_sha
        assets.append(normalized)
    return ({"path": str(contract_path), "sha256": contract_sha}, assets)


def operation_inputs_for_generation_tasks(
    state_path: Path, state: dict[str, Any], tasks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    project_dir = project_dir_for_state(state_path, state)
    contracts_by_path: dict[str, dict[str, Any]] = {}
    assets_by_path: dict[str, dict[str, Any]] = {}
    hash_cache: dict[str, str] = {}
    for task in tasks:
        if task.get("action") == "recover_artifact":
            continue
        job_path = generation_job_path_for_task(
            project_dir, task, state.get("run_mode") or state.get("mode")
        )
        if job_path is None:
            continue
        internal_sources = allowed_internal_sources_for_task(state, task)
        contract, job_assets = validate_generation_job_inputs(
            job_path,
            internal_sources=internal_sources,
            hash_cache=hash_cache,
            expected_task=task,
            state=state,
            project_dir=project_dir,
        )
        contracts_by_path[contract["path"]] = contract
        for item in job_assets:
            normalized = dict(item)
            normalized["used_by"] = [normalize_style(str(task.get("style")))]
            existing = assets_by_path.get(normalized["path"])
            if existing is None:
                assets_by_path[normalized["path"]] = normalized
            else:
                existing["used_by"] = sorted(
                    {
                        *(existing.get("used_by") or []),
                        *(normalized.get("used_by") or []),
                    }
                )
    return (list(contracts_by_path.values()), list(assets_by_path.values()))


def formal_generation_job_bindings(
    state_path: Path,
    state: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> dict[tuple[str, str, str, int], dict[str, str]]:
    """Bind each dispatched image task to one exact formal job file and hash."""

    project_dir = project_dir_for_state(state_path, state)
    mode = state.get("run_mode") or state.get("mode")
    bindings: dict[tuple[str, str, str, int], dict[str, str]] = {}
    for task in tasks:
        if task.get("action") == "recover_artifact":
            continue
        path = generation_job_path_for_task(project_dir, task, mode)
        if path is None or not path.is_file():
            raise SystemExit(
                "图片任务缺少正式 generation job："
                f"{task.get('style')}/{task.get('page_id')}/"
                f"{task.get('action')}/attempt_{task.get('attempt')}"
            )
        path = path.resolve()
        key = (
            str(task["style"]),
            str(task["page_id"]),
            str(task["action"]),
            int(task.get("attempt") or 1),
        )
        bindings[key] = {
            "generation_job_path": str(path),
            "generation_job_sha256": file_sha256(path),
        }
    return bindings


def command_record_dispatch_wave(args: argparse.Namespace) -> None:
    """原子授权同波派发；真实 Worker 启动由后续结算身份与时间证明。"""

    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    mode = state.get("run_mode") or state.get("mode")
    if mode not in {
        QUICK_8X1_MODE,
        FAST8_MODE,
        FAST_4X3_MODE,
        STRICT_4X3_MODE,
        SELECTED_STYLE_EXPANSION_MODE,
    }:
        raise SystemExit(
            "record-dispatch-wave 当前只用于 quick_8x1、fast_8x1_diverse、"
            "fast_4x3_anchored、full_4x3_anchored 或 selected_style_expansion"
        )
    if mode == SELECTED_STYLE_EXPANSION_MODE:
        selected_style = normalize_style(state.get("selected_style"))
        if selected_style is None:
            raise SystemExit("选定风格扩页状态缺少 selected_style")
        allowed = {selected_style}
    else:
        allowed = set(styles_for_mode(mode))
    raw_tasks = json.loads(args.tasks_json) if getattr(args, "tasks_json", None) else None
    if raw_tasks is not None:
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise SystemExit("--tasks-json 必须是非空任务数组")
        requested_tasks = raw_tasks
        legacy_request = False
    else:
        raw_styles = getattr(args, "styles", None)
        styles = (
            parse_style_csv(raw_styles)
            if raw_styles
            else list(allowed)
        )
        if not set(styles).issubset(allowed):
            raise SystemExit("--styles 包含当前运行未启用的席位")
        page_id = str(args.page_id or state.get("anchor_page_id"))
        requested_tasks = [
            {
                "style": style,
                "page_id": page_id,
                "action": args.action,
                "attempt": args.attempt,
            }
            for style in styles
        ]
        legacy_request = True

    normalized_tasks: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(requested_tasks):
        if not isinstance(raw, dict):
            raise SystemExit(f"tasks[{index}] 必须是对象")
        style = normalize_style(raw.get("style"))
        page_id = str(raw.get("page_id") or state.get("anchor_page_id"))
        action = raw.get("action") or "generate_anchor"
        attempt = raw.get("attempt", 1)
        if style not in allowed:
            raise SystemExit(f"tasks[{index}].style 未在当前运行启用")
        if action not in GENERATION_ACTIONS | {"recover_artifact"}:
            raise SystemExit(f"tasks[{index}].action 无效：{action}")
        if not isinstance(attempt, int) or attempt < 1:
            raise SystemExit(f"tasks[{index}].attempt 必须是正整数")
        key = (style, page_id, action)
        if key in seen_keys:
            raise SystemExit(f"--tasks-json 包含重复任务：{key}")
        seen_keys.add(key)
        normalized_tasks.append(
            {
                "style": style,
                "page_id": page_id,
                "action": action,
                "attempt": attempt,
            }
        )

    action_kinds = {item["action"] == "recover_artifact" for item in normalized_tasks}
    if len(action_kinds) > 1:
        raise SystemExit(
            "同一派发波不得混合 recover_artifact 与图片生成；"
            "请先单独派发 recovery-only 波"
        )
    timestamp = args.timestamp or now_iso()
    agent_map = json.loads(args.agent_map_json) if args.agent_map_json else {}
    if not isinstance(agent_map, dict):
        raise SystemExit("--agent-map-json 必须是对象")

    def dispatched_worker_for(task: dict[str, Any]) -> Any:
        task_key = (
            f"{task['style']}/{task['page_id']}/{task['action']}/{task['attempt']}"
        )
        legacy_task_key = f"{task['style']}/{task['page_id']}/{task['action']}"
        return agent_map.get(
            task_key,
            agent_map.get(legacy_task_key, agent_map.get(task["style"])),
        )

    scheduler = state.setdefault("scheduler", {})
    ready = scheduler.setdefault("ready_queue", [])
    active = scheduler.setdefault("active_actions", [])
    recovery_queue = scheduler.setdefault("recovery_queue", [])

    ready_before = [dict(item) for item in ready if isinstance(item, dict)]
    requested_styles_before = list(
        dict.fromkeys(
            str(item.get("style"))
            for item in ready_before
            if str(item.get("page_id"))
            == str(state.get("anchor_page_id"))
            and item.get("action") == "generate_anchor"
        )
    )
    startable: list[dict[str, Any]] = []
    for task in normalized_tasks:
        style = task["style"]
        page_id = task["page_id"]
        action = task["action"]
        attempt = int(task["attempt"])
        record = page_record(state, style, page_id)
        queued_technical_retry = any(
            item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == action
            and int(item.get("attempt") or 1) == attempt
            and item.get("technical_retry") is True
            for item in ready
        )
        already_active = any(
            item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == action
            for item in active
        )
        if already_active:
            active_attempts = {
                int(item.get("attempt") or 1)
                for item in active
                if item.get("style") == style
                and str(item.get("page_id")) == page_id
                and item.get("action") == action
            }
            if active_attempts != {attempt}:
                raise SystemExit(
                    f"style_{style}/{page_id}/{action} 已按 attempt="
                    f"{sorted(active_attempts)} 派发，拒绝改为 attempt={attempt}"
                )
            continue
        if action in {"repair_anchor", "repair_page"}:
            if not record.get("selected_source") or not record.get("tool_call_id"):
                raise SystemExit(f"style_{style}/{page_id} 没有可供定向修复的候选")
        elif action != "recover_artifact" and (
            record.get("selected_source")
            or (record.get("tool_call_id") and not queued_technical_retry)
        ):
            continue
        recovery_pending = any(
            item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == "recover_artifact"
            for item in recovery_queue
        )
        if action != "recover_artifact" and recovery_pending:
            raise SystemExit(
                f"style_{style}/{page_id} 正在等待 recover_artifact，禁止重复生图"
            )
        queue = recovery_queue if action == "recover_artifact" else ready
        queue_matches = [
            item
            for item in queue
            if item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == action
        ]
        if not queue_matches:
            raise SystemExit(f"任务尚未进入可派队列：style_{style}/{page_id}/{action}")
        queued_attempts = {int(item.get("attempt") or 1) for item in queue_matches}
        if queued_attempts != {attempt}:
            raise SystemExit(
                f"style_{style}/{page_id}/{action} 队列 attempt="
                f"{sorted(queued_attempts)}，拒绝派发 attempt={attempt}"
            )
        startable_task = dict(task)
        if any(item.get("technical_retry") is True for item in queue_matches):
            startable_task["technical_retry"] = True
        startable.append(startable_task)

    if not startable:
        raise SystemExit(
            "本次派发没有启动任何任务；请求可能已在 active_actions 或已经完成，"
            "拒绝记录 status=ok, started=0"
        )

    if (
        mode == FAST8_MODE
        and state.get("fast8_startup_contract_version")
        == FAST8_STARTUP_CONTRACT_VERSION
    ):
        identities = [dispatched_worker_for(task) for task in startable]
        missing = [
            task["style"]
            for task, identity in zip(startable, identities)
            if not isinstance(identity, str) or not identity.strip()
        ]
        if missing:
            raise SystemExit(
                "新 Fast8 派发前必须用 --agent-map-json 为每席绑定唯一 Worker "
                "task_name 或 Agent ID；缺少：" + ",".join(missing)
            )
        normalized_identities = [str(identity).strip() for identity in identities]
        if len(normalized_identities) != len(set(normalized_identities)):
            raise SystemExit("新 Fast8 同一派发波的 Worker 身份必须逐任务唯一")

    job_bindings: dict[tuple[str, str, str, int], dict[str, str]] = {}
    if any(item["action"] != "recover_artifact" for item in startable):
        operation_contracts: list[dict[str, Any]] | None = None
        operation_assets: list[dict[str, Any]] | None = None
        guard_page_ids = list(
            dict.fromkeys(str(item["page_id"]) for item in startable)
        )
        base_result = enforce_source_guard(
            state_path,
            state,
            action="generation_dispatch",
            page_ids=guard_page_ids,
        )
        job_bindings = formal_generation_job_bindings(
            state_path, state, startable
        )
        if source_guard_enabled(state_path, state):
            operation_contracts, operation_assets = operation_inputs_for_generation_tasks(
                state_path, state, startable
            )
            snapshot_path = source_snapshot_path_for_state(state_path, state)
            if base_result is None or snapshot_path is None or not snapshot_path.is_file():
                raise SystemExit("生成派发来源门禁缺少已绑定的 source snapshot")
            operation_result = apply_operation_manifest_coverage(
                base_result,
                read_json(snapshot_path),
                content_contract_paths=operation_contracts,
                asset_items=operation_assets,
                page_ids=guard_page_ids,
            )
            finalize_source_guard_result(state_path, state, operation_result)

    limit = int(
        scheduler.get("active_child_limit") or active_child_limit_for_state(state)
    )
    local_deferred_tasks: list[dict[str, Any]] = []
    if mode == FAST8_MODE:
        image_limit = int(scheduler.get("image_child_limit") or 8)
        local_available = max(0, image_limit - len(active))
        if len(startable) > local_available:
            local_deferred_tasks = startable[local_available:]
            startable = startable[:local_available]
    else:
        local_available = max(0, limit - len(active))
        if len(startable) > local_available:
            raise SystemExit(
                f"派发后 active_actions 将超过并发上限："
                f"{len(active)}+{len(startable)}>{limit}"
            )

    global_deferred_tasks: list[dict[str, Any]] = []
    global_lease_ids: dict[str, str] = {}
    global_available_slots: int | None = None
    imagegen_slot_policy = (
        fast8_imagegen_slot_policy(state) if mode == FAST8_MODE else None
    )
    if mode == FAST8_MODE and all(
        item["action"] != "recover_artifact" for item in startable
    ) and imagegen_slot_policy == LEGACY_FAST8_IMAGEGEN_SLOT_POLICY:
        (
            startable,
            global_deferred_tasks,
            global_lease_ids,
            global_available_slots,
        ) = acquire_fast8_global_imagegen_slots(
            state_path,
            state,
            startable,
            timestamp=timestamp,
        )

    if len(active) + len(startable) > limit:
        raise SystemExit(
            f"派发后 active_actions 将超过并发上限：{len(active)}+{len(startable)}>{limit}"
        )

    started_tasks: list[dict[str, Any]] = []
    for task in startable:
        style = task["style"]
        page_id = task["page_id"]
        action = task["action"]
        queue = recovery_queue if action == "recover_artifact" else ready
        queued_item = next(
            item
            for item in queue
            if item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == action
            and int(item.get("attempt") or 1) == int(task["attempt"])
        )
        if action != "recover_artifact":
            binding_key = (style, page_id, action, int(task["attempt"]))
            binding = job_bindings[binding_key]
            queued_path = queued_item.get("generation_job_path")
            if queued_path is not None and str(
                Path(str(queued_path)).expanduser().resolve()
            ) != binding["generation_job_path"]:
                raise SystemExit(
                    f"队列中的 generation_job_path 与正式任务不一致："
                    f"style_{style}/{page_id}/{action}"
                )
            queued_sha = queued_item.get("generation_job_sha256")
            if queued_sha is not None and queued_sha != binding["generation_job_sha256"]:
                raise SystemExit(
                    f"队列中的 generation_job_sha256 与正式任务不一致："
                    f"style_{style}/{page_id}/{action}"
                )
            queued_item.update(binding)
        queue[:] = [
            item
            for item in queue
            if not (
                item.get("style") == style
                and str(item.get("page_id")) == page_id
                and item.get("action") == action
            )
        ]
        dispatched_worker = dispatched_worker_for(task)
        active_item = {
            **queued_item,
            **task,
            "dispatch_requested_at": timestamp,
            "dispatch_authorized_at": timestamp,
            "worker_start_status": "authorized_unconfirmed",
            **(
                {"recovery_worker_agent_id": dispatched_worker}
                if action == "recover_artifact"
                else {"worker_agent_id": dispatched_worker}
            ),
        }
        if (
            mode == FAST8_MODE
            and action != "recover_artifact"
            and imagegen_slot_policy == LEGACY_FAST8_IMAGEGEN_SLOT_POLICY
        ):
            lease_task_key = f"{style}/{page_id}/{action}/{int(task['attempt'])}"
            lease_id = global_lease_ids.get(lease_task_key)
            if not isinstance(lease_id, str):
                raise SystemExit(
                    f"style_{style}/{page_id}/{action} 缺少全局 ImageGen 槽位租约"
                )
            active_item["global_imagegen_lease_id"] = lease_id
        if mode == FAST8_MODE and action != "recover_artifact":
            job_path = Path(str(active_item["generation_job_path"])).resolve()
            job = read_json(job_path)
            receipt_contract = job.get("worker_receipt") or {}
            receipt_path_value = receipt_contract.get("path")
            if not isinstance(receipt_path_value, str):
                raise SystemExit(
                    f"style_{style}/{page_id}/{action} 缺少 Worker 回执路径"
                )
            project_dir = project_dir_for_state(state_path, state)
            canonical_receipt_path = fast8_worker_receipt_path(
                project_dir,
                style,
                page_id,
                action,
                int(task["attempt"]),
            ).resolve()
            job_receipt_path = Path(receipt_path_value).expanduser().resolve()
            if int(task["attempt"]) == int(job.get("attempt") or 1) and (
                job_receipt_path != canonical_receipt_path
            ):
                raise SystemExit(
                    f"style_{style}/{page_id}/{action} 的正式 job 回执路径不规范"
                )
            active_item["worker_receipt_path"] = str(canonical_receipt_path)
            ticket_path = fast8_worker_ticket_path(
                project_dir,
                style,
                page_id,
                action,
                int(task["attempt"]),
            ).resolve()
            worker_runtime_contract = job.get("worker_runtime_contract")
            ticket_version = (
                FAST8_WORKER_TICKET_CONTRACT_VERSION
                if isinstance(worker_runtime_contract, dict)
                else 1
            )
            ticket = {
                "fast8_worker_ticket_contract_version": ticket_version,
                "run_id": state.get("run_id"),
                "state_path": str(state_path),
                "style": style,
                "page_id": page_id,
                "action": action,
                "attempt": int(task["attempt"]),
                "worker_task_name": dispatched_worker,
                "generation_job_path": str(job_path),
                "generation_job_sha256": active_item["generation_job_sha256"],
                "imagegen_input_fingerprint": job.get(
                    "imagegen_input_fingerprint"
                ),
                "worker_receipt_path": str(canonical_receipt_path),
                "contains_image_payload": False,
            }
            if ticket_version == FAST8_WORKER_TICKET_CONTRACT_VERSION:
                ticket["worker_runtime_contract"] = worker_runtime_contract
            write_idempotent(ticket_path, ticket)
            active_item["worker_ticket_path"] = str(ticket_path)
            active_item["worker_ticket_sha256"] = file_sha256(ticket_path)
        if action in {"repair_anchor", "repair_page"} and not isinstance(
            active_item.get("incumbent_candidate"), dict
        ):
            incumbent = incumbent_candidate_snapshot(
                page_record(state, style, page_id)
            )
            if incumbent is not None:
                active_item["incumbent_candidate"] = incumbent
        active.append(active_item)
        started_tasks.append(active_item)
        if action == "generate_follower":
            style_state = (state.get("styles") or {}).get(style)
            if isinstance(style_state, dict):
                style_state["workflow_status"] = "followers_running"

    started_styles = list(dict.fromkeys(item["style"] for item in started_tasks))
    deferred_tasks: list[dict[str, Any]] = []
    if legacy_request:
        deferred_tasks = [
            {
                "style": style,
                "page_id": str(state.get("anchor_page_id")),
                "action": "generate_anchor",
            }
            for style in requested_styles_before
            if style not in set(started_styles)
        ]
    else:
        deferred_tasks = [
            {
                "style": item.get("style"),
                "page_id": str(item.get("page_id")),
                "action": item.get("action"),
            }
            for item in ready + recovery_queue
            if isinstance(item, dict)
        ]
    deferred_styles = list(
        dict.fromkeys(
            str(item.get("style"))
            for item in deferred_tasks
            if item.get("style") is not None
        )
    )
    backpressure_reason = (getattr(args, "backpressure_reason", None) or "").strip()
    if local_deferred_tasks:
        automatic_reason = "run_image_child_capacity"
        backpressure_reason = (
            f"{backpressure_reason};{automatic_reason}"
            if backpressure_reason
            else automatic_reason
        )
    if global_deferred_tasks:
        automatic_reason = "global_imagegen_capacity"
        backpressure_reason = (
            f"{backpressure_reason};{automatic_reason}"
            if backpressure_reason
            else automatic_reason
        )
    if deferred_tasks and not backpressure_reason:
        raise SystemExit(
            "实际派发少于当前可派任务；必须用 --backpressure-reason "
            "记录运行时背压原因"
        )

    timing = state.setdefault("timing", {})
    initial_anchor_tasks = [
        item
        for item in started_tasks
        if item["action"] == "generate_anchor"
        and item["page_id"] == str(state.get("anchor_page_id"))
    ]
    if initial_anchor_tasks and not timing.get("initial_anchor_dispatch_at"):
        timing["initial_anchor_dispatch_at"] = timestamp
        append_event(
            state,
            "initial_anchor_dispatch",
            timestamp,
            details={
                "requested_styles": requested_styles_before,
                "started_styles": [item["style"] for item in initial_anchor_tasks],
                "dispatch_policy": scheduler.get("dispatch_policy"),
                "dispatch_semantics": "authorization_not_worker_start_proof",
            },
        )

    follower_tasks = [
        item for item in started_tasks if item["action"] == "generate_follower"
    ]
    if follower_tasks and not timing.get("follower_generation_started_at"):
        timing["follower_generation_started_at"] = timestamp
        append_event(
            state,
            "follower_generation_started",
            timestamp,
            details={"started_tasks": follower_tasks},
        )

    existing_observations = [
        event
        for event in state.get("events", [])
        if isinstance(event, dict)
        and event.get("name") in {"dispatch_wave", "runtime_backpressure"}
    ]
    wave_id = f"dispatch_wave_{len(existing_observations) + 1:02d}"
    observation_tasks = started_tasks or normalized_tasks
    homogeneous_pages = {item["page_id"] for item in observation_tasks}
    homogeneous_actions = {item["action"] for item in observation_tasks}
    event_page_id = next(iter(homogeneous_pages)) if len(homogeneous_pages) == 1 else None
    event_action = next(iter(homogeneous_actions)) if len(homogeneous_actions) == 1 else None
    if started_tasks:
        append_event(
            state,
            "dispatch_wave",
            timestamp,
            page_id=event_page_id,
            action=event_action,
            details={
                "wave_id": wave_id,
                "requested_styles": requested_styles_before,
                "started_styles": started_styles,
                "started_tasks": started_tasks,
                "deferred_styles": deferred_styles,
                "deferred_tasks": deferred_tasks,
                "dispatch_semantics": "authorization_not_worker_start_proof",
            },
        )
    if deferred_tasks:
        backpressure = {
            "wave_id": wave_id,
            "requested": len(started_tasks) + len(deferred_tasks),
            "started": len(started_tasks),
            "requested_styles": requested_styles_before,
            "started_styles": started_styles,
            "deferred_styles": deferred_styles,
            "deferred_tasks": deferred_tasks,
            "reason": backpressure_reason,
        }
        prior_backpressure_event = next(
            (
                event
                for event in reversed(state.get("events") or [])
                if isinstance(event, dict)
                and event.get("name") == "runtime_backpressure"
            ),
            None,
        )
        prior_details = (
            (prior_backpressure_event.get("details") or {})
            if isinstance(prior_backpressure_event, dict)
            else {}
        )
        coalesced_backpressure = bool(
            not started_tasks
            and int(prior_details.get("started") or 0) == 0
            and prior_details.get("reason") == backpressure["reason"]
            and prior_details.get("deferred_tasks") == backpressure["deferred_tasks"]
        )
        if coalesced_backpressure:
            wave_id = str(prior_details.get("wave_id") or wave_id)
            runtime_rows = scheduler.setdefault("runtime_backpressure", [])
            prior_row = next(
                (
                    item
                    for item in reversed(runtime_rows)
                    if isinstance(item, dict) and item.get("wave_id") == wave_id
                ),
                None,
            )
            if isinstance(prior_row, dict):
                prior_row["poll_count"] = int(prior_row.get("poll_count") or 1) + 1
                prior_row["last_observed_at"] = timestamp
        else:
            append_event(
                state,
                "runtime_backpressure",
                timestamp,
                page_id=event_page_id,
                action=event_action,
                details=backpressure,
            )
            scheduler.setdefault("runtime_backpressure", []).append(
                {
                    "occurred_at": timestamp,
                    "last_observed_at": timestamp,
                    "poll_count": 1,
                    **backpressure,
                }
            )
    else:
        coalesced_backpressure = False
    atomic_write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "ok" if started_tasks else "backpressured",
                "started": len(started_tasks),
                "authorized": len(started_tasks),
                "dispatch_semantics": "authorization_not_worker_start_proof",
                "styles": started_styles,
                "tasks": started_tasks,
                "deferred_styles": deferred_styles,
                "wave_id": wave_id if started_tasks else None,
                "active_count": len(active),
                "available_slots": max(0, limit - len(active)),
                "global_imagegen_available_slots": global_available_slots,
                "global_imagegen_deferred": len(global_deferred_tasks),
                "imagegen_slot_policy": imagegen_slot_policy,
                "backpressure_poll_coalesced": coalesced_backpressure,
                "retry_after_seconds": 15 if not started_tasks else 0,
                "occurred_at": timestamp,
            },
            ensure_ascii=False,
        )
    )


def command_bind_fast8_worker_sessions(args: argparse.Namespace) -> None:
    """Bind create-agent UUIDs to already-authorized Fast8 actions."""

    state_path = Path(args.state).expanduser().resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("bind-fast8-worker-sessions 只适用于 fast_8x1_diverse")
    raw_map = json.loads(args.session_map_json)
    if not isinstance(raw_map, dict) or not raw_map:
        raise SystemExit("--session-map-json 必须是非空对象")
    requested_styles = (
        set(parse_style_csv(args.styles)) if getattr(args, "styles", None) else None
    )
    active = (state.get("scheduler") or {}).get("active_actions") or []
    targets = [
        item
        for item in active
        if isinstance(item, dict)
        and item.get("action") in GENERATION_ACTIONS
        and (
            requested_styles is None
            or normalize_style(item.get("style")) in requested_styles
        )
    ]
    if not targets:
        raise SystemExit("没有可绑定 Worker session 的 active Fast8 图片任务")

    actual_runtime = {
        "model": str(getattr(args, "model", "") or ""),
        "reasoning_effort": str(
            getattr(args, "reasoning_effort", "") or ""
        ),
        "fork_turns": str(getattr(args, "fork_turns", "") or ""),
    }
    runtime_contracts: dict[int, dict[str, Any] | None] = {}
    for item in targets:
        ticket_path_value = item.get("worker_ticket_path")
        if not isinstance(ticket_path_value, str):
            raise SystemExit("active Fast8 图片任务缺少 Worker ticket")
        ticket_path = Path(ticket_path_value).expanduser().resolve()
        if not ticket_path.is_file() or item.get(
            "worker_ticket_sha256"
        ) != file_sha256(ticket_path):
            raise SystemExit("active Fast8 图片任务的 Worker ticket 已变化")
        ticket = read_json(ticket_path)
        ticket_version = ticket.get("fast8_worker_ticket_contract_version")
        if ticket_version not in FAST8_WORKER_TICKET_SUPPORTED_VERSIONS:
            raise SystemExit("Fast8 Worker ticket 合同版本无效")
        if ticket_version == 1:
            runtime_contracts[id(item)] = None
            continue
        contract = ticket.get("worker_runtime_contract")
        if not isinstance(contract, dict):
            raise SystemExit("Fast8 Worker ticket v2 缺少运行时合同")
        expected_runtime = {
            "model": contract.get("required_model"),
            "reasoning_effort": contract.get("required_reasoning_effort"),
            "fork_turns": contract.get("required_fork_turns"),
        }
        if (
            contract.get("session_binding_required") is not True
            or contract.get("imagegen_prompt_must_be_verbatim") is not True
            or actual_runtime != expected_runtime
        ):
            raise SystemExit(
                "Fast8 图片 Worker 运行时不符合正式合同："
                f"required={expected_runtime} actual={actual_runtime}"
            )
        runtime_contracts[id(item)] = contract

    def mapped_session(item: dict[str, Any]) -> Any:
        style = str(item.get("style"))
        page_id = str(item.get("page_id"))
        action = str(item.get("action"))
        attempt = int(item.get("attempt") or 1)
        full_key = f"{style}/{page_id}/{action}/{attempt}"
        legacy_key = f"{style}/{page_id}/{action}"
        return raw_map.get(full_key, raw_map.get(legacy_key, raw_map.get(style)))

    resolved: list[tuple[dict[str, Any], str]] = []
    missing: list[str] = []
    for item in targets:
        value = mapped_session(item)
        style = str(item.get("style"))
        if not isinstance(value, str) or not value.strip():
            missing.append(style)
            continue
        session_id = value.strip().lower()
        if CODEX_AGENT_THREAD_ID_RE.fullmatch(session_id) is None:
            raise SystemExit(
                f"style_{style} 的 Worker session 不是合法 Agent UUID：{value!r}"
            )
        resolved.append((item, session_id))
    if missing:
        raise SystemExit("缺少 Worker session：" + ",".join(sorted(missing)))
    session_ids = [session_id for _, session_id in resolved]
    if len(session_ids) != len(set(session_ids)):
        raise SystemExit("同一批 Fast8 图片任务不得共享 Worker session")
    other_bound = {
        str(item.get("worker_session_id"))
        for item in active
        if isinstance(item, dict)
        and item not in targets
        and isinstance(item.get("worker_session_id"), str)
    }
    duplicates = sorted(set(session_ids) & other_bound)
    if duplicates:
        raise SystemExit("Worker session 已绑定其他任务：" + ",".join(duplicates))

    timestamp = args.timestamp or now_iso()
    authorized_times = [
        item.get("dispatch_authorized_at")
        for item, _session_id in resolved
        if isinstance(item.get("dispatch_authorized_at"), str)
    ]
    batch_authorized_at = (
        min(authorized_times, key=parse_time) if authorized_times else None
    )
    try:
        authorization_to_batch_bound_seconds = round(
            (parse_time(timestamp) - parse_time(batch_authorized_at)).total_seconds(),
            3,
        )
    except (TypeError, ValueError):
        authorization_to_batch_bound_seconds = None
    batch_identity = {
        "run_id": state.get("run_id"),
        "bound_at": timestamp,
        "sessions": sorted(session_id for _item, session_id in resolved),
    }
    worker_batch_id = "worker_batch_" + hashlib.sha256(
        json.dumps(batch_identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    audit_items: list[dict[str, Any]] = []
    already_bound_items: list[dict[str, Any]] = []
    for item, session_id in resolved:
        existing = item.get("worker_session_id")
        if existing not in {None, session_id}:
            raise SystemExit(
                f"style_{item.get('style')} 已绑定不同 Worker session：{existing}"
            )
        if (
            existing == session_id
            and item.get("worker_start_status") == "worker_started_confirmed"
        ):
            # A resumed Worker may self-bind again before continuing the exact
            # same ticket.  Treat that as a read-only idempotent check: do not
            # overwrite the first real bind time or add a second batch record.
            already_bound_items.append(
                {
                    "style": item.get("style"),
                    "page_id": str(item.get("page_id")),
                    "action": item.get("action"),
                    "attempt": int(item.get("attempt") or 1),
                    "worker_task_name": item.get("worker_agent_id"),
                    "worker_session_id": session_id,
                    "worker_ticket_path": item.get("worker_ticket_path"),
                }
            )
            continue
        item["worker_session_id"] = session_id
        item["worker_session_bound_at"] = timestamp
        item["worker_start_status"] = "worker_started_confirmed"
        runtime_contract = runtime_contracts.get(id(item))
        if isinstance(runtime_contract, dict):
            item["worker_runtime_binding"] = {
                "session_id": session_id,
                **actual_runtime,
                "bound_at": timestamp,
            }
        audit_items.append(
            {
                "style": item.get("style"),
                "page_id": str(item.get("page_id")),
                "action": item.get("action"),
                "attempt": int(item.get("attempt") or 1),
                "worker_task_name": item.get("worker_agent_id"),
                "worker_session_id": session_id,
                "worker_ticket_path": item.get("worker_ticket_path"),
                **(
                    {"worker_runtime_binding": item["worker_runtime_binding"]}
                    if isinstance(runtime_contract, dict)
                    else {}
                ),
            }
        )
    if not audit_items:
        print(
            json.dumps(
                {
                    "status": "already_bound",
                    "bound": 0,
                    "already_bound": len(already_bound_items),
                    "tasks": already_bound_items,
                    "occurred_at": timestamp,
                },
                ensure_ascii=False,
            )
        )
        return
    scheduler = state.setdefault("scheduler", {})
    scheduler.setdefault("worker_session_bindings", []).append(
        {
            "worker_batch_id": worker_batch_id,
            "batch_size": len(audit_items),
            "authorized_at": batch_authorized_at,
            "bound_at": timestamp,
            "authorization_to_batch_bound_seconds": (
                authorization_to_batch_bound_seconds
            ),
            "tasks": audit_items,
        }
    )
    timing = state.setdefault("timing", {})
    timing.setdefault("first_worker_batch_bound_at", timestamp)
    timing["last_worker_batch_bound_at"] = timestamp
    atomic_write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "ok",
                "bound": len(audit_items),
                "already_bound": len(already_bound_items),
                "worker_batch_id": worker_batch_id,
                "authorization_to_batch_bound_seconds": (
                    authorization_to_batch_bound_seconds
                ),
                "tasks": audit_items,
                "occurred_at": timestamp,
            },
            ensure_ascii=False,
        )
    )


def command_self_bind_fast8_worker_session(args: argparse.Namespace) -> None:
    """Bind one Worker from its trusted Codex runtime environment."""

    state_path = Path(args.state).expanduser().resolve()
    ticket_path = Path(args.ticket).expanduser().resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("self-bind-fast8-worker-session 只适用于 fast_8x1_diverse")
    project_dir = project_dir_for_state(state_path, state)
    require_path_within(
        ticket_path,
        project_dir / "style_jobs" / "dispatch_tickets",
        "Fast8 Worker ticket",
    )
    if not ticket_path.is_file():
        raise SystemExit("Fast8 Worker ticket 不存在")
    ticket = read_json(ticket_path)
    if ticket.get("run_id") != state.get("run_id") or str(
        Path(str(ticket.get("state_path"))).expanduser().resolve()
    ) != str(state_path):
        raise SystemExit("Fast8 Worker ticket 与当前运行不一致")
    style = normalize_style(ticket.get("style"))
    page_id = str(ticket.get("page_id"))
    action = str(ticket.get("action"))
    attempt = int(ticket.get("attempt") or 0)
    active_item = next(
        (
            item
            for item in ((state.get("scheduler") or {}).get("active_actions") or [])
            if isinstance(item, dict)
            and item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == action
            and int(item.get("attempt") or 1) == attempt
        ),
        None,
    )
    if not isinstance(active_item, dict):
        raise SystemExit("Fast8 Worker ticket 没有匹配的 active_action")
    if (
        active_item.get("worker_ticket_path") != str(ticket_path)
        or active_item.get("worker_ticket_sha256") != file_sha256(ticket_path)
        or active_item.get("worker_agent_id") != ticket.get("worker_task_name")
    ):
        raise SystemExit("Fast8 Worker ticket 与 active_action 绑定无效")
    session_id = str(os.environ.get("CODEX_THREAD_ID") or "").strip().lower()
    if CODEX_AGENT_THREAD_ID_RE.fullmatch(session_id) is None:
        raise SystemExit("运行环境缺少合法 CODEX_THREAD_ID，禁止调用 ImageGen")

    # Eight Workers may self-register at once.  Serialize only this tiny state
    # mutation; generation jobs and image payloads remain untouched.
    lock_path = state_path.with_suffix(state_path.suffix + ".worker-bind.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                command_bind_fast8_worker_sessions(
                    argparse.Namespace(
                        state=str(state_path),
                        session_map_json=json.dumps({style: session_id}),
                        styles=style,
                        model=str(args.model),
                        reasoning_effort=str(args.reasoning_effort),
                        fork_turns=str(args.fork_turns),
                        timestamp=getattr(args, "timestamp", None),
                    )
                )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    result = json.loads(captured.getvalue())
    result["binding_source"] = "worker_runtime_environment"
    result["worker_session_id"] = session_id
    print(json.dumps(result, ensure_ascii=False))


def command_check_fast8_worker_ticket(args: argparse.Namespace) -> None:
    """Validate one dispatch ticket against state and its generation job."""

    state_path = Path(args.state).expanduser().resolve()
    ticket_path = Path(args.ticket).expanduser().resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("check-fast8-worker-ticket 只适用于 fast_8x1_diverse")
    require_path_within(
        ticket_path,
        project_dir_for_state(state_path, state) / "style_jobs" / "dispatch_tickets",
        "Fast8 Worker ticket",
    )
    ticket = read_json(ticket_path)
    legacy_allowed_fields = {
        "fast8_worker_ticket_contract_version",
        "run_id",
        "state_path",
        "style",
        "page_id",
        "action",
        "attempt",
        "worker_task_name",
        "generation_job_path",
        "generation_job_sha256",
        "imagegen_input_fingerprint",
        "worker_receipt_path",
        "contains_image_payload",
    }
    current_allowed_fields = legacy_allowed_fields | {"worker_runtime_contract"}
    ticket_version = ticket.get("fast8_worker_ticket_contract_version")
    if ticket_version not in FAST8_WORKER_TICKET_SUPPORTED_VERSIONS:
        raise SystemExit("Fast8 Worker ticket 合同版本无效")
    expected_fields = (
        legacy_allowed_fields if ticket_version == 1 else current_allowed_fields
    )
    if set(ticket) != expected_fields:
        raise SystemExit("Fast8 Worker ticket 字段集合无效")
    if ticket.get("run_id") != state.get("run_id"):
        raise SystemExit("Fast8 Worker ticket 的 run_id 与状态不一致")
    if str(Path(str(ticket.get("state_path"))).resolve()) != str(state_path):
        raise SystemExit("Fast8 Worker ticket 的 state_path 与当前状态不一致")
    style = normalize_style(ticket.get("style"))
    page_id = str(ticket.get("page_id"))
    action = str(ticket.get("action"))
    attempt = int(ticket.get("attempt") or 0)
    active_item = next(
        (
            item
            for item in ((state.get("scheduler") or {}).get("active_actions") or [])
            if isinstance(item, dict)
            and item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == action
            and int(item.get("attempt") or 1) == attempt
        ),
        None,
    )
    if not isinstance(active_item, dict):
        raise SystemExit("Fast8 Worker ticket 没有匹配的 active_action")
    if active_item.get("worker_ticket_path") != str(ticket_path):
        raise SystemExit("Fast8 Worker ticket 路径与 active_action 不一致")
    if active_item.get("worker_ticket_sha256") != file_sha256(ticket_path):
        raise SystemExit("Fast8 Worker ticket SHA-256 与 active_action 不一致")
    if ticket.get("worker_task_name") != active_item.get("worker_agent_id"):
        raise SystemExit("Fast8 Worker ticket 的 task_name 与 active_action 不一致")
    job_path = Path(str(ticket.get("generation_job_path"))).expanduser().resolve()
    job_sha = str(ticket.get("generation_job_sha256") or "")
    if (
        active_item.get("generation_job_path") != str(job_path)
        or active_item.get("generation_job_sha256") != job_sha
        or not job_path.is_file()
        or file_sha256(job_path) != job_sha
    ):
        raise SystemExit("Fast8 Worker ticket 的 generation job 绑定无效")
    job = read_json(job_path)
    if job.get("imagegen_input_fingerprint") != ticket.get(
        "imagegen_input_fingerprint"
    ):
        raise SystemExit("Fast8 Worker ticket 的图片输入指纹与 job 不一致")
    worker_runtime_contract = ticket.get("worker_runtime_contract")
    if ticket_version == 2:
        if (
            not isinstance(worker_runtime_contract, dict)
            or worker_runtime_contract != job.get("worker_runtime_contract")
            or worker_runtime_contract.get("session_binding_required") is not True
            or worker_runtime_contract.get("imagegen_prompt_must_be_verbatim")
            is not True
        ):
            raise SystemExit("Fast8 Worker ticket 的运行时合同与 job 不一致")
    receipt_path = Path(str(ticket.get("worker_receipt_path"))).expanduser().resolve()
    active_receipt_path = active_item.get("worker_receipt_path")
    if not isinstance(active_receipt_path, str) or receipt_path != Path(
        active_receipt_path
    ).expanduser().resolve():
        raise SystemExit("Fast8 Worker ticket 的回执路径与 active_action 不一致")
    wait_seconds = float(getattr(args, "wait_for_session_seconds", 0) or 0)
    poll_interval = float(getattr(args, "poll_interval", 0.5) or 0.5)
    if wait_seconds < 0 or wait_seconds > 90:
        raise SystemExit("--wait-for-session-seconds 必须在 0–90 秒之间")
    if poll_interval < 0.2 or poll_interval > 5:
        raise SystemExit("--poll-interval 必须在 0.2–5 秒之间")
    deadline = time.monotonic() + wait_seconds
    while True:
        session_id = active_item.get("worker_session_id")
        binding_confirmed = (
            active_item.get("worker_start_status") == "worker_started_confirmed"
            and isinstance(session_id, str)
            and CODEX_AGENT_THREAD_ID_RE.fullmatch(session_id) is not None
        )
        if binding_confirmed and ticket_version == 2:
            runtime_binding = active_item.get("worker_runtime_binding")
            expected_runtime = {
                "model": worker_runtime_contract.get("required_model"),
                "reasoning_effort": worker_runtime_contract.get(
                    "required_reasoning_effort"
                ),
                "fork_turns": worker_runtime_contract.get(
                    "required_fork_turns"
                ),
            }
            actual_runtime = (
                {
                    "model": runtime_binding.get("model"),
                    "reasoning_effort": runtime_binding.get(
                        "reasoning_effort"
                    ),
                    "fork_turns": runtime_binding.get("fork_turns"),
                }
                if isinstance(runtime_binding, dict)
                else None
            )
            binding_confirmed = (
                isinstance(runtime_binding, dict)
                and runtime_binding.get("session_id") == session_id
                and actual_runtime == expected_runtime
            )
        if binding_confirmed:
            break
        if time.monotonic() >= deadline:
            raise SystemExit(
                "worker_session_binding_required：Fast8 Worker 在 ImageGen 前必须先由主控"
                "绑定真实 Agent UUID 与合规运行时；创建后立即用 list_agents 按 "
                "task_name 解析并运行 bind-fast8-worker-sessions"
            )
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
        state = read_json(state_path)
        active_item = next(
            (
                item
                for item in ((state.get("scheduler") or {}).get("active_actions") or [])
                if isinstance(item, dict)
                and item.get("style") == style
                and str(item.get("page_id")) == page_id
                and item.get("action") == action
                and int(item.get("attempt") or 1) == attempt
            ),
            None,
        )
        if not isinstance(active_item, dict):
            raise SystemExit("等待 session 绑定时 active_action 已不存在")
        if active_item.get("worker_ticket_path") != str(ticket_path):
            raise SystemExit("等待 session 绑定时 Worker ticket 已变化")
    print(
        json.dumps(
            {
                "status": "pass",
                "worker_ticket": str(ticket_path),
                "worker_ticket_sha256": file_sha256(ticket_path),
                "generation_job_path": str(job_path),
                "generation_job_sha256": job_sha,
                "worker_receipt_path": str(receipt_path),
                "imagegen_input_fingerprint": ticket.get(
                    "imagegen_input_fingerprint"
                ),
                "worker_session_id": active_item.get("worker_session_id"),
                "worker_runtime_contract": worker_runtime_contract,
                "worker_receipt_template": {
                    "worker_receipt_contract_version": (
                        FAST8_WORKER_RECEIPT_CONTRACT_VERSION
                    ),
                    "style": style,
                    "page_id": page_id,
                    "action": action,
                    "attempt": attempt,
                    "imagegen_input_fingerprint": ticket.get(
                        "imagegen_input_fingerprint"
                    ),
                    "worker_agent_id": active_item.get("worker_session_id"),
                    "tool_call_id": None,
                    "savedPath": None,
                    "tool_started_at": None,
                    "tool_finished_at": None,
                    "receipt_written_at": None,
                    "tool_status": None,
                    "failure_class": None,
                    "tool_error_code": None,
                    "error": None,
                    "contains_image_payload": False,
                },
            },
            ensure_ascii=False,
        )
    )


def command_write_fast8_worker_receipt(args: argparse.Namespace) -> None:
    """Atomically serialize one ticket-bound Fast8 Worker receipt."""

    state_path = Path(args.state).expanduser().resolve()
    ticket_path = Path(args.ticket).expanduser().resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("write-fast8-worker-receipt 只适用于 fast_8x1_diverse")
    project_dir = project_dir_for_state(state_path, state)
    require_path_within(
        ticket_path,
        project_dir / "style_jobs" / "dispatch_tickets",
        "Fast8 Worker ticket",
    )
    ticket = read_json(ticket_path)
    ticket_version = ticket.get("fast8_worker_ticket_contract_version")
    if ticket_version not in FAST8_WORKER_TICKET_SUPPORTED_VERSIONS:
        raise SystemExit("Fast8 Worker ticket 合同版本无效")
    if ticket.get("run_id") != state.get("run_id"):
        raise SystemExit("Fast8 Worker ticket 的 run_id 与状态不一致")
    if str(Path(str(ticket.get("state_path"))).resolve()) != str(state_path):
        raise SystemExit("Fast8 Worker ticket 的 state_path 与当前状态不一致")

    style = normalize_style(ticket.get("style"))
    page_id = str(ticket.get("page_id"))
    action = str(ticket.get("action"))
    attempt = int(ticket.get("attempt") or 0)
    binding_task: dict[str, Any] | None = None
    for binding in (state.get("scheduler") or {}).get("worker_session_bindings", []):
        if not isinstance(binding, dict):
            continue
        for task in binding.get("tasks") or []:
            if (
                isinstance(task, dict)
                and task.get("style") == style
                and str(task.get("page_id")) == page_id
                and task.get("action") == action
                and int(task.get("attempt") or 1) == attempt
                and task.get("worker_ticket_path") == str(ticket_path)
            ):
                binding_task = task
                break
        if binding_task is not None:
            break
    if not isinstance(binding_task, dict):
        raise SystemExit("Fast8 Worker ticket 尚未绑定真实 Worker session")
    worker_session_id = binding_task.get("worker_session_id")
    if not isinstance(worker_session_id, str) or (
        CODEX_AGENT_THREAD_ID_RE.fullmatch(worker_session_id) is None
    ):
        raise SystemExit("Fast8 Worker session UUID 无效")
    if ticket_version == 2:
        runtime_contract = ticket.get("worker_runtime_contract") or {}
        runtime_binding = binding_task.get("worker_runtime_binding") or {}
        expected_runtime = {
            "model": runtime_contract.get("required_model"),
            "reasoning_effort": runtime_contract.get("required_reasoning_effort"),
            "fork_turns": runtime_contract.get("required_fork_turns"),
        }
        actual_runtime = {
            "model": runtime_binding.get("model"),
            "reasoning_effort": runtime_binding.get("reasoning_effort"),
            "fork_turns": runtime_binding.get("fork_turns"),
        }
        if (
            runtime_binding.get("session_id") != worker_session_id
            or actual_runtime != expected_runtime
        ):
            raise SystemExit("Fast8 Worker session 运行时绑定无效")

    dispatch_task: dict[str, Any] | None = None
    for event in reversed(state.get("events") or []):
        if not isinstance(event, dict) or event.get("name") != "dispatch_wave":
            continue
        for task in (event.get("details") or {}).get("started_tasks") or []:
            if (
                isinstance(task, dict)
                and task.get("style") == style
                and str(task.get("page_id")) == page_id
                and task.get("action") == action
                and int(task.get("attempt") or 1) == attempt
                and task.get("worker_ticket_path") == str(ticket_path)
            ):
                dispatch_task = task
                break
        if dispatch_task is not None:
            break
    if not isinstance(dispatch_task, dict):
        raise SystemExit("Fast8 Worker ticket 缺少正式 dispatch 绑定")
    if dispatch_task.get("worker_ticket_sha256") != file_sha256(ticket_path):
        raise SystemExit("Fast8 Worker ticket SHA-256 与 dispatch 不一致")

    job_path = Path(str(ticket.get("generation_job_path"))).expanduser().resolve()
    job_sha = str(ticket.get("generation_job_sha256") or "")
    if (
        dispatch_task.get("generation_job_path") != str(job_path)
        or dispatch_task.get("generation_job_sha256") != job_sha
        or not job_path.is_file()
        or file_sha256(job_path) != job_sha
    ):
        raise SystemExit("Fast8 Worker ticket 的 generation job 绑定无效")
    job = read_json(job_path)
    if job.get("imagegen_input_fingerprint") != ticket.get(
        "imagegen_input_fingerprint"
    ):
        raise SystemExit("Fast8 Worker ticket 的图片输入指纹与 job 不一致")

    receipt_path = Path(str(ticket.get("worker_receipt_path"))).expanduser().resolve()
    receipt_contract = job.get("worker_receipt") or {}
    if receipt_contract.get("path") != str(receipt_path):
        raise SystemExit("Fast8 Worker 回执路径与 generation job 不一致")
    require_path_within(
        receipt_path,
        project_dir / "style_jobs" / "results",
        "Fast8 Worker 回执",
    )

    def canonical_time(value: str | None, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"Fast8 Worker 回执缺少 {label}")
        normalized = value.strip()
        # Some tool wrappers emit a valid ISO-8601 numeric offset without the
        # colon (for example +0800).  Keep the persisted contract canonical
        # without loosening the strict parser used by the rest of the audit.
        if re.search(r"[+-]\d{4}$", normalized):
            normalized = (
                normalized[:-5] + normalized[-5:-2] + ":" + normalized[-2:]
            )
        try:
            return parse_time(normalized).isoformat(timespec="microseconds")
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Fast8 Worker 回执 {label} 无效：{exc}") from exc

    tool_status = str(args.tool_status)
    failure_class = args.failure_class
    tool_error_code = args.tool_error_code
    error = args.error
    saved_path: str | None = args.saved_path
    tool_call_id: str | None = args.tool_call_id
    if tool_status == "completed" and saved_path:
        resolved_path, derived_tool_id = resolve_imagegen_artifact_hint(saved_path)
        if resolved_path is None or derived_tool_id is None:
            raise SystemExit("Fast8 Worker completed 回执无法唯一解析标准图片路径")
        require_path_within(
            resolved_path,
            GENERATED_IMAGES_ROOT / worker_session_id,
            "Fast8 Worker session 图片",
        )
        if tool_call_id and tool_call_id != derived_tool_id:
            raise SystemExit("Fast8 Worker tool_call_id 与图片文件名不一致")
        tool_call_id = derived_tool_id
        saved_path = str(resolved_path)
        failure_class = None
        tool_error_code = None
        error = None
    elif tool_status == "completed":
        saved_path = None
        tool_call_id = tool_call_id or None
        failure_class = "artifact_missing"
        tool_error_code = None
        error = "artifact_handoff_unresolved"
    else:
        saved_path = None
        tool_call_id = tool_call_id or None
        if failure_class not in {"backend_network", "backend_failed"}:
            raise SystemExit("Fast8 Worker failed 回执必须声明 backend_network|backend_failed")
        error = "imagegen_backend_failed"

    tool_started_at = canonical_time(args.tool_started_at, "tool_started_at")
    tool_finished_at = canonical_time(args.tool_finished_at, "tool_finished_at")
    receipt_written_at = canonical_time(
        getattr(args, "timestamp", None) or now_iso(), "receipt_written_at"
    )
    if not (
        parse_time(tool_started_at)
        <= parse_time(tool_finished_at)
        <= parse_time(receipt_written_at)
    ):
        raise SystemExit("Fast8 Worker 回执时间倒序")

    receipt = {
        "worker_receipt_contract_version": FAST8_WORKER_RECEIPT_CONTRACT_VERSION,
        "style": style,
        "page_id": page_id,
        "action": action,
        "attempt": attempt,
        "imagegen_input_fingerprint": ticket.get("imagegen_input_fingerprint"),
        "worker_agent_id": worker_session_id,
        "tool_call_id": tool_call_id,
        "savedPath": saved_path,
        "tool_started_at": tool_started_at,
        "tool_finished_at": tool_finished_at,
        "receipt_written_at": receipt_written_at,
        "tool_status": tool_status,
        "failure_class": failure_class,
        "tool_error_code": tool_error_code,
        "error": error,
        "contains_image_payload": False,
    }
    if receipt_path.is_file():
        try:
            existing = read_json(receipt_path)
        except SystemExit as exc:
            raise SystemExit("既有 Fast8 Worker 回执不可读，拒绝覆盖") from exc
        if existing != receipt:
            raise SystemExit("既有 Fast8 Worker 回执内容不同，拒绝覆盖")
    else:
        atomic_write_json(receipt_path, receipt)
    # The Worker's explicit finally-release is the earliest normal path.  The
    # receipt writer repeats it idempotently so a model/tool wrapper omission
    # cannot leave capacity occupied until the 45-minute crash TTL.
    if fast8_imagegen_slot_policy(state) == CURRENT_FAST8_IMAGEGEN_SLOT_POLICY:
        jit_task = fast8_jit_imagegen_task_context(
            state_path, state, ticket_path, require_active=False
        )
        jit_lease_id = fast8_global_imagegen_lease_key(
            state_path, state, jit_task
        )
        release_fast8_global_imagegen_slots(
            state_path, state, [jit_lease_id]
        )
    print(json.dumps(receipt, ensure_ascii=False))


def raw_png_metadata(path: Path) -> tuple[int, int, int, str]:
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError as exc:
        raise SystemExit(f"无法读取图片：{path}：{exc}") from exc
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise SystemExit(f"不是有效 PNG：{path}")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise SystemExit(f"PNG 尺寸无效：{path}，实际 {width}x{height}")
    payload = path.read_bytes()
    return width, height, len(payload), hashlib.sha256(payload).hexdigest()


def png_metadata(path: Path) -> tuple[int, int, int, str]:
    width, height, size, sha256 = raw_png_metadata(path)
    if abs(width / height - 16 / 9) > 0.02:
        raise SystemExit(f"图片不是有效横向 16:9：{path}，实际 {width}x{height}")
    return width, height, size, sha256


def artifact_identity_values(item: dict[str, Any]) -> dict[str, str]:
    """返回可用于阻止跨任务误绑定的稳定产物身份。"""

    values: dict[str, str] = {}
    tool_call_id = item.get("tool_call_id")
    if isinstance(tool_call_id, str) and tool_call_id:
        values["tool_call_id"] = tool_call_id
    source = item.get("source", item.get("selected_source"))
    if isinstance(source, str) and source:
        values["source"] = str(Path(source).resolve()).casefold()
    sha256 = item.get("sha256", item.get("source_sha256"))
    if isinstance(sha256, str) and sha256:
        values["sha256"] = sha256.casefold()
    return values


def validate_unique_artifact_bindings(
    state: dict[str, Any], items: list[dict[str, Any]]
) -> None:
    """同一工具结果、文件或字节内容不得绑定到两个不同页面。"""

    bound: dict[tuple[str, str], tuple[str, str]] = {}
    for style, style_state in (state.get("styles") or {}).items():
        if not isinstance(style_state, dict):
            continue
        for page_id, record in (style_state.get("pages") or {}).items():
            if not isinstance(record, dict):
                continue
            task = (str(style), str(page_id))
            for field, value in artifact_identity_values(record).items():
                previous = bound.get((field, value))
                if previous is not None and previous != task:
                    raise SystemExit(
                        "状态中已有两个页面绑定同一图片产物："
                        f"{previous[0]}/{previous[1]} 与 {task[0]}/{task[1]} "
                        f"共享 {field}"
                    )
                bound[(field, value)] = task

    if (state.get("run_mode") or state.get("mode")) == SELECTED_STYLE_EXPANSION_MODE:
        selected_style = normalize_style(state.get("selected_style"))
        if selected_style is None:
            raise SystemExit("选定风格扩页状态缺少 selected_style")
        for page_id, record in (state.get("pages") or {}).items():
            if not isinstance(record, dict):
                continue
            task = (str(selected_style), str(page_id))
            for field, value in artifact_identity_values(record).items():
                previous = bound.get((field, value))
                if previous is not None and previous != task:
                    raise SystemExit(
                        "状态中已有两个扩页页面绑定同一图片产物："
                        f"{previous[0]}/{previous[1]} 与 {task[0]}/{task[1]} "
                        f"共享 {field}"
                    )
                bound[(field, value)] = task

    for item in items:
        task = (str(item["style"]), str(item["page_id"]))
        for field, value in artifact_identity_values(item).items():
            previous = bound.get((field, value))
            if previous is not None and previous != task:
                raise SystemExit(
                    "检测到跨任务重复绑定同一图片产物："
                    f"{previous[0]}/{previous[1]} 与 {task[0]}/{task[1]} "
                    f"共享 {field}"
                )
            bound[(field, value)] = task


def validate_timestamp_chain(
    values: list[tuple[str, str | None]], context: str
) -> None:
    available = [(name, value) for name, value in values if isinstance(value, str)]
    for (left_name, left), (right_name, right) in zip(available, available[1:]):
        try:
            if parse_time(left) > parse_time(right):
                raise SystemExit(
                    f"{context} 时间倒序：{left_name} > {right_name}"
                )
        except (TypeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc


def fast8_receipt_result_for_active(
    state_path: Path,
    state: dict[str, Any],
    active_item: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Return one hash-bound success or failure receipt without waiting for Worker prose."""

    style = normalize_style(active_item.get("style"))
    if style is None:
        raise SystemExit("Fast8 active_action 缺少合法席位")
    page_id = str(active_item.get("page_id") or state.get("anchor_page_id"))
    action = str(active_item.get("action") or "generate_anchor")
    attempt = int(active_item.get("attempt") or 1)
    job_path_value = active_item.get("generation_job_path")
    job_sha = active_item.get("generation_job_sha256")
    if not isinstance(job_path_value, str) or not isinstance(job_sha, str):
        raise SystemExit(f"style_{style} active_action 缺少正式 job 绑定")
    job_path = Path(job_path_value).expanduser().resolve()
    if not job_path.is_file() or file_sha256(job_path) != job_sha:
        raise SystemExit(f"style_{style} 正式 generation job 已变化")
    job = read_json(job_path)
    receipt_contract = job.get("worker_receipt") or {}
    if receipt_contract.get("contract_version") != FAST8_WORKER_RECEIPT_CONTRACT_VERSION:
        raise SystemExit(f"style_{style} 缺少 Fast8 Worker 回执合同")
    receipt_path_value = active_item.get("worker_receipt_path") or receipt_contract.get(
        "path"
    )
    if not isinstance(receipt_path_value, str):
        raise SystemExit(f"style_{style} Worker 回执路径缺失")
    receipt_path = Path(receipt_path_value).expanduser().resolve()
    require_path_within(
        receipt_path,
        project_dir_for_state(state_path, state) / "style_jobs" / "results",
        "Fast8 Worker 回执",
    )
    if not receipt_path.is_file():
        worker_session_id = active_item.get("worker_session_id")
        if not isinstance(worker_session_id, str) or (
            CODEX_AGENT_THREAD_ID_RE.fullmatch(worker_session_id.strip().lower()) is None
        ):
            return "binding_required", None
        session_path, session_tool_id = fast8_worker_session_artifact(active_item)
        if session_path is None or session_tool_id is None:
            terminal_failure = fast8_terminal_slot_failure_without_artifact(
                state_path, state, active_item
            )
            if terminal_failure is not None:
                return "ready", terminal_failure
            return "missing", None
        dispatch_at = active_item.get("dispatch_authorized_at") or active_item.get(
            "dispatch_requested_at"
        )
        file_at = datetime.fromtimestamp(
            session_path.stat().st_mtime
        ).astimezone().isoformat(timespec="microseconds")
        tool_started_at = dispatch_at if isinstance(dispatch_at, str) else file_at
        try:
            tool_finished_at = max(
                (tool_started_at, file_at), key=parse_time
            )
        except (TypeError, ValueError):
            tool_finished_at = file_at
        return (
            "ready",
            {
                "style": style,
                "page_id": page_id,
                "action": action,
                "attempt": attempt,
                "worker_agent_id": active_item.get("worker_session_id")
                or active_item.get("worker_agent_id"),
                "agent_action_started_at": tool_started_at,
                "agent_action_finished_at": now_iso(),
                "tool_call_id": session_tool_id,
                "savedPath": str(session_path),
                "tool_started_at": tool_started_at,
                "tool_finished_at": tool_finished_at,
                "binding_source": "worker_session_dir",
                "timing_capture": "controller_session_artifact_without_receipt",
                "tool_status": "completed",
                "failure_class": None,
                "error": None,
            },
        )
    receipt = normalize_fast8_artifact_fields(read_json(receipt_path))
    allowed_fields = {
        "worker_receipt_contract_version",
        "style",
        "page_id",
        "action",
        "attempt",
        "imagegen_input_fingerprint",
        "worker_agent_id",
        "tool_call_id",
        "savedPath",
        "tool_started_at",
        "tool_finished_at",
        "receipt_written_at",
        "tool_status",
        "failure_class",
        "tool_error_code",
        "error",
        "contains_image_payload",
    }
    unexpected = set(receipt) - allowed_fields
    if unexpected:
        raise SystemExit(
            f"style_{style} Worker 回执包含未授权字段："
            + ", ".join(sorted(unexpected))
        )
    expected_identity = {
        "worker_receipt_contract_version": FAST8_WORKER_RECEIPT_CONTRACT_VERSION,
        "style": style,
        "page_id": page_id,
        "action": action,
        "attempt": attempt,
        "imagegen_input_fingerprint": job.get("imagegen_input_fingerprint"),
        "contains_image_payload": False,
    }
    for key, expected_value in expected_identity.items():
        if receipt.get(key) != expected_value:
            raise SystemExit(f"style_{style} Worker 回执的 {key} 与正式任务不一致")
    tool_status = receipt.get("tool_status")
    failure_class = receipt.get("failure_class")
    if tool_status not in {None, "completed", "failed"}:
        raise SystemExit(f"style_{style} Worker 回执 tool_status 无效：{tool_status!r}")
    if failure_class not in {
        None,
        "backend_network",
        "backend_failed",
        "artifact_missing",
        "receipt_missing",
    }:
        raise SystemExit(
            f"style_{style} Worker 回执 failure_class 无效：{failure_class!r}"
        )
    error = receipt.get("error")
    saved_path = receipt.get("savedPath")
    binding_source = "worker_receipt"
    if isinstance(saved_path, str) and Path(saved_path).expanduser().is_file():
        saved_path = str(Path(saved_path).expanduser().resolve())
        error = None
        tool_status = "completed"
        failure_class = None
    elif tool_status == "failed" and failure_class in {
        "backend_network",
        "backend_failed",
    }:
        error = "imagegen_backend_failed"
        saved_path = None
    elif error in {None, "", "artifact_handoff_unresolved"}:
        worker_session_id = active_item.get("worker_session_id")
        if not isinstance(worker_session_id, str) or (
            CODEX_AGENT_THREAD_ID_RE.fullmatch(worker_session_id.strip().lower()) is None
        ):
            return "binding_required", None
        session_path, session_tool_id = fast8_worker_session_artifact(active_item)
        if session_path is not None:
            saved_path = str(session_path)
            if not receipt.get("tool_call_id") and session_tool_id:
                receipt["tool_call_id"] = session_tool_id
            error = None
            binding_source = "worker_session_dir"
        else:
            error = "artifact_handoff_unresolved"
            saved_path = None
    else:
        raise SystemExit(f"style_{style} Worker 回执 error 无效：{error!r}")
    tool_started = receipt.get("tool_started_at")
    tool_finished = receipt.get("tool_finished_at")
    receipt_written = receipt.get("receipt_written_at")
    agent_started = active_item.get("agent_action_started_at") or tool_started
    agent_finished = receipt_written or tool_finished
    return (
        "ready",
        {
            "style": style,
            "page_id": page_id,
            "action": action,
            "attempt": attempt,
            "worker_agent_id": active_item.get("worker_session_id")
            or receipt.get("worker_agent_id")
            or active_item.get("worker_agent_id"),
            "agent_action_started_at": agent_started,
            "agent_action_finished_at": agent_finished,
            "tool_call_id": receipt.get("tool_call_id"),
            "savedPath": saved_path,
            "tool_started_at": tool_started,
            "tool_finished_at": tool_finished,
            "binding_source": binding_source,
            "tool_status": tool_status,
            "failure_class": failure_class,
            "tool_error_code": receipt.get("tool_error_code"),
            "error": error,
        },
    )


def command_settle_fast8_receipts(args: argparse.Namespace) -> None:
    """Scan machine receipts and settle ready Fast8 seats before Worker turns finish."""

    state_path = Path(args.state).expanduser().resolve()
    requested_styles = (
        set(parse_style_csv(args.styles)) if getattr(args, "styles", None) else None
    )
    wait_seconds = float(getattr(args, "wait_seconds", 0) or 0)
    poll_interval = float(getattr(args, "poll_interval", 2) or 2)
    if not 0 <= wait_seconds <= 60:
        raise SystemExit("--wait-seconds 必须在 0 到 60 秒之间")
    if not 0.2 <= poll_interval <= 10:
        raise SystemExit("--poll-interval 必须在 0.2 到 10 秒之间")
    deadline = time.monotonic() + wait_seconds
    processed_styles: list[str] = []
    wave_paths: list[str] = []
    settle_outputs: list[dict[str, Any]] = []
    pending: list[str] = []
    binding_required: list[str] = []
    while True:
        state = read_json(state_path)
        if state.get("run_mode") != FAST8_MODE:
            raise SystemExit("settle-fast8-receipts 只适用于 fast_8x1_diverse")
        active = list(((state.get("scheduler") or {}).get("active_actions") or []))
        candidates = [
            item
            for item in active
            if isinstance(item, dict)
            and item.get("action") in {"generate_anchor", "repair_anchor"}
            and (
                requested_styles is None
                or normalize_style(item.get("style")) in requested_styles
            )
        ]
        results: list[dict[str, Any]] = []
        pending = []
        binding_required = []
        for item in candidates:
            receipt_status, receipt_result = fast8_receipt_result_for_active(
                state_path, state, item
            )
            style = str(normalize_style(item.get("style")))
            if receipt_status == "ready" and receipt_result is not None:
                results.append(receipt_result)
            else:
                pending.append(style)
                if receipt_status == "binding_required":
                    binding_required.append(style)
        if results:
            project_dir = project_dir_for_state(state_path, state)
            signature = hashlib.sha256(
                json.dumps(results, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:12]
            wave_path = (
                project_dir
                / "style_jobs"
                / "results"
                / f"receipt_settle_wave_{signature}.json"
            )
            write_idempotent(wave_path, {"results": results})
            settle_args = argparse.Namespace(
                state=str(state_path),
                results_file=str(wave_path),
                expected_styles=",".join(
                    sorted(item["style"] for item in results)
                ),
                timestamp=getattr(args, "timestamp", None),
            )
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                command_settle_wave(settle_args)
            settle_outputs.append(json.loads(captured.getvalue()))
            processed_styles.extend(str(item["style"]) for item in results)
            wave_paths.append(str(wave_path))
            # Re-read the mutated state immediately. This can settle multiple
            # staggered receipts inside one bounded controller call.
            continue
        if binding_required:
            break
        if not candidates or time.monotonic() >= deadline:
            break
        time.sleep(poll_interval)
    refreshed = read_json(state_path)
    remaining = sorted(
        {
            str(normalize_style(item.get("style")))
            for item in ((refreshed.get("scheduler") or {}).get("active_actions") or [])
            if isinstance(item, dict)
            and item.get("action") in {"generate_anchor", "repair_anchor"}
            and (
                requested_styles is None
                or normalize_style(item.get("style")) in requested_styles
            )
        }
    )
    if not processed_styles:
        print(
            json.dumps(
                {
                    "status": (
                        "worker_session_binding_required"
                        if binding_required
                        else "waiting_for_receipts"
                        if remaining
                        else "no_active_receipts"
                    ),
                    "settled": 0,
                    "pending_receipt_styles": remaining,
                    "worker_session_binding_required_styles": sorted(
                        set(binding_required)
                    ),
                    "all_anchor_tools_completed": not remaining,
                    "worker_final_text_required": False,
                },
                ensure_ascii=False,
            )
        )
        return
    processed_styles = list(dict.fromkeys(processed_styles))
    candidate_bound_styles = [
        style
        for style in processed_styles
        if page_record(
            refreshed, style, str(refreshed.get("anchor_page_id"))
        ).get("selected_source")
    ]
    recovery_pending_styles = sorted(
        {
            str(normalize_style(item.get("style")))
            for item in ((refreshed.get("scheduler") or {}).get("recovery_queue") or [])
            if isinstance(item, dict)
            and (
                requested_styles is None
                or normalize_style(item.get("style")) in requested_styles
            )
        }
    )
    retry_pending_styles = sorted(
        {
            str(normalize_style(item.get("style")))
            for item in ((refreshed.get("scheduler") or {}).get("ready_queue") or [])
            if isinstance(item, dict)
            and item.get("technical_retry") is True
            and (
                requested_styles is None
                or normalize_style(item.get("style")) in requested_styles
            )
        }
    )
    result = settle_outputs[-1] if settle_outputs else {}
    result.update(
        {
            "status": (
                "worker_session_binding_required" if binding_required else "ok"
            ),
            "processed": len(processed_styles),
            "processed_styles": processed_styles,
            "settled": len(candidate_bound_styles),
            "settled_styles": candidate_bound_styles,
            "candidate_bound_styles": candidate_bound_styles,
            "recovery_pending_styles": recovery_pending_styles,
            "retry_pending_styles": retry_pending_styles,
            "receipt_wave_path": wave_paths[-1],
            "receipt_wave_paths": wave_paths,
            "pending_receipt_styles": remaining,
            "worker_session_binding_required_styles": sorted(
                set(binding_required)
            ),
            "all_anchor_tools_completed": not remaining,
            "worker_final_text_required": False,
        }
    )
    print(json.dumps(result, ensure_ascii=False))


def command_settle_wave(args: argparse.Namespace) -> None:
    """校验并一次结算一波图片 Agent 的最小 JSON 结果。"""

    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    audit_version = state_audit_version(state)
    settled_at = args.timestamp or now_iso()
    active_snapshot = list(((state.get("scheduler") or {}).get("active_actions") or []))
    raw = read_json_value(Path(args.results_file).resolve())
    results = raw.get("results") if isinstance(raw, dict) else raw
    if not isinstance(results, list) or not results:
        raise SystemExit("结果文件必须是非空数组或包含 results 数组的对象")
    expected = set(parse_style_csv(args.expected_styles)) if args.expected_styles else None
    page_id_default = str(state.get("anchor_page_id"))
    normalized: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    seen_styles: set[str] = set()
    seen_tasks: set[tuple[str, str, str]] = set()

    def merge_fast8_worker_receipt(result: dict[str, Any]) -> dict[str, Any]:
        """Use the hash-bound worker receipt before declaring handoff unresolved."""

        if state.get("run_mode") != FAST8_MODE:
            return result
        result = normalize_fast8_artifact_fields(result)
        saved = result.get("savedPath")
        if isinstance(saved, str) and saved and Path(saved).expanduser().is_file():
            return result
        style = normalize_style(result.get("style"))
        page_id = str(result.get("page_id") or page_id_default)
        action = str(result.get("action") or "generate_anchor")
        attempt = int(result.get("attempt") or 1)
        active_item = next(
            (
                item
                for item in active_snapshot
                if isinstance(item, dict)
                and item.get("style") == style
                and str(item.get("page_id")) == page_id
                and item.get("action") == action
                and int(item.get("attempt") or 1) == attempt
            ),
            None,
        )
        if not isinstance(active_item, dict):
            return result
        job_path_value = active_item.get("generation_job_path")
        job_sha = active_item.get("generation_job_sha256")
        if not isinstance(job_path_value, str) or not isinstance(job_sha, str):
            return result
        job_path = Path(job_path_value).expanduser().resolve()
        if not job_path.is_file() or file_sha256(job_path) != job_sha:
            raise SystemExit(f"style_{style} 正式 generation job 已变化")
        job = read_json(job_path)
        receipt_contract = job.get("worker_receipt") or {}
        if receipt_contract.get("contract_version") != FAST8_WORKER_RECEIPT_CONTRACT_VERSION:
            return result
        receipt_path_value = active_item.get("worker_receipt_path") or receipt_contract.get(
            "path"
        )
        if not isinstance(receipt_path_value, str):
            return result
        receipt_path = Path(receipt_path_value).expanduser().resolve()
        require_path_within(
            receipt_path,
            project_dir_for_state(state_path, state) / "style_jobs" / "results",
            "Fast8 Worker 回执",
        )
        if not receipt_path.is_file():
            return result
        receipt = normalize_fast8_artifact_fields(read_json(receipt_path))
        allowed_fields = {
            "worker_receipt_contract_version",
            "style",
            "page_id",
            "action",
            "attempt",
            "imagegen_input_fingerprint",
            "worker_agent_id",
            "tool_call_id",
            "savedPath",
            "tool_started_at",
            "tool_finished_at",
            "receipt_written_at",
            "tool_status",
            "failure_class",
            "tool_error_code",
            "error",
            "contains_image_payload",
        }
        unexpected = set(receipt) - allowed_fields
        if unexpected:
            raise SystemExit(
                f"style_{style} Worker 回执包含未授权字段："
                + ", ".join(sorted(unexpected))
            )
        expected_identity = {
            "worker_receipt_contract_version": FAST8_WORKER_RECEIPT_CONTRACT_VERSION,
            "style": style,
            "page_id": page_id,
            "action": action,
            "attempt": attempt,
            "imagegen_input_fingerprint": job.get("imagegen_input_fingerprint"),
            "contains_image_payload": False,
        }
        for key, expected_value in expected_identity.items():
            if receipt.get(key) != expected_value:
                raise SystemExit(f"style_{style} Worker 回执的 {key} 与正式任务不一致")
        receipt_saved = receipt.get("savedPath")
        tool_status = receipt.get("tool_status")
        failure_class = receipt.get("failure_class")
        receipt_file_exists = isinstance(receipt_saved, str) and Path(
            receipt_saved
        ).expanduser().is_file()
        if not receipt_file_exists and tool_status == "failed" and failure_class in {
            "backend_network",
            "backend_failed",
        }:
            merged = dict(result)
            for key in (
                "tool_call_id",
                "tool_started_at",
                "tool_finished_at",
                "tool_status",
                "failure_class",
                "tool_error_code",
            ):
                value = receipt.get(key)
                if value not in {None, ""}:
                    merged[key] = value
            merged["worker_agent_id"] = active_item.get(
                "worker_session_id"
            ) or receipt.get("worker_agent_id") or active_item.get("worker_agent_id")
            merged["agent_action_started_at"] = active_item.get(
                "agent_action_started_at"
            ) or receipt.get("tool_started_at")
            merged["agent_action_finished_at"] = receipt.get(
                "receipt_written_at"
            ) or receipt.get("tool_finished_at")
            merged["binding_source"] = "worker_receipt"
            merged["savedPath"] = None
            merged["error"] = "imagegen_backend_failed"
            return merged
        if receipt.get("error") not in {None, "", "artifact_handoff_unresolved"}:
            return result
        binding_source = "worker_receipt"
        if not (
            isinstance(receipt_saved, str)
            and Path(receipt_saved).expanduser().is_file()
        ):
            session_path, session_tool_id = fast8_worker_session_artifact(active_item)
            if session_path is None:
                return result
            receipt_saved = str(session_path)
            receipt["savedPath"] = receipt_saved
            if not receipt.get("tool_call_id") and session_tool_id:
                receipt["tool_call_id"] = session_tool_id
            binding_source = "worker_session_dir"
        merged = dict(result)
        for key in ("tool_call_id", "savedPath", "tool_started_at", "tool_finished_at"):
            value = receipt.get(key)
            if value not in {None, ""}:
                merged[key] = value
        merged["worker_agent_id"] = active_item.get("worker_session_id") or receipt.get(
            "worker_agent_id"
        ) or active_item.get("worker_agent_id")
        merged["binding_source"] = binding_source
        merged["error"] = None
        return merged

    def generation_dispatch_time_for(
        style: str, page_id: str, action: str, attempt: int
    ) -> str | None:
        for event in reversed(state.get("events") or []):
            if not isinstance(event, dict) or event.get("name") != "dispatch_wave":
                continue
            details = event.get("details") or {}
            for task in details.get("started_tasks") or []:
                if not isinstance(task, dict):
                    continue
                if (
                    task.get("style") == style
                    and str(task.get("page_id")) == page_id
                    and task.get("action") == action
                    and int(task.get("attempt") or 1) == attempt
                ):
                    value = task.get("dispatch_requested_at") or event.get(
                        "occurred_at"
                    )
                    return value if isinstance(value, str) else None
        if action == "generate_anchor" and page_id == str(state.get("anchor_page_id")):
            value = (state.get("timing") or {}).get("initial_anchor_dispatch_at")
            return value if isinstance(value, str) else None
        return None

    def bounded_time(
        value: str | None, lower: str | None = None, upper: str | None = None
    ) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            chosen = parse_time(value)
            if isinstance(lower, str) and chosen < parse_time(lower):
                return lower
            if isinstance(upper, str) and chosen > parse_time(upper):
                return upper
        except (TypeError, ValueError):
            return value
        return value

    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise SystemExit(f"results[{index}] 必须是对象")
        result = merge_fast8_worker_receipt(result)
        style = normalize_style(result.get("style"))
        if style is None:
            raise SystemExit(f"results[{index}] 缺少 style")
        page_id = str(result.get("page_id") or page_id_default)
        action = result.get("action") or "generate_anchor"
        task_key = (style, page_id, action)
        if task_key in seen_tasks:
            raise SystemExit(f"结果文件包含重复任务：{task_key}")
        seen_tasks.add(task_key)
        seen_styles.add(style)
        attempt = result.get("attempt")
        if action not in GENERATION_ACTIONS | {"recover_artifact"}:
            raise SystemExit(f"style_{style} action 无效：{action}")
        if not isinstance(attempt, int) or attempt < 1:
            raise SystemExit(f"style_{style} attempt 无效")
        saved_path_value = result.get("savedPath")
        if isinstance(saved_path_value, str) and saved_path_value:
            supplied_path = Path(saved_path_value).expanduser()
            if not supplied_path.is_absolute():
                raise SystemExit(f"style_{style} savedPath 必须是绝对路径")
            supplied_path = supplied_path.resolve()
            if supplied_path.is_file():
                result = dict(result)
                result["savedPath"] = str(supplied_path)
                result.setdefault("binding_source", "direct_tool_result")
                if state.get("run_mode") == FAST8_MODE and action in (
                    GENERATION_ACTIONS | {"recover_artifact"}
                ):
                    active_hint = next(
                        (
                            item
                            for item in active_snapshot
                            if isinstance(item, dict)
                            and item.get("style") == style
                            and str(item.get("page_id")) == page_id
                            and item.get("action") == action
                            and int(item.get("attempt") or 1) == attempt
                        ),
                        None,
                    )
                    source_action_hint = (
                        result.get("source_action")
                        if action == "recover_artifact"
                        else action
                    )
                    derived_fields = False
                    if not result.get("tool_call_id"):
                        active_tool_id = (
                            active_hint.get("tool_call_id")
                            if isinstance(active_hint, dict)
                            else None
                        )
                        match = IMAGEGEN_TOOL_ID_RE.match(supplied_path.name)
                        if isinstance(active_tool_id, str) and active_tool_id:
                            result["tool_call_id"] = active_tool_id
                            derived_fields = True
                        elif match:
                            result["tool_call_id"] = match.group(1)
                            derived_fields = True
                    generation_dispatch_time = generation_dispatch_time_for(
                        style,
                        page_id,
                        str(source_action_hint),
                        attempt,
                    )
                    file_time = datetime.fromtimestamp(
                        supplied_path.stat().st_mtime
                    ).astimezone().isoformat(timespec="microseconds")

                    def later_time(left: str | None, right: str | None) -> str | None:
                        values = [
                            value for value in (left, right) if isinstance(value, str)
                        ]
                        if not values:
                            return None
                        try:
                            return max(values, key=parse_time)
                        except (TypeError, ValueError):
                            return values[-1]

                    active_tool_started = (
                        active_hint.get("tool_started_at")
                        if isinstance(active_hint, dict)
                        else None
                    )
                    active_tool_finished = (
                        active_hint.get("tool_finished_at")
                        if isinstance(active_hint, dict)
                        else None
                    )
                    recovery_started = result.get("recovery_started_at")
                    recovery_finished = result.get("recovery_finished_at")
                    fallback_tool_started = active_tool_started or generation_dispatch_time
                    fallback_tool_finished = active_tool_finished or bounded_time(
                        file_time,
                        lower=fallback_tool_started,
                        upper=(
                            recovery_started
                            if action == "recover_artifact"
                            and isinstance(recovery_started, str)
                            else None
                        ),
                    )
                    active_agent_started = (
                        active_hint.get("agent_action_started_at")
                        if isinstance(active_hint, dict)
                        else None
                    )
                    active_agent_finished = (
                        active_hint.get("agent_action_finished_at")
                        if isinstance(active_hint, dict)
                        else None
                    )
                    if not result.get("agent_action_started_at") and (
                        active_agent_started or fallback_tool_started
                    ):
                        result["agent_action_started_at"] = (
                            active_agent_started or fallback_tool_started
                        )
                        derived_fields = True
                    if not result.get("tool_started_at") and fallback_tool_started:
                        result["tool_started_at"] = fallback_tool_started
                        derived_fields = True
                    if not result.get("tool_finished_at") and fallback_tool_finished:
                        result["tool_finished_at"] = fallback_tool_finished
                        derived_fields = True
                    if not result.get("agent_action_finished_at"):
                        result["agent_action_finished_at"] = later_time(
                            active_agent_finished,
                            recovery_finished
                            if action == "recover_artifact"
                            else later_time(result.get("tool_finished_at"), settled_at),
                        )
                        derived_fields = True
                    if not result.get("worker_agent_id") and isinstance(
                        active_hint, dict
                    ):
                        result["worker_agent_id"] = active_hint.get(
                            "recovery_worker_agent_id"
                            if action == "recover_artifact"
                            else "worker_agent_id"
                        ) or active_hint.get("worker_agent_id")
                    if derived_fields:
                        result["timing_capture"] = (
                            "controller_bounded_recovery_fallback"
                            if action == "recover_artifact"
                            else "controller_bounded_fallback"
                        )
                    if result.get("error") == "artifact_handoff_unresolved":
                        result["error"] = None
        if result.get("error") not in {None, ""}:
            if action == "recover_artifact":
                raise SystemExit(
                    f"style_{style} 恢复未得到文件时请记录 "
                    "artifact_recovery_finished，而不是再次 settle-wave"
                )
            if (
                state.get("run_mode") == FAST8_MODE
                and result.get("error") == "artifact_handoff_unresolved"
            ):
                active_hint = next(
                    (
                        item
                        for item in active_snapshot
                        if isinstance(item, dict)
                        and item.get("style") == style
                        and str(item.get("page_id")) == page_id
                        and item.get("action") == action
                        and int(item.get("attempt") or 1) == attempt
                    ),
                    None,
                )
                worker_session_id = (
                    active_hint.get("worker_session_id")
                    if isinstance(active_hint, dict)
                    else None
                )
                if not isinstance(worker_session_id, str) or (
                    CODEX_AGENT_THREAD_ID_RE.fullmatch(
                        worker_session_id.strip().lower()
                    )
                    is None
                ):
                    raise SystemExit(
                        "worker_session_binding_required："
                        f"style_{style}/{page_id}/{action}/attempt_{attempt} "
                        "尚未绑定真实 Agent UUID；先运行 bind-fast8-worker-sessions，"
                        "禁止把缺少 session 的交接问题误排为产物恢复"
                    )
            unresolved.append(
                {
                    "style": style,
                    "page_id": page_id,
                    "action": action,
                    "attempt": attempt,
                    "error": result.get("error"),
                    "worker_agent_id": result.get("worker_agent_id"),
                    "agent_action_started_at": result.get("agent_action_started_at"),
                    "agent_action_finished_at": result.get("agent_action_finished_at"),
                    "tool_call_id": result.get("tool_call_id"),
                    "savedPath": result.get("savedPath"),
                    "tool_started_at": result.get("tool_started_at"),
                    "tool_finished_at": result.get("tool_finished_at"),
                    "binding_source": result.get("binding_source"),
                    "tool_status": result.get("tool_status"),
                    "failure_class": result.get("failure_class"),
                    "tool_error_code": result.get("tool_error_code"),
                }
            )
            continue
        source_action = action
        recovery_started_at = None
        recovery_finished_at = None
        recovery_method = None
        if action == "recover_artifact":
            source_action = result.get("source_action")
            if source_action not in GENERATION_ACTIONS:
                raise SystemExit(f"style_{style} recover_artifact 缺少合法 source_action")
            recovery_started_at = result.get("recovery_started_at")
            recovery_finished_at = result.get("recovery_finished_at")
            recovery_method = result.get("recovery_method")
            if not isinstance(recovery_started_at, str) or not isinstance(
                recovery_finished_at, str
            ):
                raise SystemExit(f"style_{style} recover_artifact 缺少恢复起止时间")
            if recovery_method not in {"same_worker", "deterministic_script"}:
                raise SystemExit(
                    f"style_{style} recovery_method 只允许 "
                    "same_worker|deterministic_script"
                )
            try:
                if parse_time(recovery_started_at) > parse_time(recovery_finished_at):
                    raise SystemExit(f"style_{style} 恢复时间倒序")
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
        tool_call_id = result.get("tool_call_id")
        saved_path = result.get("savedPath")
        started = result.get("tool_started_at")
        finished = result.get("tool_finished_at")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise SystemExit(f"style_{style} 缺少 tool_call_id")
        if not isinstance(saved_path, str) or not saved_path:
            raise SystemExit(f"style_{style} 缺少 savedPath")
        if not isinstance(started, str) or not isinstance(finished, str):
            raise SystemExit(f"style_{style} 缺少工具起止时间")
        try:
            if parse_time(started) > parse_time(finished):
                raise SystemExit(f"style_{style} 工具时间倒序")
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if action == "recover_artifact":
            validate_timestamp_chain(
                [
                    ("tool_started_at", started),
                    ("tool_finished_at", finished),
                    ("recovery_started_at", recovery_started_at),
                    ("recovery_finished_at", recovery_finished_at),
                ],
                f"style_{style}/{page_id} 原工具与恢复",
            )
            validate_timestamp_chain(
                [
                    ("agent_action_started_at", result.get("agent_action_started_at")),
                    ("recovery_started_at", recovery_started_at),
                    ("recovery_finished_at", recovery_finished_at),
                    ("agent_action_finished_at", result.get("agent_action_finished_at")),
                ],
                f"style_{style}/{page_id} 恢复 Agent",
            )
        else:
            if audit_version >= CURRENT_STATE_AUDIT_VERSION and (
                not isinstance(result.get("agent_action_started_at"), str)
                or not result.get("agent_action_started_at")
                or not isinstance(result.get("agent_action_finished_at"), str)
                or not result.get("agent_action_finished_at")
            ):
                raise SystemExit(
                    f"style_{style}/{page_id} v2 正常生图结果必须提供真实 "
                    "agent_action_started_at/agent_action_finished_at，"
                    "不得用图片工具时间代填"
                )
            validate_timestamp_chain(
                [
                    ("agent_action_started_at", result.get("agent_action_started_at")),
                    ("tool_started_at", started),
                    ("tool_finished_at", finished),
                    ("agent_action_finished_at", result.get("agent_action_finished_at")),
                ],
                f"style_{style}/{page_id}",
            )
        source = Path(saved_path).resolve()
        try:
            width, height, size, sha256 = png_metadata(source)
        except SystemExit as exc:
            unresolved.append(
                {
                    "style": style,
                    "page_id": page_id,
                    "action": action,
                    "attempt": attempt,
                    "error": "invalid_artifact",
                    "detail": str(exc),
                    "worker_agent_id": result.get("worker_agent_id"),
                    "agent_action_started_at": result.get("agent_action_started_at"),
                    "agent_action_finished_at": result.get("agent_action_finished_at"),
                    "tool_call_id": result.get("tool_call_id"),
                    "savedPath": result.get("savedPath"),
                    "tool_started_at": result.get("tool_started_at"),
                    "tool_finished_at": result.get("tool_finished_at"),
                }
            )
            continue
        normalized.append(
            {
                **result,
                "style": style,
                "page_id": page_id,
                "action": action,
                "source_action": source_action,
                "recovery_started_at": recovery_started_at,
                "recovery_finished_at": recovery_finished_at,
                "recovery_method": recovery_method,
                "source": str(source),
                "width": width,
                "height": height,
                "size": size,
                "sha256": sha256,
            }
        )
    actual = {item["style"] for item in normalized}
    if expected is not None and seen_styles != expected:
        raise SystemExit(
            f"结果席位不匹配：expected={sorted(expected)} actual={sorted(seen_styles)}"
        )
    validate_unique_artifact_bindings(state, normalized)

    scheduler = state.setdefault("scheduler", {})
    active = scheduler.setdefault("active_actions", [])
    ready = scheduler.setdefault("ready_queue", [])
    recovery_queue = scheduler.setdefault("recovery_queue", [])
    pending_events: list[dict[str, Any]] = []
    global_lease_ids_to_release: list[str] = []
    skipped = 0

    def queue_event(
        name: str,
        occurred_at: str,
        style: str | None,
        page_id: str | None,
        action: str | None,
        details: dict[str, Any],
        rank: int,
    ) -> None:
        pending_events.append(
            {
                "name": name,
                "occurred_at": occurred_at,
                "style": style,
                "page_id": page_id,
                "action": action,
                "details": details,
                "rank": rank,
            }
        )

    for item in sorted(normalized, key=lambda value: value["tool_started_at"]):
        style = item["style"]
        page_id = item["page_id"]
        action = item["action"]
        source_action = item["source_action"]
        is_recovery = action == "recover_artifact"
        record = page_record(state, style, page_id)
        existing_tool = record.get("tool_call_id")
        existing_sha = record.get("source_sha256")
        existing_attempt = int(
            record.get("selected_attempt") or record.get("attempt_count") or 0
        )
        existing_action = record.get("selected_action")
        exact_replay = (
            existing_tool == item["tool_call_id"]
            and existing_sha == item["sha256"]
            and existing_attempt == int(item["attempt"])
            and existing_action in {None, source_action}
        )
        active_match = next(
            (
                entry
                for entry in active
                if entry.get("style") == style
                and str(entry.get("page_id")) == page_id
                and entry.get("action") == action
            ),
            None,
        )
        if active_match is None:
            if exact_replay:
                skipped += 1
                continue
            if audit_version >= CURRENT_STATE_AUDIT_VERSION:
                raise SystemExit(
                    f"style_{style}/{page_id}/{action} 没有匹配的 active_action，"
                    "拒绝结算未派发结果"
                )
            active_match = {
                "style": style,
                "page_id": page_id,
                "action": action,
                "source_action": source_action,
                "attempt": item["attempt"],
                "worker_agent_id": item.get("worker_agent_id"),
                "recovery_worker_agent_id": item.get("worker_agent_id"),
                "tool_call_id": item.get("tool_call_id"),
                "tool_started_at": item.get("tool_started_at"),
                "tool_finished_at": item.get("tool_finished_at"),
                "legacy_untracked_dispatch": True,
            }
        if int(active_match.get("attempt") or 1) != int(item["attempt"]):
            raise SystemExit(
                f"style_{style}/{page_id}/{action} 结果 attempt 与 active_action 不一致"
            )
        if not is_recovery and int(item["attempt"]) > 1:
            history = record.get("attempt_history") or []
            prior_tool_ids = {
                value
                for value in (
                    existing_tool,
                    *(
                        entry.get("tool_call_id")
                        for entry in history
                        if isinstance(entry, dict)
                    ),
                )
                if isinstance(value, str) and value
            }
            prior_hashes = {
                value
                for value in (
                    existing_sha,
                    *(
                        entry.get("source_sha256")
                        for entry in history
                        if isinstance(entry, dict)
                    ),
                )
                if isinstance(value, str) and value
            }
            if item["tool_call_id"] in prior_tool_ids:
                raise SystemExit(
                    f"style_{style}/{page_id}/{action} 重用了旧 tool_call_id，"
                    "拒绝把旧结果登记为新尝试"
                )
            if item["sha256"] in prior_hashes:
                raise SystemExit(
                    f"style_{style}/{page_id}/{action} 返回了与旧尝试相同的图片哈希，"
                    "拒绝把旧产物登记为新尝试"
                )
        active_worker = active_match.get(
            "recovery_worker_agent_id" if is_recovery else "worker_agent_id"
        )
        result_worker = item.get("worker_agent_id")
        receipt_identity_verified = (
            state.get("run_mode") == FAST8_MODE
            and item.get("binding_source")
            in {"worker_receipt", "worker_session_dir"}
        )
        if (
            active_worker not in {None, ""}
            and result_worker not in {None, ""}
            and active_worker != result_worker
            and not receipt_identity_verified
        ):
            raise SystemExit(
                f"style_{style}/{page_id}/{action} 结果 worker_agent_id "
                "与 active_action 不一致"
            )
        if is_recovery and isinstance(active_match, dict):
            for field in ("source_action", "attempt", "tool_call_id"):
                expected_value = active_match.get(field)
                if expected_value not in {None, ""} and item.get(field) != expected_value:
                    raise SystemExit(
                        f"style_{style}/{page_id} 恢复结果的 {field} "
                        "与派发时保存的来源不一致"
                    )
            for field in ("tool_started_at", "tool_finished_at"):
                expected_value = active_match.get(field)
                actual_value = item.get(field)
                if expected_value in {None, ""}:
                    continue
                try:
                    matches = parse_time(expected_value) == parse_time(actual_value)
                except (TypeError, ValueError) as exc:
                    raise SystemExit(str(exc)) from exc
                if not matches:
                    raise SystemExit(
                        f"style_{style}/{page_id} 恢复结果的 {field} "
                        "与派发时保存的原工具时间不一致"
                    )
        if record.get("recovery_status") == "queued" and not is_recovery:
            raise SystemExit(
                f"style_{style}/{page_id} 已进入恢复队列；"
                "必须用 action=recover_artifact 结算，不得伪装成再次生成"
            )
        incumbent_candidate_attempt = int(
            record.get("selected_attempt") or (1 if (existing_tool or existing_sha) else 0)
        )
        replacing_repair_candidate = (
            bool(existing_tool or existing_sha)
            and int(item["attempt"]) > incumbent_candidate_attempt
            and (
                (
                    state.get("run_mode") == FAST_4X3_MODE
                    and source_action == "repair_anchor"
                )
                or (
                    state.get("run_mode") == FAST8_MODE
                    and source_action == "repair_anchor"
                    and active_match.get("diversity_replacement") is True
                )
                or (
                    state.get("run_mode") == STRICT_4X3_MODE
                    and source_action in {"repair_anchor", "repair_page"}
                )
                or (
                    state.get("run_mode") == SELECTED_STYLE_EXPANSION_MODE
                    and source_action == "repair_page"
                )
            )
        )
        replacing_unbound_technical_retry = (
            not is_recovery
            and active_match.get("technical_retry") is True
            and not record.get("selected_source")
            and not existing_sha
            and int(item["attempt"]) > existing_attempt
        )
        recovering_unbound = (
            is_recovery
            and not record.get("selected_source")
            and not existing_sha
            and (not existing_tool or existing_tool == item["tool_call_id"])
        )
        if (
            (existing_tool or existing_sha)
            and not replacing_repair_candidate
            and not replacing_unbound_technical_retry
            and not recovering_unbound
        ):
            raise SystemExit(
                f"style_{style}/{page_id} 已绑定不同工具结果，拒绝覆盖"
            )
        if replacing_unbound_technical_retry:
            if existing_tool:
                _archive_unbound_attempt(
                    record,
                    {**active_match, "source_action": source_action},
                    str(record.get("recovery_status") or "not_found"),
                )
            for field in (
                "worker_agent_id",
                "backend_used",
                "tool_call_id",
                "selected_source",
                "selected_attempt",
                "selected_action",
                "source_size_bytes",
                "source_sha256",
                "agent_action_started_at",
                "tool_started_at",
                "tool_finished_at",
                "file_validated_at",
                "agent_action_finished_at",
                "artifact_binding_source",
                "timing_capture",
                "failure_reason",
            ):
                record[field] = None
            existing_tool = None
            existing_sha = None
        if replacing_repair_candidate:
            archived = active_match.get("incumbent_candidate")
            if not isinstance(archived, dict):
                archived = incumbent_candidate_snapshot(record)
            if archived is None:
                raise SystemExit(
                    f"style_{style}/{page_id}/{source_action} 缺少待替换候选溯源"
                )
            history = record.setdefault("attempt_history", [])
            if not isinstance(history, list):
                raise SystemExit("页面 attempt_history 必须是数组")
            duplicate_archive = any(
                isinstance(entry, dict)
                and int(entry.get("attempt") or 0) == int(archived["attempt"])
                and entry.get("tool_call_id") == archived.get("tool_call_id")
                and entry.get("selected_source") == archived.get("selected_source")
                for entry in history
            )
            if not duplicate_archive:
                history.append(dict(archived))
            for field in (
                "tool_call_id",
                "selected_source",
                "selected_attempt",
                "selected_action",
                "source_size_bytes",
                "source_sha256",
                "agent_action_started_at",
                "tool_started_at",
                "tool_finished_at",
                "file_validated_at",
                "agent_action_finished_at",
                "overview_qa_at",
                "completed_at",
                "final_path",
                "content_gate",
                "spatial_gate",
                "craft_gate",
                "qa_stage",
                "qa_scope",
                "qa_note",
                "failure_reason",
            ):
                record[field] = None
        common = {
            "attempt": item["attempt"],
            "backend_used": item.get("backend_used", "built-in image_gen"),
            "tool_call_id": item["tool_call_id"],
            "worker_agent_id": (
                active_match.get("worker_agent_id")
                if is_recovery
                else item.get("worker_agent_id")
            ),
            "binding_source": item.get("binding_source")
            or "worker_result",
            "timing_capture": item.get("timing_capture") or "worker_reported",
        }
        agent_started = (
            item["tool_started_at"]
            if is_recovery
            else item.get("agent_action_started_at") or item["tool_started_at"]
        )
        if not record.get("agent_action_started_at"):
            record["agent_action_started_at"] = agent_started
            apply_page_event_effects(
                record, "agent_action_started", source_action, common
            )
            queue_event(
                "agent_action_started",
                agent_started,
                style,
                page_id,
                source_action,
                common,
                0,
            )
        if not record.get("tool_started_at"):
            record["tool_started_at"] = item["tool_started_at"]
            apply_page_event_effects(record, "tool_started", source_action, common)
            queue_event(
                "tool_started",
                item["tool_started_at"],
                style,
                page_id,
                source_action,
                common,
                1,
            )
        if not record.get("tool_finished_at"):
            record["tool_finished_at"] = item["tool_finished_at"]
            apply_page_event_effects(record, "tool_finished", source_action, common)
            queue_event(
                "tool_finished",
                item["tool_finished_at"],
                style,
                page_id,
                source_action,
                common,
                2,
            )
        validated = {
            **common,
            "selected_source": item["source"],
            "source_size_bytes": item["size"],
            "source_sha256": item["sha256"],
            "dimensions": [item["width"], item["height"]],
        }
        if is_recovery:
            recovery = {
                **validated,
                "recovery_method": item["recovery_method"],
                "recovery_worker_agent_id": item.get("worker_agent_id"),
                "recovery_agent_action_started_at": item.get(
                    "agent_action_started_at"
                ),
                "recovery_agent_action_finished_at": item.get(
                    "agent_action_finished_at"
                ),
            }
            record["artifact_recovery_started_at"] = item["recovery_started_at"]
            apply_page_event_effects(
                record, "artifact_recovery_started", "recover_artifact", recovery
            )
            queue_event(
                "artifact_recovery_started",
                item["recovery_started_at"],
                style,
                page_id,
                "recover_artifact",
                recovery,
                4,
            )
            recovery["recovery_status"] = "recovered"
            record["artifact_recovery_finished_at"] = item["recovery_finished_at"]
            apply_page_event_effects(
                record, "artifact_recovery_finished", "recover_artifact", recovery
            )
            queue_event(
                "artifact_recovery_finished",
                item["recovery_finished_at"],
                style,
                page_id,
                "recover_artifact",
                recovery,
                5,
            )
        record["file_validated_at"] = settled_at
        apply_page_event_effects(record, "file_validated", source_action, validated)
        record["selected_action"] = source_action
        queue_event(
            "file_validated",
            settled_at,
            style,
            page_id,
            source_action,
            validated,
            6,
        )
        agent_finished = (
            item["tool_finished_at"]
            if is_recovery
            else item.get("agent_action_finished_at") or item["tool_finished_at"]
        )
        if not record.get("agent_action_finished_at"):
            record["agent_action_finished_at"] = agent_finished
            apply_page_event_effects(
                record, "agent_action_finished", source_action, validated
            )
            queue_event(
                "agent_action_finished",
                agent_finished,
                style,
                page_id,
                source_action,
                validated,
                3,
            )
        if isinstance(active_match.get("global_imagegen_lease_id"), str):
            global_lease_ids_to_release.append(active_match["global_imagegen_lease_id"])
        active[:] = [
            entry
            for entry in active
            if not (
                entry.get("style") == style
                and str(entry.get("page_id")) == page_id
                and entry.get("action") in {source_action, action}
            )
        ]
        ready[:] = [
            entry
            for entry in ready
            if not (
                entry.get("style") == style
                and str(entry.get("page_id")) == page_id
                and entry.get("action") in {source_action, action}
            )
        ]
        recovery_queue[:] = [
            entry
            for entry in recovery_queue
            if not (
                entry.get("style") == style
                and str(entry.get("page_id")) == page_id
                and entry.get("action") == "recover_artifact"
            )
        ]
        refresh_style_workflow_status(state, style)
        if (
            state.get("run_mode") == FAST8_MODE
            and source_action == "repair_anchor"
            and active_match.get("diversity_replacement") is True
        ):
            diversity_review = state.setdefault("diversity_review", {})
            diversity_review["status"] = "recheck_required"
            diversity_review["final_candidate_set_sha256"] = None

    for item in unresolved:
        record = page_record(state, item["style"], item["page_id"])
        active_match = next(
            (
                entry
                for entry in active
                if entry.get("style") == item["style"]
                and str(entry.get("page_id")) == item["page_id"]
                and entry.get("action") == item["action"]
            ),
            None,
        )
        queued_recovery = next(
            (
                entry
                for entry in recovery_queue
                if entry.get("style") == item["style"]
                and str(entry.get("page_id")) == item["page_id"]
                and entry.get("action") == "recover_artifact"
                and entry.get("source_action") == item["action"]
                and int(entry.get("attempt") or 1) == int(item["attempt"])
            ),
            None,
        )
        if active_match is not None and queued_recovery is not None:
            raise SystemExit(
                f"style_{item['style']}/{item['page_id']} 同时存在 active generation "
                "和 queued recovery，状态损坏"
            )
        if queued_recovery is not None:
            provenance_pairs = {
                "failure_reason": (
                    queued_recovery.get("failure_reason"),
                    item.get("error"),
                ),
                "worker_agent_id": (
                    queued_recovery.get("worker_agent_id"),
                    item.get("worker_agent_id"),
                ),
                "tool_call_id": (
                    queued_recovery.get("tool_call_id"),
                    item.get("tool_call_id"),
                ),
                "agent_action_started_at": (
                    queued_recovery.get("agent_action_started_at"),
                    item.get("agent_action_started_at"),
                ),
                "agent_action_finished_at": (
                    queued_recovery.get("agent_action_finished_at"),
                    item.get("agent_action_finished_at"),
                ),
                "tool_started_at": (
                    queued_recovery.get("tool_started_at"),
                    item.get("tool_started_at"),
                ),
                "tool_finished_at": (
                    queued_recovery.get("tool_finished_at"),
                    item.get("tool_finished_at"),
                ),
            }
            for field, (expected_value, actual_value) in provenance_pairs.items():
                if expected_value in {None, ""} or actual_value in {None, ""}:
                    continue
                if field.endswith("_at"):
                    try:
                        matches = parse_time(expected_value) == parse_time(actual_value)
                    except (TypeError, ValueError) as exc:
                        raise SystemExit(str(exc)) from exc
                else:
                    matches = expected_value == actual_value
                if not matches:
                    raise SystemExit(
                        f"style_{item['style']}/{item['page_id']} unresolved 重放的 "
                        f"{field} 与已排 recovery 的来源冲突"
                    )
        if (
            active_match is None
            and queued_recovery is None
            and audit_version >= CURRENT_STATE_AUDIT_VERSION
        ):
            raise SystemExit(
                f"style_{item['style']}/{item['page_id']}/{item['action']} "
                "没有匹配的 active_action，拒绝记录未派发失败"
            )
        if active_match is not None:
            if int(active_match.get("attempt") or 1) != int(item["attempt"]):
                raise SystemExit(
                    f"style_{item['style']}/{item['page_id']} 失败结果 attempt "
                    "与 active_action 不一致"
                )
            active_worker = active_match.get("worker_agent_id")
            result_worker = item.get("worker_agent_id")
            receipt_identity_verified = (
                state.get("run_mode") == FAST8_MODE
                and item.get("binding_source")
                in {"worker_receipt", "worker_session_dir"}
            )
            if (
                active_worker not in {None, ""}
                and result_worker not in {None, ""}
                and active_worker != result_worker
                and not receipt_identity_verified
            ):
                raise SystemExit(
                    f"style_{item['style']}/{item['page_id']} 失败结果 worker_agent_id "
                    "与 active_action 不一致"
                )
            if isinstance(active_match.get("global_imagegen_lease_id"), str):
                global_lease_ids_to_release.append(
                    active_match["global_imagegen_lease_id"]
                )
        if item.get("error") == "imagegen_backend_failed":
            if not isinstance(active_match, dict):
                raise SystemExit(
                    f"style_{item['style']}/{item['page_id']} 后端失败缺少 active_action"
                )
            _transition_fast8_backend_failure(
                state_path,
                state,
                item,
                active_match,
                settled_at,
            )
            continue
        record["attempt_count"] = max(
            int(record.get("attempt_count") or 0), int(item["attempt"])
        )
        for field in (
            "worker_agent_id",
            "agent_action_started_at",
            "agent_action_finished_at",
            "tool_call_id",
            "tool_started_at",
            "tool_finished_at",
        ):
            value = item.get(field)
            if value not in {None, ""} and not record.get(field):
                record[field] = value
        record["status"] = "recovery_pending"
        record["failure_reason"] = item["error"]
        record["recovery_required"] = True
        record["recovery_status"] = "queued"
        recovery = {
            "style": item["style"],
            "page_id": item["page_id"],
            "action": "recover_artifact",
            "source_action": item["action"],
            "attempt": item["attempt"],
            "worker_agent_id": item.get("worker_agent_id"),
            "failure_reason": item["error"],
            "agent_action_started_at": item.get("agent_action_started_at"),
            "agent_action_finished_at": item.get("agent_action_finished_at"),
            "tool_call_id": item.get("tool_call_id"),
            "savedPath": item.get("savedPath"),
            "tool_started_at": item.get("tool_started_at"),
            "tool_finished_at": item.get("tool_finished_at"),
        }
        if isinstance(active_match, dict):
            for field in (
                "generation_job_path",
                "generation_job_sha256",
                "diversity_replacement",
            ):
                if active_match.get(field):
                    recovery[field] = active_match[field]
        incumbent = (
            active_match.get("incumbent_candidate")
            if isinstance(active_match, dict)
            else queued_recovery.get("incumbent_candidate")
            if isinstance(queued_recovery, dict)
            else None
        )
        if isinstance(incumbent, dict):
            recovery["incumbent_candidate"] = incumbent
        already_queued = any(
            entry.get("style") == recovery["style"]
            and str(entry.get("page_id")) == recovery["page_id"]
            and entry.get("action") == "recover_artifact"
            for entry in recovery_queue
        )
        if not already_queued:
            recovery_queue.append(recovery)
        else:
            existing_recovery = next(
                entry
                for entry in recovery_queue
                if entry.get("style") == recovery["style"]
                and str(entry.get("page_id")) == recovery["page_id"]
                and entry.get("action") == "recover_artifact"
            )
            for field, value in recovery.items():
                if value not in {None, ""} and not existing_recovery.get(field):
                    existing_recovery[field] = value
        active[:] = [
            entry
            for entry in active
            if not (
                entry.get("style") == item["style"]
                and str(entry.get("page_id")) == item["page_id"]
                and entry.get("action") == item["action"]
            )
        ]
        ready[:] = [
            entry
            for entry in ready
            if not (
                entry.get("style") == item["style"]
                and str(entry.get("page_id")) == item["page_id"]
                and entry.get("action") == item["action"]
            )
        ]
        if not already_queued:
            queue_event(
                "artifact_handoff_unresolved",
                settled_at,
                item["style"],
                item["page_id"],
                item["action"],
                {
                    "attempt": item["attempt"],
                    "worker_agent_id": item.get("worker_agent_id"),
                    "failure_reason": item["error"],
                    "next_action": "recover_artifact",
                    "tool_call_id": item.get("tool_call_id"),
                    "tool_started_at": item.get("tool_started_at"),
                    "tool_finished_at": item.get("tool_finished_at"),
                },
                7,
            )
        else:
            skipped += 1

    mode = state.get("run_mode") or state.get("mode")
    if mode == SELECTED_STYLE_EXPANSION_MODE:
        selected_style = normalize_style(state.get("selected_style"))
        if selected_style is None:
            raise SystemExit("选定风格扩页状态缺少 selected_style")
        active_styles = (selected_style,)
        page_order = [str(value) for value in (state.get("page_order") or [])]
        if not page_order:
            raise SystemExit("选定风格扩页状态缺少 page_order")
        anchor_page_id = page_order[0]
    else:
        active_styles = styles_for_mode(mode)
        page_order = []
        anchor_page_id = str(state.get("anchor_page_id"))
    blocked_styles = [
        style
        for style in active_styles
        if page_record(state, style, anchor_page_id).get("status") == "blocked"
    ]
    blocked_fast4x3_tasks = []
    if mode == FAST_4X3_MODE:
        page_ids = [
            anchor_page_id,
            *(str(value) for value in (state.get("follower_page_ids") or [])),
        ]
        blocked_fast4x3_tasks = []
        for style in active_styles:
            pages = (((state.get("styles") or {}).get(style) or {}).get("pages") or {})
            for page_id in page_ids:
                record = pages.get(page_id)
                if isinstance(record, dict) and record.get("status") == "blocked":
                    blocked_fast4x3_tasks.append(
                        {
                            "style": style,
                            "page_id": page_id,
                            "reason": record.get("failure_reason"),
                        }
                    )
    run_terminalized = False
    if mode == FAST8_MODE and blocked_styles:
        global_lease_ids_to_release.extend(
            terminalize_blocked_fast8_state(
                state,
                timestamp=settled_at,
                blocked_styles=blocked_styles,
            )
        )
        run_terminalized = True
    elif mode == FAST_4X3_MODE and blocked_fast4x3_tasks:
        global_lease_ids_to_release.extend(
            terminalize_blocked_run_state(
                state,
                timestamp=settled_at,
                reason="required_fast4x3_page_exhausted",
                blocked_tasks=blocked_fast4x3_tasks,
            )
        )
        run_terminalized = True
    if mode == SELECTED_STYLE_EXPANSION_MODE:
        all_ready = all(
            page_record(state, None, page_id).get("tool_finished_at")
            and page_record(state, None, page_id).get("selected_source")
            for page_id in page_order
        )
    else:
        all_ready = all(
            page_record(state, style, anchor_page_id).get("tool_finished_at")
            and page_record(state, style, anchor_page_id).get("selected_source")
            for style in active_styles
        )
    timing = state.setdefault("timing", {})
    if all_ready and not timing.get("all_anchor_tools_completed_at"):
        completed_at = max(
            (
                page_record(state, None, page_id)["tool_finished_at"]
                for page_id in page_order
            )
            if mode == SELECTED_STYLE_EXPANSION_MODE
            else (
                page_record(state, style, anchor_page_id)["tool_finished_at"]
                for style in active_styles
            ),
            key=parse_time,
        )
        timing["all_anchor_tools_completed_at"] = completed_at
        queue_event(
            "all_anchor_tools_completed",
            completed_at,
            None,
            None,
            None,
            {
                "style_count": len(active_styles),
                "page_count": len(page_order) if page_order else 1,
                "settled_by": "settle-wave",
            },
            5,
        )
    for event in sorted(
        pending_events,
        key=lambda value: (
            parse_time(value["occurred_at"]),
            value["rank"],
            value.get("style") or "",
        ),
    ):
        append_event(
            state,
            event["name"],
            event["occurred_at"],
            style=event["style"],
            page_id=event["page_id"],
            action=event["action"],
            details=event["details"],
        )
    atomic_write_json(state_path, state)
    released_global_slots = 0
    if state.get("run_mode") in {FAST8_MODE, FAST_4X3_MODE}:
        released_global_slots = release_fast8_global_imagegen_slots(
            state_path, state, global_lease_ids_to_release
        )
    print(
        json.dumps(
            {
                "status": "ok",
                "settled": len(normalized),
                "skipped": skipped,
                "styles": sorted(actual),
                "unresolved": unresolved,
                "all_anchor_tools_completed": all_ready,
                "run_terminalized": run_terminalized,
                "blocked_styles": blocked_styles,
                "released_global_imagegen_slots": released_global_slots,
            },
            ensure_ascii=False,
        )
    )


def command_prepare_quick_qa(args: argparse.Namespace) -> None:
    """为旧 quick8 v3 生成分组 QA；v4/v5 只交付总览链接。"""

    state = read_json(Path(args.state).resolve())
    if (state.get("run_mode") or state.get("mode")) != "quick_8x1":
        raise SystemExit("prepare-quick-qa 只适用于 quick_8x1")
    if layout_portfolio_contract_version(state) in ONE_SHOT_QUICK_LAYOUT_VERSIONS:
        raise SystemExit(
            "quick8 v4/v5 不创建分组 QA Agent；请立即生成 2×4 总览，"
            "由根任务做文件元数据检查、提供总览链接并等待用户选择"
        )
    project_dir = Path(args.project_dir).resolve()
    page_id = str(state.get("anchor_page_id"))
    groups = {
        "dark": FULL_STYLES,
        "light": QUICK_STYLES[4:],
    }
    selected_groups = [args.group] if args.group else ["dark", "light"]
    jobs: list[str] = []
    for group in selected_groups:
        styles = groups[group]
        pages = []
        for style in styles:
            record = page_record(state, style, page_id)
            source = record.get("selected_source")
            if not isinstance(source, str) or not Path(source).is_file():
                raise SystemExit(f"style_{style}/{page_id} 尚无可读 selected_source")
            style_job = read_json(project_dir / "style_jobs" / f"style_{style}.json")
            pages.append(
                {
                    "style": style,
                    "tone": group,
                    "selected_source": source,
                    "layout_direction": style_job.get("layout_direction")
                    or style_job.get("exploration_seed"),
                    "reference_images": style_job.get("reference_images", []),
                    "required_assets": style_job.get("required_assets", []),
                }
            )
        first_job = read_json(project_dir / "style_jobs" / f"style_{styles[0]}.json")
        qa_job = {
            "qa_contract_version": 1,
            "group": group,
            "page_id": page_id,
            "overall_requirements": first_job.get("overall_requirements"),
            "content_contract": first_job["anchor_page"],
            "pages": pages,
            "checks": [
                "content_gate：必显事实、文字、Logo 与语义关系",
                "spatial_gate：按页面档位检查入口、阅读结构、负空间、边缘和 Takeaway 角色",
                "craft_gate：完成度、模板感、图像工艺、碰撞遮挡、参考意图与导演方向命中",
                "group_diversity：允许共享母结构，但各张的版式变体、阅读路径、视觉重心或图文关系必须形成可观察差异",
            ],
        }
        path = project_dir / "qa_jobs" / f"quick_{group}.json"
        atomic_write_json(path, qa_job)
        jobs.append(str(path))
    print(json.dumps({"status": "ok", "qa_jobs": jobs}, ensure_ascii=False))


def fast8_candidate_manifest(
    state: dict[str, Any], *, styles: list[str] | None = None
) -> list[dict[str, Any]]:
    """返回 Fast8 当前候选的哈希绑定清单，不把图片载荷带入调用方。"""

    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("Fast8 候选清单只适用于 fast_8x1_diverse")
    page_id = str(state.get("anchor_page_id"))
    requested = list(QUICK_STYLES) if styles is None else styles
    if not requested:
        raise SystemExit("Fast8 候选清单的 styles 不得为空")
    manifest: list[dict[str, Any]] = []
    for style in requested:
        record = page_record(state, style, page_id)
        source = record.get("selected_source")
        source_sha = record.get("source_sha256")
        if not isinstance(source, str) or not Path(source).is_absolute():
            raise SystemExit(f"style_{style}/{page_id} 尚无绝对 selected_source")
        path = Path(source).resolve()
        width, height, size, current_sha = png_metadata(path)
        if not isinstance(source_sha, str) or source_sha != current_sha:
            raise SystemExit(f"style_{style}/{page_id} 候选文件与状态哈希不一致")
        manifest.append(
            {
                "style": style,
                "page_id": page_id,
                "selected_source": str(path),
                "selected_attempt": int(record.get("selected_attempt") or 1),
                "source_sha256": current_sha,
                "dimensions": [width, height],
                "size_bytes": size,
            }
        )
    return manifest


def fast8_candidate_set_sha256(manifest: list[dict[str, Any]]) -> str:
    identity = [
        {
            "style": item["style"],
            "page_id": str(item["page_id"]),
            "selected_attempt": int(item["selected_attempt"]),
            "source_sha256": item["source_sha256"],
        }
        for item in sorted(manifest, key=lambda value: value["style"])
    ]
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def command_prepare_global_chrome_review(args: argparse.Namespace) -> None:
    """Prepare a separate, hash-bound Fast8 deck-title QA job."""

    project_dir = Path(args.project_dir).resolve()
    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("prepare-global-chrome-review v1 只适用于 fast_8x1_diverse")
    review = state.get("global_chrome_review") or {}
    if review.get("required") is not True:
        print(json.dumps({"status": "not_applicable"}, ensure_ascii=False))
        return
    if review.get("review_mode") == "integrated_fast8_judge" and review.get(
        "status"
    ) not in {"fail", "needs_inspection"}:
        print(
            json.dumps(
                {
                    "status": "integrated_into_fast8_judge",
                    "global_chrome_status": review.get("status"),
                },
                ensure_ascii=False,
            )
        )
        return
    contract_path, contract, contract_sha = read_global_chrome_contract(
        review.get("contract_path") or state.get("global_chrome_contract_path"),
        verify_authorization_source=False,
    )
    if contract_sha != review.get("contract_sha256"):
        raise SystemExit("global chrome review 绑定的合同 SHA-256 已变化")
    manifest = fast8_candidate_manifest(state)
    candidate_set_sha = fast8_candidate_set_sha256(manifest)
    if review.get("status") == "reviewing":
        existing_path = require_formal_file_path(
            review.get("job_path"), "global chrome review job"
        )
        existing = read_json(existing_path)
        if existing.get("candidate_set_sha256") != candidate_set_sha:
            raise SystemExit("既有 global chrome review job 已过期")
        print(
            json.dumps(
                {
                    "status": "already_prepared",
                    "review_job": str(existing_path),
                    "review_job_sha256": file_sha256(existing_path),
                    "candidate_set_sha256": candidate_set_sha,
                },
                ensure_ascii=False,
            )
        )
        return
    if review.get("status") == "pass" and review.get(
        "candidate_set_sha256"
    ) == candidate_set_sha:
        print(
            json.dumps(
                {
                    "status": "already_applied",
                    "candidate_set_sha256": candidate_set_sha,
                },
                ensure_ascii=False,
            )
        )
        return

    page_id = str(state.get("anchor_page_id"))
    jobs: list[dict[str, Any]] = []
    for item in manifest:
        style = str(item["style"])
        style_job_path = project_dir / "style_jobs" / f"style_{style}.json"
        style_job = read_json(style_job_path)
        projection = style_job.get("global_chrome") or {}
        if projection.get("applies") is not True:
            raise SystemExit(f"style_{style} 缺少适用的 global chrome 投影")
        if projection.get("contract_sha256") != contract_sha:
            raise SystemExit(f"style_{style} global chrome 合同绑定不一致")
        brief = projection.get("prompt_brief")
        prompt = style_job.get("imagegen_prompt")
        if not isinstance(brief, str) or not isinstance(prompt, str) or prompt.count(
            brief
        ) != 1:
            raise SystemExit(f"style_{style} 必须且只能短编译一次 global chrome brief")
        candidate = {
            **item,
            "generation_job_path": str(style_job_path),
            "generation_job_sha256": file_sha256(style_job_path),
            "tone": projection.get("tone"),
        }
        logo_asset = projection.get("logo_asset") or {}
        logo_path = logo_asset.get("path")
        if projection.get("logo_required") is True:
            if not isinstance(logo_path, str) or logo_path not in (
                style_job.get("imagegen_referenced_paths") or []
            ):
                raise SystemExit(f"style_{style} 未路由大纲要求的官方 Logo")
            candidate["expected_logo_path"] = logo_path
        jobs.append(candidate)
    deck = contract.get("deck_title_system") or {}
    job = {
        "global_chrome_review_contract_version": GLOBAL_CHROME_REVIEW_CONTRACT_VERSION,
        "review_kind": "outline_title_system_adherence",
        "run_id": state.get("run_id"),
        "run_mode": state.get("run_mode"),
        "page_id": page_id,
        "candidate_set_sha256": candidate_set_sha,
        "global_chrome_contract": {
            "path": str(contract_path),
            "sha256": contract_sha,
            "contract_id": contract.get("contract_id"),
        },
        "qa_reference_path": deck.get("qa_reference_path"),
        "checks": list(deck.get("qa_checks") or []),
        "authorized_requirements": {
            "logo_required": bool((deck.get("logo") or {}).get("required")),
            "main_title_required": bool(
                (deck.get("main_title") or {}).get("required")
            ),
            "subtitle_policy": deck.get("subtitle_policy"),
        },
        "candidates": jobs,
        "review_protocol": {
            "root_must_not_open_images": True,
            "contact_sheet_first": True,
            "inspect_individual_when_unknown": True,
            "match_mode": "approximate",
            "pixel_exact_match_required": False,
            "fail_only_on_clear_outline_deviation": True,
            "fixed_title_zone_is_not_itself_a_breathing_failure": True,
            "return_text_json_only": True,
        },
    }
    job_path = project_dir / "visual_qa_jobs" / "global_chrome_review.json"
    atomic_write_json(job_path, job)
    review.update(
        {
            "status": "reviewing",
            "job_path": str(job_path),
            "job_sha256": file_sha256(job_path),
            "candidate_set_sha256": candidate_set_sha,
        }
    )
    state["global_chrome_review"] = review
    atomic_write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "ok",
                "review_job": str(job_path),
                "review_job_sha256": file_sha256(job_path),
                "candidate_set_sha256": candidate_set_sha,
            },
            ensure_ascii=False,
        )
    )


def command_apply_global_chrome_review(args: argparse.Namespace) -> None:
    """Apply the isolated title-system QA result without mixing it into aesthetics."""

    state_path = Path(args.state).resolve()
    project_dir = project_dir_for_state(state_path, read_json(state_path))
    state = read_json(state_path)
    review = state.get("global_chrome_review") or {}
    if review.get("required") is not True:
        raise SystemExit("当前运行不要求 global chrome review")
    job_path = Path(args.review_job).resolve()
    report_path = Path(args.report_file).resolve()
    require_path_within(job_path, project_dir / "visual_qa_jobs", "global chrome job")
    require_path_within(
        report_path, project_dir / "visual_qa_jobs" / "results", "global chrome report"
    )
    if str(job_path) != review.get("job_path") or file_sha256(job_path) != review.get(
        "job_sha256"
    ):
        raise SystemExit("global chrome review job 未登记或哈希不一致")
    job = read_json(job_path)
    report = read_json(report_path)
    allowed_fields = {
        "global_chrome_review_contract_version",
        "review_job_sha256",
        "candidate_set_sha256",
        "decision",
        "candidate_results",
        "summary",
    }
    if set(report) - allowed_fields:
        raise SystemExit("global chrome review report 包含未授权字段")
    if report.get("global_chrome_review_contract_version") != (
        GLOBAL_CHROME_REVIEW_CONTRACT_VERSION
    ):
        raise SystemExit("global chrome review report 合同版本无效")
    if report.get("review_job_sha256") != file_sha256(job_path):
        raise SystemExit("global chrome review report 未绑定正式 job")
    candidate_set_sha = fast8_candidate_set_sha256(fast8_candidate_manifest(state))
    if (
        report.get("candidate_set_sha256") != candidate_set_sha
        or job.get("candidate_set_sha256") != candidate_set_sha
    ):
        raise SystemExit("global chrome review report 已过期")
    summary = report.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 300:
        raise SystemExit("global chrome review summary 必须是 1–300 字")
    results = report.get("candidate_results")
    if not isinstance(results, list) or len(results) != len(QUICK_STYLES):
        raise SystemExit("global chrome review 必须逐席返回 A–H")
    statuses = {"pass", "fail", "unknown", "not_applicable"}
    check_fields = (
        "logo_presence",
        "official_logo_fidelity",
        "title_structure",
        "title_alignment_safe_margin",
        "chrome_weight",
    )
    seen_styles: set[str] = set()
    has_fail = False
    has_unknown = False
    requirements = job.get("authorized_requirements") or {}
    applicable_fields = {
        "logo_presence": requirements.get("logo_required") is True,
        "official_logo_fidelity": requirements.get("logo_required") is True,
        "title_structure": requirements.get("main_title_required") is True,
        "title_alignment_safe_margin": requirements.get("main_title_required") is True,
        "chrome_weight": True,
    }
    for index, item in enumerate(results):
        if not isinstance(item, dict) or set(item) - {"style", *check_fields, "note"}:
            raise SystemExit(f"candidate_results[{index}] 字段无效")
        style = normalize_style(item.get("style"))
        if style not in QUICK_STYLES or style in seen_styles:
            raise SystemExit("global chrome review 席位必须是互异 A–H")
        seen_styles.add(style)
        for field in check_fields:
            value = item.get(field)
            if value not in statuses:
                raise SystemExit(
                    f"style_{style}.{field} 只允许 pass|fail|unknown|not_applicable"
                )
            if applicable_fields[field] and value == "not_applicable":
                raise SystemExit(f"style_{style}.{field} 是大纲适用要求，不能标为 not_applicable")
            if not applicable_fields[field] and value == "not_applicable":
                continue
            has_fail = has_fail or value == "fail"
            has_unknown = has_unknown or value == "unknown"
        note = item.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 240):
            raise SystemExit(f"style_{style}.note 必须为不超过 240 字的字符串")
    decision = report.get("decision")
    expected_decision = "fail" if has_fail else "needs_inspection" if has_unknown else "pass"
    if decision != expected_decision:
        raise SystemExit(
            f"global chrome review decision 应为 {expected_decision}，实际为 {decision}"
        )
    review.update(
        {
            "status": decision,
            "report_path": str(report_path),
            "report_sha256": file_sha256(report_path),
            "candidate_set_sha256": candidate_set_sha,
            "summary": summary.strip(),
        }
    )
    state["global_chrome_review"] = review
    atomic_write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": decision,
                "report_sha256": file_sha256(report_path),
                "candidate_set_sha256": candidate_set_sha,
            },
            ensure_ascii=False,
        )
    )


def png_paeth_predictor(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def decode_png_rgb(path: Path) -> tuple[int, int, bytes]:
    """Decode non-interlaced 8-bit gray/RGB/RGBA PNG with stdlib only."""

    payload = path.read_bytes()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SystemExit(f"Fast8 contact sheet 只接受 PNG：{path}")
    offset = 8
    width = height = bit_depth = color_type = interlace = None
    compressed = bytearray()
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_data = payload[offset + 8 : offset + 8 + length]
        if offset + 12 + length > len(payload):
            raise SystemExit(f"Fast8 contact sheet PNG chunk 截断：{path}")
        if chunk_type == b"IHDR":
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk_data)
            if compression != 0 or filter_method != 0:
                raise SystemExit(f"Fast8 contact sheet PNG 压缩或过滤方法无效：{path}")
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
        offset += length + 12
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or bit_depth != 8
        or color_type not in {0, 2, 4, 6}
        or interlace != 0
    ):
        raise SystemExit(
            f"Fast8 contact sheet PNG 必须是非交错 8-bit gray/RGB/RGBA：{path}"
        )
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[int(color_type)]
    row_bytes = width * channels
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise SystemExit(f"Fast8 contact sheet PNG 数据无法解压：{path}") from exc
    expected_size = height * (row_bytes + 1)
    if len(raw) != expected_size:
        raise SystemExit(f"Fast8 contact sheet PNG 扫描行长度无效：{path}")

    decoded_rows: list[bytearray] = []
    cursor = 0
    previous = bytearray(row_bytes)
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        source_row = raw[cursor : cursor + row_bytes]
        cursor += row_bytes
        if filter_type == 0:
            current = bytearray(source_row)
        else:
            current = bytearray(row_bytes)
            for index, value in enumerate(source_row):
                left = current[index - channels] if index >= channels else 0
                above = previous[index]
                upper_left = previous[index - channels] if index >= channels else 0
                if filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = above
                elif filter_type == 3:
                    predictor = (left + above) // 2
                elif filter_type == 4:
                    predictor = png_paeth_predictor(left, above, upper_left)
                else:
                    raise SystemExit(f"Fast8 contact sheet PNG filter 无效：{path}")
                current[index] = (value + predictor) & 0xFF
        decoded_rows.append(current)
        previous = current

    if color_type == 2:
        return width, height, b"".join(decoded_rows)
    rgb = bytearray(width * height * 3)
    destination = 0
    for row in decoded_rows:
        for index in range(0, len(row), channels):
            if color_type == 0:
                red = green = blue = row[index]
                alpha = 255
            elif color_type == 2:
                red, green, blue = row[index : index + 3]
                alpha = 255
            elif color_type == 4:
                red = green = blue = row[index]
                alpha = row[index + 1]
            else:
                red, green, blue, alpha = row[index : index + 4]
            if alpha != 255:
                red = (red * alpha + 255 * (255 - alpha) + 127) // 255
                green = (green * alpha + 255 * (255 - alpha) + 127) // 255
                blue = (blue * alpha + 255 * (255 - alpha) + 127) // 255
            rgb[destination : destination + 3] = bytes((red, green, blue))
            destination += 3
    return width, height, bytes(rgb)


def resize_rgb_nearest(
    pixels: bytes,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> bytes:
    x_map = [min(source_width - 1, x * source_width // target_width) for x in range(target_width)]
    output = bytearray(target_width * target_height * 3)
    for target_y in range(target_height):
        source_y = min(source_height - 1, target_y * source_height // target_height)
        source_row = source_y * source_width * 3
        destination_row = target_y * target_width * 3
        for target_x, source_x in enumerate(x_map):
            source_offset = source_row + source_x * 3
            destination_offset = destination_row + target_x * 3
            output[destination_offset : destination_offset + 3] = pixels[
                source_offset : source_offset + 3
            ]
    return bytes(output)


def encode_png_rgb(width: int, height: int, pixels: bytes) -> bytes:
    if len(pixels) != width * height * 3:
        raise SystemExit("Fast8 contact sheet RGB 画布长度无效")

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    scanlines = bytearray()
    row_bytes = width * 3
    for row in range(height):
        scanlines.append(0)
        start = row * row_bytes
        scanlines.extend(pixels[start : start + row_bytes])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(scanlines), 6))
        + chunk(b"IEND", b"")
    )


def draw_contact_sheet_style_label(
    canvas: bytearray,
    canvas_width: int,
    x: int,
    y: int,
    cell_width: int,
    label_height: int,
    style: str,
) -> None:
    for row in range(y, y + label_height):
        start = (row * canvas_width + x) * 3
        canvas[start : start + cell_width * 3] = bytes((32, 32, 32)) * cell_width
    glyphs = {
        "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
        "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
        "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
        "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
        "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
        "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
        "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
        "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    }
    pattern = glyphs[style]
    scale = 3
    glyph_width = len(pattern[0]) * scale
    glyph_height = len(pattern) * scale
    origin_x = x + (cell_width - glyph_width) // 2
    origin_y = y + (label_height - glyph_height) // 2
    for pattern_y, pattern_row in enumerate(pattern):
        for pattern_x, enabled in enumerate(pattern_row):
            if enabled != "1":
                continue
            for delta_y in range(scale):
                row = origin_y + pattern_y * scale + delta_y
                for delta_x in range(scale):
                    column = origin_x + pattern_x * scale + delta_x
                    offset = (row * canvas_width + column) * 3
                    canvas[offset : offset + 3] = b"\xff\xff\xff"


def build_fast8_review_contact_sheet(
    project_dir: Path,
    manifest: list[dict[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    """Build one deterministic low-load Judge input from the formal candidates."""

    del project_dir  # kept in the public signature for call-site clarity
    candidate_count = len(manifest)
    if candidate_count < 1 or candidate_count > len(QUICK_STYLES):
        raise SystemExit("Fast8 contact sheet 候选数量必须在 1 到 8 之间")
    columns = 4 if candidate_count >= 7 else 3 if candidate_count >= 5 else 2
    rows = (candidate_count + columns - 1) // columns
    cell_width = 480
    cell_height = 270
    label_height = 30
    gap = 12
    canvas_width = columns * cell_width + (columns + 1) * gap
    canvas_height = rows * (label_height + cell_height) + (rows + 1) * gap
    canvas = bytearray(bytes((236, 236, 236)) * canvas_width * canvas_height)
    styles: list[str] = []

    for index, item in enumerate(manifest):
        style = str(item.get("style") or "")
        source_value = item.get("selected_source")
        if style not in QUICK_STYLES or not isinstance(source_value, str):
            raise SystemExit("Fast8 contact sheet manifest 缺少合法 style/selected_source")
        source = Path(source_value).resolve()
        if not source.is_file():
            raise SystemExit(f"Fast8 contact sheet 原图不存在：{source}")
        expected_sha = item.get("source_sha256")
        if not isinstance(expected_sha, str) or file_sha256(source) != expected_sha:
            raise SystemExit(f"Fast8 contact sheet 原图 SHA-256 不匹配：style_{style}")
        source_width, source_height, source_pixels = decode_png_rgb(source)
        resized = resize_rgb_nearest(
            source_pixels,
            source_width,
            source_height,
            cell_width,
            cell_height,
        )
        row, column = divmod(index, columns)
        x = gap + column * (cell_width + gap)
        label_y = gap + row * (label_height + cell_height + gap)
        image_y = label_y + label_height
        draw_contact_sheet_style_label(
            canvas,
            canvas_width,
            x,
            label_y,
            cell_width,
            label_height,
            style,
        )
        for image_row in range(cell_height):
            source_start = image_row * cell_width * 3
            destination_start = ((image_y + image_row) * canvas_width + x) * 3
            canvas[destination_start : destination_start + cell_width * 3] = resized[
                source_start : source_start + cell_width * 3
            ]
        styles.append(style)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    png_bytes = encode_png_rgb(canvas_width, canvas_height, bytes(canvas))
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.stem}.",
            suffix=".png",
            dir=output_path.parent,
            delete=False,
        ) as handle:
            handle.write(png_bytes)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    width, height, size_bytes, sha256 = raw_png_metadata(output_path)
    return {
        "mode": "deterministic_contact_sheet_first",
        "path": str(output_path),
        "sha256": sha256,
        "dimensions": [width, height],
        "size_bytes": size_bytes,
        "styles": styles,
        "individual_open_policy": "suspected_collision_or_craft_red_flag_only",
    }


def fast8_delivery_is_terminal(state: dict[str, Any]) -> bool:
    """Return whether the candidate set has crossed a user-facing delivery boundary."""

    if state.get("status") == "completed":
        return True
    scheduler = state.get("scheduler") or {}
    if scheduler.get("phase") == "completed":
        return True
    timing = state.get("timing") or {}
    if timing.get("formal_overview_completed_at") or timing.get(
        "process_completed_at"
    ):
        return True
    overview = state.get("overview") or {}
    if overview.get("final_path"):
        return True
    page_id = str(state.get("anchor_page_id"))
    styles = state.get("styles") or {}
    return any(
        (((styles.get(style) or {}).get("pages") or {}).get(page_id) or {}).get(
            "status"
        )
        in {"candidate_ready", "accepted"}
        for style in QUICK_STYLES
    )


def fast8_precompletion_errors(
    state: dict[str, Any], state_path: Path
) -> list[str]:
    """Return deterministic blockers before a Fast8 run is sealed completed."""

    errors: list[str] = []
    timing = state.get("timing") or {}
    overview = state.get("overview") or {}
    if not timing.get("formal_overview_completed_at"):
        errors.append("缺少 formal_overview_completed_at")
    overview_path = overview.get("final_path")
    if not isinstance(overview_path, str) or not Path(overview_path).is_file():
        errors.append("正式总览图尚未落盘")
    review = state.get("diversity_review") or {}
    if review.get("status") not in {"pass", "best_effort"}:
        errors.append("差异裁判尚未收口")
    try:
        current_set_sha = fast8_candidate_set_sha256(fast8_candidate_manifest(state))
    except SystemExit as exc:
        errors.append(str(exc))
    else:
        if review.get("final_candidate_set_sha256") != current_set_sha:
            errors.append("最终差异报告未绑定当前 A-H 候选")
    page_id = str(state.get("anchor_page_id"))
    for style in QUICK_STYLES:
        record = page_record(state, style, page_id)
        errors.extend(
            completed_quick_candidate_errors(
                record,
                f"style_{style}/{page_id}",
                allow_targeted_anchor_repair=True,
            )
        )
        style_state = (state.get("styles") or {}).get(style) or {}
        if style_state.get("workflow_status") != "ready_for_overview":
            errors.append(f"style_{style}.workflow_status 尚未 ready_for_overview")
    return errors


def fast8_pending_diversity_replacements(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return queued, active, or recovering Fast8 replacement image actions."""

    scheduler = state.get("scheduler") or {}
    return [
        item
        for item in (
            (scheduler.get("ready_queue") or [])
            + (scheduler.get("active_actions") or [])
            + (scheduler.get("recovery_queue") or [])
        )
        if isinstance(item, dict) and item.get("diversity_replacement") is True
    ]


def fast8_contract_versions(state: dict[str, Any]) -> tuple[int, int, str]:
    """Return the versioned Fast8 policy, Judge contract, and Judge scope."""

    policy_version = (state.get("fast8_candidate_policy") or {}).get("version")
    if policy_version not in {
        LEGACY_FAST8_CANDIDATE_POLICY_VERSION,
        CURRENT_FAST8_CANDIDATE_POLICY_VERSION,
    }:
        raise SystemExit("Fast8 候选策略版本无效")
    judge_version = (
        LEGACY_FAST8_JUDGE_CONTRACT_VERSION
        if policy_version == LEGACY_FAST8_CANDIDATE_POLICY_VERSION
        else CURRENT_FAST8_JUDGE_CONTRACT_VERSION
    )
    expected_scope = FAST8_JUDGE_SCOPES[judge_version]
    review = state.get("diversity_review") or {}
    recorded_version = review.get("contract_version")
    if recorded_version not in {None, judge_version}:
        raise SystemExit("Fast8 候选策略与 Judge 合同版本不一致")
    recorded_scope = review.get("scope")
    if recorded_scope not in {None, expected_scope}:
        raise SystemExit("Fast8 候选策略与 Judge scope 不一致")
    return int(policy_version), judge_version, expected_scope


def fast8_report_template_for_job(job: dict[str, Any]) -> dict[str, Any]:
    """Return the exact report skeleton a lightweight Judge must fill."""

    template: dict[str, Any] = {
        "diversity_judge_contract_version": job[
            "diversity_judge_contract_version"
        ],
        "review_job_sha256": "__FROM_CHECK_FAST8_JUDGE_JOB__",
        "candidate_set_sha256": job["candidate_set_sha256"],
        "decision": None,
        "high_confidence": False,
        "replacement_styles": [],
        "replacement_briefs": {},
        "collision_groups": [],
        "summary": "",
    }
    if job["diversity_judge_contract_version"] == (
        CURRENT_FAST8_JUDGE_CONTRACT_VERSION
    ):
        template["craft_red_flags"] = []
    if "integrated_global_chrome_check" in job:
        template["global_chrome"] = {
            "decision": None,
            "failed_styles": [],
            "unknown_styles": [],
            "summary": "",
        }
    if "integrated_required_asset_usage_check" in job:
        template["required_assets"] = {
            "decision": None,
            "failed_styles": [],
            "unknown_styles": [],
            "summary": "",
        }
    return template


def command_prepare_fast8_diversity_review(args: argparse.Namespace) -> None:
    """Create an adaptive Fast8 review without serially replaying the same set."""

    project_dir = Path(args.project_dir).resolve()
    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("prepare-fast8-diversity-review 只适用于 fast_8x1_diverse")
    policy_version, judge_contract_version, judge_scope = fast8_contract_versions(state)
    requested_checkpoint = int(args.checkpoint)
    if requested_checkpoint not in {4, 6, 8}:
        raise SystemExit("Fast8 差异检查 checkpoint 只允许 4、6、8")
    enforce_source_guard(state_path, state, action="targeted_candidate_repair")
    pending_replacements = fast8_pending_diversity_replacements(state)
    if pending_replacements:
        raise SystemExit("Fast8 差异替代尚未全部结算或恢复，不得创建任何新 checkpoint")
    page_id = str(state.get("anchor_page_id"))
    ready_records = [
        (style, page_record(state, style, page_id))
        for style in QUICK_STYLES
        if page_record(state, style, page_id).get("selected_source")
    ]
    if len(ready_records) < requested_checkpoint:
        raise SystemExit(
            f"checkpoint={requested_checkpoint} 至少需要 {requested_checkpoint} 张候选，"
            f"当前只有 {len(ready_records)} 张"
        )

    def ready_order(item: tuple[str, dict[str, Any]]) -> tuple[float, int]:
        style, record = item
        value = record.get("file_validated_at") or record.get("tool_finished_at")
        try:
            occurred = parse_time(value) if isinstance(value, str) else float("inf")
        except (TypeError, ValueError):
            occurred = float("inf")
        return occurred, QUICK_STYLES.index(style)

    ready_styles = [style for style, _ in sorted(ready_records, key=ready_order)]
    checkpoint = requested_checkpoint
    if len(ready_styles) >= 8:
        checkpoint = 8
    elif requested_checkpoint == 4 and len(ready_styles) >= 6:
        checkpoint = 6

    review = state.setdefault("diversity_review", {})
    if review.get("status") == "reviewing":
        latest_path_value = review.get("latest_job_path")
        latest_entry = next(
            (
                item
                for item in reversed(review.get("review_jobs") or [])
                if isinstance(item, dict)
                and item.get("job_path") == latest_path_value
            ),
            None,
        )
        if not isinstance(latest_entry, dict):
            raise SystemExit("Fast8 reviewing 状态缺少已登记的 latest review job")
        latest_path = require_formal_file_path(
            latest_entry.get("job_path"), "Fast8 待应用差异任务"
        )
        require_path_within(
            latest_path,
            project_dir / "visual_qa_jobs",
            "Fast8 待应用差异任务",
        )
        latest_sha = file_sha256(latest_path)
        if latest_sha != latest_entry.get("job_sha256"):
            raise SystemExit("Fast8 待应用差异任务 SHA-256 已变化")
        latest_job = read_json(latest_path)
        latest_styles = (
            list(QUICK_STYLES)
            if int(latest_job.get("full_candidate_count") or 0) == 8
            else [
                str(item.get("style"))
                for item in latest_job.get("candidates") or []
                if isinstance(item, dict) and item.get("style")
            ]
        )
        current_pending_sha = fast8_candidate_set_sha256(
            fast8_candidate_manifest(state, styles=latest_styles)
        )
        if current_pending_sha != latest_job.get("candidate_set_sha256"):
            raise SystemExit("Fast8 待应用差异任务已过期；不得静默创建另一份任务")
        print(
            json.dumps(
                {
                    "status": "already_prepared",
                    "review_job": str(latest_path),
                    "review_job_sha256": latest_sha,
                    "candidate_set_sha256": current_pending_sha,
                    "review_kind": latest_job.get("review_kind"),
                    "requested_checkpoint": requested_checkpoint,
                    "checkpoint": latest_job.get("checkpoint"),
                    "candidate_count": latest_job.get("candidate_count"),
                },
                ensure_ascii=False,
            )
        )
        return
    replacement_rounds_used = int(review.get("replacement_rounds_used") or 0)
    review_kind = "incremental"
    review_styles = ready_styles[:checkpoint]
    full_manifest: list[dict[str, Any]] | None = None
    base_report: dict[str, Any] | None = None
    fallback_reason: str | None = None
    if checkpoint == 8:
        full_manifest = fast8_candidate_manifest(state)
        review_kind = (
            "delta_recheck"
            if replacement_rounds_used >= 1 and review.get("status") == "recheck_required"
            else "final_initial"
        )
        if review_kind == "delta_recheck":
            base_report = next(
                (
                    item
                    for item in reversed(review.get("reports") or [])
                    if isinstance(item, dict) and item.get("decision") == "replace"
                ),
                None,
            )
            replacement_styles = set(review.get("replacement_styles") or [])
            focus_styles: set[str] = set()
            covered_replacements: set[str] = set()
            base_path: Path | None = None
            if not isinstance(base_report, dict):
                fallback_reason = "base_replace_report_missing"
            else:
                try:
                    base_path = require_formal_file_path(
                        base_report.get("report_path"), "基础差异报告"
                    )
                    require_path_within(
                        base_path,
                        project_dir / "visual_qa_jobs" / "results",
                        "基础差异报告",
                    )
                    if file_sha256(base_path) != base_report.get("report_sha256"):
                        raise SystemExit("基础差异报告 SHA-256 已变化")
                except SystemExit:
                    fallback_reason = "base_replace_report_unavailable_or_changed"
            if fallback_reason is None:
                for group in (base_report or {}).get("collision_groups") or []:
                    group_styles = (
                        set(group.get("styles") or [])
                        if isinstance(group, dict)
                        else set()
                    )
                    group_styles &= set(QUICK_STYLES)
                    affected = group_styles & replacement_styles
                    if affected and len(group_styles) >= 2:
                        focus_styles.update(group_styles)
                        covered_replacements.update(affected)
                if judge_contract_version == CURRENT_FAST8_JUDGE_CONTRACT_VERSION:
                    for flag in (base_report or {}).get("craft_red_flags") or []:
                        flag_style = (
                            str(flag.get("style"))
                            if isinstance(flag, dict) and flag.get("style")
                            else ""
                        )
                        if flag_style in replacement_styles:
                            focus_styles.add(flag_style)
                            covered_replacements.add(flag_style)
                if (
                    not replacement_styles
                    or covered_replacements != replacement_styles
                    or not focus_styles
                ):
                    fallback_reason = (
                        "collision_group_scope_incomplete"
                        if judge_contract_version
                        == LEGACY_FAST8_JUDGE_CONTRACT_VERSION
                        else "review_evidence_scope_incomplete"
                    )
            if fallback_reason is not None:
                review_kind = "final_recheck_fallback"
                review_styles = list(QUICK_STYLES)
            else:
                review_styles = [style for style in QUICK_STYLES if style in focus_styles]
        else:
            review_styles = list(QUICK_STYLES)

    manifest = fast8_candidate_manifest(state, styles=review_styles)
    candidate_set_sha = fast8_candidate_set_sha256(
        full_manifest if full_manifest is not None else manifest
    )
    if review.get("status") in {"pass", "best_effort"}:
        if review.get("final_candidate_set_sha256") != candidate_set_sha:
            raise SystemExit(
                "Fast8 差异门已终态但候选集合发生变化；不得静默重新开启检查"
            )
        print(
            json.dumps(
                {
                    "status": "already_complete",
                    "decision": review.get("status"),
                    "candidate_set_sha256": candidate_set_sha,
                    "review_job": review.get("latest_job_path"),
                },
                ensure_ascii=False,
            )
        )
        return
    if fast8_delivery_is_terminal(state):
        raise SystemExit("Fast8 已进入候选交付或流程完成状态，不得重新开启差异检查")
    existing_report = next(
        (
            item
            for item in reversed(review.get("reports") or [])
            if isinstance(item, dict)
            and item.get("review_kind") == review_kind
            and item.get("candidate_set_sha256") == candidate_set_sha
        ),
        None,
    )
    if isinstance(existing_report, dict):
        print(
            json.dumps(
                {
                    "status": "already_reviewed",
                    "decision": existing_report.get("decision"),
                    "candidate_set_sha256": candidate_set_sha,
                    "review_kind": review_kind,
                    "review_job": review.get("latest_job_path"),
                    "report_path": existing_report.get("report_path"),
                },
                ensure_ascii=False,
            )
        )
        return
    existing_job = next(
        (
            item
            for item in reversed(review.get("review_jobs") or [])
            if isinstance(item, dict)
            and item.get("review_kind") == review_kind
            and item.get("candidate_set_sha256") == candidate_set_sha
        ),
        None,
    )
    if isinstance(existing_job, dict):
        existing_job_path = Path(str(existing_job.get("job_path") or ""))
        if (
            existing_job_path.is_absolute()
            and existing_job_path.is_file()
            and file_sha256(existing_job_path) == existing_job.get("job_sha256")
        ):
            print(
                json.dumps(
                    {
                        "status": "already_prepared",
                        "review_job": str(existing_job_path),
                        "review_job_sha256": existing_job.get("job_sha256"),
                        "candidate_set_sha256": candidate_set_sha,
                        "review_kind": review_kind,
                        "requested_checkpoint": requested_checkpoint,
                        "checkpoint": checkpoint,
                        "candidate_count": len(manifest),
                    },
                    ensure_ascii=False,
                )
            )
            return
    replacement_count = int(review.get("replacement_count") or 0)
    job_sequence = len(review.get("review_jobs") or []) + 1
    job_stem = (
        f"fast8_diversity_{checkpoint}_{review_kind}_"
        f"{job_sequence:02d}_{candidate_set_sha[:12]}"
    )
    job = {
        "diversity_judge_contract_version": judge_contract_version,
        "mode": "qa_fast8_diversity_stream",
        "scope": judge_scope,
        "run_mode": FAST8_MODE,
        "run_id": state.get("run_id"),
        "page_id": page_id,
        "review_kind": review_kind,
        "requested_checkpoint": requested_checkpoint,
        "checkpoint": checkpoint,
        "candidate_count": len(manifest),
        "current_candidate_count": len(ready_styles),
        "full_candidate_count": len(full_manifest) if full_manifest is not None else None,
        "candidate_set_sha256": candidate_set_sha,
        "candidates": manifest,
        "replacement_budget_remaining": max(0, 2 - replacement_count),
        "decision_rules": {
            "compare_axes": [
                "reading_entry",
                "dominant_layout_topology",
                "information_organization",
                "visual_emphasis",
                "image_text_treatment",
                "semantic_emphasis",
                "attention_competition",
                "edge_pressure_and_pause",
            ],
            "checkpoint_4_or_6": "continue_only",
            "checkpoint_8": "pass_or_replace",
            "replace_only_material_collision": True,
            "same_palette_alone_is_not_collision": True,
            "subjective_beauty_is_not_collision": True,
            "judge_actual_pixels_not_planned_direction_metadata": True,
            "shared_page_wide_skeleton_requires_authorization_check": True,
            "authorized_shared_structure_is_not_collision": True,
            "repeated_hero_bottom_band_is_collision_when_same_reading_path": True,
            "max_replacements": 2,
        },
        "prohibited_claims": [
            "content_gate",
            "spatial_gate",
            "craft_gate",
            "full_visual_qa",
        ],
        "review_execution_policy": {
            "preferred_model": "gpt-5.6-terra",
            "reasoning_effort": "low",
            "fork_turns": "none",
            "primary_input": "deterministic_contact_sheet",
            "max_primary_view_calls": 1,
            "open_individual_only_on_suspicion": True,
            "soft_timeout_seconds": 180,
            "retry_limit": 0,
            "timeout_recovery": "same_session_report_only",
            "output_only_grace_seconds": 45,
            "never_spawn_second_full_visual_judge": True,
        },
        "judge_runtime_contract": {
            "required_model": FAST8_JUDGE_REQUIRED_MODEL,
            "required_reasoning_effort": FAST8_JUDGE_REQUIRED_REASONING,
            "required_fork_turns": FAST8_JUDGE_REQUIRED_FORK_TURNS,
            "session_binding_required": True,
        },
        "report_constraints": {
            "summary_max_characters": 300,
            "return_json_only": True,
        },
    }
    constraint_job_path = project_dir / "style_jobs" / "style_A.json"
    if constraint_job_path.is_file():
        constraint_job = read_json(constraint_job_path)
        constraint_page = constraint_job.get("anchor_page") or {}
        authorized_roles = []
        for item in constraint_job.get("required_assets") or []:
            role = item.get("role") if isinstance(item, dict) else None
            if isinstance(role, str) and role.strip():
                authorized_roles.append(role.strip())
        job["diversity_constraint_context"] = {
            "relationship_thesis": constraint_page.get("relationship_thesis"),
            "prompt_user_constraints": list(
                constraint_page.get("prompt_user_constraints") or []
            ),
            "semantic_invariants": list(
                constraint_page.get("semantic_invariants") or []
            ),
            "required_asset_roles": list(dict.fromkeys(authorized_roles)),
            "asset_authorization_scope": (
                "Required asset roles authorize presence only. They do not authorize shared "
                "placement, scale, hero treatment, bottom bands, or page-wide topology unless "
                "an explicit user or semantic constraint says so."
            ),
            "policy": (
                "Similarity explicitly required by these user, semantic, or reference "
                "constraints is authorized shared structure and is not a collision by itself. "
                "Judge only the remaining observable choice dimensions."
            ),
        }
    if checkpoint == 8:
        usage_checks: list[dict[str, Any]] = []
        for style in review_styles:
            style_job_path = project_dir / "style_jobs" / f"style_{style}.json"
            if not style_job_path.is_file():
                continue
            style_job = read_json(style_job_path)
            items: list[dict[str, str]] = []
            for item in style_job.get("required_assets") or []:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip()
                use = str(item.get("use") or "").strip()
                if not use or normalized_asset_role_key(role) in EVIDENCE_ASSET_ROLES:
                    continue
                path_value = str(item.get("path") or "").strip()
                if not path_value:
                    continue
                items.append(
                    {
                        "path": path_value,
                        "role": role or "required_asset",
                        "use": use,
                    }
                )
            if items:
                usage_checks.append({"style": style, "items": items})
        if usage_checks:
            job["integrated_required_asset_usage_check"] = {
                "candidate_set_sha256": candidate_set_sha,
                "candidates": usage_checks,
                "evaluation_rule": (
                    "Evaluate each asset use only when its stated condition is visibly triggered. "
                    "If the condition is not triggered, that item passes. A title-area logo does "
                    "not satisfy a separate object- or surface-placement requirement."
                ),
                "report_schema": {
                    "decision": "pass|needs_inspection|fail",
                    "failed_styles": [],
                    "unknown_styles": [],
                    "summary_max_characters": 240,
                },
            }
    if judge_contract_version == CURRENT_FAST8_JUDGE_CONTRACT_VERSION:
        job["decision_rules"].update(
            {
                "minimum_craft_filter": "severe_objective_regression_only",
                "craft_replacement_requires_distinct_issue_types": 2,
                "mild_card_feeling_alone_is_not_craft_failure": True,
                "style_reference_mismatch_alone_is_not_craft_failure": True,
                "severe_crowding_requires_two_observable_issue_types": True,
            }
        )
        job["allowed_craft_red_flag_types"] = sorted(
            FAST8_CRAFT_RED_FLAG_TYPES
        )
    chrome_review = state.get("global_chrome_review") or {}
    if (
        checkpoint == 8
        and chrome_review.get("required") is True
        and chrome_review.get("review_mode") == "integrated_fast8_judge"
    ):
        contract_path, chrome_contract, chrome_contract_sha = read_global_chrome_contract(
            chrome_review.get("contract_path") or state.get("global_chrome_contract_path"),
            verify_authorization_source=False,
        )
        if chrome_contract_sha != chrome_review.get("contract_sha256"):
            raise SystemExit("Fast8 集成标题检查绑定的合同 SHA-256 已变化")
        deck = chrome_contract.get("deck_title_system") or {}
        job["integrated_global_chrome_check"] = {
            "contract_version": GLOBAL_CHROME_REVIEW_CONTRACT_VERSION,
            "contract_path": str(contract_path),
            "contract_sha256": chrome_contract_sha,
            "candidate_set_sha256": candidate_set_sha,
            "match_mode": "approximate",
            "pixel_exact_match_required": False,
            "fail_only_on_clear_outline_deviation": True,
            "checks": list(deck.get("qa_checks") or []),
            "authorized_requirements": {
                "logo_required": bool((deck.get("logo") or {}).get("required")),
                "main_title_required": bool(
                    (deck.get("main_title") or {}).get("required")
                ),
                "subtitle_policy": deck.get("subtitle_policy"),
            },
            "report_schema": {
                "decision": "pass|needs_inspection|fail",
                "failed_styles": [],
                "unknown_styles": [],
                "summary_max_characters": 240,
            },
        }
        job["report_constraints"]["integrated_global_chrome_required"] = True
    if review_kind == "delta_recheck":
        assert isinstance(base_report, dict)
        base_path = require_formal_file_path(
            base_report.get("report_path"), "基础差异报告"
        )
        if file_sha256(base_path) != base_report.get("report_sha256"):
            raise SystemExit("Fast8 delta recheck 的基础报告 SHA-256 已变化")
        job["base_report_path"] = str(base_path)
        job["base_report_sha256"] = base_report["report_sha256"]
        job["base_candidate_set_sha256"] = base_report.get("candidate_set_sha256")
        job["changed_styles"] = sorted(review.get("replacement_styles") or [])
        job["prior_collision_groups"] = base_report.get("collision_groups") or []
        if judge_contract_version == CURRENT_FAST8_JUDGE_CONTRACT_VERSION:
            job["prior_craft_red_flags"] = base_report.get("craft_red_flags") or []
    elif review_kind == "final_recheck_fallback":
        job["fallback_reason"] = fallback_reason or "delta_scope_not_safe"
        job["changed_styles"] = sorted(review.get("replacement_styles") or [])
    report_output_path = (
        project_dir
        / "visual_qa_jobs"
        / "results"
        / f"{job_stem}_report.json"
    ).resolve()
    job["report_output_path"] = str(report_output_path)
    job["report_template"] = fast8_report_template_for_job(job)
    job["report_constraints"]["exact_top_level_keys"] = sorted(
        job["report_template"]
    )
    review_input = build_fast8_review_contact_sheet(
        project_dir,
        manifest,
        project_dir / "visual_qa_jobs" / "inputs" / f"{job_stem}_contact_sheet.png",
    )
    review_input["candidate_set_sha256"] = candidate_set_sha
    job["review_input"] = review_input
    job_path = project_dir / "visual_qa_jobs" / f"{job_stem}.json"
    write_idempotent(job_path, job)
    job_sha = file_sha256(job_path)
    entry = {
        "checkpoint": checkpoint,
        "requested_checkpoint": requested_checkpoint,
        "review_kind": review_kind,
        "candidate_set_sha256": candidate_set_sha,
        "candidate_count": len(manifest),
        "job_path": str(job_path),
        "job_sha256": job_sha,
        "prepared_at": now_iso(),
    }
    jobs = review.setdefault("review_jobs", [])
    if not any(
        isinstance(item, dict)
        and item.get("job_path") == entry["job_path"]
        and item.get("job_sha256") == job_sha
        for item in jobs
    ):
        jobs.append(entry)
    review["status"] = "reviewing"
    review["latest_job_path"] = str(job_path)
    atomic_write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "ok",
                "review_job": str(job_path),
                "review_job_sha256": job_sha,
                "candidate_set_sha256": candidate_set_sha,
                "review_kind": review_kind,
                "requested_checkpoint": requested_checkpoint,
                "checkpoint": checkpoint,
                "candidate_count": len(manifest),
            },
            ensure_ascii=False,
        )
    )


def command_check_fast8_judge_job(args: argparse.Namespace) -> None:
    """Validate a Judge job and return its machine-bound report contract."""

    state_path = Path(args.state).expanduser().resolve()
    job_path = Path(args.review_job).expanduser().resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("check-fast8-judge-job 只适用于 fast_8x1_diverse")
    project_dir = project_dir_for_state(state_path, state)
    require_path_within(job_path, project_dir / "visual_qa_jobs", "Fast8 Judge job")
    review = state.get("diversity_review") or {}
    entry = next(
        (
            item
            for item in reversed(review.get("review_jobs") or [])
            if isinstance(item, dict) and item.get("job_path") == str(job_path)
        ),
        None,
    )
    if not isinstance(entry, dict):
        raise SystemExit("Fast8 Judge job 未登记到正式状态")
    job_sha = file_sha256(job_path)
    if entry.get("job_sha256") != job_sha:
        raise SystemExit("Fast8 Judge job SHA-256 与正式状态不一致")
    if review.get("latest_job_path") != str(job_path):
        raise SystemExit("Fast8 Judge job 不是当前 latest job")
    job = read_json(job_path)
    expected_template = fast8_report_template_for_job(job)
    if job.get("report_template") != expected_template:
        raise SystemExit("Fast8 Judge job 的 report_template 无效")
    output_path_value = job.get("report_output_path")
    if not isinstance(output_path_value, str):
        raise SystemExit("Fast8 Judge job 缺少 report_output_path")
    output_path = Path(output_path_value).expanduser()
    if not output_path.is_absolute():
        raise SystemExit("Fast8 Judge report_output_path 必须是绝对路径")
    output_path = output_path.resolve()
    require_path_within(
        output_path,
        project_dir / "visual_qa_jobs" / "results",
        "Fast8 Judge report_output_path",
    )
    review_input = job.get("review_input") or {}
    contact_path = require_formal_file_path(
        review_input.get("path"), "Fast8 Judge contact sheet"
    )
    if file_sha256(contact_path) != review_input.get("sha256"):
        raise SystemExit("Fast8 Judge contact sheet SHA-256 已变化")
    template = dict(expected_template)
    template["review_job_sha256"] = job_sha
    print(
        json.dumps(
            {
                "status": "pass",
                "review_job": str(job_path),
                "review_job_sha256": job_sha,
                "candidate_set_sha256": job.get("candidate_set_sha256"),
                "contact_sheet_path": str(contact_path),
                "contact_sheet_sha256": review_input.get("sha256"),
                "report_output_path": str(output_path),
                "report_template": template,
                "review_execution_policy": job.get("review_execution_policy"),
                "judge_runtime_contract": job.get("judge_runtime_contract"),
            },
            ensure_ascii=False,
        )
    )


def command_bind_fast8_judge_session(args: argparse.Namespace) -> None:
    """Bind the actual isolated Judge session and its runtime before report apply."""

    state_path = Path(args.state).expanduser().resolve()
    job_path = Path(args.review_job).expanduser().resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("bind-fast8-judge-session 只适用于 fast_8x1_diverse")
    project_dir = project_dir_for_state(state_path, state)
    require_path_within(job_path, project_dir / "visual_qa_jobs", "Fast8 Judge job")
    if not job_path.is_file():
        raise SystemExit("Fast8 Judge job 不存在")
    job_sha = file_sha256(job_path)
    review = state.setdefault("diversity_review", {})
    entry = next(
        (
            item
            for item in reversed(review.get("review_jobs") or [])
            if isinstance(item, dict)
            and item.get("job_path") == str(job_path)
            and item.get("job_sha256") == job_sha
        ),
        None,
    )
    if not isinstance(entry, dict):
        raise SystemExit("Fast8 Judge job 未登记到正式状态或 SHA-256 已变化")
    if review.get("latest_job_path") != str(job_path):
        raise SystemExit("只能绑定当前 latest Fast8 Judge job")
    job = read_json(job_path)
    contract = job.get("judge_runtime_contract") or {}
    required = {
        "model": contract.get("required_model"),
        "reasoning_effort": contract.get("required_reasoning_effort"),
        "fork_turns": contract.get("required_fork_turns"),
    }
    actual = {
        "model": str(args.model),
        "reasoning_effort": str(args.reasoning_effort),
        "fork_turns": str(args.fork_turns),
    }
    if contract.get("session_binding_required") is not True or actual != required:
        raise SystemExit(
            "Fast8 Judge 运行时不符合正式合同："
            f"required={required} actual={actual}"
        )
    session_id = str(args.session_id).strip().lower()
    if CODEX_AGENT_THREAD_ID_RE.fullmatch(session_id) is None:
        raise SystemExit("Fast8 Judge session 不是合法 Agent UUID")
    timestamp = args.timestamp or now_iso()
    binding = {
        "review_job_path": str(job_path),
        "review_job_sha256": job_sha,
        "session_id": session_id,
        **actual,
        "bound_at": timestamp,
    }
    existing = entry.get("judge_runtime_binding")
    if isinstance(existing, dict):
        comparable = {key: existing.get(key) for key in binding if key != "bound_at"}
        expected = {key: value for key, value in binding.items() if key != "bound_at"}
        if comparable != expected:
            raise SystemExit("Fast8 Judge job 已绑定不同 session 或运行时")
        print(json.dumps({"status": "already_bound", **existing}, ensure_ascii=False))
        return
    entry["judge_runtime_binding"] = binding
    review.setdefault("judge_runtime_bindings", []).append(binding)
    append_event(
        state,
        "fast8_judge_session_bound",
        timestamp,
        details={
            "review_job_sha256": job_sha,
            "session_id": session_id,
            **actual,
        },
    )
    atomic_write_json(state_path, state)
    print(json.dumps({"status": "ok", **binding}, ensure_ascii=False))


def command_self_bind_fast8_judge_session(args: argparse.Namespace) -> None:
    """Bind the sole Judge from its trusted Codex runtime environment."""

    session_id = str(os.environ.get("CODEX_THREAD_ID") or "").strip().lower()
    if CODEX_AGENT_THREAD_ID_RE.fullmatch(session_id) is None:
        raise SystemExit("运行环境缺少合法 CODEX_THREAD_ID，禁止执行 Fast8 Judge")
    state_path = Path(args.state).expanduser().resolve()
    lock_path = state_path.with_suffix(state_path.suffix + ".judge-bind.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                command_bind_fast8_judge_session(
                    argparse.Namespace(
                        state=str(state_path),
                        review_job=str(Path(args.review_job).expanduser().resolve()),
                        session_id=session_id,
                        model=str(args.model),
                        reasoning_effort=str(args.reasoning_effort),
                        fork_turns=str(args.fork_turns),
                        timestamp=getattr(args, "timestamp", None),
                    )
                )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    result = json.loads(captured.getvalue())
    result["binding_source"] = "judge_runtime_environment"
    print(json.dumps(result, ensure_ascii=False))


def command_await_fast8_judge_job(args: argparse.Namespace) -> None:
    """Wait briefly for the sole final Judge job, then atomically claim it.

    The isolated Judge can be created while A-H are still in flight.  This
    overlaps Agent cold start with ImageGen without creating a partial contact
    sheet or permitting any visual decision before the complete job exists.
    """

    state_path = Path(args.state).expanduser().resolve()
    wait_seconds = float(args.wait_seconds)
    poll_interval = float(args.poll_interval)
    if wait_seconds < 0 or wait_seconds > 60:
        raise SystemExit("--wait-seconds 必须在 0-60 之间")
    if poll_interval < 0.2 or poll_interval > 10:
        raise SystemExit("--poll-interval 必须在 0.2-10 之间")
    session_id = str(os.environ.get("CODEX_THREAD_ID") or "").strip().lower()
    if CODEX_AGENT_THREAD_ID_RE.fullmatch(session_id) is None:
        raise SystemExit("运行环境缺少合法 CODEX_THREAD_ID，禁止等待 Fast8 Judge job")
    actual = {
        "model": str(args.model),
        "reasoning_effort": str(args.reasoning_effort),
        "fork_turns": str(args.fork_turns),
    }
    required = {
        "model": FAST8_JUDGE_REQUIRED_MODEL,
        "reasoning_effort": FAST8_JUDGE_REQUIRED_REASONING,
        "fork_turns": FAST8_JUDGE_REQUIRED_FORK_TURNS,
    }
    if actual != required:
        raise SystemExit(
            "Fast8 Judge standby 运行时不符合正式合同："
            f"required={required} actual={actual}"
        )

    started = time.monotonic()
    deadline = started + wait_seconds
    while True:
        state = read_json(state_path)
        if state.get("run_mode") != FAST8_MODE:
            raise SystemExit("await-fast8-judge-job 只适用于 fast_8x1_diverse")
        project_dir = project_dir_for_state(state_path, state)
        review = state.get("diversity_review") or {}
        latest_path_value = review.get("latest_job_path")
        if review.get("status") == "reviewing" and isinstance(
            latest_path_value, str
        ):
            job_path = Path(latest_path_value).expanduser()
            if job_path.is_absolute():
                job_path = job_path.resolve()
                require_path_within(
                    job_path,
                    project_dir / "visual_qa_jobs",
                    "Fast8 standby Judge job",
                )
                if job_path.is_file():
                    bind_output = io.StringIO()
                    with contextlib.redirect_stdout(bind_output):
                        command_self_bind_fast8_judge_session(
                            argparse.Namespace(
                                state=str(state_path),
                                review_job=str(job_path),
                                **actual,
                                timestamp=getattr(args, "timestamp", None),
                            )
                        )
                    check_output = io.StringIO()
                    with contextlib.redirect_stdout(check_output):
                        command_check_fast8_judge_job(
                            argparse.Namespace(
                                state=str(state_path),
                                review_job=str(job_path),
                            )
                        )
                    binding = json.loads(bind_output.getvalue())
                    checked = json.loads(check_output.getvalue())
                    print(
                        json.dumps(
                            {
                                **checked,
                                "status": "ready",
                                "waited_seconds": round(time.monotonic() - started, 3),
                                "judge_runtime_binding": binding,
                            },
                            ensure_ascii=False,
                        )
                    )
                    return
        now = time.monotonic()
        if now >= deadline:
            print(
                json.dumps(
                    {
                        "status": "waiting",
                        "waited_seconds": round(now - started, 3),
                        "retry_same_session": True,
                    },
                    ensure_ascii=False,
                )
            )
            return
        time.sleep(min(poll_interval, max(0.0, deadline - now)))


def fast8_existing_prompt_fingerprints(project_dir: Path) -> set[str]:
    fingerprints: set[str] = set()
    paths = list((project_dir / "style_jobs").glob("style_*.json"))
    paths.extend((project_dir / "style_jobs" / "repair_jobs").glob("*.json"))
    for path in paths:
        try:
            job = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        value = job.get("imagegen_prompt_fingerprint")
        if isinstance(value, str) and value:
            fingerprints.add(value)
    return fingerprints


def validate_fast8_craft_red_flags(
    raw_flags: Any, job_styles: list[str]
) -> tuple[list[dict[str, Any]], set[str]]:
    """Validate the deliberately narrow Fast8 v2 minimum-craft evidence."""

    if not isinstance(raw_flags, list) or len(raw_flags) > 2:
        raise SystemExit("Fast8 craft_red_flags 必须是最多两项的数组")
    normalized: list[dict[str, Any]] = []
    styles: set[str] = set()
    for index, flag in enumerate(raw_flags):
        if not isinstance(flag, dict) or set(flag) != {
            "style",
            "severity",
            "issue_types",
            "observable_evidence",
        }:
            raise SystemExit(f"craft_red_flags[{index}] 字段无效")
        style = normalize_style(flag.get("style"))
        if style is None or style not in job_styles or style in styles:
            raise SystemExit(
                f"craft_red_flags[{index}].style 必须是本次受检且互不重复的席位"
            )
        if flag.get("severity") != "severe":
            raise SystemExit(
                f"craft_red_flags[{index}].severity 只允许 severe；"
                "轻度卡片感或主观偏好不能触发替代"
            )
        issue_types = flag.get("issue_types")
        if (
            not isinstance(issue_types, list)
            or not 2 <= len(issue_types) <= 4
            or not all(isinstance(issue, str) for issue in issue_types)
            or len(issue_types) != len(set(issue_types))
            or not set(issue_types).issubset(FAST8_CRAFT_RED_FLAG_TYPES)
        ):
            raise SystemExit(
                f"craft_red_flags[{index}].issue_types 必须包含 2–4 个互异的"
                "严重客观工艺问题类型"
            )
        evidence = flag.get("observable_evidence")
        if (
            not isinstance(evidence, str)
            or not evidence.strip()
            or len(evidence.strip()) > 240
        ):
            raise SystemExit(
                f"craft_red_flags[{index}].observable_evidence 必须是 1–240 字的字符串"
            )
        styles.add(style)
        normalized.append(
            {
                "style": style,
                "severity": "severe",
                "issue_types": list(issue_types),
                "observable_evidence": evidence.strip(),
            }
        )
    return normalized, styles


def create_fast8_replacement_jobs(
    *,
    project_dir: Path,
    state: dict[str, Any],
    styles: list[str],
    briefs: dict[str, Any],
    replacement_basis: dict[str, str],
    report_sha256: str,
    timestamp: str,
) -> list[dict[str, Any]]:
    """创建最多两份新探索任务；不把撞车旧图重新喂给图片模型。"""

    page_id = str(state.get("anchor_page_id"))
    scheduler = state.setdefault("scheduler", {})
    ready = scheduler.setdefault("ready_queue", [])
    active = scheduler.setdefault("active_actions", [])
    used_fingerprints = fast8_existing_prompt_fingerprints(project_dir)
    prepared: list[dict[str, Any]] = []
    for style in styles:
        brief = briefs.get(style) or briefs.get(f"style_{style}")
        if not isinstance(brief, str) or not brief.strip():
            raise SystemExit(f"style_{style} 缺少开放、正向的 replacement_brief")
        brief = brief.strip()
        if len(brief) > 160:
            raise SystemExit(f"style_{style} replacement_brief 超过 160 字")
        if any(
            item.get("style") == style
            and str(item.get("page_id")) == page_id
            and item.get("action") == "repair_anchor"
            for item in ready + active
        ):
            raise SystemExit(f"style_{style} 已有差异替代任务在队列或执行中")
        record = page_record(state, style, page_id)
        if not record.get("selected_source") or not record.get("tool_call_id"):
            raise SystemExit(f"style_{style} 没有可替换的当前候选")
        attempt = int(record.get("attempt_count") or 1) + 1
        if attempt > 3:
            raise SystemExit(f"style_{style} 已达到 Fast8 尝试上限")
        original = read_json(project_dir / "style_jobs" / f"style_{style}.json")
        replacement = dict(original)
        replacement["action"] = "repair_anchor"
        replacement["attempt"] = attempt
        replacement["diversity_replacement"] = {
            "contract_version": (
                CURRENT_FAST8_JUDGE_CONTRACT_VERSION
                if (state.get("fast8_candidate_policy") or {}).get("version")
                == CURRENT_FAST8_CANDIDATE_POLICY_VERSION
                else LEGACY_FAST8_JUDGE_CONTRACT_VERSION
            ),
            "source_candidate": record["selected_source"],
            "source_candidate_sha256": record["source_sha256"],
            "judge_report_sha256": report_sha256,
            "replacement_brief": brief,
            "replacement_basis": replacement_basis.get(
                style, "material_collision"
            ),
            "reuse_source_candidate_as_image_input": False,
        }
        replacement["repair_source"] = record["selected_source"]
        basis = replacement["diversity_replacement"]["replacement_basis"]
        replacement["repair_issue"] = {
            "material_collision": "与候选组合存在高置信度实质同构",
            "minimum_craft_regression": "存在高置信度严重最低工艺退化",
            "material_collision_and_minimum_craft_regression": (
                "同时存在高置信度实质同构与严重最低工艺退化"
            ),
        }.get(basis, "候选组合存在高置信度可观察问题")
        replacement["repair_directive"] = {
            "must_change": [replacement["repair_issue"]],
            "invariants": [
                "全部 display_required 与 display_flexible 内容义务",
                "页面语言、tone、品牌与必要资产角色",
                "本次运行的页级 relationship_thesis",
            ],
            "single_objective": True,
        }
        language = resolve_job_language(replacement)
        use_chinese_control = language.lower().startswith("zh")
        prompt = compile_anchor_imagegen_prompt(replacement)
        legacy_collision_only = (
            replacement["diversity_replacement"]["contract_version"]
            == LEGACY_FAST8_JUDGE_CONTRACT_VERSION
        )
        prompt += (
            (
                "\n\n差异替代探索：" + brief + "。这是新的开放探索起点；"
                + (
                    "保持内容、语言、明暗和资产义务，但主动远离已识别的实质同构。"
                    if legacy_collision_only
                    else (
                        "保持内容、语言、明暗和资产义务，同时解决 Judge 已识别的"
                        "组合冗余或严重工艺退化。"
                    )
                )
                + "不要把说明转换成固定版式或组件清单，也不要复刻旧候选。"
            )
            if use_chinese_control
            else (
                "\n\nDiversity replacement: " + brief + ". Treat this as a new open "
                "exploration point. Preserve content, language, tone, and asset obligations "
                + (
                    "while moving away from the identified material collision. "
                    if legacy_collision_only
                    else (
                        "while resolving the combination redundancy or severe craft regression "
                        "identified by the Judge. "
                    )
                )
                + "Do not turn the "
                "brief into a fixed layout or component list, and do not copy the old candidate."
            )
        )
        prompt = finalize_imagegen_prompt(prompt)
        replacement["imagegen_prompt"] = prompt
        prompt_fingerprint = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if prompt_fingerprint in used_fingerprints:
            raise SystemExit(f"style_{style} 差异替代提示与既有生成提示重复")
        replacement["imagegen_prompt_fingerprint"] = prompt_fingerprint
        used_fingerprints.add(prompt_fingerprint)
        referenced_paths = extract_input_paths(
            (replacement.get("reference_images") or [])
            + (replacement.get("required_assets") or [])
        )
        normalized_paths, manifest = build_input_manifest(referenced_paths)
        replacement["imagegen_referenced_paths"] = normalized_paths
        replacement["imagegen_input_manifest"] = manifest
        replacement["imagegen_input_fingerprint"] = hashlib.sha256(
            json.dumps(
                {"prompt": prompt, "inputs": manifest},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        receipt_path = fast8_worker_receipt_path(
            project_dir, style, page_id, "repair_anchor", attempt
        )
        replacement["worker_receipt"] = {
            "contract_version": FAST8_WORKER_RECEIPT_CONTRACT_VERSION,
            "path": str(receipt_path),
            "required": True,
            "write_after_imagegen_in_same_exec": True,
            "contains_image_payload": False,
        }
        job_path = (
            project_dir
            / "style_jobs"
            / "repair_jobs"
            / f"style_{style}_page_{page_id}_attempt_{attempt}_fast8.json"
        )
        if job_path.exists() and read_json(job_path) != replacement:
            raise SystemExit(f"拒绝覆盖内容不同的既有文件：{job_path}")
        prepared.append(
            {
                "style": style,
                "attempt": attempt,
                "job_path": job_path,
                "job": replacement,
                "incumbent_candidate": incumbent_candidate_snapshot(record),
            }
        )

    # Validate and build the whole replacement batch before any job is written.
    # This prevents a bad second seat from leaving an orphan job for the first.
    for item in prepared:
        item["created_during_apply"] = not item["job_path"].exists()
        write_idempotent(item["job_path"], item["job"])

    jobs: list[dict[str, Any]] = []
    for item in prepared:
        style = item["style"]
        attempt = item["attempt"]
        job_path = item["job_path"]
        queue_item = {
            "style": style,
            "page_id": page_id,
            "action": "repair_anchor",
            "attempt": attempt,
            "diversity_replacement": True,
            "generation_job_path": str(job_path),
            "generation_job_sha256": file_sha256(job_path),
            "incumbent_candidate": item["incumbent_candidate"],
        }
        ready.append(queue_item)
        append_event(
            state,
            "queued",
            timestamp,
            style=style,
            page_id=page_id,
            action="repair_anchor",
            details={
                "source": "apply-fast8-diversity-report",
                "attempt": attempt,
                "diversity_replacement": True,
                "judge_report_sha256": report_sha256,
            },
        )
        jobs.append(
            {
                **queue_item,
                "job_path": str(job_path),
                "created_during_apply": bool(item.get("created_during_apply")),
            }
        )
    return jobs


def command_apply_fast8_diversity_report(args: argparse.Namespace) -> None:
    """校验隔离 Judge 的短报告，并原子批准一次至多两席的差异替代。"""

    project_dir = Path(args.project_dir).resolve()
    state_path = Path(args.state).resolve()
    job_path = Path(args.review_job).resolve()
    report_path = Path(args.report_file).resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("apply-fast8-diversity-report 只适用于 fast_8x1_diverse")
    _, judge_contract_version, judge_scope = fast8_contract_versions(state)
    enforce_source_guard(state_path, state, action="targeted_candidate_repair")
    require_path_within(job_path, project_dir / "visual_qa_jobs", "差异检查任务")
    require_path_within(report_path, project_dir / "visual_qa_jobs" / "results", "差异检查报告")
    job = read_json(job_path)
    report = read_json(report_path)
    report_sha = file_sha256(report_path)
    review = state.setdefault("diversity_review", {})
    reports = review.setdefault("reports", [])
    if any(
        isinstance(item, dict) and item.get("report_sha256") == report_sha
        for item in reports
    ):
        print(
            json.dumps(
                {"status": "already_applied", "report_sha256": report_sha},
                ensure_ascii=False,
            )
        )
        return
    if review.get("status") in {"pass", "best_effort"}:
        raise SystemExit(
            "Fast8 差异门已经终态；只允许精确重放已登记报告，不得应用新决定"
        )
    if fast8_delivery_is_terminal(state):
        raise SystemExit("Fast8 已进入候选交付或流程完成状态，不得应用新的差异决定")
    if fast8_pending_diversity_replacements(state):
        raise SystemExit("Fast8 差异替代尚未全部结算或恢复，不得应用新的差异报告")
    job_sha = file_sha256(job_path)
    registered_job_entry: dict[str, Any] | None = None
    for item in review.get("review_jobs") or []:
        if not isinstance(item, dict):
            continue
        registered_path = item.get("job_path")
        if not isinstance(registered_path, str):
            continue
        try:
            same_path = Path(registered_path).resolve() == job_path
        except OSError:
            same_path = False
        if same_path and item.get("job_sha256") == job_sha:
            registered_job_entry = item
            break
    if not isinstance(registered_job_entry, dict):
        raise SystemExit("差异检查任务路径与 SHA-256 未登记在当前 Fast8 状态中")
    runtime_contract = job.get("judge_runtime_contract")
    if isinstance(runtime_contract, dict) and runtime_contract.get(
        "session_binding_required"
    ) is True:
        binding = registered_job_entry.get("judge_runtime_binding")
        expected_runtime = {
            "model": runtime_contract.get("required_model"),
            "reasoning_effort": runtime_contract.get(
                "required_reasoning_effort"
            ),
            "fork_turns": runtime_contract.get("required_fork_turns"),
        }
        actual_runtime = (
            {
                "model": binding.get("model"),
                "reasoning_effort": binding.get("reasoning_effort"),
                "fork_turns": binding.get("fork_turns"),
            }
            if isinstance(binding, dict)
            else None
        )
        if (
            not isinstance(binding, dict)
            or binding.get("review_job_sha256") != job_sha
            or CODEX_AGENT_THREAD_ID_RE.fullmatch(
                str(binding.get("session_id") or "").lower()
            )
            is None
            or actual_runtime != expected_runtime
        ):
            raise SystemExit(
                "Fast8 Judge 报告缺少合规运行时绑定；先运行 "
                "bind-fast8-judge-session，并确保使用 gpt-5.6-terra / low / none"
            )
    if job.get("diversity_judge_contract_version") != judge_contract_version:
        raise SystemExit("差异检查任务合同版本无效")
    if job.get("mode") != "qa_fast8_diversity_stream" or job.get(
        "scope"
    ) != judge_scope:
        raise SystemExit("差异检查任务 mode/scope 无效")
    if judge_contract_version == CURRENT_FAST8_JUDGE_CONTRACT_VERSION:
        review_input = job.get("review_input")
        if not isinstance(review_input, dict) or review_input.get("mode") != (
            "deterministic_contact_sheet_first"
        ):
            raise SystemExit("Fast8 v2 差异检查任务缺少确定性 contact sheet 输入")
        input_path = require_formal_file_path(
            review_input.get("path"), "Fast8 contact sheet"
        )
        require_path_within(
            input_path,
            project_dir / "visual_qa_jobs" / "inputs",
            "Fast8 contact sheet",
        )
        width, height, size_bytes, input_sha = raw_png_metadata(input_path)
        if (
            input_sha != review_input.get("sha256")
            or [width, height] != review_input.get("dimensions")
            or size_bytes != review_input.get("size_bytes")
            or review_input.get("candidate_set_sha256")
            != job.get("candidate_set_sha256")
        ):
            raise SystemExit("Fast8 contact sheet 元数据、哈希或候选集合绑定已变化")
    if job.get("run_mode") != FAST8_MODE or job.get("run_id") != state.get("run_id"):
        raise SystemExit("差异检查任务不属于当前 Fast8 运行")
    if str(job.get("page_id")) != str(state.get("anchor_page_id")):
        raise SystemExit("差异检查任务页码与当前 Fast8 锚点不一致")
    if report.get("diversity_judge_contract_version") != judge_contract_version:
        raise SystemExit("差异检查报告合同版本无效")
    allowed_report_fields = {
        "diversity_judge_contract_version",
        "review_job_sha256",
        "candidate_set_sha256",
        "decision",
        "high_confidence",
        "replacement_styles",
        "replacement_briefs",
        "collision_groups",
        "summary",
    }
    if judge_contract_version == CURRENT_FAST8_JUDGE_CONTRACT_VERSION:
        allowed_report_fields.add("craft_red_flags")
    integrated_chrome = job.get("integrated_global_chrome_check")
    if isinstance(integrated_chrome, dict):
        allowed_report_fields.add("global_chrome")
    integrated_required_assets = job.get("integrated_required_asset_usage_check")
    if isinstance(integrated_required_assets, dict):
        allowed_report_fields.add("required_assets")
    unexpected_report_fields = set(report) - allowed_report_fields
    if unexpected_report_fields:
        raise SystemExit(
            "Fast8 差异报告包含未授权字段："
            + ", ".join(sorted(unexpected_report_fields))
        )
    summary = report.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 300:
        raise SystemExit("Fast8 差异报告 summary 必须是 1–300 字的字符串")
    job_styles = [item["style"] for item in job.get("candidates") or []]
    collision_groups = report.get("collision_groups") or []
    if not isinstance(collision_groups, list) or len(collision_groups) > 4:
        raise SystemExit("Fast8 collision_groups 必须是最多四项的数组")
    collision_styles: set[str] = set()
    allowed_overlap_axes = {
        "reading_entry",
        "dominant_layout_topology",
        "information_organization",
        "visual_emphasis",
        "image_text_treatment",
        "semantic_emphasis",
    }
    for index, group in enumerate(collision_groups):
        if not isinstance(group, dict) or set(group) - {
            "styles",
            "overlap_axes",
            "observable_evidence",
        }:
            raise SystemExit(f"collision_groups[{index}] 字段无效")
        group_styles = group.get("styles")
        overlap_axes = group.get("overlap_axes")
        if not isinstance(group_styles, list) or not isinstance(overlap_axes, list):
            raise SystemExit(f"collision_groups[{index}] 缺少 styles/overlap_axes 数组")
        if (
            len(group_styles) < 2
            or not all(isinstance(style, str) for style in group_styles)
            or len(group_styles) != len(set(group_styles))
            or not set(group_styles).issubset(job_styles)
        ):
            raise SystemExit(
                f"collision_groups[{index}].styles 必须包含至少两个互异的受检席位"
            )
        if (
            len(overlap_axes) < 2
            or not all(isinstance(axis, str) for axis in overlap_axes)
            or len(overlap_axes) != len(set(overlap_axes))
            or not set(overlap_axes).issubset(allowed_overlap_axes)
        ):
            raise SystemExit(
                f"collision_groups[{index}].overlap_axes 必须包含至少两个合法维度"
            )
        evidence = group.get("observable_evidence")
        if (
            not isinstance(evidence, str)
            or not evidence.strip()
            or len(evidence.strip()) > 240
        ):
            raise SystemExit(
                f"collision_groups[{index}].observable_evidence 必须是 1–240 字的字符串"
            )
        collision_styles.update(group_styles)
    craft_red_flags: list[dict[str, Any]] = []
    craft_styles: set[str] = set()
    if judge_contract_version == CURRENT_FAST8_JUDGE_CONTRACT_VERSION:
        craft_red_flags, craft_styles = validate_fast8_craft_red_flags(
            report.get("craft_red_flags"), job_styles
        )
    global_chrome_result: dict[str, Any] | None = None
    if isinstance(integrated_chrome, dict):
        if int(job.get("checkpoint") or 0) != 8:
            raise SystemExit("集成 global chrome 检查只允许出现在最终 checkpoint=8")
        if integrated_chrome.get("candidate_set_sha256") != job.get(
            "candidate_set_sha256"
        ):
            raise SystemExit("集成 global chrome 检查未绑定当前候选集合")
        raw_chrome = report.get("global_chrome")
        if not isinstance(raw_chrome, dict) or set(raw_chrome) != {
            "decision",
            "failed_styles",
            "unknown_styles",
            "summary",
        }:
            raise SystemExit("Fast8 集成 global_chrome 报告字段无效")
        chrome_decision = raw_chrome.get("decision")
        failed_styles = raw_chrome.get("failed_styles")
        unknown_styles = raw_chrome.get("unknown_styles")
        chrome_summary = raw_chrome.get("summary")
        if chrome_decision not in {"pass", "needs_inspection", "fail"}:
            raise SystemExit("global_chrome.decision 无效")
        if (
            not isinstance(failed_styles, list)
            or not isinstance(unknown_styles, list)
            or not all(isinstance(value, str) for value in failed_styles + unknown_styles)
        ):
            raise SystemExit("global_chrome failed_styles/unknown_styles 必须是数组")
        normalized_failed = [normalize_style(value) for value in failed_styles]
        normalized_unknown = [normalize_style(value) for value in unknown_styles]
        if (
            any(value is None for value in normalized_failed + normalized_unknown)
            or len(normalized_failed) != len(set(normalized_failed))
            or len(normalized_unknown) != len(set(normalized_unknown))
            or set(normalized_failed) & set(normalized_unknown)
            or not set(normalized_failed + normalized_unknown).issubset(set(job_styles))
        ):
            raise SystemExit("global_chrome 席位必须互异且属于当前受检集合")
        expected_chrome_decision = (
            "fail"
            if normalized_failed
            else "needs_inspection"
            if normalized_unknown
            else "pass"
        )
        if chrome_decision != expected_chrome_decision:
            raise SystemExit(
                f"global_chrome.decision 应为 {expected_chrome_decision}"
            )
        if (
            not isinstance(chrome_summary, str)
            or not chrome_summary.strip()
            or len(chrome_summary.strip()) > 240
        ):
            raise SystemExit("global_chrome.summary 必须是 1–240 字符")
        global_chrome_result = {
            "decision": chrome_decision,
            "failed_styles": normalized_failed,
            "unknown_styles": normalized_unknown,
            "summary": chrome_summary.strip(),
        }
    required_asset_result: dict[str, Any] | None = None
    if isinstance(integrated_required_assets, dict):
        if int(job.get("checkpoint") or 0) != 8:
            raise SystemExit("集成 required asset 检查只允许出现在最终 checkpoint=8")
        if integrated_required_assets.get("candidate_set_sha256") != job.get(
            "candidate_set_sha256"
        ):
            raise SystemExit("集成 required asset 检查未绑定当前候选集合")
        raw_assets = report.get("required_assets")
        if not isinstance(raw_assets, dict) or set(raw_assets) != {
            "decision",
            "failed_styles",
            "unknown_styles",
            "summary",
        }:
            raise SystemExit("Fast8 集成 required_assets 报告字段无效")
        asset_decision = raw_assets.get("decision")
        failed_styles = raw_assets.get("failed_styles")
        unknown_styles = raw_assets.get("unknown_styles")
        asset_summary = raw_assets.get("summary")
        if asset_decision not in {"pass", "needs_inspection", "fail"}:
            raise SystemExit("required_assets.decision 无效")
        if (
            not isinstance(failed_styles, list)
            or not isinstance(unknown_styles, list)
            or not all(isinstance(value, str) for value in failed_styles + unknown_styles)
        ):
            raise SystemExit("required_assets failed_styles/unknown_styles 必须是数组")
        normalized_failed = [normalize_style(value) for value in failed_styles]
        normalized_unknown = [normalize_style(value) for value in unknown_styles]
        if (
            any(value is None for value in normalized_failed + normalized_unknown)
            or len(normalized_failed) != len(set(normalized_failed))
            or len(normalized_unknown) != len(set(normalized_unknown))
            or set(normalized_failed) & set(normalized_unknown)
            or not set(normalized_failed + normalized_unknown).issubset(set(job_styles))
        ):
            raise SystemExit("required_assets 席位必须互异且属于当前受检集合")
        expected_asset_decision = (
            "fail"
            if normalized_failed
            else "needs_inspection"
            if normalized_unknown
            else "pass"
        )
        if asset_decision != expected_asset_decision:
            raise SystemExit(
                f"required_assets.decision 应为 {expected_asset_decision}"
            )
        if (
            not isinstance(asset_summary, str)
            or not asset_summary.strip()
            or len(asset_summary.strip()) > 240
        ):
            raise SystemExit("required_assets.summary 必须是 1–240 字符")
        required_asset_result = {
            "decision": asset_decision,
            "failed_styles": normalized_failed,
            "unknown_styles": normalized_unknown,
            "summary": asset_summary.strip(),
        }
    report_job_sha = report.get("review_job_sha256")
    if report_job_sha != job_sha:
        raise SystemExit("差异检查报告未绑定正式 review job SHA-256")
    if report.get("candidate_set_sha256") != job.get("candidate_set_sha256"):
        raise SystemExit("差异检查报告的 candidate_set_sha256 与任务不一致")
    review_kind = str(job.get("review_kind") or "legacy_checkpoint")
    current_manifest = fast8_candidate_manifest(
        state,
        styles=(
            list(QUICK_STYLES)
            if review_kind in {"delta_recheck", "final_recheck_fallback"}
            else job_styles
        ),
    )
    if fast8_candidate_set_sha256(current_manifest) != job.get("candidate_set_sha256"):
        raise SystemExit("差异检查报告已过期：受检候选已被替换或文件发生变化")
    decision = report.get("decision")
    if decision not in {"continue", "pass", "replace", "best_effort"}:
        raise SystemExit("差异检查 decision 只允许 continue|pass|replace|best_effort")
    if review.get("status") == "repair_queued":
        raise SystemExit("Fast8 差异替代尚在队列中，不得用另一份旧候选报告覆盖决定")
    checkpoint = int(job.get("checkpoint") or 0)
    replacement_styles = report.get("replacement_styles") or []
    if not isinstance(replacement_styles, list):
        raise SystemExit("replacement_styles 必须是数组")
    if not all(isinstance(item, str) for item in replacement_styles):
        raise SystemExit("replacement_styles 只能包含席位字符串")
    normalized_replacements = [normalize_style(item) for item in replacement_styles]
    if any(style is None for style in normalized_replacements) or len(
        normalized_replacements
    ) != len(set(normalized_replacements)):
        raise SystemExit("replacement_styles 必须是互不重复的合法席位")
    replacement_styles = [style for style in normalized_replacements if style]
    if checkpoint in {4, 6} and decision != "continue":
        raise SystemExit("checkpoint 4/6 只允许增量观察并返回 decision=continue")
    if checkpoint == 8 and decision == "continue":
        raise SystemExit("checkpoint 8 必须给出 pass|replace|best_effort 的收口决定")
    if decision == "pass" and craft_red_flags:
        raise SystemExit("Fast8 v2 decision=pass 时不得同时保留严重 craft_red_flags")
    if review_kind in {"delta_recheck", "final_recheck_fallback"} and decision not in {
        "pass",
        "best_effort",
    }:
        raise SystemExit(
            "Fast8 replacement recheck 只允许 pass|best_effort，不得再授权替代"
        )
    if decision == "best_effort" and int(
        review.get("replacement_rounds_used") or 0
    ) < 1:
        raise SystemExit("Fast8 只有完成一轮差异替代后才能用 best_effort 收口")
    if decision != "replace" and replacement_styles:
        raise SystemExit("只有 decision=replace 才能列 replacement_styles")
    if review_kind == "delta_recheck" and global_chrome_result is not None:
        chrome_review = state.get("global_chrome_review") or {}
        provisional = chrome_review.get("provisional_result") or {}
        prior_failed = {
            style
            for style in (provisional.get("failed_styles") or [])
            if style not in set(job_styles)
        }
        prior_unknown = {
            style
            for style in (provisional.get("unknown_styles") or [])
            if style not in set(job_styles)
        }
        merged_failed = sorted(
            prior_failed | set(global_chrome_result["failed_styles"])
        )
        merged_unknown = sorted(
            (prior_unknown | set(global_chrome_result["unknown_styles"]))
            - set(merged_failed)
        )
        global_chrome_result = {
            **global_chrome_result,
            "decision": (
                "fail"
                if merged_failed
                else "needs_inspection"
                if merged_unknown
                else "pass"
            ),
            "failed_styles": merged_failed,
            "unknown_styles": merged_unknown,
        }
    if review_kind == "delta_recheck" and required_asset_result is not None:
        asset_review = state.get("required_asset_review") or {}
        provisional = asset_review.get("provisional_result") or {}
        prior_failed = {
            style
            for style in (provisional.get("failed_styles") or [])
            if style not in set(job_styles)
        }
        prior_unknown = {
            style
            for style in (provisional.get("unknown_styles") or [])
            if style not in set(job_styles)
        }
        merged_failed = sorted(
            prior_failed | set(required_asset_result["failed_styles"])
        )
        merged_unknown = sorted(
            (prior_unknown | set(required_asset_result["unknown_styles"]))
            - set(merged_failed)
        )
        required_asset_result = {
            **required_asset_result,
            "decision": (
                "fail"
                if merged_failed
                else "needs_inspection"
                if merged_unknown
                else "pass"
            ),
            "failed_styles": merged_failed,
            "unknown_styles": merged_unknown,
        }
    if decision == "replace":
        if report.get("high_confidence") is not True:
            raise SystemExit(
                "只有 high_confidence=true 的实质同构或严重最低工艺退化可触发替代"
            )
        if not 1 <= len(replacement_styles) <= 2:
            raise SystemExit("单轮差异替代必须包含 1–2 个席位")
        if not set(replacement_styles).issubset(job_styles):
            raise SystemExit("replacement_styles 必须来自本次受检候选")
        supported_styles = collision_styles | craft_styles
        if not set(replacement_styles).issubset(supported_styles):
            raise SystemExit(
                "替代席位必须由 collision_groups 或严重 craft_red_flags 的"
                "可观察证据覆盖"
            )
        if not craft_styles.issubset(set(replacement_styles)):
            raise SystemExit(
                "final_initial 报告中的严重 craft_red_flags 必须全部进入本轮替代"
            )
    else:
        if report.get("high_confidence") is not False:
            raise SystemExit("非 replace 决定必须使用 high_confidence=false")
        briefs = report.get("replacement_briefs")
        if briefs not in ({}, None):
            raise SystemExit("非 replace 决定不得包含 replacement_briefs")
        replacement_styles = []

    queued_jobs: list[dict[str, Any]] = []
    timestamp = args.timestamp or now_iso()
    if decision == "replace":
        if int(review.get("replacement_rounds_used") or 0) >= 1:
            raise SystemExit("Fast8 最多允许一轮差异替代")
        used_styles = set(review.get("replacement_styles") or [])
        if used_styles & set(replacement_styles):
            raise SystemExit("同一 Fast8 席位最多允许一次差异替代")
        used_count = int(review.get("replacement_count") or 0)
        if used_count + len(replacement_styles) > int(
            review.get("replacement_budget_total") or 2
        ):
            raise SystemExit("Fast8 全运行最多允许两张差异替代")
        briefs = report.get("replacement_briefs")
        if not isinstance(briefs, dict):
            raise SystemExit("decision=replace 必须提供 replacement_briefs 对象")
        if set(briefs) != set(replacement_styles):
            raise SystemExit("replacement_briefs 必须且只能覆盖全部 replacement_styles")
        replacement_basis = {}
        for style in replacement_styles:
            if style in collision_styles and style in craft_styles:
                replacement_basis[style] = (
                    "material_collision_and_minimum_craft_regression"
                )
            elif style in craft_styles:
                replacement_basis[style] = "minimum_craft_regression"
            else:
                replacement_basis[style] = "material_collision"
        queued_jobs = create_fast8_replacement_jobs(
            project_dir=project_dir,
            state=state,
            styles=replacement_styles,
            briefs=briefs,
            replacement_basis=replacement_basis,
            report_sha256=report_sha,
            timestamp=timestamp,
        )
        review["replacement_count"] = used_count + len(replacement_styles)
        review["replacement_rounds_used"] = 1
        review["replacement_styles"] = sorted(used_styles | set(replacement_styles))
        review["status"] = "repair_queued"
        review["final_candidate_set_sha256"] = None
        if global_chrome_result is not None:
            chrome_review = state.setdefault("global_chrome_review", {})
            chrome_review["status"] = "pending_recheck"
            chrome_review["candidate_set_sha256"] = None
            chrome_review["provisional_result"] = global_chrome_result
        if required_asset_result is not None:
            asset_review = state.setdefault("required_asset_review", {})
            asset_review["status"] = "pending_recheck"
            asset_review["candidate_set_sha256"] = None
            asset_review["provisional_result"] = required_asset_result
    elif checkpoint == 8:
        if review_kind not in {"delta_recheck", "final_recheck_fallback"} and len(
            job_styles
        ) != 8:
            raise SystemExit("Fast8 最终差异报告必须覆盖 A-H 八张当前候选")
        if review_kind in {"delta_recheck", "final_recheck_fallback"} and int(
            job.get("full_candidate_count") or 0
        ) != 8:
            raise SystemExit("Fast8 替代后收口必须绑定完整 A-H 候选集合")
        review["status"] = decision
        review["final_candidate_set_sha256"] = job["candidate_set_sha256"]
        if global_chrome_result is not None:
            chrome_review = state.setdefault("global_chrome_review", {})
            chrome_review.update(
                {
                    "status": global_chrome_result["decision"],
                    "candidate_set_sha256": job["candidate_set_sha256"],
                    "summary": global_chrome_result["summary"],
                    "failed_styles": global_chrome_result["failed_styles"],
                    "unknown_styles": global_chrome_result["unknown_styles"],
                    "report_path": str(report_path),
                    "report_sha256": report_sha,
                    "provisional_result": None,
                }
            )
        if required_asset_result is not None:
            asset_review = state.setdefault("required_asset_review", {})
            asset_review.update(
                {
                    "status": required_asset_result["decision"],
                    "candidate_set_sha256": job["candidate_set_sha256"],
                    "summary": required_asset_result["summary"],
                    "failed_styles": required_asset_result["failed_styles"],
                    "unknown_styles": required_asset_result["unknown_styles"],
                    "report_path": str(report_path),
                    "report_sha256": report_sha,
                    "provisional_result": None,
                }
            )
    else:
        review["status"] = "waiting_for_candidates"
    reports.append(
        {
            "checkpoint": checkpoint,
            "review_kind": review_kind,
            "decision": decision,
            "candidate_set_sha256": job["candidate_set_sha256"],
            "report_path": str(report_path),
            "report_sha256": report_sha,
            "replacement_styles": replacement_styles,
            "collision_groups": collision_groups,
            "craft_red_flags": craft_red_flags,
            "summary": str(report.get("summary") or "").strip(),
            "global_chrome": global_chrome_result,
            "required_assets": required_asset_result,
            "applied_at": timestamp,
        }
    )
    review["latest_report_path"] = str(report_path)
    try:
        atomic_write_json(state_path, state)
    except Exception:
        for item in queued_jobs:
            if item.get("created_during_apply") is True:
                try:
                    Path(str(item["job_path"])).unlink()
                except FileNotFoundError:
                    pass
        raise
    public_jobs = [
        {key: value for key, value in item.items() if key != "created_during_apply"}
        for item in queued_jobs
    ]
    print(
        json.dumps(
            {
                "status": "ok",
                "decision": decision,
                "repair_jobs": public_jobs,
                "diversity_status": review.get("status"),
                "report_sha256": report_sha,
            },
            ensure_ascii=False,
        )
    )


def command_prepare_diversity_repairs(args: argparse.Namespace) -> None:
    """从主 Agent 为本页预备的正向方向池中分配撞车返修。"""

    project_dir = Path(args.project_dir).resolve()
    styles = parse_style_csv(args.styles)
    state_path = project_dir / "state" / "style_run_state.json"
    if not state_path.is_file():
        state_path = project_dir / "style_run_state.json"
    state = read_json(state_path)
    portfolio_path_value = state.get("layout_portfolio_path")
    legacy = False
    if isinstance(portfolio_path_value, str) and Path(portfolio_path_value).is_file():
        bundle = read_json(Path(portfolio_path_value))
        if bundle.get("layout_portfolio_contract_version") in FAST_DIVERSITY_QUICK_LAYOUT_VERSIONS:
            raise SystemExit(
                "Fast8 v7 必须使用隔离差异裁判与 apply-fast8-diversity-report；"
                "不得调用旧 Quick8 v3 备用方向池"
            )
        if bundle.get("layout_portfolio_contract_version") in ONE_SHOT_QUICK_LAYOUT_VERSIONS:
            raise SystemExit(
                "quick8 v4/v5 不在用户选择前做差异返修；请保留首轮候选并等待用户选择"
            )
        reserve = bundle.get("repair_directions")
        id_field = "direction_id"
        label_field = "difference_key"
    else:
        # 旧运行仍可继续使用已经落盘的 v2 reserve，不影响历史项目恢复。
        legacy = True
        bundle = read_json(project_dir / "exploration_seeds.json")
        reserve = bundle.get("reserve_layout_families")
        id_field = "family_id"
        label_field = "family_name"
    enforce_source_guard(state_path, state, action="targeted_candidate_repair")
    if not isinstance(reserve, list) or not reserve:
        raise SystemExit("本次运行没有可用的本页专属备用方向")
    collision_details = (
        json.loads(args.collision_details_json) if args.collision_details_json else {}
    )
    if not isinstance(collision_details, dict):
        raise SystemExit("--collision-details-json 必须是 style->可观察失败 的对象")

    allocation_path = project_dir / "diversity_repair_allocations.json"
    if allocation_path.exists():
        allocations_doc = read_json(allocation_path)
    else:
        allocations_doc = {
            "diversity_repair_contract_version": 1,
            "run_id": bundle.get("run_id"),
            "allocations": {},
        }
    allocations = allocations_doc.setdefault("allocations", {})
    if not isinstance(allocations, dict):
        raise SystemExit("diversity_repair_allocations.json 的 allocations 必须是对象")
    if legacy:
        for value in allocations.values():
            if isinstance(value, dict) and "direction_id" not in value and value.get("family_id"):
                value["direction_id"] = value["family_id"]
                value["direction_label"] = value.get("family_name", value["family_id"])
    reserve_by_id = {
        item.get(id_field): item
        for item in reserve
        if isinstance(item, dict) and isinstance(item.get(id_field), str)
    }
    used = {
        value.get("direction_id")
        for value in allocations.values()
        if isinstance(value, dict)
    }
    for style in styles:
        if style in allocations:
            continue
        replacement = next(
            (item for direction_id, item in reserve_by_id.items() if direction_id not in used),
            None,
        )
        if replacement is None:
            raise SystemExit("本页尚未使用的备用方向不足；请由主 Agent 增补 repair_directions")
        allocations[style] = {
            "direction_id": replacement[id_field],
            "direction_label": replacement[label_field],
            "allocated_at": now_iso(),
        }
        used.add(replacement[id_field])
    atomic_write_json(allocation_path, allocations_doc)

    repair_paths: list[str] = []
    for style in styles:
        allocation = allocations[style]
        direction = reserve_by_id.get(allocation["direction_id"])
        if direction is None:
            raise SystemExit(f"style_{style} 的已分配方向不在备用池中")
        original = read_json(project_dir / "style_jobs" / f"style_{style}.json")
        observed = collision_details.get(style) or collision_details.get(f"style_{style}")
        if not isinstance(observed, str) or not observed.strip():
            observed = "上一版与其他候选共享了实质相同的空间骨架"
        repair_job = dict(original)
        repair_job["action"] = "repair_anchor"
        repair_job["attempt"] = args.attempt
        if legacy:
            repair_direction = {
                "seed_version": 2,
                "layout_contract_version": 2,
                "seed_id": f"repair-{bundle.get('run_id')}-{style}-{direction['family_id']}",
                **direction,
                "portfolio_context": [],
                "semantic_translation_rule": "保持内容语义关系，用本次替代拓扑重新表达。",
                "anti_convergence": "必须从底层空间骨架重新组织，不能只换颜色、图标或材质。",
            }
            repair_job["exploration_seed"] = repair_direction
            repair_job.pop("layout_direction", None)
        else:
            repair_direction = dict(direction)
            repair_direction["layout_contract_version"] = 3
            repair_direction["seed_version"] = 3
            repair_direction["style_slot"] = style
            repair_direction["shared_prompt_guardrails"] = bundle.get(
                "shared_prompt_guardrails", []
            )
            repair_job["layout_direction"] = repair_direction
            repair_job.pop("exploration_seed", None)
        repair_job["diversity_repair"] = {
            "observed_collision": observed,
            "replacement_direction_id": direction[id_field],
            "replacement_direction_label": direction[label_field],
            "must_recompose_from_scratch": True,
            "preserve_content_and_brand_contract": True,
        }
        repair_job["imagegen_prompt"] = compile_anchor_imagegen_prompt(repair_job) + (
            "\n\n差异返修硬要求：上一版的可观察撞车是："
            + observed
            + "。保留事实、文字、Logo、明暗 tone 和空间压力合同；"
            + f"改用“{direction[label_field]}”方向，不得复用上一版的主要几何骨架。"
        )
        repair_job["imagegen_prompt"] = finalize_imagegen_prompt(
            repair_job["imagegen_prompt"]
        )
        manifest = repair_job.get("imagegen_input_manifest", [])
        repair_job["imagegen_input_fingerprint"] = hashlib.sha256(
            json.dumps(
                {"prompt": repair_job["imagegen_prompt"], "inputs": manifest},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        path = (
            project_dir
            / "repair_jobs"
            / f"style_{style}_attempt_{args.attempt}_diversity.json"
        )
        write_idempotent(path, repair_job)
        repair_paths.append(str(path))
    print(
        json.dumps(
            {
                "status": "ok",
                "repair_jobs": repair_paths,
                "allocations": {style: allocations[style] for style in styles},
            },
            ensure_ascii=False,
        )
    )


def command_prepare_fast_anchor_repairs(args: argparse.Namespace) -> None:
    """为新 Fast 4x3 在扩展前创建一次问题导向的锚点修复任务。"""

    project_dir = Path(args.project_dir).resolve()
    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST_4X3_MODE:
        raise SystemExit("prepare-fast-anchor-repairs 只适用于 fast_4x3_anchored")
    policy = state.get("fast4x3_candidate_policy") or {}
    if policy.get("version") != 2:
        raise SystemExit("只有新 Fast 4x3 v6 运行可使用该定向修复命令")
    enforce_source_guard(state_path, state, action="targeted_candidate_repair")
    styles = parse_style_csv(args.styles)
    if not set(styles).issubset(FULL_STYLES):
        raise SystemExit("--styles 只能包含 A-D")
    issues = json.loads(args.issues_json)
    if not isinstance(issues, dict):
        raise SystemExit("--issues-json 必须是 style->可观察问题 的对象")
    anchor_page_id = str(state.get("anchor_page_id"))
    scheduler = state.setdefault("scheduler", {})
    ready = scheduler.setdefault("ready_queue", [])
    active = scheduler.setdefault("active_actions", [])
    recovery_queue = scheduler.setdefault("recovery_queue", [])
    timestamp = now_iso()
    repair_jobs: list[dict[str, Any]] = []

    for style in styles:
        issue = issues.get(style) or issues.get(f"style_{style}")
        if not isinstance(issue, str) or not issue.strip():
            raise SystemExit(f"style_{style} 缺少非空可观察修复问题")
        style_state = (state.get("styles") or {}).get(style) or {}
        contract_path = style_state.get("contract_path")
        follower_pages = {
            str(page_id): record
            for page_id, record in (style_state.get("pages") or {}).items()
            if str(page_id) != anchor_page_id
        }
        if (
            (isinstance(contract_path, str) and Path(contract_path).exists())
            or follower_pages
        ):
            raise SystemExit(
                f"style_{style} 已创建跟随合同或页面；锚点修复必须发生在扩展之前"
            )
        if any(
            item.get("style") == style
            and str(item.get("page_id")) == anchor_page_id
            for item in active
        ):
            raise SystemExit(f"style_{style} 锚点仍有活动任务")
        if any(
            item.get("style") == style
            and str(item.get("page_id")) == anchor_page_id
            and item.get("action") == "recover_artifact"
            and item.get("source_action") == "repair_anchor"
            for item in recovery_queue
        ):
            raise SystemExit(
                f"style_{style} 定向锚点修复正在等待产物恢复，不得创建下一次修复"
            )
        record = candidate_anchor(state, style, anchor_page_id)
        if len(record.get("attempt_sources") or []) > 1:
            raise SystemExit(f"style_{style} 已使用过一次定向锚点修复")
        attempt = int(record.get("attempt_count") or 1) + 1
        if attempt > 3:
            raise SystemExit(f"style_{style} 已达到 Fast 锚点尝试上限")

        original = read_json(project_dir / "style_jobs" / f"style_{style}.json")
        language = resolve_job_language(original)
        use_chinese_control = language.lower().startswith("zh")
        repair_job = dict(original)
        repair_job["action"] = "repair_anchor"
        repair_job["attempt"] = attempt
        repair_job["repair_source"] = record["selected_source"]
        repair_job["repair_issue"] = issue.strip()
        repair_job["repair_directive"] = {
            "must_change": [issue.strip()],
            "invariants": [
                "全部 display_required 与 display_flexible 内容义务",
                "页面语言、tone 与必要资产角色",
                "上一版已经成立的整体视觉方向与完成度",
            ],
            "single_objective": True,
        }
        repair_rules = dict(repair_job.get("generation_rules") or {})
        repair_rules["max_total_attempts_per_page"] = max(
            int(repair_rules.get("max_total_attempts_per_page") or 0), attempt
        )
        repair_job["generation_rules"] = repair_rules
        repair_job["reference_images"] = [
            {
                "path": record["selected_source"],
                "role": "candidate_to_repair",
                "reference_intent": {
                    "borrow": [
                        "保留上一版有效的整体视觉方向"
                        if use_chinese_control
                        else "preserve the prior candidate's effective overall direction"
                    ],
                    "do_not_copy": [
                        "已指出的内容硬伤或实质同构问题"
                        if use_chinese_control
                        else "the identified content defect or material structural collision"
                    ],
                },
            }
        ]
        repair_job["imagegen_prompt"] = compile_anchor_imagegen_prompt(repair_job)
        if use_chinese_control:
            repair_job["imagegen_prompt"] += (
                "\n\n定向修复：以上一版候选（附件1）为基础，只修复以下可观察问题："
                + issue.strip()
                + "。保留全部必显内容、明暗、整体视觉气质和本席位的探索空间；"
                "不要重抽为另一套固定风格。"
            )
        else:
            repair_job["imagegen_prompt"] += (
                "\n\nTargeted repair: use the prior candidate (attachment 1) as the base and "
                "fix only this observable issue: "
                + issue.strip()
                + ". Preserve all required content, tone, overall visual character, and "
                "the seat's exploratory freedom; do not redraw it as a different fixed style."
            )
        repair_job["imagegen_prompt"] = finalize_imagegen_prompt(
            repair_job["imagegen_prompt"]
        )
        repair_assets = merge_attachment_items(original.get("required_assets") or [])
        repair_job["required_assets"] = repair_assets
        referenced_paths = extract_input_paths(
            repair_job["reference_images"] + repair_assets
        )
        normalized_paths, manifest = build_input_manifest(referenced_paths)
        repair_job["imagegen_referenced_paths"] = normalized_paths
        repair_job["imagegen_input_manifest"] = manifest
        repair_job["imagegen_input_fingerprint"] = hashlib.sha256(
            json.dumps(
                {"prompt": repair_job["imagegen_prompt"], "inputs": manifest},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        job_path = (
            project_dir
            / "style_jobs"
            / "repair_jobs"
            / f"style_{style}_page_{anchor_page_id}_attempt_{attempt}_fast.json"
        )
        write_idempotent(job_path, repair_job)
        queue_item = {
            "style": style,
            "page_id": anchor_page_id,
            "action": "repair_anchor",
            "attempt": attempt,
            "generation_job_path": str(job_path.resolve()),
            "generation_job_sha256": file_sha256(job_path),
        }
        if not any(
            item.get("style") == style
            and str(item.get("page_id")) == anchor_page_id
            and item.get("action") == "repair_anchor"
            for item in ready + active
        ):
            ready.append(queue_item)
            append_event(
                state,
                "queued",
                timestamp,
                style=style,
                page_id=anchor_page_id,
                action="repair_anchor",
                details={"source": "prepare-fast-anchor-repairs", "attempt": attempt},
            )
        repair_jobs.append(
            {
                **queue_item,
                "job_path": str(job_path),
                "repair_source": record["selected_source"],
            }
        )

    atomic_write_json(state_path, state)
    print(
        json.dumps(
            {"status": "ok", "repair_jobs": repair_jobs, "prepared_at": timestamp},
            ensure_ascii=False,
        )
    )


def command_prepare_fast_followers(args: argparse.Namespace) -> None:
    """按已就绪席位渐进解锁 Fast 4x3 跟随页，不等待四锚点全部通过。"""

    project_dir = Path(args.project_dir).resolve()
    state_path = Path(args.state).resolve()
    content_dir = Path(args.content_contract_dir).resolve()
    state = read_json(state_path)
    original_state_snapshot = json.dumps(state, ensure_ascii=False, sort_keys=True)
    if state.get("run_mode") != FAST_4X3_MODE:
        raise SystemExit("prepare-fast-followers 只适用于 fast_4x3_anchored")
    if (state.get("preflight") or {}).get("status") != "resolved":
        raise SystemExit("预检尚未 resolved，不得创建跟随页任务")
    anchor_page_id = state.get("anchor_page_id")
    follower_ids = state.get("follower_page_ids")
    if (
        not isinstance(anchor_page_id, str)
        or not isinstance(follower_ids, list)
        or len(follower_ids) != 2
    ):
        raise SystemExit("状态必须包含一个 anchor_page_id 和两个 follower_page_ids")

    if args.styles:
        requested_styles = parse_style_csv(args.styles)
        if not set(requested_styles).issubset(FULL_STYLES):
            raise SystemExit("--styles 只能包含 A-D")
    else:
        requested_styles = []
        for style in FULL_STYLES:
            record = page_record(state, style, anchor_page_id)
            source = record.get("selected_source")
            if (
                record.get("file_validated_at")
                and isinstance(source, str)
                and Path(source).is_file()
            ):
                requested_styles.append(style)
    if not requested_styles:
        raise SystemExit("当前没有已完成文件校验的 Fast 4x3 锚点")

    follower_contracts: dict[str, dict[str, Any]] = {}
    follower_contract_paths: dict[str, Path] = {}
    requires_v4_followers = (
        (state.get("fast4x3_candidate_policy") or {}).get("version") in {2, 3}
    )
    for page_id in follower_ids:
        path = content_dir / f"page_{page_id}.json"
        contract = read_json(path)
        require_keys(
            contract,
            [
                "content_contract_version",
                "page_id",
                "display_required",
                "source_facts",
                "display_supporting",
                "content_resolution",
                *spatial_contract_required_keys(contract),
            ],
            str(path),
        )
        validate_dispatchable_content_contract(
            contract, str(path), soft_spatial_preference=True
        )
        if requires_v4_followers and contract.get("prompt_contract_version") != 4:
            raise SystemExit(
                f"新 Fast 4x3 的跟随页必须使用 prompt_contract_version=4：{path}"
            )
        if str(contract["page_id"]) != str(page_id):
            raise SystemExit(f"页面合同 ID 不一致：{path}")
        if state.get("language"):
            contract.setdefault(
                "language", normalize_output_language(state.get("language"))
            )
        follower_contracts[page_id] = contract
        follower_contract_paths[page_id] = path.resolve()

    follower_asset_items: list[Any] = []
    for style in requested_styles:
        anchor_job = read_json(project_dir / "style_jobs" / f"style_{style}.json")
        tone = str(anchor_job.get("tone") or tone_for_style(FAST_4X3_MODE, style))
        # Keep the source guard aligned with the actual follower compiler:
        # anchor-page evidence is not forwarded to follower ImageGen inputs.
        for item in follower_shared_asset_items(
            non_global_chrome_assets(anchor_job.get("required_assets") or [])
        ):
            tagged = {"path": item, "styles": [style]}
            if isinstance(item, dict):
                tagged = {**item, "styles": [style]}
            follower_asset_items.append(tagged)
        for contract in follower_contracts.values():
            for item in filter_required_assets(
                content_contract_asset_items(contract), style, tone
            ):
                tagged = {"path": item, "styles": [style]}
                if isinstance(item, dict):
                    tagged = {**item, "styles": [style]}
                follower_asset_items.append(tagged)
    enforce_source_guard(
        state_path,
        state,
        action="continue_following_pages",
        content_contract_paths=list(follower_contract_paths.values()),
        asset_items=follower_asset_items,
        page_ids=list(follower_contract_paths),
    )

    timestamp = now_iso()
    previous_prepared_at = next(
        (
            event.get("occurred_at")
            for event in reversed(state.get("events") or [])
            if isinstance(event, dict)
            and event.get("name") == "followers_prepared"
            and set(((event.get("details") or {}).get("styles") or []))
            .issuperset(requested_styles)
        ),
        None,
    )
    scheduler = state.setdefault("scheduler", {})
    ready_queue = scheduler.setdefault("ready_queue", [])
    active_actions = scheduler.setdefault("active_actions", [])
    recovery_queue = scheduler.setdefault("recovery_queue", [])
    created_contracts: list[str] = []
    created_jobs: list[str] = []
    newly_queued: list[dict[str, Any]] = []
    dispatch_ready: list[dict[str, Any]] = []
    precompiled_prompt_count = 0

    for style in requested_styles:
        if any(
            item.get("style") == style
            and item.get("action") in {"generate_anchor", "repair_anchor"}
            for item in active_actions
        ):
            raise SystemExit(f"style_{style} 锚点仍在生成或修复，不得提前扩展")
        anchor = candidate_anchor(state, style, anchor_page_id)
        anchor_job_path = project_dir / "style_jobs" / f"style_{style}.json"
        anchor_job = read_json(anchor_job_path)
        contract = build_fast_candidate_contract(state, style, anchor, anchor_job)
        contract_path = project_dir / "style_contracts" / f"style_{style}.json"
        write_idempotent(contract_path, contract)
        created_contracts.append(str(contract_path))
        style_state = state["styles"][style]
        style_state["contract_path"] = str(contract_path)
        style_pages = style_state.setdefault("pages", {})

        for page_id in follower_ids:
            page_job = dict(follower_contracts[page_id])
            page_job.update(
                {
                    "run_mode": FAST_4X3_MODE,
                    "style_slot": style,
                    "action": "generate_follower",
                    "attempt": 1,
                    "candidate_policy": contract["candidate_policy"],
                    "spatial_preference_mode": "soft",
                    "generation_rules": contract["generation_rules"],
                    "output_target": str(
                        origin_image_target(project_dir, style, page_id)
                    ),
                    "source_content_contract_path": str(
                        follower_contract_paths[page_id]
                    ),
                    "source_content_contract_sha256": file_sha256(
                        follower_contract_paths[page_id]
                    ),
                }
            )
            if page_job.get("prompt_contract_version") == 4:
                if contract.get("style_contract_version") not in {4, 5}:
                    raise SystemExit(
                        f"style_{style}/{page_id} v4 页面合同必须配套 v4/v5 候选风格合同"
                    )
                page_job.update(compile_follower_prompt_bundle_v4(page_job, contract))
                precompiled_prompt_count += 1
            job_path = (
                project_dir
                / "style_page_jobs"
                / f"style_{style}"
                / f"page_{page_id}.json"
            )
            write_idempotent(job_path, page_job)
            created_jobs.append(str(job_path))
            if page_id not in style_pages:
                style_pages[page_id] = initial_page_state("follower", timestamp)
            record = style_pages[page_id]
            already_queued = any(
                item.get("style") == style
                and str(item.get("page_id")) == str(page_id)
                and item.get("action") == "generate_follower"
                for item in ready_queue + active_actions
            ) or any(
                item.get("style") == style
                and str(item.get("page_id")) == str(page_id)
                and item.get("action") == "recover_artifact"
                and item.get("source_action") == "generate_follower"
                for item in recovery_queue + active_actions
            )
            if not record.get("selected_source") and not already_queued:
                item = {
                    "style": style,
                    "action": "generate_follower",
                    "page_id": page_id,
                }
                ready_queue.append(item)
                newly_queued.append(item)
                dispatch_ready.append(
                    {
                        **item,
                        "job_path": str(job_path),
                        "contract_path": str(contract_path),
                    }
                )
        expected_page_ids = {str(anchor_page_id), *(str(value) for value in follower_ids)}
        if not (
            set(map(str, style_pages)) == expected_page_ids
            and all(
                record.get("status") in {"accepted", "candidate_ready"}
                for record in style_pages.values()
                if isinstance(record, dict)
            )
        ):
            style_state["workflow_status"] = (
                "followers_running"
                if any(
                    item.get("style") == style
                    and item.get("action") == "generate_follower"
                    for item in active_actions
                )
                else "contract_ready"
            )

    if scheduler.get("phase") != "completed":
        scheduler["phase"] = "follower_generation"
    scheduler["active_child_limit"] = active_child_limit_for_state(state)
    timing = state.setdefault("timing", {})
    timing.setdefault("first_fast_follower_tasks_ready_at", timestamp)
    if all(
        (project_dir / "style_contracts" / f"style_{style}.json").is_file()
        for style in FULL_STYLES
    ):
        timing.setdefault("contracts_completed_at", timestamp)
        timing.setdefault("follower_tasks_ready_at", timestamp)
    state_changed = (
        json.dumps(state, ensure_ascii=False, sort_keys=True) != original_state_snapshot
    )
    if not newly_queued and not state_changed:
        print(
            json.dumps(
                {
                    "status": "already_prepared",
                    "styles": requested_styles,
                    "contracts": len(created_contracts),
                    "page_jobs": len(created_jobs),
                    "newly_queued": 0,
                    "dispatch_ready": [],
                    "prepared_at": previous_prepared_at,
                    "checked_at": timestamp,
                },
                ensure_ascii=False,
            )
        )
        return
    append_event(
        state,
        "followers_prepared",
        timestamp,
        details={
            "mode": FAST_4X3_MODE,
            "styles": requested_styles,
            "progressive_unlock": True,
            "contract_count": len(created_contracts),
            "page_job_count": len(created_jobs),
            "newly_queued": len(newly_queued),
            "precompiled_prompt_count": precompiled_prompt_count,
            "content_contract_dir": str(content_dir),
        },
    )
    for item in newly_queued:
        append_event(
            state,
            "queued",
            timestamp,
            style=item["style"],
            page_id=item["page_id"],
            action=item["action"],
            details={"source": "prepare-fast-followers"},
        )
    atomic_write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "ok" if newly_queued else "already_prepared",
                "styles": requested_styles,
                "contracts": len(created_contracts),
                "page_jobs": len(created_jobs),
                "newly_queued": len(newly_queued),
                "dispatch_ready": dispatch_ready,
                "prepared_at": timestamp,
            },
            ensure_ascii=False,
        )
    )


def command_prepare_followers(args: argparse.Namespace) -> None:
    project_dir = Path(args.project_dir).resolve()
    state_path = Path(args.state).resolve()
    seeds_path = Path(args.contract_seeds).resolve()
    content_dir = Path(args.content_contract_dir).resolve()
    state = read_json(state_path)
    seeds = read_json(seeds_path)

    if state.get("run_mode") != "full_4x3_anchored":
        raise SystemExit("prepare-followers 只适用于 full_4x3_anchored")
    if (state.get("preflight") or {}).get("status") != "resolved":
        raise SystemExit("预检尚未 resolved，不得创建跟随页任务")
    scheduler = state.setdefault("scheduler", {})
    if scheduler.get("active_actions"):
        raise SystemExit("仍有 active_actions，不得切换到跟随页阶段")
    anchor_page_id = state.get("anchor_page_id")
    follower_ids = state.get("follower_page_ids")
    if not isinstance(anchor_page_id, str) or not isinstance(follower_ids, list) or len(follower_ids) != 2:
        raise SystemExit("状态必须包含一个 anchor_page_id 和两个 follower_page_ids")

    seed_styles = seeds.get("styles")
    if not isinstance(seed_styles, dict):
        raise SystemExit("contract seeds 必须包含 styles 对象")
    previous_event = next(
        (
            event
            for event in state.get("events", [])
            if isinstance(event, dict) and event.get("name") == "followers_prepared"
        ),
        None,
    )
    timestamp = (
        previous_event.get("occurred_at")
        if isinstance(previous_event, dict) and previous_event.get("occurred_at")
        else now_iso()
    )

    follower_contracts: dict[str, dict[str, Any]] = {}
    follower_contract_paths: dict[str, Path] = {}
    requires_v4_followers = (
        layout_portfolio_contract_version(state) == CURRENT_4X3_LAYOUT_VERSION
    )
    for page_id in follower_ids:
        path = content_dir / f"page_{page_id}.json"
        contract = read_json(path)
        require_keys(
            contract,
            [
                "content_contract_version",
                "page_id",
                "display_required",
                "source_facts",
                "display_supporting",
                "content_resolution",
                *spatial_contract_required_keys(contract),
            ],
            str(path),
        )
        validate_dispatchable_content_contract(contract, str(path))
        if requires_v4_followers and contract.get("prompt_contract_version") != 4:
            raise SystemExit(
                f"新严格 4x3 的跟随页必须使用 prompt_contract_version=4：{path}"
            )
        if str(contract["page_id"]) != str(page_id):
            raise SystemExit(f"页面合同 ID 不一致：{path}")
        if state.get("language"):
            contract.setdefault(
                "language", normalize_output_language(state.get("language"))
            )
        follower_contracts[page_id] = contract
        follower_contract_paths[page_id] = path.resolve()

    follower_asset_items: list[Any] = []
    for style in FULL_STYLES:
        seed = seed_styles.get(style) or seed_styles.get(f"style_{style}")
        if not isinstance(seed, dict):
            raise SystemExit(f"contract seeds 缺少 style_{style}")
        style_state = ((state.get("styles") or {}).get(style) or {})
        tone = str(
            seed.get("tone")
            or style_state.get("tone")
            or tone_for_style(STRICT_4X3_MODE, style)
        )
        for item in filter_required_assets(
            seed.get("required_assets") or [], style, tone
        ):
            tagged = {"path": item, "styles": [style]}
            if isinstance(item, dict):
                tagged = {**item, "styles": [style]}
            follower_asset_items.append(tagged)
        for contract in follower_contracts.values():
            for item in filter_required_assets(
                content_contract_asset_items(contract), style, tone
            ):
                tagged = {"path": item, "styles": [style]}
                if isinstance(item, dict):
                    tagged = {**item, "styles": [style]}
                follower_asset_items.append(tagged)
    enforce_source_guard(
        state_path,
        state,
        action="continue_following_pages",
        content_contract_paths=list(follower_contract_paths.values()),
        asset_items=follower_asset_items,
        page_ids=list(follower_contract_paths),
    )

    created_contracts: list[str] = []
    created_jobs: list[str] = []
    for style in FULL_STYLES:
        seed = seed_styles.get(style) or seed_styles.get(f"style_{style}")
        if not isinstance(seed, dict):
            raise SystemExit(f"contract seeds 缺少 style_{style}")
        anchor = accepted_anchor(state, style, anchor_page_id)
        contract = build_contract(state, style, seed, anchor)
        contract_path = project_dir / "style_contracts" / f"style_{style}.json"
        write_idempotent(contract_path, contract)
        created_contracts.append(str(contract_path))
        style_state = state["styles"][style]
        style_state["contract_path"] = str(contract_path)
        style_state["workflow_status"] = "contract_ready"
        style_pages = style_state.setdefault("pages", {})

        for page_id in follower_ids:
            page_job = dict(follower_contracts[page_id])
            page_job["style_slot"] = style
            page_job["action"] = "generate_follower"
            page_job["attempt"] = 1
            page_job["source_content_contract_path"] = str(
                follower_contract_paths[page_id]
            )
            page_job["source_content_contract_sha256"] = file_sha256(
                follower_contract_paths[page_id]
            )
            page_job["output_target"] = str(
                origin_image_target(project_dir, style, page_id)
            )
            if page_job.get("prompt_contract_version") == 4:
                page_job.update(compile_follower_prompt_bundle_v4(page_job, contract))
            job_path = (
                project_dir
                / "style_page_jobs"
                / f"style_{style}"
                / f"page_{page_id}.json"
            )
            write_idempotent(job_path, page_job)
            created_jobs.append(str(job_path))
            if page_id not in style_pages:
                style_pages[page_id] = initial_page_state("follower", timestamp)

    ready_queue = []
    for page_id in follower_ids:
        for style in FULL_STYLES:
            ready_queue.append(
                {"style": style, "action": "generate_follower", "page_id": page_id}
            )
    if previous_event is not None:
        atomic_write_json(state_path, state)
        print(
            json.dumps(
                {
                    "status": "already_prepared",
                    "contracts": len(created_contracts),
                    "page_jobs": len(created_jobs),
                    "prepared_at": timestamp,
                },
                ensure_ascii=False,
            )
        )
        return

    scheduler["phase"] = "follower_generation"
    scheduler["active_child_limit"] = active_child_limit_for_state(state)
    scheduler["ready_queue"] = ready_queue
    scheduler["active_actions"] = []
    timing = state.setdefault("timing", {})
    timing["contracts_completed_at"] = timestamp
    timing["follower_tasks_ready_at"] = timestamp
    append_event(
        state,
        "followers_prepared",
        timestamp,
        details={
            "contract_count": len(created_contracts),
            "page_job_count": len(created_jobs),
            "contract_seeds": str(seeds_path),
            "content_contract_dir": str(content_dir),
        },
    )
    for item in ready_queue:
        append_event(
            state,
            "queued",
            timestamp,
            style=item["style"],
            page_id=item["page_id"],
            action=item["action"],
            details={"source": "prepare-followers"},
        )
    atomic_write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "ok",
                "contracts": len(created_contracts),
                "page_jobs": len(created_jobs),
                "ready_queue": len(ready_queue),
                "prepared_at": timestamp,
            },
            ensure_ascii=False,
        )
    )


def command_route_failure(args: argparse.Namespace) -> None:
    if args.content_structure_overloaded or args.content_status == "needs_content_decision":
        route = "content_decision"
        next_action = "stop_and_request_batch_decision"
    elif args.content_status == "fail":
        route = "content_repair"
        next_action = "retry_same_page_with_content_fix"
    elif args.spatial_status == "fail":
        route = "visual_repair"
        next_action = "retry_same_page_with_visual_fix"
    elif args.craft_status == "fail":
        route = "visual_repair"
        next_action = "retry_same_page_with_craft_fix"
    elif (
        args.content_status == "pass"
        and args.spatial_status in {"pass", "not_applicable"}
        and args.craft_status in {"pass", "not_applicable"}
    ):
        route = "accept"
        next_action = "complete"
    else:
        raise SystemExit("内容门、空间门与工艺门组合无有效路由")
    print(
        json.dumps(
            {"route": route, "next_action": next_action}, ensure_ascii=False
        )
    )


def parse_time(value: str) -> datetime:
    try:
        normalized = value.strip()
        if normalized.endswith(("Z", "z")):
            normalized = normalized[:-1] + "+00:00"
        return datetime.fromisoformat(normalized)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"无效 ISO 时间：{value}") from exc


def validate_order(timing: dict[str, Any], names: list[str], errors: list[str]) -> None:
    available = [(name, timing.get(name)) for name in names if timing.get(name)]
    for (left_name, left_value), (right_name, right_value) in zip(available, available[1:]):
        try:
            if parse_time(left_value) > parse_time(right_value):
                errors.append(f"时间倒序：{left_name} > {right_name}")
        except (ValueError, TypeError) as exc:
            errors.append(str(exc))


def validate_event_audit_v2(
    state: dict[str, Any], errors: list[str], *, complete: bool
) -> None:
    events = state.get("events")
    if not isinstance(events, list):
        errors.append("v2 state.events 必须是数组")
        return
    previous_recorded: datetime | None = None
    positions: dict[str, list[int]] = {}
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            errors.append(f"events[{index - 1}] 必须是对象")
            continue
        if event.get("sequence") != index:
            errors.append(f"events[{index - 1}].sequence 应为 {index}")
        name = event.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"events[{index - 1}] 缺少 name")
        else:
            positions.setdefault(name, []).append(index)
        for field in ("occurred_at", "recorded_at"):
            value = event.get(field)
            if not isinstance(value, str):
                errors.append(f"events[{index - 1}] 缺少 {field}")
                continue
            try:
                parsed = parse_time(value)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if field == "recorded_at":
                if previous_recorded is not None:
                    try:
                        if previous_recorded > parsed:
                            errors.append("events.recorded_at 必须按追加顺序非递减")
                    except TypeError:
                        errors.append("events.recorded_at 时区格式不一致")
                previous_recorded = parsed

    # Re-running a failed terminal audit may have rebuilt the exact same formal
    # overview before the controller discovered a later blocker.  Preserve those
    # append-only attempts as retry evidence, but only when their semantic payload
    # is identical.  All other global events remain strictly unique.
    retryable_identical_events = {"formal_overview_completed"}
    unique_events = set(GLOBAL_EVENTS) | {"task_package_completed"}
    for name in sorted(unique_events):
        indexes = positions.get(name, [])
        if len(indexes) <= 1:
            continue
        if name in retryable_identical_events:
            detail_signatures = {
                json.dumps(events[index - 1].get("details") or {}, ensure_ascii=False, sort_keys=True)
                for index in indexes
            }
            if len(detail_signatures) == 1:
                continue
        errors.append(f"v2 全局事件 {name} 不得重复")

    causal_names = [
        "process_started",
        "preflight_resolved",
        "style_jobs_created",
        "task_package_completed",
        "initial_anchor_dispatch",
        "all_anchor_tools_completed",
        "formal_overview_completed",
        "process_completed",
    ]
    if complete:
        for name in causal_names:
            if not positions.get(name):
                errors.append(f"v2 完整验收缺少事件 {name}")
    present = [
        (
            name,
            positions[name][-1]
            if name in retryable_identical_events
            else positions[name][0],
        )
        for name in causal_names
        if positions.get(name)
    ]
    for (left_name, left), (right_name, right) in zip(present, present[1:]):
        if left >= right:
            errors.append(f"事件追加因果倒序：{left_name} >= {right_name}")

    timing = state.get("timing") or {}
    event_to_timing = {
        **GLOBAL_EVENTS,
        "task_package_completed": "task_package_completed_at",
    }
    for name, field in event_to_timing.items():
        indexes = positions.get(name) or []
        if not indexes:
            continue
        event_index = (
            indexes[-1]
            if name in retryable_identical_events
            else indexes[0]
        )
        event = events[event_index - 1]
        if timing.get(field) and event.get("occurred_at") != timing.get(field):
            errors.append(f"事件 {name} 与 timing.{field} 不一致")


def gate_status(record: dict[str, Any], name: str) -> str | None:
    gate = record.get(name)
    if gate is None:
        return None
    if not isinstance(gate, dict):
        return "invalid"
    status = gate.get("status")
    return status if isinstance(status, str) else "invalid"


def validate_page_audit_v2(
    state: dict[str, Any],
    record: dict[str, Any],
    label: str,
    errors: list[str],
    *,
    complete: bool,
) -> None:
    stage = record.get("qa_stage")
    scope = record.get("qa_scope")
    if stage not in QA_STAGES:
        errors.append(f"{label} qa_stage 无效：{stage!r}")
    if scope not in QA_SCOPES:
        errors.append(f"{label} qa_scope 无效：{scope!r}")
    if not complete and stage is None and scope is None:
        return
    if complete and (stage is None or scope is None):
        errors.append(f"{label} 完整验收缺少 qa_stage/qa_scope")
        return

    statuses = {
        name: gate_status(record, name)
        for name in ("content_gate", "spatial_gate", "craft_gate")
    }
    if stage == "filesystem":
        if scope != "filesystem_only":
            errors.append(f"{label} filesystem 必须配 qa_scope=filesystem_only")
        for name, status in statuses.items():
            if status not in {None, "not_applicable"}:
                errors.append(f"{label} 文件检查不得把 {name} 写成 {status}")
    elif scope == "filesystem_only":
        errors.append(f"{label} filesystem_only 必须配 qa_stage=filesystem")
    elif scope == "content_only":
        if stage not in {"visual_worker", "worker"}:
            errors.append(f"{label} content_only 必须由对话外视觉 QA 运行时执行")
        if statuses["content_gate"] not in {"pass", "fail", "needs_content_decision"}:
            errors.append(f"{label} content_only 缺少合法 content_gate")
        for name in ("spatial_gate", "craft_gate"):
            if statuses[name] != "not_applicable":
                errors.append(f"{label} content_only 的 {name} 必须为 not_applicable")
    elif scope == "full_visual":
        if stage not in {"visual_worker", "worker"}:
            errors.append(f"{label} full_visual 必须由视觉 Worker 执行")
        if statuses["content_gate"] not in {"pass", "fail", "needs_content_decision"}:
            errors.append(f"{label} full_visual 的 content_gate 无效")
        for name in ("spatial_gate", "craft_gate"):
            if statuses[name] not in {"pass", "fail", "not_applicable"}:
                errors.append(f"{label} full_visual 的 {name} 无效")
    elif scope not in {None, "filesystem_only"}:
        errors.append(f"{label} qa_stage/qa_scope 组合无效")

    events = state.get("events") or []
    if "/" in label:
        style_label, page_label = label.split("/", 1)
        event_style = style_label.removeprefix("style_")
    else:
        event_style = None
        page_label = label
    recovery_events = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("style") == event_style
        and str(event.get("page_id")) == page_label
        and event.get("name")
        in {"artifact_recovery_started", "artifact_recovery_finished"}
    ]
    started = [event for event in recovery_events if event.get("name") == "artifact_recovery_started"]
    finished = [
        event for event in recovery_events if event.get("name") == "artifact_recovery_finished"
    ]
    recovery_required = bool(record.get("recovery_required") or recovery_events)
    if recovery_required:
        if not record.get("artifact_recovery_started_at"):
            errors.append(f"{label} 恢复流程缺少 artifact_recovery_started_at")
        if not record.get("artifact_recovery_finished_at"):
            errors.append(f"{label} 恢复流程缺少 artifact_recovery_finished_at")
        if len(started) != len(finished) or not started:
            errors.append(f"{label} 恢复开始/结束事件必须成对")
        if int(record.get("recovery_attempt_count") or 0) != len(started):
            errors.append(f"{label} recovery_attempt_count 与恢复事件不一致")
        for left, right in zip(started, finished):
            if int(left.get("sequence") or 0) >= int(right.get("sequence") or 0):
                errors.append(f"{label} 恢复事件顺序倒置")
            try:
                if parse_time(left.get("occurred_at")) > parse_time(
                    right.get("occurred_at")
                ):
                    errors.append(f"{label} 恢复事件时间倒置")
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))
            left_details = left.get("details") or {}
            right_details = right.get("details") or {}
            for field in ("source_action", "attempt"):
                if (
                    left_details.get(field) not in {None, ""}
                    and right_details.get(field) not in {None, ""}
                    and left_details.get(field) != right_details.get(field)
                ):
                    errors.append(f"{label} 恢复事件 {field} 不一致")
        recovery_status = record.get("recovery_status")
        if recovery_status not in {"recovered", "not_found", "failed"}:
            errors.append(f"{label} 完成时 recovery_status 无效：{recovery_status!r}")
        if recovery_status == "recovered" and not record.get("selected_source"):
            errors.append(f"{label} recovered 但未绑定 selected_source")
        if (
            complete
            and recovery_status in {"not_found", "failed"}
            and int(record.get("attempt_count") or 0) <= 1
        ):
            errors.append(f"{label} 恢复未成功且没有合法技术重试")
    elif any(
        record.get(field)
        for field in (
            "artifact_recovery_started_at",
            "artifact_recovery_finished_at",
            "recovery_status",
            "recovery_attempt_count",
        )
    ):
        errors.append(f"{label} 未声明恢复却含恢复状态")


def validate_dispatch_audit_v2(
    state: dict[str, Any], errors: list[str], *, complete: bool
) -> None:
    mode = state.get("run_mode") or state.get("mode")
    if mode not in {QUICK_8X1_MODE, FAST8_MODE, FAST_4X3_MODE}:
        return
    scheduler = state.get("scheduler") or {}
    if scheduler.get("dispatch_policy") != "direct_fanout":
        return
    anchor_page_id = str(state.get("anchor_page_id"))
    events = state.get("events") or []
    waves = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("name") == "dispatch_wave"
    ]
    backpressure = {
        (event.get("details") or {}).get("wave_id"): event
        for event in events
        if isinstance(event, dict) and event.get("name") == "runtime_backpressure"
    }
    started: set[str] = set()
    for wave in waves:
        details = wave.get("details") or {}
        wave_id = details.get("wave_id")
        started_tasks = details.get("started_tasks")
        if isinstance(started_tasks, list):
            started.update(
                str(item.get("style"))
                for item in started_tasks
                if isinstance(item, dict)
                and item.get("action") == "generate_anchor"
                and str(item.get("page_id")) == anchor_page_id
            )
        elif (
            wave.get("action") == "generate_anchor"
            and str(wave.get("page_id")) == anchor_page_id
        ):
            started.update(details.get("started_styles") or [])
        deferred = details.get("deferred_tasks") or details.get("deferred_styles") or []
        if deferred:
            matching = backpressure.get(wave_id)
            reason = ((matching or {}).get("details") or {}).get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{wave_id} 缺少 runtime_backpressure 原因")
        elif wave_id in backpressure:
            errors.append(f"{wave_id} 无延迟席位却记录了 runtime_backpressure")
    if complete:
        expected = set(styles_for_mode(mode))
        if started != expected:
            errors.append(
                "v2 direct_fanout 派发事件未覆盖全部席位："
                f"expected={sorted(expected)} actual={sorted(started)}"
            )
        if mode == FAST_4X3_MODE and (
            (state.get("fast4x3_candidate_policy") or {}).get("version") in {2, 3}
        ):
            dispatched_tasks: set[tuple[str, str, str]] = set()
            for event in events:
                if not isinstance(event, dict) or event.get("name") != "dispatch_wave":
                    continue
                details = event.get("details") or {}
                started_tasks = details.get("started_tasks")
                if isinstance(started_tasks, list):
                    for item in started_tasks:
                        if not isinstance(item, dict):
                            continue
                        dispatched_tasks.add(
                            (
                                str(item.get("style")),
                                str(item.get("page_id")),
                                str(item.get("action")),
                            )
                        )
                elif event.get("page_id") and event.get("action"):
                    for style in details.get("started_styles") or []:
                        dispatched_tasks.add(
                            (str(style), str(event.get("page_id")), str(event.get("action")))
                        )
            expected_tasks = {
                (style, anchor_page_id, "generate_anchor") for style in FULL_STYLES
            }
            expected_tasks.update(
                (style, str(page_id), "generate_follower")
                for page_id in state.get("follower_page_ids") or []
                for style in FULL_STYLES
            )
            missing_tasks = expected_tasks - dispatched_tasks
            if missing_tasks:
                errors.append(
                    "Fast 4x3 v6 派发审计未覆盖全部 12 个精确任务："
                    f"missing={sorted(missing_tasks)}"
                )


def completed_page_errors(
    record: dict[str, Any], label: str, quality_contract_version: int | None = None
) -> list[str]:
    errors: list[str] = []
    required = [
        "agent_action_started_at",
        "tool_started_at",
        "tool_finished_at",
        "file_validated_at",
        "agent_action_finished_at",
        "overview_qa_at",
        "completed_at",
        "tool_call_id",
        "selected_source",
        "final_path",
    ]
    for field in required:
        if not record.get(field):
            errors.append(f"{label} 缺少 {field}")
    try:
        validate_timestamp_chain(
            [
                ("agent_action_started_at", record.get("agent_action_started_at")),
                ("tool_started_at", record.get("tool_started_at")),
                ("tool_finished_at", record.get("tool_finished_at")),
                ("agent_action_finished_at", record.get("agent_action_finished_at")),
                ("file_validated_at", record.get("file_validated_at")),
                ("completed_at", record.get("completed_at")),
            ],
            label,
        )
        validate_timestamp_chain(
            [
                ("file_validated_at", record.get("file_validated_at")),
                ("overview_qa_at", record.get("overview_qa_at")),
            ],
            label,
        )
    except SystemExit as exc:
        errors.append(str(exc))
    if record.get("status") != "accepted":
        errors.append(f"{label} 未 accepted")
    if (record.get("content_gate") or {}).get("status") != "pass":
        errors.append(f"{label} content_gate 未通过")
    if (record.get("spatial_gate") or {}).get("status") not in {"pass", "not_applicable"}:
        errors.append(f"{label} spatial_gate 未通过")
    if quality_contract_version == 2 and (record.get("craft_gate") or {}).get("status") not in {
        "pass",
        "not_applicable",
    }:
        errors.append(f"{label} craft_gate 未通过")
    source = record.get("selected_source")
    if isinstance(source, str) and not Path(source).is_file():
        errors.append(f"{label} selected_source 不存在")
    final_path = record.get("final_path")
    if isinstance(final_path, str) and not Path(final_path).is_file():
        errors.append(f"{label} final_path 不存在")
    return errors


def completed_quick_candidate_errors(
    record: dict[str, Any],
    label: str,
    *,
    allow_targeted_anchor_repair: bool = False,
) -> list[str]:
    """Fast 候选只验证可交付，不伪装成正式内容/空间/工艺验收。"""

    errors: list[str] = []
    for field in (
        "agent_action_started_at",
        "tool_started_at",
        "tool_finished_at",
        "file_validated_at",
        "agent_action_finished_at",
        "overview_qa_at",
        "completed_at",
        "tool_call_id",
        "selected_source",
        "final_path",
    ):
        if not record.get(field):
            errors.append(f"{label} 缺少 {field}")
    try:
        if (
            record.get("artifact_binding_source") == "worker_session_dir"
            and record.get("timing_capture") == "worker_reported_late_receipt"
        ):
            # The PNG can become visible in the bound session directory before
            # the ImageGen RPC returns, and the Worker may write its receipt after
            # settlement validates that PNG.  Artifact visibility and tool/agent
            # completion are parallel observations; neither branch must finish
            # first, but both must remain inside the same action interval.
            validate_timestamp_chain(
                [
                    ("agent_action_started_at", record.get("agent_action_started_at")),
                    ("tool_started_at", record.get("tool_started_at")),
                    ("tool_finished_at", record.get("tool_finished_at")),
                    ("agent_action_finished_at", record.get("agent_action_finished_at")),
                    ("completed_at", record.get("completed_at")),
                ],
                label,
            )
            validate_timestamp_chain(
                [
                    ("agent_action_started_at", record.get("agent_action_started_at")),
                    ("file_validated_at", record.get("file_validated_at")),
                    ("completed_at", record.get("completed_at")),
                ],
                label,
            )
        else:
            validate_timestamp_chain(
                [
                    ("agent_action_started_at", record.get("agent_action_started_at")),
                    ("tool_started_at", record.get("tool_started_at")),
                    ("tool_finished_at", record.get("tool_finished_at")),
                    ("agent_action_finished_at", record.get("agent_action_finished_at")),
                    ("file_validated_at", record.get("file_validated_at")),
                    ("completed_at", record.get("completed_at")),
                ],
                label,
            )
        validate_timestamp_chain(
            [
                ("file_validated_at", record.get("file_validated_at")),
                ("overview_qa_at", record.get("overview_qa_at")),
            ],
            label,
        )
    except SystemExit as exc:
        errors.append(str(exc))
    if record.get("status") not in {"candidate_ready", "accepted"}:
        errors.append(f"{label} 未 candidate_ready")
    max_valid_sources = 2 if allow_targeted_anchor_repair else 1
    max_attempts = 3 if allow_targeted_anchor_repair else 2
    if len(record.get("attempt_sources") or []) > max_valid_sources:
        errors.append(f"{label} 在用户选择前保留的有效候选超过允许上限")
    if int(record.get("attempt_count") or 0) > max_attempts:
        if allow_targeted_anchor_repair:
            errors.append(f"{label} 超出一次定向锚点修复加技术重试的上限")
        else:
            errors.append(f"{label} 超出首轮调用加一次技术重试的上限")
    source = record.get("selected_source")
    if isinstance(source, str) and not Path(source).is_file():
        errors.append(f"{label} selected_source 不存在")
    final_path = record.get("final_path")
    if isinstance(final_path, str) and not Path(final_path).is_file():
        errors.append(f"{label} final_path 不存在")
    return errors


def atomic_copy_candidate(source: Path, target: Path) -> None:
    """Copy one candidate without overwriting a different formal artifact."""

    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"候选来源不存在：{source}")
    if target.is_file():
        if file_sha256(target) != file_sha256(source):
            raise SystemExit(f"正式候选路径已存在不同文件，拒绝覆盖：{target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(handle)
    try:
        shutil.copy2(source, temp_name)
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def run_record_event_silently(**values: Any) -> dict[str, Any]:
    """Reuse the audited event transition while keeping finalize output concise."""

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        command_record_event(argparse.Namespace(**values))
    return json.loads(captured.getvalue())


def reconcile_fast8_late_worker_receipts(
    state_path: Path, state: dict[str, Any]
) -> list[str]:
    """Upgrade controller fallback timing from valid receipts that arrived later.

    Candidate settlement remains immediate from the bound session directory.  This
    pass only replaces derived timing metadata when the later receipt is fully bound
    to the same job, worker, tool and selected PNG; it never changes the candidate.
    Invalid or absent receipts remain visible to the non-blocking health report.
    """

    if state.get("run_mode") != FAST8_MODE:
        return []
    project_dir = project_dir_for_state(state_path, state)
    results_dir = project_dir / "style_jobs" / "results"
    reconciled: list[str] = []

    def matching_dispatch_task(
        style: str, page_id: str, action: str, attempt: int
    ) -> dict[str, Any] | None:
        for event in reversed(state.get("events") or []):
            if not isinstance(event, dict) or event.get("name") != "dispatch_wave":
                continue
            for task in (event.get("details") or {}).get("started_tasks") or []:
                if (
                    isinstance(task, dict)
                    and task.get("style") == style
                    and str(task.get("page_id")) == page_id
                    and task.get("action") == action
                    and int(task.get("attempt") or 1) == attempt
                ):
                    return task
        return None

    def worker_bound_at(
        style: str, page_id: str, attempt: int, worker_id: str
    ) -> str | None:
        for binding in (state.get("scheduler") or {}).get(
            "worker_session_bindings", []
        ):
            if not isinstance(binding, dict):
                continue
            for task in binding.get("tasks") or []:
                if (
                    isinstance(task, dict)
                    and task.get("style") == style
                    and str(task.get("page_id")) == page_id
                    and int(task.get("attempt") or 1) == attempt
                    and task.get("worker_session_id") == worker_id
                ):
                    value = binding.get("bound_at")
                    return value if isinstance(value, str) else None
        return None

    for style in QUICK_STYLES:
        page_id = str(state.get("anchor_page_id"))
        record = page_record(state, style, page_id)
        if not str(record.get("timing_capture") or "").startswith("controller_"):
            continue
        selected_source_value = record.get("selected_source")
        worker_id = record.get("worker_agent_id")
        tool_call_id = record.get("tool_call_id")
        action = str(record.get("selected_action") or "generate_anchor")
        attempt = int(record.get("selected_attempt") or 1)
        if not all(
            isinstance(value, str) and value
            for value in (selected_source_value, worker_id, tool_call_id)
        ):
            continue
        selected_source = Path(str(selected_source_value)).expanduser().resolve()
        if not selected_source.is_file():
            continue
        task = matching_dispatch_task(style, page_id, action, attempt)
        if not isinstance(task, dict):
            continue
        job_path_value = task.get("generation_job_path")
        job_sha = task.get("generation_job_sha256")
        if not isinstance(job_path_value, str) or not isinstance(job_sha, str):
            continue
        job_path = Path(job_path_value).expanduser().resolve()
        if not job_path.is_file() or file_sha256(job_path) != job_sha:
            continue
        job = read_json(job_path)
        receipt_contract = job.get("worker_receipt") or {}
        receipt_path_value = receipt_contract.get("path")
        if not isinstance(receipt_path_value, str):
            continue
        receipt_path = Path(receipt_path_value).expanduser().resolve()
        try:
            require_path_within(receipt_path, results_dir, "Fast8 Worker 回执")
        except SystemExit:
            continue
        if not receipt_path.is_file():
            continue
        try:
            receipt = normalize_fast8_artifact_fields(read_json(receipt_path))
        except SystemExit:
            continue
        allowed_fields = {
            "worker_receipt_contract_version",
            "style",
            "page_id",
            "action",
            "attempt",
            "imagegen_input_fingerprint",
            "worker_agent_id",
            "tool_call_id",
            "savedPath",
            "tool_started_at",
            "tool_finished_at",
            "receipt_written_at",
            "tool_status",
            "failure_class",
            "tool_error_code",
            "error",
            "contains_image_payload",
        }
        if set(receipt) - allowed_fields:
            continue
        expected_identity = {
            "worker_receipt_contract_version": FAST8_WORKER_RECEIPT_CONTRACT_VERSION,
            "style": style,
            "page_id": page_id,
            "action": action,
            "attempt": attempt,
            "imagegen_input_fingerprint": job.get("imagegen_input_fingerprint"),
            "worker_agent_id": worker_id,
            "tool_call_id": tool_call_id,
            "contains_image_payload": False,
        }
        if any(receipt.get(key) != value for key, value in expected_identity.items()):
            continue
        if (
            receipt.get("tool_status") != "completed"
            or receipt.get("failure_class") is not None
            or receipt.get("error") not in {None, ""}
        ):
            continue
        receipt_source_value = receipt.get("savedPath")
        if not isinstance(receipt_source_value, str):
            continue
        receipt_source = Path(receipt_source_value).expanduser().resolve()
        if not receipt_source.is_file() or receipt_source != selected_source:
            continue
        tool_started_at = receipt.get("tool_started_at")
        tool_finished_at = receipt.get("tool_finished_at")
        receipt_written_at = receipt.get("receipt_written_at")
        if not all(
            isinstance(value, str) and value
            for value in (tool_started_at, tool_finished_at, receipt_written_at)
        ):
            continue
        try:
            started = parse_time(str(tool_started_at))
            finished = parse_time(str(tool_finished_at))
            written = parse_time(str(receipt_written_at))
            bound_value = worker_bound_at(style, page_id, attempt, str(worker_id))
            bound = parse_time(bound_value) if isinstance(bound_value, str) else None
        except ValueError:
            continue
        if started > finished or finished > written or (bound is not None and started < bound):
            continue
        record["tool_started_at"] = str(tool_started_at)
        record["tool_finished_at"] = str(tool_finished_at)
        record["agent_action_finished_at"] = str(receipt_written_at)
        record["timing_capture"] = "worker_reported_late_receipt"
        append_event(
            state,
            "worker_receipt_reconciled",
            str(receipt_written_at),
            style=style,
            page_id=page_id,
            action=action,
            details={
                "attempt": attempt,
                "tool_call_id": tool_call_id,
                "receipt_path": str(receipt_path),
                "candidate_unchanged": True,
            },
        )
        reconciled.append(style)

    if reconciled:
        atomic_write_json(state_path, state)
    return reconciled


def command_finalize_fast8(args: argparse.Namespace) -> None:
    """Finalize a passed Fast8 run, including overview, handoff, audit and delivery."""

    state_path = Path(args.state).expanduser().resolve()
    state = read_json(state_path)
    if state.get("run_mode") != FAST8_MODE:
        raise SystemExit("finalize-fast8 只适用于 fast_8x1_diverse")
    project_dir = project_dir_for_state(state_path, state)
    if state.get("status") == "completed":
        captured_validation = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured_validation):
                command_validate_state(
                    argparse.Namespace(state=str(state_path), complete=True)
                )
        except SystemExit as exc:
            raise SystemExit(
                "既有 Fast8 完整状态审计失败："
                + captured_validation.getvalue().strip()
            ) from exc
        from build_fast8_delivery_message import build_message
        from validate_delivery_text import validate_text

        delivery_path, delivery_text = build_message(state, state_path)
        violations = validate_text(
            delivery_text,
            require_link=True,
            fast8_links_only=True,
            project_dir=project_dir,
        )
        if violations:
            raise SystemExit("既有 Fast8 交付文本校验失败：" + json.dumps(violations, ensure_ascii=False))
        print(
            json.dumps(
                {
                    "status": "already_completed",
                    "state": str(state_path),
                    "overview": (state.get("overview") or {}).get("final_path"),
                    "delivery_message": str(delivery_path),
                    "link_count": 9,
                },
                ensure_ascii=False,
            )
        )
        return
    # Late receipts are optional telemetry. The bound session's unique PNG is
    # already the success fact; do not mutate timing or delay delivery while
    # reconciling late Worker metadata in the critical path.
    review = state.get("diversity_review") or {}
    if review.get("status") not in {"pass", "best_effort"}:
        raise SystemExit("finalize-fast8 前必须先应用覆盖当前 A-H 的最终 Judge 报告")
    current_set_sha = fast8_candidate_set_sha256(fast8_candidate_manifest(state))
    if review.get("final_candidate_set_sha256") != current_set_sha:
        raise SystemExit("finalize-fast8 的 Judge 报告未绑定当前 A-H 候选集合")
    scheduler = state.get("scheduler") or {}
    nonempty = [
        name
        for name in ("active_actions", "ready_queue", "recovery_queue")
        if scheduler.get(name)
    ]
    if nonempty:
        raise SystemExit("finalize-fast8 前调度队列必须为空：" + ", ".join(nonempty))

    page_id = str(state.get("anchor_page_id"))
    finalized_paths: dict[str, str] = {}
    gate_reason = {
        "content_gate": {
            "status": "not_applicable",
            "reason": "Fast8 selection-stage candidate; no formal content gate claimed",
        },
        "spatial_gate": {
            "status": "not_applicable",
            "reason": "Fast8 selection-stage candidate; no formal spatial gate claimed",
        },
        "craft_gate": {
            "status": "not_applicable",
            "reason": "Fast8 Judge only checked severe minimum-craft degradation",
        },
    }
    for style in QUICK_STYLES:
        state = read_json(state_path)
        record = page_record(state, style, page_id)
        source_value = record.get("selected_source")
        if not isinstance(source_value, str) or not source_value:
            raise SystemExit(f"style_{style}/{page_id} 缺少已结算候选")
        source = Path(source_value).expanduser().resolve()
        _, _, size_bytes, source_sha = png_metadata(source)
        target = origin_image_target(project_dir, style, page_id).resolve()
        atomic_copy_candidate(source, target)
        finalized_paths[style] = str(target)
        if record.get("status") == "candidate_ready":
            if record.get("final_path") != str(target):
                raise SystemExit(f"style_{style}/{page_id} 既有 final_path 与标准路径不一致")
            continue
        event_at = now_iso()
        run_record_event_silently(
            state=str(state_path),
            event="overview_qa",
            style=style,
            page_id=page_id,
            action=None,
            timestamp=event_at,
            details_json=json.dumps(
                {"qa_stage": "filesystem", "qa_scope": "filesystem_only"},
                ensure_ascii=False,
            ),
        )
        run_record_event_silently(
            state=str(state_path),
            event="page_completed",
            style=style,
            page_id=page_id,
            action=None,
            timestamp=event_at,
            details_json=json.dumps(
                {
                    "completion_status": "candidate_ready",
                    "final_path": str(target),
                    "source_sha256": source_sha,
                    "source_size_bytes": size_bytes,
                    "qa_stage": "filesystem",
                    "qa_scope": "filesystem_only",
                    **gate_reason,
                },
                ensure_ascii=False,
            ),
        )

    state = read_json(state_path)
    overview_path = project_dir / "overview" / "ABCDEFGH_2x4.png"
    requested_matrix_python = getattr(args, "overview_python", None)
    bound_matrix_python = (state.get("overview_runtime") or {}).get("python")
    startup_fast8 = (
        state.get("fast8_startup_contract_version")
        == FAST8_STARTUP_CONTRACT_VERSION
    )
    if startup_fast8 and requested_matrix_python:
        raise SystemExit(
            "新 Fast8 的总览 Python 已在启动阶段绑定；finalize-fast8 不接受覆盖参数"
        )
    if startup_fast8 and not bound_matrix_python:
        raise SystemExit("新 Fast8 启动绑定的总览 Python 缺失，禁止在收口阶段补写")
    matrix_python = requested_matrix_python or bound_matrix_python
    if requested_matrix_python and bound_matrix_python:
        if Path(requested_matrix_python).expanduser().resolve() != Path(
            bound_matrix_python
        ).expanduser().resolve():
            raise SystemExit("finalize-fast8 不得替换 prepare 阶段绑定的总览 Python")
    if matrix_python:
        matrix_python_path = Path(matrix_python).expanduser().resolve()
        if not matrix_python_path.is_file():
            raise SystemExit(f"Fast8 总览 Python 不存在：{matrix_python_path}")
        matrix = subprocess.run(
            [
                str(matrix_python_path),
                str(SCRIPT_DIR / "build_style_matrix.py"),
                "--project-dir",
                str(project_dir),
                "--pages",
                page_id,
                "--styles",
                ",".join(QUICK_STYLES),
                "--output",
                str(overview_path),
                "--source-state",
                str(state_path),
                "--cell-width",
                "1280",
                "--header-height",
                "120",
                "--row-label-width",
                "180",
                "--gap",
                "24",
                "--ratio-tolerance",
                "0.02",
            ],
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if matrix.returncode != 0 or not overview_path.is_file():
            raise SystemExit(
                "Fast8 正式总览生成失败："
                + (matrix.stderr.strip() or matrix.stdout.strip() or "unknown error")
            )
    else:
        from build_style_matrix import build_matrix

        matrix_output = io.StringIO()
        with contextlib.redirect_stdout(matrix_output):
            invalid = build_matrix(
                project_dir=project_dir,
                styles=list(QUICK_STYLES),
                pages=[page_id],
                output=overview_path,
                cell_width=1280,
                header_height=120,
                row_label_width=180,
                gap=24,
                ratio_tolerance=0.02,
                source_state=state,
                allow_invalid=False,
            )
        if invalid:
            raise SystemExit("正式 Fast8 总览包含无效候选")
    overview_details = {
        "output_path": str(overview_path),
        "candidate_count": 8,
        "layout": "2x4",
        "diversity_status": review.get("status"),
    }
    state = read_json(state_path)
    prior_overview_events = [
        event
        for event in state.get("events") or []
        if isinstance(event, dict) and event.get("name") == "formal_overview_completed"
    ]
    if prior_overview_events:
        prior = prior_overview_events[-1]
        if (prior.get("details") or {}) != overview_details:
            raise SystemExit("既有 formal_overview_completed 与当前正式总览不一致")
        overview_at = str(prior.get("occurred_at"))
    else:
        overview_at = now_iso()
        run_record_event_silently(
            state=str(state_path),
            event="formal_overview_completed",
            style=None,
            page_id=None,
            action=None,
            timestamp=overview_at,
            details_json=json.dumps(overview_details, ensure_ascii=False),
        )

    # Build and validate the exact user-visible link payload before sealing the
    # completion timestamp.  This makes process_completed a delivery-ready
    # boundary rather than merely an internal-state boundary.
    from build_fast8_delivery_message import build_message
    from validate_delivery_text import validate_text

    delivery_ready_state = read_json(state_path)
    delivery_path, delivery_text = build_message(delivery_ready_state, state_path)
    violations = validate_text(
        delivery_text,
        require_link=True,
        fast8_links_only=True,
        project_dir=project_dir,
    )
    if violations:
        raise SystemExit(
            "Fast8 九链接交付文本校验失败："
            + json.dumps(violations, ensure_ascii=False)
        )
    completed_at = now_iso()
    completion_result = run_record_event_silently(
        state=str(state_path),
        event="process_completed",
        style=None,
        page_id=None,
        action=None,
        timestamp=completed_at,
        details_json=json.dumps(
            {
                "formal_candidate_count": 8,
                "overview_layout": "2x4",
                "diversity_status": review.get("status"),
                "global_chrome_status": (state.get("global_chrome_review") or {}).get(
                    "status", "not_applicable"
                ),
                "unresolved_issues": [],
            },
            ensure_ascii=False,
        ),
    )
    captured_validation = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured_validation):
            command_validate_state(
                argparse.Namespace(state=str(state_path), complete=True)
            )
    except SystemExit as exc:
        raise SystemExit(
            "finalize-fast8 完整状态审计失败：" + captured_validation.getvalue().strip()
        ) from exc
    validation_result = json.loads(captured_validation.getvalue())

    final_state = read_json(state_path)
    # Rebuild idempotently from the sealed state to ensure the final paths are
    # byte-for-byte identical to the pre-seal delivery-ready payload.
    final_delivery_path, final_delivery_text = build_message(final_state, state_path)
    if final_delivery_path != delivery_path or final_delivery_text != delivery_text:
        raise SystemExit("Fast8 封存前后交付文本不一致")
    print(
        json.dumps(
            {
                "status": "completed",
                "state": str(state_path),
                "overview": str(overview_path),
                "handoff": str(project_dir / "state" / "handoff.json"),
                "delivery_message": str(delivery_path),
                "link_count": 9,
                "validate_state": validation_result.get("status"),
                "monitoring": completion_result.get("monitoring"),
                "formal_candidates": finalized_paths,
            },
            ensure_ascii=False,
        )
    )


def command_validate_state(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    state = read_json(state_path)
    if args.complete:
        # Completion validation is an audit, not a state transition.  Warnings may
        # refresh the sidecar report, but the formally handed-off state must remain
        # byte-for-byte stable or its handoff hash becomes self-invalidating.
        enforce_source_guard(
            state_path,
            state,
            action="downstream_handoff",
            persist_state=False,
        )
    state_parent = state_path.parent
    project_dir = state_parent.parent if state_parent.name == "state" else state_parent
    errors: list[str] = []
    audit_version = state_audit_version(state)
    mode = state.get("run_mode") or state.get("mode")
    timing = state.get("timing") or {}
    if not isinstance(timing, dict):
        errors.append("timing 必须是对象")
        timing = {}
    anchor_dispatch_field = (
        "initial_anchor_dispatch_at"
        if timing.get("initial_anchor_dispatch_at")
        else "first_three_way_dispatch_at"
    )
    common_prefix = [
        "process_started_at",
        "preflight_decision_received_at",
        "preflight_resolved_at",
        "style_jobs_created_at",
        "task_package_completed_at",
        anchor_dispatch_field,
    ]
    if mode == FAST_4X3_MODE:
        # Fast 使用真实的渐进 DAG：首批 follower 可以早于最后一个 anchor 完成。
        validate_order(
            timing,
            common_prefix
            + [
                "first_fast_follower_tasks_ready_at",
                "follower_generation_started_at",
                "first_round_completed_at",
                "formal_overview_completed_at",
                "process_completed_at",
            ],
            errors,
        )
        validate_order(
            timing,
            common_prefix
            + [
                "all_anchor_tools_completed_at",
                "contracts_completed_at",
                "follower_tasks_ready_at",
                "first_round_completed_at",
                "formal_overview_completed_at",
                "process_completed_at",
            ],
            errors,
        )
    else:
        validate_order(
            timing,
            common_prefix
            + [
                "all_anchor_tools_completed_at",
                "anchor_qa_completed_at",
                "contracts_completed_at",
                "follower_tasks_ready_at",
                "follower_generation_started_at",
                "first_round_completed_at",
                "formal_overview_completed_at",
                "process_completed_at",
            ],
            errors,
        )
    preflight = state.get("preflight") or {}
    scheduler = state.get("scheduler") or {}
    if preflight.get("status") == "needs_user_decision":
        if scheduler.get("active_actions") or scheduler.get("ready_queue"):
            errors.append("等待用户决定时 active_actions 和 ready_queue 必须为空")
        if timing.get("style_jobs_created_at"):
            errors.append("等待用户决定时不得已有 style_jobs_created_at")
    if audit_version >= CURRENT_STATE_AUDIT_VERSION:
        validate_event_audit_v2(state, errors, complete=args.complete)
        validate_dispatch_audit_v2(state, errors, complete=args.complete)

    if args.complete:
        for field in (
            "process_started_at",
            "preflight_resolved_at",
            "formal_overview_completed_at",
            "process_completed_at",
        ):
            if not timing.get(field):
                errors.append(f"完整验收缺少 timing.{field}")
        if not isinstance(state.get("events"), list) or not state.get("events"):
            errors.append("完整验收要求非空 append-only events")
        quick_layout_version = (
            layout_portfolio_contract_version(state) if mode == QUICK_8X1_MODE else None
        )
        fast8_layout_version = (
            layout_portfolio_contract_version(state) if mode == FAST8_MODE else None
        )
        phase = state.get("phase")
        records: list[tuple[str, dict[str, Any]]] = []
        if mode in {
            STRICT_4X3_MODE,
            FAST_4X3_MODE,
            QUICK_8X1_MODE,
            FAST8_MODE,
            "quick_4x1",
        }:
            active_styles = styles_for_mode(mode)
            expected_pages = {
                STRICT_4X3_MODE: 12,
                FAST_4X3_MODE: 12,
                QUICK_8X1_MODE: 8,
                FAST8_MODE: 8,
                "quick_4x1": 4,
            }[mode]
            for style in active_styles:
                pages = ((state.get("styles") or {}).get(style) or {}).get("pages") or {}
                for page_id, record in pages.items():
                    if isinstance(record, dict):
                        records.append((f"style_{style}/{page_id}", record))
            if len(records) != expected_pages:
                errors.append(f"{mode} 应有 {expected_pages} 个页面记录，实际 {len(records)}")
            if mode in {QUICK_8X1_MODE, FAST8_MODE, "quick_4x1"}:
                anchor_page_id = str(state.get("anchor_page_id"))
                for style in active_styles:
                    style_state = (state.get("styles") or {}).get(style) or {}
                    pages = style_state.get("pages") or {}
                    if set(map(str, pages)) != {anchor_page_id}:
                        errors.append(f"{mode} 的 style_{style} 必须且只能包含共同锚点页")
                    expected_tone = tones_for_run(state, mode, active_styles)[style]
                    if style_state.get("tone") != expected_tone:
                        errors.append(
                            f"{mode} 的 style_{style}.tone 应为 {expected_tone}"
                        )
                if mode in {QUICK_8X1_MODE, "quick_4x1"} and len(
                    state.get("deferred_pages") or []
                ) != 2:
                    errors.append(f"{mode} 必须保留两个 deferred_pages")
                if (
                    mode == FAST8_MODE
                    and state.get("fast8_startup_contract_version")
                    == FAST8_STARTUP_CONTRACT_VERSION
                    and (
                        state.get("follower_page_ids")
                        or state.get("deferred_pages")
                    )
                ):
                    errors.append("新 Fast8 单页探索不得包含 follower/deferred 页面")
                if mode == QUICK_8X1_MODE:
                    if scheduler.get("active_child_limit") != QUICK8_ACTIVE_CHILD_LIMIT:
                        errors.append("quick_8x1 的 active_child_limit 必须为 8")
                    if scheduler.get("requested_initial_wave") != 8:
                        errors.append("quick_8x1 必须请求八个锚点同波派发")
                    if quick_layout_version in ONE_SHOT_QUICK_LAYOUT_VERSIONS:
                        if scheduler.get("dispatch_policy") != "direct_fanout":
                            errors.append("quick8 v4/v5 的 dispatch_policy 必须为 direct_fanout")
                        if scheduler.get("root_dispatch_wave") != 8:
                            errors.append("quick8 v4/v5 必须由主 Agent 直接同波派发 A-H")
                        policy = state.get("quick8_candidate_policy") or {}
                        if policy.get("automatic_visual_retries_before_selection") != 0:
                            errors.append("quick8 v4/v5 选择前不得自动视觉返修")
                    else:
                        if scheduler.get("dispatch_policy") != "two_branch_fanout":
                            errors.append("旧 quick8 v3 的 dispatch_policy 必须为 two_branch_fanout")
                        if scheduler.get("root_dispatch_wave") != 2:
                            errors.append("旧 quick8 v3 必须由两个组调度 Agent 同波扇出")
                        groups = scheduler.get("dispatch_groups") or {}
                        if groups.get("dark") != list(FULL_STYLES) or groups.get("light") != list(QUICK_STYLES[4:]):
                            errors.append("旧 quick8 v3 的深色/浅色派发组必须分别为 A-D/E-H")
                elif mode == FAST8_MODE:
                    if fast8_layout_version != CURRENT_FAST8_LAYOUT_VERSION:
                        errors.append("Fast8 必须使用 layout_portfolio v7")
                    if scheduler.get("active_child_limit") != FAST8_ACTIVE_CHILD_LIMIT:
                        errors.append("Fast8 的 active_child_limit 必须为 9")
                    if scheduler.get("image_child_limit") != 8:
                        errors.append("Fast8 的 image_child_limit 必须为 8")
                    if scheduler.get("diversity_judge_child_limit") != 1:
                        errors.append("Fast8 必须为隔离差异裁判保留一个子 Agent 槽位")
                    if scheduler.get("requested_initial_wave") != 8:
                        errors.append("Fast8 必须请求 A-H 八个初始锚点同波派发")
                    if scheduler.get("dispatch_policy") != "direct_fanout":
                        errors.append("Fast8 的 dispatch_policy 必须为 direct_fanout")
                    if scheduler.get("root_dispatch_wave") != 8:
                        errors.append("Fast8 必须由主 Agent 直接同波派发 A-H")
                    if (
                        state.get("fast8_startup_contract_version")
                        == FAST8_STARTUP_CONTRACT_VERSION
                    ):
                        runtime = state.get("overview_runtime") or {}
                        if (
                            runtime.get("pillow_preflight") != "pass"
                            or not runtime.get("python")
                            or runtime.get("binding_policy")
                            != "startup_bound_reuse_for_formal_overview"
                        ):
                            errors.append("新 Fast8 缺少启动阶段固化的总览运行时")
                        startup_events = [
                            item.get("name")
                            for item in (state.get("events") or [])[:2]
                            if isinstance(item, dict)
                        ]
                        if startup_events != ["process_started", "preflight_resolved"]:
                            errors.append("新 Fast8 的前两个事件必须由启动脚本写入")
                    policy = state.get("fast8_candidate_policy") or {}
                    policy_version = policy.get("version")
                    if policy_version not in {
                        LEGACY_FAST8_CANDIDATE_POLICY_VERSION,
                        CURRENT_FAST8_CANDIDATE_POLICY_VERSION,
                    }:
                        errors.append("Fast8 缺少合法候选策略 v1/v2")
                    expected_prompt_version = (
                        CURRENT_FAST8_IMAGEGEN_PROMPT_VERSION
                        if policy_version == CURRENT_FAST8_CANDIDATE_POLICY_VERSION
                        else LEGACY_FAST8_IMAGEGEN_PROMPT_VERSION
                    )
                    if policy.get("max_total_diversity_replacements") != 2:
                        errors.append("Fast8 全运行差异替代上限必须为 2")
                    prompt_fingerprints: list[str] = []
                    topology_required = policy.get("spatial_topology_required") is True
                    topology_signatures: list[tuple[str, str, str]] = []
                    topology_primary_counts: dict[str, int] = {}
                    topology_region_logics: set[str] = set()
                    integrated_evidence_count = 0
                    quiet_band_count = 0
                    for style in QUICK_STYLES:
                        job_path = project_dir / "style_jobs" / f"style_{style}.json"
                        if not job_path.is_file():
                            errors.append(f"Fast8 缺少初始任务：{job_path}")
                            continue
                        job = read_json(job_path)
                        if (
                            job.get("imagegen_prompt_contract_version")
                            != expected_prompt_version
                        ):
                            errors.append(
                                f"Fast8 style_{style} 图片提示合同必须为 "
                                f"v{expected_prompt_version}"
                            )
                        if (job.get("layout_direction") or {}).get(
                            "layout_contract_version"
                        ) != CURRENT_FAST8_LAYOUT_VERSION:
                            errors.append(f"Fast8 style_{style} 缺少 layout v7 方向")
                        if topology_required:
                            try:
                                topology = validate_spatial_topology(
                                    (job.get("layout_direction") or {}).get(
                                        "spatial_topology"
                                    ),
                                    f"Fast8 style_{style}",
                                )
                                signature = (
                                    topology["primary_entry"],
                                    topology["region_logic"],
                                    topology["evidence_attachment"],
                                )
                                topology_signatures.append(signature)
                                topology_primary_counts[signature[0]] = (
                                    topology_primary_counts.get(signature[0], 0) + 1
                                )
                                topology_region_logics.add(signature[1])
                                if signature[2] in {"integrated", "annotated"}:
                                    integrated_evidence_count += 1
                                if signature[2] == "quiet_band":
                                    quiet_band_count += 1
                            except SystemExit as exc:
                                errors.append(str(exc))
                        prompt = job.get("imagegen_prompt")
                        fingerprint = job.get("imagegen_prompt_fingerprint")
                        if not isinstance(prompt, str) or not isinstance(
                            fingerprint, str
                        ):
                            errors.append(f"Fast8 style_{style} 缺少图片提示或独立指纹")
                        elif hashlib.sha256(prompt.encode("utf-8")).hexdigest() != fingerprint:
                            errors.append(f"Fast8 style_{style} 图片提示指纹不一致")
                        else:
                            prompt_fingerprints.append(fingerprint)
                    if len(prompt_fingerprints) == 8 and len(
                        set(prompt_fingerprints)
                    ) != 8:
                        errors.append("Fast8 八份初始图片提示必须逐份唯一")
                    if topology_required and len(topology_signatures) == 8:
                        if len(set(topology_signatures)) != 8:
                            errors.append("Fast8 A-H spatial_topology 完整签名必须互异")
                        if len(topology_primary_counts) < 4:
                            errors.append("Fast8 spatial_topology 至少需要 4 种主入口")
                        if any(count > 2 for count in topology_primary_counts.values()):
                            errors.append("Fast8 每种 spatial_topology 主入口最多 2 席")
                        if len(topology_region_logics) < 5:
                            errors.append("Fast8 spatial_topology 至少需要 5 种区域逻辑")
                        if quiet_band_count > 2:
                            errors.append("Fast8 quiet_band 证据附着最多 2 席")
                        if integrated_evidence_count < 3:
                            errors.append("Fast8 至少 3 席须整合或注释式附着次级证据")
                    chrome_review = state.get("global_chrome_review") or {}
                    if chrome_review.get("required") is True:
                        if chrome_review.get("status") != "pass":
                            errors.append("Fast8 完整验收要求 global chrome 硬合同审查通过")
                        contract_path_value = state.get("global_chrome_contract_path")
                        contract_sha = state.get("global_chrome_contract_sha256")
                        if not isinstance(contract_path_value, str) or not Path(
                            contract_path_value
                        ).is_file():
                            errors.append("Fast8 缺少可读 global chrome contract")
                        elif file_sha256(Path(contract_path_value)) != contract_sha:
                            errors.append("Fast8 global chrome contract SHA-256 不一致")
                        current_set_sha = None
                        try:
                            current_set_sha = fast8_candidate_set_sha256(
                                fast8_candidate_manifest(state)
                            )
                        except SystemExit as exc:
                            errors.append(str(exc))
                        if (
                            current_set_sha is not None
                            and chrome_review.get("candidate_set_sha256")
                            != current_set_sha
                        ):
                            errors.append("global chrome 审查未绑定当前 A-H 候选集合")
                    review = state.get("diversity_review") or {}
                    expected_judge_version = (
                        CURRENT_FAST8_JUDGE_CONTRACT_VERSION
                        if policy_version == CURRENT_FAST8_CANDIDATE_POLICY_VERSION
                        else LEGACY_FAST8_JUDGE_CONTRACT_VERSION
                    )
                    if review.get("contract_version") != expected_judge_version:
                        errors.append("Fast8 候选策略与 Judge 合同版本不一致")
                    if review.get("scope") != FAST8_JUDGE_SCOPES.get(
                        expected_judge_version
                    ):
                        errors.append("Fast8 候选策略与 Judge scope 不一致")
                    if review.get("status") not in {"pass", "best_effort"}:
                        errors.append("Fast8 完整验收要求差异裁判已收口")
                    try:
                        current_manifest = fast8_candidate_manifest(state)
                        current_set_sha = fast8_candidate_set_sha256(current_manifest)
                        if review.get("final_candidate_set_sha256") != current_set_sha:
                            errors.append("Fast8 最终差异报告未绑定当前 A-H 候选")
                    except SystemExit as exc:
                        errors.append(str(exc))
                    replacement_styles = review.get("replacement_styles") or []
                    if len(replacement_styles) > 2:
                        errors.append("Fast8 差异替代席位超过两个")
                    if int(review.get("replacement_count") or 0) != len(
                        replacement_styles
                    ):
                        errors.append("Fast8 replacement_count 与替代席位清单不一致")
                    if int(review.get("replacement_rounds_used") or 0) > 1:
                        errors.append("Fast8 差异替代轮次超过一轮")
                    repair_dispatch_styles = {
                        str(item.get("style"))
                        for event in (state.get("events") or [])
                        if isinstance(event, dict)
                        and event.get("name") == "dispatch_wave"
                        for item in ((event.get("details") or {}).get("started_tasks") or [])
                        if isinstance(item, dict)
                        and item.get("action") == "repair_anchor"
                        and item.get("diversity_replacement") is True
                    }
                    if set(replacement_styles) - repair_dispatch_styles:
                        errors.append("Fast8 差异替代缺少正式 repair_anchor 派发审计")
                direction_path = state.get("layout_portfolio_path") or state.get(
                    "exploration_seed_path"
                )
                if not isinstance(direction_path, str) or not Path(direction_path).is_file():
                    errors.append(f"{mode} 缺少主 Agent 的 layout_portfolio.json")
                state_parent = Path(args.state).resolve().parent
                project_dir = state_parent.parent if state_parent.name == "state" else state_parent
                forbidden = [
                    project_dir / "style_contract_seeds.json",
                    project_dir / "style_contracts",
                    project_dir / "style_page_jobs",
                ]
                if any(path.exists() for path in forbidden):
                    errors.append(f"{mode} 不得创建视觉种子、风格合同或跟随页任务")
            if (
                mode == STRICT_4X3_MODE
                and layout_portfolio_contract_version(state)
                == CURRENT_4X3_LAYOUT_VERSION
            ):
                if (
                    scheduler.get("active_child_limit")
                    != FOUR_BY_THREE_ACTIVE_CHILD_LIMIT
                ):
                    errors.append(
                        "新严格 4x3 的 active_child_limit 必须为 "
                        f"{FOUR_BY_THREE_ACTIVE_CHILD_LIMIT}"
                    )
                direction_path = state.get("layout_portfolio_path")
                if (
                    not isinstance(direction_path, str)
                    or not Path(direction_path).is_file()
                ):
                    errors.append("新严格 4x3 缺少 A-D layout_portfolio.json")
                for style in FULL_STYLES:
                    anchor_job_path = project_dir / "style_jobs" / f"style_{style}.json"
                    if not anchor_job_path.is_file():
                        errors.append(f"新严格 4x3 缺少锚点任务：{anchor_job_path}")
                    elif read_json(anchor_job_path).get(
                        "imagegen_prompt_contract_version"
                    ) != 4:
                        errors.append(f"新严格 4x3 的 style_{style} 锚点提示必须为 v4")
                    for page_id in state.get("follower_page_ids") or []:
                        job_path = (
                            project_dir
                            / "style_page_jobs"
                            / f"style_{style}"
                            / f"page_{page_id}.json"
                        )
                        if not job_path.is_file():
                            errors.append(f"新严格 4x3 缺少跟随任务：{job_path}")
                            continue
                        if read_json(job_path).get(
                            "imagegen_prompt_contract_version"
                        ) != 4:
                            errors.append(
                                f"新严格 4x3 的 style_{style}/{page_id} "
                                "缺少预编译 v4 图片提示"
                            )
            if mode == FAST_4X3_MODE:
                fast_layout_version = layout_portfolio_contract_version(state)
                expected_fast_child_limit = (
                    FOUR_BY_THREE_ACTIVE_CHILD_LIMIT
                    if fast_layout_version == CURRENT_4X3_LAYOUT_VERSION
                    else QUICK8_ACTIVE_CHILD_LIMIT
                )
                if scheduler.get("active_child_limit") != expected_fast_child_limit:
                    errors.append(
                        "fast_4x3_anchored 的 active_child_limit 必须为 "
                        f"{expected_fast_child_limit}"
                    )
                if scheduler.get("requested_initial_wave") != 4:
                    errors.append("fast_4x3_anchored 必须请求四个锚点同波派发")
                if scheduler.get("dispatch_policy") != "direct_fanout":
                    errors.append("fast_4x3_anchored 的 dispatch_policy 必须为 direct_fanout")
                if scheduler.get("root_dispatch_wave") != 4:
                    errors.append("fast_4x3_anchored 必须由主 Agent 直接同波派发 A-D")
                policy = state.get("fast4x3_candidate_policy") or {}
                if policy.get("version") in {2, 3} and fast_layout_version != CURRENT_4X3_LAYOUT_VERSION:
                    errors.append("新 Fast 4x3 必须使用 layout_portfolio v6")
                if policy.get("automatic_visual_retries_before_selection") != 0:
                    errors.append("Fast 4x3 选择前不得自动审美返修")
                if policy.get("automatic_spatial_retries_before_selection") != 0:
                    errors.append("Fast 4x3 选择前不得因空间偏好自动返修")
                if not (
                    policy.get("unified_spatial_standard_applies") is True
                    or policy.get("low_spatial_preference_is_soft") is True
                ):
                    errors.append("Fast 4x3 必须记录统一空间标准或 legacy Low 软目标")
                direction_path = state.get("layout_portfolio_path")
                if not isinstance(direction_path, str) or not Path(direction_path).is_file():
                    errors.append("fast_4x3_anchored 缺少 A-D layout_portfolio.json")
                for style in FULL_STYLES:
                    pages = ((state.get("styles") or {}).get(style) or {}).get("pages") or {}
                    if len(pages) != 3:
                        errors.append(f"Fast 4x3 的 style_{style} 必须包含三个候选页")
                    contract_path = ((state.get("styles") or {}).get(style) or {}).get(
                        "contract_path"
                    )
                    if not isinstance(contract_path, str) or not Path(contract_path).is_file():
                        errors.append(f"Fast 4x3 的 style_{style} 缺少候选风格合同")
                        continue
                    if policy.get("version") in {2, 3}:
                        contract = read_json(Path(contract_path))
                        expected_contract_version = 5 if policy.get("version") == 3 else 4
                        if contract.get("style_contract_version") != expected_contract_version:
                            errors.append(
                                f"Fast 4x3 policy v{policy.get('version')} 的 style_{style} "
                                f"合同必须为 v{expected_contract_version}"
                            )
                        for page_id in state.get("follower_page_ids") or []:
                            job_path = (
                                project_dir
                                / "style_page_jobs"
                                / f"style_{style}"
                                / f"page_{page_id}.json"
                            )
                            if not job_path.is_file():
                                errors.append(f"Fast 4x3 v6 缺少跟随任务：{job_path}")
                                continue
                            page_job = read_json(job_path)
                            if page_job.get("imagegen_prompt_contract_version") != 4:
                                errors.append(
                                    f"Fast 4x3 v6 的 style_{style}/{page_id} "
                                    "缺少预编译 v4 图片提示"
                                )
        elif phase == "selected_style_expansion":
            for page_id, record in (state.get("pages") or {}).items():
                if isinstance(record, dict):
                    records.append((str(page_id), record))
            if len(records) != len(state.get("page_order") or []):
                errors.append("扩页 page_order 与页面记录数量不一致")
        else:
            errors.append("无法识别运行模式")
        if audit_version >= CURRENT_STATE_AUDIT_VERSION:
            if scheduler.get("phase") != "completed":
                errors.append("v2 完整验收要求 scheduler.phase=completed")
            for queue_name in ("active_actions", "ready_queue", "recovery_queue"):
                if scheduler.get(queue_name):
                    errors.append(f"v2 完整验收要求 scheduler.{queue_name} 为空")
            for style, style_state in (state.get("styles") or {}).items():
                if (
                    isinstance(style_state, dict)
                    and style_state.get("workflow_status") != "ready_for_overview"
                ):
                    errors.append(
                        f"v2 完整验收要求 style_{style}.workflow_status="
                        "ready_for_overview"
                    )
        try:
            validate_unique_artifact_bindings(state, [])
        except SystemExit as exc:
            errors.append(str(exc))
        for label, record in records:
            if audit_version >= CURRENT_STATE_AUDIT_VERSION:
                validate_page_audit_v2(
                    state, record, label, errors, complete=True
                )
            if (
                mode in {FAST_4X3_MODE, FAST8_MODE}
                or (
                    mode == QUICK_8X1_MODE
                    and quick_layout_version in ONE_SHOT_QUICK_LAYOUT_VERSIONS
                )
            ):
                errors.extend(
                    completed_quick_candidate_errors(
                        record,
                        label,
                        allow_targeted_anchor_repair=(
                            mode in {FAST_4X3_MODE, FAST8_MODE}
                            and record.get("role") == "anchor"
                        ),
                    )
                )
            else:
                errors.extend(
                    completed_page_errors(
                        record, label, state.get("quality_contract_version")
                    )
                )
        overview_path = ((state.get("overview") or {}).get("final_path"))
        if not isinstance(overview_path, str) or not Path(overview_path).is_file():
            errors.append("完整验收缺少可读 overview.final_path")
        if state.get("status") != "completed":
            errors.append("完整验收要求顶层 status=completed")
        if source_guard_enabled(state_path, state) and state.get("status") == "completed":
            handoff_json_path = project_dir / "state" / "handoff.json"
            handoff_md_path = project_dir / "state" / "handoff.md"
            if not handoff_json_path.is_file() or not handoff_md_path.is_file():
                errors.append("完整验收缺少最终 handoff.json 或 handoff.md")
            else:
                try:
                    handoff = read_json(handoff_json_path)
                    if (handoff.get("state_ref") or {}).get("sha256") != file_sha256(
                        state_path
                    ):
                        errors.append("handoff.state_ref.sha256 与当前正式状态不一致")
                    if handoff_md_path.read_text(
                        encoding="utf-8"
                    ) != render_handoff_markdown(handoff):
                        errors.append("handoff.md 不是由当前 handoff.json 确定性重建")
                except (OSError, SystemExit) as exc:
                    errors.append(f"handoff 完整性检查失败：{exc}")

    result = {
        "status": "pass" if not errors else "fail",
        "error_count": len(errors),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser(
        "snapshot-source", help="封存权威源、本页规范化内容、内容合同和实际使用资产"
    )
    snapshot.add_argument("--project-dir", required=True)
    snapshot.add_argument("--state", required=True)
    snapshot.add_argument("--source-file", required=True)
    snapshot.add_argument("--page-ids", required=True)
    snapshot.add_argument(
        "--content-contract", action="append", required=True,
        help="可重复传入本次页面范围内的内容合同绝对路径",
    )
    snapshot.add_argument("--content-contracts-json")
    snapshot.add_argument("--assets-json", default="[]")
    snapshot.add_argument(
        "--supporting-sources-json",
        default="[]",
        help="仅供内容规划/证据追溯的来源路径；不会被当作 ImageGen 图片输入",
    )
    snapshot.add_argument("--source-fragment-file")
    snapshot.add_argument(
        "--slide-identity-file",
        help="可选的独立内容 UID 文件；只参与 source snapshot 和 handoff 元数据绑定",
    )
    snapshot.add_argument(
        "--source-fragment-authority",
        choices=("extractor_aid", "authoritative_page_fragment"),
        default="extractor_aid",
    )
    snapshot.add_argument("--timestamp")
    snapshot.set_defaults(func=command_snapshot_source)

    drift = subparsers.add_parser(
        "check-source-drift", help="在恢复、修复、扩页、续页或下游交接前检测来源漂移"
    )
    drift.add_argument("--state", required=True)
    drift.add_argument("--action", required=True)
    drift.add_argument("--timestamp")
    drift.add_argument(
        "--report-only",
        action="store_true",
        help="即使检测到阻断项也只输出报告并返回零；不得用于绕过正式门禁",
    )
    drift.set_defaults(func=command_check_source_drift)

    legacy_confirmation = subparsers.add_parser(
        "confirm-legacy-source-risk",
        help="仅在用户明确确认后记录旧任务无历史快照的兼容动作范围",
    )
    legacy_confirmation.add_argument("--state", required=True)
    legacy_confirmation.add_argument(
        "--actions",
        required=True,
        help="逗号分隔的正式动作；只授权列出的动作，不生成或补写历史哈希",
    )
    legacy_confirmation.add_argument("--timestamp")
    legacy_confirmation.add_argument("--confirmed-by")
    legacy_confirmation.add_argument("--confirmation-text")
    legacy_confirmation.add_argument("--user-confirmed", action="store_true")
    legacy_confirmation.set_defaults(func=command_confirm_legacy_source_risk)

    expansion_job = subparsers.add_parser(
        "check-expansion-job",
        help="在启动选定风格扩页 Agent 前校验正式页面任务及实际图片输入",
    )
    expansion_job.add_argument("--state", required=True)
    expansion_job.add_argument("--page-id", required=True)
    expansion_job.add_argument(
        "--action", required=True, choices=["generate_page", "repair_page"]
    )
    expansion_job.add_argument("--attempt", required=True, type=int)
    expansion_job.add_argument("--generation-job", required=True)
    expansion_job.set_defaults(func=command_check_expansion_job)

    handoff = subparsers.add_parser(
        "write-handoff", help="从正式状态和 source snapshot 生成 handoff.json 与 handoff.md"
    )
    handoff.add_argument("--state", required=True)
    handoff.add_argument("--project-dir")
    handoff.add_argument("--unresolved-issues-json")
    handoff.add_argument("--next-allowed-actions-json")
    handoff.add_argument("--timestamp")
    handoff.add_argument(
        "--refresh-state-ref",
        action="store_true",
        help="仅用于修复旧版完成态验证造成的 handoff/state 哈希失配；自动保留旧 handoff",
    )
    handoff.set_defaults(func=command_write_handoff)

    rebuild = subparsers.add_parser(
        "rebuild-handoff-md", help="仅从 handoff.json 确定性重建 handoff.md"
    )
    rebuild.add_argument("--handoff-json", required=True)
    rebuild.add_argument("--output")
    rebuild.set_defaults(func=command_rebuild_handoff_markdown)

    run_health = subparsers.add_parser(
        "write-run-health",
        help="从正式状态生成非视觉技术健康报告，并更新项目级集中监测索引",
    )
    run_health.add_argument("--state", required=True)
    run_health.add_argument(
        "--monitoring-root",
        help="覆盖 task_init.json 或用户配置中的项目级集中监测目录",
    )
    run_health.add_argument(
        "--terminal-outcome",
        choices=("superseded", "aborted", "blocked"),
        help="将未完成但已明确终止的真实任务登记到中央索引",
    )
    run_health.add_argument(
        "--outcome-reason",
        help="终止原因；与 --terminal-outcome 同时使用",
    )
    run_health.add_argument("--timestamp")
    run_health.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="仅用于中断任务诊断；正常完成态报告不得使用",
    )
    run_health.set_defaults(func=command_write_run_health)

    monitoring_index = subparsers.add_parser(
        "rebuild-monitoring-index",
        help="从 entries/ 确定性重建集中监测 index.json 与 index.md",
    )
    monitoring_index.add_argument("--monitoring-root", required=True)
    monitoring_index.add_argument("--timestamp")
    monitoring_index.set_defaults(func=command_rebuild_monitoring_index)

    event = subparsers.add_parser("record-event", help="原子记录时间事件")
    event.add_argument("--state", required=True)
    event.add_argument("--event", required=True, choices=sorted(GLOBAL_EVENTS | PAGE_EVENTS))
    event.add_argument("--style")
    event.add_argument("--page-id")
    event.add_argument("--action")
    event.add_argument("--timestamp")
    event.add_argument("--details-json")
    event.set_defaults(func=command_record_event)

    anchors = subparsers.add_parser(
        "prepare-anchors", help="按运行模式批量创建四个或八个锚点任务和初始队列"
    )
    anchors.add_argument("--project-dir", required=True)
    anchors.add_argument("--state", required=True)
    anchors.add_argument("--content-contract", required=True)
    anchors.add_argument("--overall-requirements", required=True)
    anchors.add_argument("--reference-images-json", default="[]")
    required_asset_input = anchors.add_mutually_exclusive_group()
    required_asset_input.add_argument("--required-assets-json")
    required_asset_input.add_argument(
        "--required-assets-file",
        help=(
            "推荐给 Fast8 导演输出：读取顶层数组或带规范页码的 v1 assets envelope；"
            "脚本验证路径、SHA、路由并确定性投影为运行时数组"
        ),
    )
    anchors.add_argument(
        "--global-chrome-contract",
        help=(
            "可选的全稿标题/页眉硬合同 JSON；必须有明确来源授权，"
            "由脚本按页与 tone 短编译并单独路由 Logo 资产"
        ),
    )
    anchors.add_argument(
        "--source-file",
        help="新运行可在首次 prepare-anchors 时同时封存权威源；旧运行省略即可",
    )
    anchors.add_argument(
        "--slide-identity-file",
        help="可选的独立内容 UID 文件；不进入提示词、Director、Judge 或重试逻辑",
    )
    anchors.add_argument(
        "--source-page-ids",
        help="source snapshot 的相关页面；省略时按当前模式从状态推导",
    )
    anchors.add_argument("--source-fragment-file")
    anchors.add_argument(
        "--source-fragment-authority",
        choices=("extractor_aid", "authoritative_page_fragment"),
        default="extractor_aid",
    )
    anchors.add_argument("--snapshot-content-contracts-json")
    anchors.add_argument("--source-snapshot-timestamp")
    anchors.add_argument(
        "--layout-portfolio",
        help=(
            "fast_8x1_diverse、quick_8x1 与两种 4x3 新运行必填："
            "主 Agent 针对当前页面编写的 layout_portfolio.json"
        ),
    )
    anchors.add_argument(
        "--overview-python",
        help=(
            "仅供旧 Fast8 在 prepare 阶段补绑定预检过 Pillow 的 Python；"
            "新运行由 init_task_dir 固定"
        ),
    )
    anchors.set_defaults(func=command_prepare_anchors)

    dispatch = subparsers.add_parser(
        "record-dispatch-wave", help="批量记录 Fast 候选同波图片 Agent 派发"
    )
    dispatch.add_argument("--state", required=True)
    dispatch.add_argument(
        "--styles",
        help="同页同动作的席位列表；省略时自动使用当前模式全部席位",
    )
    dispatch.add_argument(
        "--tasks-json",
        help=(
            "可选：一次记录跨页异构任务数组；每项包含 "
            "style,page_id,action,attempt。提供后忽略 --styles/--page-id/--action。"
        ),
    )
    dispatch.add_argument("--page-id")
    dispatch.add_argument("--action", default="generate_anchor")
    dispatch.add_argument("--attempt", type=int, default=1)
    dispatch.add_argument("--timestamp")
    dispatch.add_argument("--agent-map-json")
    dispatch.add_argument(
        "--backpressure-reason",
        help="实际只派发当前可派任务的一部分时，记录运行时限制原因",
    )
    dispatch.set_defaults(func=command_record_dispatch_wave)

    bind_sessions = subparsers.add_parser(
        "bind-fast8-worker-sessions",
        help="把 create-agent 返回的真实 Agent UUID 绑定到已授权 Fast8 图片任务",
    )
    bind_sessions.add_argument("--state", required=True)
    bind_sessions.add_argument("--session-map-json", required=True)
    bind_sessions.add_argument("--styles", help="可选：只绑定指定席位，例如 A,C,F")
    bind_sessions.add_argument(
        "--model",
        help="新 Fast8 Worker 的实际模型；ticket v2 必须与正式运行时合同一致",
    )
    bind_sessions.add_argument(
        "--reasoning-effort",
        help="新 Fast8 Worker 的实际 reasoning effort；ticket v2 必须匹配",
    )
    bind_sessions.add_argument(
        "--fork-turns",
        help="新 Fast8 Worker 的实际 fork_turns；ticket v2 必须匹配",
    )
    bind_sessions.add_argument("--timestamp")
    bind_sessions.set_defaults(func=command_bind_fast8_worker_sessions)

    self_bind_worker = subparsers.add_parser(
        "self-bind-fast8-worker-session",
        help="Worker 从可信 CODEX_THREAD_ID 环境变量自注册真实 session",
    )
    self_bind_worker.add_argument("--state", required=True)
    self_bind_worker.add_argument("--ticket", required=True)
    self_bind_worker.add_argument("--model", required=True)
    self_bind_worker.add_argument("--reasoning-effort", required=True)
    self_bind_worker.add_argument("--fork-turns", required=True)
    self_bind_worker.add_argument("--timestamp")
    self_bind_worker.set_defaults(func=command_self_bind_fast8_worker_session)

    check_ticket = subparsers.add_parser(
        "check-fast8-worker-ticket",
        help="Worker 在生图前校验结构化 dispatch ticket，不从自然语言转抄 job SHA",
    )
    check_ticket.add_argument("--state", required=True)
    check_ticket.add_argument("--ticket", required=True)
    check_ticket.add_argument(
        "--wait-for-session-seconds",
        type=float,
        default=0,
        help="Worker 在 ImageGen 前等待主控完成真实 session 绑定，范围 0-90 秒",
    )
    check_ticket.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="等待 session 绑定时的状态轮询间隔，范围 0.2-5 秒",
    )
    check_ticket.set_defaults(func=command_check_fast8_worker_ticket)

    acquire_imagegen_slot = subparsers.add_parser(
        "acquire-fast8-imagegen-slot",
        help="Worker 在实际 ImageGen 调用前即时获取一个全局槽位",
    )
    acquire_imagegen_slot.add_argument("--state", required=True)
    acquire_imagegen_slot.add_argument("--ticket", required=True)
    acquire_imagegen_slot.add_argument(
        "--wait-seconds",
        type=float,
        default=0,
        help="槽位满时本次最多等待秒数，范围 0-1200",
    )
    acquire_imagegen_slot.add_argument(
        "--slice-seconds",
        type=float,
        help="短轮询切片，范围 0-25 秒；返回 acquired|slot_waiting|slot_wait_timeout",
    )
    acquire_imagegen_slot.add_argument(
        "--hard-wait-seconds",
        type=float,
        default=1200,
        help="跨切片累计硬等待上限，范围 1-1200 秒",
    )
    acquire_imagegen_slot.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="等待槽位的轮询间隔，范围 0.2-5 秒",
    )
    acquire_imagegen_slot.set_defaults(func=command_acquire_fast8_imagegen_slot)

    release_imagegen_slot = subparsers.add_parser(
        "release-fast8-imagegen-slot",
        help="Worker 在 ImageGen 调用结束后立即释放全局槽位",
    )
    release_imagegen_slot.add_argument("--state", required=True)
    release_imagegen_slot.add_argument("--ticket", required=True)
    release_imagegen_slot.add_argument("--lease-id", required=True)
    release_imagegen_slot.set_defaults(func=command_release_fast8_imagegen_slot)

    write_worker_receipt = subparsers.add_parser(
        "write-fast8-worker-receipt",
        help="由脚本原子写入结构化 Fast8 Worker 回执，禁止模型自由拼 JSON",
    )
    write_worker_receipt.add_argument("--state", required=True)
    write_worker_receipt.add_argument("--ticket", required=True)
    write_worker_receipt.add_argument(
        "--tool-status", choices=("completed", "failed"), required=True
    )
    write_worker_receipt.add_argument("--saved-path")
    write_worker_receipt.add_argument("--tool-call-id")
    write_worker_receipt.add_argument("--tool-started-at", required=True)
    write_worker_receipt.add_argument("--tool-finished-at", required=True)
    write_worker_receipt.add_argument(
        "--failure-class",
        choices=("backend_network", "backend_failed", "artifact_missing"),
    )
    write_worker_receipt.add_argument("--tool-error-code")
    write_worker_receipt.add_argument("--error")
    write_worker_receipt.add_argument("--timestamp")
    write_worker_receipt.set_defaults(func=command_write_fast8_worker_receipt)

    settle = subparsers.add_parser(
        "settle-wave", help="批量校验并结算一波图片 Agent 的最小 JSON 结果"
    )
    settle.add_argument("--state", required=True)
    settle.add_argument("--results-file", required=True)
    settle.add_argument("--expected-styles")
    settle.add_argument("--timestamp")
    settle.set_defaults(func=command_settle_wave)

    receipt_settle = subparsers.add_parser(
        "settle-fast8-receipts",
        help="主动扫描 Fast8 机器回执并即时结算，不等待 Worker 最终文字",
    )
    receipt_settle.add_argument("--state", required=True)
    receipt_settle.add_argument("--styles", help="可选：只扫描指定席位，例如 A,C,F")
    receipt_settle.add_argument(
        "--wait-seconds",
        type=float,
        default=0,
        help="本次最多等待回执的秒数，范围 0-60",
    )
    receipt_settle.add_argument(
        "--poll-interval",
        type=float,
        default=2,
        help="等待期间的文件轮询间隔，范围 0.2-10 秒",
    )
    receipt_settle.add_argument("--timestamp")
    receipt_settle.set_defaults(func=command_settle_fast8_receipts)

    quick_qa = subparsers.add_parser(
        "prepare-quick-qa", help="仅为旧 quick8 v3 创建深色/浅色分组 QA 任务"
    )
    quick_qa.add_argument("--project-dir", required=True)
    quick_qa.add_argument("--state", required=True)
    quick_qa.add_argument("--group", choices=("dark", "light"))
    quick_qa.set_defaults(func=command_prepare_quick_qa)

    fast8_review = subparsers.add_parser(
        "prepare-fast8-diversity-review",
        help="为 Fast8 创建终局隔离差异裁判任务；4/6 仅兼容旧任务或人工诊断",
    )
    fast8_review.add_argument("--project-dir", required=True)
    fast8_review.add_argument("--state", required=True)
    fast8_review.add_argument("--checkpoint", type=int, choices=(4, 6, 8), required=True)
    fast8_review.set_defaults(func=command_prepare_fast8_diversity_review)

    fast8_judge_check = subparsers.add_parser(
        "check-fast8-judge-job",
        help="Judge 审图前校验正式 job/contact sheet 并取得预编译报告骨架",
    )
    fast8_judge_check.add_argument("--state", required=True)
    fast8_judge_check.add_argument("--review-job", required=True)
    fast8_judge_check.set_defaults(func=command_check_fast8_judge_job)

    fast8_judge_bind = subparsers.add_parser(
        "bind-fast8-judge-session",
        help="把真实 Judge session 与强制模型、推理档位和 fork 策略绑定到正式 job",
    )
    fast8_judge_bind.add_argument("--state", required=True)
    fast8_judge_bind.add_argument("--review-job", required=True)
    fast8_judge_bind.add_argument("--session-id", required=True)
    fast8_judge_bind.add_argument("--model", required=True)
    fast8_judge_bind.add_argument("--reasoning-effort", required=True)
    fast8_judge_bind.add_argument("--fork-turns", required=True)
    fast8_judge_bind.add_argument("--timestamp")
    fast8_judge_bind.set_defaults(func=command_bind_fast8_judge_session)

    fast8_judge_self_bind = subparsers.add_parser(
        "self-bind-fast8-judge-session",
        help="Judge 从可信 CODEX_THREAD_ID 环境变量自注册真实 session",
    )
    fast8_judge_self_bind.add_argument("--state", required=True)
    fast8_judge_self_bind.add_argument("--review-job", required=True)
    fast8_judge_self_bind.add_argument("--model", required=True)
    fast8_judge_self_bind.add_argument("--reasoning-effort", required=True)
    fast8_judge_self_bind.add_argument("--fork-turns", required=True)
    fast8_judge_self_bind.add_argument("--timestamp")
    fast8_judge_self_bind.set_defaults(func=command_self_bind_fast8_judge_session)

    fast8_judge_await = subparsers.add_parser(
        "await-fast8-judge-job",
        help="让唯一 Judge 在 A-H 生图在途时待命，完整终局 job 出现后立即自绑定并校验",
    )
    fast8_judge_await.add_argument("--state", required=True)
    fast8_judge_await.add_argument("--model", required=True)
    fast8_judge_await.add_argument("--reasoning-effort", required=True)
    fast8_judge_await.add_argument("--fork-turns", required=True)
    fast8_judge_await.add_argument("--wait-seconds", type=float, default=60)
    fast8_judge_await.add_argument("--poll-interval", type=float, default=2)
    fast8_judge_await.add_argument("--timestamp")
    fast8_judge_await.set_defaults(func=command_await_fast8_judge_job)

    fast8_apply = subparsers.add_parser(
        "apply-fast8-diversity-report",
        help="校验 Fast8 差异报告并原子创建至多两张替代任务",
    )
    fast8_apply.add_argument("--project-dir", required=True)
    fast8_apply.add_argument("--state", required=True)
    fast8_apply.add_argument("--review-job", required=True)
    fast8_apply.add_argument("--report-file", required=True)
    fast8_apply.add_argument("--timestamp")
    fast8_apply.set_defaults(func=command_apply_fast8_diversity_report)

    fast8_finalize = subparsers.add_parser(
        "finalize-fast8",
        help=(
            "Judge 通过后一次完成候选平铺、2x4 总览、candidate_ready、handoff、"
            "完整状态审计、监测登记和九链接交付文本"
        ),
    )
    fast8_finalize.add_argument("--state", required=True)
    fast8_finalize.add_argument(
        "--overview-python",
        help="仅供未绑定运行时的旧 Fast8 使用；新运行自动复用启动阶段的绑定",
    )
    fast8_finalize.set_defaults(func=command_finalize_fast8)

    chrome_review = subparsers.add_parser(
        "prepare-global-chrome-review",
        help="为集成标题检查失败或旧任务创建独立、哈希绑定的诊断任务",
    )
    chrome_review.add_argument("--project-dir", required=True)
    chrome_review.add_argument("--state", required=True)
    chrome_review.set_defaults(func=command_prepare_global_chrome_review)

    chrome_apply = subparsers.add_parser(
        "apply-global-chrome-review",
        help="校验并应用异常诊断或旧任务的独立标题系统审查",
    )
    chrome_apply.add_argument("--state", required=True)
    chrome_apply.add_argument("--review-job", required=True)
    chrome_apply.add_argument("--report-file", required=True)
    chrome_apply.set_defaults(func=command_apply_global_chrome_review)

    diversity_repairs = subparsers.add_parser(
        "prepare-diversity-repairs",
        help="仅为旧 quick8 v3 撞车席位分配正向替代方向",
    )
    diversity_repairs.add_argument("--project-dir", required=True)
    diversity_repairs.add_argument("--styles", required=True)
    diversity_repairs.add_argument("--attempt", type=int, default=2)
    diversity_repairs.add_argument("--collision-details-json")
    diversity_repairs.set_defaults(func=command_prepare_diversity_repairs)

    fast_anchor_repairs = subparsers.add_parser(
        "prepare-fast-anchor-repairs",
        help="为新 Fast 4x3 在扩展前创建一次问题导向的锚点修复任务",
    )
    fast_anchor_repairs.add_argument("--project-dir", required=True)
    fast_anchor_repairs.add_argument("--state", required=True)
    fast_anchor_repairs.add_argument("--styles", required=True)
    fast_anchor_repairs.add_argument("--issues-json", required=True)
    fast_anchor_repairs.set_defaults(func=command_prepare_fast_anchor_repairs)

    followers = subparsers.add_parser(
        "prepare-followers", help="由四个锚点和内容合同批量创建合同及八个跟随任务"
    )
    followers.add_argument("--project-dir", required=True)
    followers.add_argument("--state", required=True)
    followers.add_argument("--contract-seeds", required=True)
    followers.add_argument("--content-contract-dir", required=True)
    followers.set_defaults(func=command_prepare_followers)

    fast_followers = subparsers.add_parser(
        "prepare-fast-followers",
        help="按已就绪席位渐进创建 Fast 4x3 候选合同与跟随任务",
    )
    fast_followers.add_argument("--project-dir", required=True)
    fast_followers.add_argument("--state", required=True)
    fast_followers.add_argument("--content-contract-dir", required=True)
    fast_followers.add_argument(
        "--styles", help="可选：只解锁指定的已就绪席位，例如 A,B"
    )
    fast_followers.set_defaults(func=command_prepare_fast_followers)

    route = subparsers.add_parser("route-failure", help="确定质量失败路由")
    route.add_argument(
        "--content-status", required=True, choices=("pass", "fail", "needs_content_decision")
    )
    route.add_argument(
        "--spatial-status", required=True, choices=("pass", "fail", "not_applicable")
    )
    route.add_argument(
        "--craft-status",
        choices=("pass", "fail", "not_applicable"),
        default="not_applicable",
    )
    route.add_argument("--content-structure-overloaded", action="store_true")
    route.set_defaults(func=command_route_failure)

    validate = subparsers.add_parser("validate-state", help="校验状态与计时完整性")
    validate.add_argument("--state", required=True)
    validate.add_argument("--complete", action="store_true")
    validate.set_defaults(func=command_validate_state)
    return parser


def main() -> None:
    configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
