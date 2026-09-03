# V9.2.1 图片加载修复版

## 修复
- 修复采集完成后报告图片可能全部无法加载的问题。
- 图片缓存改为多策略请求头重试：天猫 Referer、淘宝 Referer、淘宝首页 Referer、无 Referer。
- 支持 protocol-relative (`//...`) 与 data:image 图片进入本地缓存。
- 缓存结果增加图片文件签名校验，不再只依赖 Content-Type。
- 本地缓存失败时保留原始 sourceUrl，浏览器继续尝试远程回退。
- Renderer 取消 `referrerpolicy=no-referrer`，避免阻断部分电商 CDN 回退加载。
- 图片本地资源仍通过 `/reports/assets/<task>/<group>/...` 提供。

## 回归验证
- 21/21 tests passed.
- SKU 缺失不等于 0、图片驱动报告、新品方案、图片缓存优先级等 V9.2.0 行为保持不变。
