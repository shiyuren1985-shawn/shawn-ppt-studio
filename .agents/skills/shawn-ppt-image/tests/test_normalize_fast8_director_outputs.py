import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "normalize_fast8_director_outputs.py"
)


class NormalizeFast8DirectorOutputsTest(unittest.TestCase):
    def base_content(self) -> dict:
        return {
            "page_id": "P31",
            "language": "zh-CN",
            "source_facts": [{"fact": "原始事实", "status": "business_claim"}],
            "display_required": ["逐字标题"],
            "display_flexible": ["可压缩说明"],
            "display_supporting": ["辅助证据"],
            "flexible_story": "复杂性由 RA 承接，确定性留给 EPC。",
            "information_density_target": "medium",
            "semantic_invariants": ["不得颠倒责任关系"],
            "forbidden_interpretations": ["不得暗示第三方背书"],
            "prompt_semantic_guardrails": ["保持责任边界"],
            "prompt_user_constraints": ["固定标题区按大纲"],
            "content_resolution": {"status": "confirmed", "reason": "来源已确认"},
        }

    def base_layout(self, *, container: str = "directions") -> dict:
        primary = [
            "single_focus",
            "paired_contrast",
            "path",
            "network",
            "field",
            "hierarchy",
            "radial",
            "evidence_hero",
        ]
        regions = [
            "unified_field",
            "asymmetric_split",
            "staged_path",
            "distributed_nodes",
            "layered_depth",
            "annotated_object",
            "geographic_spread",
            "editorial_sequence",
        ]
        evidence = [
            "integrated",
            "annotated",
            "satellite",
            "quiet_band",
            "integrated",
            "annotated",
            "none",
            "satellite",
        ]
        activity = [
            "restrained",
            "restrained",
            "restrained",
            "balanced",
            "balanced",
            "balanced",
            "expressive",
            "expressive",
        ]
        styles = {}
        for index, style in enumerate("ABCDEFGH"):
            styles[style] = {
                "direction_id": f"direction_{style}",
                "visual_thesis": f"视觉命题 {style}",
                "craft_axis": f"工艺轴 {style}",
                "visual_activity_mode": activity[index],
                "attention_strategy": f"注意策略 {style}",
                "relationship_representation_family": f"关系家族 {style}",
                "spatial_topology": {
                    "primary_entry": primary[index],
                    "region_logic": regions[index],
                    "evidence_attachment": evidence[index],
                    "spatial_topology_intent": f"空间意图 {style}",
                },
            }
        return {
            "page_id": "P31",
            "director_rationale": "人工构造的等价 fixture，用于覆盖已观察到的容器和版本缺失。",
            "background_tone_policy": {
                "mode": "uniform",
                "tone": "light",
                "source": "primary_style_reference",
            },
            container: styles,
        }

    def run_normalizer(self, content: dict, layout: dict):
        temporary = tempfile.TemporaryDirectory(prefix="fast8_director_normalizer_")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        content_input = root / "content_contract.json"
        layout_input = root / "layout_portfolio.json"
        content_output = root / "content_contract.normalized.json"
        layout_output = root / "layout_portfolio.normalized.json"
        provenance_output = root / "director_outputs.normalized.json"
        content_input.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        layout_input.write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--content-input",
                str(content_input),
                "--layout-input",
                str(layout_input),
                "--content-output",
                str(content_output),
                "--layout-output",
                str(layout_output),
                "--provenance-output",
                str(provenance_output),
            ],
            capture_output=True,
            text=True,
        )
        return result, content_input, layout_input, content_output, layout_output, provenance_output

    def test_mechanical_fields_and_directions_alias_are_lossless(self) -> None:
        raw_content = self.base_content()
        raw_layout = self.base_layout()
        raw_content_snapshot = copy.deepcopy(raw_content)
        raw_styles_snapshot = copy.deepcopy(raw_layout["directions"])
        result, content_input, layout_input, content_output, layout_output, provenance_output = (
            self.run_normalizer(raw_content, raw_layout)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        normalized_content = json.loads(content_output.read_text(encoding="utf-8"))
        normalized_layout = json.loads(layout_output.read_text(encoding="utf-8"))
        provenance = json.loads(provenance_output.read_text(encoding="utf-8"))

        self.assertEqual(normalized_content["content_contract_version"], 2)
        self.assertEqual(normalized_content["prompt_contract_version"], 4)
        for field in raw_content_snapshot:
            self.assertEqual(normalized_content[field], raw_content_snapshot[field])
        self.assertEqual(normalized_layout["styles"], raw_styles_snapshot)
        self.assertNotIn("directions", normalized_layout)
        self.assertEqual(normalized_layout["layout_portfolio_contract_version"], 7)
        self.assertEqual(normalized_layout["art_direction_contract_version"], 1)
        self.assertEqual(normalized_layout["visual_activity_portfolio_version"], 1)
        self.assertEqual(normalized_layout["spatial_topology_portfolio_version"], 1)
        self.assertEqual(
            normalized_layout["background_tone_policy"],
            raw_layout["background_tone_policy"],
        )
        for style in "ABCDEFGH":
            for field in (
                "visual_thesis",
                "craft_axis",
                "attention_strategy",
            ):
                self.assertEqual(
                    normalized_layout["styles"][style][field],
                    raw_styles_snapshot[style][field],
                )
            self.assertEqual(
                normalized_layout["styles"][style]["spatial_topology"][
                    "spatial_topology_intent"
                ],
                raw_styles_snapshot[style]["spatial_topology"][
                    "spatial_topology_intent"
                ],
            )
        alias = next(
            item
            for item in provenance["layout"]["changes"]
            if item["mode"] == "lossless_container_alias"
        )
        self.assertTrue(all(alias["per_seat_deep_equal"].values()))
        self.assertTrue(provenance["raw_inputs_preserved"])
        self.assertFalse(provenance["semantic_mapping_performed"])
        self.assertEqual(json.loads(content_input.read_text(encoding="utf-8")), raw_content)
        self.assertEqual(json.loads(layout_input.read_text(encoding="utf-8")), raw_layout)

    def test_resolved_status_is_not_guessed(self) -> None:
        content = self.base_content()
        content["content_resolution"]["status"] = "resolved"
        result, _, _, content_output, layout_output, _ = self.run_normalizer(
            content, self.base_layout()
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不会猜测近义值", result.stderr)
        self.assertFalse(content_output.exists())
        self.assertFalse(layout_output.exists())

    def test_optional_bilingual_presentation_is_preserved_and_validated(self) -> None:
        content = self.base_content()
        content["language"] = "mixed"
        content["display_required"] = [
            "一个品牌、一个公司",
            "One Brand, One Company",
        ]
        content["language_presentation"] = {
            "mode": "bilingual",
            "delivery": "same_page",
            "logical_page_id": "P6",
            "peer_page_id": None,
            "pairing": "paired",
            "pairs": [
                {
                    "primary": "一个品牌、一个公司",
                    "secondary": "One Brand, One Company",
                }
            ],
        }

        result, _, _, content_output, _, _ = self.run_normalizer(
            content, self.base_layout()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        normalized = json.loads(content_output.read_text(encoding="utf-8"))
        self.assertEqual(
            normalized["language_presentation"],
            content["language_presentation"],
        )

        invalid = copy.deepcopy(content)
        invalid["language_presentation"]["pairs"][0]["secondary"] = (
            "Unauthorized English"
        )
        result, *_ = self.run_normalizer(invalid, self.base_layout())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("必须同时存在", result.stderr)

    def test_invalid_free_topology_is_not_mapped(self) -> None:
        layout = self.base_layout()
        layout["directions"]["A"]["spatial_topology"] = {
            "entry_mode": "hero_object",
            "flow": "left_to_right",
            "evidence": "embedded",
            "spatial_topology_intent": "保留原始自由字段",
        }
        result, _, _, _, layout_output, _ = self.run_normalizer(
            self.base_content(), layout
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未知字段", result.stderr)
        self.assertFalse(layout_output.exists())

    def test_missing_or_duplicate_container_shape_fails_closed(self) -> None:
        layout = self.base_layout()
        layout["directions"].pop("H")
        result, *_ = self.run_normalizer(self.base_content(), layout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("恰好包含 A-H", result.stderr)

        both = self.base_layout()
        both["styles"] = copy.deepcopy(both["directions"])
        result, *_ = self.run_normalizer(self.base_content(), both)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不得同时包含", result.stderr)

    def test_unknown_fields_fail_instead_of_being_swallowed(self) -> None:
        content = self.base_content()
        content["unexpected_note"] = "should fail"
        result, *_ = self.run_normalizer(content, self.base_layout())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未知字段", result.stderr)


if __name__ == "__main__":
    unittest.main()
