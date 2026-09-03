/* 独立报告视图：页面只负责渲染 JSON，不在 Python 中拼接 HTML。 */
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const arr = v => Array.isArray(v) ? v : [];
const text = (v, keys=['value','label','headline','note','insight','action','name']) => {
  if (Array.isArray(v)) return v.map(x => text(x, keys)).filter(Boolean).join(' · ');
  if (typeof v === 'string' || typeof v === 'number') return String(v);
  if (v && typeof v === 'object') for (const k of keys) if (v[k] != null && v[k] !== '') return text(v[k], keys);
  return '';
};
function cards(items, fields=['headline','note']) {
  return arr(items).map(x => `<article class="card"><h3>${esc(text(x,['label','name','type']))}</h3>${fields.map(k=>text(x,[k])).filter(Boolean).map(v=>`<p>${esc(v)}</p>`).join('')}</article>`).join('');
}
function images(data, group, limit=8) {
  const list = arr(data.evidenceLedger).filter(e => e?.type === 'image' && e?.meta?.group === group).slice(0,limit);
  return list.map(e => `<figure><img loading="lazy" src="${esc(e.meta.localUrl || e.value)}" alt="商品${esc(group)}"><figcaption>${esc(e.id)}</figcaption></figure>`).join('') || '<p>未采集</p>';
}
function section(id, title, body) { return `<section id="${id}" class="report-section"><div class="wrap"><h2>${esc(title)}</h2>${body}</div></section>`; }
async function main() {
  const q = new URLSearchParams(location.search); const source = window.REPORT_DATA || q.get('data');
  if (!source) throw new Error('缺少 data 参数');
  const data = await fetch(source).then(r => r.json()); const exp = data.experienceSolution || {}; const raw = data.facts || {}; const p = raw.product || {}; const s = raw.sales || {};
  const summary = exp.reportSummary || {}; document.title = summary.title || p.title || '商品开品分析报告';
  const owner = exp.ownerOverview?.cards || []; const plans = exp.newProductPlans?.plans || []; const title = exp.titleAnalysis || {}; const visual = exp.visualCommerce || {}; const detail = exp.detailCommerce || {};
  document.getElementById('app').innerHTML = `<nav class="v92-nav"><div class="wrap"><div class="brand">三笙 · 商品开品分析</div><a href="#decision">老板速览</a>　<a href="#plan">新品方向</a>　<a href="#main">主图</a>　<a href="#review">评价</a></div></nav><header class="v92-hero"><div class="wrap"><div class="v92-kicker">PRODUCT DECISION REPORT · JSON VIEW</div><h1>${esc(summary.title || p.title || '商品分析报告')}</h1><p>${esc(summary.verdict || '')}</p><small>价格 ${esc(s.currentPrice || '未采集')} · 评论 ${esc(data.baseline?.reviewCount || 0)}</small></div></header>${section('decision','老板速览',`<div class="grid">${cards(owner)}</div>`)}${section('plan','下一款方向',`<div class="grid">${cards(plans,['sourceType','whyThisPlan','productAction','pageAction'])}</div>`)}${section('title','标题表达',`<p>${esc(title.professionalOpinion || '')}</p>`)}${section('main','主图在卖什么',`<div class="gallery">${images(data,'main')}</div><div class="grid">${cards(visual.items,['imageRole','visualSignals','nextAction'])}</div>`)}${section('detail','详情页证明什么',`<div class="gallery">${images(data,'detail')}</div><div class="grid">${cards(detail.contentGroups,['type','visualSignals','nextAction'])}</div>`)}${section('sku','SKU怎么选',`<p>${esc(exp.skuAnalysis?.professionalOpinion || '')}</p>${cards(exp.skuAnalysis?.selectionDimensions,['name','values','evidenceIds'])}`)}${section('review','消费者实际感受到什么',`<div class="gallery">${images(data,'buyerShow',6)}</div>${cards(exp.customerExperience?.consumerInsights?.experienceSignals,['type','insight'])}`)}<footer class="v92-footer"><div class="wrap">数据来自本次采集证据；页面由独立 HTML + JSON 渲染</div></footer>`;
}
main().catch(e => { document.getElementById('app').innerHTML = `<p class="error">报告加载失败：${esc(e.message)}</p>`; });
