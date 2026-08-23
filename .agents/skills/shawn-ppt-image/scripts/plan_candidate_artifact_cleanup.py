#!/usr/bin/env python3
"""Build a fail-closed cleanup plan for formally bound image candidates.

The planner is intentionally read-only.  A host such as Shawn PPT Studio may
validate the returned paths again and move them to Trash as one transaction.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLAN_VERSION = 1
STATE_NAMES = (
    "style_run_state.json",
    "selected_style_run_state.json",
    "single_image_edit_state.json",
)
ARTIFACT_ROOTS = (
    "style_jobs",
    "style_page_jobs",
    "page_jobs",
    "repair_jobs",
    "state/burst_claims",
    "state/selected_style_claims",
)
STYLE_PATTERN = re.compile(r"^[A-H]$")


class CleanupPlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    path: Path
    style: str | None
    page_id: str | None


def fail(message: str) -> None:
    raise CleanupPlanError(message)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"无法读取正式 JSON：{path}: {exc}")


def within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and not path.is_symlink()


def canonical_existing_file(value: Any, origin_root: Path) -> Path | None:
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        return None
    candidate = Path(value).expanduser().resolve()
    if not within(candidate, origin_root) or not regular_file(candidate):
        return None
    return candidate


def normalize_style(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    result = value.strip().upper()
    return result if STYLE_PATTERN.fullmatch(result) else None


def normalize_page(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    if not result or len(result) > 64 or "\x00" in result:
        return None
    return result


def locate_state(project_root: Path) -> Path:
    matches = [project_root / "state" / name for name in STATE_NAMES]
    matches = [path for path in matches if regular_file(path)]
    if len(matches) != 1:
        fail("工程必须且只能有一个受支持的正式候选状态")
    return matches[0]


def enumerate_candidates(state_path: Path, state: Any, origin_root: Path) -> list[Candidate]:
    if not isinstance(state, dict):
        fail("正式候选状态不是对象")
    candidates: list[Candidate] = []
    if state_path.name == "style_run_state.json":
        styles = state.get("styles")
        if not isinstance(styles, dict):
            fail("style_run_state 缺少 styles")
        for style_key, style_record in styles.items():
            style = normalize_style(style_key)
            pages = style_record.get("pages") if isinstance(style_record, dict) else None
            if style is None or not isinstance(pages, dict):
                continue
            for page_key, record in pages.items():
                if not isinstance(record, dict):
                    continue
                candidate_path = canonical_existing_file(
                    record.get("final_path") or record.get("selected_source"), origin_root
                )
                if candidate_path:
                    candidates.append(Candidate(candidate_path, style, normalize_page(page_key)))
    elif state_path.name == "selected_style_run_state.json":
        style = normalize_style(state.get("selected_style"))
        pages = state.get("pages")
        if not isinstance(pages, dict):
            fail("selected_style_run_state 缺少 pages")
        for page_key, record in pages.items():
            if not isinstance(record, dict):
                continue
            candidate_path = canonical_existing_file(
                record.get("final_path") or record.get("selected_source"), origin_root
            )
            if candidate_path:
                candidates.append(Candidate(candidate_path, style, normalize_page(page_key)))
    else:
        record = state.get("candidate")
        value = record.get("path") if isinstance(record, dict) else None
        value = value or (state.get("imagegen") or {}).get("saved_path")
        candidate_path = canonical_existing_file(value, origin_root)
        if candidate_path:
            identity = state.get("identity") if isinstance(state.get("identity"), dict) else {}
            candidates.append(
                Candidate(candidate_path, None, normalize_page(identity.get("page_id")))
            )
    unique: dict[Path, Candidate] = {}
    for candidate in candidates:
        previous = unique.get(candidate.path)
        if previous and previous != candidate:
            fail("同一候选路径绑定了冲突身份")
        unique[candidate.path] = candidate
    if not unique:
        fail("正式状态中没有仍存在的候选图片")
    return list(unique.values())


def owned_paths(value: Any, paths: set[Path]) -> set[Path]:
    """Return output bindings, never incidental referenced-image inputs."""

    ownership_keys = {
        "output_target",
        "output_path",
        "saved_path",
        "final_path",
        "candidate_path",
    }
    found: set[Path] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key in ownership_keys and isinstance(nested, str) and os.path.isabs(nested):
                    resolved = Path(nested).expanduser().resolve()
                    if resolved in paths:
                        found.add(resolved)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return found


def identity_fields(value: Any) -> tuple[set[str], set[str]]:
    styles: set[str] = set()
    pages: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key in {"style", "style_slot", "selected_style"}:
                    normalized = normalize_style(nested)
                    if normalized:
                        styles.add(normalized)
                elif key in {"page_id", "anchor_page_id"}:
                    normalized = normalize_page(nested)
                    if normalized:
                        pages.add(normalized)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return styles, pages


def artifact_files(project_root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for relative in ARTIFACT_ROOTS:
        root = project_root / relative
        if not root.is_dir() or root.is_symlink():
            continue
        for path in root.rglob("*.json"):
            resolved = path.resolve()
            if resolved in seen or not regular_file(resolved) or not within(resolved, root.resolve()):
                continue
            seen.add(resolved)
            yield resolved


def identities_for_scope(
    styles: set[str], pages: set[str], candidates: list[Candidate]
) -> set[Path]:
    matches: set[Path] = set()
    for candidate in candidates:
        if styles and candidate.style not in styles:
            continue
        if pages and candidate.page_id not in pages:
            continue
        if styles or pages:
            matches.add(candidate.path)
    return matches


def partial_artifacts(
    project_root: Path,
    candidates: list[Candidate],
    delete_paths: set[Path],
) -> list[dict[str, str]]:
    all_paths = {item.path for item in candidates}
    retained_paths = all_paths - delete_paths
    targets: list[dict[str, str]] = [
        {"path": str(candidate), "kind": "file", "reason": "candidate_image"}
        for candidate in sorted(delete_paths)
    ]
    for artifact in sorted(artifact_files(project_root)):
        value = load_json(artifact)
        direct = owned_paths(value, all_paths)
        styles, pages = identity_fields(value)
        scoped = identities_for_scope(styles, pages, candidates)
        bound = direct or scoped
        if not bound or bound & retained_paths or not bound <= delete_paths:
            continue
        targets.append(
            {"path": str(artifact), "kind": "file", "reason": "candidate_artifact"}
        )
    return targets


def build_plan(project_root_value: str, candidate_path_values: list[str]) -> dict[str, Any]:
    if not os.path.isabs(project_root_value):
        fail("project_root 必须是绝对路径")
    project_root = Path(project_root_value).expanduser().resolve()
    if not project_root.is_dir() or project_root.is_symlink():
        fail("project_root 必须是仍存在的真实目录")
    origin_root = (project_root / "origin_image").resolve()
    if not origin_root.is_dir() or origin_root.is_symlink() or not within(origin_root, project_root):
        fail("工程缺少规范 origin_image 目录")
    state_path = locate_state(project_root)
    state = load_json(state_path)
    declared_root = state.get("project_dir") if isinstance(state, dict) else None
    if declared_root is not None and (
        not isinstance(declared_root, str)
        or not os.path.isabs(declared_root)
        or Path(declared_root).expanduser().resolve() != project_root
    ):
        fail("正式状态的 project_dir 与工程目录不一致")
    candidates = enumerate_candidates(state_path, state, origin_root)
    formal_by_path = {item.path: item for item in candidates}
    delete_paths: set[Path] = set()
    if not candidate_path_values:
        fail("至少需要一个候选路径")
    for value in candidate_path_values:
        if not os.path.isabs(value):
            fail("候选路径必须是绝对路径")
        resolved = Path(value).expanduser().resolve()
        if resolved not in formal_by_path:
            fail("候选路径没有被当前正式状态精确登记")
        delete_paths.add(resolved)
    retained = sorted(set(formal_by_path) - delete_paths)
    if retained:
        strategy = "partial"
        targets = partial_artifacts(project_root, candidates, delete_paths)
    else:
        strategy = "whole_run"
        targets = [
            {"path": str(project_root), "kind": "directory", "reason": "last_candidate_run"}
        ]
    return {
        "candidate_artifact_cleanup_plan_version": PLAN_VERSION,
        "project_root": str(project_root),
        "state_path": str(state_path),
        "run_mode": state.get("run_mode") or state.get("mode"),
        "strategy": strategy,
        "delete_candidate_paths": [str(item) for item in sorted(delete_paths)],
        "retained_candidate_paths": [str(item) for item in retained],
        "targets": targets,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--candidate-path", action="append", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        plan = build_plan(args.project_root, args.candidate_path)
    except CleanupPlanError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    json.dump(plan, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
