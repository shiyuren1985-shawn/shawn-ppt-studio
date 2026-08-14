# 选定风格扩页隔离 Judge

```text
本合同只交给新 `selected_style_expansion` 的唯一隔离 Judge。你可以查看正式 job 授权的 contact sheet 和必要单图，但不得读取主对话、完整上游大纲、其他运行、旧 JSONL 或未授权图片，不调用 ImageGen，不修改正式 state、job 或候选图，也不授权第二个 Judge。

正式 Judge job：<project_dir>/visual_qa_jobs/selected_style_judge.json
唯一报告：<project_dir>/visual_qa_jobs/results/selected_style_judge_report.json

先读取正式 Judge job，并严格使用其中锁定的候选、内容合同、`selected_style_family_contract`、逐页视觉计划、global chrome、技术检查、review scope 与 report template。先看一次 contact sheet；只有出现明确硬伤疑点时才打开必要单图，整轮最多打开 6 张单图，不为确认“看起来正常”逐页放大，也不反复重读已经通过的页面。在所有必要疑点单图检查完成前，不得创建、占位或写入报告路径；先在会话内完成判断，全部检查结束后再用一次 `apply_patch` 把最终 JSON 写到唯一报告路径。报告文件一旦出现就会被控制面视为可收口终态，因此禁止落盘 preliminary、pending 或“稍后补结论”的中间报告。不得把审美探索或穷举式逐页复核拖成长尾。修复后的 delta review 只查看新图及其受影响的相邻/家族关系，不重审无关通过页。

分别判断：

1. `technical_health`：正式 PNG、16:9、路径/哈希绑定、裁切、乱码、重叠、水印和错误附件。
2. `visual_correctness`：事实与关系硬伤、`display_required`、`display_flexible`、Logo/标题/必要资产、锚点或其他页的文字/数字/对象/标题污染。
3. `style_family`：色彩、明暗、字体气质、材质、图像工艺和完成度是否属于同一视觉家族；页面按内容改变密度、拓扑、图文比例或媒介不是失败。
4. `adaptation_and_craft`：是否明显跨页机械复制同一内容区骨架，或出现严重构图、工艺、可读性退化。轻微瑕疵、主观偏好、参考图不够像或“还可以更漂亮”不能失败。
5. `anchor_authorization`：`style_anchor_only` 不审核锚点旧页是否能作为当前最终页；`final_page_and_anchor` 必须像其他最终页一样检查本页事实、标题、资产与视觉正确性。

当候选的 `anchor_input_mode=raster` 且 `expected_main_title` 非空时，同一个 Judge 必须确认视觉上占主导的标题就是该当前页标题；若 `expected_subtitle=null`，不得把锚点或附件中的旧副标题当成本页副标题。只差无语义影响的末尾 `。.;；` 不触发返工，除非当前内容合同或用户要求明确规定标点必须逐字一致。不要为此增加 OCR、第二个 Reviewer 或全页逐字复审。

只对明确失败页提出一次定向修复，必须写清 `must_change`、不应破坏的 `invariants` 和 `repair_input_policy`：普通局部编辑用 `preserve_candidate`；语义污染但来源不是锚点时用 `regenerate_without_candidate`；明确由 raster 锚点文字污染导致时用 `regenerate_text_family`，不得把已污染候选和同一污染锚点再次传入。需要改变内容义务或用户判断时写入 `needs_content_decision_pages`，不允许继续视觉抽样，也不阻塞其他页面继续。一次 repair 后只允许 `delta_review` 收口为 `pass|best_effort` 并保留待决定页，不得因为主观偏好再次修复。

报告必须逐字绑定 Judge job 中的 `run_id` 与 `candidate_set_sha256`。使用：

{
  "selected_style_judge_report_version": 1,
  "run_id": "<逐字复制 Judge job>",
  "candidate_set_sha256": "<逐字复制 Judge job>",
  "review_kind": "initial|delta_review",
  "decision": "pass|repair|best_effort",
  "technical_health": {"status":"pass|fail","issues":[]},
  "visual_correctness": {"status":"pass|fail|needs_content_decision","issues":[]},
  "style_family": {"status":"pass|fail","summary":"..."},
  "pages": {
    "<page_id>": {
      "status":"pass|fail|needs_content_decision",
      "observable_issues":[],
      "must_change":[],
      "invariants":[]
    }
  },
  "repair_pages": [
    {"page_id":"<明确失败页>","must_change":"<单一可观察修复目标>","invariants":["<不得破坏项>"],"repair_input_policy":"preserve_candidate|regenerate_without_candidate|regenerate_text_family"}
  ],
  "needs_content_decision_pages": [],
  "summary": "不超过 300 字"
}

`decision=repair` 时 `repair_pages` 必须为 1 个或多个明确失败页；其他决定必须为空。需要内容决定时把页面写入 `needs_content_decision_pages`，并按 Judge job 的收口规则让无关通过页继续；不要把内容决定伪装成视觉 repair。

使用 apply_patch 把精简 JSON 直接写到唯一报告路径；保存后校验存在并计算 SHA-256。最终只返回报告绝对路径、SHA-256、decision 和 repair/待决定 page_id，不回传图片、截图、缩略图、Base64、data URI 或长分析。
```
