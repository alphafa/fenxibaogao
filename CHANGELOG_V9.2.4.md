# V9.2.5 Final — Owner + Professional User Report

## 内容工程
- SYS Prompt 改为老板/专业用户双层阅读目标。
- Task B：主图输出 imageRole + visualSignals + businessMeaning + nextAction。
- Task C：标题压缩为 currentExpression + reinforce + recommendedActions。
- Task D：详情按4-6个任务组输出 visualSignals + nextAction。
- Task E：收敛成老板决策摘要，不再生产大量重复长文。
- Task F：新品方案增加 sourceType（证据驱动优化 / 反馈驱动升级 / 探索性方向），默认只输出短决策字段。
- Task G：最终 Schema 与 V9.2.5 报告布局完全对齐。

## 渲染工程
- 报告顺序改为：老板速览 → 新品方向 → 标题 → 主图 → 详情 → SKU → 评论。
- 去掉独立“商品核心竞争表达”章节，避免与总览重复。
- 主图/详情以图片信息标签为主要文字层。
- 主图承接矩阵默认 details 折叠。
- 新品方案改成3列决策卡。
- 图片全部 contain，取消 cover 裁切；封面无边框。

## 兼容
- 保留旧字段回退：旧 message/professionalAdvice 仍可转换为单个短标签/动作。
- 保留 V9.2.3 图片缓存、sourceUrl/localUrl 回退与 legacy 图片归一化。
