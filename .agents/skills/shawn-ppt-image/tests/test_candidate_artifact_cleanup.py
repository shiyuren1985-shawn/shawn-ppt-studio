import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "plan_candidate_artifact_cleanup.py"
SPEC = importlib.util.spec_from_file_location("candidate_artifact_cleanup", MODULE_PATH)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = planner
SPEC.loader.exec_module(planner)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_image(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png-" + marker.encode())


class CandidateArtifactCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="candidate-artifact-cleanup-")
        self.root = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def fast8_fixture(self) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        styles: dict[str, object] = {}
        for style in "ABCDEFGH":
            image = self.root / "origin_image" / f"style_{style}_page_P24.png"
            write_image(image, style)
            paths[style] = image
            styles[style] = {"pages": {"P24": {"final_path": str(image)}}}
            write_json(
                self.root / "style_jobs" / f"style_{style}.json",
                {
                    "style_slot": style,
                    "page_id": "P24",
                    "output_target": str(image),
                    "imagegen_referenced_paths": (
                        [str(paths["A"])] if style != "A" else []
                    ),
                },
            )
            write_json(
                self.root / "state" / "burst_claims" / f"claim_{style}_page_P24_generate_anchor_attempt_1.json",
                {"style": style, "page_id": "P24"},
            )
            write_json(
                self.root / "style_jobs" / "results" / f"worker_receipt_{style}_page_P24_generate_anchor_attempt_1.json",
                {"style": style, "page_id": "P24", "saved_path": str(image)},
            )
        write_json(
            self.root / "state" / "style_run_state.json",
            {"project_dir": str(self.root), "run_mode": "fast_8x1_diverse", "styles": styles},
        )
        write_json(
            self.root / "content_contracts" / "page_P24.json",
            {"page_id": "P24", "title": "shared by all eight styles"},
        )
        write_json(self.root / "state" / "handoff.json", {"candidates": list(map(str, paths.values()))})
        return paths

    def test_delete_seven_keeps_eighth_and_shared_state(self) -> None:
        paths = self.fast8_fixture()
        plan = planner.build_plan(str(self.root), [str(paths[style]) for style in "ABCDEFG"])
        targets = {Path(item["path"]) for item in plan["targets"]}
        self.assertEqual(plan["strategy"], "partial")
        self.assertEqual(plan["retained_candidate_paths"], [str(paths["H"])])
        for style in "ABCDEFG":
            self.assertIn(paths[style], targets)
            self.assertIn(self.root / "style_jobs" / f"style_{style}.json", targets)
        self.assertNotIn(paths["H"], targets)
        self.assertNotIn(self.root / "style_jobs" / "style_H.json", targets)
        self.assertNotIn(self.root / "content_contracts" / "page_P24.json", targets)
        self.assertNotIn(self.root / "state" / "style_run_state.json", targets)
        self.assertNotIn(self.root / "state" / "handoff.json", targets)

    def test_last_existing_candidate_moves_whole_run(self) -> None:
        paths = self.fast8_fixture()
        for style in "ABCDEFG":
            paths[style].unlink()
        plan = planner.build_plan(str(self.root), [str(paths["H"])])
        self.assertEqual(plan["strategy"], "whole_run")
        self.assertEqual(plan["targets"], [{
            "path": str(self.root), "kind": "directory", "reason": "last_candidate_run"
        }])

    def test_referenced_retained_anchor_does_not_keep_deleted_follower_job(self) -> None:
        paths = self.fast8_fixture()
        plan = planner.build_plan(str(self.root), [str(paths["B"])])
        targets = {Path(item["path"]) for item in plan["targets"]}
        self.assertIn(self.root / "style_jobs" / "style_B.json", targets)
        self.assertNotIn(self.root / "style_jobs" / "style_A.json", targets)
        self.assertIn(str(paths["A"]), plan["retained_candidate_paths"])

    def test_unknown_candidate_fails_closed(self) -> None:
        self.fast8_fixture()
        unknown = self.root / "origin_image" / "unknown.png"
        write_image(unknown, "unknown")
        with self.assertRaises(planner.CleanupPlanError):
            planner.build_plan(str(self.root), [str(unknown)])

    def test_partial_selected_style_cleanup_keeps_frozen_page_contracts(self) -> None:
        pages: dict[str, object] = {}
        paths: dict[str, Path] = {}
        for page in ("08", "09"):
            image = self.root / "origin_image" / f"style_A_page_{page}.png"
            write_image(image, page)
            paths[page] = image
            pages[page] = {"final_path": str(image)}
            write_json(self.root / "page_jobs" / f"page_{page}.json", {
                "style_slot": "A", "page_id": page, "output_target": str(image)
            })
            write_json(self.root / "content_contracts" / f"page_{page}.json", {"page_id": page})
            write_json(self.root / "state" / "selected_style_claims" / f"claim_A_{page}_generate_page_1.json", {
                "style": "A", "page_id": page
            })
        write_json(self.root / "state" / "selected_style_run_state.json", {
            "project_dir": str(self.root),
            "run_mode": "selected_style_expansion",
            "selected_style": "A",
            "pages": pages,
        })
        plan = planner.build_plan(str(self.root), [str(paths["08"])])
        targets = {Path(item["path"]) for item in plan["targets"]}
        self.assertIn(self.root / "page_jobs" / "page_08.json", targets)
        self.assertNotIn(self.root / "content_contracts" / "page_08.json", targets)
        self.assertNotIn(self.root / "page_jobs" / "page_09.json", targets)
        self.assertNotIn(self.root / "content_contracts" / "page_09.json", targets)


if __name__ == "__main__":
    unittest.main()
