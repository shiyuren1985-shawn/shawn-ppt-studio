from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "scripts" / "pipeline_control.py"


def load_pipeline():
    spec = importlib.util.spec_from_file_location(
        "pipeline_control_selected_expansion_snapshot_union", PIPELINE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline = load_pipeline()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_png_stub(path: Path, *, tag: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1600, 900)
        + tag
    )


def input_record(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "sha256": pipeline.file_sha256(path),
    }


class SelectedExpansionSnapshotUnionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="selected_expansion_snapshot_union_"
        )
        self.project_dir = Path(self.temporary_directory.name).resolve()
        self.state_path = (
            self.project_dir / "state" / "selected_style_run_state.json"
        )
        self.source_path = self.project_dir / "source" / "outline.md"
        self.contract_08 = (
            self.project_dir / "content_contracts" / "page_08.json"
        )
        self.contract_09 = (
            self.project_dir / "content_contracts" / "page_09.json"
        )
        self.alternate_contract_08 = (
            self.project_dir / "alternate" / "page_08.json"
        )
        self.style_anchor = self.project_dir / "references" / "style_anchor.png"
        self.shared_logo = self.project_dir / "references" / "shared_logo.bin"
        self.page_09_asset = self.project_dir / "references" / "page_09_asset.bin"
        self.unused_asset = self.project_dir / "references" / "unused_asset.bin"

        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path.write_text(
            "# Outline\n\n## P08 First page\nPage eight\n\n"
            "## P09 Second page\nPage nine\n",
            encoding="utf-8",
        )
        write_json(
            self.contract_08,
            {
                "content_contract_version": 2,
                "page_id": "08",
                "display_required": ["Page eight"],
            },
        )
        write_json(
            self.contract_09,
            {
                "content_contract_version": 2,
                "page_id": "09",
                "display_required": ["Page nine"],
            },
        )
        write_json(
            self.alternate_contract_08,
            {
                "content_contract_version": 2,
                "page_id": "08",
                "display_required": ["Alternate page eight contract"],
            },
        )
        write_png_stub(self.style_anchor, tag=b"style-anchor")
        self.shared_logo.parent.mkdir(parents=True, exist_ok=True)
        self.shared_logo.write_bytes(b"SHARED-LOGO")
        self.page_09_asset.write_bytes(b"PAGE-09-ASSET")
        self.unused_asset.write_bytes(b"UNUSED-ASSET")

        write_json(
            self.state_path,
            {
                "run_id": "selected-expansion-snapshot-union-fixture",
                "project_dir": str(self.project_dir),
                "run_mode": "selected_style_expansion",
                "phase": "selected_style_expansion",
                "status": "running",
                "selected_style": "A",
                "page_order": ["08", "09"],
                "pages": {
                    "08": {"status": "pending", "attempt_count": 0},
                    "09": {"status": "pending", "attempt_count": 0},
                },
                "events": [],
                "timing": {},
            },
        )
        write_json(
            self.project_dir / "state" / "task_init.json",
            {
                "task_init_contract_version": 1,
                "project_dir": str(self.project_dir),
                "source_snapshot_required": True,
                "created_at": "2099-01-01T00:00:00+08:00",
            },
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_page_job(
        self, page_id: str, contract_path: Path, inputs: list[Path]
    ) -> Path:
        manifest = [input_record(path) for path in inputs]
        prompt = f"Generate expansion page {page_id}"
        fingerprint = hashlib.sha256(
            json.dumps(
                {"prompt": prompt, "inputs": manifest},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        path = self.project_dir / "page_jobs" / f"page_{page_id}.json"
        write_json(
            path,
            {
                "page_id": page_id,
                "style_slot": "A",
                "action": "generate_page",
                "source_content_contract_path": str(contract_path.resolve()),
                "source_content_contract_sha256": pipeline.file_sha256(
                    contract_path
                ),
                "imagegen_prompt": prompt,
                "imagegen_referenced_paths": [
                    str(input_path.resolve()) for input_path in inputs
                ],
                "imagegen_input_manifest": manifest,
                "imagegen_input_fingerprint": fingerprint,
                "output_target": str(
                    self.project_dir
                    / "origin_image"
                    / f"style_A_page_{page_id}.png"
                ),
            },
        )
        return path

    def write_complete_page_jobs(self, *, include_style_anchor: bool = True) -> None:
        anchor_inputs = [self.style_anchor] if include_style_anchor else []
        self.write_page_job(
            "08", self.contract_08, [*anchor_inputs, self.shared_logo]
        )
        self.write_page_job(
            "09", self.contract_09, [*anchor_inputs, self.page_09_asset]
        )

    def snapshot_assets(
        self,
        *,
        include_style_anchor: bool = True,
        include_page_09_asset: bool = True,
        include_unused_asset: bool = False,
    ) -> list[dict[str, str]]:
        assets: list[dict[str, str]] = []
        if include_style_anchor:
            assets.append(
                {
                    "path": str(self.style_anchor),
                    "asset_type": "reference_image",
                    "role": "style_anchor",
                }
            )
        assets.append(
            {
                "path": str(self.shared_logo),
                "asset_type": "required_asset",
                "role": "official_logo",
            }
        )
        if include_page_09_asset:
            assets.append(
                {
                    "path": str(self.page_09_asset),
                    "asset_type": "required_page_asset",
                    "role": "page_09_asset",
                }
            )
        if include_unused_asset:
            assets.append(
                {
                    "path": str(self.unused_asset),
                    "asset_type": "required_asset",
                    "role": "unused_asset",
                }
            )
        return assets

    def create_snapshot(
        self,
        *,
        contract_paths: list[Path] | None = None,
        asset_items: list[dict[str, str]] | None = None,
    ) -> dict:
        return pipeline.create_source_snapshot(
            project_dir=self.project_dir,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=["08", "09"],
            content_contract_paths=contract_paths
            if contract_paths is not None
            else [self.contract_08, self.contract_09],
            asset_items=asset_items
            if asset_items is not None
            else self.snapshot_assets(),
            timestamp="2099-01-01T00:00:01+08:00",
        )

    def test_exact_page_job_contract_and_external_asset_union_can_be_sealed(
        self,
    ) -> None:
        self.write_complete_page_jobs()

        snapshot = self.create_snapshot()

        self.assertEqual(
            {item["path"] for item in snapshot["content_contracts"]},
            {str(self.contract_08), str(self.contract_09)},
        )
        self.assertEqual(
            {item["path"] for item in snapshot["assets"]},
            {
                str(self.style_anchor),
                str(self.shared_logo),
                str(self.page_09_asset),
            },
        )

    def test_snapshot_without_any_style_anchor_is_rejected(self) -> None:
        self.write_complete_page_jobs(include_style_anchor=False)

        with self.assertRaises(SystemExit):
            self.create_snapshot(
                asset_items=self.snapshot_assets(include_style_anchor=False)
            )

        self.assertFalse(
            (self.project_dir / "state" / "source_snapshot.json").exists()
        )

    def test_snapshot_missing_page_job_asset_is_rejected(self) -> None:
        self.write_complete_page_jobs()

        with self.assertRaises(SystemExit):
            self.create_snapshot(
                asset_items=self.snapshot_assets(include_page_09_asset=False)
            )

        self.assertFalse(
            (self.project_dir / "state" / "source_snapshot.json").exists()
        )

    def test_snapshot_with_unused_extra_asset_is_rejected(self) -> None:
        self.write_complete_page_jobs()

        with self.assertRaises(SystemExit):
            self.create_snapshot(
                asset_items=self.snapshot_assets(include_unused_asset=True)
            )

        self.assertFalse(
            (self.project_dir / "state" / "source_snapshot.json").exists()
        )

    def test_snapshot_contract_path_not_used_by_page_job_is_rejected(self) -> None:
        self.write_complete_page_jobs()

        with self.assertRaises(SystemExit):
            self.create_snapshot(
                contract_paths=[self.alternate_contract_08, self.contract_09]
            )

        self.assertFalse(
            (self.project_dir / "state" / "source_snapshot.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
