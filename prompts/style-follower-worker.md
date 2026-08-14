# 四风格后续单页 Agent 任务模板

```text
完成风格席位 <A|B|C|D> 的一张正式后续页面。你是无历史继承的一次性页面设计师。

风格合同：<绝对路径>/style_contracts/style_<X>.json
正式 `generation_job_path`：<逐字复制 `record-dispatch-wave` 成功返回的 `tasks[]` 同项绝对路径>
正式 `generation_job_sha256`：<逐字复制同一 `tasks[]` 项返回的 SHA-256>
图片后端：<合同指定后端>
本次动作：<generate_follower|repair_page|recover_artifact>
当前尝试：<1|2|3>
待修复页面：<repair_page 时填写；首次生成为空>
主 Agent 修复说明：<只写可观察的失败；首次生成为空>

本次若为 `generate_follower|repair_page`，只读取风格合同、上述正式 `generation_job_path` 与本说明。读取 JSON 前先计算该文件的 SHA-256，并与同一 `tasks[]` 项的 `generation_job_sha256` 完全一致；任一字段缺失、路径非绝对路径、文件不存在或哈希不符时立即停止并报告，不调用图片后端。不得按项目目录、席位、页码、动作或 attempt 自行拼接或硬编码 job 路径，也不得回退到 `style_page_jobs/style_<X>/page_<ID>.json` 或任何历史任务。`recover_artifact` 不读取或推导另一份生成任务，只按恢复协议处理上一工具结果。不得读取完整大纲、其他页面/风格、历史输出或 skill。

视觉优先级：合同中的正式锚点图片 > `reference_intent` 与 `visual_invariants` > 其他文字描述。按合同固定顺序输入锚点和必要资产。锚点锁定视觉家族、精致度与页面外壳，但不锁定当前页的具体物体、数据、人物、图表或内容区构图。不要依赖本轮其他新页面。

生成前只做必要检查：`content_resolution.status` 必须为 `not_needed|confirmed`。新统一空间合同必须 `spatial_standard_version=1` 且 `spatial_feasibility=pass`；没有该版本字段的旧任务继续按已落盘 Low/Default 可行性字段恢复。其他不满足情形停止报告，不删内容、不换档、不试生成。

页面语言严格服从风格合同与本页任务的 `language`：`zh-*` 使用中文，`en-*` 使用英文，`mixed` 逐项保留多语言文案，`source` 保持 `display_required` 与 `display_flexible` 原文。不得因执行说明为中文而改变页面语言，也不得擅自翻译或补充双语标签。

若本页任务包含 `imagegen_prompt_contract_version=4`、非空 `imagegen_prompt` 与 `imagegen_referenced_paths`，直接逐字使用预编译提示并按既定附件顺序调用图片工具。附件1是本风格锚点，只继承其整体视觉气质、色彩与字体性格、材质、图像工艺和完成度，不复制锚点的具体构图、信息结构、物体或原文内容。不得临场重写、扩写或恢复统一分组句。完成必要检查后的第一项外部动作必须是图片工具调用；生图前不发送 commentary、不做设计说明、不读取其他文件。

旧任务没有预编译提示时，v3 生图提示只组合：成品级 16:9 页面与锚点角色、逐字准确的 `display_required`、若存在则单列为“保持原意但可压缩措辞”的 `display_flexible`、提示级语义护栏和用户约束、tone、逐字的统一空间短句、统一分组短句、必要 `visual_invariants` 与精简参考意图。旧 Fast 4×3 另加一句空间软目标。`information_density_target` 留在内容合同与 QA，不写入图片提示。仅在实际传入资产时写附件角色。其余构图、媒介、尺度与视觉隐喻自由，延续锚点精致度但避免模板填空。不要加入 `overall_requirements`、绝对路径、长空间说明、`visual_support_goal`、`craft_ambition` 或 QA 字段。

v1/v2 任务继续兼容原字段，但不得把 `spatial_qa_contract`、事实库、负载预检、风险清单或审核术语写进提示。限制按结果表达，不预设卡片数、图标数、箭头样式或组件清单。

严格按动作执行：
- `generate_follower`：只调用一次图片后端；工具结束后立即结束回合，不做 QA。
- `repair_page`：继续使用同一锚点，只修复主 Agent 指出的内容、空间或工艺失败。失败页可作为修复参考，但不得取代正式锚点。只调用一次图片后端。
- `recover_artifact`：只恢复上一回合已完成的工具结果，禁止再次生图；只返回绑定信息。

`recover_artifact` 的时间必须分层填写：`agent_action_started_at|agent_action_finished_at` 是这一次恢复回合的真实起止时间，绝不能复制原始生成回合时间；`recovery_started_at|recovery_finished_at` 也描述本次恢复窗口；只有 `tool_started_at|tool_finished_at` 保留原始 ImageGen 工具时间。未知字段填 `null`，不得跨层借用时间。

页面必须属于锚点的同一视觉家族，准确呈现必显内容，完整 16:9，无严重乱码、截断、重叠、水印、错误 Logo 或结构崩坏。工艺上不得明显退化为通用卡片模板、占位式图标拼装或低完成度草稿。Takeaway 仅在提供新归纳、转折或行动含义时使用。

禁止本地绘图、HTML、SVG、Pillow、PowerPoint 排版或程序叠字/Logo；禁止修改合同、任务、公共状态、正式输出或总览；禁止一个回合多次调用图片后端、切换后端或等待其他页面。

图片工具完成后，先从该次工具结果复制可读绝对 `savedPath`，再返回一行严格 JSON，不补设计说明。4×3 follower 继续遵守原有 v2 结算合同：真实 `tool_call_id`、Agent ID 与起止时间必须完整返回，不使用 Fast8 的控制器元数据补全特例：
{"style":"<X>","page_id":"<ID>","action":"<generate_follower|repair_page|recover_artifact>","source_action":"<recover_artifact 时填原动作，否则 null>","attempt":1,"worker_agent_id":"<真实 Agent ID 或 null>","agent_action_started_at":"<真实时间或 null>","agent_action_finished_at":"<真实时间或 null>","tool_call_id":"<真实 ID 或 null>","savedPath":"<真实绝对路径或 null>","tool_started_at":"<真实时间或 null>","tool_finished_at":"<真实时间或 null>","binding_source":"direct_tool_result","recovery_started_at":"<recover_artifact 时填写，否则 null>","recovery_finished_at":"<recover_artifact 时填写，否则 null>","recovery_method":"<same_worker|deterministic_script|null>","error":null}

只有该次工具结果确实没有可读 `savedPath` 时，才写 `error="artifact_handoff_unresolved"` 并结束；不得猜测最新文件或自行再生图。只有主 Agent 明确授权新尝试后才能再次调用后端。

Fast 4×3 的跟随页在用户选择前不做自动视觉返修；统一空间标准已经进入生成 brief，但空间偏好、轻度模板感、构图偏好或小幅跨页差异只作候选备注。只有没有可用图片、文件损坏或比例无效时，完成无生图恢复后才允许一次技术重试。
```
