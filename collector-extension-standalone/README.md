# 三笙电商商品详情采集扩展 v9.3.0（兼容参考）

跨类目采集标题、类目候选、主图、详情图、SKU 图、评论图、动态参数、变体、促销、评论与问答。字段由页面结构和文本自动发现，不绑定家纺 BOM。

此目录是独立采集扩展参考实现，不是研发日常使用的主入口；完整工具请使用根目录 `extension/` 与 `start-tmall-ai.command`。

当前服务固定为 `http://127.0.0.1:17962`。扩展只响应手动点击，采集当前单商品页后提交
`POST /api/analyze-current`（`allowPartialReviews: true`）；旧版 `:3300/api/collector/product-page`
队列已退役，不要再按旧文档配置服务地址或自动抓取任务。
