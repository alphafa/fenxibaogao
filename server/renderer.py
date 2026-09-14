import html
import json
import re
from analysis import ensure_experience_solution

UNCERTAIN = ('可能', '或许', '推测', '无法判断', '不能判断', '证据不足', '尚不能', '不足以', '未知', '未识别', '不代表', '待验证')

def H(v): return html.escape('' if v is None else str(v))
def arr(v): return v if isinstance(v, list) else []
def safe(v): return '' if v in (None, '', [], {}) else (str(v) if not isinstance(v,(dict,list,tuple)) else '')

def text_of(v, keys=('text','point','statement','label','value','driver','problem','concern','signal','item')):
    if v in (None,'',[],{}): return ''
    if isinstance(v,str): return v
    if isinstance(v,(int,float)): return str(v)
    if isinstance(v,dict):
        for k in keys:
            if v.get(k) not in (None,'',[],{}): return text_of(v.get(k),keys)
        return ''
    return ''

def concise(v, limit=90, verified=True):
    text = re.sub(r'\s+', ' ', safe(v)).strip()
    if not text: return ''
    parts = [x.strip() for x in re.split(r'(?<=[。！？；])', text) if x.strip()]
    if verified:
        text = ''.join(x for x in parts if not any(word in x for word in UNCERTAIN))
    if not text: return ''
    if len(text) <= limit: return text
    cut = max(text.rfind(mark, 0, limit + 1) for mark in '，。；：')
    if cut < limit // 2: cut = limit
    return text[:cut].rstrip('，。；： ') + '…'

def evidence_index(a): return {x.get('id'): x for x in arr(a.get('evidenceLedger')) if isinstance(x, dict) and x.get('id')}
def image_entry(eid, idx, allowed_groups=None):
    e = idx.get(eid) or {}; value = e.get('value')
    group=(e.get('meta') or {}).get('group')
    if e.get('type')!='image' or not isinstance(value,str) or not value.startswith(('http://','https://','data:image/')):return None
    if allowed_groups and group not in allowed_groups:return None
    return e
def image_url(eid, idx, allowed_groups=None):
    e=image_entry(eid,idx,allowed_groups)
    if not e:return ''
    return (e.get('meta') or {}).get('localUrl') or e.get('value')

def image_source(e):
    if not isinstance(e,dict):return ('','')
    meta=e.get('meta') or {}; return (meta.get('localUrl') or e.get('value') or '', meta.get('sourceUrl') or e.get('value') or '')

def img_tag(url, alt='商品图片', fallback=''):
    if not url:return ''
    fb=fallback if fallback and fallback!=url else ''
    attrs=f' data-fallback="{H(fb)}"' if fb else ''
    return f'<img loading="eager" decoding="async" src="{H(url)}"{attrs} alt="{H(alt)}" onerror="if(this.dataset.fallback){{this.src=this.dataset.fallback;this.dataset.fallback=\'\';return;}}this.classList.add(\'image-error\');">'

def product_hero(visual, idx):
    for item in arr(visual.get('items')):
        if isinstance(item, dict):
            url = image_url(safe(item.get('imageEvidenceId')), idx, {'main'})
            if url: return url
    return ''

def action_list(text, limit=5):
    items = []
    for value in re.split(r'[；。]\s*', safe(text)):
        value = concise(value, 64)
        if value and value not in items: items.append(value)
    return '<ul class="action-list">' + ''.join(f'<li>{H(x)}</li>' for x in items[:limit]) + '</ul>' if items else ''

def owner_cards(cards):
    out = []
    for x in arr(cards)[:6]:
        if not isinstance(x, dict): continue
        headline = concise(x.get('headline'), 46)
        bullets = [concise(v, 42) for v in arr(x.get('bullets'))]
        bullets = [v for v in bullets if v][:2]
        if not headline: continue
        detail = '<ul>' + ''.join(f'<li>{H(v)}</li>' for v in bullets) + '</ul>' if bullets else ''
        out.append(f'<article class="owner-card {H(safe(x.get("tone")) or "normal")}"><span>{H(x.get("label"))}</span><strong>{H(headline)}</strong>{detail}</article>')
    return ''.join(out)

def overview_rows(items, kind):
    out = []
    for x in arr(items)[:6]:
        if not isinstance(x, dict): continue
        label = concise(x.get('label'), 24, False)
        value = concise(x.get('value'), 84, False)
        note = concise(x.get('note'), 42, False)
        priority = concise(x.get('priority'), 14, False)
        if not label or not value: continue
        meta = priority or note
        out.append(
            f'<article class="shopper-row {H(kind)}">'
            + (f'<span class="shopper-meta">{H(meta)}</span>' if meta else '')
            + f'<strong>{H(label)}</strong><p>{H(value)}</p></article>'
        )
    return ''.join(out)

def platform_overview_html(overview):
    facts = overview_rows(overview.get('facts'), 'fact')
    outcomes = overview_rows(arr(overview.get('outcomes'))[:3], 'reason')
    actions = overview_rows(overview.get('actions'), 'check')
    groups = ''.join([
        f'<section class="shopper-group"><h3>交易与产品事实</h3><div class="shopper-grid">{facts}</div></section>' if facts else '',
        f'<section class="shopper-group"><h3>购后体验验证</h3><div class="shopper-grid">{outcomes}</div></section>' if outcomes else '',
        f'<section class="shopper-group full"><h3>平台经营建议</h3><div class="shopper-grid">{actions}</div></section>' if actions else '',
    ])
    verdict = concise(overview.get('verdict'), 70, False)
    sample = concise(overview.get('sampleNote'), 64, False)
    return '<div class="shopper-decision">' + (
        f'<header class="shopper-verdict"><span>产品分析结论</span><strong>{H(verdict)}</strong>'
        + (f'<small>{H(sample)}</small>' if sample else '') + '</header>' if verdict else ''
    ) + f'<div class="shopper-groups">{groups}</div></div>'

def decision_boundary_html(base):
    reviews = base.get('reviewCount', 0)
    public = safe(base.get('publicReviewCount'))
    coverage = f'已采有效评论 {reviews}' + (f' / 页面公开 {public}' if public else '')
    status = '评论采集已确认完整' if base.get('reviewCollectionComplete') else '评论采集未确认完整'
    items = [
        ('证据覆盖', coverage, status),
        ('本报告支持', '商品拆解、样品验证、规格校准、页面信息修正', '基于当前页面参数与已采评论'),
        ('适用范围', '不输出生产规模、利润、转化或市场容量', '当前数据不含对应经营指标'),
        ('补充数据', '完整评论、流量转化、退款售后、成本毛利', '补齐后再进入经营测算'),
    ]
    return '<section class="decision-boundary">' + ''.join(
        f'<article><span>{H(label)}</span><strong>{H(value)}</strong><small>{H(note)}</small></article>'
        for label, value, note in items
    ) + '</section>'

def review_results_html(overview):
    def rows(items, tone):
        out=[]
        for x in arr(items)[:6]:
            if not isinstance(x,dict):continue
            label=concise(x.get('label'),24,False);value=concise(x.get('value'),100,False);note=concise(x.get('note') or x.get('priority'),26,False)
            if not label or not value:continue
            out.append(f'<article class="result-row {H(tone)}">'+(f'<span>{H(note)}</span>' if note else '')+f'<strong>{H(label)}</strong><p>{H(value)}</p></article>')
        return ''.join(out)
    outcomes=rows(overview.get('outcomes'),'positive')
    risks=rows([x for x in arr(overview.get('checks')) if isinstance(x,dict) and x.get('priority')=='明确反馈'],'risk')
    questions=rows(overview.get('questions'),'question')
    return ''.join([
      f'<section class="result-block"><h3>评论确认的结果</h3><div class="result-grid">{outcomes}</div></section>' if outcomes else '',
      f'<section class="result-block"><h3>明确问题</h3><div class="result-grid">{risks}</div></section>' if risks else '',
      f'<section class="result-block"><h3>购买问答反馈</h3><div class="result-grid">{questions}</div></section>' if questions else '',
    ])

def visual_items(items, idx):
    out = []
    for x in arr(items):
        if not isinstance(x, dict): continue
        eid=safe(x.get('imageEvidenceId'));entry=image_entry(eid,idx,{'main','detail'})
        if not entry: continue
        url=entry.get('value');group=(entry.get('meta') or {}).get('group');source=(entry.get('meta') or {}).get('source')
        source_label='商品主图画廊' if group=='main' else '商品详情描述区域'
        if source not in ('meta_og_image','dom_main_gallery','structured_main_gallery','dom_product_description','structured_product_description'):continue
        headline = concise(x.get('headline'), 42)
        frame = concise(x.get('frameInfo'), 90)
        subject = concise(x.get('productSubject'), 90)
        pattern = concise(x.get('patternColor'), 90)
        text_info = concise(x.get('textInfo'), 90)
        hierarchy = concise(x.get('informationHierarchy'), 90)
        task = concise(x.get('contentTask') or x.get('persuasionTask'), 72)
        weakness = concise(x.get('weakness'), 72)
        action = concise(x.get('borrowableAction') or x.get('action') or x.get('nextProductAction'), 82)
        facts = ''.join([
            f'<div><span>画面内容</span><b>{H(frame)}</b></div>' if frame else '',
            f'<div><span>商品主体</span><b>{H(subject)}</b></div>' if subject else '',
            f'<div><span>花型配色</span><b>{H(pattern)}</b></div>' if pattern else '',
            f'<div><span>文案信息</span><b>{H(text_info)}</b></div>' if text_info else '',
            f'<div><span>层级关系</span><b>{H(hierarchy)}</b></div>' if hierarchy else '',
            f'<div><span>表达任务</span><b>{H(task)}</b></div>' if task else '',
            f'<div><span>明确问题</span><b>{H(weakness)}</b></div>' if weakness else '',
            f'<div class="action"><span>可借鉴动作</span><b>{H(action)}</b></div>' if action else ''
        ])
        out.append('<article class="story-item"><figure class="story-media">' + img_tag(url, '商品主图' if group=='main' else '商品详情图') + '</figure><div class="story-copy"><span class="source-badge">来源：' + H(source_label) + '</span><h3>' + H(headline or ('已核验主图' if group=='main' else '已核验详情图')) + '</h3><div class="evidence">' + facts + '</div></div></article>')
    return ''.join(out)

def buyer_evidence_html(block, idx):
    groups={}
    for item in arr((block or {}).get('items'))[:24]:
        if not isinstance(item,dict):continue
        image_id=safe(item.get('imageEvidenceId'));review_id=safe(item.get('reviewEvidenceId'))
        image=image_entry(image_id,idx,{'buyerShow'});review=idx.get(review_id) or {};meta=(image or {}).get('meta') or {}
        if not image or review.get('type')!='review' or review_id not in arr(meta.get('reviewEvidenceIds')):continue
        value=review.get('value') if isinstance(review.get('value'),dict) else {};quote=concise(value.get('content'),90,False)
        if not quote:continue
        details=' · '.join(x for x in (concise(value.get('sku'),42,False),concise(value.get('date'),18,False)) if x)
        group=groups.setdefault(review_id,{'quote':quote,'details':details,'images':[]})
        group['images'].append(image.get('value'))
    if not groups:return ''
    title=H((block or {}).get('title') or '评论原图与对应评价')
    image_count=sum(len(x['images']) for x in groups.values())
    out=[]
    for review_id,group in groups.items():
        gallery=''.join(
            '<figure>'+img_tag(url,f'{review_id} 评论原图 {i}')+f'<figcaption>原图 {i:02d}</figcaption></figure>'
            for i,url in enumerate(group['images'],1)
        )
        out.append('<article class="buyer-review-group"><div class="buyer-review-copy"><span>评论证据 · '+H(review_id)+'</span><blockquote>'+H(group['quote'])+'</blockquote>'+('<small>'+H(group['details'])+'</small>' if group['details'] else '')+'</div><div class="buyer-gallery">'+gallery+'</div></article>')
    return f'<section class="buyer-evidence"><header><span>评论图片证据</span><h3>{title} · {len(groups)} 条评价 / {image_count} 张原图</h3><p>每组图片只关联同一条评论，按原比例完整展示；不作为商品主图、详情图或 SKU 图使用。</p></header><div class="buyer-groups">'+''.join(out)+'</div></section>'

def stats_html(stats):
    out = []
    for x in arr(stats)[:6]:
        if isinstance(x, dict) and safe(x.get('value')):
            out.append(f'<div class="voice-stat"><span>{H(concise(x.get("label"), 16, False))}</span><strong>{H(concise(x.get("value"), 18, False))}</strong></div>')
    return ''.join(out)

def journey_html(stages):
    xs = [x for x in arr(stages) if isinstance(x, dict)]
    tabs, panels = [], []
    for i, x in enumerate(xs):
        positive = concise(x.get('positiveConfirmation'), 70); friction = concise(x.get('friction'), 70)
        if not positive and not friction: continue
        active = ' active' if not tabs else ''
        tabs.append(f'<button class="jtab{active}" data-i="{len(tabs)}"><small>{H(x.get("stageNo") or str(i + 1).zfill(2))}</small><b>{H(x.get("label"))}</b></button>')
        facts = (f'<section><span>已确认</span><p>{H(positive)}</p></section>' if positive else '') + (f'<section><span>明确问题</span><p>{H(friction)}</p></section>' if friction else '')
        quotes = []
        for q in arr(x.get('quotes'))[:2]:
            if isinstance(q, dict) and safe(q.get('text')): quotes.append(f'<li><span>{H(q.get("type"))}</span>{H(concise(q.get("text"), 90, False))}</li>')
        panels.append(f'<div class="jpanel{active}"><header><span>第 {H(x.get("stageNo") or i + 1)} 阶段</span><h4>{H(x.get("label"))}</h4><p>{H(concise(x.get("headline"), 54))}</p></header><div class="jgrid">{facts}</div>' + ('<ul class="quotes">' + ''.join(quotes) + '</ul>' if quotes else '') + '</div>')
    return '<div class="journey-tabs">' + ''.join(tabs) + '</div>' + ''.join(panels) if tabs else ''

def signals_html(signals):
    if not signals: return ''
    values = []
    for key, tone in [('positive', 'good'), ('questions', 'ask'), ('risks', 'risk')]:
        for x in arr(signals.get(key))[:5]:
            label = concise(x.get('label'), 42) if isinstance(x, dict) else ''
            if label: values.append(f'<span class="signal {tone}">{H(label)}</span>')
    return '<section class="signal-atlas"><span class="label">已确认体验信号</span><div class="signals">' + ''.join(values) + '</div></section>' if values else ''

def param_html(xs):
    out = []
    for x in arr(xs)[:8]:
        value = concise(x.get('value'), 82) if isinstance(x, dict) else ''
        if value: out.append(f'<div class="param"><span>{H(x.get("label"))}</span><b>{H(value)}</b></div>')
    return ''.join(out)

def gates_html(xs):
    out = []
    for x in arr(xs)[:6]:
        action = concise(x.get('action'), 92) if isinstance(x, dict) else ''
        if action: out.append(f'<div class="gate"><b>{H(x.get("priority"))} · {H(concise(x.get("label"), 24, False))}</b><span>{H(action)}</span></div>')
    return ''.join(out)

def plans_html(xs):
    out = []
    for x in arr(xs)[:3]:
        if not isinstance(x, dict): continue
        selling = selling_points_html(x.get('sellingPoints'))
        specs = []
        for spec in arr(x.get('specs')):
            value = concise(spec.get('value'), 82) if isinstance(spec, dict) else ''
            if value: specs.append(f'<div><span>{H(spec.get("label"))}</span><b>{H(value)}</b></div>')
        mg = x.get('manufacturingGate') or {}; vc = x.get('visualCommerce') or {}
        out.append('<article class="plan"><span>' + H(x.get('type')) + '</span><h3>' + H(concise(x.get('name'), 30, False)) + '</h3><p>' + H(concise(x.get('positioning'), 110)) + '</p>' + selling + '<div class="plan-specs">' + ''.join(specs) + '</div><div class="plan-actions"><section><h4>' + H(mg.get('title') or '制造闸门') + '</h4>' + action_list(mg.get('content')) + '</section><section><h4>' + H(vc.get('title') or '首图与商详') + '</h4>' + action_list(vc.get('content')) + '</section></div></article>')
    return ''.join(out)

def selling_points_html(xs):
    out=[]
    for x in arr(xs)[:5]:
        if not isinstance(x,dict):continue
        slogan=concise(x.get('slogan'),34,False)
        value=concise(x.get('consumerValue'),54,False)
        source=concise(x.get('evidenceSource'),32,False)
        action=concise(x.get('productAction'),64,False)
        if not slogan:continue
        out.append(f'<article><strong>{H(slogan)}</strong>'+(f'<p>{H(value)}</p>' if value else '')+(f'<small>{H(source)}</small>' if source else '')+(f'<b>{H(action)}</b>' if action else '')+'</article>')
    return '<section class="selling-points"><header><span>NEXT PRODUCT SELLING POINTS</span><h4>下一款明确卖点</h4></header><div>'+''.join(out)+'</div></section>' if out else ''

def governance_html(gov):
    if not isinstance(gov,dict):return ''
    items=[('报告角色',gov.get('role')),('结构标准',gov.get('structure')),('内容来源',gov.get('sourceRule')),('证据规则',gov.get('evidenceRule'))]
    rows=''.join(f'<article><span>{H(label)}</span><b>{H(concise(value,64,False))}</b></article>' for label,value in items if safe(value))
    return '<section class="governance"><div class="wrap"><div class="governance-grid">'+rows+'</div></div></section>' if rows else ''

def attr_lookup(raw, names):
    for x in arr(raw.get('attributes')):
        if not isinstance(x,dict):continue
        name=safe(x.get('name'))
        if any(k in name for k in names) and safe(x.get('value')):return safe(x.get('value'))
    return ''

def product_profile_html(raw, sales, base):
    rows=[
        ('一级品类', safe((raw.get('product') or {}).get('category')) or '床上用品'),
        ('商品标题', safe((raw.get('product') or {}).get('title'))),
        ('价格定位', ('¥'+safe(sales.get('currentPrice'))) if safe(sales.get('currentPrice')) else ''),
        ('公开销量', safe(sales.get('sold')) or safe(sales.get('cumulativeSales'))),
        ('目标人群', attr_lookup(raw, ['适用人群','适用对象'])),
        ('核心场景', attr_lookup(raw, ['适用场景','适用床尺寸','床品尺寸'])),
        ('产品结构', attr_lookup(raw, ['件数','套件组成','组合形式','款式'])),
        ('材质成分', attr_lookup(raw, ['成分含量','床单面料材质','被面材质','材质','棉种类'])),
        ('支数密度', ' / '.join(x for x in [attr_lookup(raw,['面料支数','纱线支数']), attr_lookup(raw,['面料密度','织物密度'])] if x)),
        ('工艺结构', attr_lookup(raw, ['床品工艺','织造工艺','印染工艺','工艺'])),
        ('风格花型', ' / '.join(x for x in [attr_lookup(raw,['风格']), attr_lookup(raw,['主图案类型','颜色分类'])] if x)),
        ('评论样本', f'{base.get("reviewCount",0)} 条有效评论'),
    ]
    cells=''.join(f'<div class="profile-cell"><span>{H(k)}</span><b>{H(concise(v,78,False))}</b></div>' for k,v in rows if safe(v))
    return '<div class="profile-board">'+cells+'</div>' if cells else ''

def deal_logic_html(plans):
    points=[]
    for plan in arr(plans.get('plans'))[:1]:
        if isinstance(plan,dict):points=arr(plan.get('sellingPoints'))
    rows=[]
    for i,x in enumerate(points[:5],1):
        if not isinstance(x,dict):continue
        rows.append(f'<article class="logic-step"><span>{i:02d}</span><strong>{H(concise(x.get("slogan"),34,False))}</strong><p>{H(concise(x.get("consumerValue"),62,False))}</p><small>{H(concise(x.get("evidenceSource"),36,False))}</small></article>')
    return '<div class="logic-chain">'+''.join(rows)+'</div>' if rows else ''

def feature_power_html(overview, product_exp):
    cards=[]
    for x in arr(overview.get('cards')):
        if not isinstance(x,dict):continue
        label=safe(x.get('label')); headline=concise(x.get('headline'),42,False)
        if not headline or label in ('销售事实','页面活动'):continue
        tone=safe(x.get('tone')) or 'normal'
        cards.append(f'<article class="feature-card {H(tone)}"><span>{H(label)}</span><strong>{H(headline)}</strong></article>')
    for x in arr(product_exp.get('gates'))[:3]:
        if not isinstance(x,dict):continue
        cards.append(f'<article class="feature-card risk"><span>{H(x.get("priority"))}</span><strong>{H(concise(x.get("label"),34,False))}</strong><p>{H(concise(x.get("action"),64,False))}</p></article>')
    return '<div class="feature-grid">'+''.join(cards[:8])+'</div>' if cards else ''

def marketing_html(raw):
    product=raw.get('product') or {}; title=safe(product.get('title'))
    slots=[
      ('品类词', '床品 / 三件套' if re.search(r'床品|三件套|四件套|被套|床单|床笠', title) else ''),
      ('人群词', attr_lookup(raw,['适用人群']) or ('学生' if '学生' in title else '')),
      ('场景词', attr_lookup(raw,['适用床尺寸','适用场景'])),
      ('材质词', attr_lookup(raw,['床单面料材质','被面材质','成分含量','材质'])),
      ('工艺词', attr_lookup(raw,['面料支数','面料密度','床品工艺','织造工艺'])),
      ('风格词', attr_lookup(raw,['风格','主图案类型'])),
    ]
    slot_html=''.join(f'<div class="market-slot"><span>{H(k)}</span><b>{H(concise(v,62,False))}</b></div>' for k,v in slots if safe(v))
    promos=''.join(f'<li>{H(concise(x.get("text"),58,False))}</li>' for x in arr(raw.get('promotions'))[:4] if isinstance(x,dict) and safe(x.get('text')))
    return '<div class="marketing-grid"><article><span>商品标题</span><strong>'+H(concise(title,90,False))+'</strong><div class="market-slots">'+slot_html+'</div></article><article><span>页面营销表达</span><ul>'+promos+'</ul></article></div>'

def visual_status_html(images, verified_visual):
    rows=[('主图',len(arr(images.get('main'))),bool(arr(images.get('main')))),('详情图',len(arr(images.get('detail'))),bool(arr(images.get('detail')))),('SKU 图',len(arr(images.get('sku'))),bool(arr(images.get('sku')))),('评论实拍',len(arr(images.get('buyerShow'))),bool(arr(images.get('buyerShow'))))]
    cards=''.join(f'<article class="visual-state {"ready" if ok else "missing"}"><span>{H(k)}</span><strong>{n}</strong><small>{"已采集" if ok else "未采集"}</small></article>' for k,n,ok in rows)
    body=verified_visual or '<p class="evidence-note">主图/详情图未形成可核验图片条目时，本章只展示来源状态，不用评论图片替代主图或详情图。</p>'
    return '<div class="visual-states">'+cards+'</div><div class="story">'+body+'</div>'

def competition_html(plans, product_exp, overview):
    point=''
    for plan in arr(plans.get('plans'))[:1]:
        if not isinstance(plan, dict):
            continue
        selling_points = arr(plan.get('sellingPoints'))
        first_point = selling_points[0] if selling_points else None
        if isinstance(first_point, dict):
            point = concise(first_point.get('slogan'), 42, False)
        elif isinstance(first_point, list) and first_point:
            nested_first = first_point[0]
            if isinstance(nested_first, dict):
                point = concise(nested_first.get('slogan'), 42, False)
    risks=[concise(x.get('label'),34,False) for x in arr(product_exp.get('gates'))[:3] if isinstance(x,dict)]
    return '<div class="competition-grid"><article class="strong"><span>核心价值</span><strong>'+H(point or '已确认体验可复用')+'</strong><p>来自页面参数与评论聚合，不写市场推断。</p></article><article class="mid"><span>基础能力</span><strong>类目关键参数、规格与页面需要和真实商品一致</strong><p>基础能力必须被主图、详情和参数共同证明。</p></article><article class="weak"><span>风险点</span><strong>'+H(' / '.join(x for x in risks if x) or '按评论明确问题处理')+'</strong><p>风险只按真实评论和参数校验项呈现。</p></article></div>'

def validation_rows(xs):
    out = []
    for x in arr(xs)[:6]:
        if isinstance(x, dict) and any(safe(x.get(k)) for k in ('stage','metrics','successMeaning','nextAction')):
            stage=concise(x.get('stage'),18,False);owner=concise(x.get('owner'),24,False)
            if not owner:continue
            out.append(f'<tr><td>{H(stage)}</td><td>{H(owner)}</td><td>{H(concise(x.get("metrics"), 62))}</td><td>{H(concise(x.get("successMeaning"), 58))}</td><td>{H(concise(x.get("nextAction"), 62))}</td></tr>')
    return ''.join(out)


# V9.2 图片驱动专业报告。分析可以深，默认报告必须轻。
DISPLAY_MARKERS = ('[数据事实]','[分析判断]','[设计建议]','[证据不足]','数据事实：','分析判断：','设计建议：')

def clean_display(v, limit=120):
    t=text_of(v) if not isinstance(v,str) else v
    if not t:return ''
    t=re.sub(r'\*\*|__','',t)
    for m in DISPLAY_MARKERS:t=t.replace(m,'')
    t=re.sub(r'\s*/\s*','；',t)
    t=re.sub(r'\s+',' ',t).strip(' ；/')
    return concise(t,limit,False)

def first_text(*values, limit=100):
    for v in values:
        t=clean_display(v,limit)
        if t:return t
    return ''

def _entries(idx, group, limit=200):
    return [(eid,e) for eid,e in idx.items() if e.get('type')=='image' and (e.get('meta') or {}).get('group')==group][:limit]

def _visual_figure(e, alt, css=''):
    src,fb=image_source(e)
    if not src:return '<figure class="visual '+H(css)+' failed"><div class="image-fallback">图片未采集</div></figure>'
    return '<figure class="visual '+H(css)+'">'+img_tag(src,alt,fb)+'<div class="image-fallback">图片暂不可用</div></figure>'

def _section(no,title,deck,body,sid):
    return f'<section class="v92-section" id="{H(sid)}"><div class="wrap"><header class="v92-head"><span>{H(no)}</span><h2>{H(title)}</h2><p>{H(deck)}</p></header>{body}</div></section>'

def _opinion(text):
    text=clean_display(text,45)
    return f'<div class="v92-opinion v925-opinion"><strong>{H(text)}</strong></div>' if text else ''

def _chips(values, limit=3):
    vals=[]
    for v in arr(values)[:limit]:
        t=clean_display(v.get('value') if isinstance(v,dict) else v,10)
        if t and t not in vals: vals.append(t)
    return '<div class="v925-signals">'+H(' · '.join(vals))+'</div>' if vals else ''

def _owner_overview(exp, raw, base, sales):
    src=arr((exp.get('ownerOverview') or {}).get('cards'))
    wanted=['为什么能卖','值得继承','下一款优先']
    mapped={k:None for k in wanted}
    for x in src:
        if not isinstance(x,dict): continue
        label=clean_display(x.get('label'),16); headline=clean_display(x.get('headline'),20); note=clean_display(x.get('note'),22)
        if not headline: continue
        for k in wanted:
            if k in label and mapped[k] is None: mapped[k]=(headline,note)
    # Compatibility fallback from old labels.
    legacy={'为什么能卖':['商品定位','场景价值'],'值得继承':['主要产品资产','产品价值'],'下一款优先':['下一款优先方向','可强化方向']}
    for x in src:
        if not isinstance(x,dict): continue
        label=clean_display(x.get('label'),18); headline=clean_display(x.get('headline'),20)
        for target,keys in legacy.items():
            if mapped[target] is None and any(k in label for k in keys) and headline: mapped[target]=(headline,'')
    pd=arr((exp.get('productValue') or {}).get('items'))
    for x in pd:
        if not isinstance(x,dict): continue
        typ=clean_display(x.get('type'),16); val=first_text(x.get('value'),limit=30)
        if typ=='场景价值' and mapped['为什么能卖'] is None: mapped['为什么能卖']=(val,'')
        elif typ=='产品价值' and mapped['值得继承'] is None: mapped['值得继承']=(val,'')
        elif typ=='可强化方向' and mapped['下一款优先'] is None: mapped['下一款优先']=(val,'')
    title=clean_display((raw.get('product') or {}).get('title'),36)
    mapped['为什么能卖']=mapped['为什么能卖'] or (title or '当前商品场景与产品组合', '')
    mapped['值得继承']=mapped['值得继承'] or (f'已确认 {base.get("attributeCount",0)} 项产品参数', '')
    mapped['下一款优先']=mapped['下一款优先'] or ('规格更清楚 · 品质更可证 · 图片更好选', '')
    cards=[]
    for k in wanted:
        headline,note=mapped[k]
        cards.append(f'<article><span>{H(k)}</span><b>{H(headline)}</b>'+(f'<p>{H(note)}</p>' if note else '')+'</article>')
    return '<div class="v92-summary3 v924-decision3">'+''.join(cards)+'</div>'

def _overview(exp, raw, base, sales):
    cards=[]
    source=arr((exp.get('ownerOverview') or {}).get('cards'))
    preferred={'商品定位':None,'主要产品资产':None,'下一款优先方向':None}
    for x in source:
        if not isinstance(x,dict):continue
        label=clean_display(x.get('label'),18);headline=clean_display(x.get('headline'),42)
        if not headline:continue
        low=label+headline
        if preferred['商品定位'] is None and any(k in low for k in ('定位','场景','人群','商品定义')):preferred['商品定位']=headline
        elif preferred['主要产品资产'] is None and any(k in low for k in ('产品','材质','资产','体验','参数')):preferred['主要产品资产']=headline
        elif preferred['下一款优先方向'] is None and any(k in low for k in ('下一款','动作','优化','调整')):preferred['下一款优先方向']=headline
    pd=(exp.get('productValue') or {}).get('items') or []
    for x in pd:
        if not isinstance(x,dict):continue
        typ=clean_display(x.get('type'),16);val=clean_display(x.get('value'),42)
        if typ=='场景价值' and not preferred['商品定位']:preferred['商品定位']=val
        if typ=='产品价值' and not preferred['主要产品资产']:preferred['主要产品资产']=val
        if typ=='可强化方向' and not preferred['下一款优先方向']:preferred['下一款优先方向']=val
    title=clean_display((raw.get('product') or {}).get('title'),60)
    attrs=arr(raw.get('attributes'))
    attr_text=' / '.join(clean_display(x.get('value'),30) for x in attrs[:6] if isinstance(x,dict) and clean_display(x.get('value'),30))
    preferred['商品定位']=preferred['商品定位'] or title or '当前商品定位以页面事实为准'
    preferred['主要产品资产']=preferred['主要产品资产'] or clean_display(attr_text,70) or f'已采 {base.get("attributeCount",0)} 项商品参数'
    preferred['下一款优先方向']=preferred['下一款优先方向'] or '优先把规格、图片表达和商品页面口径统一'
    labels=[('商品定位',preferred['商品定位'],'先看这款商品解决什么场景'),('主要产品资产',preferred['主要产品资产'],'只保留当前证据可以确认的资产'),('下一款优先方向',preferred['下一款优先方向'],'把分析转成下一款动作')]
    return '<div class="v92-summary3">'+''.join(f'<article><span>{H(l)}</span><b>{H(v)}</b><p>{H(n)}</p></article>' for l,v,n in labels)+'</div>'

def _title_v92(raw, exp, a):
    block=exp.get('titleAnalysis') or (a.get('merchandisingDecision') or {}).get('titleAnalysis') or {}
    title=clean_display(block.get('originalTitle') or (raw.get('product') or {}).get('title'),130)
    opinion=first_text(block.get('professionalOpinion'),block.get('thesis'),limit=58) or '标题优先统一场景、规格与关键品质参数。'
    current=[]
    for x in arr(block.get('currentExpression'))[:6]:
        if isinstance(x,dict): t=first_text(x.get('value'),x.get('text'),limit=10)
        else: t=clean_display(x,14)
        if t and t not in current: current.append(t)
    if not current:
        for kw in ('大学生宿舍','学生宿舍','六件套','七件套','全棉','纯棉','40支','四季'):
            if kw in title: current.append(kw)
    reinforce=[]
    for x in arr(block.get('reinforce'))[:5]:
        t=first_text(x.get('topic') if isinstance(x,dict) else x,limit=14)
        if t and t not in reinforce: reinforce.append(t)
    actions=[first_text(x.get('action') if isinstance(x,dict) else x,limit=28) for x in arr(block.get('recommendedActions'))[:2]]
    if actions and not reinforce: reinforce=actions
    return _opinion(opinion)+f'<div class="v92-title-current"><small>当前标题</small>{H(title)}</div><div class="v924-title2"><article><span>已表达</span><b>{H(" · ".join(current[:5]) or "按当前标题识别")}</b></article><article><span>建议强化</span><b>{H(" · ".join(reinforce[:5]) or (actions[0] if actions else "规格统一 · 品质参数"))}</b></article></div>'

def _main_v92(exp,a,idx):
    block=exp.get('visualCommerce') or {}; vd=a.get('visualDecision') or {}
    opinion=first_text(block.get('professionalOpinion'),(vd.get('visualThesis') or {}).get('professionalOpinion'),limit=58) or '主图优先让用户看懂商品信息，再决定是否展开详细分析。'
    items=arr(block.get('items')) or arr(vd.get('imageRoles')) or arr(vd.get('mainImageContent'))
    byid={safe(x.get('imageEvidenceId')):x for x in items if isinstance(x,dict)}
    cards=[]
    for n,(eid,e) in enumerate(_entries(idx,'main',5),1):
        x=byid.get(eid,{})
        role=first_text(x.get('imageRole'),x.get('role'),x.get('contentTask'),limit=8) or f'主图{n}'
        signals=arr(x.get('visualSignals'))
        if not signals:
            # Compatibility: old message becomes one compact signal, never a paragraph.
            msg=first_text(x.get('message'),x.get('observation'),x.get('productSubject'),limit=14)
            if msg: signals=[msg]
        action=first_text(x.get('nextAction'),x.get('professionalAdvice'),x.get('nextProductAction'),x.get('action'),limit=18)
        copy=f'<div class="v925-image-info"><div class="v925-row-title"><h3>{H(role)}</h3><span>主图 {n:02d}</span></div>{_chips(signals)}'+(f'<p class="v925-action">专业动作 · {H(action)}</p>' if action else '')+'</div>'
        cards.append('<article class="v92-main-card v925-main-card">'+_visual_figure(e,'商品主图 '+str(n),'main-ratio')+copy+'</article>')
    continuity=_continuity_v92(exp,a)
    folded=f'<details class="v924-details"><summary>查看主图 × 详情 × 评论承接关系</summary>{continuity}</details>' if continuity else ''
    return _opinion(opinion)+'<div class="v92-main-grid">'+''.join(cards)+'</div>'+folded

def _status_label(kind,value):
    v=safe(value)
    maps={
      'main':{'expressed':('已表达','ok'),'partial':('部分表达','mid'),'missing':('未覆盖','none')},
      'detail':{'proven':('已证明','ok'),'partial':('部分证明','mid'),'missing':('未覆盖','none')},
      'review':{'validated':('有验证','ok'),'partial':('部分验证','mid'),'missing':('暂无验证','none')},
    }
    if v in maps.get(kind,{}):return maps[kind][v]
    low=v.lower()
    if any(k in low for k in ('closed','已表达','已证明','有反馈','已解释','有验证')):return ('已覆盖','ok')
    if any(k in low for k in ('partial','有限','部分','pending','待')):return ('部分','mid')
    if not v:return ('—','none')
    return (clean_display(v,18),'mid')

def _continuity_v92(exp,a):
    block=exp.get('expressionContinuity') or {};checks=arr(block.get('coreClaims')) or arr((a.get('detailDecision') or {}).get('continuityChecks'))
    rows=[]
    for x in checks[:6]:
        if not isinstance(x,dict):continue
        claim=clean_display(x.get('claim'),30)
        if not claim:continue
        ml,mc=_status_label('main',x.get('mainStatus') or x.get('mainImageRole') or ('expressed' if x.get('mainImageEvidenceIds') else ''))
        dl,dc=_status_label('detail',x.get('detailStatus') or x.get('detailProof') or ('proven' if x.get('detailEvidenceIds') else ''))
        rl,rc=_status_label('review',x.get('reviewStatus') or x.get('reviewValidation'))
        adv=first_text(x.get('professionalAdvice'),x.get('nextProductAction'),x.get('gap'),limit=45)
        rows.append(f'<tr><td><b>{H(claim)}</b></td><td class="{mc}">{H(ml)}</td><td class="{dc}">{H(dl)}</td><td class="{rc}">{H(rl)}</td><td>{H(adv or "继续保持页面口径一致")}</td></tr>')
    if not rows:return ''
    return '<div class="v92-table-wrap"><table class="v92-matrix"><thead><tr><th>核心表达</th><th>主图</th><th>详情</th><th>评论</th><th>动作</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'

def _detail_v92(exp,a,idx):
    block=exp.get('detailCommerce') or {}; dd=a.get('detailDecision') or {}
    opinion=first_text(block.get('professionalOpinion'),(dd.get('detailThesis') or {}).get('professionalOpinion'),limit=58) or '详情页优先展示能证明商品价值的代表图。'
    groups=arr(block.get('contentGroups')) or arr(dd.get('contentGroups'))
    entries=dict(_entries(idx,'detail',30)); cards=[]
    for i,x in enumerate(groups[:6],1):
        if not isinstance(x,dict): continue
        eid=safe(x.get('representativeImageId') or x.get('imageEvidenceId')); e=entries.get(eid)
        if not e and entries: e=list(entries.values())[min(i-1,len(entries)-1)]
        if not e: continue
        typ=first_text(x.get('type'),x.get('stage'),limit=10) or '详情信息'
        signals=arr(x.get('visualSignals'))
        if not signals:
            msg=first_text(x.get('message'),x.get('businessMeaning'),limit=14)
            if msg: signals=[msg]
        action=first_text(x.get('nextAction'),x.get('professionalAdvice'),x.get('nextPageAction'),limit=24)
        cards.append('<article class="v925-detail-block">'+_visual_figure(e,typ,'wide-ratio')+f'<div class="v925-detail-copy"><h3>{H(typ)}</h3>{_chips(signals)}'+(f'<p class="v925-action">专业动作 · {H(action)}</p>' if action else '')+'</div></article>')
    collected=len(entries)
    note=f'<div class="v92-evidence-note">详情图 {collected} 张 · 默认展示 {len(cards)} 个信息任务代表图；其余图片保留为证据。</div>'
    return _opinion(opinion)+('<div class="v925-detail-list">'+''.join(cards)+'</div>' if cards else '<div class="v92-empty">详情图片已采集，当前未形成可靠分组。</div>')+note

def _sku_dimensions(raw):
    product=raw.get('product') or {};title=safe(product.get('title'));attrs=arr(raw.get('attributes'));sku=arr(raw.get('sku'))
    dims=[]
    def add(name,vals,source=''):
        vals=[clean_display(x,24) for x in vals if clean_display(x,24)]
        if vals and name not in [d[0] for d in dims]:dims.append((name,vals[:5]))
    if '床单' in title or '床笠' in title:add('款式',[x for x in ('床单','床笠') if x in title])
    for x in attrs:
        if not isinstance(x,dict):continue
        n=safe(x.get('name'));v=safe(x.get('value'))
        if any(k in n for k in ('尺寸','床尺寸','规格')) and v:add('尺寸',[v])
        elif any(k in n for k in ('颜色','花色','图案','款式')) and v:add('花色/款式',[v])
        elif any(k in n for k in ('件数','套件','组合')) and v:add('套件',[v])
    if sku:
        names=[]
        for x in sku[:20]:
            if isinstance(x,dict):
                val=first_text(x.get('name'),x.get('title'),x.get('value'),x.get('properties'),limit=40)
                if val:names.append(val)
        if names:add('SKU规格',names)
    return dims[:4]

def _sku_v92(exp,a,raw,idx):
    block=exp.get('skuAnalysis') or a.get('skuVisualAnalysis') or {}
    entries=_entries(idx,'sku',30); structured=arr(raw.get('sku'))
    opinion=first_text(block.get('professionalOpinion'),limit=90)
    dims=[]
    for x in arr(block.get('selectionDimensions')):
        if not isinstance(x,dict):continue
        name=clean_display(x.get('name'),18);values=[clean_display(v,24) for v in arr(x.get('values')) if clean_display(v,24)]
        if name:dims.append((name,values))
    if not dims:dims=_sku_dimensions(raw)
    order=[clean_display(x,18) for x in arr(block.get('recommendedOrder')) if clean_display(x,18)] or [x[0] for x in dims]
    if not opinion:
        opinion='当前SKU更适合按清晰选择层级组织：先解决规格是否适配，再处理组合和外观偏好。'
    mosaic=''.join(_visual_figure(e,'SKU '+str(i+1),'square-ratio') for i,(eid,e) in enumerate(entries[:8]))
    steps=''.join(f'<div class="v92-choice-row"><span>{i:02d}</span><b>{H(name)}</b>'+(f'<small>{H(" / ".join(vals[:3]))}</small>' if vals else '')+'</div>' for i,(name,vals) in enumerate(dims or [(x,[]) for x in order],1))
    advice=first_text(block.get('recommendedAction'),limit=55) or ('建议按“'+' → '.join(order)+'”分层选择。' if order else '建议先建立规格层级，再展示外观选择。')
    status='结构化SKU '+(str(len(structured))+' 个' if structured else '未完整采集')+f' · SKU图片 {len(entries)} 张'
    return _opinion(opinion)+f'<div class="v92-sku-layout"><div class="v92-sku-mosaic">{mosaic}</div><div class="v92-choice">{steps}<div class="v92-choice-note">{H(advice)}</div><small class="v92-status">{H(status)}；SKU图片数量不等于SKU数量。</small></div></div>'

def _consumer_v92(exp,a,idx):
    block=exp.get('customerExperience') or {}; cr=a.get('consumerResearch') or {}; ci=block.get('consumerInsights') or {}
    opinion=first_text(block.get('professionalOpinion'),(cr.get('consumerThesis') or {}).get('statement'),limit=58) or '消费者反馈只保留可指导下一款的真实体验信号。'
    signals=arr(ci.get('experienceSignals'))
    if not signals:
        mapping=[('稳定体验',cr.get('satisfactionDrivers')),('体验差异',cr.get('expectationGaps')),('购前关注',cr.get('prePurchaseConcerns'))]
        for typ,values in mapping:
            for x in arr(values)[:1]: signals.append({'type':typ,'insight':text_of(x)})
    buyer=_entries(idx,'buyerShow',12)
    gallery=''.join(_visual_figure(e,'买家秀 '+str(i+1),'square-ratio') for i,(eid,e) in enumerate(buyer[:4]))
    rows=[]
    for x in signals[:4]:
        if not isinstance(x,dict): continue
        typ=clean_display(x.get('type'),16) or '消费者信号'; ins=first_text(x.get('insight'),x.get('statement'),x.get('driver'),x.get('problem'),limit=38)
        if ins: rows.append(f'<article><span>{H(typ)}</span><b>{H(ins)}</b></article>')
    gallery_html=gallery or '<div class="v92-empty">未采集买家秀图片</div>'
    rows_html=''.join(rows) or '<div class="v92-empty">当前评论尚未形成可靠聚合洞察</div>'
    return _opinion(opinion)+f'<div class="v92-review-layout"><div class="v92-buyer-grid">{gallery_html}</div><div class="v92-insights">{rows_html}</div></div>'

def _value_v92(exp,a):
    block=exp.get('productValue') or {};items=arr(block.get('items'))
    if not items:
        pd=a.get('productDecision') or {};pillars=arr(pd.get('valuePillars'))
        for x in pillars[:3]:
            if isinstance(x,dict):items.append({'type':clean_display(x.get('name'),18) or '产品价值','value':first_text(x.get('customerValue'),x.get('businessMeaning'),limit=40),'explanation':first_text(x.get('mustKeep'),limit=55)})
    if not items:
        items=[{'type':'场景价值','value':'当前商品使用场景','explanation':'以标题、参数与图片证据为准'},{'type':'产品价值','value':'当前商品核心配置','explanation':'只保留页面已确认参数'},{'type':'服务价值','value':'页面已展示服务','explanation':'不推断未采集服务'},{'type':'可强化方向','value':'规格与证明表达','explanation':'优先保证图片、参数、SKU口径一致'}]
    cards=[]
    for x in items[:4]:
        if not isinstance(x,dict):continue
        typ=clean_display(x.get('type'),18);val=first_text(x.get('value'),x.get('customerValue'),limit=42);desc=first_text(x.get('explanation'),x.get('commercialValue'),x.get('mustKeep'),limit=58)
        if val:cards.append(f'<article><span>{H(typ)}</span><b>{H(val)}</b>'+(f'<p>{H(desc)}</p>' if desc else '')+'</article>')
    return _opinion(block.get('professionalOpinion'))+'<div class="v92-value-grid">'+''.join(cards)+'</div>'

def _plan_action_list(values, limit=3):
    out=[]
    for x in arr(values)[:limit]:
        t=first_text(x.get('action') if isinstance(x,dict) else x,x.get('item') if isinstance(x,dict) else '',limit=55)
        if t:out.append(t)
    return out

def _plans_v92(exp,a,idx):
    block=exp.get('newProductPlans') or {}; source=arr(block.get('plans')) or arr((a.get('launchPlans') or {}).get('plans'))
    opinion=first_text(block.get('professionalOpinion'),(a.get('launchPlans') or {}).get('professionalOpinion'),limit=58) or '优先从证据最强的优化方向开始，再看反馈升级与探索方向。'
    cards=[]
    for i,x in enumerate(source[:3],1):
        if not isinstance(x,dict): continue
        source_type=first_text(x.get('sourceType'),limit=10)
        typ=first_text(x.get('type'),limit=14)
        if not source_type:
            source_type='证据驱动优化' if i==1 else ('反馈驱动升级' if i==2 else '探索性方向')
        name=first_text(x.get('name'),limit=22) or ('新品方向 '+str(i))
        why=first_text(x.get('whyThisPlan'),x.get('positioning'),limit=48)
        product=first_text(x.get('productAction'),limit=38)
        if not product:
            acts=_plan_action_list(x.get('productChanges'),1) or _plan_action_list(x.get('mustChange'),1); product=acts[0] if acts else ''
        page=first_text(x.get('pageAction'),limit=38)
        if not page:
            main=_plan_action_list(x.get('mainImagePlan'),1); detail=_plan_action_list(x.get('detailPagePlan'),1); page='；'.join((main+detail)[:2])
        refs=arr(x.get('visualReferenceImageIds')); ref_e=None
        for eid in refs:
            if eid in idx and (idx[eid].get('meta') or {}).get('group') in ('main','detail','sku'): ref_e=idx[eid]; break
        if not ref_e:
            mains=_entries(idx,'main',5); ref_e=mains[min(i-1,len(mains)-1)][1] if mains else None
        visual=_visual_figure(ref_e,'方案参考图','plan-ratio') if ref_e else '<div class="v92-plan-placeholder">当前商品视觉参考</div>'
        body=f'<div class="v925-plan-body"><div class="v925-plan-eyebrow">方案 {chr(64+i)} · {H(source_type)}</div><h3>{H(name)}</h3><dl>'+(f'<div><dt>产品</dt><dd>{H(product)}</dd></div>' if product else '')+(f'<div><dt>页面</dt><dd>{H(page)}</dd></div>' if page else '')+'</dl></div>'
        cards.append(f'<article class="v925-plan-card">{visual}{body}</article>')
    if not cards: return _opinion(opinion)+'<div class="v92-empty">当前证据未形成可追溯新品方案。</div>'
    return _opinion(opinion)+'<div class="v925-plan-grid">'+''.join(cards)+'</div>'

def render(a, task_id):
    a=ensure_experience_solution(a)
    if not (a.get('meta') or {}).get('reportReady'): raise ValueError((a.get('meta') or {}).get('reportBlockedReason') or '本次没有可输出的证据结论')
    raw=a.get('facts') or {}; product=raw.get('product') or {}; exp=a.get('experienceSolution') or {}; summary=exp.get('reportSummary') or {}
    title=clean_display(summary.get('title') or product.get('title') or '商品分析报告',60)
    payload=json.dumps(a,ensure_ascii=False,separators=(',',':')).replace('</','<\\/').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="generator" content="Sansong Product Intelligence V9.3.0"><title>'+H(title)+'</title><link rel="stylesheet" href="/report.css?v=20260911-modal-spec4"></head><body><main id="app" class="report-app"></main><script>window.REPORT_DATA='+payload+';</script><script src="/report.js?v=20260911-modal-spec4"></script></body></html>'
