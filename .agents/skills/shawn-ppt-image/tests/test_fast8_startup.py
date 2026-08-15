from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "init_task_dir.py"


class Fast8StartupTest(unittest.TestCase):
    def run_init(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_preflight_passes_before_allocating_one_formal_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shawn_fast8_startup_") as temp:
            root = Path(temp)
            output_root = root / "output"
            source = root / "outline.md"
            asset = root / "logo.png"
            overview_python = root / "overview-python"
            source.write_text("P18 source", encoding="utf-8")
            asset.write_bytes(b"asset")
            overview_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            overview_python.chmod(0o755)
            task_name = "P18_startup_20260804_8x1"
            manifest = root / "preflight.json"
            manifest.write_text(
                json.dumps(
                    {
                        "fast8_preflight_manifest_version": 1,
                        "run_mode": "fast_8x1_diverse",
                        "task_name": task_name,
                        "timestamp_policy": "script_owned",
                        "page_ids": ["18"],
                        "required_files": [str(source)],
                        "optional_files": [str(root / "optional_missing.md")],
                        "asset_items": [{"path": str(asset), "role": "official_logo"}],
                        "tone_overrides": {style: "light" for style in "ABCDEFGH"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            preflight = self.run_init(
                "--output-root",
                str(output_root),
                "--task-name",
                task_name,
                "--preflight-manifest",
                str(manifest),
                "--preflight-only",
            )
            self.assertEqual(preflight.returncode, 0, preflight.stderr)
            self.assertFalse((output_root / task_name).exists())
            created = self.run_init(
                "--output-root",
                str(output_root),
                "--task-name",
                task_name,
                "--preflight-manifest",
                str(manifest),
                "--overview-python",
                str(overview_python),
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            payload = json.loads(created.stdout)
            project_dir = Path(payload["project_dir"])
            self.assertEqual(project_dir.name, task_name)
            task_init = json.loads(
                (project_dir / "state" / "task_init.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                task_init["formal_directory_allocation_policy"],
                "after_preflight_pass",
            )
            self.assertTrue((project_dir / "state" / "preflight_manifest.json").is_file())
            state = json.loads(
                (project_dir / "state" / "style_run_state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(state["fast8_startup_contract_version"], 1)
            self.assertEqual(state["anchor_page_id"], "18")
            self.assertEqual(state["follower_page_ids"], [])
            self.assertEqual(state["deferred_pages"], [])
            self.assertEqual(
                state["tone_overrides"],
                {style: "light" for style in "ABCDEFGH"},
            )
            self.assertEqual(
                [item["name"] for item in state["events"]],
                ["process_started", "preflight_resolved"],
            )
            self.assertEqual(
                state["overview_runtime"]["python"],
                str(overview_python.resolve()),
            )

    def test_missing_overview_runtime_does_not_allocate_formal_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shawn_fast8_startup_runtime_") as temp:
            root = Path(temp)
            output_root = root / "output"
            source = root / "outline.md"
            source.write_text("P05 source", encoding="utf-8")
            task_name = "P05_startup_20260804_8x1"
            manifest = root / "preflight.json"
            manifest.write_text(
                json.dumps(
                    {
                        "fast8_preflight_manifest_version": 1,
                        "run_mode": "fast_8x1_diverse",
                        "task_name": task_name,
                        "timestamp_policy": "script_owned",
                        "page_ids": ["05"],
                        "required_files": [str(source)],
                        "optional_files": [],
                        "asset_items": [],
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_init(
                "--output-root",
                str(output_root),
                "--task-name",
                task_name,
                "--preflight-manifest",
                str(manifest),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--overview-python", result.stderr)
            self.assertFalse((output_root / task_name).exists())

    def test_invalid_preflight_does_not_create_a_formal_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shawn_fast8_startup_bad_") as temp:
            root = Path(temp)
            output_root = root / "output"
            source = root / "outline.md"
            source.write_text("P04 source", encoding="utf-8")
            task_name = "P04_startup_20260804_8x1"
            manifest = root / "preflight.json"
            manifest.write_text(
                json.dumps(
                    {
                        "fast8_preflight_manifest_version": 1,
                        "run_mode": "fast_8x1_diverse",
                        "task_name": task_name,
                        "timestamp_policy": "script_owned",
                        "page_ids": ["04"],
                        "required_files": [str(source)],
                        "optional_files": [],
                        "asset_items": [{"path": str(source), "role": "wrong_duplicate"}],
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_init(
                "--output-root",
                str(output_root),
                "--task-name",
                task_name,
                "--preflight-manifest",
                str(manifest),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("路径重复", result.stderr)
            self.assertFalse((output_root / task_name).exists())


if __name__ == "__main__":
    unittest.main()
