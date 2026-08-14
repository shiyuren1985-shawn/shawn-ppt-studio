from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "scripts" / "pipeline_control.py"
INIT_TASK_PATH = ROOT / "scripts" / "init_task_dir.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline = load_module("pipeline_control_source_guard_regressions", PIPELINE_PATH)
init_task = load_module("init_task_source_guard_regressions", INIT_TASK_PATH)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_png_stub(
    path: Path,
    *,
    width: int = 1600,
    height: int = 900,
    tag: bytes = b"fixture",
) -> None:
    """Write the minimum header read by pipeline_control.png_metadata()."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + tag
    )


def content_contract(page_id: str) -> dict:
    return {
        "content_contract_version": 2,
        "prompt_contract_version": 4,
        "language": "en-US",
        "page_id": page_id,
        "title": f"Page {page_id}",
        "core_claim": f"Page {page_id} remains bound to its sealed source.",
        "source_facts": [f"Synthetic fact for page {page_id}"],
        "display_required": [f"Page {page_id}", "100% traceable"],
        "display_flexible": ["Supporting wording may be compressed."],
        "display_supporting": [],
        "semantic_invariants": ["100% must remain exact"],
        "forbidden_interpretations": [],
        "prompt_semantic_guardrails": ["Keep the page claim exact."],
        "prompt_user_constraints": [],
        "information_density_target": "low",
        "content_load_review": {
            "semantic_structure": "single proposition",
            "focus_relationship": "one claim supported by one fact",
            "attention_risks": [],
            "edge_and_takeaway_risks": [],
            "duplication_risks": [],
            "reason": "The fixture is feasible at low pressure.",
        },
        "content_resolution": {
            "status": "not_needed",
            "choice": None,
            "moved_items": [],
            "reason": None,
        },
        "spatial_pressure_profile": "low",
        "spatial_generation_brief": pipeline.QUICK8_BREATHING_PROMPT_CUES["en"][
            "low"
        ],
        "spatial_qa_contract": "Keep hierarchy and negative space readable.",
        "low_pressure_feasibility": "pass",
        "visual_support_goal": "Make the source binding easy to understand.",
    }


def layout_portfolio(mode: str) -> dict:
    if mode == pipeline.QUICK_8X1_MODE:
        styles = {
            "A": {"direction_id": "quick_a", "first_impression": "First see the core claim."},
            "B": {"direction_id": "quick_b", "first_impression": "First trust the evidence."},
            "C": {"direction_id": "quick_c", "first_impression": "First feel the contrast."},
            "D": {"direction_id": "quick_d", "first_impression": "First notice the progression."},
            "E": {"direction_id": "quick_e", "first_impression": "First understand the system."},
            "F": {"direction_id": "quick_f", "first_impression": "First sense the opportunity."},
            "G": {"direction_id": "quick_g"},
            "H": {"direction_id": "quick_h"},
        }
        version = 5
    else:
        styles = {
            "A": {"direction_id": "four_a", "first_impression": "First see the core value."},
            "B": {"direction_id": "four_b", "first_impression": "First trust the evidence chain."},
            "C": {"direction_id": "four_c"},
            "D": {"direction_id": "four_d"},
        }
        version = 6
    return {
        "layout_portfolio_contract_version": version,
        "page_id": "02",
        "director_rationale": "A compact synthetic portfolio exercises guarded dispatch.",
        "styles": styles,
    }


def formal_job(
    *,
    project_dir: Path,
    contract_path: Path,
    style: str,
    page_id: str,
    action: str,
    attempt: int,
    input_paths: list[Path],
) -> dict:
    prompt = f"Fixture {action} for style {style}, page {page_id}, attempt {attempt}."
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
        "anchor_page_id": page_id if action in {"generate_anchor", "repair_anchor"} else "02",
        "action": action,
        "attempt": attempt,
        "source_content_contract_path": str(contract_path.resolve()),
        "source_content_contract_sha256": pipeline.file_sha256(contract_path),
        "output_target": str(
            pipeline.origin_image_target(project_dir, style, page_id).resolve()
        ),
        "reference_images": referenced_paths,
        "required_assets": [],
        "imagegen_prompt": prompt,
        "imagegen_referenced_paths": referenced_paths,
        "imagegen_input_manifest": manifest,
        "imagegen_input_fingerprint": fingerprint,
    }


class SourceGuardRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shawn_source_guard_regressions_")
        self.base = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def call(self, function, **kwargs) -> dict:
        output = io.StringIO()
        with redirect_stdout(output):
            function(argparse.Namespace(**kwargs))
        return json.loads(output.getvalue())

    def prepare_project(self, name: str, mode: str) -> dict[str, Path]:
        root = (self.base / name).resolve()
        init_task.create_standard_dirs(root)
        init_task.write_task_init_contract(
            root, timestamp="2099-01-01T00:00:00+08:00"
        )
        state_path = root / "state" / "style_run_state.json"
        content_dir = root / "content_contracts"
        source_path = root / "source" / "outline.md"
        portfolio_path = root / "state" / "layout_portfolio.json"
        asset_path = root / "references" / "shared_asset.bin"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "# Fixture outline\n\n"
            "## P02\nSealed source for page 02.\n\n"
            "## P05\nSealed source for page 05.\n\n"
            "## P08\nSealed source for page 08.\n",
            encoding="utf-8",
        )
        for page_id in ("02", "05", "08"):
            write_json(content_dir / f"page_{page_id}.json", content_contract(page_id))
        write_json(portfolio_path, layout_portfolio(mode))
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(b"SHARED-ASSET")
        write_json(
            state_path,
            {
                "run_id": f"fixture-{name}",
                "run_mode": mode,
                "status": "running",
                "anchor_page_id": "02",
                "follower_page_ids": ["05", "08"],
                "deferred_pages": ["05", "08"],
                "preflight": {"status": "resolved"},
                "timing": {},
                "events": [],
                "scheduler": {"active_actions": [], "ready_queue": []},
            },
        )
        self.call(
            pipeline.command_prepare_anchors,
            project_dir=str(root),
            state=str(state_path),
            content_contract=str(content_dir / "page_02.json"),
            overall_requirements="Synthetic guarded dispatch fixture",
            reference_images_json="[]",
            required_assets_json=json.dumps([str(asset_path.resolve())]),
            layout_portfolio=str(portfolio_path),
            source_file=str(source_path),
            source_page_ids=None,
            source_fragment_file=None,
            snapshot_content_contracts_json=None,
            source_snapshot_timestamp="2099-01-01T00:00:00+08:00",
        )
        self.assertTrue((root / "state" / "source_snapshot.json").is_file())
        return {
            "root": root,
            "state": state_path,
            "content_dir": content_dir,
            "source": source_path,
            "asset": asset_path,
        }

    def dispatch(
        self,
        state_path: Path,
        tasks: list[dict],
        *,
        minute: int = 1,
        backpressure_reason: str | None = None,
    ) -> dict:
        agent_map = {
            f"{item['style']}/{item['page_id']}/{item['action']}/{item['attempt']}": (
                f"agent-{item['style']}-{item['page_id']}-{item['action']}"
            )
            for item in tasks
        }
        return self.call(
            pipeline.command_record_dispatch_wave,
            state=str(state_path),
            tasks_json=json.dumps(tasks),
            styles=None,
            page_id=None,
            action=tasks[0]["action"],
            attempt=tasks[0]["attempt"],
            timestamp=f"2099-01-01T00:{minute:02d}:00+08:00",
            agent_map_json=json.dumps(agent_map),
            backpressure_reason=backpressure_reason,
        )

    def install_follower_wave(self, project: dict[str, Path], page_id: str = "05") -> dict[str, Path]:
        root = project["root"]
        state_path = project["state"]
        state = pipeline.read_json(state_path)
        anchors: dict[str, Path] = {}
        tasks = []
        for style in pipeline.FULL_STYLES:
            anchor = root / "origin_image" / f"incumbent_anchor_{style}.png"
            write_png_stub(anchor, tag=f"anchor-{style}".encode("ascii"))
            anchors[style] = anchor
            anchor_record = state["styles"][style]["pages"]["02"]
            anchor_record.update(
                {
                    "status": "candidate_ready",
                    "tool_call_id": f"tool-anchor-{style}",
                    "selected_source": str(anchor.resolve()),
                    "source_sha256": pipeline.file_sha256(anchor),
                    "selected_attempt": 1,
                    "selected_action": "generate_anchor",
                    "attempt_count": 1,
                    "attempt_sources": [str(anchor.resolve())],
                    "file_validated_at": "2099-01-01T00:00:30+08:00",
                }
            )
            state["styles"][style]["pages"][page_id] = pipeline.initial_page_state(
                "follower", "2099-01-01T00:00:40+08:00"
            )
            task = {
                "style": style,
                "page_id": page_id,
                "action": "generate_follower",
                "attempt": 1,
            }
            tasks.append(task)
            job_path = (
                root / "style_page_jobs" / f"style_{style}" / f"page_{page_id}.json"
            )
            write_json(
                job_path,
                formal_job(
                    project_dir=root,
                    contract_path=project["content_dir"] / f"page_{page_id}.json",
                    style=style,
                    page_id=page_id,
                    action="generate_follower",
                    attempt=1,
                    input_paths=[anchor, project["asset"]],
                ),
            )
        state["scheduler"]["phase"] = "follower_generation"
        state["scheduler"]["active_actions"] = []
        state["scheduler"]["recovery_queue"] = []
        state["scheduler"]["ready_queue"] = tasks
        write_json(state_path, state)
        return anchors

    def incumbent_record(self, role: str, path: Path, action: str) -> dict:
        record = pipeline.initial_page_state(role, "2099-01-01T00:00:00+08:00")
        record.update(
            {
                "status": "accepted",
                "tool_call_id": f"old-tool-{path.stem}",
                "selected_source": str(path.resolve()),
                "source_size_bytes": path.stat().st_size,
                "source_sha256": pipeline.file_sha256(path),
                "selected_attempt": 1,
                "selected_action": action,
                "attempt_count": 1,
                "attempt_sources": [str(path.resolve())],
                "agent_action_started_at": "2099-01-01T00:01:00+08:00",
                "tool_started_at": "2099-01-01T00:01:10+08:00",
                "tool_finished_at": "2099-01-01T00:01:20+08:00",
                "file_validated_at": "2099-01-01T00:01:30+08:00",
                "agent_action_finished_at": "2099-01-01T00:01:40+08:00",
                "overview_qa_at": "2099-01-01T00:02:00+08:00",
                "completed_at": "2099-01-01T00:02:10+08:00",
                "final_path": str(path.resolve()),
                "qa_stage": "visual_worker",
                "qa_scope": "full_visual",
                "qa_note": "Incumbent QA note",
                "content_gate": {"status": "pass", "reason": "fixture"},
                "spatial_gate": {"status": "pass", "reason": "fixture"},
                "craft_gate": {"status": "pass", "reason": "fixture"},
                "failure_reason": "incumbent_failure_context",
            }
        )
        return record

    def run_strict_repair(
        self, *, action: str, page_id: str, recover: bool = False
    ) -> tuple[dict, Path, Path]:
        project = self.prepare_project(
            f"strict_{action}_{'recovery' if recover else 'direct'}",
            pipeline.STRICT_4X3_MODE,
        )
        root = project["root"]
        state_path = project["state"]
        state = pipeline.read_json(state_path)
        anchor = root / "origin_image" / "old_anchor_A.png"
        write_png_stub(anchor, tag=b"old-anchor")
        state["styles"]["A"]["pages"]["02"] = self.incumbent_record(
            "anchor", anchor, "generate_anchor"
        )
        incumbent = anchor
        input_paths = [anchor, project["asset"]]
        if action == "repair_page":
            incumbent = root / "origin_image" / "old_follower_A_05.png"
            write_png_stub(incumbent, tag=b"old-follower")
            state["styles"]["A"]["pages"][page_id] = self.incumbent_record(
                "follower", incumbent, "generate_follower"
            )
            input_paths = [incumbent, anchor, project["asset"]]
        task = {"style": "A", "page_id": page_id, "action": action, "attempt": 2}
        state["scheduler"]["phase"] = "repair_generation"
        state["scheduler"]["active_actions"] = []
        state["scheduler"]["recovery_queue"] = []
        state["scheduler"]["ready_queue"] = [task]
        write_json(state_path, state)
        if action == "repair_anchor":
            job_path = (
                root
                / "style_jobs"
                / "repair_jobs"
                / f"style_A_page_{page_id}_attempt_2.json"
            )
        else:
            job_path = (
                root
                / "style_page_jobs"
                / "style_A"
                / "repair_jobs"
                / f"page_{page_id}_attempt_2.json"
            )
        write_json(
            job_path,
            formal_job(
                project_dir=root,
                contract_path=project["content_dir"] / f"page_{page_id}.json",
                style="A",
                page_id=page_id,
                action=action,
                attempt=2,
                input_paths=input_paths,
            ),
        )

        before_dispatch = pipeline.read_json(state_path)["styles"]["A"]["pages"][page_id]
        dispatched = self.dispatch(state_path, [task], minute=10)
        self.assertEqual(dispatched["started"], 1)
        after_dispatch = pipeline.read_json(state_path)["styles"]["A"]["pages"][page_id]
        for field in (
            "selected_source",
            "selected_attempt",
            "qa_stage",
            "qa_scope",
            "content_gate",
            "spatial_gate",
            "craft_gate",
        ):
            self.assertEqual(after_dispatch.get(field), before_dispatch.get(field))

        replacement = root / "origin_image" / f"replacement_{action}_A_{page_id}.png"
        write_png_stub(replacement, tag=f"replacement-{action}".encode("ascii"))
        result = {
            "style": "A",
            "page_id": page_id,
            "action": action,
            "attempt": 2,
            "worker_agent_id": f"agent-A-{page_id}-{action}",
            "agent_action_started_at": "2099-01-01T00:11:00+08:00",
            "tool_started_at": "2099-01-01T00:11:10+08:00",
            "tool_finished_at": "2099-01-01T00:11:20+08:00",
            "agent_action_finished_at": "2099-01-01T00:11:30+08:00",
            "tool_call_id": f"new-tool-{action}",
            "savedPath": str(replacement.resolve()),
            "error": None,
        }
        results_path = root / "style_jobs" / "results" / f"{action}.json"
        if recover:
            unresolved = {
                **result,
                "savedPath": None,
                "error": "artifact_handoff_unresolved",
            }
            write_json(results_path, [unresolved])
            unresolved_result = self.call(
                pipeline.command_settle_wave,
                state=str(state_path),
                results_file=str(results_path),
                expected_styles="A",
                timestamp="2099-01-01T00:12:00+08:00",
            )
            self.assertEqual(len(unresolved_result["unresolved"]), 1)
            queued_state = pipeline.read_json(state_path)
            self.assertEqual(queued_state["scheduler"]["active_actions"], [])
            self.assertEqual(len(queued_state["scheduler"]["recovery_queue"]), 1)
            self.assertEqual(
                queued_state["styles"]["A"]["pages"][page_id]["selected_source"],
                str(incumbent.resolve()),
            )
            recovery_task = {
                "style": "A",
                "page_id": page_id,
                "action": "recover_artifact",
                "attempt": 2,
            }
            recovered_dispatch = self.dispatch(state_path, [recovery_task], minute=13)
            self.assertEqual(recovered_dispatch["started"], 1)
            result = {
                **result,
                "action": "recover_artifact",
                "source_action": action,
                "worker_agent_id": f"agent-A-{page_id}-recover_artifact",
                "agent_action_started_at": "2099-01-01T00:13:00+08:00",
                "agent_action_finished_at": "2099-01-01T00:13:30+08:00",
                "recovery_started_at": "2099-01-01T00:13:01+08:00",
                "recovery_finished_at": "2099-01-01T00:13:09+08:00",
                "recovery_method": "same_worker",
            }
            settle_timestamp = "2099-01-01T00:14:00+08:00"
        else:
            settle_timestamp = "2099-01-01T00:12:00+08:00"
        write_json(results_path, [result])
        settled = self.call(
            pipeline.command_settle_wave,
            state=str(state_path),
            results_file=str(results_path),
            expected_styles="A",
            timestamp=settle_timestamp,
        )
        self.assertEqual(settled["settled"], 1)
        return pipeline.read_json(state_path), incumbent, replacement

    def assert_repair_replacement(
        self,
        state: dict,
        *,
        action: str,
        page_id: str,
        incumbent: Path,
        replacement: Path,
    ) -> None:
        record = state["styles"]["A"]["pages"][page_id]
        self.assertEqual(record["status"], "generated")
        self.assertEqual(record["selected_attempt"], 2)
        self.assertEqual(record["selected_action"], action)
        self.assertEqual(record["attempt_count"], 2)
        self.assertEqual(
            record["attempt_sources"],
            [str(incumbent.resolve()), str(replacement.resolve())],
        )
        self.assertEqual(record["selected_source"], str(replacement.resolve()))
        self.assertEqual(len(record["attempt_history"]), 1)
        archived = record["attempt_history"][0]
        self.assertEqual(archived["attempt"], 1)
        self.assertEqual(archived["selected_source"], str(incumbent.resolve()))
        self.assertEqual(archived["status"], "accepted")
        self.assertEqual(archived["qa_stage"], "visual_worker")
        self.assertEqual(archived["qa_scope"], "full_visual")
        self.assertEqual(archived["failure_reason"], "incumbent_failure_context")
        for gate in ("content_gate", "spatial_gate", "craft_gate"):
            self.assertEqual(archived[gate]["status"], "pass")
            self.assertIsNone(record[gate])
        for field in (
            "qa_stage",
            "qa_scope",
            "qa_note",
            "failure_reason",
            "overview_qa_at",
            "completed_at",
            "final_path",
        ):
            self.assertIsNone(record[field])
        self.assertEqual(state["scheduler"]["active_actions"], [])
        self.assertFalse(
            any(item.get("action") == action for item in state["scheduler"]["ready_queue"])
        )

    def test_snapshot_guarded_quick8_dispatches_all_eight_anchor_tasks(self) -> None:
        project = self.prepare_project("quick8", pipeline.QUICK_8X1_MODE)
        tasks = [
            {"style": style, "page_id": "02", "action": "generate_anchor", "attempt": 1}
            for style in pipeline.QUICK_STYLES
        ]
        result = self.dispatch(project["state"], tasks)
        self.assertEqual(result["started"], 8)
        self.assertEqual(result["available_slots"], 0)
        self.assertEqual(
            {(item["style"], item["page_id"]) for item in result["tasks"]},
            {(style, "02") for style in pipeline.QUICK_STYLES},
        )

    def test_snapshot_guarded_fast_and_strict_dispatch_four_anchor_tasks(self) -> None:
        for mode in (pipeline.FAST_4X3_MODE, pipeline.STRICT_4X3_MODE):
            with self.subTest(mode=mode):
                project = self.prepare_project(f"anchors_{mode}", mode)
                tasks = [
                    {
                        "style": style,
                        "page_id": "02",
                        "action": "generate_anchor",
                        "attempt": 1,
                    }
                    for style in pipeline.FULL_STYLES
                ]
                result = self.dispatch(project["state"], tasks)
                self.assertEqual(result["started"], 4)
                self.assertEqual(result["active_count"], 4)

    def test_snapshot_guarded_fast_and_strict_dispatch_same_follower_page_across_styles(
        self,
    ) -> None:
        for mode in (pipeline.FAST_4X3_MODE, pipeline.STRICT_4X3_MODE):
            with self.subTest(mode=mode):
                project = self.prepare_project(f"followers_{mode}", mode)
                self.install_follower_wave(project)
                tasks = [
                    {
                        "style": style,
                        "page_id": "05",
                        "action": "generate_follower",
                        "attempt": 1,
                    }
                    for style in pipeline.FULL_STYLES
                ]
                result = self.dispatch(project["state"], tasks)
                self.assertEqual(result["started"], 4)
                self.assertEqual(
                    {(item["style"], item["page_id"]) for item in result["tasks"]},
                    {(style, "05") for style in pipeline.FULL_STYLES},
                )

    def test_strict_repair_anchor_dispatch_settle_archives_and_resets_qa(self) -> None:
        state, incumbent, replacement = self.run_strict_repair(
            action="repair_anchor", page_id="02"
        )
        self.assert_repair_replacement(
            state,
            action="repair_anchor",
            page_id="02",
            incumbent=incumbent,
            replacement=replacement,
        )

    def test_strict_repair_page_dispatch_settle_archives_and_resets_qa(self) -> None:
        state, incumbent, replacement = self.run_strict_repair(
            action="repair_page", page_id="05"
        )
        self.assert_repair_replacement(
            state,
            action="repair_page",
            page_id="05",
            incumbent=incumbent,
            replacement=replacement,
        )

    def test_strict_repair_recovery_preserves_incumbent_attempt_and_qa_provenance(
        self,
    ) -> None:
        state, incumbent, replacement = self.run_strict_repair(
            action="repair_anchor", page_id="02", recover=True
        )
        self.assert_repair_replacement(
            state,
            action="repair_anchor",
            page_id="02",
            incumbent=incumbent,
            replacement=replacement,
        )
        archived = state["styles"]["A"]["pages"]["02"]["attempt_history"][0]
        self.assertEqual(archived["attempt"], 1)
        self.assertEqual(archived["status"], "accepted")
        self.assertEqual(archived["failure_reason"], "incumbent_failure_context")
        self.assertEqual(archived["qa_stage"], "visual_worker")
        self.assertEqual(archived["qa_scope"], "full_visual")

    def test_guarded_strict_repair_not_found_chain_creates_and_dispatches_attempt_three(
        self,
    ) -> None:
        project = self.prepare_project(
            "strict_repair_technical_retry", pipeline.STRICT_4X3_MODE
        )
        root = project["root"]
        state_path = project["state"]
        incumbent = root / "origin_image" / "old_anchor_A_retry.png"
        write_png_stub(incumbent, tag=b"old-anchor-retry")
        state = pipeline.read_json(state_path)
        state["styles"]["A"]["pages"]["02"] = self.incumbent_record(
            "anchor", incumbent, "generate_anchor"
        )
        repair_two = {
            "style": "A",
            "page_id": "02",
            "action": "repair_anchor",
            "attempt": 2,
        }
        state["scheduler"]["phase"] = "repair_generation"
        state["scheduler"]["active_actions"] = []
        state["scheduler"]["recovery_queue"] = []
        state["scheduler"]["ready_queue"] = [repair_two]
        write_json(state_path, state)

        repair_two_job_path = (
            root
            / "style_jobs"
            / "repair_jobs"
            / "style_A_page_02_attempt_2.json"
        )
        repair_two_job = formal_job(
            project_dir=root,
            contract_path=project["content_dir"] / "page_02.json",
            style="A",
            page_id="02",
            action="repair_anchor",
            attempt=2,
            input_paths=[incumbent, project["asset"]],
        )
        write_json(repair_two_job_path, repair_two_job)
        sealed_attempt_two = repair_two_job_path.read_bytes()
        self.assertEqual(self.dispatch(state_path, [repair_two], minute=10)["started"], 1)

        unresolved = {
            "style": "A",
            "page_id": "02",
            "action": "repair_anchor",
            "attempt": 2,
            "worker_agent_id": "agent-A-02-repair_anchor",
            "agent_action_started_at": "2099-01-01T00:11:00+08:00",
            "tool_started_at": "2099-01-01T00:11:10+08:00",
            "tool_finished_at": "2099-01-01T00:11:20+08:00",
            "agent_action_finished_at": "2099-01-01T00:11:30+08:00",
            "tool_call_id": "strict-repair-attempt-2-tool",
            "savedPath": None,
            "error": "artifact_handoff_unresolved",
        }
        results_path = root / "style_jobs" / "results" / "repair_retry.json"
        write_json(results_path, [unresolved])
        unresolved_result = self.call(
            pipeline.command_settle_wave,
            state=str(state_path),
            results_file=str(results_path),
            expected_styles="A",
            timestamp="2099-01-01T00:12:00+08:00",
        )
        self.assertEqual(len(unresolved_result["unresolved"]), 1)

        recovery_task = {
            "style": "A",
            "page_id": "02",
            "action": "recover_artifact",
            "attempt": 2,
        }

        def record_recovery_event(
            event: str,
            minute: int,
            *,
            method: str,
            status: str | None = None,
        ) -> dict:
            details = {
                "source_action": "repair_anchor",
                "attempt": 2,
                "tool_call_id": unresolved["tool_call_id"],
                "tool_started_at": unresolved["tool_started_at"],
                "tool_finished_at": unresolved["tool_finished_at"],
                "recovery_method": method,
                "recovery_worker_agent_id": "agent-A-02-recover_artifact",
            }
            if status is not None:
                details["recovery_status"] = status
            return self.call(
                pipeline.command_record_event,
                state=str(state_path),
                event=event,
                style="A",
                page_id="02",
                action="recover_artifact",
                timestamp=f"2099-01-01T00:{minute:02d}:00+08:00",
                details_json=json.dumps(details),
            )

        self.assertEqual(self.dispatch(state_path, [recovery_task], minute=13)["started"], 1)
        record_recovery_event(
            "artifact_recovery_started", 14, method="same_worker"
        )
        first_not_found = record_recovery_event(
            "artifact_recovery_finished",
            15,
            method="same_worker",
            status="not_found",
        )
        self.assertEqual(first_not_found["next_action"], "recover_artifact")
        self.assertEqual(self.dispatch(state_path, [recovery_task], minute=16)["started"], 1)
        record_recovery_event(
            "artifact_recovery_started", 17, method="deterministic_script"
        )
        second_not_found = record_recovery_event(
            "artifact_recovery_finished",
            18,
            method="deterministic_script",
            status="not_found",
        )
        self.assertEqual(second_not_found["next_action"], "repair_anchor")

        repair_three_job_path = (
            root
            / "style_jobs"
            / "repair_jobs"
            / "style_A_page_02_attempt_3.json"
        )
        self.assertTrue(repair_three_job_path.is_file())
        repair_three_job = pipeline.read_json(repair_three_job_path)
        expected_retry_job = dict(repair_two_job)
        expected_retry_job["attempt"] = 3
        self.assertEqual(repair_three_job, expected_retry_job)
        self.assertEqual(repair_two_job_path.read_bytes(), sealed_attempt_two)

        queued_state = pipeline.read_json(state_path)
        queued_retry = next(
            item
            for item in queued_state["scheduler"]["ready_queue"]
            if item.get("style") == "A"
            and item.get("page_id") == "02"
            and item.get("action") == "repair_anchor"
            and item.get("attempt") == 3
        )
        self.assertTrue(queued_retry["technical_retry"])
        self.assertEqual(
            queued_retry["generation_job_path"], str(repair_three_job_path.resolve())
        )
        record = queued_state["styles"]["A"]["pages"]["02"]
        self.assertEqual(record["selected_source"], str(incumbent.resolve()))
        self.assertEqual(record["selected_attempt"], 1)
        self.assertEqual(record["attempt_count"], 2)
        self.assertEqual(record["content_gate"]["status"], "pass")
        self.assertEqual(record["spatial_gate"]["status"], "pass")
        self.assertEqual(record["craft_gate"]["status"], "pass")

        repair_three = {**repair_two, "attempt": 3}
        dispatched_retry = self.dispatch(state_path, [repair_three], minute=19)
        self.assertEqual(dispatched_retry["started"], 1)
        self.assertEqual(dispatched_retry["tasks"][0]["attempt"], 3)
        final_state = pipeline.read_json(state_path)
        active_retry = next(
            item
            for item in final_state["scheduler"]["active_actions"]
            if item.get("style") == "A"
            and item.get("page_id") == "02"
            and item.get("action") == "repair_anchor"
        )
        self.assertEqual(active_retry["attempt"], 3)
        self.assertEqual(
            active_retry["generation_job_path"], str(repair_three_job_path.resolve())
        )

    def test_dispatch_rejects_referenced_paths_manifest_tampering(self) -> None:
        project = self.prepare_project("tampered_manifest", pipeline.QUICK_8X1_MODE)
        job_path = project["root"] / "style_jobs" / "style_A.json"
        job = pipeline.read_json(job_path)
        self.assertTrue(job["imagegen_input_manifest"])
        job["imagegen_referenced_paths"] = []
        write_json(job_path, job)
        tasks = [
            {"style": style, "page_id": "02", "action": "generate_anchor", "attempt": 1}
            for style in pipeline.QUICK_STYLES
        ]
        with self.assertRaisesRegex(SystemExit, "路径或顺序不一致"):
            self.dispatch(project["state"], tasks)
        state = pipeline.read_json(project["state"])
        self.assertEqual(state["scheduler"]["active_actions"], [])
        self.assertEqual(len(state["scheduler"]["ready_queue"]), 8)
        self.assertFalse(any(event.get("name") == "dispatch_wave" for event in state["events"]))

    def test_dispatch_rejects_cross_style_anchor_reference(self) -> None:
        project = self.prepare_project("cross_style", pipeline.FAST_4X3_MODE)
        anchors = self.install_follower_wave(project)
        state = pipeline.read_json(project["state"])
        task = {
            "style": "A",
            "page_id": "05",
            "action": "generate_follower",
            "attempt": 1,
        }
        state["scheduler"]["ready_queue"] = [task]
        write_json(project["state"], state)
        job_path = project["root"] / "style_page_jobs" / "style_A" / "page_05.json"
        write_json(
            job_path,
            formal_job(
                project_dir=project["root"],
                contract_path=project["content_dir"] / "page_05.json",
                style="A",
                page_id="05",
                action="generate_follower",
                attempt=1,
                input_paths=[anchors["A"], anchors["B"], project["asset"]],
            ),
        )
        with self.assertRaises(SystemExit):
            self.dispatch(project["state"], [task])
        after = pipeline.read_json(project["state"])
        self.assertEqual(after["scheduler"]["active_actions"], [])
        self.assertEqual(after["scheduler"]["ready_queue"], [task])
        self.assertTrue(after["source_drift_detected"])
        drift = pipeline.read_json(project["root"] / "state" / "source_drift_status.json")
        self.assertTrue(
            any(
                item.get("reason") == "operation_path_not_in_snapshot"
                and item.get("path") == str(anchors["B"].resolve())
                for item in drift["changes"]
            )
        )

    def test_operation_inputs_hashes_shared_asset_once_per_wave(self) -> None:
        project = self.prepare_project("hash_cache", pipeline.QUICK_8X1_MODE)
        state = pipeline.read_json(project["state"])
        tasks = [
            {"style": style, "page_id": "02", "action": "generate_anchor", "attempt": 1}
            for style in pipeline.QUICK_STYLES
        ]
        calls: list[Path] = []
        real_sha256 = pipeline.file_sha256

        def tracking_sha256(path: Path) -> str:
            calls.append(Path(path).resolve())
            return real_sha256(path)

        with mock.patch.object(pipeline, "file_sha256", side_effect=tracking_sha256):
            contracts, assets = pipeline.operation_inputs_for_generation_tasks(
                project["state"], state, tasks
            )
        self.assertEqual(len(contracts), 1)
        self.assertEqual(len(assets), 1)
        self.assertEqual(calls.count(project["asset"].resolve()), 1)
        self.assertEqual(
            calls.count((project["content_dir"] / "page_02.json").resolve()), 1
        )


if __name__ == "__main__":
    unittest.main()
