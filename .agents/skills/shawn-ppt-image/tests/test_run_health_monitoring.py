from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_quick8_pipeline import write_json, write_png


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "scripts" / "pipeline_control.py"
INIT_PATH = ROOT / "scripts" / "init_task_dir.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline = load_module("pipeline_control_monitoring", PIPELINE_PATH)
init_task = load_module("init_task_monitoring", INIT_PATH)


class RunHealthMonitoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shawn_monitoring_")
        self.root = Path(self.temp.name).resolve()
        self.state_path = self.root / "state" / "style_run_state.json"
        self.monitoring_root = self.root / "central_monitoring"
        self.overview_path = self.root / "overview" / "overview.png"
        write_png(self.overview_path, color=b"\xfa\xfa\xfa")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_fixture(self, *, fast8: bool = False) -> None:
        styles = {}
        prompt = "建立清楚的主次关系与专业工业科技质感，保留必要文字并形成自然停顿。"
        for index, style in enumerate(("A", "B")):
            image_path = self.root / "origin_image" / f"style_{style}_page_02.png"
            write_png(image_path, color=bytes((230 - index, 240 - index, 250 - index)))
            styles[style] = {
                "pages": {
                    "02": {
                        "attempt_count": 1,
                        "technical_retry_count": 0,
                        "final_path": str(image_path),
                        "source_sha256": pipeline.file_sha256(image_path),
                        "worker_agent_id": f"worker-{style}",
                        "tool_call_id": f"tool-{style}",
                        "tool_started_at": f"2026-08-04T10:00:0{index}+08:00",
                        "tool_finished_at": f"2026-08-04T10:01:0{index}+08:00",
                        "file_validated_at": f"2026-08-04T10:01:1{index}+08:00",
                        "agent_action_finished_at": f"2026-08-04T10:01:2{index}+08:00",
                        "timing_capture": (
                            "controller_bounded_fallback"
                            if fast8 and style == "B"
                            else "direct_tool_result"
                        ),
                    }
                }
            }
            job_prompt = prompt if fast8 else f"{prompt} 候选 {style} 使用不同构图。"
            job = {
                "imagegen_prompt": job_prompt,
                "imagegen_prompt_fingerprint": hashlib.sha256(
                    job_prompt.encode("utf-8")
                ).hexdigest(),
                "imagegen_prompt_contract_version": (
                    pipeline.CURRENT_FAST8_IMAGEGEN_PROMPT_VERSION if fast8 else 4
                ),
                "reference_images": [],
                "imagegen_referenced_paths": [],
                "imagegen_input_manifest": [],
            }
            if fast8:
                job["creative_brief_projection"] = {
                    "relationship_thesis": "两项能力共同收束到同一结果",
                    "visual_quality_intent": "成熟、精致、可信",
                    "literal_anchors": ["标题", "结论"],
                    "flexible_story": "两项能力共同支撑结果",
                    "visual_thesis": "以一个汇聚关系作为主视觉",
                    "craft_axis": "工业摄影与精细编辑排版",
                    "visual_activity_mode": "restrained",
                    "attention_strategy": "一个主焦点与安静证据层",
                }
            write_json(self.root / "style_jobs" / f"style_{style}.json", job)

        events = [
            {"sequence": 1, "name": "process_started"},
            {"sequence": 2, "name": "process_completed"},
        ]
        if fast8:
            events = [
                {"sequence": 1, "name": "process_started"},
                {"sequence": 2, "name": "artifact_recovery_started"},
                {"sequence": 3, "name": "artifact_recovery_finished"},
                {"sequence": 4, "name": "process_completed"},
            ]
        write_json(
            self.state_path,
            {
                "run_id": "monitor-fast8" if fast8 else "monitor-classic",
                "run_mode": pipeline.FAST8_MODE if fast8 else pipeline.QUICK_8X1_MODE,
                "status": "completed",
                "anchor_page_id": "02",
                "follower_page_ids": [],
                "styles": styles,
                "events": events,
                "scheduler": {
                    "phase": "completed",
                    "active_actions": [],
                    "ready_queue": [],
                    "recovery_queue": [],
                },
                "timing": {
                    "process_started_at": "2026-08-04T09:55:00+08:00",
                    "task_package_completed_at": "2026-08-04T09:59:00+08:00",
                    "initial_anchor_dispatch_at": "2026-08-04T10:00:00+08:00",
                    "all_anchor_tools_completed_at": "2026-08-04T10:01:01+08:00",
                    "formal_overview_completed_at": "2026-08-04T10:03:00+08:00",
                    "process_completed_at": "2026-08-04T10:04:00+08:00",
                },
                "overview": {"final_path": str(self.overview_path)},
            },
        )

    def test_task_init_records_explicit_nonblocking_monitoring_root(self) -> None:
        init_task.create_standard_dirs(self.root)
        marker_path = init_task.write_task_init_contract(
            self.root,
            timestamp="2026-08-04T09:00:00+08:00",
            monitoring_root=self.monitoring_root,
        )
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        self.assertEqual(marker["monitoring_root"], str(self.monitoring_root))
        self.assertEqual(marker["monitoring_mode"], "background_non_blocking")

    def test_completed_run_writes_local_report_and_central_index(self) -> None:
        self.make_fixture()
        result = pipeline.write_run_health_report(
            state_path=self.state_path,
            monitoring_root=str(self.monitoring_root),
            timestamp="2026-08-04T10:04:01+08:00",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["health_status"], "healthy")
        report = pipeline.read_json(self.root / "state" / "run_health_report.json")
        self.assertEqual(report["scope"], "non_visual")
        self.assertFalse(report["blocking"])
        self.assertFalse(report["prompt_health"]["raw_prompts_stored_in_report"])
        index = pipeline.read_json(self.monitoring_root / "index.json")
        self.assertEqual(index["run_count"], 1)
        self.assertEqual(index["recent_10"][0]["run_id"], "monitor-classic")
        self.assertEqual(index["recent_10"][0]["review_status"], "pending")
        self.assertEqual(index["pending_reviews"][0]["run_id"], "monitor-classic")
        self.assertFalse(
            index["review_selection_policy"][
                "completed_reviews_are_reopened_automatically"
            ]
        )
        index_text = (self.monitoring_root / "index.json").read_text(encoding="utf-8")
        self.assertNotIn("候选 A 使用不同构图", index_text)

    def test_non_fast8_health_does_not_require_fast8_prompt_fingerprint(self) -> None:
        self.make_fixture()
        for path in (self.root / "style_jobs").glob("style_*.json"):
            job = pipeline.read_json(path)
            job.pop("imagegen_prompt_fingerprint", None)
            write_json(path, job)
        report = pipeline.build_run_health_report(
            state_path=self.state_path,
            state=pipeline.read_json(self.state_path),
            timestamp="2026-08-04T10:04:01+08:00",
        )
        codes = {item["code"] for item in report["findings"]}
        self.assertNotIn("prompt_fingerprint_missing", codes)
        self.assertNotIn("prompt_fingerprint_mismatch", codes)

    def test_report_detects_duplicate_prompt_recovery_and_timing_fallback(self) -> None:
        self.make_fixture(fast8=True)
        result = pipeline.write_run_health_report(
            state_path=self.state_path,
            monitoring_root=str(self.monitoring_root),
            timestamp="2026-08-04T10:04:01+08:00",
        )
        self.assertEqual(result["health_status"], "defect")
        report = pipeline.read_json(self.root / "state" / "run_health_report.json")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("duplicate_fast8_prompt_fingerprint", codes)
        self.assertIn("artifact_recovery_used", codes)
        self.assertIn("controller_timing_fallback_used", codes)
        self.assertEqual(report["counts"]["recovery_started_count"], 1)
        fallback = next(
            item
            for item in report["findings"]
            if item["code"] == "controller_timing_fallback_used"
        )
        self.assertEqual(fallback["evidence"]["count"], 1)

    def test_health_separates_capacity_wait_and_flags_late_worker_binding(self) -> None:
        self.make_fixture(fast8=True)
        state = pipeline.read_json(self.state_path)
        state["timing"]["task_package_completed_at"] = (
            "2026-08-04T09:55:00+08:00"
        )
        state["scheduler"]["runtime_backpressure"] = [
            {
                "occurred_at": "2026-08-04T09:56:00+08:00",
                "last_observed_at": "2026-08-04T09:59:30+08:00",
                "poll_count": 4,
                "requested": 2,
                "started": 0,
                "reason": "global_imagegen_capacity",
            }
        ]
        state["scheduler"]["worker_session_bindings"] = [
            {
                "bound_at": "2026-08-04T10:00:30+08:00",
                "tasks": [
                    {
                        "style": "A",
                        "page_id": "02",
                        "action": "generate_anchor",
                        "attempt": 1,
                    }
                ],
            }
        ]
        write_json(self.state_path, state)
        report = pipeline.build_run_health_report(
            state_path=self.state_path,
            state=state,
            timestamp="2026-08-04T10:04:01+08:00",
        )
        codes = {item["code"] for item in report["findings"]}
        self.assertNotIn("dispatch_preparation_delay", codes)
        self.assertIn("worker_session_bound_after_tool_start", codes)
        stage = report["timing"]["stage_seconds"]
        self.assertEqual(stage["process_to_package"], 0.0)
        self.assertEqual(stage["package_to_dispatch"], 300.0)
        self.assertEqual(stage["pre_dispatch_capacity_wait"], 240.0)
        self.assertEqual(stage["active_dispatch_preparation"], 60.0)

    def test_report_detects_missing_required_fast8_worker_receipt(self) -> None:
        self.make_fixture(fast8=True)
        job_path = self.root / "style_jobs" / "style_A.json"
        job = pipeline.read_json(job_path)
        job["worker_receipt"] = {
            "contract_version": pipeline.FAST8_WORKER_RECEIPT_CONTRACT_VERSION,
            "path": str(self.root / "style_jobs" / "results" / "missing.json"),
            "required": True,
            "contains_image_payload": False,
        }
        write_json(job_path, job)

        pipeline.write_run_health_report(
            state_path=self.state_path,
            monitoring_root=str(self.monitoring_root),
            timestamp="2026-08-04T10:04:01+08:00",
        )
        report = pipeline.read_json(self.root / "state" / "run_health_report.json")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("worker_receipt_missing", codes)

    def test_incomplete_diagnostic_stays_out_of_completed_run_index(self) -> None:
        self.make_fixture()
        state = pipeline.read_json(self.state_path)
        state["status"] = "running"
        write_json(self.state_path, state)
        result = pipeline.write_run_health_report(
            state_path=self.state_path,
            monitoring_root=str(self.monitoring_root),
            timestamp="2026-08-04T10:04:01+08:00",
            register_central=False,
        )
        self.assertTrue(Path(result["report_json"]).is_file())
        self.assertIsNone(result["entry"])
        self.assertFalse((self.monitoring_root / "index.json").exists())

    def test_terminal_incomplete_run_is_registered_without_becoming_completed(self) -> None:
        self.make_fixture()
        state = pipeline.read_json(self.state_path)
        state["status"] = "running"
        state["timing"].pop("process_completed_at", None)
        state["scheduler"]["active_actions"] = [
            {
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
            }
        ]
        state["events"].insert(
            -1,
            {
                "sequence": 2,
                "name": "dispatch_wave",
                "details": {
                    "started_tasks": [
                        {
                            "style": "A",
                            "page_id": "02",
                            "action": "generate_anchor",
                        }
                    ]
                },
            },
        )
        state["events"][-1]["sequence"] = 3
        write_json(self.state_path, state)

        result = pipeline.write_run_health_report(
            state_path=self.state_path,
            monitoring_root=str(self.monitoring_root),
            timestamp="2026-08-04T10:05:00+08:00",
            run_outcome="superseded",
            outcome_reason="A non-required asset was removed in a fresh run.",
        )
        self.assertIsNotNone(result["entry"])
        report = pipeline.read_json(self.root / "state" / "run_health_report.json")
        self.assertEqual(report["run"]["record_kind"], "terminal_incomplete_run")
        self.assertEqual(report["run"]["run_outcome"], "superseded")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("dispatch_authorization_unsettled", codes)
        index = pipeline.read_json(self.monitoring_root / "index.json")
        self.assertEqual(index["summary"]["completed_run_count"], 0)
        self.assertEqual(index["summary"]["terminal_incomplete_run_count"], 1)
        self.assertEqual(index["runs"][0]["run_outcome"], "superseded")

    def test_review_file_must_pass_contract_before_completed_status(self) -> None:
        self.make_fixture()
        pipeline.write_run_health_report(
            state_path=self.state_path,
            monitoring_root=str(self.monitoring_root),
            timestamp="2026-08-04T10:04:01+08:00",
        )
        index = pipeline.read_json(self.monitoring_root / "index.json")
        entry = index["runs"][0]
        review_path = self.monitoring_root / "reviews" / f"review_{entry['entry_id']}.json"
        write_json(review_path, {"review_contract_version": 1})
        _, _, invalid_index = pipeline.rebuild_monitoring_index(
            self.monitoring_root, "2026-08-04T10:05:00+08:00"
        )
        self.assertEqual(invalid_index["runs"][0]["review_status"], "invalid")
        self.assertGreater(invalid_index["summary"]["invalid_review_count"], 0)

        write_json(
            review_path,
            {
                "review_contract_version": 1,
                "entry_id": entry["entry_id"],
                "run_id": entry["run_id"],
                "review_kind": "technical_and_effect_review",
                "overview_sha256": entry["overview_sha256"],
                "technical_findings": {},
                "visual_findings": {},
                "speed_assessment": {},
                "recommended_actions": [],
                "reviewed_at": "2026-08-04T10:05:30+08:00",
                "resolution": {
                    "status": "applied",
                    "resolved_at": "2026-08-04T10:05:45+08:00",
                    "evidence_paths": [str(self.root / "state" / "run_health_report.json")],
                },
                "contains_image_payload": False,
                "contains_raw_prompt": False,
            },
        )
        _, _, valid_index = pipeline.rebuild_monitoring_index(
            self.monitoring_root, "2026-08-04T10:06:00+08:00"
        )
        self.assertEqual(valid_index["runs"][0]["review_status"], "completed")
        self.assertEqual(
            valid_index["runs"][0]["review_resolution_status"], "applied"
        )
        self.assertEqual(valid_index["pending_reviews"], [])
        self.assertEqual(valid_index["summary"]["completed_review_count"], 1)
        self.assertEqual(valid_index["summary"]["invalid_review_count"], 0)


if __name__ == "__main__":
    unittest.main()
