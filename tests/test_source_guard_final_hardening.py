from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline = load_module(
    "pipeline_control_final_hardening", ROOT / "scripts" / "pipeline_control.py"
)
init_task = load_module(
    "init_task_final_hardening", ROOT / "scripts" / "init_task_dir.py"
)
regression_tests = load_module(
    "source_guard_regression_fixtures",
    ROOT / "tests" / "test_source_guard_regressions.py",
)
handoff_tests = load_module(
    "handoff_source_drift_fixtures",
    ROOT / "tests" / "test_handoff_source_drift.py",
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def file_input_record(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "sha256": pipeline.file_sha256(path),
    }


def minimal_content_contract(page_id: str) -> dict[str, object]:
    return {
        "content_contract_version": 2,
        "prompt_contract_version": 4,
        "language": "en-US",
        "page_id": page_id,
        "title": f"Page {page_id}",
        "core_claim": f"Page {page_id} remains bound.",
        "source_facts": [f"Synthetic fact for {page_id}"],
        "display_required": [f"Page {page_id}"],
        "display_flexible": [],
        "display_supporting": [],
        "semantic_invariants": [],
        "forbidden_interpretations": [],
        "prompt_semantic_guardrails": [],
        "prompt_user_constraints": [],
        "information_density_target": "low",
        "content_load_review": {
            "semantic_structure": "single proposition",
            "focus_relationship": "one claim",
            "attention_risks": [],
            "edge_and_takeaway_risks": [],
            "duplication_risks": [],
            "reason": "fixture is feasible",
        },
        "content_resolution": {
            "status": "not_needed",
            "choice": None,
            "moved_items": [],
            "reason": None,
        },
        "spatial_pressure_profile": "low",
        "spatial_generation_brief": pipeline.QUICK8_BREATHING_PROMPT_CUES[
            "en"
        ]["low"],
        "spatial_qa_contract": "Low-pressure QA applies.",
        "low_pressure_feasibility": "pass",
        "visual_support_goal": "Support the claim.",
    }


def formal_job(
    *,
    project_dir: Path,
    contract_path: Path,
    style: str,
    page_id: str,
    action: str,
    attempt: int,
    actual_inputs: list[Path],
    reference_images: list[Path] | None = None,
    required_assets: list[Path] | None = None,
    required_page_assets: list[Path] | None = None,
) -> dict[str, object]:
    prompt = f"Fixture {action} attempt {attempt}."
    manifest = [file_input_record(path) for path in actual_inputs]
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
        "anchor_page_id": page_id,
        "action": action,
        "attempt": attempt,
        "source_content_contract_path": str(contract_path.resolve()),
        "source_content_contract_sha256": pipeline.file_sha256(contract_path),
        "output_target": str(
            pipeline.origin_image_target(project_dir, style, page_id).resolve()
        ),
        "reference_images": [
            str(path.resolve()) for path in (reference_images or [])
        ],
        "required_assets": [
            str(path.resolve()) for path in (required_assets or [])
        ],
        "required_page_assets": [
            str(path.resolve()) for path in (required_page_assets or [])
        ],
        "imagegen_prompt": prompt,
        "imagegen_referenced_paths": [
            str(path.resolve()) for path in actual_inputs
        ],
        "imagegen_input_manifest": manifest,
        "imagegen_input_fingerprint": fingerprint,
    }


class SourceGuardFinalHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="source_guard_hardening_")
        self.root = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_selected_expansion_fixture(
        self, *, include_required_logo: bool = False
    ) -> dict[str, Path]:
        project = self.root / "selected_expansion"
        init_task.create_standard_dirs(project)
        init_task.write_task_init_contract(project)
        state_path = project / "state" / "selected_style_run_state.json"
        source_path = project / "source" / "outline.md"
        contract_path = project / "content_contracts" / "page_08.json"
        anchor_path = project / "references" / "style_anchor.bin"
        logo_path = project / "references" / "required_logo.bin"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("## P08\nStable expansion content\n", encoding="utf-8")
        contract = minimal_content_contract("08")
        if include_required_logo:
            contract["required_page_assets"] = [
                {"path": str(logo_path.resolve()), "role": "official_logo"}
            ]
        write_json(contract_path, contract)
        anchor_path.parent.mkdir(parents=True, exist_ok=True)
        anchor_path.write_bytes(b"STYLE-ANCHOR")
        logo_path.write_bytes(b"REQUIRED-LOGO")
        write_json(
            state_path,
            {
                "run_id": "selected-expansion-hardening",
                "project_dir": str(project.resolve()),
                "run_mode": "selected_style_expansion",
                "phase": "selected_style_expansion",
                "selected_style": "A",
                "state_audit_contract_version": 2,
                "page_order": ["08"],
                "pages": {"08": {"status": "pending", "attempt_count": 0}},
                "scheduler": {
                    "phase": "generation",
                    "active_actions": [],
                    "ready_queue": [],
                    "recovery_queue": [],
                },
                "events": [],
                "timing": {},
            },
        )
        assets: list[dict[str, object]] = [
            {
                "path": str(anchor_path.resolve()),
                "asset_type": "reference_image",
                "role": "style_anchor",
                "styles": ["A"],
            }
        ]
        if include_required_logo:
            assets.append(
                {
                    "path": str(logo_path.resolve()),
                    "asset_type": "required_page_asset",
                    "role": "official_logo",
                    "styles": ["A"],
                }
            )
        baseline_job_path = project / "page_jobs" / "page_08.json"
        baseline_inputs = [anchor_path, *([logo_path] if include_required_logo else [])]
        write_json(
            baseline_job_path,
            formal_job(
                project_dir=project,
                contract_path=contract_path,
                style="A",
                page_id="08",
                action="generate_page",
                attempt=1,
                actual_inputs=baseline_inputs,
                reference_images=[anchor_path],
                required_page_assets=[logo_path] if include_required_logo else [],
            ),
        )
        pipeline.create_source_snapshot(
            project_dir=project,
            state_path=state_path,
            source_path=source_path,
            page_ids=["08"],
            content_contract_paths=[contract_path],
            asset_items=assets,
        )
        return {
            "project": project,
            "state": state_path,
            "contract": contract_path,
            "anchor": anchor_path,
            "logo": logo_path,
        }

    def record_selected_start(
        self,
        fixture: dict[str, Path],
        *,
        action: str,
        attempt: int,
        job_path: Path,
    ) -> None:
        with redirect_stdout(io.StringIO()):
            pipeline.command_record_event(
                argparse.Namespace(
                    state=str(fixture["state"]),
                    event="agent_action_started",
                    style=None,
                    page_id="08",
                    action=action,
                    timestamp="2099-01-01T00:01:00+08:00",
                    details_json=json.dumps(
                        {
                            "attempt": attempt,
                            "generation_job_path": str(job_path.resolve()),
                        }
                    ),
                )
            )

    def test_worker_templates_require_the_exact_formal_generation_job_path(self) -> None:
        for relative in ("prompts/style-worker.md", "prompts/style-follower-worker.md"):
            with self.subTest(template=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("generation_job_path", text)

    def test_fast_repair_queue_binds_the_formal_job_path(self) -> None:
        fixture = regression_tests.SourceGuardRegressionTests(methodName="runTest")
        fixture.setUp()
        try:
            project = fixture.prepare_project(
                "repair_job_binding", regression_tests.pipeline.FAST_4X3_MODE
            )
            root = project["root"]
            state_path = project["state"]
            candidate = root / "origin_image" / "style_A_page_02.png"
            regression_tests.write_png_stub(candidate, tag=b"candidate")
            state = regression_tests.pipeline.read_json(state_path)
            state["styles"]["A"]["pages"]["02"].update(
                {
                    "status": "candidate_ready",
                    "tool_call_id": "tool-A",
                    "selected_source": str(candidate.resolve()),
                    "source_sha256": regression_tests.pipeline.file_sha256(candidate),
                    "attempt_count": 1,
                    "attempt_sources": [str(candidate.resolve())],
                    "file_validated_at": "2099-01-01T00:00:30+08:00",
                }
            )
            state["scheduler"]["ready_queue"] = []
            state["scheduler"]["active_actions"] = []
            state["scheduler"]["recovery_queue"] = []
            write_json(state_path, state)

            fixture.call(
                regression_tests.pipeline.command_prepare_fast_anchor_repairs,
                project_dir=str(root),
                state=str(state_path),
                styles="A",
                issues_json=json.dumps({"A": "Fix the observable issue."}),
            )

            queued = regression_tests.pipeline.read_json(state_path)["scheduler"][
                "ready_queue"
            ][0]
            self.assertIn("generation_job_path", queued)
            self.assertTrue(Path(queued["generation_job_path"]).is_file())
        finally:
            fixture.tearDown()

    def test_selected_expansion_repair_job_attempt_must_match_event_attempt(self) -> None:
        fixture = self.make_selected_expansion_fixture()
        candidate = fixture["project"] / "origin_image" / "style_A_page_08.png"
        candidate.write_bytes(b"CURRENT-CANDIDATE")
        state = pipeline.read_json(fixture["state"])
        state["pages"]["08"].update(
            {
                "status": "generated",
                "attempt_count": 2,
                "selected_source": str(candidate.resolve()),
                "source_sha256": pipeline.file_sha256(candidate),
            }
        )
        write_json(fixture["state"], state)
        job_path = (
            fixture["project"]
            / "page_jobs"
            / "repair_jobs"
            / "page_08_attempt_2.json"
        )
        write_json(
            job_path,
            formal_job(
                project_dir=fixture["project"],
                contract_path=fixture["contract"],
                style="A",
                page_id="08",
                action="repair_page",
                attempt=2,
                actual_inputs=[fixture["anchor"], candidate],
                reference_images=[fixture["anchor"], candidate],
            ),
        )
        before = fixture["state"].read_bytes()

        with self.assertRaises(SystemExit):
            self.record_selected_start(
                fixture, action="repair_page", attempt=3, job_path=job_path
            )

        self.assertEqual(fixture["state"].read_bytes(), before)

    def test_generation_job_rejects_reordered_or_duplicate_attachments(self) -> None:
        project = self.root / "attachment_order"
        contract_path = project / "content_contracts" / "page_02.json"
        reference = project / "references" / "reference.bin"
        logo = project / "references" / "logo.bin"
        write_json(contract_path, {"page_id": "02"})
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_bytes(b"REFERENCE")
        logo.write_bytes(b"LOGO")
        cases = {
            "reordered": [logo, reference],
            "duplicate": [reference, reference, logo],
        }
        for name, actual_inputs in cases.items():
            with self.subTest(case=name):
                job_path = project / "style_jobs" / f"{name}.json"
                write_json(
                    job_path,
                    formal_job(
                        project_dir=project,
                        contract_path=contract_path,
                        style="A",
                        page_id="02",
                        action="generate_anchor",
                        attempt=1,
                        actual_inputs=actual_inputs,
                        reference_images=[reference],
                        required_assets=[logo],
                    ),
                )
                with self.assertRaises(SystemExit):
                    pipeline.validate_generation_job_inputs(
                        job_path,
                        internal_sources=set(),
                        expected_task={
                            "style": "A",
                            "page_id": "02",
                            "action": "generate_anchor",
                            "attempt": 1,
                        },
                        state={},
                        project_dir=project,
                    )

    def test_caller_boolean_cannot_authorize_a_technical_retry(self) -> None:
        state_path = self.root / "legacy" / "state" / "style_run_state.json"
        record = pipeline.initial_page_state("anchor", "2099-01-01T00:00:00+08:00")
        active_recovery = {
            "style": "A",
            "page_id": "02",
            "action": "recover_artifact",
            "source_action": "generate_anchor",
            "attempt": 1,
            "tool_call_id": "tool-A",
        }
        state = {
            "run_mode": pipeline.QUICK_8X1_MODE,
            "anchor_page_id": "02",
            "styles": {"A": {"pages": {"02": record}}},
            "scheduler": {
                "active_actions": [dict(active_recovery)],
                "ready_queue": [],
                "recovery_queue": [],
            },
            "events": [],
        }

        result = pipeline._transition_unsuccessful_recovery(
            state_path,
            state,
            "A",
            "02",
            "2099-01-01T00:01:00+08:00",
            {
                "recovery_status": "failed",
                "recovery_method": "same_worker",
                "technical_retry_authorized": True,
            },
            active_recovery,
        )

        self.assertNotEqual(result["next_action"], "generate_anchor")
        self.assertFalse(
            any(
                item.get("action") == "generate_anchor"
                for item in state["scheduler"]["ready_queue"]
            )
        )

    def test_fast_repair_retry_updates_its_declared_attempt_limit(self) -> None:
        project = self.root / "fast_retry_limit"
        state_path = project / "state" / "style_run_state.json"
        write_json(
            state_path,
            {
                "run_id": "fast-retry-limit",
                "project_dir": str(project.resolve()),
                "run_mode": pipeline.FAST_4X3_MODE,
                "source_guard_contract_version": 1,
                "anchor_page_id": "02",
                "styles": {},
            },
        )
        source_job = (
            project
            / "style_jobs"
            / "repair_jobs"
            / "style_A_page_02_attempt_2_fast.json"
        )
        write_json(
            source_job,
            {
                "style_slot": "A",
                "page_id": "02",
                "action": "repair_anchor",
                "attempt": 2,
                "generation_rules": {"max_total_attempts_per_page": 2},
            },
        )

        retry_path = pipeline.clone_guarded_repair_job_for_technical_retry(
            state_path,
            pipeline.read_json(state_path),
            style="A",
            page_id="02",
            action="repair_anchor",
            source_attempt=2,
            next_attempt=3,
        )

        retry_job = pipeline.read_json(retry_path)
        self.assertGreaterEqual(
            retry_job["generation_rules"]["max_total_attempts_per_page"], 3
        )

    def test_follower_page_assets_are_filtered_by_style_and_tone(self) -> None:
        project = self.root / "follower_asset_routing"
        anchor = project / "origin_image" / "style_C_page_02.png"
        asset = project / "references" / "routed_logo.bin"
        anchor.parent.mkdir(parents=True, exist_ok=True)
        anchor.write_bytes(b"ANCHOR")
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"ROUTED-LOGO")
        style_contract = {
            "style_slot": "C",
            "tone": "light",
            "language": "en-US",
            "anchor": {"path": str(anchor.resolve())},
            "required_assets": [],
        }
        cases = {
            "other_style": {"path": str(asset.resolve()), "style_slots": ["A"]},
            "other_tone": {"path": str(asset.resolve()), "tones": ["dark"]},
        }
        for name, routed_asset in cases.items():
            with self.subTest(case=name):
                page_job = minimal_content_contract("05")
                page_job["required_page_assets"] = [routed_asset]
                bundle = pipeline.compile_follower_prompt_bundle_v4(
                    page_job, style_contract
                )
                self.assertNotIn(
                    str(asset.resolve()), bundle["imagegen_referenced_paths"]
                )

    def test_follower_does_not_inherit_anchor_page_evidence(self) -> None:
        project = self.root / "follower_anchor_evidence_scope"
        anchor = project / "origin_image" / "style_C_page_02.png"
        anchor_evidence = project / "references" / "anchor_evidence.bin"
        follower_evidence = project / "references" / "follower_evidence.bin"
        shared_logo = project / "references" / "shared_logo.bin"
        anchor.parent.mkdir(parents=True, exist_ok=True)
        anchor.write_bytes(b"ANCHOR")
        anchor_evidence.parent.mkdir(parents=True, exist_ok=True)
        anchor_evidence.write_bytes(b"ANCHOR-EVIDENCE")
        follower_evidence.write_bytes(b"FOLLOWER-EVIDENCE")
        shared_logo.write_bytes(b"SHARED-LOGO")
        style_contract = {
            "style_slot": "C",
            "tone": "light",
            "language": "en-US",
            "anchor": {"path": str(anchor.resolve())},
            "required_assets": [
                {
                    "path": str(anchor_evidence.resolve()),
                    "role": "required_source_evidence",
                },
                {"path": str(shared_logo.resolve()), "role": "brand_logo"},
            ],
        }
        page_job = minimal_content_contract("05")
        page_job["required_page_assets"] = [
            {
                "path": str(follower_evidence.resolve()),
                "role": "required_source_evidence",
            }
        ]
        bundle = pipeline.compile_follower_prompt_bundle_v4(page_job, style_contract)
        paths = bundle["imagegen_referenced_paths"]
        self.assertNotIn(str(anchor_evidence.resolve()), paths)
        self.assertIn(str(anchor.resolve()), paths)
        self.assertIn(str(shared_logo.resolve()), paths)
        self.assertIn(str(follower_evidence.resolve()), paths)

    def test_state_page_scope_change_is_detected_after_snapshot_sealing(self) -> None:
        project = self.root / "scope_binding"
        init_task.create_standard_dirs(project)
        init_task.write_task_init_contract(project)
        state_path = project / "state" / "style_run_state.json"
        source_path = project / "source.md"
        source_path.write_text(
            "## P02\nAnchor\n\n## P05\nFollower one\n\n## P08\nFollower two\n",
            encoding="utf-8",
        )
        contracts = []
        for page_id in ("02", "05", "08"):
            path = project / "content_contracts" / f"page_{page_id}.json"
            write_json(path, {"page_id": page_id})
            contracts.append(path)
        write_json(
            state_path,
            {
                "run_id": "scope-binding",
                "run_mode": pipeline.FAST_4X3_MODE,
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "styles": {},
                "events": [],
                "timing": {},
            },
        )
        pipeline.create_source_snapshot(
            project_dir=project,
            state_path=state_path,
            source_path=source_path,
            page_ids=["02", "05", "08"],
            content_contract_paths=contracts,
            asset_items=[],
        )
        state = pipeline.read_json(state_path)
        state["follower_page_ids"] = ["05", "05"]
        write_json(state_path, state)

        result = pipeline.evaluate_source_drift(state_path, action="resume")

        self.assertFalse(result["can_continue"])
        self.assertEqual(result["status"], "source_drift_detected")

    def test_selected_expansion_rejects_non_page_generation_actions(self) -> None:
        fixture = self.make_selected_expansion_fixture()
        job_path = fixture["project"] / "page_jobs" / "page_08.json"
        write_json(
            job_path,
            formal_job(
                project_dir=fixture["project"],
                contract_path=fixture["contract"],
                style="A",
                page_id="08",
                action="generate_anchor",
                attempt=1,
                actual_inputs=[fixture["anchor"]],
                reference_images=[fixture["anchor"]],
            ),
        )
        before = fixture["state"].read_bytes()

        with self.assertRaises(SystemExit):
            self.record_selected_start(
                fixture, action="generate_anchor", attempt=1, job_path=job_path
            )

        self.assertEqual(fixture["state"].read_bytes(), before)

    def test_selected_expansion_cannot_omit_a_required_page_asset(self) -> None:
        fixture = self.make_selected_expansion_fixture(include_required_logo=True)
        job_path = fixture["project"] / "page_jobs" / "page_08.json"
        job = formal_job(
            project_dir=fixture["project"],
            contract_path=fixture["contract"],
            style="A",
            page_id="08",
            action="generate_page",
            attempt=1,
            actual_inputs=[fixture["anchor"]],
            reference_images=[fixture["anchor"]],
            required_page_assets=[fixture["logo"]],
        )
        write_json(job_path, job)
        before = fixture["state"].read_bytes()

        with self.assertRaises(SystemExit):
            self.record_selected_start(
                fixture, action="generate_page", attempt=1, job_path=job_path
            )

        self.assertEqual(fixture["state"].read_bytes(), before)

    def test_handoff_rejects_a_stale_drift_result(self) -> None:
        fixture = handoff_tests.HandoffAndSourceDriftTests(methodName="runTest")
        fixture.setUp()
        try:
            state = handoff_tests.pipeline.read_json(fixture.state_path)
            stale_result = handoff_tests.pipeline.evaluate_source_drift(
                fixture.state_path, state, action="candidate_delivery"
            )
            changed_contract = handoff_tests.pipeline.read_json(fixture.contract_path)
            changed_contract["display_required"] = ["Changed after drift check"]
            write_json(fixture.contract_path, changed_contract)

            with self.assertRaises(SystemExit):
                handoff_tests.pipeline.build_handoff_document(
                    project_dir=fixture.root,
                    state_path=fixture.state_path,
                    state=state,
                    drift_result=stale_result,
                )
        finally:
            fixture.tearDown()

    def test_legacy_generation_requires_an_explicit_compatibility_decision(self) -> None:
        project = self.root / "legacy_generation"
        init_task.create_standard_dirs(project)
        state_path = project / "state" / "style_run_state.json"
        task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
        }
        write_json(
            state_path,
            {
                "run_id": "legacy-generation",
                "run_mode": pipeline.QUICK_8X1_MODE,
                "anchor_page_id": "02",
                "styles": {
                    "A": {
                        "pages": {
                            "02": {"status": "pending", "attempt_count": 0}
                        }
                    }
                },
                "scheduler": {
                    "phase": "anchor_generation",
                    "active_child_limit": 8,
                    "active_actions": [],
                    "ready_queue": [task],
                    "recovery_queue": [],
                },
                "events": [],
                "timing": {},
            },
        )
        before = state_path.read_bytes()

        with self.assertRaisesRegex(SystemExit, "legacy_snapshot_missing"):
            with redirect_stdout(io.StringIO()):
                pipeline.command_record_dispatch_wave(
                    argparse.Namespace(
                        state=str(state_path),
                        tasks_json=json.dumps([task]),
                        styles=None,
                        page_id=None,
                        action="generate_anchor",
                        attempt=1,
                        timestamp="2099-01-01T00:01:00+08:00",
                        agent_map_json="{}",
                        backpressure_reason=None,
                    )
                )

        self.assertEqual(state_path.read_bytes(), before)

    def test_legacy_confirmation_is_a_bound_sidecar_and_preserves_old_state(self) -> None:
        project = self.root / "legacy_confirmed_generation"
        init_task.create_standard_dirs(project)
        state_path = project / "state" / "style_run_state.json"
        job_path = project / "style_jobs" / "style_A.json"
        task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
        }
        write_json(job_path, {"legacy_job_contract": True})
        write_json(
            state_path,
            {
                "run_id": "legacy-confirmed-generation",
                "project_dir": str(project.resolve()),
                "run_mode": pipeline.QUICK_8X1_MODE,
                "anchor_page_id": "02",
                "styles": {
                    "A": {
                        "pages": {
                            "02": {"status": "pending", "attempt_count": 0}
                        }
                    }
                },
                "scheduler": {
                    "phase": "anchor_generation",
                    "active_child_limit": 8,
                    "active_actions": [],
                    "ready_queue": [task],
                    "recovery_queue": [],
                },
                "events": [],
                "timing": {},
            },
        )
        old_state = state_path.read_bytes()
        with redirect_stdout(io.StringIO()):
            pipeline.command_confirm_legacy_source_risk(
                argparse.Namespace(
                    state=str(state_path),
                    actions="generation_dispatch",
                    timestamp="2099-01-01T00:00:30+08:00",
                    user_confirmed=True,
                    confirmed_by="fixture-user",
                    confirmation_text="Proceed with this legacy dispatch only.",
                )
            )
        self.assertEqual(state_path.read_bytes(), old_state)
        confirmation_path = project / "state" / "legacy_source_confirmation.json"
        self.assertTrue(confirmation_path.is_file())
        self.assertFalse((project / "state" / "source_snapshot.json").exists())

        with redirect_stdout(io.StringIO()):
            pipeline.command_record_dispatch_wave(
                argparse.Namespace(
                    state=str(state_path),
                    tasks_json=json.dumps([task]),
                    styles=None,
                    page_id=None,
                    action="generate_anchor",
                    attempt=1,
                    timestamp="2099-01-01T00:01:00+08:00",
                    agent_map_json="{}",
                    backpressure_reason=None,
                )
            )
        active = pipeline.read_json(state_path)["scheduler"]["active_actions"][0]
        self.assertEqual(active["generation_job_path"], str(job_path.resolve()))
        self.assertEqual(
            active["generation_job_sha256"], pipeline.file_sha256(job_path)
        )

    def test_state_injected_legacy_confirmation_cannot_authorize_dispatch(self) -> None:
        project = self.root / "legacy_injected_confirmation"
        init_task.create_standard_dirs(project)
        state_path = project / "state" / "style_run_state.json"
        task = {
            "style": "A",
            "page_id": "02",
            "action": "generate_anchor",
            "attempt": 1,
        }
        write_json(project / "style_jobs" / "style_A.json", {"legacy": True})
        write_json(
            state_path,
            {
                "run_id": "legacy-injected",
                "project_dir": str(project.resolve()),
                "run_mode": pipeline.QUICK_8X1_MODE,
                "anchor_page_id": "02",
                "legacy_source_confirmation": {
                    "confirmed": True,
                    "allowed_actions": ["generation_dispatch"],
                },
                "styles": {"A": {"pages": {"02": {"status": "pending"}}}},
                "scheduler": {
                    "active_actions": [],
                    "ready_queue": [task],
                    "recovery_queue": [],
                },
                "events": [],
            },
        )
        before = state_path.read_bytes()
        with self.assertRaisesRegex(SystemExit, "legacy_snapshot_missing"):
            with redirect_stdout(io.StringIO()):
                pipeline.command_record_dispatch_wave(
                    argparse.Namespace(
                        state=str(state_path),
                        tasks_json=json.dumps([task]),
                        styles=None,
                        page_id=None,
                        action="generate_anchor",
                        attempt=1,
                        timestamp="2099-01-01T00:01:00+08:00",
                        agent_map_json="{}",
                        backpressure_reason=None,
                    )
                )
        self.assertEqual(state_path.read_bytes(), before)

    def test_new_missing_snapshot_cannot_be_downgraded_to_legacy_confirmation(self) -> None:
        project = self.root / "new_missing_snapshot"
        init_task.create_standard_dirs(project)
        init_task.write_task_init_contract(project)
        state_path = project / "state" / "style_run_state.json"
        write_json(
            state_path,
            {
                "run_id": "new-missing-snapshot",
                "project_dir": str(project.resolve()),
                "run_mode": pipeline.QUICK_8X1_MODE,
                "anchor_page_id": "02",
            },
        )
        with self.assertRaisesRegex(SystemExit, "不适用 legacy"):
            with redirect_stdout(io.StringIO()):
                pipeline.command_confirm_legacy_source_risk(
                    argparse.Namespace(
                        state=str(state_path),
                        actions="generation_dispatch",
                        timestamp="2099-01-01T00:00:30+08:00",
                        user_confirmed=True,
                        confirmed_by=None,
                        confirmation_text=None,
                    )
                )


if __name__ == "__main__":
    unittest.main()
