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
