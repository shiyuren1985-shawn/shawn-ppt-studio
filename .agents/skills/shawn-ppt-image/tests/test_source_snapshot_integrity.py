from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "scripts" / "pipeline_control.py"
INIT_TASK_PATH = ROOT / "scripts" / "init_task_dir.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline = load_module("pipeline_control_snapshot_integrity", PIPELINE_PATH)
init_task = load_module("init_task_snapshot_integrity", INIT_TASK_PATH)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class SourceSnapshotIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shawn_snapshot_integrity_")
        self.root = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_snapshot_fixture(
        self, name: str, *, with_marker: bool
    ) -> tuple[Path, Path, Path, Path]:
        project = self.root / name
        init_task.create_standard_dirs(project)
        if with_marker:
            init_task.write_task_init_contract(
                project, timestamp="2099-01-01T00:00:00+08:00"
            )
        state_path = project / "state" / "style_run_state.json"
        source_path = project / "source.md"
        contract_path = project / "content_contracts" / "page_02.json"
        source_path.write_text("## P02\nStable page content\n", encoding="utf-8")
        write_json(contract_path, {"page_id": "02", "claim": "Stable page content"})
        write_json(
            state_path,
            {
                "run_id": f"run-{name}",
                "run_mode": pipeline.QUICK_8X1_MODE,
                "anchor_page_id": "02",
                "styles": {},
                "events": [],
                "timing": {},
            },
        )
        return project, state_path, source_path, contract_path

    def seal_snapshot(
        self, project: Path, state_path: Path, source_path: Path, contract_path: Path
    ) -> None:
        pipeline.create_source_snapshot(
            project_dir=project,
            state_path=state_path,
            source_path=source_path,
            page_ids=["02"],
            content_contract_paths=[contract_path],
            asset_items=[],
            timestamp="2099-01-01T00:00:00+08:00",
        )

    def test_pristine_legacy_without_marker_cannot_seal_snapshot(self) -> None:
        project, state_path, source_path, contract_path = self.make_snapshot_fixture(
            "pristine_legacy", with_marker=False
        )
        original_state = state_path.read_bytes()

        with self.assertRaises(SystemExit):
            self.seal_snapshot(project, state_path, source_path, contract_path)

        self.assertEqual(state_path.read_bytes(), original_state)
        self.assertFalse((project / "state" / "source_snapshot.json").exists())

    def test_invalid_task_init_markers_block_snapshot_before_mutation(self) -> None:
        invalid_markers = {
            "version": {
                "task_init_contract_version": 999,
                "source_snapshot_required": True,
            },
            "project": {
                "task_init_contract_version": init_task.TASK_INIT_CONTRACT_VERSION,
                "source_snapshot_required": True,
                "project_dir": str((self.root / "wrong-project").resolve()),
            },
            "snapshot_required": {
                "task_init_contract_version": init_task.TASK_INIT_CONTRACT_VERSION,
                "source_snapshot_required": False,
            },
        }
        for name, marker in invalid_markers.items():
            with self.subTest(marker=name):
                project, state_path, source_path, contract_path = (
                    self.make_snapshot_fixture(name, with_marker=False)
                )
                marker.setdefault("project_dir", str(project.resolve()))
                marker.setdefault("created_at", "2099-01-01T00:00:00+08:00")
                write_json(project / "state" / "task_init.json", marker)
                original_state = state_path.read_bytes()

                with self.assertRaises(SystemExit):
                    self.seal_snapshot(project, state_path, source_path, contract_path)

                self.assertEqual(state_path.read_bytes(), original_state)
                self.assertFalse(
                    (project / "state" / "source_snapshot.json").exists()
                )

    def test_duplicate_markdown_page_sections_are_rejected(self) -> None:
        source_path = self.root / "duplicate.md"
        source_path.write_text(
            "## P02 First\nFirst version\n\n## Page 002 Second\nSecond version\n",
            encoding="utf-8",
        )

        with self.assertRaises(SystemExit):
            pipeline.extract_relevant_source_content(source_path, ["02"])

    def test_duplicate_json_page_records_are_rejected(self) -> None:
        source_path = self.root / "duplicate.json"
        write_json(
            source_path,
            {
                "pages": [
                    {"page_id": "02", "text": "First version"},
                    {"page_id": "P02", "text": "Second version"},
                ]
            },
        )

        with self.assertRaises(SystemExit):
            pipeline.extract_relevant_source_content(source_path, ["02"])

    def test_state_run_mode_mismatch_with_snapshot_is_blocking_drift(self) -> None:
        project, state_path, source_path, contract_path = self.make_snapshot_fixture(
            "mode_mismatch", with_marker=True
        )
        self.seal_snapshot(project, state_path, source_path, contract_path)
        state = pipeline.read_json(state_path)
        state["run_mode"] = pipeline.FAST_4X3_MODE
        write_json(state_path, state)

        result = pipeline.evaluate_source_drift(state_path, action="resume")

        self.assertEqual(result["status"], "source_drift_detected")
        self.assertFalse(result["can_continue"])
        self.assertTrue(result["source_snapshot_changed"])
        self.assertTrue(
            any(
                item.get("component") == "source_snapshot"
                and item.get("reason") == "run_mode_mismatch"
                for item in result["changes"]
            )
        )

    def test_new_4x3_missing_follower_scope_blocks_before_jobs_or_queue_write(self) -> None:
        project = self.root / "missing_follower_scope"
        init_task.create_standard_dirs(project)
        init_task.write_task_init_contract(project)
        state_path = project / "state" / "style_run_state.json"
        source_path = project / "source.md"
        contract_path = project / "content_contracts" / "page_02.json"
        source_path.write_text(
            "## P02\nAnchor\n\n## P05\nFollower one\n\n## P08\nFollower two\n",
            encoding="utf-8",
        )
        write_json(
            state_path,
            {
                "run_id": "missing-follower-scope",
                "run_mode": pipeline.FAST_4X3_MODE,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "preflight": {"status": "resolved"},
                "scheduler": {
                    "phase": "initialization",
                    "active_actions": [],
                    "ready_queue": [],
                    "recovery_queue": [],
                },
                "events": [],
                "timing": {},
            },
        )
        write_json(
            contract_path,
            {
                "content_contract_version": 2,
                "prompt_contract_version": 4,
                "language": "en-US",
                "page_id": "02",
                "source_facts": ["Fixture fact"],
                "display_required": ["Anchor"],
                "display_flexible": [],
                "display_supporting": [],
                "prompt_semantic_guardrails": [],
                "prompt_user_constraints": [],
                "information_density_target": "medium",
                "content_load_review": {
                    "semantic_structure": "single proposition",
                    "focus_relationship": "one claim",
                    "attention_risks": [],
                    "edge_and_takeaway_risks": [],
                    "duplication_risks": [],
                    "reason": "fixture is feasible",
                },
                "content_resolution": {
                    "status": "not_needed",
                    "choice": None,
                    "moved_items": [],
                    "reason": None,
                },
                "spatial_pressure_profile": "low",
                "spatial_generation_brief": pipeline.QUICK8_BREATHING_PROMPT_CUES[
                    "en"
                ]["low"],
                "spatial_qa_contract": "Low-pressure QA applies.",
                "low_pressure_feasibility": "pass",
            },
        )
        original_state = state_path.read_bytes()

        with self.assertRaises(SystemExit):
            pipeline.command_prepare_anchors(
                argparse.Namespace(
                    project_dir=str(project),
                    state=str(state_path),
                    content_contract=str(contract_path),
                    overall_requirements="Fixture",
                    reference_images_json="[]",
                    required_assets_json="[]",
                    source_file=str(source_path),
                    source_page_ids=["02"],
                    source_fragment_file=None,
                    snapshot_content_contracts_json=None,
                    source_snapshot_timestamp="2099-01-01T00:00:00+08:00",
                    layout_portfolio=str(project / "state" / "unused.json"),
                )
            )

        self.assertEqual(state_path.read_bytes(), original_state)
        self.assertFalse((project / "state" / "source_snapshot.json").exists())
        self.assertEqual(list((project / "style_jobs").glob("*.json")), [])

    def test_snapshot_source_cannot_seal_partial_4x3_scope(self) -> None:
        project, state_path, source_path, contract_path = self.make_snapshot_fixture(
            "partial_direct_4x3", with_marker=True
        )
        source_path.write_text(
            "## P02\nAnchor\n\n## P05\nFollower one\n\n## P08\nFollower two\n",
            encoding="utf-8",
        )
        state = pipeline.read_json(state_path)
        state["run_mode"] = pipeline.STRICT_4X3_MODE
        state["follower_page_ids"] = ["05", "08"]
        write_json(state_path, state)
        original_state = state_path.read_bytes()

        with self.assertRaisesRegex(SystemExit, "完整正式范围"):
            pipeline.create_source_snapshot(
                project_dir=project,
                state_path=state_path,
                source_path=source_path,
                page_ids=["02"],
                content_contract_paths=[contract_path],
                asset_items=[],
            )

        self.assertEqual(state_path.read_bytes(), original_state)
        self.assertFalse((project / "state" / "source_snapshot.json").exists())

    def test_snapshot_source_requires_one_contract_for_every_page(self) -> None:
        project, state_path, source_path, contract_path = self.make_snapshot_fixture(
            "missing_page_contracts", with_marker=True
        )
        source_path.write_text(
            "## P02\nAnchor\n\n## P05\nFollower one\n\n## P08\nFollower two\n",
            encoding="utf-8",
        )
        state = pipeline.read_json(state_path)
        state["run_mode"] = pipeline.FAST_4X3_MODE
        state["follower_page_ids"] = ["05", "08"]
        write_json(state_path, state)
        original_state = state_path.read_bytes()

        with self.assertRaisesRegex(SystemExit, "逐页绑定"):
            pipeline.create_source_snapshot(
                project_dir=project,
                state_path=state_path,
                source_path=source_path,
                page_ids=["02", "05", "08"],
                content_contract_paths=[contract_path],
                asset_items=[],
            )

        self.assertEqual(state_path.read_bytes(), original_state)
        self.assertFalse((project / "state" / "source_snapshot.json").exists())

    def test_init_task_resume_accepts_all_four_supported_state_locations(self) -> None:
        relative_state_paths = (
            Path("state/style_run_state.json"),
            Path("state/selected_style_run_state.json"),
            Path("style_run_state.json"),
            Path("selected_style_run_state.json"),
        )
        output_root = self.root / "resume-output"
        for index, relative_state_path in enumerate(relative_state_paths):
            with self.subTest(state_path=str(relative_state_path)):
                task_name = f"P02_8x1_20990101_case_{index}"
                project = output_root / task_name
                write_json(project / relative_state_path, {"run_id": task_name})
                stdout = io.StringIO()
                with mock.patch(
                    "sys.argv",
                    [
                        "init_task_dir.py",
                        "--output-root",
                        str(output_root),
                        "--task-name",
                        task_name,
                        "--resume",
                    ],
                ), redirect_stdout(stdout):
                    self.assertEqual(init_task.main(), 0)

                result = json.loads(stdout.getvalue())
                self.assertEqual(result["status"], "resumed")
                self.assertEqual(result["project_dir"], str(project.resolve()))
                self.assertTrue((project / relative_state_path).is_file())
                self.assertFalse((project / "state" / "task_init.json").exists())


if __name__ == "__main__":
    unittest.main()
