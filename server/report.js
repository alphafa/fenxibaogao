/* 独立报告视图：以分析 JSON 为唯一数据源，完整展示分析与证据。 */
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const arr = value => Array.isArray(value) ? value : [];
const compact = value => arr(value).map(item => typeof item === 'object' ? (item.value || item.topic || item.name || item.label || item.action || item.insight || '') : item).filter(Boolean).join(' · ');
const percent = value => `${(Number(value || 0) * 100).toFixed(1).replace('.0','')}%`;
const modelLabel = item => item?.modelLabel || item?.label || item?.model || item?.id || '默认生图模型';
const modelQuality = item => item?.quality || '服务商默认';
const IMAGE_QUALITY_OPTIONS = ['auto','low','medium','high','xhigh','max'];
function imageGenerationError(error) {
  const text=String(error||'');
  if (/content_safety|content safety|HTTP 451/i.test(text)) return '此图片请求被服务商内容审核拒绝。请检查图片要求和参考图后重试，其他图片继续生成。';
  if (/HTTP 401|invalid token|invalid_api_key/i.test(text)) return '生图密钥验证失败，请检查生图渠道配置。';
  if (/HTTP 429|rate.limit|quota/i.test(text)) return '生图服务暂时受限，请稍后重试或检查账户额度。';
  if (/timeout|timed out|超时/i.test(text)) return '生图请求超时，请稍后重试。';
  return text ? '此图片生成失败，请稍后重试。' : '';
}
function mergeAvailableImageModels(available, runModels) {
  const options = new Map(arr(available).map(item => [item.id, {...item}]));
  arr(runModels).forEach(item => options.set(item.id, {...options.get(item.id), ...item}));
  return [...options.values()];
}
const resultSortKey = item => {
  const type = item?.assetType === 'main' ? 0 : 1;
  const index = Number(item?.slotIndex || 0);
  return [type, index, String(item?.modelLabel || item?.model || ''), String(item?.url || '')];
};
const orderedResults = items => arr(items).slice().sort((a,b) => {
  const aa = resultSortKey(a), bb = resultSortKey(b);
  return aa[0] - bb[0] || aa[1] - bb[1] || aa[2].localeCompare(bb[2]);
});
async function readJsonResponse(response, endpoint='接口') {
  const body=await response.text();
  try { return JSON.parse(body); }
  catch (_) {
    const returnedHtml=/^\s*</.test(body);
    const detail=returnedHtml?'返回了网页内容':'返回内容不是有效 JSON';
    throw new Error(`${endpoint} ${detail}（HTTP ${response.status}）。请关闭旧版服务，并从 http://127.0.0.1:17962 重新打开当前报告。`);
  }
}
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
  const themeCopy = item => {
    const value=String(item?.sourceType||item?.type||'');
    if (value.includes('反馈')) return [['升级动作',item.productAction],['体验证明',item.pageAction]];
    if (value.includes('探索')) return [['探索假设',item.productAction],['验证表达',item.pageAction]];
    return [['证据动作',item.productAction],['证据表达',item.pageAction]];
  };
  const valid=arr(items).map((item,index)=>({item,index})).filter(({item})=>hasContent(item));
  return valid.length ? `<div class="plan-grid">${valid.map(({item,index}) => {const rows=themeCopy(item).filter(([,value])=>hasContent(value));return `<article class="plan-card plan-${tone(item)}">${hasContent(item.sourceType||item.type)?`<span>${esc(item.sourceType||item.type)}</span>`:''}${rows.length?`<dl>${rows.map(([label,value])=>`<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`:''}<button class="generate-plan-btn" type="button" data-plan-index="${index}">按此方向开品 <span>→</span></button></article>`}).join('')}</div>` : '';
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
  // task-final-prompt is intentionally not rendered in the task card; prompts
  // remain an internal generation detail while per-image editing stays available.
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
  const matchReferenceWrap=dialog.querySelector('[data-match-reference-wrap]');
  const matchReferenceInput=dialog.querySelector('[data-match-reference-shooting]');
  const matchReferenceNote=dialog.querySelector('[data-match-reference-note]');
  const referenceInput=dialog.querySelector('[data-reference-input]');
  const referenceList=dialog.querySelector('[data-reference-list]');
  const referenceHint=dialog.querySelector('[data-reference-hint]');
  let uploadedReferences=[], pendingReferenceUploads=0;
  if (generateButton) { generateButton.textContent='正在计算生成数量…'; generateButton.disabled=true; }
  let activePlanIndex=0, previewSlots=[], selectedSlotKeys=new Set(), promptOverrides={};
  let retainedResults=[], generatedTaskSlots=[];
  let imageModelOptions=[], selectedImageModels=new Set(), selectedImageQualities=new Map(), imageModelPromise=null;
  const lastJobStorageKey=`sansong:last-image-job:${context.source||'embedded'}:${activePlanIndex}`;
  let submittedModelSpecs=[], lastSubmittedJobId=localStorage.getItem(lastJobStorageKey)||'';
  const slotKey=slot=>`${slot.assetType}:${slot.index}`;
  const mergeResults=(older,newer)=>{
    const resultKey=item=>`${item.modelKey||item.model||'default'}:${item.assetType}:${item.slotIndex}`;
    const merged=new Map(arr(older).map(item=>[resultKey(item),item]));
    arr(newer).forEach(item=>merged.set(resultKey(item),item));
    return orderedResults([...merged.values()]);
  };
  const selectedTypes=()=>[...new Set(previewSlots.filter(slot=>selectedSlotKeys.has(slotKey(slot))).map(slot=>slot.assetType))];
  const generationCounts=()=>({
    main:previewSlots.filter(x=>x.assetType==='main'&&selectedSlotKeys.has(slotKey(x))).length,
    detail:previewSlots.filter(x=>x.assetType==='detail'&&selectedSlotKeys.has(slotKey(x))).length
  });
  const countText=counts=>`${counts.main} 张主图 + ${counts.detail} 张详情图`;
  const selectedModelOptions=()=>imageModelOptions
    .filter(item=>selectedImageModels.has(item.id))
    .map(item=>({...item,quality:selectedImageQualities.get(item.id) ?? item.quality ?? ''}));
  const comparisonMode=()=>selectedImageModels.size>1;
  const modelKey=item=>item?.modelKey||item?.model||item?.id||'default';
  const imageModelControls=()=>dialog.querySelector('[data-image-model-controls]');
  const generationRunSummary=()=>dialog.querySelector('[data-generation-run-summary]');
  const renderGenerationRunSummary=(status='queued',specs=submittedModelSpecs)=>{
    const summary=generationRunSummary();
    if (!summary) return;
    const items=arr(specs);
    if (!items.length) {
      summary.hidden=true;
      summary.innerHTML='';
      return;
    }
    const stateLabel=status==='complete'?'已完成':status==='error'?'生成失败':status==='running'?'生成中':status==='queued'?'待确认':'已提交';
    summary.hidden=false;
    summary.innerHTML=`<b>本次生成参数 · ${stateLabel}</b>${items.map(item=>`<span><strong>${esc(item.label||item.id||'默认生图模型')}</strong><small>模型：${esc(item.id||'默认')} · 请求质量：${esc(modelQuality(item))}${item.quality?'':'（实际档位由服务商决定）'}</small></span>`).join('')}`;
  };
  const renderImageModelControls=()=>{
    const controls=imageModelControls();
    if (!controls) return;
    if (!imageModelOptions.length) {
      controls.innerHTML='<span class="image-model-loading">未读取到模型列表，请先在本地配置页填写生图测试模型。</span>';
      return;
    }
    controls.innerHTML=`<b>模型对比</b><span class="image-model-hint">同一图片任务会按模型并排生成，最多建议选择 3 个；模型对比建议统一使用 medium。</span>${imageModelOptions.map(item=>`<label class="image-model-option"><input type="checkbox" data-image-model="${esc(item.id)}" ${selectedImageModels.has(item.id)?'checked':''}><span class="image-model-option-name"><b>${esc(item.label||item.id)}</b><small>${esc(item.id)}</small></span><select data-image-quality-for="${esc(item.id)}" aria-label="${esc(`${item.label||item.id} 图片质量`)}">${['',...IMAGE_QUALITY_OPTIONS].map(value=>`<option value="${esc(value)}" ${((selectedImageQualities.get(item.id) ?? item.quality ?? '')===value)?'selected':''}>${esc(value||'服务商默认')}</option>`).join('')}</select></label>`).join('')}`;
  };
  const loadImageModels=()=>{
    if (imageModelPromise) return imageModelPromise;
    imageModelPromise=fetch('/health',{cache:'no-store'}).then(response=>readJsonResponse(response,'/health')).then(payload=>{
      imageModelOptions=arr(payload.imageModels).map(item=>typeof item==='string'?{id:item,label:item}:item).filter(item=>item?.id);
      imageModelOptions.forEach(item=>{
        if (!selectedImageQualities.has(item.id)) selectedImageQualities.set(item.id,item.quality||'');
      });
      if (!imageModelOptions.length&&payload.imageModel) imageModelOptions=[{id:payload.imageModel,label:payload.imageModel}];
      if (!selectedImageModels.size&&imageModelOptions[0]) selectedImageModels.add(imageModelOptions[0].id);
      selectedImageModels=new Set([...selectedImageModels].filter(id=>imageModelOptions.some(item=>item.id===id)));
      if (!selectedImageModels.size&&imageModelOptions[0]) selectedImageModels.add(imageModelOptions[0].id);
      renderImageModelControls();
      syncFissionControl();
      refreshGenerationConfirmation();
    }).catch(()=>{
      imageModelOptions=[{id:'',label:'默认生图模型'}];
      selectedImageQualities.set('','');
      selectedImageModels=new Set(['']);
      renderImageModelControls();
      refreshGenerationConfirmation();
    });
    return imageModelPromise;
  };
  const userDirection=()=>String(userDirectionInput?.value||'').trim();
  const fissionEnabled=()=>!!fissionInput?.checked&&!uploadedReferences.length&&!matchReferenceShooting()&&!comparisonMode();
  const matchReferenceShooting=()=>!!matchReferenceInput?.checked;
  const matchReferenceDescription=()=>matchReferenceShooting()
    ? '已开启：第1张上传产品图只锁定商品本身；第2张采集参考图只提供展示状态；视角、动作、朝向、展开/折叠、摆放、支撑和部件关系跟随采集商品对应图片；不复制采集图中的其他商品、颜色、花型、品牌或文字。'
    : '未开启：产品图只用于商品身份，采集图的拍摄方式、具体动作和摆放状态不继承；按每张图任务重新设计。';
  const syncMatchReferenceControl=plan=>{
    if (!matchReferenceInput) return;
    const matchReferenceLabel=matchReferenceWrap?.querySelector('b');
    if (matchReferenceLabel) {
      if (matchReferenceShooting()) matchReferenceLabel.textContent='产品展示状态跟随采集商品对应图片';
      else matchReferenceLabel.textContent='产品图身份 + 采集参考图展示状态';
    }
    const referenceHeaderLabel=dialog.querySelector('.reference-upload header b');
    if (referenceHeaderLabel) referenceHeaderLabel.textContent=uploadedReferences.length?'产品图（商品身份）':'采集参考图（默认身份参考）';
    const fallback=fallbackReferences(plan||{});
    const hasReference=uploadedReferences.length>0&&fallback.length>0;
    matchReferenceInput.disabled=!hasReference;
    if (!hasReference) matchReferenceInput.checked=false;
    if (matchReferenceNote) matchReferenceNote.textContent=hasReference?matchReferenceDescription():'请同时准备产品图和采集商品对应参考图，才能启用展示状态一致。';
    if (matchReferenceWrap) matchReferenceWrap.title=hasReference?matchReferenceDescription():'需要产品图和采集参考图';
  };
  const ensureFissionBaseSelected=()=>{
    if (!fissionEnabled()) return;
    const hasAnySelection=previewSlots.some(slot=>selectedSlotKeys.has(slotKey(slot)));
    const base=previewSlots.find(slot=>slot.assetType==='main'&&slot.index===1);
    if (hasAnySelection&&base) selectedSlotKeys.add(slotKey(base));
  };
  const syncFissionControl=()=>{
    if (!fissionWrap||!fissionInput) return;
    const lockedByReferenceMatch=matchReferenceShooting();
    const lockedByComparison=comparisonMode();
    fissionWrap.hidden=!!uploadedReferences.length||lockedByReferenceMatch;
    fissionInput.disabled=!!uploadedReferences.length||lockedByReferenceMatch||lockedByComparison;
    if (uploadedReferences.length||lockedByReferenceMatch||lockedByComparison) fissionInput.checked=false;
    if (lockedByComparison&&fissionWrap) fissionWrap.title='多模型对比使用同一参考图，暂不启用裂变基准。';
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
    return [firstMain].filter(item=>Boolean(item&&imageUrl(item)));
  };
  const renderReferences=plan=>{
    const fallback=fallbackReferences(plan), urls=uploadedReferences.length?uploadedReferences:fallback.map(imageUrl).filter(Boolean);
    if (referenceList) {
      const uploadRoot=referenceList.closest('.reference-upload');
      uploadRoot?.classList.toggle('has-reference', urls.length>0);
      referenceList.innerHTML=urls.map((url,index)=>`<figure><img src="${esc(url)}" alt="${uploadedReferences.length?'产品图':'采集参考图'} ${index+1}">${uploadedReferences.length?`<button type="button" data-remove-reference="${index}" aria-label="删除产品图">×</button>`:''}</figure>`).join('');
    }
    syncFissionControl();
    syncMatchReferenceControl(plan);
    if (referenceHint) referenceHint.textContent=uploadedReferences.length?`已上传 ${uploadedReferences.length} 张产品图，以第一张为准。开启展示状态一致后，将参考原商品图片的视角和摆放。`:(fallback.length?(fissionEnabled()?'默认先裂变生成相近花型基准图，后续主图/详情围绕该基准图生成。':'当前将直接参考采集商品主图生成。'):'当前没有商品主图，请上传产品图后生成。');
  };
  const taskName=slot=>slot.role||`${slot.assetType==='detail'?'详情图':'主图'}任务 ${slot.index||''}`;
  const taskCard=(slot,result,status='queued')=>{
    const label=status==='complete'?'已完成':status==='generating'?'生成中':status==='error'?'生成失败':'等待生成';
    const key=slotKey(slot), hasUserEdit=Object.prototype.hasOwnProperty.call(promptOverrides,key);
    const promptText=hasUserEdit?promptOverrides[key]:'';
    const planContext=compact([slot.planProductAction,slot.planPageAction]);
    const planContextHtml=planContext?`<p class="generation-plan-context"><b>${esc(slot.planName||'当前开品方案')}</b> · ${esc(planContext)}</p>`:'';
    const showDisplayReference=matchReferenceShooting();
    const referencePreview=showDisplayReference?(slot.displayReferenceUrl||''):'';
    const referenceLabel='对应采集展示参考图';
    const stateMedia=result?.url
      ? `<button class="generation-preview-btn generation-result-main" type="button" data-preview-url="${esc(result.url)}" data-preview-title="${esc(taskName(slot))}"><img loading="lazy" src="${esc(result.url)}" alt="${esc(taskName(slot))}"><span>生成结果</span></button>`
      : referencePreview
        ? `<div class="generation-reference-main"><img loading="lazy" src="${esc(referencePreview)}" alt="${esc(referenceLabel)}"><span>${esc(referenceLabel)}</span></div>`
        : `<div class="generation-task-placeholder"><span>${status==='error'?'FAILED':status==='generating'?'RUNNING':'待生成'}</span><b>${String(slot.index||1).padStart(2,'0')}</b></div>`;
    const media=`<div class="generation-task-state-media">${stateMedia}</div>`;
    const resultSpec=result?`<small class="generation-task-spec">${esc(modelLabel(result))} · 质量 ${esc(modelQuality(result))}</small>`:'';
    const choose=status==='queued'?`<label class="generation-slot-select"><input type="checkbox" data-select-slot="${esc(key)}" ${selectedSlotKeys.has(key)?'checked':''}><span>生成此图</span></label>`:'';
    return `<article class="generation-task-card generation-task-${status} ${selectedSlotKeys.has(key)?'is-selected':''}" data-task-card="${esc(key)}"><div class="generation-task-media">${media}<i>${esc(label)}</i></div><div class="generation-task-info"><small>${slot.assetType==='detail'?'详情图':'主图'} ${String(slot.index||1).padStart(2,'0')}</small><h4>${esc(taskName(slot))}</h4>${planContextHtml}${resultSpec}${arr(slot.task).length?`<p>${arr(slot.task).map(esc).join(' · ')}</p>`:''}${choose}<details class="task-prompt"><summary>编辑本张要求</summary><em>商品材质、颜色、结构等修改会同步整套图片；视觉要求仅在关联本图时融合。</em><textarea data-prompt-slot="${esc(key)}" placeholder="例如：改成天丝棉材质；或背景留白更大、改为面料微距特写">${esc(promptText)}</textarea></details></div></article>`;
  };
  const openPreview=button=>{
    const buttons=[...generateResults.querySelectorAll('[data-preview-url]')];
    openImagePreview(buttons.map(node=>({url:node.dataset.previewUrl,title:node.dataset.previewTitle||'生成图片'})),buttons.indexOf(button));
  };
  const comparisonCell=(slot,result,status,model)=>{
    const media=result?.url
      ? `<button class="generation-preview-btn" type="button" data-preview-url="${esc(result.url)}" data-preview-title="${esc(`${modelLabel(model)} · ${taskName(slot)}`)}"><img loading="lazy" src="${esc(result.url)}" alt="${esc(`${modelLabel(model)} · ${taskName(slot)}`)}"></button>`
      : `<div class="generation-task-placeholder"><span>${status==='error'?'FAILED':status==='generating'?'RUNNING':slot.assetType==='detail'?'DETAIL':'MAIN'}</span><b>${String(slot.index||1).padStart(2,'0')}</b></div>`;
    const error=imageGenerationError(result?.error);
    return `<article class="generation-comparison-cell generation-task-${status}"><header><b>${esc(modelLabel(model))}<small>${esc(modelQuality(model))}</small></b><i>${status==='complete'?'已完成':status==='generating'?'生成中':status==='error'?'失败':'等待生成'}</i></header><div class="generation-comparison-media">${media}</div>${error?`<p class="generation-error">${esc(error)}</p>`:''}</article>`;
  };
  const renderComparisonBoard=(slots,results=[],jobStatus='queued',failedSlots=[],models=selectedModelOptions())=>{
    const modelList=models.length?models:imageModelOptions;
    const resultKey=(model,slot)=>`${modelKey(model)}:${slot.assetType}:${slot.index}`;
    const resultMap=new Map(arr(results).map(item=>[`${modelKey(item)}:${item.assetType}:${item.slotIndex}`,item]));
    const failedMap=new Map(arr(failedSlots).map(item=>[`${modelKey(item)}:${item.assetType}:${item.slotIndex}`,item]));
    const row=(type,title)=>{
      const items=arr(slots).filter(slot=>slot.assetType===type);
      if (!items.length) return '';
      const completed=items.reduce((sum,slot)=>sum+modelList.filter(model=>resultMap.has(resultKey(model,slot))).length,0);
      const modelHeaders=modelList.map(model=>`<div class="generation-comparison-model"><b>${esc(modelLabel(model))}</b><small>${esc(modelQuality(model))}</small></div>`).join('');
      const taskRows=items.map(slot=>{
        const slotKeyValue=slotKey(slot);
        const choose=jobStatus==='queued'
          ? `<label class="generation-slot-select"><input type="checkbox" data-select-slot="${esc(slotKeyValue)}" ${selectedSlotKeys.has(slotKeyValue)?'checked':''}><span>生成此图</span></label>`
          : '';
        const refItems=[];
        if (matchReferenceShooting() && slot.displayReferenceUrl) refItems.push(['采集展示参考图',slot.displayReferenceUrl]);
        const refThumb=refItems.length?`<div class="generation-reference-previews"><b>确认前参考图</b><div>${refItems.map(([label,url])=>`<figure class="generation-reference-preview"><img loading="lazy" src="${esc(url)}" alt="${esc(label)}"><figcaption>${esc(label)}</figcaption></figure>`).join('')}</div></div>`:'<div class="generation-reference-empty">确认前暂无可用参考图</div>';
        const planContext=compact([slot.planProductAction,slot.planPageAction]);
        const planContextHtml=planContext?`<span class="generation-plan-context"><b>${esc(slot.planName||'当前开品方案')}</b> · ${esc(planContext)}</span>`:'';
        const taskCell=`<div class="generation-comparison-task"><small>${slot.assetType==='detail'?'详情图':'主图'} ${String(slot.index||1).padStart(2,'0')}</small><strong>${esc(taskName(slot))}</strong>${planContextHtml}${refThumb}${choose}</div>`;
        const modelCells=modelList.map(model=>{
          const key=resultKey(model,slot);
          const result=resultMap.get(key);
          const failure=failedMap.get(key);
          let status=result?'complete':'queued';
          if (!result&&jobStatus==='running') status='generating';
          if (!result&&(jobStatus==='error'||failure)) status='error';
          return comparisonCell(slot,result||failure,status,model);
        }).join('');
        return taskCell+modelCells;
      }).join('');
      return `<section class="generation-comparison-row"><header><div><span>${type==='main'?'MAIN IMAGE TASKS':'DETAIL IMAGE TASKS'}</span><h3>${title}</h3></div><b>${completed} / ${items.length*modelList.length}</b></header><div class="generation-comparison-table" style="--comparison-columns:${Math.max(1,modelList.length)}"><div class="generation-comparison-corner">图片任务</div>${modelHeaders}${taskRows}</div></section>`;
    };
    generateResults.innerHTML=row('main','主图模型对比')+row('detail','详情图模型对比');
  };
  const renderTaskBoard=(slots,results=[],jobStatus='queued',failedSlots=[])=>{
    if (!generateResults) return;
    if (selectedImageModels.size>1) {
      renderComparisonBoard(slots,results,jobStatus,failedSlots,selectedModelOptions());
      return;
    }
    const selected=arr(slots);
    const resultMap=new Map(arr(results).map(item=>[`${item.assetType}:${item.slotIndex}`,item]));
    const failedKeys=new Set(arr(failedSlots).map(item=>`${item.assetType}:${item.slotIndex}`));
    const row=(type,title)=>{
      const items=selected.filter(slot=>slot.assetType===type);
      if (!items.length) return '';
      const heading=type==='detail'?`${title}（${items.length}）`:`${title}（${items.length}）`;
      const right=type==='detail'?`<span class="generation-task-hint">左右滑动查看全部 ${items.length} 张</span>`:`<b>${items.filter(slot=>resultMap.has(`${slot.assetType}:${slot.index}`)).length} / ${items.length}</b>`;
      return `<section class="generation-task-row generation-task-row-${type}"><header><div><span>${type==='main'?'MAIN IMAGE TASKS':'DETAIL IMAGE TASKS'}</span><h3>${heading}</h3></div>${right}</header><div class="generation-task-track" style="--task-count:${items.length}">${items.map(slot=>{const key=`${slot.assetType}:${slot.index}`;const result=resultMap.get(key);let status=result?'complete':'queued';if(!result&&jobStatus==='running')status='generating';if(!result&&(jobStatus==='error'||failedKeys.has(key)))status='error';return taskCard(slot,result,status)}).join('')}</div></section>`;
    };
    generateResults.innerHTML=row('main','主图生成任务')+row('detail','详情图生成任务');
  };
  const refreshGenerationConfirmation=()=>{
    ensureFissionBaseSelected();
    const counts=generationCounts(), total=counts.main+counts.detail;
    const modelCount=Math.max(1,selectedImageModels.size);
    const requestTotal=total*modelCount;
    // Keep the count calculation in one place; the single-model label follows the modal spec.
    // 兼容旧版校验：确认生成：${countText(counts)}
    if (generateButton) { generateButton.disabled=!total||!selectedImageModels.size||pendingReferenceUploads>0; generateButton.textContent=pendingReferenceUploads?'正在上传参考图…':requestTotal?(modelCount>1?`${modelCount} 个模型 × ${countText(counts)} = ${requestTotal} 张`:`确认生成：${countText(counts)}`):'请选择要生成的图片类型'; }
    if (generateStatus && previewSlots.length) generateStatus.textContent=requestTotal?`本次计划生成 ${countText(counts)}；${modelCount>1?`将按 ${modelCount} 个模型并排对比，共 `:''}${requestTotal} 张。${fissionEnabled()&&counts.main?'裂变基准图 main:1 已计入主图数量。':''}积分：此 Demo 未接入计费。编辑要求不会调用 AI；确认提交后后台解析。`:'请至少选择一种图片类型和一个生图模型。';
    syncTypeSwitches();
    if (previewSlots.length) renderTaskBoard(previewSlots);
  };
  dialog.addEventListener('change',event=>{
    const input=event.target.closest('[data-image-model]');
    const qualityInput=event.target.closest('[data-image-quality-for]');
    if (qualityInput) {
      selectedImageQualities.set(qualityInput.dataset.imageQualityFor,qualityInput.value);
      refreshGenerationConfirmation();
      return;
    }
    if (!input) return;
    if (input.checked) selectedImageModels.add(input.dataset.imageModel);
    else selectedImageModels.delete(input.dataset.imageModel);
    if (!selectedImageModels.size) input.checked=true,selectedImageModels.add(input.dataset.imageModel);
    syncFissionControl();
    refreshGenerationConfirmation();
  });
  generateResults?.addEventListener('click',event=>{
    const button=event.target.closest('[data-preview-url]');if(button){openPreview(button);return;}
    if (event.target.closest('input,textarea,summary,details,label,button')) return;
    const card=event.target.closest('[data-task-card]');
    if (!card||!card.classList.contains('generation-task-queued')) return;
    if (selectedSlotKeys.has(card.dataset.taskCard)) selectedSlotKeys.delete(card.dataset.taskCard);
    else selectedSlotKeys.add(card.dataset.taskCard);
    refreshGenerationConfirmation();
  });
  generateResults?.addEventListener('change',event=>{
    const textarea=event.target.closest('[data-prompt-slot]');
    if (textarea) {
      promptOverrides[textarea.dataset.promptSlot]=textarea.value;
      refreshGenerationConfirmation();
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
  let activeJobPoll=0;
  const pollJob = async jobId => {
    const pollToken=++activeJobPoll;
    let networkErrors=0;
    for (let i=0;i<240;i++) {
      const endpoint='/api/image-job/'+encodeURIComponent(jobId);
      let state;
      try {
        const r=await fetch(endpoint,{cache:'no-store'});
        state=await readJsonResponse(r,endpoint);
        networkErrors=0;
      } catch (error) {
        networkErrors++;
        if (generateStatus) generateStatus.textContent=`本地服务短暂断开，正在自动重连（${networkErrors}/5）…`;
        if (networkErrors>=5) throw new Error('无法连接本地生图服务，请确认服务仍在运行后重试。');
        await new Promise(resolve=>setTimeout(resolve,Math.min(2000*networkErrors,6000)));
        continue;
      }
      if (pollToken!==activeJobPoll) return;
      // A fission run may inject main:1 as the shared product baseline even
      // when the user selected detail-only slots. Keep that implicit asset in
      // the board so the UI mirrors the manifest and does not hide the image
      // that all follow-up slots used as their reference.
      const expected=arr(state.expectedSlots);
      if (arr(state.comparisonModels).length) {
        const runModels=arr(state.comparisonModels).map(item=>({id:item.id||'',label:item.label||item.id||'默认生图模型',quality:item.quality||'',modelKey:item.modelKey}));
        imageModelOptions=mergeAvailableImageModels(imageModelOptions,runModels);
        selectedImageModels=new Set(runModels.map(item=>item.id));
        const preservedQualities=new Map(selectedImageQualities);
        runModels.forEach(item=>{
          if (item.quality || !preservedQualities.has(item.id)) preservedQualities.set(item.id,item.quality||'');
        });
        selectedImageQualities=preservedQualities;
        renderImageModelControls();
        submittedModelSpecs=runModels.map(item=>({...item,quality:selectedImageQualities.get(item.id) ?? item.quality ?? ''}));
        renderGenerationRunSummary(state.status,submittedModelSpecs);
      }
      if (expected.length) {
        const known=new Set(previewSlots.map(slotKey));
        const generatedKnown=new Set(generatedTaskSlots.map(slotKey));
        expected.forEach(slot=>{
          const key=slotKey(slot);
          if (!known.has(key)) { previewSlots.push({...slot}); known.add(key); }
          if (!generatedKnown.has(key)) { generatedTaskSlots.push({...slot}); generatedKnown.add(key); }
          if (state.fissionPattern && slot.assetType==='main' && slot.index===1) selectedSlotKeys.add(key);
        });
      }
      const displayResults=mergeResults(retainedResults,state.results);
      const boardSlots=generatedTaskSlots.length?generatedTaskSlots:expected.length?expected:previewSlots;
      if (state.status==='complete') { const gate=state.consistencyGate||{}; const shootPolicy=state.matchReferenceShooting?'已按参考图拍摄与产品展示状态生成。':'按每张图片任务重新设计拍摄和展示状态。'; const failedSlots=arr(state.failedSlots), failed=failedSlots.length; retainedResults=displayResults; if(failed){selectedSlotKeys=new Set(failedSlots.map(item=>`${item.assetType}:${item.slotIndex}`));const counts=generationCounts();if(generateButton){generateButton.disabled=false;generateButton.textContent=`仅重试失败：${countText(counts)}`;}syncTypeSwitches();} if(generateStatus) generateStatus.textContent=failed?`部分完成：累计成功 ${displayResults.length} 张，失败 ${failed} 张。点击按钮重试失败图片。`:`已生成 ${displayResults.length} 张图片。${shootPolicy}${gate.status==='passed'?'一致性校验通过。':'发布前请检查商品外观和文字。'}`; renderTaskBoard(boardSlots,displayResults,'complete',failedSlots); return; }
      if (state.status==='error') { renderTaskBoard(boardSlots,displayResults,'error',state.failedSlots); throw new Error(imageGenerationError(state.error)||'生图失败'); }
      renderTaskBoard(boardSlots,displayResults,'running',state.failedSlots);
      const counts=generationCounts(); const expectedTotal=(counts.main+counts.detail)*Math.max(1,selectedImageModels.size); if (generateStatus) generateStatus.textContent=state.status==='queued'||state.status==='preparing'?'任务已提交，正在准备；可关闭页面，稍后在生成记录中查看。':`正在并发生成：已完成 ${arr(state.results).length} / ${expectedTotal} 张 · ${state.progress||0}%`;
      await new Promise(resolve=>setTimeout(resolve,1200));
    }
    throw new Error('生图任务等待超时，请稍后刷新报告查看结果。');
  };
  generateButton?.addEventListener('click',async event=>{
    if (pendingReferenceUploads) return;
    ensureFissionBaseSelected();
    const types=selectedTypes(), counts=generationCounts(), total=counts.main+counts.detail;
    if (!types.length) { if(generateStatus) generateStatus.textContent='至少选择主图或详情图一种类型。'; return; }
    if (!total) { if(generateStatus) generateStatus.textContent='尚未完成生成数量计算，请稍后再试。'; return; }
    const modelSpecs=selectedModelOptions(), requestTotal=total*Math.max(1,modelSpecs.length);
    submittedModelSpecs=modelSpecs.map(item=>({...item}));
    renderGenerationRunSummary('queued',submittedModelSpecs);
    const modelSummary=modelSpecs.map(item=>`${item.label||item.id}（${modelQuality(item)}）`).join('、');
    if (!window.confirm(`确认开始生成？\n\n模型：${modelSummary}\n主图：${counts.main} 张${fissionEnabled()&&counts.main?'（含裂变基准图 main:1）':''}\n详情图：${counts.detail} 张\n合计：${requestTotal} 张\n积分：此 Demo 未接入计费`)) {
      renderGenerationRunSummary('queued',[]);
      if (generateStatus) generateStatus.textContent=`已取消。本次原计划生成 ${modelSpecs.length} 个模型 × ${countText(counts)}。`;
      return;
    }
    const submittedSlots=previewSlots.filter(slot=>selectedSlotKeys.has(slotKey(slot)));
    ++activeJobPoll;
    event.currentTarget.disabled=true; if(generateStatus) generateStatus.textContent='正在提交生图任务…'; renderTaskBoard(submittedSlots,retainedResults,'running');
    try {
      const body={planIndex:activePlanIndex,assetTypes:types,selectedSlots:[...selectedSlotKeys],completeSet:true,imageModels:modelSpecs.map(item=>({id:item.id,quality:item.quality||''})),referenceImages:[...uploadedReferences],userDirection:userDirection(),fissionPattern:fissionEnabled(),matchReferenceShooting:matchReferenceShooting(),promptOverrides:{...promptOverrides},reuseAnalysisJobId:lastSubmittedJobId};
      if (context.source) body.source=context.source; else if (context.data) body.reportData=context.data;
      const response=await fetch('/api/generate-images',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}), payload=await readJsonResponse(response,'/api/generate-images');
      if (!response.ok || !payload.ok) throw new Error(payload.error||'无法提交生图任务');
      generatedTaskSlots=submittedSlots.map(slot=>({...slot}));
      retainedResults=[];
      lastSubmittedJobId=payload.jobId;
      localStorage.setItem(`sansong:last-image-job:${context.source||'embedded'}:${activePlanIndex}`,payload.jobId);
      if (generateStatus) generateStatus.textContent='任务已提交，正在准备；可关闭页面，稍后在生成记录中查看。';
      window.dispatchEvent(new CustomEvent('image-job-submitted',{detail:{jobId:payload.jobId}}));
      await pollJob(payload.jobId);
      window.dispatchEvent(new CustomEvent('image-job-finished',{detail:{jobId:payload.jobId}}));
    } catch (error) { renderGenerationRunSummary('error',submittedModelSpecs); if(generateStatus) generateStatus.textContent=error.message||'生图失败'; }
    finally { event.currentTarget.disabled=false; }
  });
  const referenceUpload=dialog.querySelector('.reference-upload');
  const referenceUploadButton=dialog.querySelector('.reference-upload-btn');
  const referenceEmpty=dialog.querySelector('.reference-empty');
  const addReferenceFiles=async fileList=>{
    const files=[...fileList].slice(0,Math.max(0,4-uploadedReferences.length));
    let uploadError='';
    for (const file of files) {
      if (!file.type.startsWith('image/')) continue;
      if (file.size>9*1024*1024) { if(generateStatus) generateStatus.textContent='单张参考图不能超过 9MB。'; continue; }
      pendingReferenceUploads++;
      refreshGenerationConfirmation();
      try {
        const dataUrl=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file)});
        const response=await fetch('/api/image-reference-upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image:dataUrl})});
        const payload=await readJsonResponse(response,'/api/image-reference-upload');
        if (!response.ok||!payload.ok||!payload.url) throw new Error(payload.error||'参考图上传失败');
        uploadedReferences.push(payload.url);
      } catch (error) {
        uploadError=error.message||'参考图上传失败，请重新选择图片。';
      } finally {
        pendingReferenceUploads--;
        refreshGenerationConfirmation();
      }
    }
    renderReferences(arr(plans)[activePlanIndex]||{});
    refreshGenerationConfirmation();
    if(generateStatus) generateStatus.textContent=uploadError|| (uploadedReferences.length?`已使用上传产品图；生成时会保持产品身份。${matchReferenceShooting()?' '+matchReferenceDescription():''}`:`将使用默认采集参考图。${matchReferenceShooting()?' '+matchReferenceDescription():''}`);
  };
  referenceInput?.addEventListener('change',async event=>{
    await addReferenceFiles(event.target.files);
    event.target.value='';
  });
  // Explicitly proxy the visible button to the file input. This remains
  // reliable when modal CSS or browser label activation suppresses the native
  // label-to-input click behavior.
  referenceUploadButton?.addEventListener('click',event=>{
    if (event.target===referenceInput) return;
    event.preventDefault();
    referenceInput?.click();
  });
  referenceEmpty?.addEventListener('click',()=>referenceInput?.click());
  referenceUpload?.addEventListener('dragenter',event=>{
    event.preventDefault();
    referenceUpload.classList.add('is-dragging');
  });
  referenceUpload?.addEventListener('dragover',event=>event.preventDefault());
  referenceUpload?.addEventListener('dragleave',event=>{
    if (!referenceUpload.contains(event.relatedTarget)) referenceUpload.classList.remove('is-dragging');
  });
  referenceUpload?.addEventListener('drop',async event=>{
    event.preventDefault();
    referenceUpload.classList.remove('is-dragging');
    await addReferenceFiles(event.dataTransfer?.files||[]);
  });
  referenceList?.addEventListener('click',event=>{
    const button=event.target.closest('[data-remove-reference]'); if(!button)return;
    uploadedReferences.splice(Number(button.dataset.removeReference),1);
    if (!uploadedReferences.length&&fissionInput) fissionInput.checked=true;
    renderReferences(arr(plans)[activePlanIndex]||{});
    refreshGenerationConfirmation();
  });
  fissionInput?.addEventListener('change',()=>{
    renderReferences(arr(plans)[activePlanIndex]||{});
    refreshGenerationConfirmation();
  });
  matchReferenceInput?.addEventListener('change',()=>{
    syncMatchReferenceControl(arr(plans)[activePlanIndex]||{});
    syncFissionControl();
    refreshGenerationConfirmation();
    if (generateStatus) generateStatus.textContent=matchReferenceDescription();
  });
  document.querySelectorAll('.generate-plan-btn').forEach(button=>button.addEventListener('click',()=>{
    loadImageModels();
    const plan = arr(plans)[Number(button.dataset.planIndex)] || {};
    activePlanIndex=Number(button.dataset.planIndex)||0;
    lastSubmittedJobId=localStorage.getItem(`sansong:last-image-job:${context.source||'embedded'}:${activePlanIndex}`)||'';
    if (userDirectionInput) userDirectionInput.value='';
    if (fissionInput) fissionInput.checked=true;
    if (matchReferenceInput) matchReferenceInput.checked=false;
    uploadedReferences=[]; renderReferences(plan);
    previewSlots=[]; selectedSlotKeys=new Set(); promptOverrides={}; retainedResults=[]; generatedTaskSlots=[];
    if (generateButton) { generateButton.disabled=true; generateButton.textContent='正在计算生成数量…'; }
    submittedModelSpecs=[];
    renderGenerationRunSummary('queued',submittedModelSpecs);
    title.textContent = plan.name || '快速开品方案';
    if (reason) { reason.textContent = plan.whyThisPlan || ''; reason.hidden = !hasContent(plan.whyThisPlan); }
    [[product,plan.productAction],[page,plan.pageAction],[validation,plan.validation]].forEach(([node,value])=>{if(!node)return;node.textContent=value||'';node.closest('div').hidden=!hasContent(value)});
    if (generateStatus) generateStatus.textContent='正在加载默认图片任务；编辑阶段不会调用 AI。';
    if (generateResults) generateResults.replaceChildren();
    const setupBody={planIndex:activePlanIndex,referenceImages:[...uploadedReferences],matchReferenceShooting:!!matchReferenceInput?.checked,fissionPattern:fissionEnabled()};
    if (context.source) setupBody.source=context.source; else if (context.data) setupBody.reportData=context.data;
    fetch('/api/image-generation-setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(setupBody)}).then(response=>readJsonResponse(response,'/api/image-generation-setup')).then(async payload=>{
      if (!payload.ok) throw new Error(payload.error||'默认图片任务加载失败');
      previewSlots=arr(payload.slots);
      // 默认保留完整主图链和前六个详情证明位；详情 7-15 可按需勾选。
      selectedSlotKeys=new Set(previewSlots.filter(slot=>slot.assetType==='main'||slot.index<=6).map(slotKey));
      await loadImageModels();
      refreshGenerationConfirmation();
      if (lastSubmittedJobId) {
        if (generateStatus) generateStatus.textContent='正在恢复上次生成结果…';
        await pollJob(lastSubmittedJobId);
      }
    }).catch(error=>{if(generateStatus) generateStatus.textContent=error.message||'生成数量计算失败，请重新打开方案。'});
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open','');
  }));
  userDirectionInput?.addEventListener('change',refreshGenerationConfirmation);
  dialog.querySelector('[data-close-plan]')?.addEventListener('click',()=>dialog.close ? dialog.close() : dialog.removeAttribute('open'));
  loadImageModels();
}
function openImagePreview(items,startIndex=0,openRevision=false,returnDialog=null) {
  const list=arr(items).filter(item=>item?.url);
  if (!list.length) return;
  let index=Math.max(0,Math.min(startIndex,list.length-1));
  let dialog=document.querySelector('[data-image-preview-dialog]');
  if (!dialog) {
    dialog=document.createElement('dialog');
    dialog.className='image-preview-dialog';
    dialog.setAttribute('data-image-preview-dialog','');
    dialog.innerHTML='<button class="image-preview-close" type="button" data-preview-close aria-label="关闭">×</button><div class="image-preview-version-bar"><button type="button" data-preview-prev aria-label="上一版本">‹</button><strong data-preview-version-label>版本 1 / 1</strong><button type="button" data-preview-next aria-label="下一版本">›</button><button type="button" class="image-preview-revision-btn" data-preview-revision>重新生成</button></div><div class="image-preview-layout"><aside class="image-preview-references"><b>对应参考图</b><div data-preview-references></div></aside><figure><img data-preview-image alt=""><figcaption><div><b data-preview-title></b><small data-preview-state></small></div><span data-preview-count></span></figcaption></figure></div><section class="image-preview-revision-panel" data-preview-revision-panel hidden><header><b>重新生成当前图片</b><button type="button" data-preview-revision-cancel>取消</button></header><p>这是重新生成，不是图片编辑。会沿用原任务的产品身份、参考图和方案，只修改你这次明确补充的要求。</p><p class="image-preview-current-mode" data-preview-mode></p><textarea data-preview-revision-input rows="4" placeholder="例如：背景留白更大；材质改成哑光；保持当前产品身份和对应展示状态"></textarea><button type="button" class="image-preview-revision-submit" data-preview-revision-submit>确认重新生成</button><small data-preview-revision-status></small></section>';
    document.body.append(dialog);
    dialog.addEventListener('click',event=>{if(event.target===dialog||event.target.closest('[data-preview-close]')) dialog.close();});
    dialog.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'){event.preventDefault();dialog.querySelector('[data-preview-prev]')?.click();}if(event.key==='ArrowRight'){event.preventDefault();dialog.querySelector('[data-preview-next]')?.click();}});
    dialog.addEventListener('close',()=>{
      const target=dialog._returnDialog;
      dialog._returnDialog=null;
      if (!target||target.open) return;
      if (typeof target.showModal==='function') target.showModal(); else target.setAttribute('open','');
    });
  }
  dialog._returnDialog=returnDialog;
  const revisionPanel=dialog.querySelector('[data-preview-revision-panel]');
  const revisionInput=dialog.querySelector('[data-preview-revision-input]');
  const revisionStatus=dialog.querySelector('[data-preview-revision-status]');
  const revisionButton=dialog.querySelector('[data-preview-revision]');
  const render=()=>{
    const item=list[index]||list[0], img=dialog.querySelector('[data-preview-image]');
    dialog.classList.toggle('has-reference',arr(item.referenceUrls).length>0);
    img.src=item.url; img.alt=item.title||'生成图片';
    const references=dialog.querySelector('[data-preview-references]');
    references.innerHTML=arr(item.referenceUrls).map(ref=>`<figure><img src="${esc(ref.url)}" alt="${esc(ref.label||'参考图')}"><figcaption>${esc(ref.label||'参考图')}</figcaption></figure>`).join('')||'<span>本条记录未保存参考图</span>';
    dialog.querySelector('[data-preview-title]').textContent=item.title||'生成图片';
    const displayRevision=item.displayRevisionNumber||item.revisionNumber||index+1;
    dialog.querySelector('[data-preview-state]').textContent=`当前版本 v${displayRevision} · 可重新生成`;
    dialog.querySelector('[data-preview-mode]').textContent=`本次将沿用当前模式：${item.generationMode||'产品身份模式'}。重新生成只新增当前图片版本，不改变原版本。`;
    dialog.querySelector('[data-preview-count]').textContent=`${index+1} / ${list.length}`;
    dialog.querySelector('[data-preview-version-label]').textContent=`版本 ${displayRevision} / ${list.length}`;
    revisionButton.hidden=!item.resultId||!item.jobId;
    if (revisionPanel && !revisionPanel.hidden) revisionInput?.focus();
  };
  dialog.querySelector('[data-preview-prev]').onclick=()=>{index=(index-1+list.length)%list.length;render();};
  dialog.querySelector('[data-preview-next]').onclick=()=>{index=(index+1)%list.length;render();};
  dialog.querySelector('[data-preview-revision]').onclick=()=>{
    if (!list[index]?.resultId) return;
    revisionPanel.hidden=false; revisionStatus.textContent=''; revisionInput.value=''; revisionInput.focus();
  };
  dialog.querySelector('[data-preview-revision-cancel]').onclick=()=>{revisionPanel.hidden=true;};
  dialog.querySelector('[data-preview-revision-submit]').onclick=async()=>{
    const item=list[index], reason=String(revisionInput?.value||'').trim();
    if (!item?.resultId||!item?.jobId) return;
    if (!window.confirm(`确认重新生成“${item.title||'当前图片'}”吗？\n\n${reason?'本次会合并你的补充要求。':'本次沿用上次要求。'}\n原版本不会被覆盖，会新增一个版本。`)) return;
    const button=dialog.querySelector('[data-preview-revision-submit]'); button.disabled=true; revisionStatus.textContent='正在提交二次生成任务…';
    try {
      const overrides={...(item.promptOverrides||{})};
      if (reason) overrides[item.taskKey]=reason;
      const body={source:item.reportSource,planIndex:item.planIndex??0,assetTypes:[item.assetType],selectedSlots:[item.taskKey],completeSet:true,
        revisionOfJobId:item.jobId,parentResultId:item.resultId,revisionReason:reason,referenceImages:arr(item.referenceImages),
        matchReferenceShooting:!!item.matchReferenceShooting,fissionPattern:!!item.fissionPattern,userDirection:item.userDirection||'',
        promptOverrides:overrides,imageModels:item.model?[{id:item.model,quality:item.quality||''}]:[]};
      const response=await fetch('/api/generate-images',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const payload=await readJsonResponse(response,'/api/generate-images');
      if (!response.ok||!payload.ok) throw new Error(payload.error||'二次生成任务提交失败');
      revisionStatus.textContent='任务已提交，正在生成；原版本已保留。';
      button.disabled=false;
      window.dispatchEvent(new CustomEvent('image-job-submitted',{detail:{jobId:payload.jobId,revisionOfJobId:item.jobId}}));
      setTimeout(()=>{revisionPanel.hidden=true;},900);
    } catch(error) { button.disabled=false; revisionStatus.textContent=error.message||'二次生成任务提交失败'; }
  };
  revisionPanel.hidden=true;
  render();
  if (openRevision && !revisionButton.hidden) {
    revisionStatus.textContent='';
    revisionInput.value='';
    revisionPanel.hidden=false;
    revisionInput?.focus();
  }
  if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open','');
}
function initGenerationHistory(context={}) {
  // 兼容旧版任务状态文案：部分完成 · 失败 ${failedCount} 张
  // 兼容旧版下载地址：/api/image-job/${encodeURIComponent(job.jobId)}/download
  // 兼容旧版模型摘要：质量：${modelQuality(item)}
  // 兼容旧版轮次标题来源：job.planName
  // 兼容旧版参考策略文案：job.matchReferenceShooting?'已按参考图拍摄与展示状态一致'
  const root=document.querySelector('[data-generation-history]');
  if (!root) return;
  const endpoint='/api/image-jobs'+(context.source?'?source='+encodeURIComponent(context.source):'');
  const dialog=document.querySelector('[data-generation-history-dialog]');
  const trigger=document.querySelector('[data-generation-history-open]');
  const countNode=document.querySelector('[data-generation-history-count]');
  let timer=null;
  const setHistoryFullscreen=fullscreen=>{
    if (!dialog) return;
    dialog.classList.toggle('is-fullscreen',fullscreen);
    const button=dialog.querySelector('[data-generation-history-fullscreen]');
    button?.setAttribute('aria-pressed',String(fullscreen));
    const label=button?.querySelector('[data-generation-history-fullscreen-label]');
    if (label) label.textContent=fullscreen?'退出铺满':'铺满窗口';
  };
  const openHistory=()=>{
    setHistoryFullscreen(true);
    if (dialog && typeof dialog.showModal === 'function') dialog.showModal();
    else if (dialog) dialog.setAttribute('open','');
  };
  trigger?.addEventListener('click',openHistory);
  const fullscreenButton=dialog?.querySelector('[data-generation-history-fullscreen]');
  fullscreenButton?.addEventListener('click',()=>{
    setHistoryFullscreen(!dialog.classList.contains('is-fullscreen'));
  });
  dialog?.addEventListener('click',event=>{
    if (event.target===dialog || event.target.closest('[data-generation-history-close]')) {
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
    }
  });
  const historyItem=(job,item)=>({
    url:item.url,title:`${item.assetType==='detail'?'详情图':'主图'} ${String(item.slotIndex||'').padStart(2,'0')}`,
    referenceUrls:job.matchReferenceShooting&&item.displayReferenceUrl?[{label:'采集展示参考图',url:item.displayReferenceUrl}]:[],
    resultId:item.resultId||`${job.jobId}:${item.assetType}:${item.slotIndex}`,
    jobId:job.jobId,taskKey:item.taskKey||`${item.assetType}:${item.slotIndex}`,assetType:item.assetType,slotIndex:item.slotIndex,
    revisionNumber:Number(item.revisionNumber||job.revisionNumber||1),rootResultId:item.rootResultId||job.rootResultIds?.[item.taskKey||`${item.assetType}:${item.slotIndex}`]||job.jobId,
    generationRoundId:item.generationRoundId||job.generationRoundId||job.roundId||job.jobId,
    roundType:item.roundType||job.roundType||(job.revisionOfJobId?'revision':'initial'),
    revisionReason:item.revisionReason||job.revisionReason||'',
    reportSource:job.reportSource||context.source||'',planIndex:job.planIndex??0,referenceImages:arr(job.referenceImages),
    matchReferenceShooting:!!job.matchReferenceShooting,fissionPattern:!!job.fissionPattern,userDirection:job.userDirection||'',
    generationMode:job.matchReferenceShooting?'产品图身份 + 采集参考图展示状态':job.fissionPattern?'产品图身份 + 裂变基准图':'产品图身份',
    promptOverrides:job.promptOverrides||{},model:item.model||'',modelKey:item.modelKey||item.model||'default',quality:item.quality||'',
    createdAt:Number(item.createdAt||job.completedAt||job.createdAt||0)
  });
  const roundKeyFor=(job,jobMap)=>{
    if (job?.generationRoundId) return `round:${job.generationRoundId}`;
    const seen=new Set(); let cursor=job;
    while (cursor?.revisionOfJobId&&!seen.has(cursor.revisionOfJobId)) {
      seen.add(cursor.revisionOfJobId);
      const parent=jobMap.get(cursor.revisionOfJobId);
      if (!parent) break;
      cursor=parent;
    }
    return `round:${cursor?.jobId||job?.jobId||'unknown'}`;
  };
  const renderRoundSlot=(variant)=>{
    const versions=variant.versions.slice().sort((a,b)=>
      Number(a.createdAt||0)-Number(b.createdAt||0) ||
      Number(a.revisionNumber||1)-Number(b.revisionNumber||1) ||
      String(a.resultId||a.url||'').localeCompare(String(b.resultId||b.url||''))
    ).map((item,index)=>({...item,displayRevisionNumber:index+1}));
    const latest=versions.at(-1), label=`${latest.assetType==='detail'?'详情图':'主图'} ${String(latest.slotIndex||'').padStart(2,'0')}`;
    const versionData=JSON.stringify(versions);
    const latestIndex=Math.max(0,versions.length-1);
    return `<article class="generation-round-slot ${versions.length>1?'has-versions':''}" data-history-version-index="${latestIndex}"><button type="button" class="generation-round-slot-image" data-history-preview-url="${esc(latest.url)}" data-history-revisions="${esc(versionData)}"><img loading="lazy" src="${esc(latest.url)}" alt="${esc(label)}"></button><div class="generation-round-version-switcher"><button type="button" data-history-version-step="-1" aria-label="上一版本" ${versions.length>1?'':'disabled'}>‹</button><strong data-history-version-label>v${latest.displayRevisionNumber} / ${versions.length}</strong><button type="button" data-history-version-step="1" aria-label="下一版本" ${versions.length>1?'':'disabled'}>›</button><button type="button" class="generation-round-revision-button" data-history-revision>重新生成</button></div></article>`;
  };
  const render=records=>{
    const items=arr(records), jobMap=new Map(items.filter(job=>job?.jobId).map(job=>[job.jobId,job]));
    if (!items.length) {
      if (countNode) countNode.hidden=true;
      root.innerHTML='<p class="generation-history-empty">还没有生成记录。选择具体开品方案后，可异步生成主图与详情图。</p>';
      return;
    }
    const rounds=new Map();
    items.forEach(job=>{
      const key=roundKeyFor(job,jobMap);
      if (!rounds.has(key)) rounds.set(key,{key,root:job,variants:new Map(),pending:[],jobs:[]});
      const round=rounds.get(key); round.jobs.push(job);
      if (!round.root?.revisionOfJobId&&job.revisionOfJobId) { /* keep the initial task as the round header */ }
      else if (!round.root?.createdAt||Number(job.createdAt||0)<Number(round.root.createdAt||0)) round.root=job;
      const results=orderedResults(job.results);
      if (!results.length&&job.status!=='complete') round.pending.push(job);
      results.forEach(result=>{
        const item=historyItem(job,result), variantKey=`${item.taskKey}:${item.modelKey}`;
        if (!round.variants.has(variantKey)) round.variants.set(variantKey,{key:variantKey,assetType:item.assetType,slotIndex:item.slotIndex,versions:[]});
        round.variants.get(variantKey).versions.push(item);
      });
    });
    const roundList=[...rounds.values()].sort((a,b)=>Number(b.root?.createdAt||0)-Number(a.root?.createdAt||0));
    if (!roundList.length) { root.innerHTML='<p class="generation-history-empty">还没有可查看的生成批次。</p>'; return; }
    if (countNode) {
      countNode.textContent=roundList.length>99?'99+':String(roundList.length);
      countNode.hidden=false;
    }
    const renderBatch=(batch,batchIndex)=>{
      const variants=[...batch.variants.values()];
      const makeSection=(type,title)=>{
        const list=variants.filter(item=>item.assetType===type).sort((a,b)=>Number(a.slotIndex||0)-Number(b.slotIndex||0));
        if (!list.length) return `<section class="generation-round-section generation-round-section-empty"><header><div><span>${type==='main'?'MAIN IMAGE TASKS':'DETAIL IMAGE TASKS'}</span><h4>${title}</h4></div><small>本批次未生成</small></header></section>`;
        return `<section class="generation-round-section"><header><div><span>${type==='main'?'MAIN IMAGE TASKS':'DETAIL IMAGE TASKS'}</span><h4>${title}</h4></div><b>${list.length} 张</b></header><div class="generation-round-grid">${list.map(item=>renderRoundSlot(item)).join('')}</div></section>`;
      };
      const rootJob=batch.root||{};
      const date=rootJob.createdAt?new Date(Number(rootJob.createdAt)*1000).toLocaleString('zh-CN',{hour12:false}):'';
      const completed=variants.length, pendingCount=batch.pending.length;
      const statusText=pendingCount?`任务进行中 ${Number(batch.pending[0]?.progress||0)}%`:completed?`${completed} 个图片任务已保存`:'本批次暂无已保存图片';
      const shootPolicy=rootJob.matchReferenceShooting?'已按参考图拍摄与展示状态一致':'按任务重新设计拍摄与展示';
      const downloadJob=rootJob.jobId;
      return `<article class="generation-record generation-round-record"><header><div><span>生成批次 ${batchIndex+1} · ${batch.root?.roundType==='revision'?'二次生成':'整套生成'}</span><h3>${esc(rootJob.planName||'开品方案')} · 主图与详情图</h3><p>${esc(rootJob.productName||'')} ${date?'· '+esc(date):''}</p></div><div class="generation-record-actions"><b class="generation-status generation-status-${esc(rootJob.status||'complete')}">${esc(statusText)}</b>${downloadJob?`<a class="generation-download" href="/api/image-job/${encodeURIComponent(downloadJob)}/download" download>下载本批次</a>`:''}</div></header><p class="generation-record-policy">${esc(shootPolicy)} · ${rootJob.referenceShootingPolicy==='match_reference'?'只显示并使用对应采集参考图':'只锁定产品身份，不显示采集参考图'} · 点击任意图片可切换历史版本或二次生成。</p><div class="generation-round-sections">${makeSection('main','主图生成结果')}${makeSection('detail','详情图生成结果')}</div>${batch.pending.length?`<div class="generation-round-pending">还有 ${batch.pending.length} 个任务正在处理，完成后会自动进入本批次对应分组。</div>`:''}</article>`;
    };
    root.innerHTML=`<div class="generation-history-overview"><b>历史生成批次</b><span>共 ${roundList.length} 批，按生成时间倒序展开；每批次独立保留主图与详情图。</span></div>${roundList.map(renderBatch).join('')}`;
  };
  root.addEventListener('click',event=>{
    const showPreview=(revisions,directRevision=false,startIndex=revisions.length-1)=>{
      const returnDialog=dialog?.open?dialog:null;
      if (returnDialog && typeof returnDialog.close === 'function') returnDialog.close();
      openImagePreview(revisions,Math.max(0,startIndex),directRevision,returnDialog);
    };
    const versionButton=event.target.closest('[data-history-version-step]');
    if (versionButton) {
      const slot=versionButton.closest('.generation-round-slot'), preview=slot?.querySelector('[data-history-preview-url]');
      let revisions=[];
      try { revisions=JSON.parse(preview?.dataset.historyRevisions||'[]'); } catch (_) { revisions=[]; }
      if (!slot||!preview||revisions.length<2) return;
      const current=Number(slot.dataset.historyVersionIndex||revisions.length-1);
      const index=(current+Number(versionButton.dataset.historyVersionStep||0)+revisions.length)%revisions.length;
      const item=revisions[index];
      slot.dataset.historyVersionIndex=String(index);
      preview.dataset.historyPreviewUrl=item.url||'';
      const image=preview.querySelector('img');
      if (image) { image.src=item.url||''; image.alt=item.title||'生成图片'; }
      const label=slot.querySelector('[data-history-version-label]');
      if (label) label.textContent=`v${item.displayRevisionNumber||index+1} / ${revisions.length}`;
      return;
    }
    const revisionButton=event.target.closest('[data-history-revision]');
    if (revisionButton) {
      const slot=revisionButton.closest('.generation-round-slot'), preview=slot?.querySelector('[data-history-preview-url]');
      let revisions=[];
      try { revisions=JSON.parse(preview?.dataset.historyRevisions||'[]'); } catch (_) { revisions=[]; }
      const selectedIndex=Number(slot?.dataset.historyVersionIndex||revisions.length-1);
      showPreview(revisions,true,selectedIndex);
      return;
    }
    const button=event.target.closest('[data-history-preview-url]');
    if (!button) return;
    let revisions=[];
    try { revisions=JSON.parse(button.dataset.historyRevisions||'[]'); } catch (_) { revisions=[]; }
    const selectedIndex=Number(button.closest('.generation-round-slot')?.dataset.historyVersionIndex||revisions.length-1);
    showPreview(revisions,false,selectedIndex);
  });
  const load=async()=>{
    clearTimeout(timer);
    try {
      const response=await fetch(endpoint,{cache:'no-store'}), payload=await readJsonResponse(response,endpoint);
      if (!response.ok||!payload.ok) throw new Error(payload.error||'生成记录读取失败');
      render(payload.records);
      if (arr(payload.records).some(x=>!['complete','error'].includes(x.status))) timer=setTimeout(load,1800);
    } catch(error) {
      if (countNode) countNode.hidden=true;
      root.innerHTML=`<p class="generation-history-empty">${esc(error.message||'生成记录读取失败')}</p>`;
    }
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
    data = await readJsonResponse(response,String(source));
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
  document.getElementById('app').innerHTML = `<div class="report-top"><nav class="report-nav"><div class="wrap"><a class="brand" href="#top">三笙 · 商品开品分析</a><div class="report-nav-actions">${navLinks}${hasPlans?'<a class="quick-product-btn" href="#plan">快速开品 <span>→</span></a>':''}</div></div></nav><header id="top" class="report-hero hero-carousel" tabindex="0">${heroSlides?`<div class="hero-slides">${heroSlides}</div><div class="hero-shade"></div>`:''}<div class="wrap hero-overlay"><div class="hero-copy"><div class="report-kicker">PRODUCT DECISION REPORT · EVIDENCE BASED</div><h1>${esc(summary.title || product.title || '商品分析报告')}</h1>${hasContent(summary.verdict)?`<p>${esc(summary.verdict)}</p>`:''}${auditNotice?`<p class="report-audit-notice" role="status">${esc(auditNotice)}</p>`:''}${heroStats.length?`<div class="hero-meta">${heroStats.map(([label,value,tone])=>`<span class="hero-stat hero-stat-${tone}"><small>${label}</small><b>${esc(value)}</b></span>`).join('')}</div>`:''}</div>${heroDeck?`<div class="hero-deck" aria-label="商品主图牌组">${heroDeck}</div>`:''}${orderedMain.length>1?`<div class="hero-carousel-ui"><button type="button" data-carousel-prev aria-label="上一张主图">←</button><div class="hero-dots">${heroDots}</div><button type="button" data-carousel-next aria-label="下一张主图">→</button></div>`:''}</div></header></div>${sectionHtml}${hasPlans?'<dialog id="quick-plan-dialog" class="quick-plan-dialog"><button class="dialog-close" type="button" data-close-plan aria-label="关闭弹窗">×</button><div class="quick-plan-top"><section class="product-brief"><span>PRODUCT LAUNCH BRIEF · 产品开品说明</span><h2 data-plan-title>快速开品方案</h2><dl><div><dt>产品开品</dt><dd data-plan-product></dd></div><div><dt>主图 / 详情打造</dt><dd data-plan-page></dd></div></dl><div class="brief-controls"><label class="fission-pattern-toggle match-reference-shooting-toggle" data-match-reference-wrap><input type="checkbox" data-match-reference-shooting><span><b>产品图身份 + 采集参考图展示状态（产品展示与参考图拍摄一致）</b><small data-match-reference-note>请同时准备产品图和采集商品对应参考图，才能启用展示状态一致。</small></span></label><label class="fission-pattern-toggle" data-fission-wrap><input type="checkbox" data-fission-pattern checked> 默认裂变花型，先生成相近商品基准图</label><label class="image-user-direction"><span>用户补充要求</span><textarea data-user-direction rows="3" placeholder="例如：更偏高端酒店感、浅色背景、突出面料垂坠；不要填写价格、品牌Logo、认证或改商品结构。"></textarea></label></div></section><section class="reference-upload" aria-label="商品主图参考"><header><b>产品图（商品身份）</b><span>本地上传 · 最多 4 张</span></header><div class="reference-list" data-reference-list></div><div class="reference-empty"><span>＋</span><b>点击或拖拽上传参考图</b><small>本地上传 · 最多 4 张</small></div><label class="reference-upload-btn">＋ 上传产品图<input type="file" accept="image/*" multiple data-reference-input></label><p data-reference-hint></p><em>提示：上传主体清晰、结构完整的产品图；采集商品对应图片自动作为展示状态参考，两者不是同一张图。</em></section></div><section class="image-generation-panel"><header><div><span>AI VISUAL PRODUCTION</span><h3>AI 生图任务</h3><p>勾选任意图片任务，可横向滑动查看；主图最多 5 张，详情图最多 15 张。</p></div><button class="generate-images-btn" type="button" data-generate-images disabled>正在计算生成数量…</button></header><div class="image-generation-controls" data-generation-controls><b>默认勾选：5 张主图 + 6 张详情图。可按需增减。</b><label><input type="checkbox" data-select-type="main"> 生主图 <span>0/0</span></label><label><input type="checkbox" data-select-type="detail"> 生详情 <span>0/0</span></label></div><p class="image-generation-status" data-generate-status aria-live="polite"></p><div class="generated-image-results" data-generate-results></div></section></dialog>':''}<footer class="report-footer"><div class="wrap"><b>数据边界</b> 本报告仅使用本次采集证据；评论主题可以重叠，未准备采集证据时不宣称页面全量。</div></footer>`;
  if (window.OFFLINE_REPORT) {
    document.querySelector('.report-nav-actions')?.insertAdjacentHTML('beforeend','<span class="report-offline-label">已保存的离线报告</span>');
    document.querySelectorAll('.generate-plan-btn,.quick-product-btn,#quick-plan-dialog').forEach(node=>node.remove());
    initHeroCarousel();
    return;
  }
  const reportId=typeof source==='string' ? source.match(/^\/reports\/([A-Za-z0-9_-]+)\.json$/)?.[1] : null;
  if (reportId) {
    const download=document.createElement('button');
    download.type='button';
    download.className='report-download-btn';
    download.textContent='下载含图片报告';
    download.title='下载可直接打开浏览的单文件离线 HTML 报告';
    document.querySelector('.report-nav-actions')?.append(download);
    download.addEventListener('click',async()=>{
      download.disabled=true;
      download.textContent='正在打包图片…';
      try {
        const response=await fetch(`/api/report-export/${encodeURIComponent(reportId)}`);
        if (!response.ok) {
          const result=await readJsonResponse(response,'离线报告下载');
          throw new Error(result.error||'离线报告下载失败');
        }
        const blob=await response.blob();
        const url=URL.createObjectURL(blob);
        const link=document.createElement('a');
        link.href=url;
        link.download=`${reportId}-offline.html`;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(()=>URL.revokeObjectURL(url),60000);
        download.textContent='下载含图片报告';
      } catch(error) {
        download.textContent='下载失败，点击重试';
        window.alert(error.message||'离线报告下载失败');
      } finally { download.disabled=false; }
    });
  }
  const modelControls=document.createElement('div');
  modelControls.className='image-model-controls';
  modelControls.setAttribute('data-image-model-controls','');
  modelControls.innerHTML='<span class="image-model-loading">正在读取生图模型…</span>';
  const generationControlsNode=document.querySelector('[data-generation-controls]');
  generationControlsNode?.after(modelControls);
  const generationHeading=document.querySelector('#quick-plan-dialog .image-generation-panel h3');
  if (generationHeading) generationHeading.textContent='选择要生成的图片';
  const generationButton=document.querySelector('#quick-plan-dialog [data-generate-images]');
  const generationStatus=document.querySelector('#quick-plan-dialog [data-generate-status]');
  const generationRunSummary=document.createElement('div');
  generationRunSummary.className='generation-run-summary';
  generationRunSummary.setAttribute('data-generation-run-summary','');
  generationRunSummary.hidden=true;
  generationStatus?.after(generationRunSummary);
  const historyTrigger=document.createElement('button');
  historyTrigger.className='generation-history-fab';
  historyTrigger.type='button';
  historyTrigger.setAttribute('data-generation-history-open','');
  historyTrigger.setAttribute('aria-label','打开生成记录');
  historyTrigger.innerHTML='<span class="generation-history-fab-icon" aria-hidden="true">↺</span><span>生成记录</span><b data-generation-history-count hidden>0</b>';
  const historyDialog=document.createElement('dialog');
  historyDialog.className='generation-history-dialog is-fullscreen';
  historyDialog.setAttribute('data-generation-history-dialog','');
  historyDialog.innerHTML='<header class="generation-history-dialog-head"><div><span>AI VISUAL PRODUCTION</span><h2>生成记录</h2><p>历史生成批次直接展开，分别查看主图与详情图；点击指定图片可切换版本或发起二次生成。</p></div><div class="generation-history-dialog-actions"><button type="button" data-generation-history-fullscreen aria-pressed="true"><span data-generation-history-fullscreen-label>退出铺满</span></button><button class="dialog-close" type="button" data-generation-history-close aria-label="关闭生成记录">×</button></div></header><div class="generation-history" data-generation-history><p class="generation-history-empty">正在读取生成记录…</p></div>';
  document.body.append(historyTrigger,historyDialog);
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
