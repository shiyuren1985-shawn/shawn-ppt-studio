from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "init_task_dir_identity_guard", SCRIPTS / "init_task_dir.py"
)
assert SPEC and SPEC.loader
init_task_dir = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(init_task_dir)


class Fast8PreflightIdentityGuardTests(unittest.TestCase):
    def test_initializer_auto_binds_opted_in_required_outline(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_init_identity_guard_") as temp:
            root = Path(temp).resolve()
            source = root / "outline.md"
            manifest = root / "preflight.json"
            source.write_text(
                "---\nslide_identity_required: true\ndeck_uid: TEST_DECK\n"
                "slide_uids:\n  P7: TEST_P7\n---\n"
                "| 页码 | 标题 |\n|---|---|\n| P7 | Test |\n",
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {
                        "fast8_preflight_manifest_version": 1,
                        "run_mode": "fast_8x1_diverse",
                        "task_name": "P07_8x1_20260815_guard",
                        "timestamp_policy": "script_owned",
                        "request_started_at": "2026-08-15T12:00:00+08:00",
                        "page_ids": ["P7"],
                        "required_files": [str(source)],
                        "optional_files": [],
                        "asset_items": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            validated = init_task_dir.validate_fast8_preflight_manifest(
                manifest, "P07_8x1_20260815_guard"
            )

            self.assertEqual(validated["slide_identity_file"]["path"], str(source))
            self.assertEqual(
                validated["slide_identity_file"]["sha256"],
                init_task_dir.file_sha256(source),
            )


if __name__ == "__main__":
    unittest.main()
