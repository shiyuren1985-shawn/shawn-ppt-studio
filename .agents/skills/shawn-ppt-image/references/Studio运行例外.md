# Studio 运行例外

只在 application/developer context 明确包含 `transport=studio_app_server_v1` 时应用本文件。没有该精确 transport 标记的普通 Codex 主对话、CLI 或其他 App Server 调用继续使用图片执行子 Agent。

## Fast8

- 允许 Studio 根 turn 作为本轮唯一机械图片执行者，逐字提交 `prompts/fast8-burst-runner.md` 的 canonical `prepare --render-action` wrapper，并显式 `await eval(action)`。
- 若已经创建唯一图片执行子 Agent，仅在其 `started` 后连续 180 秒没有任何 `interacted`、command/tool activity 或中央 claim，或宿主明确报告不能直接派发首 turn 时，先中断该空闲子 Agent，再由根 turn 接管同一 wrapper。两种路由不得并存。
- 禁止创建 A–H 逐席会话、第二 runner、第二 semaphore 或第二 Judge；不得改写 locked prompt/reference。
- ImageGen 返回对象只留在 canonical `functions.exec` 局部变量中。禁止调用 `generatedImage(...)`、`image(...)`、打开候选或把图片块带回对话；只接收路径、receipt/settle 摘要和状态。
- 中央 cap5、`ticket → savedPath → receipt`、唯一 Judge、技术校验和 handoff 合同保持不变。

## 正式 `single_image_edit`

- 让 Studio 根 turn 从开始就是唯一机械 executor，不创建图片执行子 Agent；执行 `prepare → claim → ImageGen exactly once → complete`。
- 只在 ImageGen 明确 failed/cancelled 且没有 completed 结果时执行 `release`。claim 必须复用中央 cap5；`complete/release` 是唯一允许导入新图、写 state/handoff 或释放租约的入口。
- completed 但根 turn 看不到 `savedPath` 时，不得猜路径或 release；返回 host-finalize marker，由宿主把实际观察到的唯一 completed `savedPath` 交给同一个 canonical `complete`。
- 不打开结果，不调用 `generatedImage(...)` 或 `image(...)`，不覆盖父图，不修改 selection，不增加 Judge/Reviewer，不把图片块带回对话。
- 父图同时是本次编辑的视觉定位图；除非用户明确要求改变背景色调，编辑提示必须保持父图的主画布背景 tone，不把单图编辑变成深浅背景重探索。
- 用户额外指定 PDF/PPT/文档页、网页或其他非光栅视觉参考时，先按 `视觉资产解析与冻结.md` 使用 Skill 的共享 materializer；Studio 只负责把上传文件或 URL 交给 Skill，不自行维护第二套转换逻辑。父图本身不转换、不复制。
- 没有精确 transport 标记时，单图修改仍由图片执行子 Agent承载。

## 选稿台联动清理

- Studio 只负责确认用户意图、调用 `scripts/plan_candidate_artifact_cleanup.py`、二次校验路径并执行废纸篓事务；候选与过程文件的归属规则只维护在 Skill。
- 规划器只认正式 state 中仍存在且位于本次运行 `origin_image` 的精确候选路径。未登记图片、状态冲突、越界路径、符号链接或无法唯一识别的运行一律停止，不降级为猜文件名清理。
- 部分删除时，删除候选独占的任务、提示词载体、claim、ticket、receipt 和 repair job；只要该运行还留有任何正式候选，冻结页级合同、state、handoff、source snapshot 与素材必须留下，防止保留候选因共享完整性链断裂而消失。最后一张候选删除时再随整个运行目录一并回收。
- 删除一组候选后可递归移除本次运行内新产生的空目录；不得删除仍包含文件的目录。只有删掉该运行最后一张仍存在的正式候选时，计划才可把整个运行目录作为单一目标。
- Studio 在移动前再次验证所有目标均位于对应运行目录，且任何保留候选都不被目标目录覆盖；移动任一目标失败时，恢复已移动文件和已取消的选择状态。
