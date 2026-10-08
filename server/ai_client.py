import base64, json, os, re, ssl, time, uuid, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER_VERSION = '9.3.0'
IMAGE_QUALITY_OPTIONS = ('auto', 'low', 'medium', 'high', 'xhigh', 'max')

def normalize_image_quality(value):
    value = str(value or '').strip().lower()
    return value if value in IMAGE_QUALITY_OPTIONS else ''

def load_config():
    cfg = {}
    p = Path(os.getenv('AI_CONFIG_PATH') or ROOT/'config.json').expanduser()
    cfg['_config_path'] = str(p)
    cfg['_config_error'] = ''
    if p.exists():
        try:
            raw = p.read_text('utf-8').strip()
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('config.json 顶层必须是 JSON 对象')
            cfg.update(data)
        except json.JSONDecodeError as e:
            cfg['_config_error'] = f'config.json JSON 格式错误：第 {e.lineno} 行第 {e.colno} 列：{e.msg}'
        except Exception as e:
            cfg['_config_error'] = f'{type(e).__name__}: {e}'
    else:
        cfg['_config_error'] = 'config.json 不存在'
    cfg['api_base'] = os.getenv('AI_API_BASE', cfg.get('api_base','https://api.bananarouter.com/v1')).rstrip('/')
    cfg['api_key'] = os.getenv('AI_API_KEY', cfg.get('api_key',''))
    cfg['model'] = os.getenv('AI_MODEL', cfg.get('model',''))
    cfg['image_api_base'] = os.getenv('IMAGE_API_BASE', cfg.get('image_api_base','')).rstrip('/')
    cfg['image_api_key'] = os.getenv('IMAGE_API_KEY', cfg.get('image_api_key',''))
    cfg['image_model'] = os.getenv('IMAGE_MODEL', cfg.get('image_model',''))
    cfg['image_quality'] = normalize_image_quality(os.getenv('IMAGE_QUALITY', cfg.get('image_quality','')))
    raw_image_models = os.getenv('IMAGE_MODELS', cfg.get('image_models', []))
    if isinstance(raw_image_models, str):
        raw_image_models = [x.strip() for x in raw_image_models.replace('\n', ',').split(',') if x.strip()]
    if not isinstance(raw_image_models, list):
        raw_image_models = []
    image_models = []
    for item in raw_image_models:
        if isinstance(item, dict):
            model_id = str(item.get('id') or item.get('model') or '').strip()
            label = str(item.get('label') or model_id).strip()
            quality = normalize_image_quality(item.get('quality'))
        else:
            model_id = str(item or '').strip()
            label = model_id
            quality = ''
        if model_id and not any(x['id'] == model_id for x in image_models):
            image_models.append({'id': model_id, 'label': label or model_id, 'quality': quality})
    default_image_model = str(cfg['image_model'] or '').strip()
    if default_image_model and not any(x['id'] == default_image_model for x in image_models):
        image_models.insert(0, {'id': default_image_model, 'label': default_image_model, 'quality': cfg['image_quality']})
    for item in image_models:
        if not item.get('quality'):
            item['quality'] = cfg['image_quality']
    cfg['image_models'] = image_models
    cfg['chat_path'] = str(cfg.get('chat_path','/chat/completions'))
    cfg['models_path'] = str(cfg.get('models_path','/models'))
    cfg['image_models_path'] = str(cfg.get('image_models_path','/models'))
    try: cfg['temperature'] = float(os.getenv('AI_TEMPERATURE', cfg.get('temperature',0.2)))
    except Exception: cfg['temperature'] = 0.2
    try: cfg['timeout'] = int(os.getenv('AI_TIMEOUT', cfg.get('timeout',120)))
    except Exception: cfg['timeout'] = 120
    try: cfg['retries'] = max(0, int(cfg.get('retries',2)))
    except Exception: cfg['retries'] = 2
    try: cfg['image_concurrency'] = max(1, min(5, int(os.getenv('IMAGE_CONCURRENCY', cfg.get('image_concurrency',5)))))
    except Exception: cfg['image_concurrency'] = 5
    cfg['extra_headers'] = cfg.get('extra_headers',{}) or {}
    cfg['ca_bundle'] = str(cfg.get('ca_bundle','') or '')
    cfg['ssl_verify'] = bool(cfg.get('ssl_verify', True))
    return cfg

def configured():
    c=load_config()
    key=str(c.get('api_key') or '').strip(); model=str(c.get('model') or '').strip()
    return bool(not c.get('_config_error') and key and model and not key.startswith('YOUR_') and not model.startswith('YOUR_'))

def _ssl_context(c):
    if not c.get('ssl_verify', True):
        raise RuntimeError('ssl_verify=false 被禁止。V6.2 不允许关闭 HTTPS 证书校验。')
    cafile = c.get('ca_bundle') or ''
    bundled = ROOT/'cacert.pem'
    if not cafile and bundled.exists(): cafile=str(bundled)
    if cafile:
        if not Path(cafile).exists():
            raise RuntimeError(f'ca_bundle 文件不存在：{cafile}')
        ctx=ssl.create_default_context(cafile=cafile)
    else:
        try:
            import certifi
            ctx=ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx=ssl.create_default_context()
    try: ctx.minimum_version=ssl.TLSVersion.TLSv1_2
    except Exception: pass
    return ctx

def _headers(c):
    h={'Content-Type':'application/json','Accept':'application/json','Authorization':'Bearer '+c['api_key'],'User-Agent':'TmallAIProductAnalysis/9.3.0'}
    h.update(c.get('extra_headers',{}))
    return h

def image_channel(c=None):
    """Return the independently configured image provider; never borrow analysis credentials."""
    source=dict(c or load_config())
    source['api_base']=str(source.get('image_api_base') or '').rstrip('/')
    source['api_key']=str(source.get('image_api_key') or '')
    source['models_path']=str(source.get('image_models_path') or '/models')
    return source

def image_model_options(c=None):
    """Return configured image models while keeping the legacy single-model field."""
    source = c if isinstance(c, dict) else load_config()
    options = source.get('image_models') or []
    result = []
    for item in options:
        if isinstance(item, dict):
            model_id = str(item.get('id') or item.get('model') or '').strip()
            label = str(item.get('label') or model_id).strip()
            quality = normalize_image_quality(item.get('quality'))
        else:
            model_id = str(item or '').strip()
            label = model_id
            quality = ''
        if model_id and not any(x['id'] == model_id for x in result):
            result.append({'id': model_id, 'label': label or model_id, 'quality': quality})
    legacy = str(source.get('image_model') or '').strip()
    if legacy and not any(x['id'] == legacy for x in result):
        result.insert(0, {'id': legacy, 'label': legacy, 'quality': normalize_image_quality(source.get('image_quality'))})
    default_quality = normalize_image_quality(source.get('image_quality'))
    for item in result:
        if not item.get('quality'):
            item['quality'] = default_quality
    return result

def probe_image_api(timeout=15):
    c=image_channel()
    options=image_model_options(c)
    model=str(c.get('image_model') or (options[0]['id'] if options else '')).strip()
    if not c.get('api_base') or not c.get('api_key') or not options:
        return {'ok':False,'stage':'image_config','error':'生图渠道 API Base、API Key 或生图模型未配置'}
    try:
        req=urllib.request.Request(_join(c['api_base'],c['models_path']),headers=_headers(c),method='GET')
        with urllib.request.urlopen(req,timeout=min(timeout,c['timeout']),context=_ssl_context(c)) as r:
            obj=json.loads(r.read().decode('utf-8','ignore') or '{}')
        ids=[x.get('id') for x in (obj.get('data') or []) if isinstance(x,dict)]
        model_checks=[{'id':item['id'],'label':item['label'],'quality':item.get('quality') or '',
                       'found':(item['id'] in ids) if ids else None} for item in options]
        return {'ok':True,'stage':'image_models','http':200,'imageModel':model,
                'imageModelFound':(model in ids) if ids else None,'modelsCount':len(ids),
                'imageModels':model_checks,
                'allImageModelsFound':all(item['found'] is not False for item in model_checks),
                'separateChannel':bool(c.get('image_api_base') or c.get('image_api_key'))}
    except urllib.error.HTTPError as e:
        body=e.read().decode('utf-8','ignore')
        return {'ok':False,'stage':'image_models','http':e.code,'error':body[:500] or str(e),'imageModel':model}
    except Exception as e:
        return {'ok':False,'stage':'image_network','error':str(e),'imageModel':model}

def _join(base,path):
    path='/' + str(path or '').lstrip('/')
    return base.rstrip('/') + path

def probe_model_api(timeout=15):
    c=load_config()
    if c.get('_config_error'):
        return {'ok':False,'stage':'config','error':c['_config_error']}
    if not c.get('api_key') or not c.get('model'):
        return {'ok':False,'stage':'config','error':'api_key 或 model 为空'}
    try:
        req=urllib.request.Request(_join(c['api_base'],c['models_path']),headers=_headers(c),method='GET')
        with urllib.request.urlopen(req,timeout=min(timeout,c['timeout']),context=_ssl_context(c)) as r:
            obj=json.loads(r.read().decode('utf-8','ignore') or '{}')
        ids=[x.get('id') for x in (obj.get('data') or []) if isinstance(x,dict)]
        image_model=str(c.get('image_model') or '').strip()
        return {'ok':True,'stage':'models','http':200,'modelFound':(c['model'] in ids) if ids else None,'model':c['model'],
                'imageModelConfigured':bool(image_model),'imageModel':image_model or None,
                'imageModelFound':(image_model in ids) if ids and image_model else None,'modelsCount':len(ids)}
    except urllib.error.HTTPError as e:
        body=e.read().decode('utf-8','ignore')
        return {'ok':False,'stage':'models','http':e.code,'error':body[:500] or str(e)}
    except ssl.SSLCertVerificationError as e:
        return {'ok':False,'stage':'ssl','error':f'SSL证书验证失败：{e}. V6.2 已优先使用 certifi；如仍失败，请确认 Python/代理没有替换证书链。'}
    except Exception as e:
        return {'ok':False,'stage':'network','error':str(e)}

def _parse_json(s):
    if isinstance(s, dict): return s
    s = (s or '').strip()
    s = re.sub(r'^```(?:json)?\s*|\s*```$', '', s, flags=re.I|re.S)
    try: return json.loads(s)
    except Exception:
        a=s.find('{'); b=s.rfind('}')
        if a>=0 and b>a: return json.loads(s[a:b+1])
        raise

def _do_post(c,payload):
    req=urllib.request.Request(_join(c['api_base'],c['chat_path']),data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers=_headers(c),method='POST')
    with urllib.request.urlopen(req,timeout=c['timeout'],context=_ssl_context(c)) as r:
        return json.loads(r.read().decode('utf-8','ignore'))

def image_generate(prompt, size='1024x1024', n=1, model=None, reference_images=None, quality=None, style=None):
    """Generate commerce images through an OpenAI-compatible images endpoint.

    Image generation is deliberately separate from chat generation: operators can
    keep a text model for analysis and configure a dedicated image model/path in
    config.json. The return value is the provider response so the server can
    persist both URL and base64 responses locally.
    """
    c=image_channel()
    if c.get('_config_error'):
        raise RuntimeError(c['_config_error'])
    if not c.get('api_key'):
        raise RuntimeError('未配置 API Key，无法生成图片。')
    image_model=str(model or c.get('image_model') or '').strip()
    if not image_model:
        raise RuntimeError('未配置独立的生图模型 image_model。请在本地服务配置页与分析模型一起填写。')
    try: count=max(1,min(8,int(n)))
    except Exception: count=1
    payload={
        'model':image_model,
        'prompt':str(prompt or '').strip(),
        'size':str(size or c.get('image_size') or '1024x1024'),
        'n':count,
    }
    quality_value=normalize_image_quality(c.get('image_quality') if quality is None else quality)
    if quality_value: payload['quality']=quality_value
    style_value=c.get('image_style') if style is None else style
    if style_value: payload['style']=style_value
    path=str(c.get('image_path') or '/images/generations')
    last=None
    refs=[str(x).strip() for x in (reference_images or []) if str(x).strip()]
    if len(refs)>4:
        raise ValueError('单次生图最多四张参考图，不能静默丢弃输入')
    # GPT Image reference inputs belong to the image-edit contract regardless
    # of which OpenAI-compatible gateway hosts the model. Sending guessed JSON
    # fields to /images/generations can succeed while the gateway silently
    # ignores every reference image, producing an ungrounded text-to-image
    # result. Use multipart /images/edits whenever a gpt-image model has refs.
    edit_request=bool(refs and (
        image_model.startswith('gpt-image-') or path.rstrip('/').endswith('/images/edits')
    ))
    if edit_request and path.rstrip('/').endswith('/images/generations'):
        path=path.rstrip('/')[:-len('generations')]+'edits'
    variants=[]
    if edit_request:
        variants=[payload]
    elif refs:
        # OpenAI-compatible image gateways use different names for image guidance.
        # Try the common JSON shapes, but never silently drop a requested reference.
        for key in ('image','reference_images','images'):
            v=dict(payload); v[key]=refs[0] if key=='image' and len(refs)==1 else refs; variants.append(v)
    else:
        variants=[payload]
    # Gateways differ: retry without optional fields before failing the job.
    if not edit_request and ('quality' in payload or 'style' in payload):
        clean=[]
        for item in variants:
            v=dict(item); v.pop('quality',None); v.pop('style',None); clean.append(v)
        variants.extend(clean)
    retryable_http=(408,409,429,500,502,503,504)
    # Try payload aliases only when the provider rejects a shape. A transport
    # failure must retry the same request after backoff; cycling every alias on
    # a TLS EOF/reset creates a burst of duplicate generation requests.
    for variant in variants:
        shape_rejected=False
        for attempt in range(c['retries']+1):
            try:
                return _do_image_edit(c,path,variant,refs) if edit_request else _do_post_path(c,path,variant)
            except urllib.error.HTTPError as e:
                body=e.read().decode('utf-8','ignore')
                if e.code in (502,503,504):
                    last=RuntimeError(f'生图网关暂时不可用（HTTP {e.code}），系统已自动重试；请稍后仅重试失败图片')
                elif body.lstrip().lower().startswith(('<!doctype html','<html')):
                    last=RuntimeError(f'图片接口 HTTP {e.code}：上游返回了网页错误页')
                else:
                    last=RuntimeError(f'图片接口 HTTP {e.code}: {body[:900]}')
                if e.code==400:
                    if edit_request:
                        raise last
                    shape_rejected=True
                    break
                if e.code not in retryable_http:
                    raise last
            except Exception as e:
                last=RuntimeError(f'图片接口调用失败: {e}')
            if attempt<c['retries']:
                time.sleep(min(2 ** attempt * 2,8))
        if not shape_rejected:
            raise last or RuntimeError('图片接口调用失败')
    raise last or RuntimeError('图片接口调用失败')

def _do_image_edit(c,path,payload,refs):
    """Send ordered, actual image files using the provider's edit contract."""
    boundary='tmall_image_'+uuid.uuid4().hex
    chunks=[]
    for key,value in payload.items():
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode('utf-8'))
    for index,ref in enumerate(refs,1):
        if not ref.startswith('data:image/') or ',' not in ref:
            raise ValueError('编辑接口必须接收已读取的图片数据，不能传远程链接')
        head,encoded=ref.split(',',1)
        if ';base64' not in head:
            raise ValueError('参考图必须使用 Base64 图片数据')
        data=base64.b64decode(encoded,validate=True)
        mime=head[5:].split(';',1)[0].lower()
        formats={'image/png':('png',data.startswith(b'\x89PNG\r\n\x1a\n')),
                 'image/jpeg':('jpg',data.startswith(b'\xff\xd8\xff')),
                 'image/webp':('webp',data[:4]==b'RIFF' and data[8:12]==b'WEBP')}
        if mime not in formats or not formats[mime][1] or len(data)>16*1024*1024:
            raise ValueError('参考图类型、数据签名或大小不符合编辑接口要求')
        ext=formats[mime][0]
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="reference-{index}.{ext}"\r\nContent-Type: {mime}\r\n\r\n').encode('ascii'))
        chunks.extend((data,b'\r\n'))
    chunks.append(f'--{boundary}--\r\n'.encode('ascii'))
    headers=_headers(c);headers['Content-Type']='multipart/form-data; boundary='+boundary
    req=urllib.request.Request(_join(c['api_base'],path),data=b''.join(chunks),headers=headers,method='POST')
    with urllib.request.urlopen(req,timeout=c['timeout'],context=_ssl_context(c)) as response:
        return json.loads(response.read().decode('utf-8','ignore'))

def _do_post_path(c,path,payload):
    req=urllib.request.Request(_join(c['api_base'],path),data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers=_headers(c),method='POST')
    with urllib.request.urlopen(req,timeout=c['timeout'],context=_ssl_context(c)) as r:
        return json.loads(r.read().decode('utf-8','ignore'))

def chat_json(system, user, images=None, max_tokens=5000):
    c=load_config()
    if c.get('_config_error'):
        raise RuntimeError(c['_config_error'])
    if not c.get('api_key') or not c.get('model'):
        raise RuntimeError('未配置模型。请复制 config.example.json 为 config.json，并填写 api_key 与 model。')
    content=[{'type':'text','text':user}]
    for url in (images or [])[:12]:
        if isinstance(url,str) and url.startswith(('http://','https://','data:image/')):
            content.append({'type':'image_url','image_url':{'url':url}})
    base_payload={
        'model':c['model'],
        'messages':[{'role':'system','content':system},{'role':'user','content':content if len(content)>1 else user}],
        'temperature':c['temperature'],
        'response_format':{'type':'json_object'},
        'max_tokens':max_tokens
    }
    variants=[base_payload]
    # Some OpenAI-compatible gateways/models reject response_format, temperature, or max_tokens.
    v2=dict(base_payload); v2.pop('response_format',None); variants.append(v2)
    v3=dict(v2); v3.pop('temperature',None); v3['max_completion_tokens']=v3.pop('max_tokens',max_tokens); variants.append(v3)
    last=None
    for attempt in range(c['retries']+1):
        for payload in variants:
            try:
                obj=_do_post(c,payload)
                try: return _parse_json(obj['choices'][0]['message']['content'])
                except Exception as e: raise RuntimeError(f'模型返回无法解析为 JSON: {e}')
            except urllib.error.HTTPError as e:
                body=e.read().decode('utf-8','ignore')
                last=RuntimeError(f'模型接口 HTTP {e.code}: {body[:900]}')
                if e.code not in (400,408,409,429,500,502,503,504): raise last
            except ssl.SSLCertVerificationError as e:
                raise RuntimeError(f'SSL证书验证失败：{e}。V6.2 已使用 certifi CA；请检查本机 Python/代理证书链。')
            except Exception as e:
                last=RuntimeError(f'模型接口调用失败: {e}')
        if attempt<c['retries']:
            time.sleep(min(1.5*(attempt+1),4))
    # 电商详情页偶有 1-2px 占位图或超长切片；部分多模态模型会拒绝整批图片。
    # 证据文本仍在 user 中，因此自动改用纯文本证据重试，不能让单张坏图吞掉整份报告。
    if images and last and 'image length and width' in str(last).lower():
        return chat_json(system, user, images=None, max_tokens=max_tokens)
    raise last or RuntimeError('模型接口调用失败')
