from __future__ import annotations

import importlib.util
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_4x3_source_packet.py"
SPEC = importlib.util.spec_from_file_location("build_4x3_source_packet_test", SCRIPT)
assert SPEC and SPEC.loader
packet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packet)


class FourByThreeSourcePacketTest(unittest.TestCase):
    def test_keeps_shared_prose_and_exact_three_rows(self) -> None:
        text = """# Shared title rule

| Page | Title | Claim |
|---|---|---|
| P1 | One | omit |
| P2 | Two | anchor |
| P3 | Three | follower |
| P4 | Four | omit |
| P5 | Five | follower |
"""
        result = packet.markdown_packet(text, ["P2", "P3", "P5"])
        self.assertIn("# Shared title rule", result)
        self.assertIn("| P2 |", result)
        self.assertIn("| P3 |", result)
        self.assertIn("| P5 |", result)
        self.assertNotIn("| P1 |", result)
        self.assertNotIn("| P4 |", result)

    def test_heading_outline_keeps_shared_context_and_exact_three_pages(self) -> None:
        text = """# Shared purpose

## P1｜One
omit

## P2｜Two
anchor

## P3｜Three
follower

## P4｜Four
omit

## P5｜Five
follower

## Evidence index
shared evidence
"""
        result = packet.markdown_packet(text, ["P2", "P3", "P5"])
        self.assertIn("Shared purpose", result)
        self.assertIn("P2|Two", result)
        self.assertIn("P3|Three", result)
        self.assertIn("P5|Five", result)
        self.assertIn("Evidence index", result)
        self.assertNotIn("P1|One", result)
        self.assertNotIn("P4|Four", result)

    def test_atomic_packet_refuses_source_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="four_by_three_packet_") as temp:
            output = Path(temp) / "packet.md"
            self.assertEqual(packet.fast_packet.atomic_write_once(output, "first\n"), "frozen")
            self.assertEqual(
                packet.fast_packet.atomic_write_once(output, "first\n"),
                "already_frozen",
            )
            with self.assertRaisesRegex(SystemExit, "已经存在且内容不同"):
                packet.fast_packet.atomic_write_once(output, "second\n")

    def test_snapshot_json_has_one_record_per_page_and_routes_page_notes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="four_by_three_snapshot_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text(
                """# Shared rule

| Page | Title | Claim |
|---|---|---|
| P2 | Two | anchor |
| P3 | Three | follower |
| P5 | Five | follower |
""",
                encoding="utf-8",
            )
            p2 = root / "P02_detail.md"
            p2.write_text("# P02 detail\nOnly anchor evidence.\n", encoding="utf-8")
            shared = root / "shared_rules.md"
            shared.write_text("Shared supporting rule.\n", encoding="utf-8")
            value = packet.build_snapshot_source(
                source, ["P2", "P3", "P5"], [p2, shared]
            )
            self.assertEqual(set(value["pages"]), {"P2", "P3", "P5"})
            self.assertIn("Only anchor evidence", value["pages"]["P2"]["normalized_source"])
            self.assertNotIn("Only anchor evidence", value["pages"]["P3"]["normalized_source"])
            self.assertIn("Shared supporting rule", value["pages"]["P5"]["normalized_source"])
            path = root / "snapshot_source.json"
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            extracted = packet.pc.extract_relevant_source_content(
                path, ["P2", "P3", "P5"]
            )
            self.assertEqual(
                [item["page_id"] for item in extracted["pages"]],
                ["P2", "P3", "P5"],
            )

    def test_cli_requires_snapshot_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="four_by_three_cli_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text(
                "| Page | Title |\n|---|---|\n| P2 | Two |\n| P3 | Three |\n| P5 | Five |\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    str(source),
                    "--pages",
                    "P2,P3,P5",
                    "--output",
                    str(root / "packet.md"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("--snapshot-output", completed.stderr)


if __name__ == "__main__":
    unittest.main()
