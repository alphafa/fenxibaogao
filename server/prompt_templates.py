"""可复用的提示词模板注册表。

后端只负责准备 evidence/context，模板负责描述任务；接入其它项目时可直接
替换模板或覆盖变量，不需要在业务代码里拼接提示词。
"""
from dataclasses import dataclass
import json
from pathlib import Path

PRODUCT_VARIABLES = {
    "product": "商品基础信息：标题、商品ID、类目、品牌、价格、销量等页面字段",
    "attributes": "商品参数/规格：仅包含页面实际采集到的名称和值",
    "images": "图片证据：主图、详情图、SKU图、评论原图及其 evidenceId",
    "reviews": "消费者评论：原文、评分、SKU、日期和评论 evidenceId",
    "questions": "问大家/购买问答：问题、回答及 QA evidenceId",
    "programStats": "程序统计：评论数量、图片数量、参数数量等可计算指标",
    "evidence": "统一证据账本；模型只能引用其中的 evidenceId",
    "roleOutputs": "七角色中间结论：商品策略、电商转化、消费者洞察、产品/供应链、视觉设计、老板决策与总编审核；只能交叉校验和编排，不得当作无证据事实",
    "renderingPolicy": "最终可见性规则：只展示真实非空内容；证据以来源类型和内容摘要呈现，evidenceId仅用于追溯",
    "prompt": "系统根据真实商品事实、具体开品方案、套图槽位和平台约束生成的完整生图提示词",
    "matchReferenceShooting": "是否锁定参考图的拍摄语言与产品展示状态（具体动作、姿态、朝向、展开/折叠、摆放和物体关系），仅影响视觉表达，不改变未经用户确认的商品事实",
}

@dataclass(frozen=True)
class PromptTemplate:
    name: str
    body: str
    variables: tuple = ()

    def render(self, **values):
        missing = [v for v in self.variables if v not in values]
        if missing:
            raise ValueError(f"模板 {self.name} 缺少变量: {', '.join(missing)}")
        return self.body.format(**values)

TEMPLATES = {
    "system": PromptTemplate("system", "{system}\n\n可用商品变量说明：\n{variable_schema}", ("system", "variable_schema")),
    "task": PromptTemplate("task", "{task}\n\n输入变量：{input_variables}", ("task", "input_variables")),
    "image_generation": PromptTemplate("image_generation", "{prompt}", ("prompt",)),
}

def register_template(name, body, variables=()):
    """覆盖或新增模板，供宿主项目在启动时注入行业提示词。"""
    TEMPLATES[name] = PromptTemplate(name, body, tuple(variables))

def render_template(name, **values):
    if name not in TEMPLATES:
        raise KeyError(f"未知提示词模板: {name}")
    return TEMPLATES[name].render(**values)

def variable_schema():
    return json.dumps(PRODUCT_VARIABLES, ensure_ascii=False, indent=2)

def build_system_prompt(system_text):
    override=Path(__file__).with_name('prompts.json')
    if override.exists():
        try:
            data=json.loads(override.read_text('utf-8'))
            if isinstance(data, dict) and isinstance(data.get('system'), dict) and data['system'].get('body'):
                return data['system']['body'].format(system=system_text, variable_schema=variable_schema())
        except Exception: pass
    return TEMPLATES["system"].render(system=system_text, variable_schema=variable_schema())

def build_task_prompt(task_text, variables=("evidence",)):
    names = "、".join(f"{name}（{PRODUCT_VARIABLES.get(name, '任务上下文变量')}）" for name in variables)
    return TEMPLATES["task"].render(task=task_text, input_variables=names)

def build_image_generation_prompt(prompt_text):
    """Apply the operator-configured image prompt wrapper to the real generation prompt."""
    body=TEMPLATES["image_generation"].body
    override=Path(__file__).with_name('prompts.json')
    if override.exists():
        try:
            data=json.loads(override.read_text('utf-8'))
            configured_body=(data.get('image_generation') or {}).get('body') if isinstance(data,dict) else None
            if configured_body: body=str(configured_body)
        except Exception: pass
    if '{prompt}' not in body:
        raise ValueError('生图提示词模板必须包含 {prompt}，否则无法与真实商品方案联动')
    return body.replace('{prompt}', str(prompt_text or ''))


def build_display_relationship_guidance(analysis, enabled=False):
    """One category-independent relationship contract for both prompt paths."""
    if not enabled:return ''
    analysis=analysis if isinstance(analysis,dict) else {}
    relations=analysis.get('displayRelations') or (analysis.get('imageObservation') or {}).get('displayRelations') or {}
    return ('【可见展示空间关系｜对应原图约束】'+json.dumps(relations,ensure_ascii=False)
            +'。使用实际对应参考图核对可见局部之间的连续连接、接触、覆盖顺序、遮挡、方向、相对位置和形变。'
            '记录缺失时直接观察实际参考图，不能只按状态名称生成。保留未被用户修改的这些关系，不要求照搬参考商品固有材质或制造结构。'
            '产品组成、缝制和配件属于固有身份；折回、垂落、抓握和摆放形成的连接/覆盖属于展示关系，两者不能混淆。'
            '连续形变不能重构成独立物体叠放，可见层数不等于商品件数；不能根据模板补造隐藏局部或操作过程。'
            '按参考可见关系迁移当前产品，仅允许用户明确授权及实现要求不可避免的最小调整。'
            ' English constraints: Preserve the visible connectivity, contact, overlap order, occlusion, orientation and relative placement from the corresponding reference. Distinguish intrinsic product construction from display-induced deformation. Do not replace a continuous folded surface with separate stacked objects or infer item count from visible layers. Inspect the actual reference when recorded observations are incomplete; never invent hidden geometry.')


def build_reference_shooting_guidance(
    enabled=False,
    asset_type='main',
    reference_mode='collected_reference',
    business_goal='',
    product_goal='',
    slot_index=None,
):
    """Return the explicit reference-shooting policy for an image prompt.

    ``matchReferenceShooting`` is deliberately a visual-policy switch rather
    than an identity switch.  When enabled, the provider is asked to inspect
    the collected slot image for shooting grammar and display state, while a
    separately uploaded image (when present) supplies only product identity.
    When disabled, the reference remains an identity/structure anchor and the
    slot's own e-commerce composition is authoritative.  Keeping this policy
    in the shared template makes preview and execution produce identical
    instructions and gives downstream providers a deterministic contract.
    """
    kind = '主图' if str(asset_type or '').lower() == 'main' else '详情图'
    is_first_main = str(asset_type or '').lower() == 'main' and str(slot_index or '') == '1'
    source_labels = {
        'uploaded_reference': '用户上传参考图',
        'uploaded_identity_collected_reference': '用户上传图（商品身份）+ 采集商品对应槽位图（展示状态）',
        'fission_base': '采集商品主图（裂变基准图）',
        'fission_followup': '上一张已生成基准图',
        'collected_reference': '采集到的商品主图',
    }
    source = source_labels.get(str(reference_mode or ''), '随请求提供的参考图')
    uploaded = str(reference_mode or '') in ('uploaded_reference', 'uploaded_identity_collected_reference')
    hybrid = str(reference_mode or '') == 'uploaded_identity_collected_reference'
    business = str(business_goal or '').strip() or (
        '让用户快速识别商品并理解本图承担的购买确认任务'
    )
    product = str(product_goal or '').strip() or (
        '保持用户最终确认的商品品类、结构、材质、颜色、件数和规格'
    )
    if hybrid:
        first_main_rule = (
            '第1张用户上传产品图是唯一商品身份母版，第2张采集商品对应槽位图是拍摄与展示状态母版；'
            '首张主图（main:1）也必须按这两个职责分别读取，不能把产品图的机位、构图或摆放状态带入结果。'
            '采集参考图中的商品颜色、花型、材质、纹理、品牌、结构和件数不是当前商品事实，全部不得覆盖第1张产品图。'
            '只有“产品目标”或用户最终设定明确列出的字段可以改变，其他字段冻结。'
        )
    elif uploaded and is_first_main:
        first_main_rule = (
            '首张主图（main:1）必须使用第一张参考图作为商品外观母版；第一张用户上传产品图是唯一商品身份母版，整套主图与详情图都必须继承它的轮廓、比例、件数、颜色/花型、材质纹理、结构和配件位置。'
            '采集商品的标题、参数、图片、品牌、颜色、材质和视觉分析不属于当前商品身份，不能改变上传产品图。'
            '只有“产品目标”或用户最终设定明确列出的字段可以改变，其他字段冻结。'
        )
    elif uploaded:
        first_main_rule = (
            '当前槽位继续继承同一产品身份；第一张用户上传产品图仍是唯一商品身份母版。'
            '采集商品的标题、参数、图片、品牌、颜色、材质和视觉分析不属于当前商品身份，不能改变上传产品图。'
            '只有用户最终设定明确列出的字段可以改变，其他字段冻结。'
        )
    elif is_first_main:
        first_main_rule = (
            '首张主图（main:1）优先使用第一张参考图作为商品外观母版；视觉上严格保持轮廓、比例、件数、颜色/花型、材质纹理、结构和配件位置。'
            '只有“产品目标”或用户最终设定明确列出的字段可以改变，其他字段冻结。'
        )
    else:
        first_main_rule = '当前槽位继续继承同一产品身份；只有“产品目标”或用户最终设定明确列出的字段可以改变，其他字段冻结。'
    reference_role_rule = (
        '【双参考图职责分离】第1张输入图是用户上传产品图，只允许提取商品身份、轮廓、比例、材质、颜色/花型、结构、件数和配件；'
        '第2张输入图是采集商品当前槽位图，提供表达主题、文字版式以及机位、视角、景别、透视、构图、背景、光线、具体动作、朝向、展开/折叠、摆放、支撑/接触点、遮挡和部件关系；其原文参数不能当作当前产品事实。'
        '结果必须使用第1张图的商品放入第2张图的展示状态；第2张图中的商品外观、颜色、花型、材质和结构不得覆盖第1张图。不得交换两张图的职责。'
        if hybrid else
        '【单一产品身份参考】第1张输入图是用户上传产品图，也是整套图片唯一的商品身份来源；只允许提取商品品类、轮廓、比例、材质、颜色/花型、结构、件数和配件。采集商品的文字、参数和图片只用于业务目标与证据任务，不得改变当前商品外观。'
        if uploaded else
        '【参考图职责】当前参考图用于确定商品身份与本策略指定的视觉表达；不得把未授权的其他商品、品牌或文字带入结果。'
    )
    reference_role_rule_en = (
        '【Two-reference role split】Input image 1 is the uploaded product image and is the only source for product identity, silhouette, proportions, material, color/pattern, construction, quantity and accessories. Input image 2 is the collected slot image and may provide only camera/view/display state. Place the product from image 1 into the display state of image 2; image 2 product appearance, color, pattern, material and construction must never override image 1. Never swap these roles.'
        if hybrid else
        'Input image 1 is the only product identity reference for the entire image set. Use it for the product category, silhouette, proportions, material, color/pattern, construction, quantity and accessories. Collected product text, parameters and images are business context only and must never change the uploaded product appearance.'
        if uploaded else
        'Use the current reference only for the product identity and the visual policy stated here; never import another product, brand or text.'
    )
    copy_policy = (
        '【参考图文案跟随规则】必须依据当前产品事实和对应图片分析任务生成简短中文文案并渲染到图中。文字识别缺失不代表参考图无字，必须查看实际参考图。参考图有文字时严格保持文字相对位置、大小占比、对齐、标题层级、换行、行距、留白和阅读顺序，仅替换为当前产品对应文案。不得照抄品牌、价格、促销、认证或虚构产品参数，不得默认留白取消文案。'
    )
    copy_policy_en = (
        'Render short Chinese copy derived from the current product and the corresponding slot analysis. Missing OCR is not evidence that the reference is text-free. Inspect the actual collected slot reference. Preserve its text positions, relative font sizes, alignment, title hierarchy, line breaks, line spacing and margins when text is present. Never copy brands or unsupported claims. Display state and text layout take precedence over default creative styling.'
    )
    if enabled:
        return f'''【参考图拍摄与产品展示状态一致｜已勾选｜matchReferenceShooting=true】
策略定义：锁定对应参考图的拍摄语言、产品展示状态、表达主题和文字版式；替换为当前产品及基于当前产品分析的文案，不照抄参考商品原文。拍摄与摆放母版：{source}；本策略适用于当前{kind}。
【防止商品串图｜最高优先级】任何采集参考图都不是当前商品外观参考。严禁复制采集图中的颜色、花型、材质、纹理、轮廓、结构、件数、配件、包装或品牌；当前商品只能来自第1张上传产品图和用户最终明确设定。若视觉状态与商品外观发生冲突，保留第1张产品图外观，放弃采集图外观。
{reference_role_rule}
优先级（高→低）：平台合规与安全 ＞ 当前产品身份与用户明确商品设定 ＞ 用户明确表达要求 ＞ 对应参考图的产品展示状态与文案排版 ＞ 产品方案与业务任务 ＞ 默认构图与风格。产品不能擅自改变；用户明确表达要求覆盖参考对应项，未涉及的参考约束保持有效。
业务目标（不可丢失）：{business}。
产品目标（不可丢失）：{product}。
拍摄语言必须尽量一致：机位与视角、景别与主体占比、镜头透视/焦段观感、构图与裁切、背景/场景层级、光线方向与软硬度、色温与阴影、道具、视觉重心和留白节奏。
产品展示状态必须具体复现：先识别商品是平铺、悬挂、折叠、展开、堆叠、卷起、铺设、穿着、手持、使用中还是局部掀开；再保持正反面与朝向、旋转/倾斜角度、展开或折叠程度、弯曲/垂落/褶皱状态、落点与画面坐标、接触面和支撑点、遮挡关系、部件相对位置、与道具/家具/人体的距离和前后层级。
动作状态必须具体复现：若有人手或模特，保持谁在用什么部位、抓握/按压/提拉/铺开/穿戴等动作、手指或身体接触点、发力方向、动作阶段和姿态；不得把“正在动作”改成静态陈列，也不得把静态陈列擅自改成动作场景。先逐项分析实际参考图，再迁移到当前商品。
商品保真：{first_main_rule}
适配规则：在对应参考图既有展示状态与文字版式中表达当前产品的可核验信息；不引入其他商品、品牌Logo或未证实卖点。先锁定产品摆放、动作、朝向、主体占比和部件关系，再精简文案适配原有文字区域，不能为文案重新构图或移动商品。
{reference_role_rule_en}
{copy_policy}
{copy_policy_en}
【English constraints】Input image 1 supplies current product identity only. Input image 2 supplies the corresponding expression theme, shooting grammar, exact display/action state and text layout. Preserve its camera angle, shot scale, perspective, framing, background, lighting, shadows, props, negative space, orientation, fold/unfold amount, drape, placement, support/contact points, occlusion, part relationships, human touch points and action phase. Preserve the current product appearance from image 1. Render new Chinese copy supported by current product facts in the corresponding text positions, sizes, alignment, hierarchy and line spacing of image 2. Shorten copy to fit; never move or resize the product or change its display state to make room for text. Never copy another product identity, logo, original wording, watermark or unsupported claim.
'''
    return f'''【参考图拍摄与产品展示状态一致｜未勾选｜matchReferenceShooting=false】
策略定义：不继承参考图的拍摄语言或产品展示状态。参考来源：{source}；参考图只用于核对当前商品身份、结构、材质、颜色和比例。
优先级（高→低）：平台合规与安全 ＞ 用户明确商品设定与统一 identityLock ＞ 产品目标/方案允许的明确变化 ＞ 当前槽位业务目标与证据任务 ＞ 适合本图的电商拍摄方案。不要复制其机位、景别、镜头透视、构图、背景、光线、道具、姿态、具体动作、朝向、展开/折叠、摆放位置、支撑/接触点、遮挡或部件关系；不得把参考图的视觉语言或展示状态当成默认要求。
业务目标（不可丢失）：{business}。
产品目标（不可丢失）：{product}。
商品保真：{first_main_rule}
{reference_role_rule_en}
{copy_policy}
{copy_policy_en}
【English constraints】Use the reference only as a product-identity anchor. Do not copy its camera angle, shot scale, perspective, framing, background, lighting, props, display/action state, orientation, folding, placement, support/contact points, occlusion or part relationships. Design a clear ecommerce shot for the current business goal while preserving the current product identity and approved product changes.
'''
