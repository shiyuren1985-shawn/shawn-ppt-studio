---
name: shawn-ppt-image
description: Shawn 的个人 PPT 图片策划、4×3/8×1 风格定位、并发生成、总览质检和选定风格扩页 skill。用于根据中文、英文或其他语言的内容大纲生成成品级 PPT 页面图片，处理参考图、品牌资产、空间秩序、并发子 Agent、失败恢复和风格延展。
---

# Shawn PPT Image

## 目标与三层职责

生成内容准确、视觉精致、可用于正式汇报的完整 16:9 PPT 页面图片，并以八个锁定的并行 ImageGen 分支探索真实不同的方向。

始终保持三层分离：

1. **内容合同与 QA**：保存完整事实、品牌、来源、逐字文案、风险和禁止误读；目标、估算、占位符与未确认信息不得写成已验证事实。
2. **页面导演**：把内容压缩成简洁、可测试的创意简报，包括 `relationship_thesis`、`visual_quality_intent`、`literal_anchors`、`flexible_story`、候选关系表达与 `craft_axis`。
3. **ImageGen**：只负责视觉表达，不接收完整合规清单、CRAP、失败路由或其他候选方向。

`relationship_thesis` 是观众第一眼应看见的主次、对比、因果、流向、反馈或证据层级，不等于每页强行画视觉隐喻。事实密集页可以只强调主次。标准迭代为“规划 → 生成 → 独立审图 → 单一目标修改”；修复要显式保存 `must_change` 与 `invariants`，不使用巨型提示一次解决全部问题。

选定强候选后优先把图片作为 master/style image 扩页：图片传递色彩、字体、材质、图像工艺和完成度，文字合同继续传递事实与硬约束。参考图优先于通用风格规则，但不覆盖用户当前明确要求、事实、来源与品牌约束。

## 按阶段加载，不预读未来规则

主 Agent 只读当前动作需要的文件；阶段切换后再加载下一份。新 Fast8 正常路径在正式 jobs 锁定后只读 `prompts/fast8-burst-runner.md`；新 Fast 4×3 只读 `prompts/4x3-burst-runner.md`。每个新 `project_dir` 都新建本轮的短 Director Agent 并使用 `fork_turns=none`，不对上一轮 Director 发送 follow-up 来产生新运行合同，即使页面相同也不例外。主任务只做机械调度，不重读大纲、其他任务或历史图片，也不直接接收 ImageGen 或审图产生的图片载荷。图片生成和视觉检查交给子 Agent；子 Agent 只读当前正式 job 和对应 prompt，按既有管线合同完成工作并以文字、JSON 和路径交接。主对话图片负载规则不限制子 Agent 内部正常看图。

严格限域的 Studio App Server 兼容例外优先于本文件和 Fast8 引用中“根任务不得提交图片 wrapper”的普通路由：只有模型可见的 application/developer context 明确包含 `transport=studio_app_server_v1` 时，Studio 的根 turn 才可作为本轮唯一机械图片执行者，逐字提交 `prompts/fast8-burst-runner.md` 中同一个 canonical `prepare --render-action` wrapper，并显式 `await eval(action)`。Studio 可从正式 jobs 锁定后直接选择该根 turn 路由；若已创建唯一图片执行子 Agent，则仅在其 `started` 后连续 180 秒没有任何 `interacted`、command/tool activity 或中央 claim，或宿主明确报告不能直接派发首 turn 时，先中断该空闲子 Agent，再由根 turn 接管同一 wrapper。两种路由不得并存；不得创建 A–H 逐席会话、第二 runner、第二 semaphore、第二 Judge 或改写 locked prompt/reference。根 turn 内的 ImageGen 返回对象只留在 canonical `functions.exec` 局部变量中，禁止调用 `generatedImage(...)`、`image(...)`、打开候选或向对话返回图片块；只接收脚本给出的路径、receipt/settle 摘要和状态。中央 cap5、`ticket → savedPath → receipt`、唯一 Judge、技术校验和 handoff 合同全部不变。没有该精确 transport 标记的普通 Codex 主对话、CLI 或其他 App Server 调用仍必须使用图片执行子 Agent，不得援引本例外。

同一个精确 Studio transport 例外也覆盖正式 `single_image_edit`：Studio 根 turn 从开始就是唯一机械 executor，不创建图片执行子 Agent，直接按 `single_image_edit_control_plane_v1.py` 执行 `prepare → claim → ImageGen exactly once → complete`，且仅在 ImageGen 明确 failed/cancelled、没有 completed 结果时执行 `release`。claim 必须复用现有中央 cap5；`complete/release` 仍是唯一允许导入新图、写 single-edit state/handoff 或释放租约的入口。completed 但根 turn 看不到 `savedPath` 时不得猜路径或 release，只返回 Studio 约定的 host-finalize marker，由宿主把其实际观察到的唯一 completed `savedPath` 交给同一个 canonical `complete`。根 turn 不打开结果、不调用 `generatedImage(...)`/`image(...)`、不覆盖父图、不修改 selection、不增加 Judge/Reviewer，也不把图片块带回对话。没有该精确 transport 标记时，单图修改仍由图片执行子 Agent承载，不能使用此例外。

### 共用输入

- 有内容大纲、拆页或代表页：读 `references/内容规划规则.md`。
- 有参考图：读 `references/参考图与约束分层.md`。
- 需要空间提示或空间 QA：读 `references/空间节奏与视觉呼吸规范.md`。
- 涉及品牌或基础验收：读 `references/设计基础与品牌资产.md`。
- 大纲或用户明确规定标题区：读 `references/全稿外壳与标题系统.md`；没有要求就自由发挥。
- 需要官方产品图、品牌 Logo 或常用第三方 Logo：读 `references/常用PPT元素资产库.md`，按需检索本地补充资产库。资产存在不代表当前页获得使用授权。

### 新 Fast8 的分段路由

1. **准备、导演与派发**：读 `references/Fast8准备与派发.md`。此时不要读恢复、Judge、交付或监测文件。
2. **图片工具开始返回**：读 `references/Fast8产物交接与恢复.md`。没有产物交接问题时不展开 legacy 恢复细节。
3. **A–H 已结算**：读 `references/Fast8裁判与收口.md`。
4. **准备用户回复**：读 `references/媒体隔离与交付格式.md`。
5. **正式流程完成后**：仅在要写健康报告、查中央索引或批次复盘时读 `references/运行监测与批次复盘.md`。

新 Fast8 正常运行不要预读 `references/四套风格并发生成.md`；它是旧任务恢复、综合命令查阅和异常深挖手册。

### 其他动作

- `fast_4x3`、`strict_4x3`、经典 `quick_8x1`：选页前先读 `references/4x3与Quick8运行合同.md`；自由选页且无专项测试目的时必须先确定一张视觉解法开放的风格释放页，不得以“覆盖多种难度”为由把数据/固定对比、固定架构和组织树三类刚性页面同时当作风格定位组合。需要详细兼容命令时再读 `references/四套风格并发生成.md`。
- 用户选定方向后扩页：读 `references/选定风格扩页.md`。新 `selected_style_expansion` 使用共享 content v2 / prompt v4 主干、三位短导演、一个机械执行 Agent 和一个隔离 Judge；旧扩页按已落盘 job 原样恢复，不迁移。
- 新建/恢复、定向修复、继续后续页或正式交接：读 `references/阶段交接与源材料漂移.md`。

## 运行模式

- 默认单页八方向探索：`fast_8x1_diverse`，A–H 八张 + 2×4 总览；A–D 深色位于前两行，E–H 浅色位于后两行。
- 用户明确要求旧快速八图：`quick_8x1`。
- 三个代表页快速候选：`fast_4x3`，四方向 × 三页。
- 三个代表页严格质量门：`strict_4x3`。

若当前请求只是继续、修复或恢复既有项目，以正式 `state/style_run_state.json` 的模式为准，不擅自迁移合同版本或重编历史提示。

## 输出目录与来源

每次新运行一个独立目录：先解析 `output_root`，优先级为用户指定位置、`<大纲所在目录>/output`、默认 `C:\Users\shiyu\AI_Projects\PPT\output`；Fast8 先用 `scripts/build_fast8_preflight_manifest.py` 确定性生成最小清单，不让模型手写启动 JSON，再在正式目录外完成来源/资产预检，最后用 `scripts/init_task_dir.py --preflight-manifest ... --overview-python ...` 一次创建不复用的 `project_dir=<output_root>/<任务名>`，并原子写好初始状态、起始事件和总览运行时。同名自动加后缀；准备错误不得先制造废弃正式目录，时间戳由脚本生成。

正式原图平铺在 `origin_image/`，命名 `style_<席位>_page_<页码>.<扩展名>`。状态、来源快照、handoff、健康报告和交付文本放在 `state/`；任务和最小回执放在 `style_jobs/` 与 `style_jobs/results/`；隔离审图任务和报告放在 `visual_qa_jobs/`。

如权威大纲在 YAML front matter 中显式声明 `slide_identity_required: true`、`deck_uid` 与逐页 `slide_uids`，这些字段是永久内容身份，不由页码、主标题、副标题或文件名推导。UID 必须直接维护在这一份权威原大纲中；新运行不得创建或自动发现 `_饱和式UID版`、`_slide_identity` 等第二份大纲，也不得要求用户同步维护独立 UID 文件。只有已经落盘并明确记录独立身份文件的旧运行，才按原合同兼容恢复，不迁移、不反写。页面只是改顺序时，同一个 `slide_uid` 必须随内容移动；核心命题或证据义务发生大改时，必须创建新的 `slide_uid`，旧 UID 与旧候选继续保留。正式 source snapshot 在生成前必须完整投影目标页 UID，handoff 的每个候选必须写入 `deck_uid` 与 `slide_uid`；原大纲缺少 opt-in、UID 为空、重复或目标页映射不完整时，在图片派发前停止。UID 含数字只记录命名建议，不阻断。UID 只参与 snapshot/handoff 元数据，不进入提示词、Director、Judge 或重试。没有显式启用该声明的其他项目继续兼容原流程。

首次派发前必须封存 `state/source_snapshot.json`。新 Fast8 冻结当前页 packet；新 Fast/Strict 4×3 冻结恰好三页 packet。Markdown 表格和稳定页标题使用同一共享提取器：目标页只保留自己的页段，页外受众、全稿目标、统一边界和资料索引只作为一次性的 deck context；末页不得吞入后置同级章节。正式快照直接把 packet 作为权威源；后续恢复、修复、Judge 与交接只检查冻结 packet、内容合同和实际输入资产，不再读取、哈希或比较原大纲，也不因原大纲变化返工。其他旧模式仍按其来源合同执行漂移检查。不要覆盖原始大纲或用户源文件。

## 内容、标题与视觉硬合同

- `display_required` 必须逐字准确；`display_flexible` 必须完整传达原意但可适度压缩。输出语言由用户要求和内容合同决定，未指定时保留源文，不擅自增加双语。用户明确要求整套或本轮“中英双语/bilingual”时，按页执行“有则使用”：只把当前页来源中已明确提供并授权上屏的 English Display Copy、English Title 或同类英文层与中文原文一起编入合同；当前页没有现成英文层时继续按该页源文生成，不临场翻译、不报错、不阻断整轮。仅含英文术语或 `language=mixed` 不等于用户请求双语；页面级明确指定中文或英文时，以该页指定为准。
- 只有大纲或用户当前要求明确规定标题区、Logo、标题层级、大致位置、字体、对齐或安全边距时，才编译 `global_chrome_contract`。要求大致遵循，不做像素级复刻。固定标题区本身不构成呼吸感失败；正文构图仍保持自由。
- 只要当前页来源明确给出 `title`，共享 prompt v4 就必须把它逐字编译为唯一页面主标题；`global_chrome` 启用时其当前页 `main_title.text` 必须与之相容。`subtitle` 只在当前页来源明确标为副标题时编译；缺失时禁止从参考图、锚点或证据附件补写。参考图或证据页中的标题、正文和页面结论不得替代当前页标题。`source_page|source_slide` 等证据附件只传递声明用途中的事实、品牌、对象与关系，不传递旧页标题、正文、构图或视觉风格。该规则由 8×1、4×3 与选定风格扩页共用，不增加 Reviewer。
- 非证据类 `required_assets[].use` 必须作为一句可独立执行的资产用途进入最终 prompt；其中的触发条件、目标对象和放置位置不得只留在资产 JSON。Fast8 仍由同一个终局 Judge 仅在条件实际触发的候选中顺手检查该用途，未触发不构成失败，不增加 Reviewer 或完整内容复审。
- 页面建立清楚、整齐但不机械的秩序：隐形网格、共同对齐轴和基线、组内紧组间松、有限规则重复、明确对比与阅读路径；用有效负空间承担聚焦、分组、停顿和边缘缓冲。不要画出网格，不要机械铺成等重卡片墙。呼吸感与信息密度无关。
- A–H/A–D 是单次运行的临时席位，不建立跨运行固定版式或风格映射。Fast8 多候选应在用户和参考图仍然开放的关系表达、工艺轴和粗粒度空间拓扑上真实分离，不能只换底色、图片或措辞；用户额外要求、语义不变量或参考图明确规定的共享骨架优先，不能为了追求多样性而破坏，也不能在 Judge 中把这类合规相似判成撞车。空间拓扑是生成前的组合覆盖检查，不是像素模板。
- 首轮就是成品候选，不用低质量草稿换速度。局部失败只修局部；单个项目的审美问题不自动升级成全局禁令。
- 质量门保持“少而稳定”：只守事实与来源、逐字必显内容、必要品牌资产、文件/尺寸/比例、严重可观察的构图或工艺退化，以及候选是否真实分离。唯一 Judge 在 raster 锚点页顺手确认视觉主标题来自当前页；无语义影响的末尾 `。.;；` 差异不触发整页返修，除非用户或内容合同明确要求标点逐字一致。轻微瑕疵、主观偏好、参考图不够像或“还可以更漂亮”不触发自动返修。
- 不把简单任务复杂化：能由一个既有 Judge、一次确定性检查或一次局部修复完成的，不增加第二个 Reviewer、完整三门复审、重复接触表、额外解释层或新状态机；一旦稳定门通过就收口。
- 简化不能牺牲稳定性：冻结来源、内容合同、正式 job、输入指纹、唯一回执、状态原子更新、并发上限、失败分类和交付文本门继续作为 8×1 与 4×3 的共享不变量。

## 主对话媒体隔离

根任务、用户直接创建的主对话，以及由主对话创建并长期保留的新测试任务或新对话，不得接收大尺寸或批量图片载荷；除非用户明确要求在当前主对话展示指定图片，否则主对话只保留文字、JSON、绝对路径、尺寸、哈希和状态。

子 Agent 不受上述图片载荷限制，可以按既有工作合同调用 ImageGen、生成图片、打开原图或联系表并完成视觉检查。该规则不规定子 Agent 一次能看几张图，也不改变 8×1/4×3 原有 Worker 和 Judge 方法。子 Agent 向父级主对话交接时不得转发图片内容块、缩略图、Base64、Data URL、截图或联系表，只返回精简结论和文件路径。

新 Fast8 正常路径仍以 `ticket → savedPath → receipt` 为唯一图片交接闭环；只有 ImageGen 已完成但 `savedPath/receipt` 异常时才进入纯文本取证或运行 `scripts/recover_image_artifact.py` 做无生图恢复，不得按最新时间戳猜文件。视觉检查与 Judge 必须照常执行，不得因保护主对话而跳过、伪造通过或降低标准。

主对话不得打开、整段读取或复制子 Agent 原始 `.jsonl` 来找图片路径。读取或监控其他主对话必须使用 `includeOutputs=false` 或等效的仅文字摘要模式。子 Agent 的图片载荷留在子 Agent 内，不得进入父级主对话。

用户交付只使用普通可点击文件链接。Fast8 必须由 `scripts/build_fast8_delivery_message.py` 生成 `state/delivery_message.md`，再用 `scripts/validate_delivery_text.py --require-link --fast8-links-only --project-dir ...` 校验，并逐字发送。交付文本固定为两行：第一行总览，第二行横向合并 A–H 八个图片链接；不含状态、耗时、健康报告、索引或说明。控制面 v1 在现有 Judge 通过后使用 `fast8_control_plane_v1.py lean-finalize` 完成必要文件/尺寸/席位门、总览和两行文本；立即交付，不等待 Judge 文字尾巴。完整审计、handoff、健康报告、中央索引与七问在交付后执行。旧运行仍使用其原 `finalize-fast8` 合同。

## 状态、恢复与质量边界

如上游新对话创建器能提供任务收到时间，Fast8 必须把该时间传给预检清单，不得用目录创建时间重置用户端计时。冻结 packet 只含当前页及其适用共享规则；明确标注不供作图、内容合同或视觉审核读取的维护文件不得进入三位导演上下文。

页码来自多页权威大纲时，预检清单必须用 `--page-source` 在创建正式目录前验证该页存在；随机选页先从当前来源实际页码集合抽取，不沿用历史版本的页数或旧对话印象。不存在的页立即在目录创建前失败，不自动映射为相邻页，也不启动导演或 ImageGen。

- `state/style_run_state.json` 是唯一正式进度表，只由主 Agent 或确定性脚本原子更新。新 Fast8 是单页探索，不创建未请求的 `follower/deferred` 占位页；启动元数据和总览 Python 在正式目录创建时一次固化。所有图片任务先 `record-dispatch-wave`，再由 `settle-wave` 结算。
- 新 Fast8 的 `generate_anchor|repair_anchor` 由 `fast8_control_plane_v1.py` 编译 Burst manifest；新 Fast 4×3 由 `four_by_three_control_plane_v1.py` 只编译依赖图适配 manifest。两者分别通过自己的唯一 canonical `functions.exec` wrapper，由一个图片执行子 Agent 逐字提交；不创建逐图 Worker，也不复制第二套状态机或并发器。4×3 控制面直接复用 `pipeline_control.py` 的正式 job、派发、结算、来源门、PNG 校验、技术重试、恢复和 Fast8 主干拥有的共享 ImageGen 租约。`prompts/fast8-image-worker.md` 与 `prompts/style-worker.md` 只保留给旧任务和异常恢复。根任务和图片执行子 Agent都不能重新设计或改写锁定的 `imagegen_prompt` 与图片输入。
- 新 Fast/Strict 4×3 在一次冻结三页 packet 后，按与 Fast8 相同的职责边界并行创建三位短导演：事实内容、标题与资产、视觉系统。事实合同、四字段创意合并、art direction/activity/attention/topology、global chrome、资产清单、输入指纹、prompt v4 和 source snapshot 都来自 Fast8 共享主干。4×3 只增加三页 bundle、A–D 风格家族字段和 `anchor → two followers` 依赖图；锚点 `visual_thesis` 不得传给跟随页，`style_family_thesis`、色彩/字体/材质/图像工艺和完成度继续传递，而每页自己的 `relationship_thesis` 控制本页构图。当前 v5 跟随页默认把本风格锚点成图作为风格附件；当前页标题、事实、对象和关系只来自本页冻结合同，不继承锚点内容或具体构图。只有当前页事实/品牌资产已经占满 5 个附件时，才机械降级为文字化视觉家族，不增加审核或丢弃必要资产。旧 v4 风格合同继续保留锚点图路径。
- 4×3 逐页资产 bundle 合并后已经进入各页 `required_page_assets`，不得再作为 `prepare-anchors --required-assets-file` 的共享资产 envelope 重复传入。多页标题继续只维护 Fast8 一份正式 schema：内容导演保存来源明确的逐页 `title`，标题导演写共享 raw 决定并调用 `normalize_fast8_chrome_contract.py --page-title-map-json`；正式合同用 `main_title.text_by_page` 保存映射，`global_chrome_projection()` 只向当前页投影一个 `main_title.text`。旧单页 `main_title.text` 完全兼容。
- 新 4×3 调用 `build_4x3_source_packet.py` 时必须同时提供 Markdown 导演包 `--output` 和三记录 JSON `--snapshot-output`。三位导演只读 Markdown；首次准备只把 JSON 传给 `--source-file`，并同时提供三页 `--source-page-ids` 和三份 snapshot 内容合同，不传 `--source-fragment-file`。这样主大纲行和页级说明可以在导演包中共同出现，但 source guard 仍绑定每页唯一 JSON 记录。Fast8 单页 packet 继续可同时作为单页 authoritative fragment。
- 新 Fast 4×3 只使用三个规范入口：三位导演退出后执行 `prepare-directors --state <state>`，图片执行子 Agent 执行 `render-action --state <state>`，12 张齐备后执行 `lean-finalize --state <state>`。创建目录时不得向 `init_task_dir.py` 传 Fast8 专用的 `--preflight-manifest` 或 `--overview-python`；总览运行时由 `prepare-directors` 绑定。`prompt_semantic_guardrails` 的 300 字上限按每页计算，不对三页 bundle 再做重复合计；正式标题、schema 和工程路径由规范入口确定性编译，根任务不要在入口前增加一轮逐字段审查。所有内容合同、layout、source snapshot、global chrome、总览和 handoff 路径均从同一正式 state 推导，不再人工传递第二组工程路径。机械运行共享中央 JIT ImageGen 槽位表，最多 5 路；一个执行子 Agent不等于一个 ImageGen 槽，旧 `active_child_limit` 不参与新适配器容量判断。锚点一结算就只解锁同风格两张跟随页；已有 claim/receipt 或 recovery queue 先恢复、结算或明确终止，禁止重复生图。Strict 4×3 继续保留四锚点 QA 门，不因共享控制面而降级为 Fast 语义。
- 新 Fast8 正式目录应在请求后约 60 秒内创建；根任务不得在 `process_started` 之前独自展开整份内容合同与八席逐项创意推理。正式目录创建后先由 `scripts/build_fast8_page_source_packet.py` 把当前页、适用的共享规则和明确附加来源一次冻结到 `state/director_inputs/authoritative_page_packet.md`；三位导演只读这个稳定输入包，不再读取会被用户同步修改的整份大纲。本次运行采用已冻结内容；管线此后不检查原大纲是否修改、不发整纲漂移 warning、也绝不因此重做，上游后来修改只影响下一次新运行。首次 `prepare-anchors` 的 `--source-file` 与 `--source-fragment-file` 都指向 frozen packet，彻底把原大纲移出正式快照和后续关键路径。随后同回合并行创建三位短导演：`gpt-5.6-sol / high` 的事实内容合同导演只负责复杂事实、显示义务、来源边界和内容可行性，并只写精简事实合同；`gpt-5.6-terra / medium` 的标题与资产编译器只负责已授权 global chrome 和实际资产路由；另一位 `gpt-5.6-sol / high` 视觉组合导演继续负责页面级关系命题、质量意图、工艺目标与 A–H 组合。事实席保持 high 推理能力，不以降低事实质量换速度；两位 sol/high 彼此独立并行。三者都使用 `fork_turns=none`、写不同文件并在图片派发前退出；根任务随后只调用一次 `scripts/fast8_control_plane_v1.py prepare-directors --state <state>`，让确定性入口连续完成原有 narrow normalizer、四字段 merge 与 `prepare-anchors`。它只从冻结 preflight 与规范目录推导参考图、required assets、global chrome 和 source packet，不覆盖 raw JSON、不猜测语义或资产路由；任一步失败都在 style jobs 前停止。三个原命令继续保留供诊断/旧运行。标题编译器仍在同一子任务内把原始合同经 `scripts/normalize_fast8_chrome_contract.py` 规范化为正式 v1，不根据资产存在猜 Logo 授权。根任务不重复创作；该分工缩短准备关键路径，同时保留 sol/high 对最终生图审美输入的控制。
- 新 Fast8 派发时仍为每席生成唯一结构化 ticket，但不再创建八个 LLM 图片 Worker。正式 jobs 锁定后，一个图片执行子 Agent按 `prompts/fast8-burst-runner.md` 逐字提交一次固定 `functions.exec`，对 A–H 使用 `Promise.allSettled`：每席独立执行 `claim → ImageGen → savedPath/receipt → release`，成功立即落自己的回执，一席失败不取消其余七席。根任务和执行子 Agent都不创作或改写八份锁定 prompt/reference。正常路径删除 UUID 预绑定、八个逐图 Agent 冷启动、Worker 文字回执等待、session PNG 扫描和三路重复核验；UUID/session 仅是 `completed` 但 `savedPath/receipt` 异常时的取证手段，不是业务不变量。真正不变量是唯一席位、唯一正式输入、最多一次正常 ImageGen、真实 savedPath、不得串跑或重复生图。
- 所有 Fast8 任务共享既有中央 JIT ImageGen 槽位表，当前全局最多 5 路；图片执行子 Agent提交的唯一机械 `functions.exec` 不叠加第二套信号量。派发授权不占槽位，每席在即将调用 ImageGen 时机械 claim，完成或失败后立即 release，等待席位滚动补入。已有 claim/receipt 的同一 ticket 禁止再次正常生图；TTL 只作崩溃兜底。无生图恢复与 Judge 不占 ImageGen 槽位。历史 `dispatch_prelease_v1` 和旧 Worker ticket 保持原恢复语义，不强制迁移。
- 无生图恢复不增加图片尝试次数。只有工具 completed 但确实找不到产物时才进入恢复；ImageGen 明确 failed/network error 时跳过产物恢复，直接按既有预算排一次技术重试。结算脚本一旦返回 ready 重试席位，就立即通过一次来源门和增量 burst 派发，不等待首轮 A–H 齐结束；JIT 槽位仍限制真实 ImageGen 在途，因此流式重试不增加并发上限、不改变图片输入。
- 新 Fast8 保留一次终局组合 Judge；如有标题硬合同，同一 Judge 一并做近似标题检查。Judge 在子 Agent 内按正式合同查看 contact sheet 和必要单图，只向主控落盘精简报告、路径和哈希，不把图片回传主控。不得跳过 Judge或伪造 pass；缺少或不匹配的机器绑定时报告不得应用。
- Fast8 全运行最多一轮、至多两席替代；替代后只允许一次 delta 或必要的全量复核，结果以 `pass|best_effort` 收口，不无限重生。任一必需席位耗尽技术重试且无候选时，脚本立即终止旧运行、清空队列并释放租约；不得一边继续不可完成的旧运行一边启动新运行。
- 主对话只做确定性文件、尺寸、比例、哈希、状态和来源检查；图片生成和视觉检查由子 Agent 完成。
- 新选定风格扩页由确定性 initializer 创建 `state/selected_style_run_state.json` 和 target-page-only packet v2：只冻结本轮目标页各自的精确原文、页级说明和一次性 deck 共享合同，不保留整纲副本。三位导演分别写事实内容、标题资产和全稿视觉 raw 文件；随后只调用 `selected_style_control_plane_v1.py prepare-directors|render-action|lean-finalize --state <state>`。资产必须显式声明 `render_asset|planning_evidence`，后者不进入 ImageGen 附件；写实情境重建的可见披露由视觉导演逐页显式决定。视觉导演逐页决定媒介兼容性：默认 `raster` 使用一张 primary、可选一张 supporting 锚点，只有明确媒介硬冲突才选 `text_family`；正式事实/品牌附件占满总上限 5 个时由控制面按实际清单机械降级，不让导演猜容量。锚点默认是 `style_anchor_only`，不授权其内容、对象、构图或标题区；只有 `final_page_and_anchor` 才同时作为最终页单独 QA。global chrome 只来自用户或大纲明确授权。正式 jobs 后由一个机械执行 Agent 用一次滚动 wrapper 共享中央 cap5 跑到全 run 终态，不创建逐页 Worker；一个隔离 Judge 只对明确失败页授权一次定向修复。普通局部修复可保留失败候选；语义污染修复不得回灌失败候选，明确由 raster 锚点文字污染时改用 `text_family` 重生。新页不累计成为后续锚点，冻结 packet 后上游变化只影响新运行，页面级不一致只阻断该页。
- 三位导演并行时，控制面只补 schema 中可机械确定的默认字段，不替导演编造事实或语义。单个导演长时间无有效 raw 时，只中断并按同一冻结 packet 重启该导演一次；不重启其他已完成导演，不重开整轮，根任务不手写语义 raw。

## 完成、监测与速度

最终 Judge 绑定当前 A–H 后，控制面 v1 只在关键路径执行一次 `lean-finalize`：验证当前 Judge 集合、八席文件/尺寸/唯一性，平铺候选、生成 2×4 总览和严格两行链接。handoff、完整状态审计、健康报告、监测登记、中央索引与七问全部移到两行链接之后，不得阻断用户交付。旧运行仍可使用 `finalize-fast8`。监测层不增加 ImageGen、视觉 Worker 或自动修复。已经 Review 的条目保留历史但不自动重审，批次审查默认消费 `pending_reviews` 增量队列。

Fast8 的正式软目标为用户请求开始到可点击交付完成 15 分钟；状态至少记录 `request_started_at`，健康报告先给端到端时间，再给预检、派发/绑定、ImageGen、结算、Judge 和 finalize 分段。图片质量输入、来源门、最终 Judge、文件存在/尺寸校验和 handoff 不得为提速跳过；哈希与确定性文件检查通常只需毫秒到秒，不应被误判为关键路径。监测登记与批次复盘不得阻断用户交付。

每次真实运行 Review 都要重新执行“七问根因检查”：为什么发生或未发生、步骤及等待是否必要、为何此前未发现或未修好、旧修改方式是否只治表象、是否过度纠结工程细节、证据支持的根因、以及各环节应否换更快模型/更低推理/并发或脚本替代。不得把第一次分析当成后续轮次的永久答案；即使本轮健康也要重新核对，并把简洁答案写入 `technical_findings.root_cause_review`。若本轮存在失败、重试、恢复或返工，必须另外分开回答 `failure_root_cause`（失败为什么发生、能否预防）与 `post_failure_handling`（失败后的检测、分类、终止和恢复是否把短失败放大成长尾），并尽量分别量化失败本身和失败后处理耗时。七问不自动触发修改；没有本轮证据时明确记为未知并设计最小验证。

禁止本地绘图、HTML、SVG、Pillow、PowerPoint 布局或程序叠字/Logo来代替图片模型；`build_style_matrix.py` 只能缩放和排列完整页面。正式文件由主 Agent集中复制，多个 Worker 不得并发写同一正式目标。本 skill 默认只交付成品图片和总览，不组装 PPTX。
