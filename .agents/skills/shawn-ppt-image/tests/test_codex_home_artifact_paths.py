from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CodexHomeArtifactPathsTest(unittest.TestCase):
    def run_probe(self, codex_home: str | None, code: str) -> dict:
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "scripts"), str(ROOT)])}
        env.pop("CODEX_HOME", None)
        if codex_home is not None:
            env["CODEX_HOME"] = codex_home
        with tempfile.TemporaryDirectory(prefix="codex-artifact-probe-") as cwd:
            result = subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env,
                                    text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_all_control_planes_share_the_configured_artifact_root(self):
        for configured in [None, "", "relative-home", "~/studio-home"]:
            with self.subTest(configured=configured):
                result = self.run_probe(configured, '''
import json, os
from pathlib import Path
import pipeline_control as pc
import single_image_edit_control_plane_v1 as edit
import selected_style_control_plane_v1 as selected
expected = (Path(os.environ.get("CODEX_HOME") or Path.home()/".codex").expanduser()/"generated_images").resolve()
print(json.dumps({"matches": pc.GENERATED_IMAGES_ROOT == edit.GENERATED_IMAGES_ROOT == selected.pc.GENERATED_IMAGES_ROOT == expected}))
''')
                self.assertTrue(result["matches"])

    def test_spaced_isolated_home_accepts_receipt_hint_and_single_edit_but_rejects_ambiguity(self):
        with tempfile.TemporaryDirectory(prefix="studio-artifact-paths-") as root:
            isolated_home = str(Path(root) / "Studio Codex Home")
            result = self.run_probe(isolated_home, '''
import json
from pathlib import Path
from unittest import mock
import pipeline_control as pc
import selected_style_control_plane_v1 as selected
import single_image_edit_control_plane_v1 as edit
from tests.test_quick8_pipeline import write_png
image = pc.GENERATED_IMAGES_ROOT / "session" / "exec-00000000-0000-0000-0000-000000000001.png"
image.parent.mkdir(parents=True)
write_png(image)
hint = "Generated images are saved to " + str(image.parent) + " as " + str(image) + ". Use this file."
resolved, tool_id = pc.resolve_imagegen_artifact_hint(hint)
assert resolved == image and tool_id == image.stem
assert edit.validate_saved_path(str(image))[0] == image
project = Path.cwd()/"run"
key = "A|01|generate_page|1"
claim, receipt = selected.control_paths(project, key)
claim.parent.mkdir(parents=True, exist_ok=True)
claim.write_text(json.dumps({"lease_id":"fixture-lease"}))
item = {"style":"A", "page_id":"01", "action":"generate_page", "attempt":1,
        "manifest_sha256":"fixture-manifest", "generation_job_sha256":"fixture-job"}
with mock.patch.object(selected, "validate_manifest_item", return_value=({}, {}, item, project)), mock.patch.object(pc, "release_shared_imagegen_slots"):
    written = selected.write_receipt(project/"state.json", project/"manifest.json", key,
                                    {"savedPath":hint, "tool_status":"completed"})
value = json.loads(receipt.read_text())
assert written["error"] is None and value["savedPath"] == str(image)
second = image.with_name("exec-00000000-0000-0000-0000-000000000002.png")
write_png(second)
assert pc.resolve_imagegen_artifact_hint(hint + " or " + str(second)) == (None, None)
outside = Path.cwd()/"exec-00000000-0000-0000-0000-000000000003.png"
write_png(outside)
assert pc.resolve_imagegen_artifact_hint("Generated image saved at " + str(outside)) == (None, None)
try:
    edit.validate_saved_path(str(outside))
except edit.ContractError as error:
    assert error.code == "saved_path_outside_imagegen"
else:
    raise AssertionError("outside artifact accepted")
print(json.dumps({"receipt_error":value["error"], "tool_status":value["tool_status"], "unique_hint":True, "single_edit_valid":True}))
''')
            self.assertEqual(result, {"receipt_error": None, "tool_status": "completed", "unique_hint": True, "single_edit_valid": True})


if __name__ == "__main__":
    unittest.main()
