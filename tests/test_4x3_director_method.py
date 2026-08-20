from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_fast4x3_pipeline import Fast4x3PipelineTest, write_json


ROOT = Path(__file__).resolve().parents[1]
MERGE_PATH = ROOT / "scripts" / "merge_4x3_director_inputs.py"
SPEC = importlib.util.spec_from_file_location("merge_4x3_director_inputs_test", MERGE_PATH)
assert SPEC and SPEC.loader
merge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merge)
pipeline = merge.pc


def raw_content(page_id: str) -> dict:
    return {
        "content_contract_version": 2,
        "prompt_contract_version": 4,
        "page_id": page_id,
        "language": "zh-CN",
        "source_facts": [f"{page_id} 的已确认测试事实"],
        "display_required": [f"页面 {page_id}", f"指标 {page_id}"],
        "display_flexible": [f"{page_id} 的必达解释关系"],
        "display_supporting": [],
        "flexible_story": f"用自然叙事完整解释 {page_id} 的必达关系。",
        "information_density_target": "medium",
        "semantic_invariants": [f"{page_id} 不得串页"],
        "forbidden_interpretations": [],
        "prompt_semantic_guardrails": [],
        "prompt_user_constraints": [],
        "content_resolution": {"status": "not_needed", "reason": "测试合同完整"},
    }


def creative_intent(page_id: str) -> dict:
    return {
        "creative_intent_contract_version": 1,
        "page_id": page_id,
        "relationship_thesis": f"REL-{page_id}：让观众先看见本页独有的主从关系。",
        "visual_quality_intent": "成熟、克制、具有编辑判断的工业商务视觉。",
        "visual_support_goal": "用视觉组织本页关系，而不是装饰名词。",
        "craft_ambition": "成品级字体、材质与图文整合。",
    }


def style_direction(style: str, index: int) -> dict:
    entries = ("single_focus", "paired_contrast", "path", "hierarchy")
    regions = ("unified_field", "asymmetric_split", "staged_path", "layered_depth")
    evidence = ("integrated", "annotated", "satellite", "none")
    activities = ("restrained", "balanced", "balanced", "expressive")
    return {
        "direction_id": f"family_{style.lower()}",
        "visual_thesis": f"锚点页在 {style} 家族中的独有可见命题。",
        "style_family_thesis": f"{style} 家族以独特字体、材质和图像工艺形成跨页身份。",
        "relationship_representation_family": f"relationship_family_{style.lower()}",
        "craft_axis": f"craft_axis_{style.lower()} 的独特图像与排版工艺",
        "visual_activity_mode": activities[index],
        "attention_strategy": f"{style} 先聚焦主关系，证据安静从属。",
        "spatial_topology": {
            "primary_entry": entries[index],
            "region_logic": regions[index],
            "evidence_attachment": evidence[index],
            "spatial_topology_intent": f"{style} 使用开放且不固定坐标的空间关系。",
        },
        "adaptation_principle": f"{style} 随页面关系改变构图，但不改变家族工艺。",
        "continuity_invariants": [
            f"{style} 的色彩与材质家族",
            f"{style} 的字体气质与图像完成度",
        ],
    }


class FourByThreeDirectorMethodTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fast4x3PipelineTest("test_v6_v4_guided_open_anchor_contract_is_direct_and_soft")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        # The reused fixture seals its legacy contracts during setUp. This test
        # models a fresh pre-dispatch run whose director merge happens before
        # the one allowed snapshot seal.
        legacy_snapshot = self.fixture.root / "state" / "source_snapshot.json"
        legacy_snapshot.unlink()
        self.input_dir = self.fixture.root / "state" / "director_inputs"
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.pages = ["02", "05", "08"]
        self.content_bundle = self.input_dir / "content_bundle.json"
        self.assets_bundle = self.input_dir / "required_assets_by_page.json"
        self.visual_system = self.input_dir / "visual_system.json"
        write_json(
            self.content_bundle,
            {
                "four_by_three_content_bundle_version": 1,
                "page_order": self.pages,
                "pages": {page: raw_content(page) for page in self.pages},
            },
        )
        write_json(
            self.assets_bundle,
            {
                "four_by_three_assets_bundle_version": 1,
                "page_order": self.pages,
                "pages": {page: [] for page in self.pages},
            },
        )
        write_json(
            self.visual_system,
            {
                "four_by_three_visual_system_version": 1,
                "page_order": self.pages,
                "anchor_page_id": "02",
                "background_tone_policy": {
                    "mode": "uniform",
                    "tone": "light",
                    "source": "primary_style_reference",
                },
                "creative_intents": {
                    page: creative_intent(page) for page in self.pages
                },
                "layout_portfolio": {
                    "layout_portfolio_contract_version": 6,
                    "art_direction_contract_version": 1,
                    "style_family_portfolio_version": 1,
                    "visual_activity_portfolio_version": 1,
                    "spatial_topology_portfolio_version": 1,
                    "page_id": "02",
                    "director_rationale": "四个视觉家族跨三页保持身份并按关系适配。",
                    "styles": {
                        style: style_direction(style, index)
                        for index, style in enumerate("ABCD")
                    },
                },
            },
        )

    def merge_inputs(self) -> dict:
        return merge.merge_bundle(
            state_path=self.fixture.state_path,
            content_bundle_path=self.content_bundle,
            assets_bundle_path=self.assets_bundle,
            visual_system_path=self.visual_system,
            content_output_dir=self.fixture.content_dir,
            layout_output_path=self.fixture.portfolio_path,
        )

    def reseal_source(self) -> None:
        pipeline.create_source_snapshot(
            project_dir=self.fixture.root,
            state_path=self.fixture.state_path,
            source_path=self.fixture.source_path,
            page_ids=self.pages,
            content_contract_paths=[
                self.fixture.content_dir / f"page_{page}.json" for page in self.pages
            ],
            asset_items=[],
            timestamp="2099-01-01T00:00:02+08:00",
        )

    def test_three_director_merge_and_family_projection_reach_followers(self) -> None:
        merged = self.merge_inputs()
        self.assertEqual(merged["page_order"], self.pages)
        tone_state = pipeline.read_json(self.fixture.state_path)
        self.assertEqual(
            tone_state["tone_overrides"],
            {style: "light" for style in "ABCD"},
        )
        self.reseal_source()
        self.fixture.prepare_anchors()
        state = pipeline.read_json(self.fixture.state_path)
        self.assertEqual(state["fast4x3_candidate_policy"]["version"], 3)
        self.assertTrue(state["fast4x3_candidate_policy"]["three_director_method"])

        anchor_job = pipeline.read_json(self.fixture.root / "style_jobs" / "style_A.json")
        self.assertIn("A 家族", anchor_job["imagegen_prompt"])
        self.assertIn("REL-02", anchor_job["imagegen_prompt"])
        self.assertEqual(
            anchor_job["creative_brief_projection"]["style_family_portfolio_version"]
            if "style_family_portfolio_version" in anchor_job["creative_brief_projection"]
            else anchor_job["layout_direction"]["style_family_portfolio_version"],
            1,
        )

        task = {"style": "A", "page_id": "02", "action": "generate_anchor"}
        self.fixture.dispatch([task], minute=0)
        self.fixture.settle([self.fixture.result("A", "02", "generate_anchor")], minute=1)
        self.fixture.call(
            pipeline.command_prepare_fast_followers,
            project_dir=str(self.fixture.root),
            state=str(self.fixture.state_path),
            content_contract_dir=str(self.fixture.content_dir),
            styles="A",
        )
        style_contract = pipeline.read_json(
            self.fixture.root / "style_contracts" / "style_A.json"
        )
        self.assertEqual(style_contract["style_contract_version"], 5)
        self.assertNotIn("visual_thesis", style_contract)
        self.assertEqual(
            style_contract["anchor_visual_thesis"],
            "锚点页在 A 家族中的独有可见命题。",
        )
        follower = pipeline.read_json(
            self.fixture.root / "style_page_jobs" / "style_A" / "page_05.json"
        )
        prompt = follower["imagegen_prompt"]
        self.assertIn("REL-05", prompt)
        self.assertNotIn("REL-02", prompt)
        self.assertIn("A 家族", prompt)
        self.assertIn("继承家族但不得复制锚点构图", prompt)
        self.assertNotIn("relationship_family_a", prompt)
        self.assertNotIn("A 先聚焦主关系", prompt)
        self.assertNotIn("A 使用开放且不固定坐标", prompt)
        self.assertEqual(follower["anchor_input_mode"], "raster")
        self.assertEqual(len(follower["reference_images"]), 1)
        self.assertEqual(
            follower["reference_images"][0]["path"],
            str(self.fixture.image_path.resolve()),
        )
        self.assertIn("风格参考（附件1）", prompt)
        self.assertIn("本页标题、事实、对象和关系只来自当前页内容合同", prompt)
        self.assertIn(
            str(self.fixture.image_path.resolve()),
            follower["imagegen_referenced_paths"],
        )
        projection = follower["creative_brief_projection"]
        self.assertEqual(projection["relationship_thesis"], creative_intent("05")["relationship_thesis"])
        self.assertEqual(projection["style_family_thesis"], style_contract["style_family_thesis"])

    def test_merge_rejects_missing_story_and_more_than_four_page_assets(self) -> None:
        content = json.loads(self.content_bundle.read_text(encoding="utf-8"))
        content["pages"]["05"]["flexible_story"] = ""
        write_json(self.content_bundle, content)
        with self.assertRaisesRegex(SystemExit, "05.*flexible_story"):
            self.merge_inputs()

        content["pages"]["05"] = raw_content("05")
        write_json(self.content_bundle, content)
        assets = json.loads(self.assets_bundle.read_text(encoding="utf-8"))
        assets["pages"]["05"] = [
            {"path": str(self.fixture.image_path.resolve()), "role": f"evidence_{index}"}
            for index in range(5)
        ]
        write_json(self.assets_bundle, assets)
        with self.assertRaisesRegex(SystemExit, "05.*0-4"):
            self.merge_inputs()

    def test_asset_merge_accepts_simple_director_envelope(self) -> None:
        assets = json.loads(self.assets_bundle.read_text(encoding="utf-8"))
        assets["pages"]["05"] = {
            "assets": [
                {
                    "path": str(self.fixture.image_path.resolve()),
                    "role": "source_evidence",
                }
            ]
        }
        write_json(self.assets_bundle, assets)
        self.merge_inputs()
        contract = pipeline.read_json(self.fixture.content_dir / "page_05.json")
        self.assertEqual(len(contract["required_page_assets"]), 1)

    def test_asset_merge_prefers_documented_style_slots_route(self) -> None:
        assets = json.loads(self.assets_bundle.read_text(encoding="utf-8"))
        assets["pages"]["05"] = [
            {
                "path": str(self.fixture.image_path.resolve()),
                "role": "source_evidence",
                "style_slots": ["A", "B"],
                "styles": ["C", "D"],
            }
        ]
        write_json(self.assets_bundle, assets)
        self.merge_inputs()
        contract = pipeline.read_json(self.fixture.content_dir / "page_05.json")
        item = contract["required_page_assets"][0]
        self.assertEqual(item["style_slots"], ["A", "B"])
        self.assertNotIn("styles", item)

    def test_merge_binds_titles_to_authoritative_snapshot(self) -> None:
        content = json.loads(self.content_bundle.read_text(encoding="utf-8"))
        for page in self.pages:
            content["pages"][page]["title"] = f"标题,{page}?"
            content["pages"][page]["display_required"].insert(0, f"标题,{page}?")
        write_json(self.content_bundle, content)
        snapshot = self.input_dir / "authoritative_snapshot_source.json"
        write_json(
            snapshot,
            {
                "four_by_three_snapshot_source_version": 1,
                "page_order": self.pages,
                "pages": {
                    page: {
                        "page_id": page,
                        "canonical_title": f"标题，{page}？",
                        "normalized_source": f"页面 {page} 的冻结权威来源",
                    }
                    for page in self.pages
                },
            },
        )
        self.merge_inputs()
        for page in self.pages:
            contract = pipeline.read_json(self.fixture.content_dir / f"page_{page}.json")
            self.assertEqual(contract["title"], f"标题，{page}？")
            self.assertEqual(contract["display_required"][0], f"标题，{page}？")
            self.assertEqual(contract["source_title_binding"]["status"], "bound")

    def test_merge_accepts_harmless_layout_version_alias(self) -> None:
        visual = json.loads(self.visual_system.read_text(encoding="utf-8"))
        portfolio = visual["layout_portfolio"]
        portfolio["layout_portfolio_version"] = portfolio.pop(
            "layout_portfolio_contract_version"
        )
        portfolio.pop("director_rationale")
        write_json(self.visual_system, visual)
        self.merge_inputs()
        merged = pipeline.read_json(self.fixture.portfolio_path)
        self.assertEqual(merged["layout_portfolio_contract_version"], 6)
        self.assertNotIn("layout_portfolio_version", merged)
        self.assertTrue(merged["director_rationale"])

    def test_merge_normalizes_source_density_labels(self) -> None:
        content = json.loads(self.content_bundle.read_text(encoding="utf-8"))
        content["pages"]["02"]["information_density_target"] = "高｜一级+完整指定二级"
        content["pages"]["05"]["information_density_target"] = "中｜一级+必要二级"
        content["pages"]["08"]["information_density_target"] = "低｜仅一级"
        write_json(self.content_bundle, content)
        self.merge_inputs()
        self.assertEqual(
            [
                pipeline.read_json(self.fixture.content_dir / f"page_{page}.json")[
                    "information_density_target"
                ]
                for page in self.pages
            ],
            ["high", "medium", "low"],
        )

    def test_merge_supplies_missing_fixed_creative_intent_version(self) -> None:
        visual = json.loads(self.visual_system.read_text(encoding="utf-8"))
        for intent in visual["creative_intents"].values():
            intent.pop("creative_intent_contract_version")
        write_json(self.visual_system, visual)
        self.merge_inputs()
        for page in self.pages:
            contract = pipeline.read_json(self.fixture.content_dir / f"page_{page}.json")
            self.assertEqual(
                contract["relationship_thesis"],
                creative_intent(page)["relationship_thesis"],
            )

    def test_follower_drops_page_asset_already_supplied_by_shared_inputs(self) -> None:
        self.merge_inputs()
        page_job = pipeline.read_json(self.fixture.content_dir / "page_05.json")
        anchor_path = self.fixture.root / "manual_anchor.png"
        anchor_path.write_bytes(self.fixture.image_path.read_bytes())
        duplicate = {
            "path": str(self.fixture.image_path.resolve()),
            "role": "page_logo",
        }
        page_job["required_page_assets"] = [duplicate]
        contract = {
            "style_contract_version": 5,
            "style_family_portfolio_version": 1,
            "style_slot": "A",
            "tone": "dark",
            "language": "zh-CN",
            "style_family_thesis": "A 家族",
            "craft_axis": "精密工艺",
            "visual_activity_mode": "restrained",
            "adaptation_principle": "按本页关系适配",
            "continuity_invariants": ["一致字体", "一致材质"],
            "anchor": {
                "path": str(anchor_path.resolve()),
                "role": "primary_style_anchor",
            },
            "required_assets": [
                {
                    "path": str(self.fixture.image_path.resolve()),
                    "role": "deck_title_system_logo",
                }
            ],
        }
        bundle = pipeline.compile_follower_prompt_bundle_v4(page_job, contract)
        self.assertEqual(len(bundle["required_assets"]), 1)
        self.assertEqual(bundle["required_page_assets"], [])
        self.assertEqual(
            bundle["imagegen_referenced_paths"],
            [str(anchor_path.resolve()), str(self.fixture.image_path.resolve())],
        )

    def test_v5_follower_uses_text_family_only_when_assets_fill_attachment_cap(self) -> None:
        self.merge_inputs()
        page_job = pipeline.read_json(self.fixture.content_dir / "page_05.json")
        anchor_path = self.fixture.root / "cap_anchor.png"
        anchor_path.write_bytes(self.fixture.image_path.read_bytes())
        asset_paths = []
        for index in range(pipeline.IMAGEGEN_MAX_REFERENCED_PATHS):
            path = self.fixture.root / f"cap_asset_{index}.png"
            path.write_bytes(self.fixture.image_path.read_bytes())
            asset_paths.append(path)
        page_job["required_page_assets"] = [
            {"path": str(path.resolve()), "role": f"page_asset_{index}"}
            for index, path in enumerate(asset_paths)
        ]
        contract = {
            "style_contract_version": 5,
            "style_family_portfolio_version": 1,
            "style_slot": "A",
            "tone": "dark",
            "language": "zh-CN",
            "style_family_thesis": "A 家族",
            "craft_axis": "精密工艺",
            "visual_activity_mode": "restrained",
            "adaptation_principle": "按本页关系适配",
            "continuity_invariants": ["一致字体", "一致材质"],
            "anchor": {"path": str(anchor_path.resolve())},
            "required_assets": [],
        }
        bundle = pipeline.compile_follower_prompt_bundle_v4(page_job, contract)
        self.assertEqual(bundle["anchor_input_mode"], "text_family")
        self.assertEqual(bundle["reference_images"], [])
        self.assertNotIn(str(anchor_path.resolve()), bundle["imagegen_referenced_paths"])
        self.assertEqual(
            bundle["imagegen_referenced_paths"],
            [str(path.resolve()) for path in asset_paths],
        )

    def test_asset_merge_rejects_planning_document_as_image_input(self) -> None:
        evidence = self.fixture.root / "planning_evidence.pdf"
        evidence.write_bytes(b"%PDF-1.4\n")
        assets = json.loads(self.assets_bundle.read_text(encoding="utf-8"))
        assets["pages"]["02"] = [
            {"path": str(evidence.resolve()), "role": "source_evidence"}
        ]
        write_json(self.assets_bundle, assets)
        with self.assertRaisesRegex(SystemExit, "不是 ImageGen 支持的位图"):
            self.merge_inputs()

    def test_asset_director_renders_only_explicit_required_source_page(self) -> None:
        prompt = (ROOT / "prompts" / "4x3-chrome-assets-director.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("只把那一个指定页渲染", prompt)
        self.assertIn("只用于事实/对象准确性，不作为风格参考", prompt)
        self.assertIn("不要预览或渲染整份文档", prompt)

    def test_asset_directors_do_not_narrow_required_assets_for_aesthetics(self) -> None:
        for name in (
            "fast8-chrome-assets-director.md",
            "4x3-chrome-assets-director.md",
            "selected-style-chrome-assets-director.md",
        ):
            prompt = (ROOT / "prompts" / name).read_text(encoding="utf-8")
            self.assertIn("不得仅因审美、对比度", prompt)
            self.assertIn("增加合适承载底", prompt)

    def test_free_page_selection_prefers_open_visual_room_for_8x1_and_4x3(self) -> None:
        contract = (ROOT / "references" / "4x3运行合同.md").read_text(
            encoding="utf-8"
        )
        fast8 = (ROOT / "references" / "Fast8准备与派发.md").read_text(
            encoding="utf-8"
        )
        for text in (contract, fast8):
            self.assertIn("仅限自由选页", text)
            self.assertIn("用户指定页码或测试目的时逐字服从", text)
            self.assertIn("视觉解法尚未被固定图表", text)
        self.assertIn("一张数据/对比页检验信息组织", contract)
        self.assertIn("一张复杂架构或高密度页检验复杂承压", contract)
        self.assertIn("不建立评分器", contract)
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/4x3运行合同.md", skill)

    def test_fast8_preflight_enumerates_only_current_page_required_assets(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        fast8 = (ROOT / "references" / "Fast8准备与派发.md").read_text(
            encoding="utf-8"
        )
        for text in (skill, fast8):
            self.assertIn("冻结前输入枚举", text)
            self.assertIn("页级资产索引", text)
            self.assertIn("不扫描其他页面", text)
        self.assertIn("第一项状态写入", fast8)
        self.assertIn("不启动 Director/Reviewer", fast8)
        self.assertIn("全部必用图片", fast8)

    def test_new_run_does_not_reuse_director_agent_conversations(self) -> None:
        contract = (ROOT / "references" / "4x3运行合同.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("每个新 `project_dir` 都创建三位新的 `fork_turns=none` 短导演", contract)
        self.assertIn("不复用历史会话或旧路径", contract)

    def test_4x3_director_prompts_inline_hard_schema_bounds(self) -> None:
        content_prompt = (
            ROOT / "prompts" / "4x3-content-contract-director.md"
        ).read_text(encoding="utf-8")
        visual_prompt = (
            ROOT / "prompts" / "4x3-visual-system-director.md"
        ).read_text(encoding="utf-8")
        self.assertIn("没有内容时写 `[]`，不得省略", content_prompt)
        self.assertIn("两者各为 0–3 条", content_prompt)
        self.assertIn("不得输出第 4 条", content_prompt)
        self.assertIn(
            "primary_entry=single_focus|paired_contrast|path|network|field|hierarchy|radial|evidence_hero",
            visual_prompt,
        )
        self.assertIn(
            "region_logic=unified_field|asymmetric_split|staged_path|distributed_nodes|layered_depth|annotated_object|geographic_spread|editorial_sequence",
            visual_prompt,
        )
        self.assertIn(
            "evidence_attachment=integrated|annotated|satellite|quiet_band|none",
            visual_prompt,
        )
        self.assertIn("`director_rationale` 是顶层短说明", visual_prompt)
        self.assertIn("必须不超过 240 个字符", visual_prompt)
        self.assertIn("不要等确定性脚本截断", visual_prompt)

    def test_three_page_snapshot_json_is_source_file_not_text_fragment(self) -> None:
        self.merge_inputs()
        state = pipeline.read_json(self.fixture.state_path)
        state.pop("source_snapshot_path", None)
        state.pop("source_snapshot_sha256", None)
        pipeline.atomic_write_json(self.fixture.state_path, state)
        contracts = [
            str(self.fixture.content_dir / f"page_{page}.json")
            for page in self.pages
        ]
        snapshot_source = self.input_dir / "authoritative_snapshot_source.json"
        write_json(
            snapshot_source,
            {
                "four_by_three_snapshot_source_version": 1,
                "page_order": self.pages,
                "pages": {
                    page: {
                        "page_id": page,
                        "normalized_source": f"页面 {page} 的冻结权威来源",
                    }
                    for page in self.pages
                },
            },
        )
        result = self.fixture.call(
            pipeline.command_prepare_anchors,
            project_dir=str(self.fixture.root),
            state=str(self.fixture.state_path),
            content_contract=contracts[0],
            overall_requirements="四套成品级候选",
            reference_images_json="[]",
            required_assets_json="[]",
            required_assets_file=None,
            global_chrome_contract=None,
            source_file=str(snapshot_source),
            source_page_ids=",".join(self.pages),
            source_fragment_file=None,
            source_fragment_authority="extractor_aid",
            snapshot_content_contracts_json=json.dumps(contracts),
            source_snapshot_timestamp="2099-01-01T00:00:02+08:00",
            layout_portfolio=str(self.fixture.portfolio_path),
            overview_python=None,
        )
        self.assertEqual(result["style_jobs"], 4)
        snapshot = pipeline.read_json(
            self.fixture.root / "state" / "source_snapshot.json"
        )
        self.assertEqual(snapshot["page_ids"], self.pages)


if __name__ == "__main__":
    unittest.main()
