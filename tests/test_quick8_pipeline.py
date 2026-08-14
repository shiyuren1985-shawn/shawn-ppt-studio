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
SPEC = importlib.util.spec_from_file_location("pipeline_control", MODULE_PATH)
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


def legacy_direction(
    direction_id: str,
    mother: str,
    variant: str,
    path: str,
    emphasis: str,
    strategy: str,
    key: str,
) -> dict:
    return {
        "direction_id": direction_id,
        "mother_structure": mother,
        "layout_variant": variant,
        "reading_path": path,
        "visual_emphasis": emphasis,
        "image_text_strategy": strategy,
        "difference_key": key,
        "contrast_axes": ["geometry", "reading_path", "visual_emphasis"],
    }


def creative_direction(direction_id: str, guidance: str) -> dict:
    return {"direction_id": direction_id, "creative_direction": guidance}


def first_impression(direction_id: str, guidance: str | None = None) -> dict:
    value = {"direction_id": direction_id}
    if guidance is not None:
        value["first_impression"] = guidance
    return value


class Quick8PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shawn_quick8_")
        self.root = Path(self.temp.name)
        self.state_path = self.root / "style_run_state.json"
        self.content_path = self.root / "content.json"
        self.portfolio_path = self.root / "layout_portfolio.json"
        self.source_path = self.root / "source" / "outline.md"
        self.image_path = self.root / "fixture.png"
        write_png(self.image_path)
        self.result_paths = {}
        for index, style in enumerate(pipeline.QUICK_STYLES):
            path = self.root / f"fixture_{style}.png"
            write_png(path, color=bytes((240 - index, 250 - index, 255 - index)))
            self.result_paths[style] = path
        write_json(
            self.state_path,
            {
                "run_id": "test-quick8-v5",
                "run_mode": "quick_8x1",
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
                "title": "测试标题",
                "core_claim": "测试主张",
                "source_facts": ["事实1"],
                "display_required": ["测试标题", "100%"],
                "display_flexible": ["洞察能力与行动能力共同促进目标达成"],
                "display_supporting": [],
                "semantic_invariants": [
                    "标题与两项能力为主从关系",
                    "若采用顺序表达，应先呈现洞察，再呈现行动",
                ],
                "forbidden_interpretations": [],
                "prompt_semantic_guardrails": [
                    "洞察能力与行动能力必须准确呈现",
                    "标题保持上位关系",
                ],
                "prompt_user_constraints": [],
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
                "spatial_pressure_profile": "low",
                "spatial_generation_brief": pipeline.QUICK8_BREATHING_PROMPT_CUES["zh"]["low"],
                "spatial_qa_contract": "检查负空间、视觉重量和开放边缘",
                "low_pressure_feasibility": "pass",
                "visual_support_goal": "辅助理解主张",
                "craft_ambition": "精致成品级",
            },
        )
        initial = [
            first_impression("audience_A", "先感到洞察与行动相互支撑，并共同促进目标达成"),
            first_impression("audience_B", "先理解两项能力属于一个连续过程，而不是彼此孤立"),
            first_impression("audience_C", "先看到两项能力结合后带来的决策价值"),
            first_impression("audience_D", "先感到观点成熟、可信且适合管理层讨论"),
            first_impression("audience_E", "先理解洞察能力与行动能力之间的互补关系"),
            first_impression("audience_F", "先感到目标达成依赖两项能力共同成立"),
            first_impression("open_G"),
            first_impression("open_H"),
        ]
        write_json(
            self.portfolio_path,
            {
                "layout_portfolio_contract_version": 5,
                "page_id": "02",
                "director_rationale": "该页适合保留若干双重点表达，同时用不同空间语法扩大探索面。",
                "styles": dict(zip(pipeline.QUICK_STYLES, initial)),
            },
        )
        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path.write_text(
            "## P02\nStable Quick8 content\n\n"
            "## P05\nFollower one\n\n## P08\nFollower two\n",
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

    def call(self, function, **kwargs):
        with redirect_stdout(io.StringIO()):
            return function(argparse.Namespace(**kwargs))

    def seal_source_snapshot(self) -> None:
        if (self.root / "state" / "source_snapshot.json").is_file():
            return
        state = pipeline.read_json(self.state_path)
        mode = state.get("run_mode")
        page_ids = ["02"]
        contracts = [self.content_path]
        if mode in {pipeline.FAST_4X3_MODE, pipeline.STRICT_4X3_MODE}:
            page_ids.extend(["05", "08"])
            anchor_contract = pipeline.read_json(self.content_path)
            for page_id in ("05", "08"):
                path = self.root / f"page_{page_id}.json"
                follower_contract = dict(anchor_contract)
                follower_contract["page_id"] = page_id
                write_json(path, follower_contract)
                contracts.append(path)
        pipeline.create_source_snapshot(
            project_dir=self.root,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=page_ids,
            content_contract_paths=contracts,
            asset_items=[],
            timestamp="2099-01-01T00:00:01+08:00",
        )

    def prepare(self) -> None:
        self.seal_source_snapshot()
        self.call(
            pipeline.command_prepare_anchors,
            project_dir=str(self.root),
            state=str(self.state_path),
            content_contract=str(self.content_path),
            overall_requirements="八种风格与排版，四深四浅",
            reference_images_json="[]",
            required_assets_json="[]",
            layout_portfolio=str(self.portfolio_path),
        )

    def result(self, style: str, error: str | None = None) -> dict:
        index = ord(style) - ord("A")
        return {
            "style": style,
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
            "worker_agent_id": f"agent-{style}",
            "agent_action_started_at": f"2026-07-19T10:00:{index:02d}+08:00",
            "agent_action_finished_at": f"2026-07-19T10:01:{index:02d}+08:00",
            "tool_call_id": None if error else f"tool-{style}",
            "savedPath": None if error else str(self.result_paths[style]),
            "tool_started_at": f"2026-07-19T10:00:{index + 10:02d}+08:00",
            "tool_finished_at": f"2026-07-19T10:00:{index + 40:02d}+08:00",
            "error": error,
        }

    def test_prepare_uses_director_portfolio_and_compact_prompts(self) -> None:
        self.prepare()
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["scheduler"]["dispatch_policy"], "direct_fanout")
        self.assertEqual(state["scheduler"]["root_dispatch_wave"], 8)
        self.assertEqual(
            state["scheduler"]["active_child_limit"],
            8,
        )
        self.assertEqual(
            Path(state["layout_portfolio_path"]).resolve(), self.portfolio_path.resolve()
        )
        self.assertEqual(
            state["quick8_candidate_policy"]["automatic_visual_retries_before_selection"],
            0,
        )
        for style in pipeline.QUICK_STYLES:
            job = pipeline.read_json(self.root / "style_jobs" / f"style_{style}.json")
            self.assertEqual(
                Path(job["anchor_page"]["output_target"]).resolve(),
                (self.root / "origin_image" / f"style_{style}_page_02.png").resolve(),
            )
            self.assertTrue(job["imagegen_prompt"])
            self.assertTrue(job["imagegen_input_fingerprint"])
            self.assertEqual(job["imagegen_prompt_contract_version"], 4)
            self.assertEqual(job["layout_direction"]["layout_contract_version"], 5)
            self.assertIn("成熟、精致、可直接使用", job["imagegen_prompt"])
            self.assertIn("视觉手段自由选择，只保留真正帮助理解内容的部分", job["imagegen_prompt"])
            self.assertIn("疏朗、有呼吸感", job["imagegen_prompt"])
            self.assertNotIn(pipeline.GROUPING_PROMPT_CUE, job["imagegen_prompt"])
            self.assertIn("需逐字准确上屏", job["imagegen_prompt"])
            self.assertIn("说明性内容（保持原意，可适度压缩措辞）", job["imagegen_prompt"])
            self.assertNotIn("信息密度", job["imagegen_prompt"])
            self.assertEqual(job["anchor_page"]["information_density_target"], "medium")
            self.assertIn("洞察能力与行动能力必须准确呈现", job["imagegen_prompt"])
            self.assertNotIn("若采用顺序表达", job["imagegen_prompt"])
            self.assertNotIn("八种风格与排版，四深四浅", job["imagegen_prompt"])
            self.assertNotIn("母结构", job["imagegen_prompt"])
            self.assertNotIn("阅读路径", job["imagegen_prompt"])
            self.assertNotIn("品牌/Logo", job["imagegen_prompt"])
            self.assertEqual(job["generation_rules"]["max_total_attempts_per_page"], 1)
            self.assertFalse(job["generation_rules"]["automatic_visual_retry_before_selection"])
            if style in "ABCDEF":
                self.assertEqual(
                    job["layout_direction"]["guidance_level"],
                    "semantic_first_impression",
                )
                self.assertIn("第一印象：", job["imagegen_prompt"])
                self.assertIn("不规定版式、媒介或构图", job["imagegen_prompt"])
            else:
                self.assertEqual(job["layout_direction"]["guidance_level"], "open")
                self.assertNotIn("第一印象：", job["imagegen_prompt"])
                self.assertNotIn(job["layout_direction"]["direction_id"], job["imagegen_prompt"])
            self.assertLess(len(job["imagegen_prompt"]), 650)
        prompt_g = pipeline.read_json(self.root / "style_jobs" / "style_G.json")["imagegen_prompt"]
        prompt_h = pipeline.read_json(self.root / "style_jobs" / "style_H.json")["imagegen_prompt"]
        self.assertEqual(prompt_g, prompt_h)
        legacy_path = self.root / "style_jobs" / "style_A.json"
        legacy_job = pipeline.read_json(legacy_path)
        legacy_job.pop("imagegen_prompt")
        legacy_job.pop("imagegen_input_fingerprint")
        write_json(legacy_path, legacy_job)
        self.prepare()  # 已有运行应直接恢复，不重编或覆盖旧任务。
        self.assertNotIn("imagegen_prompt", pipeline.read_json(legacy_path))

    def test_full_mode_keeps_single_wave_architecture(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["run_mode"] = "full_4x3_anchored"
        write_json(self.state_path, state)
        strict_directions = [
            first_impression("strict_A", "先理解两项能力共同支撑一个上位价值"),
            first_impression("strict_B", "先感到这是一个完整协同系统"),
            first_impression("strict_C"),
            first_impression("strict_D"),
        ]
        write_json(
            self.portfolio_path,
            {
                "layout_portfolio_contract_version": 6,
                "page_id": "02",
                "director_rationale": "Strict 4x3 保留两个语义首感席位与两个开放席位。",
                "styles": dict(zip(pipeline.FULL_STYLES, strict_directions)),
            },
        )
        self.prepare()
        prepared = pipeline.read_json(self.state_path)
        self.assertEqual(prepared["scheduler"]["dispatch_policy"], "single_wave")
        self.assertEqual(prepared["scheduler"]["requested_initial_wave"], 4)
        self.assertEqual(
            prepared["scheduler"]["active_child_limit"],
            9,
        )
        self.assertEqual(
            Path(prepared["layout_portfolio_path"]).resolve(),
            self.portfolio_path.resolve(),
        )
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        self.assertEqual(
            Path(job["anchor_page"]["output_target"]).resolve(),
            (self.root / "origin_image" / "style_A_page_02.png").resolve(),
        )
        self.assertEqual(job["imagegen_prompt_contract_version"], 4)
        self.assertEqual(job["layout_direction"]["layout_contract_version"], 6)
        self.assertIn("第一印象：", job["imagegen_prompt"])
        self.assertNotIn(pipeline.GROUPING_PROMPT_CUE, job["imagegen_prompt"])
        self.assertNotIn("总体要求", job["imagegen_prompt"])
        self.assertNotIn("视觉支持目标", job["imagegen_prompt"])
        self.assertNotIn("工艺目标", job["imagegen_prompt"])
        self.assertLess(len(job["imagegen_prompt"]), 650)

    def test_compact_v3_prompt_only_names_supplied_attachment_roles(self) -> None:
        content = pipeline.read_json(self.content_path)
        job = {
            "tone": "dark",
            "anchor_page": content,
            "layout_direction": {
                "layout_contract_version": 5,
                "direction_id": "reference_test",
                "guidance_level": "open",
            },
            "reference_images": [
                {
                    "path": str(self.image_path),
                    "reference_intent": {
                        "borrow": ["精致线稿", "克制配色"],
                        "do_not_copy": ["具体内容", "单页版式"],
                    },
                },
                {
                    "path": str(self.image_path),
                    "reference_intent": {
                        "borrow": ["编辑节奏", "不应进入提示的第四项"],
                        "do_not_copy": ["节点位置"],
                    },
                },
            ],
            "required_assets": [
                {"path": str(self.image_path), "role": "品牌 Logo"}
            ],
        }
        prompt = pipeline.compile_anchor_imagegen_prompt(job)
        self.assertIn("只借鉴核心感觉——精致线稿、克制配色、编辑节奏", prompt)
        self.assertNotIn("不应进入提示的第四项", prompt)
        self.assertIn("不要继承具体构图、版式、信息结构或原文内容", prompt)
        self.assertIn("附件3=品牌 Logo", prompt)
        self.assertNotIn(str(self.image_path), prompt)

    def test_english_contract_generates_english_slide_instruction(self) -> None:
        content = pipeline.read_json(self.content_path)
        content["language"] = "en-US"
        content["display_required"] = ["Operational clarity", "Faster decisions"]
        content["display_flexible"] = ["Both benefits reinforce one operating model"]
        content["spatial_generation_brief"] = pipeline.QUICK8_BREATHING_PROMPT_CUES["en"]["low"]
        content["prompt_semantic_guardrails"] = ["Keep both benefits at equal importance"]
        job = {
            "tone": "dark",
            "language": "en-US",
            "anchor_page": content,
            "layout_direction": {
                "layout_contract_version": 5,
                "direction_id": "english_test",
                "first_impression": "See one coherent operating model before its two benefits.",
            },
            "reference_images": [],
            "required_assets": [],
        }
        prompt = pipeline.compile_anchor_imagegen_prompt(job)
        self.assertIn("All on-slide copy must be in English", prompt)
        self.assertIn("Exact on-slide copy", prompt)
        self.assertIn("Required meaning (may be concisely rephrased)", prompt)
        self.assertIn("First impression:", prompt)
        self.assertNotIn(".. This only states", prompt)
        self.assertIn("Operational clarity", prompt)
        for chinese_label in ("视觉设定", "语义护栏", "用户约束", "创意方向", "参考：", "资产："):
            self.assertNotIn(chinese_label, prompt)

    def test_prepare_anchors_inherits_english_language_contract(self) -> None:
        content = pipeline.read_json(self.content_path)
        content["language"] = "en-US"
        content["display_required"] = ["Operational clarity", "Faster decisions"]
        content["display_flexible"] = ["Both benefits reinforce one operating model"]
        content["prompt_semantic_guardrails"] = [
            "Keep both benefits accurate and at equal importance"
        ]
        content["spatial_generation_brief"] = pipeline.QUICK8_BREATHING_PROMPT_CUES["en"]["low"]
        write_json(self.content_path, content)
        portfolio = pipeline.read_json(self.portfolio_path)
        for style in "ABCDEF":
            portfolio["styles"][style]["first_impression"] = (
                f"Audience first understands the content emphasis for option {style}"
            )
        write_json(self.portfolio_path, portfolio)
        self.prepare()
        state = pipeline.read_json(self.state_path)
        job = pipeline.read_json(self.root / "style_jobs" / "style_A.json")
        self.assertEqual(state["language"], "en-US")
        self.assertEqual(job["language"], "en-US")
        self.assertEqual(job["anchor_page"]["language"], "en-US")
        self.assertIn("All on-slide copy must be in English", job["imagegen_prompt"])
        self.assertNotIn("第一印象", job["imagegen_prompt"])
        self.assertNotIn("视觉设定", job["imagegen_prompt"])

    def test_missing_language_preserves_source_copy_without_chinese_default(self) -> None:
        content = pipeline.read_json(self.content_path)
        content.pop("language")
        content["display_required"] = ["Global reach", "本地执行"]
        content["spatial_generation_brief"] = pipeline.QUICK8_BREATHING_PROMPT_CUES["en"]["low"]
        job = {
            "tone": "light",
            "anchor_page": content,
            "layout_direction": {
                "layout_contract_version": 5,
                "direction_id": "source_test",
            },
            "reference_images": [],
            "required_assets": [],
        }
        prompt = pipeline.compile_anchor_imagegen_prompt(job)
        self.assertEqual(pipeline.resolve_job_language(job), "source")
        self.assertIn("Use exactly the language or languages present", prompt)
        self.assertIn("Global reach", prompt)
        self.assertIn("本地执行", prompt)
        self.assertNotIn("中文商务", prompt)

    def test_v3_rejects_nonstandard_or_verbose_spatial_brief(self) -> None:
        content = pipeline.read_json(self.content_path)
        content["prompt_contract_version"] = 3
        content["spatial_generation_brief"] = (
            "Low 不等于极简；保持低视觉压力、开放边缘、清楚入口和丰富表现力。"
        )
        with self.assertRaisesRegex(SystemExit, "统一短句"):
            pipeline.validate_dispatchable_content_contract(content, "fixture")

    def test_v3_accepts_legacy_low_brief_for_recovery(self) -> None:
        content = pipeline.read_json(self.content_path)
        content["prompt_contract_version"] = 3
        content["spatial_generation_brief"] = (
            "低视觉压力；入口清楚、组间有停顿、边缘开放。"
        )
        pipeline.validate_dispatchable_content_contract(content, "legacy fixture")

    def test_v3_keeps_explicit_default_as_second_profile(self) -> None:
        content = pipeline.read_json(self.content_path)
        content["prompt_contract_version"] = 3
        content["spatial_pressure_profile"] = "default"
        content["spatial_generation_brief"] = pipeline.SPATIAL_PROMPT_CUES["default"]
        content["low_pressure_feasibility"] = "not_applicable"
        pipeline.validate_dispatchable_content_contract(content, "fixture")

    def test_v4_unified_spatial_standard_is_density_neutral_and_compiled(self) -> None:
        content = pipeline.read_json(self.content_path)
        content.pop("spatial_pressure_profile")
        content.pop("low_pressure_feasibility")
        content.update(
            {
                "information_density_target": "high",
                "spatial_standard_version": 1,
                "spatial_generation_brief": pipeline.UNIFIED_SPATIAL_PROMPT_CUES["zh"],
                "spatial_qa_contract": "检查隐形网格、对齐、聚拢、重复、对比和有效负空间",
                "spatial_feasibility": "pass",
            }
        )
        pipeline.validate_dispatchable_content_contract(content, "unified fixture")
        job = {
            "tone": "dark",
            "anchor_page": content,
            "layout_direction": {
                "layout_contract_version": 5,
                "direction_id": "unified_test",
            },
            "reference_images": [],
            "required_assets": [],
        }
        prompt = pipeline.compile_anchor_imagegen_prompt(job)
        self.assertIn(pipeline.UNIFIED_SPATIAL_PROMPT_CUES["zh"], prompt)
        self.assertIn("隐形网格", prompt)
        self.assertIn("组内紧、组间松", prompt)
        self.assertIn("当前信息密度下自然、有呼吸感", prompt)
        self.assertNotIn("低视觉压力", prompt)
        self.assertNotIn("疏朗、有呼吸感", prompt)

    def test_v4_unified_spatial_standard_rejects_legacy_fields_or_overload(self) -> None:
        content = pipeline.read_json(self.content_path)
        content.update(
            {
                "spatial_standard_version": 1,
                "spatial_generation_brief": pipeline.UNIFIED_SPATIAL_PROMPT_CUES["zh"],
                "spatial_feasibility": "pass",
            }
        )
        with self.assertRaisesRegex(SystemExit, "不得继续写入"):
            pipeline.validate_dispatchable_content_contract(content, "mixed fixture")

        content.pop("spatial_pressure_profile")
        content.pop("low_pressure_feasibility")
        content["spatial_feasibility"] = "overloaded"
        with self.assertRaisesRegex(SystemExit, "spatial_feasibility=pass"):
            pipeline.validate_dispatchable_content_contract(content, "overloaded fixture")

    def test_v4_unified_spatial_standard_uses_english_brief_for_english_page(self) -> None:
        content = pipeline.read_json(self.content_path)
        content.pop("spatial_pressure_profile")
        content.pop("low_pressure_feasibility")
        content.update(
            {
                "language": "en-US",
                "display_required": ["Global reach", "Local execution"],
                "display_flexible": [],
                "spatial_standard_version": 1,
                "spatial_generation_brief": pipeline.UNIFIED_SPATIAL_PROMPT_CUES["en"],
                "spatial_feasibility": "pass",
            }
        )
        pipeline.validate_dispatchable_content_contract(content, "English unified fixture")
        job = {
            "tone": "light",
            "anchor_page": content,
            "layout_direction": {
                "layout_contract_version": 5,
                "direction_id": "unified_en_test",
            },
            "reference_images": [],
            "required_assets": [],
        }
        prompt = pipeline.compile_anchor_imagegen_prompt(job)
        self.assertIn(pipeline.UNIFIED_SPATIAL_PROMPT_CUES["en"], prompt)
        self.assertIn("actual information density", prompt)
        self.assertNotIn("low visual pressure", prompt.lower())

    def test_prepare_accepts_unified_contract_and_writes_it_into_every_job(self) -> None:
        content = pipeline.read_json(self.content_path)
        content.pop("spatial_pressure_profile")
        content.pop("low_pressure_feasibility")
        content.update(
            {
                "spatial_standard_version": 1,
                "spatial_generation_brief": pipeline.UNIFIED_SPATIAL_PROMPT_CUES["zh"],
                "spatial_qa_contract": "检查隐形网格、对齐、聚拢、重复、对比和有效负空间",
                "spatial_feasibility": "pass",
            }
        )
        write_json(self.content_path, content)
        self.prepare()
        for style in pipeline.QUICK_STYLES:
            job = pipeline.read_json(self.root / "style_jobs" / f"style_{style}.json")
            self.assertEqual(job["anchor_page"]["spatial_standard_version"], 1)
            self.assertEqual(job["anchor_page"]["spatial_feasibility"], "pass")
            self.assertNotIn("spatial_pressure_profile", job["anchor_page"])
            self.assertNotIn("low_pressure_feasibility", job["anchor_page"])
            self.assertIn(pipeline.UNIFIED_SPATIAL_PROMPT_CUES["zh"], job["imagegen_prompt"])
            self.assertTrue(
                job["candidate_policy"]["unified_spatial_standard_applies"]
            )

    def test_quick8_requires_main_agent_portfolio(self) -> None:
        self.seal_source_snapshot()
        with self.assertRaisesRegex(SystemExit, "主 Agent"):
            self.call(
                pipeline.command_prepare_anchors,
                project_dir=str(self.root),
                state=str(self.state_path),
                content_contract=str(self.content_path),
                overall_requirements="八种风格与排版，四深四浅",
                reference_images_json="[]",
                required_assets_json="[]",
                layout_portfolio=None,
            )

    def test_v5_enforces_guided_open_bounds_and_minimal_schema(self) -> None:
        portfolio = pipeline.read_json(self.portfolio_path)
        content = pipeline.read_json(self.content_path)
        state = pipeline.read_json(self.state_path)
        validated = pipeline.load_layout_portfolio(self.portfolio_path, state, content)
        self.assertEqual(validated["layout_portfolio_contract_version"], 5)
        self.assertEqual(validated["guided_seat_count"], 6)
        self.assertEqual(validated["open_seat_count"], 2)
        self.assertNotIn("repair_directions", validated)

        repeated_impression = pipeline.read_json(self.portfolio_path)
        repeated_impression["styles"]["B"]["first_impression"] = repeated_impression["styles"]["A"]["first_impression"]
        repeated_path = self.root / "repeated_impression_portfolio.json"
        write_json(repeated_path, repeated_impression)
        repeated = pipeline.load_layout_portfolio(repeated_path, state, content)
        self.assertEqual(repeated["guided_seat_count"], 6)

        too_few = pipeline.read_json(self.portfolio_path)
        for style in "DEF":
            too_few["styles"][style].pop("first_impression")
        too_few_path = self.root / "too_few_portfolio.json"
        write_json(too_few_path, too_few)
        with self.assertRaisesRegex(SystemExit, "4–6"):
            pipeline.load_layout_portfolio(too_few_path, state, content)

        too_many = pipeline.read_json(self.portfolio_path)
        too_many["styles"]["G"]["first_impression"] = "先理解这是另一种开放探索"
        too_many_path = self.root / "too_many_portfolio.json"
        write_json(too_many_path, too_many)
        with self.assertRaisesRegex(SystemExit, "4–6"):
            pipeline.load_layout_portfolio(too_many_path, state, content)

        legacy_field = pipeline.read_json(self.portfolio_path)
        legacy_field["styles"]["A"]["creative_direction"] = "双栏排版"
        legacy_field_path = self.root / "legacy_field_portfolio.json"
        write_json(legacy_field_path, legacy_field)
        with self.assertRaisesRegex(SystemExit, "只允许 direction_id"):
            pipeline.load_layout_portfolio(legacy_field_path, state, content)

        duplicate_id = pipeline.read_json(self.portfolio_path)
        duplicate_id["styles"]["B"]["direction_id"] = duplicate_id["styles"]["A"]["direction_id"]
        duplicate_id_path = self.root / "duplicate_id_portfolio.json"
        write_json(duplicate_id_path, duplicate_id)
        with self.assertRaisesRegex(SystemExit, "direction_id 与其他方向重复"):
            pipeline.load_layout_portfolio(duplicate_id_path, state, content)

        portfolio["repair_directions"] = []
        reserve_path = self.root / "v5_with_reserve.json"
        write_json(reserve_path, portfolio)
        with self.assertRaisesRegex(SystemExit, "不预设 repair_directions"):
            pipeline.load_layout_portfolio(reserve_path, state, content)

    def test_v4_portfolio_is_readable_for_recovery_but_rejected_for_fresh_quick8(self) -> None:
        content = pipeline.read_json(self.content_path)
        content["prompt_contract_version"] = 3
        content["spatial_generation_brief"] = pipeline.SPATIAL_PROMPT_CUES["low"]
        content.pop("display_flexible")
        write_json(self.content_path, content)
        state = pipeline.read_json(self.state_path)
        styles = {
            style: creative_direction(f"legacy_{style}", f"旧方向 {style}")
            for style in pipeline.QUICK_STYLES
        }
        legacy_path = self.root / "legacy_v4_portfolio.json"
        write_json(
            legacy_path,
            {
                "layout_portfolio_contract_version": 4,
                "page_id": "02",
                "director_rationale": "旧 Quick8 恢复合同",
                "styles": styles,
            },
        )
        validated = pipeline.load_layout_portfolio(legacy_path, state, content)
        self.assertEqual(validated["layout_portfolio_contract_version"], 4)
        self.seal_source_snapshot()
        with self.assertRaisesRegex(SystemExit, "新 quick_8x1 必须使用"):
            self.call(
                pipeline.command_prepare_anchors,
                project_dir=str(self.root),
                state=str(self.state_path),
                content_contract=str(self.content_path),
                overall_requirements="旧合同不得用于新 Quick8",
                reference_images_json="[]",
                required_assets_json="[]",
                layout_portfolio=str(legacy_path),
            )

    def test_page_completed_can_mark_quick_candidate_ready(self) -> None:
        record = pipeline.initial_page_state("anchor", "2026-07-19T10:00:00+08:00")
        pipeline.apply_page_event_effects(
            record,
            "page_completed",
            None,
            {"completion_status": "candidate_ready"},
        )
        self.assertEqual(record["status"], "candidate_ready")

    def test_v3_portfolio_remains_readable_for_legacy_recovery(self) -> None:
        all_directions = [
            legacy_direction(
                f"legacy_{index}",
                "双栏" if index < 2 else f"母结构{index}",
                f"版式变体{index}",
                f"阅读路径{index}",
                f"视觉重心{index}",
                f"图文策略{index}",
                f"差异键{index}",
            )
            for index in range(12)
        ]
        legacy_path = self.root / "legacy_v3_portfolio.json"
        write_json(
            legacy_path,
            {
                "layout_portfolio_contract_version": 3,
                "page_id": "02",
                "director_rationale": "旧项目恢复验证",
                "styles": dict(zip(pipeline.QUICK_STYLES, all_directions[:8])),
                "repair_directions": all_directions[8:],
            },
        )
        content = pipeline.read_json(self.content_path)
        content["prompt_contract_version"] = 3
        content["spatial_generation_brief"] = pipeline.SPATIAL_PROMPT_CUES["low"]
        validated = pipeline.load_layout_portfolio(
            legacy_path, pipeline.read_json(self.state_path), content
        )
        self.assertEqual(validated["layout_portfolio_contract_version"], 3)
        self.assertEqual(validated["styles"]["A"]["mother_structure"], "双栏")
        self.assertEqual(validated["styles"]["B"]["mother_structure"], "双栏")

    def test_v5_disables_preselection_diversity_repairs(self) -> None:
        self.prepare()
        with self.assertRaisesRegex(SystemExit, "不在用户选择前做差异返修"):
            self.call(
                pipeline.command_prepare_diversity_repairs,
                project_dir=str(self.root),
                styles="C,D",
                attempt=2,
                collision_details_json="{}",
            )

    def test_partial_settlement_is_idempotent_and_qa_can_overlap(self) -> None:
        self.prepare()
        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            styles="A,B,C,D,E,F,G,H",
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-07-19T10:00:00+08:00",
            agent_map_json=None,
        )
        dark_results = [self.result(style) for style in "ABC"] + [
            self.result("D", "artifact_handoff_unresolved")
        ]
        dark_path = self.root / "dark_results.json"
        write_json(dark_path, dark_results)
        kwargs = {
            "state": str(self.state_path),
            "results_file": str(dark_path),
            "expected_styles": "A,B,C,D",
            "timestamp": "2026-07-19T10:02:00+08:00",
        }
        self.call(pipeline.command_settle_wave, **kwargs)
        first_state = pipeline.read_json(self.state_path)
        first_event_count = len(first_state["events"])
        self.assertEqual(first_state["styles"]["A"]["pages"]["02"]["status"], "generated")
        self.assertEqual(
            first_state["styles"]["D"]["pages"]["02"]["failure_reason"],
            "artifact_handoff_unresolved",
        )
        self.assertEqual(len(first_state["scheduler"]["recovery_queue"]), 1)
        self.call(pipeline.command_settle_wave, **kwargs)
        self.assertEqual(len(pipeline.read_json(self.state_path)["events"]), first_event_count)

        self.call(
            pipeline.command_record_dispatch_wave,
            state=str(self.state_path),
            tasks_json=json.dumps(
                [
                    {
                        "style": "D",
                        "page_id": "02",
                        "action": "recover_artifact",
                        "attempt": 1,
                    }
                ]
            ),
            styles=None,
            page_id=None,
            action="generate_anchor",
            attempt=1,
            timestamp="2026-07-19T10:02:00+08:00",
            agent_map_json=json.dumps({"D/02/recover_artifact": "agent-D-recovery"}),
            backpressure_reason=None,
        )
        d_path = self.root / "d_result.json"
        recovered = self.result("D")
        recovered.update(
            {
                "action": "recover_artifact",
                "source_action": "generate_anchor",
                "worker_agent_id": "agent-D-recovery",
                "agent_action_started_at": "2026-07-19T10:02:00+08:00",
                "agent_action_finished_at": "2026-07-19T10:02:10+08:00",
                "recovery_started_at": "2026-07-19T10:02:01+08:00",
                "recovery_finished_at": "2026-07-19T10:02:09+08:00",
                "recovery_method": "same_worker",
            }
        )
        write_json(d_path, [recovered])
        self.call(
            pipeline.command_settle_wave,
            state=str(self.state_path),
            results_file=str(d_path),
            expected_styles="D",
            timestamp="2026-07-19T10:02:10+08:00",
        )
        recovered_state = pipeline.read_json(self.state_path)
        recovered_record = recovered_state["styles"]["D"]["pages"]["02"]
        self.assertEqual(recovered_record["recovery_status"], "recovered")
        self.assertEqual(recovered_record["recovery_attempt_count"], 1)
        self.assertEqual(recovered_record["attempt_count"], 1)
        with self.assertRaisesRegex(SystemExit, "不创建分组 QA Agent"):
            self.call(
                pipeline.command_prepare_quick_qa,
                project_dir=str(self.root),
                state=str(self.state_path),
                group="dark",
            )
        self.assertEqual(len(pipeline.read_json(self.state_path)["scheduler"]["recovery_queue"]), 0)
        self.assertFalse((self.root / "qa_jobs" / "quick_dark.json").exists())
        self.assertFalse((self.root / "qa_jobs" / "quick_light.json").exists())


if __name__ == "__main__":
    unittest.main()
