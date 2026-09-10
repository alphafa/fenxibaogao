# 三笙电商商品分析报告插件 v9.3.0

用于把淘宝/天猫当前商品采集结果转成跨类目商品分析、新品设计和 AI 视觉生图报告。插件输出必须和本地服务 V9.3.0 的报告、生图接口保持同一份字段契约。

- `skills/tmall-product-analysis-report/SKILL.md`：跨类目分析、提示词和生图闭环规范。
- `scripts/normalize_capture.mjs`：把扩展采集 JSON 标准化为可提交给本地服务的输入。
- `assets/capture-extension/`：采集扩展参考实现；主工具入口仍是仓库根目录 `extension/`。
- `assets/taobao_detail_fields_v8.3.6.xlsx`：保持原文件名的跨类目字段对照表。

## V9.3.0 生图工作流

报告中的每个“下一款方向”都可以进入完整图片套装流程：

1. 读取报告事实和方案（`_load_report_for_generation`）。
2. 拆成有顺序的主图/详情图槽位（`build_generation_slots`）：主图最多 5 位，详情图最多 15 位；界面默认勾选主图 5 位和详情前 6 位。
3. 确定产品参考（`resolve_reference_images`）：用户上传最多 4 张优先，否则使用采集到的第一张主图。
4. 组装提示词（`build_image_prompt`、`merge_image_prompt_with_user_edit`），预览和正式生成共用同一逻辑。
5. 由 `image_generate` 调用独立或继承的 OpenAI-compatible 生图渠道。
6. 每张图保存到 `server/reports/assets/generated/<jobId>/`，并在 `consistencyGate.status=needs_review` 下等待人工复核。

浏览器报告的触发链是 `initPlanActions` → `refreshPromptPreview` → `POST /api/generate-images` → `pollJob`。提交成功后使用返回的 `jobId` 或 `statusUrl` 轮询 `GET /api/image-job/<jobId>`，不要把长时间生图请求做成同步阻塞。

## 提示词与请求契约

最终提示词按以下顺序组成：统一 `identityLock`（报告事实和用户 `productOverrides`）→ 参考图模式（`uploaded_reference`、`collected_reference`、`fission_base`、`fission_followup`）→ 全局用户方向 → 新品方案和爆款表达方法 → 当前槽位的 `assetType/index/role/task/handoff` → 页面参数、视觉和构图约束 → 平台禁区 → `image_generation` 模板中的 `{prompt}` → 相关性守卫后的 `promptMerge`。用户明确指定的材质、颜色、结构、件数、尺寸、规格、花型、款式或功能可以覆盖对应默认字段；品牌、交易、认证、二维码、水印等禁区始终拦截。

两个业务接口共用下列字段：

```json
{
  "source": "报告 JSON 在本地 reports 目录中的路径",
  "planIndex": 0,
  "assetTypes": ["main", "detail"],
  "selectedSlots": ["main:1", "detail:3"],
  "referenceImages": ["data:image/png;base64,..."],
  "userDirection": "全局最终要求",
  "promptOverrides": {"detail:3": "本张相关编辑"},
  "fissionPattern": true,
  "completeSet": true
}
```

`POST /api/image-prompt-preview` 返回 `slots`、`prompts`、`promptMerges`、`userDirectionBySlot` 和参考图状态；`POST /api/generate-images` 返回 `jobId`、`statusUrl`。状态包括 `queued`、`generating`、`complete`、`error`，完成结果包含每张图的 `assetType`、`slotIndex`、`prompt`、`identityLock`、本地 `url` 以及 `consistencyGate`。主图固定 `1024x1024`，详情图固定 `1024x1536`，每个槽位 `n=1`。

配置页把分析渠道和生图渠道分开显示：`image_model` 必填且独立于文本 `model`；`image_api_base`、`image_api_key` 为空时分别继承分析渠道对应字段。`image_models_path`（默认 `/models`）只用于保存/测试时查模型列表，真正出图使用 `image_path`（默认 `/images/generations`）。请求体会发送 `model`、`prompt`、`size`、`n`，并按供应商兼容形态尝试 `image`、`reference_images` 或 `images`；返回的 URL/Base64 会在本地落盘，页面不会显示任何 Key。

## 采集输入标准化

运行：

```bash
node scripts/normalize_capture.mjs <capture.json> > normalized.json
```

标准化结果保留 `meta`（含 `imageClassificationVersion`）、`collection`（含 `reviewCollectionComplete`）、`images.provenance/classification`、`parameterCollection`、`pageText` 和 `monitoring`，以免丢失评论完整性、图片分源或参数采集状态。评论未确认完整时，应通过 `/api/analyze-current` 的 `{raw, allowPartialReviews:true}` 进入分析；只有 `reviewCollectionComplete=true` 才提交 `/api/analyze`。

采集扩展参考目录中的旧队列实现不是当前主服务入口；使用时应以根目录 `extension/`、`http://127.0.0.1:17962` 和上述接口为准，不要把旧的 `:3300/api/collector/product-page` 地址当作可用服务。
