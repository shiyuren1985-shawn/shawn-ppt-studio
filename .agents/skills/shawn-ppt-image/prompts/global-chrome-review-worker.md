# Global Chrome 子 Agent 审查合同

本合同只交给 Reviewer 子 Agent。子 Agent 可以查看正式 job 授权的图片，但只向父级主对话交接文字报告路径和哈希，不回传图片载荷。只检查成图是否大致遵循正式 job 中由大纲或用户当前要求授权的标题区，不评价正文审美、内容完整、空间门、工艺门或 A–H 差异，也不做像素级比对。

1. 读取指定 `global_chrome_review.json`，核对 job SHA、合同 SHA、候选集合 SHA 和 A–H 路径；不读取旧聊天。
2. 先查看 job 指定的 contact sheet、总览或最小必要组合图。任何字段无法判断时，只打开对应单图；不得因为缩略图太小而猜测。
3. 固定标题区的存在本身不构成呼吸感失败。只判断来源明确要求的 Logo、层级和大致位置是否成立；不测坐标，不要求字号、间距、基线或参考图像素一致。只有明显偏离才判失败。
4. 逐席返回：`logo_presence`、`official_logo_fidelity`、`title_structure`、`title_alignment_safe_margin`、`chrome_weight`，值只允许 `pass|fail|unknown|not_applicable`。来源没有要求的项目必须返回 `not_applicable`。Logo 官方性无法判断时返回 `unknown` 并检查单图/QA 参考，不得从资产库存在性反推成图合规。
5. 所有字段通过时 `decision=pass`；任何字段失败时 `decision=fail`；无失败但仍有 unknown 时 `decision=needs_inspection`。
6. 报告只包含合同允许字段，`summary` 不超过 300 字。保存到 job 指定项目的 `visual_qa_jobs/results/global_chrome_review.json`，只向父级主对话回传报告路径和 SHA-256；不得回传图片、缩略图、Base64、data URI 或大段视觉描述。Reviewer 子 Agent 不可用时暂停并修复，不得跳过检查。
