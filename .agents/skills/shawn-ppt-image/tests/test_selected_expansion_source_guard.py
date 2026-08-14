from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "scripts" / "pipeline_control.py"


def load_pipeline():
    spec = importlib.util.spec_from_file_location(
        "pipeline_control_selected_expansion_guard", PIPELINE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline = load_pipeline()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_png_stub(path: Path, *, tag: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1600, 900)
        + tag
    )


def input_record(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "sha256": pipeline.file_sha256(path),
    }


class SelectedExpansionSourceGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="selected_expansion_source_guard_"
        )
        self.project_dir = Path(self.temporary_directory.name).resolve()
        self.state_path = (
            self.project_dir / "state" / "selected_style_run_state.json"
        )
        self.source_path = self.project_dir / "source" / "outline.md"
        self.contract_path = (
            self.project_dir / "content_contracts" / "page_08.json"
        )
        self.alternate_contract_path = (
            self.project_dir / "alternate" / "page_08.json"
        )
        self.style_anchor_path = (
            self.project_dir / "references" / "selected_style_anchor.png"
        )
        self.approved_asset_path = (
            self.project_dir / "references" / "approved_logo.bin"
        )
        self.alternate_asset_path = (
            self.project_dir / "alternate" / "unapproved_logo.bin"
        )
        self.job_path = self.project_dir / "page_jobs" / "page_08.json"

        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path.write_text(
            "# Outline\n\n## P08 Expansion page\nStable expansion content\n",
            encoding="utf-8",
        )
        write_json(
            self.contract_path,
            {
                "content_contract_version": 2,
                "page_id": "08",
                "display_required": ["Stable expansion content"],
            },
        )
        write_json(
            self.alternate_contract_path,
            {
                "content_contract_version": 2,
                "page_id": "08",
                "display_required": ["Different contract"],
            },
        )
        write_png_stub(self.style_anchor_path, tag=b"style-anchor")
        self.approved_asset_path.parent.mkdir(parents=True, exist_ok=True)
        self.approved_asset_path.write_bytes(b"APPROVED-ASSET")
        self.alternate_asset_path.parent.mkdir(parents=True, exist_ok=True)
        self.alternate_asset_path.write_bytes(b"UNAPPROVED-ASSET")

        write_json(
            self.state_path,
            {
                "run_id": "selected-expansion-source-guard-fixture",
                "project_dir": str(self.project_dir),
                "run_mode": "selected_style_expansion",
                "phase": "selected_style_expansion",
                "status": "running",
                "selected_style": "A",
                "state_audit_contract_version": 2,
                "page_order": ["08"],
                "pages": {"08": {"status": "pending", "attempt_count": 0}},
                "scheduler": {
                    "phase": "generation",
                    "active_actions": [],
                    "ready_queue": [],
                    "recovery_queue": [],
                },
                "events": [],
                "timing": {},
            },
        )
        write_json(
            self.project_dir / "state" / "task_init.json",
            {
                "task_init_contract_version": 1,
                "project_dir": str(self.project_dir),
                "source_snapshot_required": True,
                "created_at": "2099-01-01T00:00:00+08:00",
            },
        )
        self.write_job(action="generate_page")
        pipeline.create_source_snapshot(
            project_dir=self.project_dir,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=["08"],
            content_contract_paths=[self.contract_path],
            asset_items=[
                {
                    "path": str(self.style_anchor_path),
                    "asset_type": "reference_image",
                    "role": "style_anchor",
                },
                {
                    "path": str(self.approved_asset_path),
                    "asset_type": "required_asset",
                    "role": "official_logo",
                },
            ],
            timestamp="2099-01-01T00:00:01+08:00",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_job(
        self,
        *,
        action: str,
        contract_path: Path | None = None,
        inputs: list[Path] | None = None,
    ) -> Path:
        contract_path = contract_path or self.contract_path
        inputs = inputs if inputs is not None else [
            self.style_anchor_path,
            self.approved_asset_path,
        ]
        job_path = (
            self.job_path
            if action == "generate_page"
            else self.project_dir
            / "page_jobs"
            / "repair_jobs"
            / "page_08_attempt_1.json"
        )
        write_json(
            job_path,
            {
                "style_slot": "A",
                "page_id": "08",
                "action": action,
                "attempt": 1,
                "source_content_contract_path": str(contract_path.resolve()),
                "source_content_contract_sha256": pipeline.file_sha256(
                    contract_path
                ),
                "imagegen_referenced_paths": [
                    str(path.resolve()) for path in inputs
                ],
                "imagegen_input_manifest": [input_record(path) for path in inputs],
                "reference_images": [
                    {"path": str(path.resolve())} for path in inputs
                ],
                "required_assets": [],
                "required_page_assets": [],
                "output_target": str(
                    pipeline.origin_image_target(
                        self.project_dir, "A", "08"
                    ).resolve()
                ),
            },
        )
        return job_path

    def record_started(
        self, *, action: str, generation_job_path: Path | None
    ) -> None:
        details = {"attempt": 1}
        if generation_job_path is not None:
            details["generation_job_path"] = str(generation_job_path.resolve())
        with redirect_stdout(io.StringIO()):
            pipeline.command_record_event(
                argparse.Namespace(
                    state=str(self.state_path),
                    event="agent_action_started",
                    style=None,
                    page_id="08",
                    action=action,
                    timestamp="2099-01-01T00:01:00+08:00",
                    details_json=json.dumps(details),
                )
            )

    def assert_page_did_not_start(self) -> None:
        state = pipeline.read_json(self.state_path)
        page = state["pages"]["08"]
        self.assertNotEqual(page.get("status"), "generating")
        self.assertNotIn("agent_action_started_at", page)
        self.assertFalse(
            any(event.get("name") == "agent_action_started" for event in state["events"])
        )

    def add_current_candidate(self) -> Path:
        candidate_path = (
            self.project_dir / "origin_image" / "style_A_page_08.png"
        )
        write_png_stub(candidate_path, tag=b"current-candidate")
        state = pipeline.read_json(self.state_path)
        state["pages"]["08"].update(
            {
                "status": "generated",
                "selected_source": str(candidate_path),
                "source_sha256": pipeline.file_sha256(candidate_path),
            }
        )
        pipeline.atomic_write_json(self.state_path, state)
        return candidate_path

    def test_formal_page_job_allows_clean_generate_start(self) -> None:
        job_path = self.write_job(action="generate_page")

        self.record_started(action="generate_page", generation_job_path=job_path)

        state = pipeline.read_json(self.state_path)
        page = state["pages"]["08"]
        self.assertEqual(page["status"], "generating")
        self.assertEqual(page["attempt_count"], 1)
        self.assertEqual(page["agent_action_started_at"], "2099-01-01T00:01:00+08:00")
        self.assertEqual(state["events"][-1]["name"], "agent_action_started")

    def test_replaced_contract_is_blocked_before_page_starts(self) -> None:
        job_path = self.write_job(
            action="generate_page", contract_path=self.alternate_contract_path
        )

        with self.assertRaises(SystemExit):
            self.record_started(
                action="generate_page", generation_job_path=job_path
            )

        self.assert_page_did_not_start()
        report = pipeline.read_json(
            self.project_dir / "state" / "source_drift_status.json"
        )
        self.assertTrue(
            any(
                change.get("component") == "content_contract"
                and change.get("reason") == "operation_path_not_in_snapshot"
                for change in report["changes"]
            )
        )

    def test_contract_page_identity_is_bound_to_event_page(self) -> None:
        write_json(
            self.contract_path,
            {
                "content_contract_version": 2,
                "page_id": "09",
                "display_required": ["Stable expansion content"],
            },
        )
        job_path = self.write_job(action="generate_page")

        with self.assertRaisesRegex(SystemExit, "page_id"):
            pipeline.selected_expansion_event_inputs(
                self.state_path,
                pipeline.read_json(self.state_path),
                "08",
                "generate_page",
                {
                    "generation_job_path": str(job_path.resolve()),
                    "attempt": 1,
                },
            )

        self.assert_page_did_not_start()

    def test_output_target_is_bound_to_selected_style_and_page(self) -> None:
        job_path = self.write_job(action="generate_page")
        job = pipeline.read_json(job_path)
        job["output_target"] = str(
            pipeline.origin_image_target(self.project_dir, "B", "08").resolve()
        )
        write_json(job_path, job)

        with self.assertRaisesRegex(SystemExit, "output_target"):
            self.record_started(
                action="generate_page", generation_job_path=job_path
            )

        self.assert_page_did_not_start()

    def test_replaced_asset_is_blocked_before_page_starts(self) -> None:
        job_path = self.write_job(
            action="generate_page",
            inputs=[
                self.style_anchor_path,
                self.approved_asset_path,
                self.alternate_asset_path,
            ],
        )

        with self.assertRaises(SystemExit):
            self.record_started(
                action="generate_page", generation_job_path=job_path
            )

        self.assert_page_did_not_start()
        report = pipeline.read_json(
            self.project_dir / "state" / "source_drift_status.json"
        )
        self.assertTrue(
            any(
                change.get("component") == "used_asset"
                and change.get("reason") == "operation_path_not_in_snapshot"
                for change in report["changes"]
            )
        )

    def test_missing_generation_job_path_is_blocked(self) -> None:
        with self.assertRaisesRegex(SystemExit, "generation_job_path"):
            self.record_started(action="generate_page", generation_job_path=None)

        self.assert_page_did_not_start()

    def test_generate_job_cannot_masquerade_as_repair_page(self) -> None:
        candidate_path = self.add_current_candidate()
        job_path = self.write_job(
            action="generate_page",
            inputs=[
                self.style_anchor_path,
                self.approved_asset_path,
                candidate_path,
            ],
        )

        with self.assertRaisesRegex(SystemExit, "action=repair_page"):
            self.record_started(action="repair_page", generation_job_path=job_path)

        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["pages"]["08"]["status"], "generated")
        self.assertNotIn("agent_action_started_at", state["pages"]["08"])

    def test_repair_page_requires_and_accepts_current_candidate(self) -> None:
        candidate_path = self.add_current_candidate()
        job_path = self.write_job(
            action="repair_page",
            inputs=[self.style_anchor_path, self.approved_asset_path],
        )

        with self.assertRaisesRegex(SystemExit, "当前候选"):
            self.record_started(action="repair_page", generation_job_path=job_path)

        state = pipeline.read_json(self.state_path)
        self.assertNotIn("agent_action_started_at", state["pages"]["08"])

        job_path = self.write_job(
            action="repair_page",
            inputs=[
                self.style_anchor_path,
                self.approved_asset_path,
                candidate_path,
            ],
        )
        self.record_started(action="repair_page", generation_job_path=job_path)

        state = pipeline.read_json(self.state_path)
        self.assertEqual(
            state["pages"]["08"]["agent_action_started_at"],
            "2099-01-01T00:01:00+08:00",
        )
        self.assertEqual(state["events"][-1]["action"], "repair_page")

    def test_missing_style_anchor_is_blocked(self) -> None:
        job_path = self.write_job(
            action="generate_page", inputs=[self.approved_asset_path]
        )

        with self.assertRaises(SystemExit):
            self.record_started(
                action="generate_page", generation_job_path=job_path
            )

        self.assert_page_did_not_start()
        report = pipeline.read_json(
            self.project_dir / "state" / "source_drift_status.json"
        )
        self.assertTrue(
            any(
                change.get("reason") == "required_asset_role_not_used_by_operation"
                and change.get("path") == str(self.style_anchor_path)
                for change in report["changes"]
            )
        )


if __name__ == "__main__":
    unittest.main()
