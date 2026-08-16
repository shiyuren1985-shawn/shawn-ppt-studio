from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "validate_delivery_text.py"
SPEC = importlib.util.spec_from_file_location("validate_delivery_text", MODULE_PATH)
assert SPEC and SPEC.loader
delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivery)


class DeliveryTextGateTests(unittest.TestCase):
    def test_accepts_ordinary_absolute_file_links(self) -> None:
        text = (
            "候选已经生成。\n\n"
            "[打开总览](/tmp/task/overview/ABCDEFGH_4x2.png)\n\n"
            "[打开 A](</tmp/task with spaces/origin_image/style_A_page_02.png>)"
        )
        self.assertEqual(delivery.validate_text(text, require_link=True), [])

    def test_fast8_links_only_accepts_exact_nine_link_message(self) -> None:
        root = Path("/tmp/task with spaces")
        links = [f"[总览](<{root}/overview/ABCDEFGH_2x4.png>)"]
        links.extend(
            f"[{style}](<{root}/origin_image/style_{style}_page_P03.png>)"
            for style in "ABCDEFGH"
        )
        text = links[0] + "\n" + " ".join(links[1:]) + "\n"
        self.assertEqual(
            delivery.validate_text(
                text,
                require_link=True,
                fast8_links_only=True,
                project_dir=root,
            ),
            [],
        )

    def test_fast8_links_only_keeps_legacy_4x2_compatible(self) -> None:
        root = Path("/tmp/legacy task")
        links = [f"[总览](<{root}/overview/ABCDEFGH_4x2.png>)"]
        links.extend(
            f"[{style}](<{root}/origin_image/style_{style}_page_P03.png>)"
            for style in "ABCDEFGH"
        )
        text = links[0] + "\n" + " ".join(links[1:]) + "\n"
        self.assertEqual(
            delivery.validate_text(
                text,
                require_link=True,
                fast8_links_only=True,
                project_dir=root,
            ),
            [],
        )

    def test_fast8_links_only_rejects_one_link_per_line_layout(self) -> None:
        root = Path("/tmp/task")
        links = [f"[总览](<{root}/overview/ABCDEFGH_2x4.png>)"]
        links.extend(
            f"[{style}](<{root}/origin_image/style_{style}_page_P03.png>)"
            for style in "ABCDEFGH"
        )
        text = "\n\n".join(links)
        rules = {
            item["rule"]
            for item in delivery.validate_text(
                text,
                fast8_links_only=True,
                project_dir=root,
            )
        }
        self.assertIn("fast8_delivery_line_structure", rules)

    def test_fast8_links_only_rejects_diagnostics_and_extra_links(self) -> None:
        root = Path("/tmp/task")
        links = [f"[总览](<{root}/overview/ABCDEFGH_2x4.png>)"]
        links.extend(
            f"[{style}](<{root}/origin_image/style_{style}_page_P03.png>)"
            for style in "ABCDEFGH"
        )
        text = (
            "project_dir: [任务](/tmp/task)\n\n"
            + "\n\n".join(links)
            + "\n\n正式耗时：15 分钟"
        )
        rules = {
            item["rule"]
            for item in delivery.validate_text(
                text,
                fast8_links_only=True,
                project_dir=root,
            )
        }
        self.assertIn("fast8_extra_delivery_text", rules)
        self.assertIn("fast8_link_labels_or_order", rules)

    def test_rejects_inline_and_reference_markdown_images(self) -> None:
        for text in (
            "![总览](/tmp/overview.png)",
            "![总览][overview]\n\n[overview]: /tmp/overview.png",
        ):
            violations = delivery.validate_text(text)
            self.assertIn("markdown_image", {item["rule"] for item in violations})

    def test_rejects_html_data_uri_and_base64_payloads(self) -> None:
        samples = (
            "<img src='/tmp/overview.png'>",
            "<picture><source srcset='/tmp/overview.webp'></picture>",
            "data:image/png;base64,iVBORw0KGgoAAA",
            "iVBORw0KGgo" + "A" * 40,
            "A" * 600,
        )
        for text in samples:
            with self.subTest(text=text[:24]):
                self.assertTrue(delivery.validate_text(text))

    def test_docs_require_validating_exact_delivery_draft(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        reference_text = (
            SKILL_ROOT / "references" / "媒体隔离与交付格式.md"
        ).read_text(encoding="utf-8")
        self.assertIn("references/媒体隔离与交付格式.md", skill_text)
        self.assertIn("state/delivery_message.md", reference_text)
        self.assertIn("validate_delivery_text.py", reference_text)
        self.assertIn("逐字发送", reference_text)

    def test_fast8_burst_prompt_requires_same_exec_receipt(self) -> None:
        text = (SKILL_ROOT / "prompts" / "fast8-burst-runner.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("await eval(action)", text)
        self.assertIn("imagegen_referenced_paths", text)
        self.assertIn("savedPath/receipt", text)


if __name__ == "__main__":
    unittest.main()
