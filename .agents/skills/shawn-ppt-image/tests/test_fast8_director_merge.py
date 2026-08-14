import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "merge_fast8_director_inputs.py"
)


class Fast8DirectorMergeTest(unittest.TestCase):
    def test_canonical_page_id_alias_is_script_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = {
                "prompt_contract_version": 4,
                "canonical_page_id": "P6",
                "language": "zh-CN",
                "prompt_semantic_guardrails": [],
                "prompt_user_constraints": [],
            }
            intent = {
                "creative_intent_contract_version": 1,
                "page_id": "P6",
                "relationship_thesis": "a",
                "visual_quality_intent": "b",
                "visual_support_goal": "c",
                "craft_ambition": "d",
            }
            content_path = root / "content.json"
            intent_path = root / "intent.json"
            output_path = root / "merged.json"
            content_path.write_text(json.dumps(content), encoding="utf-8")
            intent_path.write_text(json.dumps(intent), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--content-contract",
                    str(content_path),
                    "--creative-intent",
                    str(intent_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["page_id"], "P6")
            self.assertNotIn("canonical_page_id", merged)
            self.assertEqual(
                merged["director_input_normalization"]["page_id_alias"],
                "canonical_page_id_to_page_id",
            )

    def test_conflicting_page_id_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content_path = root / "content.json"
            intent_path = root / "intent.json"
            output_path = root / "merged.json"
            content_path.write_text(
                json.dumps(
                    {"page_id": "P6", "canonical_page_id": "P7"}
                ),
                encoding="utf-8",
            )
            intent_path.write_text(
                json.dumps(
                    {
                        "creative_intent_contract_version": 1,
                        "page_id": "P6",
                        "relationship_thesis": "a",
                        "visual_quality_intent": "b",
                        "visual_support_goal": "c",
                        "craft_ambition": "d",
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--content-contract",
                    str(content_path),
                    "--creative-intent",
                    str(intent_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("冲突", result.stderr)

    def test_only_creative_allowlist_is_merged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = {
                "content_contract_version": 2,
                "prompt_contract_version": 4,
                "page_id": "P31",
                "language": "zh-CN",
                "title": "原始标题",
                "display_required": ["原始标题"],
                "source_status": "business_claim",
                "relationship_thesis": "baseline",
                "visual_quality_intent": "baseline",
                "visual_support_goal": "baseline",
                "craft_ambition": "baseline",
            }
            intent = {
                "creative_intent_contract_version": 1,
                "page_id": "P31",
                "relationship_thesis": "可见关系",
                "visual_quality_intent": "精致成品",
                "visual_support_goal": "一眼读懂",
                "craft_ambition": "高级工业工艺",
                "title": "不得覆盖事实标题",
            }
            content_path = root / "content.json"
            intent_path = root / "intent.json"
            output_path = root / "merged.json"
            content_path.write_text(json.dumps(content), encoding="utf-8")
            intent_path.write_text(json.dumps(intent), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--content-contract",
                    str(content_path),
                    "--creative-intent",
                    str(intent_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(result.stdout)["status"], "ok")
            merged = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["title"], "原始标题")
            self.assertEqual(merged["display_required"], ["原始标题"])
            self.assertEqual(merged["source_status"], "business_claim")
            self.assertEqual(merged["relationship_thesis"], "可见关系")
            self.assertEqual(merged["visual_quality_intent"], "精致成品")
            self.assertEqual(merged["spatial_standard_version"], 1)
            self.assertEqual(merged["spatial_feasibility"], "pass")
            self.assertIn("隐形网格", merged["spatial_generation_brief"])
            self.assertIn("有效负空间", merged["spatial_qa_contract"])
            self.assertTrue(merged["spatial_contract_provenance"]["script_owned"])
            self.assertFalse(
                merged["creative_intent_provenance"][
                    "facts_or_brand_fields_modified"
                ]
            )

    def test_lean_fact_contract_gets_script_owned_qa_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = {
                "content_contract_version": 2,
                "prompt_contract_version": 4,
                "page_id": "P16",
                "language": "zh-CN",
                "source_facts": [],
                "display_required": ["核心转变"],
                "display_flexible": [],
                "display_supporting": ["辅助事实"],
                "flexible_story": "从分散走向统一。",
                "information_density_target": "medium",
                "semantic_invariants": ["不得改写事实。"],
                "forbidden_interpretations": [],
                "prompt_semantic_guardrails": [],
                "prompt_user_constraints": [],
                "content_resolution": {"status": "not_needed", "reason": "可行"},
            }
            intent = {
                "creative_intent_contract_version": 1,
                "page_id": "P16",
                "relationship_thesis": "从分散走向统一是唯一主关系。",
                "visual_quality_intent": "正式成品",
                "visual_support_goal": "支撑核心转变",
                "craft_ambition": "精致工业表达",
            }
            content_path = root / "content.json"
            intent_path = root / "intent.json"
            output_path = root / "merged.json"
            overall_path = root / "overall_requirements.txt"
            content_path.write_text(json.dumps(content), encoding="utf-8")
            intent_path.write_text(json.dumps(intent), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--content-contract",
                    str(content_path),
                    "--creative-intent",
                    str(intent_path),
                    "--output",
                    str(output_path),
                    "--overall-requirements-output",
                    str(overall_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = json.loads(output_path.read_text(encoding="utf-8"))
            review = merged["content_load_review"]
            self.assertEqual(
                review["semantic_structure"],
                "从分散走向统一是唯一主关系。",
            )
            self.assertIn("辅助事实", review["attention_risks"][0])
            self.assertTrue(
                merged["content_load_review_provenance"][
                    "facts_or_display_obligations_modified"
                ]
                is False
            )
            self.assertIn("合并后的内容合同", overall_path.read_text(encoding="utf-8"))

    def test_existing_model_authored_load_review_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = {
                "page_id": "P1",
                "language": "en",
                "prompt_semantic_guardrails": [],
                "prompt_user_constraints": [],
                "content_load_review": {
                    "semantic_structure": "custom",
                    "focus_relationship": "custom",
                    "attention_risks": [],
                    "edge_and_takeaway_risks": [],
                    "duplication_risks": [],
                    "reason": "legacy",
                },
            }
            intent = {
                "creative_intent_contract_version": 1,
                "page_id": "P1",
                "relationship_thesis": "primary relationship",
                "visual_quality_intent": "finished",
                "visual_support_goal": "support",
                "craft_ambition": "craft",
            }
            content_path = root / "content.json"
            intent_path = root / "intent.json"
            output_path = root / "merged.json"
            content_path.write_text(json.dumps(content), encoding="utf-8")
            intent_path.write_text(json.dumps(intent), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--content-contract",
                    str(content_path),
                    "--creative-intent",
                    str(intent_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["content_load_review"]["reason"], "legacy")
            self.assertNotIn("content_load_review_provenance", merged)

    def test_page_id_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content_path = root / "content.json"
            intent_path = root / "intent.json"
            output_path = root / "merged.json"
            content_path.write_text(
                json.dumps({"page_id": "31"}), encoding="utf-8"
            )
            intent_path.write_text(
                json.dumps(
                    {
                        "creative_intent_contract_version": 1,
                        "page_id": "P31",
                        "relationship_thesis": "a",
                        "visual_quality_intent": "b",
                        "visual_support_goal": "c",
                        "craft_ambition": "d",
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--content-contract",
                    str(content_path),
                    "--creative-intent",
                    str(intent_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output_path.exists())

    def test_long_prompt_item_is_reflowed_without_model_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            long_guardrail = (
                "RA 负责 Industrial Automation、OT/Data Integration 与 Global Delivery；"
                "Microsoft 负责 Cloud、Data、AI；Cisco 负责 Industrial Network 与 Cybersecurity；"
                "三方共同支撑同一个可信、安全、可治理、可全球复制的工业数据底座，不得泛化为外部生态。"
            )
            self.assertGreater(len(long_guardrail), 120)
            content = {
                "prompt_contract_version": 4,
                "page_id": "P29",
                "language": "zh-CN",
                "prompt_semantic_guardrails": [long_guardrail],
                "prompt_user_constraints": [],
            }
            intent = {
                "creative_intent_contract_version": 1,
                "page_id": "P29",
                "relationship_thesis": "三方能力共同支撑同一底座",
                "visual_quality_intent": "精致成品",
                "visual_support_goal": "一眼读懂归属",
                "craft_ambition": "高级工业工艺",
            }
            content_path = root / "content.json"
            intent_path = root / "intent.json"
            output_path = root / "merged.json"
            content_path.write_text(json.dumps(content), encoding="utf-8")
            intent_path.write_text(json.dumps(intent), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--content-contract",
                    str(content_path),
                    "--creative-intent",
                    str(intent_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = json.loads(output_path.read_text(encoding="utf-8"))
            items = merged["prompt_semantic_guardrails"]
            self.assertLessEqual(len(items), 3)
            self.assertTrue(all(len(item) <= 120 for item in items))
            self.assertIn("deterministic_reflow_without_truncation", str(
                merged["prompt_item_normalization"]
            ))
            compact_original = "".join(long_guardrail.split())
            compact_result = "".join("".join(items).split())
            self.assertEqual(compact_result, compact_original)


if __name__ == "__main__":
    unittest.main()
