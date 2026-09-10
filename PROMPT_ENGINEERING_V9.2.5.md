# Prompt Engineering V9.2.5

## 目标
默认报告从“信息面板”升级为“大图大字决策报告”。模型不负责写长分析，而负责把真实证据压成短判断、图片信息标签和下一步动作。

## 总原则
- 大图讲事实，大字讲判断，短句讲动作。
- 老板先看：为什么能卖 / 值得继承 / 下一款优先。
- 专业用户再看：标题 / 主图 / 详情 / SKU / 消费者。
- 图片文字、规格、材质、权益、功能优先转成 visualSignals。
- 同一结论默认只出现一次。
- 未采集经营数据不推断市场规模、转化、利润。

## 可见字段硬限制
- verdict/professionalOpinion <= 45字
- owner headline <= 18字；note <= 22字
- title keyword <= 10字
- main imageRole <= 8字；visualSignals 2-3项，每项<=10字；nextAction<=18字
- detail visualSignals 2-3项，每项<=10字；nextAction<=18字
- SKU professionalOpinion <=35字；recommendedAction<=24字
- review insight <=28字
- plan productAction/pageAction <=28字

## Task B 主图
输出 imageRole + visualSignals + nextAction。visualSignals 必须是图上真实信息，如“40支新疆棉”“免费仓储”“六件套”。禁止“高级感强”“表达清晰”这类抽象词充当图片信息。

## Task D 详情
按4-6个信息任务组：品牌服务 / 套件组成 / 材质品质 / 产品功能 / 使用便利 / 花型选择 / 用户验证。每组只放代表图、2-3个 visualSignals、1个 nextAction。

## Task E 老板摘要
只回答三个问题：为什么能卖、值得继承、下一款优先。

## Task F 新品
默认最多3套，区分：证据驱动优化 / 反馈驱动升级 / 探索性方向。每套只保留 sourceType、name、productAction、pageAction 四个核心字段。产品动作是开品核心；页面动作负责完整主图与详情打造。参考图不占分析字段：用户可在生成时上传，未上传则使用当前商品第一张主图。

## Task G 编排
顺序固定：老板速览 → 下一款先做什么 → 标题 → 主图 → 详情 → SKU → 消费者。商品价值不再独立成章。
