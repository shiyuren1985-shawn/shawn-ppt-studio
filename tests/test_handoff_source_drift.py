from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "scripts" / "pipeline_control.py"
DELIVERY_PATH = ROOT / "scripts" / "validate_delivery_text.py"
INIT_TASK_PATH = ROOT / "scripts" / "init_task_dir.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline = load_module("pipeline_control_handoff", PIPELINE_PATH)
delivery = load_module("delivery_gate_handoff", DELIVERY_PATH)
init_task = load_module("init_task_handoff", INIT_TASK_PATH)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_png_stub(path: Path, width: int = 1600, height: int = 900, tag: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + tag
    )


def write_pptx_fixture(path: Path, slide_texts: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    slide_ids = "".join(
        f'<p:sldId id="{255 + index}" r:id="rId{index}"/>'
        for index in range(1, len(slide_texts) + 1)
    )
    relationships = "".join(
        (
            '<Relationship '
            f'Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{index}.xml"/>'
        )
        for index in range(1, len(slide_texts) + 1)
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            (
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f"<p:sldIdLst>{slide_ids}</p:sldIdLst></p:presentation>"
            ),
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f"{relationships}</Relationships>"
            ),
        )
        for index, text in enumerate(slide_texts, start=1):
            archive.writestr(
                f"ppt/slides/slide{index}.xml",
                (
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                    f"<p:cSld><a:t>{text}</a:t></p:cSld></p:sld>"
                ),
            )


def guarded_generation_job(
    contract_path: Path,
    input_paths: list[Path],
    *,
    prompt: str = "fixture prompt",
    style: str = "A",
    page_id: str = "02",
    action: str = "generate_anchor",
    attempt: int = 1,
) -> dict:
    referenced_paths = [str(path.resolve()) for path in input_paths]
    manifest = [
        {
            "path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "modified_ns": path.stat().st_mtime_ns,
            "sha256": pipeline.file_sha256(path),
        }
        for path in input_paths
    ]
    fingerprint = hashlib.sha256(
        json.dumps(
            {"prompt": prompt, "inputs": manifest},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "style_slot": style,
        "page_id": page_id,
        "action": action,
        "attempt": attempt,
        "output_target": str(
            contract_path.parent.parent
            / "origin_image"
            / f"style_{style}_page_{page_id}.png"
        ),
        "reference_images": [],
        "required_assets": [{"path": str(path.resolve())} for path in input_paths],
        "source_content_contract_path": str(contract_path.resolve()),
        "source_content_contract_sha256": pipeline.file_sha256(contract_path),
        "imagegen_prompt": prompt,
        "imagegen_referenced_paths": referenced_paths,
        "imagegen_input_manifest": manifest,
        "imagegen_input_fingerprint": fingerprint,
    }


class HandoffAndSourceDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shawn_handoff_")
        self.root = Path(self.temp.name).resolve()
        init_task.create_standard_dirs(self.root)
        init_task.write_task_init_contract(
            self.root, timestamp="2099-01-01T00:00:00+08:00"
        )
        self.state_path = self.root / "state" / "style_run_state.json"
        self.source_path = self.root / "source" / "大纲 source.md"
        self.contract_path = self.root / "content_contracts" / "page_02.json"
        self.asset_path = self.root / "references" / "official logo.bin"
        self.overview_path = self.root / "overview" / "ABCDEFGH_4x2.png"
        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path.write_text(
            "# 演示大纲\n\n## P02 核心主张\n目标页稳定内容 100%\n\n"
            "## P03 其他页面\n其他页版本一\n",
            encoding="utf-8",
        )
        write_json(
            self.contract_path,
            {
                "content_contract_version": 2,
                "page_id": "02",
                "display_required": ["目标页稳定内容 100%"],
            },
        )
        self.asset_path.parent.mkdir(parents=True, exist_ok=True)
        self.asset_path.write_bytes(b"ASSET-V1")
        write_png_stub(self.overview_path, 1600, 900, b"overview")

        styles = {}
        for index, style in enumerate(pipeline.QUICK_STYLES):
            image = self.root / "origin_image" / f"style_{style}_page_02.png"
            write_png_stub(image, 1600, 900, style.encode("ascii"))
            styles[style] = {
                "tone": "dark" if index < 4 else "light",
                "workflow_status": "ready_for_overview",
                "pages": {
                    "02": {
                        "role": "anchor",
                        "status": "candidate_ready",
                        "selected_source": str(image),
                        "source_sha256": pipeline.file_sha256(image),
                        "qa_stage": "filesystem",
                        "qa_scope": "filesystem_only",
                    }
                },
            }
        write_json(
            self.state_path,
            {
                "run_id": "handoff-fixture",
                "run_mode": pipeline.QUICK_8X1_MODE,
                "state_audit_contract_version": 2,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "deferred_pages": ["05", "08"],
                "styles": {},
                "scheduler": {
                    "phase": "initialization",
                    "active_actions": [],
                    "ready_queue": [],
                    "recovery_queue": [],
                },
                "events": [],
                "timing": {},
            },
        )
        pipeline.create_source_snapshot(
            project_dir=self.root,
            state_path=self.state_path,
            source_path=self.source_path,
            page_ids=["02"],
            content_contract_paths=[self.contract_path],
            asset_items=[
                {
                    "path": str(self.asset_path),
                    "asset_type": "required_asset",
                    "role": "official_logo",
                    "styles": list(pipeline.QUICK_STYLES),
                }
            ],
            timestamp="2099-01-01T00:00:00+08:00",
        )
        state = pipeline.read_json(self.state_path)
        state["status"] = "completed"
        state["styles"] = styles
        state["scheduler"]["phase"] = "completed"
        state["overview"] = {"final_path": str(self.overview_path)}
        write_json(self.state_path, state)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_handoff(self):
        return pipeline.write_handoff_files(
            project_dir=self.root,
            state_path=self.state_path,
            timestamp="2099-01-01T00:10:00+08:00",
        )

    def test_markdown_table_page_row_is_a_stable_source_fragment(self) -> None:
        text = (
            "# 新叙事大纲\n\n"
            "| 页码 | 标题 | 核心命题 |\n"
            "| --- | --- | --- |\n"
            "| P22 | 亏损从报价开始 | 风险越晚明确，代价越高 |\n"
            "| P30 | Mining 产业链 | 更早识别协同依赖 |\n"
        )
        pages = pipeline.extract_markdown_pages(text, ["22"])
        self.assertEqual(len(pages), 1)
        normalized = pages[0]["normalized_text"]
        self.assertIn("页码", normalized)
        self.assertIn("P22", normalized)
        self.assertIn("风险越晚明确", normalized)
        self.assertNotIn("P30", normalized)

    def test_duplicate_markdown_table_page_rows_are_blocked(self) -> None:
        text = (
            "| 页码 | 标题 |\n| --- | --- |\n| P22 | 版本一 |\n"
            "\n| 页码 | 标题 |\n| --- | --- |\n| Page 22 | 版本二 |\n"
        )
        with self.assertRaisesRegex(SystemExit, "多个表格记录"):
            pipeline.extract_markdown_pages(text, ["P22"])

    def test_heading_page_stops_before_peer_deck_section_and_keeps_deck_context(self) -> None:
        text = (
            "# SI deck\n\nAudience: internal sales.\n\n"
            "## P1｜Opening\n### Core\nOpening fact.\n\n"
            "## P2｜ODI connection\n### Core\nTarget fact.\n\n"
            "## Sources\nShared source index.\n"
        )
        pages = pipeline.extract_markdown_pages(text, ["02"], include_exact=True)
        self.assertIn("Target fact", pages[0]["exact_text"])
        self.assertNotIn("Shared source index", pages[0]["exact_text"])
        deck = pipeline.extract_markdown_deck_context(text)
        self.assertIsNotNone(deck)
        self.assertIn("Audience: internal sales", deck["normalized_text"])
        self.assertIn("Shared source index", deck["normalized_text"])
        self.assertNotIn("Opening fact", deck["normalized_text"])
        self.assertNotIn("Target fact", deck["normalized_text"])

    def test_normal_handoff_has_required_fields_absolute_paths_and_safe_markdown(self) -> None:
        json_path, markdown_path, handoff = self.write_handoff()
        snapshot = pipeline.read_json(self.root / "state" / "source_snapshot.json")
        for field in (
            "source_snapshot_contract_version",
            "authoritative_source",
            "page_content",
            "content_contract_sha256",
            "assets_sha256",
            "snapshot_at",
        ):
            self.assertIn(field, snapshot)
        self.assertEqual(snapshot["page_content"]["pages"][0]["page_id"], "02")
        self.assertIn("目标页稳定内容 100%", snapshot["page_content"]["normalized_text"])
        self.assertEqual(handoff["handoff_contract_version"], 1)

        self.assertEqual(handoff["state_ref"]["sha256"], pipeline.file_sha256(self.state_path))
        self.assertEqual(handoff["status"], "candidate_ready")
        self.assertEqual(len(handoff["candidates"]), 8)
        self.assertFalse(handoff["user_selection"]["selected"])
        self.assertEqual(
            handoff["current_page_content"]["snapshot_sha256"],
            handoff["current_page_content"]["current_sha256"],
        )
        self.assertTrue(json_path.is_file())
        self.assertTrue(markdown_path.is_file())

        formal_paths = [
            handoff["state_ref"]["path"],
            handoff["source_snapshot_ref"]["path"],
            handoff["authoritative_source"]["path"],
            handoff["overview"]["path"],
            *(item["path"] for item in handoff["content_contracts"]),
            *(item["path"] for item in handoff["reference_assets"]),
            *(item["path"] for item in handoff["candidates"]),
        ]
        for value in formal_paths:
            path = Path(value)
            self.assertTrue(path.is_absolute(), value)
            self.assertTrue(path.is_file(), value)

        json_text = json_path.read_text(encoding="utf-8")
        markdown = markdown_path.read_text(encoding="utf-8")
        for value in (json_text, markdown):
            lowered = value.lower()
            self.assertNotIn("data:image", lowered)
            self.assertNotIn(";base64,", lowered)
            self.assertNotIn("![", value)
            self.assertNotIn("<img", lowered)
        self.assertEqual(delivery.validate_text(markdown, require_link=True), [])
        self.assertIn("无需读取旧聊天或旧 JSONL", markdown)

    def test_write_handoff_command_requires_process_completed_state(self) -> None:
        with self.assertRaisesRegex(SystemExit, "只允许在 process_completed"):
            pipeline.command_write_handoff(
                argparse.Namespace(
                    state=str(self.state_path),
                    project_dir=str(self.root),
                    unresolved_issues_json=None,
                    next_allowed_actions_json=None,
                    timestamp="2099-01-01T00:10:00+08:00",
                )
            )

    def test_write_handoff_command_is_idempotent_after_completion(self) -> None:
        state = pipeline.read_json(self.state_path)
        state.setdefault("timing", {})["process_completed_at"] = (
            "2099-01-01T00:09:00+08:00"
        )
        write_json(self.state_path, state)
        json_path, markdown_path, _ = self.write_handoff()
        json_before = json_path.read_bytes()
        markdown_before = markdown_path.read_bytes()
        with redirect_stdout(io.StringIO()):
            pipeline.command_write_handoff(
                argparse.Namespace(
                    state=str(self.state_path),
                    project_dir=str(self.root),
                    unresolved_issues_json=None,
                    next_allowed_actions_json=None,
                    timestamp="2099-01-01T00:20:00+08:00",
                )
            )
        self.assertEqual(json_path.read_bytes(), json_before)
        self.assertEqual(markdown_path.read_bytes(), markdown_before)

    def test_complete_validation_never_mutates_formal_state_on_unrelated_source_warning(self) -> None:
        state = pipeline.read_json(self.state_path)
        state.setdefault("timing", {})["process_completed_at"] = (
            "2099-01-01T00:09:00+08:00"
        )
        write_json(self.state_path, state)
        self.write_handoff()
        self.source_path.write_text(
            "# 演示大纲\n\n## P02 核心主张\n目标页稳定内容 100%\n\n"
            "## P03 其他页面\n其他页版本二，内容已改变\n",
            encoding="utf-8",
        )
        state_hash_before = pipeline.file_sha256(self.state_path)
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                pipeline.command_validate_state(
                    argparse.Namespace(state=str(self.state_path), complete=True)
                )
        self.assertEqual(pipeline.file_sha256(self.state_path), state_hash_before)
        handoff = pipeline.read_json(self.root / "state" / "handoff.json")
        self.assertEqual(handoff["state_ref"]["sha256"], state_hash_before)
        drift = pipeline.read_json(self.root / "state" / "source_drift_status.json")
        self.assertEqual(drift["status"], "warning_unrelated_source_change")

    def test_explicit_handoff_refresh_backs_up_and_rebinds_current_state(self) -> None:
        state = pipeline.read_json(self.state_path)
        state.setdefault("timing", {})["process_completed_at"] = (
            "2099-01-01T00:09:00+08:00"
        )
        write_json(self.state_path, state)
        json_path, _, original = self.write_handoff()
        state = pipeline.read_json(self.state_path)
        state["source_integrity"] = {
            "status": "warning_unrelated_source_change",
            "checked_action": "downstream_handoff",
        }
        write_json(self.state_path, state)
        self.assertNotEqual(
            original["state_ref"]["sha256"], pipeline.file_sha256(self.state_path)
        )
        with redirect_stdout(io.StringIO()):
            pipeline.command_write_handoff(
                argparse.Namespace(
                    state=str(self.state_path),
                    project_dir=str(self.root),
                    unresolved_issues_json=None,
                    next_allowed_actions_json=None,
                    timestamp="2099-01-01T00:20:00+08:00",
                    refresh_state_ref=True,
                )
            )
        refreshed = pipeline.read_json(json_path)
        self.assertEqual(
            refreshed["state_ref"]["sha256"], pipeline.file_sha256(self.state_path)
        )
        backups = list((self.root / "state").glob("handoff.before_refresh_*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(pipeline.read_json(backups[0]), original)

    def test_rebuild_handoff_markdown_is_deterministic(self) -> None:
        json_path, markdown_path, _ = self.write_handoff()
        original = markdown_path.read_bytes()
        markdown_path.write_text("unsafe stale text", encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            pipeline.command_rebuild_handoff_markdown(
                argparse.Namespace(handoff_json=str(json_path), output=str(markdown_path))
            )
        self.assertEqual(markdown_path.read_bytes(), original)
        first_hash = pipeline.file_sha256(markdown_path)
        with redirect_stdout(io.StringIO()):
            pipeline.command_rebuild_handoff_markdown(
                argparse.Namespace(handoff_json=str(json_path), output=str(markdown_path))
            )
        self.assertEqual(pipeline.file_sha256(markdown_path), first_hash)

    def test_rebuild_markdown_depends_only_on_handoff_json(self) -> None:
        json_path, markdown_path, handoff = self.write_handoff()
        original = markdown_path.read_bytes()
        paths = [
            handoff["authoritative_source"]["path"],
            handoff["source_snapshot_ref"]["path"],
            handoff["overview"]["path"],
            *(item["path"] for item in handoff["content_contracts"]),
            *(item["path"] for item in handoff["reference_assets"]),
            *(item["path"] for item in handoff["candidates"]),
        ]
        for value in paths:
            path = Path(value)
            if path.is_file():
                path.unlink()
        markdown_path.write_text("stale", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            pipeline.command_rebuild_handoff_markdown(
                argparse.Namespace(handoff_json=str(json_path), output=str(markdown_path))
            )
        self.assertEqual(markdown_path.read_bytes(), original)

    def test_formal_overview_event_defers_handoff_until_process_completed(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["status"] = "running"
        state["scheduler"]["phase"] = "formal_overview"
        write_json(self.state_path, state)
        with redirect_stdout(io.StringIO()):
            pipeline.command_record_event(
                argparse.Namespace(
                    state=str(self.state_path),
                    event="formal_overview_completed",
                    style=None,
                    page_id=None,
                    action=None,
                    timestamp="2099-01-01T00:11:00+08:00",
                    details_json=json.dumps({"output_path": str(self.overview_path)}),
                )
            )
        self.assertFalse((self.root / "state" / "handoff.json").exists())
        self.assertFalse((self.root / "state" / "handoff.md").exists())

    def test_process_completed_refreshes_handoff_against_final_state(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["status"] = "running"
        state["scheduler"]["phase"] = "formal_overview"
        candidate_records_before = json.loads(
            json.dumps(state["styles"], ensure_ascii=False)
        )
        scheduler_queues_before = {
            key: json.loads(json.dumps(state["scheduler"].get(key) or []))
            for key in ("active_actions", "ready_queue", "recovery_queue")
        }
        write_json(self.state_path, state)
        with redirect_stdout(io.StringIO()):
            pipeline.command_record_event(
                argparse.Namespace(
                    state=str(self.state_path),
                    event="formal_overview_completed",
                    style=None,
                    page_id=None,
                    action=None,
                    timestamp="2099-01-01T00:11:00+08:00",
                    details_json=json.dumps({"output_path": str(self.overview_path)}),
                )
            )
            pipeline.command_record_event(
                argparse.Namespace(
                    state=str(self.state_path),
                    event="process_completed",
                    style=None,
                    page_id=None,
                    action=None,
                    timestamp="2099-01-01T00:12:00+08:00",
                    details_json="{}",
                )
            )
        handoff = pipeline.read_json(self.root / "state" / "handoff.json")
        self.assertEqual(handoff["generated_at"], "2099-01-01T00:12:00+08:00")
        self.assertEqual(handoff["pipeline_status"], "completed")
        self.assertEqual(handoff["pipeline_phase"], "completed")
        self.assertEqual(
            handoff["state_ref"]["sha256"], pipeline.file_sha256(self.state_path)
        )
        self.assertEqual(
            (self.root / "state" / "handoff.md").read_text(encoding="utf-8"),
            pipeline.render_handoff_markdown(handoff),
        )
        final_state = pipeline.read_json(self.state_path)
        self.assertEqual(final_state["styles"], candidate_records_before)
        for key, expected in scheduler_queues_before.items():
            self.assertEqual(final_state["scheduler"].get(key) or [], expected)

    def test_realistic_matrix_overview_does_not_need_to_be_16_by_9(self) -> None:
        write_png_stub(self.overview_path, 5420, 1752, b"quick-matrix")
        _, _, handoff = self.write_handoff()
        self.assertEqual(handoff["overview"]["width"], 5420)
        self.assertEqual(handoff["overview"]["height"], 1752)

    def test_source_completely_unchanged(self) -> None:
        result = pipeline.evaluate_source_drift(
            self.state_path, action="resume", timestamp="2099-01-01T00:20:00+08:00"
        )
        self.assertEqual(result["status"], "unchanged")
        self.assertTrue(result["can_continue"])
        self.assertFalse(result["warning"])

    def test_pptx_extractor_uses_target_slide_not_other_slide_bytes(self) -> None:
        pptx = self.root / "source" / "outline.pptx"
        write_pptx_fixture(pptx, ["第一页", "目标第二页"])
        first = pipeline.extract_relevant_source_content(pptx, ["02"])
        write_pptx_fixture(pptx, ["第一页已变化", "目标第二页"])
        second = pipeline.extract_relevant_source_content(pptx, ["02"])
        self.assertEqual(first["sha256"], second["sha256"])
        write_pptx_fixture(pptx, ["第一页已变化", "目标第二页已变化"])
        third = pipeline.extract_relevant_source_content(pptx, ["02"])
        self.assertNotEqual(first["sha256"], third["sha256"])

    def test_only_other_outline_page_changed_is_warning_and_can_continue(self) -> None:
        self.source_path.write_text(
            "# 演示大纲\n\n## P02 核心主张\n目标页稳定内容 100%\n\n"
            "## P03 其他页面\n其他页版本二，内容已改变\n",
            encoding="utf-8",
        )
        result = pipeline.evaluate_source_drift(self.state_path, action="resume")
        self.assertEqual(result["status"], "warning_unrelated_source_change")
        self.assertTrue(result["can_continue"])
        self.assertTrue(result["whole_source_changed"])
        self.assertFalse(result["relevant_page_content_changed"])
        _, markdown_path, handoff = self.write_handoff()
        self.assertEqual(
            handoff["source_drift"]["status"], "warning_unrelated_source_change"
        )
        markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("warning_unrelated_source_change", markdown)
        self.assertIn("整个权威源文件 SHA-256 已变化", markdown)

    def test_explicit_fragment_cannot_hide_authoritative_source_change(self) -> None:
        root = self.root / "fragment_run"
        init_task.create_standard_dirs(root)
        init_task.write_task_init_contract(root)
        state_path = root / "state" / "style_run_state.json"
        source = root / "source" / "outline.unsupported"
        fragment = root / "source" / "page_02.txt"
        contract = root / "content_contracts" / "page_02.json"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("source-v1", encoding="utf-8")
        fragment.write_text("目标页稳定内容", encoding="utf-8")
        write_json(contract, {"page_id": "02"})
        write_json(
            state_path,
            {
                "run_id": "fragment-run",
                "run_mode": pipeline.QUICK_8X1_MODE,
                "anchor_page_id": "02",
                "styles": {},
                "events": [],
                "timing": {},
            },
        )
        pipeline.create_source_snapshot(
            project_dir=root,
            state_path=state_path,
            source_path=source,
            page_ids=["02"],
            content_contract_paths=[contract],
            asset_items=[],
            fragment_path=fragment,
        )
        source.write_text("source-v2", encoding="utf-8")
        result = pipeline.evaluate_source_drift(state_path, action="resume")
        self.assertEqual(result["status"], "source_drift_detected")
        self.assertTrue(result["relevant_page_content_changed"])
        self.assertTrue(
            any(
                item.get("reason")
                == "source_change_unverifiable_with_external_fragment"
                for item in result["changes"]
            )
        )

    def test_authoritative_page_fragment_allows_unrelated_upstream_change(self) -> None:
        root = self.root / "authoritative_fragment_run"
        init_task.create_standard_dirs(root)
        init_task.write_task_init_contract(root)
        state_path = root / "state" / "style_run_state.json"
        source = root / "source" / "outline.unsupported"
        fragment = root / "source" / "page_02.txt"
        contract = root / "content_contracts" / "page_02.json"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("upstream-v1", encoding="utf-8")
        fragment.write_text("P02 权威页面内容", encoding="utf-8")
        write_json(contract, {"page_id": "02"})
        write_json(
            state_path,
            {
                "run_id": "authoritative-fragment-run",
                "run_mode": pipeline.FAST8_MODE,
                "anchor_page_id": "02",
                "styles": {},
                "events": [],
                "timing": {},
            },
        )
        snapshot = pipeline.create_source_snapshot(
            project_dir=root,
            state_path=state_path,
            source_path=source,
            page_ids=["02"],
            content_contract_paths=[contract],
            asset_items=[],
            fragment_path=fragment,
            fragment_authority="authoritative_page_fragment",
        )
        self.assertEqual(
            snapshot["page_content"]["authority_mode"],
            "authoritative_page_fragment",
        )
        source.write_text("upstream-v2", encoding="utf-8")
        result = pipeline.evaluate_source_drift(state_path, action="resume")
        self.assertEqual(result["status"], "unchanged")
        self.assertTrue(result["can_continue"])
        self.assertTrue(result["upstream_source_check_skipped"])
        self.assertFalse(result["relevant_page_content_changed"])

        fragment.write_text("P02 已变化的权威页面内容", encoding="utf-8")
        changed = pipeline.evaluate_source_drift(state_path, action="resume")
        self.assertEqual(changed["status"], "source_drift_detected")
        self.assertTrue(changed["relevant_page_content_changed"])

    def test_new_fast8_stops_rehashing_inputs_after_initial_dispatch(self) -> None:
        root = self.root / "fast8_dispatch_locked_run"
        init_task.create_standard_dirs(root)
        init_task.write_task_init_contract(root)
        state_path = root / "state" / "style_run_state.json"
        packet = root / "source" / "authoritative_page_packet.md"
        contract = root / "content_contracts" / "page_02.json"
        packet.parent.mkdir(parents=True, exist_ok=True)
        packet.write_text("page_id: P02\n冻结内容", encoding="utf-8")
        write_json(contract, {"page_id": "02"})
        write_json(
            state_path,
            {
                "run_id": "fast8-dispatch-locked-run",
                "run_mode": pipeline.FAST8_MODE,
                "anchor_page_id": "02",
                "styles": {},
                "events": [],
                "timing": {},
            },
        )
        pipeline.create_source_snapshot(
            project_dir=root,
            state_path=state_path,
            source_path=packet,
            page_ids=["02"],
            content_contract_paths=[contract],
            asset_items=[],
            fragment_path=packet,
            fragment_authority="authoritative_page_fragment",
        )
        state = pipeline.read_json(state_path)
        state["events"].append(
            {
                "name": "dispatch_wave",
                "occurred_at": "2099-01-01T00:00:00+08:00",
            }
        )
        pipeline.atomic_write_json(state_path, state)
        packet.write_text("page_id: P02\n派发后的外部变化", encoding="utf-8")
        result = pipeline.evaluate_source_drift(state_path, action="downstream_handoff")
        self.assertEqual(
            result["status"], "fast8_inputs_locked_at_initial_dispatch"
        )
        self.assertTrue(result["can_continue"])
        self.assertIn("post_dispatch_packet_rehash", result["checks_skipped"])

    def test_current_page_change_blocks_old_candidates_and_handoff(self) -> None:
        self.source_path.write_text(
            "# 演示大纲\n\n## P02 核心主张\n目标页已经改变 100%\n\n"
            "## P03 其他页面\n其他页版本一\n",
            encoding="utf-8",
        )
        result = pipeline.evaluate_source_drift(
            self.state_path, action="selected_style_expansion"
        )
        self.assertEqual(result["status"], "source_drift_detected")
        self.assertFalse(result["can_continue"])
        self.assertTrue(result["relevant_page_content_changed"])
        with self.assertRaises(SystemExit):
            self.write_handoff()
        self.assertFalse((self.root / "state" / "handoff.json").exists())

    def test_used_asset_hash_change_blocks_even_if_size_and_mtime_are_preserved(self) -> None:
        before = self.asset_path.stat()
        self.asset_path.write_bytes(b"ASSET-V2")
        os.utime(self.asset_path, ns=(before.st_atime_ns, before.st_mtime_ns))
        result = pipeline.evaluate_source_drift(
            self.state_path, action="targeted_candidate_repair"
        )
        self.assertEqual(result["status"], "source_drift_detected")
        self.assertTrue(result["used_asset_changed"])
        self.assertTrue(
            any(item["component"] == "used_asset" for item in result["changes"])
        )

    def test_content_contract_change_blocks_dispatch_without_queue_or_event_mutation(self) -> None:
        state_before = pipeline.read_json(self.state_path)
        record = state_before["styles"]["A"]["pages"]["02"]
        for field in ("selected_source", "source_sha256", "tool_call_id"):
            record[field] = None
        record["status"] = "pending"
        state_before["scheduler"] = {
            "phase": "anchor_generation",
            "active_child_limit": 8,
            "active_actions": [],
            "ready_queue": [
                {"style": "A", "page_id": "02", "action": "generate_anchor", "attempt": 1}
            ],
            "recovery_queue": [],
        }
        write_json(
            self.root / "style_jobs" / "style_A.json",
            guarded_generation_job(self.contract_path, [self.asset_path]),
        )
        write_json(self.state_path, state_before)
        scheduler_before = json.dumps(state_before["scheduler"], sort_keys=True)
        events_before = json.dumps(state_before["events"], sort_keys=True)
        write_json(
            self.contract_path,
            {
                "content_contract_version": 2,
                "page_id": "02",
                "display_required": ["合同已经改变"],
            },
        )
        with self.assertRaises(SystemExit):
            pipeline.command_record_dispatch_wave(
                argparse.Namespace(
                    state=str(self.state_path),
                    tasks_json=json.dumps(
                        [
                            {
                                "style": "A",
                                "page_id": "02",
                                "action": "generate_anchor",
                                "attempt": 1,
                            }
                        ]
                    ),
                    styles=None,
                    page_id=None,
                    action="generate_anchor",
                    attempt=1,
                    timestamp="2099-01-01T00:30:00+08:00",
                    agent_map_json=None,
                    backpressure_reason=None,
                )
            )
        state_after = pipeline.read_json(self.state_path)
        self.assertEqual(json.dumps(state_after["scheduler"], sort_keys=True), scheduler_before)
        self.assertEqual(json.dumps(state_after["events"], sort_keys=True), events_before)
        self.assertTrue(state_after["source_drift_detected"])
        self.assertEqual(
            state_after["source_integrity"]["status"], "source_drift_detected"
        )

    def test_legacy_project_without_snapshot_is_not_upgraded_or_given_fake_hashes(self) -> None:
        legacy_root = self.root / "legacy"
        legacy_state = legacy_root / "style_run_state.json"
        write_json(
            legacy_state,
            {
                "run_id": "legacy",
                "run_mode": "quick_4x1",
                "status": "running",
                "events": [{"name": "style_jobs_created"}],
            },
        )
        original = legacy_state.read_bytes()
        result = pipeline.evaluate_source_drift(legacy_state, action="resume")
        self.assertEqual(result["status"], "legacy_snapshot_missing")
        self.assertFalse(result["can_continue"])
        self.assertTrue(result["requires_user_confirmation"])
        self.assertEqual(legacy_state.read_bytes(), original)
        self.assertFalse((legacy_root / "state" / "source_snapshot.json").exists())
        with self.assertRaises(SystemExit):
            pipeline.create_source_snapshot(
                project_dir=legacy_root,
                state_path=legacy_state,
                source_path=self.source_path,
                page_ids=["02"],
                content_contract_paths=[self.contract_path],
                asset_items=[],
            )
        self.assertFalse((legacy_root / "state" / "source_snapshot.json").exists())

    def test_new_guarded_state_missing_snapshot_cannot_downgrade_to_legacy(self) -> None:
        state = pipeline.read_json(self.state_path)
        snapshot = Path(state["source_snapshot_path"])
        snapshot.unlink()
        result = pipeline.evaluate_source_drift(self.state_path, action="resume")
        self.assertEqual(result["status"], "source_snapshot_missing")
        self.assertFalse(result["can_continue"])
        with self.assertRaises(SystemExit):
            pipeline.enforce_source_guard(
                self.state_path, pipeline.read_json(self.state_path), action="resume"
            )

    def test_sealed_source_snapshot_tampering_is_blocked(self) -> None:
        snapshot_path = self.root / "state" / "source_snapshot.json"
        snapshot = pipeline.read_json(snapshot_path)
        snapshot["snapshot_at"] = "2099-01-01T00:00:01+08:00"
        write_json(snapshot_path, snapshot)
        result = pipeline.evaluate_source_drift(self.state_path, action="resume")
        self.assertEqual(result["status"], "source_drift_detected")
        self.assertTrue(result["source_snapshot_changed"])

    def test_handoff_rejects_page_scope_not_covered_by_snapshot(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["phase"] = "selected_style_expansion"
        state["selected_style"] = "style_A"
        state["page_order"] = ["02", "03"]
        state["pages"] = {
            "02": state["styles"]["A"]["pages"]["02"],
            "03": state["styles"]["A"]["pages"]["02"],
        }
        with self.assertRaises(SystemExit):
            pipeline.build_handoff_document(
                project_dir=self.root, state_path=self.state_path, state=state
            )

    def test_handoff_rejects_selection_not_present_in_candidates(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["user_selection"] = {
            "selected": True,
            "candidate_id": "Z-02",
            "selected_style": "style_Z",
        }
        with self.assertRaises(SystemExit):
            pipeline.build_handoff_document(
                project_dir=self.root, state_path=self.state_path, state=state
            )

    def test_operation_manifest_detects_replaced_contract_and_asset_paths(self) -> None:
        state = pipeline.read_json(self.state_path)
        result = pipeline.evaluate_source_drift(self.state_path, state, action="resume")
        snapshot = pipeline.read_json(self.root / "state" / "source_snapshot.json")
        other_contract = self.root / "content_contracts" / "page_02_copy.json"
        other_asset = self.root / "references" / "other.bin"
        write_json(other_contract, pipeline.read_json(self.contract_path))
        other_asset.write_bytes(self.asset_path.read_bytes())
        changed = pipeline.apply_operation_manifest_coverage(
            result,
            snapshot,
            content_contract_paths=[other_contract],
            asset_items=[other_asset],
        )
        self.assertEqual(changed["status"], "source_drift_detected")
        self.assertTrue(changed["content_contract_changed"])
        self.assertTrue(changed["used_asset_changed"])

    def test_content_contract_asset_collector_includes_follower_page_assets(self) -> None:
        items = pipeline.content_contract_asset_items(
            {"required_page_assets": [{"path": str(self.asset_path), "role": "logo"}]}
        )
        self.assertEqual(items[0]["path"], str(self.asset_path))
        self.assertEqual(items[0]["asset_type"], "required_page_asset")

    def test_prepare_4x3_auto_snapshot_includes_follower_page_asset(self) -> None:
        root = self.root / "auto_4x3"
        init_task.create_standard_dirs(root)
        init_task.write_task_init_contract(root)
        state_path = root / "state" / "style_run_state.json"
        source = root / "source.md"
        portfolio = root / "state" / "layout_portfolio.json"
        asset = root / "references" / "page_05_logo.bin"
        anchor_asset = root / "references" / "page_02_logo.bin"
        unused_declared_asset = root / "references" / "not_routed.bin"
        asset.write_bytes(b"PAGE-05-ASSET")
        anchor_asset.write_bytes(b"PAGE-02-ASSET")
        unused_declared_asset.write_bytes(b"NOT-ROUTED")
        source.write_text(
            "## P02\nAnchor content\n\n## P05\nFollower content\n\n## P08\nFinal content\n",
            encoding="utf-8",
        )
        write_json(
            state_path,
            {
                "run_id": "auto-4x3-snapshot",
                "run_mode": pipeline.FAST_4X3_MODE,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "preflight": {"status": "resolved"},
                "scheduler": {"active_actions": [], "ready_queue": []},
                "events": [],
                "timing": {},
            },
        )
        anchor_contract = {
            "content_contract_version": 2,
            "prompt_contract_version": 4,
            "language": "en-US",
            "page_id": "02",
            "title": "Anchor",
            "core_claim": "A stable anchor.",
            "source_facts": ["Synthetic fact"],
            "display_required": ["Anchor"],
            "display_flexible": [],
            "display_supporting": [],
            "semantic_invariants": [],
            "forbidden_interpretations": [],
            "prompt_semantic_guardrails": [],
            "prompt_user_constraints": [],
            "information_density_target": "medium",
            "content_load_review": {
                "semantic_structure": "single proposition",
                "focus_relationship": "one claim",
                "attention_risks": [],
                "edge_and_takeaway_risks": [],
                "duplication_risks": [],
                "reason": "feasible",
            },
            "content_resolution": {
                "status": "not_needed",
                "choice": None,
                "moved_items": [],
                "reason": None,
            },
            "spatial_pressure_profile": "low",
            "spatial_generation_brief": pipeline.QUICK8_BREATHING_PROMPT_CUES["en"]["low"],
            "spatial_qa_contract": "Low-pressure QA applies.",
            "low_pressure_feasibility": "pass",
            "visual_support_goal": "Support the claim.",
            "required_page_assets": [{"path": str(anchor_asset), "role": "logo"}],
        }
        write_json(root / "content_contracts" / "page_02.json", anchor_contract)
        write_json(
            root / "content_contracts" / "page_05.json",
            {
                "page_id": "05",
                "required_page_assets": [{"path": str(asset), "role": "logo"}],
                "reference_assets": [{"path": str(unused_declared_asset)}],
            },
        )
        write_json(root / "content_contracts" / "page_08.json", {"page_id": "08"})
        write_json(
            portfolio,
            {
                "layout_portfolio_contract_version": 6,
                "page_id": "02",
                "director_rationale": "Two guided and two open directions cover this test page.",
                "styles": {
                    "A": {"direction_id": "value_a", "first_impression": "The audience first understands the value."},
                    "B": {"direction_id": "evidence_b", "first_impression": "The audience first trusts the evidence."},
                    "C": {"direction_id": "open_c"},
                    "D": {"direction_id": "open_d"},
                },
            },
        )
        with redirect_stdout(io.StringIO()):
            pipeline.command_prepare_anchors(
                argparse.Namespace(
                    project_dir=str(root),
                    state=str(state_path),
                    content_contract=str(root / "content_contracts" / "page_02.json"),
                    overall_requirements="Fast 4x3 test",
                    reference_images_json="[]",
                    required_assets_json="[]",
                    layout_portfolio=str(portfolio),
                    source_file=str(source),
                    source_page_ids=None,
                    source_fragment_file=None,
                    snapshot_content_contracts_json=None,
                    source_snapshot_timestamp="2099-01-01T00:00:00+08:00",
                )
            )
        snapshot = pipeline.read_json(root / "state" / "source_snapshot.json")
        self.assertEqual(
            {item["path"] for item in snapshot["assets"]},
            {str(asset.resolve()), str(anchor_asset.resolve())},
        )
        self.assertEqual(len(snapshot["content_contracts"]), 3)
        for style in pipeline.FULL_STYLES:
            job = pipeline.read_json(root / "style_jobs" / f"style_{style}.json")
            self.assertIn(str(anchor_asset.resolve()), job["imagegen_referenced_paths"])

    def test_mixed_recovery_and_generation_wave_is_rejected_before_mutation(self) -> None:
        before = self.state_path.read_bytes()
        with self.assertRaises(SystemExit):
            pipeline.command_record_dispatch_wave(
                argparse.Namespace(
                    state=str(self.state_path),
                    tasks_json=json.dumps(
                        [
                            {"style": "A", "page_id": "02", "action": "recover_artifact", "attempt": 1},
                            {"style": "B", "page_id": "02", "action": "generate_anchor", "attempt": 1},
                        ]
                    ),
                    styles=None,
                    page_id=None,
                    action="generate_anchor",
                    attempt=1,
                    timestamp="2099-01-01T00:30:00+08:00",
                    agent_map_json=None,
                    backpressure_reason=None,
                )
            )
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_operation_asset_cannot_escape_sealed_style_routing(self) -> None:
        snapshot = pipeline.read_json(
            self.root / "state" / "source_snapshot.json"
        )
        snapshot["assets"][0]["used_by"] = ["A"]
        result = pipeline.evaluate_source_drift(
            self.state_path, action="generation_dispatch"
        )

        guarded = pipeline.apply_operation_manifest_coverage(
            result,
            snapshot,
            asset_items=[
                {
                    "path": str(self.asset_path.resolve()),
                    "sha256": pipeline.file_sha256(self.asset_path),
                    "used_by": ["B"],
                }
            ],
        )

        self.assertEqual(guarded["status"], "source_drift_detected")
        self.assertFalse(guarded["can_continue"])
        self.assertTrue(
            any(
                item.get("reason")
                == "operation_style_not_in_snapshot_routing"
                for item in guarded["changes"]
            )
        )

    def test_new_task_marker_requires_snapshot_but_legacy_has_no_marker(self) -> None:
        new_root = self.root / "new_task"
        init_task.create_standard_dirs(new_root)
        marker = init_task.write_task_init_contract(
            new_root, timestamp="2099-01-01T00:00:00+08:00"
        )
        value = pipeline.read_json(marker)
        self.assertEqual(value["task_init_contract_version"], 1)
        self.assertTrue(value["source_snapshot_required"])
        self.assertTrue(Path(value["project_dir"]).is_absolute())
        state_path = new_root / "state" / "style_run_state.json"
        write_json(
            state_path,
            {"run_id": "new", "run_mode": pipeline.QUICK_8X1_MODE, "events": []},
        )
        result = pipeline.evaluate_source_drift(state_path, action="resume")
        self.assertEqual(result["status"], "source_snapshot_missing")
        with self.assertRaises(SystemExit):
            pipeline.enforce_source_guard(state_path, pipeline.read_json(state_path), action="resume")

        legacy_root = self.root / "unmarked_legacy"
        init_task.create_standard_dirs(legacy_root)
        self.assertFalse((legacy_root / "state" / "task_init.json").exists())

    def test_init_task_main_marks_only_new_runs_and_resume_preserves_marker(self) -> None:
        output_root = self.root / "task_output"
        task_name = "P02_8x1_20990101"
        with mock.patch(
            "sys.argv",
            ["init_task_dir.py", "--output-root", str(output_root), "--task-name", task_name],
        ), redirect_stdout(io.StringIO()):
            self.assertEqual(init_task.main(), 0)
        project = output_root / task_name
        marker = project / "state" / "task_init.json"
        self.assertTrue(marker.is_file())
        original_marker = marker.read_bytes()
        write_json(project / "state" / "style_run_state.json", {"run_id": "resume"})
        with mock.patch(
            "sys.argv",
            [
                "init_task_dir.py",
                "--output-root",
                str(output_root),
                "--task-name",
                task_name,
                "--resume",
            ],
        ), redirect_stdout(io.StringIO()):
            self.assertEqual(init_task.main(), 0)
        self.assertEqual(marker.read_bytes(), original_marker)

        legacy_name = "P03_4x3_20990101"
        legacy = output_root / legacy_name
        init_task.create_standard_dirs(legacy)
        write_json(legacy / "state" / "style_run_state.json", {"run_id": "legacy"})
        with mock.patch(
            "sys.argv",
            [
                "init_task_dir.py",
                "--output-root",
                str(output_root),
                "--task-name",
                legacy_name,
                "--resume",
            ],
        ), redirect_stdout(io.StringIO()):
            self.assertEqual(init_task.main(), 0)
        self.assertFalse((legacy / "state" / "task_init.json").exists())

    def test_orphan_snapshot_can_only_rebind_same_new_run_inputs(self) -> None:
        root = self.root / "orphan"
        init_task.create_standard_dirs(root)
        init_task.write_task_init_contract(root)
        state_path = root / "state" / "style_run_state.json"
        source = root / "source.md"
        contract = root / "content_contracts" / "page_02.json"
        source.write_text("## P02\n稳定内容", encoding="utf-8")
        write_json(contract, {"page_id": "02"})
        write_json(
            state_path,
            {
                "run_id": "orphan-run",
                "run_mode": pipeline.QUICK_8X1_MODE,
                "anchor_page_id": "02",
                "events": [],
                "styles": {},
            },
        )
        pipeline.create_source_snapshot(
            project_dir=root,
            state_path=state_path,
            source_path=source,
            page_ids=["02"],
            content_contract_paths=[contract],
            asset_items=[],
            timestamp="2099-01-01T00:00:00+08:00",
        )
        sealed = (root / "state" / "source_snapshot.json").read_bytes()
        state = pipeline.read_json(state_path)
        for key in (
            "source_guard_contract_version",
            "source_snapshot_path",
            "source_snapshot_sha256",
            "source_integrity",
        ):
            state.pop(key, None)
        write_json(state_path, state)
        pipeline.create_source_snapshot(
            project_dir=root,
            state_path=state_path,
            source_path=source,
            page_ids=["02"],
            content_contract_paths=[contract],
            asset_items=[],
            timestamp="2099-01-01T00:00:01+08:00",
        )
        rebound = pipeline.read_json(state_path)
        self.assertEqual(
            rebound["source_snapshot_sha256"],
            pipeline.file_sha256(root / "state" / "source_snapshot.json"),
        )
        self.assertEqual((root / "state" / "source_snapshot.json").read_bytes(), sealed)

    def test_dispatch_rejects_job_asset_not_covered_by_snapshot(self) -> None:
        state = pipeline.read_json(self.state_path)
        record = state["styles"]["A"]["pages"]["02"]
        record["tool_call_id"] = "tool-A"
        state["scheduler"] = {
            "phase": "anchor_generation",
            "active_child_limit": 8,
            "active_actions": [],
            "ready_queue": [
                {"style": "A", "page_id": "02", "action": "repair_anchor", "attempt": 2}
            ],
            "recovery_queue": [],
        }
        write_json(self.state_path, state)
        other_asset = self.root / "references" / "unsnapshotted.bin"
        other_asset.write_bytes(b"UNSNAPSHOTTED")
        job_path = (
            self.root
            / "style_jobs"
            / "repair_jobs"
            / "style_A_page_02_attempt_2.json"
        )
        write_json(
            job_path,
            guarded_generation_job(
                self.contract_path,
                [Path(record["selected_source"]), other_asset],
                prompt="repair fixture",
                action="repair_anchor",
                attempt=2,
            ),
        )
        scheduler_before = json.dumps(
            pipeline.read_json(self.state_path)["scheduler"], sort_keys=True
        )
        with self.assertRaises(SystemExit):
            pipeline.command_record_dispatch_wave(
                argparse.Namespace(
                    state=str(self.state_path),
                    tasks_json=json.dumps(
                        [
                            {"style": "A", "page_id": "02", "action": "repair_anchor", "attempt": 2}
                        ]
                    ),
                    styles=None,
                    page_id=None,
                    action="repair_anchor",
                    attempt=2,
                    timestamp="2099-01-01T00:31:00+08:00",
                    agent_map_json=None,
                    backpressure_reason=None,
                )
            )
        after = pipeline.read_json(self.state_path)
        self.assertEqual(json.dumps(after["scheduler"], sort_keys=True), scheduler_before)
        self.assertTrue(after["source_drift_detected"])

    def test_clean_recheck_clears_stale_drift_marker(self) -> None:
        original = self.asset_path.read_bytes()
        self.asset_path.write_bytes(b"ASSET-V2")
        with self.assertRaises(SystemExit):
            pipeline.enforce_source_guard(
                self.state_path,
                pipeline.read_json(self.state_path),
                action="targeted_candidate_repair",
            )
        self.asset_path.write_bytes(original)
        result = pipeline.enforce_source_guard(
            self.state_path, pipeline.read_json(self.state_path), action="resume"
        )
        self.assertEqual(result["status"], "unchanged")
        state = pipeline.read_json(self.state_path)
        self.assertFalse(state["source_drift_detected"])
        self.assertEqual(state["source_integrity"]["status"], "unchanged")

    def test_selected_expansion_generation_event_is_guarded(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["status"] = "running"
        state["scheduler"]["phase"] = "selected_style_expansion"
        state["phase"] = "selected_style_expansion"
        state["pages"] = {"02": {"status": "pending", "attempt_count": 0}}
        write_json(self.state_path, state)
        expansion_job = self.root / "page_jobs" / "page_02.json"
        job = guarded_generation_job(self.contract_path, [self.asset_path])
        job["page_id"] = "02"
        write_json(expansion_job, job)
        self.source_path.write_text(
            "# 演示大纲\n\n## P02 核心主张\n本页已变化\n", encoding="utf-8"
        )
        before = pipeline.read_json(self.state_path)
        with self.assertRaises(SystemExit):
            pipeline.command_record_event(
                argparse.Namespace(
                    state=str(self.state_path),
                    event="agent_action_started",
                    style=None,
                    page_id="02",
                    action="generate_page",
                    timestamp="2099-01-01T00:40:00+08:00",
                    details_json=json.dumps(
                        {"generation_job_path": str(expansion_job)}
                    ),
                )
            )
        after = pipeline.read_json(self.state_path)
        self.assertEqual(after["pages"], before["pages"])
        self.assertTrue(after["source_drift_detected"])

    def test_handoff_rejects_relative_artifact_path_and_embedded_media_text(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["styles"]["A"]["pages"]["02"]["selected_source"] = "relative.png"
        with self.assertRaises(SystemExit):
            pipeline.build_handoff_document(
                project_dir=self.root,
                state_path=self.state_path,
                state=state,
            )
        _, _, handoff = self.write_handoff()
        handoff["unresolved_issues"] = ["data:image/png;base64,AAAA"]
        with self.assertRaises(SystemExit):
            pipeline.render_handoff_markdown(handoff)

    def test_parser_exposes_all_source_and_handoff_commands(self) -> None:
        parser = pipeline.build_parser()
        help_text = parser.format_help()
        for command in (
            "snapshot-source",
            "check-source-drift",
            "confirm-legacy-source-risk",
            "check-expansion-job",
            "write-handoff",
            "rebuild-handoff-md",
        ):
            self.assertIn(command, help_text)


if __name__ == "__main__":
    unittest.main()
