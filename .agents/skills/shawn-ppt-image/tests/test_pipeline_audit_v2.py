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
import zlib


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "pipeline_control.py"
SPEC = importlib.util.spec_from_file_location("pipeline_control_audit_v2", MODULE_PATH)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_png(
    path: Path,
    width: int = 1600,
    height: int = 900,
    color: bytes = b"\xff\xff\xff",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = b"".join(b"\x00" + color * width for _ in range(height))

    def chunk(name: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(raw, 1))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)


class PipelineAuditV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shawn_audit_v2_")
        self.root = Path(self.temp.name)
        self.state_path = self.root / "state" / "style_run_state.json"
        self.content_path = self.root / "content_contracts" / "page_02.json"
        self.portfolio_path = self.root / "state" / "layout_portfolio.json"
        self.source_path = self.root / "source" / "outline.md"
        write_json(
            self.state_path,
            {
                "run_id": "audit-v2",
                "run_mode": pipeline.QUICK_8X1_MODE,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "deferred_pages": ["05", "08"],
                "preflight": {"status": "resolved"},
                "timing": {},
                "events": [],
                "scheduler": {"active_actions": [], "ready_queue": []},
            },
        )
        write_json(
            self.content_path,
            {
                "content_contract_version": 2,
                "prompt_contract_version": 4,
                "language": "zh-CN",
                "page_id": "02",
                "title": "审计测试",
                "core_claim": "八个候选",
                "source_facts": ["事实"],
                "display_required": ["审计测试"],
                "display_flexible": ["说明可适度压缩"],
                "display_supporting": [],
                "semantic_invariants": [],
                "forbidden_interpretations": [],
                "prompt_semantic_guardrails": [],
                "prompt_user_constraints": [],
                "information_density_target": "medium",
                "content_load_review": {
                    "semantic_structure": "单一主张",
                    "focus_relationship": "主从",
                    "attention_risks": [],
                    "edge_and_takeaway_risks": [],
                    "duplication_risks": [],
                    "reason": "可生成",
                },
                "content_resolution": {
                    "status": "not_needed",
                    "choice": None,
                    "moved_items": [],
                    "reason": None,
                },
                "spatial_pressure_profile": "low",
                "spatial_generation_brief": pipeline.QUICK8_BREATHING_PROMPT_CUES[
                    "zh"
                ]["low"],
                "spatial_qa_contract": "Low",
                "low_pressure_feasibility": "pass",
                "visual_support_goal": "帮助理解",
            },
        )
        styles = {
            style: {"direction_id": f"open_{style}"}
            for style in pipeline.QUICK_STYLES
        }
        for style in "ABCDEF":
            styles[style]["first_impression"] = f"先理解候选 {style}"
        write_json(
            self.portfolio_path,
            {
                "layout_portfolio_contract_version": 5,
                "page_id": "02",
                "director_rationale": "六个首感、两个开放席位。",
                "styles": styles,
            },
        )
        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path.write_text("## P02\nStable audit content\n", encoding="utf-8")
        write_json(
            self.root / "state" / "task_init.json",
            {
                "task_init_contract_version": 1,
                "project_dir": str(self.root.resolve()),
                "source_snapshot_required": True,
                "created_at": "2099-01-01T00:00:00+08:00",
            },
        )
        pipeline.create_source_snapshot(
            project_dir=self.root,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=["02"],
            content_contract_paths=[self.content_path],
            asset_items=[],
            timestamp="2099-01-01T00:00:01+08:00",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def call(self, function, **kwargs):
        with redirect_stdout(io.StringIO()):
            return function(argparse.Namespace(**kwargs))

    def prepare(self) -> None:
        self.call(
            pipeline.command_prepare_anchors,
            project_dir=str(self.root),
            state=str(self.state_path),
            content_contract=str(self.content_path),
            overall_requirements="Quick8",
            reference_images_json="[]",
            required_assets_json="[]",
            layout_portfolio=str(self.portfolio_path),
        )

    def test_prepare_enables_v2_and_records_task_package_event(self) -> None:
        self.prepare()
        state = pipeline.read_json(self.state_path)
        self.assertEqual(
            state["state_audit_contract_version"],
            pipeline.CURRENT_STATE_AUDIT_VERSION,
        )
        names = [event["name"] for event in state["events"]]
        self.assertLess(
            names.index("style_jobs_created"), names.index("task_package_completed")
        )
        self.assertTrue(all(event.get("recorded_at") for event in state["events"]))

    def test_partial_dispatch_requires_and_records_backpressure(self) -> None:
        self.prepare()
        kwargs = {
            "state": str(self.state_path),
            "styles": "A,B,C",
            "page_id": None,
            "action": "generate_anchor",
            "attempt": 1,
            "timestamp": "2026-07-28T10:00:00+08:00",
            "agent_map_json": None,
        }
        with self.assertRaisesRegex(SystemExit, "backpressure-reason"):
            self.call(
                pipeline.command_record_dispatch_wave,
                **kwargs,
                backpressure_reason=None,
            )
        self.call(
            pipeline.command_record_dispatch_wave,
            **kwargs,
            backpressure_reason="runtime child thread limit",
        )
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="D,E,F,G,H",
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-07-28T10:00:01+08:00",
            agent_map_json=None,
            backpressure_reason=None,
        )
        state = pipeline.read_json(self.state_path)
        runtime_events = [
            event
            for event in state["events"]
            if event["name"] == "runtime_backpressure"
        ]
        self.assertEqual(len(runtime_events), 1)
        self.assertEqual(
            runtime_events[0]["details"]["deferred_styles"],
            ["D", "E", "F", "G", "H"],
        )
        errors: list[str] = []
        pipeline.validate_dispatch_audit_v2(state, errors, complete=True)
        self.assertEqual(errors, [])

    def test_qa_scope_prevents_false_visual_passes(self) -> None:
        record = pipeline.initial_page_state(
            "anchor", "2026-07-28T10:00:00+08:00"
        )
        pipeline.apply_page_event_effects(
            record,
            "page_completed",
            None,
            {"completion_status": "candidate_ready"},
        )
        errors: list[str] = []
        pipeline.validate_page_audit_v2(
            {"events": []}, record, "style_A/02", errors, complete=True
        )
        self.assertEqual(errors, [])

        record["qa_stage"] = "visual_worker"
        record["qa_scope"] = "content_only"
        record["content_gate"] = {"status": "pass"}
        record["spatial_gate"] = {"status": "pass"}
        record["craft_gate"] = {"status": "not_applicable"}
        errors = []
        pipeline.validate_page_audit_v2(
            {"events": []}, record, "style_A/02", errors, complete=True
        )
        self.assertTrue(any("spatial_gate 必须为 not_applicable" in item for item in errors))

    def test_process_completion_closes_scheduler_and_workflow(self) -> None:
        state = {
            "state_audit_contract_version": 2,
            "run_id": "legacy-process-completion",
            "project_dir": str(self.root.resolve()),
            "run_mode": pipeline.QUICK_8X1_MODE,
            "status": "running",
            "anchor_page_id": "02",
            "scheduler": {
                "phase": "anchor_generation",
                "active_actions": [],
                "ready_queue": [{"style": "A"}],
                "recovery_queue": [],
            },
            "styles": {
                "A": {
                    "workflow_status": "anchor_pending",
                    "pages": {"02": {"status": "candidate_ready"}},
                }
            },
            "timing": {},
            "events": [],
        }
        write_json(self.state_path, state)
        kwargs = {
            "state": str(self.state_path),
            "event": "process_completed",
            "style": None,
            "page_id": None,
            "action": None,
            "timestamp": "2026-07-28T10:10:00+08:00",
            "details_json": None,
        }
        with self.assertRaisesRegex(SystemExit, "调度队列必须为空"):
            self.call(pipeline.command_record_event, **kwargs)
        state["scheduler"]["ready_queue"] = []
        write_json(self.state_path, state)
        (self.root / "state" / "source_snapshot.json").unlink()
        (self.root / "state" / "task_init.json").unlink()
        self.call(
            pipeline.command_confirm_legacy_source_risk,
            state=str(self.state_path),
            actions="candidate_delivery",
            timestamp="2026-07-28T10:09:00+08:00",
            user_confirmed=True,
        )
        self.call(pipeline.command_record_event, **kwargs)
        completed = pipeline.read_json(self.state_path)
        self.assertEqual(completed["scheduler"]["phase"], "completed")
        self.assertEqual(
            completed["styles"]["A"]["workflow_status"], "ready_for_overview"
        )

    def test_event_causal_order_catches_late_process_start(self) -> None:
        state = {"state_audit_contract_version": 2, "events": [], "timing": {}}
        pipeline.append_event(
            state, "style_jobs_created", "2026-07-28T10:01:00+08:00"
        )
        pipeline.append_event(
            state, "process_started", "2026-07-28T09:59:00+08:00"
        )
        errors: list[str] = []
        pipeline.validate_event_audit_v2(state, errors, complete=False)
        self.assertTrue(any("因果倒序" in item for item in errors))

    def test_missing_audit_version_remains_legacy_v1(self) -> None:
        self.assertEqual(pipeline.state_audit_version({}), 1)
        with self.assertRaisesRegex(SystemExit, "只允许 1\\|2"):
            pipeline.state_audit_version({"state_audit_contract_version": 99})

    def test_complete_quick8_v2_passes_end_to_end_state_validation(self) -> None:
        for event, timestamp in (
            ("process_started", "2020-01-01T00:00:00+08:00"),
            ("preflight_resolved", "2020-01-01T00:01:00+08:00"),
        ):
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event=event,
                style=None,
                page_id=None,
                action=None,
                timestamp=timestamp,
                details_json=None,
            )
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A,B,C,D,E,F,G,H",
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2099-01-01T00:00:00+08:00",
            agent_map_json=None,
            backpressure_reason=None,
        )
        image_paths = {}
        for index, style in enumerate(pipeline.QUICK_STYLES):
            image_path = (
                self.root / "origin_image" / f"style_{style}_page_02.png"
            )
            write_png(
                image_path,
                color=bytes((240 - index, 250 - index, 255 - index)),
            )
            image_paths[style] = image_path
        results = []
        for index, style in enumerate(pipeline.QUICK_STYLES):
            results.append(
                {
                    "style": style,
                    "page_id": "02",
                    "action": "generate_anchor",
                    "attempt": 1,
                    "worker_agent_id": f"agent-{style}",
                    "agent_action_started_at": (
                        f"2099-01-01T00:00:{10 + index:02d}+08:00"
                    ),
                    "agent_action_finished_at": (
                        f"2099-01-01T00:02:{30 + index:02d}+08:00"
                    ),
                    "tool_call_id": f"tool-{style}",
                    "savedPath": str(image_paths[style]),
                    "tool_started_at": (
                        f"2099-01-01T00:01:{10 + index:02d}+08:00"
                    ),
                    "tool_finished_at": (
                        f"2099-01-01T00:02:{10 + index:02d}+08:00"
                    ),
                    "error": None,
                }
            )
        results_path = self.root / "style_jobs" / "results" / "wave.json"
        write_json(results_path, results)
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(results_path),
            expected_styles="A,B,C,D,E,F,G,H",
            timestamp="2099-01-01T00:03:00+08:00",
        )
        for index, style in enumerate(pipeline.QUICK_STYLES):
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event="overview_qa",
                style=style,
                page_id="02",
                action="qa_filesystem",
                timestamp=f"2099-01-01T00:04:{index:02d}+08:00",
                details_json=json.dumps(
                    {
                        "qa_stage": "filesystem",
                        "qa_scope": "filesystem_only",
                    }
                ),
            )
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event="page_completed",
                style=style,
                page_id="02",
                action="complete_candidate",
                timestamp=f"2099-01-01T00:05:{index:02d}+08:00",
                details_json=json.dumps(
                    {
                        "completion_status": "candidate_ready",
                        "final_path": str(image_paths[style]),
                    }
                ),
            )
        overview_path = self.root / "overview" / "ABCDEFGH_4x2.png"
        write_png(overview_path)
        self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="formal_overview_completed",
            style=None,
            page_id=None,
            action=None,
            timestamp="2099-01-01T00:06:00+08:00",
            details_json=json.dumps({"output_path": str(overview_path)}),
        )
        self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="process_completed",
            style=None,
            page_id=None,
            action=None,
            timestamp="2099-01-01T00:07:00+08:00",
            details_json=None,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            pipeline.command_validate_state(
                argparse.Namespace(state=str(self.state_path), complete=True)
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "pass")


if __name__ == "__main__":
    unittest.main()
