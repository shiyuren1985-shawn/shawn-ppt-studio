#!/usr/bin/env python3
"""Validate that the desktop bundle contains only intentional runtime files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


STUDIO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = STUDIO_ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
RUNTIME_EXTENSIONS = {".css", ".html", ".js", ".json", ".mjs"}
RUNTIME_PREFIXES = ("server/", "integrations/", "web/")
FORBIDDEN_NAMES = {".ds_store", "readme", "readme.md", "readiness", "readiness.md"}
PERSONAL_PATH = re.compile(rb"/Users/[A-Za-z0-9._-]+|OneDrive-RockwellAutomation")


def fail(message: str) -> None:
    raise AssertionError(message)


def tracked_runtime_sources() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "server", "integrations", "web"],
        cwd=STUDIO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        path
        for path in result.stdout.splitlines()
        if path.startswith(RUNTIME_PREFIXES) and Path(path).suffix in RUNTIME_EXTENSIONS
    }


def is_forbidden_name(path: Path) -> bool:
    lowered = path.name.lower()
    return lowered in FORBIDDEN_NAMES or "smoke-request" in lowered


def load_resource_manifest() -> tuple[dict[str, str], Path]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    resources = config["bundle"]["resources"]
    if not isinstance(resources, dict):
        fail("bundle.resources must be an explicit source-to-destination map")

    frontend = (CONFIG_PATH.parent / config["build"]["frontendDist"]).resolve()
    expected_frontend = (STUDIO_ROOT / "desktop" / "frontend").resolve()
    if frontend != expected_frontend:
        fail(f"frontendDist must use the clean desktop stub, got {frontend}")
    if sorted(path.relative_to(frontend).as_posix() for path in frontend.rglob("*") if path.is_file()) != ["index.html"]:
        fail("desktop frontend stub must contain only index.html")
    return resources, frontend


def source_path(source: str) -> Path:
    return (CONFIG_PATH.parent / source).resolve()


def check_source_manifest() -> dict[str, str]:
    resources, _ = load_resource_manifest()
    mapped_runtime: dict[str, str] = {}
    destinations: set[str] = set()

    for source, destination in resources.items():
        resolved = source_path(source)
        if not resolved.exists():
            fail(f"mapped resource does not exist: {source}")
        if destination in destinations:
            fail(f"duplicate resource destination: {destination}")
        destinations.add(destination)

        try:
            relative = resolved.relative_to(STUDIO_ROOT).as_posix()
        except ValueError:
            fail(f"resource escapes repository: {source}")

        if relative.startswith(RUNTIME_PREFIXES):
            if not resolved.is_file():
                fail(f"runtime resource must map an exact file, not a directory: {source}")
            if is_forbidden_name(resolved):
                fail(f"forbidden runtime resource is mapped: {relative}")
            expected_destination = f"studio/{relative}"
            if destination != expected_destination:
                fail(f"unexpected destination for {relative}: {destination}")
            mapped_runtime[relative] = destination

    expected = tracked_runtime_sources()
    actual = set(mapped_runtime)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        fail(f"runtime resource manifest drift; missing={missing}, unexpected={unexpected}")

    for source in resources:
        resolved = source_path(source)
        files = [resolved] if resolved.is_file() else [path for path in resolved.rglob("*") if path.is_file()]
        for path in files:
            if PERSONAL_PATH.search(path.read_bytes()):
                fail(f"resource contains a personal absolute path: {path.relative_to(STUDIO_ROOT)}")

    return mapped_runtime


def check_built_app(app: Path, mapped_runtime: dict[str, str]) -> None:
    studio = app / "Contents" / "Resources" / "studio"
    if not studio.is_dir():
        fail(f"desktop resources are missing: {studio}")

    expected = {destination.removeprefix("studio/") for destination in mapped_runtime.values()}
    actual: set[str] = set()
    for prefix in RUNTIME_PREFIXES:
        root = studio / prefix.rstrip("/")
        if not root.is_dir():
            fail(f"required bundle directory is missing: {root}")
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(studio).as_posix()
            actual.add(relative)
            if is_forbidden_name(path):
                fail(f"forbidden file was bundled: {relative}")
            if PERSONAL_PATH.search(path.read_bytes()):
                fail(f"bundled file contains a personal absolute path: {relative}")

    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        fail(f"built runtime resources differ from manifest; missing={missing}, unexpected={unexpected}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, help="optional built .app to inspect")
    args = parser.parse_args()

    try:
        mapped_runtime = check_source_manifest()
        if args.app:
            check_built_app(args.app.resolve(), mapped_runtime)
    except (AssertionError, KeyError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as error:
        print(f"bundle resource hygiene FAIL: {error}", file=sys.stderr)
        return 1

    scope = "source manifest and built app" if args.app else "source manifest"
    print(f"bundle resource hygiene PASS: {scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
