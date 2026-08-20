from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_fast8_preflight_manifest.py"
)


def write_minimal_pdf(path: Path) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << >> /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode())
        payload.extend(value)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    path.write_bytes(payload)


class Fast8PreflightBuilderTests(unittest.TestCase):
    def run_builder(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_exact_manifest_and_preserves_canonical_page_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_builder_") as temp:
            root = Path(temp).resolve()
            source = root / "outline.md"
            asset = root / "logo.png"
            output = root / "preflight.json"
            source.write_text("# P7\nTest page\n", encoding="utf-8")
            asset.write_bytes(b"logo")
            result = self.run_builder(
                "--output",
                str(output),
                "--task-name",
                "P7_builder_test",
                "--page-id",
                "P7",
                "--required-file",
                str(source),
                "--asset",
                f"{asset}::official_logo",
                "--request-started-at",
                "2026-08-05T12:00:00+08:00",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                set(manifest),
                {
                    "fast8_preflight_manifest_version",
                    "run_mode",
                    "task_name",
                    "timestamp_policy",
                    "request_started_at",
                    "page_ids",
                    "required_files",
                    "optional_files",
                    "asset_items",
                },
            )
            self.assertEqual(manifest["page_ids"], ["P7"])
            self.assertEqual(manifest["required_files"], [str(source)])
            self.assertEqual(
                manifest["asset_items"],
                [{"path": str(asset), "role": "official_logo"}],
            )

    def test_missing_required_file_fails_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_missing_") as temp:
            root = Path(temp).resolve()
            output = root / "preflight.json"
            result = self.run_builder(
                "--output",
                str(output),
                "--task-name",
                "P20_builder_test",
                "--page-id",
                "P20",
                "--required-file",
                str(root / "missing.md"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("不存在", result.stderr)
            self.assertFalse(output.exists())

    def test_rejects_raw_pdf_as_imagegen_asset(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_raw_pdf_") as temp:
            root = Path(temp).resolve()
            source = root / "source.pdf"
            output = root / "preflight.json"
            write_minimal_pdf(source)
            result = self.run_builder(
                "--output", str(output),
                "--task-name", "P23_raw_pdf",
                "--page-id", "P23",
                "--asset", f"{source}::required_chart_source",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("不能直接传给 ImageGen", result.stderr)
            self.assertFalse(output.exists())

    def test_materializes_one_pdf_page_before_freezing_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_pdf_page_") as temp:
            root = Path(temp).resolve()
            source = root / "source.pdf"
            output = root / "preflight.json"
            write_minimal_pdf(source)
            result = self.run_builder(
                "--output", str(output),
                "--task-name", "P23_pdf_page",
                "--page-id", "P23",
                "--document-page-asset",
                f"{source}::1::required_chart_source",
            )
            if "缺少视觉资产转换器" in result.stderr:
                self.skipTest("pdftoppm is not installed")
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["required_files"][0], str(source))
            self.assertEqual(len(manifest["required_files"]), 2)
            self.assertTrue(
                manifest["required_files"][1].endswith(".materialization.json")
            )
            self.assertEqual(len(manifest["asset_items"]), 1)
            rendered = Path(manifest["asset_items"][0]["path"])
            self.assertEqual(rendered.suffix, ".png")
            self.assertEqual(rendered.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(
                manifest["asset_items"][0]["role"], "required_chart_source"
            )

    def test_generic_source_spec_uses_the_shared_materializer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_source_spec_") as temp:
            root = Path(temp).resolve()
            source = root / "source.pdf"
            output = root / "preflight.json"
            write_minimal_pdf(source)
            result = self.run_builder(
                "--output", str(output),
                "--task-name", "P23_source_spec",
                "--page-id", "P23",
                "--source-asset-spec",
                json.dumps(
                    {
                        "source": str(source),
                        "role": "source_page",
                        "locator": {"page": 1},
                    }
                ),
            )
            if "缺少视觉资产转换器" in result.stderr:
                self.skipTest("pdftoppm is not installed")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["source_assets_materialized"], 1)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["asset_items"][0]["role"], "source_page")
            self.assertTrue(manifest["asset_items"][0]["path"].endswith(".png"))

    def test_global_chrome_contract_freezes_applicable_tone_logos(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_chrome_") as temp:
            root = Path(temp).resolve()
            dark_logo = root / "logo-dark.png"
            light_logo = root / "logo-light.png"
            contract = root / "global-chrome.json"
            output = root / "preflight.json"
            dark_logo.write_bytes(b"dark")
            light_logo.write_bytes(b"light")
            contract.write_text(
                json.dumps(
                    {
                        "global_chrome_contract_version": 1,
                        "authorization": {"status": "authorized"},
                        "deck_title_system": {
                            "enabled": True,
                            "scope": {
                                "include_page_ids": ["P21", "P22", "P23"],
                                "exclude_page_ids": [],
                            },
                            "logo": {
                                "required": True,
                                "assets_by_tone": {
                                    "dark": {"path": str(dark_logo)},
                                    "light": {"path": str(light_logo)},
                                },
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = self.run_builder(
                "--output", str(output),
                "--task-name", "P23_global_chrome",
                "--page-id", "P23",
                "--global-chrome-contract", str(contract),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["required_files"], [str(contract)])
            self.assertEqual(
                manifest["asset_items"],
                [
                    {
                        "path": str(dark_logo),
                        "role": "global_chrome_logo_dark",
                    },
                    {
                        "path": str(light_logo),
                        "role": "global_chrome_logo_light",
                    },
                ],
            )

    def test_explicit_light_tone_persists_all_eight_overrides(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_tone_") as temp:
            root = Path(temp).resolve()
            source = root / "outline.md"
            output = root / "preflight.json"
            source.write_text("# P24\nTest page\n", encoding="utf-8")
            result = self.run_builder(
                "--output", str(output),
                "--task-name", "P24_all_light",
                "--page-id", "P24",
                "--required-file", str(source),
                "--tone", "light",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["tone_overrides"],
                {style: "light" for style in "ABCDEFGH"},
            )

    def test_page_source_rejects_missing_page_before_manifest_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_page_") as temp:
            root = Path(temp).resolve()
            source = root / "outline.md"
            output = root / "preflight.json"
            source.write_text(
                "| 页码 | 标题 |\n|---|---|\n| P1 | one |\n| P2 | two |\n",
                encoding="utf-8",
            )
            result = self.run_builder(
                "--output",
                str(output),
                "--task-name",
                "P3_missing_test",
                "--page-id",
                "P3",
                "--required-file",
                str(source),
                "--page-source",
                str(source),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("P3", result.stderr)
            self.assertFalse(output.exists())

    def test_page_source_accepts_existing_page(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_page_") as temp:
            root = Path(temp).resolve()
            source = root / "outline.md"
            output = root / "preflight.json"
            source.write_text(
                "| 页码 | 标题 |\n|---|---|\n| P1 | one |\n| P2 | two |\n",
                encoding="utf-8",
            )
            result = self.run_builder(
                "--output",
                str(output),
                "--task-name",
                "P2_existing_test",
                "--page-id",
                "P2",
                "--required-file",
                str(source),
                "--page-source",
                str(source),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.exists())
            self.assertTrue(json.loads(result.stdout)["page_source_validated"])

    def test_rejects_independent_slide_identity_file_for_new_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_identity_") as temp:
            root = Path(temp).resolve()
            source = root / "outline.md"
            identity = root / "slide_identity.md"
            output = root / "preflight.json"
            source.write_text("P7", encoding="utf-8")
            identity.write_text(
                "---\nslide_identity_required: true\ndeck_uid: EPC_测试\n"
                "slide_uids:\n  P7: EPC_测试页面\n---\n",
                encoding="utf-8",
            )
            result = self.run_builder(
                "--output", str(output),
                "--task-name", "P7_identity_test",
                "--page-id", "P7",
                "--required-file", str(source),
                "--slide-identity-file", str(identity),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("不接受独立 slide identity 文件", result.stderr)

    def test_persists_identity_when_it_is_the_authoritative_page_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_identity_same_") as temp:
            root = Path(temp).resolve()
            source = root / "outline.md"
            output = root / "preflight.json"
            source.write_text(
                "---\nslide_identity_required: true\ndeck_uid: EPC_测试\n"
                "slide_uids:\n  P7: EPC_测试页面\n---\n"
                "| 页码 | 标题 |\n|---|---|\n| P7 | Test |\n",
                encoding="utf-8",
            )
            result = self.run_builder(
                "--output", str(output),
                "--task-name", "P7_identity_same_source_test",
                "--page-id", "P7",
                "--required-file", str(source),
                "--page-source", str(source),
                "--slide-identity-file", str(source),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["slide_identity_file"], str(source))

    def test_does_not_auto_discover_identity_sidecar_for_page_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fast8_preflight_identity_auto_") as temp:
            root = Path(temp).resolve()
            source = root / "outline.md"
            identity = root / "outline_饱和式UID版.md"
            output = root / "preflight.json"
            source.write_text("# P7\nTest page\n", encoding="utf-8")
            identity.write_text(
                "---\nslide_identity_required: true\ndeck_uid: EPC_测试\n"
                "slide_uids:\n  P7: EPC_测试页面\n---\n",
                encoding="utf-8",
            )
            result = self.run_builder(
                "--output", str(output),
                "--task-name", "P7_identity_auto_test",
                "--page-id", "P7",
                "--required-file", str(source),
                "--page-source", str(source),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotIn("slide_identity_file", manifest)
            self.assertEqual(manifest["asset_items"], [])


if __name__ == "__main__":
    unittest.main()
