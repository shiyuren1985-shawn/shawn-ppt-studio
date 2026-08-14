from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pipeline_control as pipeline


class SlideIdentityBindingTests(unittest.TestCase):
    def write_outline(self, text: str) -> Path:
        root = Path(self.temp.name)
        path = root / "outline.md"
        path.write_text(text, encoding="utf-8")
        return path

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="slide-identity-test-")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_projects_immutable_uids_to_requested_pages(self) -> None:
        path = self.write_outline(
            "---\n"
            "deck_uid: EPC_海外交付\n"
            "slide_identity_required: true\n"
            "slide_uids:\n"
            "  P6: EPC_一个品牌一个公司\n"
            "  P21: EPC_自动化调试风险\n"
            "---\n"
        )
        identity = pipeline.slide_identity_from_file(path, ["06", "21"])
        self.assertEqual(identity["deck_uid"], "EPC_海外交付")
        self.assertEqual(
            identity["slide_uids"],
            {"06": "EPC_一个品牌一个公司", "21": "EPC_自动化调试风险"},
        )

    def test_reorder_uses_uid_map_not_page_title(self) -> None:
        path = self.write_outline(
            "---\n"
            "deck_uid: EPC_海外交付\n"
            "slide_identity_required: true\n"
            "slide_uids:\n"
            "  P7: EPC_海外返修折返\n"
            "  P22: EPC_ProcessPower统一架构\n"
            "---\n"
            "| 页码 | 标题 |\n"
            "|---|---|\n"
            "| P7 | 标题以后可以修改 |\n"
            "| P22 | 另一个可修改标题 |\n"
        )
        identity = pipeline.slide_identity_from_file(path, ["22", "07"])
        self.assertEqual(identity["slide_uids"]["22"], "EPC_ProcessPower统一架构")
        self.assertEqual(identity["slide_uids"]["07"], "EPC_海外返修折返")

    def test_missing_target_uid_stops_before_generation(self) -> None:
        path = self.write_outline(
            "---\n"
            "deck_uid: EPC_海外交付\n"
            "slide_identity_required: true\n"
            "slide_uids:\n"
            "  P6: EPC_一个品牌一个公司\n"
            "---\n"
        )
        with self.assertRaisesRegex(SystemExit, "缺少正式页面"):
            pipeline.slide_identity_from_file(path, ["07"])

    def test_duplicate_uid_is_rejected_but_numeric_uid_only_warns(self) -> None:
        duplicate = self.write_outline(
            "---\n"
            "deck_uid: EPC_海外交付\n"
            "slide_identity_required: true\n"
            "slide_uids:\n"
            "  P6: EPC_同一内容\n"
            "  P7: EPC_同一内容\n"
            "---\n"
        )
        with self.assertRaisesRegex(SystemExit, "重复 slide_uid"):
            pipeline.slide_identity_from_file(duplicate, ["06", "07"])
        numeric = self.write_outline(
            "---\n"
            "deck_uid: EPC_海外交付\n"
            "slide_identity_required: true\n"
            "slide_uids:\n"
            "  P6: EPC_页面6\n"
            "---\n"
        )
        identity = pipeline.slide_identity_from_file(numeric, ["06"])
        self.assertEqual(identity["slide_uids"]["06"], "EPC_页面6")
        self.assertTrue(identity["naming_warnings"])

    def test_uid_fields_without_explicit_opt_in_are_ignored(self) -> None:
        path = self.write_outline(
            "---\n"
            "deck_uid: EPC_海外交付\n"
            "slide_uids:\n"
            "  P6: EPC_一个品牌一个公司\n"
            "---\n"
        )
        self.assertIsNone(pipeline.slide_identity_from_file(path, ["06"]))

    def test_discovers_only_exact_opted_in_sibling_sidecar(self) -> None:
        root = Path(self.temp.name)
        source = root / "outline.md"
        source.write_text("# P06\nContent\n", encoding="utf-8")
        sidecar = root / "outline_饱和式UID版.md"
        sidecar.write_text(
            "---\nslide_identity_required: true\ndeck_uid: EPC_海外交付\n"
            "slide_uids:\n  P6: EPC_一个品牌一个公司\n---\n",
            encoding="utf-8",
        )
        self.assertEqual(
            pipeline.discover_sibling_slide_identity_file(source),
            sidecar.resolve(),
        )

        sidecar.write_text(
            "---\ndeck_uid: EPC_海外交付\n"
            "slide_uids:\n  P6: EPC_一个品牌一个公司\n---\n",
            encoding="utf-8",
        )
        self.assertIsNone(
            pipeline.discover_sibling_slide_identity_file(source)
        )

    def test_multiple_exact_identity_sidecars_require_explicit_choice(self) -> None:
        root = Path(self.temp.name)
        source = root / "outline.md"
        source.write_text("# P06\nContent\n", encoding="utf-8")
        payload = (
            "---\nslide_identity_required: true\ndeck_uid: EPC_海外交付\n"
            "slide_uids:\n  P6: EPC_一个品牌一个公司\n---\n"
        )
        (root / "outline_饱和式UID版.md").write_text(payload, encoding="utf-8")
        (root / "outline_slide_identity.md").write_text(payload, encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "显式指定"):
            pipeline.discover_sibling_slide_identity_file(source)

    def test_explicit_identity_file_from_task_init_is_used(self) -> None:
        root = Path(self.temp.name)
        project = root / "run"
        state_dir = project / "state"
        state_dir.mkdir(parents=True)
        source = root / "plain-outline.md"
        source.write_text("# 普通权威大纲\n", encoding="utf-8")
        identity_path = self.write_outline(
            "---\n"
            "deck_uid: EPC_海外交付\n"
            "slide_identity_required: true\n"
            "slide_uids:\n"
            "  P6: EPC_一个品牌一个公司\n"
            "---\n"
        )
        state_path = state_dir / "style_run_state.json"
        state_path.write_text("{}\n", encoding="utf-8")
        (state_dir / "task_init.json").write_text(
            __import__("json").dumps(
                {
                    "task_init_contract_version": 1,
                    "project_dir": str(project.resolve()),
                    "source_snapshot_required": True,
                    "slide_identity_file": {
                        "path": str(identity_path.resolve()),
                        "sha256": pipeline.file_sha256(identity_path),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        identity = pipeline.resolve_slide_identity(
            {}, state_path, source, ["06"]
        )
        self.assertEqual(identity["slide_uids"]["06"], "EPC_一个品牌一个公司")

    def test_future_handoff_candidates_receive_content_uid(self) -> None:
        candidates = [
            {"page_id": "06", "path": "/tmp/candidate-a.png"},
            {"page_id": "P21", "path": "/tmp/candidate-b.png"},
        ]
        pipeline.attach_slide_identity_to_candidates(
            candidates,
            {
                "deck_uid": "EPC_海外交付",
                "slide_uids": {
                    "P6": "EPC_一个品牌一个公司",
                    "21": "EPC_自动化调试风险",
                },
            },
        )
        self.assertEqual(candidates[0]["deck_uid"], "EPC_海外交付")
        self.assertEqual(candidates[0]["slide_uid"], "EPC_一个品牌一个公司")
        self.assertEqual(candidates[1]["slide_uid"], "EPC_自动化调试风险")


if __name__ == "__main__":
    unittest.main()
