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


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_control.py"
SPEC = importlib.util.spec_from_file_location("pipeline_control_strict4x3", MODULE_PATH)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_png(
    path: Path,
    *,
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


def content_contract(page_id: str = "02") -> dict:
    return {
        "content_contract_version": 2,
        "prompt_contract_version": 4,
        "language": "en-US",
        "page_id": page_id,
        "title": "Strict anchor",
        "core_claim": "A strict v6 anchor can move through the audited wave pipeline.",
        "source_facts": ["Synthetic test fact"],
        "display_required": ["Strict anchor", "100% traceable"],
        "display_flexible": ["The evidence remains complete and readable."],
        "display_supporting": [],
        "semantic_invariants": ["100% must remain exact"],
        "forbidden_interpretations": [],
        "prompt_semantic_guardrails": ["Keep 100% exact."],
        "prompt_user_constraints": [],
        "information_density_target": "medium",
        "content_load_review": {
            "semantic_structure": "single proposition",
            "focus_relationship": "one claim supported by one fact",
            "attention_risks": [],
            "edge_and_takeaway_risks": [],
            "duplication_risks": [],
            "reason": "The strict Low page is feasible without changing content.",
        },
        "content_resolution": {
            "status": "not_needed",
            "choice": None,
            "moved_items": [],
            "reason": None,
        },
        "spatial_pressure_profile": "low",
        "spatial_generation_brief": pipeline.QUICK8_BREATHING_PROMPT_CUES["en"][
            "low"
        ],
        "spatial_qa_contract": "Strict Low QA applies.",
        "low_pressure_feasibility": "pass",
        "visual_support_goal": "Make the audited transition easy to understand.",
    }


def layout_portfolio(page_id: str = "02") -> dict:
    return {
        "layout_portfolio_contract_version": 6,
        "page_id": page_id,
        "director_rationale": "Two semantic first impressions and two open seats exercise strict v6.",
        "styles": {
            "A": {
                "direction_id": "strict_value_a",
                "first_impression": "The audience first understands the core value.",
            },
            "B": {
                "direction_id": "strict_evidence_b",
                "first_impression": "The audience first trusts the evidence chain.",
            },
            "C": {"direction_id": "strict_open_c"},
            "D": {"direction_id": "strict_open_d"},
        },
    }


class Strict4x3AndLegacySettlementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shawn_strict4x3_")
        self.root = Path(self.temp.name)
        self.state_path = self.root / "state" / "style_run_state.json"
        self.content_path = self.root / "content_contracts" / "page_02.json"
        self.portfolio_path = self.root / "state" / "layout_portfolio.json"
        self.source_path = self.root / "source" / "outline.md"
        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path.write_text(
            "## P02\nAnchor\n\n## P05\nFollower one\n\n## P08\nFollower two\n",
            encoding="utf-8",
        )
        write_json(
            self.root / "state" / "task_init.json",
            {
                "task_init_contract_version": 1,
                "project_dir": str(self.root.resolve()),
                "source_snapshot_required": True,
                "created_at": "2099-01-01T00:00:00+08:00",
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def call(self, function, **kwargs) -> dict:
        output = io.StringIO()
        with redirect_stdout(output):
            function(argparse.Namespace(**kwargs))
        return json.loads(output.getvalue())

    def result(
        self,
        style: str,
        source: Path,
        *,
        tool_call_id: str,
        second_offset: int = 0,
    ) -> dict:
        return {
            "style": style,
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
            "worker_agent_id": f"agent-{style}",
            "agent_action_started_at": (
                f"2099-01-01T00:00:{10 + second_offset:02d}+08:00"
            ),
            "agent_action_finished_at": (
                f"2099-01-01T00:02:{30 + second_offset:02d}+08:00"
            ),
            "tool_call_id": tool_call_id,
            "savedPath": str(source),
            "tool_started_at": f"2099-01-01T00:01:{10 + second_offset:02d}+08:00",
            "tool_finished_at": f"2099-01-01T00:02:{10 + second_offset:02d}+08:00",
            "error": None,
        }

    def write_legacy_state(self, mode: str) -> None:
        styles = {}
        for style in pipeline.styles_for_mode(mode):
            styles[style] = {
                "tone": pipeline.tone_for_style(mode, style),
                "workflow_status": "anchor_pending",
                "pages": {
                    "02": pipeline.initial_page_state(
                        "anchor", "2026-07-18T10:00:00+08:00"
                    )
                },
            }
        write_json(
            self.state_path,
            {
                "run_id": f"legacy-{mode}",
                "run_mode": mode,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "scheduler": {
                    "phase": "anchor_generation",
                    "active_actions": [],
                    "ready_queue": [],
                    "recovery_queue": [],
                },
                "styles": styles,
                "events": [],
                "timing": {},
            },
        )

    def settle(self, results: list[dict], expected_styles: str) -> dict:
        results_path = self.root / "style_jobs" / "results" / "wave.json"
        write_json(results_path, results)
        return self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(results_path),
            expected_styles=expected_styles,
            timestamp="2099-01-01T00:03:00+08:00",
        )

    def seal_strict_source_snapshot(self) -> None:
        follower_paths = []
        for page_id in ("05", "08"):
            path = self.root / "content_contracts" / f"page_{page_id}.json"
            write_json(path, content_contract(page_id))
            follower_paths.append(path)
        pipeline.create_source_snapshot(
            project_dir=self.root,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=["02", "05", "08"],
            content_contract_paths=[self.content_path, *follower_paths],
            asset_items=[],
            timestamp="2099-01-01T00:00:01+08:00",
        )

    def test_strict_v6_prepare_dispatch_and_settle_anchor_wave(self) -> None:
        write_json(
            self.state_path,
            {
                "run_id": "strict-v6-minimal-wave",
                "run_mode": pipeline.STRICT_4X3_MODE,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "preflight": {"status": "resolved"},
                "scheduler": {"active_actions": [], "ready_queue": []},
                "events": [],
                "timing": {},
            },
        )
        write_json(self.content_path, content_contract())
        write_json(self.portfolio_path, layout_portfolio())
        self.seal_strict_source_snapshot()

        prepared = self.call(
            pipeline.command_prepare_anchors,
            project_dir=str(self.root),
            state=str(self.state_path),
            content_contract=str(self.content_path),
            overall_requirements="Strict v6 minimal wave",
            reference_images_json="[]",
            required_assets_json="[]",
            layout_portfolio=str(self.portfolio_path),
        )
        self.assertEqual(prepared["style_jobs"], 4)
        self.assertEqual(prepared["ready_queue"], 4)
        prepared_state = pipeline.read_json(self.state_path)
        self.assertEqual(
            prepared_state["scheduler"]["active_child_limit"],
            9,
        )

        dispatched = self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A,B,C,D",
            tasks_json=None,
            page_id="02",
            action="generate_anchor",
            attempt=1,
            timestamp="2099-01-01T00:00:00+08:00",
            agent_map_json=json.dumps(
                {style: f"agent-{style}" for style in pipeline.FULL_STYLES}
            ),
            backpressure_reason=None,
        )
        self.assertEqual(dispatched["started"], 4)

        results = []
        for index, style in enumerate(pipeline.FULL_STYLES):
            image_path = self.root / f"strict_{style}.png"
            write_png(
                image_path,
                color=bytes((245 - index, 250 - index, 255 - index)),
            )
            results.append(
                self.result(
                    style,
                    image_path,
                    tool_call_id=f"strict-tool-{style}",
                    second_offset=index,
                )
            )
        settled = self.settle(results, "A,B,C,D")
        self.assertEqual(settled["settled"], 4)
        self.assertTrue(settled["all_anchor_tools_completed"])

        state = pipeline.read_json(self.state_path)
        self.assertEqual(
            state["state_audit_contract_version"],
            pipeline.CURRENT_STATE_AUDIT_VERSION,
        )
        self.assertEqual(state["layout_portfolio_contract_version"], 6)
        self.assertEqual(state["scheduler"]["active_actions"], [])
        for style in pipeline.FULL_STYLES:
            record = state["styles"][style]["pages"]["02"]
            self.assertEqual(record["tool_call_id"], f"strict-tool-{style}")
            self.assertTrue(record["selected_source"].endswith(f"strict_{style}.png"))
            self.assertEqual(record["attempt_count"], 1)

    def test_legacy_fast_and_quick_settle_without_active_action(self) -> None:
        for mode in (pipeline.FAST_4X3_MODE, pipeline.QUICK_8X1_MODE):
            with self.subTest(mode=mode):
                self.write_legacy_state(mode)
                image_path = self.root / f"legacy_{mode}.png"
                write_png(image_path)
                settled = self.settle(
                    [
                        self.result(
                            "A",
                            image_path,
                            tool_call_id=f"legacy-tool-{mode}",
                        )
                    ],
                    "A",
                )
                self.assertEqual(settled["settled"], 1)
                state = pipeline.read_json(self.state_path)
                self.assertNotIn("state_audit_contract_version", state)
                self.assertEqual(state["scheduler"]["active_actions"], [])
                record = state["styles"]["A"]["pages"]["02"]
                self.assertEqual(record["selected_source"], str(image_path.resolve()))
                self.assertEqual(record["attempt_count"], 1)

    def test_legacy_modes_keep_eight_slot_fallback(self) -> None:
        for mode in (
            pipeline.STRICT_4X3_MODE,
            pipeline.FAST_4X3_MODE,
            pipeline.QUICK_8X1_MODE,
        ):
            with self.subTest(mode=mode):
                self.write_legacy_state(mode)
                self.assertEqual(
                    pipeline.active_child_limit_for_state(
                        pipeline.read_json(self.state_path)
                    ),
                    8,
                )

    def test_legacy_fast_and_quick_keep_artifact_uniqueness(self) -> None:
        for mode in (pipeline.FAST_4X3_MODE, pipeline.QUICK_8X1_MODE):
            with self.subTest(mode=mode):
                self.write_legacy_state(mode)
                image_path = self.root / f"shared_{mode}.png"
                write_png(image_path)
                self.settle(
                    [self.result("A", image_path, tool_call_id=f"legacy-A-{mode}")],
                    "A",
                )
                with self.assertRaisesRegex(
                    SystemExit, "跨任务重复绑定同一图片产物"
                ):
                    self.settle(
                        [
                            self.result(
                                "B",
                                image_path,
                                tool_call_id=f"legacy-B-{mode}",
                                second_offset=1,
                            )
                        ],
                        "B",
                    )

    def test_v2_requires_real_agent_times_while_legacy_v1_keeps_fallback(self) -> None:
        write_json(
            self.state_path,
            {
                "run_id": "strict-v2-agent-time-contract",
                "run_mode": pipeline.STRICT_4X3_MODE,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "preflight": {"status": "resolved"},
                "scheduler": {"active_actions": [], "ready_queue": []},
                "events": [],
                "timing": {},
            },
        )
        write_json(self.content_path, content_contract())
        write_json(self.portfolio_path, layout_portfolio())
        self.seal_strict_source_snapshot()
        self.call(
            pipeline.command_prepare_anchors,
            project_dir=str(self.root),
            state=str(self.state_path),
            content_contract=str(self.content_path),
            overall_requirements="Strict v2 Agent timing contract",
            reference_images_json="[]",
            required_assets_json="[]",
            layout_portfolio=str(self.portfolio_path),
        )
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id="02",
            action="generate_anchor",
            attempt=1,
            timestamp="2099-01-01T00:00:00+08:00",
            agent_map_json=json.dumps({"A": "agent-A"}),
            backpressure_reason="test intentionally dispatches only A",
        )
        v2_image = self.root / "strict_v2_missing_agent_times.png"
        write_png(v2_image)
        v2_result = self.result(
            "A",
            v2_image,
            tool_call_id="strict-v2-missing-agent-times",
        )
        v2_result.pop("agent_action_started_at")
        v2_result.pop("agent_action_finished_at")
        v2_state_before = pipeline.read_json(self.state_path)
        with self.assertRaisesRegex(SystemExit, "v2 正常生图结果必须提供真实"):
            self.settle([v2_result], "A")
        self.assertEqual(pipeline.read_json(self.state_path), v2_state_before)

        self.write_legacy_state(pipeline.FAST_4X3_MODE)
        legacy_image = self.root / "legacy_v1_missing_agent_times.png"
        write_png(legacy_image, color=b"\xfe\xfe\xfe")
        legacy_result = self.result(
            "A",
            legacy_image,
            tool_call_id="legacy-v1-missing-agent-times",
        )
        legacy_result.pop("agent_action_started_at")
        legacy_result.pop("agent_action_finished_at")
        settled = self.settle([legacy_result], "A")
        self.assertEqual(settled["settled"], 1)
        legacy_record = pipeline.read_json(self.state_path)["styles"]["A"]["pages"][
            "02"
        ]
        self.assertEqual(
            legacy_record["agent_action_started_at"],
            legacy_result["tool_started_at"],
        )
        self.assertEqual(
            legacy_record["agent_action_finished_at"],
            legacy_result["tool_finished_at"],
        )


if __name__ == "__main__":
    unittest.main()
