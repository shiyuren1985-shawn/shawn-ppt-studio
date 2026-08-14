# 选定风格扩页直接运行器（唯一机械入口）

正常路径不创建逐页 LLM Worker。三导演 raw 已由 `prepare-directors` 确定性合并、正式 content v2 / prompt v4 jobs 已锁定后，根任务只创建一个图片执行子 Agent，由它提交一次下面的 canonical `functions.exec`。该执行器复用共享管线的 claim、receipt、release、恢复、PNG 校验和中央 JIT 槽位表；真实 ImageGen 最多 5 路并滚动补位，直到整个 run 终态，cap5 不是总页数上限。子 Agent 可以接收工具图片结果，但不得把任何图片载荷回传根任务。

只把 `<skill_root>` 替换为当前已加载 Skill 的绝对目录、把 `<绝对 state>` 替换为正式 state 的绝对路径；不要改写 wrapper、已编译 prompt、附件顺序或正式 job：

```javascript
const statePath = "<绝对 state>";
const skillRoot = "<skill_root>";
const shQuote = (v) => "'" + String(v).replaceAll("'", "'\"'\"'") + "'";
let r = await tools.exec_command({
  cmd: `python3 ${shQuote(skillRoot + "/scripts/selected_style_control_plane_v1.py")} render-action --state ${shQuote(statePath)}`,
  workdir: skillRoot,
  yield_time_ms: 30000,
  max_output_tokens: 30000,
});
let action = r.output || "";
while (r.session_id) {
  r = await tools.write_stdin({
    session_id: r.session_id,
    chars: "",
    yield_time_ms: 30000,
    max_output_tokens: 30000,
  });
  action += r.output || "";
}
if (r.exit_code !== 0) throw new Error(r.output || "selected-style render-action failed");
const trimmed = action.trim();
if (trimmed.startsWith("{")) {
  text(JSON.stringify(JSON.parse(trimmed)));
} else {
  await eval(action);
}
```

每页必须逐字使用 manifest 的 `imagegen_prompt` 与 `imagegen_referenced_paths`。`anchor_input_mode=raster` 只能使用 job 锁定的 primary 与可选 supporting 锚点；`text_family` 不得临时补入锚点原图。不得把新生成页面加入后续附件，不得发起第二次正常 ImageGen。已有 claim/receipt、错页、错 job 或输入指纹变化时停止对应页；单页失败不取消其他已启动页。

ImageGen 返回对象只在本次 `functions.exec` 局部变量中解析 `savedPath|output_hint`。禁止调用 `generatedImage(...)`、`image(...)`，禁止转发图片、Base64、contact sheet、逐页长解释或原始工具输出。最终只向根任务返回控制面的精简 JSON 摘要；`recovery_required` 先恢复或结算既有产物，`blocked` 只阻断报告列出的页面并确定性排空不可继续队列。
