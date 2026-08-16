# Fast8 裁判与收口

只在 A–H 当前候选均已结算后读取。只做一次最终 Judge，不设置 4/6 中途检查点。

## 最终组合裁判

新运行在图片执行子 Agent提交 canonical `functions.exec` 与 standby Judge 启动前，先以 250–1000 ms 初次 yield 后台启动唯一 `fast8_control_plane_v1.py await-close --state <state> --wait-seconds 900 --poll-interval 0.5` watcher，并保留 shell `session_id`。随后在同一派发回合创建一个且仅一个 `fork_turns="none"` standby Judge，显式使用 `gpt-5.6-terra` / `low` 和短版 `prompts/diversity-judge-worker.md`。它只重复运行 `await-fast8-judge-job`，把 Agent 冷启动与 ImageGen 重叠；完整 job 出现前不得打开任何图片。A–H 齐备后脚本确定性生成 contact sheet、候选路径/尺寸/SHA、完整集合哈希、唯一 `report_output_path`、严格 `report_template` 和机器可验的 `judge_runtime_contract`。standby Judge 随即从可信 `CODEX_THREAD_ID` 自绑定该唯一 job 并取得机器检查合同。历史恢复或 standby 不可用时，仍在 job 生成后创建同模型同标准的唯一 Judge，并先运行 `self-bind-fast8-judge-session`；根任务不等待、查询或转抄 Judge UUID。历史恢复才显式使用 `bind-fast8-judge-session --session-id ...`：

- 先且只查看 contact sheet；有明确疑点时才打开极少量单图；
- 先读取 review job 的 `diversity_constraint_context`：用户额外要求、语义不变量或明确参考结构要求共享的部分优先于多样性，不能单独判撞车；资产角色只授权资产出现，不自动授权相同摆位、hero photo、底栏或正文拓扑，固定标题区也只授权标题区。再判断约束之外 A–H 实际成图的实质差异与严重最低工艺退化，不承担完整内容、空间或工艺三门 QA。方向合同中声明的不同拓扑不是通过证据；只有三席或更多复用未获授权的同一整页骨架、只换配色、图标、措辞或局部装饰时，才登记为高置信同构并替换其中最弱 1–2 席；
- 若绑定 `global_chrome_contract`，在同一 Judge、同一次接触表查看中近似检查 Logo、标题层级、大致位置、对齐和安全边距。不是像素级复刻，也不评价正文审美；若正式 required asset 含非空 `use`，同一 Judge 只在该用途条件实际触发的候选中顺手检查资产是否按指定对象或位置出现，未触发不构成失败，也不扩展成完整内容 QA；
- Judge 先用 Skill 内 `pipeline_control.py` 的绝对路径运行 `check-fast8-judge-job`，从机器结果取得 job SHA、contact sheet 和预编译报告骨架，不在自然语言中转抄 SHA 或重新设计 JSON；
- 预启动的 `await-close` watcher 轮询正式 `report_output_path`，主控只续收 watcher shell session，不同时另起报告轮询。只有 watcher 返回 `waiting_for_judge_report` 后，才触发原 180 秒＋45 秒兜底：不得创建第二个完整视觉 Judge，只向原会话发送一次 report-only 指令，禁止重开图片，并最多等待 45 秒；仍无报告则明确登记基础设施阻塞，不得重建候选或伪造通过。

正式报告用 `apply-fast8-diversity-report` 原子应用；脚本会拒绝未绑定、错误模型、错误推理档位或继承历史的 Judge。初次最终决定只允许 `pass|replace`。只有高置信度实质同构，或单席同时命中至少两类严重客观工艺红旗，才允许同一轮替代 1–2 席；轻度卡片感、共同配色、主观“不够漂亮”、参考不够像或小文字问题不能授权替代。

替代是一张新的开放探索，不把旧图作为图片附件；旧图保留在 `attempt_history`。替代后只做一次 delta recheck，必要时才回退一次全量复核；决定只允许 `pass|best_effort`，不得开启第二轮替代。

标题系统结果与差异结果由同一报告写入正式状态。只有结果为 `unknown|fail` 且需要进一步定位时，才允许使用旧的独立 `prepare-global-chrome-review` 作为异常诊断路径；正常运行不再增加第二个标题 Reviewer。

## 确定性收口

最终 `pass|best_effort` 必须绑定当前完整 A–H 集合哈希。控制面 v1 随后只运行一次 `fast8_control_plane_v1.py lean-finalize --state ...`，在用户交付关键路径确定性完成：

1. 校验最终 Judge 的集合哈希和空调度队列；
2. 将 A–H 候选幂等平铺到 `origin_image/style_<A-H>_page_<页码>.<扩展名>`；
3. 复用正式目录创建阶段绑定且已通过 Pillow 预检的 Python，生成 `overview/ABCDEFGH_2x4.png`；排列固定为 `AB / CD / EF / GH`，前两行深色、后两行浅色；
4. 标记 `candidate_ready` 并封存 `process_completed`；
5. 生成并验证严格两行、九个普通链接的交付文本。

`state/handoff.json|md`、完整 `validate-state --complete`、技术健康、中央索引和七问复盘均在两行链接交付后异步执行。它们必须保留，但不得作为可点击交付的前置条件。

新运行不得由模型逐项执行上述步骤，也不得等待 Judge 最终文字。图片执行子 Agent的 canonical `functions.exec` 返回机器摘要后，根任务只续收派发前已经启动的 `await-close` shell session；它连续等待并应用现有 Judge 报告，`pass|best_effort` 后立即 `lean-finalize` 生成总览与两行链接。返回 `completed` 时逐字交付，随后才做完整 handoff、审计、监测、索引和七问；返回 `replacement_required` 时按既有 1–2 席预算完成替代后再启动同一 watcher。不得替换或补写启动阶段绑定的解释器。

父级主对话不得打开 contact sheet、单图或总览。视觉裁判在 Judge 子 Agent内执行；Judge 只回传文字报告路径和哈希，不回传图片载荷。Judge 子 Agent不可用时记录“未执行视觉检查”，不得伪造通过。

## Fast8 用户交付

使用 `references/媒体隔离与交付格式.md`。Fast8 最终可见回复严格只包含两行普通链接：第一行总览，第二行横向合并 A、B、C、D、E、F、G、H；不得附加项目目录、state、handoff、健康报告、耗时、调用次数、中央索引或任何解释。内部文件仍完整保留。
