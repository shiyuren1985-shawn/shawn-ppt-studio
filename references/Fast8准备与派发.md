# Fast8 准备与派发

只在新建 `fast_8x1_diverse` 运行、尚未调用 ImageGen 时读取。本文件结束后不要预读产物恢复、Judge 或监测规则。

## 目标

一次完成内容合同、八个真实分离的导演方向、来源封存、运行时预检和 A–H 同波派发。控制面 v1 由一个图片执行子 Agent提交唯一 canonical `functions.exec` wrapper，机械读取八个正式 job/ticket 的 manifest；正常路径不创建八个逐图 LLM Worker。

## 默认代表页选择（仅限自由选页）

用户未指定页码且没有压力测试等专项目的时，优先选择核心命题和视觉关系明确、但视觉解法尚未被固定图表、固定层级、固定版式或大量必显元素锁死的页面；“开放”不等于内容空泛。用户指定页码或测试目的时逐字服从，不重新选页。这是一次轻量判断，不建立评分器或新增审核。

## 准备顺序

**计时与输入范围：**如上游控制器已给出任务收到时间，必须用 `build_fast8_preflight_manifest.py --request-started-at <ISO>` 传入，不得用正式目录创建时间重置用户端计时。用户明确要求全部候选为浅色或深色背景时，必须同步传入 `--tone light` 或 `--tone dark`，由预检清单原子固定 A–H 的 `tone_overrides`；不得仅把偏好写进自然语言导演文字，却保留默认混合色调状态。`build_fast8_page_source_packet.py --include-file` 只接收当前页说明、当前页视觉约束或用户明确输入；不得传入明确声明作图、内容合同或视觉审核阶段不得读取的大纲维护文件，脚本也会排除这类文件。

1. 接到用户请求后的第一项动作只解析任务名、输出根、规范页码、权威来源、明确参考图和实际输入资产，立即调用 `scripts/build_fast8_preflight_manifest.py` 创建最小 `fast8_preflight_manifest_version=1` 清单；不要让模型手写 JSON，也不要先展开内容合同或八席创意推理。脚本负责真实 `request_started_at`、固定 schema、唯一页码、绝对路径、存在性和去重；必需来源用 `--required-file`，可选来源用 `--optional-file`，真正传给 ImageGen 的资产用 `--asset /absolute/path::role`。新 Fast8 不接受与权威原大纲分离的 UID sidecar；如需显式冻结身份绑定，只能在生成预检清单时把同一份 `--page-source` 权威原大纲同时传给 `build_fast8_preflight_manifest.py --slide-identity-file`，它只进入 task init、source snapshot 与 handoff 元数据，不属于 ImageGen 资产。后续调用 `init_task_dir.py --preflight-manifest ...` 时严禁再次传 `--slide-identity-file`，初始化器会从冻结清单读取可选身份绑定。当页码来自一个多页权威大纲时，必须同时传 `--page-source <同一 required-file>`，在创建正式目录前确定性确认该页真实存在；随机选页也必须先从当前来源实际页码集合抽取，不沿用历史页数印象。随后先运行 `init_task_dir.py --preflight-only --preflight-manifest ...`。预检通过后取得 workspace dependencies 的绑定 Python，再用同一清单调用一次 `init_task_dir.py --overview-python <已绑定 Python>` 创建唯一 `project_dir`。目标是在请求后 60 秒内完成正式运行创建，使后续创意准备也进入 `process_total`；脚本会验证 Pillow，并原子写入 `style_run_state.json`、`process_started`、`preflight_resolved` 与 `overview_runtime`。用户给出大纲且未指定输出位置时，`output_root=<大纲目录>/output`；新运行不复用旧目录。不要为准备错误反复创建带后缀的废弃正式目录。
2. 正式目录创建后，立即用 `scripts/build_fast8_page_source_packet.py --source <权威源> --page-id <当前页> --output <project_dir>/state/director_inputs/authoritative_page_packet.md` 一次冻结当前页输入。Markdown 表格大纲由脚本保留共享/全稿规则、表头和当前页记录，并去掉其他页记录；附加的本页说明或用户明确输入可用 `--include-file` 一并冻结。命令返回的 `canonical_title` 作为规范主标题候选。此后本次运行的三位导演只读该 packet，不再读取会继续变化的整份上游大纲；packet 已存在时只允许同内容幂等复用，不得随上游变化覆盖。首次 `prepare-anchors` 的 `--source-file` 和 `--source-fragment-file` 都使用该 packet，并设置 `--source-fragment-authority authoritative_page_fragment`；原大纲从此退出正式快照和关键路径。管线完全不读取、哈希或比较原大纲，不发相关 warning、更不会因此重做；用户对原大纲的新修改只影响下一次新运行。内容合同、冻结 packet 和实际生图资产自身仍做轻量完整性检查。
3. 先由根任务确定一次 `canonical_page_id` 和规范主标题；后续清单、三位导演、state、jobs 与文件名逐字复用，子导演不得自行添加或删除 `P`。然后在同一控制回合并行创建三个临时导演：
   - 事实内容合同导演使用 `gpt-5.6-sol / high / fork_turns=none` 和 `prompts/fast8-content-contract-director.md`，只写精简的原始 `state/director_inputs/content_contract.json`；它负责完整事实、显示义务、来源状态和内容可行性，不重复视觉导演字段、空间 QA 摘要或总体要求，也不编译标题或资产。该选择保留 high 推理能力，不以降级事实判断换速度。
   - 标题与资产编译器使用 `gpt-5.6-terra / medium / fork_turns=none` 和 `prompts/fast8-chrome-assets-director.md`，只写按授权可选的原始 `global_chrome_contract.json` 与顶层数组 `required_assets.json`；它不重复事实合同或 A–H 创意。若创建标题合同，必须显式写 `logo.required`、`main_title.required` 与授权策略，并在同一子任务写盘后立即运行 `scripts/normalize_fast8_chrome_contract.py` 输出 `global_chrome_contract.normalized.json`，不等待其他两位导演或根任务再次调度；正式 prepare 只使用规范化文件。脚本只修 schema、规范页码/标题、packet 路径和资产文件身份，不根据 Logo 文件存在猜授权。标题 brief 每种语言最多 300 字，由 360 字硬门复核；prepare 时使用 `--required-assets-file`。
   - 视觉组合导演使用 `gpt-5.6-sol / high / fork_turns=none` 和 `prompts/fast8-layout-portfolio-director.md`，写原始 `state/director_inputs/layout_portfolio.json` 与 `creative_intent.json`；它继续拥有 `relationship_thesis`、`visual_quality_intent`、`visual_support_goal`、`craft_ambition` 和 A–H 组合的最终判断。
   三者只共享权威来源、本页、用户要求、参考图/指定 master、规范页码、规范标题和目标路径，不共享彼此模型上下文，也不互相等待；根任务不得同时再手写一套重复合同、标题/资产合同或逐席导演方向。只要目标文件和 Agent 完成状态都已确认，根任务只调用一次 `scripts/fast8_control_plane_v1.py prepare-directors --state <state>`：该确定性入口按既有语义连续执行 narrow normalizer、creative intent merge 与 `prepare-anchors`，从冻结 preflight 和规范目录推导参考图、required assets、global chrome 与 source packet，不让模型转抄参数。原始 Director JSON 不覆盖；规范化器只写机械版本字段，并仅接受恰好 A–H 的 `directions→styles` 无损别名；merge 只合并四个创意白名单字段；prepare 只读取 normalized content/layout。任一步失败立即停止且不得创建半套 style jobs；三个原命令继续保留供诊断和旧运行使用。若页码、标题、资产路由或语义枚举不一致，脚本直接失败，根任务只恢复责任导演，不自由猜测。三位导演完成后必须退出并释放子 Agent 名额；根任务随后创建一个图片执行子 Agent，让它按 `prompts/fast8-burst-runner.md` 的静态 wrapper 运行 `scripts/fast8_control_plane_v1.py prepare --state <state> --render-action` 并显式执行 `await eval(action)`。
4. 内容合同导演按 `内容规划规则.md` 写本页 v2 内容合同和 v4 提示合同。完整事实、品牌、来源与 QA 留在合同；图片提示只保留必要文字锚点和短导演简报。
5. 内容合同至少显式包含：
   - `display_required`：必须逐字准确；
   - `display_flexible` 与不超过 320 字的 `flexible_story`；
   - `visual_quality_intent`：用户审美与完成度意图；
   - `relationship_thesis`：第一眼应看见的主次、对比、因果、流向、反馈或证据层级；
   - `spatial_generation_brief`：统一空间秩序要求。
6. 只有大纲或用户当前要求明确规定标题区时，按 `全稿外壳与标题系统.md` 编译一次 `global_chrome_contract`；没有要求就不创建。资产库、历史页面或旧母版不能反向授权当前页使用 Logo。
7. 如有参考图，按 `参考图与约束分层.md` 编译其高维视觉意图。参考图优先于通用审美偏好，但不覆盖内容事实、来源、品牌与用户当前明确硬要求。
8. 视觉组合导演创建 v7 `layout_portfolio.json`。A–H 每席必须有：
   - 唯一 `direction_id`；
   - 不超过 220 字的 `visual_thesis`；
   - 不超过 80 字的 `relationship_representation_family`；
   - 不超过 180 字的 `craft_axis`；
   - `restrained|balanced|expressive` 的 `visual_activity_mode`；
   - 不超过 160 字的 `attention_strategy`；
   - `spatial_topology`：`primary_entry`、`region_logic`、`evidence_attachment` 和一条正向 `spatial_topology_intent`。
     - `primary_entry` 只能取 `single_focus|paired_contrast|path|network|field|hierarchy|radial|evidence_hero`；
     - `region_logic` 只能取 `unified_field|asymmetric_split|staged_path|distributed_nodes|layered_depth|annotated_object|geographic_spread|editorial_sequence`；
     - `evidence_attachment` 只能取 `integrated|annotated|satellite|quiet_band|none`。
9. 顶层声明 `spatial_topology_portfolio_version=1`。八席完整拓扑签名必须逐席互异；至少四种 `primary_entry`、至少五种 `region_logic`，同一入口最多两席，`quiet_band` 最多两席，至少三席把证据整合或标注进主视觉。该检查只阻止八席复用同一“双栏＋节点/框体＋底栏”骨架，不规定像素坐标或固定构图。八席的视觉命题和工艺轴仍分别规范化互异；`relationship_representation_family` 至少六种。至少三席 `restrained`，最多两席 `expressive`。每席只有一个第一层入口；这不等于每页必须使用视觉隐喻或只能有一个对象。
10. 在首次派发前封存 `state/source_snapshot.json`。新 Fast8 由首次 `prepare-anchors --source-file <authoritative_page_packet.md> --source-fragment-file <authoritative_page_packet.md> --source-fragment-authority authoritative_page_fragment` 原子封存，不要先手工调用 `snapshot-source`。真正传给 ImageGen 的图片、Logo、标题参考与合同进入 `assets`。正式继续、恢复、修复和交接只检查 frozen packet、内容合同与实际输入资产；不再检查原大纲。
11. 总览运行时只在 `init_task_dir.py --overview-python ...` 正式创建时预检和绑定一次。`prepare-anchors` 与 `finalize-fast8` 只复用状态中的绝对路径，不接受新运行在后段覆盖或补写，也不回退猜测系统 Python。

## 状态和任务

`init_task_dir.py` 已创建 Fast8 正式初始状态；随后使用 `scripts/pipeline_control.py prepare-anchors` 创建 A–H job 和初始队列，不再重复传 `--overview-python`。新任务的每个 generation job 都包含：

- 预编译且互异的 v6 `imagegen_prompt`；
- 必要引用图路径；
- `creative_brief_projection`；
- 唯一 `style_jobs/results/*_worker_receipt.json` 回执合同。

主 Agent 不单独运行派发命令；唯一 canonical wrapper 由图片执行子 Agent在同一次 `functions.exec` 内运行 `scripts/fast8_control_plane_v1.py prepare --state <state> --render-action`。脚本一次完成派发，为 A–H 生成唯一 `worker_ticket_path`，并把 job 路径、SHA、图片输入指纹、逐字 prompt/reference 和回执路径编译到只读 manifest。根任务先用 `exec_command` 后台启动 `python3 scripts/fast8_control_plane_v1.py await-close --state <state> --wait-seconds 900 --poll-interval 0.5`；初次 `yield_time_ms` 取 250–1000 ms，只保留返回的 shell `session_id`，不得等待命令完成。随后在同一派发回合创建唯一 standby Judge，并让图片执行子 Agent逐字使用 `prompts/fast8-burst-runner.md` 的 wrapper 提交唯一一次 `functions.exec`：取得完整 `action` 字符串、续收 shell session、检查 exit code，再显式执行 `await eval(action)`。禁止把未 await 的 IIFE 当 raw source，不接收或转抄 job SHA，也不重写 prompt/reference。

`record-dispatch-wave` 在任何 Worker 创建之前必须完成正式 generation job 输入校验；每席 `imagegen_referenced_paths` 最多 5 个，超限直接阻断派发，不允许到 Worker 或 ImageGen 调用后才发现。

派发后采用 **one child-runner functions.exec + eight async branches**：固定动作以 `Promise.allSettled` 并发 A–H，每席独立执行 `claim → ImageGen → savedPath/receipt → release`。不创建八个逐图 LLM 图片控制 Agent，不收集、轮询或转抄 UUID，不等待文字回执；单席失败只终止本席，其余继续。脚本在 claim 时再次验证 ticket、页码、job SHA 和图片输入指纹，并拒绝 duplicate claim。UUID/session 只保留给 `completed` 但 `savedPath/receipt` 异常时的取证或旧 ticket 恢复。

新 Fast8 正常路径不启动八个逐图图片 Worker。内容合同、八席导演简报和正式 jobs 锁定后，根 Agent 不再做创意判断；机械链路为：一次 prepare/dispatch → 后台 `await-close` watcher → 同回合启动唯一 standby Judge 和一个图片执行子 Agent → settle → Judge → watcher 原子 apply 与 lean finalize。watcher、standby Judge 与图片执行子 Agent并行等待各自条件，但 watcher 必须位于正式 jobs 之后、Judge 与生图调用之前。根任务不读取图片做判断、不修改 job，也不参与 Judge。

A–H 派发回合中，根 Agent 在 watcher 已取得 shell `session_id` 后创建唯一 `gpt-5.6-terra / low / fork_turns=none` standby Judge，让它只运行 `await-fast8-judge-job`；该命令在完整正式 job 尚不存在时只短轮询 state，不打开图片、不创建 contact sheet、不写视觉结论。根任务随即启动图片执行子 Agent提交 canonical `functions.exec`。八图齐备后现有机器链路准备唯一 Judge job，standby Judge 从原子状态取得 job 后自绑定、校验并开始接触表审图。机械调用返回后，根任务只续收 `await-close` shell session，不等待 Judge 的文字 final/Agent completed；watcher 返回 `completed` 后立即逐字发送两行链接，再运行 post-delivery，并只在交付与审计完成后中断仍 running 的 Judge。若 watcher 返回 `replacement_required`，按既有授权替代 1–2 席后重新启动同一命令，不改变 Judge 标准。

运行时优化不得触碰质量输入：`imagegen_prompt`、`imagegen_referenced_paths`、`imagegen_prompt_fingerprint` 与 `imagegen_input_fingerprint` 均由准备脚本生成并锁定。模型选择、短 Worker 模板、回执模板或绑定元数据不得进入提示编译，也不得改变参考图顺序。任何速度改动只要造成这四项变化，就不是纯管线优化，必须停止并另做视觉回归。

旧 P31 baseline verify 与额外指纹归档只属于回归测试，不进入普通生产关键路径；正式运行只保留本次 A–H 质量输入在派发前后的自身一致性检查。

新 Fast8 是一次单页 A–H 探索：`follower_page_ids=[]`、`deferred_pages=[]`。不得为了满足旧 Quick8 验收规则制造两个未请求的占位页；用户选定方向后的扩页是独立任务。

新 Fast8 默认授权 A–H 同波；中央槽位只约束真实 ImageGen 在途。`record-dispatch-wave` 不预占容量；八个 async 分支各自在即将调用 ImageGen 时通过 `fast8_control_plane_v1.py claim` 获取既有全局 JIT 租约，并在回执或 `finally` 中幂等 release。当前同一用户所有 Fast8 合计最多 5 次真实生图在途；第 6–8 席只在同一机械动作内等待，完成一席便滚动补入。不得再叠加第二套 semaphore，也不把并发值写入 generation job 或质量指纹。无生图恢复和隔离 Judge 不占 ImageGen 槽位；租约 TTL 仅是异常崩溃保底。

JIT 全局容量不会让派发波部分授权，只会让图片执行子 Agent机械调用内的分支滚动等待。A–H 候选均由同一次调用直接写 receipt，主控不等待普通文字或 session PNG。standby Judge 可在生图前冷启动；八席全部结算后立即取得正式 contact sheet job 并审图。正常路径只有一个图片执行子 Agent和一个 Judge，不形成 root + 8 Worker + Judge 的子任务上限竞争。

成功席在同一分支直接写真实 `savedPath` 回执并释放；明确 backend failed 的席位写失败回执、跳过 session 扫描并进入既有一次技术重试预算。只有工具 completed 但 `savedPath/receipt` 缺失或不可解析时才标记 `session_forensics_required_styles`，交回主控做异常取证。该规则不增加重试预算，也不放松产物身份校验。

## 图片提示边界

新 Fast8 的图片提示只编译一次，顺序为：成品页与语言、必要逐字文字、单句内容故事、单段页面导演、短标题系统（若适用）、统一空间要求、无参考图时的一句成熟度底线。页面导演单段合并 `relationship_thesis`、`relationship_representation_family`、正向 `spatial_topology_intent`、`visual_thesis`、`attention_strategy`、`visual_activity_mode` 和 `craft_axis`，避免同义要求多次重复；同时执行统一叙事层预算：一条主关系＋至多一层安静证据，系统清单、流程、KPI、案例说明不得各自形成同权叙事链。预算以小型 `narrative_layer_budget` 保留在中间产物，枚举值和组合检查留在 job/QA，不把字段名清单塞给 ImageGen。

完整事实库、语义护栏、来源、风险、CRAP、空间 QA、失败路由和其他席位方向不进入 ImageGen。具象产品、项目或交付事实必须有来源或附件支持。
