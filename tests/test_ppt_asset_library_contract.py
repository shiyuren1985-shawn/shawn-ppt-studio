import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_TEXT = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
ASSET_REFERENCE = SKILL_ROOT / "references" / "常用PPT元素资产库.md"
ASSET_TEXT = ASSET_REFERENCE.read_text(encoding="utf-8")
CONTENT_RULES_TEXT = (SKILL_ROOT / "references" / "内容规划规则.md").read_text(
    encoding="utf-8"
)
BRAND_RULES_TEXT = (SKILL_ROOT / "references" / "设计基础与品牌资产.md").read_text(
    encoding="utf-8"
)
MODULE_PATH = SKILL_ROOT / "scripts" / "pipeline_control.py"
SPEC = importlib.util.spec_from_file_location(
    "pipeline_control_asset_library", MODULE_PATH
)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


class PptAssetLibraryContractTests(unittest.TestCase):
    def test_skill_routes_brand_asset_tasks_to_optional_library(self):
        self.assertIn("references/常用PPT元素资产库.md", SKILL_TEXT)
        self.assertIn("按需检索本地补充资产库", SKILL_TEXT)

    def test_reference_names_expected_library_and_scopes(self):
        self.assertNotIn("/Users/", ASSET_TEXT)
        self.assertIn("品牌子目录", ASSET_TEXT)
        self.assertIn("logo/", ASSET_TEXT)

    def test_library_is_selective_and_does_not_imply_relationships(self):
        self.assertIn("不得复制整个资产库", ASSET_TEXT)
        self.assertIn("不得仅凭资产库内容推断业务关系", ASSET_TEXT)
        self.assertIn("required_assets", ASSET_TEXT)
        self.assertIn("对话外 QA 运行时", ASSET_TEXT)
        self.assertIn("不得创建 Worker 代看", ASSET_TEXT)
        self.assertIn("来源与批准状态", ASSET_TEXT)
        self.assertIn("该机器上的对应路径", ASSET_TEXT)
        self.assertIn("SHAWN_PPT_ASSET_LIBRARY_ROOT", ASSET_TEXT)

    def test_title_contract_only_transcribes_explicit_source_requirements(self):
        self.assertIn("资产库、其他页面或旧母版的存在", CONTENT_RULES_TEXT)
        self.assertIn("本身不构成授权", CONTENT_RULES_TEXT)
        self.assertIn("大纲没有标题区要求时", CONTENT_RULES_TEXT)
        self.assertIn("页面自由发挥", CONTENT_RULES_TEXT)
        self.assertIn("资产库的可用性不是页面授权", BRAND_RULES_TEXT)
        self.assertIn("不得自行补充像素坐标", BRAND_RULES_TEXT)

    def test_required_assets_support_tone_and_style_routing(self):
        assets = [
            {"path": "/tmp/shared.png", "role": "shared"},
            {"path": "/tmp/dark.png", "role": "dark", "tones": ["dark"]},
            {
                "path": "/tmp/style_b.png",
                "role": "style B",
                "style_slots": ["style_B"],
            },
        ]
        self.assertEqual(
            [
                item["role"]
                for item in pipeline.filter_required_assets(assets, "B", "dark")
            ],
            ["shared", "dark", "style B"],
        )
        self.assertEqual(
            [
                item["role"]
                for item in pipeline.filter_required_assets(assets, "A", "light")
            ],
            ["shared"],
        )

    def test_input_manifest_records_content_hash(self):
        with tempfile.TemporaryDirectory(prefix="ppt_asset_manifest_") as temp_dir:
            asset = Path(temp_dir) / "logo.bin"
            payload = b"selected-logo-asset"
            asset.write_bytes(payload)
            expected_path = str(asset.resolve())
            normalized, manifest = pipeline.build_input_manifest([str(asset)])

        self.assertEqual(normalized, [expected_path])
        self.assertEqual(manifest[0]["sha256"], hashlib.sha256(payload).hexdigest())

    def test_required_asset_validation_uses_its_own_field_name(self):
        with self.assertRaisesRegex(SystemExit, r"required_assets\[0\] 缺少非空 path"):
            pipeline.filter_required_assets([{"role": "logo"}], "A", "dark")


if __name__ == "__main__":
    unittest.main()
