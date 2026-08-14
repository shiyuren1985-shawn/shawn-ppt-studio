# Fast8 Canonical functions.exec Wrapper v1

本文件保留新 Fast8 唯一 canonical `functions.exec` wrapper。正常路径由根任务交给一个图片执行子 Agent 逐字提交；历史运行可继续按原路径读取同一合同。根任务不做内容、审美、版式、品牌或提示词判断，不打开图片，也不改写任何正式 job。子 Agent 内部允许接收 ImageGen 工具图片结果，但不得把图片载荷回传根任务。

只执行以下固定动作：

1. 图片执行子 Agent 只允许提交一次 `functions.exec`，并逐字使用下面的静态 wrapper；把 `<skill_root>` 替换为当前已加载 Skill 的绝对目录，把 `<绝对 state>` 替换为本次 state 的绝对路径，不得改变其他代码：

```javascript
const statePath = "<绝对 state>";
const skillRoot = "<skill_root>";
const shQuote = (v) => "'" + String(v).replaceAll("'", "'\"'\"'") + "'";
let r = await tools.exec_command({
  cmd: `python3 ${shQuote(skillRoot + "/scripts/fast8_control_plane_v1.py")} prepare --state ${shQuote(statePath)} --render-action`,
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
if (r.exit_code !== 0) throw new Error(r.output || "render-action failed");
await eval(action);
```

2. `action` 只存在于同一次 `functions.exec` 的局部变量中，不把约 45KB 输出带回模型上下文，不改写、不拼接第二套 wrapper；禁止普通 `eval(action)`，也禁止把未 await 的 IIFE 当 raw source 提交；
3. 该动作会在八个独立 async 分支中执行既有 ticket 的 `claim → ImageGen → savedPath/receipt → release`，并由 `Promise.allSettled` 隔离单席失败；
4. 必须逐字使用 manifest 中每席的 `imagegen_prompt`，并逐项使用同席 `imagegen_referenced_paths`；不得改写、摘要、补充、删除或跨席混用；
5. 不得发起第二次正常 ImageGen。若控制脚本返回 duplicate claim、错页、错 job 或输入指纹变化，立即停止该席；若仅一席失败，其余席继续完成；
6. 正常路径不查询 UUID、不等待 Worker 文字、不扫描 session 目录。只有结算结果明确列出 `session_forensics_required_styles` 时，才把这些席位交回主控走异常取证；
7. ImageGen 返回对象只在本次 `functions.exec` 的局部变量中解析 `savedPath|output_hint`；严禁调用 `generatedImage(...)`、`image(...)` 或转发任何图片内容块；
8. 最终只向根任务返回脚本的小型 JSON 摘要，不返回图片载荷、Base64、contact sheet 或逐席解释；图片载荷留在子 Agent 内。

图片执行子 Agent 只是固定机械 wrapper 的承载者，不改写 prompt 或承担导演职责。图片质量完全来自已锁定 job 和 ImageGen；历史 Runner 恢复不得改写本 wrapper。
