import json, os, re, ssl, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER_VERSION = '9.3.0'

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
    cfg['chat_path'] = str(cfg.get('chat_path','/chat/completions'))
    cfg['models_path'] = str(cfg.get('models_path','/models'))
    try: cfg['temperature'] = float(os.getenv('AI_TEMPERATURE', cfg.get('temperature',0.2)))
    except Exception: cfg['temperature'] = 0.2
    try: cfg['timeout'] = int(os.getenv('AI_TIMEOUT', cfg.get('timeout',120)))
    except Exception: cfg['timeout'] = 120
    try: cfg['retries'] = max(0, int(cfg.get('retries',2)))
    except Exception: cfg['retries'] = 2
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
        return {'ok':True,'stage':'models','http':200,'modelFound':(c['model'] in ids) if ids else None,'model':c['model'],'modelsCount':len(ids)}
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
