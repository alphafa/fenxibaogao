# Prompt Engineering V9.2.5

## 总目标
报告服务两类用户：
- 老板/决策者：30秒内回答为什么能卖、什么值得继承、下一款先做什么。
- 专业商品用户：从图片中快速提取卖点、规格、证明与可执行动作。

核心原则：分析可以深，默认报告必须轻；图片信息优先于AI解释。

## SYS Prompt
新增硬规则：
- 同一结论默认只展示一次。
- 图片逐张提炼 `visualSignals`，禁止用长段 `message` 作为默认输出。
- 探索性新品必须标记 `sourceType=探索性方向`。
- 图片完整显示优先，Renderer 使用 contain。

## Task B — 主图商业信息提炼
默认字段：
- `imageRole`：图片承担的商业任务，<=10字
- `visualSignals`：2-4个图片可核验信息，每项<=12字
- `businessMeaning`：内部解释，<=28字
- `nextAction`：下一款动作，<=22字
- `evidenceDetail`：构图/OCR/颜色等深层分析，默认折叠

## Task C — 标题压缩
默认字段：
- `professionalOpinion` <=55字
- `currentExpression`：短词组
- `reinforce`：短词组
- `recommendedActions`：<=28字

## Task D — 详情证明信息
按4-6个任务组，不逐张流水账：
- `type`
- `representativeImageId`
- `visualSignals`
- `businessMeaning`
- `nextAction`

## Task E — 老板决策摘要
只输出可供最终报告压缩的：
- 为什么能卖
- 值得继承
- 下一款优先
不再要求大段 opportunity map / top drivers / top risks 默认展示。

## Task F — 新品方向
每套方案默认只保留：
- `sourceType`：证据驱动优化 / 反馈驱动升级 / 探索性方向
- `name`
- `whyThisPlan`
- `productAction`
- `pageAction`
- `validation`
- `visualReferenceImageIds`

## Task G — 最终编排
顺序固定：
1. 老板速览
2. 下一款方向
3. 标题
4. 主图在卖什么
5. 详情页证明什么
6. SKU怎么选
7. 消费者实际感受到什么

商品价值不再独立重复一章，合并进老板速览。

## 字数控制
- professionalOpinion <=55字
- ownerOverview headline/note <=28字
- imageRole <=10字
- visualSignal <=12字
- nextAction <=22字
- review insight <=35字
- plan why <=45字
- plan product/page action <=35字

## 证据规则
所有结论继续绑定 `evidenceIds`。图片信息标签必须来源于：
- 图片可读文字
- 图片可见产品/场景
- 与该图片明确关联的页面参数
不得用市场常识补齐。
