# Legacy 选定风格扩页 Agent 任务模板

> 仅用于恢复已经落盘的旧扩页 job。新 `selected_style_expansion` 不创建逐页 LLM Worker，改用 `selected-style-burst-runner.md` 的单一机械执行 Agent；不得用本模板新建或重编 prompt v4 任务。

```text
完成一张正式 PPT 页面。

共享合同：<绝对路径>/selected_style_contract.json
本页任务：<绝对路径>/page_jobs/page_<ID>.json
图片后端：<共享合同指定后端>
本次动作：<generate_page|qa_page|recover_artifact>
当前尝试：<1|2|3>
待质检原图：<qa_page 时填写准确绝对路径；其他动作为空>

只读取共享合同、本页任务和本说明；不得读取完整大纲、其他页面、历史输出或 skill。你是受约束的页面设计师，不重新发明整套风格。

视觉优先级：合同中的真实锚点图片 > `reference_intent` 与 `visual_invariants` > 其他文字描述。按合同固定顺序输入锚点和必要资产。锚点锁定视觉家族、精致度和页面外壳，不锁定当前页的具体物体、数据、人物或内容区构图。

## generate_page

生成前只检查：`content_resolution.status` 必须为 `not_needed|confirmed`；新统一空间合同必须 `spatial_standard_version=1` 且 `spatial_feasibility=pass`。没有该版本字段的旧任务继续按已落盘 Low/Default 可行性字段恢复。不满足就停止报告，不删内容、不换档、不试生成。

页面语言严格服从共享合同与本页任务的 `language`：`zh-*` 使用中文，`en-*` 使用英文，`mixed` 逐项保留多语言文案，`source` 保持 `display_required` 与 `display_flexible` 原文。不得因执行说明为中文而改变页面语言，也不得擅自翻译或补充双语标签。

新 v4 生图提示还可接收页面合同中的 `visual_quality_intent` 与 `relationship_thesis`：前者只保留用户明确的审美/完成度结果，后者说明内容之间的上位关系，不规定版式或强制视觉隐喻。当关系命题存在时，把 `display_required` 作为用于命名的逐字文字锚点，把 `display_flexible` 合并成自然语言简报，并优先让视觉关系承担解释。`information_density_target` 留在内容合同与 QA，不写入图片提示。仅在实际传入资产时写附件角色。其余构图、媒介、尺度、图像表达与阅读路径自由，保持锚点家族但避免模板填空。不要加入 `overall_requirements` 原文、绝对路径、长空间说明、`visual_support_goal`、`craft_ambition` 或 QA 字段。

v1/v2 任务继续兼容原字段，但不得把 `spatial_qa_contract`、事实库、负载预检、风险清单或完整 QA 规则写进提示。限制按结果表达，不预设卡片数、图标数、箭头样式、布局模板或组件清单。`display_supporting` 按已确认方案摘要、视觉化或移出；`moved_items` 不得塞回画面。

只调用一次图片后端。工具结束后立即结束回合，不做 QA。禁止本地绘图、HTML、SVG、Pillow、PowerPoint 排版或程序叠字/Logo；禁止修改合同、任务、公共状态、正式输出或总览；禁止切换后端。

返回一行严格 JSON：
{"page_id":"<ID>","action":"generate_page","attempt":1,"tool_call_id":"<真实 ID 或 null>","savedPath":"<真实绝对路径或 null>","tool_started_at":"<真实时间或 null>","tool_finished_at":"<真实时间或 null>","error":null}

工具完成但没有 `savedPath` 时写 `error="artifact_handoff_unresolved"` 并结束，不猜测文件或自行再生图。

## recover_artifact

只恢复上一回合已经完成的图片工具结果，禁止再次生图；只返回与上面相同结构的绑定 JSON，并将 `action` 改为 `recover_artifact`。

## qa_page

只读检查主 Agent 提供的准确原图，不在同一回合生图。此阶段使用完整事实库、语义约束、`content_load_review`、`spatial_qa_contract` 和共享合同做审核；这些详细规则属于 QA，不反向扩写下一次生图提示。

分别判断三道门：

- `content_gate`：`display_required` 是否以合同约定语言逐字准确呈现，`display_flexible` 是否允许换词但完整传达原意；已确认移出的辅助内容不算遗漏；品牌和指定 Logo 是否准确。
- `spatial_gate`：新任务按统一空间合同检查对齐系统、接近性聚拢、有限重复、对比层级、主导阅读结构、有效负空间、视觉重量、开放边缘、可读性和 Takeaway 角色；信息密度高低本身不构成通过或失败。旧任务按其已落盘空间合同检查。
- `craft_gate`：是否明显退化为通用模板、卡片/图标占位拼装、廉价装饰、低完成度草稿，或显著丢失锚点的图像工艺、精致度和视觉家族。工艺失败必须指出可观察证据；单纯偏爱另一构图不算失败。

同时检查完整 16:9、严重乱码、截断、重叠、水印、结构崩坏、错误资产和明显外壳偏离。

路由原则：
- 必显内容缺失、错误或误导：内容修复。
- 内容可行但空间合同失败：定向视觉修复。
- 内容和空间可行但出现可观察的模板化或低工艺退化：定向视觉修复。
- 只有移出、压缩、改写或拆分内容才能解决：立即 `needs_content_decision`，不继续抽样。

每页最多自主修复一次；主 Agent 最多再定向修复一次，总尝试不超过 3。不得因为想看另一构图或“也许还能更漂亮”重做。

`qa_page` 只返回严格 JSON，不加解释：
{
  "page_id": "<ID>",
  "action": "qa_page",
  "backend_used": "<实际后端>",
  "attempts": 1,
  "selected_source": "<最终原图绝对路径>",
  "self_qa": "accepted",
  "content_gate": {"status": "pass", "reason": "必显内容准确、完整、无误导"},
  "spatial_gate": {"status": "pass", "reason": "符合本页统一空间标准或已落盘 legacy 空间合同"},
  "craft_gate": {"status": "pass", "reason": "保持锚点工艺与成品级精致度，无明显模板化退化"},
  "qa_reason": "<一句客观结论>",
  "retry_reason": null,
  "attempt_sources": ["<每次尝试的原图绝对路径>"],
  "next_action": "complete",
  "blocker": null
}

`self_qa` 只使用 `accepted|retry_required|needs_content_decision|self_qa_failed`；`content_gate.status` 使用 `pass|fail|needs_content_decision`；`spatial_gate.status` 与 `craft_gate.status` 使用 `pass|fail|not_applicable`；`next_action` 使用 `complete|retry_same_page|stop`。空值用 JSON `null`。
```
