from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "init_task_dir.py"


class SelectedStyleInitializerTest(unittest.TestCase):
    def run_init(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def fake_pillow_python(root: Path) -> Path:
        executable = root / "overview-python"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        return executable

    @staticmethod
    def base_args(
        root: Path, source: Path, primary: Path, overview_python: Path
    ) -> list[str]:
        return [
            "--output-root",
            str(root / "output"),
            "--task-name",
            "epc_selected_style_expansion_20260807",
            "--run-mode",
            "selected_style_expansion",
            "--selected-style",
            "c",
            "--page-ids",
            "P2,010",
            "--source-file",
            str(source),
            "--anchor",
            f"{primary}::primary",
            "--anchor-approval-scope",
            "style_anchor_only",
            "--overview-python",
            str(overview_python),
        ]

    def test_creates_frozen_packet_state_and_canonical_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selected_style_init_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text(
                "# Shared deck purpose\nInternal audience only.\n\n"
                "## P02 Low density\nAlpha fact；keep：punctuation！\n\n"
                "# P03 UNREQUESTED_SENTINEL\nThis must never enter the packet.\n\n"
                "## Page 10 Architecture\nBeta fact\n\n"
                "## Source index\nDeck evidence only.\n",
                encoding="utf-8",
            )
            primary = root / "primary.png"
            supporting = root / "supporting.png"
            page_note = root / "P02_note.md"
            deck_note = root / "deck_title.md"
            primary.write_bytes(b"primary-anchor")
            supporting.write_bytes(b"supporting-anchor")
            page_note.write_text("# P2 page note\nVerified detail.\n", encoding="utf-8")
            deck_note.write_text("Shared title contract.\n", encoding="utf-8")
            overview_python = self.fake_pillow_python(root)
            args = self.base_args(root, source, primary, overview_python)
            args.extend([
                "--anchor", f"{supporting}::supporting",
                "--supporting-source", f"{page_note}::P02",
                "--supporting-source", f"{deck_note}::deck",
            ])

            result = self.run_init(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            project = Path(payload["project_dir"])
            state_path = Path(payload["state"])
            packet_path = (
                project
                / "state"
                / "director_inputs"
                / "authoritative_expansion_packet.json"
            )
            self.assertEqual(
                state_path, project / "state" / "selected_style_run_state.json"
            )
            for relative in (
                "page_jobs",
                "page_jobs/repair_jobs",
                "state/director_inputs",
            ):
                self.assertTrue((project / relative).is_dir())

            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertEqual(packet["selected_style_expansion_packet_contract_version"], 2)
            self.assertEqual(packet["page_order"], ["02", "10"])
            self.assertNotIn("authoritative_source_text", packet)
            self.assertNotIn("UNREQUESTED_SENTINEL", packet_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [item["page_id"] for item in packet["pages"]], ["02", "10"]
            )
            self.assertIn("Alpha fact", packet["pages"][0]["normalized_text"])
            self.assertIn("Alpha fact；keep：punctuation！", packet["pages"][0]["exact_text"])
            self.assertIn("Beta fact", packet["pages"][1]["normalized_text"])
            self.assertNotIn("Deck evidence only", packet["pages"][1]["normalized_text"])
            self.assertIn("Internal audience only", packet["deck_context"]["exact_text"])
            self.assertIn("Deck evidence only", packet["deck_context"]["exact_text"])
            self.assertEqual(packet["anchor_approval_scope"], "style_anchor_only")
            self.assertEqual(
                [item["role"] for item in packet["style_anchors"]],
                ["primary", "supporting"],
            )
            self.assertEqual(packet["pages"][0]["supporting_sources"][0]["path"], str(page_note.resolve()))
            self.assertIn("Verified detail", packet["pages"][0]["supporting_sources"][0]["exact_text"])
            self.assertEqual(packet["pages"][1]["supporting_sources"], [])
            self.assertEqual(len(packet["deck_shared_sources"]), 1)
            self.assertEqual(packet_path.read_text(encoding="utf-8").count("Shared title contract."), 1)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["run_mode"], "selected_style_expansion")
            self.assertEqual(state["phase"], "selected_style_expansion")
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["selected_style"], "C")
            self.assertEqual(state["page_order"], ["02", "10"])
            self.assertEqual(set(state["pages"]), {"02", "10"})
            self.assertTrue(
                all(item["status"] == "pending" for item in state["pages"].values())
            )
            self.assertEqual(state["preflight"]["status"], "resolved")
            self.assertEqual(
                [item["name"] for item in state["events"]],
                ["process_started", "preflight_resolved"],
            )
            self.assertEqual(state["scheduler"]["active_actions"], [])
            self.assertEqual(state["scheduler"]["ready_queue"], [])
            self.assertEqual(state["scheduler"]["recovery_queue"], [])
            self.assertEqual(state["scheduler"]["active_child_limit"], 8)
            self.assertEqual(
                state["source_packet_sha256"],
                hashlib.sha256(packet_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                state["source"]["sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                state["style_anchors"][0]["sha256"],
                hashlib.sha256(primary.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                state["supporting_sources"][0]["sha256"],
                hashlib.sha256(page_note.read_bytes()).hexdigest(),
            )
            self.assertEqual(state["supporting_sources"][0]["applies_to_page_ids"], ["02"])
            self.assertEqual(
                state["overview_runtime"]["python"], str(overview_python.resolve())
            )

    def test_invalid_source_page_fails_before_formal_directory_allocation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selected_style_bad_page_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text("# P02\nOnly page two\n", encoding="utf-8")
            primary = root / "primary.png"
            primary.write_bytes(b"primary")
            overview_python = self.fake_pillow_python(root)

            result = self.run_init(
                *self.base_args(root, source, primary, overview_python)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("页面 10", result.stderr)
            self.assertFalse(
                (root / "output" / "epc_selected_style_expansion_20260807").exists()
            )

    def test_anchorless_multi_page_defaults_to_director_text_family(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selected_style_anchorless_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text("# P02\nTwo\n\n# P10\nTen\n", encoding="utf-8")
            overview_python = self.fake_pillow_python(root)
            result = self.run_init(
                "--output-root", str(root / "output"),
                "--task-name", "anchorless_multi_page",
                "--run-mode", "selected_style_expansion",
                "--page-ids", "02,10",
                "--source-file", str(source),
                "--overview-python", str(overview_python),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            state = json.loads(Path(payload["state"]).read_text(encoding="utf-8"))
            packet = json.loads(
                Path(state["source_packet_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(state["selected_style"], "A")
            self.assertEqual(state["style_anchors"], [])
            self.assertEqual(state["visual_family_source"], "director_defined_text_family")
            self.assertEqual(packet["style_anchors"], [])
            self.assertEqual(packet["visual_family_source"], "director_defined_text_family")

            rejected = self.run_init(
                "--output-root", str(root / "other-output"),
                "--task-name", "anchorless_final_anchor_scope",
                "--run-mode", "selected_style_expansion",
                "--page-ids", "02,10",
                "--source-file", str(source),
                "--anchor-approval-scope", "final_page_and_anchor",
                "--overview-python", str(overview_python),
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("无锚点逐页制作不能使用 final_page_and_anchor", rejected.stderr)

    def test_provided_anchors_require_one_primary_and_rejects_args_without_opt_in(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selected_style_anchor_gate_") as temp:
            root = Path(temp)
            source = root / "outline.json"
            source.write_text(
                json.dumps(
                    {"pages": [{"page_id": "02", "title": "Two"}, {"page_id": "10", "title": "Ten"}]}
                ),
                encoding="utf-8",
            )
            primary = root / "primary.png"
            primary.write_bytes(b"primary")
            overview_python = self.fake_pillow_python(root)
            args = self.base_args(root, source, primary, overview_python)
            primary_index = args.index(f"{primary}::primary")
            args[primary_index] = f"{primary}::supporting"
            bad_anchor = self.run_init(*args)
            self.assertNotEqual(bad_anchor.returncode, 0)
            self.assertIn("一个 primary", bad_anchor.stderr)

            no_opt_in = self.run_init(
                "--output-root",
                str(root / "other-output"),
                "--task-name",
                "P02_existing_20260807_8x1",
                "--selected-style",
                "A",
            )
            self.assertNotEqual(no_opt_in.returncode, 0)
            self.assertIn("--run-mode selected_style_expansion", no_opt_in.stderr)

    def test_same_task_name_allocates_new_directory_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selected_style_no_overwrite_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text(
                "# P02\nTwo\n\n# P10\nTen\n", encoding="utf-8"
            )
            primary = root / "primary.png"
            primary.write_bytes(b"primary")
            overview_python = self.fake_pillow_python(root)
            args = self.base_args(root, source, primary, overview_python)
            first = self.run_init(*args)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_payload = json.loads(first.stdout)
            first_state = Path(first_payload["state"])
            first_bytes = first_state.read_bytes()

            second = self.run_init(*args)
            self.assertEqual(second.returncode, 0, second.stderr)
            second_payload = json.loads(second.stdout)
            self.assertNotEqual(first_payload["project_dir"], second_payload["project_dir"])
            self.assertTrue(second_payload["project_dir"].endswith("_02"))
            self.assertEqual(first_state.read_bytes(), first_bytes)

    def test_supporting_source_requires_explicit_page_or_deck_scope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selected_style_scope_gate_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text("# P02\nTwo\n\n# P10\nTen\n", encoding="utf-8")
            support = root / "P02_note.md"
            support.write_text("Only page two.\n", encoding="utf-8")
            primary = root / "primary.png"
            primary.write_bytes(b"primary")
            overview_python = self.fake_pillow_python(root)
            result = self.run_init(
                *self.base_args(root, source, primary, overview_python),
                "--supporting-source", str(support),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("绝对路径::P02,P05", result.stderr)

    def test_rejects_independent_slide_identity_for_new_selected_style(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selected_style_identity_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text("# P02\nTwo\n\n# P10\nTen\n", encoding="utf-8")
            identity = root / "slide_identity.md"
            identity.write_text(
                "---\nslide_identity_required: true\ndeck_uid: EPC_测试\n"
                "slide_uids:\n  P2: EPC_页面二\n  P10: EPC_页面十\n---\n",
                encoding="utf-8",
            )
            primary = root / "primary.png"
            primary.write_bytes(b"primary")
            overview_python = self.fake_pillow_python(root)
            result = self.run_init(
                *self.base_args(root, source, primary, overview_python),
                "--slide-identity-file", str(identity.resolve()),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("不接受独立 slide identity 文件", result.stderr)

    def test_does_not_auto_discover_identity_sidecar_for_selected_style(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selected_style_identity_auto_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text("# P02\nTwo\n\n# P10\nTen\n", encoding="utf-8")
            identity = root / "outline_饱和式UID版.md"
            identity.write_text(
                "---\nslide_identity_required: true\ndeck_uid: EPC_测试\n"
                "slide_uids:\n  P2: EPC_页面二\n  P10: EPC_页面十\n---\n",
                encoding="utf-8",
            )
            primary = root / "primary.png"
            primary.write_bytes(b"primary")
            overview_python = self.fake_pillow_python(root)
            result = self.run_init(
                *self.base_args(root, source, primary, overview_python)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            task_init = json.loads(
                Path(json.loads(result.stdout)["task_init_contract"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertNotIn("slide_identity_file", task_init)

    def test_deck_contract_scope_and_page_maps_are_projected_to_target_pages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="selected_style_deck_projection_") as temp:
            root = Path(temp)
            source = root / "outline.md"
            source.write_text("# P02\nTwo\n\n# P10\nTen\n", encoding="utf-8")
            deck = root / "deck_contract.json"
            deck.write_text(json.dumps({
                "deck_title_system": {
                    "scope": {
                        "include_page_ids": ["P02", "P03", "P10", "P30"],
                        "exclude_page_ids": ["P05"],
                        "special_page_note": "P03 and P30 use old exceptions",
                    },
                    "main_title": {
                        "text_by_page": {
                            "P02": "Two", "P03": "Three", "P10": "Ten", "P30": "Thirty"
                        }
                    },
                    "prompt_briefs": {"en": "Use one shared title hierarchy."},
                }
            }, ensure_ascii=False), encoding="utf-8")
            primary = root / "primary.png"
            primary.write_bytes(b"primary")
            overview_python = self.fake_pillow_python(root)
            result = self.run_init(
                *self.base_args(root, source, primary, overview_python),
                "--supporting-source", f"{deck}::deck",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            project = Path(json.loads(result.stdout)["project_dir"])
            packet_path = project / "state/director_inputs/authoritative_expansion_packet.json"
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertEqual(len(packet["deck_shared_sources"]), 1)
            deck_record = packet["deck_shared_sources"][0]
            projected = json.loads(deck_record["exact_text"])
            self.assertEqual(
                projected["deck_title_system"]["scope"]["include_page_ids"],
                ["P02", "P10"],
            )
            self.assertEqual(
                projected["deck_title_system"]["main_title"]["text_by_page"],
                {"P02": "Two", "P10": "Ten"},
            )
            packet_text = packet_path.read_text(encoding="utf-8")
            self.assertNotIn("P03", packet_text)
            self.assertNotIn("P30", packet_text)
            self.assertEqual(deck_record["applies_to_page_ids"], ["02", "10"])
            self.assertEqual(deck_record["projection_kind"], "target_page_scope_intersection_v1")


if __name__ == "__main__":
    unittest.main()
