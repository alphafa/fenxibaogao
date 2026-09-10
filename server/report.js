/* 独立报告视图：以分析 JSON 为唯一数据源，完整展示分析与证据。 */
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const arr = value => Array.isArray(value) ? value : [];
const compact = value => arr(value).map(item => typeof item === 'object' ? (item.value || item.topic || item.name || item.label || item.action || item.insight || '') : item).filter(Boolean).join(' · ');
const percent = value => `${(Number(value || 0) * 100).toFixed(1).replace('.0','')}%`;
let evidenceIndex = new Map();
const EMPTY_COPY = /^(暂无|无|未采集|未评级|尚未结构化|图片证据未采集|评论原文未采集|日期未采集)$/;
function hasContent(value) {
  if (value == null) return false;
  if (typeof value === 'string') return Boolean(value.trim()) && !EMPTY_COPY.test(value.trim());
  if (typeof value === 'number' || typeof value === 'boolean') return true;
  if (Array.isArray(value)) return value.some(hasContent);
  if (typeof value === 'object') return Object.values(value).some(hasContent);
  return false;
}

const FIELD_LABELS = {
  professionalOpinion:'专业判断', positioning:'商品定位', statement:'结论', decisionImpact:'决策意义', valuePillars:'核心产品资产',
  claimVsProof:'卖点与证明', positioningRisks:'定位风险', title:'标题表达', visual:'主图与视觉', detail:'详情页信息链',
  consumerInsights:'消费者洞察', experienceSignals:'体验信号', productImplications:'产品需求', buyerEvidence:'买家秀验证',
  sku:'SKU结构', product:'产品与供应链', parameterFacts:'参数事实', gates:'风险与验证门', baseline:'样本基线',
  fashionThesis:'视觉方向', designAssets:'视觉资产', styleSignals:'风格信号', fashionRisks:'视觉风险', trendBoundary:'趋势边界',
  chapterTitle:'章节', cards:'决策卡', status:'审核状态', validation:'审核结果', scope:'审核范围', checks:'检查项', missing:'缺失项',
  customerValue:'消费者价值', businessMeaning:'经营意义', mustKeep:'必须保留', commercialRisk:'商业风险', businessImpact:'业务影响',
  action:'执行动作', nextAction:'下一步动作', developmentAction:'开发动作', observation:'观察', risk:'风险', why:'原因',
  originalTitle:'当前标题', currentExpression:'已经表达', reinforce:'建议强化', recommendedActions:'推荐动作', recommendedTitles:'标题建议',
  contentGroups:'信息任务', pageSequence:'页面顺序', selectionDimensions:'选择维度', recommendedOrder:'推荐选择顺序', recommendedAction:'推荐动作',
  evidenceIds:'证据', confidence:'置信度', name:'名称', type:'类型', value:'内容', label:'标签', headline:'结论', note:'说明', bullets:'要点',
  claim:'卖点', productAction:'产品动作', pageAction:'页面动作', commercialMeaning:'商业意义', whatItMeansForProduct:'对产品的意义',
  asset:'资产', signal:'信号', field:'字段', actual:'实际', minimum:'最低要求', ok:'通过', originalTitle:'当前标题',
  currentExpression:'已表达信息', reinforce:'建议强化', recommendedTitles:'标题建议', items:'图片任务', evidenceDetail:'补充证据',
  representativeImageIds:'代表图片', structuredStatus:'结构状态', structuredCount:'结构化SKU数', imageCount:'图片数', reviewCount:'评论样本',
  questionCount:'问答样本', ratingBuckets:'评分分布', topics:'评论主题', skuBreakdown:'SKU反馈', imageCounts:'图片统计', skuCount:'SKU数',
  attributeCount:'属性数', promotionCount:'促销信息数', reviewCollectionComplete:'评论采集完成', reviewStopReason:'采集停止原因',
  publicReviewCount:'页面公开评论', reviewPagesVisited:'评论访问页数', buyerEvidence:'买家秀证据', stages:'消费阶段', signals:'反馈信号',
  positive:'正向反馈', questions:'用户疑问', risks:'风险反馈', fashionThesis:'视觉主张', commercialValue:'商业价值', trendBoundary:'趋势判断边界',
  fashionRisks:'视觉风险', designAssets:'设计资产', styleSignals:'风格信号', validation:'审核结果', scope:'审核范围',
  structuredStatus:'结构化状态', status:'状态', gate:'验证门', examples:'评论原话', mentions:'提及次数', sampleRate:'样本占比'
};
Object.assign(FIELD_LABELS,{
  all:'全部图片',batchFindings:'批次发现',buyerShow:'买家实拍',compareDimensions:'对比维度',composition:'构图信息',concern:'购前顾虑',concerns:'购前顾虑',
  consumerThesis:'消费者结论',conversionImpact:'转化影响',coreClaims:'核心卖点',coreStory:'核心表达链',decision:'决策',decisionGates:'决策门槛',decisionQuestion:'决策问题',deemphasize:'降低强调',
  detailStatus:'详情证明状态',driver:'驱动因素',evidenceId:'证据编号',executiveDecision:'经营决策',expectationGaps:'预期差异',expected:'用户预期',finding:'分析发现',fixAction:'修正动作',
  grade:'数据等级',hypothesis:'验证假设',ifOnlyOneAction:'唯一优先动作',imageEvidenceId:'图片证据编号',imageRole:'图片任务',imageRoles:'图片任务分工',images:'图片统计',
  isProductRiskOrInfoGap:'问题性质',item:'项目',keepAction:'保留动作',knownLimitations:'已知限制',mainStatus:'主图表达状态',mechanism:'作用机制',metrics:'验收指标',module:'分析模块',
  mustFix:'必须修正',oneSentence:'一句话结论',owner:'负责人',pageFix:'页面修正',painPoints:'用户痛点',patternColor:'花型与颜色',prePurchaseConcerns:'购前关注',prePurchaseThesis:'购前判断',
  primaryQuestions:'核心问题',priority:'优先级',problem:'问题',productOpportunity:'产品机会',productSubject:'商品主体',promotionAnalysis:'促销分析',purchaseDrivers:'购买驱动',question:'用户问题',
  questionConcern:'问答关注点',questionSample:'问答样本',reason:'原因',representativeQuotes:'代表评论',requiredCompetitorSet:'所需竞品样本',reviewReality:'评论实际反馈',reviewSample:'评论样本',
  reviewStatus:'评论验证状态',role:'作用',rows:'验证步骤',satisfactionDrivers:'满意驱动',sectionPlan:'章节计划',severity:'严重程度',skuSignals:'规格反馈',stage:'验证阶段',successMeaning:'通过标准',
  text:'原文',textInfo:'图中文字',titleAnalysis:'标题分析',unansweredQuestions:'未解决问题',validatedByReviews:'评论验证结果',valuePillars:'价值支柱',verbatimQuotes:'评论原话',verdict:'最终判断',
  visualSignals:'视觉信号',visualThesis:'视觉结论',whatUserIsBuying:'用户实际购买价值',whyItBlocksPurchase:'阻碍购买原因',whyItSells:'购买理由',main:'主图',detail:'详情图',sku:'规格结构'
});

const ROLE_META = [
  ['productStrategy','01','商品策略','卖什么、为什么值得参考、下一款继承什么'],
  ['conversion','02','电商转化','用户为什么点、为什么继续看、为什么愿意买'],
  ['consumerInsight','03','消费者洞察','把评论和买家秀转成真实产品需求'],
  ['productSupply','04','产品 / 供应链','哪些能落地、哪些必须验证'],
  ['visualDesign','05','视觉设计','提炼下一款可复用的视觉资产'],
  ['executiveDecision','06','商业决策 / 老板','把专业判断压成直接决策'],
  ['editorReview','07','总编审核','统一校验、纠错、去重与压缩']
];

function imageEntries(data, group) {
  return arr(data.evidenceLedger).filter(item => item?.type === 'image' && item?.meta?.group === group);
}
function imageUrl(item) { return item?.meta?.localUrl || item?.value || ''; }
function figure(item, caption='', className='') {
  if (!item || !imageUrl(item)) return '';
  const source = esc(imageUrl(item));
  return `<figure class="report-figure ${esc(className)}" data-evidence-id="${esc(item.id || '')}"><span class="report-image-stage"><img class="report-image-product" loading="lazy" src="${source}" alt="${esc(caption || '商品图片')}"></span></figure>`;
}
function section(id, no, title, deck, body) {
  if (!hasContent(body)) return '';
  return `<section id="${esc(id)}" class="report-section"><div class="wrap"><header class="report-heading"><span>${esc(no)}</span><div><h2>${esc(title)}</h2><p>${esc(deck)}</p></div></header>${body}</div></section>`;
}
function decisionCards(items) {
  const valid=arr(items).filter(item=>hasContent(item?.headline)||hasContent(item?.name)||hasContent(item?.note)||hasContent(item?.bullets));
  return valid.length ? `<div class="decision-grid">${valid.map(item => `<article>${hasContent(item.label||item.type)?`<span>${esc(item.label||item.type)}</span>`:''}${hasContent(item.headline||item.name)?`<h3>${esc(item.headline||item.name)}</h3>`:''}${hasContent(item.note)?`<p>${esc(item.note)}</p>`:''}${hasContent(item.bullets)?`<ul>${arr(item.bullets).filter(hasContent).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}</article>`).join('')}</div>` : '';
}
function planCards(items) {
  const tone = item => String(item?.sourceType || '').includes('探索') ? 'explore' : String(item?.sourceType || '').includes('反馈') ? 'upgrade' : 'evidence';
  const valid=arr(items).map((item,index)=>({item,index})).filter(({item})=>hasContent(item));
  return valid.length ? `<div class="plan-grid">${valid.map(({item,index}) => {const rows=[['产品开品',item.productAction],['主图 / 详情打造',item.pageAction]].filter(([,value])=>hasContent(value));return `<article class="plan-card plan-${tone(item)}">${hasContent(item.sourceType||item.type)?`<span>${esc(item.sourceType||item.type)}</span>`:''}${hasContent(item.name)?`<h3>${esc(item.name)}</h3>`:''}${rows.length?`<dl>${rows.map(([label,value])=>`<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`:''}<button class="generate-plan-btn" type="button" data-plan-index="${index}">打造这款产品 <span>→</span></button></article>`}).join('')}</div>` : '';
}
function titleAnalysis(block) {
  const expressed = compact(block.currentExpression);
  const reinforce = arr(block.reinforce).map(x=>x?.topic || x?.value || x).filter(Boolean).join(' · ');
  const compare=[['已经表达',expressed],['建议强化',reinforce||compact(block.recommendedActions)]].filter(([,value])=>hasContent(value));
  return `${hasContent(block.professionalOpinion)?`<p class="lead-opinion">${esc(block.professionalOpinion)}</p>`:''}${hasContent(block.originalTitle)?`<div class="current-title"><span>当前标题</span>${esc(block.originalTitle)}</div>`:''}${compare.length?`<div class="title-compare">${compare.map(([label,value])=>`<article><span>${label}</span><b>${esc(value)}</b></article>`).join('')}</div>`:''}${hasContent(block.recommendedTitles)?`<details class="evidence-drawer"><summary>查看推荐标题</summary><ol>${arr(block.recommendedTitles).filter(hasContent).map(x=>`<li>${esc(x)}</li>`).join('')}</ol></details>`:''}`;
}
function mainImages(data, block) {
  const entries = new Map(imageEntries(data,'main').map(item=>[item.id,item]));
  const items=arr(block.items).filter(item=>hasContent(item)&&entries.get(item.imageEvidenceId));
  return `${hasContent(block.professionalOpinion)?`<p class="lead-opinion">${esc(block.professionalOpinion)}</p>`:''}${items.length?`<div class="main-analysis-grid">${items.map(item=>`<article>${figure(entries.get(item.imageEvidenceId), item.imageRole || '商品主图')}<div class="image-copy"><span>主图分析</span>${hasContent(item.imageRole)?`<h3>${esc(item.imageRole)}</h3>`:''}${hasContent(item.visualSignals)?`<b>${esc(compact(item.visualSignals))}</b>`:''}${hasContent(item.businessMeaning)?`<p>${esc(item.businessMeaning)}</p>`:''}${hasContent(item.nextAction)?`<em>${esc(item.nextAction)}</em>`:''}</div></article>`).join('')}</div>`:''}`;
}
function classifyDetailGroup(group) {
  const keyed = {
    scene_problem: [10, '场景证明', '先回答为什么需要'],
    material_proof: [20, '材质证明', '证明产品基础'],
    structure_proof: [30, '结构工艺', '证明结构如何实现'],
    function_proof: [40, '功能表现', '证明使用表现'],
    spec_adaptation: [50, '规格适配', '降低选择门槛'],
    care_durability: [60, '使用维护', '说明洗护与长期使用']
  };
  if (keyed[group?.contentKey]) {
    const [sequencePriority, sequenceLabel, sequenceHint] = keyed[group.contentKey];
    return {...group, sequencePriority, sequenceLabel, sequenceHint};
  }
  const source = `${group?.type || ''} ${group?.stage || ''}`;
  const rules = [
    [/场景|人群|体验|需求/,10,'使用场景','先回答为什么需要'],
    [/卖点|利益|价值/,15,'核心利益','再说明能带来什么'],
    [/材质|面料|成分|填充/,20,'材质证明','证明产品基础'],
    [/工艺|细节|结构|做工/,30,'工艺细节','证明品质如何实现'],
    [/耐用|性能|功能|洗涤|防护|透气/,40,'性能验证','证明长期使用表现'],
    [/规格|尺寸|SKU|选择|适配/,50,'规格选择','降低选择门槛'],
    [/洗护|护理|清洁|耐用/,60,'使用维护','说明洗护与长期使用']
  ];
  const found = rules.find(([pattern])=>pattern.test(source));
  return found ? {...group,sequencePriority:found[1],sequenceLabel:found[2],sequenceHint:found[3]} : {...group,sequencePriority:70,sequenceLabel:'补充证据',sequenceHint:'补充未覆盖的信息'};
}
function detailProof(data, block) {
  const allImages = arr(data.evidenceLedger).filter(item=>item?.type === 'image');
  const byId = new Map(allImages.map(item=>[item.id,item]));
  const detailImages = imageEntries(data,'detail');
  const groups = arr(block.contentGroups).filter(hasContent).slice(0,6).map(classifyDetailGroup).sort((a,b)=>a.sequencePriority-b.sequencePriority);
  const used = new Set();
  const rows = groups.map((group,index) => {
    const image = byId.get(group.representativeImageId || group.imageEvidenceId);
    if (image) used.add(image.id);
    const imageGroup = image?.meta?.group;
    const badge = imageGroup === 'detail' ? '详情代表图' : imageGroup === 'main' ? '主图补充证据' : '图片证据';
    return `<article class="detail-proof-row">${image?`<div class="detail-proof-media">${figure(image, group.type || '详情任务')}</div>`:''}<div class="detail-proof-copy">${hasContent(group.sequenceLabel)?`<span>${esc(group.sequenceLabel)}</span>`:''}${hasContent(group.type)?`<h3>${esc(group.type)}</h3>`:''}${hasContent(group.visualSignals)||hasContent(group.businessMeaning)?`<b>${esc(compact(group.visualSignals)||group.businessMeaning)}</b>`:''}${hasContent(group.businessMeaning)?`<p>${esc(group.businessMeaning)}</p>`:''}${hasContent(group.nextAction)?`<div class="next-action"><small>下一步动作</small>${esc(group.nextAction)}</div>`:''}</div></article>`;
  }).join('');
  return `${hasContent(block.professionalOpinion)?`<p class="lead-opinion">${esc(block.professionalOpinion)}</p>`:''}${groups.length?`<nav class="detail-sequence">${groups.map(group=>`<span><b>${esc(group.sequenceLabel)}</b>${hasContent(group.type)?`<small>${esc(group.type)}</small>`:''}</span>`).join('')}</nav>`:''}${rows?`<div class="detail-proof-list">${rows}</div>`:''}${detailImages.length?`<details class="evidence-drawer"><summary>查看全部详情图证据 <b>${detailImages.length} 张</b></summary><p class="drawer-note">默认展示信息任务代表图，其余图片作为完整证据保留。</p><div class="evidence-gallery">${detailImages.map(item=>figure(item,'详情图')).join('')}</div></details>`:''}`;
}
function skuAnalysis(block) {
  const dimensions=arr(block.selectionDimensions).filter(item=>hasContent(item?.name)||hasContent(item?.values));
  return `${hasContent(block.professionalOpinion)?`<p class="lead-opinion">${esc(block.professionalOpinion)}</p>`:''}${dimensions.length?`<div class="sku-grid">${dimensions.map(item=>`<article>${hasContent(item.name)?`<span>${esc(item.name)}</span>`:''}${hasContent(item.values)?`<h3>${esc(compact(item.values))}</h3>`:''}</article>`).join('')}</div>`:''}${hasContent(block.recommendedAction)?`<div class="action-banner"><span>推荐动作</span><b>${esc(block.recommendedAction)}</b></div>`:''}`;
}
function topicBars(base) {
  const topics = arr(base.topics).slice(0,8);
  if (!topics.length) return '';
  return `<div class="topic-panel"><header><div><span>评论关注主题</span><h3>用户实际在讨论什么</h3></div><small>主题可重叠，比例不应相加为100%</small></header><div class="topic-bars">${topics.map(item=>{const rate = Number(item.sampleRate ?? (base.reviewCount ? item.mentions/base.reviewCount : 0)); return `<div class="topic-row"><span>${esc(item.topic)}</span><div class="topic-track"><i style="width:${Math.max(2,Math.min(100,rate*100))}%"></i></div><b>${Number(item.mentions || 0)}次</b><em>${percent(rate)}</em></div>`}).join('')}</div></div>`;
}
function buyerGallery(data, block) {
  const items = arr(block?.buyerEvidence?.items);
  const byId = new Map(arr(data.evidenceLedger).map(item=>[item.id,item]));
  const grouped = new Map();
  items.forEach(item=>{
    const key = item.reviewEvidenceId || item.imageEvidenceId;
    if (!grouped.has(key)) grouped.set(key,{reviewId:item.reviewEvidenceId,quote:item.quote,date:item.date,sku:item.sku,scenario:item.scenario || item.context,insight:item.insight || item.conclusion || item.businessMeaning,images:[]});
    grouped.get(key).images.push(byId.get(item.imageEvidenceId));
  });
  if (!grouped.size) {
    const loose = imageEntries(data,'buyerShow');
    return loose.length ? `<div class="buyer-story"><div class="buyer-photo-grid">${loose.map(item=>figure(item,item.id)).join('')}</div><p>买家秀已采集，尚未关联到具体评论。</p></div>` : '';
  }
  return [...grouped.values()].filter(group=>group.images.some(Boolean)||hasContent(group.quote)||hasContent(group.sku)).map((group,index)=>`<article class="buyer-story"><div class="buyer-story-head"><span>案例 ${String(index+1).padStart(2,'0')}${hasContent(group.reviewId)?` · ${esc(group.reviewId)}`:''}</span><small>${group.images.filter(Boolean).length} 张实拍图${hasContent(group.date)?` · ${esc(group.date)}`:''}</small></div>${group.images.some(Boolean)?`<div class="buyer-photo-grid">${group.images.filter(Boolean).map(item=>figure(item,'')).join('')}</div>`:''}${hasContent(group.scenario)?`<p class="case-scenario"><b>使用场景</b>${esc(group.scenario)}</p>`:''}${hasContent(group.quote)?`<blockquote>“${esc(group.quote)}”</blockquote>`:''}${hasContent(group.insight)?`<p class="case-insight"><b>案例结论</b>${esc(group.insight)}</p>`:''}${hasContent(group.sku)?`<p><b>SKU</b> ${esc(group.sku)}</p>`:''}</article>`).join('');
}
function reviews(data, block) {
  const base = data.baseline || {};
  const quality = data.dataQuality || {};
  const signals = arr(block?.consumerInsights?.experienceSignals).filter(item=>hasContent(item?.insight)||hasContent(item?.statement));
  const research = data.consumerResearch || {};
  const batchFindings = arr(data.reviewBatchAnalysis).flatMap(batch => arr(batch?.batchFindings));
  const issues = [
    ...arr(research.painPoints).map(item => ({label:'用户痛点', title:item.problem, impact:item.businessImpact, action:item.productAction, evidence:item.evidenceIds, tone:'risk'})),
    ...arr(research.expectationGaps).map(item => ({label:'预期落差', title:`${item.expected} → ${item.actual}`, impact:item.commercialRisk, action:item.productOpportunity, evidence:item.evidenceIds, tone:'gap'})),
    ...arr(research.prePurchaseConcerns).map(item => ({label:'购前疑问', title:item.concern, impact:item.conversionImpact, action:item.pageAction, evidence:item.evidenceIds, tone:'question'}))
  ];
  const fallbackIssues = batchFindings.filter(item=>['pain','expectation_gap','prepurchase_concern'].includes(item.type)).map(item=>({label:item.type==='pain'?'用户痛点':item.type==='expectation_gap'?'预期落差':'购前疑问',title:item.finding,impact:item.businessMeaning,action:'转为产品、页面或履约验证动作',evidence:item.evidenceIds,tone:item.type==='pain'?'risk':'gap'}));
  const issueCards = (issues.length ? issues : fallbackIssues).filter(item=>hasContent(item.title)||hasContent(item.impact)||hasContent(item.action)).slice(0,4).map(item=>`<article class="problem-card ${esc(item.tone || 'risk')}">${hasContent(item.label)?`<span>${esc(item.label)}</span>`:''}${hasContent(item.title)?`<h4>${esc(item.title)}</h4>`:''}${hasContent(item.impact)?`<p><b>影响</b> ${esc(item.impact)}</p>`:''}${hasContent(item.action)?`<p><b>动作</b> ${esc(item.action)}</p>`:''}${arr(item.evidence).length?`<small>${arr(item.evidence).length} 条对应证据</small>`:''}</article>`).join('');
  const completed = Boolean(base.reviewCollectionComplete);
  const stopText = completed ? '已到达可访问末页' : base.reviewStopReason === 'user_stopped' ? '用户主动停止，当前为样本分析' : '采集未确认完成';
  const reviewCount = base.reviewCount ?? quality.reviewSample;
  const publicCount = base.publicReviewCount ?? quality.publicReviewCount;
  const stats = [['本次有效评论',reviewCount],['页面公开数量',publicCount],['访问页数',base.reviewPagesVisited],['样本状态',stopText,completed?'complete':'limited']].filter(([,value])=>hasContent(value));
  const topics = topicBars(base);
  const signalHtml = signals.length ? `<div class="signal-panel"><header><span>结论层</span><h3>认可、差异与购前顾虑</h3></header>${signals.map(item=>`<article class="signal-card">${hasContent(item.type)?`<span>${esc(item.type)}</span>`:''}<h4>${esc(item.insight||item.statement)}</h4>${arr(item.evidenceIds).length?`<small>${arr(item.evidenceIds).length} 条对应证据</small>`:''}</article>`).join('')}</div>` : '';
  const buyers = buyerGallery(data,block);
  return `${hasContent(block.professionalOpinion)?`<p class="lead-opinion">${esc(block.professionalOpinion)}</p>`:''}${stats.length?`<div class="sample-strip">${stats.map(([label,value,tone])=>`<article class="${tone||''}"><span>${label}</span><b>${esc(value)}</b></article>`).join('')}</div>`:''}${topics||signalHtml?`<div class="review-visual-grid">${topics}${signalHtml}</div>`:''}${issueCards?`<div class="problem-section"><header><span>问题洞察</span><h3>用户讨论暴露了哪些需要解决的问题</h3><p>从痛点、预期落差和购前疑问转成可执行动作</p></header><div class="problem-grid">${issueCards}</div></div>`:''}${buyers?`<div class="buyer-section"><header><span>买家秀验证</span><h3>图片按评论合并，不把多张图重复计算为多人反馈</h3></header>${buyers}</div>`:''}`;
}
const ROLE_DENSE_FIELDS = new Set(['baseline','buyerEvidence','signals','stages','evidenceDetail']);
function displayValue(value) {
  if (typeof value === 'boolean') return value ? '是' : '否';
  const status = {
    passed:'已通过',confirmed:'已确认',missing:'缺失',partial:'部分满足',unknown:'待确认',high:'高风险',medium:'中风险',low:'低风险',
    consumer_supported:'评论支持',conflicted:'存在冲突',page_claim_only:'仅页面宣称',not_enough_evidence:'证据不足',user_stopped:'用户主动停止',
    expressed:'主图已表达',proven:'详情已证明',validated:'评论已验证',main_missing:'主图未表达',detail_missing:'详情未证明',review_pending:'等待评论验证',closed_loop:'证据闭环',conflict:'存在冲突',
    product_risk:'产品风险',information_gap:'信息缺口',purchase_driver:'购买驱动',satisfaction:'满意因素',pain:'用户痛点',expectation_gap:'预期差异',prepurchase_concern:'购前顾虑',sku_signal:'规格反馈',usage_scene:'使用场景',
    complete:'采集完成',limited:'样本有限',collected:'已采集',ready:'已就绪',normal:'一般',good:'良好',risk:'风险',true:'是',false:'否'
  };
  return status[value] || value;
}
function itemTitle(item) {
  return item?.headline || item?.name || item?.type || item?.asset || item?.signal || item?.claim || item?.risk || item?.gate || item?.topic || item?.field || '';
}
function evidenceType(item, id='') {
  if (item?.type === 'image') return ({main:'商品主图',detail:'详情图片',buyerShow:'买家秀'})[item?.meta?.group] || '图片证据';
  if (item?.type === 'review' || id.startsWith('REV_')) return '用户评论';
  if (item?.type === 'question' || id.startsWith('QA_')) return '用户问答';
  if (item?.type === 'attribute' || id.startsWith('ATTR_')) return '商品属性';
  if (item?.type === 'promotion' || id.startsWith('PROMO_')) return '促销信息';
  if (item?.type === 'sales' || id.startsWith('S_')) return '页面数据';
  if (item?.type === 'product' || id.startsWith('P_')) return '商品信息';
  return '证据';
}
function evidenceText(item, id='') {
  const value = item?.value;
  if (item?.type === 'image') return ({main:'商品主图采集',detail:'详情页图片采集',buyerShow:'评论买家秀采集'})[item?.meta?.group] || '页面图片采集';
  if (item?.type === 'attribute') return `${value?.name || '属性'}：${value?.value ?? ''}`;
  if (item?.type === 'review') return value?.content || value?.appendContent || '评论内容未采集';
  if (item?.type === 'question') return value?.question || '问答内容未采集';
  if (item?.type === 'promotion') return value?.text || '促销内容未采集';
  const labels = {P_TITLE:'商品标题',P_SHOP:'店铺信息',P_ITEMID:'商品ID',P_SKUID:'SKU ID',S_CURRENTPRICE:'当前价格',S_SOLD:'页面销量',S_RANKING:'榜单排名'};
  return `${labels[id] ? `${labels[id]}：` : ''}${typeof value === 'object' ? compact(Object.values(value)) : (value ?? '未采集')}`;
}
function readableEvidence(id) {
  const item = evidenceIndex.get(id);
  if (!item || !hasContent(item.value)) return '';
  const text = evidenceText(item,id);
  const preview = text.length > 120 ? `${text.slice(0,120)}…` : text;
  const image = item?.type === 'image' && imageUrl(item) ? `<img loading="lazy" src="${esc(imageUrl(item))}" alt="${esc(evidenceType(item,id))}">` : '';
  return `<article class="role-evidence-item ${image?'has-image':''}">${image}<div><b>${esc(evidenceType(item,id))}</b><p>${esc(preview)}</p><code>${esc(id)}</code></div></article>`;
}
function renderStructured(value, depth=0) {
  if (!hasContent(value)) return '';
  if (typeof value !== 'object') return `<p>${esc(displayValue(value))}</p>`;
  if (Array.isArray(value)) {
    const valid=value.filter(hasContent);
    if (!valid.length) return '';
    if (valid.every(item=>typeof item !== 'object')) return `<div class="role-chip-list">${valid.map(item=>`<span>${esc(displayValue(item))}</span>`).join('')}</div>`;
    return `<div class="structured-list">${valid.map(item=>{const title=itemTitle(item);const inner=renderStructured(Object.fromEntries(Object.entries(item || {}).filter(([key])=>!title || !['headline','name','type','asset','signal','claim','risk','gate','topic','field'].includes(key))),depth+1);return title||inner?`<article class="structured-card">${title?`<header><span>${esc(displayValue(title))}</span></header>`:''}${inner}</article>`:''}).join('')}</div>`;
  }
  return `<div class="structured-object">${Object.entries(value).map(([key,item])=>{
    if (!hasContent(item)) return '';
    const label = FIELD_LABELS[key] || key;
    if (key === 'confidence') return `<div class="role-confidence"><span>${esc(label)}</span><i><b style="width:${Math.max(0,Math.min(100,Number(item)*100))}%"></b></i><strong>${percent(item)}</strong></div>`;
    if (key === 'evidenceIds') { const ids=arr(item).filter(id=>evidenceIndex.has(id)&&hasContent(evidenceIndex.get(id)?.value)); if(!ids.length)return ''; const sources=[...new Set(ids.map(id=>evidenceType(evidenceIndex.get(id),id)))]; return `<details class="role-evidence"><summary>查看证据 · ${ids.length} 条${sources.length?` · ${esc(sources.join(' / '))}`:''}</summary><div class="role-evidence-list">${ids.map(readableEvidence).join('')}</div></details>`; }
    const dense = depth > 0 && (key === 'examples' || key === 'skuBreakdown');
    if (dense) return `<details class="role-raw"><summary>${esc(label)} · ${arr(item).length} 项</summary>${renderStructured(item,depth+1)}</details>`;
    return `<div class="structured-field"><span>${esc(label)}</span>${renderStructured(item,depth+1)}</div>`;
  }).join('')}</div>`;
}
function roleConclusion(key, content) {
  if (content?.professionalOpinion) return content.professionalOpinion;
  if (key === 'productStrategy') return content?.positioning?.statement || '';
  if (key === 'conversion') return [content?.title?.professionalOpinion,content?.visual?.professionalOpinion,content?.detail?.professionalOpinion].filter(Boolean).join(' ');
  if (key === 'productSupply') return content?.sku?.professionalOpinion || content?.product?.gates?.[0]?.gate || '';
  if (key === 'visualDesign') return content?.fashionThesis?.statement || '';
  if (key === 'executiveDecision') return arr(content?.cards).map(item=>item.headline).filter(Boolean).slice(0,3).join('；');
  if (key === 'editorReview') return content?.status === 'passed' ? '本次报告已通过事实、证据、对象匹配和表达一致性审核。' : '报告仍有需要复核的项目。';
  return '';
}
function roleOutputs(roles) {
  const visible=ROLE_META.map(([key,no,title,deck])=>{const content=roles?.[key];if(!hasContent(content))return '';const sections=Object.entries(content).filter(([field,value])=>field!=='professionalOpinion'&&hasContent(value)&&hasContent(renderStructured(value)));const conclusion=roleConclusion(key,content);if(!hasContent(conclusion)&&!sections.length)return '';return `<details class="role-block role-${esc(key)}" ${key === 'productStrategy' ? 'open' : ''}><summary><span>${no}</span><div><h3>${esc(title)}</h3><p>${esc(deck)}</p></div><b>${sections.length} 个分析模块</b></summary><div class="role-content">${hasContent(conclusion)?`<article class="role-conclusion"><span>核心判断</span><p>${esc(conclusion)}</p></article>`:''}${sections.length?`<div class="role-section-list">${sections.map(([field,value],index)=>`<details class="role-section" ${index===0&&!ROLE_DENSE_FIELDS.has(field)?'open':''}><summary><span>${esc(FIELD_LABELS[field]||field)}</span><b>${Array.isArray(value)?`${value.filter(hasContent).length} 项`:'查看分析'}</b></summary><div class="role-section-body">${renderStructured(value)}</div></details>`).join('')}</div>`:''}</div></details>`}).filter(Boolean);
  return visible.length ? `<div class="role-list">${visible.join('')}</div>` : '';
}
function supportAnalysis(data) {
  const exp=data.experienceSolution||{};
  const blocks=[
    ['reportPlan','报告分析计划',data.reportPlan],
    ['dataQuality','数据质量与样本边界',data.dataQuality],
    ['reviewBatchAnalysis','评论批次分析',data.reviewBatchAnalysis],
    ['productExperience','产品与供应链核验',exp.productExperience],
    ['validationLoop','验证闭环',exp.validationLoop],
    ['expressionContinuity','卖点承接检查',exp.expressionContinuity],
    ['consumerResearch','消费者研究明细',data.consumerResearch],
    ['questionResearch','购前问答研究',data.questionResearch],
    ['commercialDecision','商业决策依据',data.commercialDecision],
    ['competitionDecision','单品边界与竞品数据',data.competitionDecision],
    ['merchandisingDecision','经营表达决策明细',data.merchandisingDecision],
    ['productDecision','产品决策明细',data.productDecision],
    ['visualDecision','视觉决策明细',data.visualDecision]
  ].filter(([, ,value])=>hasContent(value));
  if(!blocks.length)return '';
  return `<div class="support-analysis-grid">${blocks.map(([key,title,value])=>`<details class="support-analysis-card"><summary><span>${esc(title)}</span><b>查看内容</b></summary><div class="support-analysis-body">${renderStructured(value)}</div></details>`).join('')}</div>`;
}
function initHeroCarousel() {
  const root = document.querySelector('.hero-carousel');
  if (!root) return;
  const slides = [...root.querySelectorAll('.hero-slide')], dots = [...root.querySelectorAll('.hero-dot')], cards = [...root.querySelectorAll('.hero-deck-card')];
  if (slides.length < 2) return;
  let current = 0, timer;
  const show = index => {
    current = (index + slides.length) % slides.length;
    slides.forEach((slide,i)=>{slide.classList.toggle('active',i===current); slide.setAttribute('aria-hidden',i===current?'false':'true')});
    dots.forEach((dot,i)=>{dot.classList.toggle('active',i===current); dot.setAttribute('aria-current',i===current?'true':'false')});
    const step = window.innerWidth <= 560 ? 26 : window.innerWidth <= 800 ? 34 : 58;
    const angle = window.innerWidth <= 560 ? 5 : 6;
    const center = (cards.length - 1) / 2;
    cards.forEach((card,i)=>{const slot=i-center;card.classList.toggle('active',i===current);card.setAttribute('aria-current',i===current?'true':'false');card.style.setProperty('--deck-x',`${slot*step}px`);card.style.setProperty('--deck-r',`${slot*angle}deg`)});
    const count = root.querySelector('.hero-carousel-count');
    if (count) count.textContent = `${String(current+1).padStart(2,'0')} / ${String(slides.length).padStart(2,'0')}`;
  };
  const stop = () => clearInterval(timer);
  const start = () => { stop(); if (!matchMedia('(prefers-reduced-motion: reduce)').matches) timer=setInterval(()=>show(current+1),5000); };
  root.querySelector('[data-carousel-prev]')?.addEventListener('click',()=>{show(current-1);start()});
  root.querySelector('[data-carousel-next]')?.addEventListener('click',()=>{show(current+1);start()});
  dots.forEach((dot,index)=>dot.addEventListener('click',()=>{show(index);start()}));
  cards.forEach((card,index)=>card.addEventListener('click',()=>{show(index);start()}));
  root.addEventListener('mouseenter',stop); root.addEventListener('mouseleave',start);
  root.addEventListener('focusin',stop); root.addEventListener('focusout',start);
  root.addEventListener('keydown',event=>{if(event.key==='ArrowLeft')show(current-1);if(event.key==='ArrowRight')show(current+1)});
  window.addEventListener('resize',()=>show(current),{passive:true});
  show(0); start();
}
function initPlanActions(plans, context={}) {
  const dialog = document.querySelector('#quick-plan-dialog');
  if (!dialog) return;
  const title = dialog.querySelector('[data-plan-title]'), reason = dialog.querySelector('[data-plan-reason]');
  const product = dialog.querySelector('[data-plan-product]'), page = dialog.querySelector('[data-plan-page]'), validation = dialog.querySelector('[data-plan-validation]');
  const generateButton=dialog.querySelector('[data-generate-images]');
  const generateStatus=dialog.querySelector('[data-generate-status]');
  const generateResults=dialog.querySelector('[data-generate-results]');
  const generationControls=dialog.querySelector('[data-generation-controls]');
  const userDirectionInput=dialog.querySelector('[data-user-direction]');
  const fissionWrap=dialog.querySelector('[data-fission-wrap]');
  const fissionInput=dialog.querySelector('[data-fission-pattern]');
  const referenceInput=dialog.querySelector('[data-reference-input]');
  const referenceList=dialog.querySelector('[data-reference-list]');
  const referenceHint=dialog.querySelector('[data-reference-hint]');
  let uploadedReferences=[];
  if (generateButton) { generateButton.textContent='正在计算生成数量…'; generateButton.disabled=true; }
  let activePlanIndex=0, previewSlots=[], selectedSlotKeys=new Set(), promptOverrides={};
  const slotKey=slot=>`${slot.assetType}:${slot.index}`;
  const selectedTypes=()=>[...new Set(previewSlots.filter(slot=>selectedSlotKeys.has(slotKey(slot))).map(slot=>slot.assetType))];
  const generationCounts=()=>({
    main:previewSlots.filter(x=>x.assetType==='main'&&selectedSlotKeys.has(slotKey(x))).length,
    detail:previewSlots.filter(x=>x.assetType==='detail'&&selectedSlotKeys.has(slotKey(x))).length
  });
  const countText=counts=>`${counts.main} 张主图 + ${counts.detail} 张详情图`;
  const userDirection=()=>String(userDirectionInput?.value||'').trim();
  const fissionEnabled=()=>!!fissionInput?.checked&&!uploadedReferences.length;
  const ensureFissionBaseSelected=()=>{
    if (!fissionEnabled()) return;
    const hasAnySelection=previewSlots.some(slot=>selectedSlotKeys.has(slotKey(slot)));
    const base=previewSlots.find(slot=>slot.assetType==='main'&&slot.index===1);
    if (hasAnySelection&&base) selectedSlotKeys.add(slotKey(base));
  };
  const syncFissionControl=()=>{
    if (!fissionWrap||!fissionInput) return;
    fissionWrap.hidden=!!uploadedReferences.length;
    if (uploadedReferences.length) fissionInput.checked=false;
  };
  const directionNote=direction=>{
    if (!direction?.raw) return '';
    const accepted=arr(direction.accepted), rejected=arr(direction.rejected);
    const ok=accepted.length?`已采纳：${accepted.join(' / ')}`:'未采纳可执行补充';
    const no=rejected.length?`；已忽略：${rejected.join(' / ')}`:'';
    return `${ok}${no}`;
  };
  const syncTypeSwitches=()=>{
    if (!generationControls) return;
    generationControls.querySelectorAll('[data-select-type]').forEach(input=>{
      const slots=previewSlots.filter(slot=>slot.assetType===input.dataset.selectType);
      const selected=slots.filter(slot=>selectedSlotKeys.has(slotKey(slot))).length;
      input.checked=!!slots.length&&selected===slots.length;
      input.indeterminate=selected>0&&selected<slots.length;
      input.disabled=!slots.length;
      const count=input.closest('label')?.querySelector('span');
      if (count) count.textContent=`${selected}/${slots.length}`;
    });
  };
  const fallbackReferences=plan=>{
    const firstMain=[...evidenceIndex.values()].find(item=>item?.type==='image'&&item?.meta?.group==='main');
    return [firstMain].filter(Boolean);
  };
  const renderReferences=plan=>{
    const fallback=fallbackReferences(plan), urls=uploadedReferences.length?uploadedReferences:fallback.map(imageUrl).filter(Boolean);
    if (referenceList) referenceList.innerHTML=urls.map((url,index)=>`<figure><img src="${esc(url)}" alt="产品参考图 ${index+1}">${uploadedReferences.length?`<button type="button" data-remove-reference="${index}" aria-label="删除参考图">×</button>`:''}</figure>`).join('');
    syncFissionControl();
    if (referenceHint) referenceHint.textContent=uploadedReferences.length?`已上传 ${uploadedReferences.length} 张；第一张作为产品主体基准。`:(fallback.length?(fissionEnabled()?'默认先裂变生成相近花型基准图，后续主图/详情围绕该基准图生成。':'已关闭裂变花型，将直接参考采集商品主图生成。'):'当前没有商品主图，请上传产品参考图后生成。');
  };
  const taskName=slot=>slot.role||`${slot.assetType==='detail'?'详情图':'主图'}任务 ${slot.index||''}`;
  const taskCard=(slot,result,status='queued')=>{
    const label=status==='complete'?'已完成':status==='generating'?'生成中':status==='error'?'生成失败':'等待生成';
    const key=slotKey(slot), hasUserEdit=Object.prototype.hasOwnProperty.call(promptOverrides,key);
    const promptText=hasUserEdit?promptOverrides[key]:'';
    const mergeMode=slot.promptMerge?.mode;
    const globalDirection=slot.userDirection||{};
    const hasGlobalAccepted=arr(globalDirection.accepted).length>0;
    const hasGlobalIgnored=arr(globalDirection.ignored).length>0;
    const hasGlobalRejected=arr(globalDirection.rejected).length>0;
    const mergeNote=mergeMode==='applied'?'本图已关联并优先融合本图编辑':
      hasGlobalAccepted?'本图已关联并优先融合全局用户要求':
      mergeMode==='ignored_unrelated'||hasGlobalIgnored||hasGlobalRejected?'本图未关联或存在不可执行要求，继续执行内置策划':
      '本图执行内置策划';
    const media=result?.url?`<button class="generation-preview-btn" type="button" data-preview-url="${esc(result.url)}" data-preview-title="${esc(taskName(slot))}"><img loading="lazy" src="${esc(result.url)}" alt="${esc(taskName(slot))}"></button>`:`<div class="generation-task-placeholder"><span>${slot.assetType==='detail'?'DETAIL':'MAIN'}</span><b>${String(slot.index||1).padStart(2,'0')}</b></div>`;
    const choose=status==='queued'?`<label class="generation-slot-select"><input type="checkbox" data-select-slot="${esc(key)}" ${selectedSlotKeys.has(key)?'checked':''}><span>生成此图</span></label>`:'';
    return `<article class="generation-task-card generation-task-${status} ${selectedSlotKeys.has(key)?'is-selected':''}" data-task-card="${esc(key)}"><div class="generation-task-media">${media}<i>${esc(label)}</i><div class="generation-task-overlay"><small>${slot.assetType==='detail'?'详情图':'主图'} ${String(slot.index||1).padStart(2,'0')}</small><h4>${esc(taskName(slot))}</h4>${arr(slot.task).length?`<p>${arr(slot.task).map(esc).join(' · ')}</p>`:''}<p class="generation-prompt-status">${esc(mergeNote)}</p>${choose}<details class="task-prompt"><summary>编辑本张提示词</summary><em>商品材质、颜色、结构等修改会同步整套图片；视觉要求仅在关联本图时融合。</em><textarea data-prompt-slot="${esc(key)}" placeholder="例如：改成天丝棉材质；或背景留白更大、改为面料微距特写">${esc(promptText)}</textarea><details class="task-final-prompt"><summary>查看最终提示词</summary><pre>${esc(slot.prompt||'')}</pre></details></details></div></div></article>`;
  };
  const openPreview=button=>{
    const buttons=[...generateResults.querySelectorAll('[data-preview-url]')];
    openImagePreview(buttons.map(node=>({url:node.dataset.previewUrl,title:node.dataset.previewTitle||'生成图片'})),buttons.indexOf(button));
  };
  const renderTaskBoard=(slots,results=[],jobStatus='queued')=>{
    if (!generateResults) return;
    const selected=jobStatus==='queued'?arr(slots):arr(slots).filter(slot=>selectedSlotKeys.has(slotKey(slot)));
    const resultMap=new Map(arr(results).map(item=>[`${item.assetType}:${item.slotIndex}`,item]));
    const row=(type,title)=>{
      const items=selected.filter(slot=>slot.assetType===type);
      if (!items.length) return '';
      return `<section class="generation-task-row"><header><div><span>${type==='main'?'MAIN IMAGE TASKS':'DETAIL IMAGE TASKS'}</span><h3>${title}</h3></div><b>${items.filter(slot=>resultMap.has(`${slot.assetType}:${slot.index}`)).length} / ${items.length}</b></header><div class="generation-task-track" style="--task-count:${items.length}">${items.map(slot=>{const result=resultMap.get(`${slot.assetType}:${slot.index}`);let status=result?'complete':'queued';if(!result&&jobStatus==='running')status='generating';if(!result&&jobStatus==='error')status='error';return taskCard(slot,result,status)}).join('')}</div></section>`;
    };
    generateResults.innerHTML=row('main','主图生成任务')+row('detail','详情图生成任务');
  };
  const refreshGenerationConfirmation=()=>{
    ensureFissionBaseSelected();
    const counts=generationCounts(), total=counts.main+counts.detail;
    if (generateButton) { generateButton.disabled=!total; generateButton.textContent=total?`确认生成：${countText(counts)}`:'请选择要生成的图片类型'; }
    if (generateStatus && previewSlots.length) generateStatus.textContent=total?`本次计划生成 ${countText(counts)}，共 ${total} 张。${fissionEnabled()&&counts.main?'裂变模式已计入 main:1 基准图。':''}点击按钮后还需确认。`:'请至少选择一种图片类型。';
    syncTypeSwitches();
    if (previewSlots.length) renderTaskBoard(previewSlots);
  };
  generateResults?.addEventListener('click',event=>{
    const button=event.target.closest('[data-preview-url]');if(button){openPreview(button);return;}
    if (event.target.closest('input,textarea,summary,details,label,button')) return;
    const card=event.target.closest('[data-task-card]');
    if (!card||!card.classList.contains('generation-task-queued')) return;
    if (selectedSlotKeys.has(card.dataset.taskCard)) selectedSlotKeys.delete(card.dataset.taskCard);
    else selectedSlotKeys.add(card.dataset.taskCard);
    refreshGenerationConfirmation();
  });
  const refreshPromptPreview=()=>{
    if (!previewSlots.length) return Promise.resolve();
    const previewBody={planIndex:activePlanIndex,assetTypes:['main','detail'],referenceImages:uploadedReferences,userDirection:userDirection(),fissionPattern:fissionEnabled(),promptOverrides};
    if (context.source) previewBody.source=context.source; else if (context.data) previewBody.reportData=context.data;
    return fetch('/api/image-prompt-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(previewBody)}).then(response=>response.json()).then(payload=>{
      if (!payload.ok) throw new Error(payload.error||'提示词融合失败');
      const promptIndexes={main:0,detail:0};
      previewSlots=arr(payload.slots).map(slot=>{
        const index=promptIndexes[slot.assetType]++;
        const key=`${slot.assetType}:${slot.index}`;
        return {...slot,prompt:arr(payload.prompts?.[slot.assetType])[index]||'',promptMerge:payload.promptMerges?.[key],userDirection:payload.userDirectionBySlot?.[key]};
      });
      if (generateStatus && payload.userDirection?.raw) generateStatus.textContent=directionNote(payload.userDirection);
    });
  };
  generateResults?.addEventListener('change',event=>{
    const textarea=event.target.closest('[data-prompt-slot]');
    if (textarea) {
      promptOverrides[textarea.dataset.promptSlot]=textarea.value;
      refreshPromptPreview().then(refreshGenerationConfirmation).catch(error=>{if(generateStatus) generateStatus.textContent=error.message||'提示词融合失败';});
      return;
    }
    const input=event.target.closest('[data-select-slot]');
    if(!input)return;if(input.checked)selectedSlotKeys.add(input.dataset.selectSlot);else selectedSlotKeys.delete(input.dataset.selectSlot);refreshGenerationConfirmation();
  });
  generateResults?.addEventListener('input',event=>{const textarea=event.target.closest('[data-prompt-slot]');if(!textarea)return;promptOverrides[textarea.dataset.promptSlot]=textarea.value;});
  generationControls?.addEventListener('change',event=>{
    const input=event.target.closest('[data-select-type]');
    if (!input) return;
    previewSlots.filter(slot=>slot.assetType===input.dataset.selectType).forEach(slot=>{
      if (input.checked) selectedSlotKeys.add(slotKey(slot));
      else selectedSlotKeys.delete(slotKey(slot));
    });
    refreshGenerationConfirmation();
  });
  const pollJob = async jobId => {
    for (let i=0;i<240;i++) {
      const r=await fetch('/api/image-job/'+encodeURIComponent(jobId),{cache:'no-store'}), state=await r.json();
      // A fission run may inject main:1 as the shared product baseline even
      // when the user selected detail-only slots. Keep that implicit asset in
      // the board so the UI mirrors the manifest and does not hide the image
      // that all follow-up slots used as their reference.
      const expected=arr(state.expectedSlots);
      if (expected.length) {
        const known=new Set(previewSlots.map(slotKey));
        expected.forEach(slot=>{
          const key=slotKey(slot);
          if (!known.has(key)) { previewSlots.push({...slot}); known.add(key); }
          if (state.fissionPattern && slot.assetType==='main' && slot.index===1) selectedSlotKeys.add(key);
        });
      }
      if (state.status==='complete') { const gate=state.consistencyGate||{}; if(generateStatus) generateStatus.textContent=`已生成 ${arr(state.results).length} 张图片。${gate.status==='passed'?'一致性校验通过。':'已共享产品身份锁，发布前仍需完成一致性复核。'}`; renderTaskBoard(previewSlots,state.results,'complete'); return; }
      if (state.status==='error') { renderTaskBoard(previewSlots,state.results,'error'); throw new Error(state.error||'生图失败'); }
      renderTaskBoard(previewSlots,state.results,'running');
      const counts=generationCounts(); if (generateStatus) generateStatus.textContent=`正在并发生成：已完成 ${arr(state.results).length} / ${counts.main+counts.detail} 张 · ${state.progress||0}%`;
      await new Promise(resolve=>setTimeout(resolve,1200));
    }
    throw new Error('生图任务等待超时，请稍后刷新报告查看结果。');
  };
  generateButton?.addEventListener('click',async event=>{
    ensureFissionBaseSelected();
    const types=selectedTypes(), counts=generationCounts(), total=counts.main+counts.detail;
    if (!types.length) { if(generateStatus) generateStatus.textContent='至少选择主图或详情图一种类型。'; return; }
    if (!total) { if(generateStatus) generateStatus.textContent='尚未完成生成数量计算，请稍后再试。'; return; }
    if (!window.confirm(`确认开始生成？\n\n主图：${counts.main} 张\n详情图：${counts.detail} 张\n合计：${total} 张`)) {
      if (generateStatus) generateStatus.textContent=`已取消。本次原计划生成 ${countText(counts)}。`;
      return;
    }
    event.currentTarget.disabled=true; if(generateStatus) generateStatus.textContent='正在提交生图任务…'; renderTaskBoard(previewSlots,[],'running');
    try {
      const body={planIndex:activePlanIndex,assetTypes:types,selectedSlots:[...selectedSlotKeys],completeSet:true,referenceImages:uploadedReferences,userDirection:userDirection(),fissionPattern:fissionEnabled(),promptOverrides};
      if (context.source) body.source=context.source; else if (context.data) body.reportData=context.data;
      const response=await fetch('/api/generate-images',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}), payload=await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error||'无法提交生图任务');
      window.dispatchEvent(new CustomEvent('image-job-submitted',{detail:{jobId:payload.jobId}}));
      await pollJob(payload.jobId);
      window.dispatchEvent(new CustomEvent('image-job-finished',{detail:{jobId:payload.jobId}}));
    } catch (error) { if(generateStatus) generateStatus.textContent=error.message||'生图失败'; }
    finally { event.currentTarget.disabled=false; }
  });
  referenceInput?.addEventListener('change',async event=>{
    const files=[...event.target.files].slice(0,4-uploadedReferences.length);
    for (const file of files) {
      if (!file.type.startsWith('image/')) continue;
      if (file.size>9*1024*1024) { if(generateStatus) generateStatus.textContent='单张参考图不能超过 9MB。'; continue; }
      uploadedReferences.push(await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file)}));
    }
    event.target.value=''; renderReferences(arr(plans)[activePlanIndex]||{});
    if (previewSlots.length) await refreshPromptPreview().then(refreshGenerationConfirmation).catch(error=>{if(generateStatus) generateStatus.textContent=error.message||'参考图提示词刷新失败';});
    if(generateStatus) generateStatus.textContent=uploadedReferences.length?'已使用上传参考图；生成时会保持同一产品主体。':'将使用默认参考图。';
  });
  referenceList?.addEventListener('click',event=>{
    const button=event.target.closest('[data-remove-reference]'); if(!button)return;
    uploadedReferences.splice(Number(button.dataset.removeReference),1);
    if (!uploadedReferences.length&&fissionInput) fissionInput.checked=true;
    renderReferences(arr(plans)[activePlanIndex]||{});
    if (previewSlots.length) refreshPromptPreview().then(refreshGenerationConfirmation).catch(error=>{if(generateStatus) generateStatus.textContent=error.message||'参考图提示词刷新失败';});
  });
  fissionInput?.addEventListener('change',()=>{
    renderReferences(arr(plans)[activePlanIndex]||{});
    if (previewSlots.length) refreshPromptPreview().then(refreshGenerationConfirmation).catch(error=>{if(generateStatus) generateStatus.textContent=error.message||'裂变提示词刷新失败';});
  });
  document.querySelectorAll('.generate-plan-btn').forEach(button=>button.addEventListener('click',()=>{
    const plan = arr(plans)[Number(button.dataset.planIndex)] || {};
    activePlanIndex=Number(button.dataset.planIndex)||0;
    if (userDirectionInput) userDirectionInput.value='';
    if (fissionInput) fissionInput.checked=true;
    uploadedReferences=[]; renderReferences(plan);
    previewSlots=[]; selectedSlotKeys=new Set(); promptOverrides={};
    if (generateButton) { generateButton.disabled=true; generateButton.textContent='正在计算生成数量…'; }
    title.textContent = plan.name || '快速开品方案';
    if (reason) { reason.textContent = plan.whyThisPlan || ''; reason.hidden = !hasContent(plan.whyThisPlan); }
    [[product,plan.productAction],[page,plan.pageAction],[validation,plan.validation]].forEach(([node,value])=>{if(!node)return;node.textContent=value||'';node.closest('div').hidden=!hasContent(value)});
    if (generateStatus) generateStatus.textContent='已按此方案准备生图提示词。请先选择要生成的图片类型。';
    if (generateResults) generateResults.replaceChildren();
    const previewBody={planIndex:activePlanIndex,assetTypes:['main','detail'],referenceImages:uploadedReferences,userDirection:userDirection(),fissionPattern:fissionEnabled(),promptOverrides};
    if (context.source) previewBody.source=context.source; else if (context.data) previewBody.reportData=context.data;
    fetch('/api/image-prompt-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(previewBody)}).then(response=>response.json()).then(payload=>{
      if (!payload.ok) throw new Error(payload.error||'提示词预览失败');
      const promptIndexes={main:0,detail:0};
      previewSlots=arr(payload.slots).map(slot=>{
        const index=promptIndexes[slot.assetType]++;
        const key=`${slot.assetType}:${slot.index}`;
        return {...slot,prompt:arr(payload.prompts?.[slot.assetType])[index]||'',promptMerge:payload.promptMerges?.[key],userDirection:payload.userDirectionBySlot?.[key]};
      });
      // 默认保留完整主图链和前六个详情证明位；详情 7-15 可按需勾选。
      selectedSlotKeys=new Set(previewSlots.filter(slot=>slot.assetType==='main'||slot.index<=6).map(slotKey));
      refreshGenerationConfirmation();
    }).catch(error=>{if(generateStatus) generateStatus.textContent=error.message||'生成数量计算失败，请重新打开方案。'});
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open','');
  }));
  userDirectionInput?.addEventListener('change',()=>{
    if (!previewSlots.length) return;
    const previewBody={planIndex:activePlanIndex,assetTypes:['main','detail'],referenceImages:uploadedReferences,userDirection:userDirection(),fissionPattern:fissionEnabled(),promptOverrides};
    if (context.source) previewBody.source=context.source; else if (context.data) previewBody.reportData=context.data;
    fetch('/api/image-prompt-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(previewBody)}).then(response=>response.json()).then(payload=>{
      if (!payload.ok) throw new Error(payload.error||'用户补充判断失败');
      const promptIndexes={main:0,detail:0};
      previewSlots=arr(payload.slots).map(slot=>{
        const index=promptIndexes[slot.assetType]++;
        const key=`${slot.assetType}:${slot.index}`;
        return {...slot,prompt:arr(payload.prompts?.[slot.assetType])[index]||'',promptMerge:payload.promptMerges?.[key],userDirection:payload.userDirectionBySlot?.[key]};
      });
      refreshGenerationConfirmation();
      if (generateStatus && payload.userDirection?.raw) generateStatus.textContent=directionNote(payload.userDirection);
    }).catch(error=>{if(generateStatus) generateStatus.textContent=error.message||'用户补充判断失败';});
  });
  dialog.querySelector('[data-close-plan]')?.addEventListener('click',()=>dialog.close ? dialog.close() : dialog.removeAttribute('open'));
}
function openImagePreview(items,startIndex=0) {
  const list=arr(items).filter(item=>item?.url);
  if (!list.length) return;
  let index=Math.max(0,Math.min(startIndex,list.length-1));
  let dialog=document.querySelector('[data-image-preview-dialog]');
  if (!dialog) {
    dialog=document.createElement('dialog');
    dialog.className='image-preview-dialog';
    dialog.setAttribute('data-image-preview-dialog','');
    dialog.innerHTML='<button class="image-preview-close" type="button" data-preview-close aria-label="关闭">×</button><button class="image-preview-nav image-preview-prev" type="button" data-preview-prev aria-label="上一张">‹</button><figure><img data-preview-image alt=""><figcaption><b data-preview-title></b><span data-preview-count></span></figcaption></figure><button class="image-preview-nav image-preview-next" type="button" data-preview-next aria-label="下一张">›</button>';
    document.body.append(dialog);
    dialog.addEventListener('click',event=>{if(event.target===dialog||event.target.closest('[data-preview-close]')) dialog.close();});
    dialog.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'){event.preventDefault();dialog.querySelector('[data-preview-prev]')?.click();}if(event.key==='ArrowRight'){event.preventDefault();dialog.querySelector('[data-preview-next]')?.click();}});
  }
  const render=()=>{
    const item=list[index]||list[0], img=dialog.querySelector('[data-preview-image]');
    img.src=item.url; img.alt=item.title||'生成图片';
    dialog.querySelector('[data-preview-title]').textContent=item.title||'生成图片';
    dialog.querySelector('[data-preview-count]').textContent=`${index+1} / ${list.length}`;
  };
  dialog.querySelector('[data-preview-prev]').onclick=()=>{index=(index-1+list.length)%list.length;render();};
  dialog.querySelector('[data-preview-next]').onclick=()=>{index=(index+1)%list.length;render();};
  render();
  if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open','');
}
function initGenerationHistory(context={}) {
  const root=document.querySelector('[data-generation-history]');
  if (!root) return;
  const endpoint='/api/image-jobs'+(context.source?'?source='+encodeURIComponent(context.source):'');
  let timer=null;
  const render=records=>{
    const items=arr(records);
    if (!items.length) { root.innerHTML='<p class="generation-history-empty">还没有生成记录。选择上方具体开品方案后，可异步生成主图与详情图。</p>'; return; }
    root.innerHTML=items.map(job=>{
      const status=job.status==='complete'?'已完成':job.status==='error'?'失败':`生成中 ${Number(job.progress||0)}%`;
      const thumbs=arr(job.results).slice(0,15).map(item=>`<button type="button" data-history-preview-url="${esc(item.url)}" data-history-preview-title="${esc(item.assetType==='detail'?'详情图':'主图')} ${String(item.slotIndex||'').padStart(2,'0')}"><img loading="lazy" src="${esc(item.url)}" alt="${esc(job.planName||'开品方案')}生成图"></button>`).join('');
      const date=job.createdAt?new Date(Number(job.createdAt)*1000).toLocaleString('zh-CN',{hour12:false}):'';
      return `<article class="generation-record"><header><div><span>开品方案</span><h3>${esc(job.planName||'未命名开品方案')}</h3><p>${esc(job.productName||'')} ${date?'· '+esc(date):''}</p></div><b class="generation-status generation-status-${esc(job.status||'queued')}">${esc(status)}</b></header>${job.error?`<p class="generation-error">${esc(job.error)}</p>`:''}${thumbs?`<div class="generation-thumbs">${thumbs}</div>`:''}<small>记录编号：${esc(job.jobId||'')}</small></article>`;
    }).join('');
  };
  root.addEventListener('click',event=>{
    const button=event.target.closest('[data-history-preview-url]');
    if (!button) return;
    const buttons=[...root.querySelectorAll('[data-history-preview-url]')];
    openImagePreview(buttons.map(node=>({url:node.dataset.historyPreviewUrl,title:node.dataset.historyPreviewTitle||'生成图片'})),buttons.indexOf(button));
  });
  const load=async()=>{
    clearTimeout(timer);
    try {
      const response=await fetch(endpoint,{cache:'no-store'}), payload=await response.json();
      if (!response.ok||!payload.ok) throw new Error(payload.error||'生成记录读取失败');
      render(payload.records);
      if (arr(payload.records).some(x=>!['complete','error'].includes(x.status))) timer=setTimeout(load,1800);
    } catch(error) { root.innerHTML=`<p class="generation-history-empty">${esc(error.message||'生成记录读取失败')}</p>`; }
  };
  load();
  window.addEventListener('image-job-submitted',load);
  window.addEventListener('image-job-finished',load);
}
async function main() {
  const query = new URLSearchParams(location.search);
  const source = window.REPORT_DATA || query.get('data');
  if (!source) throw new Error('缺少 data 参数');
  let data;
  if (typeof source === 'object') data = source;
  else {
    const response = await fetch(source,{cache:'no-store'});
    if (!response.ok) throw new Error(`报告数据读取失败（${response.status}）`);
    data = await response.json();
  }
  evidenceIndex = new Map(arr(data.evidenceLedger).map(item=>[item.id,item]));
  const exp = data.experienceSolution || {}, roles = data.roleOutputs || {}, facts = data.facts || {};
  const audit = data.meta?.reportValidation;
  const auditNotice = data.meta?.reportNotice || (!audit?.ok && audit?.missing?.length ? `审核未通过，报告仍已生成。请优先补齐：${audit.missing.join('、')}` : '');
  const product = facts.product || {}, sales = facts.sales || {}, summary = exp.reportSummary || {};
  const owner = exp.ownerOverview?.cards || roles.executiveDecision?.cards || [];
  const plans = exp.newProductPlans?.plans || data.launchPlans?.plans || [];
  const title = exp.titleAnalysis || roles.conversion?.title || {};
  const visual = exp.visualCommerce || roles.conversion?.visual || {};
  const detail = exp.detailCommerce || roles.conversion?.detail || {};
  const sku = exp.skuAnalysis || roles.productSupply?.sku || {};
  const customer = exp.customerExperience || roles.consumerInsight || {};
  const mainEvidence = imageEntries(data,'main');
  const coverEvidence = arr(data.evidenceLedger).find(item=>item?.id === summary.coverImageId && item?.type === 'image' && item?.meta?.group === 'main') || mainEvidence[0];
  const orderedMain = coverEvidence ? [coverEvidence,...mainEvidence.filter(item=>item.id!==coverEvidence.id)] : mainEvidence;
  const heroSlides = orderedMain.map((item,index)=>`<figure class="hero-slide ${index===0?'active':''}" aria-hidden="${index===0?'false':'true'}"><img class="hero-slide-product" src="${esc(imageUrl(item))}" alt="商品主图"></figure>`).join('');
  const heroDots = orderedMain.map((item,index)=>`<button class="hero-dot ${index===0?'active':''}" type="button" aria-label="查看主图 ${index+1}" aria-current="${index===0?'true':'false'}"></button>`).join('');
  const heroDeckCenter = (orderedMain.length - 1) / 2;
  const heroDeck = orderedMain.map((item,index)=>`<button class="hero-deck-card ${index===0?'active':''}" type="button" style="--deck-index:${index};--deck-count:${orderedMain.length};--deck-x:${(index-heroDeckCenter)*58}px;--deck-r:${(index-heroDeckCenter)*6}deg" aria-label="切换到主图 ${index+1}" aria-current="${index===0?'true':'false'}"><img src="${esc(imageUrl(item))}" alt=""></button>`).join('');
  const bodies = [
    ['decision','老板速览','先看结论，再进入证据和执行动作',decisionCards(owner)],
    ['plan','下一款方向','从证据、反馈和探索方向拆分执行优先级',planCards(plans)],
    ['title','标题表达','标题承担点击与首次筛选任务',titleAnalysis(title)],
    ['main','主图在卖什么','逐张说明信息任务、视觉信号与下一步动作',mainImages(data,visual)],
    ['detail','详情页证明什么','图片与分析绑定，形成连续的页面证明链',detailProof(data,detail)],
    ['sku','SKU怎么选','先解决适配，再解决组合与外观偏好',skuAnalysis(sku)],
    ['review','消费者实际感受到什么','样本边界、主题频次、体验结论和买家秀共同验证',reviews(data,customer)],
    ['verification','产品验证与证据闭环','参数、页面表达、消费者反馈与下一步验证集中核对',supportAnalysis(data)],
    ['roles','七角色完整分析','完整保留专业判断，默认折叠避免干扰老板速览',roleOutputs(roles)]
  ].filter(([, , ,body])=>hasContent(body));
  const sectionHtml = bodies.map(([id,titleText,deck,body],index)=>section(id,String(index+1).padStart(2,'0'),titleText,deck,body)).join('');
  const navNames = {decision:'老板速览',detail:'详情',review:'评论',verification:'验证闭环',roles:'完整分析'};
  const navLinks = bodies.filter(([id])=>navNames[id]).map(([id])=>`<a href="#${id}">${navNames[id]}</a>`).join('');
  const hasPlans = bodies.some(([id])=>id==='plan');
  const heroStats = [['当前价格',sales.currentPrice,'price'],['评论样本',data.baseline?.reviewCount,'sample'],['状态',data.dataQuality?.grade,'status']].filter(([,value])=>hasContent(value));
  document.title = summary.title || product.title || '商品开品分析报告';
  document.getElementById('app').innerHTML = `<div class="report-top"><nav class="report-nav"><div class="wrap"><a class="brand" href="#top">三笙 · 商品开品分析</a><div class="report-nav-actions">${navLinks}${hasPlans?'<a class="quick-product-btn" href="#plan">快速开品 <span>→</span></a>':''}</div></div></nav><header id="top" class="report-hero hero-carousel" tabindex="0">${heroSlides?`<div class="hero-slides">${heroSlides}</div><div class="hero-shade"></div>`:''}<div class="wrap hero-overlay"><div class="hero-copy"><div class="report-kicker">PRODUCT DECISION REPORT · EVIDENCE BASED</div><h1>${esc(summary.title || product.title || '商品分析报告')}</h1>${hasContent(summary.verdict)?`<p>${esc(summary.verdict)}</p>`:''}${auditNotice?`<p class="report-audit-notice" role="status">${esc(auditNotice)}</p>`:''}${heroStats.length?`<div class="hero-meta">${heroStats.map(([label,value,tone])=>`<span class="hero-stat hero-stat-${tone}"><small>${label}</small><b>${esc(value)}</b></span>`).join('')}</div>`:''}</div>${heroDeck?`<div class="hero-deck" aria-label="商品主图牌组">${heroDeck}</div>`:''}${orderedMain.length>1?`<div class="hero-carousel-ui"><button type="button" data-carousel-prev aria-label="上一张主图">←</button><div class="hero-dots">${heroDots}</div><button type="button" data-carousel-next aria-label="下一张主图">→</button></div>`:''}</div></header></div>${sectionHtml}${hasPlans?'<dialog id="quick-plan-dialog" class="quick-plan-dialog"><button class="dialog-close" type="button" data-close-plan aria-label="关闭弹窗">×</button><div class="quick-plan-top"><section class="product-brief"><span>PRODUCT LAUNCH BRIEF · 产品开品说明</span><h2 data-plan-title>快速开品方案</h2><dl><div><dt>产品开品</dt><dd data-plan-product></dd></div><div><dt>主图 / 详情打造</dt><dd data-plan-page></dd></div></dl></section><section class="reference-upload"><header><b>商品主图参考</b><span>本地上传 · 最多 4 张</span></header><div class="reference-list" data-reference-list></div><label class="reference-upload-btn">＋ 本地上传商品主图<input type="file" accept="image/*" multiple data-reference-input></label><p data-reference-hint></p><label class="fission-pattern-toggle" data-fission-wrap><input type="checkbox" data-fission-pattern checked> 默认裂变花型，先生成相近商品基准图</label><em>提示：请上传主体清晰、结构完整的商品图；第一张将作为整套图片的产品身份基准。</em></section></div><section class="image-generation-panel"><header><span>AI VISUAL PRODUCTION</span><h3>选择要生成的图片</h3><p>勾选任意图片任务，可横向滑动查看；主图最多 5 张，详情图最多 15 张。</p></header><label class="image-user-direction"><span>用户补充要求</span><textarea data-user-direction rows="3" placeholder="例如：更偏高端酒店感、浅色背景、突出面料垂坠；不要填写价格、品牌Logo、认证或改商品结构。"></textarea></label><div class="image-generation-controls" data-generation-controls><b>默认勾选：5 张主图 + 6 张详情图。可按需增减。</b><label><input type="checkbox" data-select-type="main"> 生主图 <span>0/0</span></label><label><input type="checkbox" data-select-type="detail"> 生详情 <span>0/0</span></label></div><button class="generate-images-btn" type="button" data-generate-images disabled>正在计算生成数量…</button><p class="image-generation-status" data-generate-status aria-live="polite"></p><div class="generated-image-results" data-generate-results></div></section></dialog>':''}<footer class="report-footer"><div class="wrap"><b>数据边界</b> 本报告仅使用本次采集证据；评论主题可以重叠，未完成采集时不宣称平台全量。</div></footer>`;
  const history=document.createElement('section'); history.id='generation-history'; history.className='report-section generation-history-section';
  history.innerHTML=`<div class="wrap"><header class="report-heading"><span>${String(bodies.length+1).padStart(2,'0')}</span><div><h2>生成记录</h2><p>按具体开品方案保留异步生成结果；点击图片查看原图。</p></div></header><div class="generation-history" data-generation-history><p class="generation-history-empty">正在读取生成记录…</p></div></div>`;
  document.querySelector('.report-footer')?.before(history);
  initHeroCarousel();
  const userDirectionField=document.querySelector('[data-user-direction]');
  if (userDirectionField) {
    userDirectionField.previousElementSibling.textContent='用户最终要求';
    userDirectionField.placeholder='例如：改成天丝棉材质、颜色改为浅灰；或更偏高端酒店感、背景留白更大。不要填写价格、品牌Logo、认证、二维码等平台禁区。';
  }
  const footer=document.querySelector('.report-footer .wrap');
  if (footer) {
    const brand=document.createElement('div'); brand.className='report-footer-brand'; brand.innerHTML='<b>三笙AI</b><span>商品开品分析</span>';
    footer.prepend(brand);
    footer.append(document.createElement('br'),'参数事实、验证门与验证闭环统一收录在底部完整分析区。');
  }
  initPlanActions(plans,{source:typeof source==='string'?source:'',data:typeof source==='object'?data:null});
  initGenerationHistory({source:typeof source==='string'?source:'',data:typeof source==='object'?data:null});
}
main().catch(error => { document.getElementById('app').innerHTML = `<div class="report-error"><h1>报告加载失败</h1><p>${esc(error.message)}</p></div>`; });
