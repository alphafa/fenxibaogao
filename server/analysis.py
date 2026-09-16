import json, re
from collections import Counter, defaultdict
from ai_client import chat_json, configured
from prompt_templates import build_system_prompt, build_task_prompt

ENGINE_VERSION='9.3.0'

ROLE_CONTRACT_VERSION='1.1'
ROLE_CONTRACT={
  'productStrategy': {'responsibility':'判断商品卖什么、为什么值得参考、下一款继承什么','outputs':['商品定位','核心产品资产','核心卖点结构','目标使用场景','值得继承的产品逻辑','需要调整的方向','商品与同类差异点','下一款策略假设']},
  'conversion': {'responsibility':'判断用户为什么点击、继续看并愿意购买','outputs':['标题表达','主图任务分工','主图核心信息','详情页信息链','卖点承接','信任证明','页面信息缺口','标题/主图/详情优化动作']},
  'consumerInsight': {'responsibility':'从评论和买家秀提炼真实使用体验并转成产品需求','outputs':['稳定正向体验','体验差异','高频顾虑','购前关注','售后问题','消费者语言','真实使用场景','买家秀验证','下一款必须解决的用户需求']},
  'productSupply': {'responsibility':'判断产品怎么改、哪些能落地、哪些必须验证','outputs':['材质','工艺','支数/克重','尺寸','套件','SKU结构','功能参数','规格适配','产品调整项','生产风险','打样验证项','首批验证项','不可直接下结论的产品假设']},
  'visualDesign': {'responsibility':'拆解视觉资产并转成下一款设计和生图方向','outputs':['风格','颜色','花型','元素','材质视觉','构图','拍摄方式','场景','光线','画面氛围','视觉锤','值得继承的视觉资产','下一款视觉变化方向','AI生图参考要求']},
  'executiveDecision': {'responsibility':'把专业判断压缩成老板可直接决策的结论','outputs':['为什么值得做','为什么能卖','最强资产','最大机会','最需要关注的问题','下一款第一优先级','建议保留什么','建议升级什么','探索方向','执行优先顺序']},
  'editorReview': {'responsibility':'对外发布前统一审核、压缩、纠错和去重','outputs':['事实一致性','证据支持','经营数据边界','产品对象与卖点匹配','图片分类','章节一致性','重复删除','措辞统一','字数压缩','最终结构']}
}

SYS='''你是“三笙电商商品开品分析引擎”，面向两类读者：老板/决策者与专业商品开发用户。你的工作不是展示AI分析过程，而是把真实商品证据压缩成可决策、可复用、可开品的专业报告。

角色协作规则（内容生产链）：
1. 商品策略、电商转化、消费者洞察、产品/供应链、视觉设计分别只判断自己的职责范围；可并行，但不得互相越权。
2. 商业决策/老板角色只综合前序角色的证据，不重新发明事实；输出为什么值得做、为什么能卖、第一优先级和执行顺序。
3. 总编审核角色是发布前质量门，不是新的观点来源；必须删除重复、纠正错配、标记假设并保留证据边界。
4. 每个角色的结论、风险、动作和假设都必须能回溯到 ACTUAL_EVIDENCE；没有证据时标记 hypothesis 或 unknown。

最终阅读逻辑：
1. 老板先看：为什么能卖、哪些资产值得继承、下一款优先做什么。
2. 专业用户再看：标题怎么表达、主图在卖什么、详情证明什么、SKU怎么选、消费者实际感受到什么。
3. 图片是主信息载体。用户必须能从图片旁的短标签直接看懂商品信息，不依赖长段解释。

硬规则：
1. 只使用 ACTUAL_EVIDENCE 和程序统计；缺失即未采集，不用常识补齐。
2. 禁止把内部推理标签输出给用户：不得出现[数据事实][分析判断][设计建议][证据不足]。
3. 禁止审核式好坏评分；优先使用“核心判断、值得继承、建议强化、专业动作、下一款方向”。
4. 同一结论默认只出现一次。不要在专业意见、卡片说明、建议中重复同一句信息。
5. 图片信息提炼优先于图片解释：从图片可核验文字/商品/场景中提炼 visualSignals（2-4个短标签），再给1条 nextAction。
6. 主图默认每张只输出：imageRole + visualSignals + nextAction。businessMeaning/evidenceDetail仅供内部或折叠层使用。
7. 详情页按4-6个信息任务组输出，每组：代表图 + visualSignals + nextAction；不得逐张写长文。
8. SKU图片数量不等于SKU数量。SKU重点回答选择维度与顺序；先解决适配，再解决审美。
9. 评论先聚合成稳定体验/体验差异/购前关注，再进入新品方案；买家秀只是证据。
10. 新品方案分来源等级：证据驱动优化 / 反馈驱动升级 / 探索性方向。探索性方向必须明确标记，不得伪装成已有事实。
11. 只要有商品基础证据且主图或详情任一存在，至少输出1套新品方案；证据较完整可输出2-3套。
12. 图片原图完整展示优先于铺满容器；报告渲染必须使用 contain，不以裁切换取整齐。
13. 默认可见层不使用小卡片堆叠思维：每屏只突出1个主结论、1-2张大图或一组大规格图片。
14. 图片上的文字/卖点是核心证据，visualSignals必须优先提取具体词，如规格、材质、权益、功能，而不是抽象评价。
15. 不输出私有思维过程。严格输出 JSON，不要 Markdown 或 HTML。
16. 没有真实内容的可选字段直接省略，不得输出空字符串、空数组、空对象或“暂无/未采集/待补充”等占位文案。'''

STYLE_RULES='''V9.3.0 输出压缩与可见性规则：
- reportSummary.verdict / professionalOpinion：<=55字。
- 老板速览 headline：<=28字；note：<=28字。
- 标题 currentExpression/reinforce：短词组，不写完整分析段落。
- 单张主图 imageRole<=10字；visualSignals 2-4项，每项<=12字；nextAction<=22字。
- 详情组 type<=8字；visualSignals 2-4项，每项<=12字；nextAction<=22字。
- SKU professionalOpinion<=45字；recommendedAction<=30字。
- 评论 insight<=35字；默认不再附第二段 implication。
- 新品方案 whyThisPlan<=45字；productAction<=35字；pageAction<=35字；validation<=25字。
- 禁止通过Renderer用省略号硬截断来制造短文；模型必须直接生成短文本。
- 详细构图/OCR/颜色/材质推理放 evidenceDetail，默认报告不展示。
- 同一事实不在同一章节重复三次。
- 没有真实内容的字段直接省略；禁止为了补结构输出“暂无、未采集、待补充、无”。
- 空字符串、空数组和空对象不得进入用户可见结论。数值0和明确的采集状态属于有效内容，可保留。
- evidenceIds 只用于追溯；用户可见层应由渲染器显示“来源类型+真实内容摘要”，不得让用户只看到字符编号。
'''

FINAL_REPORT_PROMPT='''任务G｜V9.3.0 七角色总编报告编排器。你只能压缩和映射前序分析，不重新发明事实。

输入中的 roleOutputs 来自七个职责角色。编排要求：商品策略进入“为什么能卖/值得继承”；电商转化进入标题、主图、详情；消费者洞察进入真实体验；产品/供应链进入SKU、参数与验证；视觉设计进入视觉资产与下一款视觉变化；老板决策压缩为首屏；总编审核负责删除角色间重复和冲突。角色输出不是额外证据，所有结论仍必须保留 evidenceIds。

最终顺序：老板速览 → 下一款方向 → 标题 → 主图 → 详情 → SKU → 消费者反馈。商品价值不要单独重复成一整章，吸收到老板速览。

严格输出 JSON：
{
  "reportSummary":{"title":"","verdict":"<=45字","coverImageId":"IMG_MAIN_0001"},
  "ownerOverview":{"chapterTitle":"老板速览","cards":[
    {"label":"为什么能卖","headline":"<=18字","note":"<=22字","evidenceIds":[]},
    {"label":"值得继承","headline":"<=18字","note":"<=22字","evidenceIds":[]},
    {"label":"下一款优先","headline":"<=18字","note":"<=22字","evidenceIds":[]}
  ]},
  "titleAnalysis":{"professionalOpinion":"<=45字","originalTitle":"","currentExpression":[{"value":"<=10字","evidenceIds":[]}],"reinforce":[{"topic":"<=10字","evidenceIds":[]}],"recommendedActions":[{"action":"<=22字","evidenceIds":[]}],"recommendedTitles":[]},
  "visualCommerce":{"professionalOpinion":"<=45字","items":[{"imageEvidenceId":"IMG_MAIN_0001","imageRole":"<=8字","visualSignals":["<=10字"],"businessMeaning":"<=22字","nextAction":"<=18字","contentKey":"product_overview|usage_scene|material_touch|structure_function|spec_choice","evidenceIds":[]}],"evidenceDetail":[]},
  "detailCommerce":{"professionalOpinion":"<=45字","contentGroups":[{"type":"场景证明|材质证明|结构工艺|功能表现|规格适配|使用维护","representativeImageId":"IMG_DETAIL_0001","visualSignals":["<=10字"],"businessMeaning":"<=22字","nextAction":"<=18字","contentKey":"scene_problem|material_proof|structure_proof|function_proof|spec_adaptation|care_durability","imageEvidenceIds":[],"evidenceIds":[]}],"pageSequence":[]},
  "skuAnalysis":{"professionalOpinion":"<=35字","selectionDimensions":[{"name":"<=8字","values":[],"evidenceIds":[]}],"recommendedOrder":[],"representativeImageIds":[],"recommendedAction":"<=24字","structuredStatus":"confirmed|missing","structuredCount":null,"imageCount":0},
  "customerExperience":{"professionalOpinion":"<=45字","consumerInsights":{"experienceSignals":[{"type":"稳定体验|体验差异|购前关注|对新品的启示","insight":"<=28字","evidenceIds":[]}],"productImplications":[]},"buyerEvidence":{}},
  "expressionContinuity":{"coreClaims":[{"claim":"<=24字","mainStatus":"expressed|partial|missing","detailStatus":"proven|partial|missing","reviewStatus":"validated|partial|missing","nextAction":"<=24字","evidenceIds":[]}]},
  "newProductPlans":{"professionalOpinion":"<=45字","plans":[{"sourceType":"证据驱动优化|反馈驱动升级|探索性方向","name":"<=18字","productAction":"<=45字","pageAction":"<=36字"}]},
  "productExperience":{"parameterFacts":[],"gates":[]},
  "validationLoop":{"rows":[]}
}

硬规则：
- ownerOverview.cards 必须正好3项，且分别回答“为什么能卖 / 值得继承 / 下一款优先”。
- visualCommerce.items 中每张图必须优先给 visualSignals；不要写长 message。
- detailCommerce.contentGroups 证据允许时输出4-6组，顺序必须是场景 → 材质 → 结构/工艺 → 功能 → 规格 → 使用维护。
- 主图与详情必须形成连续页面：主图先让用户看懂商品和使用入口，详情逐项证明；同一卖点只能在一个信息任务中承担主责。
- 主图和详情只表达商品本身的结构、材质、成分、尺寸、件数、功能、工艺、触感、使用场景和洗护等内容。品牌、商标、专利、授权、认证、奖项、包邮、物流、价格、销量、促销、客服、售后、二维码、防伪和店铺信息不得进入 visualCommerce 或 detailCommerce。
- newProductPlans.plans 必须正好3项，依次为证据驱动优化、反馈驱动升级、探索性方向；探索项必须明确为待验证方向，不能当作已验证结论。
- productExperience.parameterFacts>=2、productExperience.gates>=2、validationLoop.rows>=3，继续用于工程证据校验，但默认报告不展示。
- 禁止用户可见字段出现[数据事实][分析判断][设计建议][证据不足]。
- 只返回有真实内容的可选字段；不得用空字符串、空数组、空对象或“暂无/未采集/待补充”填充版面。
- 七角色输出必须能归入“核心判断—关键发现—执行动作—风险/验证”；证据编号仅作机器追溯，不作为面向用户的说明文字。
'''

FINAL_REPORT_REPAIR_PROMPT='''任务G-R｜修复 V9.3.0 最终报告 JSON。只修复结构缺失和证据引用，不扩写正文。
必须保留短文本与图片信息优先规则。
强制最小结构：reportSummary.title/verdict非空；ownerOverview.cards>=3；productExperience.parameterFacts>=2；productExperience.gates>=2；newProductPlans.plans=3；validationLoop.rows>=3。
如果 customerExperience 有评论证据，优先保留 experienceSignals；无评论时允许为空。
所有 evidenceIds 只能来自 ACTUAL_EVIDENCE。不要输出 Markdown、解释或包装层。
可选字段没有真实内容时直接省略，不得填入“暂无、未采集、待补充”或空容器。
''' 

TOPICS={
 '颜值/配色':['好看','漂亮','颜色','色彩','高级','颜值','款式','花色','图案','搭配'],
 '面料/触感':['柔软','舒服','舒适','亲肤','手感','面料','纯棉','全棉','透气','粗糙','刮'],
 '厚薄/季节':['薄','厚','厚实','轻薄','冬天','夏天','季节'],
 '色差':['色差','偏黄','偏白','偏暗','颜色不一样','实物和图片'],
 '做工/破损':['做工','线头','走线','缝','破','开线','油污','质量'],
 '尺寸/适配':['尺寸','大小','合适','床笠','床单','被套','罩不住','紧张'],
 '起球/掉毛':['起球','掉毛','粘毛','浮毛'],
 '缩水/掉色':['缩水','掉色','褪色','变形'],
 '气味':['味道','气味','异味'],
 '物流/服务':['物流','发货','客服','包装','快递','售后'],
 '价格/价值感':['划算','性价比','价格','便宜','值','贵']
 ,'尺码/上身':['尺码','码数','偏大','偏小','合身','显瘦','上身','版型']
 ,'口味/复购':['口味','味道','好吃','难吃','甜','咸','回购','复购']
 ,'成分/肤感':['成分','肤感','吸收','刺激','过敏','敏感','闷痘']
 ,'配置/性能':['配置','兼容','性能','速度','续航','发热','卡顿','连接']
}

def _txt(v): return '' if v is None else str(v)
def _arr(v): return v if isinstance(v,list) else []
def _uniq(xs):
    out=[]; seen=set()
    for x in xs or []:
        k=_txt(x).strip()
        if k and k not in seen: seen.add(k); out.append(x)
    return out

def _question_like(c):
    c=_txt(c).strip()
    return bool(re.search(r'问大家|更多回答|查看全部问答|大家问|^问[：:\s]|请问|会不会|有没有|多少价|(?:起球|缩水|掉色|尺寸).*[？?]',c))

BAD_TITLES = ('用户评价', '累计评价', '商品评价', '问大家', '参数信息', '规格参数', '图文详情', '商品详情')
BAD_PARAM_CODE = re.compile(r'(?:^\d+$|window\.|console\.|function\b|frontend_data|performance\.|[{}\[\]"\'=;<>])', re.I)
NEGATIVE_REVIEW_KEYS = ('不够', '一般', '不会复购', '偏小', '偏大', '缩水', '掉色', '起球', '掉毛', '异味', '破损', '开线', '色差', '不合身', '难吃', '变质', '漏液', '过敏', '刺激', '不兼容', '卡顿', '发热', '续航差')
IMAGE_GROUPS = ('main', 'detail', 'sku', 'buyerShow')
BAD_IMAGE_URL = re.compile(r'(?:avatar|sns_logo|credit|logo|icon|sprite|shopmanager|/tps/|/tfs/TB1[^/]+-\d{1,4}-\d{1,4}\.png|tps-\d{1,3}-\d{1,3}|defaultRate)', re.I)
BAD_PAGE_IMAGE_URL = re.compile(r'(?:[-_]rate(?:\.|_|-)|rate_livephoto|tbbala|/tps/|/tfs/TB1[^/]+-\d{1,4}-\d{1,4}\.png)', re.I)

def _clean_product_title(v):
    value=re.sub(r'\s+',' ',_txt(v)).strip()
    suffix=r'(?:[-_｜|·\s]*)?(?:(?:www\.)?(?:tmall|taobao)\.com)?(?:天猫(?:网)?|淘宝网?)'
    previous=None
    while value and value!=previous:
        previous=value
        value=re.sub(suffix+r'\s*$','',value,flags=re.I).rstrip('-_｜|· ')
    return value

def _valid_title(v):
    value=_clean_product_title(v)
    return value if 4<=len(value)<=260 and not any(x in value for x in BAD_TITLES) and not re.search(r'登录|验证码|访问受限',value) else ''

def _valid_param(name,value):
    name=re.sub(r'\s+',' ',_txt(name)).strip(); value=re.sub(r'\s+',' ',_txt(value)).strip()
    if not name or not value or len(name)>60 or len(value)>220:return False
    if BAD_PARAM_CODE.search(name) or re.search(r'(?:console\.log|window\.|performance\.now|frontend_data)',value,re.I):return False
    return bool(re.search(r'[\u4e00-\u9fffA-Za-z]',name))

def _image_url(value):
    if isinstance(value,dict):
        value=next((_txt(value.get(k)) for k in ('url','picUrl','imageUrl','src','bigUrl','thumbnail') if value.get(k)), '')
    value=_txt(value).strip().replace('&amp;','&')
    if value.startswith('//'):value='https:'+value
    return value if value.startswith(('http://','https://','data:image/')) and not BAD_IMAGE_URL.search(value) else ''

def _clean_image_urls(values):
    return _uniq([url for url in (_image_url(x) for x in values or []) if url])

def _normalize_image_groups(raw, reviews):
    source=raw.get('images',{}) if isinstance(raw.get('images'),dict) else {}
    meta=raw.get('meta',{}) if isinstance(raw.get('meta'),dict) else {}
    strict=(meta.get('imageClassificationVersion')=='strict-v1' and isinstance(source.get('provenance'),list))
    review_links={};legacy_review_links={}
    for review_index,review in enumerate(reviews,1):
        cleaned=_clean_image_urls(review.get('images',[]));review['images']=cleaned
        for url in cleaned:
            review_links.setdefault(url,[]).append(review_index)
            if review.get('source')=='dom_visible':legacy_review_links.setdefault(url,[]).append(review_index)
    incoming=[]
    for record in source.get('provenance',[]) or []:
        if not isinstance(record,dict):continue
        url=_image_url(record.get('url'));group=record.get('group');origin=_txt(record.get('source')).strip()
        if url and group in IMAGE_GROUPS and origin:incoming.append({'url':url,'group':group,'source':origin})
    groups={key:[] for key in IMAGE_GROUPS};provenance=[];assigned=set()
    buyer_candidates=[]
    if strict:
        buyer_candidates=[x['url'] for x in incoming if x['group']=='buyerShow' and x['source']=='review_record' and x['url'] in review_links]
    else:
        buyer_candidates=list(legacy_review_links)
    for url in _uniq(buyer_candidates):
        if url in assigned:continue
        assigned.add(url);groups['buyerShow'].append(url)
        link_index=review_links if strict else legacy_review_links
        for review_index in link_index.get(url,[]):provenance.append({'url':url,'group':'buyerShow','source':'review_record','reviewIndex':review_index,'reviewEvidenceId':f'REV_{review_index:06d}'})
    if strict:
        allowed_sources={'sku':{'dom_sku_selector','structured_sku_selector'},'main':{'meta_og_image','dom_main_gallery','structured_main_gallery'},'detail':{'dom_product_description','structured_product_description'}}
        for group in ('sku','main','detail'):
            for record in incoming:
                if record['group']!=group or record['source'] not in allowed_sources[group] or record['url'] in assigned:continue
                if group in ('main','detail','sku') and BAD_PAGE_IMAGE_URL.search(record['url']):continue
                assigned.add(record['url']);groups[group].append(record['url']);provenance.append(record)
    else:
        # V9.2.3 legacy/standalone compatibility:
        # Older and standalone collectors already separate main/detail/sku arrays but do not emit strict-v1 provenance.
        # Do NOT discard these verified-by-collector groups merely because provenance metadata is absent.
        legacy_sources={'main':'legacy_group_main','detail':'legacy_group_detail','sku':'legacy_group_sku'}
        for group in ('main','detail','sku'):
            for raw_url in source.get(group,[]) or []:
                url=_image_url(raw_url)
                if not url or url in assigned or BAD_PAGE_IMAGE_URL.search(url):continue
                assigned.add(url);groups[group].append(url)
                provenance.append({'url':url,'group':group,'source':legacy_sources[group]})
    source_values=[]
    for key in IMAGE_GROUPS:
        if isinstance(source.get(key),list):source_values.extend(source.get(key))
    original_count=len(set(_clean_image_urls(source_values)))
    all_images=_uniq(sum((groups[k] for k in IMAGE_GROUPS),[]))
    policy='strict-v1' if strict else 'legacy-review-only'
    previous_excluded=(source.get('classification',{}) or {}).get('unverifiedExcludedCount',0)
    try:previous_excluded=max(0,int(previous_excluded))
    except:previous_excluded=0
    return {**groups,'all':all_images,'provenance':provenance,'classification':{'version':policy,'classifiedCount':len(all_images),'unverifiedExcludedCount':max(previous_excluded,original_count-len(all_images),0),'groupsAreDisjoint':True}}

def _normalize_questions(values):
    out=[];seen=set()
    def add(q,a='',source='unknown'):
        q=re.sub(r'^(?:问大家|大家问)\s*[·\d]*\s*','',_txt(q)).strip(' ，,。')
        q=re.sub(r'\s*(?:更多回答|查看全部问答)\s*$','',q).strip(' ，,。')
        if len(q)<3:return
        key=re.sub(r'[\s，,。！？?]','',q)
        if key in seen:return
        seen.add(key);out.append({'question':q[:1800],'answer':_txt(a).strip()[:1800],'source':source})
    for x in values or []:
        if isinstance(x,str):x={'question':x}
        if not isinstance(x,dict):continue
        q=_txt(x.get('question') or x.get('title') or x.get('ask') or x.get('content')).strip()
        a=_txt(x.get('answer') or x.get('reply')).strip(); source=x.get('source') or 'questions_input'
        chunks=re.findall(r'(?:^|\s)问[：:\s]+(.+?)(?=\s*更多回答|\s*查看全部问答|\s+问[：:\s]|$)',q)
        if chunks:
            for chunk in chunks:add(chunk,'',source)
        else:add(q,a,source)
    return out

def _normalize_question(x, source='unknown'):
    if isinstance(x,str): return {'question':x.strip(),'answer':'','source':source}
    if not isinstance(x,dict): return None
    q=_txt(x.get('question') or x.get('title') or x.get('ask') or x.get('content')).strip()
    a=_txt(x.get('answer') or x.get('reply')).strip()
    if len(q)<3:return None
    return {'question':q[:1800],'answer':a[:1800],'source':x.get('source') or source}

def normalize(raw):
    r=dict(raw or {})
    reviews=[]; questions=_normalize_questions(r.get('questions',[]) or []); seen=set(); qseen={re.sub(r'\s+','',x['question'])[:260] for x in questions}
    for x in r.get('reviews',[]) or []:
        if isinstance(x,str): x={'content':x}
        c=_txt(x.get('content') or x.get('text')).strip(); append=_txt(x.get('appendContent') or x.get('append')).strip()
        if re.fullmatch(r'\d{4}年\d{1,2}月\d{1,2}日已购[：:].+',c):continue
        if re.search(r'该用户(?:未填写评价内容|没有填写评价|觉得商品非常好)',c):
            if append:c=append;append=''
            else:continue
        if len(c)<3 or c in ('此用户没有填写评价','系统默认好评'): continue
        if _question_like(c):
            qq=_normalize_question({'question':c,'source':x.get('source') or 'misclassified_review'},'misclassified_review')
            if qq:
                k=re.sub(r'\s+','',qq['question'])[:260]
                if k not in qseen:qseen.add(k);questions.append(qq)
            continue
        key=re.sub(r'\s+','',c)[:260]
        if key in seen: continue
        seen.add(key)
        reviews.append({'content':c[:2200],'appendContent':append[:1200],
                        'rating':x.get('rating') or x.get('score') or x.get('star'),'sku':_txt(x.get('sku') or x.get('skuInfo')).strip()[:260],
                        'date':_txt(x.get('date') or x.get('time')).strip()[:100],'images':_clean_image_urls(x.get('images',[]) or [])[:24],'likes':x.get('likes'),'source':x.get('source') or ''})
    r['reviews']=reviews; r['questions']=questions[:5000]
    attrs=[];attr_seen=set()
    for x in r.get('attributes',[]) or []:
        if not isinstance(x,dict):continue
        name=x.get('name');value=x.get('value')
        if not _valid_param(name,value):continue
        key=(re.sub(r'\s+','',_txt(name)),re.sub(r'\s+','',_txt(value)))
        if key in attr_seen:continue
        attr_seen.add(key);attrs.append({'name':_txt(name).strip(),'value':_txt(value).strip()})
    r['attributes']=attrs[:500]
    product=dict(r.get('product') or {})
    product['title']=_valid_title(product.get('title'))
    r['product']=product
    r['images']=_normalize_image_groups(r,reviews)
    return r

def _attribute_rows(raw):
    return [x for x in raw.get('attributes',[]) if isinstance(x,dict) and _valid_param(x.get('name'),x.get('value'))]

def _find_attr(attrs, words):
    for i,x in enumerate(attrs,1):
        name=_txt(x.get('name'))
        if any(word in name for word in words):return x,f'ATTR_{i:04d}'
    return None,''

CATEGORY_TEMPLATES={
  'apparel':{
    'label':'服饰','keywords':('服饰','女装','男装','童装','连衣裙','衬衫','裤子','外套','内衣','鞋','尺码','版型'),
    'dimensions':(
      ('尺码与适配',('尺码','尺寸','适用身高','适用体重','码数')),
      ('版型与轮廓',('版型','衣长','裤型','领型','袖长','腰型')),
      ('面料与成分',('面料','材质','成分','里料','含量')),
      ('做工与细节',('工艺','做工','缝制','拉链','纽扣')),
      ('颜色与款式',('颜色','色号','款式','图案','风格')),
      ('洗护与标准',('洗护','洗涤','执行标准','安全类别','等级')),
    )},
  'food':{
    'label':'食品','keywords':('食品','零食','饮料','咖啡','茶','牛奶','饼干','坚果','冲饮','口味','配料','保质期','净含量'),
    'dimensions':(
      ('规格与净含量',('规格','净含量','重量','数量','包装规格')),
      ('口味与食用体验',('口味','风味','甜度','食用方法')),
      ('配料与营养',('配料','成分','营养','能量','蛋白质')),
      ('保质期与储存',('保质期','生产日期','储存','保存')),
      ('产地与合规',('产地','生产许可证','执行标准','厂名','厂址')),
      ('包装与运输',('包装','包装方式','运输','破损')),
    )},
  'beauty':{
    'label':'美妆','keywords':('美妆','护肤','彩妆','面霜','精华','乳液','面膜','口红','粉底','防晒','肤质','功效'),
    'dimensions':(
      ('功效宣称',('功效','功能','效果','宣称')),
      ('适用肤质与人群',('肤质','适用人群','适用部位','肌肤')),
      ('成分与配方',('成分','配方','主要成分','净含量')),
      ('使用方式',('使用方法','使用步骤','用法','频次')),
      ('敏感与风险',('敏感','注意事项','禁忌','过敏')),
      ('备案与保质期',('备案','批准文号','执行标准','保质期','生产日期')),
    )},
  'digital':{
    'label':'数码','keywords':('数码','手机','电脑','平板','耳机','相机','键盘','鼠标','充电器','处理器','内存','存储','兼容'),
    'dimensions':(
      ('核心配置',('型号','处理器','内存','存储','容量','功率','分辨率')),
      ('兼容性',('兼容','适用型号','系统','接口','协议')),
      ('性能与续航',('性能','续航','电池','速度','刷新率','传输')),
      ('版本与规格',('版本','配置','颜色','尺寸','重量')),
      ('使用问题',('使用说明','连接','安装','故障')),
      ('质保与售后',('质保','保修','售后','认证','执行标准')),
    )},
  'home_textile':{
    'label':'家纺','keywords':('家纺','床品','四件套','三件套','被套','床单','床笠','枕套','被芯','枕芯','毛毯'),
    'dimensions':(
      ('结构与规格',('件数','套件组成','尺寸','规格','床型')),
      ('材质与触感',('面料','材质','成分','支数','密度','克重')),
      ('颜色与花型',('颜色','花型','图案','风格')),
      ('工艺与做工',('工艺','织造','印染','缝制')),
      ('洗后表现',('洗护','洗涤','缩水','掉色','起球')),
      ('场景适配',('适用场景','适用人群','季节')),
    )},
}

def detect_category(raw):
    product=raw.get('product') or {}; attrs=_attribute_rows(raw)
    corpus=' '.join([_txt(product.get('category')),_txt(product.get('title'))]+[f"{x.get('name')} {x.get('value')}" for x in attrs]+[_txt(x.get('group'))+' '+_txt(x.get('name')) for x in raw.get('sku',[]) if isinstance(x,dict)])
    scores={key:sum(1 for word in spec['keywords'] if word and word in corpus) for key,spec in CATEGORY_TEMPLATES.items()}
    key=max(scores,key=scores.get) if scores and max(scores.values()) else 'generic'
    if key=='generic':
        return {'key':'generic','label':_txt(product.get('category')).strip() or '通用商品','confidence':0.35,'dimensions':()}
    total=max(1,sum(scores.values()))
    spec=CATEGORY_TEMPLATES[key]
    return {'key':key,'label':spec['label'],'confidence':round(min(0.98,0.55+scores[key]/total*0.4),2),'dimensions':spec['dimensions']}

def _category_parameter_facts(raw, limit=12):
    attrs=_attribute_rows(raw); route=detect_category(raw); used=set(); facts=[]
    dimensions=route.get('dimensions') or ()
    if not dimensions:
        dimensions=tuple((_txt(x.get('name')).strip(),(_txt(x.get('name')).strip(),)) for x in attrs[:8])
    for label,aliases in dimensions:
        matches=[];refs=[]
        for i,item in enumerate(attrs,1):
            if i in used:continue
            name=_txt(item.get('name')).strip()
            if any(alias and alias in name for alias in aliases):
                used.add(i);matches.append(item);refs.append(f'ATTR_{i:04d}')
        if not matches:continue
        value='；'.join(f"{x.get('name')}：{x.get('value')}" for x in matches)
        facts.append({'label':label,'value':concise_fact(value,240),'productMeaning':'当前类目需要核对的页面产品定义','evidenceIds':refs})
        if len(facts)>=limit:return facts
    for i,item in enumerate(attrs,1):
        if i in used:continue
        facts.append({'label':_txt(item.get('name')),'value':concise_fact(item.get('value'),180),'productMeaning':'页面采集参数，开发新品前与实物或资料核对','evidenceIds':[f'ATTR_{i:04d}']})
        if len(facts)>=limit:break
    return facts

def _category_gates(raw, issue=None):
    issue=issue or _review_issue(raw); route=detect_category(raw); attrs=_attribute_rows(raw); gates=[]
    if issue:
        gates.append({'priority':'P0','label':f"评论问题：{issue['label']}",'action':issue['action'],'businessReason':concise_fact(issue['text'],72),'evidenceIds':[issue['evidenceId']]})
    for fact in _category_parameter_facts(raw,6):
        gates.append({'priority':'P0' if len(gates)<3 else 'P1','label':f"核对{fact['label']}",'action':f"核对样品、SKU、参数和详情页中的{fact['label']}是否一致",'businessReason':f"{route['label']}商品的关键选择信息必须可追溯",'evidenceIds':fact['evidenceIds']})
    return gates[:7]

def _category_validation_rows(raw):
    route=detect_category(raw); facts=_category_parameter_facts(raw,8); refs=_uniq(sum((_arr(x.get('evidenceIds')) for x in facts),[])); issue=_review_issue(raw)
    issue_refs=[issue['evidenceId']] if issue else []
    return [
      {'stage':'商品定义','owner':'商品企划 / 商品运营','hypothesis':'','metrics':f"锁定{route['label']}商品的关键参数、SKU和目标场景",'successMeaning':'商品定义与已采参数逐项对应','nextAction':'通过后发起打样；不一致则退回定义','evidenceIds':refs},
      {'stage':'样品与资料','owner':'供应链 / 品控','hypothesis':'','metrics':'核对实物、标签、包装、合规资料和页面宣称','successMeaning':'页面信息与真实商品一致','nextAction':'通过后锁版；不一致则暂停对应宣称','evidenceIds':refs},
      {'stage':'场景验证','owner':'商品企划 / 品控','hypothesis':'','metrics':'按当前类目关键使用场景验证规格、功能和体验','successMeaning':'验证结果有记录并可回溯到SKU','nextAction':'通过后进入页面制作；不通过则调整产品','evidenceIds':refs+issue_refs},
      {'stage':'页面验收','owner':'视觉与内容','hypothesis':'','metrics':'逐项核对主图、详情图、SKU、参数和营销表达','successMeaning':'图片来源清晰且没有结构、颜色或功能冲突','nextAction':'通过后上架；不通过则重新采集或修改页面','evidenceIds':refs},
      {'stage':'首批反馈','owner':'客服与数据','hypothesis':'','metrics':'按SKU记录咨询、评论、退款售后原话与问题批次','successMeaning':'反馈可以归因到具体规格和问题类型','nextAction':'保留通过SKU；集中问题返回供应链整改','evidenceIds':issue_refs},
    ]

def _product_label(raw):
    product=raw.get('product',{}); title=_valid_title(product.get('title'))
    if title:return title
    route=detect_category(raw); attrs=_attribute_rows(raw); parts=[]
    for words in [('品牌',),('品类','类别','商品类型'),('型号','款式','口味','色号')]:
        x,_=_find_attr(attrs,words)
        if x and _txt(x.get('value')).strip() not in parts:parts.append(_txt(x.get('value')).strip())
    return ' '.join(parts[:3]) or route['label'] or '当前商品'

def _review_ref(raw, predicate):
    for i,x in enumerate(raw.get('reviews',[]) or [],1):
        text=_txt(x.get('content'))+' '+_txt(x.get('appendContent'))
        if predicate(text):return text.strip(),f'REV_{i:06d}'
    return '',''

def _buyer_evidence(raw, limit=24):
    images=raw.get('images',{}) or {}; buyer=images.get('buyerShow',[]) or []; index_by_url={url:i for i,url in enumerate(buyer,1)}
    out=[];seen=set()
    for review_index,review in enumerate(raw.get('reviews',[]) or [],1):
        for url in review.get('images',[]) or []:
            image_index=index_by_url.get(url)
            if not image_index or url in seen:continue
            seen.add(url);out.append({'imageEvidenceId':f'IMG_BUYERSHOW_{image_index:04d}','reviewEvidenceId':f'REV_{review_index:06d}','quote':concise_fact(review.get('content'),72),'sku':_txt(review.get('sku')).strip(),'date':_txt(review.get('date')).strip(),'sourceLabel':'评论原图'})
            if len(out)>=limit:return out
    return out

REVIEW_OUTCOME_RULES=(
  ('花型与空间呈现',('好看','漂亮','可爱','高级','颜值','搭配儿童房','风格也搭','氛围感','少女心'),'明确反馈花型好看、可爱或能搭配房间'),
  ('触感与睡感',('柔软','舒服','舒适','亲肤','滑滑','光滑','手感很好','手感特别'),'明确反馈柔软、舒服、亲肤或光滑'),
  ('儿童接受度',('孩子很喜欢','孩子特别喜欢','宝宝超喜欢','宝宝很喜欢','女儿很喜欢'),'明确反馈孩子、宝宝或女儿喜欢'),
  ('质量与做工',('做工也很好','做工细节都很棒','做工好精致','质量真的很好','质量特别好','质量非常好','品质真不错','质感很好'),'明确反馈质量或做工表现好'),
  ('复购意愿',('再买一套','下次还会来','下次再回购','认准你家'),'明确表达再次购买、回购或认准店铺'),
)

REVIEW_ISSUE_RULES=(
  ('size_fit','尺寸与床型适配',r'罩不住|铺不满|盖不住|垂边不够|床单.{0,10}(?:短|小|窄|不够)|(?:尺寸|大小).{0,8}(?:偏小|偏大|不合适|不符)|被套.{0,8}(?:偏小|偏大|不合适|不符)','按评论对应 SKU 在实际床垫铺装，记录床单垂边、床笠包裹和被套适配后再锁版'),
  ('wash_stability','首洗缩水或掉色',r'缩水|掉色|褪色|洗后.{0,8}(?:变形|发硬|变小|小了)','按标示洗护完成首洗，对比洗前洗后尺寸、颜色和表面状态'),
  ('pilling_shedding','起球或掉毛',r'起球|掉毛|粘毛|浮毛','完成面料与成品洗后起球、掉毛检查，不通过则调整面料或后整理'),
  ('odor','气味',r'异味|刺鼻|味道.{0,8}(?:大|重|难闻)','检查面料、印染、填充与包装来源，成品散味验收通过后再入仓'),
  ('sewing_breakage','缝制或破损',r'破损|开线|脱线|线头.{0,8}(?:多|严重)|走线.{0,8}(?:歪|差)|缝.{0,8}(?:开|坏)','复核裁剪、缝制、锁边和出货外观，问题批次返修后复检'),
  ('material_mismatch','材质信息不一致',r'不是纯棉|不是全棉|材质.{0,8}(?:不符|不一样)|面料.{0,8}(?:不符|不一样)|货不对板','核对供应资料、水洗标、吊牌、样品和页面材质表述，一处不一致即暂停宣称'),
  ('packaging_transfer','包装污染或转移',r'包装.{0,10}(?:染|脏|掉色)|油墨|印字.{0,8}(?:沾|染)|包装袋.{0,8}(?:沾|染)','做包装接触与运输模拟，检查油墨、颜色、气味和污渍转移'),
  ('pillow_filling','枕芯或填充支撑',r'枕头.{0,8}(?:太高|太低|太硬|太软|塌)|枕芯.{0,8}(?:太高|太低|太硬|太软|塌)|填充.{0,8}(?:少|不均|结团)','核对填充重量、均匀度和支撑感，按套件 BOM 留样验收'),
  ('color_difference','实物色差',r'色差|实物.{0,8}(?:偏黄|偏白|偏暗|颜色不一样)|图片.{0,8}(?:不一样|差很多)','自然光核对实物色号与页面图片，页面补充真实色差说明'),
)

def _review_issue(raw):
    reviews=raw.get('reviews',[]) or []
    route=detect_category(raw)
    dynamic_rules={
      'apparel':(
        ('apparel_size','尺码或版型适配',r'尺码|码数|偏大|偏小|不合身|显胖|版型.{0,8}(?:不符|奇怪)','按评论对应SKU复核尺码表、版型数据和真人试穿效果'),
        ('apparel_workmanship','服饰做工问题',r'开线|脱线|线头|拉链|纽扣|破损','复核对应批次的缝制、辅料和出货外观'),
        ('apparel_color','服饰图实色差',r'色差|实物.{0,8}颜色|图片.{0,8}不一样','在统一自然光下核对实物色号与页面图片'),
      ),
      'food':(
        ('food_taste','口味反馈分化',r'难吃|太甜|太咸|口味.{0,8}(?:怪|淡|重)','按口味SKU统计反馈并复核配方与页面描述'),
        ('food_package','食品包装或运输问题',r'漏液|胀包|破包|碎了|包装.{0,8}(?:破|坏)','复核包装密封、内衬和运输模拟结果'),
        ('food_freshness','新鲜度或保质风险',r'变质|过期|不新鲜|临期|发霉','核对生产批次、保质期、储存和出库规则'),
      ),
      'beauty':(
        ('beauty_sensitive','敏感或刺激反馈',r'过敏|刺激|刺痛|泛红|闷痘|爆痘','按肤质和使用方式复核对应SKU与成分风险提示'),
        ('beauty_claim','功效体验不一致',r'没效果|无效|不吸收|搓泥|拔干|油腻','拆分功效宣称、使用方法与真实反馈，降低过强承诺'),
        ('beauty_package','美妆包装问题',r'漏液|泵头|瓶口|包装.{0,8}(?:坏|破)','复核包材、密封和运输跌落测试'),
      ),
      'digital':(
        ('digital_compat','兼容或连接问题',r'不兼容|连不上|连接.{0,8}(?:失败|断)|识别不了','按设备型号、系统和接口复核兼容列表'),
        ('digital_performance','性能或续航问题',r'卡顿|发热|死机|续航.{0,8}(?:差|短)|掉电|速度慢','按配置版本复测性能、温度、续航和稳定性'),
        ('digital_quality','数码质量问题',r'失灵|故障|坏了|杂音|断触|黑屏','定位批次和故障场景，复核出厂测试与售后记录'),
      ),
    }
    for key,label,pattern,action in dynamic_rules.get(route['key'],()):
        rx=re.compile(pattern,re.I)
        for i,review in enumerate(reviews,1):
            if not isinstance(review,dict):continue
            text=(' '.join(x for x in (_txt(review.get('content')).strip(),_txt(review.get('appendContent')).strip()) if x)).strip()
            if text and rx.search(text):
                return {'key':key,'label':label,'action':action,'text':text,'evidenceId':f'REV_{i:06d}','sku':_txt(review.get('sku')).strip()}
    for key,label,pattern,action in REVIEW_ISSUE_RULES:
        rx=re.compile(pattern,re.I)
        for i,review in enumerate(reviews,1):
            if not isinstance(review,dict):continue
            text=(' '.join(x for x in (_txt(review.get('content')).strip(),_txt(review.get('appendContent')).strip()) if x)).strip()
            if text and rx.search(text):
                return {'key':key,'label':label,'action':action,'text':text,'evidenceId':f'REV_{i:06d}','sku':_txt(review.get('sku')).strip()}
    for i,review in enumerate(reviews,1):
        if not isinstance(review,dict):continue
        text=(' '.join(x for x in (_txt(review.get('content')).strip(),_txt(review.get('appendContent')).strip()) if x)).strip()
        if text and any(k in text for k in NEGATIVE_REVIEW_KEYS):
            return {'key':'other','label':'评论明确问题','action':'按评论原文定位对应 SKU 和批次，复核实物后再决定是否修版','text':text,'evidenceId':f'REV_{i:06d}','sku':_txt(review.get('sku')).strip()}
    return {}

HOME_TEXTILE_FACT_GROUPS=(
  ('适用场景 / 人群',('适用场景','适用人群','适用对象'),'用于锁定使用场景与商品表达'),
  ('套件 BOM',('套件组成','套件件数','件数','组合形式','套件种类'),'用于逐件核对套装构成与包装清单'),
  ('材质 / 成分',('成分含量','床单面料材质','被面材质','被里材质','枕套材质','面料材质','棉种类','材质'),'用于核对供应资料、水洗标与页面宣称'),
  ('支数 / 密度 / 克重',('面料支数','纱线支数','织物密度','面料密度','克重'),'用于锁定面料规格，不等同于检测结果'),
  ('床型 / 成品尺寸',('适用床尺寸','床品尺寸','被套尺寸','床单尺寸','床笠尺寸','枕套尺寸','尺寸'),'用于床型铺装和 SKU 适配校验'),
  ('工艺 / 结构',('床品工艺','织造工艺','印染工艺','面料工艺','绗缝工艺','填充工艺','工艺','款式'),'用于样品结构与生产工艺核对'),
  ('等级 / 标准',('产品等级','安全类别','执行标准','质量等级'),'用于核对吊牌、检测资料与页面口径'),
  ('洗护说明',('洗涤说明','洗护说明','洗涤方式','护理方法'),'用于首洗验证和售后说明'),
)

def _home_textile_parameter_facts(raw, limit=10):
    attrs=_attribute_rows(raw);used=set();facts=[]
    for label,words,meaning in HOME_TEXTILE_FACT_GROUPS:
        matches=[];refs=[]
        for i,item in enumerate(attrs,1):
            if i in used:continue
            name=_txt(item.get('name')).strip()
            if any(word in name for word in words):
                used.add(i);matches.append(item);refs.append(f'ATTR_{i:04d}')
        if not matches:continue
        value='；'.join((f"{x.get('name')}：{x.get('value')}" if len(matches)>1 else _txt(x.get('value'))) for x in matches)
        facts.append({'label':label,'value':concise_fact(value,220),'productMeaning':meaning,'evidenceIds':refs})
        if len(facts)>=limit:return facts
    for i,item in enumerate(attrs,1):
        if i in used:continue
        facts.append({'label':_txt(item.get('name')),'value':concise_fact(item.get('value'),180),'productMeaning':'页面采集参数，批量上架前与实物核对','evidenceIds':[f'ATTR_{i:04d}']})
        if len(facts)>=limit:break
    return facts

def _home_textile_gates(raw, issue=None):
    attrs=_attribute_rows(raw);issue=issue or _review_issue(raw)
    material,material_id=_find_attr(attrs,('成分含量','床单面料材质','被面材质','被里材质','材质','棉种类'))
    pieces,pieces_id=_find_attr(attrs,('套件组成','套件件数','件数','组合形式'))
    size,size_id=_find_attr(attrs,('适用床尺寸','床品尺寸','被套尺寸','床单尺寸','尺寸'))
    wash,wash_id=_find_attr(attrs,('洗涤说明','洗护说明','洗涤方式','护理方法'))
    grade,grade_id=_find_attr(attrs,('产品等级','安全类别','执行标准'))
    gates=[]
    if pieces:gates.append({'priority':'P0','label':'套件 BOM 一致','action':'逐件核对样品、包装清单、SKU 名称和详情页的品类、件数与尺寸','businessReason':'套件构成必须与页面参数一致','evidenceIds':[pieces_id]})
    if material or grade:gates.append({'priority':'P0','label':'材质与标签一致','action':'核对供应资料、水洗标、吊牌、样品和页面的成分、等级与执行标准','businessReason':'页面宣称必须能回溯到真实资料','evidenceIds':[x for x in (material_id,grade_id) if x]})
    if size:gates.append({'priority':'P0','label':'床型与尺寸实测','action':'按页面覆盖床型和床垫高度逐一铺装，记录床单垂边、床笠包裹与被套适配','businessReason':'每个 SKU 通过实床铺装后才能锁版','evidenceIds':[size_id]})
    gates.append({'priority':'P0','label':'首洗前后验收','action':'按标示洗护完成首洗，记录各部件尺寸、颜色、起球掉毛和外观变化','businessReason':'结果须符合页面声明及企业验收标准','evidenceIds':[wash_id] if wash_id else []})
    gates.append({'priority':'P1','label':'缝制与填充验收','action':'检查走线、锁边、拉链、线头、污渍；含枕芯或被芯时同步检查填充重量与均匀度','businessReason':'成品外观与套件完整性通过后再入仓','evidenceIds':[pieces_id] if pieces_id else []})
    gates.append({'priority':'P1','label':'气味与包装转移','action':'完成密封、运输模拟和开箱检查，记录气味、油墨、颜色与污渍转移','businessReason':'包装与商品接触后不得污染成品','evidenceIds':[]})
    if issue:gates.insert(0,{'priority':'P0','label':f"评论问题：{issue['label']}",'action':issue['action'],'businessReason':concise_fact(issue['text'],72),'evidenceIds':[issue['evidenceId']]})
    return gates[:7]

def _home_textile_validation_rows(raw):
    attrs=_attribute_rows(raw);all_refs=[f'ATTR_{i:04d}' for i in range(1,min(len(attrs),8)+1)]
    issue=_review_issue(raw);issue_refs=[issue['evidenceId']] if issue else []
    return [
      {'stage':'商品定义','owner':'商品企划 / 商品运营','hypothesis':'','metrics':'锁定目标场景、套件 BOM、材质工艺、床型尺寸与 SKU','successMeaning':'商品定义表与页面已采参数逐项对应','nextAction':'通过后发起打样；不一致则退回定义','evidenceIds':all_refs},
      {'stage':'资料与标签','owner':'供应链 / 品控','hypothesis':'','metrics':'核对供应资料、水洗标、吊牌、包装和样品','successMeaning':'成分、等级、标准与洗护口径一致','nextAction':'通过后确认样品；不一致则暂停宣称','evidenceIds':all_refs},
      {'stage':'实床与首洗','owner':'品控 / 供应链','hypothesis':'','metrics':'按 SKU 实床铺装；首洗前后记录尺寸、掉色、起球掉毛与外观','successMeaning':'符合页面声明及企业验收标准，记录可追溯','nextAction':'通过后锁版；不通过则调整尺寸、面料或工艺','evidenceIds':all_refs+issue_refs},
      {'stage':'成品与包装','owner':'品控 / 仓配','hypothesis':'','metrics':'检查缝制、填充、污渍、气味及包装接触转移','successMeaning':'成品与包装验收项全部通过','nextAction':'通过后入仓；问题批次返修复检','evidenceIds':issue_refs},
      {'stage':'页面验收','owner':'视觉与内容','hypothesis':'','metrics':'逐项核对主图、详情、SKU 表、尺寸图、材质与洗护说明','successMeaning':'页面图片来源清晰，且与样品、包装、标签一致','nextAction':'通过后上架；不通过则停止投放','evidenceIds':all_refs},
      {'stage':'首批反馈','owner':'客服与数据','hypothesis':'','metrics':'按 SKU 记录咨询、评论、退款售后原话与问题批次','successMeaning':'反馈均可回溯到 SKU、订单和问题类型','nextAction':'保留通过 SKU；集中问题返回供应链整改','evidenceIds':[]},
    ]

def _review_outcomes(raw):
    reviews=raw.get('reviews',[]) or [];out=[]
    for label,keys,result in REVIEW_OUTCOME_RULES:
        matched=[]
        for i,x in enumerate(reviews,1):
            if not isinstance(x,dict):continue
            text=_txt(x.get('content'))+' '+_txt(x.get('appendContent'))
            if any(k in text for k in keys):matched.append(f'REV_{i:06d}')
        if matched:out.append({'label':label,'value':f'{len(matched)} 条评论{result}','note':f'评论结果 · {len(matched)}/{len(reviews)}','evidenceIds':matched})
    return out

def _find_outcome(outcomes, label):
    for item in outcomes or []:
        if isinstance(item,dict) and item.get('label')==label:return item
    return {}

def _generic_selling_points(raw, base=None, issue=None):
    base=base or baseline(raw); issue=issue or _review_issue(raw); route=detect_category(raw)
    points=[]
    for fact in _category_parameter_facts(raw,5):
        value=concise_fact(fact.get('value'),52)
        if not value:continue
        points.append({
          'slogan':f"{fact.get('label')}：{value}",
          'consumerValue':f"让消费者直接确认{route['label']}商品的{fact.get('label')}",
          'evidenceSource':'页面参数',
          'productAction':f"主图或详情页用实物、参数或资料证明{fact.get('label')}",
          'evidenceIds':fact.get('evidenceIds') or []
        })
    outcomes=_review_outcomes(raw)
    for outcome in outcomes[:2]:
        refs=_arr(outcome.get('evidenceIds'))
        if refs:points.append({'slogan':concise_fact(outcome.get('value'),46),'consumerValue':'把评论已验证体验转成页面可理解的利益表达','evidenceSource':'评论聚合','productAction':'保留对应产品体验，并用实拍或细节证据承接','evidenceIds':refs[:8]})
    if issue:
        points.append({'slogan':f"优先修正{issue['label']}",'consumerValue':'避免下一款重复当前已出现的问题','evidenceSource':'评论明确问题','productAction':issue['action'],'evidenceIds':[issue['evidenceId']]})
    unique=[];seen=set()
    for point in points:
        key=point.get('slogan')
        if key and key not in seen:seen.add(key);unique.append(point)
    return unique[:6]

def _derive_next_selling_points(raw, base=None, issue=None):
    if detect_category(raw)['key']!='home_textile':
        return _generic_selling_points(raw,base,issue)
    base=base or baseline(raw); issue=issue or _review_issue(raw)
    attrs=_attribute_rows(raw); outcomes=_review_outcomes(raw)
    title=_txt((raw.get('product') or {}).get('title')).strip()
    sku_text=' '.join(_txt(x.get('name') or x.get('text') or x.get('value')) for x in raw.get('sku',[]) if isinstance(x,dict))[:3000]
    attr_text=' '.join(f"{x.get('name')}:{x.get('value')}" for x in attrs)[:3000]
    corpus=' '.join([title,sku_text,attr_text])
    size,size_id=_find_attr(attrs,('适用床尺寸','床品尺寸','被套尺寸','床单尺寸','床笠尺寸','尺寸'))
    material,material_id=_find_attr(attrs,('成分含量','床单面料材质','被面材质','被里材质','枕套材质','面料材质','材质','棉种类'))
    craft,craft_id=_find_attr(attrs,('床品工艺','织造工艺','面料密度','面料支数','工艺'))
    pattern,pattern_id=_find_attr(attrs,('主图案类型','风格','颜色分类','款式'))
    pieces,pieces_id=_find_attr(attrs,('件数','套件组成','套件件数','组合形式'))
    touch=_find_outcome(outcomes,'触感与睡感')
    design=_find_outcome(outcomes,'花型与空间呈现')
    size_outcome=_find_outcome(outcomes,'儿童接受度') if '儿童' in corpus else {}
    points=[]
    def add(slogan, consumer, evidence, action, refs):
        refs=[x for x in _uniq(refs) if x]
        if not refs:return
        points.append({'slogan':slogan,'consumerValue':consumer,'evidenceSource':evidence,'productAction':action,'evidenceIds':refs})
    has_dorm_scene=bool(re.search(r'宿舍|大学|大学生',corpus))
    has_small_bed=bool(re.search(r'0\.?9|0.9|1\.?2|1.2|90|120',corpus))
    scene='宿舍床专用' if has_dorm_scene else ('小床专用' if has_small_bed else '目标床型专用')
    if size:
        size_value=_txt(size.get('value'))
        if has_dorm_scene and re.search(r'0\.?9|0.9|90',size_value+corpus):
            add('0.9m 宿舍床专用，不用猜尺寸','消费者一眼知道这套床品适配哪张宿舍床','页面尺寸参数、目标场景与 SKU 信息', '首图拍 0.9m 宿舍床效果；详情页单独列被套、床单/床笠、枕套尺寸', [size_id,pieces_id])
        elif has_small_bed:
            add('小床尺寸单独讲清，不让用户猜','消费者一眼知道这套床品适配哪张床','页面尺寸参数与 SKU 信息', '首图拍对应床型效果；详情页单独列被套、床单/床笠、枕套尺寸', [size_id,pieces_id])
        else:
            add(f'{scene}，尺寸直接看清','减少买错床型和规格的理解成本','页面尺寸参数', '按主销床型分别拍铺设边界和套件尺寸图', [size_id,pieces_id])
    if re.search(r'床笠',corpus) and re.search(r'床单',corpus):
        add('床笠款 / 床单款分开买，不混规格','消费者能判断自己要包床垫款还是普通床单款','SKU 与参数中同时出现床笠、床单', '分标题、分 SKU、分主图、分详情页说明两种结构', [x for x in (size_id,pieces_id) if x])
    elif re.search(r'床笠',corpus):
        add('床笠款包住床垫，铺上不跑位','强调包裹、防滑和宿舍床垫适配','页面 SKU/参数出现床笠', '拍四角包裹、床垫厚度、洗后回弹', [size_id,pieces_id])
    if material:
        mat=_txt(material.get('value'))
        add(('100%棉基础面料，贴身不将就' if '100' in mat or '棉' in mat else '基础面料信息讲清楚'),'消费者知道材质承诺来自页面参数','页面材质/成分参数', '材质页同时展示水洗标、吊牌和面料近景', [material_id]+_arr(touch.get('evidenceIds'))[:3])
    if touch.get('evidenceIds'):
        add('全棉要柔软，不要偏硬刮肤','把“全棉”转成可感知的触感利益','评论聚合中有柔软、亲肤或舒服反馈', '打样增加触感验收、柔软后整理和首洗后手感复检', _arr(touch.get('evidenceIds'))[:6]+([material_id] if material_id else []))
    if issue and issue.get('key')=='wash_stability':
        add('首洗后尺寸稳定，洗完还能铺得平','消费者买床品要省心耐用','评论明确出现缩水或掉色反馈', '每批做首洗尺寸、颜色和外观记录，页面展示洗前洗后结果', [issue.get('evidenceId'),size_id])
    elif issue and issue.get('key')=='size_fit':
        add('铺上合适，边界不尴尬','消费者最怕买回去罩不住、铺不满','评论明确出现尺寸适配问题', '按 SKU 实床铺设并记录床单垂边、床笠包裹和被套适配', [issue.get('evidenceId'),size_id])
    if design.get('evidenceIds') or pattern:
        add(('耐看花色，宿舍日常好打理' if has_dorm_scene else '耐看花色，日常好打理'),'花色不是只讲好看，要讲耐看、耐脏、适合日常','评论花型反馈或页面花型参数', '保留已验证花型方向；主图补自然光、局部纹样和整套陈列', _arr(design.get('evidenceIds'))[:5]+([pattern_id] if pattern_id else []))
    if craft:
        add('工艺参数讲明白，品质感有出处','支数、密度、印染或织造信息不只放参数表','页面工艺/支数/密度参数', '详情页用面料近景、工艺说明和水洗标承接参数', [craft_id])
    return points[:6]

def _apply_selling_points(exp, raw, base=None):
    if not isinstance(exp,dict):return exp
    base=base or baseline(raw); issue=_review_issue(raw); points=_derive_next_selling_points(raw,base,issue)
    plans=exp.setdefault('newProductPlans',{})
    plan_list=plans.setdefault('plans',[])
    if plan_list and isinstance(plan_list[0],dict):
        existing=_arr(plan_list[0].get('sellingPoints'))
        plan_list[0]['sellingPoints']=points[:5] or existing
        if points:
            kept=[x for x in _arr(plan_list[0].get('specs')) if not (isinstance(x,dict) and x.get('label')=='下一款明确卖点')]
            plan_list[0]['specs']=[{'label':'下一款明确卖点','value':' / '.join(x['slogan'] for x in points[:3])}]+kept
    if points:
        overview=exp.setdefault('ownerOverview',{})
        cards=[x for x in overview.setdefault('cards',[]) if not (isinstance(x,dict) and x.get('label')=='下一款明确卖点')]
        cards.append({'label':'下一款明确卖点','headline':points[0]['slogan'],'bullets':[x['slogan'] for x in points[1:3]],'tone':'good','evidenceIds':points[0].get('evidenceIds',[])})
        overview['cards']=cards
    exp['contentGovernance']={
        'role':'专业电商报告输出总监',
        'structure':'商品产品分析报告',
        'sourceRule':'页面参数、主图/详情/SKU/评论图、评论统计、问答和监测数据分来源呈现',
        'evidenceRule':'每个结论必须引用 evidenceIds；缺失证据不补写',
        'visualRule':'报告渲染采用时尚网页设计美学：大图完整展示、清晰层级、短结论、证据卡片化'
    }
    return exp

def _ensure_three_product_plans(exp, raw, base=None):
    """Keep one evidence-backed plan for each decision horizon, even when the model returns fewer."""
    if not isinstance(exp,dict):return exp
    base=base or baseline(raw); block=exp.setdefault('newProductPlans',{})
    existing=[x for x in block.get('plans',[]) or [] if isinstance(x,dict)]
    valid_types=('证据驱动优化','反馈驱动升级','探索性方向')
    by_type={}
    untyped=[]
    for plan in existing:
        source=_txt(plan.get('sourceType')).strip()
        if source in valid_types and source not in by_type:by_type[source]=dict(plan)
        else:untyped.append(dict(plan))
    for source in valid_types:
        if source not in by_type and untyped:
            plan=untyped.pop(0);plan['sourceType']=source;by_type[source]=plan

    attrs=_attribute_rows(raw);issue=_review_issue(raw);points=_derive_next_selling_points(raw,base,issue)
    attr_refs=[f'ATTR_{i:04d}' for i in range(1,min(len(attrs),6)+1)]
    review_refs=[]
    if issue and issue.get('evidenceId'):review_refs.append(issue['evidenceId'])
    for point in points:
        review_refs.extend(x for x in point.get('evidenceIds',[]) or [] if _txt(x).startswith('REV_'))
    review_refs=_uniq(review_refs)[:6]
    shared_refs=_uniq((attr_refs or ['P_TITLE'])+review_refs)
    strongest=points[0] if points else {}

    fallbacks={
      '证据驱动优化':{
        'sourceType':'证据驱动优化','name':'规格校准款',
        'productAction':_txt(strongest.get('productAction')).strip() or '统一现有规格、材质、结构与套件口径',
        'pageAction':'主图讲清商品与场景，详情逐项证明材质、结构和规格',
        'evidenceIds':shared_refs,
      },
      '反馈驱动升级':{
        'sourceType':'反馈驱动升级','name':'体验升级款',
        'productAction':(_txt(issue.get('action')).strip() if issue else '') or '围绕已采消费者反馈优化使用体验与规格适配',
        'pageAction':'用实拍动作、细节近景和对照信息回应购买顾虑',
        'evidenceIds':_uniq(review_refs+attr_refs) or shared_refs,
      },
      '探索性方向':{
        'sourceType':'探索性方向','name':'差异探索款',
        'productAction':'基于现有结构开发差异化配色或规格小样，先验证再定款',
        'pageAction':'独立展示探索设计与适用场景，不宣称已获市场验证',
        'evidenceIds':shared_refs,
      },
    }
    plans=[]
    for source in valid_types:
        plan=by_type.get(source) or fallbacks[source]
        plan['sourceType']=source
        if not _txt(plan.get('name')).strip():plan['name']=fallbacks[source]['name']
        name=_txt(plan.get('name')).strip()
        if len(name)>14:name=fallbacks[source]['name']
        if not name.endswith('款'):name=name[:17].rstrip(' ，。-')+'款'
        plan['name']=name[:17].rstrip(' ，。-')+'款' if len(name)>18 else name
        if not _txt(plan.get('productAction')).strip():plan['productAction']=fallbacks[source]['productAction']
        if not _txt(plan.get('pageAction')).strip():plan['pageAction']=fallbacks[source]['pageAction']
        if not plan.get('evidenceIds'):plan['evidenceIds']=fallbacks[source]['evidenceIds']
        plans.append(plan)
    block['plans']=plans
    block['professionalOpinion']=block.get('professionalOpinion') or '三条路径并行对照：先优化现有商品，再回应反馈，最后小样验证差异方向。'
    return exp

def _generic_platform_overview(raw, base=None):
    base=base or baseline(raw); route=detect_category(raw); attrs=_attribute_rows(raw); sales=raw.get('sales') or {}; issue=_review_issue(raw)
    price=_txt(sales.get('currentPrice')).strip(); sold=_txt(sales.get('sold') or sales.get('cumulativeSales')).strip(); facts=[]
    facts.append({'label':'商品是什么','value':_product_label(raw),'note':f"自动识别：{route['label']}",'evidenceIds':['P_TITLE'] if _valid_title((raw.get('product') or {}).get('title')) else []})
    if price or sold:facts.append({'label':'价格与销量','value':' · '.join(x for x in (f'¥{price}' if price else '',f'公开销量 {sold}' if sold else '') if x),'note':'采集时页面公开值','evidenceIds':[x for x in ('S_CURRENTPRICE' if price else '','S_SOLD' if sold else '') if x]})
    if attrs:facts.append({'label':'动态参数','value':f'已采集 {len(attrs)} 项','note':'；'.join(f"{x.get('name')}：{x.get('value')}" for x in attrs[:3]),'evidenceIds':[f'ATTR_{i:04d}' for i in range(1,min(3,len(attrs))+1)]})
    outcomes=_review_outcomes(raw); actions=[]
    if outcomes:actions.append({'label':'保留','value':'保留评论已验证的实际体验','note':outcomes[0].get('value'),'evidenceIds':outcomes[0].get('evidenceIds') or []})
    if issue:actions.append({'label':'修正','value':issue['action'],'note':issue['label'],'evidenceIds':[issue['evidenceId']]})
    refs=[f'ATTR_{i:04d}' for i in range(1,min(3,len(attrs))+1)]
    if refs:actions.append({'label':'下一步','value':f"按{route['label']}关键维度核对样品、SKU和页面一致性",'note':'当前证据支持商品拆解与新品开发','evidenceIds':refs})
    public=_txt(base.get('publicReviewCount')).strip();sample=f"已采有效评论 {base.get('reviewCount',0)}"+(f" / 页面公开 {public}" if public else '')
    sample+='；评论采集已确认完整' if base.get('reviewCollectionComplete') else '；评论采集未确认完整'
    return {'chapterTitle':'商品分析结论','verdict':'先保留已确认信息，再处理评论问题和页面缺口','facts':facts,'outcomes':outcomes[:5],'actions':actions,'checks':_category_gates(raw,issue)[:3],'questions':[{'label':'购买问答原文','value':concise_fact(x.get('question'),64),'evidenceIds':[f'QA_{i:05d}']} for i,x in enumerate(raw.get('questions',[])[:2],1) if isinstance(x,dict)],'sampleNote':sample,'decisionBoundary':{'supported':'商品拆解、样品验证、规格校准、页面修正和新品方案','excluded':'生产规模、利润、转化、市场容量','required':'完整评论、流量转化、退款售后、成本毛利'}}

def build_platform_overview(raw, base=None):
    if detect_category(raw)['key']!='home_textile':
        return _generic_platform_overview(raw,base)
    base=base or baseline(raw);attrs=_attribute_rows(raw);sales=raw.get('sales',{}) or {};topics=base.get('topics',[]) or []
    label=_product_label(raw);price=_txt(sales.get('currentPrice')).strip();sold=_txt(sales.get('sold') or sales.get('cumulativeSales')).strip()
    material,material_id=_find_attr(attrs,('床单面料材质','被面材质','材质','成分'))
    thread,thread_id=_find_attr(attrs,('面料支数',));pieces,pieces_id=_find_attr(attrs,('件数','套件组成'))
    size_attr,size_id=_find_attr(attrs,('适用床尺寸','床品尺寸','尺寸'));audience,audience_id=_find_attr(attrs,('适用人群',))
    craft,craft_id=_find_attr(attrs,('床品工艺','织造工艺','工艺'));grade,grade_id=_find_attr(attrs,('产品等级','安全类别','执行标准'))
    promotions=[x for x in raw.get('promotions',[]) or [] if isinstance(x,dict) and _txt(x.get('text')).strip()]
    issue=_review_issue(raw);neg_text=issue.get('text','');neg_id=issue.get('evidenceId','')
    facts=[]
    product_parts=[];product_refs=[]
    for x,eid in ((material,material_id),(thread,thread_id),(pieces,pieces_id),(craft,craft_id)):
        if x:product_parts.append(f"{x.get('name')}：{x.get('value')}");product_refs.append(eid)
    facts.append({'label':'商品是什么','value':label,'note':'；'.join(product_parts[:3]),'evidenceIds':product_refs[:3]})
    if audience:facts.append({'label':'页面适用人群','value':audience.get('value'),'note':'页面参数原文','evidenceIds':[audience_id]})
    if price or sold:
        facts.append({'label':'价格与销量','value':' · '.join(x for x in (f'¥{price}' if price else '',f'公开销量 {sold}' if sold else '') if x),'note':'采集时页面公开值','evidenceIds':[x for x in ('S_CURRENTPRICE' if price else '','S_SOLD' if sold else '') if x]})
    if promotions:facts.append({'label':'页面活动','value':concise_fact(promotions[0].get('text'),72),'note':'活动以采集时页面展示为准','evidenceIds':['PROMO_0001']})
    outcomes=_review_outcomes(raw)
    checks=[]
    if size_attr:checks.append({'priority':'运营校验','label':'核对床型与套件尺寸','value':size_attr.get('value'),'evidenceIds':[size_id]})
    if neg_id:checks.append({'priority':'明确反馈','label':f"重点核对{issue['label']}",'value':concise_fact(neg_text,72),'evidenceIds':[neg_id]})
    if grade:checks.append({'priority':'页面参数','label':grade.get('name'),'value':grade.get('value'),'evidenceIds':[grade_id]})
    questions=[]
    for i,q in enumerate(raw.get('questions',[])[:3],1):
        text=concise_fact(q.get('question'),64) if isinstance(q,dict) else ''
        if text:questions.append({'label':'购买问答原文','value':text,'evidenceIds':[f'QA_{i:05d}']})
    outcome_map={x.get('label'):x for x in outcomes}
    appearance=outcome_map.get('花型与空间呈现',{});touch=outcome_map.get('触感与睡感',{})
    positive_refs=_uniq((appearance.get('evidenceIds') or [])+(touch.get('evidenceIds') or []))
    actions=[]
    if positive_refs:actions.append({'label':'保留','value':'保留评论已验证的花型呈现与触感表达','note':'按本次有效评论统计','evidenceIds':positive_refs})
    if issue:actions.append({'label':'修正','value':issue['action'],'note':f"评论明确出现{issue['label']}",'evidenceIds':[neg_id]})
    actions.append({'label':'下一步','value':'进入样品验证；同步核对成本、家纺验收项与页面一致性','note':'当前证据支持样品和页面校准','evidenceIds':[x for x in (size_id,neg_id) if x]})
    verdict='保留已验证体验，优先核对尺寸、成本和页面一致性'
    public=_txt(base.get('publicReviewCount')).strip()
    sample=f"已采有效评论 {base.get('reviewCount',0)}"+(f" / 页面公开 {public}" if public else '')
    sample+='；评论采集已确认完整' if base.get('reviewCollectionComplete') else '；评论采集未确认完整'
    return {'chapterTitle':'商品分析结论','verdict':verdict,'facts':facts[:4],'outcomes':outcomes[:5],'actions':actions,'checks':checks[:3],'questions':questions[:2],'sampleNote':sample,
            'decisionBoundary':{'supported':'商品拆解、样品验证、规格校准、页面信息修正','excluded':'生产规模、利润、转化、市场容量','required':'完整评论、流量转化、退款售后、成本毛利'}}

def _core_solution_ok(exp):
    if not isinstance(exp,dict):return False
    checks=(
      bool(_txt((exp.get('reportSummary') or {}).get('title')).strip()),
      bool(_txt((exp.get('reportSummary') or {}).get('verdict')).strip()),
      isinstance((exp.get('ownerOverview') or {}).get('cards'),list) and len((exp.get('ownerOverview') or {}).get('cards'))>=3,
      isinstance((exp.get('productExperience') or {}).get('parameterFacts'),list) and len((exp.get('productExperience') or {}).get('parameterFacts'))>=2,
      isinstance((exp.get('productExperience') or {}).get('gates'),list) and len((exp.get('productExperience') or {}).get('gates'))>=2,
      isinstance((exp.get('newProductPlans') or {}).get('plans'),list) and len((exp.get('newProductPlans') or {}).get('plans'))>=3,
      isinstance((exp.get('validationLoop') or {}).get('rows'),list) and len((exp.get('validationLoop') or {}).get('rows'))>=3,
    )
    return all(checks)

def core_solution_diagnostics(exp):
    exp=exp if isinstance(exp,dict) else {}
    specs=(
      ('reportSummary.title',bool(_txt((exp.get('reportSummary') or {}).get('title')).strip()),1,1),
      ('reportSummary.verdict',bool(_txt((exp.get('reportSummary') or {}).get('verdict')).strip()),1,1),
      ('ownerOverview.cards',isinstance((exp.get('ownerOverview') or {}).get('cards'),list),len((exp.get('ownerOverview') or {}).get('cards') or []),3),
      ('productExperience.parameterFacts',isinstance((exp.get('productExperience') or {}).get('parameterFacts'),list),len((exp.get('productExperience') or {}).get('parameterFacts') or []),2),
      ('productExperience.gates',isinstance((exp.get('productExperience') or {}).get('gates'),list),len((exp.get('productExperience') or {}).get('gates') or []),2),
      ('newProductPlans.plans',isinstance((exp.get('newProductPlans') or {}).get('plans'),list),len((exp.get('newProductPlans') or {}).get('plans') or []),3),
      ('validationLoop.rows',isinstance((exp.get('validationLoop') or {}).get('rows'),list),len((exp.get('validationLoop') or {}).get('rows') or []),3),
    )
    checks=[]
    for field,right_type,actual,minimum in specs:
        ok=bool(right_type and actual>=minimum)
        checks.append({'field':field,'actual':actual,'minimum':minimum,'ok':ok})
    return {'ok':all(x['ok'] for x in checks),'checks':checks,'missing':[x['field'] for x in checks if not x['ok']]}

def repair_core_solution_with_evidence(draft, raw, base=None):
    """Fill only missing core report structure from deterministic, evidence-backed facts."""
    draft=dict(draft or {})
    evidence=build_fallback_experience(raw,base)
    valid_ids={x.get('id') for x in evidence_ledger(normalize(raw)) if x.get('id')}
    scalar_rules=(('reportSummary','title'),('reportSummary','verdict'))
    list_rules=(
      ('ownerOverview','cards',3),
      ('productExperience','parameterFacts',2),('productExperience','gates',2),
      ('newProductPlans','plans',3),('validationLoop','rows',3),
    )
    for section,key in scalar_rules:
        current=dict(draft.get(section) or {})
        source=evidence.get(section) or {}
        if not _txt(current.get(key)).strip():current[key]=source.get(key,'')
        draft[section]=current
    for section,key,minimum in list_rules:
        current=dict(draft.get(section) or {})
        source=evidence.get(section) or {}
        values=_filter_evidence_items(current.get(key),valid_ids)
        source_values=_filter_evidence_items(source.get(key),valid_ids)
        if section=='ownerOverview' and key=='cards' and len(source_values)<minimum:
            for fact in _filter_evidence_items((evidence.get('productExperience') or {}).get('parameterFacts'),valid_ids):
                source_values.append({'label':fact.get('label') or '商品参数','headline':fact.get('value') or fact.get('note') or '已采集','bullets':[fact.get('note')] if fact.get('note') else [],'tone':'normal','evidenceIds':fact.get('evidenceIds') or []})
        for item in source_values:
            if len(values)>=minimum:break
            if isinstance(item,dict) and item not in values:values.append(item)
        current[key]=values;draft[section]=current
    return draft

def build_generic_fallback_experience(raw, base=None):
    raw=normalize(raw);base=base or baseline(raw);route=detect_category(raw);attrs=_attribute_rows(raw);sales=raw.get('sales') or {};issue=_review_issue(raw)
    label=_product_label(raw);review_count=base.get('reviewCount',0);question_count=base.get('questionCount',0);sold=_txt(sales.get('sold')).strip();price=_txt(sales.get('currentPrice')).strip()
    refs=[f'ATTR_{i:04d}' for i in range(1,min(len(attrs),8)+1)];facts=_category_parameter_facts(raw);gates=_category_gates(raw,issue);points=_generic_selling_points(raw,base,issue)
    main_ids=[f'IMG_MAIN_{i:04d}' for i,_ in enumerate((raw.get('images') or {}).get('main',[])[:8],1)]
    visual=[]
    roles=('商品全貌与第一印象','核心卖点与使用场景','规格、款式或选择信息','材质、成分或配置证据','细节、功能或实际效果','服务、合规或补充说明')
    for i,eid in enumerate(main_ids):
        role=roles[min(i,len(roles)-1)]
        visual.append({'label':f'{i+1:02d} / 已核验主图','headline':role,'explanation':'','imageEvidenceId':eid,'frameInfo':'按原图完整展示，识别主体、场景、配色、文字与信息层级','persuasionTask':role,'weakness':'','action':'确保本图承担独立购买确认任务，并与参数和SKU一致','evidenceIds':[eid]})
    owner=[
      {'label':'商品定义','headline':label,'bullets':[f"自动识别为{route['label']}"],'tone':'normal','evidenceIds':['P_TITLE'] if _valid_title((raw.get('product') or {}).get('title')) else refs[:1]},
      {'label':'公开销售事实','headline':' · '.join(x for x in (f'¥{price}' if price else '',f'销量 {sold}' if sold else '') if x) or '价格或销量未采集','bullets':[],'tone':'normal','evidenceIds':[x for x in ('S_CURRENTPRICE' if price else '','S_SOLD' if sold else '') if x]},
      {'label':'当前用户信号','headline':f'有效评论 {review_count} 条','bullets':[x.get('topic') for x in (base.get('topics') or [])[:3]],'tone':'good','evidenceIds':[f'REV_{i:06d}' for i in range(1,min(review_count,3)+1)]},
      {'label':'当前明确问题','headline':issue.get('label') if issue else '评论未形成明确问题','bullets':[concise_fact(issue.get('text'),58)] if issue else [],'tone':'risk' if issue else 'normal','evidenceIds':[issue.get('evidenceId')] if issue else refs[:1]},
    ]
    stages=[]
    for i,topic in enumerate((base.get('topics') or [])[:3],1):
        examples=topic.get('examples') or [];evidence=[]
        for j,review in enumerate(raw.get('reviews',[]) or [],1):
            text=_txt(review.get('content'))
            if any(k in text for k in TOPICS.get(topic.get('topic'),[])):evidence.append(f'REV_{j:06d}')
        if evidence:stages.append({'key':f'signal{i}','stageNo':f'{i:02d}','label':topic.get('topic'),'headline':f"{topic.get('mentions')} 条评论提及",'userExpectation':'','positiveConfirmation':concise_fact(examples[0],90) if examples else '', 'friction':'','businessImpact':'将该信号对应到具体SKU和页面证据','quotes':[{'type':'评论','text':concise_fact(examples[0],90),'evidenceId':evidence[0]}] if examples else [],'evidenceIds':evidence[:8]})
    if len(stages)<2 and refs:
        for i,fact in enumerate(facts[:2],len(stages)+1):stages.append({'key':f'fact{i}','stageNo':f'{i:02d}','label':fact.get('label'),'headline':fact.get('value'),'userExpectation':'看清商品关键信息','positiveConfirmation':'页面参数已采集','friction':'','businessImpact':'与SKU和详情页保持一致','quotes':[],'evidenceIds':fact.get('evidenceIds') or []})
    plan_specs=[{'label':x.get('label'),'value':x.get('value')} for x in facts[:6]]
    exp={
      'reportSummary':{'title':f'{label}产品分析报告','subtitle':f'{route["label"]} · 有效评论 {review_count} 条 · 参数 {len(attrs)} 项','verdict':'保留有证据的商品价值，先修正明确问题，再形成差异化新品','verdictDetail':'页面事实、图片、评论和问答分来源呈现。','monitorSummary':''},
      'platformOverview':_generic_platform_overview(raw,base),
      'ownerOverview':{'chapterTitle':f'{route["label"]}商品事实、用户信号与下一款动作','chapterDeck':'','thesis':'','sampleSummary':f'有效评论 {review_count} 条，购买问答 {question_count} 条','cards':owner},
      'visualCommerce':{'chapterTitle':'主图逐张承担不同购买确认任务','chapterDeck':'','items':visual},
      'customerExperience':{'chapterTitle':'当前评论只形成用户信号，不扩大为普遍结论','chapterDeck':'','stats':[{'label':'有效评论','value':str(review_count)},{'label':'购买问答','value':str(question_count)},{'label':'有效参数','value':str(len(attrs))}],'journeyTitle':'评论体验、问题与购买顾虑分开呈现','journeyDeck':'','stages':stages,'buyerEvidence':{'title':'评论原图与对应评价','items':_buyer_evidence(raw)},'signals':{'title':'当前用户信号','positive':[],'questions':[],'risks':[{'label':issue.get('label'),'countOrNote':'明确评论文本','evidenceIds':[issue.get('evidenceId')]}] if issue else []}},
      'productExperience':{'chapterTitle':f'{route["label"]}动态产品定义','chapterDeck':'','parameterFacts':facts,'thesis':'','thesisDetail':'','gates':gates},
      'newProductPlans':{'chapterTitle':'稳健优化、设计升级与差异探索','chapterDeck':'','plans':[{'type':'稳健优化款','name':f'{label}优化款','positioning':'保留已确认价值，优先修正评论问题与页面信息冲突','sellingPoints':points,'specs':plan_specs,'manufacturingGate':{'title':'产品验证','content':'按当前类目关键参数核对样品、SKU、标签、包装和页面'},'visualCommerce':{'title':'主图与详情','content':'首图确认商品全貌，后续图片依次证明规格、材质/成分/配置、使用效果与服务'},'evidenceIds':_uniq((refs[:5])+([issue.get('evidenceId')] if issue else []))}], 'commercialSummary':{'title':'从当前商品保留什么','thesis':'只复用有证据的体验和信息结构','keep':points[0].get('slogan') if points else '页面已采参数','fix':issue.get('label') if issue else '页面与商品一致性','prove':'样品、SKU、参数、图片和评论可以相互核对'}},
      'validationLoop':{'chapterTitle':f'{route["label"]}新品验证闭环','chapterDeck':'','rows':_category_validation_rows(raw)}
    }
    return _apply_selling_points(exp,raw,base)

def build_fallback_experience(raw, base=None):
    if detect_category(raw)['key']!='home_textile':
        return build_generic_fallback_experience(raw,base)
    raw=normalize(raw);base=base or baseline(raw);attrs=_attribute_rows(raw);sales=raw.get('sales',{});label=_product_label(raw)
    sold=_txt(sales.get('sold') or sales.get('cumulativeSales')).strip();price=_txt(sales.get('currentPrice')).strip()
    topics=base.get('topics',[]) or []; top=topics[:3];review_outcomes=_review_outcomes(raw)
    outcome_counts={x.get('label'):len(x.get('evidenceIds') or []) for x in review_outcomes}
    topic_cards=[]
    for t in top:
        topic_cards.append({'label':t.get('topic'),'headline':f"{t.get('mentions',0)} 条评论提及",'explanation':'','bullets':[],'tone':'good','evidenceIds':[]})
    issue=_review_issue(raw);neg_text=issue.get('text','');neg_id=issue.get('evidenceId','')
    size_attr,size_attr_id=_find_attr(attrs,('适用床尺寸','床品尺寸','尺寸'))
    material,material_id=_find_attr(attrs,('床单面料材质','被面材质','材质','成分'))
    thread,thread_id=_find_attr(attrs,('面料支数',))
    pieces,pieces_id=_find_attr(attrs,('件数','套件组成'))
    craft,craft_id=_find_attr(attrs,('床品工艺','织造工艺','工艺'))
    grade,grade_id=_find_attr(attrs,('产品等级','安全类别','执行标准'))
    attr_refs=[x for x in (material_id,thread_id,pieces_id,size_attr_id,craft_id,grade_id) if x]
    top_text='、'.join(f"{x.get('label')} {len(x.get('evidenceIds') or [])}/{base.get('reviewCount',0)}" for x in review_outcomes[:3]) or '当前评论未形成可统计结果'
    review_count=base.get('reviewCount',0);question_count=base.get('questionCount',0)
    customer_results=[]
    if outcome_counts.get('触感与睡感'):customer_results.append(f"{outcome_counts['触感与睡感']} 条确认触感")
    if outcome_counts.get('花型与空间呈现'):customer_results.append(f"{outcome_counts['花型与空间呈现']} 条确认花型")
    sales_bits=[]
    if sold:sales_bits.append(f'公开销量 {sold}')
    if price:sales_bits.append(f'采集价 ¥{price}')
    sales_bits.extend([f'有效评论 {review_count} 条',f'购买问答 {question_count} 条'])
    owner_cards=[
      {'label':'销售事实','headline':' · '.join(sales_bits[:2]) or '页面未展示销量与价格','bullets':sales_bits[2:],'tone':'normal','evidenceIds':[x for x in ('S_SOLD' if sold else '', 'S_CURRENTPRICE' if price else '') if x]},
      {'label':'评论已验证体验','headline':top_text,'bullets':['按本次实际评论文本统计'],'tone':'good','evidenceIds':[]},
      {'label':'当前明确问题','headline':(f"1 条评论明确出现{issue['label']}" if issue else '现有评论未出现规则可识别的明确问题'),'bullets':([concise_fact(neg_text,52)] if neg_text else []),'tone':'risk' if neg_id else 'normal','evidenceIds':[neg_id] if neg_id else []},
      {'label':'参数与信任','headline':f'已采 {len(attrs)} 项有效参数','bullets':[f"{x.get('name')}：{x.get('value')}" for x in attrs[:2]],'tone':'normal','evidenceIds':attr_refs[:3]},
      {'label':'下一款怎么开','headline':('保留已验证体验，先修正'+issue['label'] if issue else '保留已验证体验，进入家纺样品验收'),'bullets':['BOM、样品、标签、包装与页面口径必须一致'],'tone':'good','evidenceIds':([neg_id] if neg_id else [])+attr_refs[:2]},
    ]
    promotions=[x for x in raw.get('promotions',[]) or [] if isinstance(x,dict) and _txt(x.get('text')).strip()]
    if promotions:
        owner_cards.insert(1,{'label':'页面活动','headline':concise_fact(promotions[0].get('text'),46),'bullets':['报告只记录采集时页面展示内容'],'tone':'normal','evidenceIds':['PROMO_0001']})
    main_ids=[]
    for i,url in enumerate((raw.get('images',{}) or {}).get('main',[]) or [],1):
        if re.search(r'(?:avatar|sns_logo|shopmanager|tps-\d{1,3}-\d{1,3}|logo)',_txt(url),re.I):continue
        main_ids.append(f'IMG_MAIN_{i:04d}')
        if len(main_ids)>=3:break
    visual_items=[]
    visual_defs=[
      ('01 / 已核验主图','首图：看清商品全貌','主体、套件形态、花型面积与页面文字必须同屏核对','保留原图比例，优先检查商品是否完整、文案是否遮挡主体'),
      ('02 / 已核验主图','辅图：补充花型与搭配','观察配色、纹样密度、床品铺陈方式和儿童房场景信息','把可见花型、配色和套件组成拆成可复用拍摄清单'),
      ('03 / 已核验主图','辅图：承接规格信息','核对床型、件数、尺寸和页面参数是否一致','图上出现的规格表达必须与 SKU、参数表和详情页保持一致')
    ]
    for eid,defs in zip(main_ids,visual_defs):
        item_label,headline,task,action=defs
        visual_items.append({'label':item_label,'headline':headline,'explanation':'','imageEvidenceId':eid,'frameInfo':'按原图完整展示，重点看主体、花型、配色、场景、文案层级','persuasionTask':task,'weakness':'','action':action,'evidenceIds':[eid]})
    detail_id=''
    for i,url in enumerate((raw.get('images',{}) or {}).get('detail',[]) or [],1):
        if re.search(r'(?:avatar|sns_logo|shopmanager|tps-\d{1,3}-\d{1,3}|logo)',_txt(url),re.I):continue
        detail_id=f'IMG_DETAIL_{i:04d}';break
    if detail_id:
        visual_items.append({'label':'04 / 已核验详情图','headline':'商品详情页原图','explanation':'','imageEvidenceId':detail_id,'frameInfo':'完整展示','persuasionTask':'来源：商品详情描述容器','weakness':'','action':'图片文字与页面参数表逐项核对','evidenceIds':[detail_id]})
    positive=[]
    for outcome in review_outcomes[:5]:
        count=len(outcome.get('evidenceIds') or [])
        positive.append({'label':f"{outcome.get('label')}：{count}/{review_count} 条验证",'countOrNote':str(count),'evidenceIds':outcome.get('evidenceIds') or []})
    first_positive=(top[0] if top else {'topic':'有效评论','mentions':review_count})
    quote1,qid1=_review_ref(raw,lambda text:any(k in text for k in ('好看','漂亮','颜色','图案','花色')))
    quote2,qid2=_review_ref(raw,lambda text:any(k in text for k in ('舒服','柔软','亲肤','手感')))
    stages=[
      {'key':'see','stageNo':'01','label':'看到商品','headline':f"{first_positive.get('topic')}是当前最强评论信号",'userExpectation':'看清商品与花型','positiveConfirmation':f"{first_positive.get('mentions',0)} 条有效评论提及{first_positive.get('topic')}",'friction':'','businessImpact':'首图完整展示商品与花型','quotes':[{'type':'评论','text':quote1,'evidenceId':qid1}] if quote1 else [],'evidenceIds':[qid1] if qid1 else []},
      {'key':'choose','stageNo':'02','label':'选择规格','headline':'规格必须对应实际床型与套件 BOM','userExpectation':'一次看清床型、件数和各部件尺寸','positiveConfirmation':_txt(size_attr.get('value')) if size_attr else '','friction':(f"1 条评论明确出现{issue['label']}" if issue else ''),'businessImpact':'页面、样品与包装统一规格口径','quotes':[{'type':'评论','text':neg_text,'evidenceId':neg_id}] if neg_id else [],'evidenceIds':[x for x in (size_attr_id,neg_id) if x]},
      {'key':'use','stageNo':'03','label':'实际使用','headline':'触感反馈已形成明确正向信号','userExpectation':'柔软、亲肤、睡感舒适','positiveConfirmation':next((f"{x.get('mentions')} 条有效评论提及{x.get('topic')}" for x in topics if x.get('topic')=='面料/触感'),''),'friction':'','businessImpact':'材质页参数与评论原话并列证明','quotes':[{'type':'评论','text':quote2,'evidenceId':qid2}] if quote2 else [],'evidenceIds':[qid2] if qid2 else []},
    ]
    param_facts=_home_textile_parameter_facts(raw)
    material_value=_txt(material.get('value')) if material else ''
    size_value=_txt(size_attr.get('value')) if size_attr else ''
    plan_specs=[]
    if material_value:plan_specs.append({'label':'材质','value':material_value})
    if thread:plan_specs.append({'label':'面料支数','value':thread.get('value')})
    if size_value:plan_specs.append({'label':'SKU','value':size_value})
    if craft:plan_specs.append({'label':'工艺','value':craft.get('value')})
    return _apply_selling_points({
      'reportSummary':{'title':f'{label}产品分析报告','subtitle':'；'.join(sales_bits),'verdict':'保留已验证体验，优先核对尺寸、成本和页面一致性','verdictDetail':'只使用已采页面参数与实际评论。','monitorSummary':''},
      'platformOverview':build_platform_overview(raw,base),
      'ownerOverview':{'chapterTitle':f"{top_text}，{issue['label']+'需先修正' if issue else '进入家纺样品验收'}",'chapterDeck':'','thesis':'','sampleSummary':f'有效评论 {review_count} 条，购买问答 {question_count} 条','cards':owner_cards[:6]},
      'visualCommerce':{'chapterTitle':'完整展示商品，再依次解释花型、材质与规格','chapterDeck':'','items':visual_items},
      'customerExperience':{'chapterTitle':'，'.join(customer_results)+(f"；1 条明确出现{issue['label']}" if issue else ''),'chapterDeck':'','stats':[{'label':'有效评论','value':str(review_count),'note':''},{'label':'购买问答','value':str(question_count),'note':''},{'label':'有效参数','value':str(len(attrs)),'note':''}], 'journeyTitle':'从看到商品到首洗：只呈现评论已验证结果','journeyDeck':'','stages':stages,'buyerEvidence':{'title':'评论原图与对应评价','items':_buyer_evidence(raw)},'signals':{'title':'评论结果与购买前关注点','positive':positive,'questions':[{'label':f'采集到 {question_count} 条购买问答','countOrNote':str(question_count),'evidenceIds':[]} ] if question_count else [],'risks':[{'label':concise_fact(neg_text,44),'countOrNote':'1 条明确文本','evidenceIds':[neg_id]}] if neg_id else []}},
      'productExperience':{'chapterTitle':'家纺开品底板：BOM、材质、尺寸与首洗逐项过门','chapterDeck':'','parameterFacts':param_facts,'thesis':'','thesisDetail':'','gates':_home_textile_gates(raw,issue)},
      'newProductPlans':{'chapterTitle':('只做一个方向：保留已验证体验，先修正'+issue['label'] if issue else '只做一个方向：保留已验证体验，先完成家纺验收'),'chapterDeck':'','plans':[{'type':'主销款','name':f'{label}规格校准款','positioning':('沿用现有评论确认的花型与触感表达，优先修正'+issue['label'] if issue else '沿用现有评论确认的体验表达，先完成家纺样品验收'),'sellingPoints':_derive_next_selling_points(raw,base,issue),'specs':plan_specs,'manufacturingGate':{'title':'制造闸门','content':'核对套件 BOM、材质标签与各床型铺装；完成首洗、缝制填充、气味包装验收'},'visualCommerce':{'title':'首图与商详','content':'首图完整展示商品；后续图依次说明花型材质、套件清单、床型尺寸和洗护证据'},'evidenceIds':([neg_id] if neg_id else [])+attr_refs}], 'commercialSummary':{'title':'从当前商品保留什么','thesis':'只复用评论已确认的体验','keep':top_text,'fix':(issue['label'] if issue else '家纺样品与页面一致性'),'prove':'BOM、样品、标签、包装、页面五处一致'}},
      'validationLoop':{'chapterTitle':'六道家纺验收门决定上架、返修或停止','chapterDeck':'','rows':_home_textile_validation_rows(raw)}
    }, raw, base)

def concise_fact(value,limit=48):
    text=re.sub(r'\s+',' ',_txt(value)).strip()
    return text if len(text)<=limit else text[:limit].rstrip('，。； ')+'…'

REPORT_LANGUAGE_REPLACEMENTS=(
  ('客户为什么购买','评论已验证体验'),('用户为什么购买','评论已验证体验'),('用户为什么买','评论已验证体验'),
  ('成交原因','现有证据'),('决定成交','影响页面理解'),('推动选择','提供选择信息'),
  ('提升转化','验证页面效果'),('降低退货','验证售后结果'),('省心型大众爆款','当前高销量商品'),('爆款','当前商品'),
  ('建议立项验证','进入样品验证'),('有条件立项验证','先补齐验证项'),('暂不建议立项','暂停新增样品动作'),
  ('立项判断','产品分析结论'),('立项','样品验证'),('不成立','需修正'),('成立','已确认'),('诊断报告','产品分析报告'),('商品诊断','商品分析'),
  ('经营结论','产品分析结论'),('经营判断','产品分析结论'),('经营总览','产品摘要'),('老板决策总览','产品摘要'),
  ('经营与开品报告','产品分析报告'),('商品经营结论','商品分析结论'),('商品经营','商品产品'),
  ('建议进入样品验证','进入样品验证'),('再做量产决策','再安排生产测算'),('不做量产决策','不输出生产规模判断'),
  ('量产前','批量上架前'),('量产判断','生产规模判断'),('量产规模','生产规模'),('量产测算','生产测算'),
  ('有条件样品验证','样品校准分析'),
)

def _sanitize_report_language(value):
    if isinstance(value,dict):return {k:_sanitize_report_language(v) for k,v in value.items()}
    if isinstance(value,list):return [_sanitize_report_language(x) for x in value]
    if not isinstance(value,str):return value
    for source,target in REPORT_LANGUAGE_REPLACEMENTS:value=value.replace(source,target)
    return value

def _separate_qa_signals(exp):
    customer=exp.get('customerExperience') or {};signals=customer.get('signals') or {}
    questions=list(signals.get('questions') or []);risks=[]
    for item in signals.get('risks') or []:
        if not isinstance(item,dict):continue
        refs=[x for x in item.get('evidenceIds',[]) or [] if isinstance(x,str)]
        if refs and all(x.startswith('QA_') for x in refs):
            moved=dict(item);moved['label']='购买前关注：'+_txt(item.get('label')).removeprefix('购买前关注：')
            questions.append(moved)
        else:risks.append(item)
    signals['questions']=questions;signals['risks']=risks;customer['signals']=signals
    for stage in customer.get('stages') or []:
        if not isinstance(stage,dict):continue
        refs=[x for x in stage.get('evidenceIds',[]) or [] if isinstance(x,str)]
        quotes=[x for x in stage.get('quotes',[]) or [] if isinstance(x,dict)]
        only_questions=bool(refs) and all(x.startswith('QA_') for x in refs)
        if only_questions or (quotes and all(_txt(x.get('type')) in ('问答','购买问答') for x in quotes)):
            if stage.get('friction') and not stage.get('userExpectation'):stage['userExpectation']=stage['friction']
            stage['friction']=''
    return exp

def _filter_evidence_items(values, valid_ids, image=False):
    out=[]
    for item in values or []:
        if not isinstance(item,dict):continue
        refs=[x for x in item.get('evidenceIds',[]) or [] if x in valid_ids]
        image_id=item.get('imageEvidenceId') if image else ''
        if image_id in valid_ids and image_id not in refs:refs.append(image_id)
        if not refs:continue
        clean=dict(item);clean['evidenceIds']=refs;out.append(clean)
    return out

VISUAL_EXCLUDED_TERMS=(
    '品牌','商标','专利','授权','认证','证书','奖项','背书',
    '包邮','物流','快递','运费','价格','销量','优惠','折扣','促销','红包',
    '二维码','防伪','官方','店铺','客服','售后','信任服务','品牌服务',
    '条形码','商品编码','货号','发明人','正宗','产品等级','执行标准','安全类别'
)

MAIN_VISUAL_TASKS=(
    {'contentKey':'product_overview','role':'商品全貌','signals':('主体完整','整体组成'),'keywords':('件数','套件','组合','商品','产品'),'nextAction':'先让用户看清商品主体与整体组成'},
    {'contentKey':'usage_scene','role':'使用场景','signals':('真实使用状态','空间适配'),'keywords':('场景','适用','人群','床型','季节','用途'),'nextAction':'承接使用场景，说明产品适合怎么用'},
    {'contentKey':'material_touch','role':'材质触感','signals':('材质近景','触感细节'),'keywords':('材质','面料','成分','支数','密度','克重','填充'),'nextAction':'用近景和参数把材质触感讲具体'},
    {'contentKey':'structure_function','role':'结构功能','signals':('结构细节','使用动作'),'keywords':('结构','工艺','功能','做工','细节','拉链','接口'),'nextAction':'把结构、工艺或功能的实现方式拍清楚'},
    {'contentKey':'spec_choice','role':'规格选择','signals':('尺寸清楚','选择路径'),'keywords':('尺寸','规格','件数','颜色','款式','SKU','适配'),'nextAction':'最后承接尺寸、件数和选择方式'},
)

DETAIL_VISUAL_TASKS=(
    {'contentKey':'scene_problem','role':'场景证明','signals':('使用问题','真实场景'),'keywords':('场景','适用','人群','用途','问题'),'nextAction':'先用真实场景回答产品解决什么使用问题'},
    {'contentKey':'material_proof','role':'材质证明','signals':('材质参数','表面细节'),'keywords':('材质','面料','成分','支数','密度','克重','填充'),'nextAction':'接着证明材质、成分或填充信息'},
    {'contentKey':'structure_proof','role':'结构工艺','signals':('结构拆解','工艺细节'),'keywords':('结构','工艺','做工','细节','缝制','接口','拉链'),'nextAction':'继续证明结构、工艺和关键细节'},
    {'contentKey':'function_proof','role':'功能表现','signals':('使用动作','效果边界'),'keywords':('功能','性能','使用','透气','防护','收纳','连接'),'nextAction':'用使用动作说明功能表现，不扩大功效'},
    {'contentKey':'spec_adaptation','role':'规格适配','signals':('尺寸对照','套件清单'),'keywords':('规格','尺寸','件数','套件','SKU','适配','颜色','款式'),'nextAction':'单独列清尺寸、件数、款式与适配关系'},
    {'contentKey':'care_durability','role':'使用维护','signals':('洗护方式','耐用检查'),'keywords':('洗护','洗涤','护理','耐用','首洗','清洁','保存'),'nextAction':'最后说明洗护、耐用或长期使用注意事项'},
    {'contentKey':'material_closeup','role':'材质近观','signals':('纤维纹理','触感近景'),'keywords':('材质','面料','成分','纤维','触感'),'nextAction':'补充面料纹理与触感的微观证明'},
    {'contentKey':'craft_closeup','role':'工艺近观','signals':('走线细节','工艺局部'),'keywords':('工艺','缝制','绗缝','做工','细节'),'nextAction':'补充走线、接口或工艺局部的清晰证明'},
    {'contentKey':'function_scenario','role':'功能场景','signals':('功能动作','使用结果'),'keywords':('功能','使用','性能','保暖','透气','抗菌'),'nextAction':'在真实使用动作中补充功能表现'},
    {'contentKey':'size_compare','role':'尺寸对照','signals':('尺寸标注','实物对照'),'keywords':('尺寸','规格','床型','长度','宽度'),'nextAction':'用实物与标注对照减少规格误解'},
    {'contentKey':'set_inventory','role':'套件清单','signals':('部件清楚','组合关系'),'keywords':('件数','套件','组合','配件','被套'),'nextAction':'单独说清套件包含什么及组合关系'},
    {'contentKey':'color_selection','role':'款式选择','signals':('颜色对比','款式区分'),'keywords':('颜色','配色','花型','款式','SKU'),'nextAction':'用同一版式清楚区分可选颜色或款式'},
    {'contentKey':'care_steps','role':'洗护步骤','signals':('洗护提示','操作步骤'),'keywords':('洗护','洗涤','护理','晾晒','保存'),'nextAction':'把洗护步骤和注意事项拆成可执行说明'},
    {'contentKey':'quality_check','role':'耐用核验','signals':('长期使用','品质检查'),'keywords':('耐用','首洗','回弹','起球','褪色'),'nextAction':'补充长期使用和样品核验的观察点'},
    {'contentKey':'purchase_summary','role':'选择总结','signals':('适用边界','购买确认'),'keywords':('适用','人群','场景','规格','选择'),'nextAction':'最后汇总适用人群、场景和选择边界'},
)

def _visual_product_text(value, limit=18, blocked_terms=()):
    """Keep only product-facing phrases; trust and transaction metadata stay outside the visual chain."""
    if isinstance(value,list):
        parts=[]
        for item in value:
            parts.extend(_visual_product_text(item,limit,blocked_terms))
        return _uniq(parts)
    if isinstance(value,dict):
        for key in ('visualSignals','signal','statement','headline','value','label','topic','action','consumerValue','businessMeaning'):
            if value.get(key):
                return _visual_product_text(value.get(key),limit,blocked_terms)
        return []
    text=re.sub(r'\s+',' ',_txt(value)).strip(' ，,。；;')
    if not text:return []
    pieces=re.split(r'[；;。！？!?，,、|/]+',text)
    out=[]
    for piece in pieces:
        piece=re.sub(r'\s+',' ',piece).strip(' ：:')
        if not piece or any(term in piece for term in VISUAL_EXCLUDED_TERMS) or any(term and term in piece for term in blocked_terms):continue
        if piece not in out:out.append(piece[:limit])
    return out

def _visual_refs(item, valid_ids):
    refs=[]
    if isinstance(item,dict):
        refs.extend(x for x in item.get('evidenceIds',[]) or [] if x in valid_ids)
        for key in ('imageEvidenceId','representativeImageId'):
            if item.get(key) in valid_ids:refs.append(item.get(key))
        refs.extend(x for x in item.get('imageEvidenceIds',[]) or [] if x in valid_ids)
    return _uniq(refs)

def _visual_fact_signals(raw, keywords, limit=2, blocked_terms=()):
    signals=[]
    for item in _attribute_rows(raw):
        name=_txt(item.get('name')); value=_txt(item.get('value'))
        if any(word in name for word in keywords):
            signals.extend(_visual_product_text(f'{name}：{value}',18,blocked_terms))
        if len(signals)>=limit:break
    return _uniq(signals)[:limit]

def _visual_image_ids(raw, group):
    return [f'IMG_{group.upper()}_{i:04d}' for i,_ in enumerate((raw.get('images') or {}).get(group,[]) or [],1)]

def _visual_identity_terms(raw):
    terms=[]
    product=raw.get('product') or {}
    for value in (_txt(product.get('brand')),):
        if len(value.strip())>=2:terms.append(value.strip())
    for item in _attribute_rows(raw):
        name=_txt(item.get('name'))
        value=_txt(item.get('value')).strip()
        if any(key in name for key in ('品牌','商标')) and len(value)>=2:
            terms.append(value)
    return _uniq(terms)

def _visual_signal_matches(signal, keywords):
    return any(keyword in signal for keyword in keywords)

def _canonical_visual_items(raw, items, tasks, valid_ids, plan_points=None, blocked_terms=()):
    """Give every visual asset one job and a stable handoff to the next job."""
    source=[x for x in items or [] if isinstance(x,dict)]
    image_ids=_visual_image_ids(raw,'main' if tasks is MAIN_VISUAL_TASKS else 'detail')
    count=min(len(tasks),max(len(source),len(image_ids)))
    if not count:return []
    plan_signals=[]
    for point in plan_points or []:
        if isinstance(point,dict):
            plan_signals.extend(_visual_product_text(point.get('slogan') or point.get('consumerValue')))
    result=[]
    used_sources=set()
    for index in range(count):
        task=tasks[index]
        eid=image_ids[index] if index<len(image_ids) else ''
        src=None
        if eid:
            src=next((x for x in source if x.get('imageEvidenceId')==eid or x.get('representativeImageId')==eid),None)
        if src is None:
            src=next((x for i,x in enumerate(source) if i not in used_sources),None)
        if src is not None:used_sources.add(source.index(src))
        refs=_visual_refs(src,valid_ids) if src else []
        if eid in valid_ids and eid not in refs:refs.append(eid)
        if not refs:continue
        signals=_visual_product_text(src.get('visualSignals') if src else [],18,blocked_terms)
        signals=[x for x in signals if _visual_signal_matches(x,task['keywords'])]
        if not signals and src:
            signals=_visual_product_text(src.get('message') or src.get('observation') or src.get('businessMeaning'),18,blocked_terms)
            signals=[x for x in signals if _visual_signal_matches(x,task['keywords'])]
        fact_signals=_visual_fact_signals(raw,task['keywords'],2,blocked_terms)
        task_plan_signals=[x for x in plan_signals if _visual_signal_matches(x,task['keywords'])]
        signals=_uniq(signals+fact_signals+task_plan_signals)[:4]
        if not signals:signals=list(task['signals'])
        result.append({
          'contentKey':task['contentKey'],'imageEvidenceId':eid or next((x for x in refs if x.startswith('IMG_')),refs[0]),
          'imageRole':task['role'],'visualSignals':signals[:4],
          'businessMeaning':f"本图只承担{task['role']}信息，不与其他图片重复",
          'nextAction':task['nextAction'],'evidenceIds':_uniq(refs)
        })
    return result

def _normalize_visual_continuity(exp, raw, valid_ids):
    """Normalize main/detail responsibilities after model output and build the page handoff."""
    exp=dict(exp or {})
    plans=((exp.get('newProductPlans') or {}).get('plans') or [])
    plan_points=plans[0].get('sellingPoints') if plans and isinstance(plans[0],dict) else []
    blocked_terms=_visual_identity_terms(raw)
    visual=exp.get('visualCommerce') or {}
    detail=exp.get('detailCommerce') or {}
    main=_canonical_visual_items(raw,visual.get('items'),MAIN_VISUAL_TASKS,valid_ids,plan_points,blocked_terms)
    groups=_canonical_visual_items(raw,detail.get('contentGroups'),DETAIL_VISUAL_TASKS,valid_ids,plan_points,blocked_terms)
    visual['items']=main
    visual['professionalOpinion']='主图先让用户看懂商品、场景和选择入口，每张图只承担一个购买确认任务。'
    detail['contentGroups']=[{
      'contentKey':item.get('contentKey'),'type':item.get('role'),'representativeImageId':item.get('imageEvidenceId'),
      'visualSignals':item.get('visualSignals'),'businessMeaning':item.get('businessMeaning'),
      'nextAction':item.get('nextAction'),'evidenceIds':item.get('evidenceIds')
    } for item in groups]
    detail['professionalOpinion']='详情按场景、材质、结构、功能、规格和维护顺序连续证明产品，不重复主图已经讲清的内容。'
    detail['pageSequence']=[{
      'order':index+1,'contentKey':item.get('contentKey'),'mainImageRole':main[min(index,len(main)-1)].get('imageRole') if main else '主图信息',
      'detailRole':item.get('role'),'handoff':f"主图先提出{item.get('role')}，详情继续给出可核对证明"
    } for index,item in enumerate(DETAIL_VISUAL_TASKS[:len(groups)])]
    claims=[]
    for index,item in enumerate(DETAIL_VISUAL_TASKS[:min(len(main),len(groups))]):
        main_item=main[index];detail_item=groups[index]
        claims.append({
          'claim':item['role'],'mainStatus':'expressed','detailStatus':'proven',
          'reviewStatus':'partial','nextAction':item['nextAction'],
          'evidenceIds':_uniq((main_item.get('evidenceIds') or [])+(detail_item.get('evidenceIds') or []))
        })
    exp['visualCommerce']=visual;exp['detailCommerce']=detail
    if claims:exp['expressionContinuity']={'coreClaims':claims}
    for plan in plans:
        if not isinstance(plan,dict):continue
        page_action=_visual_product_text(plan.get('pageAction'),18,blocked_terms)
        if not page_action or any(term in _txt(plan.get('pageAction')) for term in VISUAL_EXCLUDED_TERMS):
            plan['pageAction']='主图展示商品全貌与场景，详情依次证明材质、结构、功能和规格'
        else:
            plan['pageAction']='；'.join(page_action[:2])
        points=plan.get('sellingPoints')
        if isinstance(points,list):
            plan['sellingPoints']=[p for p in points if isinstance(p,dict) and _visual_product_text(p.get('slogan') or p.get('consumerValue'),18,blocked_terms)]
    return exp

def _evidence_backed_solution(exp, valid_ids):
    exp=dict(exp or {})
    owner=exp.get('ownerOverview') or {};owner['cards']=_filter_evidence_items(owner.get('cards'),valid_ids);exp['ownerOverview']=owner
    visual=exp.get('visualCommerce') or {};visual['items']=_filter_evidence_items(visual.get('items'),valid_ids,True);exp['visualCommerce']=visual
    detail=exp.get('detailCommerce') or {}
    groups=[]
    for item in detail.get('contentGroups') or []:
        if not isinstance(item,dict):continue
        clean=dict(item);refs=_visual_refs(item,valid_ids)
        if refs:
            clean['evidenceIds']=refs;groups.append(clean)
    detail['contentGroups']=groups;exp['detailCommerce']=detail
    customer=exp.get('customerExperience') or {};customer['stages']=_filter_evidence_items(customer.get('stages'),valid_ids)
    signals=customer.get('signals') or {}
    for key in ('positive','questions','risks'):signals[key]=_filter_evidence_items(signals.get(key),valid_ids)
    customer['signals']=signals
    ci=customer.get('consumerInsights') or {}
    ci['experienceSignals']=_filter_evidence_items(ci.get('experienceSignals'),valid_ids)
    ci['productImplications']=_filter_evidence_items(ci.get('productImplications'),valid_ids)
    customer['consumerInsights']=ci;exp['customerExperience']=customer
    product=exp.get('productExperience') or {}
    product['parameterFacts']=_filter_evidence_items(product.get('parameterFacts'),valid_ids)
    product['gates']=_filter_evidence_items(product.get('gates'),valid_ids);exp['productExperience']=product
    plans=exp.get('newProductPlans') or {};plans['plans']=_filter_evidence_items(plans.get('plans'),valid_ids)[:3];exp['newProductPlans']=plans
    validation=exp.get('validationLoop') or {};rows=_filter_evidence_items(validation.get('rows'),valid_ids)
    validation['rows']=[x for x in rows if _txt(x.get('owner')).strip() and _txt(x.get('owner')).strip()!='项目负责人'];exp['validationLoop']=validation
    return exp

def ensure_experience_solution(analysis):
    raw=normalize(analysis.get('facts',{}) or {})
    analysis['facts']=raw
    analysis['baseline']=baseline(raw)
    analysis['evidenceLedger']=evidence_ledger(raw)
    was_fallback=bool((analysis.get('meta') or {}).get('fallbackReport'))
    analysis.setdefault('meta',{})['engineVersion']=ENGINE_VERSION
    route=detect_category(raw)
    analysis['meta']['industryTemplate']=route['key']
    analysis['meta']['categoryLabel']=route['label']
    analysis['meta']['categoryConfidence']=route['confidence']
    analysis['meta']['analysisDimensions']=route['dimensions']
    analysis['meta']['imageSourcePolicy']=(raw.get('images',{}).get('classification',{}) or {}).get('version') or 'legacy-review-only'
    valid_ids={x.get('id') for x in analysis['evidenceLedger'] if x.get('id')}
    exp=_evidence_backed_solution(analysis.get('experienceSolution') or {},valid_ids)
    if not _arr((exp.get('newProductPlans') or {}).get('plans')) and _arr((analysis.get('launchPlans') or {}).get('plans')):
        exp.setdefault('newProductPlans',{})['plans']=_filter_evidence_items((analysis.get('launchPlans') or {}).get('plans'),valid_ids)[:3]
        if (analysis.get('launchPlans') or {}).get('professionalOpinion'):
            exp['newProductPlans']['professionalOpinion']=(analysis.get('launchPlans') or {}).get('professionalOpinion')
    exp=_separate_qa_signals(exp)
    exp=_sanitize_report_language(_apply_selling_points(exp,raw,analysis['baseline']))
    exp=_ensure_three_product_plans(exp,raw,analysis['baseline'])
    # 核心工程模块缺失时，先使用同一批真实证据确定性补齐；不得带着失败审核输出正式报告。
    exp=repair_core_solution_with_evidence(exp,raw,analysis['baseline'])
    exp=_evidence_backed_solution(exp,valid_ids)
    # 最后一轮把主图与详情收敛为连续的信息任务，避免模型把同一卖点复制到多张图。
    exp=_normalize_visual_continuity(exp,raw,valid_ids)
    exp=_evidence_backed_solution(exp,valid_ids)
    analysis['experienceSolution']=exp
    analysis['meta'].pop('fallbackReport',None)
    analysis['meta']['fallbackReport']=False
    if was_fallback:
        analysis['meta']['reportReady']=False
        analysis['meta']['reportBlockedReason']='历史分析标记为兜底结果，本版本拒绝重新渲染为正式报告。'
        return analysis
    validation=core_solution_diagnostics(exp)
    analysis['meta']['reportValidation']=validation
    if not validation['ok']:
        analysis['meta']['reportReady']=False
        analysis['meta']['reportAuditPassed']=False
        analysis['meta']['reportQuality']='blocked'
        analysis['meta']['reportBlockedReason']='报告审核未通过，已停止生成。缺失：'+', '.join(validation['missing'])
        analysis['meta'].pop('reportNotice',None)
        return analysis
    analysis['meta']['reportReady']=True
    analysis['meta']['reportAuditPassed']=True
    analysis['meta']['reportQuality']='passed'
    analysis['meta'].pop('reportBlockedReason',None)
    customer=exp.setdefault('customerExperience',{})
    customer['stats']=[{'label':'有效评论','value':str(analysis['baseline'].get('reviewCount',0))},{'label':'购买问答','value':str(analysis['baseline'].get('questionCount',0))},{'label':'有效参数','value':str(analysis['baseline'].get('attributeCount',0))}]
    customer['buyerEvidence']={'title':'评论原图与对应评价','items':_buyer_evidence(raw)}
    exp.pop('shopperDecision',None)
    plans=exp.setdefault('newProductPlans',{})
    summary=exp.setdefault('reportSummary',{})
    summary['title']=_clean_product_title(re.sub(r'(床品|商品)商品经营',r'\1产品',_txt(summary.get('title'))))
    analysis['experienceSolution']=exp
    return analysis

def evidence_ledger(raw):
    ev=[]
    def add(eid,etype,label,value,source='page',meta=None):
        if value in (None,'',[],{}): return
        ev.append({'id':eid,'type':etype,'label':label,'value':value,'source':source,'meta':meta or {}})
    p=raw.get('product',{}); s=raw.get('sales',{})
    for k,label in [('title','商品标题'),('shop','店铺'),('brand','品牌'),('category','类目'),('itemId','Item ID'),('skuId','SKU ID')]: add('P_'+k.upper(),'product',label,p.get(k),'page')
    for k,label in [('currentPrice','当前采集价格'),('sold','销量公开值'),('cumulativeSales','累计销量'),('monthlySales','月销量'),('ranking','榜单/排名')]: add('S_'+k.upper(),'sales',label,s.get(k),'page')
    for i,x in enumerate(raw.get('monitoring',[])[:30],1): add(f'MON_{i:03d}','monitoring','商品监测数据',x,'monitoring')
    for i,x in enumerate(raw.get('sku',[])[:500],1): add(f'SKU_{i:04d}','sku','SKU',x,'page')
    for i,x in enumerate(raw.get('attributes',[])[:500],1): add(f'ATTR_{i:04d}','attribute','页面属性',x,'page_claim')
    for i,x in enumerate(raw.get('promotions',[])[:300],1): add(f'PROMO_{i:04d}','promotion','促销/服务',x,'page_claim')
    for i,x in enumerate(raw.get('reviews',[]),1): add(f'REV_{i:06d}','review','消费者评价',x,'consumer')
    for i,x in enumerate(raw.get('questions',[])[:2000],1): add(f'QA_{i:05d}','question','购买问答',x,'consumer')
    images=raw.get('images',{}) or {};provenance=images.get('provenance',[]) or []
    for group in IMAGE_GROUPS:
        for i,u in enumerate(images.get(group,[])[:1000],1):
            records=[x for x in provenance if isinstance(x,dict) and x.get('group')==group and x.get('url')==u]
            source=records[0].get('source') if records else ''
            meta={'group':group,'source':source,'classification':(images.get('classification',{}) or {}).get('version')}
            if group=='buyerShow':
                meta['reviewEvidenceIds']=_uniq([x.get('reviewEvidenceId') for x in records if x.get('reviewEvidenceId')])
            add(f'IMG_{group.upper()}_{i:04d}','image',group,u,'verified_image',meta)
    return ev

def baseline(raw):
    rev=raw.get('reviews',[]); buckets={'good':0,'mid':0,'bad':0,'unknown':0}; topic=Counter(); examples=defaultdict(list); sku_topic=defaultdict(Counter)
    for x in rev:
        try:s=float(x.get('rating'))
        except:s=0
        if s>=4:buckets['good']+=1
        elif s==3:buckets['mid']+=1
        elif s>0:buckets['bad']+=1
        else:buckets['unknown']+=1
        c=x['content']; sku=x.get('sku') or '未识别SKU'
        for t,keys in TOPICS.items():
            if any(k in c for k in keys):
                topic[t]+=1; sku_topic[sku][t]+=1
                if len(examples[t])<8: examples[t].append(c[:220])
    collection=raw.get('collection') or {}
    return {'reviewCount':len(rev),'questionCount':len(raw.get('questions',[])),'ratingBuckets':buckets,
            'topics':[{'topic':k,'mentions':v,'sampleRate':round(v/max(1,len(rev)),4),'examples':examples[k][:6]} for k,v in topic.most_common(24)],
            'skuTopicSignals':[{'sku':sku,'topics':[{'topic':k,'mentions':v} for k,v in cnt.most_common(8)]} for sku,cnt in sorted(sku_topic.items(),key=lambda kv:sum(kv[1].values()),reverse=True)[:30]],
            'imageCounts':{k:len(raw.get('images',{}).get(k,[]) or []) for k in ['main','detail','sku','buyerShow','all']},
            'skuCount':len(raw.get('sku',[]) or []),'attributeCount':len(raw.get('attributes',[]) or []),'promotionCount':len(raw.get('promotions',[]) or []),
            'reviewCollectionComplete':bool(collection.get('reviewCollectionComplete')),'reviewStopReason':collection.get('reviewStopReason') or '',
            'publicReviewCount':collection.get('publicReviewCount') or '', 'reviewPagesVisited':collection.get('reviewPagesVisited') or 0}

def compact_evidence(ledger, allowed_types=None, limit=400):
    xs=[x for x in ledger if not allowed_types or x['type'] in allowed_types]
    return xs[:limit]

def require_refs(obj, valid):
    if isinstance(obj,dict):
        if isinstance(obj.get('evidenceIds'),list):
            obj['evidenceIds']=[x for x in obj['evidenceIds'] if x in valid]
            if not obj['evidenceIds']:
                obj['insufficientEvidence']=True
                obj.setdefault('missingEvidence',['未找到可核验引用'])
                try: obj['confidence']=min(float(obj.get('confidence',0.4)),0.45)
                except: obj['confidence']=0.35
        for v in obj.values(): require_refs(v,valid)
    elif isinstance(obj,list):
        for v in obj: require_refs(v,valid)
    return obj

def call(prompt,payload,max_tokens,images=None):
    # 统一模板入口：业务任务只提供 task 文本和变量值，接入其他后端时可替换 registry。
    try:
        task = build_task_prompt(prompt, tuple(payload.keys()) if isinstance(payload, dict) else ('evidence',))
        user = task+'\n'+STYLE_RULES+'\nACTUAL_EVIDENCE:\n'+json.dumps(payload,ensure_ascii=False)
        return chat_json(build_system_prompt(SYS), user, images=images, max_tokens=max_tokens),None
    except Exception as e:return {},str(e)

def batch_review_analysis(raw, valid, progress=lambda *a:None, enabled=True):
    reviews=raw.get('reviews',[])
    if not enabled or not reviews: return {'batches':[],'aggregate':{}}, None
    BATCH=160
    summaries=[]; errors=[]
    total=max(1,(len(reviews)+BATCH-1)//BATCH)
    for bi,start in enumerate(range(0,len(reviews),BATCH),1):
        chunk=[]
        for j,r in enumerate(reviews[start:start+BATCH],start+1):
            chunk.append({'evidenceId':f'REV_{j:06d}','content':r.get('content','')[:520],'appendContent':r.get('appendContent','')[:260],'rating':r.get('rating'),'sku':r.get('sku'),'date':r.get('date')})
        prompt='''任务｜评论批次研究。不要做泛泛总结，只抽取能影响开品的消费者事实。输出：
{"batchFindings":[{"finding":"","type":"purchase_driver|satisfaction|pain|expectation_gap|prepurchase_concern|sku_signal|usage_scene","businessMeaning":"","evidenceIds":[],"confidence":0}],"representativeQuotes":[{"text":"原文","evidenceId":"REV_000001","role":""}]}
要求：每条 finding 最多引用 8 个真实评论ID；不要估算全量次数。'''
        z,e=call(prompt,{'batchIndex':bi,'reviews':chunk},5200)
        if e: errors.append(f'batch {bi}: {e}')
        summaries.append(require_refs(z,valid))
        pct=78+int(8*bi/total)
        progress('review',f'processing {bi}/{total}',pct)
    prompt='''任务｜全量评论商业聚合。输入包含：程序对全部评论的统计 + 每批模型结论。请形成能直接影响商品定义、页面表达与下一款方案的消费者洞察，不得做评论罗列。每一项必须回答‘这说明什么、对商品意味着什么、下一款如何处理’；不得把批次出现次数当全量次数，只有 programStats 中的次数可以写为数量。
输出：
{
"consumerThesis":{"statement":"","businessMeaning":"","evidenceIds":[],"confidence":0},
"purchaseDrivers":[{"driver":"","whatUserIsBuying":"","commercialValue":"","productAction":"","evidenceIds":[],"confidence":0}],
"satisfactionDrivers":[{"driver":"","commercialValue":"","keepAction":"","evidenceIds":[],"confidence":0}],
"painPoints":[{"problem":"","severity":"high|medium|low","businessImpact":"","productAction":"","evidenceIds":[],"confidence":0}],
"expectationGaps":[{"expected":"","actual":"","commercialRisk":"","productOpportunity":"","evidenceIds":[],"confidence":0}],
"prePurchaseConcerns":[{"concern":"","conversionImpact":"","pageAction":"","evidenceIds":[],"confidence":0}],
"skuSignals":[{"sku":"","signal":"","decision":"","evidenceIds":[],"confidence":0}],
"verbatimQuotes":[{"text":"原文","evidenceId":"REV_000001","role":""}]
}'''
    payload={'programStats':baseline(raw),'batchSummaries':summaries}
    z,e=call(prompt,payload,9000)
    if e: errors.append('aggregate: '+e)
    return {'batches':summaries,'aggregate':require_refs(z,valid)}, '; '.join(errors) if errors else None

def question_analysis(raw, valid, enabled=True):
    qs=raw.get('questions',[])
    if not enabled or not qs:return {},None
    payload=[]
    for i,q in enumerate(qs[:1200],1): payload.append({'evidenceId':f'QA_{i:05d}','question':q.get('question','')[:700],'answer':q.get('answer','')[:700]})
    prompt='''任务｜购买前疑虑研究。这里全部是问大家/购买问答，不是差评。回答用户在下单前担心什么、页面哪里没有解释清楚、哪些疑虑被真实买后评论验证。不得把提问本身当产品缺陷。
输出：{"prePurchaseThesis":{"statement":"","commercialMeaning":"","evidenceIds":[],"confidence":0},"concerns":[{"concern":"","whyItBlocksPurchase":"","isProductRiskOrInfoGap":"product_risk|information_gap|unknown","commercialAction":"","evidenceIds":[],"confidence":0}],"validatedByReviews":[{"questionConcern":"","reviewReality":"","decision":"","evidenceIds":[],"confidence":0}],"unansweredQuestions":[{"question":"","pageFix":"","evidenceIds":[],"confidence":0}]}
只引用真实 QA_/REV_ ID。'''
    z,e=call(prompt,{'questions':payload,'reviewStats':baseline(raw)},7200)
    return require_refs(z,valid),e


def _evidence_backed_launch_fallback(raw, valid_ids):
    """V9.2: 只用已有证据构造最小新品方向，避免证据充足时整章为空。"""
    title=_txt((raw.get('product') or {}).get('title')).strip() or '当前商品'
    refs=[]
    for eid in ('P_TITLE','S_CURRENTPRICE','S_SOLD'):
        if eid in valid_ids:refs.append(eid)
    attr_refs=sorted([x for x in valid_ids if x.startswith('ATTR_')])[:4]
    review_refs=sorted([x for x in valid_ids if x.startswith('REV_')])[:2]
    image_refs=sorted([x for x in valid_ids if x.startswith('IMG_MAIN_')])[:2]
    refs=_uniq(refs+attr_refs+review_refs+image_refs)
    if not refs:return {'strategyMode':'mixed','professionalOpinion':'','plans':[]}
    changes=[]
    if attr_refs:changes.append({'action':'优先核对并统一当前商品的规格、材质与页面口径','evidenceIds':attr_refs[:2]})
    if review_refs:changes.append({'action':'把消费者已验证体验与差异反馈转成下一款产品选择说明','evidenceIds':review_refs})
    return {
      'strategyMode':'mixed',
      'professionalOpinion':'保留当前商品已有证据支持的产品逻辑，下一款优先把规格选择、体验表达和页面证明做得更清楚。',
      'plans':[{
        'type':'现有基础优化','name':_clean_product_title(title)+' 优化款',
        'whyThisPlan':'基于当前商品参数、图片与消费者反馈做有限优化，不引入无证据的新材料或市场结论。',
        'visualReferenceImageIds':image_refs,'productChanges':changes,
        'skuStrategy':'先按真实结构化SKU与参数建立选择层级；缺失项待补采后再细化。',
        'mainImagePlan':['首图保持商品全貌与核心场景','后续图片依次解释规格、材质/配置与证明信息'],
        'detailPagePlan':['按主图提出的信息逐项解释和证明','消费者反馈只作为购后体验证据'],
        'validationItems':['样品、SKU、参数、图片与页面文字口径一致'],
        'evidenceIds':refs,'confidence':0.55
      }]
    }

def analyze(raw, progress=lambda *a:None):
    raw=dict(raw or {}); model_available=raw.pop('_model_available',None)
    model_configured=configured(); use_ai=model_configured if model_available is None else bool(model_available and model_configured)
    raw=normalize(raw); base=baseline(raw); ledger=evidence_ledger(raw); valid={x['id'] for x in ledger}
    route=detect_category(raw)
    out={'meta':{'modelConfigured':model_configured,'modelUsed':use_ai,'engineVersion':ENGINE_VERSION,'roleContractVersion':ROLE_CONTRACT_VERSION,'roleContract':ROLE_CONTRACT,'actualOnly':True,'dynamicReport':True,'industryTemplate':route['key'],'categoryLabel':route['label'],'categoryConfidence':route['confidence'],'analysisDimensions':route['dimensions']},'facts':raw,'baseline':base,'evidenceLedger':ledger,'modelErrors':{}}

    progress('evidence','processing',28)
    limitations=[]
    if not base['reviewCollectionComplete']:
        limitations.append('评论采集未确认到达平台可访问末页；当前报告使用本次实际获取的全部评论，不宣称为平台全量。')
    if base['questionCount']==0: limitations.append('未采集到问大家，无法判断下单前主要疑虑。')
    if not raw.get('sales',{}).get('sold') and not raw.get('sales',{}).get('cumulativeSales'): limitations.append('未采集到销量公开值，不能判断经营表现。')
    out['dataQuality']={'grade':'A' if base['reviewCollectionComplete'] and base['reviewCount']>=100 and base['imageCounts']['main']>=3 else 'B+' if base['reviewCount']>=100 else 'B' if base['reviewCount']>=30 else 'C',
      'reviewSample':base['reviewCount'],'reviewCollectionComplete':base['reviewCollectionComplete'],'reviewStopReason':base['reviewStopReason'],
      'publicReviewCount':base['publicReviewCount'],'questionSample':base['questionCount'],'images':base['imageCounts'],'skuCount':base['skuCount'],'attributeCount':base['attributeCount'],'promotionCount':base['promotionCount'],'knownLimitations':limitations}
    progress('evidence','done',32)

    # 先做报告策划：决定这款商品最需要讲清楚什么，而不是先套章节。
    progress('planner','processing',34)
    if use_ai:
        prompt='''任务0｜报告策划。先判断“这款商品最需要被讲清楚的产品问题是什么”，再决定报告内容和顺序。输出：
{
"coreStory":"一句具体产品分析主线",
"decisionQuestion":"运营者最需要看清的一个产品问题",
"primaryQuestions":["3-6个具体问题"],
"sectionPlan":[{"module":"executive|facts|positioning|fashion|main_visual|title_promo|detail|consumer|qa|pain|sku|competition|opportunity|plans|gates","title":"必须是针对该商品的结果型标题","priority":100,"reason":"为什么需要出现"}],
"deemphasize":[{"module":"","reason":"为什么当前证据下不重点展开"}]
}
要求：executive/facts/plans/gates必须出现；其他模块按实际证据和商业价值动态排序。标题禁止使用空泛的“消费者分析”“视觉分析”。'''
        z,e=call(prompt,{'baseline':base,'facts':compact_evidence(ledger,{'product','sales','attribute','promotion','sku'},260)},5000)
        if e: out['modelErrors']['planner']=e
        out['reportPlan']=require_refs(z,valid)
    else: out['reportPlan']={}
    progress('planner','done',38)

    progress('product','processing',40)
    if use_ai:
        prompt='''任务A｜商品价值结构。输出具体到产品定义与运营动作：
{"positioning":{"statement":"","decisionImpact":"","evidenceIds":[],"confidence":0},"valuePillars":[{"name":"","customerValue":"","businessMeaning":"","mustKeep":"","evidenceIds":[],"confidence":0}],"claimVsProof":[{"claim":"","status":"consumer_supported|page_claim_only|conflicted|not_enough_evidence","commercialRisk":"","evidenceIds":[],"confidence":0}],"positioningRisks":[{"risk":"","businessImpact":"","action":"","evidenceIds":[],"confidence":0}]}'''
        z,e=call(prompt,compact_evidence(ledger,{'product','sales','sku','attribute','promotion','review'},320),6200)
        if e:out['modelErrors']['product']=e
        out['productDecision']=require_refs(z,valid)
    else: out['productDecision']={}
    progress('product','done',48)

    progress('fashion','processing',49)
    fashion_imgs=(raw.get('images',{}).get('main',[])[:6]+raw.get('images',{}).get('detail',[])[:6])
    if use_ai and fashion_imgs:
        prompt='''任务A2｜时尚与设计资产判断。只分析实际图片与页面文字中的色彩、花型/纹样、材质视觉、风格语言、细节工艺和人群审美表达。禁止把当前商品风格说成市场趋势，因为没有外部趋势数据。
输出：{"fashionThesis":{"statement":"","commercialMeaning":"","evidenceIds":[],"confidence":0},"designAssets":[{"asset":"","observation":"","commercialValue":"","developmentAction":"","evidenceIds":[],"confidence":0}],"styleSignals":[{"signal":"","whatItMeansForProduct":"","evidenceIds":[],"confidence":0}],"fashionRisks":[{"risk":"","why":"","action":"","evidenceIds":[],"confidence":0}],"trendBoundary":"没有外部趋势/竞品数据时不能判断流行度与生命周期"}'''
        z,e=call(prompt,{'evidence':compact_evidence(ledger,{'product','sku','attribute','image'},280)},7200,fashion_imgs)
        if e:out['modelErrors']['fashion']=e
        out['fashionDecision']=require_refs(z,valid)
    else: out['fashionDecision']={}
    progress('fashion','done',50)

    progress('visual','processing',51)
    main_imgs=raw.get('images',{}).get('main',[])[:8]
    if use_ai and main_imgs:
        prompt='''任务B｜主图商业信息提炼。目标不是解释图片，而是让专业用户一眼看到“这张图在卖什么”。逐张提炼图片中可核验的商品信息标签，再给一个短动作。
同时逐图记录可见展示空间关系，放入evidenceDetail.displayRelations：{"visibleParts":[{"id":"局部1","description":"可见区域，不把折叠层误认为独立件数"}],"relations":[{"type":"连接|接触|覆盖|遮挡|方向|相对位置|形变","from":"局部1","to":"局部2","observation":"看得见的关系"}],"view":"观察视角","uncertainAreas":["不可见且不能确认的部分"]}。只记录实际图中的关系；折叠、悬挂、手持、铺展等共用此描述，不套固定状态模板，不猜隐藏结构、件数或操作过程。产品固有组成与摆放形成的折边、接触、覆盖必须区分；详细关系不适用页面标签字数限制。
输出：
{"visualThesis":{"professionalOpinion":"<=45字","evidenceIds":[]},"coreClaims":[],"imageRoles":[{"imageEvidenceId":"IMG_MAIN_0001","imageRole":"<=8字","visualSignals":["2-3个，每项<=10字"],"businessMeaning":"<=22字","nextAction":"<=18字","contentKey":"product_overview|usage_scene|material_touch|structure_function|spec_choice","evidenceIds":[],"confidence":0}],"evidenceDetail":[{"imageEvidenceId":"IMG_MAIN_0001","composition":"","textInfo":"","productSubject":"","patternColor":"","evidenceIds":[]}]}
visualSignals必须来自图片可见文字、商品、场景或已确认参数，例如“40支全棉/六件套/90×190cm”，不能写抽象评价。
主图按商品全貌、使用场景、材质触感、结构功能、规格选择分工；每张图只承担一个主任务，不把品牌、专利、授权、价格、销量、物流或服务当作视觉卖点。
'''
        z,e=call(prompt,{'evidence':compact_evidence(ledger,{'product','sales','image','attribute'},220)},6800,main_imgs)
        if e:out['modelErrors']['visual']=e
        out['visualDecision']=require_refs(z,valid)
    else: out['visualDecision']={}
    progress('visual','done',57)

    progress('merchandising','processing',58)
    if use_ai:
        prompt='''任务C｜标题表达压缩。只回答三件事：当前已经表达什么、还应强化什么、建议怎么改。不要输出解释型长段落。
输出：
{"titleAnalysis":{"professionalOpinion":"<=45字","currentExpression":[{"value":"<=10字","evidenceIds":[]}],"reinforce":[{"topic":"<=10字","evidenceIds":[]}],"recommendedActions":[{"action":"<=22字","evidenceIds":[]}],"recommendedTitles":[]},"promotionAnalysis":{}}
'''
        z,e=call(prompt,{'evidence':compact_evidence(ledger,{'product','sales','promotion','sku','attribute'},300)},7200)
        if e:out['modelErrors']['merchandising']=e
        out['merchandisingDecision']=require_refs(z,valid)
    else: out['merchandisingDecision']={}
    progress('merchandising','done',64)

    progress('detail','processing',65)
    detail_imgs=raw.get('images',{}).get('detail',[])[:20]
    if use_ai and detail_imgs:
        prompt='''任务D｜详情页证明信息提炼。按4-6个信息任务组选代表图，不按图片流水账。每组只提炼2-4个图片信息标签和1条专业动作。
对实际输入图片在evidenceDetail中按imageEvidenceId记录composition与displayRelations：{"visibleParts":[{"id":"局部1","description":"可见区域"}],"relations":[{"type":"连接|接触|覆盖|遮挡|方向|相对位置|形变","from":"局部1","to":"局部2","observation":"实际可见关系"}],"view":"观察视角","uncertainAreas":["不能确认的部分"]}。区分产品固有结构与展示空间关系，不将可见层数当产品件数，不猜隐藏连接或操作过程；详细观察不按标签长度压缩，保持证据ID对应原图。
输出：
{"detailThesis":{"professionalOpinion":"<=45字","evidenceIds":[]},"contentGroups":[{"type":"场景证明|材质证明|结构工艺|功能表现|规格适配|使用维护","representativeImageId":"IMG_DETAIL_0001","visualSignals":["2-3项，每项<=10字"],"businessMeaning":"<=22字","nextAction":"<=18字","contentKey":"scene_problem|material_proof|structure_proof|function_proof|spec_adaptation|care_durability","imageEvidenceIds":[],"evidenceIds":[]}],"continuityChecks":[{"claim":"<=24字","mainImageEvidenceIds":[],"detailEvidenceIds":[],"status":"closed_loop|detail_missing|main_missing|conflict|review_pending","nextAction":"<=24字","evidenceIds":[]}],"pageSequence":[],"evidenceDetail":[]}
详情顺序必须接续主图：场景证明 → 材质证明 → 结构工艺 → 功能表现 → 规格适配 → 使用维护；每组只负责一个购买疑问，不重复其他组。不要输出品牌、专利、授权、认证、奖项、包邮、物流、价格、销量、促销、客服或售后等唯一性/交易信息。
'''
        z,e=call(prompt,{'visualDecision':out.get('visualDecision',{}),'evidence':compact_evidence(ledger,{'product','attribute','promotion','image'},360)},8200,detail_imgs)
        if e:out['modelErrors']['detail']=e
        out['detailDecision']=require_refs(z,valid)
    else: out['detailDecision']={}
    progress('detail','done',72)

    progress('review','processing',74)
    rb,e=batch_review_analysis(raw,valid,progress,enabled=use_ai)
    if e: out['modelErrors']['review']=e
    out['reviewBatchAnalysis']=rb.get('batches',[])
    out['consumerResearch']=rb.get('aggregate',{})
    progress('review','done',86)

    progress('qa','processing',87)
    qz,qe=question_analysis(raw,valid,enabled=use_ai)
    if qe: out['modelErrors']['qa']=qe
    out['questionResearch']=qz or {}
    progress('qa','done',89)

    progress('competition','processing',90)
    out['competitionDecision']={'status':'missing_competitor_dataset','statement':'当前只有单品证据，不输出相对竞品的价格、设计、材质或营销优劣。','commercialMeaning':'单品报告只分析当前商品的页面表达、参数定义和购后反馈。','requiredCompetitorSet':['同核心搜索词','同目标场景','同主销规格','同可比价格带'],'compareDimensions':['当前价/主销价','销量/榜单公开值','标题槽位','主图内容结构','材质/工艺宣称','SKU结构','促销服务','评论痛点','详情证明方式']}
    progress('competition','done',91)

    progress('strategy','processing',92)
    if use_ai:
        context={'reportPlan':out.get('reportPlan',{}),'dataQuality':out['dataQuality'],'baseline':base,'productDecision':out.get('productDecision',{}),'visualDecision':out.get('visualDecision',{}),'merchandisingDecision':out.get('merchandisingDecision',{}),'detailDecision':out.get('detailDecision',{}),'consumerResearch':out.get('consumerResearch',{}),'questionResearch':out.get('questionResearch',{}),'fashionDecision':out.get('fashionDecision',{}),'competitionDecision':out.get('competitionDecision',{}),'evidence':compact_evidence(ledger,{'product','sales','sku','attribute','promotion','review','question'},420)}
        prompt='''任务E｜老板决策摘要。不要写大段商业分析，只形成可供最终编排器使用的三个答案：为什么能卖、值得继承、下一款优先。
输出：
{"executiveDecision":{"verdict":"<=45字","oneSentence":"<=55字","ifOnlyOneAction":"<=35字","evidenceIds":[]},"whyItSells":[{"mechanism":"<=20字","evidenceIds":[]}],"mustKeep":[{"item":"<=20字","evidenceIds":[]}],"mustFix":[{"item":"<=20字","fixAction":"<=28字","evidenceIds":[]}],"decisionGates":[]}
'''
        z,e=call(prompt,context,9800)
        if e:out['modelErrors']['strategy']=e
        out['commercialDecision']=require_refs(z,valid)
    else: out['commercialDecision']={}
    progress('strategy','done',94)

    progress('plans','processing',95)
    if use_ai:
        context={'reportPlan':out.get('reportPlan',{}),'commercialDecision':out.get('commercialDecision',{}),'consumerResearch':out.get('consumerResearch',{}),'questionResearch':out.get('questionResearch',{}),'fashionDecision':out.get('fashionDecision',{}),'competitionDecision':out.get('competitionDecision',{}),'productDecision':out.get('productDecision',{}),'visualDecision':out.get('visualDecision',{}),'merchandisingDecision':out.get('merchandisingDecision',{}),'detailDecision':out.get('detailDecision',{}),'baseline':base}
        prompt='''任务F｜下一款产品开品方案。必须输出3套不同的产品新方案；每套只保留四个核心字段：来源等级、名称、产品动作、页面动作。产品动作是核心，必须具体说明下一款产品本身怎么改；页面动作必须说明该方案自己的完整主图证据链与详情图证据链如何承接。不要扩展字段。产品参考图由生成环节处理，不要求模型输出。
必须正好3套，顺序固定为：证据驱动优化、反馈驱动升级、探索性方向。每套名称必须是简洁的“XX款”，不能直接复用商品长标题；三个方案不得只是换名字，产品结构、材质、规格、工艺、配色或使用体验上必须有可辨认差异。
来源等级：
- 证据驱动优化：直接来自当前商品页面/参数/评论；
- 反馈驱动升级：直接来自消费者体验差异/购前关注；
- 探索性方向：设计创新或扩展想法，必须明确标记为待小样验证，不能当作已验证结论。
输出：
{"professionalOpinion":"<=45字","plans":[{"sourceType":"证据驱动优化|反馈驱动升级|探索性方向","name":"<=18字且以款结尾","productAction":"<=45字，明确结构/材质/规格/工艺/配色/包装中实际要改的内容","pageAction":"<=36字，说明该方案完整主图与详情证据链如何表达产品改进"}]}
'''
        z,e=call(prompt,context,9800)
        if e:out['modelErrors']['plans']=e
        out['launchPlans']=require_refs(z,valid)
        if not _arr((out.get('launchPlans') or {}).get('plans')):
            out['launchPlans']=_evidence_backed_launch_fallback(raw,valid)
    else: out['launchPlans']={}
    progress('plans','done',98)

    # 最终编辑层：把前面的事实与分析统一收敛为“全方位产品体验解决方案”。
    progress('editor','processing',98)
    if use_ai:
        context={
          'monitoring':raw.get('monitoring',[]), 'baseline':base, 'categoryRoute':route,
          'productDecision':out.get('productDecision',{}), 'fashionDecision':out.get('fashionDecision',{}),
          'visualDecision':out.get('visualDecision',{}), 'merchandisingDecision':out.get('merchandisingDecision',{}),
          'detailDecision':out.get('detailDecision',{}), 'consumerResearch':out.get('consumerResearch',{}),
          'questionResearch':out.get('questionResearch',{}), 'commercialDecision':out.get('commercialDecision',{}),
          'launchPlans':out.get('launchPlans',{}),
          'roleOutputs':{
            'productStrategy':out.get('productDecision',{}),
            'conversion':{'title':out.get('merchandisingDecision',{}),'visual':out.get('visualDecision',{}),'detail':out.get('detailDecision',{})},
            'consumerInsight':{'reviews':out.get('consumerResearch',{}),'questions':out.get('questionResearch',{})},
            'productSupply':{'product':out.get('productDecision',{}),'baseline':base},
            'visualDesign':out.get('fashionDecision',{}),
            'executiveDecision':out.get('commercialDecision',{}),
            'editorReview':{'scope':ROLE_CONTRACT['editorReview']['outputs']}
          },
          'evidence':compact_evidence(ledger,{'monitoring','product','sales','sku','attribute','promotion','review','question','image'},650)
        }
        prompt=FINAL_REPORT_PROMPT
        imgs=(raw.get('images',{}).get('main',[])[:8]+raw.get('images',{}).get('sku',[])[:8]+raw.get('images',{}).get('detail',[])[:16]+raw.get('images',{}).get('buyerShow',[])[:8])
        z,e=call(prompt,context,12000,imgs)
        if e: out['modelErrors']['experienceSolution']=e
        out['experienceSolution']=require_refs(z,valid)
    else:
        out['experienceSolution']={}
    # 最终编排模型不可用或被异常图片拒绝时，仍需用真实页面、参数、评论和问答生成完整本地分析，不能只输出最小结构。
    final_draft=out.get('experienceSolution') or {}
    if not isinstance(final_draft,dict) or not _txt((final_draft.get('reportSummary') or {}).get('title')).strip():
        out['experienceSolution']=build_fallback_experience(raw,base)
        out.setdefault('modelErrors',{})['experienceSolutionFallback']='最终编排未返回可用内容，已按真实采集证据生成本地完整分析。'

    # 将分角色产物显式挂载到结果，供报告样式、审计和后续导出复用；不复制或丢弃既有分析字段。
    out['roleOutputs']={
      'productStrategy':out.get('productDecision',{}),
      'conversion':{'title':out.get('merchandisingDecision',{}),'visual':out.get('visualDecision',{}),'detail':out.get('detailDecision',{})},
      'consumerInsight':{'reviews':out.get('consumerResearch',{}),'questions':out.get('questionResearch',{})},
      'productSupply':{'product':out.get('productDecision',{}),'sku':out.get('skuDecision',{}),'baseline':base},
      'visualDesign':out.get('fashionDecision',{}),
      'executiveDecision':out.get('commercialDecision',{}),
      'editorReview':{'status':'pending','scope':ROLE_CONTRACT['editorReview']['outputs']}
    }
    result=ensure_experience_solution(out)
    final_exp=result.get('experienceSolution') or {}
    role_outputs=result.setdefault('roleOutputs',{})
    # 以总编后的最终结构补齐角色视图，确保角色层与对外报告完全一致。
    role_outputs['conversion']={
      'title':final_exp.get('titleAnalysis') or role_outputs.get('conversion',{}).get('title',{}),
      'visual':final_exp.get('visualCommerce') or role_outputs.get('conversion',{}).get('visual',{}),
      'detail':final_exp.get('detailCommerce') or role_outputs.get('conversion',{}).get('detail',{})
    }
    role_outputs['consumerInsight']=final_exp.get('customerExperience') or role_outputs.get('consumerInsight',{})
    role_outputs['productSupply']={
      'sku':final_exp.get('skuAnalysis') or {},
      'product':final_exp.get('productExperience') or role_outputs.get('productSupply',{}).get('product',{}),
      'baseline':base
    }
    role_outputs['visualDesign']=role_outputs.get('visualDesign') or {}
    role_outputs['executiveDecision']=final_exp.get('ownerOverview') or role_outputs.get('executiveDecision',{})
    if use_ai and not result['meta'].get('reportReady'):
        first_validation=result['meta'].get('reportValidation') or core_solution_diagnostics(result.get('experienceSolution'))
        progress('editor','processing repair',99)
        repair_payload={
          'failedChecks':first_validation.get('checks',[]),
          'draft':result.get('experienceSolution') or {},
          'evidence':compact_evidence(ledger,{'monitoring','product','sales','sku','attribute','promotion','review','question','image'},650),
        }
        repaired,repair_error=call(FINAL_REPORT_REPAIR_PROMPT,repair_payload,12000,imgs)
        if repair_error:out['modelErrors']['experienceSolutionRepair']=repair_error
        if repaired:
            out['experienceSolution']=require_refs(repaired,valid)
            result=ensure_experience_solution(out)
        result['meta']['modelRepairAttempted']=True
        result['meta']['initialReportValidation']=first_validation
    if use_ai and not result['meta'].get('reportReady'):
        before=result['meta'].get('reportValidation') or core_solution_diagnostics(result.get('experienceSolution'))
        out['experienceSolution']=repair_core_solution_with_evidence(result.get('experienceSolution'),raw,base)
        out['meta'].update(result.get('meta') or {})
        out['meta']['evidenceStructuralRepairApplied']=True
        out['meta']['preStructuralRepairValidation']=before
        result=ensure_experience_solution(out)
    result.setdefault('roleOutputs',{})['editorReview']={
      'status':'passed' if result['meta'].get('reportReady') else 'needs_repair',
      'validation':result['meta'].get('reportValidation') or {},
      'scope':ROLE_CONTRACT['editorReview']['outputs']
    }
    result.setdefault('meta',{})['roleContractVersion']=ROLE_CONTRACT_VERSION
    result.setdefault('meta',{})['roleContract']=ROLE_CONTRACT
    progress('editor','done' if result['meta'].get('reportReady') else 'failed',99)
    return result
