from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_fast8_page_source_packet.py"
)


class Fast8PageSourcePacketTests(unittest.TestCase):
    def test_include_file_self_excluded_from_image_stages_is_not_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "outline.md"
            maintenance = root / "maintenance_rules.md"
            output = root / "packet.md"
            source.write_text(
                "| 页码 | 标题 |\n|---|---|\n| P6 | 六 |\n",
                encoding="utf-8",
            )
            maintenance.write_text(
                "本文件仅供维护大纲使用。\n"
                "作图准备、内容合同编译、图片生成和视觉审核阶段不得读取、引用、封存或传递本文件。\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--source",
                    str(source),
                    "--page-id",
                    "P6",
                    "--output",
                    str(output),
                    "--include-file",
                    str(maintenance),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            packet = output.read_text(encoding="utf-8")
            self.assertNotIn("本文件仅供维护大纲使用", packet)

    def test_include_markdown_drops_unrelated_page_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "outline.md"
            shared = root / "visual_rules.md"
            output = root / "packet.md"
            source.write_text(
                "| 页码 | 标题 |\n|---|---|\n| P6 | 六 |\n",
                encoding="utf-8",
            )
            shared.write_text(
                "# 全稿规则\n保持留白。\n\n"
                "| 页面 | 硬约束 |\n|---|---|\n"
                "| P7 | 七页专用 |\n| P16 | 十六页专用 |\n\n"
                "## 默认开放页面\n未列页面自由构图。\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--source",
                    str(source),
                    "--page-id",
                    "P6",
                    "--output",
                    str(output),
                    "--include-file",
                    str(shared),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            packet = output.read_text(encoding="utf-8")
            self.assertIn("保持留白", packet)
            self.assertIn("默认开放页面", packet)
            self.assertNotIn("七页专用", packet)
            self.assertNotIn("十六页专用", packet)

    def test_keeps_global_rules_and_only_target_page_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "outline.md"
            output = root / "state" / "director_inputs" / "page_source.md"
            source.write_text(
                "# Deck\n\n全稿规则：保持留白。\n\n"
                "| 页码 | 客户钩子／页面标题 | 内容 |\n"
                "|---|---|---|\n"
                "| P22 | 标题二十二 | A |\n"
                "| P23 | 标题二十三 | B |\n\n"
                "## 统一标题区要求\n使用官方 Logo。\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--source",
                    str(source),
                    "--page-id",
                    "P23",
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            status = json.loads(result.stdout)
            packet = output.read_text(encoding="utf-8")
            self.assertEqual(status["canonical_title"], "标题二十三")
            self.assertIn("全稿规则:保持留白", packet)
            self.assertIn("统一标题区要求", packet)
            self.assertIn("P23", packet)
            self.assertNotIn("P22", packet)

    def test_heading_outline_keeps_deck_context_and_only_target_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "outline.md"
            output = root / "packet.md"
            source.write_text(
                "# SI deck\n\nAudience: internal sales.\n\n"
                "## P2｜ODI connection\n### Core\nTarget fact.\n\n"
                "## P3｜Sales action\n### Core\nUNRELATED_PAGE.\n\n"
                "## Sources\nShared source index.\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3", str(SCRIPT), "--source", str(source),
                    "--page-id", "P2", "--output", str(output),
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            status = json.loads(result.stdout)
            packet = output.read_text(encoding="utf-8")
            self.assertEqual(status["canonical_title"], "ODI connection")
            self.assertIn("Audience: internal sales", packet)
            self.assertIn("Target fact", packet)
            self.assertIn("Shared source index", packet)
            self.assertNotIn("UNRELATED_PAGE", packet)

    def test_existing_packet_is_immutable_but_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "outline.md"
            output = root / "packet.md"
            source.write_text(
                "| 页码 | 标题 |\n|---|---|\n| P7 | 原标题 |\n",
                encoding="utf-8",
            )
            command = [
                "python3",
                str(SCRIPT),
                "--source",
                str(source),
                "--page-id",
                "P7",
                "--output",
                str(output),
            ]
            subprocess.run(command, text=True, capture_output=True, check=True)
            again = subprocess.run(command, text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(again.stdout)["status"], "already_frozen")
            source.write_text(
                "| 页码 | 标题 |\n|---|---|\n| P7 | 新标题 |\n",
                encoding="utf-8",
            )
            changed = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("不得随上游变化重写", changed.stderr)


if __name__ == "__main__":
    unittest.main()
