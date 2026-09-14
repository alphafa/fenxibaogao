---
name: tmall-product-analysis-report
description: Generate evidence-based, cross-category ecommerce product analysis reports and V9.3.0 image-generation briefs from captured product evidence.
---

# 三笙电商商品分析报告引擎

本技能把真实电商商品数据转成完整阅读型报告和下一款 AI 视觉方案。报告面向商品、运营、设计、供应链和决策者；研发需要时可沿同一份字段契约查看提示词、槽位、接口和复核状态。

## 工作顺序

1. 读取类目、标题、参数、SKU、主图、详情图、评论、买家图和问答。
2. 自动识别类目及分析维度。家纺只是分支，不是默认模板。
3. 建立证据编号，并把内容分为数据事实、分析判断、设计建议和证据不足。
4. 输出商品总览、商品画像、标题、主图、详情、SKU、评价、商品价值、新品设计和 AI 生成企划。

## V9.3.0 生图工作流（研发可读）

生图不是脱离报告的自由绘图，而是由报告事实和新品方案驱动的六步链路：

1. `_load_report_for_generation` 读取本地报告或请求体，并由 `planIndex` 选择一个新品方案。
2. `build_generation_slots` 将方案拆成有顺序的图片任务：主图最多 5 位，详情图最多 15 位；界面默认主图 5 位和详情前 6 位。
3. `resolve_reference_images` 确定产品基准：用户上传最多 4 张优先，否则使用采集到的第一张商品主图。
4. `build_image_prompt` 生成每个槽位的基础提示词，`merge_image_prompt_with_user_edit` 只融合安全且与本图相关的编辑；预览和正式生成必须调用同一套逻辑。
5. `image_generate` 将最终提示词、尺寸、数量和参考图发送到 OpenAI-compatible 生图接口；每槽位 `n=1`，主图为 `1024x1024`，详情图为 `1024x1536`。
6. `_persist_image_job` 逐张保存结果到 `server/reports/assets/generated/<jobId>/`，并以 `consistencyGate.status=needs_review` 交给人工复核，不把它误报为视觉质检通过。

浏览器报告的调用链为 `initPlanActions` → `refreshPromptPreview` → `POST /api/generate-images` → `pollJob`。异步任务返回 `jobId/statusUrl`，客户端轮询 `GET /api/image-job/<jobId>`；状态为 `queued`、`generating`、`complete` 或 `error`。

## 提示词分层与优先级

最终提示词按固定层级拼装：

1. `identityLock`：报告商品事实、卖点和整套图片共享的身份 ID。
2. 参考图模式：`uploaded_reference`、`collected_reference`、`fission_base` 或 `fission_followup`。
3. 全局用户方向：明确的材质、颜色、结构、件数、尺寸、规格、花型、款式和功能写入 `productOverrides`，作用于整套图；视觉要求按槽位相关性分配。
4. 新品方案：方案名称、产品动作、页面动作，以及只借鉴表达方法的爆款结构。
5. 当前槽位：`assetType`、`index`、`role`、`task` 和 `handoff`，一张图只承担一个主要证明任务。
6. 页面事实、视觉信号、构图/尺寸和平台约束。
7. `image_generation` 模板的 `{prompt}` 包裹，再经 `promptMerge` 记录单图编辑是已应用、内置还是未关联。

用户明确指定的商品字段可以覆盖对应报告默认值；未指定字段继续沿用报告基准。品牌、Logo、价格、销量、认证、专利、交易承诺、二维码、水印及其他平台禁区始终拦截。不要展示模型隐藏推理过程，也不要让单图编辑静默替换整套产品身份。

### 参考图拍摄与产品展示状态一致开关

请求字段 `matchReferenceShooting` 默认 `false`，控制拍摄语言和产品展示状态，不改变产品身份。勾选为 `true` 时，先分析第一张参考图的机位/视角、景别、主体占比、透视、构图/裁切、背景层级、光线、道具与留白，再具体识别商品的平铺/悬挂/折叠/展开/堆叠/铺设/穿着/手持/使用中状态、朝向、折叠程度、垂落褶皱、摆放落点、支撑/接触点、遮挡、部件关系，以及人物抓握/按压/提拉/铺开/穿戴的动作阶段并迁移到当前商品；不得复制参考图的品牌、文字、无关商品或未证实卖点。未勾选时，参考图只核对商品身份，拍摄与展示状态由当前槽位重新设计。

优先级固定为：平台合规与安全 ＞ 用户明确商品设定和 `identityLock` ＞ 方案产品目标/允许的明确变化 ＞ 当前槽位业务目标与证据任务 ＞（勾选时）参考图拍摄语言 ＞ 默认构图风格。首张 `main:1` 以第一张参考图作商品外观母版；只允许产品目标或用户最终设定列出的字段改变，其他字段冻结。生成结果的 `referenceShootingPolicy` 为 `match_reference` 或 `identity_only`，预览和正式生成必须相同。

## 类目分支

- 服饰：尺码、版型、面料、做工、色差、上身效果。
- 食品：规格、口味、配料、保质期、复购、包装。
- 美妆：功效宣称、肤质、成分、使用反馈、敏感风险。
- 数码：配置、兼容性、性能、售后、使用问题。
- 家纺：结构规格、材质触感、颜色花型、工艺、洗后表现、场景适配。
- 其他：从已采标题、参数、SKU 和评论自动形成维度。

## 证据规则

- 主图、详情图、SKU 图和评论图严格分源，并绑定对应 imageEvidenceId。
- 评论只验证购后体验，问答只表示购买前顾虑。
- 单商品特征不等于竞争力；没有竞品数据时只给出有证据边界的商品价值判断。
- “存在”不等于“必须继承”。设计结论分为已验证资产、候选方向和 AI 探索变量。
- 缺少可靠数据时显示“未采集 / 当前不可分析”，不得用常识补齐。

## 报告结构

1. 商品总览与证据边界。
2. 动态商品画像。
3. 标题与营销表达拆解。
4. 主图逐张深度分析。
5. 详情页分段分析。
6. SKU 与参数矩阵。
7. 评论、问答和买家实拍。
8. 商品价值判断（吸收到老板速览和新品方向）。
9. 新品方案与设计资产分级。
10. AI 视觉生成企划。
11. 样品和页面落地验证。

## AI 视觉输出

每套新品方案至少要能映射为 `name/sourceType/productAction/pageAction`，并为主图和详情图提供可追溯的图片任务：`assetType`、`index`、`role`、`contentKey`、`task`、`nextAction`、`handoff` 和 `evidenceIds`。运行时由 `identityLock`、`referenceSource`、`productOverrides`、`promptMerge` 和 `consistencyGate` 补充执行元数据；这些字段应与报告中的事实和方案一致，不得凭空增加商品规格或卖点。

视觉方案应分别说明 Product、Style、Scene、Photography、Material Rendering、Composition 和 Negative Rules，但只保留有证据或明确标记为探索变量的内容。`Reference DNA`、`Design Delta`、`Must Keep`、`Must Change` 等旧版概念如需保留，须映射到当前 `identityLock.mustKeep/mustNotChange` 和方案动作，不能与当前字段并列制造两套标准。

## 本地接口契约

生成请求使用 `source` 或 `reportData`、`planIndex`、`assetTypes`、`selectedSlots`、`referenceImages`、`matchReferenceShooting`、`userDirection`、`promptOverrides`、`fissionPattern` 和 `completeSet`。先调用 `/api/image-prompt-preview` 检查槽位与最终提示词，再调用 `/api/generate-images`；不要在插件中绕过预览直接拼接提示词。参考图最多 4 张，上传后自动关闭裂变基准分支；没有任何可用商品主图或上传图时应明确报错。

生图配置字段要和页面含义保持一致：`image_model` 是独立必填模型，`image_models_path`（默认 `/models`）用于模型列表探测，`image_path`（默认 `/images/generations`）用于实际 POST；`image_api_base`/`image_api_key` 未填写时逐字段继承分析渠道。每个槽位请求 `model`、`prompt`、`size`、`n=1`，参考图兼容字段按 `image`、`reference_images`、`images` 依次尝试；结果可为 URL 或 Base64，必须落盘并写入 job manifest。

保持用户选择的槽位并发执行。TLS EOF 或连接重置只重试当前 payload 并指数退避，不能因传输错误轮换字段产生重复生图。单个独立槽位失败不得终止其余槽位：成功结果继续落盘，失败项写入 `failedSlots` 并设置 `partialFailure=true`，前端只重试失败槽位；全部失败或裂变基准图失败才将整批标记为 `error`。

采集 JSON 经过 `scripts/normalize_capture.mjs` 后，必须保留 `meta.imageClassificationVersion`、`images.provenance/classification`、`collection.reviewCollectionComplete`、`product.parameterCollection`、`pageText` 和 `monitoring`。评论未确认完整时使用 `/api/analyze-current` 的部分分析入口；只有 `reviewCollectionComplete=true` 才使用 `/api/analyze`。

## 页面设计

使用白色背景和高对比深色文字，青绿到青蓝渐变只承担品牌、进度和重点强调。商品图保持原比例；大段内容用图文并排、卡片分层和表格呈现，桌面与移动端均需可读。
