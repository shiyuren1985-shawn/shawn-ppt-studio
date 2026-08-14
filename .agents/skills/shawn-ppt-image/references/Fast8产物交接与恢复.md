# Fast8 产物交接与恢复

只在 Fast8 图片工具开始返回后读取。目标是让“图片已生成”立即变成可结算的文件绑定，不等待模型文字。控制面 v1 优先执行下述原子闭环；后文标有“旧 Worker”的段落只用于历史 ticket 恢复。

## 控制面 v1：同次调用原子闭环

根任务在唯一固定 `functions.exec` 中启动八个 async 分支。每席必须且只能完成：

1. `claim` 验证当前页、唯一 ticket、job SHA、图片输入指纹并取得既有全局 JIT 槽位；
2. 逐字调用该席正式 `imagegen_prompt` 与 `imagegen_referenced_paths`；
3. 从同次工具结果取得唯一绝对 `savedPath`，立即由脚本验证文件、16:9、工具 ID 和 job 身份并原子写 receipt；
4. 在 receipt 或 `finally` 中幂等 release；
5. 由 `Promise.allSettled` 隔离失败，禁止一席失败取消其他席位。

八个分支结束后运行一次 `fast8_control_plane_v1.py settle --state ...`。有效成功 receipt 直接进入现有结算；明确 `backend_network|backend_failed` 跳过产物恢复，按既有预算排一次技术重试；只有 `completed` 但 `savedPath/receipt` 缺失或不可解析时，输出 `session_forensics_required_styles` 并进入无生图恢复。正常路径不查询 UUID、不扫描 session、不等待模型文字、不从 `.jsonl` 找路径，也不维护 session/receipt/PNG 三套成功证据。

duplicate claim、错页、错 job 或输入指纹变化直接拒绝，不再次生图。输出继续区分 `candidate_bound_styles|settled_styles`、`recovery_pending_styles`、`retry_pending_styles` 与 `session_forensics_required_styles`；不得把失败回执报告成候选已结算。

## 旧 Worker ticket：同次调用机器回执

旧 Fast8 Worker 必须在同一个 `functions.exec` 中完成：

1. `await imagegen`；
2. 只在同一次机械调用内部解析 `result` 的 `savedPath|output_hint`；严禁调用 `generatedImage(result)`、`image(...)` 或向任何 Codex 对话交接图片块；
3. 立即从 `result.output_hint|savedPath` 取得绝对路径；如果返回的是说明句，只抽取其中唯一的 `/.../exec-<UUID>.png` 路径子串并验证文件存在，不把整句当路径或工具 ID；
4. 把真实工具结果传给 `pipeline_control.py write-fast8-worker-receipt`，由脚本按 job 内唯一合同验证 session/job/图片身份、规范化时间并原子写入小型 JSON 回执；禁止 Worker 用 `apply_patch`、shell 重定向或自由文本拼 JSON。工具 completed 但路径缺失时由脚本写 `failure_class=artifact_missing`，工具本身 failed/network error 时写 `failure_class=backend_failed|backend_network`；
5. 用 `text(...)` 返回相同的最小绑定 JSON。

Worker 启动门默认最多等待主控 90 秒完成真实 session/runtime 绑定；这只是两次工具调用之间的控制面竞态缓冲，不延后已生成图片的结算，也不改变 ImageGen 输入。

回执只包含路径、工具调用标识、起止时间、失败分类和 job 身份，不含图片、Base64、提示词或日志。它是审计和失败分类通道，不是成功产物的等待门；准确 session 中的唯一标准 PNG 可先于回执直接结算。

## 旧 Worker ticket：即到即结算

派发后立即运行 `settle-fast8-receipts --state ... --wait-seconds 60 --poll-interval 2`；每次最多等 60 秒，未齐就继续短轮询并保持用户可见进度。哪些席位先写回执，就先结算哪些席位，不等 Worker 最终文字，也不需要模型手工拼本波结果 JSON。控制器依次尝试：

1. 派发后正式绑定的真实 `worker_session_id`：只检查 `generated_images/<worker_session_id>/`，目录内恰有一个且写入时间不早于本次派发的标准 `exec-*.png` 时，直接作为 `worker_session_dir` 结算；回执尚未出现也不等待；
2. Worker 最终结果里的可读绝对 `savedPath`；
3. 与正式 job、job SHA 和工具指纹匹配的唯一 `worker_receipt`；控制器也会安全解析说明句中的唯一标准 `exec-*.png`，仅接受实际存在且位于 Codex `generated_images` 根下的嵌入路径；
4. 只有工具已经 completed 且 session、最终结果和回执都没有唯一可读产物时，才进入无生图只读恢复。

真实 Worker session 是恢复路径的前置身份证据；新 ticket v2 还必须同时存在与正式合同一致的 Worker 模型、reasoning effort 和 fork turns 绑定。若缺少合规绑定，且回执也未提供可验证的成功文件或明确后端失败，控制器返回 `worker_session_binding_required` 并停止本轮结算；先补 `bind-fast8-worker-sessions`，不得把流程绑定缺失伪装成图片产物丢失。历史 ticket v1 仍按原 session 合同恢复。

有效成功回执直接绑定文件。`tool_status=completed` 的产物缺失才清除原 active action 并进入恢复队列；`tool_status=failed` 且 `failure_class=backend_network|backend_failed` 时跳过产物恢复，释放全局 ImageGen 槽位，并按既有预算排一次技术重试。`settle-fast8-receipts` 只要返回非空 `retry_pending_styles`，主控就立即对当前 ready 集合执行 `record-dispatch-wave` 和 burst Worker 创建；本轮输入已在首次正式派发锁定，不再重复读取、哈希或检查 frozen packet、合同和资产。不得等待其余首轮席位、未来失败或 A–H 齐结算。JIT 全局上限继续控制真实生图在途，因此提前创建重试不会突破容量或改变任何图片输入。若只有部分席位就绪，后续继续调用同一命令；结果文件幂等落盘，不重复结算。

命令输出必须区分 `processed_styles`、真正已有候选的 `candidate_bound_styles|settled_styles`、`recovery_pending_styles` 和 `retry_pending_styles`；不得把已经处理但转入恢复或重试的失败回执报告成“图片已结算”。

图片已完成且存在可读路径时，不得因为缺少普通文字总结而进入恢复。真实 Worker session UUID 与唯一会话目录是确定性身份证据，不是按时间猜最新文件。Fast8 仅缺工具 ID 或时间元数据时，控制器可从标准文件名、派发边界和文件时间确定性补齐并标记 fallback；其他模式维持原严格元数据合同。

候选从 session 目录结算后可以立即进入 Judge，但不要为了结束文字长尾而中断仍在同一个 `functions.exec` 中写回执的 Worker。Judge 与这些尾部回执并行；`finalize-fast8` 会在不等待、不改变候选的前提下，用完整且身份、job、工具与图片均一致的迟到回执替换控制器推导的时间元数据。图片文件可能在 ImageGen RPC 返回前已对 session 目录可见，因此文件验证和工具/回执完成是两条并行观测：不要求 `tool_finished_at` 或 `agent_action_finished_at` 早于 `file_validated_at`，但两条支路都必须晚于本次 `agent_action_started_at` 并早于正式收口。回执仍缺失或不合规时保留技术警告，不用隐藏或补造。

## 无生图恢复

只有路径真正缺失、不是绝对路径或不可读时，才标记 `artifact_handoff_unresolved`：

- 立即向原 Worker 发起 `recover_artifact`，禁止再次调用 ImageGen；
- 只要准确工具时间窗或准确会话目录已知，可同时运行 `scripts/recover_image_artifact.py`，无需等待固定 45 秒；
- 两条路径都是只读恢复，先得到唯一合法绑定的一方获胜，迟到结果只作审计，不得重复结算；
- 不得按“最新文件”猜测，也不得让根任务打开或整段读取原始 `.jsonl`；
- `ambiguous` 继续恢复；同一动作/尝试先后得到 `same_worker:not_found` 与 `deterministic_script:not_found` 两份独立证据后，才允许一次技术重试。

恢复与重试采用流式就绪批次并发：每次结算后，把当下已经 ready 的 recovery 或 retry 任务合并派发一次；不同轮次新出现的 ready 集合继续增量派发。不得为等待更大的批次设置首轮齐备屏障，也不得为每个席位机械串行重复控制步骤。

新 Fast8 首次正式派发后不再检查原大纲、frozen packet、内容合同或资产是否变化；技术重试和差异替代继续使用已经锁定的 generation job。用户后续改稿只影响下一次新运行，不让当前图片任务返工。

恢复成功以 `action=recover_artifact` 结算，并保留原 `source_action`、图片工具时间、恢复时间和 `recovery_method`。恢复不增加图片 `attempt_count`。只有新的 ImageGen 调用才计尝试。绑定 session 的唯一 PNG 已经结算后，迟到或缺失的 Worker 回执只属于后台遥测；不得在 `finalize-fast8` 或用户回复前同步补齐。

每个生成 attempt 使用独立的 `worker_receipt_path`。技术重试即使复用 immutable 初始 generation job 的提示与输入，也必须使用 dispatch ticket 返回的 attempt 专属回执路径，禁止覆盖 attempt_1 回执。

技术重试成功时，控制器必须以新 attempt 的 Worker、工具和文件时间覆盖当前计时字段，第一次失败只保留在 `attempt_history`；不得让旧 `tool_started_at|tool_finished_at|failure_reason` 污染成功候选和健康报告。

任一必需席位在无 incumbent 的情况下耗尽技术重试后，当前 run 已不可完成。控制器必须原子设为 `blocked`、关闭调度队列并释放所有在途租约；先完成旧 run 终止登记，之后只有在上层任务仍明确要求完成时才可新建一份干净运行。禁止旧运行继续占槽位，也禁止旧、新两份同时生图。

## 长尾判断

图片后端时间、根任务机械分支时间、文件绑定时间分别记录。图片已落盘后的模型长回合不得归因给 ImageGen。控制面 v1 正常路径只认同次调用的 `ticket → savedPath → receipt`，不等待文字、不扫描 session、不做三路重复取证；只有 `completed` 但 `savedPath/receipt` 异常时才启动 session 取证。明确 backend failed 直接按既有预算路由技术重试，不先做产物恢复；已存在有效 receipt 的 ticket 不得重复生图。
