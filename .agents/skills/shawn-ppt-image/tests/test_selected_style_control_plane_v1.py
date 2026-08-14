from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.test_quick8_pipeline import write_png


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "selected_style_control_plane_v1_test",
    SCRIPTS / "selected_style_control_plane_v1.py",
)
assert SPEC and SPEC.loader
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)
pipeline = control.pc
INIT = SCRIPTS / "init_task_dir.py"
PYTHON_WITH_PIL = Path(os.environ.get("SHAWN_PPT_TEST_PYTHON", Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"))


class SelectedStyleControlPlaneV1Test(unittest.TestCase):
    def test_director_prompts_keep_required_chrome_and_anchor_text_boundaries(self) -> None:
        chrome_prompt = (ROOT / "prompts" / "selected-style-chrome-assets-director.md").read_text(
            encoding="utf-8"
        )
        visual_prompt = (ROOT / "prompts" / "selected-style-visual-director.md").read_text(
            encoding="utf-8"
        )
        content_prompt = (ROOT / "prompts" / "selected-style-content-director.md").read_text(
            encoding="utf-8"
        )
        judge_prompt = (ROOT / "prompts" / "selected-style-judge.md").read_text(
            encoding="utf-8"
        )
        expansion_reference = (ROOT / "references" / "选定风格扩页.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("prompt_briefs.zh", chrome_prompt)
        self.assertIn("prompt_briefs.en", chrome_prompt)
        self.assertIn("各自非空", chrome_prompt)
        self.assertIn("`canonical_titles` 都保持 null", chrome_prompt)
        self.assertIn('"status":"authorized"', chrome_prompt)
        self.assertIn("默认选 `raster`", visual_prompt)
        self.assertIn("不得根据计划中可能出现的 Logo、产品图或附件数量猜测容量", visual_prompt)
        self.assertIn("正式附件占满 5 个时由控制面机械降级", visual_prompt)
        self.assertIn("旧主标题或正文并不单独构成降级理由", visual_prompt)
        self.assertIn("不要为了想象中的污染风险逐页过度审查", visual_prompt)
        self.assertIn('"subtitle"', content_prompt)
        self.assertIn("控制面只补机械默认值", content_prompt)
        self.assertIn("无语义影响的末尾", judge_prompt)
        self.assertIn("regenerate_text_family", judge_prompt)
        self.assertIn("整轮最多打开 6 张单图", judge_prompt)
        self.assertIn("所有必要疑点单图检查完成前", judge_prompt)
        self.assertIn("禁止落盘 preliminary、pending", judge_prompt)
        self.assertIn("只中断并以同一冻结 packet", expansion_reference)
        self.assertIn("不重启三席或整轮", expansion_reference)
        for prompt_name in (
            "fast8-content-contract-director.md",
            "4x3-content-contract-director.md",
            "selected-style-content-director.md",
        ):
            director_prompt = (ROOT / "prompts" / prompt_name).read_text(encoding="utf-8")
            self.assertIn("原文优先：大纲中的表达已经清楚、自然时", director_prompt)
            self.assertIn("不写“先……再……最后……”等导演式叙述", director_prompt)
            self.assertIn("不新增口号、观点或结论", director_prompt)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="selected_style_control_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "epc_outline.md"
        self.source.write_text(
            "# P02 Value thesis\nValidated value relationship.\n\n"
            "# P10 Architecture\nValidated architecture relationship.\n",
            encoding="utf-8",
        )
        self.primary = self.root / "primary.png"
        self.supporting = self.root / "supporting.png"
        self.fact_asset = self.root / "fact_asset.png"
        write_png(self.primary, color=b"\x20\x30\x40")
        write_png(self.supporting, color=b"\x30\x40\x50")
        write_png(self.fact_asset, color=b"\xf0\xe0\xd0")
        result = subprocess.run(
            [
                sys.executable,
                str(INIT),
                "--output-root",
                str(self.root / "output"),
                "--task-name",
                "epc_selected_style_control_test",
                "--run-mode",
                "selected_style_expansion",
                "--selected-style",
                "C",
                "--page-ids",
                "02,10",
                "--source-file",
                str(self.source),
                "--anchor",
                f"{self.primary}::primary",
                "--anchor",
                f"{self.supporting}::supporting",
                "--anchor-approval-scope",
                "style_anchor_only",
                "--overview-python",
                str(PYTHON_WITH_PIL),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.project = Path(payload["project_dir"])
        self.state_path = Path(payload["state"])
        self.director_dir = self.project / "state" / "director_inputs"
        self.generated_root = self.root / "generated_images"
        self.slot_registry = self.root / "runtime" / "imagegen_slots.json"
        self.env = mock.patch.dict(
            control.os.environ,
            {"SHAWN_PPT_IMAGE_GLOBAL_SLOT_STATE": str(self.slot_registry)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.generated_patch = mock.patch.object(
            control.pc, "GENERATED_IMAGES_ROOT", self.generated_root.resolve()
        )
        self.generated_patch.start()
        self.addCleanup(self.generated_patch.stop)

    @staticmethod
    def content_page(page_id: str, title: str, fact: str) -> dict:
        return {
            "page_id": page_id,
            "title": title,
            "language": "en-US",
            "source_facts": [fact],
            "display_required": [title, fact],
            "display_flexible": [],
            "display_supporting": [],
            "flexible_story": "",
            "information_density_target": "medium",
            "semantic_invariants": [fact],
            "forbidden_interpretations": [],
            "prompt_semantic_guardrails": [],
            "prompt_user_constraints": [],
            "content_resolution": {"status": "not_needed", "reason": "source sufficient"},
        }

    def write_director_inputs(
        self,
        *,
        page_02_assets: list[dict] | None = None,
        page_02_mode: str = "raster",
        page_10_mode: str = "text_family",
    ) -> None:
        content = {
            "selected_style_content_bundle_version": 1,
            "language": "en-US",
            "pages": [
                self.content_page("P2", "Value thesis", "Validated value relationship."),
                self.content_page("010", "Architecture", "Validated architecture relationship."),
            ],
        }
        assets = {
            "selected_style_assets_bundle_version": 1,
            "shared_required_assets": [],
            "global_chrome_authorized": False,
            "global_chrome_contract_raw": None,
            "pages": [
                {"page_id": "02", "required_page_assets": page_02_assets or []},
                {"page_id": "10", "required_page_assets": []},
            ],
        }
        visual = {
            "selected_style_visual_plan_version": 1,
            "style_family": {
                "style_family_thesis": "Dark engineered editorial family with precise luminous accents.",
                "tone": "dark",
                "palette_and_light": "Charcoal field, restrained blue-white illumination.",
                "typography_character": "Crisp modern industrial sans serif.",
                "material_character": "Technical glass, metal and controlled grain.",
                "image_craft": "Diagram, photography or abstraction chosen from page evidence.",
                "finish_quality": "Executive presentation finish with exact hierarchy.",
                "continuity_invariants": [
                    "charcoal and blue-white light family",
                    "precise editorial typography and premium finish",
                ],
            },
            "pages": [
                {
                    "page_id": "02",
                    "relationship_thesis": "Value follows from the validated relationship.",
                    "visual_quality_intent": "A concise executive proposition.",
                    "craft_axis": "editorial abstraction",
                    "visual_activity_mode": "restrained",
                    "attention_strategy": "single focal statement",
                    "spatial_topology_intent": "Open field with one anchored relationship.",
                    "page_adaptation_brief": "Use low density and generous open space.",
                    "anchor_input_mode": page_02_mode,
                    "representation_disclosure": {"mode": "none"},
                },
                {
                    "page_id": "10",
                    "relationship_thesis": "The architecture connects the validated components.",
                    "visual_quality_intent": "Readable high-density system view.",
                    "craft_axis": "technical systems diagram",
                    "visual_activity_mode": "balanced",
                    "attention_strategy": "guided left-to-right system path",
                    "spatial_topology_intent": "Layered architecture with aligned dependency lanes.",
                    "page_adaptation_brief": "Use diagrammatic density without copying the anchor layout.",
                    "anchor_input_mode": page_10_mode,
                    "representation_disclosure": {"mode": "none"},
                },
            ],
        }
        for name, value in (
            ("content_bundle.raw.json", content),
            ("chrome_assets_bundle.raw.json", assets),
            ("visual_family_plan.raw.json", visual),
        ):
            (self.director_dir / name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def prepare_and_manifest(self) -> tuple[dict, Path]:
        self.write_director_inputs()
        prepared = control.prepare_directors(self.state_path)
        self.assertEqual(prepared["status"], "prepared")
        action = control.render_action(self.state_path)
        self.assertIn("Promise.race", action)
        self.assertIn("tools.write_stdin", action)
        self.assertNotIn("Promise.allSettled", action)
        started = control.prepare_next(self.state_path, recover_orphans=True)
        self.assertEqual(started["status"], "started")
        manifests = list((self.project / "state" / "selected_style_manifests").glob("wave_*.json"))
        self.assertEqual(len(manifests), 1)
        return prepared, manifests[0]

    def test_prepare_next_is_bounded_and_leaves_remaining_tasks_ready(self) -> None:
        self.write_director_inputs()
        control.prepare_directors(self.state_path)
        with mock.patch.object(control, "GLOBAL_IMAGEGEN_CAPACITY", 1):
            prepared = control.prepare_next(self.state_path, recover_orphans=True)
        self.assertEqual(prepared["status"], "started")
        manifests = list(
            (self.project / "state" / "selected_style_manifests").glob("wave_*.json")
        )
        self.assertEqual(len(manifests), 1)
        self.assertEqual(len(pipeline.read_json(manifests[0])["tasks"]), 1)
        state = pipeline.read_json(self.state_path)
        self.assertEqual(len(state["scheduler"]["active_actions"]), 1)
        self.assertEqual(len(state["scheduler"]["ready_queue"]), 1)

    def test_generate_page_technical_retry_reuses_attempt_one_locked_job_and_sha(self) -> None:
        _prepared, manifest_path = self.prepare_and_manifest()
        manifest = pipeline.read_json(manifest_path)
        failed, succeeded = manifest["tasks"]
        locked_job_path = failed["generation_job_path"]
        locked_job_sha = failed["generation_job_sha256"]
        for item in (failed, succeeded):
            self.assertEqual(
                control.claim(self.state_path, manifest_path, item["task_key"], 0)["status"],
                "claimed",
            )
        failed_receipt = control.write_receipt(
            self.state_path,
            manifest_path,
            failed["task_key"],
            {
                "savedPath": None,
                "tool_started_at": "2099-01-01T00:00:10+08:00",
                "tool_finished_at": "2099-01-01T00:00:11+08:00",
                "tool_status": "failed",
                "error": "imagegen_backend_failed",
                "failure_class": "backend_failed",
                "tool_error_code": "fixture_failure",
            },
        )
        control.settle_receipt(self.state_path, Path(failed_receipt["receipt_path"]))
        tool_id = "exec-00000000-0000-4000-8000-000000000088"
        artifact = self.generated_root / "session" / f"{tool_id}.png"
        write_png(artifact, color=b"\xa1\xb1\xc1")
        success_receipt = control.write_receipt(
            self.state_path,
            manifest_path,
            succeeded["task_key"],
            {
                "savedPath": str(artifact),
                "tool_call_id": tool_id,
                "tool_started_at": "2099-01-01T00:00:10+08:00",
                "tool_finished_at": "2099-01-01T00:00:11+08:00",
                "tool_status": "completed",
                "error": None,
            },
        )
        control.settle_receipt(self.state_path, Path(success_receipt["receipt_path"]))

        first_retry_prepare = control.prepare_next(self.state_path)
        self.assertEqual(first_retry_prepare["status"], "recovery_required")
        second_retry_prepare = control.prepare_next(self.state_path)
        self.assertEqual(second_retry_prepare["status"], "started")
        retry_manifest = pipeline.read_json(Path(second_retry_prepare["manifest_path"]))
        self.assertEqual(len(retry_manifest["tasks"]), 1)
        retry = retry_manifest["tasks"][0]
        self.assertEqual(retry["action"], "generate_page")
        self.assertEqual(retry["attempt"], 2)
        self.assertTrue(retry["technical_retry"])
        self.assertEqual(retry["generation_job_path"], locked_job_path)
        self.assertEqual(retry["generation_job_sha256"], locked_job_sha)

    def test_recover_orphans_requeues_only_when_claim_and_receipt_are_both_absent(self) -> None:
        _prepared, manifest_path = self.prepare_and_manifest()
        manifest = pipeline.read_json(manifest_path)
        requeue_item, protected_item = manifest["tasks"]
        initial_state = pipeline.read_json(self.state_path)

        for protected_kind in ("claim", "receipt"):
            with self.subTest(protected_kind=protected_kind):
                pipeline.atomic_write_json(self.state_path, initial_state)
                for item in manifest["tasks"]:
                    claim_path, receipt_path = control.control_paths(
                        self.project, item["task_key"]
                    )
                    claim_path.unlink(missing_ok=True)
                    receipt_path.unlink(missing_ok=True)
                claim_path, receipt_path = control.control_paths(
                    self.project, protected_item["task_key"]
                )
                protected_path = claim_path if protected_kind == "claim" else receipt_path
                protected_path.parent.mkdir(parents=True, exist_ok=True)
                protected_path.write_text("{}", encoding="utf-8")

                result = control.prepare_next(self.state_path, recover_orphans=True)
                self.assertEqual(result["status"], "recovery_required")
                state = pipeline.read_json(self.state_path)
                active_keys = {
                    control.task_key(item)
                    for item in state["scheduler"]["active_actions"]
                }
                ready_keys = {
                    control.task_key(item)
                    for item in state["scheduler"]["ready_queue"]
                }
                self.assertIn(protected_item["task_key"], active_keys)
                self.assertNotIn(protected_item["task_key"], ready_keys)
                self.assertNotIn(requeue_item["task_key"], active_keys)
                self.assertIn(requeue_item["task_key"], ready_keys)

    def test_more_than_five_pages_are_drained_by_one_rolling_wrapper(self) -> None:
        self.write_director_inputs()
        control.prepare_directors(self.state_path)
        state = pipeline.read_json(self.state_path)
        template = dict(state["pages"]["10"])
        job_path = self.project / "page_jobs" / "page_10.json"
        job_sha = pipeline.file_sha256(job_path)
        for page_id in ("11", "12", "13", "14", "15"):
            state["page_order"].append(page_id)
            state["pages"][page_id] = {
                **template, "page_id": page_id, "status": "pending", "selected_source": None,
            }
            state["scheduler"]["ready_queue"].append({
                "style": "C", "page_id": page_id, "action": "generate_page", "attempt": 1,
                "generation_job_path": str(job_path), "generation_job_sha256": job_sha,
            })
        pipeline.atomic_write_json(self.state_path, state)
        wrapper = control.render_action(self.state_path)
        self.assertIn("while(true)", wrapper)
        self.assertIn("Promise.race", wrapper)
        self.assertIn("_prepare-next", wrapper)
        self.assertIn("tools.write_stdin", wrapper)
        self.assertIn(".finally", wrapper)
        self.assertIn('base+"_release"', wrapper)
        self.assertNotIn("Promise.allSettled", wrapper)
        def fake_capture(function, **kwargs):
            self.assertIs(function, control.pc.command_record_dispatch_wave)
            requested = json.loads(kwargs["tasks_json"])
            value = pipeline.read_json(self.state_path)
            requested_keys = {control.task_key(item) for item in requested}
            selected = [
                item for item in value["scheduler"]["ready_queue"]
                if control.task_key(item) in requested_keys
            ]
            value["scheduler"]["ready_queue"] = [
                item for item in value["scheduler"]["ready_queue"]
                if control.task_key(item) not in requested_keys
            ]
            value["scheduler"]["active_actions"].extend(selected)
            pipeline.atomic_write_json(self.state_path, value)
            return {"wave_id": f"fixture-{len(selected)}-{len(value['scheduler']['ready_queue'])}", "tasks": selected}

        with mock.patch.object(control.pc, "validate_generation_job_inputs"), mock.patch.object(
            control.pc, "generation_job_path_for_task",
            side_effect=lambda _project, item, _mode: Path(item["generation_job_path"]),
        ), mock.patch.object(control, "capture", side_effect=fake_capture):
            first = control.prepare_next(self.state_path, recover_orphans=True)
            self.assertEqual(first["status"], "started")
            self.assertEqual(len(first["tasks"]), 5)
            state = pipeline.read_json(self.state_path)
            self.assertEqual(len(state["scheduler"]["ready_queue"]), 2)
            completed_pages = [item["page_id"] for item in state["scheduler"]["active_actions"]]
            state["scheduler"]["active_actions"] = []
            for page_id in completed_pages:
                state["pages"][page_id]["selected_source"] = str(self.primary.resolve())
            pipeline.atomic_write_json(self.state_path, state)
            second = control.prepare_next(self.state_path)
        self.assertEqual(second["status"], "started")
        self.assertEqual(len(second["tasks"]), 2)
        self.assertEqual(len(pipeline.read_json(self.state_path)["scheduler"]["ready_queue"]), 0)

    def test_burst_runner_parses_terminal_json_without_eval(self) -> None:
        prompt = (ROOT / "prompts" / "selected-style-burst-runner.md").read_text(
            encoding="utf-8"
        )
        self.assertIn('trimmed.startsWith("{")', prompt)
        self.assertIn("JSON.parse(trimmed)", prompt)

    def settle_manifest(self, manifest_path: Path, *, color_seed: int = 0) -> None:
        manifest = pipeline.read_json(manifest_path)
        for index, item in enumerate(manifest["tasks"], start=1 + color_seed):
            claimed = control.claim(self.state_path, manifest_path, item["task_key"], 0)
            self.assertEqual(claimed["status"], "claimed")
            tool_id = f"exec-00000000-0000-4000-8000-{index:012d}"
            artifact = self.generated_root / "session" / f"{tool_id}.png"
            write_png(artifact, color=bytes((200 - index, 210 - index, 220 - index)))
            receipt = control.write_receipt(
                self.state_path,
                manifest_path,
                item["task_key"],
                {
                    "savedPath": str(artifact), "tool_call_id": tool_id,
                    "tool_started_at": "2099-01-01T00:00:10+08:00",
                    "tool_finished_at": "2099-01-01T00:00:11+08:00",
                    "tool_status": "completed", "error": None,
                },
            )
            control.settle_receipt(self.state_path, Path(receipt["receipt_path"]))

    def test_director_merge_compiles_v4_and_two_anchor_modes(self) -> None:
        self.write_director_inputs()
        prepared = control.prepare_directors(self.state_path)
        self.assertEqual(prepared["content_contracts"], 2)
        self.assertEqual(prepared["page_jobs"], 2)
        raster = pipeline.read_json(self.project / "page_jobs" / "page_02.json")
        text_family = pipeline.read_json(self.project / "page_jobs" / "page_10.json")
        self.assertEqual(raster["content_contract_version"], 2)
        self.assertEqual(raster["prompt_contract_version"], 4)
        self.assertEqual(raster["anchor_input_mode"], "raster")
        self.assertEqual(len(raster["reference_images"]), 2)
        self.assertEqual(text_family["anchor_input_mode"], "text_family")
        self.assertEqual(text_family["reference_images"], [])
        self.assertIn("creative_brief_projection", raster)
        self.assertIn("Exact main title", raster["imagegen_prompt"])
        self.assertEqual(raster["imagegen_prompt"].count("Value thesis"), 1)
        self.assertNotIn("global_chrome", raster)
        self.assertNotIn("global_chrome", text_family)
        self.assertEqual(
            pipeline.read_json(self.project / "selected_style_contract.json")[
                "anchor_approval_scope"
            ],
            "style_anchor_only",
        )
        snapshot = pipeline.read_json(
            self.project / "state" / "source_snapshot.json"
        )
        self.assertEqual(snapshot["page_content"]["authority_mode"], "authoritative_page_fragment")

    def test_required_assets_win_over_supporting_anchor_under_cap_five(self) -> None:
        assets = []
        for index in range(4):
            path = self.root / f"fact_{index}.png"
            write_png(path, color=bytes((120 + index, 130 + index, 140 + index)))
            assets.append({
                "path": str(path), "asset_usage": "render_asset",
                "role": "required_page_asset", "use": "render the verified product asset",
            })
        self.write_director_inputs(page_02_assets=assets)
        control.prepare_directors(self.state_path)
        job = pipeline.read_json(self.project / "page_jobs" / "page_02.json")
        self.assertEqual(len(job["required_page_assets"]), 4)
        self.assertEqual(len(job["reference_images"]), 1)
        self.assertEqual(len(job["imagegen_referenced_paths"]), 5)
        self.assertTrue(
            all(Path(item["path"]).name.startswith("fact_") for item in job["required_page_assets"])
        )

    def test_actual_required_assets_mechanically_downgrade_raster_at_cap_five(self) -> None:
        assets = []
        for index in range(5):
            path = self.root / f"capacity_fact_{index}.png"
            write_png(path, color=bytes((100 + index, 110 + index, 120 + index)))
            assets.append({
                "path": str(path), "asset_usage": "render_asset",
                "role": "required_page_asset", "use": "render the verified product asset",
            })
        self.write_director_inputs(page_02_assets=assets, page_02_mode="raster")
        control.prepare_directors(self.state_path)
        job = pipeline.read_json(self.project / "page_jobs" / "page_02.json")
        self.assertEqual(job["anchor_input_mode"], "text_family")
        self.assertEqual(job["reference_images"], [])
        self.assertEqual(len(job["required_page_assets"]), 5)
        self.assertEqual(len(job["imagegen_referenced_paths"]), 5)

    def test_planning_evidence_is_frozen_but_never_attached_and_disclosure_is_visible(self) -> None:
        render_asset = self.root / "render_asset.png"
        planning_evidence = self.root / "old_org_chart.png"
        write_png(render_asset, color=b"\x91\x92\x93")
        write_png(planning_evidence, color=b"\x61\x62\x63")
        self.write_director_inputs(page_02_assets=[
            {
                "path": str(render_asset), "asset_usage": "render_asset",
                "role": "authorized_product_image", "use": "show the actual product",
            },
            {
                "path": str(planning_evidence), "asset_usage": "planning_evidence",
                "role": "old_organization_chart", "use": "extract the verified relationship only",
            },
        ])
        visual_path = self.director_dir / "visual_family_plan.raw.json"
        visual = pipeline.read_json(visual_path)
        visual["pages"][0]["representation_disclosure"] = {
            "mode": "visible", "visible_text": "情境重建｜非现场原图",
            "reason": "No authorized site photograph is available for this reconstruction.",
        }
        visual_path.write_text(json.dumps(visual, ensure_ascii=False), encoding="utf-8")
        control.prepare_directors(self.state_path)
        job = pipeline.read_json(self.project / "page_jobs" / "page_02.json")
        self.assertIn(str(render_asset.resolve()), job["imagegen_referenced_paths"])
        self.assertNotIn(str(planning_evidence.resolve()), job["imagegen_referenced_paths"])
        self.assertEqual(job["planning_evidence"][0]["path"], str(planning_evidence.resolve()))
        self.assertIn("情境重建｜非现场原图", job["imagegen_prompt"])
        contract = pipeline.read_json(self.project / "content_contracts" / "page_02.json")
        self.assertIn("情境重建｜非现场原图", contract["display_required"])
        snapshot = pipeline.read_json(self.project / "state" / "source_snapshot.json")
        self.assertIn(str(planning_evidence.resolve()), json.dumps(snapshot, ensure_ascii=False))

    def test_prepare_directors_is_identity_bound_and_does_not_reset_progress(self) -> None:
        self.write_director_inputs()
        first = control.prepare_directors(self.state_path)
        self.assertEqual(first["status"], "prepared")
        state = pipeline.read_json(self.state_path)
        original_event_count = len(state["events"])
        state["pages"]["02"]["status"] = "accepted"
        pipeline.atomic_write_json(self.state_path, state)
        repeated = control.prepare_directors(self.state_path)
        self.assertEqual(repeated["status"], "already_prepared")
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["pages"]["02"]["status"], "accepted")
        self.assertEqual(len(state["events"]), original_event_count)
        state["status"] = "completed"
        pipeline.atomic_write_json(self.state_path, state)
        terminal = control.prepare_directors(self.state_path)
        self.assertEqual(terminal["status"], "already_prepared")
        raw = self.director_dir / "content_bundle.raw.json"
        raw.write_text(raw.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "冻结文件已变化"):
            control.prepare_directors(self.state_path)

    def test_global_chrome_is_compiled_only_from_explicit_authorization(self) -> None:
        self.write_director_inputs()
        assets_path = self.director_dir / "chrome_assets_bundle.raw.json"
        assets = pipeline.read_json(assets_path)
        assets.update({
            "global_chrome_authorized": True,
            "canonical_titles": None,
            "global_chrome_contract_raw": {
                "authorization": {
                    "status": "authorized",
                    "basis": "Frozen outline explicitly requires a shared title header.",
                },
                "deck_title_system": {
                    "enabled": True,
                    "scope": {"include_page_ids": ["02", "10"]},
                    "logo": {"required": False, "position": "top-left"},
                    "main_title": {"required": True, "position": "top-left"},
                    "prompt_briefs": {
                        "zh": "按冻结标题逐页呈现统一标题层级，不改变内容区布局。",
                        "en": "Render each frozen title in one shared hierarchy without fixing the content layout.",
                    },
                    "qa_required": True,
                },
            },
        })
        assets_path.write_text(json.dumps(assets, ensure_ascii=False), encoding="utf-8")
        control.prepare_directors(self.state_path)
        normalized = self.director_dir / "global_chrome_contract.normalized.json"
        self.assertTrue(normalized.is_file())
        chrome = pipeline.read_json(normalized)
        self.assertEqual(
            chrome["deck_title_system"]["main_title"]["text_by_page"],
            {"02": "Value thesis", "10": "Architecture"},
        )
        for page_id in ("02", "10"):
            job = pipeline.read_json(self.project / "page_jobs" / f"page_{page_id}.json")
            self.assertIn("global_chrome", job)
            self.assertEqual(job["global_chrome"]["main_title"]["text"], chrome["deck_title_system"]["main_title"]["text_by_page"][page_id])

    def test_mixed_language_uses_content_contract_prompt_locale(self) -> None:
        self.write_director_inputs()
        content_path = self.director_dir / "content_bundle.raw.json"
        content = pipeline.read_json(content_path)
        content["pages"][0]["language"] = "mixed"
        content["pages"][0]["display_required"] = [
            "核心价值 Value",
            "通过统一方法降低执行偏差并提升跨区域交付确定性。",
        ]
        content["pages"][0]["source_facts"] = [
            "通过统一方法降低执行偏差并提升跨区域交付确定性。",
        ]
        content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        control.prepare_directors(self.state_path)
        contract = pipeline.read_json(self.project / "content_contracts" / "page_02.json")
        self.assertEqual(
            contract["spatial_generation_brief"],
            pipeline.UNIFIED_SPATIAL_PROMPT_CUES["zh"],
        )

    def test_page_input_mismatch_blocks_only_that_page(self) -> None:
        self.write_director_inputs()
        control.prepare_directors(self.state_path)
        bad_job = self.project / "page_jobs" / "page_02.json"
        value = pipeline.read_json(bad_job)
        value["unauthorized_mutation"] = True
        bad_job.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        prepared = control.prepare_next(self.state_path, recover_orphans=True)
        self.assertEqual(prepared["status"], "started")
        state = pipeline.read_json(self.state_path)
        self.assertEqual(
            [(item["page_id"], item["status"]) for item in state["scheduler"]["recovery_queue"]],
            [("02", "page_input_mismatch")],
        )
        self.assertEqual(
            [item["page_id"] for item in state["scheduler"]["active_actions"]],
            ["10"],
        )
        self.assertEqual(state["pages"]["02"]["status"], "attention_required")

    def test_content_decision_page_does_not_block_accepted_page_delivery(self) -> None:
        state = pipeline.read_json(self.state_path)
        for index, page_id in enumerate(("02", "10"), start=1):
            candidate = self.generated_root / "decision" / f"page_{page_id}.png"
            write_png(candidate, color=bytes((180 + index, 190 + index, 200 + index)))
            state["pages"][page_id]["selected_source"] = str(candidate)
        pipeline.atomic_write_json(self.state_path, state)
        values = control.candidate_set(state)
        report_path = self.project / "visual_qa_jobs" / "results" / "decision.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "needs_content_decision_pages": ["02"],
            "pages": {
                "02": {
                    "status": "needs_content_decision",
                    "content_gate": {"status": "needs_content_decision", "reason": "Choose one claim."},
                },
                "10": {
                    "status": "pass",
                    "content_gate": {"status": "pass", "reason": "verified"},
                    "spatial_gate": {"status": "pass", "reason": "verified"},
                    "craft_gate": {"status": "pass", "reason": "verified"},
                },
            },
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        result = control.finalize_content_decision_partial(
            self.state_path, state, self.project, report, values, report_path
        )
        self.assertEqual(result["status"], "needs_content_decision")
        self.assertEqual(result["accepted_pages"], ["10"])
        updated = pipeline.read_json(self.state_path)
        self.assertEqual(updated["pages"]["02"]["status"], "needs_content_decision")
        self.assertEqual(updated["pages"]["10"]["status"], "accepted")
        self.assertTrue(Path(updated["pages"]["10"]["final_path"]).is_file())
        self.assertTrue(Path(result["partial_handoff"]).is_file())

    def test_judge_uses_generate_page_job_after_attempt_two_generate_page_selection(self) -> None:
        self.write_director_inputs()
        control.prepare_directors(self.state_path)
        state = pipeline.read_json(self.state_path)
        for index, page_id in enumerate(state["page_order"], start=1):
            candidate = self.generated_root / "judge" / f"page_{page_id}.png"
            write_png(candidate, color=bytes((150 + index, 160 + index, 170 + index)))
            state["pages"][page_id]["selected_source"] = str(candidate.resolve())
            state["pages"][page_id]["attempt_count"] = 2
            state["pages"][page_id]["selected_attempt"] = 2
            state["pages"][page_id]["selected_action"] = "generate_page"
        pipeline.atomic_write_json(self.state_path, state)

        values = control.candidate_set(state)
        judge_job_path, _report_path, _overview_path = control.ensure_judge_job(
            self.state_path, state, self.project, values
        )
        judge_job = pipeline.read_json(judge_job_path)
        for candidate in judge_job["candidates"]:
            expected = self.project / "page_jobs" / f"page_{candidate['page_id']}.json"
            self.assertEqual(candidate["generation_job_path"], str(expected.resolve()))
            self.assertEqual(
                candidate["generation_job_sha256"], pipeline.file_sha256(expected)
            )

    def test_duplicate_claim_settle_idempotent_render_and_lean_finalize(self) -> None:
        _prepared, manifest_path = self.prepare_and_manifest()
        manifest = pipeline.read_json(manifest_path)
        first = manifest["tasks"][0]
        claimed = control.claim(self.state_path, manifest_path, first["task_key"], 0)
        self.assertEqual(claimed["status"], "claimed")
        with self.assertRaisesRegex(SystemExit, "duplicate claim"):
            control.claim(self.state_path, manifest_path, first["task_key"], 0)
        for index, item in enumerate(manifest["tasks"], start=1):
            if item is not first:
                claimed = control.claim(self.state_path, manifest_path, item["task_key"], 0)
                self.assertEqual(claimed["status"], "claimed")
            tool_id = f"exec-00000000-0000-4000-8000-{index:012d}"
            artifact = self.generated_root / "session" / f"{tool_id}.png"
            write_png(artifact, color=bytes((200 - index, 210 - index, 220 - index)))
            receipt = control.write_receipt(
                self.state_path,
                manifest_path,
                item["task_key"],
                {
                    "savedPath": str(artifact),
                    "tool_call_id": tool_id,
                    "tool_started_at": "2099-01-01T00:00:10+08:00",
                    "tool_finished_at": "2099-01-01T00:00:11+08:00",
                    "tool_status": "completed",
                    "error": None,
                },
            )
            control.settle_receipt(self.state_path, Path(receipt["receipt_path"]))

        self.assertEqual(control.prepare_next(self.state_path)["status"], "complete")
        waiting = control.lean_finalize(self.state_path)
        self.assertEqual(waiting["status"], "waiting_for_judge")
        job = pipeline.read_json(Path(waiting["judge_job"]))
        report = {
            "selected_style_judge_report_version": 1,
            "run_id": job["run_id"],
            "candidate_set_sha256": job["candidate_set_sha256"],
            "decision": "pass",
            "technical_health": {"status": "pass", "issues": []},
            "visual_correctness": {
                "status": "pass",
                "issues": [],
                "pages": {
                    page: {
                        "content_gate": {"status": "pass", "reason": "fixture"},
                        "spatial_gate": {"status": "pass", "reason": "fixture"},
                        "craft_gate": {"status": "pass", "reason": "fixture"},
                    }
                    for page in ("02", "10")
                },
            },
        }
        report_path = Path(waiting["report_output_path"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report), encoding="utf-8")
        completed = control.lean_finalize(self.state_path)
        self.assertEqual(completed["status"], "completed")
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["status"], "completed")
        self.assertTrue(Path(completed["overview"]).is_file())
        self.assertTrue(Path(completed["handoff"]).is_file())
        self.assertEqual(control.lean_finalize(self.state_path)["status"], "already_completed")

    def test_one_targeted_repair_then_delta_review_closes(self) -> None:
        _prepared, manifest_path = self.prepare_and_manifest()
        self.settle_manifest(manifest_path)
        waiting = control.lean_finalize(self.state_path)
        job = pipeline.read_json(Path(waiting["judge_job"]))
        page_02_candidate = next(item for item in job["candidates"] if item["page_id"] == "02")
        self.assertEqual(page_02_candidate["expected_main_title"], "Value thesis")
        self.assertIsNone(page_02_candidate["expected_subtitle"])
        self.assertTrue(
            page_02_candidate["title_review_policy"][
                "allow_harmless_terminal_punctuation_difference"
            ]
        )
        self.assertIn("current_page_main_title", job["checks"])
        report_path = Path(waiting["report_output_path"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({
            "selected_style_judge_report_version": 1,
            "run_id": job["run_id"],
            "candidate_set_sha256": job["candidate_set_sha256"],
            "decision": "repair",
            "repair_pages": [{
                "page_id": "02", "must_change": "Remove the observable stray label.",
                "invariants": ["preserve validated facts", "preserve visual family"],
                "repair_input_policy": "regenerate_text_family",
            }],
        }), encoding="utf-8")
        repair = control.lean_finalize(self.state_path)
        self.assertEqual(repair["status"], "repair_required")
        self.assertEqual(repair["pages"], ["02"])
        repair_job = pipeline.read_json(Path(repair["jobs"][0]))
        self.assertEqual(repair_job["repair_input_policy"], "regenerate_text_family")
        self.assertEqual(repair_job["anchor_input_mode"], "text_family")
        self.assertIsNone(repair_job["repair_source"])
        self.assertEqual(repair_job["reference_images"], [])
        self.assertEqual(repair_job["imagegen_referenced_paths"], [])
        self.assertIn("Exact main title", repair_job["imagegen_prompt"])
        self.assertNotIn("Style references (", repair_job["imagegen_prompt"])
        started = control.prepare_next(self.state_path, recover_orphans=True)
        self.assertEqual(started["status"], "started")
        manifests = sorted((self.project / "state" / "selected_style_manifests").glob("wave_*.json"))
        self.assertEqual(len(manifests), 2)
        self.settle_manifest(manifests[-1], color_seed=10)
        delta = control.lean_finalize(self.state_path)
        self.assertEqual(delta["status"], "waiting_for_judge")
        delta_job = pipeline.read_json(Path(delta["judge_job"]))
        self.assertEqual(delta_job["review_kind"], "delta_review")
        self.assertEqual(delta_job["review_scope"]["repaired_page_ids"], ["02"])
        delta_report_path = Path(delta["report_output_path"])
        delta_report_path.write_text(json.dumps({
            "selected_style_judge_report_version": 1,
            "run_id": delta_job["run_id"],
            "candidate_set_sha256": delta_job["candidate_set_sha256"],
            "decision": "pass",
            "technical_health": {"status": "pass", "issues": []},
            "visual_correctness": {"status": "pass", "issues": []},
            "pages": {
                page: {
                    "status": "pass",
                    "content_gate": {"status": "pass", "reason": "delta fixture"},
                    "spatial_gate": {"status": "pass", "reason": "delta fixture"},
                    "craft_gate": {"status": "pass", "reason": "delta fixture"},
                } for page in ("02", "10")
            },
            "repair_pages": [], "needs_content_decision_pages": [],
        }), encoding="utf-8")
        completed = control.lean_finalize(self.state_path)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(
            pipeline.read_json(self.state_path)["selected_style_judge"]["repair_rounds_used"], 1
        )

    def test_semantic_repair_can_drop_failed_candidate_but_keep_clean_anchor(self) -> None:
        _prepared, manifest_path = self.prepare_and_manifest()
        self.settle_manifest(manifest_path)
        waiting = control.lean_finalize(self.state_path)
        judge_job = pipeline.read_json(Path(waiting["judge_job"]))
        report_path = Path(waiting["report_output_path"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({
            "selected_style_judge_report_version": 1,
            "run_id": judge_job["run_id"],
            "candidate_set_sha256": judge_job["candidate_set_sha256"],
            "decision": "repair",
            "repair_pages": [{
                "page_id": "02",
                "must_change": "Remove content not authorized by the current page.",
                "invariants": ["preserve current-page facts"],
                "repair_input_policy": "regenerate_without_candidate",
            }],
        }), encoding="utf-8")
        result = control.lean_finalize(self.state_path)
        repair_job = pipeline.read_json(Path(result["jobs"][0]))
        self.assertEqual(repair_job["repair_input_policy"], "regenerate_without_candidate")
        self.assertIsNone(repair_job["repair_source"])
        self.assertEqual(repair_job["anchor_input_mode"], "raster")
        self.assertEqual(len(repair_job["reference_images"]), 2)
        self.assertNotIn(
            str(Path(pipeline.read_json(self.state_path)["pages"]["02"]["selected_source"]).resolve()),
            repair_job["imagegen_referenced_paths"],
        )

    def test_one_backend_failure_does_not_cancel_other_started_page(self) -> None:
        _prepared, manifest_path = self.prepare_and_manifest()
        manifest = pipeline.read_json(manifest_path)
        failed, succeeded = manifest["tasks"]
        for item in (failed, succeeded):
            self.assertEqual(
                control.claim(self.state_path, manifest_path, item["task_key"], 0)["status"],
                "claimed",
            )
        failed_receipt = control.write_receipt(
            self.state_path, manifest_path, failed["task_key"],
            {
                "savedPath": None, "tool_started_at": "2099-01-01T00:00:10+08:00",
                "tool_finished_at": "2099-01-01T00:00:11+08:00",
                "tool_status": "failed", "error": "imagegen_backend_failed",
                "failure_class": "backend_failed", "tool_error_code": "fixture_failure",
            },
        )
        control.settle_receipt(self.state_path, Path(failed_receipt["receipt_path"]))
        tool_id = "exec-00000000-0000-4000-8000-000000000099"
        artifact = self.generated_root / "session" / f"{tool_id}.png"
        write_png(artifact, color=b"\xa0\xb0\xc0")
        success_receipt = control.write_receipt(
            self.state_path, manifest_path, succeeded["task_key"],
            {
                "savedPath": str(artifact), "tool_call_id": tool_id,
                "tool_started_at": "2099-01-01T00:00:10+08:00",
                "tool_finished_at": "2099-01-01T00:00:11+08:00",
                "tool_status": "completed", "error": None,
            },
        )
        control.settle_receipt(self.state_path, Path(success_receipt["receipt_path"]))
        state = pipeline.read_json(self.state_path)
        self.assertTrue(state["pages"][succeeded["page_id"]]["selected_source"])
        self.assertFalse(
            any(item["page_id"] == succeeded["page_id"] for item in state["scheduler"]["active_actions"])
        )
        failed_pending = [
            item for item in state["scheduler"]["ready_queue"] + state["scheduler"]["recovery_queue"]
            if item["page_id"] == failed["page_id"]
        ]
        self.assertTrue(failed_pending or state["pages"][failed["page_id"]]["status"] in {"failed", "attention_required"})


if __name__ == "__main__":
    unittest.main()
