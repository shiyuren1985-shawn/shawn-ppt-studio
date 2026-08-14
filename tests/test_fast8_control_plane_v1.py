from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

import tests.test_fast8x1_pipeline as fast8_fixture
from tests.test_quick8_pipeline import write_json, write_png


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "fast8_control_plane_v1.py"
BURST_WRAPPER_PATH = ROOT / "prompts" / "fast8-burst-runner.md"
SPEC = importlib.util.spec_from_file_location("fast8_control_plane_v1_test", MODULE_PATH)
assert SPEC and SPEC.loader
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)
pipeline = fast8_fixture.pipeline
NODE = Path(os.environ.get("SHAWN_PPT_TEST_NODE", Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"))
PYTHON_WITH_PIL = Path(os.environ.get("SHAWN_PPT_TEST_PYTHON", Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"))


class Fast8ControlPlaneV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fast8_fixture.Fast8PipelineTest(
            "test_prepare_uses_art_directed_prompts_and_nine_slots"
        )
        self.fixture.setUp()
        self.fixture.prepare(overview_python=str(PYTHON_WITH_PIL))
        self.generated_root = self.fixture.root / "generated_images"
        self.slot_registry = self.fixture.root / "runtime" / "imagegen_slots.json"
        self.env = mock.patch.dict(
            control.os.environ,
            {
                "SHAWN_PPT_IMAGE_GLOBAL_SLOT_STATE": str(self.slot_registry),
                control.IMAGEGEN_SLOT_LIMIT_ENV: "5",
            },
        )
        self.env.start()
        self.generated_patch = mock.patch.object(
            control.pc, "GENERATED_IMAGES_ROOT", self.generated_root.resolve()
        )
        self.generated_patch.start()

    def tearDown(self) -> None:
        self.generated_patch.stop()
        self.env.stop()
        self.fixture.tearDown()

    def prepare(self) -> dict:
        return control.build_manifest(self.fixture.state_path.resolve(), dispatch=True)

    def claim(
        self,
        ticket: Path,
        wait_seconds: float = 0,
        *,
        manifest: dict | None = None,
        capacity_limit: int | None = None,
        manifest_sha256: str | None = None,
    ) -> dict:
        manifest = manifest or self.prepare()
        return control.claim_ticket(
            self.fixture.state_path,
            ticket,
            wait_seconds,
            manifest_path=Path(manifest["manifest_path"]),
            manifest_sha256=manifest_sha256 or manifest["manifest_sha256"],
            capacity_limit=(
                capacity_limit
                if capacity_limit is not None
                else manifest["global_imagegen_concurrency"]
            ),
        )

    def ticket(self, style: str) -> Path:
        manifest = self.prepare()
        return Path(next(item["ticket_path"] for item in manifest["seats"] if item["style"] == style))

    def artifact(self, style: str) -> tuple[Path, str]:
        index = ord(style) - ord("A") + 1
        tool_id = f"exec-00000000-0000-4000-8000-{index:012d}"
        path = self.generated_root / "burst" / f"{tool_id}.png"
        write_png(path, color=bytes((220 - index, 230 - index, 240 - index)))
        return path, tool_id

    def slot_task(self, style: str) -> dict:
        return {
            "style": style,
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
            "lease_kind": "test",
        }

    def acquire_slot(self, style: str, capacity_limit: int | None):
        state = pipeline.read_json(self.fixture.state_path)
        return pipeline.acquire_fast8_global_imagegen_slots(
            self.fixture.state_path,
            state,
            [self.slot_task(style)],
            timestamp=pipeline.now_iso(),
            capacity_limit=capacity_limit,
        )

    def claim_and_receipt(self, style: str, *, missing: bool = False, failed: bool = False) -> None:
        ticket = self.ticket(style)
        claim = self.claim(ticket)
        self.assertEqual(claim["status"], "claimed")
        path, tool_id = self.artifact(style)
        started = control.pc.now_iso()
        finished = control.pc.now_iso()
        control.write_receipt(
            self.fixture.state_path,
            ticket,
            tool_status="failed" if failed else "completed",
            saved_path=None if missing or failed else str(path),
            tool_call_id=None if missing or failed else tool_id,
            tool_started_at=started,
            tool_finished_at=finished,
            failure_class="backend_failed" if failed else None,
            tool_error_code="stub_failure" if failed else None,
        )

    def settle_all_success(self) -> None:
        self.prepare()
        for style in control.STYLES:
            self.claim_and_receipt(style)
        result = control.settle(self.fixture.state_path)
        self.assertTrue(result["all_anchor_tools_completed"])

    def test_prepare_dispatches_exactly_eight_without_changing_quality_inputs(self) -> None:
        before = {}
        for style in control.STYLES:
            job_path = self.fixture.root / "style_jobs" / f"style_{style}.json"
            job = pipeline.read_json(job_path)
            before[style] = (
                pipeline.file_sha256(job_path),
                job["imagegen_prompt_fingerprint"],
                job["imagegen_input_fingerprint"],
                list(job["imagegen_referenced_paths"]),
            )
        manifest = self.prepare()
        self.assertEqual([item["style"] for item in manifest["seats"]], list(control.STYLES))
        self.assertEqual(len({item["ticket_sha256"] for item in manifest["seats"]}), 8)
        for item in manifest["seats"]:
            style = item["style"]
            self.assertEqual(
                before[style],
                (
                    item["job_sha256"],
                    item["imagegen_prompt_fingerprint"],
                    item["imagegen_input_fingerprint"],
                    item["imagegen_referenced_paths"],
                ),
            )

    def test_duplicate_claim_and_wrong_page_or_job_are_rejected(self) -> None:
        ticket = self.ticket("A")
        self.claim(ticket)
        with self.assertRaisesRegex(SystemExit, "duplicate claim"):
            self.claim(ticket)

        state = pipeline.read_json(self.fixture.state_path)
        state["anchor_page_id"] = "wrong-page"
        write_json(self.fixture.state_path, state)
        with self.assertRaisesRegex(SystemExit, "页码错绑"):
            control.active_for_ticket(self.fixture.state_path, state, self.ticket_path_from_disk("B"))

    def ticket_path_from_disk(self, style: str) -> Path:
        matches = list((self.fixture.root / "style_jobs" / "dispatch_tickets").glob(f"ticket_{style}_*.json"))
        self.assertEqual(len(matches), 1)
        return matches[0].resolve()

    def unprepared_fixture(self):
        fixture = fast8_fixture.Fast8PipelineTest(
            "test_prepare_uses_art_directed_prompts_and_nine_slots"
        )
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture

    def write_director_bundle(
        self,
        fixture,
        *,
        style_reference: Path,
        evidence: Path,
        fail_stage: str | None = None,
    ) -> dict[str, Path]:
        root = fixture.root / "state" / "director_inputs"
        root.mkdir(parents=True, exist_ok=True)
        source = root / "authoritative_page_packet.md"
        source.write_text(fixture.source_path.read_text(encoding="utf-8"), encoding="utf-8")
        prepared_content = pipeline.read_json(fixture.content_path)
        raw_content = {
            "page_id": "02",
            "language": prepared_content["language"],
            "source_facts": prepared_content["source_facts"],
            "display_required": prepared_content["display_required"],
            "display_flexible": prepared_content["display_flexible"],
            "display_supporting": prepared_content["display_supporting"],
            "flexible_story": prepared_content["flexible_story"],
            "information_density_target": prepared_content[
                "information_density_target"
            ],
            "semantic_invariants": prepared_content["semantic_invariants"],
            "forbidden_interpretations": prepared_content[
                "forbidden_interpretations"
            ],
            "prompt_semantic_guardrails": prepared_content[
                "prompt_semantic_guardrails"
            ],
            "prompt_user_constraints": prepared_content["prompt_user_constraints"],
            "content_resolution": {
                "status": "resolved" if fail_stage == "normalize" else "not_needed",
                "reason": "fixture 已明确，无需额外决定。",
            },
        }
        content_raw = root / "content_contract.json"
        write_json(content_raw, raw_content)
        raw_layout = pipeline.read_json(fixture.portfolio_path)
        styles = raw_layout.pop("styles")
        for field in (
            "layout_portfolio_contract_version",
            "art_direction_contract_version",
            "visual_activity_portfolio_version",
            "spatial_topology_portfolio_version",
        ):
            raw_layout.pop(field, None)
        raw_layout["directions"] = styles
        if fail_stage == "prepare":
            raw_layout["directions"]["H"]["craft_axis"] = raw_layout[
                "directions"
            ]["A"]["craft_axis"]
        layout_raw = root / "layout_portfolio.json"
        write_json(layout_raw, raw_layout)
        creative = {
            "creative_intent_contract_version": 1,
            "page_id": "02",
            "relationship_thesis": prepared_content["relationship_thesis"],
            "visual_quality_intent": prepared_content["visual_quality_intent"],
            "visual_support_goal": prepared_content["visual_support_goal"],
            "craft_ambition": prepared_content["craft_ambition"],
        }
        if fail_stage == "merge":
            creative.pop("craft_ambition")
        creative_intent = root / "creative_intent.json"
        write_json(creative_intent, creative)
        required_assets = root / "required_assets.json"
        write_json(
            required_assets,
            [
                {
                    "path": str(evidence.resolve()),
                    "role": "project_visual_evidence",
                    "use": "fixture evidence",
                }
            ],
        )
        write_json(
            fixture.root / "state" / "preflight_manifest.json",
            {
                "fast8_preflight_manifest_version": 1,
                "run_mode": pipeline.FAST8_MODE,
                "page_ids": ["02"],
                "asset_items": [
                    {
                        "path": str(style_reference.resolve()),
                        "role": "primary_style_reference",
                    },
                    {
                        "path": str(evidence.resolve()),
                        "role": "project_visual_evidence",
                    },
                ],
            },
        )
        return {
            "root": root,
            "source": source,
            "content_raw": content_raw,
            "layout_raw": layout_raw,
            "creative_intent": creative_intent,
            "required_assets": required_assets,
            "content_normalized": root / "content_contract.normalized.json",
            "layout_normalized": root / "layout_portfolio.normalized.json",
            "provenance": root / "director_outputs.normalized.json",
            "content_merged": root / "content_contract.merged.json",
            "overall": root / "overall_requirements.txt",
        }

    def old_three_step_prepare(
        self,
        fixture,
        paths: dict[str, Path],
        style_reference: Path,
    ) -> None:
        normalizer = MODULE_PATH.parent / "normalize_fast8_director_outputs.py"
        merger = MODULE_PATH.parent / "merge_fast8_director_inputs.py"
        subprocess.run(
            [
                str(PYTHON_WITH_PIL),
                str(normalizer),
                "--content-input",
                str(paths["content_raw"]),
                "--layout-input",
                str(paths["layout_raw"]),
                "--content-output",
                str(paths["content_normalized"]),
                "--layout-output",
                str(paths["layout_normalized"]),
                "--provenance-output",
                str(paths["provenance"]),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                str(PYTHON_WITH_PIL),
                str(merger),
                "--content-contract",
                str(paths["content_normalized"]),
                "--creative-intent",
                str(paths["creative_intent"]),
                "--output",
                str(paths["content_merged"]),
                "--overall-requirements-output",
                str(paths["overall"]),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        fixture.call(
            pipeline.command_prepare_anchors,
            project_dir=str(fixture.root),
            state=str(fixture.state_path),
            content_contract=str(paths["content_merged"]),
            overall_requirements=str(paths["overall"]),
            reference_images_json=json.dumps(
                [
                    {
                        "path": str(style_reference.resolve()),
                        "role": "primary_style_reference",
                    }
                ]
            ),
            required_assets_json=None,
            required_assets_file=str(paths["required_assets"]),
            global_chrome_contract=None,
            source_file=str(paths["source"]),
            source_page_ids="02",
            source_fragment_file=str(paths["source"]),
            source_fragment_authority="authoritative_page_fragment",
            snapshot_content_contracts_json=None,
            source_snapshot_timestamp=None,
            layout_portfolio=str(paths["layout_normalized"]),
            overview_python=None,
        )

    def write_standard_chrome_director_bundle(
        self,
        fixture,
        *,
        extra_preflight_assets: list[dict[str, str]] | None = None,
        required_assets: list[dict[str, str]] | None = None,
    ) -> dict[str, Path]:
        unused_style = fixture.root / "unused_style.png"
        unused_evidence = fixture.root / "unused_evidence.png"
        write_png(unused_style, color=bytes((220, 225, 230)))
        write_png(unused_evidence, color=bytes((200, 210, 220)))
        paths = self.write_director_bundle(
            fixture, style_reference=unused_style, evidence=unused_evidence
        )
        write_json(paths["required_assets"], required_assets or [])

        source_contract = fixture.write_global_chrome_contract()
        chrome = pipeline.read_json(source_contract)
        raw_chrome = paths["root"] / "global_chrome_contract.json"
        normalized_chrome = paths["root"] / "global_chrome_contract.normalized.json"
        write_json(raw_chrome, chrome)
        write_json(normalized_chrome, chrome)

        deck = chrome["deck_title_system"]
        asset_items = [
            {
                "path": item["path"],
                "role": f"official_ra_graphic_logo_{tone}_tone",
            }
            for tone, item in deck["logo"]["assets_by_tone"].items()
        ]
        asset_items.append(
            {
                "path": deck["qa_reference_path"],
                "role": "global_chrome_alignment_reference",
            }
        )
        asset_items.extend(extra_preflight_assets or [])
        write_json(
            fixture.root / "state" / "preflight_manifest.json",
            {
                "fast8_preflight_manifest_version": 1,
                "run_mode": pipeline.FAST8_MODE,
                "page_ids": ["02"],
                "asset_items": asset_items,
            },
        )
        paths.update(
            {
                "global_chrome_raw": raw_chrome,
                "global_chrome": normalized_chrome,
                "qa_reference": Path(deck["qa_reference_path"]).resolve(),
            }
        )
        return paths

    def test_prepare_directors_matches_old_three_step_quality_inputs(self) -> None:
        legacy = self.unprepared_fixture()
        combined = self.unprepared_fixture()
        style_reference = self.fixture.root / "shared_style_reference.png"
        evidence = self.fixture.root / "shared_evidence.png"
        write_png(style_reference, color=bytes((220, 225, 230)))
        write_png(evidence, color=bytes((200, 210, 220)))
        legacy_paths = self.write_director_bundle(
            legacy, style_reference=style_reference, evidence=evidence
        )
        combined_paths = self.write_director_bundle(
            combined, style_reference=style_reference, evidence=evidence
        )
        self.old_three_step_prepare(legacy, legacy_paths, style_reference)
        run = subprocess.run(
            [
                str(PYTHON_WITH_PIL),
                str(MODULE_PATH),
                "prepare-directors",
                "--state",
                str(combined.state_path),
            ],
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        summary = json.loads(run.stdout)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["style_job_count"], 8)
        self.assertEqual(
            list(summary["stages"]), ["normalize", "merge", "prepare_anchors"]
        )
        self.assertNotIn("imagegen_prompt", run.stdout)
        self.assertEqual(
            pipeline.read_json(legacy_paths["content_normalized"]),
            pipeline.read_json(combined_paths["content_normalized"]),
        )
        self.assertEqual(
            pipeline.read_json(legacy_paths["layout_normalized"]),
            pipeline.read_json(combined_paths["layout_normalized"]),
        )
        legacy_merged = pipeline.read_json(legacy_paths["content_merged"])
        combined_merged = pipeline.read_json(combined_paths["content_merged"])
        for value in (legacy_merged, combined_merged):
            provenance = value.get("creative_intent_provenance") or {}
            provenance.pop("path", None)
        self.assertEqual(legacy_merged, combined_merged)
        for style in control.STYLES:
            legacy_job = pipeline.read_json(
                legacy.root / "style_jobs" / f"style_{style}.json"
            )
            combined_job = pipeline.read_json(
                combined.root / "style_jobs" / f"style_{style}.json"
            )
            for field in (
                "imagegen_prompt",
                "imagegen_prompt_fingerprint",
                "imagegen_input_fingerprint",
                "imagegen_referenced_paths",
            ):
                self.assertEqual(legacy_job[field], combined_job[field])

    def test_prepare_directors_accepts_global_chrome_qa_reference_without_routing_it_to_imagegen(
        self,
    ) -> None:
        fixture = self.unprepared_fixture()
        paths = self.write_standard_chrome_director_bundle(fixture)

        result = control.prepare_director_inputs(fixture.state_path.resolve())

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["style_job_count"], 8)
        chrome = pipeline.read_json(paths["global_chrome"])
        brief = chrome["deck_title_system"]["prompt_briefs"]["zh"]
        logo_paths = {
            str(Path(item["path"]).resolve())
            for item in chrome["deck_title_system"]["logo"]["assets_by_tone"].values()
        }
        for style in control.STYLES:
            job = pipeline.read_json(
                fixture.root / "style_jobs" / f"style_{style}.json"
            )
            self.assertEqual(job["imagegen_prompt"].count(brief), 1)
            self.assertNotIn(
                str(paths["qa_reference"]), job["imagegen_referenced_paths"]
            )
            self.assertEqual(len(job["imagegen_referenced_paths"]), 1)
            self.assertIn(job["imagegen_referenced_paths"][0], logo_paths)
        snapshot = pipeline.read_json(
            fixture.root / "state" / "source_snapshot.json"
        )
        qa_assets = [
            item
            for item in snapshot["assets"]
            if item["path"] == str(paths["qa_reference"])
        ]
        self.assertEqual(len(qa_assets), 1)
        self.assertIn("global_chrome_qa_reference", qa_assets[0]["roles"])

    def test_prepare_directors_still_rejects_other_unrouted_non_style_assets(
        self,
    ) -> None:
        for role in ("project_visual_evidence", "required_page_asset"):
            with self.subTest(role=role):
                fixture = self.unprepared_fixture()
                missing = fixture.root / f"unrouted_{role}.png"
                write_png(missing, color=bytes((180, 190, 200)))
                self.write_standard_chrome_director_bundle(
                    fixture,
                    extra_preflight_assets=[
                        {"path": str(missing.resolve()), "role": role}
                    ],
                )

                result = control.prepare_director_inputs(fixture.state_path.resolve())

                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["failed_stage"], "precheck")
                self.assertIn(str(missing.resolve()), result["error"])
                self.assertEqual(result["style_job_count"], 0)
                self.assertEqual(
                    list((fixture.root / "style_jobs").glob("style_[A-H].json")),
                    [],
                )
                state = pipeline.read_json(fixture.state_path)
                self.assertEqual(
                    (state.get("scheduler") or {}).get("active_actions") or [], []
                )
                self.assertFalse((fixture.root / "state" / "burst_claims").exists())
                self.assertEqual(
                    list(
                        (fixture.root / "style_jobs" / "results").glob(
                            "*receipt*.json"
                        )
                    ),
                    [],
                )
                self.assertEqual(
                    list((fixture.root / "origin_image").glob("*")), []
                )

    def test_prepare_directors_without_global_chrome_still_succeeds_with_no_assets(
        self,
    ) -> None:
        fixture = self.unprepared_fixture()
        unused_style = fixture.root / "unused_no_chrome_style.png"
        unused_evidence = fixture.root / "unused_no_chrome_evidence.png"
        write_png(unused_style, color=bytes((220, 225, 230)))
        write_png(unused_evidence, color=bytes((200, 210, 220)))
        paths = self.write_director_bundle(
            fixture, style_reference=unused_style, evidence=unused_evidence
        )
        write_json(paths["required_assets"], [])
        write_json(
            fixture.root / "state" / "preflight_manifest.json",
            {
                "fast8_preflight_manifest_version": 1,
                "run_mode": pipeline.FAST8_MODE,
                "page_ids": ["02"],
                "asset_items": [],
            },
        )

        result = control.prepare_director_inputs(fixture.state_path.resolve())

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["style_job_count"], 8)
        for style in control.STYLES:
            job = pipeline.read_json(
                fixture.root / "style_jobs" / f"style_{style}.json"
            )
            self.assertEqual(job["imagegen_referenced_paths"], [])
        self.assertFalse((fixture.root / "state" / "burst_claims").exists())
        self.assertEqual(
            list((fixture.root / "style_jobs" / "results").glob("*receipt*.json")),
            [],
        )

    def test_prepare_directors_stage_failures_never_dispatch_or_write_receipts(self) -> None:
        style_reference = self.fixture.root / "failure_style_reference.png"
        evidence = self.fixture.root / "failure_evidence.png"
        write_png(style_reference, color=bytes((220, 220, 220)))
        write_png(evidence, color=bytes((200, 200, 200)))
        for stage, expected in (
            ("normalize", "normalize"),
            ("merge", "merge"),
            ("prepare", "prepare_anchors"),
        ):
            with self.subTest(stage=stage):
                fixture = self.unprepared_fixture()
                self.write_director_bundle(
                    fixture,
                    style_reference=style_reference,
                    evidence=evidence,
                    fail_stage=stage,
                )
                run = subprocess.run(
                    [
                        str(PYTHON_WITH_PIL),
                        str(MODULE_PATH),
                        "prepare-directors",
                        "--state",
                        str(fixture.state_path),
                    ],
                    text=True,
                    capture_output=True,
                    timeout=30,
                )
                self.assertNotEqual(run.returncode, 0)
                summary = json.loads(run.stdout)
                self.assertEqual(summary["failed_stage"], expected)
                self.assertEqual(summary["style_job_count"], 0)
                self.assertEqual(
                    list((fixture.root / "style_jobs").glob("style_[A-H].json")), []
                )
                state = pipeline.read_json(fixture.state_path)
                scheduler = state.get("scheduler") or {}
                self.assertEqual(scheduler.get("active_actions") or [], [])
                self.assertFalse((fixture.root / "state" / "burst_claims").exists())
                self.assertEqual(
                    list((fixture.root / "style_jobs" / "results").glob("*receipt*.json")),
                    [],
                )

    def test_live_cap5_rejects_cap6_without_mutating_registry(self) -> None:
        self.acquire_slot("A", 5)
        before = self.slot_registry.read_bytes()
        with self.assertRaisesRegex(SystemExit, "禁止切换全局容量"):
            self.acquire_slot("B", 6)
        self.assertEqual(self.slot_registry.read_bytes(), before)
        registry = pipeline.read_json(self.slot_registry)
        self.assertEqual(registry["capacity"], 5)
        self.assertEqual([item["style"] for item in registry["leases"]], ["A"])

    def test_live_cap6_accepts_more_cap6_claims(self) -> None:
        first = self.acquire_slot("A", 6)
        second = self.acquire_slot("B", 6)
        self.assertEqual([item["style"] for item in first[0]], ["A"])
        self.assertEqual([item["style"] for item in second[0]], ["B"])
        registry = pipeline.read_json(self.slot_registry)
        self.assertEqual(registry["capacity"], 6)
        self.assertEqual({item["style"] for item in registry["leases"]}, {"A", "B"})

    def test_capacity_returns_to_five_after_all_cap6_leases_release(self) -> None:
        acquired, _deferred, lease_ids, _remaining = self.acquire_slot("A", 6)
        self.assertEqual([item["style"] for item in acquired], ["A"])
        state = pipeline.read_json(self.fixture.state_path)
        self.assertEqual(
            pipeline.release_fast8_global_imagegen_slots(
                self.fixture.state_path,
                state,
                list(lease_ids.values()),
            ),
            1,
        )
        self.acquire_slot("B", 5)
        registry = pipeline.read_json(self.slot_registry)
        self.assertEqual(registry["capacity"], 5)
        self.assertEqual([item["style"] for item in registry["leases"]], ["B"])

    def test_expired_lease_does_not_block_capacity_switch(self) -> None:
        write_json(
            self.slot_registry,
            {
                "fast8_global_imagegen_slot_contract_version": (
                    pipeline.FAST8_GLOBAL_IMAGEGEN_SLOT_CONTRACT_VERSION
                ),
                "capacity": 6,
                "leases": [
                    {
                        "lease_id": "expired",
                        "style": "A",
                        "expires_at": "2000-01-01T00:00:00+00:00",
                    }
                ],
            },
        )
        self.acquire_slot("B", 5)
        registry = pipeline.read_json(self.slot_registry)
        self.assertEqual(registry["capacity"], 5)
        self.assertEqual([item["style"] for item in registry["leases"]], ["B"])

    def test_legacy_acquire_without_capacity_limit_preserves_current_capacity(self) -> None:
        self.acquire_slot("A", 6)
        self.acquire_slot("B", None)
        registry = pipeline.read_json(self.slot_registry)
        self.assertEqual(registry["capacity"], 6)
        self.assertEqual({item["style"] for item in registry["leases"]}, {"A", "B"})

    def test_global_jit_capacity_is_five_and_release_unblocks_next_seat(self) -> None:
        manifest = self.prepare()
        tickets = {item["style"]: Path(item["ticket_path"]) for item in manifest["seats"]}
        for style in "ABCDE":
            self.assertEqual(
                self.claim(tickets[style], manifest=manifest)["status"],
                "claimed",
            )
        self.assertEqual(
            self.claim(tickets["F"], manifest=manifest)["status"],
            "capacity_wait_timeout",
        )
        control.release_ticket(self.fixture.state_path, tickets["A"])
        self.assertEqual(
            self.claim(tickets["F"], manifest=manifest)["status"],
            "claimed",
        )
        registry = pipeline.read_json(self.slot_registry)
        self.assertLessEqual(len(registry["leases"]), 5)
        self.assertEqual(registry["capacity"], 5)

    def test_default_and_experimental_capacity_are_frozen_in_manifest_and_claims(self) -> None:
        default_manifest = self.prepare()
        self.assertEqual(default_manifest["global_imagegen_concurrency"], 5)
        default_action = control.render_action(default_manifest)
        self.assertIn("--capacity 5", default_action)
        self.assertIn(
            f"--manifest-sha256 {default_manifest['manifest_sha256']}",
            default_action,
        )

    def test_override_six_is_parsed_once_and_caps_claims_at_six(self) -> None:
        before = {}
        for style in control.STYLES:
            job_path = self.fixture.root / "style_jobs" / f"style_{style}.json"
            job = pipeline.read_json(job_path)
            before[style] = (
                job["imagegen_prompt_fingerprint"],
                job["imagegen_input_fingerprint"],
                list(job["imagegen_referenced_paths"]),
            )
        with mock.patch.dict(
            control.os.environ,
            {control.IMAGEGEN_SLOT_LIMIT_ENV: "6"},
        ):
            manifest = self.prepare()
        self.assertEqual(manifest["global_imagegen_concurrency"], 6)
        action = control.render_action(manifest)
        self.assertIn("--capacity 6", action)
        self.assertEqual(action.count("--capacity 6"), 1)
        for item in manifest["seats"]:
            self.assertEqual(
                before[item["style"]],
                (
                    item["imagegen_prompt_fingerprint"],
                    item["imagegen_input_fingerprint"],
                    item["imagegen_referenced_paths"],
                ),
            )
        tickets = {item["style"]: Path(item["ticket_path"]) for item in manifest["seats"]}
        for style in "ABCDEF":
            self.assertEqual(
                self.claim(tickets[style], manifest=manifest)["status"],
                "claimed",
            )
        self.assertEqual(
            self.claim(tickets["G"], manifest=manifest)["status"],
            "capacity_wait_timeout",
        )
        registry = pipeline.read_json(self.slot_registry)
        self.assertEqual(registry["capacity"], 6)
        self.assertEqual(len(registry["leases"]), 6)

    def test_override_eight_allows_exactly_eight_claims(self) -> None:
        with mock.patch.dict(
            control.os.environ,
            {control.IMAGEGEN_SLOT_LIMIT_ENV: "8"},
        ):
            manifest = self.prepare()
        self.assertEqual(manifest["global_imagegen_concurrency"], 8)
        tickets = {item["style"]: Path(item["ticket_path"]) for item in manifest["seats"]}
        for style in control.STYLES:
            self.assertEqual(
                self.claim(tickets[style], manifest=manifest)["status"],
                "claimed",
            )
        registry = pipeline.read_json(self.slot_registry)
        self.assertEqual(registry["capacity"], 8)
        self.assertEqual(len(registry["leases"]), 8)

    def test_invalid_experimental_capacity_is_rejected_before_dispatch(self) -> None:
        for value in ("0", "9", "not-a-number"):
            with self.subTest(value=value), mock.patch.dict(
                control.os.environ,
                {control.IMAGEGEN_SLOT_LIMIT_ENV: value},
            ):
                with self.assertRaisesRegex(SystemExit, "1–8"):
                    control.build_manifest(
                        self.fixture.state_path.resolve(),
                        dispatch=True,
                    )
                state = pipeline.read_json(self.fixture.state_path)
                self.assertEqual((state.get("scheduler") or {}).get("active_actions") or [], [])

    def test_claim_rejects_capacity_or_manifest_identity_mismatch(self) -> None:
        manifest = self.prepare()
        ticket = Path(manifest["seats"][0]["ticket_path"])
        with self.assertRaisesRegex(SystemExit, "capacity 与 manifest"):
            self.claim(ticket, manifest=manifest, capacity_limit=6)
        with self.assertRaisesRegex(SystemExit, "manifest SHA"):
            self.claim(
                ticket,
                manifest=manifest,
                manifest_sha256="0" * 64,
            )
        self.assertFalse(self.slot_registry.exists())

    def test_claim_wait_constant_drives_cli_action_and_virtual_long_queue(self) -> None:
        self.assertEqual(control.CLAIM_WAIT_SECONDS, 600)
        args = control.build_parser().parse_args(
            [
                "claim",
                "--state",
                "/tmp/state.json",
                "--ticket",
                "/tmp/ticket.json",
                "--manifest",
                "/tmp/manifest.json",
                "--manifest-sha256",
                "0" * 64,
                "--capacity",
                "5",
            ]
        )
        self.assertEqual(args.wait_seconds, control.CLAIM_WAIT_SECONDS)

        manifest = self.prepare()
        action = control.render_action(manifest)
        self.assertIn(
            f"--wait-seconds {control.CLAIM_WAIT_SECONDS}", action
        )
        self.assertNotIn("--wait-seconds 300", action)

        ticket = Path(
            next(item["ticket_path"] for item in manifest["seats"] if item["style"] == "A")
        )
        virtual_now = [0.0]

        def acquire_after_450_seconds(
            _state_path, _state, tasks, *, timestamp, capacity_limit=None
        ):
            del timestamp, capacity_limit
            if virtual_now[0] <= 300:
                return [], tasks, {}, 0
            task = tasks[0]
            key = (
                f"{task['style']}/{task['page_id']}/{task['action']}/"
                f"{int(task.get('attempt') or 1)}"
            )
            return tasks, [], {key: "virtual-lease-after-450-seconds"}, 0

        def advance_without_real_wait(_seconds: float) -> None:
            virtual_now[0] = 450.0

        with (
            mock.patch.object(control.time, "monotonic", side_effect=lambda: virtual_now[0]),
            mock.patch.object(control.time, "sleep", side_effect=advance_without_real_wait),
            mock.patch.object(
                control.pc,
                "acquire_fast8_global_imagegen_slots",
                side_effect=acquire_after_450_seconds,
            ),
        ):
            result = self.claim(
                ticket,
                control.CLAIM_WAIT_SECONDS,
                manifest=manifest,
            )
        self.assertGreater(virtual_now[0], 300)
        self.assertLessEqual(virtual_now[0], control.CLAIM_WAIT_SECONDS)
        self.assertEqual(result["status"], "claimed")

    def test_one_backend_failure_does_not_cancel_seven_successes(self) -> None:
        self.prepare()
        for style in "ABCDEFG":
            self.claim_and_receipt(style)
        self.claim_and_receipt("H", failed=True)
        result = control.settle(self.fixture.state_path)
        state = pipeline.read_json(self.fixture.state_path)
        successes = [
            style
            for style in "ABCDEFG"
            if pipeline.page_record(state, style, "02").get("selected_source")
        ]
        self.assertEqual(successes, list("ABCDEFG"))
        self.assertEqual(result["session_forensics_required_styles"], [])
        retries = (state.get("scheduler") or {}).get("ready_queue") or []
        self.assertEqual([item["style"] for item in retries], ["H"])

    def test_session_forensics_is_requested_only_for_completed_missing_saved_path(self) -> None:
        self.prepare()
        for style in "ABCDEFG":
            self.claim_and_receipt(style)
        self.claim_and_receipt("H", missing=True)
        result = control.settle(self.fixture.state_path)
        self.assertEqual(result["session_forensics_required_styles"], ["H"])
        self.assertFalse(result["normal_path_session_scan_used"])
        state = pipeline.read_json(self.fixture.state_path)
        self.assertTrue(pipeline.page_record(state, "A", "02").get("selected_source"))

    def test_rendered_stub_action_calls_eight_once_uses_allsettled_and_peaks_at_five(self) -> None:
        manifest = self.prepare()
        action = control.render_action(manifest)
        self.assertTrue(action.startswith("(async () => {"))
        self.assertTrue(action.rstrip().endswith("})()"))
        self.assertIn("Promise.allSettled", action)
        self.assertIn(f"--wait-seconds {control.CLAIM_WAIT_SECONDS}", action)
        self.assertNotIn("--wait-seconds 300", action)
        # The action itself must be one Promise expression.  Reintroducing an
        # await before the IIFE would recreate the production parse failure.
        self.assertNotIn("await", action[: action.index("(async () => {")])
        harness = f"""
let active=0, peak=0, calls=0, released=new Set(), waiting=[], claimCommands=[];
let sessionUsed=false, writeStdinCalls=0, sessionStyle=null;
const take=()=>{{active++;peak=Math.max(peak,active)}};
const wake=()=>{{ if(active<5 && waiting.length) waiting.shift()(); }};
globalThis.tools={{
  exec_command: async (req)=>{{
    const cmd=req.cmd;
    const style=((cmd.match(/ticket_([A-H])_page_/)||[])[1])||"?";
    if(cmd.includes(" claim ")){{
      claimCommands.push(cmd);
      if(active>=5) await new Promise(resolve=>waiting.push(()=>{{take();resolve()}}));
      else take();
      if(style==="A" && !sessionUsed){{sessionUsed=true;sessionStyle=style;return {{session_id:77,output:""}};}}
      return {{exit_code:0,output:JSON.stringify({{status:"claimed",style}})}};
    }}
    if(cmd.includes(" release ")){{ if(!released.has(style)){{released.add(style);active--;wake();}} return {{exit_code:0,output:'{{"status":"released"}}'}}; }}
    if(cmd.includes(" receipt ")) return {{exit_code:0,output:JSON.stringify({{style,tool_status:cmd.includes(" failed ")?"failed":"completed"}})}};
    if(cmd.includes(" settle ")) return {{exit_code:0,output:'{{"all_anchor_tools_completed":false}}'}};
    return {{exit_code:0,output:'{{}}'}};
  }},
  write_stdin: async (req)=>{{writeStdinCalls++;return {{exit_code:0,output:JSON.stringify({{status:"claimed",style:sessionStyle}})}};}},
  image_gen__imagegen: async ()=>{{
    calls++;
    const n=calls;
    await new Promise(resolve=>setTimeout(resolve,5));
    if(n===4) throw new Error("stub one-seat failure");
    return {{output_hint:`/tmp/exec-00000000-0000-4000-8000-${{String(n).padStart(12,"0")}}.png`}};
  }}
}};
globalThis.generatedImage=()=>{{}};
let finalText=""; globalThis.text=(v)=>{{finalText=String(v)}};
const action={json.dumps(action)};
(async()=>{{
await eval(action);
process.stdout.write(JSON.stringify({{active,peak,calls,writeStdinCalls,claimCommands,finalText}}));
}})().catch(e=>{{console.error(e);process.exit(1)}});
"""
        with tempfile.TemporaryDirectory(prefix="fast8_node_stub_") as tmp:
            path = Path(tmp) / "stub.mjs"
            path.write_text(harness, encoding="utf-8")
            run = subprocess.run([str(NODE), str(path)], text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["calls"], 8)
        self.assertEqual(result["writeStdinCalls"], 1)
        self.assertLessEqual(result["peak"], 5)
        self.assertEqual(len(result["claimCommands"]), 8)
        self.assertTrue(all("--capacity 5" in cmd for cmd in result["claimCommands"]))
        self.assertTrue(
            all(
                f"--manifest-sha256 {manifest['manifest_sha256']}" in cmd
                for cmd in result["claimCommands"]
            )
        )
        statuses = [item["status"] for item in json.loads(result["finalText"])["results"]]
        self.assertEqual(statuses.count("fulfilled"), 7)
        self.assertEqual(statuses.count("rejected"), 1)
        self.assertEqual(result["active"], 0)

    def test_child_runner_uses_canonical_wrapper_without_changing_locked_jobs(self) -> None:
        prompt = BURST_WRAPPER_PATH.read_text(encoding="utf-8")
        preparation = (ROOT / "references" / "Fast8准备与派发.md").read_text(
            encoding="utf-8"
        )
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("图片执行子 Agent 只是固定机械 wrapper 的承载者", prompt)
        self.assertIn("图片执行子 Agent", preparation)
        self.assertIn("不创建八个逐图 LLM Worker", preparation)
        self.assertIn("不再创建八个 LLM 图片 Worker", skill)

        wrapper = prompt.split("```javascript\n", 1)[1].split("\n```", 1)[0]
        wrapper = wrapper.replace("<绝对 state>", str(self.fixture.state_path.resolve()))
        wrapper = wrapper.replace("<skill_root>", str(ROOT))
        harness = f"""
let request=null, writeStdinCalls=0, finalText="";
globalThis.tools={{
  exec_command: async (req)=>{{
    request=req;
    return {{exit_code:0,output:'text("root-direct-ok");'}};
  }},
  write_stdin: async ()=>{{writeStdinCalls++;throw new Error("unexpected session");}},
}};
globalThis.text=(value)=>{{finalText=String(value)}};
{wrapper}
process.stdout.write(JSON.stringify({{request,writeStdinCalls,finalText}}));
"""
        with tempfile.TemporaryDirectory(prefix="fast8_root_wrapper_stub_") as tmp:
            path = Path(tmp) / "stub.mjs"
            path.write_text(harness, encoding="utf-8")
            run = subprocess.run(
                [str(NODE), str(path)], text=True, capture_output=True, timeout=30
            )
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertIn(" prepare ", result["request"]["cmd"])
        self.assertIn(" --render-action", result["request"]["cmd"])
        self.assertEqual(result["request"]["workdir"], str(ROOT))
        self.assertEqual(result["writeStdinCalls"], 0)
        self.assertEqual(result["finalText"], "root-direct-ok")

    def test_post_imagegen_receipt_failure_routes_to_forensics_without_regeneration(self) -> None:
        manifest = self.prepare()
        action = control.render_action(manifest)
        prompt_to_style = {
            item["imagegen_prompt"]: item["style"] for item in manifest["seats"]
        }
        harness = f"""
let calls={{}}, firstReceiptFailure=true, commands=[];
const promptToStyle={json.dumps(prompt_to_style, ensure_ascii=False)};
globalThis.tools={{
  exec_command: async (req)=>{{
    const cmd=req.cmd; commands.push(cmd);
    const style=((cmd.match(/ticket_([A-H])_page_/)||[])[1])||"?";
    if(cmd.includes(" claim ")) return {{exit_code:0,output:JSON.stringify({{status:"claimed",style}})}};
    if(cmd.includes(" receipt ")){{
      if(style==="D" && cmd.includes("--saved-path") && firstReceiptFailure){{firstReceiptFailure=false;return {{exit_code:1,output:"stub receipt path validation failed"}};}}
      const missing=!cmd.includes("--saved-path");
      return {{exit_code:0,output:JSON.stringify({{style,tool_status:"completed",failure_class:missing?"artifact_missing":null,savedPath:missing?null:"ok"}})}};
    }}
    if(cmd.includes(" release ")) return {{exit_code:0,output:'{{"status":"released"}}'}};
    if(cmd.includes(" settle ")) return {{exit_code:0,output:'{{"all_anchor_tools_completed":false,"session_forensics_required_styles":["D"]}}'}};
    return {{exit_code:0,output:'{{}}'}};
  }},
  write_stdin: async ()=>{{throw new Error("unexpected session")}},
  image_gen__imagegen: async (input)=>{{
    const style=promptToStyle[input.prompt]; calls[style]=(calls[style]||0)+1;
    const n=style.charCodeAt(0)-64;
    return {{output_hint:`/tmp/exec-00000000-0000-4000-8000-${{String(n).padStart(12,"0")}}.png`}};
  }}
}};
globalThis.generatedImage=()=>{{}};
let finalText=""; globalThis.text=(v)=>{{finalText=String(v)}};
const action={json.dumps(action)};
(async()=>{{
await eval(action);
process.stdout.write(JSON.stringify({{calls,commands,finalText}}));
}})().catch(e=>{{console.error(e);process.exit(1)}});
"""
        with tempfile.TemporaryDirectory(prefix="fast8_post_rpc_stub_") as tmp:
            path = Path(tmp) / "stub.mjs"
            path.write_text(harness, encoding="utf-8")
            run = subprocess.run([str(NODE), str(path)], text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["calls"], {style: 1 for style in control.STYLES})
        d_receipts = [
            cmd
            for cmd in result["commands"]
            if " receipt " in cmd and "ticket_D_page_" in cmd
        ]
        self.assertEqual(len(d_receipts), 2)
        self.assertIn("--saved-path", d_receipts[0])
        self.assertNotIn("--saved-path", d_receipts[1])
        self.assertNotIn("--tool-status failed", "\n".join(d_receipts))
        final = json.loads(result["finalText"])
        self.assertEqual(final["settled"]["session_forensics_required_styles"], ["D"])

    def test_backend_failure_recompiles_only_incremented_technical_retry(self) -> None:
        self.prepare()
        claims_per_style = {style: 0 for style in control.STYLES}
        for style in "ABCDEFG":
            self.claim_and_receipt(style)
            claims_per_style[style] += 1
        self.claim_and_receipt("H", failed=True)
        claims_per_style["H"] += 1
        first = control.settle(self.fixture.state_path)
        self.assertEqual(first["retry_pending_styles"], ["H"])

        retry_manifest = control.build_manifest(
            self.fixture.state_path.resolve(), dispatch=True
        )
        self.assertEqual([item["style"] for item in retry_manifest["seats"]], ["H"])
        self.assertEqual(retry_manifest["seats"][0]["attempt"], 2)
        self.assertTrue(
            retry_manifest["manifest_path"].endswith(
                "fast8_burst_manifest_v1_technical_retry_H2.json"
            )
        )
        retry_ticket = Path(retry_manifest["seats"][0]["ticket_path"])
        claim = self.claim(retry_ticket, manifest=retry_manifest)
        self.assertEqual(claim["status"], "claimed")
        claims_per_style["H"] += 1
        path, tool_id = self.artifact("H")
        now = control.pc.now_iso()
        control.write_receipt(
            self.fixture.state_path,
            retry_ticket,
            tool_status="completed",
            saved_path=str(path),
            tool_call_id=tool_id,
            tool_started_at=now,
            tool_finished_at=control.pc.now_iso(),
            failure_class=None,
            tool_error_code=None,
        )
        second = control.settle(self.fixture.state_path)
        self.assertTrue(second["all_anchor_tools_completed"])
        state = pipeline.read_json(self.fixture.state_path)
        self.assertEqual(
            [
                style
                for style in control.STYLES
                if pipeline.page_record(state, style, "02").get("selected_source")
            ],
            list(control.STYLES),
        )
        self.assertEqual(claims_per_style, {**{style: 1 for style in "ABCDEFG"}, "H": 2})
        for style in "ABCDEFG":
            self.assertEqual(
                pipeline.page_record(state, style, "02")["attempt_count"], 1
            )
        self.assertEqual(pipeline.page_record(state, "H", "02")["attempt_count"], 2)

    def test_existing_judge_pass_then_lean_finalize_produces_strict_two_lines(self) -> None:
        self.settle_all_success()
        job_path, _output = self.fixture.make_review()
        report = self.fixture.write_report(job_path, decision="pass")
        self.fixture.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.fixture.root),
            state=str(self.fixture.state_path),
            review_job=str(job_path),
            report_file=str(report),
            timestamp="2026-08-05T10:05:00+08:00",
        )
        result = control.lean_finalize(self.fixture.state_path)
        lines = result["delivery_text"].splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].count("]("), 1)
        self.assertEqual(lines[1].count("]("), 8)
        state = pipeline.read_json(self.fixture.state_path)
        self.assertEqual(state["fast8_control_plane"]["post_delivery_audit_status"], "pending")
        post = control.post_delivery(self.fixture.state_path)
        self.assertTrue(Path(post["report_path"]).is_file())
        self.assertTrue(Path(result["delivery_message"]).is_file())
        self.assertIn(post["status"], {"ok", "attention"})

    def test_await_close_can_start_before_judge_job_and_finalize_when_report_arrives(self) -> None:
        self.settle_all_success()
        result_box: dict[str, dict] = {}
        error_box: dict[str, BaseException] = {}
        watcher_started = threading.Event()

        def watch() -> None:
            watcher_started.set()
            try:
                result_box["result"] = control.await_close(
                    self.fixture.state_path.resolve(), 20, 0.01
                )
            except BaseException as exc:  # pragma: no cover - surfaced below
                error_box["error"] = exc

        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        self.assertTrue(watcher_started.wait(1))
        time.sleep(0.05)
        self.assertTrue(thread.is_alive())
        self.assertFalse((self.fixture.root / "state" / "delivery_message.md").exists())

        job_path, _output = self.fixture.make_review()
        job = pipeline.read_json(job_path)
        report_stem = Path(job["report_output_path"]).stem
        self.fixture.write_report(job_path, decision="pass", suffix=report_stem)
        thread.join(20)

        self.assertFalse(thread.is_alive())
        if error_box:
            raise error_box["error"]
        result = result_box["result"]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["delivery_text"].splitlines()), 2)
        state = pipeline.read_json(self.fixture.state_path)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["diversity_review"]["status"], "pass")

    def test_await_close_waits_through_partial_report_then_completes(self) -> None:
        self.settle_all_success()
        job_path, _output = self.fixture.make_review()
        job = pipeline.read_json(job_path)
        report_path = Path(job["report_output_path"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes(b"")
        result_box: dict[str, dict] = {}
        error_box: dict[str, BaseException] = {}

        def watch() -> None:
            try:
                result_box["result"] = control.await_close(
                    self.fixture.state_path.resolve(), 20, 0.01
                )
            except BaseException as exc:  # pragma: no cover - surfaced below
                error_box["error"] = exc

        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        time.sleep(0.05)
        self.assertTrue(thread.is_alive())
        report_path.write_bytes(b"\xff")
        time.sleep(0.05)
        self.assertTrue(thread.is_alive())
        report_path.write_text('{"decision":', encoding="utf-8")
        time.sleep(0.05)
        self.assertTrue(thread.is_alive())
        self.fixture.write_report(job_path, decision="pass", suffix=report_path.stem)
        thread.join(20)

        self.assertFalse(thread.is_alive())
        if error_box:
            raise error_box["error"]
        self.assertEqual(result_box["result"]["status"], "completed")

    def test_await_close_returns_waiting_when_report_stays_truncated(self) -> None:
        self.settle_all_success()
        job_path, _output = self.fixture.make_review()
        job = pipeline.read_json(job_path)
        report_path = Path(job["report_output_path"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('{"decision":', encoding="utf-8")

        result = control.await_close(self.fixture.state_path.resolve(), 0.05, 0.01)

        self.assertEqual(result, {"status": "waiting_for_judge_report"})

    def test_await_close_does_not_hide_parseable_invalid_report(self) -> None:
        self.settle_all_success()
        job_path, _output = self.fixture.make_review()
        job = pipeline.read_json(job_path)
        report_path = self.fixture.write_report(
            job_path,
            decision="pass",
            suffix=Path(job["report_output_path"]).stem,
        )
        report = pipeline.read_json(report_path)
        report["diversity_judge_contract_version"] = 999
        write_json(report_path, report)

        with self.assertRaisesRegex(SystemExit, "差异检查报告合同版本无效"):
            control.await_close(self.fixture.state_path.resolve(), 20, 0.01)

    def test_existing_judge_bounded_replacement_stays_at_two(self) -> None:
        self.settle_all_success()
        job_path, _output = self.fixture.make_review()
        report = self.fixture.write_report(
            job_path,
            decision="replace",
            replacements=["A", "B"],
            briefs={"A": "改用新的主导阅读入口", "B": "改用新的空间关系骨架"},
        )
        _unused, applied = self.fixture.call(
            pipeline.command_apply_fast8_diversity_report,
            project_dir=str(self.fixture.root),
            state=str(self.fixture.state_path),
            review_job=str(job_path),
            report_file=str(report),
            timestamp="2026-08-05T10:05:00+08:00",
        )
        self.assertEqual(applied["decision"], "replace")
        state = pipeline.read_json(self.fixture.state_path)
        self.assertEqual(state["diversity_review"]["replacement_count"], 2)
        self.assertEqual(
            sorted(item["style"] for item in state["scheduler"]["ready_queue"]),
            ["A", "B"],
        )
        replacement_manifest = control.build_manifest(
            self.fixture.state_path.resolve(), dispatch=True
        )
        self.assertEqual(
            [item["style"] for item in replacement_manifest["seats"]], ["A", "B"]
        )
        self.assertTrue(
            replacement_manifest["manifest_path"].endswith(
                "fast8_burst_manifest_v1_replacement_AB.json"
            )
        )

    def test_p31_quality_baseline_remains_byte_identical(self) -> None:
        baseline_value = os.environ.get("SHAWN_PPT_FAST8_BASELINE")
        if not baseline_value:
            self.skipTest("SHAWN_PPT_FAST8_BASELINE is not configured")
        baseline = Path(baseline_value).expanduser().resolve()
        result = control.verify_baseline(baseline)
        self.assertEqual(result, {"status": "pass", "mismatches": []})


if __name__ == "__main__":
    unittest.main()
