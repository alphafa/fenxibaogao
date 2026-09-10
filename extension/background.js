const SERVER='http://127.0.0.1:17962';
const EXTENSION_VERSION=chrome.runtime.getManifest().version;
const RUN_GAP=8*60*1000;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const isProduct=u=>/^https:\/\/detail\.tmall\.com\/item\.htm/i.test(u||'') || /item\.taobao\.com\/item\.htm/i.test(u||'');

async function setStatus(tabId,patch){
  const key='status_'+tabId; const old=(await chrome.storage.local.get(key))[key]||{};
  await chrome.storage.local.set({[key]:{...old,...patch,updatedAt:Date.now()}});
}
async function health(){ try{const r=await fetch(SERVER+'/health');return r.ok?await r.json():{ok:false}}catch(e){return {ok:false,error:String(e)}} }

chrome.runtime.onMessage.addListener((m,s,send)=>{
  if(m?.type==='ANALYZE_CURRENT_NOW'){
    (async()=>{
      try{
        const tabId=m.tabId;
        const [{result:pageInfo}]=await chrome.scripting.executeScript({
          target:{tabId},world:'MAIN',
          func:()=>({url:location.href,itemId:(location.href.match(/[?&]id=(\d+)/)||[])[1]||''})
        });
        const itemId=pageInfo?.itemId||'';
        if(!itemId){send({ok:false,error:'当前页面没有识别到商品ID'});return}
        let raw=null;
        try{
          const got=await chrome.storage.local.get('tmall_last_raw_'+itemId);
          raw=got['tmall_last_raw_'+itemId]||null;
        }catch(e){}
        if(raw){
          const hasFacts=!!(raw.product?.title||raw.product?.shop||raw.sales?.currentPrice||raw.sku?.length||raw.attributes?.length||raw.images?.main?.length);
          if(!hasFacts)raw=null;
        }
        if(!raw){
          // 没有历史raw时，做一次“轻采集”：复用 collector，但立即给 stop flag，
          // 只保留当前页面已经可见/已捕获的数据，不再长时间采评论。
          await chrome.scripting.executeScript({target:{tabId},world:'MAIN',func:()=>{window.__TMALL_AI_STOP_REVIEW__=true;}});
          const [{result:r}]=await chrome.scripting.executeScript({target:{tabId},world:'MAIN',func:collector,args:[true,'500',EXTENSION_VERSION]});
          raw=r;
        }
        if(!raw){send({ok:false,error:'当前没有可用于分析的数据'});return}

        raw.collection=raw.collection||{};
        raw.collection.analysisMode='current_snapshot';
        raw.collection.reviewCollectionComplete=!!raw.collection.reviewCollectionComplete;
        raw.collection.reviewCompleteness=raw.collection.reviewCollectionComplete?'confirmed':'partial';
        raw.collection.analysisStartedBeforeReviewComplete=!raw.collection.reviewCollectionComplete;
        raw.collection.analysisStartedAt=new Date().toISOString();

        const resp=await fetch('http://127.0.0.1:17962/api/analyze-current',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({raw,allowPartialReviews:true})
        });
        const j=await resp.json().catch(()=>({ok:false,error:'后端返回无法解析'}));
        send({...j,reviewCount:raw.reviews?.length||0});
      }catch(e){send({ok:false,error:String(e)})}
    })();
    return true;
  }
  if(m?.type==='STOP_COLLECTION'){(async()=>{try{await chrome.scripting.executeScript({target:{tabId:m.tabId},world:'MAIN',func:()=>{window.__TMALL_AI_STOP_REVIEW__=true;}});send({ok:true})}catch(e){send({ok:false,error:String(e)})}})();return true;}
  if(m?.type==='RUN_CURRENT'){ run(m.tabId,true,m.sampleMode||'500').then(x=>send(x)).catch(e=>send({ok:false,error:String(e)})); return true; }
  if(m?.type==='HEALTH'){ health().then(send); return true; }
});

async function run(tabId,manual,sampleMode='500'){
  const tab=await chrome.tabs.get(tabId);
  if(!isProduct(tab.url)) throw new Error('当前标签页不是天猫/淘宝商品详情页');
  const h=await health();
  if(!h.ok){ await setStatus(tabId,{state:'server_offline',message:'本地 AI 服务未启动'}); throw new Error('本地 AI 服务未启动，请先运行 根目录的「start-tmall-ai.command」'); }
  if(!h.modelConfigured){ await setStatus(tabId,{state:'model_unconfigured',message:'模型未配置：请填写 本地设置页'}); throw new Error('模型未配置。请先填写 本地设置页 的 api_key 与 model。'); }
  const [{result:pageState}]=await chrome.scripting.executeScript({
    target:{tabId},world:'MAIN',
    func:async()=>{
      if(document.readyState==='loading') await new Promise(resolve=>document.addEventListener('DOMContentLoaded',resolve,{once:true}));
      for(let i=0;i<8&&(document.body?.innerText||'').trim().length<120;i++) await new Promise(r=>setTimeout(r,350));
      const body=(document.body?.innerText||'').replace(/\s+/g,' ').slice(0,5000);
      const login=/login\.taobao\.com|login\.tmall\.com/i.test(location.hostname)||(/密码登录|短信登录|手机扫码登录/.test(body)&&!/商品评价|宝贝详情/.test(body));
      const verification=/验证码|滑块验证|安全验证|访问过于频繁|操作频繁/.test(body);
      return {url:location.href,login,verification,bodyLength:(document.body?.innerText||'').length};
    }
  });
  if(pageState?.login){await setStatus(tabId,{state:'login_required',message:'淘宝要求登录。请先在当前浏览器登录淘宝，再刷新商品页重试。',progress:0});throw new Error('淘宝商品页未登录：请登录后刷新当前商品页再采集')}
  if(pageState?.verification){await setStatus(tabId,{state:'verification_required',message:'页面出现淘宝安全验证，请手动完成后刷新重试。',progress:0});throw new Error('页面出现淘宝安全验证，请手动完成验证后重试')}
  if(!isProduct(pageState?.url)){throw new Error('商品页已跳转，当前不是可采集的淘宝/天猫详情页')}
  await setStatus(tabId,{state:'collecting',sampleMode,message:`正在采集当前商品：主图、SKU、详情、参数、问答与评论（评论样本：${sampleMode==='all'?'全部':sampleMode+' 条'}）。不会采集推荐商品…`,progress:10});
  await chrome.scripting.executeScript({target:{tabId},world:'MAIN',func:()=>{window.__TMALL_AI_STOP_REVIEW__=false;window.__TMALL_AI_REVIEW_PROGRESS__={count:0,round:0,stagnant:0,mode:'启动',elapsedMs:0,preview:[]};}});
  let collectorDone=false,collectorError=null;const startedAt=Date.now();
  const collectorPromise=chrome.scripting.executeScript({target:{tabId},world:'MAIN',func:collector,args:[manual,sampleMode,EXTENSION_VERSION]}).then(v=>v).catch(e=>{collectorError=e;return null}).finally(()=>{collectorDone=true});
  while(!collectorDone){try{const rr=await chrome.scripting.executeScript({target:{tabId},world:'MAIN',func:()=>window.__TMALL_AI_REVIEW_PROGRESS__||null});const live=rr?.[0]?.result;if(live)await setStatus(tabId,{state:'collecting_reviews',message:`评论采集中：${live.count||0} 条 · ${live.mode||'处理中'}${live.stagnant?` · ${live.stagnant}轮无新增`:''}`,progress:Math.min(67,18+(Number(live.round||0)*2)),reviewLive:{...live,elapsedMs:Date.now()-startedAt}})}catch(e){}await sleep(600)}
  const collectorResult=await collectorPromise;
  if(collectorError)throw new Error('页面采集脚本执行失败：'+String(collectorError?.message||collectorError));
  const raw=collectorResult?.[0]?.result;
  if(!raw?.product?.itemId) throw new Error('未识别到 itemId，请确认商品页已正常打开并刷新后重试');
  const hasProductFacts=!!(raw.product.title||raw.product.shop||raw.sales?.currentPrice||raw.sku?.length||raw.attributes?.length||raw.images?.main?.length);
  if(!hasProductFacts){
    await setStatus(tabId,{state:'product_empty',message:'已识别商品ID，但页面商品信息为空。请确认已登录、详情已加载后刷新重试。',progress:0});
    throw new Error('商品字段为空：请确认淘宝已登录且商品详情加载完成，然后刷新页面重试');
  }
  try{
    await chrome.storage.local.set({['tmall_last_raw_'+(raw?.product?.itemId||'unknown')]:raw});
    try{
      const p=(raw?.product?.parameterCollection)||{};
      await chrome.storage.local.set({['tmall_param_status_'+(raw?.product?.itemId||'unknown')]:p});
    }catch(e){}

  }catch(e){}

  await chrome.storage.local.set({['last_raw_'+raw.product.itemId]:raw});
  if(!raw.collection?.reviewCollectionComplete){
    const reason=raw.collection?.reviewStopReason||'unknown';
    const human=reason==='human_verification_required';const stopped=reason==='user_stopped';
    const noReviewData=!raw.reviews?.length&&!raw.collection?.networkReviewResponses;
    const folded=raw.collection?.foldedDefaultReviewCount?`；平台另折叠 ${raw.collection.foldedDefaultReviewCount} 条默认好评，未提供逐条内容`:'';
    const msg=stopped?`已终止采集，并保存当前 ${raw.reviews?.length||0} 条评论。可随时继续。`:human?`评论已保存 ${raw.reviews?.length||0} 条，页面出现验证。请手动完成验证后继续。`:noReviewData?'页面未释放可读取的评论数据。商品信息已保存；请在当前页打开“评价/评论”后再次点击继续采集。':`评论已保存 ${raw.reviews?.length||0} 条，尚未确认完整${folded}。已停止低效空转，可继续采集。`;
    await setStatus(tabId,{state:stopped?'reviews_stopped':'reviews_incomplete',sampleMode, message:msg,progress:68,itemId:raw.product.itemId,reviewStopReason:reason,reviewLive:raw.collection?.reviewLive||null,parameterStatus:raw.product?.parameterCollection||null});
    return {ok:false,needsReviewResume:true,message:msg,reviewStopReason:reason,rawStats:{title:raw.product?.title||'',reviews:raw.reviews?.length||0,questions:raw.questions?.length||0,sku:raw.sku?.length||0,attributes:raw.attributes?.length||0,promotions:raw.promotions?.length||0,images:raw.images?.all?.length||0}};
  }
  await setStatus(tabId,{state:'sending',message:`评论完整性已确认，共 ${raw.reviews?.length||0} 条。正在生成新品开品闭环…`,progress:78,itemId:raw.product.itemId});
  const r=await fetch(SERVER+'/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(raw)});
  const j=await r.json(); if(!r.ok||!j.ok) throw new Error(j.error||'提交分析失败');
  await setStatus(tabId,{state:'analyzing',message:'正在分析全方位产品体验并生成解决方案',progress:82,taskId:j.taskId,taskUrl:j.taskUrl});
  await chrome.tabs.create({url:j.taskUrl});
  return {ok:true,taskId:j.taskId,rawStats:{title:raw.product?.title||'',reviews:raw.reviews?.length||0,questions:raw.questions?.length||0,sku:raw.sku?.length||0,attributes:raw.attributes?.length||0,promotions:raw.promotions?.length||0,images:raw.images?.all?.length||0}};
}

async function collector(manual=false,sampleMode='500',collectorVersion='9.3.0'){
  const delay=ms=>new Promise(r=>setTimeout(r,ms));
  const text=(el)=>el?.innerText?.trim()||el?.textContent?.trim()||'';
  const clean=s=>(s||'').replace(/\s+/g,' ').trim();
  const uniq=a=>[...new Set((a||[]).filter(Boolean))];
  let queryRoots=[]; let queryRootsAt=0;
  const refreshQueryRoots=()=>{
    if(Date.now()-queryRootsAt<1200&&queryRoots.length)return;
    const roots=[document];
    for(let i=0;i<roots.length;i++){
      try{for(const el of roots[i].querySelectorAll('*'))if(el.shadowRoot&&!roots.includes(el.shadowRoot))roots.push(el.shadowRoot)}catch(e){}
    }
    queryRoots=roots;queryRootsAt=Date.now();
  };
  const $all=s=>{refreshQueryRoots();const out=[];for(const root of queryRoots){try{out.push(...root.querySelectorAll(s))}catch(e){}}return [...new Set(out)]};
  const assetUrl=u=>{u=String(u||'').trim();if(u.startsWith('//'))u='https:'+u;return u.replace(/&amp;/g,'&')};
  const srcOf=img=>assetUrl(img?.currentSrc||img?.src||img?.getAttribute?.('data-src')||img?.getAttribute?.('data-ks-lazyload')||img?.getAttribute?.('data-lazyload-src')||'');
  const url=new URL(location.href); const itemId=url.searchParams.get('id')||location.href.match(/[?&]id=(\d+)/)?.[1]||''; const skuId=url.searchParams.get('skuId')||'';
  const bodyClone=document.body?.cloneNode(true);
  try{bodyClone?.querySelectorAll?.('[class*=recommend],[class*=Recommend],[class*=guess],[class*=Guess],[class*=related],[class*=Related],[class*=similar],[class*=Similar],[class*=猜你喜欢],[id*=recommend],[id*=guess]').forEach(n=>n.remove())}catch(e){}
  const bodyText=clean(bodyClone?.innerText||document.body?.innerText||'');
  const captured=[];
  const reviews=[]; const questions=[];
  const reviewCap=sampleMode==='all'?Infinity:Math.max(1,Math.min(10000,Number(sampleMode)||500));
  const reviewNetMeta={totals:[],hasMoreFalse:false,lastPageFlags:[],pageHints:[],networkReviewObjects:0,networkResponses:0};
  const reviewStartedAt=Date.now();
  const processedCaptureKeys=new Set();
  function dedupReviewCount(){const m=new Set();for(const r of reviews){const k=clean(r.content||'').replace(/\s+/g,'').slice(0,320);if(k)m.add(k)}return m.size}
  function publishReviewProgress(round=0,stagnant=0,mode='DOM',extra={}){const seen=new Set(),preview=[];for(let i=reviews.length-1;i>=0&&preview.length<3;i--){const c=clean(reviews[i]?.content||'');const k=c.replace(/\s+/g,'').slice(0,320);if(k&&!seen.has(k)){seen.add(k);preview.push(c.slice(0,70)+(c.length>70?'…':''))}}window.__TMALL_AI_REVIEW_PROGRESS__={
    count:dedupReviewCount(),
    rawCount:reviews.length,
    networkReviewObjects:reviewNetMeta.networkReviewObjects,
    networkResponses:reviewNetMeta.networkResponses,
    round,stagnant,mode,
    elapsedMs:Date.now()-reviewStartedAt,
    preview,
    capturePolicy:'passive_code_and_network',
    extraRequestsCreated:0,
    safety:'no_api_replay_no_auth_bypass_no_rate_limit_bypass',
    ...extra
  }}

  const looksQuestion=(c)=>{c=clean(c);return /问大家|更多回答|查看全部问答|大家问|^问[：:\s]|请问|请教|会不会|有没有|能不能|是否|怎么|如何|多少|适合|兼容|保质期|[？?]$/.test(c)};
  const addQuestion=(o,source='unknown')=>{ const q=clean(o?.question||o?.title||o?.ask||o?.content||o?.text||''); const a=clean(o?.answer||o?.reply||o?.answers?.[0]?.content||''); if(q.length>2)questions.push({question:q,answer:a,source}); };
  const reviewImageUrl=v=>assetUrl(typeof v==='string'?v:(v?.url||v?.picUrl||v?.imageUrl||v?.src||v?.bigUrl||v?.thumbnail||''));
  const validReviewImage=u=>/^https?:\/\//.test(u)&&!/(?:avatar|sns_logo|credit|logo|icon|defaultRate|sprite|\/tps\/|\/tfs\/TB1[^/]+-\d{1,4}-\d{1,4}\.png)/i.test(u);
  const addReview=(o,source='unknown')=>{ if(!o)return; const c=clean(o.content||o.rateContent||o.feedback||o.comment||o.text||o.contentText||''); if(c.length<3)return; if(looksQuestion(c)){addQuestion({question:c},source);return;} const media=uniq((o.images||o.pics||o.photos||[]).map(reviewImageUrl)).filter(validReviewImage).slice(0,24);reviews.push({content:c,appendContent:clean(o.appendContent||o.append||o.appendComment||''),rating:o.rating||o.rate||o.star||o.score||o.starLevel||'',sku:clean(o.sku||o.skuInfo||o.auctionSku||o.skuMap||''),date:clean(o.date||o.time||o.gmtCreate||o.rateDate||''),images:media,likes:o.likes||o.likeCount||0,source});};
  function scanPageMeta(obj){
    if(!obj||typeof obj!=='object'||Array.isArray(obj))return;
    for(const [k,v] of Object.entries(obj)){
      const key=String(k).toLowerCase();
      if(/^(total|totalcount|total_count|reviewcount|ratecount|commentcount|totalnum|totalnumber)$/.test(key)){
        const n=Number(String(v).replace(/,/g,'')); if(Number.isFinite(n)&&n>=0&&n<10000000)reviewNetMeta.totals.push(n);
      }
      if(/^(hasmore|has_more|hasnext|has_next|hasnextpage|has_next_page|more)$/.test(key) && (v===false||v===0||v==='false'||v==='0')) reviewNetMeta.hasMoreFalse=true;
      if(/^(lastpage|islast|is_last|islastpage|is_last_page|last|end|isend|is_end)$/.test(key) && (v===true||v===1||v==='true'||v==='1')) reviewNetMeta.lastPageFlags.push(true);
      if(/^(page|pageno|page_no|pagenum|page_num|currentpage|current_page)$/.test(key)){
        const n=Number(v); if(Number.isFinite(n)&&n>0)reviewNetMeta.pageHints.push(n);
      }
    }
  }
  function walk(obj,depth=0,sourceUrl=''){
    if(!obj||depth>10)return;
    if(Array.isArray(obj)){for(const x of obj.slice(0,2500))walk(x,depth+1,sourceUrl);return;}
    if(typeof obj!=='object')return;
    scanPageMeta(obj);
    const ks=Object.keys(obj); const qaUrl=/ask|question|wdj|qa/i.test(sourceUrl||'');
    const hasQ=ks.some(k=>/question|ask/i.test(k)); const hasA=ks.some(k=>/answer|reply/i.test(k));
    if(qaUrl || (hasQ&&hasA)) addQuestion(obj,sourceUrl||'network');
    else if(ks.some(k=>/rateContent|feedback|comment|contentText|reviewContent|rateText/i.test(k)) || ((('content'in obj)||('text'in obj))&&(/review|rate|comment|feedback|evaluate|评价|评论/i.test(sourceUrl||'') || ks.some(k=>/star|rating|sku|rate|append|user|buyer|date|time|pic|photo/i.test(k))))){
      const before=reviews.length; addReview(obj,sourceUrl||'network'); if(reviews.length>before)reviewNetMeta.networkReviewObjects++;
    }
    for(const k of ks){ const v=obj[k]; if(v&&typeof v==='object')walk(v,depth+1,sourceUrl); }
  }
  // V8.1.5：评论网络监听由 page-review-hook.js 在 document_start 提前安装。
  // 这里禁止再次重置 __TMALL_AI_CAPTURE__，否则会丢失用户打开商品页后已经收到的评论响应。
  // 如果极端情况下 MAIN-world hook 未安装，只记录状态并继续使用 DOM / inline JSON 兜底，不主动重放接口。
  if(!Array.isArray(window.__TMALL_AI_CAPTURE__)) window.__TMALL_AI_CAPTURE__=[];
  if(!Array.isArray(window.__TMALL_AI_SOURCE_SNAPSHOTS__)) window.__TMALL_AI_SOURCE_SNAPSHOTS__=[];

  const visible=(el)=>{try{const r=el.getBoundingClientRect?.();return !r||(r.width>0&&r.height>0)}catch(e){return true}};
  const textControl=(patterns)=>{
    const matches=$all('button,a,[role=tab],[role=button],li,div,span').filter(el=>{
      const t=clean(text(el));
      return visible(el)&&t&&t.length<=36&&patterns.some(pattern=>pattern.test(t));
    });
    return matches.sort((a,b)=>{
      const ai=/^(BUTTON|A)$/.test(a.tagName)||a.getAttribute('role')==='tab'||a.getAttribute('role')==='button';
      const bi=/^(BUTTON|A)$/.test(b.tagName)||b.getAttribute('role')==='tab'||b.getAttribute('role')==='button';
      return Number(bi)-Number(ai)||clean(text(a)).length-clean(text(b)).length;
    })[0];
  };
  const activatePanel=async(patterns)=>{
    const control=textControl(patterns);if(!control)return false;
    try{control.scrollIntoView({block:'center'});await delay(220);control.click();await delay(1000);queryRootsAt=0;return true}catch(e){return false}
  };
  const reviewDrawerOpen=()=>{
    const scrollBox=$all('[class*=comments],[class*=Comments],[class*=commentList],[class*=CommentList]').find(el=>{
      try{const style=getComputedStyle(el);return visible(el)&&/(auto|scroll)/.test(style.overflowY)&&el.clientHeight>180}
      catch(e){return false}
    });
    const drawer=$all('[class*=Drawer],[class*=drawer]').find(el=>visible(el)&&/用户评价/.test(clean(text(el))));
    return Boolean(scrollBox&&drawer);
  };
  const clickControl=async(el,waitMs=900)=>{
    if(!el)return false;
    try{
      el.scrollIntoView({block:'center',inline:'nearest'});await delay(220);
      el.click();await delay(waitMs);queryRootsAt=0;return true;
    }catch(e){return false}
  };
  const openReviewDrawer=async()=>{
    if(reviewDrawerOpen())return true;
    for(let attempt=0;attempt<4;attempt++){
      queryRootsAt=0;
      const showAll=$all('button,a,[role=button],div,span').filter(el=>{
        const t=clean(text(el));return visible(el)&&/^(查看全部评价|查看全部评论|全部评价|全部评论)$/.test(t);
      }).sort((a,b)=>{
        const score=el=>/ShowButton/i.test(String(el.className||''))?4:(/^(BUTTON|A)$/.test(el.tagName)||el.getAttribute('role')==='button'?3:/footer/i.test(String(el.className||''))?1:2);
        return score(b)-score(a)||clean(text(b)).length-clean(text(a)).length;
      })[0];
      if(showAll){publishReviewProgress(pagesVisited,0,'打开全部评价');await clickControl(showAll,1200);if(reviewDrawerOpen())return true;}
      const reviewTab=$all('button,a,[role=tab],[role=button],div,span').filter(el=>visible(el)&&clean(text(el))==='用户评价').sort((a,b)=>{
        const ac=/tabTitleItem/i.test(String(a.className||''));const bc=/tabTitleItem/i.test(String(b.className||''));return Number(bc)-Number(ac);
      })[0];
      if(reviewTab){publishReviewProgress(pagesVisited,0,'定位用户评价');await clickControl(/tabTitle/i.test(String(reviewTab.parentElement?.className||''))?reviewTab.parentElement:reviewTab,700);}
      else{window.scrollBy(0,700);await delay(500)}
    }
    return reviewDrawerOpen();
  };
  // V5: Collect all currently accessible effective reviews. Resume from page-local checkpoint when possible.
  const checkpointKey='__TMALL_AI_REVIEWS_V62__'+itemId;
  async function idbOpen(){return await new Promise((resolve,reject)=>{try{const req=indexedDB.open('TMALL_AI_V62',1);req.onupgradeneeded=()=>{const db=req.result;if(!db.objectStoreNames.contains('checkpoints'))db.createObjectStore('checkpoints')};req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error)}catch(e){reject(e)}})}
  async function loadCheckpoint(){try{const db=await idbOpen();return await new Promise((resolve,reject)=>{const tx=db.transaction('checkpoints','readonly');const req=tx.objectStore('checkpoints').get(checkpointKey);req.onsuccess=()=>resolve(req.result||{});req.onerror=()=>reject(req.error)})}catch(e){try{return JSON.parse(localStorage.getItem(checkpointKey)||'{}')||{}}catch(_){return {}}}}
  async function saveCheckpoint(data){try{const db=await idbOpen();await new Promise((resolve,reject)=>{const tx=db.transaction('checkpoints','readwrite');tx.objectStore('checkpoints').put(data,checkpointKey);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error)})}catch(e){try{localStorage.setItem(checkpointKey,JSON.stringify({...data,reviews:(data.reviews||[]).slice(-1500),questions:(data.questions||[]).slice(-500)}))}catch(_){}}}
  let checkpoint=await loadCheckpoint(); checkpoint=checkpoint||{};
  for(const r of (checkpoint.reviews||[])) addReview(r); for(const q of (checkpoint.questions||[])) addQuestion(q,q.source||'checkpoint');
  let collectionComplete=false, stopReason='unknown', pagesVisited=Number(checkpoint.round||0), explicitEnd=false;
  const domReviewSeen=new Set();
  function collectVisibleReviews(){
    const selectors=[
      '[class^="Comment--"]','[class^="comment--"]','[class*=rate-item]','[class*=rateItem]','[class*=review-item]','[class*=reviewItem]',
      '[class*=comment-item]','[class*=commentItem]','[class*=feedback-item]','[class*=feedbackItem]',
      '[data-testid*=review-card]','[data-testid=review]','[class*=ReviewItem]','[class*=CommentItem]','[class*=RateItem]','[class*=reviewCard]','[class*=commentCard]','[class*=rateCard]'
    ];
    const rawNodes=uniq(selectors.flatMap(s=>{try{return $all(s)}catch(e){return[]}}));
    const genericNodes=$all('article,[role=article],li,section,div').filter(el=>{
      const raw=String(el.innerText||'').replace(/\u00a0/g,' ').trim();
      return visible(el)&&raw.length>=10&&raw.length<=1500&&/20\d{2}[-/.年]\s*\d{1,2}[-/.月]\s*\d{1,2}/.test(raw)&&/[。！？!?，,]/.test(raw);
    });
    const genericAtomic=genericNodes.filter(n=>![...n.children].some(child=>genericNodes.includes(child)&&String(child.innerText||'').trim().length>=10));
    const nodes=uniq([...rawNodes,...genericAtomic]).filter(n=>!rawNodes.some(o=>o!==n&&o.contains?.(n))&&!genericAtomic.some(o=>o!==n&&o.contains?.(n))); // 只保留独立评论卡，避免父子容器重复/合并
    for(const b of nodes){
      const contentNode=b.querySelector?.('[class^="content--"],[class^="Content--"],[class*=comment-content],[class*=review-content],[class*=rate-content],[data-testid*=content]');
      const c=clean(text(contentNode)||text(b));
      if(c.length<8||c.length>1800) continue;
      const k=c.replace(/\s+/g,'').slice(0,240);
      if(domReviewSeen.has(k)) continue;
      domReviewSeen.add(k);
      const ratingText=clean(b.querySelector?.('[class*=star],[class*=score],[class*=rating]')?.getAttribute?.('aria-label')||text(b.querySelector?.('[class*=star],[class*=score],[class*=rating]')));
      const rm=ratingText.match(/([1-5](?:\.\d)?)/);
      const sku=clean(text(b.querySelector?.('[class*=sku],[class*=spec],[class*=auction]')));
      const metaText=clean(text(b.querySelector?.('time,[class*=date],[class*=time],[class^="meta--"]')));
      const date=metaText.match(/20\d{2}[^\d]?\d{1,2}[^\d]?\d{1,2}/)?.[0]||metaText;
      const purchased=metaText.match(/已购[：:]?\s*(.+)$/)?.[1]||'';
      const appendContent=clean((clean(text(b)).match(/(?:追评|追加评价)[：:]\s*(.{2,1200})/)||[])[1]||'');
      const images=uniq([...b.querySelectorAll?.('img')||[]].map(srcOf)).filter(validReviewImage).slice(0,16);
      addReview({content:c,appendContent,rating:rm?.[1]||'',sku:purchased||sku,date,images},'dom_visible');
    }
  }
  function scrollReviewContainers(){
    let moved=false;
    const boxes=$all('[class*=comments],[class*=Comments],[class*=commentList],[class*=CommentList],[class*=drawer],[class*=Drawer]').filter(el=>{
      try{return visible(el)&&el.scrollHeight>el.clientHeight+8}
      catch(e){return false}
    });
    for(const box of boxes){
      try{
        const old=box.scrollTop; const step=Math.max(420,Math.floor(box.clientHeight*.82));
        box.scrollTop=Math.min(box.scrollHeight-box.clientHeight,old+step);
        if(box.scrollTop>old+2)moved=true;
        box.dispatchEvent(new Event('scroll',{bubbles:true}));
      }catch(e){}
    }
    return moved;
  }
  function collectVisibleQuestions(){
    const selectors=['[class*=question]','[class*=Question]','[class*=ask]','[class*=Ask]','[class*=qa]','[class*=Qa]'];
    const nodes=uniq(selectors.flatMap(sel=>{try{return $all(sel)}catch(e){return[]}}));
    for(const b of nodes){const c=clean(text(b));if(c.length>=4&&c.length<=1800&&(/问大家|更多回答|查看全部问答|请问|请教|会不会|有没有|能不能|是否|怎么|如何|多少|适合|兼容|保质期|[？?]/.test(c)))addQuestion({question:c},'dom_question');}
  }
  // Trigger review/question areas if clickable text exists.
  // 先按用户通常的顺序打开详情/规格区域；新版页面常把参数放在折叠面板内。
  await activatePanel([/^(?:宝贝)?详情$/,/商品详情/,/规格参数|商品参数|产品参数/]);
  // 必须确认“查看全部评价”抽屉已打开；只点“用户评价”页签不算成功。
  const reviewDrawerWasOpened=await openReviewDrawer();
  // V8.0.4：实时、可终止、快速停滞检测。优先分页/加载更多，不再长时间整页空转。
  let stagnant=0;const MAX_ROUNDS=40;publishReviewProgress(pagesVisited,0,reviewDrawerWasOpened?'评论抽屉已打开':'读取页面可见评论',{reviewDrawerOpened:reviewDrawerWasOpened});
  for(let attempt=0;attempt<MAX_ROUNDS;attempt++){
    const round=pagesVisited;pagesVisited+=1;if(window.__TMALL_AI_STOP_REVIEW__){stopReason='user_stopped';publishReviewProgress(round,stagnant,'用户终止');break}
    const before=dedupReviewCount();const capBefore=(window.__TMALL_AI_CAPTURE__||[]).length;collectVisibleReviews();collectVisibleQuestions();publishReviewProgress(round,stagnant,'读取当前评论');
    const navNodes=$all('button,a,span,div,[role=button]');
    const next=navNodes.find(el=>{const t=clean(text(el));const dis=el.getAttribute?.('disabled')!=null||el.getAttribute?.('aria-disabled')==='true'||/disabled|next-disabled/.test(String(el.className||''));const r=el.getBoundingClientRect?.();return !dis&&t&&t.length<20&&/下一页|下页|查看更多|加载更多|更多评价|展开更多|下一批/.test(t)&&(!r||(r.width>0&&r.height>0))});
    const disabledNext=navNodes.find(el=>{const t=clean(text(el));const dis=el.getAttribute?.('disabled')!=null||el.getAttribute?.('aria-disabled')==='true'||/disabled|next-disabled/.test(String(el.className||''));return dis&&/下一页|下页/.test(t)});
    if(next){try{next.scrollIntoView({block:'center'});await delay(180);next.click();publishReviewProgress(round,stagnant,'加载下一批');await delay(1100+Math.floor(Math.random()*500))}catch(e){}}
    else{const rev=document.querySelector('[class*=review],[class*=rate],[class*=comment],[data-testid*=review]');try{rev?.scrollIntoView({block:'center'})}catch(e){}for(let i=0;i<4;i++){if(window.__TMALL_AI_STOP_REVIEW__)break;window.scrollBy(0,650);scrollReviewContainers();await delay(240);collectVisibleReviews();collectVisibleQuestions()}await delay(550)}
    if(window.__TMALL_AI_STOP_REVIEW__){stopReason='user_stopped';publishReviewProgress(round,stagnant,'用户终止');break}
    // 每轮即时解析已捕获网络响应
    const capNow=(window.__TMALL_AI_CAPTURE__||[]).slice(-120);for(const c of capNow){try{const ck=String(c.__safeKey||[c.method||'',c.url||'',String(c.text||'').slice(0,240)].join('|'));if(processedCaptureKeys.has(ck))continue;processedCaptureKeys.add(ck);if(/review|rate|comment|feed/i.test(c.url||''))reviewNetMeta.networkResponses++;let z=(c.text||'').replace(/^\s*[\w$.]+\(/,'').replace(/\)\s*;?\s*$/,'');try{walk(JSON.parse(z),0,c.url||'')}catch(_){const m=z.match(/\{[\s\S]*\}/);if(m)try{walk(JSON.parse(m[0]),0,c.url||'')}catch(__){}}}catch(e){}}
    collectVisibleReviews();collectVisibleQuestions();const after=dedupReviewCount();stagnant=after<=before?stagnant+1:0;publishReviewProgress(round+1,stagnant,next?'翻页/加载更多':'短滚动',{lastDelta:after-before});
    if(Number.isFinite(reviewCap) && after>=reviewCap){collectionComplete=true;explicitEnd=true;stopReason='sample_cap';publishReviewProgress(round+1,stagnant,`已采够 ${reviewCap} 条评论样本`);break}
    const bodyNow=clean(document.body?.innerText||'');const noMoreText=/没有更多(?:评价|评论)|已显示全部(?:评价|评论)|到底了|暂无更多(?:评价|评论)/.test(bodyNow);const captcha=/验证码|滑块|安全验证|访问过于频繁|操作频繁/.test(bodyNow);
    if(captcha){stopReason='human_verification_required';publishReviewProgress(round+1,stagnant,'需要人工验证');break}
    if((disabledNext||noMoreText)&&stagnant>=1){explicitEnd=true;collectionComplete=true;stopReason='explicit_last_page';publishReviewProgress(round+1,stagnant,'页面明确结束');break}
    // 连续4轮没有新增才停止；给异步评论接口和虚拟列表更多响应时间，但仍避免长时间空转。
    if(stagnant>=4){collectionComplete=false;explicitEnd=false;stopReason='no_progress_after_4_rounds';publishReviewProgress(round+1,stagnant,'无新增，停止空转');break}
    await saveCheckpoint({reviews,questions,round:round+1,updatedAt:Date.now()});
  }
  await delay(300);
  // V8.1.5 安全模式：
  // 只消费页面在正常浏览过程中已经产生的真实 fetch/XHR 响应。
  // 不根据 performance resource URL 主动重放请求，避免额外接口调用、重复页和频控风险。
  captured.push(...(window.__TMALL_AI_CAPTURE__||[]).slice(-100));

  // 同时读取页面已经内嵌的脚本/JSON快照，不产生任何网络请求。
  const sourceSnapshots=(window.__TMALL_AI_SOURCE_SNAPSHOTS__||[]).slice(-12);
  for(const snap of sourceSnapshots){
    captured.push({
      url:'page-source://inline-script',
      method:'SOURCE',
      status:200,
      text:String(snap?.text||'').slice(0,1200000),
      passive:true
    });
  }
  for(const c of captured){
    const ck=String(c.__safeKey||[c.method||'',c.url||'',String(c.text||'').slice(0,240)].join('|'));
    if(processedCaptureKeys.has(ck)) continue;
    processedCaptureKeys.add(ck);
    if(/review|rate|comment|feed/i.test(c.url||''))reviewNetMeta.networkResponses++;
    let s=c.text||''; s=s.replace(/^\s*[\w$.]+\(/,'').replace(/\)\s*;?\s*$/,'');
    try{walk(JSON.parse(s),0,c.url||'')}catch(e){ const m=s.match(/\{[\s\S]*\}/);if(m)try{walk(JSON.parse(m[0]),0,c.url||'')}catch(_){}}
  }
  // DOM fallback：仍按“单个评论卡”解析，不读取整块评价容器，避免把多条买家评论合并。
  collectVisibleReviews(); collectVisibleQuestions();
  // 评论采集完成后再切换问大家，读取页面正常加载出来的问答，不额外调用接口。
  const qaNow=$all('a,button,div,span,[role=tab]').find(el=>{const t=clean(text(el));return t&&t.length<32&&/问大家|大家问/.test(t)});
  if(qaNow){
    try{
      qaNow.scrollIntoView({block:'center'});await delay(220);qaNow.click();await delay(1000);
      for(let i=0;i<3;i++){collectVisibleQuestions();window.scrollBy(0,420);await delay(220)}
      collectVisibleQuestions();
    }catch(e){}
  }
  // 评论完成后重新打开详情/规格面板，避免问大家面板覆盖参数区域。
  await activatePanel([/^(?:宝贝)?详情$/,/商品详情/,/规格参数|商品参数|产品参数/]);
  // 像正常浏览一样有限滚动详情容器，触发页面自身的图片懒加载；不创建额外接口请求。
  const detailRootSelectors=['#J_DivItemDesc','#description','[id="description"]','[class*="detailContent"]','[class*="DetailContent"]','[class*="detail-content"]','[class*="descV8"]','[class^="desc--"]','[data-testid*="product-description"]','[class*="ProductDetail"]','[class*="productDetail"]','[class*="detailDesc"]','[class*="DetailDesc"]','[class*="moduleDesc"]','[class*="ModuleDesc"]','[class*="contentDetail"]','[class*="ContentDetail"]','[class*="aplus"]','[class*="Aplus"]'];
  const detailRoots=uniq(detailRootSelectors.flatMap(sel=>{try{return $all(sel)}catch(e){return[]}}));
  const detailScanUrls=[];
  const scanRootImages=root=>{try{for(const img of root.querySelectorAll('img')){const u=srcOf(img);if(u&&!detailScanUrls.includes(u))detailScanUrls.push(u)}}catch(e){}};
  for(const root of detailRoots.slice(0,4)){
    try{
      const box=root.getBoundingClientRect();const top=Math.max(0,window.scrollY+box.top-120);const height=Math.max(box.height,root.scrollHeight||0);const rounds=Math.min(14,Math.max(1,Math.ceil(height/700)));
      for(let i=0;i<rounds;i++){window.scrollTo({top:top+Math.min(height-1,i*700),behavior:'auto'});await delay(150);scanRootImages(root)}
    }catch(e){}
  }
  // Product facts: DOM first, then schema/meta and page-owned inline state for the 2025 Taobao/Tmall detail app.
  const freshClone=document.body?.cloneNode(true);
  try{freshClone?.querySelectorAll?.('[class*=recommend],[class*=Recommend],[class*=guess],[class*=Guess],[class*=related],[class*=Related],[class*=similar],[class*=Similar],[id*=recommend],[id*=guess]').forEach(n=>n.remove())}catch(e){}
  const liveBodyRaw=freshClone?.innerText||document.body?.innerText||'';
  const liveBodyText=clean(liveBodyRaw);
  const firstText=(selectors)=>{for(const sel of selectors){try{const v=clean(text(document.querySelector(sel)));if(v)return v}catch(e){}}return''};
  const meta=(selectors)=>{for(const sel of selectors){try{const v=clean(document.querySelector(sel)?.getAttribute?.('content')||'');if(v)return v}catch(e){}}return''};
  const scalar=v=>(typeof v==='string'||typeof v==='number')?clean(String(v)):'';
  const structured={titles:[],shops:[],brands:[],categories:[],prices:[],sold:[],sku:[],attrs:[],promos:[],images:[],imageRecords:[]};
  const addSignal=(group,value,max=300)=>{value=scalar(value);if(value&&value.length<=max&&!structured[group].includes(value))structured[group].push(value)};
  const roots=[];
  for(const script of $all('script[type="application/ld+json"],script#__NEXT_DATA__,script[type="application/json"]')){
    const raw=String(script.textContent||'').trim();if(!raw||raw.length>6000000)continue;
    try{roots.push(JSON.parse(raw))}catch(e){}
  }
  for(const key of ['__INITIAL_STATE__','__INIT_DATA__','__DATA__','__SSR_DATA__','__APOLLO_STATE__']){
    try{const value=window[key];if(value&&typeof value==='object')roots.push(value)}catch(e){}
  }
  const seenStructured=new WeakSet();let structuredNodes=0;
  function walkProduct(obj,path='',depth=0){
    if(!obj||typeof obj!=='object'||depth>11||structuredNodes>30000||seenStructured.has(obj))return;
    seenStructured.add(obj);structuredNodes++;
    if(Array.isArray(obj)){for(const x of obj.slice(0,2000))walkProduct(x,path,depth+1);return}
    const objName=scalar(obj.attrName||obj.propertyName||obj.propName||obj.name||obj.label||obj.key);
    const objValue=scalar(obj.attrValue||obj.propertyValue||obj.valueName||obj.value||obj.text);
    if(objName&&objValue&&/(?:attr|param|property|prop|feature|规格|参数|属性)/i.test(path))structured.attrs.push({name:objName,value:objValue});
    for(const [key,value] of Object.entries(obj)){
      const lower=String(key).toLowerCase(),next=path?path+'.'+lower:lower;
      if(value&&typeof value==='object'){walkProduct(value,next,depth+1);continue}
      const valueText=scalar(value);if(!valueText)continue;
      if(/^(title|itemtitle|item_title|auctiontitle|producttitle|subject|name)$/.test(lower)&&/(?:item|product|auction|detail|schema|offers?|^$)/i.test(path))addSignal('titles',valueText,260);
      if(/^(shopname|shop_name|shoptitle|sellername|seller_name|storename|store_name|nick)$/.test(lower))addSignal('shops',valueText,160);
      if(/^(brand|brandname|brand_name)$/.test(lower))addSignal('brands',valueText,120);
      if(/^(category|categoryname|category_name|catname)$/.test(lower))addSignal('categories',valueText,160);
      if(/^(price|pricetext|price_text|promotionprice|promotion_price|saleprice|sale_price|pricevalue)$/.test(lower))addSignal('prices',valueText,80);
      if(/^(sold|soldcount|sold_count|sales|salescount|sales_count|monthsold|monthlysales)$/.test(lower))addSignal('sold',valueText,80);
      if(/(?:sku|property|prop|spec)/i.test(path)&&/^(name|text|title|value|valuename|value_name)$/.test(lower))addSignal('sku',valueText,100);
      if(/(?:promo|promotion|activity|coupon|discount|benefit|service)/i.test(next))addSignal('promos',valueText,220);
      if(/(?:image|img|pic|picture|thumb)/i.test(lower)&&/^https?:\/\/|^\/\//i.test(valueText)){
        const imageUrl=assetUrl(valueText);addSignal('images',imageUrl,1200);
        if(imageUrl&&!structured.imageRecords.some(x=>x.url===imageUrl&&x.path===next))structured.imageRecords.push({url:imageUrl,path:next});
      }
    }
  }
  for(const root of roots)walkProduct(root);
  const relevantScripts=$all('script').map(s=>String(s.textContent||'')).filter(s=>s.length>20&&s.length<=6000000&&(s.includes(itemId)||/itemTitle|auctionTitle|shopName|skuBase|priceInfo|promotion/i.test(s))).slice(0,16);
  const scriptCorpus=relevantScripts.join('\n').slice(0,10000000);
  const scriptString=(keys,max=300)=>{
    for(const key of keys){
      const escaped=key.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
      const m=scriptCorpus.match(new RegExp('["\\\']'+escaped+'["\\\']\\s*:\\s*"((?:\\\\.|[^"\\\\]){1,'+max+'})"','i'));
      if(m){try{return clean(JSON.parse('"'+m[1]+'"'))}catch(e){return clean(m[1].replace(/\\u([0-9a-f]{4})/gi,(_,h)=>String.fromCharCode(parseInt(h,16))))}}
    }
    return'';
  };
  const validProductTitle=value=>{
    value=clean(value).replace(/[-_–—|]\s*(淘宝网|天猫|淘宝).*$/,'');
    if(value.length<4||value.length>260)return'';
    if(/用户评价|累计评价|商品评价|问大家|参数信息|规格参数|图文详情|商品详情|登录|验证码/.test(value))return'';
    return value;
  };
  const titleCandidates=[
    meta(['meta[property="og:title"]','meta[name="twitter:title"]']),
    ...structured.titles,
    scriptString(['itemTitle','auctionTitle','productTitle']),
    firstText(['[data-testid="item-title"]','[data-testid*=item-title]','h1[class*="ItemTitle"]','h1[class*="itemTitle"]','[class*="ItemTitle--"]','[class*="itemTitle--"]','h1']),
    clean(document.title)
  ];
  const title=titleCandidates.map(validProductTitle).find(Boolean)||'';
  const visiblePriceTexts=$all('[class*=price],[class*=Price],[data-testid*=price]').filter(el=>{const r=el.getBoundingClientRect?.();return !r||(r.width>0&&r.height>0&&r.top<1600)}).map(text).map(clean).filter(x=>/\d/.test(x)).slice(0,30);
  const metaPrice=meta(['meta[property="product:price:amount"]','meta[property="og:price:amount"]','meta[itemprop="price"]']);
  const visiblePrice=(visiblePriceTexts.join(' ')+' '+liveBodyText.slice(0,6000)).match(/(?:到手价|券后价|活动价|促销价|价格)?\s*[¥￥]\s*(\d{1,7}(?:\.\d{1,2})?)/)?.[1]||(liveBodyText.slice(0,6000).match(/(?:到手价|券后价|活动价|促销价|价格)\s*[：:]?\s*(\d{1,7}(?:\.\d{1,2})?)/)||[])[1]||'';
  const fallbackPrice=structured.prices[0]||scriptString(['promotionPrice','salePrice','priceText','price'],80);
  const priceValue=(String(metaPrice).match(/\d{1,7}(?:\.\d{1,2})?/)||[])[0]||visiblePrice||(String(fallbackPrice).match(/\d{1,7}(?:\.\d{1,2})?/)||[])[0]||'';
  const soldMatch=liveBodyText.match(/(?:已售|销量|月销|付款|成交)\s*([\d,.万+]+)/);
  const soldValue=soldMatch?.[1]||structured.sold[0]||scriptString(['soldCount','salesCount','monthSold','monthlySales'],80);
  const rankMatch=liveBodyText.match(/(?:热销榜|榜单|排名)[^\d]{0,8}(?:第)?\s*(\d+)\s*名?/);
  const shop=firstText(['[data-testid*=shop]','[class*=shopName]','[class*=shop-name]','[class*=ShopName]','[class*=sellerName]','[class*=SellerName]','[class*=storeName]','[class*=StoreName]'])||meta(['meta[name="seller"]'])||structured.shops[0]||scriptString(['shopName','shopTitle','sellerName','storeName'],160);
  const domSkuTexts=$all('[class*=sku] button,[class*=sku] li,[class*=sku] label,[class*=sku] [role=button],[class*=Sku] button,[class*=Sku] li,[class*=prop] button,[class*=Prop] button,[data-testid*=sku] button').map(text).map(clean);
  const skuTexts=uniq([...domSkuTexts,...structured.sku]).filter(x=>x&&x.length<100&&!/加入购物车|立即购买|领券购买|购买|收藏|客服|分享|确定|取消|数量/.test(x)).slice(0,160);
  // 参数必采：同时读取属性列表、规格参数、表格、dt/dd 等常见结构；只保留短文本，避免把整块详情正文误当参数。
  const paramPairs=[];
  const validParam=(name,value)=>{
    if(!name||!value||name.length>60||value.length>220)return false;
    if(/^\d+$/.test(name)||/(?:window\.|console\.|function\b|frontend_data|performance\.|[{}\[\]"'=;<>])/i.test(name))return false;
    if(/(?:console\.log|window\.|performance\.now|frontend_data)/i.test(value))return false;
    return /[\u4e00-\u9fffA-Za-z]/.test(name);
  };
  const pushParam=(name,value)=>{name=clean(name);value=clean(value);if(!validParam(name,value))return;const k=name+'\u0000'+value;if(!paramPairs.some(x=>x._k===k))paramPairs.push({name,value,_k:k});};
  const parseParamText=(s)=>{s=clean(s);if(!s||s.length>260)return;const m=s.match(/^([^：:]{1,60})[：:]\s*(.{1,220})$/);if(m)pushParam(m[1],m[2]);};
  for(const el of $all('[class*=attr] li,[class*=Attr] li,[class*=parameter] li,[class*=Parameter] li,[class*=prop] li,[class*=Prop] li,[class*=specification] li,[class*=Specification] li,[class*=attribute] li,[class*=Attribute] li')) parseParamText(text(el));
  for(const dl of $all('dl')){const dts=[...dl.querySelectorAll('dt')],dds=[...dl.querySelectorAll('dd')];for(let i=0;i<Math.min(dts.length,dds.length);i++)pushParam(text(dts[i]),text(dds[i]));}
  for(const tr of $all('table tr')){const cells=[...tr.querySelectorAll('th,td')].map(text).map(clean).filter(Boolean);if(cells.length>=2)pushParam(cells[0],cells.slice(1).join(' '));}
  // 兜底读取页面中常见“键：值”短行。
  const paramTextNodes=$all('[class*=attr],[class*=parameter],[class*=specification],[class*=attribute]').slice(0,80);
  for(const el of paramTextNodes){for(const line of String(text(el)||'').split(/\n+/).slice(0,80))parseParamText(line);}
  // 淘宝新版经常移除参数容器 class，但可见页面仍保留“字段：值”短行。
  for(const line of String(liveBodyRaw||'').split(/\n+/).slice(0,5000))parseParamText(line);
  for(const el of $all('li,dt,dd,tr,td,th,[role=listitem]').slice(0,3000)){
    for(const line of String(el.innerText||'').split(/\n+/).slice(0,12))parseParamText(line);
  }
  // 当前淘宝新版参数是“值 + 字段名”或“字段名 + 值”两列，没有冒号。
  for(const el of $all('[class*="emphasisParamsInfoItem--"],[class*="generalParamsInfoItem--"]').slice(0,400)){
    const children=[...el.children].filter(child=>clean(child.getAttribute?.('title')||text(child)));
    if(children.length<2)continue;
    const values=children.map(child=>clean(child.getAttribute?.('title')||text(child)));
    const isGeneral=/generalParamsInfoItem/i.test(String(el.className||''));
    const label=isGeneral?values[0]:values[1];
    const value=isGeneral?values[1]:values[0];
    pushParam(label,value);
  }
  for(const pair of structured.attrs)pushParam(pair.name,pair.value);
  const attrs=paramPairs.slice(0,240).map(({name,value})=>({name,value}));
  const PARAM_GROUPS={
    '基础身份':['品牌','品类','型号','货号','名称'],
    '规格选择':['规格','尺寸','尺码','颜色','容量','净含量','口味','版本','数量','包装'],
    '材质/成分/配置':['材质','面料','成分','配料','填充','配置','处理器','内存','存储'],
    '功能与适用':['功能','功效','适用','肤质','兼容','性能','版型','风格','场景'],
    '工艺与使用':['工艺','做工','使用','洗护','洗涤','清洗','保养','食用方法'],
    '合规与服务':['产地','等级','执行标准','保质期','生产日期','认证','质保','售后']
  };
  function evaluateParameterCollectionJS(list){
    const found=[],missing=[];const keys=(list||[]).map(x=>clean(x.name)).filter(Boolean);
    for(const [canon,aliases] of Object.entries(PARAM_GROUPS)){
      const hit=(list||[]).some(x=>aliases.some(a=>clean(x.name).includes(a))&&clean(x.value));
      (hit?found:missing).push(canon);
    }
    const state=(list||[]).length>=3?'complete':((list||[]).length?'partial':'missing');
    return {state,stateText:state==='complete'?'动态参数已采集':state==='partial'?'参数样本较少':'未识别到有效参数',count:(list||[]).length,keys:keys.slice(0,50),found,missing:state==='missing'?['页面动态参数']:[]};
  }
  const parameterCollection=evaluateParameterCollectionJS(attrs);
  const promoDom=$all('[class*=promo],[class*=Promo],[class*=coupon],[class*=Coupon],[class*=activity],[class*=Activity],[class*=discount],[class*=Discount],[class*=service],[class*=Service]').map(text).map(clean);
  const promoLines=String(liveBodyRaw||'').split(/\n+/).map(clean).filter(x=>x.length>=2&&x.length<=180&&/(减|券|折|赠|包邮|价保|退|换新|补贴|立减|满|活动|优惠|会员|服务)/.test(x));
  const promoTexts=uniq([...promoDom,...promoLines,...structured.promos]).filter(x=>x&&x.length>=2&&x.length<=220&&/(减|券|折|赠|包邮|价保|退|换新|补贴|立减|满|活动|优惠|会员|服务)/.test(x)).slice(0,120);
  const isRecImg=img=>{try{return !!img.closest('[class*=recommend],[class*=Recommend],[class*=guess],[class*=Guess],[class*=related],[class*=Related],[class*=similar],[class*=Similar],[id*=recommend],[id*=guess]')}catch(e){return false}};
  const validImg=u=>/^https?:\/\//.test(u)&&!/icon|logo|avatar|sprite|shopmanager|\/tps\/|\/tfs\/TB1[^/]+-\d{1,4}-\d{1,4}\.png|(?:-|_)rate(?:\.|_|-)|rate_livephoto|tbbala|alicdn.*\.gif/i.test(u);
  const deReview=new Map();
  for(const r of reviews){
    const k=clean(r.content).replace(/\s+/g,'').slice(0,320);if(!k)continue;
    if(!deReview.has(k))deReview.set(k,{...r,images:uniq((r.images||[]).map(reviewImageUrl)).filter(validReviewImage)});
    else{const old=deReview.get(k);old.images=uniq([...(old.images||[]),...(r.images||[]).map(reviewImageUrl)]).filter(validReviewImage).slice(0,24)}
  }
  let reviewRows=[...deReview.values()];
  // 评论过多时保留最有决策价值的样本：差评、带图、最新评论优先，其余按原顺序补齐。
  let reviewSampled=false;
  if(reviewRows.length>reviewCap){
    const scored=reviewRows.map((r,i)=>{const rating=Number(String(r.rating||'').match(/[1-5]/)?.[0]||5);const bad=rating<=3?5:0;const media=(r.images||[]).length?3:0;const date=Date.parse(String(r.date||''));const rec=Number.isFinite(date)?Math.max(0,Math.min(2,(date-Date.now()+31536000000)/31536000000)):0;return {r,i,score:bad+media+rec}});
    scored.sort((a,b)=>b.score-a.score||a.i-b.i);
    const keep=new Set(scored.slice(0,reviewCap).map(x=>x.i));
    reviewRows=reviewRows.filter((_,i)=>keep.has(i)); reviewSampled=true;
  }
  const buyerCandidates=uniq(reviewRows.flatMap(r=>r.images||[])).filter(validReviewImage);
  const metaImage=assetUrl(meta(['meta[property="og:image"]','meta[name="twitter:image"]','meta[itemprop="image"]']));
  const isMainRegionImg=img=>{try{if(isRecImg(img)||img.closest('[class*=review],[class*=Review],[class*=rate],[class*=Rate],[class*=comment],[class*=Comment],[class*=detail],[class*=Detail],[class*=desc],[class*=Desc]'))return false;const r=img.getBoundingClientRect();return r.top<1800&&r.bottom>-80&&r.width>=34&&r.height>=34&&r.left<innerWidth*.76}catch(e){return false}};
  const mainGallerySelector='[class*="PicGallery--"],[class*="picGallery--"],[class*="MainPic--"],[class*="mainPic--"],[class*="main-picture"],[class*="mainPicture"],[data-testid*="main-image"],[data-testid*="gallery"],#J_UlThumb,[class*="Gallery"],[class*="gallery"],[class*="Photo"],[class*="photo"],[class*="Thumb"],[class*="thumb"],[class*="PicList"],[class*="picList"]';
  const isMainGalleryImg=img=>{try{if(isRecImg(img)||img.closest('[class*=review],[class*=Review],[class*=rate],[class*=Rate],[class*=comment],[class*=Comment],[class*=detail],[class*=Detail],[class*=desc],[class*=Desc]'))return false;const inGallery=!!img.closest(mainGallerySelector);const w=img.naturalWidth||img.width||img.getBoundingClientRect().width;const h=img.naturalHeight||img.height||img.getBoundingClientRect().height;return inGallery?(w>=34&&h>=34):isMainRegionImg(img)}catch(e){return false}};
  const mainDom=$all(mainGallerySelector+' img').filter(isMainGalleryImg).map(srcOf);
  const skuDom=$all('[class*="SkuContent--"] img,[class*="skuContent--"] img,[class*="SkuItem--"] img,[class*="skuItem--"] img,[data-testid*="sku"] img,[class*="sku"] [role="button"] img,[class*="Sku"] [role="button"] img').filter(img=>!isRecImg(img)).map(srcOf);
  const detailDom=uniq([...detailScanUrls,...detailRoots.flatMap(root=>{try{return [...root.querySelectorAll('img')].filter(img=>!isRecImg(img)).map(srcOf)}catch(e){return[]}})]);
  const structuredMain=structured.imageRecords.filter(x=>/(?:main|gallery|itempic|auctionpic|primary|header)/i.test(x.path)&&!/(?:detail|desc|review|rate|comment|sku|prop|recommend|shop)/i.test(x.path)).map(x=>x.url);
  const structuredDetail=structured.imageRecords.filter(x=>/(?:detail|desc|module|content|aplus)/i.test(x.path)&&!/(?:review|rate|comment|recommend|shop)/i.test(x.path)).map(x=>x.url);
  const structuredSku=structured.imageRecords.filter(x=>/(?:sku|prop|spec)/i.test(x.path)&&!/(?:review|rate|comment)/i.test(x.path)).map(x=>x.url);
  const buyerSet=new Set(buyerCandidates);
  const skuImages=uniq([...skuDom,...structuredSku]).filter(validImg).filter(u=>!buyerSet.has(u)).slice(0,80);const skuSet=new Set(skuImages);
  const main=uniq([metaImage,...mainDom,...structuredMain]).filter(validImg).filter(u=>!buyerSet.has(u)&&!skuSet.has(u)).slice(0,24);const mainSet=new Set(main);
  const detail=uniq([...detailDom,...structuredDetail]).filter(validImg).filter(u=>!buyerSet.has(u)&&!skuSet.has(u)&&!mainSet.has(u)).slice(0,160);
  const buyer=buyerCandidates.slice(0,200);
  const allPageCandidates=uniq($all('img').filter(img=>!isRecImg(img)).map(srcOf)).filter(validImg);
  const allImgs=uniq([...main,...detail,...skuImages,...buyer]);
  const provenance=[];
  for(const u of main)provenance.push({url:u,group:'main',source:u===metaImage?'meta_og_image':structuredMain.includes(u)?'structured_main_gallery':'dom_main_gallery'});
  for(const u of detail)provenance.push({url:u,group:'detail',source:structuredDetail.includes(u)?'structured_product_description':'dom_product_description'});
  for(const u of skuImages)provenance.push({url:u,group:'sku',source:structuredSku.includes(u)?'structured_sku_selector':'dom_sku_selector'});
  reviewRows.forEach((r,reviewIndex)=>{for(const u of r.images||[])if(buyerSet.has(u))provenance.push({url:u,group:'buyerShow',source:'review_record',reviewIndex:reviewIndex+1,reviewSource:r.source||'unknown'})});
  const deQ=new Map(); for(const q of questions){const k=clean(q.question).replace(/\s+/g,'').slice(0,260);if(k&&!deQ.has(k))deQ.set(k,q)}
  const publicRaw=(liveBodyText.match(/(?:评价|评论)[^\d]{0,8}([\d,.]+\s*万?\+?)/)||[])[1]||'';
  const parseCount=v=>{v=String(v||'').replace(/,/g,'').trim();const m=v.match(/([\d.]+)\s*(万)?/);if(!m)return null;return Math.round(parseFloat(m[1])*(m[2]?10000:1))};
  const publicNumeric=parseCount(publicRaw);
  const foldedDefaultMatch=liveBodyText.match(/已折叠\s*([\d,.]+)\s*条[^\n]{0,30}评价/);
  const defaultPraiseMatch=liveBodyText.match(/近半年\s*([\d,.]+)\s*位买家默认好评/);
  const networkTotal=reviewNetMeta.totals.length?Math.max(...reviewNetMeta.totals.filter(n=>Number.isFinite(n))):null;
  if(publicNumeric&&deReview.size>=publicNumeric){collectionComplete=true;explicitEnd=true;stopReason='matched_public_review_count';}
  else if(networkTotal!==null&&networkTotal>0&&deReview.size>=networkTotal){collectionComplete=true;explicitEnd=true;stopReason='matched_network_review_total';}
  else if((reviewNetMeta.hasMoreFalse||reviewNetMeta.lastPageFlags.length>0) && deReview.size>0){collectionComplete=true;explicitEnd=true;stopReason='network_explicit_end';}
  // 严禁“无新增/无下一页控件”单独作为完整依据
  const completeness=collectionComplete?'confirmed':'unconfirmed';
  await saveCheckpoint({reviews:[...deReview.values()],questions:[...deQ.values()],round:pagesVisited,updatedAt:Date.now(),complete:collectionComplete,stopReason,completeness,networkTotal,publicNumeric,reviewNetMeta});
  return {
    meta:{platform:location.hostname.includes('tmall')?'tmall':'taobao',collectedAt:new Date().toISOString(),url:location.href,collectorVersion,imageClassificationVersion:'strict-v1',networkCaptures:captured.length,structuredRoots:roots.length},
    product:{itemId,skuId,title,shop,brand:structured.brands[0]||scriptString(['brandName','brand'],120),category:structured.categories[0]||scriptString(['categoryName','catName'],160),url:location.href,parameterCollection},
    sales:{currentPrice:priceValue,sold:soldValue,ranking:rankMatch?.[1]||''},
    sku:skuTexts.map(name=>({name})),attributes:attrs,promotions:promoTexts.map(text=>({text})),
    images:{main,detail,sku:skuImages,buyerShow:buyer,all:allImgs,provenance,classification:{version:'strict-v1',classifiedCount:allImgs.length,unclassifiedCount:Math.max(0,allPageCandidates.length-allImgs.length),groupsAreDisjoint:true}},
    reviews:reviewRows,questions:[...deQ.values()],pageText:liveBodyText.slice(0,120000),collection:{reviewActual:deReview.size,reviewSampled,reviewSampleCap:Number.isFinite(reviewCap)?reviewCap:null,reviewCollectionMode:sampleMode,questionActual:deQ.size,reviewDrawerOpened:reviewDrawerWasOpened,reviewCollectionComplete:collectionComplete,reviewCompleteness:reviewSampled?'sampled':(collectionComplete?'confirmed':'unconfirmed'),reviewStopReason:reviewSampled?'sample_cap':stopReason,reviewPagesVisited:pagesVisited,publicReviewCount:publicRaw,publicReviewCountNumeric:publicNumeric,foldedDefaultReviewCount:foldedDefaultMatch?parseCount(foldedDefaultMatch[1]):null,defaultPraiseBuyerCount:defaultPraiseMatch?parseCount(defaultPraiseMatch[1]):null,networkReviewTotal:networkTotal,networkReviewObjects:reviewNetMeta.networkReviewObjects,networkReviewResponses:reviewNetMeta.networkResponses,networkExplicitEnd:reviewNetMeta.hasMoreFalse||reviewNetMeta.lastPageFlags.length>0,explicitEnd,reviewLive:window.__TMALL_AI_REVIEW_PROGRESS__||null}
  };
}
