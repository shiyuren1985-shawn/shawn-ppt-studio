# 风格定位正式锚点 Agent 任务模板

```text
以独立锚点设计师身份完成风格席位 <A|B|C|D|E|F|G|H> 的共同锚点页。它是当前运行中的成品级候选，不是草稿：严格 4×3 用于正式验收，Fast 4×3 与快速 8×1 用于选择前候选。

项目目录：<绝对路径>
新 Fast8 正式 `state`：<绝对路径；其他模式为空>
新 Fast8 正式 `worker_ticket_path`：<逐字复制 `record-dispatch-wave` 返回的 tasks[] 同项 ticket 路径；其他模式为空>
其他模式正式 `generation_job_path`：<绝对路径；新 Fast8 不从自然语言接收>
其他模式正式 `generation_job_sha256`：<SHA-256；新 Fast8 不从自然语言接收>
图片后端：<任务指定后端>
本次动作：<generate_anchor|repair_anchor|recover_artifact>
当前尝试：<1|2|3>
待修复锚点：<repair_anchor 时填写；首次生成为空>
主 Agent 修复说明：<只写可观察的失败；首次生成为空>

本次若为新 Fast8 的 `generate_anchor|repair_anchor`，第一步运行 `python3 "<skill_root>/scripts/pipeline_control.py" check-fast8-worker-ticket --state "<state>" --ticket "<worker_ticket_path>" --wait-for-session-seconds 20 --poll-interval 0.5`。该命令会先等待主控把真实 Worker session 写入正式状态；只有返回 `status=pass` 且 `worker_session_id` 为合法 UUID，才可使用其返回的 `generation_job_path`、SHA、回执路径和图片指纹。超时或校验失败立即停止，不调用图片后端。不得由主 Agent 或 Worker 在自然语言中转抄 64 位 job SHA。

其他模式仍只读取上述正式 `generation_job_path` 与本说明，读取 JSON 前计算 SHA-256 并与任务值完全一致。所有模式任一字段缺失、路径非绝对、文件不存在或哈希不符时都立即停止。不得按项目目录、席位、页码、动作或 attempt 自行拼接或硬编码 job 路径，也不得回退到 `style_jobs/style_<X>.json` 或历史任务。`recover_artifact` 不读取或推导另一份生成任务，只按恢复协议处理上一工具结果。不得读取完整大纲、其他席位、后续页面、历史输出或 skill。A–H 只是当前运行的临时席位，不是固定风格名；实际只处理任务指定的一席。

视觉优先级：用户明确的事实与参考意图 > 任务中与本席位匹配的真实参考图 > 默认经验。只使用任务实际传入的参考图和必要资产，并按任务顺序输入。参考图是核心视觉感觉的高维证据，不是排版模板：借鉴任务中压缩后的整体气质、空间感或图像工艺，不继承具体构图、版式、信息结构、物体、数据、人物或原文内容。若无参考图，则根据内容和 tone 自主建立成熟、有辨识度的视觉方向。

生成前只做必要检查：`content_resolution.status` 必须为 `not_needed|confirmed`。新统一空间合同必须 `spatial_standard_version=1` 且 `spatial_feasibility=pass`；没有该版本字段的旧任务继续按已落盘 Low/Default 可行性字段恢复。其他不满足情形停止报告，不删内容、不换档、不试生成。

页面语言严格服从任务的 `language`：`zh-*` 使用中文，`en-*` 使用英文，`mixed` 逐项保留多语言文案，`source` 保持 `display_required` 与 `display_flexible` 原文。不得因为本说明是中文就把英文页面改成中文，也不得擅自翻译或补充双语标签。

若任务包含 `imagegen_prompt_contract_version` 与非空 `imagegen_prompt`：无论版本号是多少，都直接、逐字使用任务里的 `imagegen_prompt`，并按 `imagegen_referenced_paths` 的既定顺序传入图片工具；不得重新总结、扩写或再次编译提示词。新 Fast8 只允许先运行一次带 session 等待门的 ticket 机器校验；校验和必要读取完成后，第一项外部动作必须是图片工具调用。其他模式仍要求必要读取完成后的第一项外部动作就是图片工具。生图前不发送 commentary、不做设计说明、不读取其他文件。新 `repair_anchor` 的问题和修复边界已经编入提示词，不再追加；只有旧任务未预编译修复说明时才追加主 Agent 的短说明。

新 Fast8 v7 使用 `art_direction_contract_version=1`、`visual_activity_portfolio_version=1` 与 `spatial_topology_portfolio_version=1`：内容合同提供页级 `visual_quality_intent`、`relationship_thesis` 与显式 `flexible_story`，八席分别获得临时且互异的 `visual_thesis`、`craft_axis`、`visual_activity_mode`、`attention_strategy` 与正向空间拓扑意图，并编译进正式图片提示。空间拓扑是粗粒度组合分离，不是像素模板或组件合同。完整 `display_flexible` 与语义护栏继续留在合同和 QA，不由 Worker 再次展开。Worker 不得自行补写、翻译、扩展或读取其他席位来判断差异。已创建旧任务继续按既有预编译提示恢复。无风格参考图的 Fast8 提示仍保留成熟度与视觉签名底线。若任务含 `diversity_replacement`，它是隔离 Judge 授权的一次新探索：逐字使用已编译提示，不把旧候选另行加入附件，不自行判断撞车或最低工艺，也不授权下一轮。

新 Quick8 v5 与新 4×3 v6 必须已有 `imagegen_prompt_contract_version=4` 的预编译提示：`display_required` 逐字准确，`display_flexible` 保持原意且可压缩。新 4×3 使用艺术导演 v1 的页级关系综合、候选级视觉命题与工艺轴；已创建的旧 v6 才继续使用 2–3 个首感席位和 1–2 个开放席位。Quick8 仍保留 4–6 个 `first_impression` 席位与 2–4 个自由席位。参考图只收敛核心感觉，不继承构图；控制文本按页面语言使用中文或英文。Worker 不得自行补写或扩展任何导演字段。

旧任务没有预编译提示词时，页面 v3 提示仍按原合同组合：成品级 16:9 页面、`display_required`、0–3 条 `prompt_semantic_guardrails`、0–3 条 `prompt_user_constraints`、tone、逐字的统一 `spatial_generation_brief`、统一分组短句、精简参考意图和旧席位短方向。`information_density_target` 留在内容合同与 QA，不写入图片提示。quick8 v4 的 `creative_direction` 只作软性启发；具体版式、媒介、材质、细节与图文关系保持开放。仅在实际传入必要资产时写附件角色和原样使用要求。不要加入 `overall_requirements`、母结构、绝对路径、`visual_support_goal`、`craft_ambition` 或任何 QA 字段。

v1/v2 任务继续兼容原字段，但不得把 `spatial_qa_contract`、事实库、负载预检、风险清单或完整审核规则写进提示。`layout_contract_version=5|6` 只执行可选首感，不按首感或具体版式验收；`layout_contract_version=4` 只供旧 Fast/Quick8 恢复并把 `creative_direction` 当作探索建议；旧 v3 恢复任务继续实现其具体变体，更旧 v2 继续按原构图拓扑执行。不得自行增加固定卡片数、图标数、箭头样式、像素位置或组件清单。

两种 4×3 模式下，本锚点都应建立可扩展的视觉家族：背景与材质、字体气质、色彩、图像工艺、页面外壳与精致度清楚，同时给后续页面留下构图自由。Fast 4×3 的每张新图都使用统一空间标准，但不因空间偏好、轻度模板感或主观审美自动重抽；只有明确内容硬伤、无效文件或与另一锚点实质同构时，主 Agent 才可能授权一次定向修复。Fast8 与经典 Quick8 都不创建风格合同或跟随页；Fast8 只接受状态中已经授权的一轮组合裁判替代，经典 Quick8 v5 仍在用户选择前完全不返修。Takeaway 只在语义需要时使用，不固化为每页底栏。

严格按动作执行：
- `generate_anchor`：只调用一次图片后端；工具结束后立即结束回合，不做 QA。
- `repair_anchor`：逐字使用任务已经编译好的定向修复提示与附件顺序，只调用一次图片后端。Fast8 任务含 `diversity_replacement=true` 时，它是离开冗余 incumbent 的新探索：保留内容义务、tone、参考图核心感觉和不冲突的品牌约束，但不得继承 incumbent 的构图或视觉方向，逐字执行 replacement prompt，且不把旧图另作附件。其他模式保留已成立的内容义务与视觉方向；旧任务含 `diversity_repair` 时按其中的正向替代方向执行。
- `recover_artifact`：只恢复上一回合已完成的工具结果，禁止再次生图；直接检查上一工具结果与本 Agent 的准确生成目录，不重新读取完整任务、不展开设计分析，只返回绑定信息。新 Fast8 回执缺失时，主 Agent 可能立即并行启动确定性只读恢复；这不授权本 Worker 停止或重新生图，迟到结果也不得要求重复结算。

`recover_artifact` 的时间必须分层填写：`agent_action_started_at|agent_action_finished_at` 是这一次恢复回合的真实起止时间，绝不能复制原始生成回合时间；`recovery_started_at|recovery_finished_at` 也描述本次恢复窗口，并应落在或等于本次 Agent 回合边界；只有 `tool_started_at|tool_finished_at` 保留原始 ImageGen 工具调用时间。若无法读取某一层真实时间则填 `null`，不得把另一层时间冒充它。

以下回执规则中的工具返回字段，明确指 `result.savedPath` 与 `result.output_hint`。

新 Fast8 正式任务含 `worker_receipt`。生成时必须把 ImageGen 与回执写入放在同一个机械 `functions.exec` 中顺序完成：先 `await tools.image_gen__imagegen(...)`，只在该调用内部从返回对象的 `savedPath|output_hint` 解析唯一真实路径；严禁调用 `generatedImage(...)`、`image(...)` 或把任何图片结果块送入 Codex 对话。如果值本身是绝对路径，直接验证文件存在；如果是说明句，只抽取其中唯一的 `/.../exec-<UUID>.png` 绝对路径子串并验证文件存在，绝不能把整句说明写进 `savedPath` 或 `tool_call_id`。`tool_call_id` 优先取真实字段，否则只从已验证文件名去掉 `.png` 得到。然后用 `tools.apply_patch` 把下列 JSON 写到 `check-fast8-worker-ticket` 返回的唯一 `worker_receipt_path`；该路径对本次 attempt 是唯一权威，技术重试时优先于 immutable 初始 job 内的 attempt_1 回执路径。最后用 `text(...)` 返回同一最小 JSON。多个候选路径、路径不可读或无法唯一解析时写失败回执，不按时间猜文件。不得等模型在下一步从视觉结果回忆路径，也不得把图片载荷写入回执。回执只是一份席位独占、非正式状态的机器审计与失败分类文件，因此是“多个 Worker 不得并发写正式目录”的唯一例外；每个 Worker 只写自己的唯一回执文件。控制器已经绑定本 Worker 的准确 session；只要该 session 中出现本次唯一 `exec-*.png`，即使回执尚未写完也可直接结算，所以回执不得成为成功产物的等待门。

Fast8 回执必须严格使用。无论路径成功还是无法取得，都必须在同一个 `functions.exec` 中写回执；主控会并行轮询已绑定 session 与该回执，任一形成确定性成功绑定即可结算，不等待本 Worker 的最终文字：
{"worker_receipt_contract_version":1,"style":"<X>","page_id":"<ID>","action":"<generate_anchor|repair_anchor>","attempt":<逐字复制 ticket 返回值中的本次整数 attempt>,"imagegen_input_fingerprint":"<逐字复制任务值>","worker_agent_id":"<真实 Agent ID、派发绑定的唯一 task_name 或 null>","tool_call_id":"<真实 ID 或从已验证的 exec-*.png 文件名取得；否则 null>","savedPath":"<已验证且从返回值中唯一解析出的真实绝对 PNG 路径>","tool_started_at":"<真实时间或 null>","tool_finished_at":"<真实时间或 null>","receipt_written_at":"<真实时间>","tool_status":"completed","failure_class":null,"tool_error_code":null,"error":null,"contains_image_payload":false}

失败必须区分两类。若 ImageGen 工具本身明确返回 failed、网络错误或没有生成结果，写 `tool_status="failed"`、`failure_class="backend_network"|"backend_failed"`、`savedPath=null`、`error="imagegen_backend_failed"`，并尽量填写稳定的 `tool_error_code`；主控会跳过无意义的产物恢复，直接进入一次技术重试。只有工具已经 completed，但 `output_hint|savedPath` 缺失或无法唯一解析时，才写 `tool_status="completed"`、`failure_class="artifact_missing"`、`savedPath=null`、`error="artifact_handoff_unresolved"`；主控会先检查已绑定 session，再决定是否恢复。只有回执文件本身写入失败时，才直接返回交接错误；任何失败都不得再次调用 ImageGen。

禁止本地绘图、HTML、SVG、Pillow、PowerPoint 排版或程序叠字/Logo；禁止修改任务、公共状态、正式输出或总览；禁止一个回合多次调用图片后端、切换后端或把多页合图。

图片工具完成后，先从该次工具结果中复制可读绝对 `savedPath`，再返回一行严格 JSON，不补设计说明。所有模式都应优先填写真实 `tool_call_id`、Agent ID 和起止时间。Fast8 的 `savedPath` 是成功交接的首要字段：只要它存在且可读，就必须使用 `error=null`，不得因其余元数据暂时不可得而把已经生成的图片改报为 `artifact_handoff_unresolved`；Fast8 主控可从正式派发边界、标准 `exec-*.png` 文件名和文件写入时间做带标记的确定性补全。Quick8 与两种 4×3 不使用该补全特例，必须继续返回原合同要求的完整真实元数据：
{"style":"<X>","page_id":"<ID>","action":"<generate_anchor|repair_anchor|recover_artifact>","source_action":"<recover_artifact 时填原动作，否则 null>","attempt":1,"worker_agent_id":"<真实 Agent ID 或 null>","agent_action_started_at":"<真实时间或 null>","agent_action_finished_at":"<真实时间或 null>","tool_call_id":"<真实 ID 或 null>","savedPath":"<真实绝对路径或 null>","tool_started_at":"<真实时间或 null>","tool_finished_at":"<真实时间或 null>","binding_source":"direct_tool_result","recovery_started_at":"<recover_artifact 时填写，否则 null>","recovery_finished_at":"<recover_artifact 时填写，否则 null>","recovery_method":"<same_worker|deterministic_script|null>","error":null}

只有工具已经 completed、但该次结果确实没有可读 `savedPath` 时，才写 `error="artifact_handoff_unresolved"` 并结束；工具自身 failed 时按上一段写 `imagegen_backend_failed`。不得猜测最新文件或自行再生图。只有主 Agent 明确授权新尝试后才能再次调用后端。对经典 quick8 v5，主 Agent 不会在用户选择前因版式相似、首感未精确命中、轻微文字瑕疵或审美偏好授权 `repair_anchor`；新 Fast8 只在最终组合报告确认高置信度实质同构或严重最低工艺退化时，按正式任务允许一轮、全运行至多两席的替代；轻度卡片感和主观审美仍不触发。既有 Fast8 v5 仍只按旧差异合同恢复。对 Fast 4×3，空间偏好和主观审美同样不触发修复，只有明确硬伤或锚点实质同构才允许一次定向修复。确认没有可用图片或文件/比例无效时，才可能授权一次技术重试。
```
