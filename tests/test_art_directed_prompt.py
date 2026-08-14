from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_control.py"
SPEC = importlib.util.spec_from_file_location("pipeline_control_art_direction", MODULE_PATH)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def add_valid_spatial_topologies(styles: dict[str, dict[str, object]]) -> None:
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
        styles[style]["spatial_topology"] = {
            "primary_entry": primary_entries[index],
            "region_logic": region_logics[index],
            "evidence_attachment": evidence_modes[index],
            "spatial_topology_intent": f"候选 {style} 使用独立空间组织。",
        }


class ArtDirectedPromptTest(unittest.TestCase):
    def test_recovery_worker_prompts_separate_recovery_and_original_tool_times(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative in ("prompts/style-worker.md", "prompts/style-follower-worker.md"):
            text = (root / relative).read_text(encoding="utf-8")
            self.assertIn("绝不能复制原始生成回合时间", text)
            self.assertIn("tool_started_at|tool_finished_at", text)

    def test_fast8_art_direction_compiles_relationship_and_craft(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shawn_art_direction_") as temp:
            root = Path(temp)
            content = {
                "content_contract_version": 2,
                "prompt_contract_version": 4,
                "language": "zh-CN",
                "page_id": "18",
                "display_required": ["页面标题", "结论金句"],
                "display_flexible": [
                    "三个相关能力属于同一责任体系。",
                    "客户获得连续的问题解决路径。",
                ],
                "flexible_story": "三个能力共同形成一条连续的问题解决路径。",
                "prompt_semantic_guardrails": ["三个能力不得被误画成互不相关的清单"],
                "prompt_user_constraints": [],
                "visual_quality_intent": "专业克制、优雅高级，具有真实工业质感。",
                "relationship_thesis": (
                    "三个能力是同一整体的连接面，并共同收束到一个客户结果。"
                ),
                "spatial_pressure_profile": "low",
                "spatial_generation_brief": pipeline.QUICK8_BREATHING_PROMPT_CUES[
                    "zh"
                ]["low"],
            }
            styles = {}
            modes = [
                "restrained",
                "balanced",
                "restrained",
                "expressive",
                "restrained",
                "balanced",
                "restrained",
                "balanced",
            ]
            for index, style in enumerate(pipeline.QUICK_STYLES):
                styles[style] = {
                    "direction_id": f"run_local_{style}",
                    "visual_thesis": f"用第{index + 1}种可见关系解释整体与结果。",
                    "relationship_representation_family": f"关系表达家族 {index + 1}",
                    "craft_axis": f"第{index + 1}种独立材质、光感与图像工艺。",
                    "visual_activity_mode": modes[index],
                    "attention_strategy": f"候选 {style} 只保留一个主导入口，证据层保持安静。",
                }
            add_valid_spatial_topologies(styles)
            portfolio = {
                "layout_portfolio_contract_version": 7,
                "art_direction_contract_version": 1,
                "visual_activity_portfolio_version": 1,
                "spatial_topology_portfolio_version": 1,
                "page_id": "18",
                "director_rationale": "用关系命题与工艺轴扩张真实选择面。",
                "styles": styles,
            }
            portfolio_path = root / "layout_portfolio.json"
            write_json(portfolio_path, portfolio)

            bundle = pipeline.load_layout_portfolio(
                portfolio_path,
                {"run_mode": pipeline.FAST8_MODE, "run_id": "test"},
                content,
                expected_styles=pipeline.QUICK_STYLES,
            )
            seed = bundle["styles"]["A"]
            prompt = pipeline.compile_minimal_prompt_v4(
                {
                    "run_mode": pipeline.FAST8_MODE,
                    "imagegen_prompt_contract_version": (
                        pipeline.CURRENT_FAST8_IMAGEGEN_PROMPT_VERSION
                    ),
                    "tone": "dark",
                    "language": "zh-CN",
                    "anchor_page": content,
                    "layout_direction": seed,
                    "reference_images": [],
                    "required_assets": [],
                }
            )

            self.assertEqual(bundle["art_direction_contract_version"], 1)
            self.assertIn("审美与完成度意图", prompt)
            self.assertIn("文字锚点（逐字准确，仅用于命名，不代表组件清单）", prompt)
            self.assertIn("内容简报（完整传达原意", prompt)
            self.assertIn("关系综合", prompt)
            self.assertIn("本候选的可见视觉命题", prompt)
            self.assertIn("视觉活跃度", prompt)
            self.assertIn("注意力策略", prompt)
            self.assertIn("支撑证据收束", prompt)
            self.assertIn("图文整合", prompt)
            self.assertIn("不要把内容合同的字段边界直接翻译成默认的左右分区", prompt)
            self.assertIn("内容本身确实要求这些结构，可以使用", prompt)
            self.assertIn("图像工艺与材质导演", prompt)
            self.assertIn("未提供的真实产品、项目或交付事实", prompt)
            self.assertIn("具有特定事实指向的具象对象", prompt)
            self.assertNotIn("\n- 页面标题", prompt)
            self.assertNotIn("开放性创作启发", prompt)
            self.assertIn("最高优先级语义护栏", prompt)
            self.assertIn("三个能力不得被误画成互不相关的清单", prompt)
            self.assertIn("不得用连线、箭头、树枝、嵌套或空间从属补出", prompt)
            projection = pipeline.build_creative_brief_projection(content, seed)
            self.assertEqual(projection["literal_anchors"], ["页面标题", "结论金句"])
            self.assertEqual(
                projection["flexible_story"],
                "三个能力共同形成一条连续的问题解决路径。",
            )
            self.assertEqual(
                projection["flexible_story_source"], "explicit_director_story"
            )
            self.assertEqual(
                projection["relationship_thesis"],
                "三个能力是同一整体的连接面，并共同收束到一个客户结果。",
            )
            self.assertEqual(projection["craft_axis"], seed["craft_axis"])
            self.assertEqual(
                projection["relationship_representation_family"],
                seed["relationship_representation_family"],
            )
            self.assertEqual(projection["visual_activity_mode"], "restrained")
            self.assertTrue(projection["attention_strategy"])

    def test_art_direction_requires_unique_craft_axes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shawn_art_direction_bad_") as temp:
            root = Path(temp)
            content = {
                "prompt_contract_version": 4,
                "page_id": "02",
                "prompt_semantic_guardrails": [],
                "visual_quality_intent": "高级、克制。",
                "relationship_thesis": "所有内容收束到一个上位结果。",
                "flexible_story": "所有必要事实共同支持一个结果。",
            }
            styles = {
                style: {
                    "direction_id": f"id_{style}",
                    "visual_thesis": f"命题 {style}",
                    "relationship_representation_family": f"家族 {style}",
                    "craft_axis": "完全相同的工艺轴",
                    "visual_activity_mode": "restrained",
                    "attention_strategy": f"候选 {style} 保持一个主导入口。",
                }
                for style in pipeline.QUICK_STYLES
            }
            add_valid_spatial_topologies(styles)
            path = root / "layout_portfolio.json"
            write_json(
                path,
                {
                    "layout_portfolio_contract_version": 7,
                    "art_direction_contract_version": 1,
                    "visual_activity_portfolio_version": 1,
                    "spatial_topology_portfolio_version": 1,
                    "page_id": "02",
                    "director_rationale": "测试重复工艺轴。",
                    "styles": styles,
                },
            )
            with self.assertRaisesRegex(SystemExit, "craft_axis 与其他方向完全重复"):
                pipeline.load_layout_portfolio(
                    path,
                    {"run_mode": pipeline.FAST8_MODE},
                    content,
                    expected_styles=pipeline.QUICK_STYLES,
                )

    def test_visual_activity_portfolio_requires_explicit_story_and_quiet_coverage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shawn_attention_portfolio_") as temp:
            root = Path(temp)
            content = {
                "prompt_contract_version": 4,
                "page_id": "09",
                "prompt_semantic_guardrails": [],
                "visual_quality_intent": "克制、有呼吸感。",
                "relationship_thesis": "一个主导关系统领其余证据。",
            }
            styles = {}
            modes = [
                "restrained",
                "restrained",
                "restrained",
                "balanced",
                "balanced",
                "balanced",
                "expressive",
                "balanced",
            ]
            for index, style in enumerate(pipeline.QUICK_STYLES):
                styles[style] = {
                    "direction_id": f"attention_{style}",
                    "visual_thesis": f"候选 {style} 由一个关系承担第一眼。",
                    "relationship_representation_family": f"注意力家族 {index + 1}",
                    "craft_axis": f"候选 {style} 的独立工艺轴。",
                    "visual_activity_mode": modes[index],
                    "attention_strategy": f"候选 {style} 保持主视觉集中，证据安静。",
                }
            add_valid_spatial_topologies(styles)
            path = root / "layout_portfolio.json"
            write_json(
                path,
                {
                    "layout_portfolio_contract_version": 7,
                    "art_direction_contract_version": 1,
                    "visual_activity_portfolio_version": 1,
                    "spatial_topology_portfolio_version": 1,
                    "page_id": "09",
                    "director_rationale": "测试视觉活跃度覆盖。",
                    "styles": styles,
                },
            )
            with self.assertRaisesRegex(SystemExit, "缺少非空 flexible_story"):
                pipeline.load_layout_portfolio(
                    path,
                    {"run_mode": pipeline.FAST8_MODE},
                    content,
                    expected_styles=pipeline.QUICK_STYLES,
                )

            content["flexible_story"] = "必要事实被压缩为一句自然创意简报。"
            bundle = pipeline.load_layout_portfolio(
                path,
                {"run_mode": pipeline.FAST8_MODE},
                content,
                expected_styles=pipeline.QUICK_STYLES,
            )
            self.assertEqual(bundle["visual_activity_portfolio_version"], 1)
            self.assertEqual(
                bundle["candidate_policy"],
                "art_directed_relationship_topology_portfolio",
            )

    def test_spatial_topology_rejects_a_repeated_eight_seat_skeleton(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shawn_topology_bad_") as temp:
            root = Path(temp)
            content = {
                "prompt_contract_version": 4,
                "page_id": "10",
                "prompt_semantic_guardrails": [],
                "visual_quality_intent": "克制、清晰。",
                "relationship_thesis": "证据共同收束到一个结论。",
                "flexible_story": "必要事实形成一个清晰结论。",
            }
            styles = {}
            for index, style in enumerate(pipeline.QUICK_STYLES):
                styles[style] = {
                    "direction_id": f"topology_{style}",
                    "visual_thesis": f"候选 {style} 的独立可见命题。",
                    "relationship_representation_family": f"家族 {index + 1}",
                    "craft_axis": f"工艺轴 {index + 1}",
                    "visual_activity_mode": (
                        "restrained" if index < 3 else "balanced"
                    ),
                    "attention_strategy": f"候选 {style} 保持单一入口。",
                    "spatial_topology": {
                        "primary_entry": "paired_contrast",
                        "region_logic": "asymmetric_split",
                        "evidence_attachment": "quiet_band",
                        "spatial_topology_intent": f"候选 {style} 使用相同骨架。",
                    },
                }
            path = root / "layout_portfolio.json"
            write_json(
                path,
                {
                    "layout_portfolio_contract_version": 7,
                    "art_direction_contract_version": 1,
                    "visual_activity_portfolio_version": 1,
                    "spatial_topology_portfolio_version": 1,
                    "page_id": "10",
                    "director_rationale": "验证同骨架必须在生图前被拒绝。",
                    "styles": styles,
                },
            )
            with self.assertRaisesRegex(SystemExit, "完整签名必须逐席互异"):
                pipeline.load_layout_portfolio(
                    path,
                    {"run_mode": pipeline.FAST8_MODE},
                    content,
                    expected_styles=pipeline.QUICK_STYLES,
                )


if __name__ == "__main__":
    unittest.main()
