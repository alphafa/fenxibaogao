const API_BASE='http://127.0.0.1:3300/api/collector/product-page'

async function capture(tabId){
  const result=await chrome.scripting.executeScript({target:{tabId},func:()=>{
    const clean=value=>String(value||'').replace(/\s+/g,' ').trim()
    const uniq=rows=>[...new Set(rows.filter(Boolean))]
    const bodyText=document.body?.innerText||''
    const lines=bodyText.split(/\n+/).map(clean).filter(Boolean)
    const url=location.href
    const itemId=url.match(/[?&]id=(\d+)/)?.[1]||url.match(/\/(\d+)\.html/)?.[1]||''
    const skuId=url.match(/[?&]skuId=(\d+)/)?.[1]||''
    const platform=/tmall/i.test(location.hostname)?'tmall':/taobao/i.test(location.hostname)?'taobao':/jd\.com/i.test(location.hostname)?'jd':'unknown'
    const title=clean(document.querySelector('h1')?.textContent||document.querySelector('meta[property="og:title"]')?.content||document.title)
    const readAfter=patterns=>{const row=lines.find(line=>patterns.some(pattern=>pattern.test(line)));if(!row)return'';const parts=row.split(/[：:]/);return clean(parts.length>1?parts.slice(1).join(':'):row)}
    const shop=clean(document.querySelector('[class*="shop-name"],[class*="shopName"],[class*="seller-name"],[class*="sellerName"]')?.textContent)||readAfter([/^店铺/,/^店名/,/^卖家/])
    const priceText=clean(document.querySelector('[class*="promotionPrice"],[class*="salePrice"],[class*="price"]')?.textContent||'')
    const currentPrice=clean(priceText.match(/[¥￥]?\s*(\d+(?:\.\d+)?)/)?.[1]||bodyText.match(/(?:券后|到手价|活动价|价格)\s*[¥￥]?\s*(\d+(?:\.\d+)?)/)?.[1]||'')
    const originalPrice=clean(bodyText.match(/(?:原价|划线价|优惠前)\s*[¥￥]?\s*(\d+(?:\.\d+)?)/)?.[1]||'')
    const sold=clean(bodyText.match(/(?:已售|付款|销量|累计销量)\s*([0-9.万wW+]+)/)?.[1]||'')
    const publicReviewCount=clean(bodyText.match(/(?:累计评价|全部评价|商品评价|评论)\s*([0-9.万wW+]+)/)?.[1]||'')
    const ranking=clean(bodyText.match(/(?:热销榜|排行榜|榜第)\s*第?\s*([0-9]+)\s*名/)?.[0]||'')

    const meta={}
    document.querySelectorAll('meta').forEach(el=>{const key=el.getAttribute('property')||el.getAttribute('name');const value=el.getAttribute('content');if(key&&value&&!/cookie|authorization|token|password/i.test(key))meta[key]=value})
    const jsonld=[]
    document.querySelectorAll('script[type="application/ld+json"]').forEach(el=>{try{jsonld.push(JSON.parse(el.textContent||'null'))}catch{}})

    const badImage=/avatar|icon|logo|sprite|loading|placeholder|qrcode|qr-code|emoji|badge/i
    const imageRows=[...document.images].map(img=>({
      url:img.currentSrc||img.src,
      width:img.naturalWidth||img.width||0,
      height:img.naturalHeight||img.height||0,
      alt:clean(img.alt),
      context:clean(`${img.alt||''} ${img.closest('[class],[id]')?.className||''} ${img.closest('[class],[id]')?.id||''}`)
    })).filter(row=>/^https?:\/\//.test(row.url)&&!badImage.test(`${row.url} ${row.context}`)&&(row.width>=120||row.height>=120))
    const uniqueImages=rows=>{const seen=new Set();return rows.filter(row=>{const key=row.url.replace(/_[0-9]+x[0-9]+[^/]*$/,'');if(seen.has(key))return false;seen.add(key);return true})}
    const reviewRows=uniqueImages(imageRows.filter(row=>/review|comment|rate|evaluate|buyer|show|评价|评论|买家秀|晒单/i.test(row.context)))
    const detailRows=uniqueImages(imageRows.filter(row=>/detail|description|desc|richtext|module|详情|图文|描述/i.test(row.context)&&!reviewRows.some(x=>x.url===row.url)))
    const skuRows=uniqueImages(imageRows.filter(row=>/sku|prop|variant|option|规格|颜色|尺码|型号|口味/i.test(row.context)&&!reviewRows.some(x=>x.url===row.url)&&!detailRows.some(x=>x.url===row.url)))
    const mainRows=uniqueImages(imageRows.filter(row=>/gallery|thumb|preview|main|swiper|carousel|主图|轮播/i.test(row.context)&&!reviewRows.some(x=>x.url===row.url)&&!detailRows.some(x=>x.url===row.url))).slice(0,30)
    const allImages=uniqueImages(imageRows)

    const blockedAttribute=/优惠|券|立减|包邮|发货|送达|价保|退货|客服|店铺|销量|付款|评论|评价|问答/
    const attributes=[]
    const attributeSeen=new Set()
    const addAttribute=(name,value,source='dom')=>{name=clean(name).replace(/[：:]$/,'');value=clean(value);if(!name||!value||name.length>36||value.length>600||blockedAttribute.test(name))return;const key=`${name}\u0000${value}`;if(attributeSeen.has(key))return;attributeSeen.add(key);attributes.push({name,value,source})}
    document.querySelectorAll('table tr,[class*="attribute"] li,[class*="Attribute"] li,[class*="parameter"] li,[class*="Parameter"] li,[class*="property"] li,[class*="Property"] li,[class*="attr"] li').forEach(el=>{
      const cells=[...el.querySelectorAll(':scope > th,:scope > td,:scope > span,:scope > div')].map(x=>clean(x.textContent)).filter(Boolean)
      if(cells.length>=2)addAttribute(cells[0],cells.slice(1).join(' '),'attribute_dom')
      else{const text=clean(el.textContent);const match=text.match(/^([^：:]{1,36})[：:]\s*(.{1,600})$/);if(match)addAttribute(match[1],match[2],'attribute_dom')}
    })
    lines.forEach(line=>{const match=line.match(/^([^：:]{1,30})[：:]\s*(.{1,400})$/);if(match)addAttribute(match[1],match[2],'page_text')})

    const breadcrumb=uniq([...document.querySelectorAll('[class*="breadcrumb"] a,[class*="crumb"] a,[class*="category"] a')].map(el=>clean(el.textContent))).filter(x=>x.length<=40).slice(0,12)
    const categoryCandidates=uniq([...breadcrumb,...attributes.filter(x=>/类目|分类|品类|产品类型|商品类型/.test(x.name)).map(x=>x.value)]).slice(0,20)

    const variants=[]
    const variantSeen=new Set()
    const addVariant=row=>{const name=clean(row.name);if(!name||name.length>180)return;const key=`${clean(row.group)}\u0000${name}`;if(variantSeen.has(key))return;variantSeen.add(key);variants.push({...row,name,group:clean(row.group),source:row.source||'sku_dom'})}
    document.querySelectorAll('[class*="sku"],[class*="Sku"],[class*="variant"],[class*="Variant"],[class*="prop"] ,[class*="Prop"]').forEach(container=>{
      const group=clean(container.querySelector('[class*="title"],[class*="label"],[class*="name"]')?.textContent||'')
      container.querySelectorAll('button,[role="option"],li,[class*="item"],[class*="Item"]').forEach(el=>{
        const name=clean(el.getAttribute('title')||el.getAttribute('aria-label')||el.textContent)
        const image=el.querySelector('img')?.currentSrc||el.querySelector('img')?.src||''
        addVariant({group,name,image,selected:el.getAttribute('aria-selected')==='true'||/selected|active|current/i.test(el.className),disabled:el.getAttribute('aria-disabled')==='true'||el.hasAttribute('disabled')})
      })
    })
    const variantKeywords=/(颜色|色号|尺码|尺寸|规格|型号|版本|配置|容量|净含量|口味|香型|套装|套餐|款式|适用|包装|重量|数量|码数|度数|功率|内存|存储)/
    lines.filter(line=>variantKeywords.test(line)&&line.length<=500).slice(0,180).forEach(line=>line.split(/[,，]/).map(clean).filter(Boolean).forEach(name=>addVariant({group:'',name,source:'page_text'})))

    const promotionPattern=/(优惠|券|立减|满减|包邮|免运费|价保|退货|退款|七天无理由|预计.*发货|送达|大促|活动|限时|到手价|店铺优惠|赠品|买一送一)/i
    const promotions=uniq(lines.filter(line=>promotionPattern.test(line)&&line.length<=120)).slice(0,100).map(text=>({text,source:'page_text'}))

    const questions=[]
    document.querySelectorAll('[class*="question"],[class*="Question"],[class*="ask"],[class*="Ask"]').forEach((el,index)=>{
      const text=clean(el.innerText);if(!text)return
      const question=clean(el.querySelector('[class*="question"],[class*="title"]')?.textContent||text.match(/(.{2,160}[？?])/)?.[1])
      const answer=clean(el.querySelector('[class*="answer"]')?.textContent||'')
      if(question)questions.push({id:`question-${index+1}`,question,answer,source:'question_dom'})
    })

    const reviewSelectors=['[class*="review-item"]','[class*="comment-item"]','[class*="rate-item"]','[class*="ReviewItem"]','[class*="CommentItem"]','[data-testid*="review"]']
    const reviews=[...document.querySelectorAll(reviewSelectors.join(','))].slice(0,500).map((el,index)=>{
      const content=clean(el.innerText);if(content.length<6||content.length>3000)return null
      const images=uniq([...el.querySelectorAll('img')].map(img=>img.currentSrc||img.src).filter(src=>/^https?:\/\//.test(src)&&!badImage.test(src)))
      const date=content.match(/20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?(?:\s+\d{1,2}:\d{2})?/)?.[0]||''
      const appendContent=clean(content.match(/(?:追评|追加评价)[：:\s]*(.{2,800})/)?.[1]||'')
      const sku=clean(el.querySelector('[class*="sku"],[class*="spec"],[class*="attr"]')?.textContent||'')
      const merchantReply=clean(el.querySelector('[class*="reply"],[class*="seller"]')?.textContent||'')
      const rating=Number(el.getAttribute('data-score')||el.getAttribute('data-rating')||el.querySelector('[data-score]')?.getAttribute('data-score'))||null
      return{id:el.getAttribute('data-id')||el.id||`review-${index+1}`,content,appendContent,date,rating,sku,hasImage:images.length>0,images,merchantReply,source:'review_dom'}
    }).filter(Boolean)

    const collection={
      publicReviewCount,
      reviewActual:reviews.length,
      questionActual:questions.length,
      reviewCompleteness:reviews.length?'visible_content_collected':'no_visible_review_nodes',
      reviewStopReason:reviews.length?'visible_dom_exhausted':'reviews_not_open_or_platform_folded',
      capturedAt:new Date().toISOString(),
      collectorVersion:chrome.runtime.getManifest().version,
      platform
    }
    const structured={
      meta:{...collection,url},
      category:{candidates:categoryCandidates,breadcrumb},
      product:{itemId,skuId,title,shop,brand:attributes.find(item=>/^品牌$/.test(item.name))?.value||'',url,platform},
      sales:{currentPrice,originalPrice,sold,ranking},
      promotions,attributes,sku:variants,questions,reviews,
      images:{all:allImages,main:mainRows,detail:detailRows.slice(0,120),sku:skuRows.slice(0,120),buyerShow:reviewRows.slice(0,160)},
      collection,pageText:bodyText
    }
    return{structured,...structured,jsonld,meta}
  }})
  return result?.[0]?.result
}

const lastCaptured=new Map()
function isProductUrl(url=''){return /^https:\/\/(?:item\.jd\.com\/\d+\.html|item\.taobao\.com\/item\.htm|detail\.tmall\.com\/item\.htm)/i.test(url)}

async function reportAuthState(){
  try{
    const [taobaoCookies,jdCookies]=await Promise.all([chrome.cookies.getAll({domain:'.taobao.com'}),chrome.cookies.getAll({domain:'.jd.com'})])
    const response=await fetch(`${API_BASE}/auth-heartbeat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:chrome.runtime.getManifest().version,platforms:{taobao:{loggedIn:taobaoCookies.some(cookie=>/tracknick|cookie2|_tb_token_|sgcookie/i.test(cookie.name))},jd:{loggedIn:jdCookies.some(cookie=>/pin|thor|unick/i.test(cookie.name))}}})})
    return response.ok
  }catch(error){console.error('[三笙登录态上报]',error);return false}
}

async function captureAndSend(tab,{force=false}={}){
  if(!tab?.id||!isProductUrl(tab.url))return
  const key=`${tab.id}:${tab.url}`
  if(!force&&Date.now()-(lastCaptured.get(key)||0)<30_000)return
  lastCaptured.set(key,Date.now())
  try{
    await chrome.action.setBadgeText({tabId:tab.id,text:'采'})
    await chrome.action.setBadgeBackgroundColor({tabId:tab.id,color:'#2563EB'})
    const payload=await capture(tab.id)
    const response=await fetch(`${API_BASE}/capture`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    if(!response.ok)throw new Error(await response.text())
    await chrome.action.setBadgeText({tabId:tab.id,text:'OK'})
    await chrome.action.setBadgeBackgroundColor({tabId:tab.id,color:'#155C4E'})
    setTimeout(()=>chrome.action.setBadgeText({tabId:tab.id,text:''}),2500)
  }catch(error){
    lastCaptured.delete(key)
    await chrome.action.setBadgeText({tabId:tab.id,text:'!'})
    await chrome.action.setBadgeBackgroundColor({tabId:tab.id,color:'#A54F43'})
    console.error('[三笙商品采集]',error)
  }
}

chrome.tabs.onUpdated.addListener((tabId,changeInfo,tab)=>{if(changeInfo.status==='complete'&&isProductUrl(tab.url))setTimeout(()=>captureAndSend({...tab,id:tabId}),2500)})
chrome.tabs.onRemoved.addListener(tabId=>{for(const key of lastCaptured.keys())if(key.startsWith(`${tabId}:`))lastCaptured.delete(key)})
chrome.action.onClicked.addListener(tab=>captureAndSend(tab,{force:true}))

let queueBusy=false
let queueBackoffMs=1000
async function processCaptureQueue(){
  if(queueBusy)return
  queueBusy=true
  let tab
  try{
    const response=await fetch(`${API_BASE}/next`)
    if(response.status===204){queueBackoffMs=Math.min(queueBackoffMs*1.5,15_000);return}
    if(!response.ok)throw new Error(`任务队列 HTTP ${response.status}`)
    const task=await response.json()
    tab=await chrome.tabs.create({url:task.url,active:false})
    await new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>{chrome.tabs.onUpdated.removeListener(listener);reject(new Error('商品页加载超时'))},45_000)
      const listener=(tabId,changeInfo,updated)=>{if(tabId===tab.id&&changeInfo.status==='complete'){clearTimeout(timeout);chrome.tabs.onUpdated.removeListener(listener);resolve(updated)}}
      chrome.tabs.onUpdated.addListener(listener)
    })
    await new Promise(resolve=>setTimeout(resolve,3500))
    await captureAndSend(await chrome.tabs.get(tab.id),{force:true})
    queueBackoffMs=1000
  }catch(error){console.error('[三笙采集队列]',error);queueBackoffMs=Math.min(queueBackoffMs*2,30_000)}
  finally{if(tab?.id)await chrome.tabs.remove(tab.id).catch(()=>{});queueBusy=false;setTimeout(processCaptureQueue,queueBackoffMs)}
}

chrome.runtime.onInstalled.addListener(()=>{chrome.alarms.create('sansong-product-queue',{periodInMinutes:.5});processCaptureQueue()})
chrome.runtime.onStartup.addListener(()=>{chrome.alarms.create('sansong-product-queue',{periodInMinutes:.5});processCaptureQueue()})
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='sansong-product-queue')processCaptureQueue();if(alarm.name==='sansong-auth-heartbeat')reportAuthState()})
chrome.alarms.create('sansong-product-queue',{periodInMinutes:.5})
chrome.alarms.create('sansong-auth-heartbeat',{periodInMinutes:1})
processCaptureQueue()
reportAuthState()
chrome.runtime.onMessage.addListener((message,_sender,sendResponse)=>{if(message?.type!=='SANSONG_COLLECTOR_WAKE')return;reportAuthState().then(connected=>sendResponse({connected})).catch(()=>sendResponse({connected:false}));return true})
chrome.cookies.onChanged.addListener(change=>{if(/(?:^|\.)(?:taobao|tmall|jd)\.com$/i.test(change.cookie.domain))setTimeout(reportAuthState,300)})
