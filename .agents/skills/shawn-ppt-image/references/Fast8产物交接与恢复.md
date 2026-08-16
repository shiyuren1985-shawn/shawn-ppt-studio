# Fast8 产物交接与恢复

只在 Fast8 图片工具开始返回后读取。目标是让图片结果立即绑定到正式 job 和 receipt，不等待模型文字，也不创建第二套恢复管线。

## 同次调用原子闭环

唯一 canonical `functions.exec` 中的每个 A–H 分支必须且只能完成：

1. `claim` 验证当前页、唯一 ticket、job SHA、图片输入指纹并取得中央 JIT 槽位；
2. 逐字调用正式 `imagegen_prompt` 与 `imagegen_referenced_paths`；
3. 从同次工具结果取得唯一绝对 `savedPath`，由脚本验证文件、16:9、工具 ID 和 job 身份并原子写 receipt；
4. 在 receipt 或 `finally` 中幂等 release；
5. 由 `Promise.allSettled` 隔离失败，禁止一席失败取消其他席位。

八个分支结束后运行一次 `fast8_control_plane_v1.py settle --state ...`。有效 receipt 直接结算；明确 `backend_network|backend_failed` 按既有预算排一次技术重试；只有工具 completed 但 `savedPath/receipt` 缺失或不可解析时，才进入无生图恢复。duplicate claim、错页、错 job 或输入指纹变化直接拒绝，不再次生图。

## 无生图恢复

无生图恢复不增加图片尝试次数。只在已知准确工具时间窗或准确会话目录时运行 `scripts/recover_image_artifact.py`，不得按最新时间戳猜文件、打开原始 `.jsonl` 或让根任务接收图片载荷。

- 路径可读且身份唯一时立即绑定，不因缺少普通文字总结进入恢复。
- 工具明确 failed/network error 时跳过产物恢复，直接进入一次技术重试预算。
- 同一动作与 attempt 得到两份独立 `not_found` 证据后，才允许技术重试。
- 恢复成功保留原 `source_action`、工具时间、恢复时间和 `recovery_method`；只有新的 ImageGen 调用才增加 attempt。
- 技术重试使用独立 receipt 路径；成功后以新 attempt 的 Worker、工具和文件时间覆盖当前计时，第一次失败留在 `attempt_history`。
- 必需席位在无 incumbent 的情况下耗尽技术重试后，原子把 run 设为 blocked、清空队列并释放租约，不同时启动另一份生图运行。

## 长尾判断

分别记录图片后端、机械分支和文件绑定时间。正常路径只认同次调用的 `ticket → savedPath → receipt`，不等待文字、不扫描 session、不做三路重复取证。已经存在有效 receipt 的 ticket 不得重复生图；冻结 job 后的重试和替代不再读取上游完整大纲。
