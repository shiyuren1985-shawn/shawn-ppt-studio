# 新 Fast 4×3 直接运行器（唯一机械入口）

正常路径不创建 12 个逐图 Worker。根任务在三导演输出已经确定性合并、A–D 锚点 jobs 已锁定后，创建一个图片执行子 Agent，由它只提交一次 `functions.exec`；该机械表达式按 `anchor → same-style followers` 的依赖图滚动运行，共用 Fast8 主干的中央 ImageGen 槽位表，真实 RPC 最多 5 路。子 Agent 可以接收 ImageGen 工具图片结果，但不得把图片载荷回传根任务。

只把 `<skill_root>` 替换为当前已加载 Skill 的绝对目录、把 `<绝对 state>` 替换为正式 state 的绝对路径后逐字执行；内容合同目录由 state 的规范工程路径推导，不再人工传递。不要改写已编译的 prompt 或附件：

```javascript
const rendered = await tools.exec_command({
  cmd: "python3 '<skill_root>/scripts/four_by_three_control_plane_v1.py' render-action --state '<绝对 state>'",
  workdir: "<skill_root>",
  yield_time_ms: 30000,
  max_output_tokens: 4000
});
if (rendered.exit_code !== 0) throw new Error(rendered.output || "4x3 runner compile failed");
await eval(rendered.output);
```

ImageGen 返回对象只在这次 `functions.exec` 的局部变量中解析 `savedPath|output_hint`；不得调用 `generatedImage(...)`、`image(...)` 或把图片内容块转发父级主对话。结果为 `complete` 后只调用 `four_by_three_control_plane_v1.py lean-finalize --state <state>` 进入 4×3 总览与交接。结果为 `recovery_required` 时先恢复或结算既有产物，不得再次生图；结果为 `blocked` 时结束旧运行，不新开并行替代任务。父级主对话不打开图片。
