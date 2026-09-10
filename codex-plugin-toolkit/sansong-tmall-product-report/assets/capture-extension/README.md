# 三笙电商商品详情采集扩展 v9.3.0（兼容参考）

跨类目采集商品标题、类目候选、主图、详情、SKU、动态参数、评论和问答。家纺仅为分析模板分支，不限制采集字段。

这是随插件打包的兼容参考扩展，不是研发日常使用的主入口。推荐加载仓库根目录的
`extension/`，并先启动 `start-tmall-ai.command`。当前本地服务固定为
`http://127.0.0.1:17962`；本扩展只在用户手动点击时采集当前单商品页，然后提交
`POST /api/analyze-current`（`allowPartialReviews: true`）。

旧版 `:3300/api/collector/product-page` 队列已退役，不要再按旧文档配置服务地址或自动抓取任务。
