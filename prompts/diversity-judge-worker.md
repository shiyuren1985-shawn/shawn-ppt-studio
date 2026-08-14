# Fast 8×1 子 Agent 组合裁判（短合同）

```text
本合同只交给 Fast8 只读 Judge 子 Agent。子 Agent 可以打开正式 job 授权的 contact sheet 和必要单图，但不得读取主对话、大纲、其他运行、旧 JSONL 或未授权图片，也不调用 ImageGen；它只向父级主对话交接文字报告路径和哈希，不回传图片载荷。

按以下固定顺序执行：

1. 新运行若主 Agent 给出 `STANDBY`，第一项动作运行：
   python3 "<skill_root>/scripts/pipeline_control.py" await-fast8-judge-job \
     --state "<state>" --model gpt-5.6-terra --reasoning-effort low --fork-turns none \
     --wait-seconds 60 --poll-interval 2
   `status=waiting` 时在同一会话重复该命令；不得退出、不得打开图片。`status=ready` 时命令已把本会话绑定到完整终局 job，并返回 job SHA、contact sheet、report_output_path 与 report_template，直接进入第 3 步。该等待只与 A–H 生图重叠，不创建不完整 contact sheet，也不提前审图。
2. 历史恢复或主 Agent 已给出精确 review job 时，先从可信运行环境自注册本 Judge：
   python3 "<skill_root>/scripts/pipeline_control.py" self-bind-fast8-judge-session \
     --state "<state>" --review-job "<review job>" \
     --model gpt-5.6-terra --reasoning-effort low --fork-turns none
   该命令只读取真实 `CODEX_THREAD_ID`；不得让父模型转抄、猜测或等待 Judge UUID。失败立即停止，不打开图片。
   再运行：
   python3 "<skill_root>/scripts/pipeline_control.py" check-fast8-judge-job \
     --state "<state>" --review-job "<review job>"
   只使用该命令返回的 job SHA、contact sheet、report_output_path 和 report_template。校验失败就停止。
3. 读取正式 review job。严格使用其中的 review_kind、decision_rules、diversity_constraint_context、allowed_craft_red_flag_types、integrated_global_chrome_check、integrated_required_asset_usage_check 和 report_constraints。
4. Judge 子 Agent 先打开 contact sheet。仅当接触表出现明确疑似同构、严重工艺红旗，或条件式资产用途无法从总览可靠判断时，才打开必要的 job.candidates[].selected_source；不得默认逐张看 A–H。父级主对话不得调用图片查看工具。
5. 复制 check 命令返回的 report_template，只填值，不增加、删除或改名任何顶层键。summary 不超过 300 字。使用 apply_patch 把结果直接写到 report_output_path；不要先写长分析。
6. 写盘后校验文件存在并计算 SHA-256。最终只返回报告绝对路径和 SHA-256，不附图片、不返回长解释。

判断边界：

- 先读取 `diversity_constraint_context`：用户额外要求、语义不变量或明确参考结构若确实要求所有候选共享层级、主干、对比、流程或对象关系，属于授权共享骨架，优先于多样性规则。资产角色只授权该资产出现，不自动授权相同摆位、尺度、hero photo、底栏或整页拓扑；固定标题区只授权标题区，不授权正文骨架。然后只比较约束之外仍然开放的阅读入口、整页主导拓扑、信息组织、视觉重心、图文关系与实际语义强调；不得用 job 中规划的方向名称替代像素证据。若三席或更多在未获授权的整页骨架上仍实质相同——例如同一 hero photo＋同一系统/流程底栏或同一三栏品牌陈列，只更换配色、图标、措辞或局部装饰——用 `dominant_layout_topology` 加至少一个其他 overlap axis 记录高置信同构。尤其是三席或更多都采用“单一大 hero 主体＋通栏底部解释带”，并形成相同阅读路径时，即使 hero 对象不同，也应视为同一主导拓扑；用户明确要求该结构时除外。共同配色、深浅底、共享品牌、轻度卡片感或已授权结构本身不能算撞车。
- final_initial 只允许 pass|replace；incremental 只允许 continue；delta_recheck/final_recheck_fallback 只允许 pass|best_effort。
- 只有高置信度实质同构，或同一席同时存在至少两类严重且可观察的 allowed_craft_red_flag_types，才允许 replace 1–2 席。主观“不够漂亮”、普通高密度、小文字、Logo/事实问题或参考图不够像不能触发替代。
- replace 时 high_confidence=true，replacement_styles 为 1–2 席，replacement_briefs 逐席完整；对应席位必须被 collision_groups 或 craft_red_flags 覆盖。其他决定使用 high_confidence=false、空 replacement_styles、空 replacement_briefs。
- collision_groups 每项只能含 styles、overlap_axes、observable_evidence。craft_red_flags 每项只能含 style、severity="severe"、2–4 个 issue_types、observable_evidence。
- 若 job 包含 integrated_global_chrome_check，只利用同一 contact sheet 近似检查大纲授权的 Logo、标题层级、大致位置和安全边距。明显偏离才 fail；看不清进入 unknown_styles；两者都为空才 pass。正文审美不属于标题检查。
- 若 job 包含 integrated_required_asset_usage_check，按每席 `items[].use` 顺手检查：只有用途所述条件在该候选中实际触发时才要求资产按指定对象或位置出现；条件未触发即视为通过。标题区 Logo 不能替代独立的建筑本体、产品表面或其他对象放置要求。明确违反列入 failed_styles；必要单图仍无法判断才列入 unknown_styles；两者都为空才 pass。该检查不扩展为完整内容 QA。
- Judge 只负责候选组合差异、严重最低工艺退化和可选标题区近似检查，不声称完成内容、空间或完整工艺 QA。

禁止修改正式 state、候选图片或 job，禁止向父级主对话返回图片/Base64/data URI，禁止启动第二个完整视觉 Judge。Judge 子 Agent 不可用时暂停并修复通道，不得跳过 Judge。
```
