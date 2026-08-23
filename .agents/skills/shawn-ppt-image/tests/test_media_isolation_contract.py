from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MediaIsolationContractTests(unittest.TestCase):
    def test_shared_quality_principles_remain_minimal_and_stable(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("质量门保持少而稳定", skill_text)
        self.assertIn("只保留一个隔离 Judge", skill_text)
        self.assertIn("不增加第二 Reviewer", skill_text)
        self.assertIn("正式 state", skill_text)

    def test_main_conversation_is_image_free_and_child_qa_is_allowed(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        media_text = (
            SKILL_ROOT / "references" / "媒体隔离与交付格式.md"
        ).read_text(encoding="utf-8")
        worker_text = (SKILL_ROOT / "prompts" / "visual-review-worker.md").read_text(
            encoding="utf-8"
        )
        global_agents_text = (Path.home() / ".codex" / "AGENTS.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("references/媒体隔离与交付格式.md", skill_text)
        self.assertIn("视觉检查与 Judge 必须照常在子 Agent 内执行", media_text)
        self.assertIn("includeOutputs=false", media_text)
        self.assertIn("只使用普通可点击文件链接", media_text)
        self.assertIn("原始 `.jsonl`", media_text)
        self.assertIn("recover_image_artifact.py", media_text)
        self.assertIn("子 Agent 视觉审查合同", worker_text)
        self.assertIn("子 Agent 可以读取任务明确列出的本地图片", worker_text)
        self.assertIn('"suspect_paths"', worker_text)
        self.assertIn("图片检查与主对话负载控制", global_agents_text)
        self.assertIn("隔离的子 Agent", global_agents_text)
        self.assertIn("子 Agent 可以按任务需要使用图片工具", global_agents_text)
        self.assertIn("includeOutputs=false", global_agents_text)
        self.assertIn("不得因为主对话的负载规则削弱", global_agents_text)

    def test_imagegen_wrappers_never_emit_generated_image_blocks(self) -> None:
        fast8_script = (SKILL_ROOT / "scripts" / "fast8_control_plane_v1.py").read_text(
            encoding="utf-8"
        )
        four_by_three_script = (
            SKILL_ROOT / "scripts" / "four_by_three_control_plane_v1.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("generatedImage(result)", fast8_script)
        self.assertNotIn("generatedImage(generated)", four_by_three_script)
        self.assertNotIn("image(result)", fast8_script)
        self.assertNotIn("image(generated)", four_by_three_script)

    def test_new_task_directory_contains_isolated_qa_locations(self) -> None:
        module = load_module(
            "init_task_dir", SKILL_ROOT / "scripts" / "init_task_dir.py"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "P16_8x1_20260724"
            module.create_standard_dirs(project_dir)
            self.assertTrue((project_dir / "origin_image").is_dir())
            self.assertFalse((project_dir / "origin_image" / "style_A").exists())
            self.assertTrue((project_dir / "visual_qa_jobs").is_dir())
            self.assertTrue((project_dir / "visual_qa_jobs" / "results").is_dir())

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow not available")
    def test_quick8_overview_uses_two_columns_and_four_tone_rows(self) -> None:
        from PIL import Image

        matrix = load_module(
            "build_style_matrix_2x4",
            SKILL_ROOT / "scripts" / "build_style_matrix.py",
        )
        colors = {
            style: (20 + index * 20, 30 + index * 10, 40 + index * 5)
            for index, style in enumerate(matrix.QUICK_STYLES)
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            origin_dir = project_dir / "origin_image"
            origin_dir.mkdir()
            for style, color in colors.items():
                Image.new("RGB", (1600, 900), color).save(
                    origin_dir / f"style_{style}_page_02.png"
                )

            output = project_dir / "overview" / "ABCDEFGH_2x4.png"
            matrix.build_matrix(
                project_dir=project_dir,
                styles=list(matrix.QUICK_STYLES),
                pages=["02"],
                output=output,
                cell_width=320,
                header_height=40,
                row_label_width=80,
                gap=0,
                ratio_tolerance=0.02,
            )

            with Image.open(output) as overview:
                self.assertEqual(overview.size, (720, 880))
                centers = (
                    (240, 130), (560, 130),
                    (240, 350), (560, 350),
                    (240, 570), (560, 570),
                    (240, 790), (560, 790),
                )
                self.assertEqual(
                    [overview.getpixel(point) for point in centers],
                    [colors[style] for style in matrix.QUICK_STYLES],
                )

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow not available")
    def test_overview_scripts_prefer_flat_images_and_read_legacy_layout(self) -> None:
        from PIL import Image

        matrix = load_module(
            "build_style_matrix_flat",
            SKILL_ROOT / "scripts" / "build_style_matrix.py",
        )
        scripts_dir = str(SKILL_ROOT / "scripts")
        sys.path.insert(0, scripts_dir)
        try:
            page_overview = load_module(
                "build_page_overview_flat",
                SKILL_ROOT / "scripts" / "build_page_overview.py",
            )
        finally:
            sys.path.remove(scripts_dir)

        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            origin_dir = project_dir / "origin_image"
            origin_dir.mkdir()

            for style in matrix.FULL_STYLES:
                Image.new("RGB", (1600, 900), "white").save(
                    origin_dir / f"style_{style}_page_02.png"
                )
            flat = origin_dir / "style_A_page_02.png"
            self.assertEqual(matrix.find_page(project_dir, "A", "02"), flat)
            self.assertEqual(
                page_overview.find_page(project_dir, "style_A", "02", None), flat
            )
            matrix_output = project_dir / "overview" / "ABCD_4x1.png"
            matrix.build_matrix(
                project_dir=project_dir,
                styles=list(matrix.FULL_STYLES),
                pages=["02"],
                output=matrix_output,
                cell_width=320,
                header_height=40,
                row_label_width=80,
                gap=0,
                ratio_tolerance=0.02,
            )
            self.assertTrue(matrix_output.is_file())

            page_output = project_dir / "overview" / "style_A_02_overview.png"
            page_overview.build_overview(
                project_dir=project_dir,
                style_id="style_A",
                pages=["02"],
                output=page_output,
                columns=1,
                cell_width=320,
                label_height=40,
                gap=0,
                ratio_tolerance=0.02,
                source_state=None,
                allow_invalid=False,
            )
            self.assertTrue(page_output.is_file())

            flat.unlink()
            legacy = origin_dir / "style_A" / "page_02.png"
            legacy.parent.mkdir()
            Image.new("RGB", (1600, 900), "white").save(legacy)
            self.assertEqual(matrix.find_page(project_dir, "A", "02"), legacy)
            self.assertEqual(
                page_overview.find_page(project_dir, "style_A", "02", None), legacy
            )

            quick_flat = origin_dir / "style_E_page_02.png"
            Image.new("RGB", (1600, 900), "white").save(quick_flat)
            self.assertEqual(
                matrix.infer_styles(project_dir, ["02"], None),
                list(matrix.QUICK_STYLES),
            )

    def test_overview_event_defaults_to_visual_worker(self) -> None:
        script_text = (SKILL_ROOT / "scripts" / "pipeline_control.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('details.get("qa_stage", "visual_worker")', script_text)
        self.assertNotIn('details.get("qa_stage", "main")', script_text)


if __name__ == "__main__":
    unittest.main()
