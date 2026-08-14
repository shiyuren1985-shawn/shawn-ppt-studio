from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "single_image_edit_control_plane_v1.py"
SPEC = importlib.util.spec_from_file_location("single_image_edit_control_plane_v1_test", MODULE_PATH)
assert SPEC and SPEC.loader
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path: Path, color: tuple[int, int, int], width: int = 1200, height: int = 675) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = b"\x00" + bytes(color) * width
    raw = row * height
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, 1))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


class SingleImageEditControlPlaneV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.candidate_root = self.root / "output"
        self.candidate_root.mkdir()
        self.generated_root = self.root / "generated_images"
        self.generated_root.mkdir()
        self.generated_patch = mock.patch.object(
            control, "GENERATED_IMAGES_ROOT", self.generated_root.resolve()
        )
        self.generated_patch.start()
        self.slot_registry = self.root / "monitoring" / "runtime" / "imagegen_slots.json"
        self.slot_env = mock.patch.dict(
            control.os.environ,
            {"SHAWN_PPT_IMAGE_GLOBAL_SLOT_STATE": str(self.slot_registry)},
        )
        self.slot_env.start()

        self.outline = self.root / "outline.md"
        self.outline.write_text(
            "---\n"
            "deck_uid: EPC_DECK\n"
            "slide_identity_required: true\n"
            "slide_uids:\n"
            "  P05: EPC_SLIDE_5\n"
            "---\n"
            "| P05 | Test title | Test point | Low | Required | Open |\n",
            encoding="utf-8",
        )
        self.revision = f"sha256:{sha256(self.outline)}"

        self.parent_project = self.candidate_root / "P05_parent"
        parent_state = self.parent_project / "state" / "style_run_state.json"
        parent_snapshot = self.parent_project / "state" / "source_snapshot.json"
        self.parent_image = self.parent_project / "origin_image" / "style_A_page_P05.png"
        write_png(self.parent_image, (10, 20, 30))
        write_json(parent_state, {"run_id": "fast8-parent", "status": "completed"})
        write_json(parent_snapshot, {"run_id": "fast8-parent", "page_ids": ["P05"]})
        self.parent_handoff = self.parent_project / "state" / "handoff.json"
        write_json(
            self.parent_handoff,
            {
                "handoff_contract_version": 1,
                "run_id": "fast8-parent",
                "run_mode": "fast_8x1_diverse",
                "project_dir": str(self.parent_project),
                "pipeline_status": "completed",
                "status": "candidate_ready",
                "state_ref": {"path": str(parent_state), "sha256": sha256(parent_state)},
                "source_snapshot_ref": {
                    "path": str(parent_snapshot),
                    "sha256": sha256(parent_snapshot),
                },
                "slide_identity": {
                    "required": True,
                    "deck_uid": "EPC_DECK",
                    "slide_uids": {"P05": "EPC_SLIDE_5"},
                    "source_path": str(self.outline),
                    "source_sha256": sha256(self.outline),
                },
                "candidates": [
                    {
                        "candidate_id": "A-P05",
                        "style_slot": "A",
                        "page_id": "P05",
                        "path": str(self.parent_image),
                        "width": 1200,
                        "height": 675,
                        "sha256": sha256(self.parent_image),
                        "status": "candidate_ready",
                        "deck_uid": "EPC_DECK",
                        "slide_uid": "EPC_SLIDE_5",
                    }
                ],
                "user_selection": {"selected": False},
            },
        )
        self.parent_handoff_sha = sha256(self.parent_handoff)

    def tearDown(self) -> None:
        self.slot_env.stop()
        self.generated_patch.stop()
        self.temp.cleanup()

    def args(self, **overrides) -> argparse.Namespace:
        values = {
            "candidate_root": str(self.candidate_root),
            "outline_path": str(self.outline),
            "expected_revision": self.revision,
            "deck_uid": "EPC_DECK",
            "slide_uid": "EPC_SLIDE_5",
            "page_id": "P05",
            "parent_handoff_path": str(self.parent_handoff),
            "parent_handoff_sha256": self.parent_handoff_sha,
            "parent_candidate_id": "A-P05",
            "user_request_sha256": hashlib.sha256("Make it orange".encode()).hexdigest(),
            "request_started_at": "2026-08-12T14:00:00.000Z",
            "execute_key": "1" * 64,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def direct_args(self, **overrides) -> argparse.Namespace:
        direct_refs = {
            "deck_uid": "EPC_DECK",
            "slide_uid": "EPC_SLIDE_5",
            "candidate_id": "legacy-confirmed-P05",
            "path": str(self.parent_image),
            "sha256": sha256(self.parent_image),
            "width": 1200,
            "height": 675,
            "source_revision_status": "unrecorded",
        }
        direct_refs.update(overrides.pop("direct_refs", {}))
        return self.args(
            parent_handoff_path=None,
            parent_handoff_sha256=None,
            parent_candidate_id=None,
            direct_parent_refs_json=json.dumps(direct_refs, ensure_ascii=False),
            execute_key="2" * 64,
            **overrides,
        )

    def test_prepare_complete_verify_and_discovery_compatible_handoff(self) -> None:
        selection = self.root / "selection.json"
        selection.write_text('{"unchanged":true}\n', encoding="utf-8")
        selection_before = selection.read_bytes()
        parent_before = self.parent_image.read_bytes()

        prepared = control.prepare_edit(self.args())
        self.assertEqual(prepared["status"], "prepared")
        state_path = Path(prepared["state_path"])
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["parent_candidate"]["candidate_id"], "A-P05")
        self.assertEqual(state["parent_candidate"]["source_run_id"], "fast8-parent")
        self.assertEqual(state["source_outline"]["revision"], self.revision)
        self.assertEqual(state["request"]["user_request_sha256"], self.args().user_request_sha256)

        generated = self.generated_root / "session" / "exec-edited.png"
        write_png(generated, (230, 100, 20))
        claimed = control.claim_edit(str(state_path), 0)
        self.assertEqual(claimed["status"], "claimed")
        self.assertEqual(len(json.loads(self.slot_registry.read_text())["leases"]), 1)
        completed = control.complete_edit(str(state_path), str(generated))
        self.assertEqual(len(json.loads(self.slot_registry.read_text())["leases"]), 0)
        self.assertEqual(completed["status"], "candidate_ready")
        verified = control.verify_edit(str(state_path))
        self.assertEqual(verified["native_refs"], completed["native_refs"])

        handoff = json.loads(Path(completed["native_refs"]["handoff_path"]).read_text(encoding="utf-8"))
        self.assertEqual(handoff["run_mode"], "single_image_edit")
        self.assertEqual(handoff["pipeline_status"], "completed")
        self.assertEqual(handoff["status"], "candidate_ready")
        self.assertFalse(handoff["user_selection"]["selected"])
        self.assertEqual(len(handoff["candidates"]), 1)
        candidate = handoff["candidates"][0]
        self.assertEqual(candidate["derivation_kind"], "single_image_edit")
        self.assertEqual(candidate["parent_candidate_id"], "A-P05")
        self.assertEqual(candidate["source_run_id"], "fast8-parent")
        self.assertEqual(candidate["deck_uid"], "EPC_DECK")
        self.assertEqual(candidate["slide_uid"], "EPC_SLIDE_5")
        self.assertRegex(Path(candidate["path"]).name, r"_page_P05\.png$")
        self.assertEqual(candidate["sha256"], sha256(Path(candidate["path"])))
        self.assertEqual((candidate["width"], candidate["height"]), (1200, 675))
        self.assertEqual(self.parent_image.read_bytes(), parent_before)
        self.assertEqual(selection.read_bytes(), selection_before)
        self.assertFalse(any("judge" in str(path).lower() for path in Path(prepared["project_dir"]).rglob("*")))

    def test_confirmed_direct_parent_creates_new_candidate_and_releases_shared_slot(self) -> None:
        parent_before = self.parent_image.read_bytes()
        selection = self.root / "selection.json"
        selection.write_text('{"confirmed":true}\n', encoding="utf-8")
        selection_before = selection.read_bytes()

        prepared = control.prepare_edit(self.direct_args())
        self.assertEqual(prepared["parent_candidate"]["source_kind"], "direct_selection")
        self.assertEqual(prepared["parent_candidate"]["source_revision_status"], "unrecorded")
        self.assertIsNone(prepared["parent_candidate"]["source_run_id"])
        self.assertNotEqual(Path(prepared["project_dir"]), self.parent_image.parent.parent)

        claimed = control.claim_edit(prepared["state_path"], 0)
        self.assertEqual(claimed["status"], "claimed")
        released = control.release_edit(prepared["state_path"])
        self.assertEqual(released["released"], 1)
        self.assertEqual(json.loads(self.slot_registry.read_text())["leases"], [])

        control.claim_edit(prepared["state_path"], 0)
        generated = self.generated_root / "session" / "direct-edit.png"
        write_png(generated, (230, 90, 20))
        completed = control.complete_edit(prepared["state_path"], str(generated))
        verified = control.verify_edit(prepared["state_path"])
        self.assertEqual(completed["native_refs"], verified["native_refs"])
        handoff = json.loads(Path(completed["native_refs"]["handoff_path"]).read_text())
        self.assertEqual(handoff["lineage"]["parent_source_kind"], "direct_selection")
        self.assertEqual(handoff["lineage"]["source_revision_status"], "unrecorded")
        self.assertEqual(handoff["lineage"]["parent_candidate_id"], "legacy-confirmed-P05")
        self.assertIsNone(handoff["lineage"]["source_run_id"])
        self.assertEqual(handoff["candidates"][0]["derivation_kind"], "single_image_edit")
        self.assertEqual(handoff["candidates"][0]["source_revision_status"], "unrecorded")
        self.assertEqual(json.loads(self.slot_registry.read_text())["leases"], [])
        self.assertEqual(self.parent_image.read_bytes(), parent_before)
        self.assertEqual(selection.read_bytes(), selection_before)

    def test_direct_parent_rejects_changed_bytes_and_symlink(self) -> None:
        stale_sha = sha256(self.parent_image)
        write_png(self.parent_image, (250, 1, 1))
        with self.assertRaisesRegex(control.ContractError, "hash no longer matches"):
            control.prepare_edit(self.direct_args(direct_refs={"sha256": stale_sha}))

        real_parent = self.root / "legacy-parent.png"
        write_png(real_parent, (20, 30, 40))
        linked_parent = self.root / "legacy-parent-link.png"
        linked_parent.symlink_to(real_parent)
        with self.assertRaisesRegex(control.ContractError, "not a symlink"):
            control.prepare_edit(
                self.direct_args(
                    direct_refs={
                        "path": str(linked_parent),
                        "sha256": sha256(real_parent),
                    }
                )
            )

    def test_same_execute_prepare_and_complete_are_idempotent_without_duplicate_candidate(self) -> None:
        first_prepare = control.prepare_edit(self.args())
        second_prepare = control.prepare_edit(self.args())
        self.assertTrue(second_prepare["idempotent"])
        self.assertEqual(first_prepare["project_dir"], second_prepare["project_dir"])
        generated = self.generated_root / "session" / "exec-one.png"
        write_png(generated, (1, 200, 3))
        control.claim_edit(first_prepare["state_path"], 0)
        first_complete = control.complete_edit(first_prepare["state_path"], str(generated))
        second_complete = control.complete_edit(first_prepare["state_path"], str(generated))
        self.assertFalse(first_complete["idempotent"])
        self.assertTrue(second_complete["idempotent"])
        origin = Path(first_prepare["project_dir"]) / "origin_image"
        self.assertEqual(len(list(origin.iterdir())), 1)

        different = self.generated_root / "session" / "exec-two.png"
        write_png(different, (2, 3, 220))
        with self.assertRaisesRegex(control.ContractError, "different savedPath"):
            control.complete_edit(first_prepare["state_path"], str(different))

    def test_prepare_rejects_revision_parent_hash_and_identity_drift(self) -> None:
        with self.assertRaisesRegex(control.ContractError, "revision has changed"):
            control.prepare_edit(self.args(expected_revision="sha256:" + "0" * 64))
        with self.assertRaisesRegex(control.ContractError, "handoff hash"):
            control.prepare_edit(self.args(parent_handoff_sha256="0" * 64))
        with self.assertRaisesRegex(control.ContractError, "does not map"):
            control.prepare_edit(self.args(slide_uid="WRONG"))

    def test_complete_rejects_non_imagegen_path_parent_copy_and_bad_dimensions(self) -> None:
        prepared = control.prepare_edit(self.args())
        outside = self.root / "outside.png"
        write_png(outside, (200, 1, 1))
        control.claim_edit(prepared["state_path"], 0)
        with self.assertRaisesRegex(control.ContractError, "below Codex generated_images"):
            control.complete_edit(prepared["state_path"], str(outside))
        self.assertEqual(len(json.loads(self.slot_registry.read_text())["leases"]), 0)

        copied_parent = self.generated_root / "session" / "same.png"
        copied_parent.parent.mkdir(parents=True, exist_ok=True)
        copied_parent.write_bytes(self.parent_image.read_bytes())
        control.claim_edit(prepared["state_path"], 0)
        with self.assertRaisesRegex(control.ContractError, "identical copy"):
            control.complete_edit(prepared["state_path"], str(copied_parent))
        self.assertEqual(len(json.loads(self.slot_registry.read_text())["leases"]), 0)

        bad = self.generated_root / "session" / "portrait.png"
        write_png(bad, (1, 2, 3), width=675, height=1200)
        control.claim_edit(prepared["state_path"], 0)
        with self.assertRaisesRegex(control.ContractError, "usable 16:9"):
            control.complete_edit(prepared["state_path"], str(bad))

    def test_claim_reuses_shared_central_cap5_and_release_is_idempotent(self) -> None:
        prepared = control.prepare_edit(self.args())
        claimed = control.claim_edit(prepared["state_path"], 0)
        self.assertEqual(claimed["status"], "claimed")
        registry = json.loads(self.slot_registry.read_text(encoding="utf-8"))
        self.assertEqual(registry["capacity"], 5)
        self.assertEqual(len(registry["leases"]), 1)
        self.assertEqual(registry["leases"][0]["lease_kind"], "single_image_edit_v1")
        again = control.claim_edit(prepared["state_path"], 0)
        self.assertTrue(again["idempotent"])
        self.assertEqual(len(json.loads(self.slot_registry.read_text())["leases"]), 1)
        released = control.release_edit(prepared["state_path"])
        self.assertEqual(released["released"], 1)
        self.assertEqual(len(json.loads(self.slot_registry.read_text())["leases"]), 0)
        again = control.release_edit(prepared["state_path"])
        self.assertEqual(again["released"], 0)

    def test_concurrent_same_execute_claims_only_one_shared_lease(self) -> None:
        prepared = control.prepare_edit(self.args())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _value: control.claim_edit(prepared["state_path"], 0), range(2)))
        self.assertEqual({item["status"] for item in results}, {"claimed"})
        self.assertEqual(sum(not item["idempotent"] for item in results), 1)
        registry = json.loads(self.slot_registry.read_text(encoding="utf-8"))
        self.assertEqual(len(registry["leases"]), 1)

    def test_cli_prints_json_and_never_accepts_generated_root_override(self) -> None:
        parser = control.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["complete", "--state", "/tmp/x", "--saved-path", "/tmp/y", "--generated-images-root", "/tmp"])


if __name__ == "__main__":
    unittest.main()
