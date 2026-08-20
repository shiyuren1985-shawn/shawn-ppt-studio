#!/usr/bin/env python3
"""Minimal Fast8 control plane: one burst, direct receipts, one Judge, lean delivery.

This module deliberately owns only mechanical orchestration.  It consumes the
already-compiled generation jobs and the existing Judge implementation; it does
not create or rewrite any visual prompt, reference input, content contract, or
quality rule.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Any

import pipeline_control as pc


CONTROL_VERSION = 1
STYLES = tuple("ABCDEFGH")
CLAIM_STATES = {"claimed", "receipt_written", "released"}
CLAIM_WAIT_SECONDS = 600
IMAGEGEN_SLOT_LIMIT_ENV = "SHAWN_PPT_IMAGE_GLOBAL_SLOT_LIMIT"
SCRIPT_PATH = Path(__file__).resolve()


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False))


def capture(function, **kwargs: Any) -> dict[str, Any]:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        function(argparse.Namespace(**kwargs))
    raw = stream.getvalue().strip()
    return json.loads(raw) if raw else {}


def require_fast8(state_path: Path) -> tuple[dict[str, Any], Path]:
    state = pc.read_json(state_path)
    if state.get("run_mode") != pc.FAST8_MODE:
        raise SystemExit("Fast8 control plane v1 只适用于 fast_8x1_diverse")
    return state, pc.project_dir_for_state(state_path, state)


def resolve_imagegen_concurrency() -> int:
    raw = os.environ.get(
        IMAGEGEN_SLOT_LIMIT_ENV,
        str(pc.FAST8_JIT_STABLE_IMAGEGEN_SLOT_LIMIT),
    )
    try:
        capacity = int(raw)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{IMAGEGEN_SLOT_LIMIT_ENV} 必须是 1–8 的整数") from exc
    if capacity < 1 or capacity > pc.FAST8_GLOBAL_IMAGEGEN_SLOT_LIMIT:
        raise SystemExit(f"{IMAGEGEN_SLOT_LIMIT_ENV} 必须在 1–8 之间")
    return capacity


def _director_input_paths(project_dir: Path) -> dict[str, Path]:
    root = project_dir / "state" / "director_inputs"
    return {
        "root": root,
        "content_raw": root / "content_contract.json",
        "layout_raw": root / "layout_portfolio.json",
        "creative_intent": root / "creative_intent.json",
        "required_assets": root / "required_assets.json",
        "source_packet": root / "authoritative_page_packet.md",
        "global_chrome_raw": root / "global_chrome_contract.json",
        "global_chrome": root / "global_chrome_contract.normalized.json",
        "content_normalized": root / "content_contract.normalized.json",
        "layout_normalized": root / "layout_portfolio.normalized.json",
        "normalization_provenance": root / "director_outputs.normalized.json",
        "content_merged": root / "content_contract.merged.json",
        "overall_requirements": root / "overall_requirements.txt",
    }


def _run_small_json_command(command: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        return None, error
    try:
        return json.loads(completed.stdout.strip() or "{}"), None
    except json.JSONDecodeError:
        return None, "command did not return one JSON object"


def _preflight_reference_inputs(
    project_dir: Path,
    required_assets_path: Path,
    global_chrome_path: Path | None,
    page_id: str,
) -> list[dict[str, str]]:
    manifest_path = project_dir / "state" / "preflight_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"缺少冻结 preflight manifest：{manifest_path}")
    manifest = pc.read_json(manifest_path)
    items = manifest.get("asset_items") or []
    if not isinstance(items, list):
        raise SystemExit("preflight asset_items 必须是数组")
    style_references: list[dict[str, str]] = []
    frozen_non_style_paths: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise SystemExit(f"preflight asset_items[{index}] 必须是对象")
        path_value = item.get("path")
        role_value = item.get("role")
        if not isinstance(path_value, str) or not isinstance(role_value, str):
            raise SystemExit(f"preflight asset_items[{index}] 缺少 path/role")
        path = Path(path_value).expanduser()
        if not path.is_absolute() or not path.resolve().is_file():
            raise SystemExit(f"preflight asset_items[{index}] 不是现存绝对文件")
        normalized = {"path": str(path.resolve()), "role": role_value.strip().lower()}
        if normalized["role"] in pc.FAST8_STYLE_REFERENCE_ROLES:
            style_references.append(normalized)
        else:
            frozen_non_style_paths.add(normalized["path"])

    required_assets = pc.read_required_assets_input(
        json_value=None,
        file_value=str(required_assets_path),
        expected_page_id=page_id,
    )
    required_paths = {
        str(Path(str(item["path"])).expanduser().resolve()) for item in required_assets
    }
    chrome_paths: set[str] = set()
    if global_chrome_path is not None:
        chrome = pc.read_json(global_chrome_path)
        assets_by_tone = (
            ((chrome.get("deck_title_system") or {}).get("logo") or {}).get(
                "assets_by_tone"
            )
            or {}
        )
        if not isinstance(assets_by_tone, dict):
            raise SystemExit("global chrome logo.assets_by_tone 必须是对象")
        for item in assets_by_tone.values():
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                chrome_paths.add(str(Path(item["path"]).expanduser().resolve()))
        qa_reference = (chrome.get("deck_title_system") or {}).get(
            "qa_reference_path"
        )
        if isinstance(qa_reference, str) and qa_reference.strip():
            candidate = Path(qa_reference).expanduser()
            if candidate.is_absolute() and candidate.resolve().is_file():
                chrome_paths.add(str(candidate.resolve()))

    unresolved = frozen_non_style_paths - required_paths - chrome_paths
    unfrozen = required_paths - frozen_non_style_paths
    overlap = required_paths & {item["path"] for item in style_references}
    if unresolved:
        raise SystemExit(
            "preflight 非风格资产未由 required_assets/global chrome 路由："
            + ", ".join(sorted(unresolved))
        )
    if unfrozen:
        raise SystemExit(
            "required_assets 包含未在冻结 preflight 登记的图片输入："
            + ", ".join(sorted(unfrozen))
        )
    if overlap:
        raise SystemExit("同一图片不得同时作为风格参考和 required asset")
    return style_references


def prepare_director_inputs(state_path: Path) -> dict[str, Any]:
    state, project_dir = require_fast8(state_path)
    paths = _director_input_paths(project_dir)
    stages: dict[str, dict[str, Any]] = {}
    existing_jobs = sorted((project_dir / "style_jobs").glob("style_[A-H].json"))
    if existing_jobs:
        return {
            "status": "failed",
            "failed_stage": "precheck",
            "error": "style_jobs 已存在；单入口只用于首次准备",
            "stages": stages,
            "style_job_count": len(existing_jobs),
        }
    for label in (
        "content_raw",
        "layout_raw",
        "creative_intent",
        "required_assets",
        "source_packet",
    ):
        if not paths[label].is_file():
            return {
                "status": "failed",
                "failed_stage": "precheck",
                "error": f"缺少规范输入：{paths[label]}",
                "stages": stages,
                "style_job_count": 0,
            }
    if paths["global_chrome_raw"].is_file() and not paths["global_chrome"].is_file():
        return {
            "status": "failed",
            "failed_stage": "precheck",
            "error": "存在 raw global chrome，但缺少 normalized 合同",
            "stages": stages,
            "style_job_count": 0,
        }
    global_chrome = paths["global_chrome"] if paths["global_chrome"].is_file() else None
    try:
        reference_images = _preflight_reference_inputs(
            project_dir,
            paths["required_assets"],
            global_chrome,
            str(state.get("anchor_page_id")),
        )
    except SystemExit as exc:
        return {
            "status": "failed",
            "failed_stage": "precheck",
            "error": str(exc),
            "stages": stages,
            "style_job_count": 0,
        }

    started = time.perf_counter()
    normalized, error = _run_small_json_command(
        [
            sys.executable,
            str(SCRIPT_PATH.parent / "normalize_fast8_director_outputs.py"),
            "--content-input",
            str(paths["content_raw"]),
            "--layout-input",
            str(paths["layout_raw"]),
            "--content-output",
            str(paths["content_normalized"]),
            "--layout-output",
            str(paths["layout_normalized"]),
            "--provenance-output",
            str(paths["normalization_provenance"]),
        ]
    )
    stages["normalize"] = {
        "status": "failed" if error else "ok",
        "seconds": round(time.perf_counter() - started, 3),
        "content_output": str(paths["content_normalized"]),
        "layout_output": str(paths["layout_normalized"]),
    }
    if error:
        return {
            "status": "failed",
            "failed_stage": "normalize",
            "error": error,
            "stages": stages,
            "style_job_count": 0,
        }

    try:
        normalized_layout = pc.read_json(paths["layout_normalized"])
        current_state = pc.read_json(state_path)
        if pc.apply_background_tone_policy(
            current_state,
            normalized_layout.get("background_tone_policy"),
            tuple("ABCDEFGH"),
            label="layout_portfolio.background_tone_policy",
        ):
            pc.atomic_write_json(state_path, current_state)
    except SystemExit as exc:
        return {
            "status": "failed",
            "failed_stage": "background_tone_policy",
            "error": str(exc),
            "stages": stages,
            "style_job_count": 0,
        }

    started = time.perf_counter()
    merged, error = _run_small_json_command(
        [
            sys.executable,
            str(SCRIPT_PATH.parent / "merge_fast8_director_inputs.py"),
            "--content-contract",
            str(paths["content_normalized"]),
            "--creative-intent",
            str(paths["creative_intent"]),
            "--output",
            str(paths["content_merged"]),
            "--overall-requirements-output",
            str(paths["overall_requirements"]),
        ]
    )
    stages["merge"] = {
        "status": "failed" if error else "ok",
        "seconds": round(time.perf_counter() - started, 3),
        "content_output": str(paths["content_merged"]),
        "overall_requirements": str(paths["overall_requirements"]),
    }
    if error:
        return {
            "status": "failed",
            "failed_stage": "merge",
            "error": error,
            "stages": stages,
            "style_job_count": 0,
        }

    started = time.perf_counter()
    try:
        prepared = capture(
            pc.command_prepare_anchors,
            project_dir=str(project_dir),
            state=str(state_path),
            content_contract=str(paths["content_merged"]),
            overall_requirements=str(paths["overall_requirements"]),
            reference_images_json=json.dumps(reference_images, ensure_ascii=False),
            required_assets_json=None,
            required_assets_file=str(paths["required_assets"]),
            global_chrome_contract=str(global_chrome) if global_chrome else None,
            source_file=str(paths["source_packet"]),
            source_page_ids=str(state.get("anchor_page_id")),
            source_fragment_file=str(paths["source_packet"]),
            source_fragment_authority="authoritative_page_fragment",
            snapshot_content_contracts_json=None,
            source_snapshot_timestamp=None,
            layout_portfolio=str(paths["layout_normalized"]),
            overview_python=None,
        )
    except SystemExit as exc:
        stages["prepare_anchors"] = {
            "status": "failed",
            "seconds": round(time.perf_counter() - started, 3),
            "style_jobs_dir": str(project_dir / "style_jobs"),
        }
        job_count = len(list((project_dir / "style_jobs").glob("style_[A-H].json")))
        return {
            "status": "failed",
            "failed_stage": "prepare_anchors",
            "error": str(exc),
            "stages": stages,
            "style_job_count": job_count,
        }
    job_count = len(list((project_dir / "style_jobs").glob("style_[A-H].json")))
    stages["prepare_anchors"] = {
        "status": "ok",
        "seconds": round(time.perf_counter() - started, 3),
        "style_jobs_dir": str(project_dir / "style_jobs"),
        "style_job_count": job_count,
    }
    return {
        "status": "ok",
        "stages": stages,
        "style_job_count": job_count,
        "style_jobs_dir": str(project_dir / "style_jobs"),
        "content_contract": str(paths["content_merged"]),
        "layout_portfolio": str(paths["layout_normalized"]),
    }


def claim_path(project_dir: Path, style: str, page_id: str, action: str, attempt: int) -> Path:
    safe_action = re.sub(r"[^a-z0-9_]+", "_", action.lower()).strip("_")
    return (
        project_dir
        / "state"
        / "burst_claims"
        / f"claim_{style}_page_{page_id}_{safe_action}_attempt_{attempt}.json"
    )


def active_for_ticket(
    state_path: Path, state: dict[str, Any], ticket_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    state_path = state_path.expanduser().resolve()
    ticket_path = ticket_path.expanduser().resolve()
    project_dir = pc.project_dir_for_state(state_path, state)
    pc.require_path_within(
        ticket_path,
        project_dir / "style_jobs" / "dispatch_tickets",
        "Fast8 burst ticket",
    )
    ticket, ticket_sha = pc.read_json_with_sha256(ticket_path)
    allowed = {
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
        "worker_runtime_contract",
    }
    if set(ticket) - allowed:
        raise SystemExit("Fast8 burst ticket 含未知字段")
    if ticket.get("run_id") != state.get("run_id"):
        raise SystemExit("Fast8 burst ticket run_id 错绑")
    if str(Path(str(ticket.get("state_path"))).resolve()) != str(state_path):
        raise SystemExit("Fast8 burst ticket state_path 错绑")
    style = pc.normalize_style(ticket.get("style"))
    page_id = str(ticket.get("page_id"))
    action = str(ticket.get("action"))
    attempt = int(ticket.get("attempt") or 0)
    if style not in STYLES or page_id != str(state.get("anchor_page_id")):
        raise SystemExit("Fast8 burst ticket 席位或页码错绑")
    active = next(
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
    if not isinstance(active, dict):
        raise SystemExit("Fast8 burst ticket 没有唯一 active_action")
    if active.get("worker_ticket_path") != str(ticket_path):
        raise SystemExit("Fast8 burst ticket 路径与 active_action 不一致")
    if active.get("worker_ticket_sha256") != ticket_sha:
        raise SystemExit("Fast8 burst ticket SHA-256 与 active_action 不一致")
    job_path = Path(str(ticket.get("generation_job_path"))).expanduser().resolve()
    job_sha = str(ticket.get("generation_job_sha256") or "")
    if (
        active.get("generation_job_path") != str(job_path)
        or active.get("generation_job_sha256") != job_sha
        or not job_path.is_file()
        or pc.file_sha256(job_path) != job_sha
    ):
        raise SystemExit("Fast8 burst generation job 错绑或已变化")
    job = pc.read_json(job_path)
    if job.get("imagegen_input_fingerprint") != ticket.get(
        "imagegen_input_fingerprint"
    ):
        raise SystemExit("Fast8 burst ticket 与 job 图片输入指纹不一致")
    if hashlib.sha256(str(job.get("imagegen_prompt") or "").encode("utf-8")).hexdigest() != job.get(
        "imagegen_prompt_fingerprint"
    ):
        raise SystemExit("Fast8 generation job 的提示词指纹已变化")
    return active, ticket, job


def dispatch_if_needed(state_path: Path) -> None:
    state, _project_dir = require_fast8(state_path)
    scheduler = state.get("scheduler") or {}
    active = scheduler.get("active_actions") or []
    if active:
        return
    # Burst claims are the JIT lease boundary.  Prevent the legacy dispatcher
    # from pre-leasing all eight seats before any RPC actually starts.
    if scheduler.get("imagegen_slot_policy") != pc.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY:
        scheduler["imagegen_slot_policy"] = pc.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY
        state["scheduler"] = scheduler
        pc.atomic_write_json(state_path, state)
    page_id = str(state.get("anchor_page_id"))
    ready = [
        item
        for item in (scheduler.get("ready_queue") or [])
        if isinstance(item, dict)
        and item.get("style") in STYLES
        and str(item.get("page_id")) == page_id
        and item.get("action") in {"generate_anchor", "repair_anchor"}
    ]
    review = state.get("diversity_review") or {}
    replacement_mode = review.get("status") == "repair_queued"
    technical_retry_mode = bool(ready) and all(
        item.get("technical_retry") is True for item in ready
    )
    if replacement_mode and technical_retry_mode:
        raise SystemExit("Burst Runner 不得混合 Judge 替代与技术重试")
    expected_styles = (
        set(review.get("replacement_styles") or [])
        if replacement_mode
        else {str(item.get("style")) for item in ready}
        if technical_retry_mode
        else set(STYLES)
    )
    ready_styles = {item.get("style") for item in ready}
    if ready_styles != expected_styles or (
        replacement_mode and not 1 <= len(ready) <= 2
    ) or (
        technical_retry_mode and not 1 <= len(ready) <= 8
    ) or (not replacement_mode and not technical_retry_mode and len(ready) != 8):
        raise SystemExit(
            "Burst Runner 派发任务与初始 A-H、Judge 替代或技术重试授权不一致"
        )
    if technical_retry_mode:
        for item in ready:
            style = str(item.get("style"))
            attempt = int(item.get("attempt") or 0)
            record = pc.page_record(state, style, page_id)
            history = record.get("attempt_history") or []
            last = history[-1] if history and isinstance(history[-1], dict) else {}
            if (
                int(record.get("technical_retry_count") or 0) < 1
                or last.get("outcome") != "imagegen_backend_failed"
                or int(last.get("attempt") or 0) + 1 != attempt
                or attempt < 2
            ):
                raise SystemExit(
                    f"style_{style} technical retry 缺少既有后端失败与递增 attempt 授权"
                )
    tasks = [
        {
            "style": style,
            "page_id": page_id,
            "action": next(item["action"] for item in ready if item["style"] == style),
            "attempt": int(
                next(item.get("attempt") or 1 for item in ready if item["style"] == style)
            ),
        }
        for style in STYLES
        if style in expected_styles
    ]
    agent_map = {
        f"{item['style']}/{item['page_id']}/{item['action']}/{item['attempt']}": (
            f"fast8_burst_runner_v1_{item['style']}"
        )
        for item in tasks
    }
    capture(
        pc.command_record_dispatch_wave,
        state=str(state_path),
        styles=None,
        tasks_json=json.dumps(tasks, ensure_ascii=False),
        page_id=None,
        action="generate_anchor",
        attempt=1,
        timestamp=None,
        agent_map_json=json.dumps(agent_map, ensure_ascii=False),
        backpressure_reason=None,
    )


def build_manifest(state_path: Path, *, dispatch: bool) -> dict[str, Any]:
    imagegen_concurrency = resolve_imagegen_concurrency()
    if dispatch:
        dispatch_if_needed(state_path)
    state, project_dir = require_fast8(state_path)
    active = [
        item
        for item in ((state.get("scheduler") or {}).get("active_actions") or [])
        if isinstance(item, dict)
        and item.get("style") in STYLES
        and str(item.get("page_id")) == str(state.get("anchor_page_id"))
        and item.get("action") in {"generate_anchor", "repair_anchor"}
    ]
    by_style = {str(item.get("style")): item for item in active}
    review = state.get("diversity_review") or {}
    replacement_mode = review.get("status") == "repair_queued"
    technical_retry_mode = bool(active) and all(
        item.get("technical_retry") is True for item in active
    )
    if replacement_mode and technical_retry_mode:
        raise SystemExit("Burst Runner active tickets 混合了 Judge 替代与技术重试")
    expected_styles = (
        set(review.get("replacement_styles") or [])
        if replacement_mode
        else {str(item.get("style")) for item in active}
        if technical_retry_mode
        else set(STYLES)
    )
    if set(by_style) != expected_styles or (
        replacement_mode and not 1 <= len(active) <= 2
    ) or (
        technical_retry_mode and not 1 <= len(active) <= 8
    ) or (not replacement_mode and not technical_retry_mode and len(active) != 8):
        raise SystemExit("Burst Runner active tickets 与本轮授权集合不一致")
    if technical_retry_mode:
        for style, item in by_style.items():
            attempt = int(item.get("attempt") or 0)
            record = pc.page_record(state, style, str(state.get("anchor_page_id")))
            history = record.get("attempt_history") or []
            last = history[-1] if history and isinstance(history[-1], dict) else {}
            if (
                int(record.get("technical_retry_count") or 0) < 1
                or last.get("outcome") != "imagegen_backend_failed"
                or int(last.get("attempt") or 0) + 1 != attempt
            ):
                raise SystemExit(f"style_{style} active technical retry 授权无效")
    seats: list[dict[str, Any]] = []
    for style in STYLES:
        if style not in expected_styles:
            continue
        ticket_path = Path(str(by_style[style].get("worker_ticket_path"))).resolve()
        _active, ticket, job = active_for_ticket(state_path, state, ticket_path)
        refs = job.get("imagegen_referenced_paths") or []
        if not isinstance(refs, list) or not all(isinstance(value, str) for value in refs):
            raise SystemExit(f"style_{style} imagegen_referenced_paths 无效")
        seats.append(
            {
                "style": style,
                "page_id": str(ticket["page_id"]),
                "action": str(ticket["action"]),
                "attempt": int(ticket["attempt"]),
                "ticket_path": str(ticket_path),
                "ticket_sha256": pc.file_sha256(ticket_path),
                "job_path": str(Path(str(ticket["generation_job_path"])).resolve()),
                "job_sha256": str(ticket["generation_job_sha256"]),
                "imagegen_prompt": job["imagegen_prompt"],
                "imagegen_prompt_fingerprint": job["imagegen_prompt_fingerprint"],
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "imagegen_referenced_paths": refs,
                "receipt_path": str(Path(str(ticket["worker_receipt_path"])).resolve()),
            }
        )
    manifest = {
        "fast8_control_plane_version": CONTROL_VERSION,
        "run_id": state.get("run_id"),
        "state_path": str(state_path),
        "project_dir": str(project_dir),
        "page_id": str(state.get("anchor_page_id")),
        "global_imagegen_concurrency": imagegen_concurrency,
        "seats": seats,
    }
    if replacement_mode:
        manifest_suffix = "replacement_" + "".join(
            style for style in STYLES if style in expected_styles
        )
    elif technical_retry_mode:
        attempts = "_".join(
            f"{style}{int(by_style[style].get('attempt') or 0)}"
            for style in STYLES
            if style in expected_styles
        )
        manifest_suffix = "technical_retry_" + attempts
    else:
        manifest_suffix = "initial"
    path = project_dir / "state" / f"fast8_burst_manifest_v1_{manifest_suffix}.json"
    pc.write_idempotent(path, manifest)
    return {
        **manifest,
        "manifest_path": str(path),
        "manifest_sha256": pc.file_sha256(path),
    }


def validate_claim_manifest(
    state_path: Path,
    ticket_path: Path,
    manifest_path: Path,
    manifest_sha256: str,
    capacity_limit: int,
) -> int:
    if capacity_limit < 1 or capacity_limit > pc.FAST8_GLOBAL_IMAGEGEN_SLOT_LIMIT:
        raise SystemExit("Burst claim capacity 必须在 1–8 之间")
    state, project_dir = require_fast8(state_path)
    resolved_manifest = manifest_path.resolve()
    if resolved_manifest.parent != (project_dir / "state").resolve():
        raise SystemExit("Burst claim manifest 不属于当前运行")
    if not resolved_manifest.is_file():
        raise SystemExit(f"Burst claim manifest 不存在：{resolved_manifest}")
    if pc.file_sha256(resolved_manifest) != manifest_sha256:
        raise SystemExit("Burst claim manifest SHA 不一致")
    manifest = pc.read_json(resolved_manifest)
    if manifest.get("fast8_control_plane_version") != CONTROL_VERSION:
        raise SystemExit("Burst claim manifest 版本不一致")
    if str(Path(str(manifest.get("state_path"))).resolve()) != str(state_path.resolve()):
        raise SystemExit("Burst claim manifest state 不一致")
    if manifest.get("run_id") != state.get("run_id"):
        raise SystemExit("Burst claim manifest run_id 不一致")
    if int(manifest.get("global_imagegen_concurrency") or 0) != capacity_limit:
        raise SystemExit("Burst claim capacity 与 manifest 不一致")
    matching_seats = [
        item
        for item in (manifest.get("seats") or [])
        if isinstance(item, dict)
        and str(Path(str(item.get("ticket_path"))).resolve()) == str(ticket_path.resolve())
    ]
    if len(matching_seats) != 1:
        raise SystemExit("Burst claim ticket 不在唯一 manifest 席位中")
    return capacity_limit


def claim_ticket(
    state_path: Path,
    ticket_path: Path,
    wait_seconds: float,
    *,
    manifest_path: Path,
    manifest_sha256: str,
    capacity_limit: int,
) -> dict[str, Any]:
    capacity_limit = validate_claim_manifest(
        state_path,
        ticket_path,
        manifest_path,
        manifest_sha256,
        capacity_limit,
    )
    deadline = time.monotonic() + wait_seconds
    while True:
        state, project_dir = require_fast8(state_path)
        active, ticket, _job = active_for_ticket(state_path, state, ticket_path)
        style = str(ticket["style"])
        page_id = str(ticket["page_id"])
        action = str(ticket["action"])
        attempt = int(ticket["attempt"])
        path = claim_path(project_dir, style, page_id, action, attempt)
        if path.exists():
            existing = pc.read_json(path)
            if existing.get("status") in CLAIM_STATES:
                raise SystemExit(f"style_{style} duplicate claim 被拒绝")
        task = {
            "style": style,
            "page_id": page_id,
            "action": action,
            "attempt": attempt,
            "lease_kind": "burst_runner_v1",
            "worker_ticket_sha256": pc.file_sha256(ticket_path),
        }
        acquired, deferred, leases, _remaining = pc.acquire_fast8_global_imagegen_slots(
            state_path,
            state,
            [task],
            timestamp=pc.now_iso(),
            capacity_limit=capacity_limit,
        )
        if acquired:
            key = f"{style}/{page_id}/{action}/{attempt}"
            lease_id = leases[key]
            claim = {
                "fast8_control_plane_version": CONTROL_VERSION,
                "status": "claimed",
                "run_id": state.get("run_id"),
                "style": style,
                "page_id": page_id,
                "action": action,
                "attempt": attempt,
                "ticket_path": str(ticket_path),
                "ticket_sha256": pc.file_sha256(ticket_path),
                "generation_job_sha256": active.get("generation_job_sha256"),
                "imagegen_input_fingerprint": ticket.get("imagegen_input_fingerprint"),
                "global_lease_id": lease_id,
                "claimed_at": pc.now_iso(),
            }
            pc.write_idempotent(path, claim)
            return {"status": "claimed", "style": style, "claim_path": str(path), "lease_id": lease_id}
        if not deferred:
            raise SystemExit("全局 ImageGen 槽位返回了不一致结果")
        if time.monotonic() >= deadline:
            return {"status": "capacity_wait_timeout", "style": style}
        time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))


def canonical_time(value: str, label: str) -> str:
    try:
        return pc.parse_time(value).isoformat(timespec="microseconds")
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{label} 无效：{exc}") from exc


def write_receipt(
    state_path: Path,
    ticket_path: Path,
    *,
    tool_status: str,
    saved_path: str | None,
    tool_call_id: str | None,
    tool_started_at: str,
    tool_finished_at: str,
    failure_class: str | None,
    tool_error_code: str | None,
) -> dict[str, Any]:
    state, project_dir = require_fast8(state_path)
    _active, ticket, job = active_for_ticket(state_path, state, ticket_path)
    style = str(ticket["style"])
    page_id = str(ticket["page_id"])
    action = str(ticket["action"])
    attempt = int(ticket["attempt"])
    cpath = claim_path(project_dir, style, page_id, action, attempt)
    if not cpath.is_file():
        raise SystemExit(f"style_{style} 尚未 claim，拒绝写回执")
    claim = pc.read_json(cpath)
    if claim.get("status") != "claimed" or claim.get("ticket_sha256") != pc.file_sha256(ticket_path):
        raise SystemExit(f"style_{style} claim 状态或 ticket 绑定无效")
    started = canonical_time(tool_started_at, "tool_started_at")
    finished = canonical_time(tool_finished_at, "tool_finished_at")
    written = pc.now_iso()
    if not pc.parse_time(started) <= pc.parse_time(finished) <= pc.parse_time(written):
        raise SystemExit("Burst receipt 时间倒序")
    error: str | None = None
    resolved: Path | None = None
    if tool_status == "completed" and saved_path:
        resolved, derived = pc.resolve_imagegen_artifact_hint(saved_path)
        if resolved is None:
            raise SystemExit(f"style_{style} completed 但 savedPath 不可解析")
        pc.require_path_within(resolved, pc.GENERATED_IMAGES_ROOT, "Burst ImageGen 图片")
        pc.png_metadata(resolved)
        if derived and tool_call_id and tool_call_id != derived:
            raise SystemExit("tool_call_id 与 savedPath 文件名不一致")
        tool_call_id = derived or tool_call_id
        saved_path = str(resolved)
        failure_class = None
    elif tool_status == "completed":
        saved_path = None
        failure_class = "artifact_missing"
        error = "artifact_handoff_unresolved"
    elif tool_status == "failed":
        saved_path = None
        if failure_class not in {"backend_network", "backend_failed"}:
            failure_class = "backend_failed"
        error = "imagegen_backend_failed"
    else:
        raise SystemExit("tool_status 只允许 completed|failed")
    receipt = {
        "worker_receipt_contract_version": pc.FAST8_WORKER_RECEIPT_CONTRACT_VERSION,
        "style": style,
        "page_id": page_id,
        "action": action,
        "attempt": attempt,
        "imagegen_input_fingerprint": job.get("imagegen_input_fingerprint"),
        "worker_agent_id": "fast8_burst_runner_v1",
        "tool_call_id": tool_call_id,
        "savedPath": saved_path,
        "tool_started_at": started,
        "tool_finished_at": finished,
        "receipt_written_at": written,
        "tool_status": tool_status,
        "failure_class": failure_class,
        "tool_error_code": tool_error_code,
        "error": error,
        "contains_image_payload": False,
    }
    receipt_path = Path(str(ticket["worker_receipt_path"])).resolve()
    pc.write_idempotent(receipt_path, receipt)
    lease_id = str(claim.get("global_lease_id") or "")
    pc.release_fast8_global_imagegen_slots(state_path, state, [lease_id])
    claim.update(
        {
            "status": "receipt_written",
            "receipt_path": str(receipt_path),
            "receipt_written_at": written,
            "forensics_required": tool_status == "completed" and resolved is None,
            "released_at": pc.now_iso(),
        }
    )
    pc.atomic_write_json(cpath, claim)
    return receipt


def release_ticket(state_path: Path, ticket_path: Path) -> dict[str, Any]:
    state, project_dir = require_fast8(state_path)
    _active, ticket, _job = active_for_ticket(state_path, state, ticket_path)
    path = claim_path(
        project_dir,
        str(ticket["style"]),
        str(ticket["page_id"]),
        str(ticket["action"]),
        int(ticket["attempt"]),
    )
    if not path.is_file():
        return {"status": "no_claim", "released": 0}
    claim = pc.read_json(path)
    released = pc.release_fast8_global_imagegen_slots(
        state_path, state, [str(claim.get("global_lease_id") or "")]
    )
    if claim.get("status") == "claimed":
        claim["status"] = "released"
        claim["released_at"] = pc.now_iso()
        pc.atomic_write_json(path, claim)
    return {"status": "released", "released": released}


def settle(state_path: Path) -> dict[str, Any]:
    state, project_dir = require_fast8(state_path)
    forensic_styles: list[str] = []
    for item in ((state.get("scheduler") or {}).get("active_actions") or []):
        if not isinstance(item, dict) or item.get("style") not in STYLES:
            continue
        receipt_value = item.get("worker_receipt_path")
        if not isinstance(receipt_value, str) or not Path(receipt_value).is_file():
            continue
        receipt = pc.read_json(Path(receipt_value))
        if receipt.get("tool_status") == "completed" and not receipt.get("savedPath"):
            forensic_styles.append(str(item["style"]))
    result = capture(
        pc.command_settle_fast8_receipts,
        state=str(state_path),
        styles=None,
        wait_seconds=0,
        poll_interval=0.2,
        timestamp=None,
    )
    result["session_forensics_required_styles"] = sorted(forensic_styles)
    result["normal_path_session_scan_used"] = False
    result["project_dir"] = str(project_dir)
    return result


def prepare_judge(state_path: Path) -> dict[str, Any]:
    state, project_dir = require_fast8(state_path)
    return capture(
        pc.command_prepare_fast8_diversity_review,
        project_dir=str(project_dir),
        state=str(state_path),
        checkpoint=8,
    )


def lean_finalize(state_path: Path) -> dict[str, Any]:
    state, project_dir = require_fast8(state_path)
    review = state.get("diversity_review") or {}
    if review.get("status") not in {"pass", "best_effort"}:
        raise SystemExit("lean finalize 前必须通过现有终局 Judge")
    manifest = pc.fast8_candidate_manifest(state)
    if review.get("final_candidate_set_sha256") != pc.fast8_candidate_set_sha256(manifest):
        raise SystemExit("lean finalize 的 Judge 未绑定当前 A-H")
    required_asset_review = state.get("required_asset_review")
    if isinstance(required_asset_review, dict) and required_asset_review.get(
        "status"
    ) != "pass":
        raise SystemExit("lean finalize 前 required asset 用途检查必须通过")
    scheduler = state.get("scheduler") or {}
    if any(scheduler.get(name) for name in ("active_actions", "ready_queue", "recovery_queue")):
        raise SystemExit("lean finalize 前仍有未收口图片任务")
    page_id = str(state.get("anchor_page_id"))
    finalized: dict[str, str] = {}
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
    for style in STYLES:
        record = pc.page_record(state, style, page_id)
        source = Path(str(record.get("selected_source") or "")).resolve()
        _width, _height, size_bytes, source_sha = pc.png_metadata(source)
        target = pc.origin_image_target(project_dir, style, page_id).resolve()
        pc.atomic_copy_candidate(source, target)
        event_at = pc.now_iso()
        record.update(
            {
                "status": "candidate_ready",
                "final_path": str(target),
                "source_sha256": source_sha,
                "source_size_bytes": size_bytes,
                "overview_qa_at": record.get("overview_qa_at") or event_at,
                "completed_at": record.get("completed_at") or event_at,
                "completion_status": "candidate_ready",
                "qa_stage": "filesystem",
                "qa_scope": "filesystem_only",
                **gate_reason,
            }
        )
        ((state.get("styles") or {}).get(style) or {})[
            "workflow_status"
        ] = "ready_for_overview"
        pc.append_event(
            state,
            "overview_qa",
            event_at,
            style=style,
            page_id=page_id,
            details={"qa_stage": "filesystem", "qa_scope": "filesystem_only"},
        )
        pc.append_event(
            state,
            "page_completed",
            event_at,
            style=style,
            page_id=page_id,
            details={
                "completion_status": "candidate_ready",
                "final_path": str(target),
                "source_sha256": source_sha,
                "source_size_bytes": size_bytes,
                "qa_stage": "filesystem",
                "qa_scope": "filesystem_only",
                **gate_reason,
            },
        )
        finalized[style] = str(target)
    overview = project_dir / "overview" / "ABCDEFGH_2x4.png"
    matrix_python = (state.get("overview_runtime") or {}).get("python")
    if isinstance(matrix_python, str) and matrix_python:
        run = subprocess.run(
            [
                str(Path(matrix_python).resolve()),
                str(SCRIPT_PATH.parent / "build_style_matrix.py"),
                "--project-dir",
                str(project_dir),
                "--pages",
                page_id,
                "--styles",
                ",".join(STYLES),
                "--output",
                str(overview),
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
        if run.returncode != 0:
            raise SystemExit(
                "lean finalize 正式总览生成失败："
                + (run.stderr.strip() or run.stdout.strip() or "unknown error")
            )
    else:
        from build_style_matrix import build_matrix

        invalid = build_matrix(
            project_dir=project_dir,
            styles=list(STYLES),
            pages=[page_id],
            output=overview,
            cell_width=1280,
            header_height=120,
            row_label_width=180,
            gap=24,
            ratio_tolerance=0.02,
            source_state=state,
            allow_invalid=False,
        )
        if invalid:
            raise SystemExit("lean finalize 正式总览包含无效候选")
    if not overview.is_file():
        raise SystemExit("lean finalize 正式总览生成失败")
    completed_at = pc.now_iso()
    state["overview"] = {
        "status": "completed",
        "final_path": str(overview),
        "layout": "2x4",
        "candidate_count": 8,
        "completed_at": completed_at,
    }
    state["status"] = "completed"
    state.setdefault("scheduler", {})["phase"] = "completed"
    timing = state.setdefault("timing", {})
    timing["formal_overview_completed_at"] = completed_at
    timing["process_completed_at"] = completed_at
    target = state.setdefault("timing_target", {})
    target.setdefault("target_minutes", 15)
    target.setdefault("hard_deadline", False)
    target["scope"] = "request_started_at_to_delivery_ready"
    started_at = timing.get("request_started_at") or timing.get("process_started_at")
    target["started_at"] = started_at
    target["ended_at"] = completed_at
    try:
        if not isinstance(started_at, str) or not started_at.strip():
            raise ValueError("missing timing start")
        elapsed_seconds = (
            pc.parse_time(completed_at) - pc.parse_time(started_at)
        ).total_seconds()
    except (AttributeError, TypeError, ValueError):
        target["elapsed_minutes"] = None
        target["met"] = None
    else:
        target["elapsed_minutes"] = round(elapsed_seconds / 60, 3)
        target["met"] = elapsed_seconds <= int(target["target_minutes"]) * 60
    target["soft_target_missed"] = target.get("met") is False
    append = pc.append_event
    append(
        state,
        "formal_overview_completed",
        completed_at,
        details={"output_path": str(overview), "candidate_count": 8, "layout": "2x4"},
    )
    append(
        state,
        "process_completed",
        completed_at,
        details={
            "formal_candidate_count": 8,
            "overview_layout": "2x4",
            "diversity_status": review.get("status"),
            "post_delivery_audit_pending": True,
        },
    )
    state["fast8_control_plane"] = {
        "version": CONTROL_VERSION,
        "delivery_mode": "lean_then_async_audit",
        "delivered_at": completed_at,
        "post_delivery_audit_status": "pending",
    }
    pc.atomic_write_json(state_path, state)
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
        raise SystemExit("Fast8 两行交付校验失败：" + json.dumps(violations, ensure_ascii=False))
    return {
        "status": "completed",
        "overview": str(overview),
        "delivery_message": str(delivery_path),
        "delivery_text": delivery_text,
        "formal_candidates": finalized,
    }


def post_delivery(state_path: Path) -> dict[str, Any]:
    """Run handoff, full audit, health, and central index after links exist."""

    state, project_dir = require_fast8(state_path)
    delivery = project_dir / "state" / "delivery_message.md"
    if state.get("status") != "completed" or not delivery.is_file():
        raise SystemExit("post-delivery 只允许在两行链接已经落盘后运行")
    result: dict[str, Any] = {
        "fast8_control_plane_version": CONTROL_VERSION,
        "status": "ok",
        "delivery_message": str(delivery),
        "started_at": pc.now_iso(),
    }
    try:
        result["handoff"] = capture(
            pc.command_write_handoff,
            state=str(state_path),
            project_dir=str(project_dir),
            unresolved_issues_json=None,
            next_allowed_actions_json=None,
            timestamp=None,
        )
    except (Exception, SystemExit) as exc:
        result["status"] = "attention"
        result["handoff"] = {"status": "warning", "error": str(exc)}
    try:
        result["validation"] = capture(
            pc.command_validate_state, state=str(state_path), complete=True
        )
    except (Exception, SystemExit) as exc:
        result["status"] = "attention"
        result["validation"] = {"status": "warning", "error": str(exc)}
    try:
        result["monitoring"] = pc.write_run_health_report(
            state_path=state_path,
            state=pc.read_json(state_path),
            timestamp=pc.now_iso(),
            best_effort_registry=True,
        )
    except (Exception, SystemExit) as exc:
        result["status"] = "attention"
        result["monitoring"] = {"status": "warning", "error": str(exc)}
    result["finished_at"] = pc.now_iso()
    sidecar = project_dir / "state" / "post_delivery_control_plane_v1.json"
    pc.atomic_write_json(sidecar, result)
    return {**result, "report_path": str(sidecar)}


def await_close(state_path: Path, wait_seconds: float, poll_interval: float) -> dict[str, Any]:
    deadline = time.monotonic() + wait_seconds
    while True:
        state, project_dir = require_fast8(state_path)
        review = state.get("diversity_review") or {}
        job_value = review.get("latest_job_path")
        if isinstance(job_value, str) and Path(job_value).is_file():
            job_path = Path(job_value).resolve()
            job = pc.read_json(job_path)
            report_value = job.get("report_output_path")
            if isinstance(report_value, str) and Path(report_value).is_file():
                report_path = Path(report_value).resolve()
                try:
                    json.loads(report_path.read_bytes().decode("utf-8"))
                except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
                    pass
                else:
                    applied = capture(
                        pc.command_apply_fast8_diversity_report,
                        project_dir=str(project_dir),
                        state=str(state_path),
                        review_job=str(job_path),
                        report_file=str(report_path),
                        timestamp=None,
                    )
                    decision = applied.get("decision") or applied.get("status")
                    refreshed = pc.read_json(state_path)
                    review_status = (refreshed.get("diversity_review") or {}).get("status")
                    if review_status in {"pass", "best_effort"}:
                        final = lean_finalize(state_path)
                        return {"status": "completed", "judge": applied, **final}
                    return {
                        "status": "replacement_required",
                        "decision": decision,
                        "replacement_styles": (refreshed.get("diversity_review") or {}).get(
                            "replacement_styles", []
                        ),
                    }
        if time.monotonic() >= deadline:
            return {"status": "waiting_for_judge_report"}
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


def render_action(manifest: dict[str, Any]) -> str:
    state = shlex.quote(str(manifest["state_path"]))
    script = shlex.quote(str(SCRIPT_PATH))
    manifest_path = shlex.quote(str(manifest["manifest_path"]))
    manifest_sha256 = shlex.quote(str(manifest["manifest_sha256"]))
    imagegen_concurrency = int(manifest["global_imagegen_concurrency"])
    seats_json = json.dumps(manifest["seats"], ensure_ascii=False)
    return f'''(async () => {{
const seats = {seats_json};
const py = "python3";
const shQuote = (v) => "'" + String(v).replaceAll("'", "'\\"'\\"'") + "'";
const run = async (args, wait=300000) => {{
  let r = await tools.exec_command({{cmd: `${{py}} {script} ${{args}}`, workdir: {json.dumps(str(SCRIPT_PATH.parent.parent))}, yield_time_ms: Math.min(wait, 30000), max_output_tokens: 2000}});
  while (r.session_id) r = await tools.write_stdin({{session_id:r.session_id, chars:"", yield_time_ms:30000, max_output_tokens:2000}});
  if (r.exit_code !== 0) throw new Error(r.output || "control command failed");
  return JSON.parse((r.output || "{{}}").trim());
}};
const findPath = (value) => {{
  const seen = new Set();
  const walk = (v) => {{
    if (v == null || seen.has(v)) return null;
    if (typeof v === "string") return v.includes("/exec-") && v.includes(".png") ? v : null;
    if (typeof v !== "object") return null;
    seen.add(v);
    for (const key of ["savedPath", "saved_path", "output_hint", "path"]) {{ if (key in v) {{ const p=walk(v[key]); if (p) return p; }} }}
    for (const [key, child] of Object.entries(v)) {{ if (!["data", "image_url"].includes(key)) {{ const p=walk(child); if (p) return p; }} }}
    return null;
  }};
  return walk(value);
}};
const branch = async (seat) => {{
  const ticket = shQuote(seat.ticket_path);
  let started = new Date().toISOString();
  let claim;
  let rpcCompleted = false;
  let phase = "claim";
  try {{
    claim = await run(`claim --state {state} --ticket ${{ticket}} --manifest {manifest_path} --manifest-sha256 {manifest_sha256} --capacity {imagegen_concurrency} --wait-seconds {CLAIM_WAIT_SECONDS}`);
    if (claim.status !== "claimed") throw new Error(`claim failed: ${{claim.status}}`);
    started = new Date().toISOString();
    phase = "imagegen_rpc";
    const input = {{prompt: seat.imagegen_prompt}};
    if (seat.imagegen_referenced_paths.length) input.referenced_image_paths = seat.imagegen_referenced_paths;
    const result = await tools.image_gen__imagegen(input);
    rpcCompleted = true;
    phase = "artifact_handoff";
    const finished = new Date().toISOString();
    const savedPath = findPath(result);
    const toolId = savedPath ? (savedPath.match(/(exec-[0-9a-fA-F-]{{36}})\\.png/) || [])[1] : null;
    phase = "receipt";
    return await run(`receipt --state {state} --ticket ${{ticket}} --tool-status completed --tool-started-at ${{shQuote(started)}} --tool-finished-at ${{shQuote(finished)}} ${{savedPath ? `--saved-path ${{shQuote(savedPath)}}` : ""}} ${{toolId ? `--tool-call-id ${{shQuote(toolId)}}` : ""}}`);
  }} catch (error) {{
    const finished = new Date().toISOString();
    if (claim && claim.status === "claimed") {{
      if (rpcCompleted) {{
        try {{
          return await run(`receipt --state {state} --ticket ${{ticket}} --tool-status completed --tool-started-at ${{shQuote(started)}} --tool-finished-at ${{shQuote(finished)}}`);
        }} catch (fallbackError) {{
          throw new Error(`post_imagegen_${{phase}}_failed; artifact forensics required; ${{fallbackError}}`);
        }}
      }}
      try {{ await run(`receipt --state {state} --ticket ${{ticket}} --tool-status failed --failure-class backend_failed --tool-error-code burst_exception --tool-started-at ${{shQuote(started)}} --tool-finished-at ${{shQuote(finished)}}`); }} catch (_) {{}}
    }}
    throw error;
  }} finally {{
    try {{ await run(`release --state {state} --ticket ${{ticket}}`); }} catch (_) {{}}
  }}
}};
const results = await Promise.allSettled(seats.map(branch));
const settled = await run(`settle --state {state}`);
let judge = null;
if (settled.all_anchor_tools_completed) judge = await run(`prepare-judge --state {state}`);
text(JSON.stringify({{results: results.map((r,i)=>({{style:seats[i].style,status:r.status}})), settled, judge}}));
}})()'''


def verify_baseline(baseline_path: Path) -> dict[str, Any]:
    baseline = pc.read_json(baseline_path)
    project_dir = Path(str(baseline.get("p31_project_dir"))).resolve()
    mismatches: list[str] = []
    for style in STYLES:
        expected = (baseline.get("styles") or {}).get(style) or {}
        job_path = project_dir / "style_jobs" / f"style_{style}.json"
        job = pc.read_json(job_path)
        actual = {
            "imagegen_prompt_fingerprint": job.get("imagegen_prompt_fingerprint"),
            "imagegen_input_fingerprint": job.get("imagegen_input_fingerprint"),
            "job_sha256": pc.file_sha256(job_path),
            "referenced_paths": job.get("imagegen_referenced_paths") or [],
        }
        if actual != expected:
            mismatches.append(style)
    judge_fingerprint = baseline.get("judge_standard_fingerprint") or {}
    judge_prompt_path = SCRIPT_PATH.parent.parent / "prompts" / "diversity-judge-worker.md"
    quality_rules_expected = judge_fingerprint.get("quality_decision_rules_sha256")
    if quality_rules_expected:
        judge_text = judge_prompt_path.read_text(encoding="utf-8")
        quality_rules = judge_text.split("判断边界：", 1)[1].split(
            "禁止修改正式 state", 1
        )[0]
        judge_expected = quality_rules_expected
        judge_actual = hashlib.sha256(quality_rules.encode("utf-8")).hexdigest()
    else:
        judge_expected = judge_fingerprint.get("prompt_sha256")
        judge_actual = pc.file_sha256(judge_prompt_path)
    if judge_actual != judge_expected:
        mismatches.append("judge_prompt")
    return {"status": "pass" if not mismatches else "mismatch", "mismatches": mismatches}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    director_prepare = sub.add_parser("prepare-directors")
    director_prepare.add_argument("--state", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--state", required=True)
    prepare.add_argument("--no-dispatch", action="store_true")
    prepare.add_argument("--render-action", action="store_true")
    claim = sub.add_parser("claim")
    claim.add_argument("--state", required=True)
    claim.add_argument("--ticket", required=True)
    claim.add_argument("--manifest", required=True)
    claim.add_argument("--manifest-sha256", required=True)
    claim.add_argument("--capacity", type=int, required=True)
    claim.add_argument("--wait-seconds", type=float, default=CLAIM_WAIT_SECONDS)
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--state", required=True)
    receipt.add_argument("--ticket", required=True)
    receipt.add_argument("--tool-status", choices=("completed", "failed"), required=True)
    receipt.add_argument("--saved-path")
    receipt.add_argument("--tool-call-id")
    receipt.add_argument("--tool-started-at", required=True)
    receipt.add_argument("--tool-finished-at", required=True)
    receipt.add_argument("--failure-class")
    receipt.add_argument("--tool-error-code")
    release = sub.add_parser("release")
    release.add_argument("--state", required=True)
    release.add_argument("--ticket", required=True)
    settle_parser = sub.add_parser("settle")
    settle_parser.add_argument("--state", required=True)
    judge = sub.add_parser("prepare-judge")
    judge.add_argument("--state", required=True)
    close = sub.add_parser("await-close")
    close.add_argument("--state", required=True)
    close.add_argument("--wait-seconds", type=float, default=240)
    close.add_argument("--poll-interval", type=float, default=0.5)
    finalize = sub.add_parser("lean-finalize")
    finalize.add_argument("--state", required=True)
    post = sub.add_parser("post-delivery")
    post.add_argument("--state", required=True)
    verify = sub.add_parser("verify-baseline")
    verify.add_argument("--baseline", required=True)
    return parser


def main() -> None:
    pc.configure_utf8_stdio()
    args = build_parser().parse_args()
    if args.command == "prepare-directors":
        result = prepare_director_inputs(Path(args.state).resolve())
        emit(result)
        if result["status"] != "ok":
            raise SystemExit(1)
    elif args.command == "prepare":
        result = build_manifest(Path(args.state).resolve(), dispatch=not args.no_dispatch)
        if args.render_action:
            print(render_action(result))
        else:
            emit(
                {key: value for key, value in result.items() if key != "seats"}
                | {"seat_count": len(result["seats"])}
            )
    elif args.command == "claim":
        emit(
            claim_ticket(
                Path(args.state).resolve(),
                Path(args.ticket).resolve(),
                args.wait_seconds,
                manifest_path=Path(args.manifest).resolve(),
                manifest_sha256=args.manifest_sha256,
                capacity_limit=args.capacity,
            )
        )
    elif args.command == "receipt":
        emit(
            write_receipt(
                Path(args.state).resolve(),
                Path(args.ticket).resolve(),
                tool_status=args.tool_status,
                saved_path=args.saved_path,
                tool_call_id=args.tool_call_id,
                tool_started_at=args.tool_started_at,
                tool_finished_at=args.tool_finished_at,
                failure_class=args.failure_class,
                tool_error_code=args.tool_error_code,
            )
        )
    elif args.command == "release":
        emit(release_ticket(Path(args.state).resolve(), Path(args.ticket).resolve()))
    elif args.command == "settle":
        emit(settle(Path(args.state).resolve()))
    elif args.command == "prepare-judge":
        emit(prepare_judge(Path(args.state).resolve()))
    elif args.command == "await-close":
        emit(await_close(Path(args.state).resolve(), args.wait_seconds, args.poll_interval))
    elif args.command == "lean-finalize":
        emit(lean_finalize(Path(args.state).resolve()))
    elif args.command == "post-delivery":
        emit(post_delivery(Path(args.state).resolve()))
    elif args.command == "verify-baseline":
        result = verify_baseline(Path(args.baseline).resolve())
        emit(result)
        if result["status"] != "pass":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
