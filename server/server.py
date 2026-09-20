import json, os, threading, time, uuid, traceback, html, base64, csv, io, zipfile, re, mimetypes, hashlib, urllib.request, urllib.error, subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, as_completed
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote_to_bytes, parse_qs
from pathlib import Path
from analysis import (
    analyze, normalize, MAIN_VISUAL_TASKS, DETAIL_VISUAL_TASKS,
    VISUAL_EXCLUDED_TERMS, _visual_product_text
)
from renderer import render
from ai_client import (
    configured, load_config, probe_model_api, probe_image_api, image_generate,
    image_model_options, normalize_image_quality, IMAGE_QUALITY_OPTIONS,
    _ssl_context, chat_json,
)
from prompt_templates import (
    TEMPLATES, PRODUCT_VARIABLES, build_image_generation_prompt,
    build_reference_shooting_guidance, build_display_relationship_guidance,
)

ROOT=Path(__file__).resolve().parent
PROMPT_CONFIG=ROOT/'prompts.json'
REPORTS=ROOT/'reports'; REPORTS.mkdir(exist_ok=True)
MONITOR_DIR=ROOT/'monitor_data'; MONITOR_DIR.mkdir(exist_ok=True)
PORT=int(os.getenv('TMALL_AI_PORT','17962'))
SERVER_VERSION='9.3.0'
REFERENCE_ROLE_VERSION='20260911-reference-role-fix4'
MODEL_PROBE={'ok':False,'stage':'startup','error':'尚未检测'}
MODEL_PROBE_AT=0
TASKS={}
LOCK=threading.Lock()


IMAGE_ASSET_ROOT=REPORTS/'assets'; IMAGE_ASSET_ROOT.mkdir(exist_ok=True)
GENERATED_ASSET_ROOT=IMAGE_ASSET_ROOT/'generated'; GENERATED_ASSET_ROOT.mkdir(exist_ok=True)
IMAGE_JOBS={}
IMAGE_INTENT_CACHE={}
IMAGE_INTENT_LOCK=threading.Lock()

def _image_model_specs(request=None):
    """Resolve selected comparison models, falling back to the configured default."""
    config_options=image_model_options(load_config())
    requested=(request or {}).get('imageModels') if isinstance(request,dict) else None
    requested_specs=[]
    if isinstance(requested,list):
        for item in requested:
            if isinstance(item,dict):
                value=item.get('id') or item.get('model')
                quality=item.get('quality')
            else:
                value=item
                quality=None
            value=str(value or '').strip()
            if value and not any(spec['id']==value for spec in requested_specs):
                requested_specs.append({'id':value,'quality':quality})
    allowed={item['id']:item for item in config_options}
    selected=[]
    for requested_spec in requested_specs:
        configured=allowed.get(requested_spec['id'])
        if not configured:
            continue
        spec=dict(configured)
        if requested_spec.get('quality') is not None:
            spec['quality']=normalize_image_quality(requested_spec.get('quality'))
        selected.append(spec)
    if not selected:
        selected=[dict(item) for item in config_options[:1]]
    if not selected:
        selected=[{'id':'','label':'默认生图模型','quality':''}]
    return selected

def _image_model_key(model_id):
    return 'model_'+hashlib.sha256(str(model_id).encode('utf-8')).hexdigest()[:10]

def _result_identity(item):
    item=item if isinstance(item,dict) else {}
    return (
        str(item.get('modelKey') or 'default'),
        str(item.get('assetType') or ''),
        int(item.get('slotIndex') or 0),
    )

def _asset_ext(url, content_type=''):
    c=(content_type or '').split(';',1)[0].strip().lower()
    mapping={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/gif':'.gif','image/avif':'.avif'}
    if c in mapping:return mapping[c]
    path=urlparse(str(url or '')).path.lower()
    for ext in ('.webp','.jpg','.jpeg','.png','.gif','.avif'):
        if ext in path:return '.jpg' if ext=='.jpeg' else ext
    return '.img'

def _normalize_asset_url(url):
    url=str(url or '').strip().replace('&amp;','&')
    if url.startswith('//'):url='https:'+url
    return url

def _looks_like_image(data, content_type=''):
    if not data:return False
    c=(content_type or '').split(';',1)[0].strip().lower()
    if c.startswith('image/'):return True
    sig=data[:16]
    return (sig.startswith(b'\xff\xd8\xff') or sig.startswith(b'\x89PNG\r\n\x1a\n') or sig[:6] in (b'GIF87a',b'GIF89a') or (len(sig)>=12 and sig[:4]==b'RIFF' and sig[8:12]==b'WEBP') or b'ftypavif' in data[:32])

def _download_image(url, timeout=18):
    """Download a commerce image with several anti-hotlink compatible header strategies."""
    url=_normalize_asset_url(url)
    strategies=[
      {'Referer':'https://detail.tmall.com/','Origin':'https://detail.tmall.com'},
      {'Referer':'https://item.taobao.com/','Origin':'https://item.taobao.com'},
      {'Referer':'https://www.taobao.com/'},
      {},
    ]
    last=None
    for extra in strategies:
        try:
            headers={
              'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36',
              'Accept':'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
              'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8',
              'Cache-Control':'no-cache',
            }
            headers.update(extra)
            req=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(req,timeout=timeout,context=_ssl_context(load_config())) as r:
                data=r.read(16*1024*1024+1)
                if len(data)>16*1024*1024:raise ValueError('image too large')
                ctype=r.headers.get('Content-Type','')
            if not _looks_like_image(data,ctype):raise ValueError('not image response')
            return data,ctype
        except Exception as ex:last=ex
    # macOS Python installations may not trust the same system roots as curl.
    # Keep certificate verification enabled and use curl's trusted system store
    # only after urllib's verified attempts have failed.
    if isinstance(last, urllib.error.URLError) and 'CERTIFICATE_VERIFY_FAILED' in str(last):
        try:
            response=subprocess.run(
                ['curl','--fail','--location','--silent','--show-error','--max-time',str(timeout),
                 '--max-filesize',str(16*1024*1024),'--user-agent',
                 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36',
                 '--referer','https://detail.tmall.com/',url],
                capture_output=True,timeout=timeout+3,check=False,
            )
            if response.returncode==0 and len(response.stdout)<=16*1024*1024 and _looks_like_image(response.stdout):
                return response.stdout,''
        except (OSError,subprocess.TimeoutExpired):
            pass
    raise last or RuntimeError('image download failed')

def cache_report_images(result, task_id):
    """Persist report images under /reports/assets. Keep the source URL as a browser fallback."""
    root=IMAGE_ASSET_ROOT/task_id; root.mkdir(parents=True,exist_ok=True)
    ok=failed=skipped=0
    for e in result.get('evidenceLedger') or []:
        if not isinstance(e,dict) or e.get('type')!='image':continue
        url=_normalize_asset_url(e.get('value'))
        meta=e.setdefault('meta',{})
        if not url:
            skipped+=1;continue
        # Keep source URL even when caching fails so the renderer can still try the browser.
        meta['sourceUrl']=url
        group=re.sub(r'[^a-zA-Z0-9_-]+','_',str(meta.get('group') or 'other'))
        eid=re.sub(r'[^a-zA-Z0-9_-]+','_',str(e.get('id') or hashlib.sha1(url.encode()).hexdigest()[:12]))
        group_dir=root/group; group_dir.mkdir(parents=True,exist_ok=True)
        try:
            if url.startswith('data:image/'):
                head,payload=url.split(',',1)
                data=base64.b64decode(payload) if ';base64' in head else unquote_to_bytes(payload)
                ctype=head[5:].split(';',1)[0]
            elif url.startswith(('http://','https://')):
                data,ctype=_download_image(url)
            else:
                raise ValueError('unsupported image url')
            ext=_asset_ext(url,ctype); target=group_dir/(eid+ext); target.write_bytes(data)
            # Browser URL is absolute-from-server-root and therefore works from every report route.
            meta['localUrl']=f'/reports/assets/{task_id}/{group}/{target.name}'
            meta['cacheStatus']='success'; meta.pop('cacheError',None); ok+=1
        except Exception as ex:
            meta.pop('localUrl',None); meta['cacheStatus']='failed'; meta['cacheError']=str(ex)[:220]; failed+=1
    result.setdefault('meta',{})['imageCache']={'success':ok,'failed':failed,'skipped':skipped,'mode':'local-first-multi-retry-remote-fallback'}
    return result

def build_offline_report(report_id):
    """Return a standalone HTML report with every evidence image embedded."""
    if not re.fullmatch(r'[A-Za-z0-9_-]+',report_id):
        raise ValueError('报告编号无效')
    report_path=REPORTS/f'{report_id}.json'
    if not report_path.is_file():
        raise FileNotFoundError('报告文件不存在')
    data=json.loads(report_path.read_text('utf-8'))
    entries=[e for e in data.get('evidenceLedger') or [] if isinstance(e,dict) and e.get('type')=='image']
    embedded={}; local_urls={}; cache_updates={}; failures=[]
    for entry in entries:
        meta=entry.setdefault('meta',{})
        source=_normalize_asset_url(meta.get('sourceUrl') or entry.get('value'))
        if not source:
            failures.append(str(entry.get('id') or '未知图片'))
            continue
        if source not in embedded:
            local=str(meta.get('localUrl') or '')
            candidate=(REPORTS/local.removeprefix('/reports/')).resolve() if local.startswith('/reports/assets/') else None
            if candidate and REPORTS.resolve() in candidate.parents and candidate.is_file():
                image_bytes=candidate.read_bytes()
                local_url=local
            else:
                try:
                    if source.startswith('data:image/'):
                        header,payload=source.split(',',1)
                        image_bytes=base64.b64decode(payload) if ';base64' in header else unquote_to_bytes(payload)
                    elif source.startswith(('https://','http://')):
                        image_bytes,_=_download_image(source)
                    else:
                        raise ValueError('不支持的图片地址')
                except Exception:
                    failures.append(str(entry.get('id') or '未知图片'))
                    continue
                if _looks_like_image(image_bytes):
                    group=re.sub(r'[^a-zA-Z0-9_-]+','_',str(meta.get('group') or 'other'))
                    eid=re.sub(r'[^a-zA-Z0-9_-]+','_',str(entry.get('id') or hashlib.sha1(source.encode()).hexdigest()[:12]))
                    target=IMAGE_ASSET_ROOT/report_id/group/(eid+_asset_ext(source))
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(image_bytes)
                    local_url=f'/reports/assets/{report_id}/{group}/{target.name}'
            if not _looks_like_image(image_bytes):
                failures.append(str(entry.get('id') or '未知图片'))
                continue
            mime=mimetypes.guess_type(source.split('?',1)[0])[0]
            if not mime or not mime.startswith('image/'):
                mime=mimetypes.guess_type(str(candidate or ''))[0] or 'image/jpeg'
            embedded[source]=f'data:{mime};base64,{base64.b64encode(image_bytes).decode("ascii")}'
            local_urls[source]=local_url
        if meta.get('localUrl')!=local_urls[source] or meta.get('cacheStatus')!='success':
            cache_updates[entry.get('id')]=local_urls[source]
        meta['localUrl']=embedded[source]
    if failures:
        raise ValueError(f'有 {len(failures)} 张报告图片未能下载，暂不提供缺图文件。请检查网络或图片源后重试。')
    if cache_updates:
        # Persist the restored local cache paths, not the larger inline data URIs.
        cached=json.loads(report_path.read_text('utf-8'))
        for old in cached.get('evidenceLedger') or []:
            if not isinstance(old,dict) or old.get('id') not in cache_updates: continue
            old.setdefault('meta',{})['localUrl']=cache_updates[old['id']]
            old['meta']['cacheStatus']='success'
            old['meta'].pop('cacheError',None)
        statuses=[e.get('meta',{}).get('cacheStatus') for e in cached.get('evidenceLedger') or [] if isinstance(e,dict) and e.get('type')=='image']
        cached.setdefault('meta',{})['imageCache']={'success':statuses.count('success'),'failed':statuses.count('failed'),'skipped':len(statuses)-statuses.count('success')-statuses.count('failed'),'mode':'local-first-multi-retry-remote-fallback'}
        temp_path=report_path.with_name(report_path.name+'.'+uuid.uuid4().hex+'.tmp')
        temp_path.write_text(json.dumps(cached,ensure_ascii=False,indent=2),'utf-8')
        os.replace(temp_path,report_path)
    document=(ROOT/'report.html').read_text('utf-8')
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('</','<\\/').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    css=(ROOT/'report.css').read_text('utf-8').replace('</style','<\\/style')
    js=(ROOT/'report.js').read_text('utf-8').replace('</script','<\\/script')
    document=re.sub(r'<link rel="stylesheet" href="/report\.css[^\"]*">',lambda _:f'<style>{css}</style>',document,count=1)
    document=re.sub(r'<script src="/report\.js[^\"]*"></script>',lambda _:f'<script>window.REPORT_DATA={payload};window.OFFLINE_REPORT=true;\n{js}</script>',document,count=1)
    return document.encode('utf-8')

def _generated_ext(content_type='', url=''):
    return _asset_ext(url, content_type) if content_type or url else '.png'

def _save_generated_item(item, root, index):
    """Persist one provider image response and return a browser URL."""
    if not isinstance(item,dict): raise ValueError('图片接口返回了无效条目')
    raw=item.get('b64_json') or item.get('base64')
    image_obj=item.get('image_url')
    url=item.get('url') or (image_obj.get('url') if isinstance(image_obj,dict) else image_obj if isinstance(image_obj,str) else '')
    ctype='image/png'
    if raw:
        data=base64.b64decode(raw)
    elif isinstance(url,str) and url.startswith('data:image/'):
        head,payload=url.split(',',1); ctype=head[5:].split(';',1)[0]; data=base64.b64decode(payload) if ';base64' in head else unquote_to_bytes(payload)
    elif isinstance(url,str) and url.startswith(('http://','https://')):
        data,ctype=_download_image(url)
    else:
        raise ValueError('图片接口未返回 url 或 b64_json')
    if not _looks_like_image(data,ctype): raise ValueError('图片接口返回内容不是有效图片')
    ext=_generated_ext(ctype,str(url or '')); target=root/f'{index:02d}{ext}'; target.write_bytes(data)
    return {'url':f'/reports/assets/generated/{root.name}/{target.name}','sourceUrl':url if isinstance(url,str) and url.startswith(('http://','https://')) else '', 'width':None,'height':None,'_path':str(target)}

def _result_task_key(item):
    item=item if isinstance(item,dict) else {}
    return str(item.get('taskKey') or f"{item.get('assetType') or 'main'}:{item.get('slotIndex') or 0}")

def _result_revision_number(item, default=1):
    try:
        return max(1,int((item or {}).get('revisionNumber') or default))
    except Exception:
        return default

def _next_result_revision_number(parent_job, parent_result):
    """Allocate the next visible version across successful sibling branches."""
    parent_job=parent_job if isinstance(parent_job,dict) else {}
    parent_result=parent_result if isinstance(parent_result,dict) else {}
    task_key=_result_task_key(parent_result)
    root_result_id=str(parent_result.get('rootResultId') or '').strip()
    round_id=str(parent_job.get('generationRoundId') or parent_job.get('roundId') or parent_job.get('jobId') or '').strip()
    model_key=str(parent_result.get('modelKey') or parent_result.get('model') or 'default')
    jobs={key:dict(value) for key,value in IMAGE_JOBS.items() if isinstance(value,dict)}
    for saved in REPORTS.glob('generated_*.json'):
        try:
            job=json.loads(saved.read_text('utf-8'))
            if isinstance(job,dict) and job.get('jobId'): jobs[job['jobId']]=job
        except Exception:
            continue
    siblings=[]
    for job in jobs.values():
        job_round=str(job.get('generationRoundId') or job.get('roundId') or job.get('jobId') or '').strip()
        if round_id and job_round!=round_id: continue
        for item in job.get('results') or []:
            if not isinstance(item,dict) or _result_task_key(item)!=task_key: continue
            item_model=str(item.get('modelKey') or item.get('model') or 'default')
            if item_model!=model_key: continue
            item_root=str(item.get('rootResultId') or '').strip()
            if root_result_id and item_root and item_root!=root_result_id: continue
            siblings.append(item)
    unique={str(item.get('resultId') or item.get('url') or id(item)) for item in siblings}
    return max(_result_revision_number(parent_result)+1,len(unique)+1)

def _generated_item_data_url(item):
    path=Path(str((item or {}).get('_path') or ''))
    if not path.exists(): return ''
    ctype=mimetypes.guess_type(str(path))[0] or 'image/png'
    return 'data:'+ctype+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')

def _generated_result_sort_key(item):
    item=item if isinstance(item,dict) else {}
    asset_type=str(item.get('assetType') or '')
    try:index=int(item.get('slotIndex') or 0)
    except Exception:index=0
    return (
        0 if asset_type=='main' else 1,
        index,
        str(item.get('modelLabel') or item.get('model') or ''),
        str(item.get('url') or ''),
    )

def _ordered_generated_results(items):
    return sorted(
        [item for item in (items or []) if isinstance(item,dict)],
        key=_generated_result_sort_key,
    )

def _text_list(value, limit=5):
    keys=('signal','statement','style','asset','headline','value','topic','name','label','action','consumerValue')
    def one(x):
        if isinstance(x,dict):
            return next((str(x[k]) for k in keys if x.get(k)), '')
        return str(x) if x else ''
    if isinstance(value,list): return [one(x)[:80] for x in value if one(x)][:limit]
    text=one(value)
    return [text[:80]] if text else []

def _report_visual_identity_terms(report):
    facts=report.get('facts') or {}
    product=facts.get('product') or {}
    terms=[]
    for value in (product.get('brand'),):
        value=str(value or '').strip()
        if len(value)>=2:terms.append(value)
    attrs=facts.get('attributes') or []
    if isinstance(attrs,list):
        for item in attrs:
            if not isinstance(item,dict):continue
            name=str(item.get('name') or '')
            value=str(item.get('value') or '').strip()
            if any(key in name for key in ('品牌','商标')) and len(value)>=2:
                terms.append(value)
    return list(dict.fromkeys(terms))

def _visual_clean(value, limit=18, blocked_terms=()):
    return _visual_product_text(value,limit,blocked_terms)[:8]

def _visual_title(title, brand='', blocked_terms=()):
    text=str(title or '商品').strip()
    terms=[str(brand or '').strip(), *(str(term).strip() for term in blocked_terms)]
    for term in terms:
        if term:
            text=text.replace(term,'')
    parts=[]
    for part in re.split(r'[\s｜|·]+',text):
        if part and not any(term in part for term in VISUAL_EXCLUDED_TERMS):
            parts.append(part)
    return ' '.join(parts).strip() or '商品主体'

def _image_user_direction(value, blocked_terms=()):
    text=str(value or '').strip()
    blocked_terms=tuple(str(x) for x in blocked_terms if x)
    if not text: return {'raw':'','accepted':[],'rejected':[],'ignored':[],'items':[],'blockedTerms':list(blocked_terms)}
    risky=tuple(VISUAL_EXCLUDED_TERMS)+blocked_terms+(
      '低价','包邮','顺丰','销量','已售','第一','冠军','专利','认证','防伪','旗舰店','正品','logo','Logo','LOGO',
      '二维码','水印','退款','退货','客服','促销','满减','买一送一','折扣','价格','￥','¥'
    )
    def risky_reason(part):
        return '涉及品牌、交易、认证或平台禁区' if any(term and term in part for term in risky) else ''
    def scope_of(part):
        product_terms=('商品','产品','材质','面料','材料','成分','结构','件数','尺寸','规格','颜色','花型','款式','功能','填充','支数')
        change_terms=('换成','改成','变成','换为','改为','变为','采用','使用','调整为','设为')
        presentation_terms=('构图','背景','氛围','镜头','光线','布局','排版','留白','主体','角度','近景','远景','特写',
                            '场景','证明','展示','画面','视角','比例','风格','质感','酒店感','清爽','明亮','高级','极简','治愈',
                            '拆解图','微距','拍摄')
        has_product_term=any(term in part for term in product_terms)
        has_change_term=any(term in part for term in change_terms)
        has_presentation_term=any(term in part for term in presentation_terms)
        # A product-level request is shared by the whole image set. A phrase
        # such as “材质证明改成面料微距特写” remains a visual-only request.
        identity_same_terms=('这是同一个','同一个商品','同款','保持一致','同一商品','不要换商品','不要换产品')
        if any(term in part for term in identity_same_terms):
            return 'product'
        return 'product' if has_product_term and has_change_term and not has_presentation_term else 'visual'
    parts=[x.strip(' ，,。；;、') for x in re.split(r'[。；;，,、\n]+',text) if x.strip(' ，,。；;、')]
    accepted=[]; rejected=[]; items=[]; product_overrides=[]
    for part in parts:
      reason=risky_reason(part)
      if reason:
        rejected.append(part[:80]); items.append({'text':part[:80],'status':'rejected','reason':reason}); continue
      clean=[part]
      if clean:
        scope=scope_of(part)
        accepted.extend(clean)
        items.append({'text':'；'.join(clean),'status':'accepted','scope':scope,'reason':''})
        if scope=='product':
            product_overrides.extend(clean)
      else:
        rejected.append(part[:80]); items.append({'text':part[:80],'status':'rejected','reason':'没有可执行的视觉要求'})
    # Identity statements are global constraints even without a product noun
    # or change verb, for example: “这是同一个”. Keep the original wording
    # visible and add an executable identity instruction.
    identity_parts=[part for part in parts if any(term in part for term in ('这是同一个','同一个商品','同款','保持一致','同一商品','不要换商品','不要换产品'))]
    if identity_parts:
        identity_rule='所有生成图片必须是同一个商品；以第1张产品图的外观和视觉风格为唯一商品基准。'
        accepted.extend(identity_parts)
        accepted.append(identity_rule)
        product_overrides.append(identity_rule)
        for item in items:
            if item.get('text') in identity_parts:
                item['scope']='product'
        items.append({'text':identity_rule,'status':'accepted','scope':'product','reason':'全局商品身份约束'})
    accepted=list(dict.fromkeys(accepted))
    rejected=list(dict.fromkeys(rejected))
    return {'raw':text,'accepted':accepted,'rejected':rejected,'ignored':[],
            'productOverrides':list(dict.fromkeys(product_overrides)),
            'items':items,'blockedTerms':list(blocked_terms)}

def _prompt_override(value):
    text=str(value or '').strip()
    if not text: return ''
    return text

def _slot_relation_terms(slot):
    slot=slot if isinstance(slot,dict) else {}
    terms=[]
    terms.extend(_text_list(slot.get('role')))
    terms.extend(_text_list(slot.get('contentKey')))
    terms.extend(_text_list(slot.get('task')))
    terms.extend(_text_list(slot.get('nextAction')))
    terms.extend(_text_list(slot.get('planProductAction')))
    terms.extend(_text_list(slot.get('planPageAction')))
    content_key=str(slot.get('contentKey') or '')
    category_terms={
      'product_overview':('商品','产品','主体','整体','件数','套件','组合'),
      'usage_scene':('场景','使用','空间','适用','人群','季节','用途'),
      'material_touch':('材质','面料','成分','支数','密度','克重','填充','触感','质感','特写','近景'),
      'structure_function':('结构','工艺','功能','做工','细节','走线','接口','拉链'),
      'spec_choice':('尺寸','规格','件数','颜色','款式','SKU','适配'),
      'scene_problem':('场景','使用','人群','适用','用途','问题'),
      'material_proof':('材质','面料','成分','支数','密度','克重','填充','触感','质感','特写','近景'),
      'structure_proof':('结构','工艺','做工','细节','缝制','接口','拉链','走线'),
      'function_proof':('功能','性能','使用','透气','防护','收纳','连接','结果'),
      'spec_adaptation':('规格','尺寸','件数','套件','SKU','适配','颜色','款式'),
      'care_durability':('洗护','洗涤','护理','耐用','首洗','清洁','保存'),
      'material_closeup':('材质','面料','成分','纤维','触感','质感','特写','近景','纹理'),
      'craft_closeup':('工艺','缝制','绗缝','做工','细节','走线','接口'),
      'function_scenario':('功能','使用','性能','保暖','透气','抗菌','结果'),
      'size_compare':('尺寸','规格','床型','长度','宽度','对照'),
      'set_inventory':('件数','套件','组合','配件','被套'),
      'color_selection':('颜色','配色','花型','款式','SKU'),
      'care_steps':('洗护','洗涤','护理','晾晒','保存'),
      'quality_check':('耐用','首洗','回弹','起球','褪色'),
      'purchase_summary':('适用','人群','场景','规格','选择'),
    }
    terms.extend(category_terms.get(content_key,()))
    if slot.get('assetType')=='main':
        terms.extend(['主图','首图','封面','点击','构图','卖点','氛围','背景','镜头','光线','留白'])
    else:
        terms.extend(['详情','详情图','证明','介绍','排版','对比'])
    clean=[]
    relation_stop_terms={'证明','详情','详情图','介绍','主图','首图','封面','点击','卖点'}
    for term in terms:
        for part in re.split(r'[，,。；;、\s/|]+',str(term or '')):
            part=part.strip()
            if len(part)>=2 and part not in relation_stop_terms: clean.append(part[:24])
    return list(dict.fromkeys(clean))[:36]

def _prompt_edit_relevance(text, slot, user_direction=None):
    text=str(text or '').strip()
    if not text: return {'related':False,'matched':[],'unrelated':[]}
    relation_terms=_slot_relation_terms(slot)
    matched=[term for term in relation_terms if term and term in text][:10]
    direction_terms=[]
    if isinstance(user_direction,dict):
        direction_terms=[x for x in user_direction.get('accepted') or [] if x and x in text]
    broad_terms=('场景','构图','背景','氛围','镜头','光线','布局','排版','留白','主体','角度','比例','信息层级',
                 '风格','清爽','浅色','明亮','高端','酒店感','极简','治愈')
    broad=[term for term in broad_terms if term in text]
    related=bool(matched or direction_terms or broad)
    unrelated=[]
    if not related:
        unrelated=[text[:120]]
    return {'related':related,'matched':list(dict.fromkeys(matched+direction_terms+broad))[:12],'unrelated':unrelated}

def _user_direction_for_slot(direction, slot):
    """Keep only safe global user direction that is relevant to this image slot."""
    direction=direction if isinstance(direction,dict) else {}
    if 'resolvedBySlot' in direction:
        key=f"{slot.get('assetType')}:{slot.get('index')}"
        resolved=direction['resolvedBySlot'].get(key) or {}
        return {**direction,
                'accepted':list(dict.fromkeys(direction.get('globalInstructions',[])+resolved.get('instructions',[]))),
                'ignored':[], 'slotResolution':resolved}
    accepted=[]; rejected=list(direction.get('rejected') or []); ignored=[]; matched=[]
    items=direction.get('items') or [
      {'text':value,'status':'accepted','scope':'visual','reason':''} for value in direction.get('accepted') or []
    ]
    for item in items:
        if not isinstance(item,dict) or item.get('status')!='accepted': continue
        text=str(item.get('text') or '').strip()
        if not text: continue
        if item.get('scope')=='product':
            accepted.append(text)
            matched.append('用户明确商品设定')
            continue
        relation=_prompt_edit_relevance(text,slot)
        if relation.get('related'):
            accepted.append(text)
            matched.extend(relation.get('matched') or [])
        else:
            ignored.append(text)
    return {
      'raw':direction.get('raw') or '',
      'accepted':list(dict.fromkeys(accepted))[:6],
      'rejected':list(dict.fromkeys(rejected))[:6],
      'ignored':list(dict.fromkeys(ignored))[:6],
      'productOverrides':list(dict.fromkeys(
        [x for x in accepted if x in (direction.get('productOverrides') or [])]
      ))[:6],
      'items':items,
      'matched':list(dict.fromkeys(matched))[:12],
      'blockedTerms':direction.get('blockedTerms') or []
    }

def _collect_prompt_product_overrides(prompt_overrides, blocked_terms=()):
    """Extract safe product changes from per-slot edits for the shared image set."""
    overrides=[]
    if not isinstance(prompt_overrides,dict): return overrides
    for value in prompt_overrides.values():
        direction=_image_user_direction(value,blocked_terms)
        overrides.extend(direction.get('productOverrides') or [])
    return list(dict.fromkeys(overrides))[:12]

def _apply_product_overrides(direction, overrides):
    """Promote product changes from any input surface into the shared direction."""
    direction=dict(direction or {}) if isinstance(direction,dict) else {}
    for key in ('accepted','rejected','ignored','items','productOverrides','matched','blockedTerms'):
        value=direction.get(key)
        direction[key]=list(value) if isinstance(value,list) else []
    existing=set(direction.get('productOverrides') or [])
    for value in overrides or []:
        text=str(value or '').strip()
        if not text or text in existing: continue
        existing.add(text)
        direction['productOverrides'].append(text)
        if text not in direction['accepted']:
            direction['accepted'].append(text)
        direction['items'].append({'text':text,'status':'accepted','scope':'product','reason':'','source':'per_slot'})
    direction['productOverrides']=direction['productOverrides'][:12]
    direction['accepted']=list(dict.fromkeys(direction['accepted']))[:12]
    return direction

def _resolve_image_user_intent(report, plan, slots, direction, prompt_overrides, reference_images, match_reference_shooting):
    """Resolve the same product/plan/reference relationship for preview and generation.

    No input means no extra model call or automatic replanning. Explicit input
    is interpreted once with the full plan and corresponding image analyses;
    fixed navigation labels never decide whether a request is discarded.
    """
    edits={key:_prompt_override(value) for key,value in (prompt_overrides or {}).items() if _prompt_override(value)}
    if not direction.get('raw') and not edits:
        return direction
    payload={'product':(report.get('facts') or {}).get('product') or {},
             'attributes':(report.get('facts') or {}).get('attributes') or {},
             'plan':plan, 'userInput':direction.get('raw') or '', 'perImageInput':edits,
             'matchReferenceShooting':bool(match_reference_shooting),
             'images':[{'key':f"{s.get('assetType')}:{s.get('index')}", 'task':s.get('task') or [],
                        'referenceAnalysis':s.get('referenceAnalysis') or {}} for s in slots]}
    encoded=json.dumps({'payload':payload,'identityImages':reference_images[:1]},ensure_ascii=False,sort_keys=True)
    cache_key=hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    with IMAGE_INTENT_LOCK:
        cached=IMAGE_INTENT_CACHE.get(cache_key)
    if cached is None:
        system='''你是电商生图的统一意图解析器。只输出JSON，不生图、不重做报告。
所选方案是默认底座。结合用户完整输入、产品图片、品类、产品信息及每张对应参考图分析，判断用户明确要求与必然关联的调整。不得靠固定槽位名称决定主题，不得丢弃没有关键词匹配的有效输入。
没有被要求改变的方案方向继续保留。换品类也不自动清空方案、要求补资料或重分析；保留适用的主题并适配新品。只有用户要求重策划才调整整体方向。旧品专属参数不能冒充新品事实；没有新品参数时保留适用表达方向，使用有依据的可见描述，不编造数值。
全局输入须判断对每张图的影响；单图视觉输入只作用对应key，但其中明确的产品/品类修改应作用整套商品。产品、品类、用途、人群、场景、卖点及文案间的必然关联须同步。
开启参考一致时，对应参考图的展示状态和文字位置、大小、层级、对齐、排版是默认约束；同品复现，跨品类保留适用构图关系与展示意图，不强迫新品执行不适用的动作。用户明确改变某项展示或排版时仅覆盖该项，其余保持参考。文案主题参考对应图，内容按当前产品和用户要求调整。
上传图提供默认身份，用户明确要求换品类/产品/属性时覆盖对应字段，不能同时要求新品与旧品类完全一致。用户输入是指令，不自动逐字印在图上；明确指定标题原文则按要求执行。不得生成品牌Logo、交易促销、认证或未证实宣称。
输出结构：{"productUpdates":[{"field":"category|productName|material|color|specification|purpose|audience|sellingPoint","value":"明确的新内容","sourceText":"用户输入中的原文片段"}],"globalInstructions":["整套图须执行的调整"],"perSlot":{"main:1":{"instructions":["本图采纳的要求"],"theme":"本图方案主题如何适配当前产品","display":"与对应参考图的展示关系","copy":"本图文案内容与参考排版的关系"}}}。
productUpdates只能来自用户明确输入，每项sourceText必须逐字出自userInput或perImageInput。必须覆盖传入的所有图片key。无调整的字段不输出更新，instructions可为空，保留默认方案和参考关系。所有指令应可追溯至输入或方案，不能擅自新增商品变化。'''
        analysis_error=''
        try:
            resolved=chat_json(system,json.dumps(payload,ensure_ascii=False),images=reference_images[:1] or None,max_tokens=6500)
        except Exception as error:
            # Intent interpretation is advisory, not a second mandatory gateway.
            # Preserve the actual instructions for the multimodal generation
            # model to interpret with the same plan/reference/product context.
            resolved={}
            analysis_error=str(error)
        original_result=resolved
        resolved=dict(resolved) if isinstance(resolved,dict) else {}
        def texts(value):
            if isinstance(value,str):return [value] if value.strip() else []
            if not isinstance(value,list):return []
            return [x for x in value if isinstance(x,str) and x.strip()]
        resolved['globalInstructions']=texts(resolved.get('globalInstructions',[]))
        per_slot=resolved.get('perSlot')
        resolved['perSlot']=dict(per_slot) if isinstance(per_slot,dict) else {}
        for slot in slots:
            key=f"{slot.get('assetType')}:{slot.get('index')}"
            item=resolved['perSlot'].get(key)
            item=dict(item) if isinstance(item,dict) else {}
            for field in ('theme','display','copy'):
                if not isinstance(item.get(field),str):item[field]=''
            item['instructions']=texts(item.get('instructions',[]))
            resolved['perSlot'][key]=item
        all_input='\n'.join([direction.get('raw') or '']+list(edits.values()))
        updates=resolved.get('productUpdates',[])
        fields={'category','productName','material','color','specification','purpose','audience','sellingPoint'}
        safe_updates=[]
        for update in updates if isinstance(updates,list) else []:
            if isinstance(update,dict) and update.get('field') in fields and isinstance(update.get('value'),str) and update['value'].strip() and isinstance(update.get('sourceText'),str) and update['sourceText'] and update['sourceText'] in all_input:
                safe_updates.append(update)
        resolved['productUpdates']=safe_updates
        if isinstance(updates,list) and len(safe_updates)!=len(updates):
            # A rejected identity inference may already have contaminated every
            # slot's display/theme prose. Keep the raw response for diagnosis,
            # but never pass that ungrounded narrative to generation.
            resolved['globalInstructions']=[]
            resolved['perSlot']={f"{slot.get('assetType')}:{slot.get('index')}":{
                'instructions':[],'theme':'','display':'','copy':''} for slot in slots}
        resolved['analysisRecord']={'response':original_result,'error':analysis_error}
        # JSON copy prevents a slot/prompt mutation from altering the shared result.
        cached=json.dumps(resolved,ensure_ascii=False)
        with IMAGE_INTENT_LOCK:
            if len(IMAGE_INTENT_CACHE)>=32:
                IMAGE_INTENT_CACHE.pop(next(iter(IMAGE_INTENT_CACHE)))
            IMAGE_INTENT_CACHE[cache_key]=cached
    resolved=json.loads(cached)
    result=dict(direction)
    result.update({'resolvedBySlot':resolved['perSlot'], 'globalInstructions':resolved['globalInstructions'],
                   'perImageInput':edits,'analysisRecord':resolved.get('analysisRecord'),
                   'productUpdates':resolved.get('productUpdates',[]),
                   'productOverrides':[f"{u['field']}：{u['value']}" for u in resolved.get('productUpdates',[])],
                   'accepted':resolved['globalInstructions'], 'ignored':[]})
    return result

def merge_image_prompt_with_user_edit(base_prompt, edit_text, slot, user_direction=None):
    """Fuse per-image user edits with the built-in visual strategy only when relevant."""
    edit=_prompt_override(edit_text)
    if isinstance(user_direction,dict) and 'resolvedBySlot' in user_direction:
        # The complete edit has already been interpreted with the shared product
        # context and this reference. Do not append it again with a competing
        # "highest priority" instruction or re-run the keyword relevance filter.
        return base_prompt, {'mode':'applied' if edit else 'builtin','related':bool(edit),
                             'matched':user_direction.get('accepted') or [],'ignored':[]}
    if not edit:
        return base_prompt, {'mode':'builtin','related':False,'matched':[],'ignored':[]}
    blocked_terms=((user_direction or {}).get('blockedTerms') or ()) if isinstance(user_direction,dict) else ()
    edit_direction=_image_user_direction(edit,blocked_terms)
    accepted_edits=edit_direction.get('accepted') or []
    product_edits=edit_direction.get('productOverrides') or []
    visual_edits=[value for value in accepted_edits if value not in product_edits]
    visual_text='；'.join(visual_edits)
    visual_relevance=_prompt_edit_relevance(visual_text,slot,user_direction) if visual_text else {'related':False,'matched':[],'unrelated':[]}
    related=bool(product_edits or visual_relevance.get('related'))
    safe_parts=list(product_edits)
    if visual_relevance.get('related'):
        safe_parts.extend(visual_edits)
    safe_edit='；'.join(list(dict.fromkeys(safe_parts)))
    relevance={
      'related':related,
      'matched':list(dict.fromkeys((['用户明确商品设定'] if product_edits else [])+list(visual_relevance.get('matched') or [])))[:12],
      'unrelated':list(visual_relevance.get('unrelated') or [])
    }
    if not relevance.get('related'):
        guard="\n\n【单图用户编辑未采纳】用户编辑内容与本张图片策划任务、主题、卖点、场景或构图没有明确关联；本图继续执行内置策划，不替换当前图片任务。"
        ignored=list(dict.fromkeys((edit_direction.get('rejected') or [])+(relevance.get('unrelated') or [])))[:6]
        return base_prompt+guard, {'mode':'ignored_unrelated','related':False,'matched':[],'ignored':ignored}
    accepted='；'.join((user_direction or {}).get('accepted') or []) if isinstance(user_direction,dict) else ''
    merged=f'''【每张图用户编辑提示词｜当前图片相关，优先执行】
    {safe_edit}

【联合分析与自动优化规则】
以上用户编辑内容已判断与当前图片策划相关：{('；'.join(relevance.get('matched') or []) or '与场景/构图/表达方向相关')}。
请以用户编辑内容为最高优先级，自动融合到本张图的商品设定、主题、构图、场景、氛围、镜头、排版或表达重点中；如果它与报告事实、参考图或内置策划细节发生冲突，优先满足用户明确指定的内容。
{('当前全局用户补充要求也需优先兼容：'+accepted+'。') if accepted else ''}

【内置关联提示词｜必须继承】
{base_prompt}

【不可覆盖约束】
用户明确指定的商品变化必须执行；用户未指定的字段继续保持默认基准。仅禁止品牌Logo、价格、销量、认证、二维码、水印、交易承诺及其他平台禁区内容。
'''
    ignored=list(dict.fromkeys((edit_direction.get('rejected') or [])+(relevance.get('unrelated') or [])))[:6]
    return merged, {'mode':'applied','related':True,'matched':relevance.get('matched') or [],'ignored':ignored}

def _slot_definitions(asset_type):
    return MAIN_VISUAL_TASKS if asset_type=='main' else DETAIL_VISUAL_TASKS

def build_identity_lock(report, plan, user_direction=None, uploaded_product_identity=False):
    """Create one shared product baseline plus the user's final overrides."""
    facts=report.get('facts') or {}; product=facts.get('product') or {}
    attrs=facts.get('attributes') or []
    title=str(product.get('title') or '商品').strip()
    brand=str(product.get('brand') or '').strip()
    blocked_terms=_report_visual_identity_terms(report)
    fields=[]
    if uploaded_product_identity:
        # Collected facts remain available to the business brief, but never
        # become the visual identity of a user-supplied replacement product.
        brand=''
        fields=[]
    elif isinstance(attrs,dict):
        fields=[f'{k}={v}' for k,v in attrs.items() if str(v).strip() and _visual_clean(f'{k}={v}',18,blocked_terms)][:12]
    else:
        fields=[f"{x.get('name')}={x.get('value')}" for x in attrs if isinstance(x,dict) and x.get('name') and x.get('value') and _visual_clean(f"{x.get('name')}={x.get('value')}",18,blocked_terms)][:12]
    selling=[text for x in (plan or {}).get('sellingPoints',[]) if isinstance(x,dict) for text in _visual_clean(x.get('slogan') or x.get('consumerValue'),32,blocked_terms)][:5]
    if uploaded_product_identity:
        selling=[]
    user_overrides=list(dict.fromkeys(
      (user_direction or {}).get('productOverrides') or []
    )) if isinstance(user_direction,dict) else []
    identity_text='|'.join([title,brand,';'.join(fields),';'.join(selling),';'.join(user_overrides)])
    identity_id='identity_'+hashlib.sha256(identity_text.encode('utf-8')).hexdigest()[:12]
    updates=(user_direction or {}).get('productUpdates') or []
    for update in updates:
        if update.get('field') in ('category','productName'):title=update['value']
    return {
      'id':identity_id,'productName':title,'brand':brand,'verifiedFacts':fields,
      'userOverrides':user_overrides,
      'sellingPoints':selling,
      'mustKeep':['上传产品图或方案提供默认身份，用户明确修改的品类/产品字段及其必然关联变化覆盖默认身份' if updates else '上传产品图中的商品品类、轮廓、比例、材质、颜色/花型、结构、件数和配件' if uploaded_product_identity else '商品品类','用户未明确修改且适用于当前产品的商品字段','同一套图片共享同一最终商品设定'],
      'mustNotChange':['品牌Logo、价格、销量、水印或二维码','认证、专利、授权及其他未证实平台宣称','用户未明确要求的额外商品变化']
    }

def build_generation_slots(report, plan):
    """Derive a complete, ordered image set from the analysis output."""
    exp=report.get('experienceSolution') or {}
    visual=exp.get('visualCommerce') or {}
    detail=exp.get('detailCommerce') or {}
    main_items=[x for x in (visual.get('items') or []) if isinstance(x,dict)]
    detail_items=[x for x in (detail.get('contentGroups') or []) if isinstance(x,dict)]
    raw_visual=report.get('visualDecision') or {}
    raw_detail=report.get('detailDecision') or {}
    # Report presentation normalizes roles by position. Generation needs the
    # original image analysis, not those rewritten presentation roles.
    original_main={str(x.get('imageEvidenceId')):x for x in raw_visual.get('imageRoles',[]) if isinstance(x,dict) and x.get('imageEvidenceId')}
    original_detail={str(x.get('representativeImageId') or x.get('imageEvidenceId')):x for x in raw_detail.get('contentGroups',[]) if isinstance(x,dict) and (x.get('representativeImageId') or x.get('imageEvidenceId'))}
    original_observations={str(x.get('imageEvidenceId')):x for block in (raw_visual,raw_detail,visual,detail) for x in block.get('evidenceDetail',[]) if isinstance(x,dict) and x.get('imageEvidenceId')}
    # Raw observations win over the optional presentation detail.
    original_observations.update({str(x.get('imageEvidenceId')):x for block in (raw_visual,raw_detail) for x in block.get('evidenceDetail',[]) if isinstance(x,dict) and x.get('imageEvidenceId')})
    # Keep the OCR/text observation attached to the corresponding collected
    # image slot.  It is separate from visualSignals so the image prompt can
    # preserve a reference's copy-led layout without inventing copy.
    text_by_image_id={
        str(x.get('imageEvidenceId') or ''): str(x.get('textInfo') or '').strip()
        for x in (visual.get('evidenceDetail') or []) if isinstance(x,dict) and x.get('imageEvidenceId')
    }
    text_by_image_id.update({
        str(x.get('imageEvidenceId') or ''): str(x.get('textInfo') or '').strip()
        for x in (detail.get('evidenceDetail') or []) if isinstance(x,dict) and x.get('imageEvidenceId')
    })
    selling=[x for x in (plan or {}).get('sellingPoints',[]) if isinstance(x,dict)]
    if not main_items:
        main_items=[{'imageRole':'主商品全貌','visualSignals':_text_list(x.get('slogan') or x.get('consumerValue')),'nextAction':'完整展示商品与核心卖点'} for x in selling[:5]]
    if not main_items: main_items=[{'imageRole':'主商品全貌','visualSignals':['商品主体完整'],'nextAction':'完整展示商品'}]
    if not detail_items:
        detail_labels=['场景证明','材质证明','结构工艺','功能表现','规格适配','使用维护']
        detail_items=[{
            'type':label,
            'visualSignals':_text_list(x.get('slogan') or x.get('consumerValue')),
            'businessMeaning':x.get('consumerValue',''),
            'nextAction':x.get('productAction','')
        } for label,x in zip(detail_labels,selling)]
    if not detail_items:
        detail_items=[{
            'type':definition['role'],
            'visualSignals':list(definition['signals']),
            'nextAction':definition['nextAction']
        } for definition in DETAIL_VISUAL_TASKS]
    valid_ids={x.get('id') for x in (report.get('evidenceLedger') or []) if isinstance(x,dict)}
    blocked_terms=_report_visual_identity_terms(report)

    def make_slots(asset_type, source_items, max_count):
        definitions=_slot_definitions(asset_type)
        image_group='main' if asset_type=='main' else 'detail'
        image_ids=[f'IMG_{image_group.upper()}_{i:04d}' for i,_ in enumerate(((report.get('facts') or {}).get('images') or {}).get(image_group,[]) or [],1)]
        # Expose the full selectable task set. Users may pick any subset; detail
        # tasks deliberately extend to 15 evidence positions.
        count=min(max_count,len(definitions))
        used_source=set();used_signals=set();result=[]
        for index in range(count):
            definition=definitions[index]
            eid=image_ids[index] if index<len(image_ids) else ''
            source=None;source_index=None
            if eid:
                for candidate_index,candidate in enumerate(source_items):
                    if candidate.get('imageEvidenceId')==eid or candidate.get('representativeImageId')==eid:
                        source=candidate;source_index=candidate_index;break
            if source is None:
                for candidate_index,candidate in enumerate(source_items):
                    if candidate_index not in used_source:
                        source=candidate;source_index=candidate_index;break
            if source_index is not None:used_source.add(source_index)
            original=(original_main if asset_type=='main' else original_detail).get(eid)
            if original is not None:
                source=original
            observation=original_observations.get(eid) or {}
            reference_text = ''
            if isinstance(source,dict):
                reference_text = str(source.get('textInfo') or '').strip()
            if not reference_text and eid:
                reference_text = str(observation.get('textInfo') or text_by_image_id.get(eid, ''))
            refs=[]
            if isinstance(source,dict):
                refs.extend(x for x in source.get('evidenceIds',[]) or [] if x in valid_ids)
                refs.extend(x for x in source.get('imageEvidenceIds',[]) or [] if x in valid_ids)
                for key in ('imageEvidenceId','representativeImageId'):
                    if source.get(key) in valid_ids:refs.append(source.get(key))
            if eid in valid_ids:refs.append(eid)
            refs=list(dict.fromkeys(refs))
            source_signals=_visual_clean(source.get('visualSignals') if source else [],18,blocked_terms)
            source_signals=[x for x in source_signals if any(word in x for word in definition['keywords'])]
            source_signals=[x for x in source_signals if x not in used_signals]
            used_signals.update(source_signals)
            task=list(dict.fromkeys(list(definition['signals'])+source_signals))[:4]
            result.append({
                'assetType':asset_type,'index':index+1,'contentKey':definition['contentKey'],
                'role':definition['role'],'task':task,'nextAction':definition['nextAction'],
                'planName':_text_list((plan or {}).get('name'))[0] if _text_list((plan or {}).get('name')) else '新品方案',
                'planSubtitle':_text_list((plan or {}).get('sourceType'))[0] if _text_list((plan or {}).get('sourceType')) else '产品新方案',
                'planProductAction':_visual_clean((plan or {}).get('productAction'),45,blocked_terms),
                'planPageAction':_visual_clean((plan or {}).get('pageAction'),36,blocked_terms),
                'handoff':f"本图完成{definition['role']}后，继续进入下一项产品证明",
                'avoidTopics':['其他图片已承担的卖点','品牌/专利/授权/物流/交易信息'],
                'evidenceIds':refs,
                'referenceTextInfo':reference_text,
                'collectedReferenceEvidenceId':eid,
                'referenceAnalysis': {
                    'theme':str((source or {}).get('imageRole') or (source or {}).get('type') or ''),
                    'signals':((source or {}).get('visualSignals') or []) if isinstance((source or {}).get('visualSignals'),list) else [str((source or {}).get('visualSignals'))] if (source or {}).get('visualSignals') else [],
                    'meaning':(source or {}).get('businessMeaning') or '',
                    'composition':str(observation.get('composition') or ''),
                    'productSubject':str(observation.get('productSubject') or ''),
                    'displayRelations':observation.get('displayRelations') or (source or {}).get('displayRelations') or {},
                    'imageRoleAnalysis':source or {},
                    'imageObservation':observation,
                },
            })
        return result

    # 主图最多 5 张；详情图提供最多 15 个可选证明位。
    return make_slots('main',main_items,5)+make_slots('detail',detail_items,15)

def resolve_reference_images(report, plan, requested=None):
    """Resolve uploaded product-identity inputs for the image set.

    The first upload is the canonical identity master used alone by main:1.
    Follow-up slots may use the remaining uploads as supporting views of the
    same product; per-slot routing decides how many images reach the provider.
    """
    uploads=[]
    if isinstance(requested,list) and len(requested)>4:
        raise ValueError('单次生图最多四张参考图')
    for value in requested or []:
        value=str(value or '').strip()
        if not value: continue
        if value.startswith('data:image/'):
            if len(value)>12*1024*1024: raise ValueError('单张参考图不能超过 9MB')
            uploads.append(value)
        elif value.startswith('/reports/assets/reference_uploads/'):
            path=(REPORTS/value[len('/reports/'):]).resolve()
            if (IMAGE_ASSET_ROOT/'reference_uploads').resolve() not in path.parents or not path.is_file():
                raise ValueError('上传参考图不存在或路径无效')
            uploads.append(value)
        elif value.startswith(('http://','https://')):
            uploads.append(value)
        else:
            raise ValueError('参考图必须是图片文件或 HTTPS 图片地址')
    if uploads: return uploads[:4],'uploaded'
    ledger=[x for x in (report.get('evidenceLedger') or []) if isinstance(x,dict) and x.get('type')=='image']
    def usable(item):
        if not item:return ''
        meta=item.get('meta') or {}
        candidates=[meta.get('sourceUrl'),item.get('value'),meta.get('localUrl')]
        return next((str(x) for x in candidates if str(x or '').startswith(('http://','https://','data:image/'))),'')
    first=next((usable(x) for x in ledger if (x.get('meta') or {}).get('group')=='main' and usable(x)), '')
    if first:return [first],'first_main'
    raise ValueError('没有可用的商品主图，请先上传产品参考图')

def _evidence_image_url(report, evidence_id):
    evidence_id=str(evidence_id or '').strip()
    if not evidence_id:return ''
    for item in report.get('evidenceLedger') or []:
        if not isinstance(item,dict) or item.get('type')!='image' or str(item.get('id') or '')!=evidence_id:continue
        meta=item.get('meta') or {}
        candidates=(meta.get('sourceUrl'),item.get('value'),meta.get('value'),meta.get('localUrl'))
        return next((str(x).strip() for x in candidates if str(x or '').strip().startswith(('http://','https://','data:image/','/reports/'))),'')
    return ''

def _indexed_fact_image_url(report, asset_type, index):
    group='main' if asset_type=='main' else 'detail'
    try:index=max(1,int(index or 1))
    except Exception:index=1
    images=(((report.get('facts') or {}).get('images') or {}).get(group) or [])
    if index<=len(images):
        item=images[index-1]
        if isinstance(item,dict):
            candidates=(item.get('sourceUrl'),item.get('url'),item.get('value'),item.get('localUrl'))
        else:
            candidates=(item,)
        return next((str(x).strip() for x in candidates if str(x or '').strip().startswith(('http://','https://','data:image/','/reports/'))),'')
    return ''

def _collected_slot_reference(report, slot):
    """Resolve the collected image that owns a slot's display state.

    Uploaded references can define the replacement product, but they must not
    replace the source image that defines this slot's camera and presentation.
    Prefer the slot's explicit evidence id, then its indexed collected image,
    and finally the first image in the same collected group as a controlled
    fallback.
    """
    slot=slot if isinstance(slot,dict) else {}
    asset_type='main' if slot.get('assetType')=='main' else 'detail'
    prefix='IMG_MAIN_' if asset_type=='main' else 'IMG_DETAIL_'
    try:index=max(1,int(slot.get('index') or 1))
    except Exception:index=1

    def pack(url='', binding='', evidence_id='', image_index=None):
        return {
            'url':str(url or '').strip(),
            'binding':binding,
            'evidenceId':str(evidence_id or '').strip(),
            'imageIndex':image_index,
        }

    ids=[str(x) for x in (slot.get('evidenceIds') or []) if str(x)]
    if slot.get('collectedReferenceEvidenceId'):
        ids.insert(0,str(slot['collectedReferenceEvidenceId']))
    evidence_id=next((x for x in ids if x.startswith(prefix) and _evidence_image_url(report,x)),'')
    if not evidence_id:
        candidate=f'{prefix}{index:04d}'
        if _evidence_image_url(report,candidate): evidence_id=candidate
    if evidence_id:
        url=_evidence_image_url(report,evidence_id)
        if url:
            return pack(url,'slot_evidence_reference',evidence_id,index)

    indexed=_indexed_fact_image_url(report,asset_type,index)
    if indexed:
        return pack(indexed,'slot_indexed_reference','',index)

    # A report can have fewer visual evidence positions than generated slots.
    # Keep the state source in the collected product set instead of silently
    # falling back to an uploaded image's camera angle.
    for item in report.get('evidenceLedger') or []:
        if not isinstance(item,dict) or item.get('type')!='image': continue
        meta=item.get('meta') or {}
        if meta.get('group')!=asset_type: continue
        evidence_id=str(item.get('id') or '').strip()
        url=_evidence_image_url(report,evidence_id)
        if url:
            return pack(url,'collected_group_fallback',evidence_id,None)
    images=(((report.get('facts') or {}).get('images') or {}).get(asset_type) or [])
    for item_index,item in enumerate(images,1):
        if isinstance(item,dict):
            candidates=(item.get('sourceUrl'),item.get('url'),item.get('value'),item.get('localUrl'))
        else:
            candidates=(item,)
        url=next((str(x).strip() for x in candidates if str(x or '').strip().startswith(('http://','https://','data:image/','/reports/'))),'')
        if url:
            return pack(url,'collected_index_fallback','',item_index)
    return pack()

def _slot_reference_images(report, slot, reference_images, reference_source, reference_mode, match_reference_shooting=False):
    """Choose the actual image guidance for one slot and describe the binding.

    ``resolve_reference_images`` finds a product baseline for the whole run.
    When the user asks to match reference shooting/display state, each slot
    needs a concrete visual master instead of sharing an undifferentiated image
    pool.  In the hybrid path the uploaded product image is always input 1 and
    the collected slot image is always input 2.  This keeps main:1 tied to
    IMG_MAIN_0001, main:2 to IMG_MAIN_0002, and detail slots to their own
    detail evidence whenever the report has it.
    """
    slot=slot if isinstance(slot,dict) else {}
    refs=[str(x).strip() for x in (reference_images or []) if str(x or '').strip()]
    meta={
        'referenceBinding':'shared_product_reference',
        'referenceImageIndex':None,
        'referenceEvidenceId':'',
        'displayReferenceBinding':'',
        'displayReferenceEvidenceId':'',
        'displayReferenceImageIndex':None,
        'identityReferenceImageIndex':None,
        'identityReferenceUrl':'',
        'displayReferenceUrl':'',
    }
    if not refs:
        return [],meta
    # Every preview slot must expose the identity reference, including
    # fission follow-up slots.  The fission branch still sends the generated
    # base image to the provider, but the UI must not lose the original
    # reference image metadata.
    meta['identityReferenceUrl']=refs[0]
    # The card preview is slot-specific even when the provider follows a
    # shared/fission identity reference. Resolve and expose the collected
    # image before the fission early return so main:02/detail:02 do not show
    # main:01 as their visual reference.
    collected=_collected_slot_reference(report,slot)
    collected_url=collected.get('url')
    if collected_url:
        meta['displayReferenceUrl']=collected_url
        meta['displayReferenceBinding']=collected.get('binding','')
        meta['displayReferenceEvidenceId']=collected.get('evidenceId','')
        meta['displayReferenceImageIndex']=collected.get('imageIndex')
    if reference_mode=='fission_followup' and not _coerce_bool(match_reference_shooting, False):
        meta['referenceBinding']='generated_fission_base'
        return refs[:1],meta
    # Preview metadata always exposes the slot's corresponding collected
    # image, even when display-state matching is disabled. The UI needs to
    # show the reference that would be used for this slot without making that
    # image an input to the provider.
    if refs:
        meta['identityReferenceUrl']=refs[0]
    if not _coerce_bool(match_reference_shooting, False):
        return refs[:4],meta

    if reference_source=='uploaded':
        # Input 1 owns product identity; input 2 owns this slot's camera and
        # display state.  Merely describing input 2 in text is insufficient:
        # the provider must receive the actual collected image to reproduce a
        # concrete pose, fold, placement or interaction.  The prompt assigns
        # strict, non-overlapping roles so input 2 cannot redefine appearance.
        identity_ref=refs[0]
        if collected_url:
            slot_refs=[identity_ref,collected_url]
            meta.update({
                'referenceBinding':'uploaded_identity_collected_slot',
                'referenceImageIndex':1,
                'referenceEvidenceId':collected.get('evidenceId',''),
                'displayReferenceBinding':collected.get('binding',''),
                'displayReferenceEvidenceId':collected.get('evidenceId',''),
                'displayReferenceImageIndex':2,
                'identityReferenceImageIndex':1,
                'identityReferenceUrl':identity_ref,
                'displayReferenceUrl':collected_url,
            })
            return slot_refs,meta
        meta.update({
            'referenceBinding':'uploaded_identity_only',
            'referenceImageIndex':1,
            'identityReferenceImageIndex':1,
            'identityReferenceUrl':identity_ref,
        })
        return [identity_ref],meta

    if collected_url:
        binding=collected.get('binding') or 'slot_evidence_reference'
        meta.update({
            'referenceBinding':binding,
            'referenceEvidenceId':collected.get('evidenceId',''),
            'displayReferenceBinding':binding,
            'displayReferenceEvidenceId':collected.get('evidenceId',''),
            'displayReferenceImageIndex':collected.get('imageIndex'),
            'referenceImageIndex':collected.get('imageIndex'),
            'displayReferenceUrl':collected_url,
        })
        return [collected_url],meta
    meta['referenceBinding']='fallback_primary_reference'
    return refs[:1],meta

def image_reference_mode(reference_source, fission_pattern=False, slot=None, match_reference_shooting=False):
    """Use the same per-slot reference rule in prompt preview and execution."""
    if reference_source=='uploaded':
        return 'uploaded_identity_collected_reference' if _coerce_bool(match_reference_shooting, False) else 'uploaded_reference'
    if not fission_pattern: return 'collected_reference'
    slot=slot if isinstance(slot,dict) else {}
    return 'fission_base' if slot.get('assetType')=='main' and slot.get('index')==1 else 'fission_followup'

def _reference_data_url(value):
    """Materialize guidance before generation; a URL alone is not proof of input."""
    value=str(value or '').strip()
    if value.startswith('data:image/'):
        return value
    if value.startswith('/reports/'):
        target=(REPORTS/value[len('/reports/'):]).resolve()
        if REPORTS.resolve() not in target.parents or not target.is_file():
            raise ValueError('参考图片文件不存在或路径无效')
        data=target.read_bytes(); ctype=mimetypes.guess_type(target.name)[0] or ''
    elif value.startswith(('http://','https://')):
        data,ctype=_download_image(value)
    else:
        raise ValueError('参考图片地址无效')
    if len(data)>16*1024*1024 or not _looks_like_image(data,ctype):
        raise ValueError('参考图不是有效图片或超过大小限制')
    ctype=ctype.split(';',1)[0].strip()
    if not ctype.startswith('image/'):
        ctype=mimetypes.guess_type('reference'+_asset_ext(value,ctype))[0] or 'image/png'
    return 'data:'+ctype+';base64,'+base64.b64encode(data).decode('ascii')


def _coerce_bool(value, default=False):
    """Parse a JSON/form boolean without treating non-empty strings as true.

    The browser normally sends a real JSON boolean, but older extension builds
    and hand-written API calls may send ``"true"``/``"false"`` or 0/1.  A
    strict parser keeps the reference-shooting switch deterministic and
    prevents an accidental string such as ``"off"`` from enabling it.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ('true', '1', 'yes', 'y', 'on', 'enable', 'enabled', '是', '开启', '打开'):
            return True
        if text in ('false', '0', 'no', 'n', 'off', 'disable', 'disabled', '否', '关闭', '不'):
            return False
    return bool(default)


def _match_reference_shooting(value, default=False):
    """Read the canonical shooting-match flag with backwards-compatible aliases.

    ``matchReferenceShooting`` is the public contract.  The aliases are only
    accepted at the API boundary so preview, execution and persisted manifests
    always expose one canonical field.
    """
    if isinstance(value, dict):
        for key in (
            'matchReferenceShooting', 'referenceShootingMatch',
            'reference_shooting_match', 'shootingMatch',
        ):
            if key in value:
                return _coerce_bool(value.get(key), default)
        return _coerce_bool(default, False)
    return _coerce_bool(value, default)


def _reference_shooting_goals(report, plan, slot, lock, uploaded_product_identity=False):
    """Build compact business/product goals used by the shooting policy.

    These are intentionally derived from the selected plan and slot rather
    than invented by the toggle.  Thus matching a reference photo can alter
    visual grammar while preserving the commercial job of the image and the
    product identity lock.
    """
    plan = plan if isinstance(plan, dict) else {}
    slot = slot if isinstance(slot, dict) else {}
    lock = lock if isinstance(lock, dict) else {}
    plan_name = str(plan.get('name') or '').strip()
    def without_plan_name(value):
        text = str(value or '').strip()
        return text.replace(plan_name, '').strip() if plan_name else text
    business_parts = []
    for value in (
        without_plan_name(plan.get('pageAction')), without_plan_name(plan.get('whyThisPlan')), slot.get('nextAction'),
        slot.get('task'), slot.get('role'),
    ):
        business_parts.extend(_visual_clean(value, 28, _report_visual_identity_terms(report)))
    product_parts = []
    product_parts.extend(_visual_clean(without_plan_name(plan.get('productAction')), 42, _report_visual_identity_terms(report)))
    if not uploaded_product_identity:
        product_parts.extend(str(x) for x in (lock.get('verifiedFacts') or []) if str(x).strip())
    product_parts.extend(str(x) for x in (lock.get('userOverrides') or []) if str(x).strip())
    def compact(parts, fallback, limit=220):
        text='；'.join(list(dict.fromkeys(str(x).strip() for x in parts if str(x).strip())))
        return (text[:limit] if text else fallback)
    if uploaded_product_identity:
        product_goal='保持用户最终确认的商品品类；第1张上传产品图是商品身份真值，优先保持其轮廓、比例、材质、颜色/花型、结构、件数和配件；采集参考图只提供展示状态。'
        if product_parts:
            product_goal+=' 产品方案与用户明确商品设定：'+'；'.join(list(dict.fromkeys(str(x).strip() for x in product_parts if str(x).strip())))[:150]+'。'
        return compact(business_parts, '完成当前图片槽位的购买确认任务'), product_goal
    return (
        compact(business_parts, '完成当前图片槽位的购买确认任务'),
        '保持用户最终确认的商品品类与字段；' + compact(
            product_parts, '保持统一产品身份锁及用户最终商品设定', 190,
        ),
    )

def build_image_prompt(report, plan, asset_type='main', variant_index=0, slot=None, user_direction=None, product_reference_mode='collected_reference', identity_lock=None, match_reference_shooting=False):
    """Turn one evidence-backed visual task into a platform-aware image brief."""
    facts=report.get('facts') or {}; product=facts.get('product') or {}
    attrs=facts.get('attributes') or report.get('attributes') or {}
    title=str(product.get('title') or report.get('product',{}).get('title') or '商品')
    brand=str(product.get('brand') or '').strip()
    category=str(product.get('category') or report.get('product',{}).get('category') or '电商商品')
    audience=str(product.get('audience') or product.get('target') or '')
    plan=plan if isinstance(plan,dict) else {}
    slot=slot if isinstance(slot,dict) else {}
    role=((report.get('roleOutputs') or {}).get('visualDesign') or {})
    blocked_terms=_report_visual_identity_terms(report)
    user_direction=user_direction if isinstance(user_direction,dict) else _image_user_direction(user_direction,blocked_terms)
    lock=identity_lock if isinstance(identity_lock,dict) else build_identity_lock(report,plan,user_direction)
    # The switch is a visual-policy input.  Compute it before composing the
    # slot defaults so the generic ecommerce composition cannot later
    # override a user's request to follow the reference shoot.
    shooting_enabled = _coerce_bool(match_reference_shooting, False)
    display_relationship_guidance=build_display_relationship_guidance(slot.get('referenceAnalysis'),shooting_enabled)
    uploaded_identity = product_reference_mode in ('uploaded_reference','uploaded_identity_collected_reference')
    signals=_visual_clean(slot.get('task'),18,blocked_terms)
    # In hybrid mode the collected listing is only a display-state reference;
    # its style signals often contain campaign decorations (mascots, cotton,
    # skies, slogans) that must not contaminate the uploaded product.
    style=([] if uploaded_identity else
           _visual_clean(role.get('styleSignals'),18,blocked_terms)+_visual_clean(role.get('fashionThesis'),18,blocked_terms))
    params=[]
    if uploaded_identity:
        # Product attributes from the collected listing are evidence for the
        # business brief only. They must never become visual instructions for
        # a replacement product supplied by the user.
        params=[]
    elif isinstance(attrs,dict):
        params=[f'{k}：{v}' for k,v in list(attrs.items())[:8] if str(v).strip() and _visual_clean(f'{k}：{v}',18,blocked_terms)]
    elif isinstance(attrs,list):
        params=[f"{x.get('name')}：{x.get('value')}" for x in attrs if isinstance(x,dict) and x.get('value') and _visual_clean(f"{x.get('name')}：{x.get('value')}",18,blocked_terms)][:8]
    if asset_type=='detail':
        proof='；'.join(signals) or '围绕当前详情任务给出产品证明'
        composition='天猫详情页长图，纵向信息分区，只展示当前任务对应的产品证据；主图已经讲清的内容不再重复，每区留出清晰中文排版空间'
        size='1024x1536'
        goal='详情图：把一个购买疑问变成可验证的视觉证明，信息顺序清晰，适合移动端连续浏览'
    else:
        proof='；'.join(signals) or '突出商品主体与真实使用场景'
        composition='天猫首屏主图，商品主体占画面60-80%，单一核心卖点，强对比但不堆叠文字；干净背景、主体完整、移动端缩略图仍可识别'
        size='1024x1024'
        goal='主图：0.5秒内让用户看懂是什么、为什么值得点、是否适合自己'
    reference_text_info=str(slot.get('referenceTextInfo') or '').strip()
    reference_text_rule=(
        f'对应采集参考图已识别到可见文字：{reference_text_info}。本图必须保留“有文字”的信息表达，并生成与当前商品事实和本槽位任务对应的短文案；不得照抄原图品牌、价格、促销、认证或其他禁用内容。'
        if reference_text_info else
        '本报告缺少对应图文字识别结果，这不代表参考图没有文字。必须查看实际对应采集参考图，依据本图分析任务生成当前产品的简短中文文案并真实渲染到图中；参考图有文字时，严格保持其文字位置、大小占比、对齐、层级、换行、行距和留白。不要凭缺失识别字段生成无字图，不得虚构当前产品参数。'
    )
    analysis_context=json.dumps(slot.get('referenceAnalysis') or {},ensure_ascii=False)
    reference_text_rule += (
        f' 对应图片分析依据：{analysis_context}。'
        '先理解实际对应参考图的表达主题，以上分析用于辅助核对，不能用固定槽位任务改换参考图主题。'
        '本图文案交付要求：生成并真实绘制一个与该主题对应的简短中文主标题；'
        '参考图有副标题或参数层级时，在原有区域生成对应副文案。'
        '内容仅依据当前产品已确认事实及用户批准的产品设定；采集商品原文只提供表达主题，不能视为上传产品的参数证据。'
        '缺乏参数证据时使用可见展示描述，不编造材质比例、尺寸或性能承诺。'
        '文案过长时精简内容以适配参考版式，不得挪动、缩小商品或改变动作、折叠程度、主体占比来腾出文字区域。'
    )
    visual_title=_visual_title(title,brand,blocked_terms)
    product_name=(
        f'''商品文字上下文：仅用于业务目标、证据任务和页面表达；当前商品外观完全由第1张上传产品图决定，采集商品标题、参数、颜色、材质、结构和视觉分析不得改变它。'''
        if uploaded_identity else
        f'''商品默认身份：{visual_title}。仅用于确定起始商品，不把身份信息当成画面卖点。'''
    )
    plan_name=str(plan.get('name') or '').strip()
    def without_plan_name(value):
        text=str(value or '').strip()
        return text.replace(plan_name,'').strip() if plan_name else text
    product_action=_visual_clean(without_plan_name(plan.get('productAction')),45,blocked_terms)
    page_action=_visual_clean(without_plan_name(plan.get('pageAction')),36,blocked_terms)
    plan_rule=f"产品与页面执行约束：产品必须落实：{'；'.join(product_action) or '以已确认商品事实为基础形成明确差异'}；整套图片必须落实：{'；'.join(page_action) or '主图提出购买理由，详情逐项完成证据证明'}。"
    slot_rule=f"本套图中的第{slot.get('index')}个{asset_type}位：{slot.get('role') or '通用'}；唯一任务：{'；'.join(signals) or '保持商品主体清晰'}；承接：{slot.get('handoff') or slot.get('nextAction') or '不偏离当前产品证明'}。"
    if shooting_enabled:
        source_analysis=slot.get('referenceAnalysis') or {}
        slot_rule=(
            f"本套图中的第{slot.get('index')}个{asset_type}位：以对应参考图实际表达为准；"
            f"原始图片主题：{source_analysis.get('theme') or '查看对应参考图确定'}；"
            f"原始展示与构图观察：{source_analysis.get('composition') or '记录缺失，查看对应参考图确定，不能按固定任务重拍'}。"
            '此处描述的是采集图的展示，不授权复制其产品身份。固定槽位名称只用于导航，不约束本图拍摄或改变参考图主题。'
        )
        proof='；'.join(str(item) for item in (source_analysis.get('signals') or [])) or '根据对应参考图的实际表达主题组织当前产品信息'
    accepted=user_direction.get('accepted') or []
    product_overrides=user_direction.get('productOverrides') or []
    user_rule=f"【本图用户要求】以下要求在方案底座上执行，仅覆盖明确要求及必然关联的内容；未涉及的方案方向和参考约束保持有效：{'；'.join(accepted)}。" if accepted else ''
    product_rule=f"【用户最终商品设定｜整套图片共享】用户明确修改的商品字段覆盖报告默认字段和参考图默认外观，所有主图、详情图及裂变基准图必须统一执行：{'；'.join(product_overrides)}。" if product_overrides else ''
    rejected=user_direction.get('rejected') or []
    ignored=user_direction.get('ignored') or []
    rejected_rule=f"仅拦截的用户要求：{'；'.join(rejected)}。原因：涉及品牌、交易、认证或平台禁区；其他商品和视觉修改要求不因改变报告基准而被拦截。" if rejected else ''
    ignored_rule=f"本图未采纳的用户要求：{'；'.join(ignored)}。原因：与本张图片的内策划任务、主题或证明重点没有明确关联。" if ignored else ''
    if shooting_enabled:
        # When matching a reference shoot, conversion learnings may still
        # inform information hierarchy, but must not silently replace the
        # reference camera grammar with our default subject ratio/background.
        benchmark_rule='参考图表达：保留对应参考图的表达主题、文字层次和信息阅读顺序；必须保持其机位、景别、透视、主体占比、构图、场景、背景、光线、动作、朝向、展开/折叠、摆放、接触点、遮挡、部件关系和留白。只替换为当前产品及其对应文案，不复制参考商品外观、品牌、Logo、原文或未证实卖点。'
        composition=(
            '以参考图拍摄语言为主，仅为1024x1536详情画布、当前证明任务和移动端阅读做最小适配；'
            '保持参考图的机位、景别、透视、构图、背景、光线、主体占比、具体动作、朝向、展开/折叠、摆放位置、支撑/接触点、遮挡、部件关系和留白，不额外套用默认详情分区。'
            if asset_type=='detail' else
            '以参考图拍摄语言为主，仅为1024x1024主图画布、当前业务目标和移动端识别做最小适配；'
            '保持参考图的机位、景别、透视、构图、背景、光线、主体占比、具体动作、朝向、展开/折叠、摆放位置、支撑/接触点、遮挡、部件关系和留白，不额外套用默认60-80%主体占比或干净背景。'
        )
    else:
        benchmark_rule='爆款商品特征借鉴：借鉴爆款主图/详情图的高转化结构、主体占比、场景钩子、证明顺序和信息层级；只借鉴表达方法，不复制对标商品外观、品牌、Logo、原文文案或未证实卖点。'
    reference_modes={
      'uploaded_reference':'产品默认参考：用户上传图片用于确定起始商品外观；用户明确指定的商品变化优先覆盖上传图对应字段。',
      'uploaded_identity_collected_reference':'产品默认参考分工：用户上传图片只用于确定要生成的商品身份；采集商品对应槽位图只用于确定本图的拍摄与展示状态；两类参考不得互换职责。',
      'fission_base':'产品默认参考：先基于采集商品主图生成新品基准图；用户明确指定的商品变化优先执行，并作为整套图片的最终商品设定。',
      'fission_followup':'产品默认参考：随请求提供的图片是上一张生成结果；本图继续保持用户最终指定的商品设定和整套图片一致。',
      'collected_reference':'产品默认参考：以采集商品主图作为起始商品参考；用户明确指定的商品变化优先覆盖参考图对应字段。'
    }
    reference_rule=reference_modes.get(product_reference_mode,reference_modes['collected_reference'])
    hybrid_identity_rule=(
        '【产品身份最终裁决】第1张上传产品图是本次生成商品的唯一外观真值。它优先决定商品品类、轮廓、比例、材质、颜色/花型、结构、件数和配件；'
        '报告中采集商品的标题、参数、视觉分析以及第2张采集参考图里的商品外观，只能作为业务任务或展示状态参考。若它们与第1张产品图冲突，以第1张产品图为准；'
        '除非用户明确提出商品修改，不得把第2张图的蓝色/花型/颜色/材质/结构等外观带入结果。'
        if uploaded_identity else ''
    )
    reference_input_rule=(
        '【双参考输入顺序｜职责不可互换】第1张输入图是用户上传产品图，只读取商品身份、轮廓、比例、材质、颜色/花型、结构、件数和配件；第2张输入图是采集商品当前槽位图，只读取拍摄与产品展示状态。'
        '生成结果必须先锁定第1张产品图的商品，再把这个商品放入第2张采集参考图的视角、构图、朝向、展开/折叠、摆放、支撑、遮挡和部件关系；第2张图中的商品外观、颜色、花型、材质和结构不得覆盖第1张产品图；严禁让产品图决定本图视角。'
        if uploaded_identity else
        '【参考输入职责】当前请求中的参考图只按上面的参考策略使用；未被明确授权的参考图视觉状态不得覆盖当前槽位规则。'
    )
    business_goal, product_goal = _reference_shooting_goals(
        report, plan, slot, lock,
        uploaded_product_identity=uploaded_identity,
    )
    shooting_guidance = build_reference_shooting_guidance(
        enabled=shooting_enabled,
        asset_type=asset_type,
        reference_mode=product_reference_mode,
        business_goal=business_goal,
        product_goal=product_goal,
        slot_index=slot.get('index'),
    )
    reference_binding=slot.get('referenceBinding')
    reference_evidence_id=str(slot.get('referenceEvidenceId') or '').strip()
    reference_image_index=slot.get('referenceImageIndex')
    if reference_binding=='uploaded_identity_collected_slot':
        display_evidence_id=str(slot.get('displayReferenceEvidenceId') or reference_evidence_id).strip()
        display_index=slot.get('displayReferenceImageIndex')
        display_source=(f'采集商品对应槽位图（证据图片 {display_evidence_id}）' if display_evidence_id
                        else f'采集商品对应槽位图（第{display_index}张）' if display_index
                        else '采集商品对应槽位图')
        identity_index=slot.get('identityReferenceImageIndex') or 1
        reference_binding_rule=(
            f'【当前槽位双参考绑定】展示状态母版={display_source}；商品身份母版=用户上传产品图第{identity_index}张。'
            '前者只决定视角/机位/构图/摆放状态，后者只决定产品外观/材质/颜色/结构；不得交换。'
        )
    elif reference_binding in ('slot_evidence_reference','slot_indexed_reference','collected_group_fallback','collected_index_fallback') and (reference_evidence_id or reference_image_index):
        reference_binding_rule=f'【当前槽位参考图绑定】本图只使用证据图片 {reference_evidence_id} 作为拍摄与产品展示状态母版，不混用其他主图或详情图。'
        if not reference_evidence_id:
            reference_binding_rule=f'【当前槽位参考图绑定】本图只使用采集商品第{reference_image_index}张图片作为拍摄与产品展示状态母版，不混用其他主图或详情图。'
    elif reference_binding in ('slot_uploaded_reference','primary_uploaded_reference','uploaded_identity_only') and reference_image_index:
        reference_binding_rule=f'【当前槽位参考图绑定】本图只使用上传参考图第{reference_image_index}张作为拍摄与产品展示状态母版，不混用其他上传图片。'
    elif reference_binding=='generated_fission_base':
        reference_binding_rule='【当前槽位参考图绑定】本图只使用上一张已生成的裂变基准图作为拍摄与产品展示状态母版。'
    else:
        reference_binding_rule='【当前槽位参考图绑定】本图使用当前请求中的主参考图作为拍摄与产品展示状态母版。'
    shooting_priority = '参考图拍摄语言与产品展示状态（仅视觉表达）' if shooting_enabled else '当前槽位默认拍摄方案'
    identity_basis_rule=(
        '【产品图与采集参考图是两个不同条件】第1张输入图（产品图）是本次生成商品的唯一外观真值；第2张输入图（采集参考图）只提供本槽位的展示状态。先保留第1张图的商品，再迁移第2张图的展示方式。'
        if uploaded_identity else
        '每张图默认以随请求提供的参考图为起始外观基准；用户最终商品设定可以覆盖对应字段，未指定的字段继续保持同一商品设定。'
    )
    product_context_rule=(
        '报告商品文字上下文仅用于类目、业务目标和证据任务；不要把报告采集商品的视觉外观当作当前商品外观。当前商品外观只认第1张上传产品图。'
        if uploaded_identity else
        '报告商品文字上下文和参考图共同提供当前商品的默认身份；用户最终商品设定可以覆盖对应字段。'
    )
    product_style_rule=(
        '【产品身份与拍摄表达分离】第1张上传产品图只确定商品外观、颜色/花型、材质纹理和结构细节，不用它的背景、机位、光线或摆放状态覆盖对应采集参考图。开启参考一致时，整体拍摄表达和文字版式由对应采集参考图确定。'
        if uploaded_identity else ''
    )
    final_priority_rule=(
        '【最终执行优先级】平台合规 ＞ 对应参考图的产品展示状态及文案排版 ＞ 当前产品身份与用户明确商品设定 ＞ 方案与业务任务 ＞ 默认构图和风格。用第1张图的产品复现第2张图的展示状态，文案依据当前产品分析生成；其他创作要求不得改变展示状态或文字版式。'
        if uploaded_identity else
        '【最终身份优先级】平台合规 ＞ 用户明确商品设定/统一身份锁 ＞ 产品目标与新品方案约束 ＞ 当前槽位业务目标 ＞ '+('参考图拍摄语言与产品展示状态（仅视觉表达）' if shooting_enabled else '当前槽位默认拍摄方案')+' ＞ 默认构图。'
    )
    category_rule=(
        '类目由第1张上传产品图识别；报告类目仅用于选择电商表达方式，不得改变产品外观。'
        if uploaded_identity else
        f'类目：{category}；目标人群/场景：{audience or "以采集到的商品页面与推荐方案为准"}。'
    )
    relation_rule=''
    if 'resolvedBySlot' in user_direction:
        updates=user_direction.get('productUpdates') or []
        relation=user_direction.get('slotResolution') or user_direction['resolvedBySlot'].get(f"{asset_type}:{slot.get('index')}") or {}
        default_plan=json.dumps({k:v for k,v in plan.items() if k not in ('name','sourceType')},ensure_ascii=False)
        if plan_name:default_plan=default_plan.replace(plan_name,'')
        relation_rule=(
            '【统一产品—方案—参考关系｜本图执行依据】'
            +json.dumps({'defaultPlan':json.loads(default_plan),'explicitProductUpdates':updates,'thisImage':relation},ensure_ascii=False)
        )
        relation_rule+=(
            '。方案默认生效，仅按用户明确要求和必然关联关系调整，不自动清空、重策划或补造新品资料。'
            '本图主题、展示和文案按上述统一关系执行，不能再被旧品专属参数、固定槽位或通用模板改回去。'
            '未受影响的方案方向继续保留；跨品类沿用适用表达方向，不把旧品专属参数当成新品事实。'
        )
        category_updates=[u['value'] for u in updates if u['field']=='category']
        if category_updates:
            category_rule=f"当前品类以用户要求为准：{'；'.join(category_updates)}；报告与上传图的旧品类仅提供默认方案背景，不能覆盖新品类。"
        if updates:
            identity_basis_rule='【当前商品身份】上传产品图提供默认商品依据；用户明确产品更新及其必然关联变化覆盖对应字段。整套图保持更新后的同一商品，禁止同时复现已被替换的旧身份。'
            product_context_rule='报告产品信息作为方案默认背景，按统一产品更新关系使用；未受影响且适用的内容保留，被替换的旧品专属信息不能当成当前产品事实。'
            product_style_rule='商品外观以默认产品图结合用户明确产品更新为准；对应采集图提供展示和排版关系，跨品类按本图统一关系适配。'
            product_name='当前商品文字与品类上下文按统一产品更新关系执行，不沿用冲突的旧品描述。'
            hybrid_identity_rule='【商品更新边界】用户明确商品更新覆盖默认身份的对应字段及必然关联内容；其余适用字段保留。采集参考图不能自行改变商品身份。'
            reference_input_rule='【输入职责】产品图是默认身份依据；对应采集图是本图展示与排版依据。结合明确产品更新执行，输入顺序不变，不得把已替换的旧品类强加给新品。'
        slot_rule=f"本套图中的第{slot.get('index')}个{asset_type}位，主题、展示与文案按统一关系执行：{json.dumps(relation,ensure_ascii=False)}。"
        proof=relation.get('theme') or proof
        plan_rule='方案默认产品与页面方向继续保留；仅根据统一判断适配用户明确要求及必然关联变化，不把方案标签印成产品文案。'
        shooting_guidance=(
            f"【参考图拍摄与产品展示状态一致｜{'已勾选' if shooting_enabled else '未勾选'}｜matchReferenceShooting={'true' if shooting_enabled else 'false'}】"
            +('对应采集图为本图展示与排版母版；保持适用的机位、构图、背景、光线、主体占比、动作、朝向、折叠/展开、接触点、遮挡与文字位置、大小、层级、对齐、行距及留白。跨品类按统一关系适配展示意图；只有用户明确改变的项可以覆盖，其余不变。' if shooting_enabled else '按方案及本图统一判断设计展示，不默认复制采集图的拍摄状态。')
            +'当前产品身份由默认产品依据结合用户明确更新确定；文案随品类、产品、人群、场景、卖点及用户要求联动，参考原文不作为新品参数。'
            +' English constraints: Follow the resolved product, plan and per-image relationship. Explicit user changes override only affected defaults and necessary dependencies. Preserve compatible reference display and typography when matching is enabled. Adapt across categories without importing obsolete product facts. Render Chinese copy for the updated product, not the old product.'
        )
        benchmark_rule='对应参考图的借鉴和适配仅按统一关系执行，其他爆款或默认槽位不得改写本图主题。'
        composition=relation.get('display') or composition
        reference_text_rule=(f'对应参考图原始文字观察：{reference_text_info}；完整图片分析：{analysis_context}。'
                             f"本图文案执行：{relation.get('copy')}。生成并真实绘制当前产品中文文案；用户明确指定标题原文时按要求执行，其他输入作为指令而非逐字印刷。不要虚构参数或沿用不适用的旧品事实。")
        final_priority_rule='【统一执行规则】平台合规始终有效；所选方案为默认底座；用户明确要求仅覆盖对应字段及必然关联内容；参考一致开启时保留对应图适用的展示与文字版式，除非用户明确要求改变该项；默认槽位与风格不能覆盖以上关系。'
    facts_label='方案默认商品信息（按统一关系适配，不视为新品自动确认参数）：' if relation_rule else '报告采集商品的文字事实（仅作非视觉业务参考）：' if product_reference_mode=='uploaded_identity_collected_reference' else '已确认产品事实：'
    identity_tail=('未受影响且适用的字段继续保持默认依据；参考展示与排版按本图统一关系执行，用户明确改变的项及跨品类必然适配不能被旧默认约束覆盖。'
                   if relation_rule else '用户未明确修改的商品字段继续遵循产品图（混合模式）或当前参考身份基准。勾选参考一致时，采集商品对应槽位图锁定拍摄语言与产品展示/动作/摆放状态，上传图只锁定商品身份，不得覆盖产品、业务或槽位展示约束。')
    base_prompt=f'''为中国电商平台生成第{variant_index+1}版{asset_type}图片。{goal}。
【统一产品身份锁｜{lock['id']}】
本任务必须与同一套图片保持产品完全一致。{facts_label}{'；'.join(lock['verifiedFacts']) or '以当前商品参考为准'}。
必须保持：{'、'.join(lock['mustKeep'])}。禁止改变：{'、'.join(lock['mustNotChange'])}。
{identity_basis_rule}
{product_context_rule}
{product_style_rule}
{product_name}
{reference_rule}
{hybrid_identity_rule}
{reference_input_rule}
{reference_binding_rule}
{shooting_guidance}
{user_rule}
{product_rule}
{rejected_rule}
{ignored_rule}
{plan_rule}
{benchmark_rule}
{slot_rule}
{display_relationship_guidance}
{category_rule}
{relation_rule}
报告默认页面信息（仅对未被用户明确修改的字段生效，不得覆盖用户最终商品设定）：{'; '.join(params) or '以商品外观为准'}。
{f"用户最终商品设定已覆盖对应默认字段：{'；'.join(product_overrides)}。" if product_overrides else ''}
视觉信号/证明任务：{proof}。
视觉参考：{'；'.join(style) or '克制、真实、质感清晰'}。
构图要求：{composition}。本图尺寸比例：{size}。如果画面出现商品局部、套件、包装或场景，必须与用户最终指定的商品设定相互对应，不得擅自引入用户未要求的其他商品变化。
参考图文字承接：{reference_text_rule}
{final_priority_rule}；{identity_tail}
硬性禁止：不要出现任何品牌或商标字样、专利、授权、认证、奖项、价格、销量、促销、物流、客服、售后、二维码或防伪信息；不要生成水印、乱码或英文占位字；不使用竞品元素；不裁切商品主体；不要擅自增加用户未要求的额外商品变化；用户明确要求的材质、颜色、结构、件数、尺寸、规格、花型、款式或功能变化必须执行；图片内是否出现文案及文案区域遵循“参考图文案跟随规则”。
'''
    if 'resolvedBySlot' in user_direction:
        # One authoritative instruction surface: observations and suggestions
        # remain data, rather than competing imperative template paragraphs.
        key=f"{asset_type}:{slot.get('index')}"
        original_input={'global':user_direction.get('raw') or '',
                        'thisImage':(user_direction.get('perImageInput') or {}).get(key) or '',
                        'otherImageInputs':{k:v for k,v in (user_direction.get('perImageInput') or {}).items() if k!=key}}
        base_prompt=f'''为中国电商平台生成{key}图片，尺寸{size}。
【统一执行规则｜统一产品—方案—参考关系】平台安全与合规始终有效。当前产品身份不可擅自改变；用户明确授权换产品或品类时先更新身份，整套保持更新后的同一商品。其后遵守本图用户要求，再使用适用的对应参考约束，最后以所选方案补充未指定内容。通用建议不能覆盖用户要求。
【当前产品身份边界】{identity_basis_rule}
{category_rule}
明确产品更新：{json.dumps(user_direction.get('productUpdates') or [],ensure_ascii=False)}。
上传产品图是默认身份依据，参考图不能自行替换商品。背景、文案、排版、镜头要求不得擅自改变产品。若解析更新不完整，依据下方用户原文理解明确修改，不把解析缺项当成用户未提出要求。
【本图用户完整输入｜执行指令】{json.dumps(original_input,ensure_ascii=False)}
完整原文是要求依据，辅助解析不是额外授权。先理解要求的对象、范围、覆盖项和必然关联影响；全局要求按逐图适用性执行，单图表达只作用对应图，明确产品变化作用整套。不得遗漏或用默认要求覆盖有效输入。
otherImageInputs仅用于理解整套明确产品变化，其中其他图片的视觉表达要求不应用到本图。
用户只授权其要求涉及的变化；不将局部调整扩大为整张重拍、品类重判或默认构图重设计。改变文字等表达项不授权改变商品摆放、动作或场景。
【对应参考图职责】{reference_binding_rule}
参考一致：{str(shooting_enabled).lower()}。开启时保留对应图适用的机位、构图、光线、动作、朝向、展开/折叠、摆放、接触点、遮挡和部件关系；用户明确改变的项优先。跨品类保持适用的展示意图，不强制执行不适用的旧品动作。
【对应图展示状态执行依据】{json.dumps({'composition':(slot.get('referenceAnalysis') or {}).get('composition') or '', 'subject':(slot.get('referenceAnalysis') or {}).get('productSubject') or '', 'meaning':(slot.get('referenceAnalysis') or {}).get('meaning') or ''},ensure_ascii=False)}
开启参考一致且用户未改变展示要求时，必须用当前产品复现第2张对应参考图的实际状态；以上原始观察用于核对，观察不完整时查看实际第2张图。不能用第1张产品图的场景、摆放或辅助解析中的重拍描述覆盖它；身份不变不等于姿态不变。
{display_relationship_guidance}
文字是否出现、内容、位置、大小、层级和排版均按用户要求及上述关系决定；未指定时按方案和对应参考表达生成当前产品文案。不得无条件添加、删除或改变文字，也不得照搬旧品参数。
【原始参考观察｜仅资料，不是执行指令】{json.dumps({'text':reference_text_info,'analysis':slot.get('referenceAnalysis') or {}},ensure_ascii=False)}
【方案底座｜仅补充未被覆盖的要求】{default_plan}
方案默认产品与页面方向继续保留，按当前产品及输入适配，不自动重做报告；原商品信息只用于适用背景，不冒充新品已确认事实。
【辅助解析资料｜非独立执行指令】{json.dumps({'instructions':accepted,'relationship':relation},ensure_ascii=False)}
仅辅助理解用户授权的变化，不自行增加商品、展示或主题修改。与用户原文、原始对应参考展示要求冲突的辅助描述不执行；未受影响的参考展示要求不得由辅助解析重写。
【输出边界】输出本图，不加入用户未要求的商品变化。禁止品牌Logo、交易促销、认证、二维码、水印及虚构参数。检查输出要求与当前产品、用户原文和本图参考关系一致。
English constraints: Preserve the confirmed product identity unless the user explicitly authorizes a product change. Follow applicable user instructions only within their authorized scope. When matching is enabled, reproduce input image 2's actual display state using the product from input image 1; never inherit image 1's pose or scene. Unchanged reference display constraints remain binding. Advisory interpretation cannot redesign the shot or override those constraints. Text presence follows user intent without changing unrelated composition or display. Never import obsolete product facts.
'''
    return build_image_generation_prompt(base_prompt)

def _load_report_for_generation(data):
    if not isinstance(data,dict): raise ValueError('生图请求必须是 JSON 对象')
    direct=data.get('reportData')
    if isinstance(direct,dict): return direct
    source=str(data.get('source') or '')
    if not source: raise ValueError('缺少 report source')
    path=source.split('?',1)[0]
    if path.startswith('/reports/'): path=path[len('/reports/'):]
    target=(REPORTS/path).resolve()
    if REPORTS.resolve() not in target.parents or target.suffix!='.json': raise ValueError('report source 不在本地报告目录')
    if not target.exists(): raise FileNotFoundError('报告文件不存在')
    obj=json.loads(target.read_text('utf-8'))
    if not isinstance(obj,dict): raise ValueError('报告数据格式错误')
    return obj

def _persist_image_job(job_id, state):
    """Checkpoint image work after every asset so a restart never hides returned images."""
    payload=dict(state or {})
    if isinstance(payload.get('results'),list):
        payload['results']=_ordered_generated_results(payload['results'])
    payload['jobId']=job_id
    (REPORTS/f'generated_{job_id}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),'utf-8')

def _generation_intent_fingerprint(report, plan, slots, request, references):
    """Bind a reusable interpretation to the exact product, plan and inputs."""
    payload={
        'product':(report.get('facts') or {}).get('product'),
        'attributes':(report.get('facts') or {}).get('attributes'),
        'plan':plan,
        'slots':[{'assetType':s.get('assetType'),'index':s.get('index'),
                  'task':s.get('task'),'referenceAnalysis':s.get('referenceAnalysis')} for s in slots],
        'userDirection':request.get('userDirection'),
        'promptOverrides':request.get('promptOverrides'),
        'matchReferenceShooting':_match_reference_shooting(request,False),
        'referenceHashes':[hashlib.sha256(str(ref).encode('utf-8')).hexdigest() for ref in references],
    }
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode('utf-8')).hexdigest()

def save_generation_reference(data_url):
    """Store one validated local product reference before job submission."""
    value=str(data_url or '')
    match=re.fullmatch(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)',value)
    if not match:
        raise ValueError('仅支持 PNG、JPEG 或 WebP 参考图')
    mime,encoded=match.groups()
    try:
        binary=base64.b64decode(encoded,validate=True)
    except Exception as error:
        raise ValueError('参考图数据无效') from error
    signatures={
        'image/png':binary.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/jpeg':binary.startswith(b'\xff\xd8\xff'),
        'image/webp':binary[:4]==b'RIFF' and binary[8:12]==b'WEBP',
    }
    if not signatures[mime] or not binary or len(binary)>9*1024*1024:
        raise ValueError('参考图格式无效或超过 9MB')
    suffix={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[mime]
    folder=IMAGE_ASSET_ROOT/'reference_uploads'
    folder.mkdir(parents=True,exist_ok=True)
    name=uuid.uuid4().hex+suffix
    (folder/name).write_bytes(binary)
    return f'/reports/assets/reference_uploads/{name}'

def image_generation_setup(report, plan_index=0, reference_images=None, match_reference_shooting=False, fission_pattern=None):
    exp=report.get('experienceSolution') or {}
    plans=(exp.get('newProductPlans') or {}).get('plans') or (report.get('launchPlans') or {}).get('plans') or []
    index=int(plan_index)
    if not plans or index<0 or index>=len(plans):
        raise ValueError('方案索引无效')
    plan=plans[index]
    try:
        refs,reference_source=resolve_reference_images(report,plan,reference_images)
    except ValueError as error:
        # Setup is a read-only preview step. It must still render the slots
        # when the report has no product image; final submission keeps the
        # strict reference validation.
        if '没有可用的商品主图' not in str(error):
            raise
        refs,reference_source=[], 'none'
    fission=bool(reference_source!='uploaded' if fission_pattern is None else fission_pattern) and reference_source!='uploaded' and not _coerce_bool(match_reference_shooting,False)
    slots=[]
    # Prompt preview is deterministic local assembly; it does not invoke the
    # AI intent parser.  This lets the editing UI show the exact default
    # prompt before the user confirms generation.
    preview_direction={}
    preview_identity=build_identity_lock(
        report,plan,preview_direction,
        uploaded_product_identity=reference_source=='uploaded',
    )
    for slot in build_generation_slots(report,plan):
        mode=image_reference_mode(reference_source,fission,slot,_coerce_bool(match_reference_shooting,False))
        _,reference_meta=_slot_reference_images(report,slot,refs,reference_source,mode,_coerce_bool(match_reference_shooting,False))
        annotated=dict(slot); annotated.update(reference_meta)
        annotated['prompt']=build_image_prompt(
            report,plan,slot.get('assetType','main'),int(slot.get('index',1))-1,
            annotated,preview_direction.get(f"{slot.get('assetType')}:{slot.get('index')}"),
            mode,preview_identity,_coerce_bool(match_reference_shooting,False),
        )
        slots.append(annotated)
    return {'ok':True,'slots':slots,'creditPricingAvailable':False,'referenceSource':reference_source,'referenceCount':len(refs),'matchReferenceShooting':_coerce_bool(match_reference_shooting,False)}

def _load_image_job(job_id):
    """Read an image job from memory first, then fall back to its checkpoint."""
    job_id=str(job_id or '').strip()
    if not re.fullmatch(r'img_[A-Za-z0-9_-]+',job_id):
        return None
    job=IMAGE_JOBS.get(job_id)
    if isinstance(job,dict):
        return dict(job)
    saved=REPORTS/f'generated_{job_id}.json'
    if not saved.exists():
        return None
    try:
        job=json.loads(saved.read_text('utf-8'))
    except Exception:
        return None
    return dict(job) if isinstance(job,dict) else None

def _revision_job_chain(parent_job):
    """Return the selected parent followed by its persisted ancestors."""
    chain=[]; seen=set(); current=parent_job if isinstance(parent_job,dict) else None
    while current and str(current.get('jobId') or '') not in seen:
        chain.append(current)
        job_id=str(current.get('jobId') or '')
        if job_id: seen.add(job_id)
        ancestor_id=str(current.get('revisionOfJobId') or '').strip()
        if not ancestor_id or ancestor_id in seen: break
        current=_load_image_job(ancestor_id)
    return chain

def _revision_job_value(chain, key, default=None):
    for job in chain:
        if key in job and job.get(key) is not None:
            return job.get(key)
    return default

def _revision_reference_images(parent_job):
    """Recover original product references without mixing in display refs."""
    chain=_revision_job_chain(parent_job)
    for job in chain:
        refs=job.get('referenceImages')
        if isinstance(refs,list) and any(str(item or '').strip() for item in refs):
            return list(dict.fromkeys(str(item).strip() for item in refs if str(item or '').strip()))[:4]
    recovered=[]
    for job in chain:
        results=[item for item in (job.get('results') or []) if isinstance(item,dict)]
        uploaded_mode=(
            str(job.get('referenceSource') or '')=='uploaded' or
            any(str(item.get('referenceBinding') or '').startswith(('uploaded_','primary_uploaded_','slot_uploaded_')) for item in results)
        )
        if not uploaded_mode: continue
        for item in results:
            value=str(item.get('identityReferenceUrl') or '').strip()
            if value.startswith(('data:image/','http://','https://','/reports/assets/reference_uploads/')) and value not in recovered:
                recovered.append(value)
    return recovered[:4]

def _revision_fission_base(parent_job, parent_result):
    """Load the original round's generated identity base for a follow-up slot."""
    if _result_task_key(parent_result)=='main:1': return ''
    chain=_revision_job_chain(parent_job)
    round_id=str(_revision_job_value(chain,'generationRoundId','') or '').strip()
    if round_id and all(str(job.get('jobId') or '')!=round_id for job in chain):
        root=_load_image_job(round_id)
        if root: chain.append(root)
    for job in reversed(chain):
        if not bool(job.get('fissionPattern',False)): continue
        candidates=[item for item in (job.get('results') or []) if isinstance(item,dict) and _result_task_key(item)=='main:1']
        candidates.sort(key=lambda item:_result_revision_number(item))
        for item in candidates:
            data_url=_generated_item_data_url(item)
            if data_url: return data_url
    return ''

def _generated_item_path(job_id, item):
    """Resolve one persisted result without allowing paths outside its job folder."""
    root=(GENERATED_ASSET_ROOT/str(job_id)).resolve()
    candidate=Path(str((item or {}).get('_path') or '')).resolve()
    if candidate.exists() and root in candidate.parents and candidate.is_file():
        return candidate
    url=str((item or {}).get('url') or '')
    prefix=f'/reports/assets/generated/{job_id}/'
    if url.startswith(prefix):
        name=Path(unquote_to_bytes(url[len(prefix):]).decode('utf-8','ignore')).name
        fallback=(root/name).resolve()
        if fallback.exists() and root in fallback.parents and fallback.is_file():
            return fallback
    return None

def _image_job_archive(job_id):
    """Return a ZIP containing the generated images and a portable task manifest."""
    job=_load_image_job(job_id)
    if not job:
        raise FileNotFoundError('image job not found')
    results=[]
    files=[]
    for item in job.get('results') or []:
        if not isinstance(item,dict):
            continue
        path=_generated_item_path(job_id,item)
        if not path:
            continue
        asset_type='detail' if item.get('assetType')=='detail' else 'main'
        try:
            slot_index=int(item.get('slotIndex') or 0)
        except Exception:
            slot_index=0
        is_comparison=bool(job.get('comparisonMode') or len(job.get('comparisonModels') or [])>1)
        if is_comparison:
            model_part=re.sub(r'[^A-Za-z0-9._-]+','_',str(item.get('modelLabel') or item.get('model') or 'model'))
            archive_name=f'images/{model_part}-{asset_type}-{slot_index:02d}{path.suffix.lower() or ".png"}'
        else:
            archive_name=f'images/{asset_type}-{slot_index:02d}{path.suffix.lower() or ".png"}'
        files.append((path,archive_name))
        results.append({key:value for key,value in item.items() if key!='_path'} | {'downloadFile':archive_name})
    if not files:
        raise ValueError('该任务还没有可下载的图片')
    manifest=dict(job)
    manifest['results']=results
    manifest['downloadFiles']=[name for _,name in files]
    manifest.pop('_path',None)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for path,name in files:
            archive.write(path,name)
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return buffer.getvalue()

def _generation_worker(job_id, report, request):
    try:
        exp=report.get('experienceSolution') or {}; plans=(exp.get('newProductPlans') or {}).get('plans') or report.get('launchPlans',{}).get('plans') or []
        plan=plans[int(request.get('planIndex',0))] if plans and 0<=int(request.get('planIndex',0))<len(plans) else (plans[0] if plans else {})
        model_specs=_image_model_specs(request)
        comparison_mode=len(model_specs)>1
        match_reference_shooting=_match_reference_shooting(request, False)
        reference_images,reference_source=resolve_reference_images(report,plan,request.get('referenceImages'))
        # A fission base is a newly generated image, so it cannot be the
        # original reference's display-state master. Matching mode therefore
        # uses the original per-slot references directly.
        fission_pattern=bool(request.get('fissionPattern', reference_source!='uploaded')) and reference_source!='uploaded' and not match_reference_shooting and not comparison_mode
        prompt_overrides=request.get('promptOverrides') if isinstance(request.get('promptOverrides'),dict) else {}
        blocked_terms=_report_visual_identity_terms(report)
        user_direction=_image_user_direction(request.get('userDirection'),blocked_terms)
        user_direction=_apply_product_overrides(
            user_direction,
            _collect_prompt_product_overrides(prompt_overrides,blocked_terms),
        )
        slots=build_generation_slots(report,plan)
        intent_fingerprint=_generation_intent_fingerprint(report,plan,slots,request,reference_images)
        previous=_load_image_job(request.get('reuseAnalysisJobId')) if request.get('reuseAnalysisJobId') else None
        if previous and previous.get('analysisInputHash')==intent_fingerprint and isinstance(previous.get('resolvedUserDirection'),dict):
            user_direction=previous['resolvedUserDirection']
        else:
            IMAGE_JOBS[job_id].update(status='preparing',progress=10)
            _persist_image_job(job_id,IMAGE_JOBS[job_id])
            user_direction=_resolve_image_user_intent(report,plan,slots,user_direction,prompt_overrides,reference_images,match_reference_shooting)
        IMAGE_JOBS[job_id].update(analysisInputHash=intent_fingerprint,resolvedUserDirection=user_direction)
        _persist_image_job(job_id,IMAGE_JOBS[job_id])
        identity_lock=build_identity_lock(
            report,plan,user_direction,
            uploaded_product_identity=reference_source=='uploaded',
        )
        types=request.get('assetTypes') or ['main','detail']; types=[x for x in types if x in ('main','detail')][:2] or ['main','detail']
        complete_set=bool(request.get('completeSet',True))
        selected_keys={str(x) for x in request.get('selectedSlots',[]) if isinstance(x,(str,int))}
        if complete_set:
            selected_slots=[slot for slot in slots if slot['assetType'] in types and (not selected_keys or f"{slot['assetType']}:{slot['index']}" in selected_keys)]
        else:
            try: count=max(1,min(6,int(request.get('count',1))))
            except Exception: count=1
            selected_slots=[{'assetType':asset_type,'index':i+1} for asset_type in types for i in range(count)][:12]
        inherited_fission_base=str(request.get('fissionBaseReference') or '').strip()
        if fission_pattern and not inherited_fission_base and not any(slot.get('assetType')=='main' and slot.get('index')==1 for slot in selected_slots):
            base_slot=next((slot for slot in slots if slot.get('assetType')=='main' and slot.get('index')==1), None)
            if base_slot:
                selected_slots=[base_slot]+selected_slots
        if not selected_slots: raise ValueError('请至少选择一张要生成的图片')
        root=GENERATED_ASSET_ROOT/job_id; root.mkdir(parents=True,exist_ok=True); results=[]; failed_slots=[]
        total=len(selected_slots)*len(model_specs); done=0
        user_direction_by_slot={
          f"{slot.get('assetType')}:{slot.get('index')}":_user_direction_for_slot(user_direction,slot)
          for slot in selected_slots
        }
        comparison_models=[
            {'id':spec.get('id') or '', 'label':spec.get('label') or spec.get('id') or '默认生图模型',
             'quality':normalize_image_quality(spec.get('quality')),
             'modelKey':_image_model_key(spec.get('id') or 'default')}
            for spec in model_specs
        ]
        slot_reference_map={}
        for slot in selected_slots:
            prompt_key=f"{slot.get('assetType')}:{slot.get('index')}"
            reference_mode=image_reference_mode(reference_source,fission_pattern,slot,match_reference_shooting)
            _,reference_meta=_slot_reference_images(report,slot,reference_images,reference_source,reference_mode,match_reference_shooting)
            slot_reference_map[prompt_key]={key:value for key,value in reference_meta.items() if key.endswith('Url') or key.endswith('Id') or key.endswith('Index') or key in ('referenceBinding','displayReferenceBinding')}
        revision_number=max(1,int(request.get('revisionNumber') or 1))
        revision_of_job_id=str(request.get('revisionOfJobId') or '')
        parent_result_id=str(request.get('parentResultId') or '')
        revision_reason=str(request.get('revisionReason') or '').strip()
        reuse_prompt=str(request.get('reusePrompt') or '').strip()
        generation_round_id=str(request.get('generationRoundId') or request.get('roundId') or '').strip()
        if not generation_round_id:
            generation_round_id=str(request.get('rootGenerationJobId') or revision_of_job_id or job_id)
        round_type='revision' if revision_of_job_id else 'initial'
        root_result_ids=request.get('rootResultIds') if isinstance(request.get('rootResultIds'),dict) else {}
        for slot in selected_slots:
            key=f"{slot.get('assetType')}:{slot.get('index')}"
            root_result_ids.setdefault(key, f"root_{uuid.uuid4().hex[:12]}")
        state=IMAGE_JOBS.setdefault(job_id,{})
        state.update({'jobId':job_id,'status':'generating','progress':20,'results':results,
                      'planName':plan.get('name') or '未命名开品方案','productName':identity_lock.get('productName') or '商品',
                      'referenceRoleVersion':REFERENCE_ROLE_VERSION,
                      'reportSource':str(request.get('source') or ''),'planIndex':int(request.get('planIndex',0) or 0),
                      'assetTypes':types,'completeSet':complete_set,
                      'expectedSlots':selected_slots,'referenceSource':reference_source,'referenceCount':len(reference_images),
                      'referenceImages':list(request.get('referenceImages') or []) if isinstance(request.get('referenceImages'),list) else [],
                      'slotReferences':slot_reference_map,
                      'userDirection':user_direction,'userDirectionBySlot':user_direction_by_slot,
                      'analysisInputHash':intent_fingerprint,'resolvedUserDirection':user_direction,
                      'comparisonMode':comparison_mode,'comparisonModels':comparison_models,
                      'selectedImageModels':[item['id'] for item in comparison_models],
                      'fissionPattern':fission_pattern,
                      'matchReferenceShooting':match_reference_shooting,
                      'referenceShootingPolicy':'match_reference' if match_reference_shooting else 'identity_only',
                      'promptOverrides':prompt_overrides,'revisionNumber':revision_number,
                      'revisionOfJobId':revision_of_job_id,'parentResultId':parent_result_id,
                      'revisionReason':revision_reason,'rootResultIds':root_result_ids,
                      'generationRoundId':generation_round_id,'roundType':round_type})
        _persist_image_job(job_id,state)
        result_lock=threading.Lock()
        def generate_slot(order_slot, refs, reference_mode, model_spec, persist_index):
            order,slot=order_slot
            asset_type=slot['assetType']; i=slot.get('index',order+1)-1
            prompt_key=f"{asset_type}:{slot.get('index')}"
            slot_direction=user_direction_by_slot.get(prompt_key) or _user_direction_for_slot(user_direction,slot)
            slot_refs,reference_meta=_slot_reference_images(
                report,slot,refs,reference_source,reference_mode,match_reference_shooting,
            )
            if revision_of_job_id and reference_source=='uploaded' and match_reference_shooting:
                # A revision must keep the confirmed prompt and product identity
                # stable. The collected image remains prompt/display metadata,
                # but sending it as a second product image lets providers copy
                # its merchandise despite the role instructions.
                slot_refs=slot_refs[:1]
                reference_meta['displayReferenceTransport']='prompt_only'
            prompt_slot=dict(slot); prompt_slot.update(reference_meta)
            if reuse_prompt and revision_of_job_id and not revision_reason:
                prompt=reuse_prompt
                prompt_merge={'mode':'reused_confirmed_prompt','related':False,'matched':[],'ignored':[]}
            else:
                base_prompt=build_image_prompt(
                    report, plan, asset_type, i, prompt_slot, slot_direction, reference_mode,
                    identity_lock, match_reference_shooting,
                )
                prompt,prompt_merge=merge_image_prompt_with_user_edit(base_prompt,prompt_overrides.get(prompt_key),slot,slot_direction)
            # The first main image is the identity master, but matching mode
            # still needs its corresponding collected image as input 2; that
            # is the only way the provider can see the requested pose/layout.
            is_product_master=asset_type=='main' and slot.get('index')==1
            if is_product_master and reference_meta.get('referenceBinding')!='uploaded_identity_collected_slot':
                slot_refs=slot_refs[:1]
            if match_reference_shooting and reference_meta.get('displayReferenceBinding') in ('collected_group_fallback','collected_index_fallback'):
                raise ValueError('当前槽位缺少对应采集参考图，不能使用其他图片代替展示状态')
            if match_reference_shooting and not reference_meta.get('displayReferenceUrl'):
                raise ValueError('当前槽位缺少采集展示参考图，请补充对应图片')
            try:
                provider_refs=[_reference_data_url(ref) for ref in slot_refs]
            except Exception as error:
                raise ValueError(f'参考图读取失败，本槽位未发送生图请求：{error}') from error
            model_id=str(model_spec.get('id') or '').strip()
            model_label=str(model_spec.get('label') or model_id or '默认生图模型').strip()
            model_quality=normalize_image_quality(model_spec.get('quality'))
            response=image_generate(
                prompt,size='1024x1536' if asset_type=='detail' else '1024x1024',n=1,
                model=model_id or None,reference_images=provider_refs,quality=model_quality,
            )
            entries=response.get('data') if isinstance(response,dict) else None
            if not isinstance(entries,list) or not entries: raise ValueError('图片接口返回为空')
            # Providers/tests may return a reusable mapping; copy it before
            # adding per-slot metadata so parallel results never alias and
            # later slots cannot rewrite the product master record.
            saved=dict(_save_generated_item(entries[0],root,persist_index) or {})
            saved.update({'assetType':asset_type,'slotIndex':slot.get('index'),'slotRole':slot.get('role',''),'slotTask':slot.get('task',[]),'prompt':prompt,'planName':plan.get('name') or '',
                          'promptMerge':prompt_merge,'userDirection':slot_direction,
                          'model':model_id,'modelLabel':model_label,'quality':model_quality,
                          'modelKey':_image_model_key(model_id or 'default'),
                          'comparisonKey':f"{_image_model_key(model_id or 'default')}:{asset_type}:{slot.get('index')}",
                          'consistencyGroupId':identity_lock['id'],'identityLock':identity_lock,
                          'matchReferenceShooting':match_reference_shooting,
                          'referenceShootingPolicy':'match_reference' if match_reference_shooting else 'identity_only',
                          'referenceRole':(
                              'uploaded_identity_collected_display' if reference_meta.get('referenceBinding')=='uploaded_identity_collected_slot' else
                              'primary_product_master' if is_product_master else
                              'generated_product_base' if reference_mode=='fission_followup' else
                              'supporting_product_reference'
                          ),
                          **reference_meta,
                          'referenceCount':len(slot_refs),
                          'referenceCountUsed':len(slot_refs),
                          'taskKey':prompt_key,
                          'resultId':f"res_{uuid.uuid4().hex[:14]}",
                          'revisionNumber':revision_number,
                          'revisionOfJobId':revision_of_job_id,
                          'parentResultId':parent_result_id,
                          'rootResultId':root_result_ids.get(prompt_key),
                          'generationRoundId':generation_round_id,
                          'roundType':round_type})
            saved.update({
                'referenceAnalysis':slot.get('referenceAnalysis') or {},
            })
            return saved
        ordered_slots=list(enumerate(selected_slots))
        fission_item=next((item for item in ordered_slots if item[1].get('assetType')=='main' and item[1].get('index')==1), None) if fission_pattern and not inherited_fission_base else None
        followup_refs=[inherited_fission_base] if inherited_fission_base else reference_images
        if fission_item:
            # The fission base is always the first persisted asset.  When the
            # caller selected only detail slots we prepend the base above, but
            # the original enumerate index can still be zero for the first
            # detail item; passing an explicit zero here and reindexing the
            # remaining slots below prevents both assets from overwriting
            # ``01.png``.
            saved=generate_slot(
                (0,fission_item[1]),reference_images,
                image_reference_mode(reference_source,True,fission_item[1],False),
                model_specs[0],1,
            )
            results.append(saved); done+=1
            base_ref=_generated_item_data_url(saved) or saved.get('sourceUrl') or (reference_images[0] if reference_images else '')
            followup_refs=[base_ref] if base_ref else reference_images
            IMAGE_JOBS[job_id].update(progress=20+int(done/total*75),results=results,productBaseImage=saved.get('url'))
            _persist_image_job(job_id,IMAGE_JOBS[job_id])
            remaining_slots=[item[1] for item in ordered_slots if item[0]!=fission_item[0]]
            # Follow-up filenames start at 02.png and remain stable even when
            # the base was injected into a request that selected only details.
            ordered_slots=[(index,slot) for index,slot in enumerate(remaining_slots,start=1)]
        if fission_item:
            pairs=[(order,slot,model_specs[0],order+1) for order,slot in ordered_slots]
        else:
            pairs=[
                (order,slot,model_spec,model_index*len(selected_slots)+order+1)
                for model_index,model_spec in enumerate(model_specs)
                for order,slot in ordered_slots
            ]
        # Reference-guided image calls are large.  Bound concurrency across
        # the whole model-comparison grid so the upstream gateway is not hit
        # by every slot (and every retry) at the same instant.
        try:
            image_concurrency=max(1,min(5,int(load_config().get('image_concurrency',5))))
        except Exception:
            image_concurrency=5
        state['imageConcurrency']=image_concurrency
        with ThreadPoolExecutor(max_workers=min(image_concurrency,max(1,len(pairs)))) as image_pool:
            futures={
                image_pool.submit(
                    generate_slot,(order,slot),
                    followup_refs if (fission_item or inherited_fission_base) else reference_images,
                    image_reference_mode(reference_source,fission_pattern,slot,match_reference_shooting),
                    model_spec,persist_index,
                ):(slot,model_spec)
                for order,slot,model_spec,persist_index in pairs
            }
            for future in as_completed(futures):
                slot,model_spec=futures[future]
                with result_lock:
                    try:
                        results.append(future.result())
                    except Exception as slot_error:
                        failed_slots.append({
                            'assetType':slot.get('assetType'),
                            'slotIndex':slot.get('index'),
                            'slotRole':slot.get('role',''),
                            'model':str(model_spec.get('id') or ''),
                            'modelLabel':str(model_spec.get('label') or model_spec.get('id') or '默认生图模型'),
                            'quality':normalize_image_quality(model_spec.get('quality')),
                            'modelKey':_image_model_key(model_spec.get('id') or 'default'),
                            'error':str(slot_error),
                        })
                    done+=1; IMAGE_JOBS[job_id].update(
                        progress=20+int(done/total*75),results=results,failedSlots=failed_slots,
                    )
                    _persist_image_job(job_id,IMAGE_JOBS[job_id])
        if not results and failed_slots:
            raise RuntimeError(f"全部 {len(failed_slots)} 张图片生成失败：{failed_slots[0]['error']}")
        meta={'jobId':job_id,'status':'complete','progress':100,'results':_ordered_generated_results(results),'failedSlots':failed_slots,
              'partialFailure':bool(failed_slots),'planName':plan.get('name') or '未命名开品方案',
              'productName':identity_lock.get('productName') or '商品','reportSource':str(request.get('source') or ''),
              'planIndex':int(request.get('planIndex',0) or 0),
              'referenceRoleVersion':REFERENCE_ROLE_VERSION,
              'createdAt':IMAGE_JOBS.get(job_id,{}).get('createdAt') or time.time(),'completedAt':time.time(),
              'assetTypes':types,'completeSet':complete_set,'expectedSlots':selected_slots,'referenceSource':reference_source,'referenceCount':len(reference_images),
              'referenceImages':list(request.get('referenceImages') or []) if isinstance(request.get('referenceImages'),list) else [],
              'slotReferences':IMAGE_JOBS.get(job_id,{}).get('slotReferences',{}),
              'userDirection':user_direction,'userDirectionBySlot':user_direction_by_slot,
              'analysisInputHash':intent_fingerprint,'resolvedUserDirection':user_direction,
              'comparisonMode':comparison_mode,'comparisonModels':comparison_models,
              'selectedImageModels':[item['id'] for item in comparison_models],
              'imageConcurrency':state.get('imageConcurrency',5),
              'fissionPattern':fission_pattern,'consistencyGate':{
                'status':'needs_review','groupId':identity_lock['id'],
                'message':'主图与详情图共享同一产品身份锁；正式发布前需做商品结构、颜色、材质、规格与文案复核。',
                'checks':['product_identity_shared','plan_constraints_shared','platform_rules_embedded']
              }}
        meta.update({'promptOverrides':prompt_overrides,'revisionNumber':revision_number,
                     'revisionOfJobId':revision_of_job_id,'parentResultId':parent_result_id,
                     'revisionReason':revision_reason,'rootResultIds':root_result_ids,
                     'generationRoundId':generation_round_id,'roundType':round_type})
        meta['matchReferenceShooting']=match_reference_shooting
        meta['referenceShootingPolicy']='match_reference' if match_reference_shooting else 'identity_only'
        _persist_image_job(job_id,meta); IMAGE_JOBS[job_id]=meta
    except Exception as e:
        IMAGE_JOBS[job_id].update(status='error',progress=100,error=str(e),completedAt=time.time())
        try: _persist_image_job(job_id,IMAGE_JOBS[job_id])
        except Exception: pass

def jdump(o): return json.dumps(o,ensure_ascii=False).encode('utf-8')


def _norm_key(k): return re.sub(r'\s+','',str(k or '')).lower()
MONITOR_ALIASES={
 'date':['日期','采集日期','监测日期','统计日期','date','day','capturedate','capturedat','capturedAt'],
 'itemId':['商品id','itemid','item_id','id','商品链接','链接','url','商品url'],
 'sales':['销量展示值','销量展示','销量','销售量','salesdisplay','sales','sold','销量档位','已售'],
 'rank':['榜单排名','排名','rank','ranking','榜单','类目排名'],
 'price':['价格','当前价','当前价格','到手价','price','currentprice'],
 'promotion':['活动','促销','promotion','promotions','活动信息','优惠'],
 'title':['标题','商品标题','title','name','商品名称']
}
def _pick(row,name):
    m={_norm_key(k):v for k,v in (row or {}).items()}
    for a in MONITOR_ALIASES[name]:
        if _norm_key(a) in m:return m[_norm_key(a)]
    return ''
def _xlsx_rows(data):
    # 标准 xlsx 第一张工作表；纯标准库解析，用户本机无需安装 openpyxl。
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            ns={'a':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            for si in root.findall('a:si',ns): shared.append(''.join(t.text or '' for t in si.findall('.//a:t',ns)))
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rel=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        relmap={x.attrib.get('Id'):x.attrib.get('Target') for x in rel}
        ns={'a':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
        sh=wb.find('a:sheets/a:sheet',ns); rid=sh.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        target=relmap.get(rid,'worksheets/sheet1.xml').lstrip('/')
        if not target.startswith('xl/'): target='xl/'+target
        root=ET.fromstring(z.read(target))
        rows=[]
        for rr in root.findall('.//a:sheetData/a:row',ns):
            vals=[]
            for c in rr.findall('a:c',ns):
                t=c.attrib.get('t'); v=c.find('a:v',ns); val='' if v is None else (v.text or '')
                if t=='s' and val!='':
                    try: val=shared[int(val)]
                    except: pass
                elif t=='inlineStr':
                    val=''.join(x.text or '' for x in c.findall('.//a:t',ns))
                vals.append(val)
            rows.append(vals)
        if not rows:return []
        head=[str(x).strip() for x in rows[0]]
        return [{head[i]:(r[i] if i<len(r) else '') for i in range(len(head))} for r in rows[1:] if any(str(x).strip() for x in r)]
def parse_monitor_file(filename,data):
    ext=Path(filename).suffix.lower()
    if ext=='.json':
        obj=json.loads(data.decode('utf-8-sig')); rows=obj if isinstance(obj,list) else obj.get('data',[]) if isinstance(obj,dict) else []
    elif ext=='.csv':
        text=data.decode('utf-8-sig',errors='replace'); rows=list(csv.DictReader(io.StringIO(text)))
    elif ext in ('.xlsx','.xls'):
        if ext=='.xls': raise ValueError('旧版 .xls 暂不支持，请另存为 .xlsx 或 CSV')
        rows=_xlsx_rows(data)
    else: raise ValueError('仅支持 .xlsx / .csv / .json')
    return rows

def _norm_item_id(v):
    s=str(v or '').strip()
    if not s:return ''
    # URL / 普通数字 / Excel 科学计数法都尽量恢复为商品ID
    m=re.search(r'[?&]id=(\d+)',s)
    if m:return m.group(1)
    if re.fullmatch(r'\d+(?:\.0+)?',s): return s.split('.')[0]
    if re.fullmatch(r'\d+(?:\.\d+)?[eE][+-]?\d+',s):
        try:return str(int(float(s)))
        except:return s
    m=re.search(r'(?<!\d)(\d{8,})(?!\d)',s)
    return m.group(1) if m else s

def _norm_monitor_date(v):
    s=str(v or '').strip()
    if not s:return ''
    # Excel 日期序列号
    try:
        f=float(s)
        if 20000 <= f <= 80000:
            import datetime
            d=datetime.datetime(1899,12,30)+datetime.timedelta(days=f)
            return d.strftime('%Y-%m-%d')
    except: pass
    s=s.replace('/','-').replace('.','-')
    m=re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})',s)
    if m:return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s

def normalize_monitor_rows(rows,item_id,force_bind=False):
    out=[]
    current=_norm_item_id(item_id)
    for r in rows:
        rid=_norm_item_id(_pick(r,'itemId'))
        if rid and current and rid!=current and not force_bind: continue
        date=_norm_monitor_date(_pick(r,'date'))
        sales=str(_pick(r,'sales') or '').strip()
        if not date or not sales: continue
        out.append({
            'date':date,
            'itemId':current or rid,
            'salesDisplay':sales,
            'ranking':str(_pick(r,'rank') or '').strip(),
            'price':str(_pick(r,'price') or '').strip(),
            'promotion':str(_pick(r,'promotion') or '').strip(),
            'title':str(_pick(r,'title') or '').strip()
        })
    by={}
    for x in out: by[x['date']]=x
    return sorted(by.values(),key=lambda x:x['date'])[-7:]
def monitor_path(item_id): return MONITOR_DIR/(re.sub(r'\D','',str(item_id)) or 'unknown')
def set_task(tid, **kw):
    with LOCK: TASKS.setdefault(tid,{}).update(kw)

def task_evidence_summary(raw):
    clean=normalize(raw);images=clean.get('images') or {}; collection=clean.get('collection') or {}
    groups=(('main','商品主图'),('detail','详情图'),('sku','SKU 图'),('buyerShow','评论原图'))
    preview=[];seen=set()
    for key,label in groups:
        for url in (images.get(key) or [])[:4]:
            if not isinstance(url,str) or not url.startswith(('http://','https://','data:image/')) or url in seen:continue
            seen.add(url);preview.append({'url':url,'group':key,'label':label})
            if len(preview)>=8:break
        if len(preview)>=8:break
    return {
      'counts':{
        'parameters':len(clean.get('attributes') or []),'reviews':len(clean.get('reviews') or []),
        'questions':len(clean.get('questions') or []),'main':len(images.get('main') or []),
        'detail':len(images.get('detail') or []),'sku':len(images.get('sku') or []),
        'buyerShow':len(images.get('buyerShow') or []),
      },
      'publicReviewCount':collection.get('publicReviewCount') or '',
      'reviewComplete':bool(collection.get('reviewCollectionComplete')),
      'previewImages':preview,
    }

def worker(tid, raw):
    try:
        evidence_summary=task_evidence_summary(raw);counts=evidence_summary['counts']
        set_task(tid,status='analyzing',progress=28,evidenceSummary=evidence_summary,steps={'collect':'done','evidence':'waiting','planner':'waiting','product':'waiting','fashion':'waiting','visual':'not_collected' if not counts['main'] else 'waiting','merchandising':'waiting','detail':'not_collected' if not counts['detail'] else 'waiting','review':'waiting','qa':'waiting','competition':'waiting','strategy':'waiting','plans':'waiting','editor':'waiting','report':'waiting'})
        def progress(step,state,pct):
            with LOCK:
                t=TASKS[tid]; t['progress']=pct
                if step=='visual' and not counts['main']:t['steps'][step]='not_collected'
                elif step=='detail' and not counts['detail']:t['steps'][step]='not_collected'
                else:t['steps'][step]=state
        # 分析设置硬超时，避免模型/API异常导致任务永久停留在“处理中”。
        timeout_seconds=max(60,int(os.getenv('TMALL_ANALYSIS_TIMEOUT','900')))
        pool=ThreadPoolExecutor(max_workers=1)
        future=pool.submit(analyze,raw,progress)
        try:
            result=future.result(timeout=timeout_seconds)
        except FutureTimeout:
            future.cancel()
            # 用无模型本地路径生成可交付报告，而不是让任务卡死。
            result=analyze({**raw,'_model_available':False},progress)
        except Exception as analysis_error:
            # 模型返回结构异常或单个分析模块崩溃时，退回证据驱动本地报告。
            result=analyze({**raw,'_model_available':False},progress)
            result.setdefault('meta',{})['reportNotice']=f'部分分析模块异常，已输出证据报告：{analysis_error}'
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if not (result.get('meta') or {}).get('reportReady'):
            (REPORTS/f'{tid}.failed.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
            raise RuntimeError((result.get('meta') or {}).get('reportBlockedReason') or '模型未生成可输出报告，本次不使用兜底内容。')
        set_task(tid,status='rendering',progress=95)
        TASKS[tid]['steps']['report']='processing'
        result=cache_report_images(result,tid)
        (REPORTS/f'{tid}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
        # 报告页面是静态 HTML；数据单独由 JSON 接口提供，便于部署和独立迭代 UI。
        set_task(tid,status='complete',progress=100,reportUrl=f'/report.html?data=/reports/{tid}.json',analysisUrl=f'/reports/{tid}.json')
        TASKS[tid]['steps']['report']='done'
    except Exception as e:
        with LOCK:
            task=TASKS.setdefault(tid,{})
            for key,state in (task.get('steps') or {}).items():
                if str(state).startswith('processing'):task['steps'][key]='failed'
        set_task(tid,status='error',error=str(e),trace=traceback.format_exc(),progress=100)

def task_page(tid):
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>行业平台报告生成中</title><link rel="stylesheet" href="/report.css"></head><body class="loading-page"><main class="loading-shell"><header class="loading-head"><div><div class="eyebrow">SANXIAN · PRODUCT INTELLIGENCE</div><h1 id="title">正在生成商品产品分析报告</h1><p id="desc">按真实采集证据完成核验、评论聚合、主图分析、详情参数解读、活动分析、产品定义、推荐方案与落地方式。</p></div><strong id="percent">8%</strong></header><section class="loading-evidence"><div class="loading-section-title"><span>本次证据</span><small id="reviewState"></small></div><div id="evidenceStats" class="loading-stats"></div><div id="imagePreview" class="loading-images"></div></section><section class="loading-work"><div class="loading-section-title"><span>生成进度</span><small>缺失资料会明确标记，不会补写</small></div><div id="steps" class="loading-steps"></div></section><div class="topic-bar"><i id="bar" style="width:8%"></i></div><p id="err" class="error"></p></main><script>window.TASK_ID={json.dumps(tid)}</script><script src="/task.js"></script></body></html>'''

TASK_JS='''
const labels={collect:'商品页面采集',evidence:'证据清洗与建库',planner:'报告结构编排',product:'商品与参数核验',fashion:'设计资产梳理',visual:'商品主图核验',merchandising:'标题与活动核验',detail:'商品详情图核验',review:'评论体验聚合',qa:'购买问答整理',competition:'竞品数据边界',strategy:'产品结论生成',plans:'开品建议生成',editor:'最终报告汇总与校验',report:'图文报告渲染'};
const stateText={done:'已完成',processing:'处理中',waiting:'待处理',not_collected:'未采到',failed:'失败'};
const statLabels={parameters:'有效参数',reviews:'有效评论',questions:'去重问答',main:'商品主图',detail:'详情图',sku:'SKU 图',buyerShow:'评论原图'};
function fillEvidence(summary){
  const counts=summary?.counts||{}; const stats=document.getElementById('evidenceStats'); stats.replaceChildren();
  Object.entries(statLabels).forEach(([key,label])=>{const card=document.createElement('div');const s=document.createElement('span');s.textContent=label;const b=document.createElement('b');b.textContent=String(counts[key]||0);card.append(s,b);stats.append(card)});
  const state=document.getElementById('reviewState'); const publicCount=summary?.publicReviewCount; state.textContent=(publicCount?`已采 ${counts.reviews||0} / 页面公开 ${publicCount} · `:`已采 ${counts.reviews||0} 条 · `)+(summary?.reviewComplete?'评论采集已确认完整':'评论采集未确认完整');
  const preview=document.getElementById('imagePreview'); preview.replaceChildren();
  (summary?.previewImages||[]).forEach((item,i)=>{const fig=document.createElement('figure');const img=document.createElement('img');img.src=item.url;img.alt=item.label+' '+(i+1);img.referrerPolicy='no-referrer';const cap=document.createElement('figcaption');cap.textContent=item.label;fig.append(img,cap);preview.append(fig)});
  preview.hidden=!preview.children.length;
}
function fillSteps(steps){const box=document.getElementById('steps');box.replaceChildren();Object.entries(steps||{}).forEach(([key,state])=>{const row=document.createElement('div');row.className='loading-step '+String(state).split(' ')[0];const mark=document.createElement('i');const name=document.createElement('span');name.textContent=labels[key]||key;const value=document.createElement('b');value.textContent=String(state).startsWith('processing')?'处理中':(stateText[state]||state);row.append(mark,name,value);box.append(row)})}
async function tick(){
  const r=await fetch('/api/task/'+encodeURIComponent(window.TASK_ID)); const d=await r.json();
  document.getElementById('bar').style.width=(d.progress||0)+'%';
  document.getElementById('percent').textContent=(d.progress||0)+'%'; fillEvidence(d.evidenceSummary); fillSteps(d.steps);
  if(d.status==='complete'){ location.href=d.reportUrl; return; }
  if(d.status==='error'){ document.getElementById('title').textContent='本次未生成报告'; document.getElementById('desc').textContent='模型结论未达到完整性与证据引用要求，不显示兜底内容。'; document.getElementById('err').textContent=d.error||'未生成可输出结论'; return; }
  setTimeout(tick,900);
} tick();
'''

def save_config(data):
    if not isinstance(data, dict):
        raise ValueError('配置请求必须是 JSON 对象')
    p=ROOT/'config.json'
    # 完整包首次解压或被移动后，确保配置目录存在再进行原子写入。
    p.parent.mkdir(parents=True, exist_ok=True)
    old={}
    if p.exists():
        try: old=json.loads(p.read_text('utf-8'))
        except Exception: old={}
    key=str(data.get('api_key','')).strip()
    if not key: key=str(old.get('api_key','')).strip()
    raw_image_models=data.get('image_models', old.get('image_models', []))
    if isinstance(raw_image_models,str):
        raw_image_models=[x.strip() for x in raw_image_models.replace('\n',',').split(',') if x.strip()]
    if not isinstance(raw_image_models,list):
        raw_image_models=[]
    image_quality=normalize_image_quality(
        data['image_quality'] if 'image_quality' in data else old.get('image_quality')
    )
    old_model_quality={}
    for item in old.get('image_models', []) if isinstance(old.get('image_models', []), list) else []:
        if isinstance(item, dict):
            model_id=str(item.get('id') or item.get('model') or '').strip()
            if model_id:
                old_model_quality[model_id]=normalize_image_quality(item.get('quality'))
    image_models=[]
    for item in raw_image_models:
        if isinstance(item,dict):
            model_id=str(item.get('id') or item.get('model') or '').strip()
            label=str(item.get('label') or model_id).strip()
            quality=normalize_image_quality(item.get('quality'))
        else:
            model_id=str(item or '').strip()
            label=model_id
            quality=old_model_quality.get(model_id, '')
        if model_id and not any(x['id']==model_id for x in image_models):
            image_models.append({'id':model_id,'label':label or model_id,'quality':quality})
    legacy_image_model=str(data.get('image_model') or old.get('image_model') or '').strip()
    if legacy_image_model and not any(x['id']==legacy_image_model for x in image_models):
        image_models.insert(0,{'id':legacy_image_model,'label':legacy_image_model,
                               'quality':image_quality})
    if not legacy_image_model and image_models:
        legacy_image_model=image_models[0]['id']
    for item in image_models:
        if not item.get('quality'):
            item['quality']=image_quality
    cfg={
      'api_base':str(data.get('api_base') or old.get('api_base') or 'https://api.bananarouter.com/v1').strip().rstrip('/'),
      'api_key':key,
      'model':str(data.get('model') or old.get('model') or 'gpt-5.5').strip(),
      'chat_path':'/chat/completions','models_path':'/models','temperature':0.2,'timeout':120,'retries':2,
      'ssl_verify':True,'ca_bundle':'','extra_headers':{},
      'image_model':legacy_image_model,
      'image_models':image_models,
      'image_api_base':str(data.get('image_api_base') or old.get('image_api_base') or '').strip().rstrip('/'),
      'image_api_key':str(data.get('image_api_key') or old.get('image_api_key') or '').strip(),
      'image_path':str(data.get('image_path') or old.get('image_path') or '/images/generations').strip(),
      'image_models_path':str(data.get('image_models_path') or old.get('image_models_path') or '/models').strip(),
      'image_size':str(data.get('image_size') or old.get('image_size') or '1024x1024').strip(),
      'image_quality':image_quality,
      # Preserve an optional provider style hint even though the compact
      # settings page does not expose it as a separate input.
      'image_style':str(data.get('image_style') or old.get('image_style') or '').strip(),
    }
    tmp=p.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),'utf-8')
    tmp.replace(p)
    return cfg

def _image_channel_label(config):
    """Describe field-level fallback without exposing any API credential."""
    image_base_set=bool(str((config or {}).get('image_api_base') or '').strip())
    image_key_set=bool(str((config or {}).get('image_api_key') or '').strip())
    if image_base_set and image_key_set: return '独立生图渠道'
    if image_base_set or image_key_set: return '混合继承（部分字段复用分析渠道）'
    return '复用分析渠道'

def control_page():
    global MODEL_PROBE, MODEL_PROBE_AT
    c=load_config(); is_cfg=configured()
    if is_cfg and (time.time()-MODEL_PROBE_AT>30):
        MODEL_PROBE=probe_model_api(timeout=12); MODEL_PROBE_AT=time.time()
    api_ok=bool(MODEL_PROBE.get('ok'))
    base=html.escape(str(c.get('api_base') or 'https://api.bananarouter.com/v1'))
    model=html.escape(str(c.get('model') or 'gpt-5.5'))
    image_base=html.escape(str(c.get('image_api_base') or ''))
    image_model=html.escape(str(c.get('image_model') or ''))
    image_models=image_model_options(c)
    image_models_text=html.escape('\n'.join(item['id'] for item in image_models))
    image_quality=normalize_image_quality(c.get('image_quality'))
    quality_options=''.join(
        f'<option value="{html.escape(value)}"{" selected" if value==image_quality else ""}>'
        f'{html.escape(value) if value else "服务商默认"}</option>'
        for value in ('',)+IMAGE_QUALITY_OPTIONS
    )
    image_path=html.escape(str(c.get('image_path') or '/images/generations'))
    image_models_path=html.escape(str(c.get('image_models_path') or '/models'))
    effective_image_base=str(c.get('image_api_base') or c.get('api_base') or '').rstrip('/')
    effective_image_path=str(c.get('image_path') or '/images/generations')
    image_endpoint=html.escape((effective_image_base+'/'+effective_image_path.lstrip('/')) if effective_image_base else '未配置')
    image_channel_label=_image_channel_label(c)
    image_cfg=bool(str(c.get('image_model') or '').strip())
    effective_image_key=str(c.get('image_api_key') or c.get('api_key') or '').strip()
    image_ready=bool(image_cfg and effective_image_base and effective_image_key and not effective_image_key.startswith('YOUR_'))
    request_timeout=html.escape(str(c.get('timeout') or 120))
    request_retries=html.escape(str(c.get('retries') if c.get('retries') is not None else 2))
    # The status card reports credential readiness without exposing a key. The
    # provider/model list probe below remains the source of truth for reachability.
    image_ok=image_ready
    cfg_err=html.escape(str(c.get('_config_error') or ''))
    probe=html.escape(str(MODEL_PROBE.get('error') or ''))
    key_state='已保存' if str(c.get('api_key') or '').strip() and not str(c.get('api_key')).startswith('YOUR_') else '未填写'
    image_key_state='已单独保存' if str(c.get('image_api_key') or '').strip() else '未单独填写，当前复用分析渠道 Key'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>三笙 · 电商商品分析闭环 V{SERVER_VERSION}</title><style>
    *{{box-sizing:border-box}}body{{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;background:#f5faf9;color:#10191d;margin:0}}.wrap{{max-width:1160px;margin:54px auto;padding:0 24px 60px}}.hero{{background:#071114;color:#fff;padding:34px;border-radius:22px;border-top:5px solid #00cdb0}}h1{{font-size:38px;margin:0 0 10px}}h2{{letter-spacing:-.02em}}.sub{{color:#b9d0d4;line-height:1.65}}.card{{margin-top:18px;background:#fff;border:1px solid #dbe8e8;border-radius:18px;padding:24px}}.status{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.pill{{padding:14px;border-radius:12px;background:#eef9f7;font-weight:700}}.ok{{color:#008c78}}.bad{{color:#c54552}}label{{display:block;font-size:13px;font-weight:700;margin:16px 0 7px}}input,textarea{{width:100%;padding:13px 14px;border:1px solid #bcd8d6;border-radius:10px;font-size:15px}}textarea{{min-height:108px;resize:vertical;font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}}.field-help{{display:block;margin-top:6px;color:#6f7d80;font-size:12px;line-height:1.55;overflow-wrap:anywhere}}button{{margin-top:18px;border:0;border-radius:10px;padding:13px 18px;background:linear-gradient(110deg,#00cdb0,#008fd8);color:white;font-weight:800;font-size:15px;cursor:pointer}}button.secondary{{background:#071114;margin-left:8px}}#msg{{margin-top:12px;white-space:pre-wrap}}code{{background:#eaf7f5;padding:3px 6px;border-radius:5px;color:#087465;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}}a{{color:#087f70}}.section-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:24px}}.section-head h2{{margin:4px 0 8px;font-size:28px}}.section-head p{{max-width:760px;margin:0;color:#667477;line-height:1.65}}.eyebrow{{color:#008f7a;font-size:11px;font-weight:900;letter-spacing:.14em}}.doc-link{{flex:0 0 auto;display:inline-flex;align-items:center;padding:9px 12px;border:1px solid #a9d7d0;border-radius:9px;background:#f1fbf9;font-size:12px;font-weight:800;text-decoration:none}}.workflow-card{{border-top:4px solid #00b99f}}.flow{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:22px 0 0;padding:0;list-style:none;counter-reset:flow}}.flow li{{position:relative;min-height:142px;padding:15px 13px;border:1px solid #d8e7e5;border-radius:13px;background:linear-gradient(155deg,#f7fcfb,#eef8f6);counter-increment:flow}}.flow li::before{{content:"0" counter(flow);display:block;margin-bottom:18px;color:#00a58e;font-size:11px;font-weight:900;letter-spacing:.08em}}.flow li:not(:last-child)::after{{content:"→";position:absolute;z-index:2;right:-9px;top:66px;width:18px;height:18px;border:1px solid #cae2de;border-radius:50%;background:#fff;color:#008f7a;text-align:center;font-size:12px;line-height:16px}}.flow b{{display:block;margin-bottom:7px;font-size:14px}}.flow small{{display:block;color:#68777a;font-size:11px;line-height:1.55}}.code-name{{display:block;margin-top:8px;color:#087f70;font:10px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}}.runtime-strip{{display:grid;grid-template-columns:1.3fr 1fr 1fr 1fr;gap:8px;margin-top:12px}}.runtime-item{{padding:10px 12px;border-radius:10px;background:#091619;color:#d6e7e7;font-size:11px;line-height:1.5;overflow-wrap:anywhere}}.runtime-item b{{display:block;color:#27d8bd;font-size:10px;letter-spacing:.08em}}.runtime-chain{{margin:12px 0 0;padding:10px 12px;border-radius:10px;background:#e9f7f4;color:#47605d;font-size:11px;line-height:1.6;overflow-wrap:anywhere}}.runtime-chain b{{color:#087f70;margin-right:8px}}.dev-grid{{display:grid;grid-template-columns:1.1fr .9fr;gap:14px;margin-top:14px}}.dev-panel{{border:1px solid #dbe8e8;border-radius:14px;overflow:hidden;background:#fff}}.dev-panel>header{{padding:15px 16px;background:#f5faf9}}.dev-panel h3{{margin:0 0 4px;font-size:16px}}.dev-panel header p{{margin:0;color:#6d797b;font-size:11px;line-height:1.5}}.prompt-stack{{margin:0;padding:6px 16px 14px;list-style:none;counter-reset:layer}}.prompt-stack li{{display:grid;grid-template-columns:26px 1fr;gap:8px;padding:9px 0;border-bottom:1px solid #edf3f2;counter-increment:layer}}.prompt-stack li:last-child{{border-bottom:0}}.prompt-stack li::before{{content:counter(layer);display:flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:6px;background:#e5f6f3;color:#008a76;font-size:10px;font-weight:900}}.prompt-stack b{{font-size:12px}}.prompt-stack span{{display:block;margin-top:3px;color:#6d797b;font-size:10px;line-height:1.5}}.branch-list{{margin:0;padding:7px 16px 15px;list-style:none}}.branch-list li{{padding:10px 0;border-bottom:1px solid #edf3f2;font-size:11px;line-height:1.55}}.branch-list li:last-child{{border-bottom:0}}.branch-list b{{display:block;margin-bottom:2px;color:#0b7567;font-size:12px}}.formula{{margin:0 16px 16px;padding:11px 12px;border-radius:10px;background:#071114;color:#d8e9e8;font:10px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}}details.tech-detail{{min-width:0;margin-top:14px;border:1px solid #dbe8e8;border-radius:14px;background:#fff;overflow:hidden}}details.tech-detail>summary{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:15px 16px;background:#f5faf9;cursor:pointer;font-size:14px;font-weight:800}}details.tech-detail>summary small{{color:#718083;font-size:11px;font-weight:500}}.table-wrap{{max-width:100%;overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:11px}}th,td{{padding:11px 12px;border-top:1px solid #e4eeec;text-align:left;vertical-align:top;line-height:1.55}}th{{background:#fbfdfd;color:#506063;font-size:10px;letter-spacing:.05em;white-space:nowrap}}td:first-child{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#087465;white-space:nowrap}}.callout{{margin:14px 0 0;padding:12px 14px;border-left:4px solid #00ad94;border-radius:8px;background:#edf9f7;color:#47605d;font-size:12px;line-height:1.65}}.dev-grid>*,.channel-grid>*,.channel-grid>.card{{min-width:0}}.channel-grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}}.channel-grid>.card{{height:max-content}}@media(max-width:980px){{.flow{{grid-template-columns:repeat(3,minmax(0,1fr))}}.flow li:nth-child(3)::after{{display:none}}.runtime-strip{{grid-template-columns:1fr 1fr}}.dev-grid,.channel-grid{{grid-template-columns:minmax(0,1fr)}}}}@media(max-width:700px){{.wrap{{margin-top:24px;padding:0 14px 40px}}h1{{font-size:30px}}.hero,.card{{padding:20px}}.status,.flow,.runtime-strip{{grid-template-columns:minmax(0,1fr)}}.flow li{{min-height:auto}}.flow li::after{{display:none!important}}.section-head{{display:block}}.doc-link{{margin-top:14px}}details.tech-detail>summary{{display:block}}details.tech-detail>summary small{{display:block;margin-top:5px}}.table-wrap{{overflow:visible}}table,thead,tbody,tr,th,td{{display:block;width:100%}}thead{{display:none}}tr{{padding:9px 12px;border-top:1px solid #e4eeec}}td,td:first-child{{display:grid;grid-template-columns:82px minmax(0,1fr);gap:8px;padding:3px 0;border:0;white-space:normal;overflow-wrap:anywhere}}td::before{{color:#718083;font:9px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}td:nth-child(1)::before{{content:"参数"}}td:nth-child(2)::before{{content:"来源 / 默认"}}td:nth-child(3)::before{{content:"作用"}}td:nth-child(4)::before{{content:"校验 / 兼容"}}button.secondary{{margin-left:0}}}}
    </style></head><body><div class="wrap"><section class="hero"><div style="font-size:12px;letter-spacing:.16em;color:#12d8bb;font-weight:800">ONE-CLICK LOCAL SERVICE</div><h1>三笙 · 电商商品分析引擎 V{SERVER_VERSION}</h1><div class="sub">单商品手动深采；类目不限，参数与SKU动态识别，评论可持续采集，也可随时基于当前数据开始分析。</div></section>
    <section class="card"><div class="status"><div class="pill">本地服务<br><span class="ok">运行正常 · V{SERVER_VERSION}</span></div><div class="pill">分析模型<br><span class="{'ok' if is_cfg else 'bad'}">{'已配置 '+model if is_cfg else '待配置'}</span></div><div class="pill">生图模型<br><span class="{'ok' if image_ok else 'bad'}">{'已配置 '+image_model if image_cfg else '待配置'}</span></div></div></section>
    <section class="card workflow-card" id="image-workflow"><div class="section-head"><div><span class="eyebrow">ENGINEERING MAP · REAL RUNTIME</span><h2>生图工作流 · 研发速览</h2><p>弹窗只读取默认图位并本地编辑要求；确认提交后，后台解析用户意图一次、组装逐图提示词，再调用生图接口并逐张保存。Demo 未接入积分计费与余额校验。</p></div><a class="doc-link" href="/prompts">查看 / 编辑提示词模板 →</a></div><p class="runtime-chain"><b>前端触发链</b><code>initPlanActions</code> → <code>/api/image-generation-setup</code> → <code>/api/generate-images</code> → <code>pollJob</code>；后台按槽位调用 <code>image_generate</code>，逐张写入 manifest。</p>
    <ol class="flow"><li><b>读取报告与方案</b><small>从报告文件或请求体读取真实商品事实，按 <code>planIndex</code> 选择“下一款方向”。</small><span class="code-name">_load_report_for_generation</span></li><li><b>拆成逐图任务</b><small>提供主图 5 位、详情图 15 位；弹窗默认选择主图 5 位 + 详情前 6 位。</small><span class="code-name">build_generation_slots</span></li><li><b>确定起始产品基准</b><small>用户上传最多 4 张优先；否则取采集到的第一张商品主图。明确的用户商品设定可覆盖对应字段。</small><span class="code-name">resolve_reference_images</span></li><li><b>组装与校验提示词</b><small>注入身份锁、报告参数、用户最终设定、方案、单图任务和禁区；视觉要求再按槽位相关性分配。</small><span class="code-name">build_image_prompt + merge_image_prompt_with_user_edit</span></li><li><b>调用生图渠道</b><small>把最终 prompt、模型、尺寸、数量和参考图发给 OpenAI-compatible 接口。</small><span class="code-name">image_generate</span></li><li><b>落盘与一致性复核</b><small>兼容 URL / Base64 返回；每完成一张即保存图片与任务清单，最后标记人工复核。</small><span class="code-name">_persist_image_job + consistencyGate</span></li></ol>
    <div class="runtime-strip"><div class="runtime-item"><b>当前真实端点</b>{image_endpoint}</div><div class="runtime-item"><b>渠道选择</b>{html.escape(image_channel_label)}</div><div class="runtime-item"><b>固定出图尺寸</b>主图 1024×1024<br>详情图 1024×1536</div><div class="runtime-item"><b>单任务与容错</b>每槽位 n=1<br>超时 {request_timeout}s · 重试 {request_retries} 次</div></div>
    <div class="dev-grid"><section class="dev-panel"><header><h3>最终提示词怎样组成</h3><p>这是实际拼装顺序，不展示模型的隐藏推理过程。</p></header><ol class="prompt-stack"><li><div><b>统一产品身份锁 <code>identityLock</code></b><span>报告商品与参数作为默认基准；全局明确商品修改写入 <code>productOverrides</code>，整套图共享同一最终 identityId。</span></div></li><li><div><b>参考图规则</b><span>uploaded / collected / fission 决定起始外观；用户明确指定的商品字段优先覆盖参考图对应默认字段。</span></div></li><li><div><b>全局用户方向</b><span>明确的材质、颜色、结构、规格等商品设定作用于整套图；视觉要求按槽位相关性分配；品牌、交易、认证等禁区被拦截。</span></div></li><li><div><b>开品方案与爆款表达</b><span>注入方案名称、产品动作、页面动作；只借鉴高转化表达方法，不复制竞品。</span></div></li><li><div><b>当前图片默认任务</b><span>注入 assetType、index、role、task 与 handoff；用户没有明确覆盖时，继续执行本图默认信息任务。</span></div></li><li><div><b>事实、视觉与构图约束</b><span>类目、受众、页面实采参数提供默认值；视觉信号、尺寸和平台硬性禁区共同收口。</span></div></li><li><div><b>模板包裹与单图编辑 <code>promptMerge</code></b><span><code>image_generation</code> 用 <code>{{prompt}}</code> 注入内置提示词；商品字段编辑直接提权，视觉编辑需与本图相关，不相关内容保留默认策划。</span></div></li></ol><p class="formula">basePrompt → image_generation.replace("{{prompt}}", basePrompt) → relevanceGuard(promptOverride) → finalPrompt</p></section>
    <section class="dev-panel"><header><h3>参考图与并发分支</h3><p>是否上传参考图和“裂变花型”开关决定执行 DAG。</p></header><ul class="branch-list"><li><b>上传参考图</b>第一张作为商品身份基准；“产品展示与参考图拍摄一致”开启时，采集商品对应槽位图负责机位、构图、动作和摆放状态，上传图不再决定视角。</li><li><b>未上传 · 普通同款</b>采集商品第一张主图作为共同起始参考，已选槽位可并行生成。</li><li><b>未上传 · 裂变花型</b>先串行生成 <code>main:1</code> 新品基准图，再把该结果作为其余槽位的共同参考并行生成。</li><li><b>没有任何可用参考图</b>预览和正式任务都会立即报错，不会无产品基准盲生图。</li><li><b>结果复核</b>系统记录共享身份设定、参考角色（<code>referenceRole</code>）和使用数量（<code>referenceCountUsed</code>），但不等于视觉质检通过；发布前仍需人工核对结构、颜色、材质、规格、文字与合规。</li></ul></section></div>
    <details class="tech-detail" open><summary>业务请求参数 <small>报告弹窗 → /api/image-prompt-preview 与 /api/generate-images</small></summary><div class="table-wrap"><table><thead><tr><th>参数</th><th>来源 / 默认</th><th>作用</th><th>校验与边界</th></tr></thead><tbody><tr><td>source / reportData</td><td>当前报告 URL 或报告 JSON</td><td>提供商品事实、证据账本、视觉分析和开品方案。</td><td>source 只能读取本地 reports 目录内的 JSON。</td></tr><tr><td>planIndex</td><td>用户选择；默认 0</td><td>决定本次执行哪一个新品方案。</td><td>必须落在实际方案数组范围内。</td></tr><tr><td>assetTypes</td><td>main / detail</td><td>决定生成主图、详情图或两者。</td><td>其他值被过滤；正式生成至少保留一种。</td></tr><tr><td>selectedSlots</td><td>例如 main:1、detail:3</td><td>精确选择要执行的图片槽位。</td><td>空值代表执行所选类型的全部槽位。</td></tr><tr><td>referenceImages</td><td>用户上传；最多 4 张</td><td>提供真实起始商品外观，不只是写进文字提示词。</td><td>用户明确商品设定可覆盖对应默认字段；单张上传限制约 9 MB。</td></tr><tr><td>matchReferenceShooting</td><td>默认 false（未勾选）</td><td>true 时继承参考图拍摄语言：机位、景别、透视、构图、背景、光线、姿态、陈列与留白；false 时仅锁定产品身份，按当前槽位业务目标重新设计拍摄。</td><td>只影响视觉表达；平台合规、identityLock、方案产品目标和当前槽位业务目标优先，首张 main:1 仍冻结未明确修改的商品字段。</td></tr><tr><td>userDirection</td><td>全局最终要求</td><td>既可指定商品字段，也可调整场景、构图、镜头和排版。</td><td>商品设定应用整套图；视觉要求再按槽位相关性分配；平台禁区拦截。</td></tr><tr><td>promptOverrides</td><td>按槽位保存的单图编辑</td><td>让某张图优先执行明确商品修改或相关视觉要求。</td><td>商品字段可覆盖本图默认值；视觉编辑需相关；平台禁区始终不能覆盖。</td></tr><tr><td>fissionPattern</td><td>未上传时默认开启</td><td>先产出新品基准，再保持整套裂变商品一致。</td><td>上传参考图时强制关闭。</td></tr><tr><td>completeSet</td><td>默认 true</td><td>按已计算的槽位任务生成，而非简单重复 n 张。</td><td>true 且 selectedSlots 为空时执行所选类型的全部槽位。</td></tr><tr><td>jobId / statusUrl</td><td>POST 成功返回</td><td>异步任务标识与轮询地址。</td><td>客户端按 statusUrl 查询，不阻塞当前请求。</td></tr><tr><td>GET status</td><td>/api/image-job/&lt;jobId&gt;</td><td>返回 status、progress、results、error 和 consistencyGate。</td><td>queued / generating / complete / error；完成后结果可追溯。</td></tr></tbody></table></div></details>
    <details class="tech-detail" open><summary>生图接口参数与返回 <small>服务端 → 当前生图 API；密钥不会显示在页面</small></summary><div class="table-wrap"><table><thead><tr><th>参数</th><th>当前值 / 默认</th><th>作用</th><th>兼容策略</th></tr></thead><tbody><tr><td>model</td><td>{image_model or '未配置'}</td><td>真正写入生图请求体的模型 ID。</td><td>必填；与分析模型完全独立。</td></tr><tr><td>image_models_path</td><td>{image_models_path}</td><td>保存/测试连接时查询生图模型列表的路径。</td><td>默认 <code>/models</code>；与实际出图路径分开。</td></tr><tr><td>prompt</td><td>按上方 7 层动态组成</td><td>每张图都得到不同的最终提示词。</td><td>预览接口与正式生成共用同一拼装函数。</td></tr><tr><td>size</td><td>main 1024×1024<br>detail 1024×1536</td><td>按主图 / 详情图用途固定画布比例。</td><td>由槽位类型决定，不使用页面自由输入覆盖。</td></tr><tr><td>n</td><td>1</td><td>一次接口调用只生成当前槽位的一张图。</td><td>整套数量由 selectedSlots 决定。</td></tr><tr><td>image / reference_images / images</td><td>同一组参考图的兼容字段</td><td>把真实产品图随请求发送给生图服务。</td><td>按三种常见字段形态逐一尝试，不能静默丢弃参考图。</td></tr><tr><td>quality / style</td><td>{image_quality or '服务商默认'} / {html.escape(str(c.get('image_style') or '服务商默认'))}</td><td>quality 控制图片质量；style 保留供应商风格提示。</td><td>配置页提供默认质量；报告弹窗可按模型覆盖 quality。接口拒绝可选字段时自动移除后重试。</td></tr><tr><td>response.data[]</td><td>URL 或 Base64</td><td>读取 url、image_url、b64_json 或 base64。</td><td>校验确为图片后保存到 generated/&lt;jobId&gt;/。</td></tr><tr><td>job manifest</td><td>每张图完成即写入</td><td>保存 prompt、slot、方案、identityLock 与结果地址。</td><td>服务重启后已完成图片仍可追溯，未完成项提示重提。</td></tr><tr><td>consistencyGate</td><td>完成时为 needs_review</td><td>记录整套图共享身份与约束后的复核状态。</td><td>不是视觉质检通过；正式发布前仍需人工检查。</td></tr></tbody></table></div></details>
    <p class="callout"><b>优先级一句话：</b>平台合规 ＞ 用户明确商品设定与 identityLock ＞ 方案产品目标 ＞ 当前槽位业务目标 ＞（勾选时）参考图拍摄语言 ＞ 默认构图；拍摄一致只影响视觉表达，不覆盖业务/产品目标，未明确修改的商品字段继续沿用参考基准。</p></section>
    <div class="channel-grid"><section class="card"><h2 style="margin-top:0">分析渠道</h2><p style="color:#667067">负责提炼商品事实、生成报告与新品方案；不直接输出图片。</p>
    <label>分析 API Base</label><input id="base" value="{base}"><small class="field-help">OpenAI-compatible 文本模型服务根地址；服务端会拼接 <code>/models</code> 和 <code>/chat/completions</code>。</small><label>分析 API Key（{key_state}）</label><input id="key" type="password" placeholder="粘贴新的 Key；已保存时可留空"><small class="field-help">仅保存在本机配置文件中；留空表示继续使用已保存值，页面不会回显密钥。</small><label>分析模型（必填）</label><input id="model" value="{model}" placeholder="例如 qwen3.7-flash"><small class="field-help">用于七角色商品分析和结构化报告，不会代替下方生图模型。</small></section>
    <section class="card"><h2 style="margin-top:0">生图渠道</h2><p style="color:#667067">负责主图和详情图，可使用与分析渠道不同的服务商、Key 和模型；API Base 与 Key 未单独配置时，各字段分别复用分析渠道。</p>
    <label>生图 API Base</label><input id="imageBase" value="{image_base}" placeholder="例如 https://example.com/v1；未配置时复用分析 API Base"><small class="field-help">生图服务根地址；配置值为空时继承“分析 API Base”。当前实际模式：<b>{html.escape(image_channel_label)}</b>。</small><label>生图 API Key（{image_key_state}）</label><input id="imageKey" type="password" placeholder="粘贴生图渠道 Key；已保存时可留空"><small class="field-help">未保存独立 Key 时继承分析 Key；若上方标记“已单独保存”，输入框留空表示继续使用已保存值。页面永不回显密钥。</small><label>默认生图模型（必填）</label><input id="imageModel" value="{image_model}" placeholder="例如 qwen-image-3.0"><small class="field-help">兼容旧流程；同时作为对比测试的默认模型。</small><label>默认图片质量</label><select id="imageQuality">{quality_options}</select><small class="field-help">留空使用服务商默认。建议模型对比时统一选择 <code>medium</code>，避免把模型差异和质量差异混在一起。</small><label>生图测试模型列表</label><textarea id="imageModels" placeholder="每行一个模型 ID">{image_models_text}</textarea><small class="field-help">每行一个模型 ID。报告弹窗会按这些模型提供复选框，并以“模型列 × 图片任务行”展示对比结果；每个模型还可单独选择质量。</small><label>生图接口路径</label><input id="imagePath" value="{image_path}"><small class="field-help">拼接在实际 API Base 后；默认 <code>/images/generations</code>。当前完整端点：<code>{image_endpoint}</code>。</small>
    <button onclick="save()">保存并测试连接</button><button class="secondary" onclick="test()">仅重新测试</button><div id="msg" role="status" aria-live="polite">{'配置错误：'+cfg_err if cfg_err else ('API错误：'+probe if (is_cfg and not api_ok and probe) else '')}</div></section></div>
    <section class="card"><h2 style="margin-top:0">提示词与业务联动</h2><p>查看当前模板原文、变量说明和真实模型联动。<code>image_generation</code> 模板必须保留 <code>{{prompt}}</code>，保存后下一次预览与正式生图立即生效。</p><p><a href="/prompts">打开提示词与模型联动配置 →</a></p></section>
    <section class="card"><h2 style="margin-top:0">下一步</h2><p>Chrome 只需加载一次 <code>extension</code> 文件夹。之后每次使用：双击启动 → 打开已登录的天猫商品页 → 可选导入监测数据 → 点击扩展“开始深度采集”。</p></section></div>
    <script>
    async function save(){{const msg=document.getElementById('msg');if(!model.value.trim()||!imageModel.value.trim()){{msg.textContent='✕ 分析模型和默认生图模型都必须填写。';return}}msg.textContent='正在保存并分别测试两个渠道…';const r=await fetch('/api/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{api_base:base.value,api_key:key.value,model:model.value,image_api_base:imageBase.value,image_api_key:imageKey.value,image_model:imageModel.value,image_quality:document.getElementById('imageQuality').value,image_models:imageModels.value.split(/[,\\n]/).map(x=>x.trim()).filter(Boolean),image_path:imagePath.value}})}});const d=await r.json();msg.textContent=d.ok?'✓ 分析渠道和生图渠道均已保存并验证。':'✕ '+(d.error||'配置失败');if(d.ok)setTimeout(()=>location.reload(),700)}}
    async function test(){{const msg=document.getElementById('msg');msg.textContent='正在分别测试两个渠道…';const r=await fetch('/api/model-test');const d=await r.json();msg.textContent=d.ok?'✓ 分析渠道：'+(d.analysis?.model||'')+'；生图渠道：'+(d.image?.imageModel||'')+(d.image?.separateChannel?'（独立渠道）':'（复用分析渠道）'):'✕ '+(d.error||'连接失败')}}
    </script></body></html>'''

def prompt_page():
    saved={}
    if PROMPT_CONFIG.exists():
        try:
            saved=json.loads(PROMPT_CONFIG.read_text('utf-8'))
            if not isinstance(saved,dict): saved={}
        except Exception: saved={}
    items={k:{'name':v.name,'body':saved.get(k,{}).get('body',v.body),'variables':list(v.variables)} for k,v in TEMPLATES.items()}
    vars_html=''.join(f'<div class="var"><b>{html.escape(k)}</b><br>{html.escape(v)}</div>' for k,v in PRODUCT_VARIABLES.items())
    template_html=''.join(f'<section class="card"><h2>{html.escape(k)}</h2><p>变量：{html.escape("、".join(v["variables"]) or "自定义")}</p><textarea data-key="{html.escape(k)}">{html.escape(v["body"])}</textarea></section>' for k,v in items.items())
    c=load_config(); channel=_image_channel_label(c)
    live_html=f'<section class="card live"><h2>当前真实联动</h2><div class="vars"><div class="var"><b>生图渠道</b><br>{html.escape(channel)}</div><div class="var"><b>生图 API</b><br>{html.escape(c.get("image_api_base") or c.get("api_base") or "未配置")}</div><div class="var"><b>生图模型</b><br>{html.escape(c.get("image_model") or "未配置")}</div><div class="var"><b>接口路径</b><br>{html.escape(c.get("image_path") or "/images/generations")}</div></div><p>生成时先用报告中的真实商品事实、具体开品方案与每张图任务组成 <code>{{prompt}}</code>，再套用下方“image_generation”模板。</p></section>'
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<title>提示词配置</title><style>body{font-family:-apple-system,BlinkMacSystemFont,PingFang SC,sans-serif;background:#f5faf9;margin:0;color:#122027}.wrap{max-width:1100px;margin:30px auto;padding:0 20px}.card{background:#fff;border:1px solid #dbe8e8;border-radius:16px;padding:22px;margin:16px 0}.live{border-top:4px solid #008f7a}textarea{width:100%;min-height:260px;font:14px monospace;padding:12px;border:1px solid #bcd8d6;border-radius:10px}button{background:#008f7a;color:#fff;border:0;border-radius:9px;padding:12px 18px;font-weight:700;cursor:pointer}.vars{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}.var{background:#eef9f7;padding:10px;border-radius:8px;font-size:13px}code{background:#eaf7f5;padding:2px 5px}</style>'
      '<div class="wrap"><h1>提示词与模型联动配置</h1><p>编辑后保存，下一次分析或生图任务立即生效。</p>'+live_html+'<section class="card"><h2>商品变量说明</h2><div class="vars">'+vars_html+'</div></section>'+template_html
      +'<button onclick="save()">保存全部模板</button><span id="msg" style="margin-left:12px"></span></div><script>async function save(){const templates={};document.querySelectorAll("textarea[data-key]").forEach(x=>templates[x.dataset.key]={body:x.value});const r=await fetch("/api/prompts",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({templates})});const d=await r.json();document.getElementById("msg").textContent=d.ok?"已保存":"保存失败："+(d.error||"")}</script></html>')

class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): print('[HTTP]',fmt%args)
    def cors(self):
        self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Headers','Content-Type');self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS')
    def send_json(self,obj,code=200):
        b=jdump(obj);self.send_response(code);self.cors();self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def send_file(self,p,ctype):
        p=Path(p)
        if not p.exists(): self.send_error(404);return
        b=p.read_bytes();self.send_response(200);self.cors();self.send_header('Content-Type',ctype);self.send_header('Cache-Control','no-store, max-age=0');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def send_bytes(self,b,ctype,filename=''):
        self.send_response(200);self.cors();self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(b)))
        if filename:
            self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers();self.wfile.write(b)
    def do_OPTIONS(self): self.send_response(204);self.cors();self.end_headers()
    def do_POST(self):
        global MODEL_PROBE, MODEL_PROBE_AT
        if self.path=='/api/image-reference-upload':
            try:
                n=int(self.headers.get('Content-Length','0'))
                if n<=0 or n>13*1024*1024: raise ValueError('参考图请求超过大小限制')
                data=json.loads(self.rfile.read(n).decode('utf-8'))
                url=save_generation_reference(data.get('image') if isinstance(data,dict) else None)
                self.send_json({'ok':True,'url':url})
            except Exception as e: self.send_json({'ok':False,'error':str(e)},400)
            return
        if self.path=='/api/prompts':
            try:
                n=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                templates=data.get('templates') if isinstance(data.get('templates'),dict) else {}
                clean={k:{'body':str(v.get('body',''))[:100000]} for k,v in templates.items() if k in TEMPLATES and isinstance(v,dict)}
                image_body=(clean.get('image_generation') or {}).get('body','')
                if image_body and '{prompt}' not in image_body:
                    self.send_json({'ok':False,'error':'image_generation 模板必须保留 {prompt}，它负责注入真实商品与具体开品方案'},400); return
                PROMPT_CONFIG.write_text(json.dumps(clean,ensure_ascii=False,indent=2),'utf-8'); self.send_json({'ok':True})
            except Exception as e: self.send_json({'ok':False,'error':str(e)},400)
            return
        if self.path=='/api/monitor-import':
            try:
                n=int(self.headers.get('Content-Length','0'))
                data=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                item_id=_norm_item_id(data.get('itemId'))
                filename=str(data.get('filename') or '')
                force_bind=bool(data.get('forceBind'))
                if not item_id:
                    self.send_json({'ok':False,'error':'缺少当前商品 itemId','code':'MISSING_ITEM_ID'},400); return
                blob=base64.b64decode(data.get('dataBase64') or '')
                parsed=parse_monitor_file(filename,blob)
                file_ids=sorted({ _norm_item_id(_pick(r,'itemId')) for r in parsed if _norm_item_id(_pick(r,'itemId')) })
                if file_ids and item_id not in file_ids and not force_bind:
                    self.send_json({
                        'ok':False,
                        'code':'ITEM_ID_MISMATCH',
                        'error':'监测文件中的商品ID与当前商品不一致',
                        'currentItemId':item_id,
                        'fileItemIds':file_ids[:20],
                        'canForce':len(file_ids)==1
                    },409); return
                rows=normalize_monitor_rows(parsed,item_id,force_bind=force_bind)
                if not rows:
                    self.send_json({
                        'ok':False,
                        'code':'NO_VALID_ROWS',
                        'error':'没有识别到当前商品的有效“日期 + 销量”数据',
                        'fileItemIds':file_ids[:20]
                    },400); return
                monitor_path(item_id).with_suffix('.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),'utf-8')
                self.send_json({
                    'ok':True,'days':len(rows),
                    'firstSales':rows[0].get('salesDisplay'),
                    'lastSales':rows[-1].get('salesDisplay'),
                    'itemId':item_id
                }); return
            except Exception as e:
                self.send_json({'ok':False,'code':'IMPORT_EXCEPTION','error':str(e)},400); return
        if self.path=='/api/monitor-clear':
            try:
                n=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(n).decode('utf-8') or '{}'); p=monitor_path(data.get('itemId')).with_suffix('.json')
                if p.exists(): p.unlink()
                self.send_json({'ok':True}); return
            except Exception as e: self.send_json({'ok':False,'error':str(e)},400); return
        if self.path=='/api/config':
            try:
                n=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                save_config(data)
                MODEL_PROBE=probe_model_api(timeout=18); MODEL_PROBE_AT=time.time()
                if not MODEL_PROBE.get('ok'): self.send_json({'ok':False,'error':MODEL_PROBE.get('error') or 'API连接失败','probe':MODEL_PROBE},400); return
                c=load_config()
                if not c.get('image_model'): self.send_json({'ok':False,'error':'生图模型为必填项'},400); return
                image_probe=probe_image_api(timeout=18)
                if not image_probe.get('ok'): self.send_json({'ok':False,'error':'生图渠道连接失败：'+str(image_probe.get('error') or ''),'analysis':MODEL_PROBE,'image':image_probe},400); return
                if image_probe.get('allImageModelsFound') is False:
                    missing=', '.join(item['id'] for item in image_probe.get('imageModels',[]) if item.get('found') is False)
                    self.send_json({'ok':False,'error':'生图渠道的模型列表中未找到 '+missing,'analysis':MODEL_PROBE,'image':image_probe},400); return
                self.send_json({'ok':True,'model':c.get('model'),'imageModel':c.get('image_model'),
                                'imageModels':image_probe.get('imageModels') or image_model_options(c),
                                'analysis':MODEL_PROBE,'image':image_probe}); return
            except Exception as e: self.send_json({'ok':False,'error':str(e)},400); return
        if self.path=='/api/generate-images':
            try:
                n=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                # A revision is a new generation request for one existing slot,
                # never an image-edit operation. Rehydrate the original task
                # context first, then allow the caller's edited requirements
                # to override only the fields it explicitly supplied.
                revision_of_job_id=str(data.get('revisionOfJobId') or '').strip()
                parent_result_id=str(data.get('parentResultId') or '').strip()
                parent_job=_load_image_job(revision_of_job_id) if revision_of_job_id else None
                parent_result=None
                if parent_job and parent_result_id:
                    parent_result=next((item for item in parent_job.get('results') or [] if isinstance(item,dict) and str(item.get('resultId') or '')==parent_result_id),None)
                    # Older checkpoints predate resultId. The history UI uses
                    # a stable job:assetType:slotIndex fallback so those
                    # records can still become the parent of a new version.
                    if not parent_result and parent_result_id.startswith(revision_of_job_id+':'):
                        fallback_parts=parent_result_id.split(':',2)
                        if len(fallback_parts)==3:
                            parent_result=next((item for item in parent_job.get('results') or []
                                                if isinstance(item,dict)
                                                and str(item.get('assetType') or '')==fallback_parts[1]
                                                and str(item.get('slotIndex') or '')==fallback_parts[2]),None)
                            if parent_result:
                                parent_result_id=str(parent_result.get('resultId') or parent_result_id)
                if revision_of_job_id:
                    if not parent_job: raise ValueError('原生成任务不存在，无法进行二次生成')
                    if not parent_result: raise ValueError('原图片版本不存在，无法进行二次生成')
                    parent_chain=_revision_job_chain(parent_job)
                    data['source']=str(_revision_job_value(parent_chain,'reportSource','') or '')
                    data['planIndex']=int(_revision_job_value(parent_chain,'planIndex',0) or 0)
                    # A revision is generated in the parent image's current
                    # mode. The edit text may change, but the identity,
                    # reference-display and fission branches must not drift
                    # because the history UI or a stale client omitted them.
                    data['referenceImages']=_revision_reference_images(parent_job)
                    data['matchReferenceShooting']=bool(_revision_job_value(parent_chain,'matchReferenceShooting',False))
                    data['fissionPattern']=bool(_revision_job_value(parent_chain,'fissionPattern',False))
                    data['userDirection']=_revision_job_value(parent_chain,'userDirection','') or ''
                    inherited_overrides=_revision_job_value(parent_chain,'promptOverrides',{})
                    inherited_overrides=inherited_overrides if isinstance(inherited_overrides,dict) else {}
                    requested_overrides=data.get('promptOverrides') if isinstance(data.get('promptOverrides'),dict) else {}
                    data['promptOverrides']={**inherited_overrides,**requested_overrides}
                    data['reuseAnalysisJobId']=revision_of_job_id
                    task_key=_result_task_key(parent_result)
                    data['selectedSlots']=[task_key]
                    data['assetTypes']=[parent_result.get('assetType') or task_key.split(':',1)[0]]
                    data['completeSet']=True
                    data['imageModels']=[{'id':parent_result.get('model') or '', 'quality':parent_result.get('quality') or ''}]
                    if data['fissionPattern'] and task_key!='main:1':
                        fission_base=_revision_fission_base(parent_job,parent_result)
                        if not fission_base: raise ValueError('原批次裂变基准图不存在，无法保持原商品设定重新生成')
                        data['fissionBaseReference']=fission_base
                    data['revisionNumber']=max(_next_result_revision_number(parent_job,parent_result),int(data.get('revisionNumber') or 0))
                    data['rootResultIds']={task_key:parent_result.get('rootResultId') or f"root_{uuid.uuid4().hex[:12]}"}
                    data['revisionReason']=str(data.get('revisionReason') or '').strip()
                    if not data['revisionReason']:
                        data['reusePrompt']=str(parent_result.get('prompt') or '').strip()
                report=_load_report_for_generation(data)
                exp=report.get('experienceSolution') or {}; plans=(exp.get('newProductPlans') or {}).get('plans') or report.get('launchPlans',{}).get('plans') or []
                if not plans: raise ValueError('报告没有可执行的新品推荐方案')
                idx=int(data.get('planIndex',0));
                if idx<0 or idx>=len(plans): raise ValueError('方案索引无效')
                chosen=plans[idx]
                resolve_reference_images(report,chosen,data.get('referenceImages'))
                available={f"{slot['assetType']}:{slot['index']}" for slot in build_generation_slots(report,chosen)}
                selected=data.get('selectedSlots') or []
                if selected and (not isinstance(selected,list) or any(key not in available for key in selected)):
                    raise ValueError('所选图片任务无效，请重新打开弹窗')
                job_id='img_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
                generation_round_id=(
                    str((parent_job or {}).get('generationRoundId') or
                        (parent_job or {}).get('roundId') or
                        revision_of_job_id or job_id)
                )
                round_type='revision' if revision_of_job_id else 'initial'
                match_reference_shooting=_match_reference_shooting(data, False)
                product=(report.get('facts') or {}).get('product') or {}
                IMAGE_JOBS[job_id]={'jobId':job_id,'status':'queued','progress':5,'results':[],'createdAt':time.time(),
                                    'planName':chosen.get('name') or '未命名开品方案',
                                    'productName':product.get('title') or '商品','reportSource':str(data.get('source') or ''),
                                    'planIndex':idx,'referenceImages':list(data.get('referenceImages') or []) if isinstance(data.get('referenceImages'),list) else [],
                                    'matchReferenceShooting':match_reference_shooting,
                                    'referenceShootingPolicy':'match_reference' if match_reference_shooting else 'identity_only',
                                    'revisionOfJobId':revision_of_job_id,'parentResultId':parent_result_id,
                                    'revisionReason':str(data.get('revisionReason') or '').strip(),
                                    'revisionNumber':max(1,int(data.get('revisionNumber') or 1)),
                                    'rootResultIds':data.get('rootResultIds') if isinstance(data.get('rootResultIds'),dict) else {},
                                    'promptOverrides':data.get('promptOverrides') if isinstance(data.get('promptOverrides'),dict) else {},
                                    'userDirection':data.get('userDirection') or '',
                                    'generationRoundId':generation_round_id,
                                    'roundType':round_type}
                data['generationRoundId']=generation_round_id
                data['roundType']=round_type
                _persist_image_job(job_id,IMAGE_JOBS[job_id])
                threading.Thread(target=_generation_worker,args=(job_id,report,data),daemon=True).start()
                self.send_json({'ok':True,'jobId':job_id,'statusUrl':f'/api/image-job/{job_id}',
                                'matchReferenceShooting':match_reference_shooting,
                                'referenceShootingPolicy':'match_reference' if match_reference_shooting else 'identity_only'})
            except Exception as e: self.send_json({'ok':False,'error':str(e)},400)
            return
        if self.path=='/api/image-generation-setup':
            try:
                n=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                report=_load_report_for_generation(data)
                # Setup is deterministic and read-only: no intent analysis or prompt construction.
                self.send_json(image_generation_setup(
                    report,data.get('planIndex',0),data.get('referenceImages'),
                    _match_reference_shooting(data,False),data.get('fissionPattern'),
                ))
            except Exception as e: self.send_json({'ok':False,'error':str(e)},400)
            return
        if self.path=='/api/image-prompt-preview':
            try:
                n=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                report=_load_report_for_generation(data)
                exp=report.get('experienceSolution') or {}; plans=(exp.get('newProductPlans') or {}).get('plans') or report.get('launchPlans',{}).get('plans') or []
                idx=int(data.get('planIndex',0))
                if not plans or idx<0 or idx>=len(plans): raise ValueError('方案索引无效')
                types=data.get('assetTypes') or ['main','detail']; types=[x for x in types if x in ('main','detail')]
                chosen=plans[idx]; slots=build_generation_slots(report,chosen)
                match_reference_shooting=_match_reference_shooting(data, False)
                refs,ref_source=resolve_reference_images(report,chosen,data.get('referenceImages'))
                fission_pattern=bool(data.get('fissionPattern', ref_source!='uploaded')) and ref_source!='uploaded' and not match_reference_shooting
                prompt_overrides=data.get('promptOverrides') if isinstance(data.get('promptOverrides'),dict) else {}
                blocked_terms=_report_visual_identity_terms(report)
                user_direction=_image_user_direction(data.get('userDirection'),blocked_terms)
                user_direction=_apply_product_overrides(
                    user_direction,
                    _collect_prompt_product_overrides(prompt_overrides,blocked_terms),
                )
                user_direction=_resolve_image_user_intent(report,chosen,slots,user_direction,prompt_overrides,refs,match_reference_shooting)
                identity_lock=build_identity_lock(
                    report,chosen,user_direction,
                    uploaded_product_identity=ref_source=='uploaded',
                )
                selected=[slot for slot in slots if slot['assetType'] in (types or ['main','detail'])]
                prompts={}; prompt_merges={}; user_direction_by_slot={}; annotated_selected=[]
                for slot in selected:
                    asset_type=slot['assetType']
                    slot_direction=_user_direction_for_slot(user_direction,slot)
                    prompt_key=f"{asset_type}:{slot.get('index')}"
                    user_direction_by_slot[prompt_key]=slot_direction
                    reference_mode=image_reference_mode(ref_source,fission_pattern,slot,match_reference_shooting)
                    _slot_refs,reference_meta=_slot_reference_images(
                        report,slot,refs,ref_source,reference_mode,match_reference_shooting,
                    )
                    slot=dict(slot); slot.update(reference_meta)
                    annotated_selected.append(slot)
                    base_prompt=build_image_prompt(
                        report, chosen, asset_type, slot['index']-1, slot, slot_direction,
                        reference_mode, identity_lock, match_reference_shooting,
                    )
                    prompt,prompt_merge=merge_image_prompt_with_user_edit(base_prompt,prompt_overrides.get(prompt_key),slot,slot_direction)
                    prompts.setdefault(asset_type,[]).append(prompt)
                    prompt_merges[prompt_key]=prompt_merge
                self.send_json({'ok':True,'slots':annotated_selected,'prompts':prompts,'promptMerges':prompt_merges,'userDirectionBySlot':user_direction_by_slot,
                                'referenceSource':ref_source,'referenceCount':len(refs),'fissionPattern':fission_pattern,
                                'matchReferenceShooting':match_reference_shooting,
                                'referenceShootingPolicy':'match_reference' if match_reference_shooting else 'identity_only',
                                'userDirection':user_direction})
            except Exception as e: self.send_json({'ok':False,'error':str(e)},400)
            return
        if self.path not in ('/api/analyze','/api/analyze-current'):
            self.send_json({'ok':False,'error':f'接口不存在：{urlparse(self.path).path}'},404); return
        try:
            c=load_config(); model_ready=configured()
            MODEL_PROBE=probe_model_api(timeout=15) if model_ready else {'ok':False,'stage':'config','error':'模型未配置，使用事实报告'}
            MODEL_PROBE_AT=time.time()
            n=int(self.headers.get('Content-Length','0'))
            payload=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
            if self.path=='/api/analyze-current':
                raw=payload.get('raw') if isinstance(payload,dict) else None
                allow_partial=True
            else:
                raw=payload
                allow_partial=False
            if not isinstance(raw,dict):
                self.send_json({'ok':False,'error':'分析数据格式错误：缺少 raw 商品数据'},400); return
            raw['_model_available']=bool(MODEL_PROBE.get('ok'))
            item_id=str(raw.get('product',{}).get('itemId') or '')
            if not item_id:
                self.send_json({'ok':False,'error':'采集数据缺少商品 itemId，请刷新商品页后重新采集'},400); return
            has_facts=bool(raw.get('product',{}).get('title') or raw.get('product',{}).get('shop') or raw.get('sales',{}).get('currentPrice') or raw.get('sku') or raw.get('attributes') or raw.get('images',{}).get('main'))
            if not has_facts:
                self.send_json({'ok':False,'error':'采集数据中商品字段为空，请确认淘宝已登录且详情加载完成'},400); return
            if not bool((raw.get('collection') or {}).get('reviewCollectionComplete')) and not allow_partial:
                self.send_json({'ok':False,'error':'评论尚未确认完整。如需立即分析，请使用“基于当前数据开始分析”。'},409); return
            mp=monitor_path(item_id).with_suffix('.json')
            if mp.exists():
                try: raw['monitoring']=json.loads(mp.read_text('utf-8'))
                except Exception: raw['monitoring']=[]
            tid='tmall_'+str(item_id or 'item')+'_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:5]
            summary=task_evidence_summary(raw);counts=summary['counts']
            TASKS[tid]={'status':'queued','progress':20,'evidenceSummary':summary,'steps':{'collect':'done','evidence':'waiting','planner':'waiting','product':'waiting','fashion':'waiting','visual':'not_collected' if not counts['main'] else 'waiting','merchandising':'waiting','detail':'not_collected' if not counts['detail'] else 'waiting','review':'waiting','qa':'waiting','competition':'waiting','strategy':'waiting','plans':'waiting','editor':'waiting','report':'waiting'},'createdAt':time.time()}
            threading.Thread(target=worker,args=(tid,raw),daemon=True).start()
            self.send_json({'ok':True,'taskId':tid,'taskUrl':f'http://127.0.0.1:{PORT}/task/{tid}'})
        except Exception as e: self.send_json({'ok':False,'error':str(e)},400)
    def do_GET(self):
        global MODEL_PROBE, MODEL_PROBE_AT
        p=urlparse(self.path).path
        if p=='/health':
            c=load_config(); self.send_json({'ok':True,'serverVersion':SERVER_VERSION,'referenceRoleVersion':REFERENCE_ROLE_VERSION,'modelConfigured':configured(),'model':c.get('model') or None,'imageModelConfigured':bool(c.get('image_model')),'imageModel':c.get('image_model') or None,'imageQuality':normalize_image_quality(c.get('image_quality')),'imageQualityOptions':list(IMAGE_QUALITY_OPTIONS),'imageModels':image_model_options(c),'apiBase':c.get('api_base') or None,'configPath':c.get('_config_path'),'configError':c.get('_config_error') or None,'modelProbe':MODEL_PROBE,'port':PORT}); return
        if p=='/api/prompts':
            saved={}
            if PROMPT_CONFIG.exists():
                try:
                    saved=json.loads(PROMPT_CONFIG.read_text('utf-8'))
                    if not isinstance(saved,dict): saved={}
                except Exception: pass
            self.send_json({'ok':True,'variables':PRODUCT_VARIABLES,'templates':{k:{'body':saved.get(k,{}).get('body',v.body),'variables':list(v.variables)} for k,v in TEMPLATES.items()}}); return
        if p=='/prompts':
            b=prompt_page().encode('utf-8'); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return
        if p=='/version':
            self.send_json({'ok':True,'serverVersion':SERVER_VERSION,'referenceRoleVersion':REFERENCE_ROLE_VERSION,'port':PORT}); return
        if p=='/api/model-test':
            MODEL_PROBE=probe_model_api(timeout=18); MODEL_PROBE_AT=time.time(); image_probe=probe_image_api(timeout=18)
            ok=bool(MODEL_PROBE.get('ok') and image_probe.get('ok') and image_probe.get('allImageModelsFound') is not False)
            self.send_json({'ok':ok,'analysis':MODEL_PROBE,'image':image_probe,'error':(MODEL_PROBE.get('error') or image_probe.get('error')) if not ok else None},200 if ok else 502); return
        if p.startswith('/api/monitor/'):
            item_id=p.rsplit('/',1)[-1]; mp=monitor_path(item_id).with_suffix('.json')
            if not mp.exists(): self.send_json({'ok':True,'days':0}); return
            try:
                rows=json.loads(mp.read_text('utf-8')); self.send_json({'ok':True,'days':len(rows),'firstSales':rows[0].get('salesDisplay') if rows else None,'lastSales':rows[-1].get('salesDisplay') if rows else None,'rows':rows}); return
            except Exception as e: self.send_json({'ok':False,'error':str(e)},500); return
        if p.startswith('/api/task/'):
            tid=p.rsplit('/',1)[-1]; t=TASKS.get(tid); self.send_json(t if t else {'error':'task not found'},200 if t else 404); return
        if re.fullmatch(r'/api/report-export/[A-Za-z0-9_-]+',p):
            report_id=p.rsplit('/',1)[-1]
            try:
                document=build_offline_report(report_id)
                self.send_bytes(document,'text/html; charset=utf-8',f'{report_id}-offline.html')
            except FileNotFoundError as e:
                self.send_json({'ok':False,'error':str(e)},404)
            except ValueError as e:
                self.send_json({'ok':False,'error':str(e)},409)
            except Exception as e:
                self.send_json({'ok':False,'error':f'离线报告制作失败：{e}'},500)
            return
        if re.fullmatch(r'/api/image-job/[^/]+/download',p):
            jid=p.split('/')[-2]
            try:
                archive=_image_job_archive(jid)
                self.send_bytes(archive,'application/zip',f'{jid}.zip')
            except FileNotFoundError as e:
                self.send_json({'ok':False,'error':str(e)},404)
            except ValueError as e:
                self.send_json({'ok':False,'error':str(e)},409)
            except Exception as e:
                self.send_json({'ok':False,'error':str(e)},500)
            return
        if p.startswith('/api/image-job/'):
            jid=p.rsplit('/',1)[-1]; job=IMAGE_JOBS.get(jid)
            if not job:
                saved=REPORTS/f'generated_{jid}.json'
                if saved.exists():
                    try: job=json.loads(saved.read_text('utf-8'))
                    except Exception: job=None
                    if isinstance(job,dict) and job.get('status') in ('queued','generating','running'):
                        job['status']='error'; job['progress']=100
                        job['error']='本地服务在生图过程中重启；已成功保存的图片仍可在下方查看，请重新提交未完成的图片任务。'
                        job['completedAt']=time.time()
                        try: _persist_image_job(jid,job)
                        except Exception: pass
            if isinstance(job,dict) and isinstance(job.get('results'),list):
                job=dict(job); job['results']=_ordered_generated_results(job['results'])
            self.send_json(job if job else {'error':'image job not found'},200 if job else 404); return
        if p=='/api/image-jobs':
            source=(parse_qs(urlparse(self.path).query).get('source') or [''])[0]
            jobs={k:dict(v) for k,v in IMAGE_JOBS.items()}
            # Checkpoints are named generated_<jobId>.json. Keep persisted
            # history visible after a local service restart as well as in-memory
            # jobs created by the current process.
            for saved in REPORTS.glob('generated_*.json'):
                try:
                    item=json.loads(saved.read_text('utf-8'))
                    if isinstance(item,dict) and item.get('jobId'): jobs[item['jobId']]=item
                except Exception: pass
            records=[x for x in jobs.values() if not source or x.get('reportSource')==source]
            for item in records:
                if isinstance(item.get('results'),list):
                    item['results']=_ordered_generated_results(item['results'])
            records.sort(key=lambda x:float(x.get('createdAt') or 0),reverse=True)
            self.send_json({'ok':True,'records':records[:50]}); return
        if p.startswith('/task/'):
            tid=p.rsplit('/',1)[-1]; b=task_page(tid).encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        if p=='/task.js':
            b=TASK_JS.encode();self.send_response(200);self.send_header('Content-Type','text/javascript; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        if p=='/report.css': self.send_file(ROOT/'report.css','text/css; charset=utf-8'); return
        if p=='/report.js': self.send_file(ROOT/'report.js','text/javascript; charset=utf-8'); return
        if p=='/report.html': self.send_file(ROOT/'report.html','text/html; charset=utf-8'); return
        if p.startswith('/reports/'):
            f=(REPORTS/p.split('/reports/',1)[1]).resolve()
            if REPORTS.resolve() not in f.parents:self.send_error(403);return
            # 兼容历史报告链接中遗漏 .json 后缀的情况。
            if not f.exists() and f.suffix=='' and f.with_suffix('.json').exists():
                f=f.with_suffix('.json')
            ctype=mimetypes.guess_type(str(f))[0] or 'application/octet-stream'
            if f.suffix=='.json':ctype='application/json; charset=utf-8'
            elif f.suffix=='.html':ctype='text/html; charset=utf-8'
            self.send_file(f,ctype);return
        if p=='/':
            b=control_page().encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        if p.startswith('/api/'):
            self.send_json({'ok':False,'error':f'接口不存在：{p}'},404); return
        self.send_error(404)

def main():
    print(f'Sansong Ecommerce Product Loop V{SERVER_VERSION} running: http://127.0.0.1:{PORT}',flush=True)
    print(f'Dedicated port {PORT}. Manual single-product collection; no recommendation scraping.',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),H).serve_forever()
if __name__=='__main__': main()
DYNAMIC_PARAM_FAMILIES = {
    '身份与合规':['品牌','产地','型号','执行标准','备案','许可证','等级'],
    '规格与选择':['尺寸','尺码','规格','颜色','口味','容量','重量','净含量','版本','配置'],
    '材质与成分':['材质','面料','成分','配料','配方','填充物'],
    '功能与适用':['功能','功效','适用','肤质','人群','场景','兼容'],
    '工艺与使用':['工艺','做工','版型','洗护','使用方法','保质期','储存','续航','性能'],
}
def evaluate_parameter_collection(attrs):
    keys=list((attrs or {}).keys())
    norm = {str(k).strip():str(v).strip() for k,v in (attrs or {}).items() if str(v).strip()}
    found=[]
    for canon, aliases in DYNAMIC_PARAM_FAMILIES.items():
        hit=False
        for k,v in norm.items():
            if any(a in k for a in aliases) and v:
                hit=True; break
        if hit: found.append(canon)
    status = 'collected' if norm else 'missing'
    return {
        'state':status,
        'stateText': {'collected':'参数已采集并等待类目分析','missing':'未识别到有效参数'}.get(status,'参数已采集'),
        'count': len(norm),
        'keys': keys[:50],
        'found': found,
        'missing': []
    }
