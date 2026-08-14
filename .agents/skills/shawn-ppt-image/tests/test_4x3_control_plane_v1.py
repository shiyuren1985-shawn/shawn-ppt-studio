from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import uuid

from tests.test_4x3_director_method import FourByThreeDirectorMethodTest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "four_by_three_control_plane_v1.py"
SPEC = importlib.util.spec_from_file_location("four_by_three_control_plane_v1_test", MODULE_PATH)
assert SPEC and SPEC.loader
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)
pipeline = control.pc
NODE = Path(os.environ.get("SHAWN_PPT_TEST_NODE", Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"))


class FourByThreeControlPlaneV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FourByThreeDirectorMethodTest(
            "test_three_director_merge_and_family_projection_reach_followers"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.merge_inputs()
        self.fixture.reseal_source()
        self.fixture.fixture.prepare_anchors()
        self.state_path = self.fixture.fixture.state_path
        self.project_dir = self.fixture.fixture.root
        self.content_dir = self.fixture.fixture.content_dir
        self.original_generated_root = control.pc.GENERATED_IMAGES_ROOT
        control.pc.GENERATED_IMAGES_ROOT = self.project_dir.resolve()
        self.addCleanup(
            lambda: setattr(
                control.pc, "GENERATED_IMAGES_ROOT", self.original_generated_root
            )
        )

    def test_anchor_settlement_unlocks_only_its_own_followers(self) -> None:
        prepared = control.prepare_next(self.state_path, self.content_dir)
        self.assertEqual(prepared["status"], "started")
        self.assertEqual(
            [(item["style"], item["page_id"]) for item in prepared["tasks"]],
            [(style, "02") for style in "ABCD"],
        )
        self.assertTrue(all("prompt" not in item for item in prepared["tasks"]))
        self.assertLess(len(json.dumps(prepared, ensure_ascii=False)), 4000)
        manifest = Path(prepared["manifest_path"])
        exact_input = control.task_input(
            self.state_path, manifest, prepared["tasks"][0]["task_key"]
        )
        self.assertTrue(exact_input["prompt"].strip())
        self.assertTrue(exact_input["imagegen_input_fingerprint"])
        resumed = control.prepare_next(self.state_path, self.content_dir)
        self.assertEqual(resumed["status"], "resuming_preclaim")
        self.assertEqual(resumed["manifest_path"], str(manifest))
        a = prepared["tasks"][0]
        claimed = control.claim(self.state_path, manifest, a["task_key"], 0)
        self.assertEqual(claimed["status"], "claimed")
        with self.assertRaisesRegex(SystemExit, "已有 claim"):
            control.claim(self.state_path, manifest, a["task_key"], 0)
        receipt = control.write_receipt(
            self.state_path,
            manifest,
            a["task_key"],
            {
                "savedPath": str(self.fixture.fixture.image_path.resolve()),
                "tool_started_at": "2099-01-01T00:00:10+08:00",
                "tool_finished_at": "2099-01-01T00:00:11+08:00",
                "error": None,
            },
        )
        control.settle_receipt(
            self.state_path, Path(receipt["receipt_path"]), self.content_dir
        )
        state = pipeline.read_json(self.state_path)
        ready = (state.get("scheduler") or {}).get("ready_queue") or []
        self.assertEqual(
            [(item["style"], item["page_id"]) for item in ready],
            [("A", "05"), ("A", "08")],
        )
        next_wave = control.prepare_next(self.state_path, self.content_dir)
        self.assertEqual(len(next_wave["tasks"]), 2)
        self.assertEqual(
            [
                (item["style"], item["page_id"])
                for item in next_wave["tasks"]
            ],
            [("A", "05"), ("A", "08")],
        )

    def test_receipt_reuses_fast8_output_hint_path_parser(self) -> None:
        prepared = control.prepare_next(self.state_path, self.content_dir)
        manifest = Path(prepared["manifest_path"])
        item = prepared["tasks"][0]
        claimed = control.claim(self.state_path, manifest, item["task_key"], 0)
        self.assertEqual(claimed["status"], "claimed")
        generated = (
            self.project_dir
            / "exec-00000000-0000-0000-0000-000000000001.png"
        )
        generated.write_bytes(self.fixture.fixture.image_path.read_bytes())
        receipt_result = control.write_receipt(
            self.state_path,
            manifest,
            item["task_key"],
            {
                "savedPath": f"Image saved successfully to {generated}",
                "tool_started_at": "2099-01-01T00:00:10+08:00",
                "tool_finished_at": "2099-01-01T00:00:11+08:00",
                "error": None,
            },
        )
        receipt = pipeline.read_json(Path(receipt_result["receipt_path"]))
        self.assertEqual(receipt["savedPath"], str(generated.resolve()))
        self.assertEqual(
            receipt["tool_call_id"],
            "exec-00000000-0000-0000-0000-000000000001",
        )
        self.assertIsNone(receipt["error"])

    def test_partial_follower_wave_records_shared_capacity_backpressure(self) -> None:
        prepared = control.prepare_next(self.state_path, self.content_dir)
        manifest = Path(prepared["manifest_path"])
        source_paths = [
            self.fixture.fixture.image_path.resolve(),
            self.fixture.fixture.follower_image_paths["05"].resolve(),
        ]
        for item, source in zip(prepared["tasks"][:2], source_paths):
            claimed = control.claim(
                self.state_path, manifest, item["task_key"], 0
            )
            self.assertEqual(claimed["status"], "claimed")
            receipt = control.write_receipt(
                self.state_path,
                manifest,
                item["task_key"],
                {
                    "savedPath": str(source),
                    "tool_started_at": "2099-01-01T00:00:10+08:00",
                    "tool_finished_at": "2099-01-01T00:00:11+08:00",
                    "error": None,
                },
            )
            control.settle_receipt(
                self.state_path, Path(receipt["receipt_path"]), self.content_dir
            )
        next_wave = control.prepare_next(self.state_path, self.content_dir)
        self.assertEqual(next_wave["status"], "started")
        self.assertEqual(len(next_wave["tasks"]), 3)
        state = pipeline.read_json(self.state_path)
        backpressure = [
            event
            for event in state["events"]
            if event.get("name") == "runtime_backpressure"
        ][-1]
        self.assertEqual(
            backpressure["details"]["reason"],
            "shared_imagegen_capacity",
        )

    def test_recovery_queue_stops_before_any_regeneration(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["scheduler"]["recovery_queue"] = [
            {
                "style": "A",
                "page_id": "02",
                "action": "recover_artifact",
                "attempt": 1,
            }
        ]
        pipeline.atomic_write_json(self.state_path, state)
        result = control.prepare_next(self.state_path, self.content_dir)
        self.assertEqual(result["status"], "recovery_required")
        self.assertEqual(
            result["reason"], "existing_artifact_must_be_recovered_before_regeneration"
        )
        state = pipeline.read_json(self.state_path)
        self.assertFalse((state.get("scheduler") or {}).get("active_actions"))

    def test_claim_without_receipt_is_recovery_required_on_fresh_runner(self) -> None:
        prepared = control.prepare_next(self.state_path, self.content_dir)
        manifest = Path(prepared["manifest_path"])
        item = prepared["tasks"][0]
        control.claim(self.state_path, manifest, item["task_key"], 0)
        recovered = control.prepare_next(
            self.state_path, self.content_dir, recover_orphans=True
        )
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertEqual(len(recovered["recovery_tasks"]), 1)
        self.assertEqual(
            recovered["recovery_tasks"][0]["reason"],
            "claim_without_receipt_requires_artifact_recovery",
        )

    def test_technical_retry_waits_until_existing_rpc_wave_is_drained(self) -> None:
        prepared = control.prepare_next(self.state_path, self.content_dir)
        manifest = Path(prepared["manifest_path"])
        control.claim(
            self.state_path, manifest, prepared["tasks"][0]["task_key"], 0
        )
        state = pipeline.read_json(self.state_path)
        state["scheduler"]["ready_queue"].append(
            {
                "style": "A",
                "page_id": "02",
                "action": "generate_anchor",
                "attempt": 2,
                "technical_retry": True,
                "retry_reason": "imagegen_backend_failed",
            }
        )
        pipeline.atomic_write_json(self.state_path, state)
        result = control.prepare_next(self.state_path, self.content_dir)
        self.assertEqual(result["status"], "waiting")
        state = pipeline.read_json(self.state_path)
        self.assertEqual(len(state["scheduler"]["active_actions"]), 4)
        retries = [
            item
            for item in state["scheduler"]["ready_queue"]
            if int(item.get("attempt") or 1) == 2
        ]
        self.assertEqual(len(retries), 1)

    def test_failed_receipt_preserves_compact_tool_error(self) -> None:
        prepared = control.prepare_next(self.state_path, self.content_dir)
        manifest = Path(prepared["manifest_path"])
        item = prepared["tasks"][0]
        control.claim(self.state_path, manifest, item["task_key"], 0)
        result = control.write_receipt(
            self.state_path,
            manifest,
            item["task_key"],
            {
                "savedPath": None,
                "tool_started_at": "2099-01-01T00:00:10+08:00",
                "tool_finished_at": "2099-01-01T00:00:11+08:00",
                "error": "imagegen_backend_failed",
                "tool_status": "failed",
                "failure_class": "backend_failed",
                "tool_error_code": "unsupported referenced image type: pdf",
            },
        )
        receipt = pipeline.read_json(Path(result["receipt_path"]))
        self.assertEqual(receipt["tool_status"], "failed")
        self.assertEqual(receipt["failure_class"], "backend_failed")
        self.assertIn("pdf", receipt["tool_error_code"])

    def test_terminalize_closes_queues_and_releases_claim_lease(self) -> None:
        prepared = control.prepare_next(self.state_path, self.content_dir)
        manifest = Path(prepared["manifest_path"])
        item = prepared["tasks"][0]
        control.claim(self.state_path, manifest, item["task_key"], 0)
        result = control.terminalize(
            self.state_path, "unrecoverable_fast4x3_runtime_state"
        )
        self.assertEqual(result["status"], "blocked")
        self.assertGreaterEqual(result["released_leases"], 1)
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["scheduler"]["phase"], "terminal")
        for name in ("active_actions", "ready_queue", "recovery_queue"):
            self.assertEqual(state["scheduler"][name], [])
        event_count = len(
            [event for event in state["events"] if event.get("name") == "run_terminalized"]
        )
        repeated = control.terminalize(
            self.state_path, "unrecoverable_fast4x3_runtime_state"
        )
        self.assertEqual(repeated["status"], "already_blocked")
        state = pipeline.read_json(self.state_path)
        self.assertEqual(
            len(
                [
                    event
                    for event in state["events"]
                    if event.get("name") == "run_terminalized"
                ]
            ),
            event_count,
        )

    def test_text_family_follower_allows_logo_plus_four_page_assets(self) -> None:
        state = pipeline.read_json(self.state_path)
        dummy_chrome = self.project_dir / "state" / "director_inputs" / "chrome.json"
        dummy_chrome.parent.mkdir(parents=True, exist_ok=True)
        dummy_chrome.write_text("{}", encoding="utf-8")
        state["global_chrome_contract_path"] = str(dummy_chrome)
        state["global_chrome_contract_sha256"] = "chrome-sha"
        pipeline.atomic_write_json(self.state_path, state)
        paths = []
        for index in range(4):
            path = self.project_dir / f"asset_{index}.png"
            path.write_bytes(self.fixture.fixture.image_path.read_bytes())
            paths.append(path)
        follower = pipeline.read_json(self.content_dir / "page_05.json")
        follower["required_page_assets"] = [
            {"path": str(path), "role": f"evidence_{index}"}
            for index, path in enumerate(paths)
        ]
        pipeline.atomic_write_json(self.content_dir / "page_05.json", follower)
        logo = self.project_dir / "logo.png"
        logo.write_bytes(self.fixture.fixture.image_path.read_bytes())
        with mock.patch.object(
            control.pc,
            "read_global_chrome_contract",
            return_value=(dummy_chrome, {}, "chrome-sha"),
        ), mock.patch.object(
            control.pc,
            "global_chrome_projection",
            return_value={
                "applies": True,
                "main_title_required": False,
                "logo_asset": {"path": str(logo), "role": "global_chrome_logo"},
            },
        ):
            counts = control.validate_follower_attachment_budget(
                self.state_path,
                pipeline.read_json(self.state_path),
                self.project_dir,
                self.content_dir,
            )
        self.assertEqual(counts["A/05"], 5)

    @unittest.skipUnless(NODE.is_file(), "node is unavailable")
    def test_rendered_stub_runs_twelve_tasks_as_one_dynamic_dag(self) -> None:
        action = control.render_action(self.state_path, self.content_dir)
        self.assertTrue(action.startswith("(async () => {"))
        self.assertIn("Promise.race", action)
        self.assertNotIn("spawn_agent", action)
        harness = f'''
let preparedOnce=false, activeTasks=new Set(), ready=[], settled=new Set(), receiptKeys=new Map(), itemsByKey=new Map();
let calls=0, releaseCalls=0, rpcActive=0, peak=0, anchorSettled=new Set(), followerBeforeAnchor=false;
const makeItem=(style,page)=>({{style,page_id:page,action:page==="02"?"generate_anchor":"generate_follower",attempt:1,task_key:`${{style}}/${{page}}/${{page==="02"?"generate_anchor":"generate_follower"}}/1`,prompt:`prompt-${{style}}-${{page}}`,referenced_image_paths:[]}});
const takeWave=()=>{{
  if(!preparedOnce){{preparedOnce=true;const items=[...[..."ABCD"].map(s=>makeItem(s,"02"))];for(const item of items){{activeTasks.add(item.task_key);itemsByKey.set(item.task_key,item);}}return items;}}
  const room=5-activeTasks.size, items=ready.splice(0,room);for(const item of items){{activeTasks.add(item.task_key);itemsByKey.set(item.task_key,item);}}return items;
}};
const keyFrom=(cmd)=>(cmd.match(/--task-key '([^']+)'/)||[])[1];
const receiptFrom=(cmd)=>(cmd.match(/--receipt '([^']+)'/)||[])[1];
globalThis.tools={{
  exec_command:async(req)=>{{
    const cmd=req.cmd;
    if(cmd.includes("prepare-next")){{const items=takeWave();if(items.length)return {{exit_code:0,output:JSON.stringify({{status:"started",manifest_path:"/tmp/manifest.json",tasks:items}})}};if(settled.size===12)return {{exit_code:0,output:JSON.stringify({{status:"complete",completed:12}})}};return {{exit_code:0,output:JSON.stringify({{status:"waiting",active_count:activeTasks.size}})}};}}
    if(cmd.includes("task-input")){{const key=keyFrom(cmd);return {{exit_code:0,output:JSON.stringify(itemsByKey.get(key))}};}}
    if(cmd.includes(" claim "))return {{exit_code:0,output:JSON.stringify({{status:"claimed"}})}};
    if(cmd.includes(" receipt ")){{const key=keyFrom(cmd),path=`/tmp/receipt-${{settled.size}}-${{key[0]}}.json`;receiptKeys.set(path,key);return {{exit_code:0,output:JSON.stringify({{status:"receipt_written",receipt_path:path}})}};}}
    if(cmd.includes(" release ")){{releaseCalls++;return {{exit_code:0,output:'{{"status":"released"}}'}};}}
    if(cmd.includes(" settle ")){{const path=receiptFrom(cmd),key=receiptKeys.get(path);activeTasks.delete(key);settled.add(key);const [style,page]=key.split("/");if(page==="02"){{anchorSettled.add(style);ready.push(makeItem(style,"05"),makeItem(style,"08"));}}return {{exit_code:0,output:'{{"status":"settled"}}'}};}}
    return {{exit_code:1,output:"unknown command"}};
  }},
  image_gen__imagegen:async(input)=>{{calls++;rpcActive++;peak=Math.max(peak,rpcActive);const parts=input.prompt.split("-");if(parts[2]!=="02"&&!anchorSettled.has(parts[1]))followerBeforeAnchor=true;await new Promise(r=>setTimeout(r,3));rpcActive--;return {{output_hint:`/tmp/exec-${{calls}}.png`}};}}
}};
let finalText="";globalThis.text=value=>{{finalText=String(value)}};
const action={json.dumps(action)};
(async()=>{{await eval(action);process.stdout.write(JSON.stringify({{calls,releaseCalls,peak,followerBeforeAnchor,finalText}}));}})().catch(error=>{{console.error(error);process.exit(1)}});
'''
        with tempfile.TemporaryDirectory(prefix="four_by_three_node_") as tmp:
            path = Path(tmp) / "stub.mjs"
            path.write_text(harness, encoding="utf-8")
            run = subprocess.run(
                [str(NODE), str(path)], text=True, capture_output=True, timeout=30
            )
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["calls"], 12)
        self.assertEqual(result["releaseCalls"], 12)
        self.assertLessEqual(result["peak"], 5)
        self.assertFalse(result["followerBeforeAnchor"])
        self.assertEqual(json.loads(result["finalText"])["completed"], 12)

    @unittest.skipUnless(NODE.is_file(), "node is unavailable")
    def test_runner_drains_inflight_tasks_before_raising_prepare_error(self) -> None:
        action = control.render_action(self.state_path, self.content_dir)
        harness = f'''
const seats=[..."ABCD"].map(style=>({{style,page_id:"02",action:"generate_anchor",attempt:1,task_key:`${{style}}/02/generate_anchor/1`,prompt:`prompt-${{style}}`,referenced_image_paths:[]}}));
let prepareCalls=0, settled=0;const receipts=new Map();
const keyFrom=cmd=>(cmd.match(/--task-key '([^']+)'/)||[])[1];
const receiptFrom=cmd=>(cmd.match(/--receipt '([^']+)'/)||[])[1];
globalThis.tools={{
  exec_command:async req=>{{const cmd=req.cmd;
    if(cmd.includes("prepare-next")){{prepareCalls++;if(prepareCalls===1)return {{exit_code:0,output:JSON.stringify({{status:"started",manifest_path:"/tmp/m.json",tasks:seats}})}};return {{exit_code:1,output:"follower attachment validation failed"}};}}
    if(cmd.includes("task-input"))return {{exit_code:0,output:JSON.stringify(seats.find(x=>x.task_key===keyFrom(cmd)))}};
    if(cmd.includes(" claim "))return {{exit_code:0,output:'{{"status":"claimed"}}'}};
    if(cmd.includes(" receipt ")){{const path=`/tmp/r-${{keyFrom(cmd)[0]}}.json`;receipts.set(path,keyFrom(cmd));return {{exit_code:0,output:JSON.stringify({{status:"receipt_written",receipt_path:path}})}};}}
    if(cmd.includes(" release "))return {{exit_code:0,output:'{{"status":"released"}}'}};
    if(cmd.includes(" settle ")){{if(receipts.has(receiptFrom(cmd)))settled++;return {{exit_code:0,output:'{{"status":"settled"}}'}};}}
    return {{exit_code:1,output:"unknown"}};
  }},
  image_gen__imagegen:async input=>{{const slow=!input.prompt.endsWith("A");await new Promise(r=>setTimeout(r,slow?20:1));return {{output_hint:"/tmp/exec-00000000-0000-0000-0000-000000000001.png"}};}}
}};
globalThis.text=()=>{{}};const action={json.dumps(action)};
(async()=>{{try{{await eval(action)}}catch(error){{process.stdout.write(JSON.stringify({{settled,error:String(error)}}));}}}})();
'''
        with tempfile.TemporaryDirectory(prefix="four_by_three_drain_") as tmp:
            path = Path(tmp) / "drain.mjs"
            path.write_text(harness, encoding="utf-8")
            run = subprocess.run(
                [str(NODE), str(path)], text=True, capture_output=True, timeout=30
            )
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["settled"], 4)
        self.assertIn("follower attachment validation failed", result["error"])

    @unittest.skipUnless(NODE.is_file(), "node is unavailable")
    def test_runner_drains_other_rpcs_after_one_task_control_error(self) -> None:
        action = control.render_action(self.state_path, self.content_dir)
        harness = f'''
const seats=[..."ABCD"].map(style=>({{style,page_id:"02",action:"generate_anchor",attempt:1,task_key:`${{style}}/02/generate_anchor/1`,prompt:`prompt-${{style}}`,referenced_image_paths:[]}}));
let prepared=false, settled=0, released=0;const receipts=new Map();
const keyFrom=cmd=>(cmd.match(/--task-key '([^']+)'/)||[])[1];
const receiptFrom=cmd=>(cmd.match(/--receipt '([^']+)'/)||[])[1];
globalThis.tools={{
  exec_command:async req=>{{const cmd=req.cmd;
    if(cmd.includes("prepare-next")){{if(!prepared){{prepared=true;return {{exit_code:0,output:JSON.stringify({{status:"started",manifest_path:"/tmp/m.json",tasks:seats}})}};}}return {{exit_code:0,output:'{{"status":"waiting"}}'}};}}
    if(cmd.includes("task-input"))return {{exit_code:0,output:JSON.stringify(seats.find(x=>x.task_key===keyFrom(cmd)))}};
    if(cmd.includes(" claim "))return {{exit_code:0,output:'{{"status":"claimed"}}'}};
    if(cmd.includes(" receipt ")){{const key=keyFrom(cmd);if(key.startsWith("A/"))return {{exit_code:1,output:"receipt write failed"}};const path=`/tmp/r-${{key[0]}}.json`;receipts.set(path,key);return {{exit_code:0,output:JSON.stringify({{status:"receipt_written",receipt_path:path}})}};}}
    if(cmd.includes(" release ")){{released++;return {{exit_code:0,output:'{{"status":"released"}}'}};}}
    if(cmd.includes(" settle ")){{if(receipts.has(receiptFrom(cmd)))settled++;return {{exit_code:0,output:'{{"status":"settled"}}'}};}}
    return {{exit_code:1,output:"unknown"}};
  }},
  image_gen__imagegen:async input=>{{await new Promise(r=>setTimeout(r,input.prompt.endsWith("A")?1:20));return {{output_hint:"/tmp/exec-00000000-0000-0000-0000-000000000001.png"}};}}
}};
globalThis.text=()=>{{}};const action={json.dumps(action)};
(async()=>{{try{{await eval(action)}}catch(error){{process.stdout.write(JSON.stringify({{settled,released,error:String(error)}}));}}}})();
'''
        with tempfile.TemporaryDirectory(prefix="four_by_three_task_drain_") as tmp:
            path = Path(tmp) / "task_drain.mjs"
            path.write_text(harness, encoding="utf-8")
            run = subprocess.run(
                [str(NODE), str(path)], text=True, capture_output=True, timeout=30
            )
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["settled"], 3)
        self.assertEqual(result["released"], 4)
        self.assertIn("receipt write failed", result["error"])


class FourByThreeCanonicalEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FourByThreeDirectorMethodTest(
            "test_three_director_merge_and_family_projection_reach_followers"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.state_path = self.fixture.fixture.state_path
        self.project_dir = self.fixture.fixture.root
        state = pipeline.read_json(self.state_path)
        state.pop("source_snapshot_path", None)
        state.pop("source_snapshot_sha256", None)
        pipeline.atomic_write_json(self.state_path, state)
        _state, _project, self.paths = control.canonical_paths(
            self.state_path, require_three_director_method=False
        )
        self.paths["source_packet"].write_text(
            "# Frozen P02/P05/P08\n", encoding="utf-8"
        )
        pipeline.atomic_write_json(
            self.paths["snapshot_source"],
            {
                "four_by_three_snapshot_source_version": 1,
                "page_order": ["02", "05", "08"],
                "pages": {
                    page: {
                        "page_id": page,
                        "normalized_source": f"页面 {page} 的冻结权威来源",
                    }
                    for page in ("02", "05", "08")
                },
            },
        )

    def test_prepare_directors_derives_every_path_from_state(self) -> None:
        result = control.prepare_director_inputs(self.state_path)
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["style_job_count"], 4)
        self.assertEqual(result["executor_agents"], 1)
        self.assertEqual(result["imagegen_capacity"], 5)
        self.assertTrue((self.project_dir / "state" / "source_snapshot.json").is_file())
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["fast4x3_candidate_policy"]["version"], 3)
        action = control.render_action(self.state_path)
        self.assertNotIn("content-contract-dir", action)

    def test_prepare_directors_rejects_bad_initial_timing_before_writing_jobs(self) -> None:
        state = pipeline.read_json(self.state_path)
        state["timing"] = {
            "process_started_at": "2026-08-07T04:58:22.268454+08:00",
            "preflight_resolved_at": "2026-08-07T04:58:22+08:00",
        }
        pipeline.atomic_write_json(self.state_path, state)

        result = control.prepare_director_inputs(self.state_path)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_stage"], "precheck")
        self.assertIn("时间倒序", result["error"])
        self.assertEqual(result["style_job_count"], 0)
        self.assertFalse((self.project_dir / "state" / "source_snapshot.json").exists())
        self.assertFalse(list((self.project_dir / "style_jobs").glob("style_[A-D].json")))

    def test_failed_zero_job_prepare_rolls_back_new_source_snapshot(self) -> None:
        visual = pipeline.read_json(self.paths["visual_system"])
        visual["layout_portfolio"]["styles"]["B"]["craft_axis"] = visual[
            "layout_portfolio"
        ]["styles"]["A"]["craft_axis"]
        pipeline.atomic_write_json(self.paths["visual_system"], visual)
        result = control.prepare_director_inputs(self.state_path)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["style_job_count"], 0)
        self.assertTrue(result["source_snapshot_rolled_back"])
        self.assertFalse((self.project_dir / "state" / "source_snapshot.json").exists())
        state = pipeline.read_json(self.state_path)
        self.assertNotIn("source_snapshot_path", state)
        self.assertNotIn("source_snapshot_sha256", state)

    def test_merge_rejects_a_director_file_from_another_path(self) -> None:
        outside = self.project_dir / "content_bundle_copy.json"
        outside.write_bytes(self.paths["content_bundle"].read_bytes())
        with self.assertRaisesRegex(SystemExit, "规范路径"):
            control.merge4x3.merge_bundle(
                state_path=self.state_path,
                content_bundle_path=outside,
                assets_bundle_path=self.paths["assets_bundle"],
                visual_system_path=self.paths["visual_system"],
                content_output_dir=self.paths["content_dir"],
                layout_output_path=self.paths["layout_portfolio"],
            )


class FourByThreeFinalizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FourByThreeDirectorMethodTest(
            "test_three_director_merge_and_family_projection_reach_followers"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.state_path = self.fixture.fixture.state_path
        self.project_dir = self.fixture.fixture.root
        self.content_dir = self.fixture.fixture.content_dir
        self.original_generated_root = control.pc.GENERATED_IMAGES_ROOT
        control.pc.GENERATED_IMAGES_ROOT = self.project_dir.resolve()
        self.addCleanup(
            lambda: setattr(
                control.pc, "GENERATED_IMAGES_ROOT", self.original_generated_root
            )
        )
        for event in (
            "process_started",
            "preflight_decision_received",
            "preflight_resolved",
        ):
            pipeline.run_record_event_silently(
                state=str(self.state_path),
                event=event,
                style=None,
                page_id=None,
                action=None,
                timestamp=pipeline.now_iso(),
                details_json="{}",
            )
        self.fixture.merge_inputs()
        pipeline.create_source_snapshot(
            project_dir=self.project_dir,
            state_path=self.state_path,
            source_path=self.fixture.fixture.source_path,
            page_ids=["02", "05", "08"],
            content_contract_paths=[
                self.content_dir / f"page_{page}.json"
                for page in ("02", "05", "08")
            ],
            asset_items=[],
            timestamp=pipeline.now_iso(),
        )
        self.fixture.fixture.prepare_anchors()

    def test_twelve_candidates_finalize_to_overview_and_handoff(self) -> None:
        source_bytes = self.fixture.fixture.image_path.read_bytes()
        generated = 0
        while True:
            prepared = control.prepare_next(self.state_path)
            if prepared["status"] == "complete":
                break
            self.assertEqual(prepared["status"], "started", prepared)
            manifest = Path(prepared["manifest_path"])
            for item in prepared["tasks"]:
                control.claim(self.state_path, manifest, item["task_key"], 0)
                generated += 1
                image = self.project_dir / f"exec-{uuid.uuid4()}.png"
                image.write_bytes(source_bytes + generated.to_bytes(2, "big"))
                now = pipeline.now_iso()
                receipt = control.write_receipt(
                    self.state_path,
                    manifest,
                    item["task_key"],
                    {
                        "savedPath": str(image),
                        "tool_started_at": now,
                        "tool_finished_at": now,
                        "error": None,
                    },
                )
                control.settle_receipt(
                    self.state_path, Path(receipt["receipt_path"])
                )
        self.assertEqual(generated, 12)
        result = control.lean_finalize(self.state_path)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["validate_state"], "pass", result)
        self.assertTrue(Path(result["overview"]).is_file())
        self.assertTrue(Path(result["handoff"]).is_file())
        state = pipeline.read_json(self.state_path)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["scheduler"]["phase"], "completed")
        self.assertEqual(len(result["formal_candidates"]), 12)


if __name__ == "__main__":
    unittest.main()
