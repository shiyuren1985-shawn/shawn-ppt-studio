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
SPEC = importlib.util.spec_from_file_location("pipeline_control_fast4x3", MODULE_PATH)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_png(path: Path, width: int = 1600, height: int = 900) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))

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


def content_contract(page_id: str, feasibility: str = "pass") -> dict:
    return {
        "content_contract_version": 2,
        "prompt_contract_version": 4,
        "language": "zh-CN",
        "page_id": page_id,
        "title": f"页面 {page_id}",
        "core_claim": "成品级候选主张",
        "source_facts": ["事实"],
        "display_required": ["标题", "关键数字 100%"],
        "display_flexible": ["辅助说明可以压缩措辞"],
        "display_supporting": [],
        "semantic_invariants": ["100% 必须保留"],
        "forbidden_interpretations": [],
        "prompt_semantic_guardrails": ["保留关键数字"],
        "prompt_user_constraints": [],
        "information_density_target": "high",
        "content_load_review": {
            "semantic_structure": "主从关系",
            "focus_relationship": "主张为入口",
            "attention_risks": [],
            "edge_and_takeaway_risks": [],
            "duplication_risks": [],
            "reason": "内容可完整清晰呈现",
        },
        "content_resolution": {
            "status": "not_needed",
            "choice": None,
            "moved_items": [],
            "reason": None,
        },
        "spatial_pressure_profile": "low",
        "spatial_generation_brief": pipeline.QUICK8_BREATHING_PROMPT_CUES["zh"][
            "low"
        ],
        "spatial_qa_contract": "Low 仅作 Fast 候选软目标",
        "low_pressure_feasibility": feasibility,
        "visual_support_goal": "帮助理解主张",
    }


class Fast4x3PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shawn_fast4x3_")
        self.root = Path(self.temp.name)
        self.state_path = self.root / "state" / "style_run_state.json"
        self.content_dir = self.root / "content_contracts"
        self.anchor_content = self.content_dir / "page_02.json"
        self.portfolio_path = self.root / "state" / "layout_portfolio.json"
        self.image_path = self.root / "fixture.png"
        self.follower_image_paths = {
            "05": self.root / "fixture_05.png",
            "08": self.root / "fixture_08.png",
        }
        self.repair_image_path = self.root / "fixture_repair.png"
        self.source_path = self.root / "source" / "outline.md"
        write_png(self.image_path)
        write_png(self.follower_image_paths["05"], width=1280, height=720)
        write_png(self.follower_image_paths["08"], width=2048, height=1152)
        write_png(self.repair_image_path, width=1920, height=1080)
        self.result_file_index = 0
        write_json(
            self.state_path,
            {
                "run_id": "test-fast4x3",
                "run_mode": pipeline.FAST_4X3_MODE,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "preflight": {"status": "resolved"},
                "timing": {},
                "events": [],
                "scheduler": {"active_actions": [], "ready_queue": []},
            },
        )
        write_json(self.anchor_content, content_contract("02"))
        write_json(self.content_dir / "page_05.json", content_contract("05", "soft_target_unmet"))
        write_json(self.content_dir / "page_08.json", content_contract("08"))
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
        pipeline.create_source_snapshot(
            project_dir=self.root,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=["02", "05", "08"],
            content_contract_paths=[
                self.anchor_content,
                self.content_dir / "page_05.json",
                self.content_dir / "page_08.json",
            ],
            asset_items=[],
            timestamp="2099-01-01T00:00:01+08:00",
        )
        write_json(
            self.portfolio_path,
            {
                "layout_portfolio_contract_version": 6,
                "page_id": "02",
                "director_rationale": "两个高层首感与两个完全开放席位共同扩大探索面。",
                "styles": {
                    "A": {
                        "direction_id": "audience_value",
                        "first_impression": "先理解核心价值来自完整交付链",
                    },
                    "B": {
                        "direction_id": "audience_evidence",
                        "first_impression": "先感到关键事实可信且彼此支撑",
                    },
                    "C": {"direction_id": "open_c"},
                    "D": {"direction_id": "open_d"},
                },
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def call(self, function, **kwargs) -> dict:
        output = io.StringIO()
        with redirect_stdout(output):
            function(argparse.Namespace(**kwargs))
        return json.loads(output.getvalue())

    def prepare_anchors(self) -> None:
        self.call(
            pipeline.command_prepare_anchors,
            project_dir=str(self.root),
            state=str(self.state_path),
            content_contract=str(self.anchor_content),
            overall_requirements="四套成品级候选",
            reference_images_json="[]",
            required_assets_json="[]",
            layout_portfolio=str(self.portfolio_path),
        )

    def dispatch(self, tasks: list[dict], minute: int = 0) -> dict:
        agent_map = {
            f"{item['style']}/{item['page_id']}/{item['action']}": (
                f"agent-{item['style']}-{item['page_id']}-{item['action']}"
            )
            for item in tasks
        }
        return self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            tasks_json=json.dumps(tasks),
            styles="A",
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp=f"2099-01-01T00:{minute:02d}:00+08:00",
            agent_map_json=json.dumps(agent_map),
            backpressure_reason="test intentionally leaves other ready tasks queued",
        )

    def result(
        self,
        style: str,
        page_id: str,
        action: str,
        *,
        attempt: int = 1,
        minute: int = 1,
        source: Path | None = None,
        error: str | None = None,
        source_action: str | None = None,
        original_tool_minute: int | None = None,
    ) -> dict:
        if source is None:
            source = (
                self.image_path
                if page_id == "02"
                else self.follower_image_paths[page_id]
            )
        tool_minute = minute if original_tool_minute is None else original_tool_minute
        tool_action = source_action if action == "recover_artifact" else action
        value = {
            "style": style,
            "page_id": page_id,
            "action": action,
            "attempt": attempt,
            "worker_agent_id": f"agent-{style}-{page_id}-{action}",
            "agent_action_started_at": f"2099-01-01T00:{minute:02d}:00+08:00",
            "agent_action_finished_at": f"2099-01-01T00:{minute:02d}:30+08:00",
            "tool_call_id": f"tool-{style}-{page_id}-{tool_action}-{attempt}",
            "savedPath": None if error else str(source),
            "tool_started_at": f"2099-01-01T00:{tool_minute:02d}:10+08:00",
            "tool_finished_at": f"2099-01-01T00:{tool_minute:02d}:20+08:00",
            "error": error,
        }
        if action == "recover_artifact":
            value.update(
                {
                    "source_action": source_action,
                    "recovery_started_at": f"2099-01-01T00:{minute:02d}:01+08:00",
                    "recovery_finished_at": f"2099-01-01T00:{minute:02d}:09+08:00",
                    "recovery_method": "same_worker",
                }
            )
        return value

    def settle(
        self,
        results: list[dict],
        *,
        minute: int,
        expected_styles: str | None = None,
    ) -> dict:
        self.result_file_index += 1
        path = self.root / "results" / f"wave_{self.result_file_index}.json"
        write_json(path, results)
        if expected_styles is None:
            expected_styles = ",".join(
                dict.fromkeys(str(item["style"]) for item in results)
            )
        return self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(path),
            expected_styles=expected_styles,
            timestamp=f"2099-01-01T00:{minute:02d}:50+08:00",
        )

    def complete_anchor(self, style: str = "A", minute: int = 0) -> None:
        self.dispatch(
            [
                {
                    "style": style,
                    "page_id": "02",
                    "action": "generate_anchor",
                    "attempt": 1,
                }
            ],
            minute=minute,
        )
        self.settle(
            [self.result(style, "02", "generate_anchor", minute=minute + 1)],
            minute=minute + 1,
            expected_styles=style,
        )

    def prepare_followers(self, styles: str) -> dict:
        return self.call(
            pipeline.command_prepare_fast_followers,
            project_dir=str(self.root),
            state=str(self.state_path),
            content_contract_dir=str(self.content_dir),
            styles=styles,
        )

    def test_v6_v4_guided_open_anchor_contract_is_direct_and_soft(self) -> None:
        self.prepare_anchors()
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["scheduler"]["dispatch_policy"], "direct_fanout")
        self.assertEqual(state["scheduler"]["root_dispatch_wave"], 4)
        self.assertEqual(
            state["scheduler"]["active_child_limit"],
            9,
        )
        self.assertEqual(
            [
                (item["style"], item["page_id"], item["action"])
                for item in state["scheduler"]["ready_queue"]
            ],
            [
                (style, "02", "generate_anchor")
                for style in pipeline.FULL_STYLES
            ],
        )
        policy = state["fast4x3_candidate_policy"]
        self.assertEqual(policy["version"], 2)
        self.assertEqual(policy["guided_seat_count"], 2)
        self.assertEqual(policy["open_seat_count"], 2)
        self.assertTrue(policy["precompiled_follower_prompts"])
        self.assertEqual(
            policy["requested_follower_concurrency"],
            8,
        )
        self.assertTrue(state["fast4x3_candidate_policy"]["low_spatial_preference_is_soft"])
        self.assertEqual(
            state["fast4x3_candidate_policy"]["automatic_spatial_retries_before_selection"],
            0,
        )
        direction_ids = set()
        output_targets = set()
        for style in pipeline.FULL_STYLES:
            job = pipeline.read_json(self.root / "style_jobs" / f"style_{style}.json")
            direction_ids.add(job["layout_direction"]["direction_id"])
            output_targets.add(job["anchor_page"]["output_target"])
            self.assertEqual(
                Path(job["anchor_page"]["output_target"]).resolve(),
                (self.root / "origin_image" / f"style_{style}_page_02.png").resolve(),
            )
            self.assertEqual(job["candidate_policy"]["mode"], "one_shot_final_quality")
            self.assertTrue(job["candidate_policy"]["low_spatial_preference_is_soft"])
            self.assertEqual(job["layout_direction"]["layout_contract_version"], 6)
            self.assertEqual(job["layout_direction"]["style_slot"], style)
            self.assertNotIn("creative_direction", job["layout_direction"])
            self.assertEqual(job["imagegen_prompt_contract_version"], 4)
            self.assertTrue(job["imagegen_input_fingerprint"])
            self.assertIn("最高优先级语义护栏", job["imagegen_prompt"])
            self.assertIn("保留关键数字", job["imagegen_prompt"])
            self.assertIn(
                "不得用连线、箭头、树枝、嵌套或空间从属补出",
                job["imagegen_prompt"],
            )
            self.assertNotIn(pipeline.GROUPING_PROMPT_CUE, job["imagegen_prompt"])
            self.assertFalse(job["generation_rules"]["automatic_spatial_retry_before_selection"])
            self.assertEqual(job["generation_rules"]["max_total_attempts_per_page"], 2)
            if style in {"A", "B"}:
                self.assertEqual(
                    job["layout_direction"]["guidance_level"],
                    "semantic_first_impression",
                )
                self.assertIn("第一印象：", job["imagegen_prompt"])
                self.assertIn("不规定版式、媒介或构图", job["imagegen_prompt"])
            else:
                self.assertEqual(job["layout_direction"]["guidance_level"], "open")
                self.assertNotIn("first_impression", job["layout_direction"])
                self.assertNotIn("第一印象：", job["imagegen_prompt"])
                self.assertNotIn(
                    job["layout_direction"]["direction_id"], job["imagegen_prompt"]
                )
        self.assertEqual(len(direction_ids), 4)
        self.assertEqual(len(output_targets), 4)

        soft = content_contract("05", "soft_target_unmet")
        pipeline.validate_dispatchable_content_contract(
            soft, "fast fixture", soft_spatial_preference=True
        )
        with self.assertRaisesRegex(SystemExit, "Low 页面必须"):
            pipeline.validate_dispatchable_content_contract(soft, "strict fixture")

    def test_v6_portfolio_enforces_guided_open_bounds_and_minimal_schema(self) -> None:
        state = pipeline.read_json(self.state_path)
        content = pipeline.read_json(self.anchor_content)
        validated = pipeline.load_layout_portfolio(
            self.portfolio_path,
            state,
            content,
            expected_styles=pipeline.FULL_STYLES,
        )
        self.assertEqual(validated["layout_portfolio_contract_version"], 6)
        self.assertEqual(validated["guided_seat_count"], 2)
        self.assertEqual(validated["open_seat_count"], 2)

        too_few = pipeline.read_json(self.portfolio_path)
        too_few["styles"]["B"].pop("first_impression")
        too_few_path = self.root / "too_few.json"
        write_json(too_few_path, too_few)
        with self.assertRaisesRegex(SystemExit, "2–3"):
            pipeline.load_layout_portfolio(
                too_few_path, state, content, expected_styles=pipeline.FULL_STYLES
            )

        too_many = pipeline.read_json(self.portfolio_path)
        too_many["styles"]["C"]["first_impression"] = "先看到第三个内容首感"
        too_many["styles"]["D"]["first_impression"] = "先看到第四个内容首感"
        too_many_path = self.root / "too_many.json"
        write_json(too_many_path, too_many)
        with self.assertRaisesRegex(SystemExit, "2–3"):
            pipeline.load_layout_portfolio(
                too_many_path, state, content, expected_styles=pipeline.FULL_STYLES
            )

        duplicate = pipeline.read_json(self.portfolio_path)
        duplicate["styles"]["B"]["first_impression"] = duplicate["styles"]["A"][
            "first_impression"
        ]
        duplicate_path = self.root / "duplicate_impression.json"
        write_json(duplicate_path, duplicate)
        with self.assertRaisesRegex(SystemExit, "first_impression 与其他方向完全重复"):
            pipeline.load_layout_portfolio(
                duplicate_path, state, content, expected_styles=pipeline.FULL_STYLES
            )

        fixed_layout = pipeline.read_json(self.portfolio_path)
        fixed_layout["styles"]["A"]["creative_direction"] = "固定双栏摄影拼贴"
        fixed_layout_path = self.root / "fixed_layout.json"
        write_json(fixed_layout_path, fixed_layout)
        with self.assertRaisesRegex(SystemExit, "只允许 direction_id 与可选 first_impression"):
            pipeline.load_layout_portfolio(
                fixed_layout_path,
                state,
                content,
                expected_styles=pipeline.FULL_STYLES,
            )

    def test_precompiled_followers_unlock_progressively_and_are_idempotent(self) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="page_completed",
            style="A",
            page_id="02",
            action="generate_anchor",
            timestamp="2099-01-01T00:02:00+08:00",
            details_json=json.dumps({"completion_status": "candidate_ready"}),
        )
        anchor_only = pipeline.read_json(self.state_path)
        self.assertNotEqual(
            anchor_only["styles"]["A"]["workflow_status"],
            "ready_for_overview",
        )
        prepared = self.prepare_followers("A")
        self.assertEqual(prepared["newly_queued"], 2)
        self.assertEqual(len(prepared["dispatch_ready"]), 2)
        state = pipeline.read_json(self.state_path)
        self.assertEqual(
            state["scheduler"]["active_child_limit"],
            9,
        )
        queued = state["scheduler"]["ready_queue"]
        follower_queue = [item for item in queued if item["action"] == "generate_follower"]
        self.assertEqual(len(follower_queue), 2)
        self.assertTrue((self.root / "style_contracts" / "style_A.json").is_file())
        self.assertFalse((self.root / "style_contracts" / "style_B.json").exists())
        self.assertFalse((self.root / "style_contracts" / "style_C.json").exists())
        contract = pipeline.read_json(self.root / "style_contracts" / "style_A.json")
        self.assertEqual(state["styles"]["A"]["workflow_status"], "contract_ready")
        self.assertEqual(contract["style_contract_version"], 4)
        self.assertTrue(contract["candidate_contract"])
        self.assertEqual(contract["spatial_preference_mode"], "soft")
        self.assertTrue(contract["candidate_policy"]["precompiled_follower_prompt"])
        self.assertEqual(contract["layout_contract_version"], 6)
        self.assertIn("first_impression", contract)
        self.assertNotIn("creative_direction", contract)
        self.assertEqual(contract["generation_rules"]["max_total_attempts_per_page"], 1)
        page_job = pipeline.read_json(
            self.root / "style_page_jobs" / "style_A" / "page_05.json"
        )
        self.assertEqual(page_job["low_pressure_feasibility"], "soft_target_unmet")
        self.assertEqual(page_job["candidate_policy"]["mode"], "one_shot_final_quality")
        self.assertEqual(page_job["imagegen_prompt_contract_version"], 4)
        self.assertTrue(page_job["imagegen_input_fingerprint"])
        self.assertEqual(
            page_job["imagegen_referenced_paths"], [str(self.image_path.resolve())]
        )
        self.assertIn("风格参考（附件1）", page_job["imagegen_prompt"])
        self.assertIn("只借鉴核心感觉", page_job["imagegen_prompt"])
        self.assertIn("不要继承具体构图、版式、信息结构或原文内容", page_job["imagegen_prompt"])
        self.assertIn("其余视觉决策保持开放", page_job["imagegen_prompt"])
        self.assertNotIn(contract["first_impression"], page_job["imagegen_prompt"])
        self.assertEqual(
            Path(page_job["output_target"]).resolve(),
            (self.root / "origin_image" / "style_A_page_05.png").resolve(),
        )

        follower_event_count = sum(
            event["name"] == "followers_prepared" for event in state["events"]
        )
        repeated_result = self.prepare_followers("A")
        self.assertEqual(repeated_result["status"], "already_prepared")
        self.assertEqual(repeated_result["dispatch_ready"], [])
        repeated = pipeline.read_json(self.state_path)
        follower_queue = [
            item
            for item in repeated["scheduler"]["ready_queue"]
            if item["action"] == "generate_follower"
        ]
        self.assertEqual(len(follower_queue), 2)
        self.assertEqual(
            sum(event["name"] == "followers_prepared" for event in repeated["events"]),
            follower_event_count,
        )

    def test_cross_page_same_style_batch_dispatch_and_settle(self) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        self.prepare_followers("A")
        tasks = [
            {
                "style": "A",
                "page_id": page_id,
                "action": "generate_follower",
                "attempt": 1,
            }
            for page_id in ("05", "08")
        ]
        dispatched = self.dispatch(tasks, minute=3)
        self.assertEqual(dispatched["started"], 2)
        self.assertEqual(
            {(item["style"], item["page_id"]) for item in dispatched["tasks"]},
            {("A", "05"), ("A", "08")},
        )
        settled = self.settle(
            [
                self.result("A", "05", "generate_follower", minute=4),
                self.result("A", "08", "generate_follower", minute=4),
            ],
            minute=4,
            expected_styles="A",
        )
        self.assertEqual(settled["settled"], 2)
        state = pipeline.read_json(self.state_path)
        for page_id in ("05", "08"):
            record = state["styles"]["A"]["pages"][page_id]
            self.assertEqual(record["status"], "generated")
            self.assertEqual(record["attempt_count"], 1)
            self.assertEqual(
                record["selected_source"],
                str(self.follower_image_paths[page_id].resolve()),
            )
        self.assertFalse(
            any(
                item["style"] == "A" and item["page_id"] in {"05", "08"}
                for item in state["scheduler"]["active_actions"]
            )
        )
        self.assertIn("follower_generation_started_at", state["timing"])
        self.assertNotIn("all_anchor_tools_completed_at", state["timing"])
        wave = [event for event in state["events"] if event["name"] == "dispatch_wave"][-1]
        self.assertIsNone(wave["page_id"])
        self.assertEqual(len(wave["details"]["started_tasks"]), 2)

    def test_cross_task_duplicate_artifact_is_rejected(self) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        self.dispatch(
            [
                {
                    "style": "B",
                    "page_id": "02",
                    "action": "generate_anchor",
                    "attempt": 1,
                }
            ],
            minute=3,
        )
        with self.assertRaisesRegex(SystemExit, "跨任务重复绑定同一图片产物"):
            self.settle(
                [
                    self.result(
                        "B",
                        "02",
                        "generate_anchor",
                        minute=4,
                        source=self.image_path,
                    )
                ],
                minute=4,
                expected_styles="B",
            )

    def test_settle_rejects_a_ready_but_undispatched_page(self) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        self.prepare_followers("A")
        self.dispatch(
            [
                {
                    "style": "A",
                    "page_id": "05",
                    "action": "generate_follower",
                    "attempt": 1,
                }
            ],
            minute=3,
        )
        with self.assertRaisesRegex(SystemExit, "没有匹配的 active_action"):
            self.settle(
                [self.result("A", "08", "generate_follower", minute=4)],
                minute=4,
                expected_styles="A",
            )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["styles"]["A"]["pages"]["08"]["status"], "pending")
        self.assertTrue(
            any(
                item.get("page_id") == "05"
                and item.get("action") == "generate_follower"
                for item in state["scheduler"]["active_actions"]
            )
        )

    def test_recovery_queue_deduplicates_cross_page_tasks_and_recovers(self) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        self.prepare_followers("A")
        follower_tasks = [
            {
                "style": "A",
                "page_id": page_id,
                "action": "generate_follower",
                "attempt": 1,
            }
            for page_id in ("05", "08")
        ]
        self.dispatch(follower_tasks, minute=3)
        unresolved = [
            self.result(
                "A",
                page_id,
                "generate_follower",
                minute=4,
                error="artifact_handoff_unresolved",
            )
            for page_id in ("05", "08")
        ]
        self.settle(unresolved, minute=4, expected_styles="A")
        first_state = pipeline.read_json(self.state_path)
        self.assertEqual(len(first_state["scheduler"]["recovery_queue"]), 2)
        self.assertEqual(
            {
                (item["style"], item["page_id"], item["action"])
                for item in first_state["scheduler"]["recovery_queue"]
            },
            {
                ("A", "05", "recover_artifact"),
                ("A", "08", "recover_artifact"),
            },
        )
        unresolved_event_count = sum(
            event["name"] == "artifact_handoff_unresolved"
            for event in first_state["events"]
        )

        repeated = self.settle(unresolved, minute=5, expected_styles="A")
        self.assertEqual(repeated["skipped"], 2)
        repeated_state = pipeline.read_json(self.state_path)
        self.assertEqual(len(repeated_state["scheduler"]["recovery_queue"]), 2)
        self.assertEqual(
            sum(
                event["name"] == "artifact_handoff_unresolved"
                for event in repeated_state["events"]
            ),
            unresolved_event_count,
        )

        recovery_tasks = [
            {
                "style": "A",
                "page_id": page_id,
                "action": "recover_artifact",
                "attempt": 1,
            }
            for page_id in ("05", "08")
        ]
        self.dispatch(recovery_tasks, minute=6)
        recovered = [
            self.result(
                "A",
                page_id,
                "recover_artifact",
                minute=7,
                source_action="generate_follower",
                original_tool_minute=4,
            )
            for page_id in ("05", "08")
        ]
        self.settle(recovered, minute=7, expected_styles="A")
        recovered_state = pipeline.read_json(self.state_path)
        self.assertEqual(recovered_state["scheduler"]["recovery_queue"], [])
        for page_id in ("05", "08"):
            record = recovered_state["styles"]["A"]["pages"][page_id]
            self.assertEqual(record["recovery_status"], "recovered")
            self.assertEqual(record["recovery_attempt_count"], 1)
            self.assertEqual(record["attempt_count"], 1)
            self.assertEqual(
                record["worker_agent_id"],
                f"agent-A-{page_id}-generate_follower",
            )
            self.assertEqual(
                record["selected_source"],
                str(self.follower_image_paths[page_id].resolve()),
            )

    def test_unresolved_replay_must_match_queued_recovery_provenance(self) -> None:
        self.prepare_anchors()
        task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
        }
        self.assertEqual(self.dispatch([task], minute=0)["started"], 1)
        unresolved = self.result(
            "A",
            "02",
            "generate_anchor",
            minute=1,
            error="artifact_handoff_unresolved",
        )
        self.settle([unresolved], minute=1, expected_styles="A")
        queued_state = pipeline.read_json(self.state_path)
        self.assertEqual(len(queued_state["scheduler"]["recovery_queue"]), 1)

        exact_replay = self.settle([unresolved], minute=2, expected_styles="A")
        self.assertEqual(exact_replay["skipped"], 1)
        self.assertEqual(pipeline.read_json(self.state_path), queued_state)

        conflicting_replay = dict(unresolved)
        conflicting_replay.update(
            {
                "tool_call_id": "tool-A-02-generate_anchor-conflicting",
                "tool_started_at": "2099-01-01T00:02:10+08:00",
                "tool_finished_at": "2099-01-01T00:02:20+08:00",
            }
        )
        state_before_conflict = pipeline.read_json(self.state_path)
        with self.assertRaisesRegex(SystemExit, "与已排 recovery 的来源冲突"):
            self.settle([conflicting_replay], minute=3, expected_styles="A")
        self.assertEqual(pipeline.read_json(self.state_path), state_before_conflict)

    def test_recovery_without_original_agent_times_uses_tool_window(self) -> None:
        self.prepare_anchors()
        self.dispatch(
            [
                {
                    "style": "A",
                    "page_id": "02",
                    "action": "generate_anchor",
                    "attempt": 1,
                }
            ],
            minute=0,
        )
        unresolved = self.result(
            "A",
            "02",
            "generate_anchor",
            minute=1,
            error="artifact_handoff_unresolved",
        )
        unresolved["agent_action_started_at"] = None
        unresolved["agent_action_finished_at"] = None
        self.settle([unresolved], minute=1, expected_styles="A")
        queued = pipeline.read_json(self.state_path)["scheduler"]["recovery_queue"][0]
        self.assertEqual(queued["tool_call_id"], unresolved["tool_call_id"])
        self.assertEqual(queued["tool_started_at"], unresolved["tool_started_at"])

        self.dispatch(
            [
                {
                    "style": "A",
                    "page_id": "02",
                    "action": "recover_artifact",
                    "attempt": 1,
                }
            ],
            minute=2,
        )
        active = pipeline.read_json(self.state_path)["scheduler"]["active_actions"][0]
        self.assertEqual(active["source_action"], "generate_anchor")
        self.assertEqual(active["tool_finished_at"], unresolved["tool_finished_at"])
        recovered = self.result(
            "A",
            "02",
            "recover_artifact",
            minute=3,
            source_action="generate_anchor",
            original_tool_minute=1,
        )
        self.settle([recovered], minute=3, expected_styles="A")
        record = pipeline.read_json(self.state_path)["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["agent_action_started_at"], record["tool_started_at"])
        self.assertEqual(record["agent_action_finished_at"], record["tool_finished_at"])
        self.assertEqual(record["recovery_status"], "recovered")

    def test_deterministic_unbound_ambiguity_authorizes_one_attempt_two(self) -> None:
        self.prepare_anchors()
        generation_task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
        }
        self.assertEqual(self.dispatch([generation_task], minute=0)["started"], 1)
        unresolved = self.result(
            "A",
            "02",
            "generate_anchor",
            minute=1,
            error="artifact_handoff_unresolved",
        )
        self.settle([unresolved], minute=1, expected_styles="A")
        recovery_task = {
            "style": "A",
            "page_id": "02",
            "action": "recover_artifact",
            "attempt": 1,
        }
        self.assertEqual(self.dispatch([recovery_task], minute=2)["started"], 1)
        common = {
            "source_action": "generate_anchor",
            "attempt": 1,
            "tool_call_id": unresolved["tool_call_id"],
            "tool_started_at": unresolved["tool_started_at"],
            "tool_finished_at": unresolved["tool_finished_at"],
            "recovery_method": "deterministic_script",
            "recovery_worker_agent_id": "recovery-inspector",
        }
        self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="artifact_recovery_started",
            style="A",
            page_id="02",
            action="recover_artifact",
            timestamp="2099-01-01T00:03:00+08:00",
            details_json=json.dumps(common),
        )
        self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="artifact_recovery_finished",
            style="A",
            page_id="02",
            action="recover_artifact",
            timestamp="2099-01-01T00:04:00+08:00",
            details_json=json.dumps(
                {
                    **common,
                    "recovery_status": "ambiguous",
                    "candidate_count": 3,
                    "recovery_basis": (
                        "official_script_and_nonpixel_metadata_unbound"
                    ),
                }
            ),
        )
        state = pipeline.read_json(self.state_path)
        self.assertFalse(state["scheduler"]["recovery_queue"])
        retries = [
            item
            for item in state["scheduler"]["ready_queue"]
            if item.get("style") == "A"
            and item.get("page_id") == "02"
            and item.get("action") == "generate_anchor"
        ]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0]["attempt"], 2)
        self.assertIs(retries[0]["technical_retry"], True)
        self.assertEqual(
            retries[0]["retry_reason"], "artifact_recovery_ambiguous"
        )

    def test_backend_failure_skips_recovery_and_schedules_attempt_two(self) -> None:
        self.prepare_anchors()
        generation_task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
        }
        self.assertEqual(self.dispatch([generation_task], minute=0)["started"], 1)
        failed = self.result(
            "A",
            "02",
            "generate_anchor",
            minute=1,
            error="imagegen_backend_failed",
        )
        self.settle([failed], minute=1, expected_styles="A")

        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["status"], "retry_pending")
        self.assertEqual(record["technical_retry_count"], 1)
        self.assertFalse(state["scheduler"].get("recovery_queue"))
        retries = [
            item
            for item in state["scheduler"]["ready_queue"]
            if item.get("style") == "A"
            and item.get("page_id") == "02"
            and item.get("action") == "generate_anchor"
        ]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0]["attempt"], 2)
        self.assertIs(retries[0]["technical_retry"], True)
        self.assertEqual(retries[0]["retry_reason"], "imagegen_backend_failed")

        retry_dispatch = self.dispatch(retries, minute=2)
        self.assertEqual(retry_dispatch["started"], 1)
        state = pipeline.read_json(self.state_path)
        self.assertFalse(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "02"
                and item.get("action") == "generate_anchor"
                for item in state["scheduler"]["ready_queue"]
            )
        )
        self.assertEqual(len(state["scheduler"]["active_actions"]), 1)
        self.assertEqual(state["scheduler"]["active_actions"][0]["attempt"], 2)

    def test_second_backend_failure_terminalizes_fast4x3_run(self) -> None:
        self.prepare_anchors()
        first_task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
        }
        self.assertEqual(self.dispatch([first_task], minute=0)["started"], 1)
        self.settle(
            [
                self.result(
                    "A",
                    "02",
                    "generate_anchor",
                    attempt=1,
                    minute=1,
                    error="imagegen_backend_failed",
                )
            ],
            minute=1,
            expected_styles="A",
        )
        state = pipeline.read_json(self.state_path)
        retries = [
            item
            for item in state["scheduler"]["ready_queue"]
            if item.get("style") == "A"
            and item.get("page_id") == "02"
            and item.get("action") == "generate_anchor"
        ]
        self.assertEqual(len(retries), 1)
        self.assertEqual(self.dispatch(retries, minute=2)["started"], 1)

        # Simulate another style holding a shared ImageGen lease when this
        # required page exhausts its retry budget. Terminalization must release
        # that lease as well as clear the local queues.
        state = pipeline.read_json(self.state_path)
        state["scheduler"]["active_actions"].append(
            {
                "style": "B",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "global_imagegen_lease_id": "lease-b",
            }
        )
        pipeline.atomic_write_json(self.state_path, state)
        registry_path, _ = pipeline.fast8_global_imagegen_slot_paths(
            self.state_path, state
        )
        write_json(
            registry_path,
            {
                "fast8_global_imagegen_slot_contract_version": (
                    pipeline.FAST8_GLOBAL_IMAGEGEN_SLOT_CONTRACT_VERSION
                ),
                "capacity": 5,
                "leases": [
                    {
                        "lease_id": "lease-b",
                        "run_id": state["run_id"],
                        "state_path": str(self.state_path.resolve()),
                        "style": "B",
                        "page_id": "02",
                        "action": "generate_anchor",
                        "attempt": 1,
                        "acquired_at": "2099-01-01T00:02:00+08:00",
                        "expires_at": "2099-01-01T00:47:00+08:00",
                    }
                ],
            },
        )
        self.settle(
            [
                self.result(
                    "A",
                    "02",
                    "generate_anchor",
                    attempt=2,
                    minute=3,
                    error="imagegen_backend_failed",
                )
            ],
            minute=3,
            expected_styles="A",
        )

        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["scheduler"]["phase"], "terminal")
        self.assertFalse(state["scheduler"]["ready_queue"])
        self.assertFalse(state["scheduler"]["active_actions"])
        self.assertFalse(state["scheduler"].get("recovery_queue"))
        self.assertFalse(pipeline.read_json(registry_path)["leases"])
        terminal = [
            event for event in state["events"] if event.get("name") == "run_terminalized"
        ]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(
            terminal[0]["details"]["reason"],
            "required_fast4x3_page_exhausted",
        )

    def test_two_not_found_recoveries_schedule_attempt_two_and_reject_active_duplicate(
        self,
    ) -> None:
        self.prepare_anchors()
        generation_task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
        }
        self.assertEqual(self.dispatch([generation_task], minute=0)["started"], 1)
        unresolved = self.result(
            "A",
            "02",
            "generate_anchor",
            minute=1,
            error="artifact_handoff_unresolved",
        )
        self.settle([unresolved], minute=1, expected_styles="A")

        recovery_task = {
            "style": "A",
            "page_id": "02",
            "action": "recover_artifact",
            "attempt": 1,
        }
        self.assertEqual(self.dispatch([recovery_task], minute=2)["started"], 1)

        def record_recovery_event(
            event: str,
            minute: int,
            *,
            method: str,
            recovery_status: str | None = None,
        ) -> None:
            details = {
                "source_action": "generate_anchor",
                "attempt": 1,
                "tool_call_id": unresolved["tool_call_id"],
                "tool_started_at": unresolved["tool_started_at"],
                "tool_finished_at": unresolved["tool_finished_at"],
                "recovery_method": method,
                "recovery_worker_agent_id": "agent-A-02-recover_artifact",
            }
            if recovery_status is not None:
                details["recovery_status"] = recovery_status
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event=event,
                style="A",
                page_id="02",
                action="recover_artifact",
                timestamp=f"2099-01-01T00:{minute:02d}:00+08:00",
                details_json=json.dumps(details),
            )

        record_recovery_event(
            "artifact_recovery_started",
            3,
            method="same_worker",
        )
        record_recovery_event(
            "artifact_recovery_finished",
            4,
            method="same_worker",
            recovery_status="not_found",
        )
        after_first_not_found = pipeline.read_json(self.state_path)
        self.assertFalse(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "02"
                and item.get("action") == "recover_artifact"
                for item in after_first_not_found["scheduler"]["active_actions"]
            )
        )
        self.assertEqual(
            [
                (
                    item.get("style"),
                    item.get("page_id"),
                    item.get("action"),
                    item.get("attempt"),
                )
                for item in after_first_not_found["scheduler"]["recovery_queue"]
            ],
            [("A", "02", "recover_artifact", 1)],
        )

        self.assertEqual(self.dispatch([recovery_task], minute=5)["started"], 1)
        record_recovery_event(
            "artifact_recovery_started",
            6,
            method="deterministic_script",
        )
        record_recovery_event(
            "artifact_recovery_finished",
            7,
            method="deterministic_script",
            recovery_status="not_found",
        )
        after_second_not_found = pipeline.read_json(self.state_path)
        self.assertFalse(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "02"
                and item.get("action") == "recover_artifact"
                for item in after_second_not_found["scheduler"]["active_actions"]
            )
        )
        self.assertFalse(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "02"
                and item.get("action") == "recover_artifact"
                for item in after_second_not_found["scheduler"]["recovery_queue"]
            )
        )
        self.assertTrue(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "02"
                and item.get("action") == "generate_anchor"
                and item.get("attempt") == 2
                for item in after_second_not_found["scheduler"]["ready_queue"]
            )
        )

        retry_task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 2,
        }
        retry_dispatch = self.dispatch([retry_task], minute=8)
        self.assertEqual(retry_dispatch["started"], 1)
        self.assertEqual(retry_dispatch["tasks"][0]["attempt"], 2)

        dispatch_wave_count = sum(
            event["name"] == "dispatch_wave"
            for event in pipeline.read_json(self.state_path)["events"]
        )
        with self.assertRaises(SystemExit):
            self.dispatch([retry_task], minute=9)
        final_state = pipeline.read_json(self.state_path)
        self.assertEqual(
            sum(event["name"] == "dispatch_wave" for event in final_state["events"]),
            dispatch_wave_count,
        )
        self.assertEqual(
            [
                (
                    item.get("style"),
                    item.get("page_id"),
                    item.get("action"),
                    item.get("attempt"),
                )
                for item in final_state["scheduler"]["active_actions"]
                if item.get("style") == "A" and item.get("page_id") == "02"
            ],
            [("A", "02", "generate_anchor", 2)],
        )

    def test_recovery_finished_before_started_is_rejected(self) -> None:
        self.prepare_anchors()
        generation_task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
        }
        self.dispatch([generation_task], minute=0)
        unresolved = self.result(
            "A",
            "02",
            "generate_anchor",
            minute=1,
            error="artifact_handoff_unresolved",
        )
        self.settle([unresolved], minute=1, expected_styles="A")
        recovery_task = {
            "style": "A",
            "page_id": "02",
            "action": "recover_artifact",
            "attempt": 1,
        }
        self.dispatch([recovery_task], minute=2)
        state_before_finished = pipeline.read_json(self.state_path)

        with self.assertRaisesRegex(
            SystemExit,
            "必须先记录 artifact_recovery_started",
        ):
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event="artifact_recovery_finished",
                style="A",
                page_id="02",
                action="recover_artifact",
                timestamp="2099-01-01T00:03:00+08:00",
                details_json=json.dumps(
                    {
                        "source_action": "generate_anchor",
                        "attempt": 1,
                        "tool_call_id": unresolved["tool_call_id"],
                        "tool_started_at": unresolved["tool_started_at"],
                        "tool_finished_at": unresolved["tool_finished_at"],
                        "recovery_status": "not_found",
                        "recovery_method": "same_worker",
                    }
                ),
            )
        self.assertEqual(pipeline.read_json(self.state_path), state_before_finished)

    def test_not_found_authorization_is_scoped_to_source_action_and_attempt(
        self,
    ) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        state = pipeline.read_json(self.state_path)
        anchor_record = state["styles"]["A"]["pages"]["02"]
        for cycle in (1, 2):
            pipeline.append_event(
                state,
                "artifact_recovery_started",
                f"2099-01-01T00:0{cycle}:31+08:00",
                style="A",
                page_id="02",
                action="recover_artifact",
                details={
                    "source_action": "generate_anchor",
                    "attempt": 1,
                    "recovery_cycle": cycle,
                },
            )
            pipeline.append_event(
                state,
                "artifact_recovery_finished",
                f"2099-01-01T00:0{cycle}:32+08:00",
                style="A",
                page_id="02",
                action="recover_artifact",
                details={
                    "source_action": "generate_anchor",
                    "attempt": 1,
                    "recovery_status": "not_found",
                    "recovery_cycle": cycle,
                },
            )
        anchor_record["recovery_attempt_count"] = 2
        anchor_record["recovery_status"] = "not_found"
        write_json(self.state_path, state)

        self.call(
            pipeline.command_prepare_fast_anchor_repairs,
            project_dir=str(self.root),
            state=str(self.state_path),
            styles="A",
            issues_json=json.dumps({"A": "修复必显信息"}),
        )
        repair_task = {
            "style": "A",
            "page_id": "02",
            "action": "repair_anchor",
            "attempt": 2,
        }
        self.dispatch([repair_task], minute=3)
        unresolved_repair = self.result(
            "A",
            "02",
            "repair_anchor",
            attempt=2,
            minute=4,
            error="artifact_handoff_unresolved",
        )
        self.settle([unresolved_repair], minute=4, expected_styles="A")
        recovery_task = {
            "style": "A",
            "page_id": "02",
            "action": "recover_artifact",
            "attempt": 2,
        }
        self.dispatch([recovery_task], minute=5)
        recovery_details = {
            "source_action": "repair_anchor",
            "attempt": 2,
            "tool_call_id": unresolved_repair["tool_call_id"],
            "tool_started_at": unresolved_repair["tool_started_at"],
            "tool_finished_at": unresolved_repair["tool_finished_at"],
            "recovery_method": "same_worker",
        }
        self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="artifact_recovery_started",
            style="A",
            page_id="02",
            action="recover_artifact",
            timestamp="2099-01-01T00:06:00+08:00",
            details_json=json.dumps(recovery_details),
        )
        first_repair_not_found = self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="artifact_recovery_finished",
            style="A",
            page_id="02",
            action="recover_artifact",
            timestamp="2099-01-01T00:07:00+08:00",
            details_json=json.dumps(
                {**recovery_details, "recovery_status": "not_found"}
            ),
        )
        self.assertEqual(first_repair_not_found["next_action"], "recover_artifact")
        after_first_repair_not_found = pipeline.read_json(self.state_path)
        self.assertTrue(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "02"
                and item.get("action") == "recover_artifact"
                and item.get("source_action") == "repair_anchor"
                and item.get("attempt") == 2
                for item in after_first_repair_not_found["scheduler"][
                    "recovery_queue"
                ]
            )
        )
        self.assertFalse(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "02"
                and item.get("action") == "repair_anchor"
                and item.get("attempt") == 3
                for item in after_first_repair_not_found["scheduler"]["ready_queue"]
            )
        )

    def test_prepare_fast_followers_does_not_requeue_generation_during_recovery(
        self,
    ) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        self.prepare_followers("A")
        follower_task = {
            "style": "A",
            "page_id": "05",
            "action": "generate_follower",
            "attempt": 1,
        }
        self.dispatch([follower_task], minute=3)
        unresolved = self.result(
            "A",
            "05",
            "generate_follower",
            minute=4,
            error="artifact_handoff_unresolved",
        )
        self.settle([unresolved], minute=4, expected_styles="A")

        queued_result = self.prepare_followers("A")
        self.assertFalse(
            any(item.get("page_id") == "05" for item in queued_result["dispatch_ready"])
        )
        queued_state = pipeline.read_json(self.state_path)
        self.assertFalse(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "05"
                and item.get("action") == "generate_follower"
                for item in queued_state["scheduler"]["ready_queue"]
            )
        )
        self.assertTrue(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "05"
                and item.get("action") == "recover_artifact"
                for item in queued_state["scheduler"]["recovery_queue"]
            )
        )

        recovery_task = {
            "style": "A",
            "page_id": "05",
            "action": "recover_artifact",
            "attempt": 1,
        }
        self.dispatch([recovery_task], minute=5)
        active_result = self.prepare_followers("A")
        self.assertFalse(
            any(item.get("page_id") == "05" for item in active_result["dispatch_ready"])
        )
        active_state = pipeline.read_json(self.state_path)
        self.assertFalse(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "05"
                and item.get("action") == "generate_follower"
                for item in active_state["scheduler"]["ready_queue"]
            )
        )
        self.assertTrue(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "05"
                and item.get("action") == "recover_artifact"
                for item in active_state["scheduler"]["active_actions"]
            )
        )

    def test_prepare_fast_anchor_repair_refuses_during_repair_recovery(
        self,
    ) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        repair_args = {
            "project_dir": str(self.root),
            "state": str(self.state_path),
            "styles": "A",
            "issues_json": json.dumps({"A": "修复必显信息"}),
        }
        self.call(pipeline.command_prepare_fast_anchor_repairs, **repair_args)
        repair_task = {
            "style": "A",
            "page_id": "02",
            "action": "repair_anchor",
            "attempt": 2,
        }
        self.dispatch([repair_task], minute=3)
        unresolved = self.result(
            "A",
            "02",
            "repair_anchor",
            attempt=2,
            minute=4,
            error="artifact_handoff_unresolved",
        )
        self.settle([unresolved], minute=4, expected_styles="A")
        queued_state = pipeline.read_json(self.state_path)
        with self.assertRaisesRegex(SystemExit, "等待产物恢复"):
            self.call(pipeline.command_prepare_fast_anchor_repairs, **repair_args)
        self.assertEqual(pipeline.read_json(self.state_path), queued_state)
        self.assertFalse(
            (
                self.root
                / "style_jobs"
                / "repair_jobs"
                / "style_A_page_02_attempt_3_fast.json"
            ).exists()
        )

        recovery_task = {
            "style": "A",
            "page_id": "02",
            "action": "recover_artifact",
            "attempt": 2,
        }
        self.dispatch([recovery_task], minute=5)
        active_state = pipeline.read_json(self.state_path)
        with self.assertRaisesRegex(SystemExit, "仍有活动任务"):
            self.call(pipeline.command_prepare_fast_anchor_repairs, **repair_args)
        self.assertEqual(pipeline.read_json(self.state_path), active_state)
        self.assertFalse(
            (
                self.root
                / "style_jobs"
                / "repair_jobs"
                / "style_A_page_02_attempt_3_fast.json"
            ).exists()
        )

    def test_optional_anchor_repair_is_single_and_precedes_followers(self) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        self.assertFalse((self.root / "style_jobs" / "repair_jobs").exists())
        issue = "关键数字 100% 在首个候选中缺失"
        prepared = self.call(
            pipeline.command_prepare_fast_anchor_repairs,
            project_dir=str(self.root),
            state=str(self.state_path),
            styles="A",
            issues_json=json.dumps({"A": issue}),
        )
        self.assertEqual(len(prepared["repair_jobs"]), 1)
        repair_item = prepared["repair_jobs"][0]
        self.assertEqual(repair_item["attempt"], 2)
        repair_job = pipeline.read_json(Path(repair_item["job_path"]))
        self.assertEqual(repair_job["action"], "repair_anchor")
        self.assertEqual(repair_job["repair_source"], str(self.image_path.resolve()))
        self.assertIn(issue, repair_job["imagegen_prompt"])
        self.assertEqual(
            repair_job["imagegen_referenced_paths"], [str(self.image_path.resolve())]
        )
        self.assertTrue(repair_job["imagegen_input_fingerprint"])

        repeated = self.call(
            pipeline.command_prepare_fast_anchor_repairs,
            project_dir=str(self.root),
            state=str(self.state_path),
            styles="A",
            issues_json=json.dumps({"A": issue}),
        )
        self.assertEqual(len(repeated["repair_jobs"]), 1)
        state = pipeline.read_json(self.state_path)
        repair_queue = [
            item
            for item in state["scheduler"]["ready_queue"]
            if item.get("action") == "repair_anchor"
        ]
        self.assertEqual(len(repair_queue), 1)
        with self.assertRaisesRegex(SystemExit, r"队列 attempt=\[2\]"):
            self.dispatch(
                [
                    {
                        "style": "A",
                        "page_id": "02",
                        "action": "repair_anchor",
                        "attempt": 3,
                    }
                ],
                minute=3,
            )

        self.dispatch(
            [
                {
                    "style": "A",
                    "page_id": "02",
                    "action": "repair_anchor",
                    "attempt": 2,
                }
            ],
            minute=3,
        )
        repair_result = self.result(
            "A",
            "02",
            "repair_anchor",
            attempt=2,
            minute=4,
            source=self.repair_image_path,
        )
        self.settle(
            [repair_result],
            minute=4,
            expected_styles="A",
        )
        repaired_state = pipeline.read_json(self.state_path)
        repaired = repaired_state["styles"]["A"]["pages"]["02"]
        self.assertEqual(repaired["attempt_count"], 2)
        self.assertEqual(
            repaired["selected_source"], str(self.repair_image_path.resolve())
        )
        self.assertEqual(len(repaired["attempt_history"]), 1)
        self.assertEqual(repaired["attempt_history"][0]["attempt"], 1)
        self.assertEqual(repaired["selected_attempt"], 2)
        self.assertEqual(len(repaired["attempt_sources"]), 2)
        event_count = len(repaired_state["events"])
        replay = self.settle([repair_result], minute=5, expected_styles="A")
        self.assertEqual(replay["skipped"], 1)
        replayed_state = pipeline.read_json(self.state_path)
        self.assertEqual(
            len(replayed_state["styles"]["A"]["pages"]["02"]["attempt_history"]),
            1,
        )
        self.assertEqual(len(replayed_state["events"]), event_count)

        with self.assertRaisesRegex(SystemExit, "已使用过一次定向锚点修复"):
            self.call(
                pipeline.command_prepare_fast_anchor_repairs,
                project_dir=str(self.root),
                state=str(self.state_path),
                styles="A",
                issues_json=json.dumps({"A": "再次修复"}),
            )
        self.prepare_followers("A")
        contract = pipeline.read_json(self.root / "style_contracts" / "style_A.json")
        self.assertEqual(
            contract["anchor"]["path"], str(self.repair_image_path.resolve())
        )

    def test_repair_attempt_two_rejects_stale_anchor_id_and_png_without_mutation(
        self,
    ) -> None:
        self.prepare_anchors()
        self.complete_anchor("A")
        original_state = pipeline.read_json(self.state_path)
        original_record = original_state["styles"]["A"]["pages"]["02"]
        old_tool_call_id = original_record["tool_call_id"]
        old_selected_attempt = original_record["selected_attempt"]
        old_history = original_record.get("attempt_history")

        self.call(
            pipeline.command_prepare_fast_anchor_repairs,
            project_dir=str(self.root),
            state=str(self.state_path),
            styles="A",
            issues_json=json.dumps({"A": "关键数字需要修复"}),
        )
        repair_task = {
            "style": "A",
            "page_id": "02",
            "action": "repair_anchor",
            "attempt": 2,
        }
        self.assertEqual(self.dispatch([repair_task], minute=3)["started"], 1)
        state_before_stale_results = pipeline.read_json(self.state_path)

        stale_tool_result = self.result(
            "A",
            "02",
            "repair_anchor",
            attempt=2,
            minute=4,
            source=self.repair_image_path,
        )
        stale_tool_result["tool_call_id"] = old_tool_call_id
        with self.assertRaisesRegex(SystemExit, "旧 tool_call_id"):
            self.settle([stale_tool_result], minute=4, expected_styles="A")
        self.assertEqual(
            pipeline.read_json(self.state_path),
            state_before_stale_results,
        )

        stale_png_result = self.result(
            "A",
            "02",
            "repair_anchor",
            attempt=2,
            minute=5,
            source=self.image_path,
        )
        with self.assertRaisesRegex(SystemExit, "旧产物"):
            self.settle([stale_png_result], minute=5, expected_styles="A")
        final_state = pipeline.read_json(self.state_path)
        self.assertEqual(final_state, state_before_stale_results)
        final_record = final_state["styles"]["A"]["pages"]["02"]
        self.assertEqual(final_record["selected_attempt"], old_selected_attempt)
        self.assertEqual(final_record.get("attempt_history"), old_history)
        self.assertTrue(
            any(
                item.get("style") == "A"
                and item.get("page_id") == "02"
                and item.get("action") == "repair_anchor"
                and item.get("attempt") == 2
                for item in final_state["scheduler"]["active_actions"]
            )
        )

    def test_only_fast_anchor_may_keep_one_targeted_repair_candidate(self) -> None:
        record = {
            "status": "candidate_ready",
            "agent_action_started_at": "2026-07-26T10:00:00+08:00",
            "tool_started_at": "2026-07-26T10:01:00+08:00",
            "tool_finished_at": "2026-07-26T10:02:00+08:00",
            "agent_action_finished_at": "2026-07-26T10:04:00+08:00",
            "file_validated_at": "2026-07-26T10:05:00+08:00",
            "overview_qa_at": "2026-07-26T10:06:00+08:00",
            "completed_at": "2026-07-26T10:07:00+08:00",
            "tool_call_id": "tool-A-repair",
            "selected_source": str(self.image_path),
            "final_path": str(self.image_path),
            "attempt_count": 2,
            "attempt_sources": [str(self.image_path), str(self.image_path)],
        }
        self.assertEqual(
            pipeline.completed_quick_candidate_errors(
                record,
                "style_A/02",
                allow_targeted_anchor_repair=True,
            ),
            [],
        )
        errors = pipeline.completed_quick_candidate_errors(record, "style_A/05")
        self.assertTrue(any("有效候选超过允许上限" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
