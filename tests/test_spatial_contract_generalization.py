from __future__ import annotations

from pathlib import Path
import re
import unittest


SPATIAL_REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "空间节奏与视觉呼吸规范.md"
)
PIPELINE_CONTROL = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_control.py"


class SpatialContractGeneralizationTests(unittest.TestCase):
    def test_global_spatial_rules_do_not_define_page_specific_cases(self) -> None:
        text = SPATIAL_REFERENCE.read_text(encoding="utf-8")
        self.assertIn(
            "任何具体客户、项目、页码、页面原文或历史大纲案例都不得成为"
            "全局空间规范的特殊分支或验收锚点",
            text,
        )
        headings = re.findall(r"(?m)^## .+$", text)
        self.assertFalse(
            any(re.search(r"\bP\d{1,3}\b", heading, re.IGNORECASE) for heading in headings)
        )

    def test_pipeline_has_no_page_specific_legacy_mechanisms(self) -> None:
        text = PIPELINE_CONTROL.read_text(encoding="utf-8")
        for symbol in (
            "LEGACY_LAYOUT_VOCABULARY",
            "build_legacy_exploration_seed_bundle",
            "layout_decoupling",
        ):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, text)


if __name__ == "__main__":
    unittest.main()
