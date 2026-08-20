from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tests.test_quick8_pipeline import write_json, write_png


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_control.py"
SPEC = importlib.util.spec_from_file_location("pipeline_control_fast8", MODULE_PATH)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


class Fast8PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shawn_fast8_")
        self.root = Path(self.temp.name)
        self.state_path = self.root / "state" / "style_run_state.json"
        self.content_path = self.root / "content_contracts" / "page_02.json"
        self.portfolio_path = self.root / "state" / "layout_portfolio.json"
        self.source_path = self.root / "source" / "outline.md"
        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path.write_text("## P02\nStable Fast8 content\n", encoding="utf-8")
        write_json(
            self.root / "state" / "task_init.json",
            {
                "task_init_contract_version": 1,
                "project_dir": str(self.root.resolve()),
                "source_snapshot_required": True,
                "created_at": "2099-01-01T00:00:00+08:00",
            },
        )
        write_json(
            self.state_path,
            {
                "run_id": "test-fast8-v7",
                "run_mode": pipeline.FAST8_MODE,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": [],
                "deferred_pages": [],
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
                "title": "测试标题",
                "core_claim": "测试主张",
                "source_facts": ["事实1"],
                "display_required": ["测试标题", "100%"],
                "display_flexible": ["洞察能力与行动能力共同促进目标达成"],
                "flexible_story": "两项互补能力共同促成一个目标结果；细节只作从属证据。",
                "display_supporting": [],
                "semantic_invariants": ["两项能力共同支撑目标达成"],
                "forbidden_interpretations": [],
                "prompt_semantic_guardrails": ["两项能力必须准确呈现"],
                "prompt_user_constraints": [],
                "visual_quality_intent": "专业克制、精致成熟，具有可信的工业科技质感。",
                "relationship_thesis": "两项能力不是并列清单，而是共同收束到同一个目标结果。",
                "information_density_target": "medium",
                "content_load_review": {
                    "must_render_groups": [],
                    "dense_relationships": [],
                    "visual_channels": [],
                    "semantic_structure": "单一主张",
                    "focus_relationship": "主从",
                    "attention_risks": [],
                    "edge_and_takeaway_risks": [],
                    "duplication_risks": [],
                    "reason": "可行",
                },
                "content_resolution": {
                    "status": "not_needed",
                    "choice": None,
                    "moved_items": [],
                    "reason": None,
                },
                "spatial_standard_version": 1,
                "spatial_generation_brief": pipeline.UNIFIED_SPATIAL_PROMPT_CUES["zh"],
                "spatial_qa_contract": "检查负空间、视觉重量和开放边缘",
                "spatial_feasibility": "pass",
                "visual_support_goal": "辅助理解主张",
                "craft_ambition": "精致成品级",
            },
        )
        visual_theses = [
            "让两项能力成为同一系统的两个连接面，并共同收束到目标结果",
            "让两股作用力汇聚到一个稳定结果，形成清楚的因果张力",
            "让观众沿着连续路径看见能力如何转化为目标达成",
            "让一个完整核心包容两项能力，突出整体大于简单相加",
            "让证据层级从两项能力逐级收束到唯一结论",
            "让两种互补信号在同一决策点合流，形成明确阅读焦点",
            "让前景中的目标结果反向统领两项支撑能力的主次关系",
            "让两项能力以不同尺度互锁，直接呈现共同负责的整体关系",
        ]
        craft_axes = [
            "精密工业剖视、真实材质与克制光影",
            "编辑字体、大胆尺度关系与受控负空间",
            "连续摄影叙事、细腻景深与自然光感",
            "高端信息雕塑、半透明材料与精细边缘",
            "工程制图语言、严谨线条与局部真实纹理",
            "信号场可视化、微粒光效与清晰字体层级",
            "纪实工业摄影、强前后景关系与克制标注",
            "纸张拼贴与精细排版形成的现代编辑工艺",
        ]
        representation_families = [
            "双面连接体",
            "双向汇流",
            "连续转化路径",
            "整体包容结构",
            "证据阶梯",
            "信号合流场",
            "结果反向统领",
            "异尺度互锁",
        ]
        styles = {}
        activity_modes = [
            "restrained",
            "balanced",
            "restrained",
            "expressive",
            "restrained",
            "balanced",
            "restrained",
            "balanced",
        ]
        primary_entries = [
            "single_focus",
            "paired_contrast",
            "path",
            "network",
            "field",
            "hierarchy",
            "radial",
            "evidence_hero",
        ]
        region_logics = [
            "unified_field",
            "asymmetric_split",
            "staged_path",
            "distributed_nodes",
            "layered_depth",
            "annotated_object",
            "geographic_spread",
            "editorial_sequence",
        ]
        evidence_modes = [
            "integrated",
            "annotated",
            "integrated",
            "satellite",
            "integrated",
            "annotated",
            "quiet_band",
            "none",
        ]
        for index, style in enumerate(pipeline.QUICK_STYLES):
            styles[style] = {
                "direction_id": f"run_local_{style}",
                "visual_thesis": visual_theses[index],
                "relationship_representation_family": representation_families[index],
                "craft_axis": craft_axes[index],
                "visual_activity_mode": activity_modes[index],
                "attention_strategy": (
                    f"由候选 {style} 的主导关系承担第一眼，其他证据降低对比并保留停顿。"
                ),
                "spatial_topology": {
                    "primary_entry": primary_entries[index],
                    "region_logic": region_logics[index],
                    "evidence_attachment": evidence_modes[index],
                    "spatial_topology_intent": (
                        f"候选 {style} 用独立空间关系组织主视觉与证据。"
                    ),
                },
            }
        write_json(
            self.portfolio_path,
            {
                "layout_portfolio_contract_version": 7,
                "art_direction_contract_version": 1,
                "visual_activity_portfolio_version": 1,
                "spatial_topology_portfolio_version": 1,
                "page_id": "02",
                "director_rationale": "用八个可见关系命题与独立工艺轴扩大真实选择面。",
                "styles": styles,
            },
        )
        self.initial_paths: dict[str, Path] = {}
        for index, style in enumerate(pipeline.QUICK_STYLES):
            path = self.root / "fixtures" / f"initial_{style}.png"
            write_png(path, color=bytes((230 - index, 240 - index, 250 - index)))
            self.initial_paths[style] = path

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_explicit_preflight_tone_override_outranks_reference_policy(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["tone_overrides"] = {style: "dark" for style in pipeline.QUICK_STYLES}

        changed = pipeline.apply_background_tone_policy(
            state,
            {
                "mode": "uniform",
                "tone": "light",
                "source": "primary_style_reference",
            },
            pipeline.QUICK_STYLES,
            label="test.background_tone_policy",
        )

        self.assertFalse(changed)
        self.assertEqual(
            state["tone_overrides"],
            {style: "dark" for style in pipeline.QUICK_STYLES},
        )

    def test_required_assets_file_normalizes_v1_director_envelope(self) -> None:
        light_logo = self.root / "fixtures" / "director_light.png"
        evidence = self.root / "fixtures" / "director_evidence.png"
        write_png(light_logo, color=bytes((240, 240, 240)))
        write_png(evidence, color=bytes((210, 220, 230)))
        path = self.root / "state" / "director_inputs" / "required_assets.json"
        write_json(
            path,
            {
                "canonical_page_id": "02",
                "asset_contract_version": 1,
                "assets": [
                    {
                        "path": str(evidence),
                        "type": "project_visual_evidence",
                        "requirements": "只作项目事实证据",
                    },
                    {
                        "path": str(light_logo),
                        "sha256": pipeline.file_sha256(light_logo),
                        "type": "official_logo",
                        "required_when": "light_background",
                        "requirements": "原样使用",
                    },
                ],
                "reference_assets_not_sent_to_imagegen": [],
            },
        )
        result = pipeline.read_required_assets_input(
            json_value=None,
            file_value=str(path),
            expected_page_id="02",
        )
        self.assertEqual(
            [item["path"] for item in result],
            [str(evidence.resolve()), str(light_logo.resolve())],
        )
        self.assertEqual(result[0]["role"], "project_visual_evidence")
        self.assertEqual(result[0]["use"], "只作项目事实证据")
        self.assertEqual(result[1]["tones"], ["light"])
        self.assertEqual(result[0]["sha256"], pipeline.file_sha256(evidence))
        self.assertEqual(result[1]["sha256"], pipeline.file_sha256(light_logo))

    def test_matching_redundant_style_slot_is_script_normalized(self) -> None:
        portfolio = pipeline.read_json(self.portfolio_path)
        for style in pipeline.QUICK_STYLES:
            portfolio["styles"][style]["style_slot"] = style
        write_json(self.portfolio_path, portfolio)
        self.prepare()
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        self.assertEqual(job["style_slot"], "A")

    def test_required_assets_file_rejects_wrong_page_without_partial_guessing(self) -> None:
        asset = self.root / "fixtures" / "wrong_page.png"
        write_png(asset, color=bytes((200, 200, 200)))
        path = self.root / "state" / "director_inputs" / "required_assets.json"
        write_json(
            path,
            {
                "canonical_page_id": "P20",
                "asset_contract_version": 1,
                "assets": [{"path": str(asset), "type": "source_slide"}],
            },
        )
        with self.assertRaisesRegex(SystemExit, "页码与当前运行不一致"):
            pipeline.read_required_assets_input(
                json_value=None,
                file_value=str(path),
                expected_page_id="02",
            )

    def test_global_chrome_title_must_match_content_contract_when_both_are_explicit(self) -> None:
        with self.assertRaisesRegex(SystemExit, "主标题与内容合同标题不一致"):
            pipeline.validate_page_global_chrome_compatibility(
                {"page_title": "正确标题", "prompt_user_constraints": []},
                {
                    "applies": True,
                    "logo_required": False,
                    "main_title_required": True,
                    "main_title": {"text": "错误标题"},
                },
                "P20",
            )

    def call(self, function, **kwargs):
        stream = io.StringIO()
        with redirect_stdout(stream):
            result = function(argparse.Namespace(**kwargs))
        output = stream.getvalue().strip()
        return result, json.loads(output) if output else None

    def write_global_chrome_contract(self) -> Path:
        authorization_source = self.root / "source" / "visual_system.md"
        authorization_source.write_text(
            "## 统一标题区\nP02 使用官方 Logo 与固定标题层级。\n",
            encoding="utf-8",
        )
        dark_logo = self.root / "fixtures" / "ra_dark.png"
        light_logo = self.root / "fixtures" / "ra_light.png"
        qa_reference = self.root / "fixtures" / "title_reference.png"
        write_png(dark_logo, color=bytes((255, 255, 255)))
        write_png(light_logo, color=bytes((220, 20, 60)))
        write_png(qa_reference, color=bytes((240, 240, 240)))
        path = self.root / "global_chrome_contract.json"
        write_json(
            path,
            {
                "global_chrome_contract_version": 1,
                "contract_id": "test-deck-title-v1",
                "authorization": {
                    "status": "authorized",
                    "source_kind": "authoritative_outline",
                    "source_path": str(authorization_source),
                    "source_sha256": pipeline.file_sha256(authorization_source),
                    "source_locator": "## 统一标题区",
                },
                "deck_title_system": {
                    "enabled": True,
                    "scope": {
                        "include_page_ids": ["02"],
                        "exclude_page_ids": [],
                    },
                    "logo": {
                        "required": True,
                        "assets_by_tone": {
                            "dark": {"path": str(dark_logo)},
                            "light": {"path": str(light_logo)},
                        },
                    },
                    "main_title": {
                        "required": True,
                        "text": "测试标题",
                        "position": "logo right",
                        "alignment": "shared baseline",
                        "safe_margin": "inside safe area",
                    },
                    "subtitle_policy": "source_only_optional",
                    "prompt_briefs": {
                        "zh": "使用轻量全稿标题区：官方 Logo 在标题起始侧，主标题在右并共享基线与安全边距；正文构图保持自由。",
                        "en": "Use the lightweight deck title system with the official logo, shared title baseline, and safe margins; keep the body open.",
                    },
                    "qa_required": True,
                    "qa_reference_path": str(qa_reference),
                    "qa_checks": ["Logo", "标题层级", "基线与安全边距", "标题区视觉重量"],
                },
            },
        )
        return path

    def prepare(
        self,
        global_chrome_contract: Path | None = None,
        overview_python: str | None = None,
    ) -> None:
        if global_chrome_contract is None:
            pipeline.create_source_snapshot(
                project_dir=self.root,
                state_path=self.state_path,
                source_path=self.source_path,
                page_ids=["02"],
                content_contract_paths=[self.content_path],
                asset_items=[],
                timestamp="2099-01-01T00:00:01+08:00",
            )
        self.call(
            pipeline.command_prepare_anchors,
            project_dir=str(self.root),
            state=str(self.state_path),
            content_contract=str(self.content_path),
            overall_requirements="八张保持内容准确并扩大视觉探索",
            reference_images_json="[]",
            required_assets_json="[]",
            layout_portfolio=str(self.portfolio_path),
            source_file=(
                str(self.source_path) if global_chrome_contract is not None else None
            ),
            source_page_ids=None,
            source_fragment_file=None,
            snapshot_content_contracts_json=None,
            source_snapshot_timestamp=None,
            global_chrome_contract=(
                str(global_chrome_contract)
                if global_chrome_contract is not None
                else None
            ),
            overview_python=overview_python,
        )

    def prepare_root_with_assets(
        self,
        root: Path,
        *,
        reference_images: list[dict],
        required_assets: list[dict],
    ) -> None:
        self.call(
            pipeline.command_prepare_anchors,
            project_dir=str(root),
            state=str(root / "state" / "style_run_state.json"),
            content_contract=str(root / "content_contracts" / "page_02.json"),
            overall_requirements="八张保持内容准确并扩大视觉探索",
            reference_images_json=json.dumps(reference_images),
            required_assets_json=json.dumps(required_assets),
            layout_portfolio=str(root / "state" / "layout_portfolio.json"),
            source_file=str(root / "source" / "outline.md"),
            source_page_ids=None,
            source_fragment_file=None,
            snapshot_content_contracts_json=None,
            source_snapshot_timestamp="2099-01-01T00:00:01+08:00",
            global_chrome_contract=None,
            overview_python=None,
        )

    def result(
        self,
        style: str,
        *,
        action: str = "generate_anchor",
        attempt: int = 1,
        path: Path | None = None,
        minute: int = 0,
    ) -> dict:
        index = ord(style) - ord("A")
        return {
            "style": style,
            "page_id": "02",
            "action": action,
            "attempt": attempt,
            "worker_agent_id": f"agent-{style}-{attempt}",
            "agent_action_started_at": f"2026-08-03T10:{minute:02d}:{index:02d}+08:00",
            "agent_action_finished_at": f"2026-08-03T10:{minute + 1:02d}:{index:02d}+08:00",
            "tool_call_id": f"tool-{style}-{attempt}",
            "savedPath": str(path or self.initial_paths[style]),
            "tool_started_at": f"2026-08-03T10:{minute:02d}:{index + 10:02d}+08:00",
            "tool_finished_at": f"2026-08-03T10:{minute:02d}:{index + 40:02d}+08:00",
            "error": None,
        }

    def settle_initials(self) -> None:
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A,B,C,D,E,F,G,H",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=None,
            backpressure_reason=None,
        )
        results_path = self.root / "style_jobs" / "results" / "initial.json"
        write_json(results_path, [self.result(style) for style in pipeline.QUICK_STYLES])
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(results_path),
            expected_styles="A,B,C,D,E,F,G,H",
            timestamp="2026-08-03T10:02:00+08:00",
        )

    def make_review(self, checkpoint: int = 8) -> tuple[Path, dict]:
        _, output = self.call(
            pipeline.command_prepare_fast8_diversity_review,
            project_dir=str(self.root),
            state=str(self.state_path),
            checkpoint=checkpoint,
        )
        assert output
        job_path = Path(output["review_job"])
        job = pipeline.read_json(job_path)
        if isinstance(job.get("judge_runtime_contract"), dict):
            self.call(
                pipeline.command_bind_fast8_judge_session,
                state=str(self.state_path),
                review_job=str(job_path),
                session_id="019fcdb5-c91c-7b60-b931-e2442324b122",
                model="gpt-5.6-terra",
                reasoning_effort="low",
                fork_turns="none",
                timestamp="2026-08-03T10:03:00+08:00",
            )
        return job_path, output

    def write_report(
        self,
        job_path: Path,
        *,
        decision: str,
        replacements: list[str] | None = None,
        briefs: dict[str, str] | None = None,
        craft_red_flags: list[dict] | None = None,
        collision_for_replacements: bool = True,
        suffix: str = "report",
    ) -> Path:
        job = pipeline.read_json(job_path)
        path = self.root / "visual_qa_jobs" / "results" / f"{suffix}.json"
        replacement_styles = replacements or []
        collision_groups = []
        if decision == "replace" and collision_for_replacements:
            collision_styles = list(replacement_styles)
            for candidate in pipeline.QUICK_STYLES:
                if candidate not in collision_styles:
                    collision_styles.append(candidate)
                    break
            collision_groups = [
                {
                    "styles": collision_styles,
                    "overlap_axes": [
                        "reading_entry",
                        "information_organization",
                    ],
                    "observable_evidence": "这些席位使用相同阅读入口和信息组织骨架，选择价值明显下降。",
                }
            ]
        report = {
            "diversity_judge_contract_version": job[
                "diversity_judge_contract_version"
            ],
            "review_job_sha256": pipeline.file_sha256(job_path),
            "candidate_set_sha256": job["candidate_set_sha256"],
            "decision": decision,
            "high_confidence": decision == "replace",
            "replacement_styles": replacement_styles,
            "replacement_briefs": briefs or {},
            "collision_groups": collision_groups,
            "summary": "检查候选组合差异和版本允许的最低工艺边界。",
        }
        if job["diversity_judge_contract_version"] == 2:
            report["craft_red_flags"] = craft_red_flags or []
        if "integrated_global_chrome_check" in job:
            report["global_chrome"] = {
                "decision": "pass",
                "failed_styles": [],
                "unknown_styles": [],
                "summary": "大纲授权的 Logo 与标题区关系在同一接触表上大致成立。",
            }
        if "integrated_required_asset_usage_check" in job:
            report["required_assets"] = {
                "decision": "pass",
                "failed_styles": [],
                "unknown_styles": [],
                "summary": "已按每席实际触发条件检查 required asset 的指定用途。",
            }
        write_json(path, report)
        return path

    def test_prepare_uses_art_directed_prompts_and_nine_slots(self) -> None:
        self.prepare()
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["run_mode"], pipeline.FAST8_MODE)
        self.assertEqual(state["art_direction_contract_version"], 1)
        self.assertEqual(state["scheduler"]["active_child_limit"], 9)
        self.assertEqual(state["scheduler"]["image_child_limit"], 8)
        self.assertEqual(state["scheduler"]["diversity_judge_child_limit"], 1)
        self.assertEqual(
            state["diversity_review"]["scheduling_policy"],
            "final_only_after_same_wave",
        )
        self.assertEqual(
            state["diversity_review"]["replacement_recheck_policy"],
            "delta_review_evidence_first",
        )
        self.assertEqual(state["fast8_candidate_policy"]["version"], 2)
        self.assertEqual(
            state["fast8_candidate_policy"]["creative_brief_projection_version"],
            1,
        )
        self.assertTrue(
            state["fast8_candidate_policy"]["relationship_thesis_required"]
        )
        self.assertEqual(
            state["fast8_candidate_policy"]["visual_activity_portfolio_version"],
            1,
        )
        self.assertEqual(state["spatial_topology_portfolio_version"], 1)
        self.assertEqual(
            state["fast8_candidate_policy"]["spatial_topology_portfolio_version"],
            1,
        )
        self.assertTrue(state["fast8_candidate_policy"]["spatial_topology_required"])
        self.assertTrue(
            state["fast8_candidate_policy"]["explicit_flexible_story_required"]
        )
        self.assertEqual(
            state["fast8_candidate_policy"][
                "same_worker_recovery_soft_escalation_seconds"
            ],
            0,
        )
        self.assertTrue(
            state["fast8_candidate_policy"][
                "deterministic_recovery_may_race_after_soft_escalation"
            ]
        )
        self.assertEqual(
            state["fast8_candidate_policy"]["optional_effect_review_policy"],
            {
                "preferred_model": "gpt-5.6-terra",
                "reasoning_effort": "low",
                "max_overview_view_calls": 1,
                "soft_timeout_seconds": 180,
                "max_retries_same_overview_sha256": 1,
                "formal_timing_excluded": True,
            },
        )

        self.assertEqual(state["diversity_review"]["contract_version"], 2)
        self.assertEqual(
            state["diversity_review"]["scope"],
            "diversity_and_minimum_craft",
        )
        fingerprints = []
        for style in pipeline.QUICK_STYLES:
            job = pipeline.read_json(self.root / "style_jobs" / f"style_{style}.json")
            self.assertEqual(job["imagegen_prompt_contract_version"], 6)
            self.assertIn("审美与完成度意图", job["imagegen_prompt"])
            self.assertIn("页面导演", job["imagegen_prompt"])
            self.assertIn("关系表达家族", job["imagegen_prompt"])
            self.assertIn("本候选的可见命题", job["imagegen_prompt"])
            self.assertIn("视觉活跃度", job["imagegen_prompt"])
            self.assertIn("空间关系=", job["imagegen_prompt"])
            self.assertIn("注意力=", job["imagegen_prompt"])
            self.assertIn("用一个主导关系统领", job["imagegen_prompt"])
            self.assertIn("图像工艺=", job["imagegen_prompt"])
            self.assertIn("没有风格参考图时", job["imagegen_prompt"])
            self.assertEqual(job["imagegen_prompt"].count("页级关系="), 1)
            self.assertNotIn("开放性创作启发", job["imagegen_prompt"])
            self.assertNotIn("关系综合", job["imagegen_prompt"])
            self.assertNotIn("叙事收束", job["imagegen_prompt"])
            projection = job["creative_brief_projection"]
            self.assertEqual(projection["creative_brief_projection_version"], 1)
            self.assertEqual(
                projection["relationship_thesis"],
                "两项能力不是并列清单，而是共同收束到同一个目标结果。",
            )
            self.assertEqual(projection["literal_anchors"], ["测试标题", "100%"])
            self.assertEqual(
                projection["flexible_story"],
                "两项互补能力共同促成一个目标结果；细节只作从属证据。",
            )
            self.assertEqual(
                projection["flexible_story_source"], "explicit_director_story"
            )
            self.assertTrue(projection["visual_thesis"])
            self.assertTrue(projection["relationship_representation_family"])
            self.assertTrue(projection["craft_axis"])
            self.assertIn(projection["visual_activity_mode"], {"restrained", "balanced", "expressive"})
            self.assertTrue(projection["attention_strategy"])
            self.assertEqual(
                projection["narrative_layer_budget"]["primary_relationships"], 1
            )
            self.assertEqual(
                projection["narrative_layer_budget"][
                    "supporting_evidence_layers_max"
                ],
                1,
            )
            self.assertTrue(projection["spatial_topology"]["spatial_topology_intent"])
            self.assertIn("语义护栏", job["imagegen_prompt"])
            self.assertIn("两项能力必须准确呈现", job["imagegen_prompt"])
            self.assertNotIn(job["layout_direction"]["direction_id"], job["imagegen_prompt"])
            expected = pipeline.hashlib.sha256(
                job["imagegen_prompt"].encode("utf-8")
            ).hexdigest()
            self.assertEqual(job["imagegen_prompt_fingerprint"], expected)
            fingerprints.append(expected)
        self.assertEqual(len(set(fingerprints)), 8)

    def test_prepare_binds_one_preflighted_overview_python(self) -> None:
        check = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(pipeline.subprocess, "run", return_value=check) as run:
            self.prepare(overview_python=pipeline.sys.executable)
        state = pipeline.read_json(self.state_path)
        self.assertEqual(
            state["overview_runtime"],
            {
                "python": str(Path(pipeline.sys.executable).resolve()),
                "pillow_preflight": "pass",
                "binding_policy": "reuse_for_formal_overview",
            },
        )
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][1:3], ["-c", "from PIL import Image"])

    def test_preflight_allocated_fast8_requires_overview_runtime_before_jobs(self) -> None:
        marker_path = self.root / "state" / "task_init.json"
        marker = pipeline.read_json(marker_path)
        marker["formal_directory_allocation_policy"] = "after_preflight_pass"
        marker["preflight_manifest_path"] = str(
            (self.root / "state" / "preflight_manifest.json").resolve()
        )
        write_json(marker_path, marker)
        with self.assertRaisesRegex(SystemExit, "--overview-python"):
            self.prepare()
        self.assertFalse((self.root / "style_jobs" / "style_A.json").exists())

    def test_startup_bound_runtime_is_reused_without_prepare_recheck(self) -> None:
        marker_path = self.root / "state" / "task_init.json"
        marker = pipeline.read_json(marker_path)
        marker["formal_directory_allocation_policy"] = "after_preflight_pass"
        write_json(marker_path, marker)
        state = pipeline.read_json(self.state_path)
        state["fast8_startup_contract_version"] = 1
        state["overview_runtime"] = {
            "python": str(Path(pipeline.sys.executable).resolve()),
            "pillow_preflight": "pass",
            "binding_policy": "startup_bound_reuse_for_formal_overview",
        }
        state["timing"] = {
            "process_started_at": "2026-08-03T09:50:00+08:00",
            "preflight_resolved_at": "2026-08-03T09:51:00+08:00",
        }
        state["events"] = [
            {"sequence": 1, "name": "process_started"},
            {"sequence": 2, "name": "preflight_resolved"},
        ]
        write_json(self.state_path, state)
        with mock.patch.object(
            pipeline.subprocess,
            "run",
            side_effect=AssertionError("prepare must not recheck startup runtime"),
        ):
            self.prepare()
        prepared = pipeline.read_json(self.state_path)
        self.assertEqual(
            prepared["overview_runtime"]["binding_policy"],
            "startup_bound_reuse_for_formal_overview",
        )

    def test_source_snapshot_validates_modern_contract_before_sealing(self) -> None:
        contract = pipeline.read_json(self.content_path)
        contract["language"] = "source"
        contract["spatial_generation_brief"] = pipeline.UNIFIED_SPATIAL_PROMPT_CUES[
            "en"
        ]
        write_json(self.content_path, contract)

        with self.assertRaisesRegex(SystemExit, "spatial_generation_brief"):
            pipeline.create_source_snapshot(
                project_dir=self.root,
                state_path=self.state_path,
                source_path=self.source_path,
                page_ids=["02"],
                content_contract_paths=[self.content_path],
                asset_items=[],
                timestamp="2099-01-01T00:00:01+08:00",
            )

        self.assertFalse((self.root / "state" / "source_snapshot.json").exists())

    def test_source_language_infers_prompt_locale_from_display_copy(self) -> None:
        contract = pipeline.read_json(self.content_path)
        contract["language"] = "source"
        self.assertEqual(pipeline.content_contract_prompt_locale(contract), "zh")
        pipeline.validate_dispatchable_content_contract(contract, "中文 source 合同")

        contract["display_required"] = ["Global delivery model", "100%"]
        contract["display_flexible"] = ["One company owns the outcome"]
        contract["flexible_story"] = "One accountable delivery path."
        contract["spatial_generation_brief"] = pipeline.UNIFIED_SPATIAL_PROMPT_CUES[
            "en"
        ]
        self.assertEqual(pipeline.content_contract_prompt_locale(contract), "en")
        pipeline.validate_dispatchable_content_contract(contract, "英文 source 合同")

    def test_supporting_planning_source_is_not_generation_asset_and_drift_is_guarded(
        self,
    ) -> None:
        planning_source = self.root / "source" / "visual_rules.md"
        planning_source.write_text("planning constraints v1\n", encoding="utf-8")
        write_json(
            self.root / "state" / "preflight_manifest.json",
            {
                "required_files": [
                    str(self.source_path.resolve()),
                    str(planning_source.resolve()),
                    str(self.content_path.resolve()),
                ]
            },
        )
        supporting = pipeline.preflight_supporting_source_paths(
            self.root,
            authoritative_source=self.source_path,
            content_contract_paths=[self.content_path],
            asset_items=[],
        )
        self.assertEqual(supporting, [planning_source.resolve()])
        pipeline.create_source_snapshot(
            project_dir=self.root,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=["02"],
            content_contract_paths=[self.content_path],
            asset_items=[],
            supporting_source_paths=supporting,
            timestamp="2099-01-01T00:00:01+08:00",
        )
        snapshot = pipeline.read_json(self.root / "state" / "source_snapshot.json")
        self.assertEqual(snapshot["assets"], [])
        self.assertEqual(
            [item["path"] for item in snapshot["supporting_sources"]],
            [str(planning_source.resolve())],
        )
        planning_source.write_text("planning constraints v2\n", encoding="utf-8")
        drift = pipeline.evaluate_source_drift(self.state_path, action="resume")
        self.assertEqual(drift["status"], "source_drift_detected")
        self.assertTrue(drift["supporting_source_changed"])
        self.assertFalse(drift["can_continue"])

    def test_supporting_sources_accept_resolved_preflight_records(self) -> None:
        planning_source = self.root / "source" / "resolved_visual_rules.md"
        planning_source.write_text("planning constraints v1\n", encoding="utf-8")
        write_json(
            self.root / "state" / "preflight_manifest.json",
            {
                "required_files": [
                    {
                        "path": str(self.source_path.resolve()),
                        "exists": True,
                        "sha256": pipeline.file_sha256(self.source_path),
                    },
                    {
                        "path": str(planning_source.resolve()),
                        "exists": True,
                        "sha256": pipeline.file_sha256(planning_source),
                    },
                    {
                        "path": str(self.content_path.resolve()),
                        "exists": True,
                        "sha256": pipeline.file_sha256(self.content_path),
                    },
                ]
            },
        )
        supporting = pipeline.preflight_supporting_source_paths(
            self.root,
            authoritative_source=self.source_path,
            content_contract_paths=[self.content_path],
            asset_items=[],
        )
        self.assertEqual(supporting, [planning_source.resolve()])

        planning_source.write_text("planning constraints v2\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "SHA-256 与预检结果不一致"):
            pipeline.preflight_supporting_source_paths(
                self.root,
                authoritative_source=self.source_path,
                content_contract_paths=[self.content_path],
                asset_items=[],
            )

    def test_new_fast8_rejects_project_evidence_in_style_reference_slot(self) -> None:
        evidence = self.root / "fixtures" / "source_slide.png"
        write_png(evidence)
        with self.assertRaisesRegex(SystemExit, "请移入 required_assets"):
            self.call(
                pipeline.command_prepare_anchors,
                project_dir=str(self.root),
                state=str(self.state_path),
                content_contract=str(self.content_path),
                overall_requirements="扩大探索",
                reference_images_json=json.dumps(
                    [
                        {
                            "path": str(evidence.resolve()),
                            "role": "project_visual_evidence",
                        }
                    ]
                ),
                required_assets_json="[]",
                layout_portfolio=str(self.portfolio_path),
                source_file=None,
                source_page_ids=None,
                source_fragment_file=None,
                snapshot_content_contracts_json=None,
                source_snapshot_timestamp=None,
            )
        self.assertFalse((self.root / "style_jobs" / "style_A.json").exists())

    def test_asset_used_by_alias_preserves_snapshot_and_task_routing(self) -> None:
        logo = self.root / "fixtures" / "logo.png"
        write_png(logo)
        item = {
            "path": str(logo.resolve()),
            "asset_type": "required_asset",
            "role": "official_logo",
            "used_by": ["A", "B"],
        }
        records = pipeline.normalize_asset_records([item])
        self.assertEqual(records[0]["used_by"], ["A", "B"])
        self.assertEqual(
            pipeline.filter_routed_attachments([item], "A", "dark", "assets"),
            [item],
        )
        self.assertEqual(
            pipeline.filter_routed_attachments([item], "C", "dark", "assets"),
            [],
        )

    def test_conflicting_asset_routing_aliases_are_rejected(self) -> None:
        logo = self.root / "fixtures" / "logo.png"
        write_png(logo)
        item = {
            "path": str(logo.resolve()),
            "style_slots": ["A"],
            "used_by": ["B"],
        }
        with self.assertRaisesRegex(SystemExit, "路由字段冲突"):
            pipeline.normalize_asset_records([item])

    def test_snapshot_tagging_keeps_metadata_and_replaces_authoring_routes(self) -> None:
        item = {
            "path": "/tmp/example.png",
            "role": "project_visual_evidence",
            "asset_type": "required_asset",
            "tones": ["dark", "light"],
            "requirements": "保持事实关系",
            "sha256": "abc123",
            "style_slots": list(pipeline.QUICK_STYLES),
            "used_by": list(pipeline.QUICK_STYLES),
        }
        tagged = pipeline.snapshot_tagged_asset(
            item, asset_type="required_asset", style="C"
        )
        self.assertEqual(tagged["styles"], ["C"])
        self.assertNotIn("style_slots", tagged)
        self.assertNotIn("used_by", tagged)
        for field in ("path", "role", "asset_type", "tones", "requirements", "sha256"):
            self.assertEqual(tagged[field], item[field])
        self.assertEqual(item["style_slots"], list(pipeline.QUICK_STYLES))

    def test_snapshot_canonicalizes_full_seat_routes_without_quality_input_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_route_assets_") as asset_dir_value:
            asset_dir = Path(asset_dir_value)
            reference = asset_dir / "style_reference.png"
            required = asset_dir / "required_asset.png"
            page_asset = asset_dir / "page_asset.png"
            write_png(reference, color=bytes((220, 230, 240)))
            write_png(required, color=bytes((210, 220, 230)))
            write_png(page_asset, color=bytes((200, 210, 220)))
            all_styles = list(pipeline.QUICK_STYLES)
            reference_item = {
                "path": str(reference.resolve()),
                "role": "primary_style_reference",
                "reference_intent": {
                    "borrow": ["成熟工业编辑感"],
                    "do_not_copy": ["具体构图"],
                },
                "style_slots": all_styles,
                "tones": ["dark", "light"],
            }
            required_item = {
                "path": str(required.resolve()),
                "role": "project_visual_evidence",
                "requirements": "保持事实关系",
                "style_slots": all_styles,
                "tones": ["dark", "light"],
            }
            content = pipeline.read_json(self.content_path)
            content["required_page_assets"] = [
                {
                    "path": str(page_asset.resolve()),
                    "role": "required_page_assets",
                    "requirements": "必须出现",
                    "style_slots": all_styles,
                    "tones": ["dark", "light"],
                }
            ]
            write_json(self.content_path, content)

            with tempfile.TemporaryDirectory(prefix="fast8_route_baseline_") as clone_value:
                clone_root = Path(clone_value)
                shutil.copytree(self.root, clone_root, dirs_exist_ok=True)
                task_init = pipeline.read_json(clone_root / "state" / "task_init.json")
                task_init["project_dir"] = str(clone_root.resolve())
                write_json(clone_root / "state" / "task_init.json", task_init)
                clone_content_path = clone_root / "content_contracts" / "page_02.json"
                clone_content = pipeline.read_json(clone_content_path)
                for item in clone_content["required_page_assets"]:
                    item.pop("style_slots", None)
                    item.pop("tones", None)
                write_json(clone_content_path, clone_content)

                self.prepare_root_with_assets(
                    self.root,
                    reference_images=[reference_item],
                    required_assets=[required_item],
                )
                self.prepare_root_with_assets(
                    clone_root,
                    reference_images=[
                        {
                            key: value
                            for key, value in reference_item.items()
                            if key not in {"style_slots", "tones"}
                        }
                    ],
                    required_assets=[
                        {
                            key: value
                            for key, value in required_item.items()
                            if key not in {"style_slots", "tones"}
                        }
                    ],
                )

                snapshot = pipeline.read_json(
                    self.root / "state" / "source_snapshot.json"
                )
                assets_by_path = {item["path"]: item for item in snapshot["assets"]}
                for path in (reference, required, page_asset):
                    record = assets_by_path[str(path.resolve())]
                    self.assertEqual(record["used_by"], all_styles)
                    self.assertNotIn("style_slots", record)
                    self.assertNotIn("styles", record)

                quality_fields = (
                    "imagegen_prompt",
                    "imagegen_prompt_fingerprint",
                    "imagegen_referenced_paths",
                    "imagegen_input_fingerprint",
                )
                for style in pipeline.QUICK_STYLES:
                    routed_job = pipeline.read_json(
                        self.root / "style_jobs" / f"style_{style}.json"
                    )
                    baseline_job = pipeline.read_json(
                        clone_root / "style_jobs" / f"style_{style}.json"
                    )
                    for field in quality_fields:
                        self.assertEqual(
                            routed_job[field],
                            baseline_job[field],
                            f"style {style} changed {field}",
                        )

    def test_snapshot_records_only_subset_and_tone_eligible_styles(self) -> None:
        asset = self.root / "fixtures" / "dark_subset.png"
        write_png(asset, color=bytes((190, 200, 210)))
        routed_styles = ["A", "B", "C", "D"]
        state = pipeline.read_json(self.state_path)
        tones = pipeline.tones_for_run(
            state, pipeline.FAST8_MODE, list(pipeline.QUICK_STYLES)
        )
        expected = sorted(
            style for style in routed_styles if tones[style] == "dark"
        )
        self.prepare_root_with_assets(
            self.root,
            reference_images=[],
            required_assets=[
                {
                    "path": str(asset.resolve()),
                    "role": "project_visual_evidence",
                    "style_slots": routed_styles,
                    "tones": ["dark"],
                }
            ],
        )
        snapshot = pipeline.read_json(self.root / "state" / "source_snapshot.json")
        record = next(
            item for item in snapshot["assets"] if item["path"] == str(asset.resolve())
        )
        self.assertEqual(record["used_by"], expected)
        self.assertNotIn("style_slots", record)
        self.assertNotIn("styles", record)
        for style in pipeline.QUICK_STYLES:
            job = pipeline.read_json(self.root / "style_jobs" / f"style_{style}.json")
            self.assertEqual(
                str(asset.resolve()) in job["imagegen_referenced_paths"],
                style in expected,
            )

    def test_true_route_alias_conflicts_stop_before_jobs_or_runtime_artifacts(
        self,
    ) -> None:
        asset = self.root / "fixtures" / "conflicting_route.png"
        write_png(asset)
        conflicts = (
            {"style_slots": ["A"], "styles": ["B"]},
            {"style_slots": ["A"], "used_by": ["B"]},
        )
        for conflict in conflicts:
            with self.subTest(conflict=conflict):
                with self.assertRaisesRegex(SystemExit, "路由字段冲突"):
                    self.prepare_root_with_assets(
                        self.root,
                        reference_images=[],
                        required_assets=[
                            {
                                "path": str(asset.resolve()),
                                "role": "project_visual_evidence",
                                **conflict,
                            }
                        ],
                    )
                self.assertEqual(
                    list((self.root / "style_jobs").glob("style_?.json")), []
                )
                state = pipeline.read_json(self.state_path)
                self.assertEqual(state["scheduler"]["active_actions"], [])
                self.assertEqual(state["scheduler"]["ready_queue"], [])
                self.assertFalse((self.root / "state" / "source_snapshot.json").exists())
                self.assertEqual(list(self.root.rglob("*receipt*.json")), [])
                self.assertEqual(list(self.root.rglob("*claim*.json")), [])
                origin = self.root / "origin_image"
                self.assertFalse(origin.exists() and any(origin.iterdir()))

    def test_project_evidence_asset_is_not_treated_as_style_or_must_copy_art(self) -> None:
        self.prepare()
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        job["required_assets"] = [
            {
                "path": str((self.root / "fixtures" / "source_slide.png").resolve()),
                "role": "project_visual_evidence：保留事实关系，不复制旧页构图",
            }
        ]
        prompt = pipeline.compile_minimal_prompt_v4(job)
        self.assertIn("明确要求保留的事实、品牌、对象与关系优先", prompt)
        self.assertIn("不把证据页当作风格模板", prompt)
        self.assertNotIn("风格参考（附件", prompt)
        self.assertNotIn("按角色原样使用", prompt)

    def test_render_asset_use_is_compiled_and_checked_by_final_judge(self) -> None:
        asset = self.root / "fixtures" / "building_logo.png"
        write_png(asset, color=bytes((245, 245, 245)))
        use = "仅当画出完整 E-House 时，将该官方 Logo 原样放在建筑外壳上。"
        self.prepare_root_with_assets(
            self.root,
            reference_images=[],
            required_assets=[
                {
                    "path": str(asset.resolve()),
                    "role": "render_asset",
                    "use": use,
                }
            ],
        )
        style_job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        self.assertIn("附件1=render_asset", style_job["imagegen_prompt"])
        self.assertIn("用途：" + use, style_job["imagegen_prompt"])

        self.settle_initials()
        review_job_path, _ = self.make_review(8)
        review_job = pipeline.read_json(review_job_path)
        usage_check = review_job["integrated_required_asset_usage_check"]
        self.assertEqual(len(usage_check["candidates"]), 8)
        self.assertEqual(usage_check["candidates"][0]["items"][0]["use"], use)

        report_path = self.write_report(
            review_job_path,
            decision="pass",
            suffix="required_asset_usage_pass",
        )
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(review_job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:04:00+08:00",
        )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["required_asset_review"]["status"], "pass")

    def test_generation_job_rejects_more_than_five_image_inputs(self) -> None:
        self.prepare()
        job_path = self.root / "style_jobs" / "style_A.json"
        job = pipeline.read_json(job_path)
        paths = []
        for index in range(6):
            path = self.root / "fixtures" / f"input_{index}.png"
            write_png(path, color=bytes((220 - index, 230 - index, 240 - index)))
            paths.append(str(path.resolve()))
        normalized, manifest = pipeline.build_input_manifest(paths)
        job["imagegen_referenced_paths"] = normalized
        job["imagegen_input_manifest"] = manifest
        job["imagegen_input_fingerprint"] = pipeline.hashlib.sha256(
            json.dumps(
                {"prompt": job["imagegen_prompt"], "inputs": manifest},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        write_json(job_path, job)
        with self.assertRaisesRegex(SystemExit, "最多 5 个"):
            pipeline.validate_generation_job_inputs(
                job_path,
                internal_sources=set(),
            )

    def test_explicit_style_reference_is_accepted_without_no_reference_cue(self) -> None:
        reference = self.root / "fixtures" / "style_reference.png"
        write_png(reference)
        pipeline.create_source_snapshot(
            project_dir=self.root,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=["02"],
            content_contract_paths=[self.content_path],
            asset_items=[
                {
                    "path": str(reference.resolve()),
                    "asset_type": "reference_image",
                    "role": "primary_style_reference",
                    "styles": list(pipeline.QUICK_STYLES),
                }
            ],
            timestamp="2099-01-01T00:00:01+08:00",
        )
        self.call(
            pipeline.command_prepare_anchors,
            project_dir=str(self.root),
            state=str(self.state_path),
            content_contract=str(self.content_path),
            overall_requirements="扩大探索",
            reference_images_json=json.dumps(
                [
                    {
                        "path": str(reference.resolve()),
                        "role": "primary_style_reference",
                        "reference_intent": {
                            "borrow": ["成熟的编辑感与精细图像工艺"],
                            "do_not_copy": ["具体构图"],
                        },
                    }
                ]
            ),
            required_assets_json="[]",
            layout_portfolio=str(self.portfolio_path),
            source_file=None,
            source_page_ids=None,
            source_fragment_file=None,
            snapshot_content_contracts_json=None,
            source_snapshot_timestamp=None,
        )
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        self.assertIn("风格参考（附件1）", job["imagegen_prompt"])
        self.assertNotIn("没有风格参考图时", job["imagegen_prompt"])
        self.assertEqual(job["imagegen_referenced_paths"], [str(reference.resolve())])

    def test_legacy_fast8_policy_still_prepares_v1_diversity_job(self) -> None:
        self.prepare()
        self.settle_initials()
        state = pipeline.read_json(self.state_path)
        state["fast8_candidate_policy"]["version"] = 1
        state["diversity_review"]["contract_version"] = 1
        state["diversity_review"]["scope"] = "diversity_only"
        state["diversity_review"][
            "replacement_recheck_policy"
        ] = "delta_collision_group_first"
        write_json(self.state_path, state)
        job_path, _ = self.make_review(8)
        job = pipeline.read_json(job_path)
        self.assertEqual(job["diversity_judge_contract_version"], 1)
        self.assertEqual(job["scope"], "diversity_only")
        self.assertNotIn("allowed_craft_red_flag_types", job)

    def test_v2_review_job_has_hash_bound_contact_sheet_and_fast_policy(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        job = pipeline.read_json(job_path)
        review_input = job["review_input"]
        contact_sheet = Path(review_input["path"])
        self.assertTrue(contact_sheet.is_file())
        self.assertEqual(
            pipeline.file_sha256(contact_sheet), review_input["sha256"]
        )
        self.assertEqual(review_input["candidate_set_sha256"], job["candidate_set_sha256"])
        self.assertEqual(review_input["styles"], list(pipeline.QUICK_STYLES))
        self.assertEqual(
            job["review_execution_policy"]["preferred_model"],
            "gpt-5.6-terra",
        )
        self.assertEqual(job["review_execution_policy"]["reasoning_effort"], "low")
        self.assertEqual(job["review_execution_policy"]["fork_turns"], "none")
        self.assertEqual(job["review_execution_policy"]["max_primary_view_calls"], 1)
        self.assertEqual(job["review_execution_policy"]["soft_timeout_seconds"], 180)
        self.assertEqual(job["review_execution_policy"]["retry_limit"], 0)
        self.assertEqual(
            job["review_execution_policy"]["timeout_recovery"],
            "same_session_report_only",
        )
        self.assertEqual(
            job["review_execution_policy"]["output_only_grace_seconds"], 45
        )
        self.assertEqual(job["report_constraints"]["summary_max_characters"], 300)
        self.assertEqual(
            sorted(job["report_template"]),
            job["report_constraints"]["exact_top_level_keys"],
        )
        self.assertIsNone(job["report_template"]["decision"])
        self.assertEqual(
            job["report_template"]["candidate_set_sha256"],
            job["candidate_set_sha256"],
        )
        _, checked = self.call(
            pipeline.command_check_fast8_judge_job,
            state=str(self.state_path),
            review_job=str(job_path),
        )
        assert checked
        self.assertEqual(checked["status"], "pass")
        self.assertEqual(
            checked["review_job_sha256"], pipeline.file_sha256(job_path)
        )
        self.assertEqual(
            checked["report_template"]["review_job_sha256"],
            pipeline.file_sha256(job_path),
        )
        self.assertEqual(
            checked["report_output_path"], job["report_output_path"]
        )
        self.assertIn("attention_competition", job["decision_rules"]["compare_axes"])
        self.assertIn(
            "dominant_layout_topology", job["decision_rules"]["compare_axes"]
        )
        self.assertTrue(
            job["decision_rules"][
                "shared_page_wide_skeleton_requires_authorization_check"
            ]
        )
        self.assertTrue(
            job["decision_rules"]["authorized_shared_structure_is_not_collision"]
        )
        self.assertTrue(
            job["decision_rules"][
                "repeated_hero_bottom_band_is_collision_when_same_reading_path"
            ]
        )
        self.assertEqual(
            job["diversity_constraint_context"]["prompt_user_constraints"], []
        )
        self.assertEqual(
            job["diversity_constraint_context"]["relationship_thesis"],
            "两项能力不是并列清单，而是共同收束到同一个目标结果。",
        )
        self.assertIn(
            "authorize presence only",
            job["diversity_constraint_context"]["asset_authorization_scope"],
        )
        self.assertIn(
            "competing_first_level_zones", job["allowed_craft_red_flag_types"]
        )
        self.assertIn(
            "explanatory_module_overload", job["allowed_craft_red_flag_types"]
        )
        self.assertTrue(
            job["decision_rules"][
                "severe_crowding_requires_two_observable_issue_types"
            ]
        )

    def test_settle_wave_accepts_utc_z_timestamps(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T02:00:00Z",
            agent_map_json=None,
            backpressure_reason="test_partial_wave",
        )
        result = self.result("A")
        result.update(
            {
                "agent_action_started_at": "2026-08-03T02:00:01Z",
                "tool_started_at": "2026-08-03T02:00:10Z",
                "tool_finished_at": "2026-08-03T02:00:40Z",
                "agent_action_finished_at": "2026-08-03T02:01:00Z",
            }
        )
        results_path = self.root / "style_jobs" / "results" / "z_timestamp.json"
        write_json(results_path, [result])
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(results_path),
            expected_styles="A",
            timestamp="2026-08-03T02:02:00Z",
        )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(
            state["styles"]["A"]["pages"]["02"]["selected_source"],
            str(self.initial_paths["A"].resolve()),
        )

    def test_startup_fast8_requires_unique_predeclared_worker_identities(self) -> None:
        self.prepare()
        state = pipeline.read_json(self.state_path)
        state["fast8_startup_contract_version"] = 1
        write_json(self.state_path, state)
        with self.assertRaisesRegex(SystemExit, "agent-map-json"):
            self.call(
                pipeline.command_record_dispatch_wave,
                state=str(self.state_path),
                styles="A,B",
                tasks_json=None,
                page_id=None,
                action="generate_anchor",
                attempt=1,
                timestamp="2026-08-03T10:00:00+08:00",
                agent_map_json=None,
                backpressure_reason="test_partial_wave",
            )
        with self.assertRaisesRegex(SystemExit, "必须逐任务唯一"):
            self.call(
                pipeline.command_record_dispatch_wave,
                state=str(self.state_path),
                styles="A,B",
                tasks_json=None,
                page_id=None,
                action="generate_anchor",
                attempt=1,
                timestamp="2026-08-03T10:00:00+08:00",
                agent_map_json=json.dumps({"A": "same-worker", "B": "same-worker"}),
                backpressure_reason="test_partial_wave",
            )

    def test_fast8_worker_receipt_avoids_recovery_when_final_json_lacks_path(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "agent-A"}),
            backpressure_reason="test_partial_wave",
        )
        job_path = self.root / "style_jobs" / "style_A.json"
        job = pipeline.read_json(job_path)
        receipt_path = Path(job["worker_receipt"]["path"])
        write_json(
            receipt_path,
            {
                "worker_receipt_contract_version": 1,
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "worker_agent_id": "agent-A",
                "tool_call_id": "tool-A-1",
                "savedPath": str(self.initial_paths["A"]),
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
                "receipt_written_at": "2026-08-03T10:01:00+08:00",
                "error": None,
                "contains_image_payload": False,
            },
        )
        result_path = self.root / "style_jobs" / "results" / "missing_path.json"
        write_json(
            result_path,
            [
                {
                    "style": "A",
                    "page_id": "02",
                    "action": "generate_anchor",
                    "attempt": 1,
                    "savedPath": None,
                    "error": "artifact_handoff_unresolved",
                }
            ],
        )
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(result_path),
            expected_styles="A",
            timestamp="2026-08-03T10:02:00+08:00",
        )
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["selected_source"], str(self.initial_paths["A"].resolve()))
        self.assertEqual(record["artifact_binding_source"], "worker_receipt")
        self.assertFalse(record["recovery_required"])

    def test_receipt_watcher_extracts_exec_png_from_explanatory_output_hint(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "fast8-page02-A"}),
            backpressure_reason="test_partial_wave",
        )
        generated_root = self.root / ".codex" / "generated_images"
        generated = (
            generated_root
            / "thread-01"
            / "exec-12345678-1234-1234-1234-123456789abc.png"
        )
        write_png(generated)
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        output_hint = (
            f"Generated images are saved to {generated.parent} as {generated} by default.\n"
            "Use the saved image for the requested deliverable."
        )
        write_json(
            Path(job["worker_receipt"]["path"]),
            {
                "worker_receipt_contract_version": 1,
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "worker_agent_id": None,
                "tool_call_id": output_hint,
                "savedPath": output_hint,
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
                "receipt_written_at": "2026-08-03T10:01:00+08:00",
                "error": None,
                "contains_image_payload": False,
            },
        )
        with mock.patch.object(pipeline, "GENERATED_IMAGES_ROOT", generated_root.resolve()):
            self.call(
                pipeline.command_settle_fast8_receipts,
                state=str(self.state_path),
                styles="A",
                wait_seconds=0,
                poll_interval=0.2,
                timestamp="2026-08-03T10:01:01+08:00",
            )
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["selected_source"], str(generated.resolve()))
        self.assertEqual(
            record["tool_call_id"],
            "exec-12345678-1234-1234-1234-123456789abc",
        )
        self.assertEqual(record["worker_agent_id"], "fast8-page02-A")
        self.assertFalse(record["recovery_required"])

    def test_dispatch_ticket_eliminates_natural_language_job_sha_copy(self) -> None:
        self.prepare()
        _, dispatch = self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "stable-task-A"}),
            backpressure_reason="test_partial_wave",
        )
        assert dispatch
        ticket_path = Path(dispatch["tasks"][0]["worker_ticket_path"])
        self.assertTrue(ticket_path.is_file())
        with self.assertRaisesRegex(SystemExit, "worker_session_binding_required"):
            self.call(
                pipeline.command_check_fast8_worker_ticket,
                state=str(self.state_path),
                ticket=str(ticket_path),
                wait_for_session_seconds=0,
                poll_interval=0.2,
            )
        worker_uuid = "019fcc95-aaaa-bbbb-cccc-123456789abc"
        with self.assertRaisesRegex(SystemExit, "运行时不符合正式合同"):
            self.call(
                pipeline.command_bind_fast8_worker_sessions,
                state=str(self.state_path),
                session_map_json=json.dumps({"A": worker_uuid}),
                styles="A",
                model="gpt-5.6-sol",
                reasoning_effort="high",
                fork_turns="none",
                timestamp="2026-08-03T10:00:01+08:00",
            )
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps({"A": worker_uuid}),
            styles="A",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:00:01+08:00",
        )
        _, checked = self.call(
            pipeline.command_check_fast8_worker_ticket,
            state=str(self.state_path),
            ticket=str(ticket_path),
            wait_for_session_seconds=0,
            poll_interval=0.2,
        )
        assert checked
        self.assertEqual(checked["status"], "pass")
        self.assertEqual(
            checked["generation_job_sha256"],
            pipeline.file_sha256(self.root / "style_jobs" / "style_A.json"),
        )
        self.assertEqual(checked["worker_session_id"], worker_uuid)
        self.assertEqual(
            checked["worker_runtime_contract"]["required_model"],
            "gpt-5.6-terra",
        )
        self.assertEqual(
            checked["worker_receipt_template"]["imagegen_input_fingerprint"],
            checked["imagegen_input_fingerprint"],
        )
        self.assertIsNone(checked["worker_receipt_template"]["savedPath"])

    def test_script_writes_atomic_canonical_fast8_worker_receipt(self) -> None:
        self.prepare()
        _, dispatch = self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "stable-task-A"}),
            backpressure_reason="test_partial_wave",
        )
        assert dispatch
        ticket_path = Path(dispatch["tasks"][0]["worker_ticket_path"])
        worker_uuid = "019fcc95-aaaa-bbbb-cccc-123456789abc"
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps({"A": worker_uuid}),
            styles="A",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:00:01+08:00",
        )
        generated_root = self.root / ".codex" / "generated_images"
        generated = (
            generated_root
            / worker_uuid
            / "exec-12345678-1234-1234-1234-123456789abc.png"
        )
        write_png(generated)
        with mock.patch.object(
            pipeline, "GENERATED_IMAGES_ROOT", generated_root.resolve()
        ):
            _, receipt = self.call(
                pipeline.command_write_fast8_worker_receipt,
                state=str(self.state_path),
                ticket=str(ticket_path),
                tool_status="completed",
                saved_path=(
                    f"Generated images are saved to {generated.parent} as {generated}"
                ),
                tool_call_id=None,
                tool_started_at="2026-08-03T10:00:10+0800",
                tool_finished_at="2026-08-03T10:00:40+0800",
                failure_class=None,
                tool_error_code=None,
                error=None,
                timestamp="2026-08-03T10:00:41+0800",
            )
        assert receipt
        receipt_path = Path(dispatch["tasks"][0]["worker_receipt_path"])
        saved = pipeline.read_json(receipt_path)
        self.assertEqual(saved, receipt)
        self.assertLess(receipt_path.stat().st_size, 2048)
        self.assertEqual(len(saved), 17)
        self.assertEqual(saved["worker_agent_id"], worker_uuid)
        self.assertEqual(saved["savedPath"], str(generated.resolve()))
        self.assertEqual(
            saved["tool_call_id"],
            "exec-12345678-1234-1234-1234-123456789abc",
        )
        self.assertEqual(
            saved["tool_started_at"], "2026-08-03T10:00:10.000000+08:00"
        )
        self.assertEqual(
            saved["receipt_written_at"], "2026-08-03T10:00:41.000000+08:00"
        )

    def test_fast8_late_receipt_and_artifact_visibility_are_parallel(self) -> None:
        source = self.initial_paths["A"]
        record = {
            "status": "candidate_ready",
            "agent_action_started_at": "2026-08-03T10:00:00+08:00",
            "tool_started_at": "2026-08-03T10:00:10+08:00",
            "tool_finished_at": "2026-08-03T10:00:40+08:00",
            "file_validated_at": "2026-08-03T10:00:35+08:00",
            "agent_action_finished_at": "2026-08-03T10:00:50+08:00",
            "overview_qa_at": "2026-08-03T10:01:00+08:00",
            "completed_at": "2026-08-03T10:01:00+08:00",
            "tool_call_id": "exec-12345678-1234-1234-1234-123456789abc",
            "selected_source": str(source),
            "final_path": str(source),
            "attempt_sources": [str(source)],
            "attempt_count": 1,
            "artifact_binding_source": "worker_session_dir",
            "timing_capture": "worker_reported_late_receipt",
        }
        self.assertEqual(
            pipeline.completed_quick_candidate_errors(record, "style_A/02"), []
        )
        record["timing_capture"] = "worker_reported"
        errors = pipeline.completed_quick_candidate_errors(record, "style_A/02")
        self.assertTrue(any("时间倒序" in error for error in errors))

    def test_identical_formal_overview_retries_remain_append_only_and_valid(self) -> None:
        details = {
            "output_path": str(self.root / "overview" / "ABCDEFGH_2x4.png"),
            "candidate_count": 8,
            "layout": "2x4",
            "diversity_status": "pass",
        }
        state = {
            "events": [
                {
                    "sequence": 1,
                    "name": "formal_overview_completed",
                    "occurred_at": "2026-08-03T10:00:00+08:00",
                    "recorded_at": "2026-08-03T10:00:01+08:00",
                    "details": details,
                },
                {
                    "sequence": 2,
                    "name": "formal_overview_completed",
                    "occurred_at": "2026-08-03T10:01:00+08:00",
                    "recorded_at": "2026-08-03T10:01:01+08:00",
                    "details": dict(details),
                },
            ],
            "timing": {
                "formal_overview_completed_at": "2026-08-03T10:01:00+08:00"
            },
        }
        errors: list[str] = []
        pipeline.validate_event_audit_v2(state, errors, complete=False)
        self.assertEqual(errors, [])

        state["events"][1]["details"] = {**details, "candidate_count": 7}
        errors = []
        pipeline.validate_event_audit_v2(state, errors, complete=False)
        self.assertTrue(any("不得重复" in error for error in errors))

    def test_worker_runtime_metadata_does_not_change_imagegen_quality_input(
        self,
    ) -> None:
        self.prepare()
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        without_runtime = json.loads(json.dumps(job))
        without_runtime.pop("worker_runtime_contract", None)
        self.assertEqual(
            pipeline.compile_anchor_imagegen_prompt(without_runtime),
            job["imagegen_prompt"],
        )
        self.assertEqual(
            hashlib.sha256(job["imagegen_prompt"].encode("utf-8")).hexdigest(),
            job["imagegen_prompt_fingerprint"],
        )
        expected_input_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "prompt": job["imagegen_prompt"],
                    "inputs": job["imagegen_input_manifest"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            expected_input_fingerprint,
            job["imagegen_input_fingerprint"],
        )

    def test_legacy_worker_ticket_v1_still_binds_without_runtime_upgrade(
        self,
    ) -> None:
        self.prepare()
        job_path = self.root / "style_jobs" / "style_A.json"
        job = pipeline.read_json(job_path)
        job.pop("worker_runtime_contract", None)
        pipeline.atomic_write_json(job_path, job)
        state = pipeline.read_json(self.state_path)
        for item in state["scheduler"]["ready_queue"]:
            if item.get("style") == "A":
                item["generation_job_sha256"] = pipeline.file_sha256(job_path)
        pipeline.atomic_write_json(self.state_path, state)
        _, dispatch = self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "legacy-task-A"}),
            backpressure_reason="legacy_ticket_compatibility",
        )
        assert dispatch
        ticket_path = Path(dispatch["tasks"][0]["worker_ticket_path"])
        ticket = pipeline.read_json(ticket_path)
        self.assertEqual(ticket["fast8_worker_ticket_contract_version"], 1)
        self.assertNotIn("worker_runtime_contract", ticket)

        worker_uuid = "019fcc95-ffff-eeee-dddd-123456789abc"
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps({"A": worker_uuid}),
            styles="A",
            timestamp="2026-08-03T10:00:01+08:00",
        )
        _, checked = self.call(
            pipeline.command_check_fast8_worker_ticket,
            state=str(self.state_path),
            ticket=str(ticket_path),
            wait_for_session_seconds=0,
            poll_interval=0.2,
        )
        assert checked
        self.assertEqual(checked["status"], "pass")
        self.assertIsNone(checked["worker_runtime_contract"])

    def test_technical_retry_uses_attempt_specific_worker_receipt(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "attempt-one-A"}),
            backpressure_reason="test_partial_wave",
        )
        state = pipeline.read_json(self.state_path)
        active_a = state["scheduler"]["active_actions"][0]
        state["scheduler"]["active_actions"] = []
        state["scheduler"]["ready_queue"].append(
            {
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 2,
                "technical_retry": True,
                "retry_reason": "test_retry",
                "generation_job_path": active_a["generation_job_path"],
                "generation_job_sha256": active_a["generation_job_sha256"],
            }
        )
        write_json(self.state_path, state)
        _, retry = self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles=None,
            tasks_json=json.dumps(
                [
                    {
                        "style": "A",
                        "page_id": "02",
                        "action": "generate_anchor",
                        "attempt": 2,
                    }
                ]
            ),
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:02:00+08:00",
            agent_map_json=json.dumps({"A/02/generate_anchor/2": "attempt-two-A"}),
            backpressure_reason="test_retry_only",
        )
        assert retry
        ticket_path = Path(retry["tasks"][0]["worker_ticket_path"])
        ticket = pipeline.read_json(ticket_path)
        retry_receipt_path = Path(ticket["worker_receipt_path"])
        initial_job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        initial_receipt_path = Path(initial_job["worker_receipt"]["path"])
        self.assertNotEqual(retry_receipt_path, initial_receipt_path)
        self.assertIn("attempt_2", retry_receipt_path.name)
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps(
                {"A": "019fcc95-bbbb-cccc-dddd-123456789abc"}
            ),
            styles="A",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:02:01+08:00",
        )
        _, checked = self.call(
            pipeline.command_check_fast8_worker_ticket,
            state=str(self.state_path),
            ticket=str(ticket_path),
            wait_for_session_seconds=0,
            poll_interval=0.2,
        )
        assert checked
        self.assertEqual(checked["worker_receipt_path"], str(retry_receipt_path))
        write_json(
            retry_receipt_path,
            {
                "worker_receipt_contract_version": 1,
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 2,
                "imagegen_input_fingerprint": initial_job[
                    "imagegen_input_fingerprint"
                ],
                "worker_agent_id": "attempt-two-A",
                "tool_call_id": "tool-A-2",
                "savedPath": str(self.initial_paths["A"]),
                "tool_started_at": "2026-08-03T10:02:10+08:00",
                "tool_finished_at": "2026-08-03T10:02:40+08:00",
                "receipt_written_at": "2026-08-03T10:02:41+08:00",
                "error": None,
                "contains_image_payload": False,
            },
        )
        self.call(
            pipeline.command_settle_fast8_receipts,
            state=str(self.state_path),
            styles="A",
            wait_seconds=0,
            poll_interval=0.2,
            timestamp="2026-08-03T10:02:42+08:00",
        )
        final_state = pipeline.read_json(self.state_path)
        record = final_state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["attempt_count"], 2)
        self.assertEqual(record["selected_source"], str(self.initial_paths["A"].resolve()))
        self.assertFalse(initial_receipt_path.exists())

    def test_bound_worker_session_dir_settles_unresolved_receipt_without_recovery(
        self,
    ) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "stable-task-A"}),
            backpressure_reason="test_partial_wave",
        )
        session_id = "019fcc95-aaaa-bbbb-cccc-123456789abc"
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps({"A": session_id}),
            styles="A",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:00:01+08:00",
        )
        generated_root = self.root / ".codex" / "generated_images"
        generated = (
            generated_root
            / session_id
            / "exec-12345678-1234-1234-1234-123456789abc.png"
        )
        write_png(generated)
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        write_json(
            Path(job["worker_receipt"]["path"]),
            {
                "worker_receipt_contract_version": 1,
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "worker_agent_id": "/root/stable-task-A",
                "tool_call_id": None,
                "savedPath": None,
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
                "receipt_written_at": "2026-08-03T10:00:41+08:00",
                "error": "artifact_handoff_unresolved",
                "contains_image_payload": False,
            },
        )
        with mock.patch.object(
            pipeline, "GENERATED_IMAGES_ROOT", generated_root.resolve()
        ):
            self.call(
                pipeline.command_settle_fast8_receipts,
                state=str(self.state_path),
                styles="A",
                wait_seconds=0,
                poll_interval=0.2,
                timestamp="2026-08-03T10:00:42+08:00",
            )
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["selected_source"], str(generated.resolve()))
        self.assertEqual(record["artifact_binding_source"], "worker_session_dir")
        self.assertEqual(record["worker_agent_id"], session_id)
        self.assertFalse(record["recovery_required"])
        self.assertEqual(state["scheduler"]["recovery_queue"], [])

    def test_bound_worker_session_dir_settles_before_receipt_exists(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "stable-task-A"}),
            backpressure_reason="test_partial_wave",
        )
        session_id = "019fcc95-abcd-abcd-abcd-123456789abc"
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps({"A": session_id}),
            styles="A",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:00:01+08:00",
        )
        generated_root = self.root / ".codex" / "generated_images"
        generated = (
            generated_root
            / session_id
            / "exec-12345678-1234-1234-1234-123456789abc.png"
        )
        write_png(generated)
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        self.assertFalse(Path(job["worker_receipt"]["path"]).exists())
        with mock.patch.object(
            pipeline, "GENERATED_IMAGES_ROOT", generated_root.resolve()
        ):
            _, output = self.call(
                pipeline.command_settle_fast8_receipts,
                state=str(self.state_path),
                styles="A",
                wait_seconds=0,
                poll_interval=0.2,
                timestamp="2026-08-03T10:00:42+08:00",
            )
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(output["candidate_bound_styles"], ["A"])
        self.assertEqual(record["selected_source"], str(generated.resolve()))
        self.assertEqual(record["artifact_binding_source"], "worker_session_dir")
        self.assertEqual(
            record["timing_capture"], "controller_session_artifact_without_receipt"
        )
        self.assertEqual(state["scheduler"]["recovery_queue"], [])

        write_json(
            Path(job["worker_receipt"]["path"]),
            {
                "worker_receipt_contract_version": 1,
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "worker_agent_id": session_id,
                "tool_call_id": "exec-12345678-1234-1234-1234-123456789abc",
                "savedPath": str(generated.resolve()),
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
                "receipt_written_at": "2026-08-03T10:00:41+08:00",
                "tool_status": "completed",
                "failure_class": None,
                "tool_error_code": None,
                "error": None,
                "contains_image_payload": False,
            },
        )
        refreshed = pipeline.read_json(self.state_path)
        reconciled = pipeline.reconcile_fast8_late_worker_receipts(
            self.state_path, refreshed
        )
        self.assertEqual(reconciled, ["A"])
        refreshed = pipeline.read_json(self.state_path)
        record = refreshed["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["selected_source"], str(generated.resolve()))
        self.assertEqual(record["artifact_binding_source"], "worker_session_dir")
        self.assertEqual(record["tool_started_at"], "2026-08-03T10:00:10+08:00")
        self.assertEqual(record["tool_finished_at"], "2026-08-03T10:00:40+08:00")
        self.assertEqual(record["timing_capture"], "worker_reported_late_receipt")
        self.assertEqual(
            refreshed["events"][-1]["name"], "worker_receipt_reconciled"
        )

    def test_backend_failure_skips_artifact_recovery_and_queues_retry(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "stable-task-A"}),
            backpressure_reason="test_partial_wave",
        )
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        write_json(
            Path(job["worker_receipt"]["path"]),
            {
                "worker_receipt_contract_version": 1,
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "worker_agent_id": "stable-task-A",
                "tool_call_id": None,
                "savedPath": None,
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
                "receipt_written_at": "2026-08-03T10:00:41+08:00",
                "tool_status": "failed",
                "failure_class": "backend_network",
                "tool_error_code": "network_request_failed",
                "error": "imagegen_backend_failed",
                "contains_image_payload": False,
            },
        )
        _, output = self.call(
            pipeline.command_settle_fast8_receipts,
            state=str(self.state_path),
            styles="A",
            wait_seconds=0,
            poll_interval=0.2,
            timestamp="2026-08-03T10:00:42+08:00",
        )
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(output["retry_pending_styles"], ["A"])
        self.assertEqual(state["scheduler"]["recovery_queue"], [])
        retry = next(
            item
            for item in state["scheduler"]["ready_queue"]
            if item.get("style") == "A" and item.get("technical_retry") is True
        )
        self.assertEqual(retry["attempt"], 2)
        self.assertEqual(record["status"], "retry_pending")
        self.assertEqual(record["attempt_history"][-1]["outcome"], "imagegen_backend_failed")
        health = pipeline.build_run_health_report(
            state_path=self.state_path,
            state=state,
            timestamp="2026-08-03T10:00:43+08:00",
        )
        self.assertNotIn(
            "worker_receipt_invalid",
            {item["code"] for item in health["findings"]},
        )
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=2,
            timestamp="2026-08-03T10:02:00+08:00",
            agent_map_json=json.dumps({"A": "stable-task-A-retry"}),
            backpressure_reason="test_retry_only",
        )
        retry_result_path = self.root / "style_jobs" / "results" / "retry_ok.json"
        retry_result = self.result("A", attempt=2, minute=2)
        retry_result["worker_agent_id"] = "stable-task-A-retry"
        write_json(
            retry_result_path,
            [retry_result],
        )
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(retry_result_path),
            expected_styles="A",
            timestamp="2026-08-03T10:03:00+08:00",
        )
        retried = pipeline.read_json(self.state_path)["styles"]["A"]["pages"]["02"]
        self.assertEqual(retried["selected_attempt"], 2)
        self.assertEqual(retried["tool_started_at"], "2026-08-03T10:02:10+08:00")
        self.assertEqual(retried["tool_finished_at"], "2026-08-03T10:02:40+08:00")
        self.assertIsNone(retried["failure_reason"])

    def test_terminal_empty_rpc_queues_retry_without_waiting_for_worker_receipt(
        self,
    ) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "stable-task-A"}),
            backpressure_reason="test_terminal_empty_rpc",
        )
        session_id = "019fcc95-feed-beef-cafe-123456789abc"
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps({"A": session_id}),
            styles="A",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:00:01+08:00",
        )
        state = pipeline.read_json(self.state_path)
        active = state["scheduler"]["active_actions"][0]
        telemetry_path = pipeline.fast8_imagegen_slot_telemetry_path(
            self.state_path, state, active
        )
        write_json(
            telemetry_path,
            {
                "imagegen_slot_telemetry_version": 1,
                "run_id": state["run_id"],
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "worker_session_id": session_id,
                "worker_ticket_sha256": active["worker_ticket_sha256"],
                "status": "released",
                "acquired_at": "2026-08-03T10:00:10+08:00",
                "released_at": "2026-08-03T10:00:11+08:00",
                "rpc_terminal": True,
            },
        )
        generated_root = self.root / ".codex" / "generated_images"
        with mock.patch.object(
            pipeline, "GENERATED_IMAGES_ROOT", generated_root.resolve()
        ):
            _, output = self.call(
                pipeline.command_settle_fast8_receipts,
                state=str(self.state_path),
                styles="A",
                wait_seconds=0,
                poll_interval=0.2,
                timestamp="2026-08-03T10:00:20+08:00",
            )
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(output["retry_pending_styles"], ["A"])
        self.assertEqual(state["scheduler"]["recovery_queue"], [])
        self.assertEqual(record["status"], "retry_pending")
        self.assertEqual(
            record["attempt_history"][-1]["outcome"],
            "imagegen_backend_failed",
        )
        self.assertEqual(
            record["attempt_history"][-1]["tool_finished_at"],
            "2026-08-03T10:00:11+08:00",
        )

    def test_terminal_empty_rpc_respects_artifact_grace_period(self) -> None:
        self.prepare()
        current = pipeline.now_iso()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp=current,
            agent_map_json=json.dumps({"A": "stable-task-A"}),
            backpressure_reason="test_terminal_empty_rpc_grace",
        )
        session_id = "019fcc95-face-cafe-beef-123456789abc"
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps({"A": session_id}),
            styles="A",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp=current,
        )
        state = pipeline.read_json(self.state_path)
        active = state["scheduler"]["active_actions"][0]
        telemetry_path = pipeline.fast8_imagegen_slot_telemetry_path(
            self.state_path, state, active
        )
        write_json(
            telemetry_path,
            {
                "imagegen_slot_telemetry_version": 1,
                "run_id": state["run_id"],
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "worker_session_id": session_id,
                "worker_ticket_sha256": active["worker_ticket_sha256"],
                "status": "released",
                "acquired_at": current,
                "released_at": current,
                "rpc_terminal": True,
            },
        )
        generated_root = self.root / ".codex" / "generated_images"
        with mock.patch.object(
            pipeline, "GENERATED_IMAGES_ROOT", generated_root.resolve()
        ):
            _, output = self.call(
                pipeline.command_settle_fast8_receipts,
                state=str(self.state_path),
                styles="A",
                wait_seconds=0,
                poll_interval=0.2,
                timestamp=current,
            )
        self.assertEqual(output["pending_receipt_styles"], ["A"])
        state = pipeline.read_json(self.state_path)
        self.assertNotEqual(
            state["styles"]["A"]["pages"]["02"]["status"], "retry_pending"
        )

    def test_missing_worker_session_blocks_false_artifact_recovery(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "stable-task-A"}),
            backpressure_reason="test_binding_gate",
        )
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        write_json(
            Path(job["worker_receipt"]["path"]),
            {
                "worker_receipt_contract_version": 1,
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "worker_agent_id": "stable-task-A",
                "tool_call_id": "tool-A-1",
                "savedPath": None,
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
                "receipt_written_at": "2026-08-03T10:00:41+08:00",
                "error": "artifact_handoff_unresolved",
                "contains_image_payload": False,
            },
        )
        _, output = self.call(
            pipeline.command_settle_fast8_receipts,
            state=str(self.state_path),
            styles="A",
            wait_seconds=60,
            poll_interval=2,
            timestamp="2026-08-03T10:00:42+08:00",
        )
        self.assertEqual(output["status"], "worker_session_binding_required")
        self.assertEqual(output["worker_session_binding_required_styles"], ["A"])
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["scheduler"]["recovery_queue"], [])
        self.assertEqual([item["style"] for item in state["scheduler"]["active_actions"]], ["A"])

    def test_global_imagegen_slots_are_shared_and_released(self) -> None:
        shared_root = self.root / "shared_monitoring"
        state_a = {"run_id": "run-a", "monitoring": {"root": str(shared_root)}}
        state_b = {"run_id": "run-b", "monitoring": {"root": str(shared_root)}}
        state_path_a = self.root / "a" / "state.json"
        state_path_b = self.root / "b" / "state.json"
        tasks = [
            {
                "style": style,
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
            }
            for style in pipeline.QUICK_STYLES
        ]
        acquired_a, deferred_a, leases_a, remaining_a = (
            pipeline.acquire_fast8_global_imagegen_slots(
                state_path_a, state_a, tasks, timestamp=pipeline.now_iso()
            )
        )
        self.assertEqual(len(acquired_a), 8)
        self.assertEqual(deferred_a, [])
        self.assertEqual(remaining_a, 0)
        acquired_b, deferred_b, _, remaining_b = (
            pipeline.acquire_fast8_global_imagegen_slots(
                state_path_b, state_b, tasks, timestamp=pipeline.now_iso()
            )
        )
        self.assertEqual(acquired_b, [])
        self.assertEqual(len(deferred_b), 8)
        self.assertEqual(remaining_b, 0)
        first_lease = next(iter(leases_a.values()))
        self.assertEqual(
            pipeline.release_fast8_global_imagegen_slots(
                state_path_a, state_a, [first_lease]
            ),
            1,
        )
        acquired_b, deferred_b, _, remaining_b = (
            pipeline.acquire_fast8_global_imagegen_slots(
                state_path_b, state_b, tasks, timestamp=pipeline.now_iso()
            )
        )
        self.assertEqual(len(acquired_b), 1)
        self.assertEqual(len(deferred_b), 7)
        self.assertEqual(remaining_b, 0)

    def test_record_dispatch_wave_rolls_all_tasks_when_global_slots_are_full(
        self,
    ) -> None:
        self.prepare()
        shared_root = self.root / "shared_monitoring"
        state = pipeline.read_json(self.state_path)
        state["monitoring"] = {"root": str(shared_root)}
        write_json(self.state_path, state)
        occupying_state = {
            "run_id": "other-run",
            "monitoring": {"root": str(shared_root)},
        }
        occupying_tasks = [
            {
                "style": style,
                "page_id": "99",
                "action": "generate_anchor",
                "attempt": 1,
            }
            for style in pipeline.QUICK_STYLES
        ]
        acquired, _, _, _ = pipeline.acquire_fast8_global_imagegen_slots(
            self.root / "other" / "state.json",
            occupying_state,
            occupying_tasks,
            timestamp=pipeline.now_iso(),
        )
        self.assertEqual(len(acquired), 8)
        _, output = self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A,B,C,D,E,F,G,H",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp=pipeline.now_iso(),
            agent_map_json=json.dumps(
                {style: f"worker-{style}" for style in pipeline.QUICK_STYLES}
            ),
            backpressure_reason=None,
        )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(output["started"], 0)
        self.assertEqual(output["global_imagegen_deferred"], 8)
        self.assertEqual(state["scheduler"]["active_actions"], [])
        self.assertEqual(len(state["scheduler"]["ready_queue"]), 8)
        self.assertEqual(
            state["scheduler"]["runtime_backpressure"][-1]["reason"],
            "global_imagegen_capacity",
        )

    def test_jit_dispatch_authorizes_all_workers_even_when_global_slots_are_full(
        self,
    ) -> None:
        self.prepare()
        shared_root = self.root / "shared_monitoring_jit"
        state = pipeline.read_json(self.state_path)
        state["monitoring"] = {"root": str(shared_root)}
        state["fast8_imagegen_slot_policy"] = (
            pipeline.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY
        )
        state["scheduler"]["imagegen_slot_policy"] = (
            pipeline.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY
        )
        write_json(self.state_path, state)
        occupying_state = {
            "run_id": "other-run",
            "monitoring": {"root": str(shared_root)},
        }
        occupying_tasks = [
            {
                "style": style,
                "page_id": "99",
                "action": "generate_anchor",
                "attempt": 1,
            }
            for style in pipeline.QUICK_STYLES
        ]
        pipeline.acquire_fast8_global_imagegen_slots(
            self.root / "other" / "state.json",
            occupying_state,
            occupying_tasks,
            timestamp=pipeline.now_iso(),
        )
        _, output = self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A,B,C,D,E,F,G,H",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp=pipeline.now_iso(),
            agent_map_json=json.dumps(
                {style: f"worker-{style}" for style in pipeline.QUICK_STYLES}
            ),
            backpressure_reason=None,
        )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(output["started"], 8)
        self.assertEqual(output["global_imagegen_deferred"], 0)
        self.assertEqual(
            output["imagegen_slot_policy"],
            pipeline.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY,
        )
        self.assertEqual(len(state["scheduler"]["active_actions"]), 8)
        self.assertEqual(state["scheduler"]["ready_queue"], [])
        self.assertTrue(
            all(
                "global_imagegen_lease_id" not in item
                for item in state["scheduler"]["active_actions"]
            )
        )

    def test_jit_slot_is_bound_to_ticket_session_and_released_idempotently(
        self,
    ) -> None:
        self.prepare()
        job_path = self.root / "style_jobs" / "style_A.json"
        original_job = pipeline.read_json(job_path)
        quality_inputs = {
            key: original_job.get(key)
            for key in (
                "imagegen_prompt",
                "imagegen_referenced_paths",
                "imagegen_prompt_fingerprint",
                "imagegen_input_fingerprint",
            )
        }
        state = pipeline.read_json(self.state_path)
        state["fast8_imagegen_slot_policy"] = (
            pipeline.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY
        )
        state["scheduler"]["imagegen_slot_policy"] = (
            pipeline.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY
        )
        write_json(self.state_path, state)
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "worker-A"}),
            backpressure_reason="test_single_seat",
        )
        session_id = "00000000-0000-4000-8000-000000000001"
        _, bound = self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps({"A": session_id}),
            styles="A",
            model=pipeline.FAST8_WORKER_REQUIRED_MODEL,
            reasoning_effort=pipeline.FAST8_WORKER_REQUIRED_REASONING,
            fork_turns=pipeline.FAST8_WORKER_REQUIRED_FORK_TURNS,
            timestamp="2026-08-03T10:00:01+08:00",
        )
        self.assertEqual(bound["bound"], 1)
        self.assertEqual(bound["authorization_to_batch_bound_seconds"], 1.0)
        state = pipeline.read_json(self.state_path)
        ticket_path = state["scheduler"]["active_actions"][0]["worker_ticket_path"]
        _, acquired = self.call(
            pipeline.command_acquire_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=ticket_path,
            wait_seconds=0,
            poll_interval=0.5,
        )
        self.assertEqual(acquired["status"], "acquired")
        self.assertEqual(acquired["worker_session_id"], session_id)
        _, released = self.call(
            pipeline.command_release_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=ticket_path,
            lease_id=acquired["lease_id"],
        )
        self.assertEqual(released["status"], "released")
        _, released_again = self.call(
            pipeline.command_release_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=ticket_path,
            lease_id=acquired["lease_id"],
        )
        self.assertEqual(released_again["status"], "already_released")
        final_job = pipeline.read_json(job_path)
        self.assertEqual(
            {
                key: final_job.get(key)
                for key in quality_inputs
            },
            quality_inputs,
        )

    def test_jit_stable_cap_queues_sixth_rpc_without_changing_quality_inputs(
        self,
    ) -> None:
        self.prepare()
        state = pipeline.read_json(self.state_path)
        state["fast8_imagegen_slot_policy"] = (
            pipeline.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY
        )
        state["scheduler"]["imagegen_slot_policy"] = (
            pipeline.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY
        )
        write_json(self.state_path, state)
        styles = "A,B,C,D,E,F"
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles=styles,
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps(
                {style: f"worker-{style}" for style in styles.split(",")}
            ),
            backpressure_reason="test_jit_stable_cap",
        )
        session_map = {
            style: f"00000000-0000-4000-8000-00000000000{index}"
            for index, style in enumerate(styles.split(","), start=1)
        }
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps(session_map),
            styles=styles,
            model=pipeline.FAST8_WORKER_REQUIRED_MODEL,
            reasoning_effort=pipeline.FAST8_WORKER_REQUIRED_REASONING,
            fork_turns=pipeline.FAST8_WORKER_REQUIRED_FORK_TURNS,
            timestamp="2026-08-03T10:00:01+08:00",
        )
        state = pipeline.read_json(self.state_path)
        tickets = {
            item["style"]: item["worker_ticket_path"]
            for item in state["scheduler"]["active_actions"]
        }
        original_f = pipeline.read_json(self.root / "style_jobs" / "style_F.json")
        quality_keys = (
            "imagegen_prompt",
            "imagegen_referenced_paths",
            "imagegen_prompt_fingerprint",
            "imagegen_input_fingerprint",
        )
        original_quality = {key: original_f.get(key) for key in quality_keys}
        acquired = {}
        for style in "ABCDE":
            _, result = self.call(
                pipeline.command_acquire_fast8_imagegen_slot,
                state=str(self.state_path),
                ticket=tickets[style],
                wait_seconds=0,
                poll_interval=0.5,
            )
            self.assertEqual(result["status"], "acquired")
            acquired[style] = result["lease_id"]
        _, queued = self.call(
            pipeline.command_acquire_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=tickets["F"],
            wait_seconds=0,
            poll_interval=0.5,
        )
        self.assertEqual(queued["status"], "slot_wait_timeout")
        queued_sidecar = pipeline.read_json(Path(queued["telemetry_path"]))
        self.assertEqual(queued_sidecar["observed_global_cap"], 5)
        self.assertEqual(queued_sidecar["status"], "slot_wait_timeout")
        _, sliced_wait = self.call(
            pipeline.command_acquire_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=tickets["F"],
            wait_seconds=0,
            slice_seconds=0,
            hard_wait_seconds=1200,
            poll_interval=0.5,
        )
        self.assertEqual(sliced_wait["status"], "slot_waiting")
        first_requested_at = pipeline.read_json(
            Path(sliced_wait["telemetry_path"])
        )["requested_at"]
        self.call(
            pipeline.command_release_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=tickets["A"],
            lease_id=acquired["A"],
        )
        _, promoted = self.call(
            pipeline.command_acquire_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=tickets["F"],
            wait_seconds=0,
            slice_seconds=0,
            hard_wait_seconds=1200,
            poll_interval=0.5,
        )
        self.assertEqual(promoted["status"], "acquired")
        self.assertEqual(promoted["global_imagegen_available_slots"], 0)
        promoted_telemetry = pipeline.read_json(Path(promoted["telemetry_path"]))
        self.assertEqual(promoted_telemetry["requested_at"], first_requested_at)
        _, first_release = self.call(
            pipeline.command_release_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=tickets["F"],
            lease_id=promoted["lease_id"],
        )
        terminal_telemetry = pipeline.read_json(Path(first_release["telemetry_path"]))
        _, second_release = self.call(
            pipeline.command_release_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=tickets["F"],
            lease_id=promoted["lease_id"],
        )
        self.assertEqual(second_release["status"], "already_released")
        self.assertEqual(
            pipeline.read_json(Path(second_release["telemetry_path"])),
            terminal_telemetry,
        )
        _, terminal_acquire = self.call(
            pipeline.command_acquire_fast8_imagegen_slot,
            state=str(self.state_path),
            ticket=tickets["F"],
            wait_seconds=0,
            slice_seconds=0,
            hard_wait_seconds=1200,
            poll_interval=0.5,
        )
        self.assertEqual(
            terminal_acquire["status"], "imagegen_attempt_already_terminal"
        )
        final_f = pipeline.read_json(self.root / "style_jobs" / "style_F.json")
        self.assertEqual(
            {key: final_f.get(key) for key in quality_keys},
            original_quality,
        )

    def test_worker_self_binding_uses_codex_thread_environment(self) -> None:
        self.prepare()
        state = pipeline.read_json(self.state_path)
        state["fast8_imagegen_slot_policy"] = (
            pipeline.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY
        )
        state["scheduler"]["imagegen_slot_policy"] = (
            pipeline.CURRENT_FAST8_IMAGEGEN_SLOT_POLICY
        )
        write_json(self.state_path, state)
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "worker-A"}),
            backpressure_reason="test_single_seat",
        )
        state = pipeline.read_json(self.state_path)
        ticket_path = state["scheduler"]["active_actions"][0]["worker_ticket_path"]
        session_id = "00000000-0000-4000-8000-000000000002"
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": session_id}):
            _, bound = self.call(
                pipeline.command_self_bind_fast8_worker_session,
                state=str(self.state_path),
                ticket=ticket_path,
                model=pipeline.FAST8_WORKER_REQUIRED_MODEL,
                reasoning_effort=pipeline.FAST8_WORKER_REQUIRED_REASONING,
                fork_turns=pipeline.FAST8_WORKER_REQUIRED_FORK_TURNS,
                timestamp="2026-08-03T10:00:01+08:00",
            )
        self.assertEqual(bound["binding_source"], "worker_runtime_environment")
        self.assertEqual(bound["worker_session_id"], session_id)
        active = pipeline.read_json(self.state_path)["scheduler"]["active_actions"][0]
        self.assertEqual(active["worker_session_id"], session_id)
        first_state = pipeline.read_json(self.state_path)
        first_bound_at = first_state["timing"]["last_worker_batch_bound_at"]
        first_batch_count = len(
            first_state["scheduler"]["worker_session_bindings"]
        )
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": session_id}):
            _, repeated = self.call(
                pipeline.command_self_bind_fast8_worker_session,
                state=str(self.state_path),
                ticket=ticket_path,
                model=pipeline.FAST8_WORKER_REQUIRED_MODEL,
                reasoning_effort=pipeline.FAST8_WORKER_REQUIRED_REASONING,
                fork_turns=pipeline.FAST8_WORKER_REQUIRED_FORK_TURNS,
                timestamp="2026-08-03T10:00:09+08:00",
            )
        self.assertEqual(repeated["status"], "already_bound")
        repeated_state = pipeline.read_json(self.state_path)
        self.assertEqual(
            repeated_state["timing"]["last_worker_batch_bound_at"], first_bound_at
        )
        self.assertEqual(
            len(repeated_state["scheduler"]["worker_session_bindings"]),
            first_batch_count,
        )
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "bad"}):
            with self.assertRaisesRegex(SystemExit, "合法 CODEX_THREAD_ID"):
                self.call(
                    pipeline.command_self_bind_fast8_worker_session,
                    state=str(self.state_path),
                    ticket=ticket_path,
                    model=pipeline.FAST8_WORKER_REQUIRED_MODEL,
                    reasoning_effort=pipeline.FAST8_WORKER_REQUIRED_REASONING,
                    fork_turns=pipeline.FAST8_WORKER_REQUIRED_FORK_TURNS,
                    timestamp="2026-08-03T10:00:02+08:00",
                )

    def test_zero_start_backpressure_is_coalesced_and_next_wave_id_is_unique(self) -> None:
        self.prepare()
        shared_root = self.root / "shared_monitoring_coalesced"
        state = pipeline.read_json(self.state_path)
        state["monitoring"] = {"root": str(shared_root)}
        write_json(self.state_path, state)
        occupying_state = {
            "run_id": "other-run",
            "monitoring": {"root": str(shared_root)},
        }
        occupying_tasks = [
            {
                "style": style,
                "page_id": "99",
                "action": "generate_anchor",
                "attempt": 1,
            }
            for style in pipeline.QUICK_STYLES
        ]
        _, _, lease_map, _ = pipeline.acquire_fast8_global_imagegen_slots(
            self.root / "other" / "state.json",
            occupying_state,
            occupying_tasks,
            timestamp=pipeline.now_iso(),
        )
        outputs = []
        for _ in range(2):
            _, output = self.call(
                pipeline.command_record_dispatch_wave,
                state=str(self.state_path),
                styles="A,B,C,D,E,F,G,H",
                tasks_json=None,
                page_id=None,
                action="generate_anchor",
                attempt=1,
                timestamp=pipeline.now_iso(),
                agent_map_json=json.dumps(
                    {style: f"worker-{style}" for style in pipeline.QUICK_STYLES}
                ),
                backpressure_reason=None,
            )
            outputs.append(output)
        state = pipeline.read_json(self.state_path)
        backpressure_events = [
            item
            for item in state["events"]
            if item.get("name") == "runtime_backpressure"
        ]
        self.assertEqual(len(backpressure_events), 1)
        self.assertFalse(outputs[0]["backpressure_poll_coalesced"])
        self.assertTrue(outputs[1]["backpressure_poll_coalesced"])
        self.assertEqual(
            state["scheduler"]["runtime_backpressure"][-1]["poll_count"], 2
        )
        pipeline.release_fast8_global_imagegen_slots(
            self.root / "other" / "state.json",
            occupying_state,
            list(lease_map.values()),
        )
        _, dispatched = self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A,B,C,D,E,F,G,H",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp=pipeline.now_iso(),
            agent_map_json=json.dumps(
                {style: f"worker-{style}" for style in pipeline.QUICK_STYLES}
            ),
            backpressure_reason=None,
        )
        self.assertEqual(dispatched["wave_id"], "dispatch_wave_02")
        errors: list[str] = []
        pipeline.validate_dispatch_audit_v2(
            pipeline.read_json(self.state_path), errors, complete=False
        )
        self.assertEqual(errors, [])

    def test_exhausted_required_seat_terminalizes_run_and_releases_queues(self) -> None:
        self.prepare()
        for attempt in (1, 2):
            self.call(
                pipeline.command_record_dispatch_wave,
                state=str(self.state_path),
                styles="A",
                tasks_json=None,
                page_id=None,
                action="generate_anchor",
                attempt=attempt,
                timestamp=f"2026-08-03T10:0{attempt}:00+08:00",
                agent_map_json=json.dumps({"A": f"worker-A-{attempt}"}),
                backpressure_reason="test_terminalization",
            )
            state = pipeline.read_json(self.state_path)
            active = next(
                item
                for item in state["scheduler"]["active_actions"]
                if item.get("style") == "A"
            )
            receipt_path = Path(active["worker_receipt_path"])
            job = pipeline.read_json(Path(active["generation_job_path"]))
            write_json(
                receipt_path,
                {
                    "worker_receipt_contract_version": 1,
                    "style": "A",
                    "page_id": "02",
                    "action": "generate_anchor",
                    "attempt": attempt,
                    "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                    "worker_agent_id": f"worker-A-{attempt}",
                    "tool_call_id": None,
                    "savedPath": None,
                    "tool_started_at": f"2026-08-03T10:0{attempt}:10+08:00",
                    "tool_finished_at": f"2026-08-03T10:0{attempt}:40+08:00",
                    "receipt_written_at": f"2026-08-03T10:0{attempt}:41+08:00",
                    "tool_status": "failed",
                    "failure_class": "backend_network",
                    "tool_error_code": "network_request_failed",
                    "error": "imagegen_backend_failed",
                    "contains_image_payload": False,
                },
            )
            self.call(
                pipeline.command_settle_fast8_receipts,
                state=str(self.state_path),
                styles="A",
                wait_seconds=0,
                poll_interval=0.2,
                timestamp=f"2026-08-03T10:0{attempt}:42+08:00",
            )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["scheduler"]["phase"], "terminal")
        self.assertEqual(state["scheduler"]["active_actions"], [])
        self.assertEqual(state["scheduler"]["ready_queue"], [])
        self.assertEqual(state["scheduler"]["recovery_queue"], [])
        self.assertEqual(state["terminal_reason"], "required_fast8_seat_exhausted")

    def test_bound_worker_session_dir_requires_exactly_one_exec_png(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="B",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"B": "stable-task-B"}),
            backpressure_reason="test_partial_wave",
        )
        session_id = "019fcc95-bbbb-cccc-dddd-123456789abc"
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps({"B": session_id}),
            styles="B",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:00:01+08:00",
        )
        generated_root = self.root / ".codex" / "generated_images"
        session_dir = generated_root / session_id
        write_png(
            session_dir / "exec-12345678-1234-1234-1234-123456789abc.png"
        )
        write_png(
            session_dir / "exec-abcdefab-cdef-abcd-efab-cdefabcdefab.png"
        )
        job = pipeline.read_json(self.root / "style_jobs" / "style_B.json")
        write_json(
            Path(job["worker_receipt"]["path"]),
            {
                "worker_receipt_contract_version": 1,
                "style": "B",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "worker_agent_id": "/root/stable-task-B",
                "tool_call_id": None,
                "savedPath": None,
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
                "receipt_written_at": "2026-08-03T10:00:41+08:00",
                "error": "artifact_handoff_unresolved",
                "contains_image_payload": False,
            },
        )
        with mock.patch.object(
            pipeline, "GENERATED_IMAGES_ROOT", generated_root.resolve()
        ):
            self.call(
                pipeline.command_settle_fast8_receipts,
                state=str(self.state_path),
                styles="B",
                wait_seconds=0,
                poll_interval=0.2,
                timestamp="2026-08-03T10:00:42+08:00",
            )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(
            [item["style"] for item in state["scheduler"]["recovery_queue"]],
            ["B"],
        )

    def test_receipt_watcher_settles_success_and_failure_without_worker_final_text(
        self,
    ) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A,B",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "agent-A", "B": "agent-B"}),
            backpressure_reason="test_receipt_watcher",
        )
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps(
                {
                    "A": "019fcc95-aaaa-bbbb-cccc-123456789aba",
                    "B": "019fcc95-aaaa-bbbb-cccc-123456789abb",
                }
            ),
            styles="A,B",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:00:01+08:00",
        )
        for style, saved_path, error in (
            ("A", str(self.initial_paths["A"]), None),
            ("B", None, "artifact_handoff_unresolved"),
        ):
            job = pipeline.read_json(self.root / "style_jobs" / f"style_{style}.json")
            write_json(
                Path(job["worker_receipt"]["path"]),
                {
                    "worker_receipt_contract_version": 1,
                    "style": style,
                    "page_id": "02",
                    "action": "generate_anchor",
                    "attempt": 1,
                    "imagegen_input_fingerprint": job[
                        "imagegen_input_fingerprint"
                    ],
                    "worker_agent_id": f"agent-{style}",
                    "tool_call_id": f"tool-{style}-1",
                    "savedPath": saved_path,
                    "tool_started_at": "2026-08-03T10:00:10+08:00",
                    "tool_finished_at": "2026-08-03T10:00:40+08:00",
                    "receipt_written_at": "2026-08-03T10:00:41+08:00",
                    "error": error,
                    "contains_image_payload": False,
                },
            )
        _, output = self.call(
            pipeline.command_settle_fast8_receipts,
            state=str(self.state_path),
            styles="A,B",
            wait_seconds=0,
            poll_interval=0.2,
            timestamp="2026-08-03T10:00:42+08:00",
        )
        assert output
        self.assertFalse(output["worker_final_text_required"])
        self.assertEqual(output["processed_styles"], ["A", "B"])
        self.assertEqual(output["candidate_bound_styles"], ["A"])
        self.assertEqual(output["settled_styles"], ["A"])
        self.assertEqual(output["recovery_pending_styles"], ["B"])
        state = pipeline.read_json(self.state_path)
        record_a = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record_a["artifact_binding_source"], "worker_receipt")
        self.assertEqual(record_a["selected_source"], str(self.initial_paths["A"].resolve()))
        self.assertEqual(state["scheduler"]["active_actions"], [])
        self.assertEqual(
            [item["style"] for item in state["scheduler"]["recovery_queue"]],
            ["B"],
        )
        with mock.patch.object(pipeline.time, "sleep") as sleep:
            _, idle = self.call(
                pipeline.command_settle_fast8_receipts,
                state=str(self.state_path),
                styles="A,B",
                wait_seconds=60,
                poll_interval=2,
                timestamp="2026-08-03T10:00:43+08:00",
            )
        sleep.assert_not_called()
        assert idle
        self.assertEqual(idle["status"], "no_active_receipts")
        self.assertTrue(idle["all_anchor_tools_completed"])

    def test_success_receipt_preserves_real_agent_id_over_bound_task_name(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "stable-task-A"}),
            backpressure_reason="test_receipt_identity",
        )
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        real_agent_id = "019fcc95-aaaa-bbbb-cccc-123456789abc"
        write_json(
            Path(job["worker_receipt"]["path"]),
            {
                "worker_receipt_contract_version": 1,
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "worker_agent_id": real_agent_id,
                "tool_call_id": "tool-A-1",
                "savedPath": str(self.initial_paths["A"]),
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
                "receipt_written_at": "2026-08-03T10:00:41+08:00",
                "error": None,
                "contains_image_payload": False,
            },
        )
        self.call(
            pipeline.command_settle_fast8_receipts,
            state=str(self.state_path),
            styles="A",
            wait_seconds=0,
            poll_interval=0.2,
            timestamp="2026-08-03T10:00:42+08:00",
        )
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["worker_agent_id"], real_agent_id)
        self.assertEqual(record["artifact_binding_source"], "worker_receipt")

    def test_unresolved_receipt_preserves_real_agent_id_in_recovery_queue(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="B",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"B": "stable-task-B"}),
            backpressure_reason="test_receipt_identity",
        )
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps(
                {"B": "019fcc95-aaaa-bbbb-cccc-123456789abc"}
            ),
            styles="B",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:00:01+08:00",
        )
        job = pipeline.read_json(self.root / "style_jobs" / "style_B.json")
        real_agent_id = "/root/p15_fast8_b_20260804"
        write_json(
            Path(job["worker_receipt"]["path"]),
            {
                "worker_receipt_contract_version": 1,
                "style": "B",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 1,
                "imagegen_input_fingerprint": job["imagegen_input_fingerprint"],
                "worker_agent_id": real_agent_id,
                "tool_call_id": "tool-B-1",
                "savedPath": None,
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
                "receipt_written_at": "2026-08-03T10:00:41+08:00",
                "error": "artifact_handoff_unresolved",
                "contains_image_payload": False,
            },
        )
        self.call(
            pipeline.command_settle_fast8_receipts,
            state=str(self.state_path),
            styles="B",
            wait_seconds=0,
            poll_interval=0.2,
            timestamp="2026-08-03T10:00:42+08:00",
        )
        state = pipeline.read_json(self.state_path)
        recovery_queue = state["scheduler"]["recovery_queue"]
        self.assertEqual(len(recovery_queue), 1)
        self.assertEqual(recovery_queue[0]["style"], "B")
        self.assertEqual(
            recovery_queue[0]["worker_agent_id"],
            "019fcc95-aaaa-bbbb-cccc-123456789abc",
        )
        self.assertEqual(state["scheduler"]["active_actions"], [])

    def test_v2_review_input_tampering_blocks_report_application(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(job_path, decision="pass", suffix="pass")
        job = pipeline.read_json(job_path)
        contact_sheet = Path(job["review_input"]["path"])
        contact_sheet.write_bytes(contact_sheet.read_bytes() + b"tampered")
        with self.assertRaisesRegex(SystemExit, "contact sheet 元数据"):
            self.call(
                pipeline.command_apply_fast8_diversity_report,
                project_dir=str(self.root),
                state=str(self.state_path),
                review_job=str(job_path),
                report_file=str(report_path),
                timestamp="2026-08-03T10:04:00+08:00",
            )

    def test_v2_severe_craft_regression_can_use_existing_replacement_budget(
        self,
    ) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(
            job_path,
            decision="replace",
            replacements=["C"],
            briefs={"C": "建立完整统一的视觉语言与更精细的图像和容器关系"},
            collision_for_replacements=False,
            craft_red_flags=[
                {
                    "style": "C",
                    "severity": "severe",
                    "issue_types": [
                        "default_component_assembly",
                        "crude_container_dominance",
                    ],
                    "observable_evidence": (
                        "主体由多块粗糙圆角框和泛化图标拼接，框体压过内容，"
                        "整体没有成立的设计语言。"
                    ),
                }
            ],
            suffix="craft_replace_c",
        )
        _, output = self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:04:00+08:00",
        )
        repair = pipeline.read_json(Path(output["repair_jobs"][0]["job_path"]))
        self.assertEqual(
            repair["diversity_replacement"]["replacement_basis"],
            "minimum_craft_regression",
        )
        self.assertIn("严重最低工艺退化", repair["repair_issue"])
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["diversity_review"]["replacement_count"], 1)
        self.assertEqual(
            state["diversity_review"]["reports"][-1]["craft_red_flags"][0][
                "style"
            ],
            "C",
        )
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles=None,
            tasks_json=json.dumps(
                [
                    {
                        "style": "C",
                        "page_id": "02",
                        "action": "repair_anchor",
                        "attempt": 2,
                    }
                ]
            ),
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:05:00+08:00",
            agent_map_json=None,
            backpressure_reason=None,
        )
        replacement = self.root / "fixtures" / "craft_replacement_C.png"
        write_png(replacement, color=bytes((42, 84, 126)))
        result_path = self.root / "style_jobs" / "results" / "craft_replace.json"
        write_json(
            result_path,
            [
                self.result(
                    "C",
                    action="repair_anchor",
                    attempt=2,
                    path=replacement,
                    minute=6,
                )
            ],
        )
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(result_path),
            expected_styles="C",
            timestamp="2026-08-03T10:08:00+08:00",
        )
        delta_path, _ = self.make_review(8)
        delta = pipeline.read_json(delta_path)
        self.assertEqual(delta["review_kind"], "delta_recheck")
        self.assertEqual(delta["candidate_count"], 1)
        self.assertEqual(delta["changed_styles"], ["C"])
        self.assertEqual(delta["prior_craft_red_flags"][0]["style"], "C")

    def test_single_mild_craft_issue_cannot_trigger_replacement(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(
            job_path,
            decision="replace",
            replacements=["C"],
            briefs={"C": "提升整体完成度"},
            collision_for_replacements=False,
            craft_red_flags=[
                {
                    "style": "C",
                    "severity": "severe",
                    "issue_types": ["crude_container_dominance"],
                    "observable_evidence": "页面有较多容器。",
                }
            ],
            suffix="mild_craft_rejected",
        )
        with self.assertRaisesRegex(SystemExit, "2–4 个"):
            self.call(
                pipeline.command_apply_fast8_diversity_report,
                project_dir=str(self.root),
                state=str(self.state_path),
                review_job=str(job_path),
                report_file=str(report_path),
                timestamp="2026-08-03T10:04:00+08:00",
            )
        self.assertEqual(
            list((self.root / "style_jobs" / "repair_jobs").glob("*_fast8.json")),
            [],
        )

    def test_new_prepare_rejects_legacy_v7_without_art_direction(self) -> None:
        legacy_styles = {}
        for index, style in enumerate(pipeline.QUICK_STYLES):
            legacy_styles[style] = {
                "direction_id": f"legacy_{style}",
                "creative_impulse": f"第{index + 1}种旧版开放视觉启发",
                **(
                    {"first_impression": f"第{index + 1}种旧版第一印象"}
                    if index < 6
                    else {}
                ),
            }
        write_json(
            self.portfolio_path,
            {
                "layout_portfolio_contract_version": 7,
                "page_id": "02",
                "director_rationale": "验证旧版方向不能创建新的 Fast8 任务。",
                "styles": legacy_styles,
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
        with self.assertRaisesRegex(
            SystemExit, "必须使用 art_direction_contract_version=1"
        ):
            self.call(
                pipeline.command_prepare_anchors,
                project_dir=str(self.root),
                state=str(self.state_path),
                content_contract=str(self.content_path),
                overall_requirements="扩大探索",
                reference_images_json="[]",
                required_assets_json="[]",
                layout_portfolio=str(self.portfolio_path),
                source_file=None,
                source_page_ids=None,
                source_fragment_file=None,
                snapshot_content_contracts_json=None,
                source_snapshot_timestamp=None,
            )
        self.assertFalse((self.root / "style_jobs" / "style_A.json").exists())

    def test_duplicate_visual_thesis_is_rejected_before_jobs_are_written(self) -> None:
        portfolio = pipeline.read_json(self.portfolio_path)
        portfolio["styles"]["H"]["visual_thesis"] = portfolio["styles"]["G"][
            "visual_thesis"
        ]
        write_json(self.portfolio_path, portfolio)
        pipeline.create_source_snapshot(
            project_dir=self.root,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=["02"],
            content_contract_paths=[self.content_path],
            asset_items=[],
            timestamp="2099-01-01T00:00:01+08:00",
        )
        with self.assertRaisesRegex(SystemExit, "visual_thesis 与其他方向完全重复"):
            self.call(
                pipeline.command_prepare_anchors,
                project_dir=str(self.root),
                state=str(self.state_path),
                content_contract=str(self.content_path),
                overall_requirements="扩大探索",
                reference_images_json="[]",
                required_assets_json="[]",
                layout_portfolio=str(self.portfolio_path),
                source_file=None,
                source_page_ids=None,
                source_fragment_file=None,
                snapshot_content_contracts_json=None,
                source_snapshot_timestamp=None,
            )
        self.assertFalse((self.root / "style_jobs" / "style_A.json").exists())

    def test_incremental_review_cannot_replace_before_eight(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A,B,C,D",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=None,
            backpressure_reason="运行时先返回四席",
        )
        path = self.root / "style_jobs" / "results" / "partial.json"
        write_json(path, [self.result(style) for style in "ABCD"])
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(path),
            expected_styles="A,B,C,D",
            timestamp="2026-08-03T10:02:00+08:00",
        )
        job_path, _ = self.make_review(4)
        repeated_path, repeated = self.make_review(4)
        self.assertEqual(repeated["status"], "already_prepared")
        self.assertEqual(repeated_path, job_path)
        report_path = self.write_report(
            job_path,
            decision="replace",
            replacements=["D"],
            briefs={"D": "改变视觉入口与图文张力"},
            suffix="early_replace",
        )
        with self.assertRaisesRegex(SystemExit, "checkpoint 4/6 只允许"):
            self.call(
                pipeline.command_apply_fast8_diversity_report,
                project_dir=str(self.root),
                state=str(self.state_path),
                review_job=str(job_path),
                report_file=str(report_path),
                timestamp="2026-08-03T10:03:00+08:00",
            )

    def test_ready_eight_promotes_requested_four_directly_to_final_review(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, output = self.make_review(4)
        job = pipeline.read_json(job_path)
        self.assertEqual(output["requested_checkpoint"], 4)
        self.assertEqual(output["checkpoint"], 8)
        self.assertEqual(output["review_kind"], "final_initial")
        self.assertEqual(job["candidate_count"], 8)
        self.assertEqual(len(job["candidates"]), 8)

        repeated_path, repeated = self.make_review(8)
        self.assertEqual(repeated["status"], "already_prepared")
        self.assertEqual(repeated_path, job_path)
        state = pipeline.read_json(self.state_path)
        self.assertEqual(len(state["diversity_review"]["review_jobs"]), 1)

    def test_readable_saved_path_binds_without_recovery_even_if_metadata_missing(
        self,
    ) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:00:00+08:00",
            agent_map_json=json.dumps({"A": "agent-A"}),
            backpressure_reason="运行时只启动一个测试席位",
        )
        source = (
            self.root
            / "generated"
            / "exec-12345678-1234-1234-1234-1234567890ab.png"
        )
        write_png(source)
        result_path = self.root / "style_jobs" / "results" / "direct_path.json"
        write_json(
            result_path,
            [
                {
                    "style": "A",
                    "page_id": "02",
                    "action": "generate_anchor",
                    "attempt": 1,
                    "savedPath": str(source),
                    "error": "artifact_handoff_unresolved",
                }
            ],
        )
        _, output = self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(result_path),
            expected_styles="A",
            timestamp="2099-01-01T00:00:00+08:00",
        )
        self.assertEqual(output["settled"], 1)
        self.assertEqual(output["unresolved"], [])
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["selected_source"], str(source.resolve()))
        self.assertEqual(record["tool_call_id"], source.stem)
        self.assertEqual(record["artifact_binding_source"], "direct_tool_result")
        self.assertEqual(record["timing_capture"], "controller_bounded_fallback")
        self.assertEqual(state["scheduler"]["recovery_queue"], [])

    def test_recovery_result_reuses_original_tool_metadata_from_active_task(self) -> None:
        self.prepare()
        state = pipeline.read_json(self.state_path)
        state["scheduler"]["active_actions"] = [
            {
                "style": "A",
                "page_id": "02",
                "action": "recover_artifact",
                "source_action": "generate_anchor",
                "attempt": 1,
                "tool_call_id": "original-tool",
                "tool_started_at": "2026-08-03T10:00:10+08:00",
                "tool_finished_at": "2026-08-03T10:00:40+08:00",
            }
        ]
        write_json(self.state_path, state)
        result_path = self.root / "style_jobs" / "results" / "bad_recovery.json"
        write_json(
            result_path,
            [
                {
                    "style": "A",
                    "page_id": "02",
                    "action": "recover_artifact",
                    "source_action": "generate_anchor",
                    "attempt": 1,
                    "savedPath": str(self.initial_paths["A"]),
                    "recovery_started_at": "2026-08-03T10:01:00+08:00",
                    "recovery_finished_at": "2026-08-03T10:01:10+08:00",
                    "recovery_method": "same_worker",
                    "error": None,
                }
            ],
        )
        _, output = self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(result_path),
            expected_styles="A",
            timestamp="2026-08-03T10:01:20+08:00",
        )
        self.assertEqual(output["settled"], 1)
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["tool_call_id"], "original-tool")
        self.assertEqual(
            record["timing_capture"], "controller_bounded_recovery_fallback"
        )
        self.assertEqual(record["recovery_status"], "recovered")

    def test_recovery_result_derives_missing_original_metadata_without_regeneration(
        self,
    ) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A",
            tasks_json=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2099-01-01T00:00:00+08:00",
            agent_map_json=json.dumps({"A": "agent-A"}),
            backpressure_reason="test_missing_handoff",
        )
        self.call(
            pipeline.command_bind_fast8_worker_sessions,
            state=str(self.state_path),
            session_map_json=json.dumps(
                {"A": "019fcc95-aaaa-bbbb-cccc-123456789abc"}
            ),
            styles="A",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2099-01-01T00:00:01+08:00",
        )
        unresolved_path = self.root / "style_jobs" / "results" / "missing.json"
        write_json(
            unresolved_path,
            [
                {
                    "style": "A",
                    "page_id": "02",
                    "action": "generate_anchor",
                    "attempt": 1,
                    "worker_agent_id": "agent-A",
                    "savedPath": None,
                    "error": "artifact_handoff_unresolved",
                }
            ],
        )
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(unresolved_path),
            expected_styles="A",
            timestamp="2099-01-01T00:01:00+08:00",
        )
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles=None,
            tasks_json=json.dumps(
                [
                    {
                        "style": "A",
                        "page_id": "02",
                        "action": "recover_artifact",
                        "attempt": 1,
                    }
                ]
            ),
            page_id=None,
            action="recover_artifact",
            attempt=1,
            timestamp="2099-01-01T00:01:10+08:00",
            agent_map_json=json.dumps(
                {"A/02/recover_artifact/1": "agent-A"}
            ),
            backpressure_reason="recovery_only",
        )
        source = (
            self.root
            / "generated"
            / "exec-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.png"
        )
        write_png(source)
        recovered_path = self.root / "style_jobs" / "results" / "recovered.json"
        write_json(
            recovered_path,
            [
                {
                    "style": "A",
                    "page_id": "02",
                    "action": "recover_artifact",
                    "source_action": "generate_anchor",
                    "attempt": 1,
                    "worker_agent_id": "agent-A",
                    "savedPath": str(source),
                    "recovery_started_at": "2099-01-01T00:01:11+08:00",
                    "recovery_finished_at": "2099-01-01T00:01:12+08:00",
                    "recovery_method": "same_worker",
                    "error": None,
                }
            ],
        )
        _, output = self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(recovered_path),
            expected_styles="A",
            timestamp="2099-01-01T00:01:20+08:00",
        )
        self.assertEqual(output["settled"], 1)
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["tool_call_id"], source.stem)
        self.assertEqual(
            record["timing_capture"], "controller_bounded_recovery_fallback"
        )
        self.assertEqual(record["recovery_status"], "recovered")
        self.assertEqual(record["attempt_count"], 1)

    def test_post_dispatch_source_change_does_not_block_fast8_review(self) -> None:
        self.prepare()
        self.settle_initials()
        self.source_path.write_text(
            "## P02\nChanged Fast8 content\n", encoding="utf-8"
        )
        before = sorted((self.root / "visual_qa_jobs").glob("fast8_diversity_*.json"))
        self.make_review(8)
        after = sorted((self.root / "visual_qa_jobs").glob("fast8_diversity_*.json"))
        self.assertEqual(len(after), len(before) + 1)

    def test_fast8_page_completed_cannot_use_accepted_bypass(self) -> None:
        self.prepare()
        self.settle_initials()
        with self.assertRaisesRegex(SystemExit, "只允许 candidate_ready"):
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event="page_completed",
                style="A",
                page_id="02",
                action=None,
                timestamp="2026-08-03T10:03:00+08:00",
                details_json="{}",
            )

    def test_final_pass_is_required_before_candidate_ready(self) -> None:
        self.prepare()
        self.settle_initials()
        with self.assertRaisesRegex(SystemExit, "必须先完成"):
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event="page_completed",
                style="A",
                page_id="02",
                action=None,
                timestamp="2026-08-03T10:03:00+08:00",
                details_json=json.dumps({"completion_status": "candidate_ready"}),
            )
        job_path, _ = self.make_review(8)
        report_path = self.write_report(job_path, decision="pass", suffix="pass")
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:04:00+08:00",
        )
        self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="page_completed",
            style="A",
            page_id="02",
            action=None,
            timestamp="2026-08-03T10:05:00+08:00",
            details_json=json.dumps({"completion_status": "candidate_ready"}),
        )
        record = pipeline.read_json(self.state_path)["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["status"], "candidate_ready")
        self.assertEqual(record["qa_scope"], "filesystem_only")

    def test_diversity_report_cannot_claim_full_visual_qa(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(job_path, decision="pass", suffix="bad_qa")
        report = pipeline.read_json(report_path)
        report["content_gate"] = "pass"
        write_json(report_path, report)
        with self.assertRaisesRegex(SystemExit, "未授权字段"):
            self.call(
                pipeline.command_apply_fast8_diversity_report,
                project_dir=str(self.root),
                state=str(self.state_path),
                review_job=str(job_path),
                report_file=str(report_path),
                timestamp="2026-08-03T10:04:00+08:00",
            )

    def test_prepare_after_pass_is_idempotent_and_does_not_reopen_gate(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(job_path, decision="pass", suffix="pass_once")
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:04:00+08:00",
        )
        _, repeated = self.call(
            pipeline.command_prepare_fast8_diversity_review,
            project_dir=str(self.root),
            state=str(self.state_path),
            checkpoint=8,
        )
        self.assertEqual(repeated["status"], "already_complete")
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["diversity_review"]["status"], "pass")

    def test_new_report_after_pass_cannot_reopen_replacement(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        pass_report = self.write_report(job_path, decision="pass", suffix="terminal_pass")
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(pass_report),
            timestamp="2026-08-03T10:04:00+08:00",
        )
        replace_report = self.write_report(
            job_path,
            decision="replace",
            replacements=["H"],
            briefs={"H": "重新建立开放的视觉重心与更鲜明的图文张力"},
            suffix="late_replace",
        )
        with self.assertRaisesRegex(SystemExit, "差异门已经终态"):
            self.call(
                pipeline.command_apply_fast8_diversity_report,
                project_dir=str(self.root),
                state=str(self.state_path),
                review_job=str(job_path),
                report_file=str(replace_report),
                timestamp="2026-08-03T10:05:00+08:00",
            )

    def test_fast8_judge_report_requires_exact_runtime_binding(self) -> None:
        self.prepare()
        self.settle_initials()
        _, prepared = self.call(
            pipeline.command_prepare_fast8_diversity_review,
            project_dir=str(self.root),
            state=str(self.state_path),
            checkpoint=8,
        )
        job_path = Path(prepared["review_job"])
        report_path = self.write_report(
            job_path, decision="pass", suffix="runtime_binding_pass"
        )
        with self.assertRaisesRegex(SystemExit, "缺少合规运行时绑定"):
            self.call(
                pipeline.command_apply_fast8_diversity_report,
                project_dir=str(self.root),
                state=str(self.state_path),
                review_job=str(job_path),
                report_file=str(report_path),
                timestamp="2026-08-03T10:05:00+08:00",
            )
        with self.assertRaisesRegex(SystemExit, "运行时不符合正式合同"):
            self.call(
                pipeline.command_bind_fast8_judge_session,
                state=str(self.state_path),
                review_job=str(job_path),
                session_id="019fcdb5-c91c-7b60-b931-e2442324b122",
                model="gpt-5.6-sol",
                reasoning_effort="high",
                fork_turns="all",
                timestamp="2026-08-03T10:03:00+08:00",
            )
        self.call(
            pipeline.command_bind_fast8_judge_session,
            state=str(self.state_path),
            review_job=str(job_path),
            session_id="019fcdb5-c91c-7b60-b931-e2442324b122",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            fork_turns="none",
            timestamp="2026-08-03T10:03:00+08:00",
        )
        _, applied = self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:05:00+08:00",
        )
        self.assertEqual(applied["decision"], "pass")
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["diversity_review"]["status"], "pass")

    def test_judge_self_binding_uses_codex_thread_environment(self) -> None:
        self.prepare()
        self.settle_initials()
        _, prepared = self.call(
            pipeline.command_prepare_fast8_diversity_review,
            project_dir=str(self.root),
            state=str(self.state_path),
            checkpoint=8,
        )
        job_path = Path(prepared["review_job"])
        session_id = "00000000-0000-4000-8000-000000000003"
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": session_id}):
            _, bound = self.call(
                pipeline.command_self_bind_fast8_judge_session,
                state=str(self.state_path),
                review_job=str(job_path),
                model=pipeline.FAST8_JUDGE_REQUIRED_MODEL,
                reasoning_effort=pipeline.FAST8_JUDGE_REQUIRED_REASONING,
                fork_turns=pipeline.FAST8_JUDGE_REQUIRED_FORK_TURNS,
                timestamp="2026-08-03T10:03:00+08:00",
            )
        self.assertEqual(bound["binding_source"], "judge_runtime_environment")
        self.assertEqual(bound["session_id"], session_id)
        state = pipeline.read_json(self.state_path)
        binding = state["diversity_review"]["review_jobs"][-1][
            "judge_runtime_binding"
        ]
        self.assertEqual(binding["session_id"], session_id)
        self.assertEqual(state["scheduler"]["ready_queue"], [])

    def test_standby_judge_waits_without_creating_partial_review_job(self) -> None:
        self.prepare()
        session_id = "00000000-0000-4000-8000-000000000004"
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": session_id}):
            _, result = self.call(
                pipeline.command_await_fast8_judge_job,
                state=str(self.state_path),
                model=pipeline.FAST8_JUDGE_REQUIRED_MODEL,
                reasoning_effort=pipeline.FAST8_JUDGE_REQUIRED_REASONING,
                fork_turns=pipeline.FAST8_JUDGE_REQUIRED_FORK_TURNS,
                wait_seconds=0,
                poll_interval=0.2,
                timestamp="2026-08-03T10:03:00+08:00",
            )
        self.assertEqual(result["status"], "waiting")
        self.assertTrue(result["retry_same_session"])
        state = pipeline.read_json(self.state_path)
        self.assertFalse((state.get("diversity_review") or {}).get("review_jobs"))
        self.assertFalse((self.root / "visual_qa_jobs").exists())

    def test_standby_judge_claims_complete_job_and_returns_check_contract(self) -> None:
        self.prepare()
        self.settle_initials()
        _, prepared = self.call(
            pipeline.command_prepare_fast8_diversity_review,
            project_dir=str(self.root),
            state=str(self.state_path),
            checkpoint=8,
        )
        session_id = "00000000-0000-4000-8000-000000000005"
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": session_id}):
            _, result = self.call(
                pipeline.command_await_fast8_judge_job,
                state=str(self.state_path),
                model=pipeline.FAST8_JUDGE_REQUIRED_MODEL,
                reasoning_effort=pipeline.FAST8_JUDGE_REQUIRED_REASONING,
                fork_turns=pipeline.FAST8_JUDGE_REQUIRED_FORK_TURNS,
                wait_seconds=0,
                poll_interval=0.2,
                timestamp="2026-08-03T10:03:00+08:00",
            )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["review_job"], prepared["review_job"])
        self.assertEqual(
            result["judge_runtime_binding"]["session_id"], session_id
        )
        self.assertTrue(Path(result["contact_sheet_path"]).is_file())
        state = pipeline.read_json(self.state_path)
        binding = state["diversity_review"]["review_jobs"][-1][
            "judge_runtime_binding"
        ]
        self.assertEqual(binding["session_id"], session_id)

    def test_invalid_second_replacement_leaves_no_orphan_jobs(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(
            job_path,
            decision="replace",
            replacements=["C", "H"],
            briefs={"C": "建立新的视觉重心与开放边缘"},
            suffix="missing_second_brief",
        )
        with self.assertRaisesRegex(SystemExit, "replacement_briefs 必须且只能覆盖"):
            self.call(
                pipeline.command_apply_fast8_diversity_report,
                project_dir=str(self.root),
                state=str(self.state_path),
                review_job=str(job_path),
                report_file=str(report_path),
                timestamp="2026-08-03T10:04:00+08:00",
            )
        repair_dir = self.root / "style_jobs" / "repair_jobs"
        self.assertEqual(list(repair_dir.glob("*_fast8.json")), [])
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["scheduler"]["ready_queue"], [])
        self.assertEqual(state["diversity_review"]["replacement_count"], 0)

    def test_pending_replacement_cannot_be_bypassed_by_new_checkpoint(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        replace_report = self.write_report(
            job_path,
            decision="replace",
            replacements=["H"],
            briefs={"H": "重新建立开放的视觉重心与更鲜明的图文张力"},
            suffix="queue_h",
        )
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(replace_report),
            timestamp="2026-08-03T10:04:00+08:00",
        )
        with self.assertRaisesRegex(SystemExit, "不得创建任何新 checkpoint"):
            self.call(
                pipeline.command_prepare_fast8_diversity_review,
                project_dir=str(self.root),
                state=str(self.state_path),
                checkpoint=4,
            )
        stale_pass = self.write_report(job_path, decision="pass", suffix="stale_pass")
        with self.assertRaisesRegex(SystemExit, "不得应用新的差异报告"):
            self.call(
                pipeline.command_apply_fast8_diversity_report,
                project_dir=str(self.root),
                state=str(self.state_path),
                review_job=str(job_path),
                report_file=str(stale_pass),
                timestamp="2026-08-03T10:05:00+08:00",
            )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["diversity_review"]["status"], "repair_queued")
        self.assertEqual(len(state["scheduler"]["ready_queue"]), 1)
        with self.assertRaisesRegex(SystemExit, "必须先完成"):
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event="page_completed",
                style="A",
                page_id="02",
                action=None,
                timestamp="2026-08-03T10:06:00+08:00",
                details_json=json.dumps({"completion_status": "candidate_ready"}),
            )

    def test_no_replacement_run_completes_candidate_handoff_and_full_validation(
        self,
    ) -> None:
        original_now_iso = pipeline.now_iso
        pipeline.now_iso = lambda: "2026-08-03T09:52:00+08:00"
        self.addCleanup(setattr, pipeline, "now_iso", original_now_iso)
        for event, timestamp in (
            ("process_started", "2026-08-03T09:50:00+08:00"),
            ("preflight_resolved", "2026-08-03T09:51:00+08:00"),
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
        for index, style in enumerate(pipeline.QUICK_STYLES):
            path = self.root / "origin_image" / f"style_{style}_page_02.png"
            write_png(path, color=bytes((210 - index, 220 - index, 230 - index)))
            self.initial_paths[style] = path
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(job_path, decision="pass", suffix="full_pass")
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:02:30+08:00",
        )
        for index, style in enumerate(pipeline.QUICK_STYLES):
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event="overview_qa",
                style=style,
                page_id="02",
                action="qa_filesystem",
                timestamp=f"2026-08-03T10:03:{index:02d}+08:00",
                details_json=json.dumps(
                    {"qa_stage": "filesystem", "qa_scope": "filesystem_only"}
                ),
            )
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event="page_completed",
                style=style,
                page_id="02",
                action="complete_candidate",
                timestamp=f"2026-08-03T10:04:{index:02d}+08:00",
                details_json=json.dumps(
                    {
                        "completion_status": "candidate_ready",
                        "final_path": str(self.initial_paths[style]),
                    }
                ),
            )
        overview_path = self.root / "overview" / "ABCDEFGH_2x4.png"
        write_png(overview_path)
        self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="formal_overview_completed",
            style=None,
            page_id=None,
            action=None,
            timestamp="2026-08-03T10:05:00+08:00",
            details_json=json.dumps({"output_path": str(overview_path)}),
        )
        self.call(
            pipeline.command_record_event,
            state=str(self.state_path),
            event="process_completed",
            style=None,
            page_id=None,
            action=None,
            timestamp="2026-08-03T10:05:00+08:00",
            details_json=None,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            try:
                pipeline.command_validate_state(
                    argparse.Namespace(state=str(self.state_path), complete=True)
                )
            except SystemExit as exc:
                self.fail(f"Fast8 完整验收失败：{output.getvalue()} ({exc})")
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "pass")
        self.assertTrue((self.root / "state" / "handoff.json").is_file())
        self.assertTrue((self.root / "state" / "handoff.md").is_file())
        self.assertTrue((self.root / "state" / "run_health_report.json").is_file())
        self.assertTrue((self.root / "state" / "run_health_report.md").is_file())
        local_monitoring = (
            self.root / "state" / "_monitoring" / "shawn-ppt-image"
        )
        self.assertTrue((local_monitoring / "index.json").is_file())
        self.assertEqual(
            pipeline.read_json(local_monitoring / "index.json")["run_count"], 1
        )
        completed_state = pipeline.read_json(self.state_path)
        target = completed_state["timing_target"]
        self.assertFalse(target["hard_deadline"])
        self.assertEqual(
            target["scope"], "request_started_at_to_delivery_ready"
        )
        self.assertTrue(target["met"])
        handoff = pipeline.read_json(self.root / "state" / "handoff.json")
        self.assertEqual(handoff["state_ref"]["sha256"], pipeline.file_sha256(self.state_path))
        with self.assertRaisesRegex(SystemExit, "正式状态已封存"):
            self.call(
                pipeline.command_record_event,
                state=str(self.state_path),
                event="overview_qa",
                style="A",
                page_id="02",
                action="qa_filesystem",
                timestamp="2026-08-03T10:07:00+08:00",
                details_json=json.dumps(
                    {"qa_stage": "filesystem", "qa_scope": "filesystem_only"}
                ),
            )
        self.assertEqual(
            pipeline.read_json(self.root / "state" / "handoff.json")["state_ref"]["sha256"],
            pipeline.file_sha256(self.state_path),
        )

    def test_finalize_fast8_performs_the_entire_post_judge_tail_once(self) -> None:
        original_now_iso = pipeline.now_iso
        pipeline.now_iso = lambda: "2026-08-03T09:52:00+08:00"
        self.addCleanup(setattr, pipeline, "now_iso", original_now_iso)
        for event, timestamp in (
            ("process_started", "2026-08-03T09:50:00+08:00"),
            ("preflight_resolved", "2026-08-03T09:51:00+08:00"),
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
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(job_path, decision="pass", suffix="finalize_pass")
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:02:30+08:00",
        )
        pipeline.now_iso = lambda: "2026-08-03T10:03:00+08:00"
        matrix_module = mock.Mock()
        matrix_module.build_matrix = lambda **kwargs: (
            write_png(Path(kwargs["output"])) or []
        )
        with mock.patch.dict(pipeline.sys.modules, {"build_style_matrix": matrix_module}):
            _, output = self.call(
                pipeline.command_finalize_fast8,
                state=str(self.state_path),
                overview_python=None,
            )
        assert output
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["link_count"], 9)
        self.assertEqual(output["validate_state"], "pass")
        self.assertTrue((self.root / "overview" / "ABCDEFGH_2x4.png").is_file())
        self.assertTrue((self.root / "state" / "handoff.json").is_file())
        self.assertTrue(Path(output["delivery_message"]).is_file())
        self.assertEqual(pipeline.read_json(self.state_path)["status"], "completed")

    def test_two_replacements_are_archived_and_require_one_final_recheck(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(
            job_path,
            decision="replace",
            replacements=["C", "H"],
            briefs={
                "C": "建立更鲜明的单一视觉重心与开放边缘",
                "H": "改变阅读入口和图像处理，让节奏更具编辑感",
            },
            suffix="replace_ch",
        )
        _, applied = self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:04:00+08:00",
        )
        assert applied
        self.assertEqual(len(applied["repair_jobs"]), 2)
        for item in applied["repair_jobs"]:
            repair = pipeline.read_json(Path(item["job_path"]))
            self.assertFalse(
                repair["diversity_replacement"]["reuse_source_candidate_as_image_input"]
            )
            self.assertNotIn(
                repair["repair_source"], repair["imagegen_referenced_paths"]
            )
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles=None,
            tasks_json=json.dumps(
                [
                    {"style": style, "page_id": "02", "action": "repair_anchor", "attempt": 2}
                    for style in ("C", "H")
                ]
            ),
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-08-03T10:05:00+08:00",
            agent_map_json=None,
            backpressure_reason=None,
        )
        replacement_paths = {}
        for index, style in enumerate(("C", "H")):
            path = self.root / "fixtures" / f"replacement_{style}.png"
            write_png(path, color=bytes((40 + index, 80 + index, 120 + index)))
            replacement_paths[style] = path
        results_path = self.root / "style_jobs" / "results" / "replacement.json"
        write_json(
            results_path,
            [
                self.result(
                    style,
                    action="repair_anchor",
                    attempt=2,
                    path=replacement_paths[style],
                    minute=6,
                )
                for style in ("C", "H")
            ],
        )
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(results_path),
            expected_styles="C,H",
            timestamp="2026-08-03T10:08:00+08:00",
        )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["diversity_review"]["status"], "recheck_required")
        self.assertEqual(len(state["styles"]["C"]["pages"]["02"]["attempt_history"]), 1)
        final_job, _ = self.make_review(8)
        final_job_value = pipeline.read_json(final_job)
        self.assertEqual(final_job_value["review_kind"], "delta_recheck")
        self.assertEqual(final_job_value["full_candidate_count"], 8)
        self.assertLess(final_job_value["candidate_count"], 8)
        self.assertEqual(set(final_job_value["changed_styles"]), {"C", "H"})
        final_report = self.write_report(final_job, decision="pass", suffix="final_pass")
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(final_job),
            report_file=str(final_report),
            timestamp="2026-08-03T10:09:00+08:00",
        )
        final_state = pipeline.read_json(self.state_path)
        self.assertEqual(final_state["diversity_review"]["status"], "pass")
        self.assertEqual(final_state["diversity_review"]["replacement_count"], 2)

    def test_replacement_jobs_are_removed_if_state_commit_fails(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(
            job_path,
            decision="replace",
            replacements=["C", "H"],
            briefs={"C": "改变入口", "H": "改变图文张力"},
            suffix="transaction_failure",
        )
        original_atomic = pipeline.atomic_write_json

        def fail_state_only(path, value):
            if Path(path).resolve() == self.state_path.resolve():
                raise OSError("simulated state commit failure")
            return original_atomic(path, value)

        with mock.patch.object(pipeline, "atomic_write_json", side_effect=fail_state_only):
            with self.assertRaisesRegex(OSError, "simulated state commit failure"):
                self.call(
                    pipeline.command_apply_fast8_diversity_report,
                    project_dir=str(self.root),
                    state=str(self.state_path),
                    review_job=str(job_path),
                    report_file=str(report_path),
                    timestamp="2026-08-03T10:04:00+08:00",
                )
        self.assertEqual(
            list((self.root / "style_jobs" / "repair_jobs").glob("*_fast8.json")),
            [],
        )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["diversity_review"]["replacement_count"], 0)
        self.assertEqual(state["scheduler"]["ready_queue"], [])

    def test_changed_base_report_uses_one_full_recheck_fallback(self) -> None:
        self.prepare()
        self.settle_initials()
        job_path, _ = self.make_review(8)
        report_path = self.write_report(
            job_path,
            decision="replace",
            replacements=["H"],
            briefs={"H": "改变阅读入口"},
            suffix="base_report_for_fallback",
        )
        report = pipeline.read_json(report_path)
        state = pipeline.read_json(self.state_path)
        review = state["diversity_review"]
        review.update(
            {
                "status": "recheck_required",
                "replacement_count": 1,
                "replacement_rounds_used": 1,
                "replacement_styles": ["H"],
                "final_candidate_set_sha256": None,
                "reports": [
                    {
                        "decision": "replace",
                        "report_path": str(report_path),
                        "report_sha256": pipeline.file_sha256(report_path),
                        "candidate_set_sha256": report["candidate_set_sha256"],
                        "collision_groups": report["collision_groups"],
                    }
                ],
            }
        )
        write_json(self.state_path, state)
        report["summary"] = "tampered after apply"
        write_json(report_path, report)
        fallback_job, output = self.make_review(8)
        fallback = pipeline.read_json(fallback_job)
        self.assertEqual(output["review_kind"], "final_recheck_fallback")
        self.assertEqual(fallback["candidate_count"], 8)
        self.assertEqual(fallback["full_candidate_count"], 8)
        self.assertEqual(
            fallback["fallback_reason"],
            "base_replace_report_unavailable_or_changed",
        )
        repeated_path, repeated = self.make_review(8)
        self.assertEqual(repeated["status"], "already_prepared")
        self.assertEqual(repeated_path, fallback_job)
        final_state = pipeline.read_json(self.state_path)
        self.assertEqual(len(final_state["diversity_review"]["review_jobs"]), 2)

    def test_exhausted_replacement_retry_restores_incumbent_and_rechecks(self) -> None:
        self.prepare()
        self.settle_initials()
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        incumbent = pipeline.incumbent_candidate_snapshot(record)
        assert incumbent is not None
        state["diversity_review"]["status"] = "repair_queued"
        state["diversity_review"]["final_candidate_set_sha256"] = "stale"
        active_recovery = {
            "style": "A",
            "page_id": "02",
            "action": "recover_artifact",
            "source_action": "repair_anchor",
            "attempt": 3,
            "diversity_replacement": True,
            "incumbent_candidate": incumbent,
        }
        state["scheduler"]["active_actions"] = [active_recovery]
        for sequence, method in enumerate(
            ("same_worker", "deterministic_script"), start=1
        ):
            state["events"].append(
                {
                    "sequence": sequence,
                    "name": "artifact_recovery_finished",
                    "style": "A",
                    "page_id": "02",
                    "action": "recover_artifact",
                    "details": {
                        "source_action": "repair_anchor",
                        "attempt": 3,
                        "recovery_status": "not_found",
                        "recovery_method": method,
                    },
                }
            )
        result = pipeline._transition_unsuccessful_recovery(
            self.state_path,
            state,
            "A",
            "02",
            "2026-08-03T10:10:00+08:00",
            {"recovery_status": "not_found"},
            active_recovery,
        )
        self.assertEqual(result["next_action"], "recheck_diversity")
        self.assertEqual(record["selected_source"], incumbent["selected_source"])
        self.assertEqual(state["diversity_review"]["status"], "recheck_required")
        self.assertIsNone(state["diversity_review"]["final_candidate_set_sha256"])
        self.assertEqual(
            record["diversity_replacement_failures"][-1]["reason"],
            "technical_retry_budget_exhausted",
        )
        self.assertEqual(state["scheduler"]["active_actions"], [])

    def test_global_chrome_compiles_once_and_routes_tone_logo(self) -> None:
        contract_path = self.write_global_chrome_contract()
        self.prepare(contract_path)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        brief = contract["deck_title_system"]["prompt_briefs"]["zh"]
        dark_job = json.loads(
            (self.root / "style_jobs" / "style_A.json").read_text(encoding="utf-8")
        )
        light_job = json.loads(
            (self.root / "style_jobs" / "style_E.json").read_text(encoding="utf-8")
        )
        self.assertEqual(dark_job["imagegen_prompt"].count(brief), 1)
        self.assertEqual(light_job["imagegen_prompt"].count(brief), 1)
        self.assertIn("ra_dark.png", dark_job["imagegen_referenced_paths"][0])
        self.assertIn("ra_light.png", light_job["imagegen_referenced_paths"][0])
        self.assertTrue(dark_job["global_chrome"]["applies"])
        self.assertEqual(dark_job["global_chrome"]["match_mode"], "approximate")
        self.assertEqual(
            dark_job["creative_brief_projection"]["global_chrome_contract_ref"][
                "sha256"
            ],
            pipeline.file_sha256(contract_path),
        )
        snapshot = json.loads(
            (self.root / "state" / "source_snapshot.json").read_text(encoding="utf-8")
        )
        snapshot_paths = {item["path"] for item in snapshot["assets"]}
        self.assertIn(str(contract_path.resolve()), snapshot_paths)
        authorization_source = contract["authorization"]["source_path"]
        self.assertNotIn(str(Path(authorization_source).resolve()), snapshot_paths)

    def test_global_chrome_outline_authorization_does_not_block_unrelated_page_edit(
        self,
    ) -> None:
        self.source_path.write_text(
            "## P02\nStable Fast8 content\n\n## P03\nOther page v1\n",
            encoding="utf-8",
        )
        contract_path = self.write_global_chrome_contract()
        contract = pipeline.read_json(contract_path)
        contract["authorization"]["source_path"] = str(self.source_path.resolve())
        contract["authorization"]["source_sha256"] = pipeline.file_sha256(
            self.source_path
        )
        write_json(contract_path, contract)
        self.prepare(contract_path)
        self.source_path.write_text(
            "## P02\nStable Fast8 content\n\n## P03\nOther page v2\n",
            encoding="utf-8",
        )
        drift = pipeline.evaluate_source_drift(self.state_path, action="resume")
        self.assertEqual(drift["status"], "warning_unrelated_source_change")
        self.assertTrue(drift["can_continue"])
        self.assertFalse(drift["used_asset_changed"])
        self.settle_initials()
        job_path, prepared = self.make_review(8)
        self.assertEqual(prepared["status"], "ok")
        self.assertTrue(job_path.is_file())

    def test_global_chrome_initial_binding_rejects_stale_outline_authority(self) -> None:
        contract_path = self.write_global_chrome_contract()
        contract = pipeline.read_json(contract_path)
        authorization_source = Path(contract["authorization"]["source_path"])
        authorization_source.write_text("changed before initial binding\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "授权来源 SHA-256 不匹配"):
            self.prepare(contract_path)
        self.assertFalse((self.root / "style_jobs" / "style_A.json").exists())

    def test_without_outline_title_requirement_keeps_title_zone_free(self) -> None:
        self.prepare()
        job = json.loads(
            (self.root / "style_jobs" / "style_A.json").read_text(encoding="utf-8")
        )
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertNotIn("global_chrome", job)
        self.assertNotIn("global_chrome_contract_path", state)
        self.assertNotIn("global_chrome_review", state)

    def test_global_chrome_rejects_page_level_no_logo_conflict(self) -> None:
        contract_path = self.write_global_chrome_contract()
        content = json.loads(self.content_path.read_text(encoding="utf-8"))
        content["prompt_user_constraints"] = ["只使用主标题，不添加 RA Logo。"]
        write_json(self.content_path, content)
        with self.assertRaisesRegex(SystemExit, "禁止删除必需 Logo"):
            self.prepare(contract_path)
        self.assertFalse((self.root / "style_jobs" / "style_A.json").exists())

    def test_global_chrome_review_is_integrated_into_final_fast8_judge(self) -> None:
        contract_path = self.write_global_chrome_contract()
        self.prepare(contract_path)
        self.settle_initials()
        job_path, prepared = self.make_review(8)
        job = pipeline.read_json(job_path)
        self.assertIn("integrated_global_chrome_check", job)
        self.assertTrue(
            job["integrated_global_chrome_check"]["authorized_requirements"][
                "logo_required"
            ]
        )
        report_path = self.write_report(
            job_path, decision="pass", suffix="integrated_chrome_pass"
        )
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:04:00+08:00",
        )
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["global_chrome_review"]["status"], "pass")
        _, integrated = self.call(
            pipeline.command_prepare_global_chrome_review,
            project_dir=str(self.root),
            state=str(self.state_path),
        )
        self.assertEqual(integrated["status"], "integrated_into_fast8_judge")

    def test_outline_title_review_supports_no_logo_and_approximate_match(self) -> None:
        contract_path = self.write_global_chrome_contract()
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["deck_title_system"]["logo"] = {"required": False}
        contract["deck_title_system"]["prompt_briefs"] = {
            "zh": "按大纲大致保留主标题的位置和层级；没有 Logo 要求，正文构图自由。",
            "en": "Approximately retain the outline's title position and hierarchy; no logo is required and the body remains free.",
        }
        write_json(contract_path, contract)
        self.prepare(contract_path)
        self.settle_initials()
        job_path, _ = self.make_review(8)
        job = json.loads(job_path.read_text(encoding="utf-8"))
        integrated = job["integrated_global_chrome_check"]
        self.assertFalse(integrated["pixel_exact_match_required"])
        self.assertTrue(integrated["fail_only_on_clear_outline_deviation"])
        self.assertFalse(integrated["authorized_requirements"]["logo_required"])
        report_path = self.write_report(
            job_path, decision="pass", suffix="integrated_no_logo_pass"
        )
        self.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.root),
            state=str(self.state_path),
            review_job=str(job_path),
            report_file=str(report_path),
            timestamp="2026-08-03T10:04:00+08:00",
        )
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["global_chrome_review"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
