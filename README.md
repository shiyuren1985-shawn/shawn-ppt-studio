# Shawn PPT Image

面向 Codex 的 PPT 图片策划与生成 Skill，用于完成内容预检、参考图与品牌约束整理、4×3 / 8×1 风格探索、成品总览、质量检查、失败恢复和选定风格扩页。

## 主要能力

- 默认 Fast 4×3：开放探索 A–D 四个当次方向，每套三个代表页，共 12 张成品候选；锚点完成后即以滚动并发扩展本方向，不等待其余锚点。
- Fast 8×1 Diversity（默认）：同一锚点页用八个 run-local 开放启发并发生成八个候选；显式 `flexible_story` 避免把内容与护栏重复塞入生图提示，八席用可测试的视觉活跃度和注意力策略覆盖至少三种克制方向。没有风格参考图时仍保留一条成熟度与视觉签名底线。预留第九槽给隔离组合 Judge；脚本先生成哈希绑定的低负载 contact sheet，再由快速低推理 Judge 单次查看，在同一轮内处理实质同构与严重最低工艺/构图健康退化。最多替代两张，输出 2×4 总览。
- 选定风格扩页：基于锚点和共享合同延展后续页面。
- 确定性流水线：使用状态文件、任务合同和恢复脚本管理生成过程。
- 非阻塞运行监测：完成任务与明确终止的真实任务都进入轻量集中索引，专用审查任务可按全部记录、任意最近数量或待审状态复盘；不增加生图调用也不阻断交付。

新 Fast 4×3 不再为 12 张图片创建逐图 LLM Agent；根任务用一个机械控制面执行 `anchor → same-style followers` 依赖图，并与 Fast8 共用中央 ImageGen 槽位表，真实调用最多 5 路。

Fast 8×1 同样请求 9 个子 Agent 槽位，但最多只有 8 个图片动作在途；第九槽专门留给隔离组合 Judge，不增加图片调用。Judge 默认使用 `gpt-5.6-terra` / `low`，从机器校验结果取得预编译报告路径和 JSON 骨架；正式交付文本固定为两行：总览一行，A–H 八张图片链接合并一行。

新 Fast8 的艺术导演提示要求每席由一个主导视觉动作或关系承担第一层故事，其他必要信息降为从属证据；在生图前还检查 A–H 的粗粒度空间拓扑组合，直接减少反复出现的“双栏＋节点/框体＋底部横条”骨架。`restrained|balanced|expressive` 只控制视觉活跃度，不改变内容密度；八席显式区分关系表达、工艺轴和空间组织，但不固化像素模板。Judge 只有在多个第一层区域竞争、解释模块过载、装饰节点过载或边缘无停顿中至少两类达到严重程度时才替换，普通高密度和轻度卡片感仍不触发。新 Fast8 在同一次 ImageGen 调用中写成功或失败机器回执；控制器主动监听并立即结算，不等待 Worker 最终文字。A–H 齐备后默认只做一次终局 Judge；标题硬合同合并进同一审图回合。Judge 通过后由一个确定性命令完成总览、handoff、状态审计、监测和交付文本，压缩工具结束后的长尾。

Fast 8×1 从用户请求到可点击交付以 15 分钟为软目标；超时会记录但不会强制终止任务或跳过质量与恢复门禁。

## 安装

Codex 会从用户目录和项目的 `.agents/skills` 中发现 Skills。只使用 Skill、不使用 Studio 的用户，可以直接把本仓库克隆到用户 Skill 目录：

```powershell
git clone https://github.com/shiyuren1985-shawn/shawn-ppt-image-skill "$env:USERPROFILE\.codex\skills\shawn-ppt-image"
```

macOS / Linux：

```bash
git clone https://github.com/shiyuren1985-shawn/shawn-ppt-image-skill \
  "$HOME/.codex/skills/shawn-ppt-image"
```

本仓库是 Skill 的唯一开发源，可独立安装、测试和发布。Shawn PPT Studio 在开发环境中优先使用用户 Skill 目录中的安装；发布包内保留一份由本仓库同步生成的固定版本兜底，因此普通 Studio 用户不需要另外安装 Skill。

## 本地开发与 Studio 联调

同时维护 Skill 和 Studio 时，不要复制两份分别修改。把本仓库克隆到普通开发目录，再将 Codex 的安装路径链接到这份 checkout：

```bash
git clone https://github.com/shiyuren1985-shawn/shawn-ppt-image-skill \
  "$HOME/Projects/shawn-ppt-image-skill"
ln -s "$HOME/Projects/shawn-ppt-image-skill" \
  "$HOME/.codex/skills/Shawn-PPT-image"
```

此后直接修改并提交本仓库；本机 Studio 的新任务会读取同一份本地文件，不会从 GitHub 在线拉取。Studio 发版前，再在 Studio 仓库运行同步脚本，把已经测试并提交的 Skill 版本写入应用包兜底副本。正在运行的任务仍应使用启动时冻结的合同和状态，不把热更新强行写入旧任务。

## 依赖

- 需要兼容的 Codex 客户端和有效登录。
- 图片生成使用 Codex 提供的系统级 `imagegen` Skill；本仓库不复制或修改它。运行前应确认当前 Codex 环境能够发现并调用 `imagegen`。
- 控制面使用 Python；联系表和图片检查需要 Pillow。Codex 桌面端应优先使用其 workspace dependencies 返回的绑定 Python，不建议修改系统 Python。
- 可选品牌资产库通过 `SHAWN_PPT_ASSET_LIBRARY_ROOT` 指向。未设置时，只使用任务中明确提供的资产和参考图。

## 使用

在 Codex 中明确调用 `$shawn-ppt-image`，并提供内容大纲、页面大纲、参考图或品牌资产。完整工作方式与输出规则见 [SKILL.md](SKILL.md)。

## 验证

```bash
python3 -m unittest discover -s tests -v
```

本仓库不包含运行生成的图片、项目状态或 Python 缓存文件。
