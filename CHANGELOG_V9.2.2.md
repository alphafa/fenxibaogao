# V9.2.2

## P0 图片链路修复
- 修复 standalone / legacy collector 已采集 `images.main/detail/sku`，但因缺少 strict-v1 provenance 在 `analysis._normalize_image_groups()` 被全部丢弃的问题。
- legacy/standalone 模式现在保留采集器已经分组的 main/detail/sku，并生成兼容 provenance。
- buyerShow 仍只从评论记录建立，避免页面图误归类为买家秀。
- 保留 V9.2.1 本地图片缓存与远程 URL 回退。
