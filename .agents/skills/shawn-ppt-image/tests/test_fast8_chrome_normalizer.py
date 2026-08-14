from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Optional

from tests.test_fast8x1_pipeline import pipeline


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "normalize_fast8_chrome_contract.py"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fast8ChromeNormalizerTests(unittest.TestCase):
    def fixture(self, root: Path, *, required: bool = True) -> tuple[Path, Path]:
        packet = root / "authoritative_page_packet.md"
        packet.write_text("page_id: P29\n标准标题区已授权。\n", encoding="utf-8")
        dark = root / "dark.png"
        light = root / "light.png"
        dark.write_bytes(b"dark-logo")
        light.write_bytes(b"light-logo")
        raw = root / "raw.json"
        raw.write_text(
            json.dumps(
                {
                    "schema_version": "global_chrome_contract_v1",
                    "authorization": {
                        "status": "authorized",
                        "basis": "frozen packet explicitly authorizes the title system",
                    },
                    "deck_title_system": {
                        "enabled": True,
                        "scope": {"include_page_ids": ["P29"]},
                        "prompt_briefs": {
                            "zh": "使用来源授权的轻量标题区，正文保持自由。",
                            "en": "Use the source-authorized lightweight title area and keep the body open.",
                        },
                    },
                    "logo": {
                        "required": required,
                        "assets_by_tone": {
                            "dark": {"path": str(dark), "sha256": sha256(dark)},
                            "light": str(light),
                        },
                    },
                    "main_title": {"required": True, "text": "模型标点不同"},
                    "subtitle_policy": "source_exact_only_optional",
                    "qa_required": True,
                    "qa_reference_path": str(packet),
                    "qa_checks": ["title_structure"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return packet, raw

    def run_normalizer(
        self,
        root: Path,
        packet: Path,
        raw: Path,
        page_title_map: Optional[dict[str, str]] = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
                sys.executable,
                str(SCRIPT),
                "--input",
                str(raw),
                "--output",
                str(root / "normalized.json"),
                "--page-id",
                "P29",
                "--canonical-title",
                "RA 携手 Microsoft、Cisco,共筑可信工业数据底座",
                "--source-packet",
                str(packet),
            ]
        if page_title_map is not None:
            command.extend(
                ["--page-title-map-json", json.dumps(page_title_map, ensure_ascii=False)]
            )
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
        )

    def test_loose_shape_is_normalized_without_guessing_title(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, raw = self.fixture(root)
            result = self.run_normalizer(root, packet, raw)
            self.assertEqual(result.returncode, 0, result.stderr)
            normalized = json.loads((root / "normalized.json").read_text())
            deck = normalized["deck_title_system"]
            self.assertTrue(deck["logo"]["required"])
            self.assertTrue(deck["main_title"]["required"])
            self.assertEqual(
                deck["main_title"]["text"],
                "RA 携手 Microsoft、Cisco,共筑可信工业数据底座",
            )
            self.assertEqual(
                normalized["authorization"]["source_path"], str(packet.resolve())
            )
            self.assertFalse(
                normalized["normalization_provenance"]
                ["authorization_inferred_from_asset_presence"]
            )
            self.assertNotIn("qa_reference_path", deck)

    def test_missing_required_flags_are_rejected_instead_of_silent_false(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, raw = self.fixture(root)
            value = json.loads(raw.read_text())
            value["logo"].pop("required")
            value["main_title"].pop("required")
            raw.write_text(json.dumps(value), encoding="utf-8")
            result = self.run_normalizer(root, packet, raw)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("不会根据资产存在", result.stderr)
            self.assertFalse((root / "normalized.json").exists())

    def test_explicit_optional_logo_does_not_route_library_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, raw = self.fixture(root, required=False)
            result = self.run_normalizer(root, packet, raw)
            self.assertEqual(result.returncode, 0, result.stderr)
            deck = json.loads((root / "normalized.json").read_text())[
                "deck_title_system"
            ]
            self.assertFalse(deck["logo"]["required"])
            self.assertNotIn("assets_by_tone", deck["logo"])

    def test_shared_normalizer_projects_distinct_titles_for_multiple_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, raw = self.fixture(root)
            value = json.loads(raw.read_text())
            value["deck_title_system"]["scope"]["include_page_ids"] = [
                "P29",
                "P30",
            ]
            raw.write_text(json.dumps(value), encoding="utf-8")
            title_map = {
                "P29": "RA 携手 Microsoft、Cisco,共筑可信工业数据底座",
                "P30": "从趋势判断走向执行蓝图",
            }
            result = self.run_normalizer(
                root, packet, raw, page_title_map=title_map
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            path = root / "normalized.json"
            formal_path, contract, contract_sha = pipeline.read_global_chrome_contract(
                path
            )
            self.assertEqual(
                contract["deck_title_system"]["main_title"]["text_by_page"],
                title_map,
            )
            p29 = pipeline.global_chrome_projection(
                contract,
                contract_path=formal_path,
                contract_sha256=contract_sha,
                page_id="P29",
                style="A",
                tone="dark",
                language="zh-CN",
            )
            p30 = pipeline.global_chrome_projection(
                contract,
                contract_path=formal_path,
                contract_sha256=contract_sha,
                page_id="P30",
                style="C",
                tone="light",
                language="zh-CN",
            )
            self.assertEqual(p29["main_title"]["text"], title_map["P29"])
            self.assertEqual(p30["main_title"]["text"], title_map["P30"])
            self.assertNotIn("text_by_page", p30["main_title"])


if __name__ == "__main__":
    unittest.main()
