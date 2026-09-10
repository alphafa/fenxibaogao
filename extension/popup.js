const SERVER='http://127.0.0.1:17962';
const EXPECTED_SERVER_VERSION='9.3.0';
let backendCompatible=false;
const server=document.getElementById('server'),status=document.getElementById('status'),bar=document.getElementById('bar'),runBtn=document.getElementById('run'),stopBtn=document.getElementById('stop'),reviewLive=document.getElementById('reviewLive'),liveCount=document.getElementById('liveCount'),liveNet=document.getElementById('liveNet'),liveRound=document.getElementById('liveRound'),liveStagnant=document.getElementById('liveStagnant'),liveMode=document.getElementById('liveMode'),liveElapsed=document.getElementById('liveElapsed'),livePreview=document.getElementById('livePreview');
const paramLive=document.getElementById('paramLive'),paramState=document.getElementById('paramState'),paramCount=document.getElementById('paramCount'),paramTags=document.getElementById('paramTags'),paramMissing=document.getElementById('paramMissing');
const analysisModelState=document.getElementById('analysisModelState'),imageModelState=document.getElementById('imageModelState');
function modelStatus(configured,model,probe){
 const name=String(model||'').trim();
 if(!configured) return {text:'待配置',className:'warn'};
 if(probe===true) return {text:(name||'已填写')+' · 已验证',className:'ok'};
 return {text:(name||'已填写')+' · 待测试',className:'pending'};
}
async function active(){return (await chrome.tabs.query({active:true,currentWindow:true}))[0]}
function itemIdFromUrl(u){try{return new URL(u).searchParams.get('id')||((u||'').match(/[?&]id=(\d+)/)||[])[1]||''}catch(e){return''}}
async function refresh(){
 let h={ok:false};
 try{h=await chrome.runtime.sendMessage({type:'HEALTH'})||{ok:false}}catch(e){h={ok:false,error:String(e)}}
 backendCompatible=!!(h?.ok && h.serverVersion===EXPECTED_SERVER_VERSION);
 if(!h?.ok){
   server.textContent='本地服务未启动 ✕';
   server.className='state warn';
   if(analysisModelState){analysisModelState.textContent='服务不可用';analysisModelState.className='warn'}
   if(imageModelState){imageModelState.textContent='服务不可用';imageModelState.className='warn'}
 }else if(!backendCompatible){
   server.textContent=`版本不一致 ✕ 插件 ${EXPECTED_SERVER_VERSION} / 后端 ${h.serverVersion||'未知'}，请启动本包最新服务`;
   server.className='state warn';
   const analysis=modelStatus(h.modelConfigured,h.model,h.modelProbe?.ok===true),image=modelStatus(h.imageModelConfigured,h.imageModel,h.imageProbe?.ok===true);
   if(analysisModelState){analysisModelState.textContent=analysis.text;analysisModelState.className=analysis.className}
   if(imageModelState){imageModelState.textContent=image.text;imageModelState.className=image.className}
 }else{
   const analysis=modelStatus(h.modelConfigured,h.model,h.modelProbe?.ok===true),image=modelStatus(h.imageModelConfigured,h.imageModel,h.imageProbe?.ok===true);
   server.textContent=`本地服务 ✓ V${h.serverVersion} · 分析${analysis.text} · 生图${image.text}`;
   server.className='state ok';
   if(analysisModelState){analysisModelState.textContent=analysis.text;analysisModelState.className=analysis.className}
   if(imageModelState){imageModelState.textContent=image.text;imageModelState.className=image.className}
 }
 const t=await active(); if(!t)return; const id=itemIdFromUrl(t.url||'');
 if(!id){status.textContent='请打开天猫/淘宝商品详情页';return}
 const k='status_'+t.id; const d=(await chrome.storage.local.get(k))[k];
 if(d){status.textContent=d.message||d.state;bar.style.width=(d.progress||0)+'%';runBtn.textContent=(d.state==='reviews_incomplete'||d.state==='reviews_stopped')?'继续采集评论':'开始深度采集';const lp=d.reviewLive;const activeCollect=d.state==='collecting'||d.state==='collecting_reviews';stopBtn.style.display=activeCollect?'block':'none';reviewLive.style.display=(lp||activeCollect||d.state==='reviews_incomplete'||d.state==='reviews_stopped')?'block':'none';const ps=d.parameterStatus;
   paramLive.style.display=ps?'block':'none';
   if(ps){
     paramState.textContent=ps.stateText||'已采集';
     paramCount.textContent=ps.count??0;
     paramTags.innerHTML=(ps.keys||[]).slice(0,10).map(k=>`<span class="param-tag">${String(k).replace(/[<>&]/g,s=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[s]))}</span>`).join('')||'<span class="param-tag">暂无</span>';
     paramMissing.textContent='缺失项：'+((ps.missing||[]).length?(ps.missing.join('、')):'无');
   }
   if(lp){liveCount.textContent=lp.count??0;liveNet.textContent=lp.networkReviewObjects??0;liveRound.textContent=lp.round??0;liveStagnant.textContent=lp.stagnant??0;liveMode.textContent=lp.mode||'—';liveElapsed.textContent=Math.round((lp.elapsedMs||0)/1000)+'s';livePreview.innerHTML=(lp.preview||[]).map((x,i)=>`<div>${i+1}. ${String(x).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}</div>`).join('')||'等待评论数据…'}}else{status.textContent='已识别当前商品，等待手动开始。';bar.style.width='0%';runBtn.textContent='开始深度采集';stopBtn.style.display='none';reviewLive.style.display='none'}
}
let collectionMode='500';
const sampleButtons=[...document.querySelectorAll('[data-sample]')];
const customSampleWrap=document.getElementById('customSampleWrap');
const customSample=document.getElementById('customSample');
sampleButtons.forEach(btn=>btn.addEventListener('click',()=>{sampleButtons.forEach(x=>x.classList.remove('active'));btn.classList.add('active');collectionMode=btn.dataset.sample;customSampleWrap.style.display=collectionMode==='custom'?'block':'none';}));
;(async()=>{try{const t=await active();const p=(await chrome.storage.local.get('status_'+t.id))['status_'+t.id];if((p?.state==='reviews_incomplete'||p?.state==='reviews_stopped')&&p.sampleMode){collectionMode=p.sampleMode;sampleButtons.forEach(x=>x.classList.toggle('active',x.dataset.sample===collectionMode));customSampleWrap.style.display=collectionMode==='custom'?'block':'none'}}catch(e){}})();
runBtn.onclick=async()=>{
 if(!backendCompatible){status.textContent='插件与本地后端版本不一致，请先双击本包“start-tmall-ai.command”';return}
 const t=await active();let sample=collectionMode;if(sample==='custom'){const n=Number(customSample?.value||0);if(!Number.isInteger(n)||n<1||n>10000){status.textContent='请输入 1-10000 的评论数量';return}sample=String(n)}status.textContent=`开始采集当前商品（评论样本 ${sample==='all'?'全部':sample+' 条'}）…`;try{const r=await chrome.runtime.sendMessage({type:'RUN_CURRENT',tabId:t.id,sampleMode:sample});if(r?.needsReviewResume){status.textContent=r.message||'评论采集已暂停，可继续';runBtn.textContent='继续采集评论'}else if(!r?.ok){status.textContent='采集失败：'+(r?.error||'未知错误')}}catch(e){status.textContent='采集失败：'+String(e)}setTimeout(refresh,500)};
document.getElementById('install').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('install.html')});
document.getElementById('open').onclick=()=>chrome.tabs.create({url:SERVER+'/'});
document.getElementById('openWorkflow').onclick=()=>chrome.tabs.create({url:SERVER+'/#image-workflow'});
document.getElementById('openPrompts').onclick=()=>chrome.tabs.create({url:SERVER+'/prompts'});
document.getElementById('importMonitor')?.addEventListener('click',()=>document.getElementById('monitorFile')?.click());
document.getElementById('monitorFile')?.addEventListener('change',async e=>{
 const f=e.target.files?.[0];if(!f)return;
 if(!backendCompatible){monitorStatus.textContent='导入失败：插件与后端版本不一致，请启动本包最新服务';e.target.value='';return}
 const t=await active();const itemId=itemIdFromUrl(t?.url||'');
 if(!itemId){monitorStatus.textContent='请先打开目标商品页';e.target.value='';return}
 monitorStatus.textContent='正在解析并导入…';
 try{
   const buf=await f.arrayBuffer();
   let binary='';const bytes=new Uint8Array(buf);
   for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
   const base64=btoa(binary);
   const send=async(forceBind=false)=>{
     const r=await fetch(SERVER+'/api/monitor-import',{
       method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({itemId,filename:f.name,dataBase64:base64,forceBind})
     });
     const j=await r.json().catch(()=>({ok:false,error:'服务返回内容无法解析'}));
     return {r,j};
   };
   let {r,j}=await send(false);
   if(!j.ok && j.code==='ITEM_ID_MISMATCH' && j.canForce){
     const fileId=(j.fileItemIds||[])[0]||'未知';
     const yes=confirm(`监测文件中的商品ID为 ${fileId}，当前页面商品ID为 ${itemId}。

如果这份文件确实属于当前商品，点击“确定”后按当前商品绑定；否则点击“取消”。`);
     if(yes)({r,j}=await send(true));
   }
   if(j.ok){
     monitorStatus.textContent=`已导入 ${j.days} 天 · ${j.firstSales||'—'} → ${j.lastSales||'—'}`;
   }else{
     const extra=j.fileItemIds?.length?`（文件商品ID：${j.fileItemIds.slice(0,5).join(', ')}）`:'';
     monitorStatus.textContent=`导入失败：${j.error||'未知错误'}${extra}`;
   }
 }catch(err){
   monitorStatus.textContent='导入失败：'+String(err);
 }
 e.target.value='';
});
document.getElementById('clearMonitor')?.addEventListener('click',async()=>{});
refresh();setInterval(refresh,1300);

stopBtn.onclick=async()=>{const t=await active();stopBtn.disabled=true;stopBtn.textContent='正在终止…';try{const r=await chrome.runtime.sendMessage({type:'STOP_COLLECTION',tabId:t?.id});status.textContent=r?.ok?'已发送终止指令，正在保存当前进度…':'终止失败，请重试'}catch(e){status.textContent='终止失败：'+String(e)}setTimeout(()=>{stopBtn.disabled=false;stopBtn.textContent='终止采集并保存进度'},1000)};

const analyzeNow=document.getElementById('analyzeNow');
const modeQuick=document.getElementById('modeQuick');
const modeStandard=document.getElementById('modeStandard');
const modeFull=document.getElementById('modeFull');
let analysisMode='standard';

function setMode(mode){
  analysisMode=mode;
  modeQuick?.classList.toggle('active',mode==='quick');
  modeStandard?.classList.toggle('active',mode==='standard');
  modeFull?.classList.toggle('active',mode==='full');
  if(analyzeNow){
    analyzeNow.textContent='基于当前数据开始分析';
    analyzeNow.disabled=false;
  }
}
modeQuick && (modeQuick.onclick=()=>setMode('quick'));
modeStandard && (modeStandard.onclick=()=>setMode('standard'));
modeFull && (modeFull.onclick=()=>setMode('full'));
setMode('standard');

analyzeNow && (analyzeNow.onclick=async()=>{
  if(!backendCompatible){
    status.textContent='插件与本地后端版本不一致，请先启动本包最新服务';
    return;
  }
  const t=await active();
  if(!t?.id){status.textContent='请先打开目标商品页';return}
  analyzeNow.disabled=true;
  analyzeNow.textContent='正在提交当前数据…';
  try{
    const r=await chrome.runtime.sendMessage({type:'ANALYZE_CURRENT_NOW',tabId:t.id});
    if(r?.ok){
      status.textContent=`已开始分析当前数据${r.reviewCount!=null?` · 当前评论 ${r.reviewCount} 条`:''}`;
      if(r.taskUrl) chrome.tabs.create({url:/^https?:\/\//i.test(r.taskUrl)?r.taskUrl:SERVER+r.taskUrl});
    }else{
      status.textContent='无法开始分析：'+(r?.error||'未知错误');
    }
  }catch(e){
    status.textContent='无法开始分析：'+String(e);
  }finally{
    analyzeNow.disabled=false;
    analyzeNow.textContent='基于当前数据开始分析';
  }
});
