from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "pipeline_control.py"
SPEC = importlib.util.spec_from_file_location(
    "pipeline_control_prompt_title_evidence_isolation", MODULE_PATH
)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


class PromptTitleEvidenceIsolationTest(unittest.TestCase):
    def build_job(self, run_mode: str) -> dict[str, object]:
        layout_versions = {
            pipeline.FAST8_MODE: pipeline.CURRENT_FAST8_LAYOUT_VERSION,
            pipeline.FAST_4X3_MODE: pipeline.CURRENT_4X3_LAYOUT_VERSION,
            pipeline.SELECTED_STYLE_EXPANSION_MODE: pipeline.SELECTED_STYLE_LAYOUT_VERSION,
        }
        return {
            "run_mode": run_mode,
            "imagegen_prompt_contract_version": (
                pipeline.CURRENT_FAST8_IMAGEGEN_PROMPT_VERSION
                if run_mode == pipeline.FAST8_MODE
                else 4
            ),
            "tone": "light",
            "language": "mixed",
            "anchor_page": {
                "content_contract_version": 2,
                "prompt_contract_version": 4,
                "page_id": "P09",
                "title": "采选冶一体化，贯通数据与运营",
                "language": "mixed",
                "display_required": ["Level 0–Level 2", "数据向上", "决策向下"],
                "display_flexible": [],
                "flexible_story": "四层连续架构贯通现场数据与运营决策。",
                "visual_quality_intent": "清晰、成熟、具有工程精度。",
                "relationship_thesis": "四层纵向连续，数据向上、决策向下。",
                "prompt_semantic_guardrails": [],
                "prompt_user_constraints": [],
                "spatial_pressure_profile": "low",
            },
            "layout_direction": {
                "layout_contract_version": layout_versions[run_mode],
                "art_direction_contract_version": pipeline.ART_DIRECTION_CONTRACT_VERSION,
                "visual_thesis": "以单一纵向架构统领页面。",
                "craft_axis": "精密线性架构与克制的浅色材质。",
                "visual_activity_mode": "restrained",
                "attention_strategy": "先看完整四层，再读取双向关系。",
            },
            "reference_images": [],
            "required_assets": [
                {
                    "path": "/tmp/source_page.png",
                    "role": "source_page",
                    "use": "仅核对四层事实与对象，不复制旧页标题和构图",
                }
            ],
            "global_chrome": {
                "applies": True,
                "main_title_required": True,
                "main_title": {
                    "required": True,
                    "text": "采选冶一体化，贯通数据与运营",
                },
                "prompt_brief": "使用统一而开放的标题层级，不固定正文布局。",
            },
        }

    def test_shared_prompt_v4_protects_title_and_evidence_in_all_new_modes(self) -> None:
        for run_mode in (
            pipeline.FAST8_MODE,
            pipeline.FAST_4X3_MODE,
            pipeline.SELECTED_STYLE_EXPANSION_MODE,
        ):
            with self.subTest(run_mode=run_mode):
                prompt = pipeline.compile_minimal_prompt_v4(self.build_job(run_mode))
                self.assertIn(
                    "逐字主标题（当前页唯一主标题，不得用附件、参考图或正文中的其他文字替换）："
                    "采选冶一体化，贯通数据与运营",
                    prompt,
                )
                self.assertIn("当前页没有授权副标题；不得从附件或参考图补写、复制副标题", prompt)
                self.assertIn(
                    "只用于以下证据用途：仅核对四层事实与对象，不复制旧页标题和构图",
                    prompt,
                )
                self.assertIn(
                    "不得继承附件标题、正文、页面结论、构图、容器、底栏或视觉风格",
                    prompt,
                )
                self.assertNotIn("附件1=source_page；按角色原样使用", prompt)

    def test_required_global_chrome_title_fails_before_prompt_dispatch_when_missing(self) -> None:
        job = self.build_job(pipeline.FAST_4X3_MODE)
        job["global_chrome"]["main_title"]["text"] = ""
        with self.assertRaisesRegex(SystemExit, "缺少逐字 main_title.text"):
            pipeline.compile_minimal_prompt_v4(job)

    def test_page_title_and_optional_subtitle_compile_without_global_chrome(self) -> None:
        job = self.build_job(pipeline.SELECTED_STYLE_EXPANSION_MODE)
        job.pop("global_chrome")
        job["anchor_page"]["subtitle"] = "从现场数据到经营决策"
        prompt = pipeline.compile_minimal_prompt_v4(job)
        self.assertIn("逐字主标题（当前页唯一主标题", prompt)
        self.assertIn("逐字副标题（仅作为当前页副标题）：从现场数据到经营决策", prompt)
        self.assertEqual(prompt.count("采选冶一体化，贯通数据与运营"), 1)

    def test_global_chrome_title_conflict_is_rejected(self) -> None:
        job = self.build_job(pipeline.FAST_4X3_MODE)
        job["global_chrome"]["main_title"]["text"] = "另一页标题"
        with self.assertRaisesRegex(SystemExit, "title 与 global chrome"):
            pipeline.compile_minimal_prompt_v4(job)


if __name__ == "__main__":
    unittest.main()
