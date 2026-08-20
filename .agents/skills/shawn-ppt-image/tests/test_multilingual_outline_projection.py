from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROJECTOR = ROOT / "scripts" / "project_multilingual_outline.py"
INIT = ROOT / "scripts" / "init_task_dir.py"


class MultilingualOutlineProjectionTest(unittest.TestCase):
    @staticmethod
    def outline() -> str:
        return (
            "# Unified outline\n\n"
            "| 页码 | 客户钩子／页面标题 | 核心命题 | 信息密度／上屏层级 | 页面必讲内容 | English Page Content | 双语交付策略 | 同页双语配对 | 视觉表达目标／用户硬约束 |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| P2 | 中文标题二 | 中文命题二 | 低 | 中文内容二 | Title: English Two<br>Core: English content two | **bilingual_strategy:** same_page | 中文标题二 ⇄ English Two | 简洁视觉 |\n"
            "| P9 | 中文标题九 | 中文命题九 | 高 | 中文内容九 | Title: English Nine<br>Core: Full English content nine | **bilingual_strategy:** split_zh_en | — | 复杂架构 |\n"
        )

    def run_projector(
        self, root: Path, mode: str
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        source = root / "outline.md"
        source.write_text(self.outline(), encoding="utf-8")
        output = root / f"projection_{mode}.json"
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECTOR),
                "--source",
                str(source),
                "--page-ids",
                "P2,P9",
                "--output-mode",
                mode,
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        return result, output

    def test_bilingual_projection_pairs_simple_page_and_splits_dense_page(self) -> None:
        with tempfile.TemporaryDirectory(prefix="multilingual_projection_") as temp:
            root = Path(temp)
            result, output = self.run_projector(root, "bilingual")
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["page_order"], ["02", "09-ZH", "09-EN"])
            pages = {item["page_id"]: item for item in value["pages"]}
            self.assertEqual(
                pages["02"]["same_page_pairs"],
                [{"primary": "中文标题二", "secondary": "English Two"}],
            )
            self.assertNotIn("English Page Content", json.dumps(pages["02"], ensure_ascii=False))
            self.assertNotIn("Full English content nine", json.dumps(pages["09-ZH"], ensure_ascii=False))
            self.assertNotIn("中文内容九", json.dumps(pages["09-EN"], ensure_ascii=False))
            self.assertEqual(
                pages["09-ZH"]["language_presentation_seed"]["peer_page_id"],
                "09-EN",
            )
            self.assertEqual(
                pages["09-EN"]["language_presentation_seed"]["peer_page_id"],
                "09-ZH",
            )

    def test_single_language_projection_excludes_other_display_layer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="multilingual_projection_single_") as temp:
            root = Path(temp)
            zh_result, zh_output = self.run_projector(root, "zh")
            self.assertEqual(zh_result.returncode, 0, zh_result.stderr)
            zh_value = json.loads(zh_output.read_text(encoding="utf-8"))
            self.assertNotIn(
                "Full English content nine",
                json.dumps(zh_value, ensure_ascii=False),
            )

            en_result, en_output = self.run_projector(root, "en")
            self.assertEqual(en_result.returncode, 0, en_result.stderr)
            en_value = json.loads(en_output.read_text(encoding="utf-8"))
            self.assertNotIn("中文内容九", json.dumps(en_value, ensure_ascii=False))

    def test_initializer_accepts_split_physical_page_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix="multilingual_split_init_") as temp:
            root = Path(temp)
            result, output = self.run_projector(root, "bilingual")
            self.assertEqual(result.returncode, 0, result.stderr)
            overview_python = root / "overview-python"
            overview_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            overview_python.chmod(0o755)
            deck_scope = root / "deck_scope.md"
            deck_scope.write_text(
                "Title chrome applies to P02, P09-ZH and P09-EN.\n",
                encoding="utf-8",
            )
            init = subprocess.run(
                [
                    sys.executable,
                    str(INIT),
                    "--output-root",
                    str(root / "output"),
                    "--task-name",
                    "multilingual_split",
                    "--run-mode",
                    "selected_style_expansion",
                    "--page-ids",
                    "02,09-ZH,09-EN",
                    "--source-file",
                    str(output),
                    "--supporting-source",
                    f"{deck_scope}::deck",
                    "--overview-python",
                    str(overview_python),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            payload = json.loads(init.stdout)
            state = json.loads(Path(payload["state"]).read_text(encoding="utf-8"))
            self.assertEqual(state["page_order"], ["02", "09-ZH", "09-EN"])

    def test_split_scope_does_not_treat_siblings_as_logical_page_leak(self) -> None:
        with tempfile.TemporaryDirectory(prefix="multilingual_split_scope_") as temp:
            root = Path(temp)
            scope = root / "scope.md"
            scope.write_text(
                "Rules for P09-ZH and P09-EN only; logical P09 covers both siblings.",
                encoding="utf-8",
            )
            sys.path.insert(0, str(ROOT / "scripts"))
            try:
                import init_task_dir as init_module

                exact, _ = init_module.freeze_expansion_supporting_text(
                    scope, "deck", ["09-ZH", "09-EN"]
                )
                self.assertIn("P09-ZH", exact)
                self.assertIn("P09-EN", exact)
            finally:
                sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
