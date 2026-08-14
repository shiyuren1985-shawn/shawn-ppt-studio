#!/usr/bin/env python3
"""Canonical, deterministic control plane for one user-requested image edit.

This module owns only the technical handoff around one ImageGen edit.  It does
not call ImageGen, select a candidate, alter the parent run, or add a visual
reviewer.  The caller must first ``prepare`` the run, invoke ImageGen exactly
once with the verified parent image, and then pass the completed ``savedPath``
to ``complete``.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat as stat_module
import struct
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
import pipeline_control as pc


CONTRACT_VERSION = 1
RUN_MODE = "single_image_edit"
GENERATED_IMAGES_ROOT = (Path.home() / ".codex" / "generated_images").resolve()
CENTRAL_IMAGEGEN_CAPACITY = 5
DEFAULT_CLAIM_WAIT_SECONDS = 600.0
PAGE_ID_PATTERN = re.compile(r"^P0*([1-9]\d{0,2})$", re.IGNORECASE)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REVISION_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ContractError(RuntimeError):
    """A stable, user-facing hard-gate failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def fail(code: str, message: str) -> None:
    raise ContractError(code, message)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_text(value: Any, name: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        fail("invalid_input", f"{name} must be a non-empty string")
    if len(value) > maximum or "\x00" in value or "\n" in value or "\r" in value:
        fail("invalid_input", f"{name} is not a valid bounded single-line string")
    return value.strip()


def require_sha256(value: Any, name: str) -> str:
    text = require_text(value, name, 80).lower()
    if not SHA256_PATTERN.fullmatch(text):
        fail("invalid_input", f"{name} must be 64 lowercase hexadecimal characters")
    return text


def canonical_page_id(value: Any) -> str:
    match = PAGE_ID_PATTERN.fullmatch(require_text(value, "page_id", 16))
    if not match:
        fail("invalid_page_id", f"invalid page_id: {value}")
    return f"P{int(match.group(1)):02d}"


def require_absolute_path(value: Any, name: str) -> Path:
    text = require_text(value, name, 4096)
    path = Path(text).expanduser()
    if not path.is_absolute() or str(path) != str(Path(os.path.normpath(str(path)))):
        fail("invalid_path", f"{name} must be an absolute normalized path")
    return path


def require_regular_real_file(value: Any, name: str) -> Path:
    path = require_absolute_path(value, name)
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail("missing_file", f"{name} does not exist: {path}")
    if stat_module.S_ISLNK(info.st_mode) or not stat_module.S_ISREG(info.st_mode):
        fail("invalid_file", f"{name} must be a regular file and not a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        fail("invalid_file", f"{name} cannot be resolved: {error}")
    if resolved != path:
        fail("invalid_file", f"{name} must not traverse a symlink")
    return path


def require_real_directory(value: Any, name: str) -> Path:
    path = require_absolute_path(value, name)
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail("missing_directory", f"{name} does not exist: {path}")
    if stat_module.S_ISLNK(info.st_mode) or not stat_module.S_ISDIR(info.st_mode):
        fail("invalid_directory", f"{name} must be a real directory and not a symlink")
    if path.resolve(strict=True) != path:
        fail("invalid_directory", f"{name} must not traverse a symlink")
    return path


def relative_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def read_json(path: Path, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        fail("invalid_json", f"{name} is not readable JSON: {error}")
    if not isinstance(payload, dict):
        fail("invalid_json", f"{name} must contain a JSON object")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def parse_outline_identity(path: Path, expected_revision: str) -> dict[str, Any]:
    outline = require_regular_real_file(str(path), "outline_path")
    match = REVISION_PATTERN.fullmatch(require_text(expected_revision, "expected_revision", 80).lower())
    if not match:
        fail("invalid_revision", "expected_revision must use sha256:<64 lowercase hex>")
    data = outline.read_bytes()
    actual_sha256 = sha256_bytes(data)
    if actual_sha256 != match.group(1):
        fail("outline_revision_conflict", "authoritative outline revision has changed")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        fail("invalid_outline", "authoritative outline must be UTF-8 Markdown")
    if not text.startswith("---\n"):
        fail("invalid_outline", "authoritative outline is missing YAML front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        fail("invalid_outline", "authoritative outline YAML front matter is not closed")
    frontmatter = text[4:end]
    if len(re.findall(r"^slide_identity_required:\s*true\s*$", frontmatter, re.MULTILINE | re.I)) != 1:
        fail("invalid_outline", "outline must enable slide_identity_required exactly once")
    deck_matches = re.findall(r"^deck_uid:\s*(\S.*?)\s*$", frontmatter, re.MULTILINE)
    if len(deck_matches) != 1:
        fail("invalid_outline", "outline must declare deck_uid exactly once")
    slide_uids: dict[str, str] = {}
    for raw_page, raw_uid in re.findall(r"^\s{2}(P\d+):\s*(\S.*?)\s*$", frontmatter, re.MULTILINE | re.I):
        page_id = canonical_page_id(raw_page)
        uid = raw_uid.strip().strip("\"'")
        if page_id in slide_uids or not uid:
            fail("invalid_outline", "outline has invalid or duplicate slide UID entries")
        slide_uids[page_id] = uid
    if not slide_uids or len(set(slide_uids.values())) != len(slide_uids):
        fail("invalid_outline", "outline slide UIDs must be non-empty and unique")
    return {
        "path": str(outline),
        "sha256": actual_sha256,
        "revision": f"sha256:{actual_sha256}",
        "deck_uid": deck_matches[0].strip().strip("\"'"),
        "slide_uids": slide_uids,
    }


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        fail("invalid_image", "ImageGen savedPath must be a valid PNG file")
    width, height = struct.unpack(">II", header[16:24])
    if width < 1000 or height < 500 or abs((width / height) - (16 / 9)) > 0.03:
        fail("invalid_image_dimensions", f"edited image must be a usable 16:9 slide, got {width}x{height}")
    return width, height


def verify_parent_handoff(
    candidate_root: Path,
    handoff_path: Path,
    expected_handoff_sha256: str,
    candidate_id: str,
    deck_uid: str,
    slide_uid: str,
    page_id: str,
) -> dict[str, Any]:
    handoff_file = require_regular_real_file(str(handoff_path), "parent_handoff_path")
    if not relative_within(candidate_root, handoff_file):
        fail("parent_outside_candidate_root", "parent handoff must be below the approved candidate root")
    actual_handoff_sha256 = sha256_file(handoff_file)
    if actual_handoff_sha256 != expected_handoff_sha256:
        fail("parent_handoff_changed", "parent handoff hash does not match the verified reference")
    handoff = read_json(handoff_file, "parent handoff")
    if handoff.get("status") not in {"candidate_ready", "accepted"}:
        fail("parent_handoff_not_ready", "parent handoff is not candidate-ready")
    project_dir = require_real_directory(handoff.get("project_dir"), "parent project_dir")
    if handoff_file != project_dir / "state" / "handoff.json":
        fail("invalid_parent_handoff", "parent handoff is not canonical for its project_dir")
    if not relative_within(candidate_root, project_dir) or project_dir == candidate_root:
        fail("invalid_parent_handoff", "parent project_dir is outside the candidate root")
    run_id = require_text(handoff.get("run_id"), "parent run_id", 256)

    for key in ("state_ref", "source_snapshot_ref"):
        ref = handoff.get(key)
        if not isinstance(ref, dict):
            fail("parent_handoff_unverified", f"parent handoff is missing {key}")
        ref_path = require_regular_real_file(ref.get("path"), f"parent {key}.path")
        ref_sha = require_sha256(ref.get("sha256"), f"parent {key}.sha256")
        if not relative_within(project_dir, ref_path) or sha256_file(ref_path) != ref_sha:
            fail("parent_handoff_unverified", f"parent {key} hash or path is invalid")

    identity = handoff.get("slide_identity")
    if not isinstance(identity, dict) or identity.get("deck_uid") != deck_uid:
        fail("parent_identity_mismatch", "parent handoff deck UID does not match")
    identities = {
        canonical_page_id(key): value
        for key, value in (identity.get("slide_uids") or {}).items()
    }
    if identities.get(page_id) != slide_uid:
        fail("parent_identity_mismatch", "parent handoff slide UID does not match")

    matches = [
        item
        for item in handoff.get("candidates") or []
        if isinstance(item, dict) and item.get("candidate_id") == candidate_id
    ]
    if len(matches) != 1:
        fail("parent_candidate_missing", "parent candidate_id must occur exactly once in the verified handoff")
    candidate = matches[0]
    if (
        candidate.get("deck_uid") != deck_uid
        or candidate.get("slide_uid") != slide_uid
        or canonical_page_id(candidate.get("page_id")) != page_id
    ):
        fail("parent_identity_mismatch", "parent candidate identity does not match the edit scope")
    parent_path = require_regular_real_file(candidate.get("path"), "parent candidate path")
    if not relative_within(project_dir / "origin_image", parent_path):
        fail("invalid_parent_candidate", "parent candidate must be in its canonical origin_image directory")
    parent_sha256 = require_sha256(candidate.get("sha256"), "parent candidate sha256")
    if sha256_file(parent_path) != parent_sha256:
        fail("parent_candidate_changed", "parent candidate hash no longer matches its handoff")
    width, height = png_dimensions(parent_path)
    recorded_width = candidate.get("width")
    recorded_height = candidate.get("height")
    if recorded_width not in {None, width} or recorded_height not in {None, height}:
        fail("parent_candidate_changed", "parent candidate dimensions no longer match its handoff")
    return {
        "candidate_id": candidate_id,
        "path": str(parent_path),
        "sha256": parent_sha256,
        "width": width,
        "height": height,
        "source_run_id": run_id,
        "handoff_path": str(handoff_file),
        "handoff_sha256": actual_handoff_sha256,
    }


def verify_direct_parent_refs(
    value: Any,
    deck_uid: str,
    slide_uid: str,
) -> dict[str, Any]:
    """Revalidate a confirmed legacy selection without inventing a parent run.

    The Studio owns the real-time selection check.  This control plane only
    accepts its bounded projection and independently verifies the immutable
    filesystem evidence before creating a new edit project.
    """

    if isinstance(value, str):
        raw = require_text(value, "direct_parent_refs_json", 16384)
        try:
            refs = json.loads(raw)
        except json.JSONDecodeError as error:
            fail("invalid_direct_parent_refs", f"direct_parent_refs_json is invalid JSON: {error}")
    else:
        refs = value
    if not isinstance(refs, dict):
        fail("invalid_direct_parent_refs", "direct_parent_refs must be a JSON object")
    expected_keys = {
        "deck_uid",
        "slide_uid",
        "candidate_id",
        "path",
        "sha256",
        "width",
        "height",
        "source_revision_status",
    }
    if set(refs) != expected_keys:
        fail("invalid_direct_parent_refs", "direct_parent_refs has unsupported or missing fields")
    if (
        require_text(refs.get("deck_uid"), "direct parent deck_uid", 256) != deck_uid
        or require_text(refs.get("slide_uid"), "direct parent slide_uid", 256) != slide_uid
    ):
        fail("parent_identity_mismatch", "direct parent deck/slide UID does not match the edit scope")
    source_revision_status = require_text(
        refs.get("source_revision_status"), "direct parent source_revision_status", 32
    )
    if source_revision_status != "unrecorded":
        fail(
            "invalid_source_revision_status",
            "direct parent source_revision_status must be unrecorded when no canonical source evidence exists",
        )
    parent_path = require_regular_real_file(refs.get("path"), "direct parent path")
    parent_sha256 = require_sha256(refs.get("sha256"), "direct parent sha256")
    if sha256_file(parent_path) != parent_sha256:
        fail("parent_candidate_changed", "direct parent hash no longer matches the selection projection")
    width, height = png_dimensions(parent_path)
    if (
        not isinstance(refs.get("width"), int)
        or isinstance(refs.get("width"), bool)
        or not isinstance(refs.get("height"), int)
        or isinstance(refs.get("height"), bool)
        or refs["width"] != width
        or refs["height"] != height
    ):
        fail("parent_candidate_changed", "direct parent dimensions no longer match the selection projection")
    return {
        "candidate_id": require_text(refs.get("candidate_id"), "direct parent candidate_id", 256),
        "path": str(parent_path),
        "sha256": parent_sha256,
        "width": width,
        "height": height,
        "source_kind": "direct_selection",
        "source_revision_status": source_revision_status,
        "source_run_id": None,
        "handoff_path": None,
        "handoff_sha256": None,
    }


def expected_project_dir(candidate_root: Path, page_id: str, request_started_at: str, execute_key: str) -> Path:
    try:
        timestamp = dt.datetime.fromisoformat(request_started_at.replace("Z", "+00:00"))
    except ValueError:
        fail("invalid_timestamp", "request_started_at must be an ISO-8601 timestamp")
    if not re.fullmatch(r"[0-9a-f]{16,64}", execute_key):
        fail("invalid_execute_key", "execute_key must be 16-64 lowercase hexadecimal characters")
    task_name = f"{page_id}_single_image_edit_{timestamp:%Y%m%d}_{execute_key[:16]}"
    return candidate_root / task_name


def request_identity(args: argparse.Namespace) -> dict[str, Any]:
    candidate_root = require_real_directory(args.candidate_root, "candidate_root")
    outline = parse_outline_identity(require_absolute_path(args.outline_path, "outline_path"), args.expected_revision)
    deck_uid = require_text(args.deck_uid, "deck_uid", 256)
    slide_uid = require_text(args.slide_uid, "slide_uid", 256)
    page_id = canonical_page_id(args.page_id)
    if outline["deck_uid"] != deck_uid or outline["slide_uids"].get(page_id) != slide_uid:
        fail("outline_identity_mismatch", "current outline does not map the requested deck/slide/page identity")
    direct_parent_refs_json = getattr(args, "direct_parent_refs_json", None)
    legacy_values = [
        getattr(args, "parent_handoff_path", None),
        getattr(args, "parent_handoff_sha256", None),
        getattr(args, "parent_candidate_id", None),
    ]
    if direct_parent_refs_json and any(legacy_values):
        fail("ambiguous_parent", "use either canonical parent handoff flags or direct_parent_refs, not both")
    if direct_parent_refs_json:
        parent = verify_direct_parent_refs(direct_parent_refs_json, deck_uid, slide_uid)
    else:
        if not all(legacy_values):
            fail("parent_required", "canonical parent handoff flags or direct_parent_refs are required")
        parent_handoff_path = require_absolute_path(legacy_values[0], "parent_handoff_path")
        parent_handoff_sha256 = require_sha256(legacy_values[1], "parent_handoff_sha256")
        parent_candidate_id = require_text(legacy_values[2], "parent_candidate_id", 256)
        parent = verify_parent_handoff(
            candidate_root,
            parent_handoff_path,
            parent_handoff_sha256,
            parent_candidate_id,
            deck_uid,
            slide_uid,
            page_id,
        )
    user_request_sha256 = require_sha256(args.user_request_sha256, "user_request_sha256")
    request_started_at = require_text(args.request_started_at, "request_started_at", 64)
    execute_key = require_text(args.execute_key, "execute_key", 64).lower()
    project_dir = expected_project_dir(candidate_root, page_id, request_started_at, execute_key)
    return {
        "candidate_root": str(candidate_root),
        "project_dir": str(project_dir),
        "run_id": f"single-edit-{execute_key[:24]}",
        "identity": {"deck_uid": deck_uid, "slide_uid": slide_uid, "page_id": page_id},
        "source_outline": {
            "path": outline["path"],
            "revision": outline["revision"],
            "sha256": outline["sha256"],
        },
        "parent_candidate": parent,
        "request": {
            "user_request_sha256": user_request_sha256,
            "request_started_at": request_started_at,
            "execute_key": execute_key,
        },
    }


def stable_request_view(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": value.get("run_id"),
        "project_dir": value.get("project_dir"),
        "identity": value.get("identity"),
        "source_outline": value.get("source_outline"),
        "parent_candidate": value.get("parent_candidate"),
        "request": value.get("request"),
    }


def prepare_edit(args: argparse.Namespace) -> dict[str, Any]:
    request = request_identity(args)
    project_dir = Path(request["project_dir"])
    state_dir = project_dir / "state"
    origin_dir = project_dir / "origin_image"
    state_path = state_dir / "single_image_edit_state.json"
    snapshot_path = state_dir / "source_snapshot.json"

    if project_dir.exists():
        if not project_dir.is_dir() or project_dir.is_symlink() or not state_path.is_file():
            fail("execute_key_collision", "existing project directory is not a compatible prepared edit")
        require_regular_real_file(str(state_path), "existing single image edit state")
        existing = read_json(state_path, "single image edit state")
        if stable_request_view(existing) != stable_request_view(request):
            fail("execute_key_collision", "execute_key is already bound to a different request")
        validate_state_bindings(existing, state_path)
        if existing.get("status") == "completed":
            verify_edit(str(state_path))
        return prepare_result(existing, idempotent=True)

    project_dir.mkdir(mode=0o700)
    state_dir.mkdir(mode=0o700)
    origin_dir.mkdir(mode=0o700)
    prepared_at = now_iso()
    snapshot = {
        "source_snapshot_contract_version": 1,
        "run_id": request["run_id"],
        "project_dir": request["project_dir"],
        "run_mode": RUN_MODE,
        "page_ids": [request["identity"]["page_id"]],
        "authoritative_source": {
            "path": request["source_outline"]["path"],
            "sha256": request["source_outline"]["sha256"],
        },
        "slide_identity": {
            "slide_identity_contract_version": 1,
            "required": True,
            "deck_uid": request["identity"]["deck_uid"],
            "slide_uids": {
                request["identity"]["page_id"]: request["identity"]["slide_uid"]
            },
            "source_path": request["source_outline"]["path"],
            "source_sha256": request["source_outline"]["sha256"],
            "identity_rule": "immutable_content_identity_not_page_or_title",
        },
        "snapshot_at": prepared_at,
    }
    atomic_write_json(snapshot_path, snapshot)
    state = {
        "single_image_edit_state_contract_version": CONTRACT_VERSION,
        "run_id": request["run_id"],
        "run_mode": RUN_MODE,
        "status": "prepared",
        "project_dir": request["project_dir"],
        "candidate_root": request["candidate_root"],
        "identity": request["identity"],
        "source_outline": request["source_outline"],
        "source_snapshot_path": str(snapshot_path),
        "source_snapshot_sha256": sha256_file(snapshot_path),
        "parent_candidate": request["parent_candidate"],
        "request": request["request"],
        "imagegen": {
            "status": "pending",
            "generated_images_root": str(GENERATED_IMAGES_ROOT),
            "saved_path": None,
            "saved_sha256": None,
        },
        "candidate": None,
        "events": [
            {
                "sequence": 1,
                "type": "single_image_edit_prepared",
                "occurred_at": prepared_at,
            }
        ],
        "prepared_at": prepared_at,
        "completed_at": None,
    }
    atomic_write_json(state_path, state)
    return prepare_result(state, idempotent=False)


def prepare_result(state: dict[str, Any], *, idempotent: bool) -> dict[str, Any]:
    result = {
        "contract_version": CONTRACT_VERSION,
        "status": state["status"],
        "idempotent": idempotent,
        "run_id": state["run_id"],
        "project_dir": state["project_dir"],
        "state_path": str(Path(state["project_dir"]) / "state" / "single_image_edit_state.json"),
        "parent_candidate": state["parent_candidate"],
        "request": state["request"],
    }
    if state.get("status") == "completed":
        handoff_path = Path(state["project_dir"]) / "state" / "handoff.json"
        require_regular_real_file(str(handoff_path), "completed handoff")
        result["native_refs"] = native_result(state, handoff_path, idempotent=True)["native_refs"]
    return result


def validate_saved_path(value: Any) -> tuple[Path, str, int, int, int]:
    root = require_real_directory(str(GENERATED_IMAGES_ROOT), "Codex generated_images root")
    saved_path = require_regular_real_file(value, "ImageGen savedPath")
    if not relative_within(root, saved_path) or saved_path == root:
        fail("saved_path_outside_imagegen", "savedPath must be below Codex generated_images")
    width, height = png_dimensions(saved_path)
    return saved_path, sha256_file(saved_path), width, height, saved_path.stat().st_size


def shared_slot_task(state: dict[str, Any]) -> dict[str, Any]:
    return {
        # The shared owner currently requires an A-H style key.  This is only a
        # registry lane; lineage/style metadata remains EDIT in our own state.
        "style": "A",
        "page_id": state["identity"]["page_id"],
        "action": "single_image_edit",
        "attempt": 1,
        "lease_kind": "single_image_edit_v1",
        "worker_ticket_sha256": state["request"]["execute_key"],
    }


def lease_task_key(task: dict[str, Any]) -> str:
    return f"{task['style']}/{task['page_id']}/{task['action']}/{task['attempt']}"


@contextlib.contextmanager
def locked_edit_state(state_path: Path):
    """Serialize one execute's mutations; this is not an ImageGen semaphore."""

    lock_path = state_path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def claim_edit(state_path_value: Any, wait_seconds: float) -> dict[str, Any]:
    state_path = require_regular_real_file(state_path_value, "state_path")
    with locked_edit_state(state_path):
        return _claim_edit_locked(state_path, wait_seconds)


def _claim_edit_locked(state_path: Path, wait_seconds: float) -> dict[str, Any]:
    state = read_json(state_path, "single image edit state")
    validate_state_bindings(state, state_path)
    if state.get("status") == "completed":
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "candidate_ready",
            "idempotent": True,
            "run_id": state["run_id"],
        }
    if state.get("status") != "prepared":
        fail("invalid_state", "only a prepared edit may claim ImageGen capacity")
    imagegen = state.get("imagegen") or {}
    if imagegen.get("status") == "leased" and imagegen.get("global_lease_id"):
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "claimed",
            "idempotent": True,
            "run_id": state["run_id"],
            "lease_id": imagegen["global_lease_id"],
        }
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    task = shared_slot_task(state)
    while True:
        acquired, deferred, lease_ids, remaining = pc.acquire_shared_imagegen_slots(
            state_path,
            state,
            [task],
            timestamp=pc.now_iso(),
            capacity_limit=CENTRAL_IMAGEGEN_CAPACITY,
        )
        if acquired:
            lease_id = lease_ids[lease_task_key(task)]
            occurred_at = now_iso()
            state["imagegen"] = {
                **imagegen,
                "status": "leased",
                "global_lease_id": lease_id,
                "lease_kind": "single_image_edit_v1",
                "leased_at": occurred_at,
            }
            state["events"].append(
                {
                    "sequence": len(state["events"]) + 1,
                    "type": "single_image_edit_imagegen_slot_claimed",
                    "occurred_at": occurred_at,
                    "global_lease_id": lease_id,
                }
            )
            atomic_write_json(state_path, state)
            return {
                "contract_version": CONTRACT_VERSION,
                "status": "claimed",
                "idempotent": False,
                "run_id": state["run_id"],
                "lease_id": lease_id,
                "remaining_capacity": remaining,
            }
        if not deferred:
            fail("imagegen_slot_inconsistent", "central ImageGen slot registry returned no result")
        if time.monotonic() >= deadline:
            return {
                "contract_version": CONTRACT_VERSION,
                "status": "capacity_wait_timeout",
                "idempotent": False,
                "run_id": state["run_id"],
            }
        time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))


def release_state_lease(state_path: Path, state: dict[str, Any], *, reset_pending: bool) -> int:
    lease_id = str((state.get("imagegen") or {}).get("global_lease_id") or "")
    released = pc.release_shared_imagegen_slots(state_path, state, [lease_id])
    if reset_pending and state.get("status") == "prepared" and lease_id:
        occurred_at = now_iso()
        state["imagegen"] = {
            **state["imagegen"],
            "status": "pending",
            "global_lease_id": None,
            "released_at": occurred_at,
        }
        state["events"].append(
            {
                "sequence": len(state["events"]) + 1,
                "type": "single_image_edit_imagegen_slot_released",
                "occurred_at": occurred_at,
                "released": released,
            }
        )
        atomic_write_json(state_path, state)
    return released


def release_edit(state_path_value: Any) -> dict[str, Any]:
    state_path = require_regular_real_file(state_path_value, "state_path")
    with locked_edit_state(state_path):
        return _release_edit_locked(state_path)


def _release_edit_locked(state_path: Path) -> dict[str, Any]:
    state = read_json(state_path, "single image edit state")
    validate_state_bindings(state, state_path)
    released = release_state_lease(state_path, state, reset_pending=True)
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "released",
        "run_id": state["run_id"],
        "released": released,
    }


def import_without_overwrite(source: Path, destination: Path, expected_sha256: str) -> None:
    if destination.exists():
        existing = require_regular_real_file(str(destination), "existing destination candidate")
        if sha256_file(existing) != expected_sha256:
            fail("candidate_collision", "destination candidate already exists with different bytes")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            created = True
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
    except Exception:
        if created and destination.exists() and destination.is_file():
            with contextlib_suppress_oserror():
                destination.unlink()
        raise
    if sha256_file(destination) != expected_sha256:
        fail("candidate_copy_failed", "imported candidate hash differs from ImageGen savedPath")


class contextlib_suppress_oserror:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exception_type: Any, exception: Any, traceback: Any) -> bool:
        return bool(exception_type and issubclass(exception_type, OSError))


def build_handoff(state: dict[str, Any], state_path: Path) -> dict[str, Any]:
    candidate = state["candidate"]
    identity = state["identity"]
    snapshot_path = Path(state["source_snapshot_path"])
    parent = state["parent_candidate"]
    generated_at = state["completed_at"]
    if parent.get("source_kind") == "direct_selection":
        lineage = {
            "derivation_kind": "single_image_edit",
            "parent_candidate_id": parent["candidate_id"],
            "parent_path": parent["path"],
            "parent_sha256": parent["sha256"],
            "source_run_id": None,
            "parent_source_kind": "direct_selection",
            "source_revision_status": parent["source_revision_status"],
        }
    else:
        # Preserve the v1 canonical-parent projection byte-for-byte.
        lineage = {
            "derivation_kind": "single_image_edit",
            "parent_candidate_id": parent["candidate_id"],
            "parent_path": parent["path"],
            "parent_sha256": parent["sha256"],
            "source_run_id": parent["source_run_id"],
            "parent_handoff_path": parent["handoff_path"],
            "parent_handoff_sha256": parent["handoff_sha256"],
        }
    return {
        "handoff_contract_version": 1,
        "run_id": state["run_id"],
        "run_mode": RUN_MODE,
        "project_dir": state["project_dir"],
        "pipeline_status": "completed",
        "status": "candidate_ready",
        "current_stage": "candidate_ready",
        "page_scope": [identity["page_id"]],
        "authoritative_source": state["source_outline"],
        "state_ref": {
            "path": str(state_path),
            "sha256": sha256_file(state_path),
            "state_contract_version": CONTRACT_VERSION,
        },
        "source_snapshot_ref": {
            "path": str(snapshot_path),
            "sha256": sha256_file(snapshot_path),
            "source_snapshot_contract_version": 1,
        },
        "slide_identity": {
            "slide_identity_contract_version": 1,
            "required": True,
            "deck_uid": identity["deck_uid"],
            "slide_uids": {identity["page_id"]: identity["slide_uid"]},
            "source_path": state["source_outline"]["path"],
            "source_sha256": state["source_outline"]["sha256"],
            "identity_rule": "immutable_content_identity_not_page_or_title",
        },
        "lineage": lineage,
        "request": state["request"],
        "candidates": [candidate],
        "overview": None,
        "user_selection": {
            "selected": False,
            "candidate_id": None,
            "selected_style": None,
            "selected_page_id": None,
            "recorded_at": None,
        },
        "unresolved_issues": [],
        "next_allowed_actions": ["await_user_candidate_selection", "create_single_image_edit"],
        "generated_at": generated_at,
    }


def validate_state_bindings(state: dict[str, Any], state_path: Path) -> None:
    if state.get("run_mode") != RUN_MODE:
        fail("invalid_state", "state run_mode is not single_image_edit")
    project_dir = require_real_directory(state.get("project_dir"), "project_dir")
    candidate_root = require_real_directory(state.get("candidate_root"), "candidate_root")
    if state_path != project_dir / "state" / "single_image_edit_state.json":
        fail("invalid_state_path", "state_path does not match project_dir")
    identity = state.get("identity") or {}
    deck_uid = require_text(identity.get("deck_uid"), "state deck_uid", 256)
    slide_uid = require_text(identity.get("slide_uid"), "state slide_uid", 256)
    page_id = canonical_page_id(identity.get("page_id"))
    source = state.get("source_outline") or {}
    outline = parse_outline_identity(
        require_absolute_path(source.get("path"), "state outline path"),
        source.get("revision"),
    )
    if (
        source.get("sha256") != outline["sha256"]
        or outline["deck_uid"] != deck_uid
        or outline["slide_uids"].get(page_id) != slide_uid
    ):
        fail("outline_identity_mismatch", "state source outline identity or revision is invalid")
    request = state.get("request") or {}
    execute_key = require_text(request.get("execute_key"), "state execute_key", 64)
    require_sha256(request.get("user_request_sha256"), "state user_request_sha256")
    request_started_at = require_text(request.get("request_started_at"), "state request_started_at", 64)
    if expected_project_dir(candidate_root, page_id, request_started_at, execute_key) != project_dir:
        fail("invalid_state", "project_dir is not the deterministic directory for this execute")
    if state.get("run_id") != f"single-edit-{execute_key[:24]}":
        fail("invalid_state", "run_id is not bound to execute_key")
    parent = state.get("parent_candidate") or {}
    if parent.get("source_kind") == "direct_selection":
        direct_refs = {
            key: parent.get(key)
            for key in (
                "candidate_id",
                "path",
                "sha256",
                "width",
                "height",
                "source_revision_status",
            )
        }
        direct_refs.update({"deck_uid": deck_uid, "slide_uid": slide_uid})
        verified_parent = verify_direct_parent_refs(direct_refs, deck_uid, slide_uid)
    else:
        verified_parent = verify_parent_handoff(
            candidate_root,
            require_absolute_path(parent.get("handoff_path"), "state parent handoff path"),
            require_sha256(parent.get("handoff_sha256"), "state parent handoff sha256"),
            require_text(parent.get("candidate_id"), "state parent candidate_id", 256),
            deck_uid,
            slide_uid,
            page_id,
        )
    if verified_parent != parent:
        fail("parent_candidate_changed", "state parent candidate differs from verified handoff")
    snapshot_path = require_regular_real_file(state.get("source_snapshot_path"), "source snapshot")
    if snapshot_path != project_dir / "state" / "source_snapshot.json":
        fail("invalid_state", "source snapshot path is not canonical")
    if sha256_file(snapshot_path) != require_sha256(
        state.get("source_snapshot_sha256"), "state source snapshot sha256"
    ):
        fail("invalid_state", "source snapshot hash differs from state")
    snapshot = read_json(snapshot_path, "source snapshot")
    snapshot_identity = snapshot.get("slide_identity") or {}
    if (
        snapshot.get("run_id") != state.get("run_id")
        or snapshot.get("run_mode") != RUN_MODE
        or snapshot_identity.get("deck_uid") != deck_uid
        or snapshot_identity.get("slide_uids") != {page_id: slide_uid}
        or snapshot_identity.get("source_path") != outline["path"]
        or snapshot_identity.get("source_sha256") != outline["sha256"]
    ):
        fail("invalid_state", "source snapshot identity differs from state")


def complete_edit(state_path_value: Any, saved_path_value: Any) -> dict[str, Any]:
    state_path = require_regular_real_file(state_path_value, "state_path")
    if state_path.name != "single_image_edit_state.json" or state_path.parent.name != "state":
        fail("invalid_state_path", "state_path is not a canonical single-image-edit state path")
    with locked_edit_state(state_path):
        return _complete_edit_locked(state_path, saved_path_value)


def _complete_edit_locked(state_path: Path, saved_path_value: Any) -> dict[str, Any]:
    state = read_json(state_path, "single image edit state")
    project_dir = require_real_directory(state.get("project_dir"), "project_dir")
    validate_state_bindings(state, state_path)

    if state.get("status") == "completed":
        saved_path_text = str(require_absolute_path(saved_path_value, "ImageGen savedPath"))
        if state.get("imagegen", {}).get("saved_path") != saved_path_text:
            fail("duplicate_execute", "this execute is already completed with a different savedPath")
        saved_path = Path(saved_path_text)
        if saved_path.exists():
            _, saved_sha256, _, _, _ = validate_saved_path(saved_path_text)
            if state.get("imagegen", {}).get("saved_sha256") != saved_sha256:
                fail("saved_path_changed", "completed ImageGen savedPath bytes have changed")
        candidate_path = require_regular_real_file(state.get("candidate", {}).get("path"), "candidate path")
        if sha256_file(candidate_path) != state["candidate"]["sha256"]:
            fail("candidate_changed", "completed candidate bytes have changed")
        handoff_path = project_dir / "state" / "handoff.json"
        expected = build_handoff(state, state_path)
        if handoff_path.exists() and read_json(handoff_path, "handoff") != expected:
            fail("handoff_changed", "existing handoff differs from the canonical projection")
        if not handoff_path.exists():
            atomic_write_json(handoff_path, expected)
        release_state_lease(state_path, state, reset_pending=False)
        return native_result(state, handoff_path, idempotent=True)

    if state.get("status") != "prepared":
        fail("invalid_state", "single-image-edit state is neither prepared nor completed")
    if state.get("imagegen", {}).get("status") != "leased" or not state.get("imagegen", {}).get(
        "global_lease_id"
    ):
        fail("imagegen_slot_not_claimed", "claim the shared central ImageGen slot before editing")
    try:
        saved_path, saved_sha256, width, height, size_bytes = validate_saved_path(saved_path_value)
        parent = state.get("parent_candidate") or {}
        if saved_path == Path(parent.get("path", "")) or saved_sha256 == parent.get("sha256"):
            fail("unchanged_candidate", "edited candidate must not be the parent file or an identical copy")
        page_id = canonical_page_id(state["identity"]["page_id"])
        execute_key = state["request"]["execute_key"]
        candidate_id = f"edit-{execute_key[:24]}-{page_id}"
        destination = project_dir / "origin_image" / f"single_edit_{execute_key[:16]}_page_{page_id}.png"
        import_without_overwrite(saved_path, destination, saved_sha256)
    except Exception:
        release_state_lease(state_path, state, reset_pending=True)
        raise
    completed_at = now_iso()
    candidate = {
        "candidate_id": candidate_id,
        "style_slot": "EDIT",
        "page_id": page_id,
        "role": "single_image_edit",
        "path": str(destination),
        "path_kind": "final_path",
        "width": width,
        "height": height,
        "size_bytes": size_bytes,
        "sha256": saved_sha256,
        "status": "candidate_ready",
        "qa_stage": "filesystem",
        "qa_scope": "filesystem_only",
        "deck_uid": state["identity"]["deck_uid"],
        "slide_uid": state["identity"]["slide_uid"],
        "derivation_kind": "single_image_edit",
        "parent_candidate_id": parent["candidate_id"],
        "parent_path": parent["path"],
        "parent_sha256": parent["sha256"],
        "source_run_id": parent["source_run_id"],
        "source_outline_revision": state["source_outline"]["revision"],
        "user_request_sha256": state["request"]["user_request_sha256"],
        "generated_at": completed_at,
    }
    if parent.get("source_kind") == "direct_selection":
        candidate["parent_source_kind"] = "direct_selection"
        candidate["source_revision_status"] = parent["source_revision_status"]
    state["status"] = "completed"
    state["imagegen"] = {
        **state["imagegen"],
        "status": "completed",
        "saved_path": str(saved_path),
        "saved_sha256": saved_sha256,
        "width": width,
        "height": height,
        "size_bytes": size_bytes,
        "released_at": completed_at,
    }
    state["candidate"] = candidate
    state["events"].append(
        {
            "sequence": len(state["events"]) + 1,
            "type": "single_image_edit_candidate_imported",
            "occurred_at": completed_at,
            "candidate_id": candidate_id,
            "candidate_path": str(destination),
            "candidate_sha256": saved_sha256,
        }
    )
    state["completed_at"] = completed_at
    atomic_write_json(state_path, state)
    handoff_path = project_dir / "state" / "handoff.json"
    atomic_write_json(handoff_path, build_handoff(state, state_path))
    release_state_lease(state_path, state, reset_pending=False)
    return native_result(state, handoff_path, idempotent=False)


def native_result(state: dict[str, Any], handoff_path: Path, *, idempotent: bool) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "candidate_ready",
        "idempotent": idempotent,
        "native_refs": {
            "project_dir": state["project_dir"],
            "state_path": str(Path(state["project_dir"]) / "state" / "single_image_edit_state.json"),
            "handoff_path": str(handoff_path),
            "run_id": state["run_id"],
        },
    }


def verify_edit(state_path_value: Any) -> dict[str, Any]:
    state_path = require_regular_real_file(state_path_value, "state_path")
    state = read_json(state_path, "single image edit state")
    validate_state_bindings(state, state_path)
    if state.get("status") != "completed" or state.get("run_mode") != RUN_MODE:
        fail("not_candidate_ready", "single-image-edit run is not completed")
    project_dir = require_real_directory(state.get("project_dir"), "project_dir")
    handoff_path = require_regular_real_file(str(project_dir / "state" / "handoff.json"), "handoff")
    if read_json(handoff_path, "handoff") != build_handoff(state, state_path):
        fail("handoff_changed", "handoff is not the canonical projection of state")
    candidate_path = require_regular_real_file(state["candidate"]["path"], "candidate path")
    if sha256_file(candidate_path) != state["candidate"]["sha256"]:
        fail("candidate_changed", "candidate hash differs from state")
    return native_result(state, handoff_path, idempotent=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--candidate-root", required=True)
    prepare.add_argument("--outline-path", required=True)
    prepare.add_argument("--expected-revision", required=True)
    prepare.add_argument("--deck-uid", required=True)
    prepare.add_argument("--slide-uid", required=True)
    prepare.add_argument("--page-id", required=True)
    prepare.add_argument("--parent-handoff-path")
    prepare.add_argument("--parent-handoff-sha256")
    prepare.add_argument("--parent-candidate-id")
    prepare.add_argument("--direct-parent-refs-json")
    prepare.add_argument("--user-request-sha256", required=True)
    prepare.add_argument("--request-started-at", required=True)
    prepare.add_argument("--execute-key", required=True)
    complete = subparsers.add_parser("complete")
    complete.add_argument("--state", required=True)
    complete.add_argument("--saved-path", required=True)
    claim = subparsers.add_parser("claim")
    claim.add_argument("--state", required=True)
    claim.add_argument("--wait-seconds", type=float, default=DEFAULT_CLAIM_WAIT_SECONDS)
    release = subparsers.add_parser("release")
    release.add_argument("--state", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--state", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_edit(args)
        elif args.command == "claim":
            result = claim_edit(args.state, args.wait_seconds)
        elif args.command == "release":
            result = release_edit(args.state)
        elif args.command == "complete":
            result = complete_edit(args.state, args.saved_path)
        else:
            result = verify_edit(args.state)
    except ContractError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
