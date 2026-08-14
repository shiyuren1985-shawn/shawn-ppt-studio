# 4×3 与经典 Quick8 运行合同

只在用户明确选择 `fast_4x3`、`strict_4x3`、`quick_8x1`，或恢复这些旧任务时读取。详细兼容、命令、状态和修复规则保留在 `四套风格并发生成.md`；不要让新 Fast8 预读该综合手册。

## 默认代表页选择（仅限自由选页）

只在用户未指定页码且没有压力测试等专项目的时启用；用户指定页码或测试目的时逐字服从，不重新选页。自由选页时优先选择“核心命题和视觉关系明确，但视觉解法尚未被固定图表、固定层级、固定版式或大量必显元素锁死”的页面；“开放”不等于内容空泛。`quick_8x1` 以这类页面作为单页风格定位样本；4×3 以它作为风格释放的锚点页，再搭配一张数据/对比页检验信息组织、一张复杂架构或高密度页检验复杂承压，避免三页全部被刚性约束锁死。这是一次轻量选页判断，不建立评分器、不新增审核或并行管线。

## 经典 Quick8 v5

八席同波、每席一次首轮 ImageGen。无差异 Judge，选择前不因主观审美、轻度模板感或候选相似自动返修。八张可用后生成 2×4 总览并标记 `candidate_ready`：A–D 深色位于前两行，E–H 浅色位于后两行。v4/v3 仅恢复，不迁移。

## Fast 4×3

新运行先用 `build_4x3_source_packet.py` 同时写入规范路径 `state/director_inputs/authoritative_three_page_packet.md` 与 `authoritative_snapshot_source.json`，冻结恰好三页，再并行使用事实内容、标题资产、三页视觉系统三位导演。每个新运行都创建三个 `fork_turns=none` 的新 Director Agent，只读本轮冻结包、本轮参考图分析和本轮正式路径；不发 follow-up 给历史 Director，不复用其会话内存或旧路径。三者的职责边界与 Fast8 相同；4×3 只把单页内容包装为三页 bundle，并把 A–H 页面方向改为 A–D 跨页视觉家族。

创建 Fast 4×3 目录时不得向 `init_task_dir.py` 传 Fast8 专用的 `--preflight-manifest` 或 `--overview-python`；总览 Python 由首次 `prepare-directors` 确定性绑定。如有独立 UID 大纲，可在初始化时传 `--slide-identity-file <绝对路径>`，它只参与 source snapshot/handoff 绑定，不进入三位 Director、ImageGen 或 Judge。事实导演的 `prompt_semantic_guardrails` 300 字上限按每页计算，不是三页 bundle 合计；正式标题与工程路径由 `prepare-directors` 按冻结来源和规范目录再次编译，根任务不要在入口前增加一轮重复逐字段审核。

逐页资产 bundle 由 `merge_4x3_director_inputs.py` 写入各 `content_contracts/page_<ID>.json.required_page_assets`；其中只允许 PNG/JPEG/WebP 这类真实光栅附件，PDF/PPTX/Markdown 等规划证据只进入 supporting sources，不得作为 ImageGen 附件。调用 `prepare-anchors` 时不得再把 `required_assets_by_page.json` 传给 `--required-assets-file`，该兼容参数只接受共享资产 envelope。多页标题不得复制一份 4×3 schema：标题导演写 Fast8 raw chrome 决定，再用共享 `normalize_fast8_chrome_contract.py --page-title-map-json ...` 编译一份正式合同；`global_chrome_projection()` 按页选择标题。

`build_4x3_source_packet.py` 同次冻结两个同源产物，`--snapshot-output` 是正式运行必填：三位导演读取 Markdown 包；source guard 读取恰好三条记录的 JSON。三位导演退出后只调用 `four_by_three_control_plane_v1.py prepare-directors --state <state>`；它从同一工程推导三份导演输出、三页内容合同、layout、global chrome 和 source snapshot，再确定性完成 merge 与 `prepare-anchors`。不要人工重复传递这些路径，也不要把导演 Markdown 直接当 source snapshot。

`prepare-directors` 会在写 source snapshot 或 style job 之前执行一次轻量状态审计；初始化时间戳、事件顺序或规范工程路径有问题时应在这里确定性修正，不得带着坏状态完成 12 次生图后才到收口阶段发现。

A–D 四张锚点同波；根任务创建一个图片执行子 Agent，由它执行 `prompts/4x3-burst-runner.md` 的唯一机械入口，不创建逐图 LLM Worker。哪个锚点先结算，控制面就用既有 `prepare-fast-followers` 创建本风格两张跟随页并滚动补派，不等待所有锚点。一个执行 Agent 与真实 ImageGen 并发是两个概念：12 个节点共用 Fast8 主干的中央槽位表，真实调用最多 5 路；旧 `active_child_limit` 只作历史状态兼容，不参与新适配器容量判断。12 张齐备后调用 `four_by_three_control_plane_v1.py lean-finalize --state <state>`，直接生成 `overview/ABCD_4x3.png`、标记 `candidate_ready` 并写正式 handoff。选择前不做阻塞式完整视觉 QA；只有明确内容硬伤或锚点实质同构可触发一次定向修复。

## 严格 4×3

A–D 锚点同波完成后，用审图子 Agent 做内容、空间、工艺三门 QA。通过后创建四份风格合同和八张跟随页；每张跟随页只引用本风格锚点与必要资产，不串行学习本轮其他新页。最终总览也需同样的子 Agent QA；子 Agent 不可用时不得跳过检查或伪造通过。

## 共同约束

所有图片任务必须先 `record-dispatch-wave`，再由 `settle-wave` 结算；Worker 只接受正式返回的 job 路径与 SHA。统一空间秩序适用于所有新图，但快速候选模式不因偏好自动重抽。旧状态按原合同恢复，不静默升级或重编历史提示。

## 8×1 主干与 4×3 薄适配边界

以下只维护一份，由 Fast8 主干提供，4×3 直接复用：

- `content_contract_version=2` / `prompt_contract_version=4` 的事实、显示义务、来源状态和 `flexible_story` 语义；
- 四字段创意合并：`relationship_thesis`、`visual_quality_intent`、`visual_support_goal`、`craft_ambition`；
- 当前 v5 follower 默认附带本风格 anchor 成图来继承视觉家族、工艺和连续性，但不继承 anchor 页的关系命题、空间拓扑或对象级注意力；每页由自己的 `relationship_thesis` 和当前页内容合同定义主关系。事实/品牌必要资产已占满 5 个附件时才机械降级为文字化家族，不增加 Reviewer。旧 v4 合同继续保留锚点图路径；
- 艺术方向、视觉活跃度、注意力策略、空间拓扑枚举、空间秩序和 ImageGen prompt v4 编译；
- global chrome、标题授权、资产角色、最多 5 个附件、输入 manifest 与指纹；
- 冻结来源、source snapshot、来源漂移门、正式 generation job、`record-dispatch-wave`、`settle-wave`、PNG 校验、技术重试和无生图恢复；
- 中央 ImageGen 槽位表、文件锁、租约 TTL、claim/receipt/release 原则、媒体隔离和监测原则。

4×3 只维护以下差异层：

- 恰好三页的冻结包和逐页 bundle 外壳；
- A–D 四个跨页视觉家族，其中锚点 `visual_thesis` 不传给跟随页，家族 thesis、字体/材质/色彩/图像工艺与完成度继续传递；
- `anchor → two followers` 的 12 节点依赖图；
- Fast 与 Strict 不同的 QA 门，以及 4×3 总览/交付形态。

不要把 Fast8 的 A–H 数量、单页终局差异 Judge、两行 A–H 交付格式或至多两席替代规则硬套到 4×3。也不要为 4×3 复制来源解析、提示编译、状态机、全局并发或恢复实现；需要新能力时优先加到共享主干，再由 4×3 适配。
