import json, os, threading, time, uuid, traceback, html, base64, csv, io, zipfile, re, mimetypes, hashlib, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote_to_bytes
from pathlib import Path
from analysis import analyze, normalize
from renderer import render
from ai_client import configured, load_config, probe_model_api
from prompt_templates import TEMPLATES, PRODUCT_VARIABLES

ROOT=Path(__file__).resolve().parent
PROMPT_CONFIG=ROOT/'prompts.json'
REPORTS=ROOT/'reports'; REPORTS.mkdir(exist_ok=True)
MONITOR_DIR=ROOT/'monitor_data'; MONITOR_DIR.mkdir(exist_ok=True)
PORT=int(os.getenv('TMALL_AI_PORT','17962'))
SERVER_VERSION='9.3.0'
MODEL_PROBE={'ok':False,'stage':'startup','error':'尚未检测'}
MODEL_PROBE_AT=0
TASKS={}
LOCK=threading.Lock()


IMAGE_ASSET_ROOT=REPORTS/'assets'; IMAGE_ASSET_ROOT.mkdir(exist_ok=True)

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
            with urllib.request.urlopen(req,timeout=timeout) as r:
                data=r.read(16*1024*1024+1)
                if len(data)>16*1024*1024:raise ValueError('image too large')
                ctype=r.headers.get('Content-Type','')
            if not _looks_like_image(data,ctype):raise ValueError('not image response')
            return data,ctype
        except Exception as ex:last=ex
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
        result=analyze(raw,progress)
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
    p=ROOT/'config.json'
    old={}
    if p.exists():
        try: old=json.loads(p.read_text('utf-8'))
        except Exception: old={}
    key=str(data.get('api_key','')).strip()
    if not key: key=str(old.get('api_key','')).strip()
    cfg={
      'api_base':str(data.get('api_base') or old.get('api_base') or 'https://api.bananarouter.com/v1').strip().rstrip('/'),
      'api_key':key,
      'model':str(data.get('model') or old.get('model') or 'gpt-5.5').strip(),
      'chat_path':'/chat/completions','models_path':'/models','temperature':0.2,'timeout':120,'retries':2,
      'ssl_verify':True,'ca_bundle':'','extra_headers':{}
    }
    tmp=p.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),'utf-8')
    tmp.replace(p)
    return cfg

def control_page():
    global MODEL_PROBE, MODEL_PROBE_AT
    c=load_config(); is_cfg=configured()
    if is_cfg and (time.time()-MODEL_PROBE_AT>30):
        MODEL_PROBE=probe_model_api(timeout=12); MODEL_PROBE_AT=time.time()
    api_ok=bool(MODEL_PROBE.get('ok'))
    base=html.escape(str(c.get('api_base') or 'https://api.bananarouter.com/v1'))
    model=html.escape(str(c.get('model') or 'gpt-5.5'))
    cfg_err=html.escape(str(c.get('_config_error') or ''))
    probe=html.escape(str(MODEL_PROBE.get('error') or ''))
    key_state='已保存' if str(c.get('api_key') or '').strip() and not str(c.get('api_key')).startswith('YOUR_') else '未填写'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>三笙 · 电商商品分析闭环 V{SERVER_VERSION}</title><style>
    *{{box-sizing:border-box}}body{{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;background:#f5faf9;color:#10191d;margin:0}}.wrap{{max-width:900px;margin:54px auto;padding:0 24px}}.hero{{background:#071114;color:#fff;padding:34px;border-radius:22px;border-top:5px solid #00cdb0}}h1{{font-size:38px;margin:0 0 10px}}.sub{{color:#b9d0d4}}.card{{margin-top:18px;background:#fff;border:1px solid #dbe8e8;border-radius:18px;padding:24px}}.status{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.pill{{padding:14px;border-radius:12px;background:#eef9f7;font-weight:700}}.ok{{color:#008c78}}.bad{{color:#c54552}}label{{display:block;font-size:13px;font-weight:700;margin:16px 0 7px}}input{{width:100%;padding:13px 14px;border:1px solid #bcd8d6;border-radius:10px;font-size:15px}}button{{margin-top:18px;border:0;border-radius:10px;padding:13px 18px;background:linear-gradient(110deg,#00cdb0,#008fd8);color:white;font-weight:800;font-size:15px;cursor:pointer}}button.secondary{{background:#071114;margin-left:8px}}#msg{{margin-top:12px;white-space:pre-wrap}}code{{background:#eaf7f5;padding:3px 6px;border-radius:5px}}@media(max-width:700px){{.status{{grid-template-columns:1fr}}}}
    </style></head><body><div class="wrap"><section class="hero"><div style="font-size:12px;letter-spacing:.16em;color:#12d8bb;font-weight:800">ONE-CLICK LOCAL SERVICE</div><h1>三笙 · 电商商品分析引擎 V{SERVER_VERSION}</h1><div class="sub">单商品手动深采；类目不限，参数与SKU动态识别，评论可持续采集，也可随时基于当前数据开始分析。</div></section>
    <section class="card"><div class="status"><div class="pill">本地服务<br><span class="ok">运行正常 · V{SERVER_VERSION}</span></div><div class="pill">模型配置<br><span class="{'ok' if is_cfg else 'bad'}">{'已配置 '+model if is_cfg else '待配置'}</span></div><div class="pill">API连接<br><span class="{'ok' if api_ok else 'bad'}">{'连通 ✓' if api_ok else '待检测/失败'}</span></div></div></section>
    <section class="card"><h2 style="margin-top:0">首次只需要填一次 API Key</h2><p style="color:#667067">默认已为 BananaRouter + gpt-5.5 配好。API Key 只保存在本机 <code>server/config.json</code>，不会写入 Chrome 扩展。</p>
    <label>API Base</label><input id="base" value="{base}"><label>API Key（{key_state}）</label><input id="key" type="password" placeholder="粘贴新的 sk-...；已保存时可留空"><label>模型</label><input id="model" value="{model}">
    <button onclick="save()">保存并测试连接</button><button class="secondary" onclick="test()">仅重新测试</button><div id="msg">{'配置错误：'+cfg_err if cfg_err else ('API错误：'+probe if (is_cfg and not api_ok and probe) else '')}</div></section>
    <section class="card"><h2 style="margin-top:0">下一步</h2><p>Chrome 只需加载一次 <code>extension</code> 文件夹。之后每次使用：双击启动 → 打开已登录的天猫商品页 → 可选导入监测数据 → 点击扩展“开始深度采集”。</p></section></div>
    <script>
    async function save(){{const msg=document.getElementById('msg');msg.textContent='正在保存并测试…';const r=await fetch('/api/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{api_base:base.value,api_key:key.value,model:model.value}})}});const d=await r.json();msg.textContent=d.ok?'✓ 配置已保存，API连接正常。现在可以去天猫商品页运行扩展。':'✕ '+(d.error||'配置失败');if(d.ok)setTimeout(()=>location.reload(),600)}}
    async function test(){{const msg=document.getElementById('msg');msg.textContent='正在测试…';const r=await fetch('/api/model-test');const d=await r.json();msg.textContent=d.ok?'✓ API连接正常，模型 '+(d.model||'')+' 可用。':'✕ '+(d.error||'连接失败')}}
    </script></body></html>'''

def prompt_page():
    saved={}
    if PROMPT_CONFIG.exists():
        try: saved=json.loads(PROMPT_CONFIG.read_text('utf-8'))
        except Exception: saved={}
    items={k:{'name':v.name,'body':saved.get(k,{}).get('body',v.body),'variables':list(v.variables)} for k,v in TEMPLATES.items()}
    vars_html=''.join(f'<div class="var"><b>{html.escape(k)}</b><br>{html.escape(v)}</div>' for k,v in PRODUCT_VARIABLES.items())
    template_html=''.join(f'<section class="card"><h2>{html.escape(k)}</h2><p>变量：{html.escape("、".join(v["variables"]) or "自定义")}</p><textarea data-key="{html.escape(k)}">{html.escape(v["body"])}</textarea></section>' for k,v in items.items())
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<title>提示词配置</title><style>body{font-family:-apple-system,BlinkMacSystemFont,PingFang SC,sans-serif;background:#f5faf9;margin:0}.wrap{max-width:1100px;margin:30px auto;padding:0 20px}.card{background:#fff;border:1px solid #dbe8e8;border-radius:16px;padding:22px;margin:16px 0}textarea{width:100%;min-height:260px;font:14px monospace;padding:12px;border:1px solid #bcd8d6;border-radius:10px}button{background:#008f7a;color:#fff;border:0;border-radius:9px;padding:12px 18px;font-weight:700;cursor:pointer}.vars{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}.var{background:#eef9f7;padding:10px;border-radius:8px;font-size:13px}</style>'
      '<div class="wrap"><h1>提示词可视化配置</h1><p>编辑后保存，下一次分析任务生效。</p><section class="card"><h2>商品变量说明</h2><div class="vars">'+vars_html+'</div></section>'+template_html
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
        b=p.read_bytes();self.send_response(200);self.cors();self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_OPTIONS(self): self.send_response(204);self.cors();self.end_headers()
    def do_POST(self):
        global MODEL_PROBE, MODEL_PROBE_AT
        if self.path=='/api/prompts':
            try:
                n=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                templates=data.get('templates') if isinstance(data.get('templates'),dict) else {}
                clean={k:{'body':str(v.get('body',''))[:100000]} for k,v in templates.items() if k in TEMPLATES and isinstance(v,dict)}
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
                self.send_json({'ok':True,'model':load_config().get('model'),'probe':MODEL_PROBE}); return
            except Exception as e: self.send_json({'ok':False,'error':str(e)},400); return
        if self.path not in ('/api/analyze','/api/analyze-current'): self.send_error(404);return
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
            c=load_config(); self.send_json({'ok':True,'serverVersion':SERVER_VERSION,'modelConfigured':configured(),'model':c.get('model') or None,'apiBase':c.get('api_base') or None,'configPath':c.get('_config_path'),'configError':c.get('_config_error') or None,'modelProbe':MODEL_PROBE,'port':PORT}); return
        if p=='/api/prompts':
            saved={}
            if PROMPT_CONFIG.exists():
                try: saved=json.loads(PROMPT_CONFIG.read_text('utf-8'))
                except Exception: pass
            self.send_json({'ok':True,'variables':PRODUCT_VARIABLES,'templates':{k:{'body':saved.get(k,{}).get('body',v.body),'variables':list(v.variables)} for k,v in TEMPLATES.items()}}); return
        if p=='/prompts':
            b=prompt_page().encode('utf-8'); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return
        if p=='/version':
            self.send_json({'ok':True,'serverVersion':SERVER_VERSION,'port':PORT}); return
        if p=='/api/model-test':
            MODEL_PROBE=probe_model_api(timeout=18); MODEL_PROBE_AT=time.time(); self.send_json(MODEL_PROBE,200 if MODEL_PROBE.get('ok') else 502); return
        if p.startswith('/api/monitor/'):
            item_id=p.rsplit('/',1)[-1]; mp=monitor_path(item_id).with_suffix('.json')
            if not mp.exists(): self.send_json({'ok':True,'days':0}); return
            try:
                rows=json.loads(mp.read_text('utf-8')); self.send_json({'ok':True,'days':len(rows),'firstSales':rows[0].get('salesDisplay') if rows else None,'lastSales':rows[-1].get('salesDisplay') if rows else None,'rows':rows}); return
            except Exception as e: self.send_json({'ok':False,'error':str(e)},500); return
        if p.startswith('/api/task/'):
            tid=p.rsplit('/',1)[-1]; t=TASKS.get(tid); self.send_json(t if t else {'error':'task not found'},200 if t else 404); return
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
            ctype=mimetypes.guess_type(str(f))[0] or 'application/octet-stream'
            if f.suffix=='.json':ctype='application/json; charset=utf-8'
            elif f.suffix=='.html':ctype='text/html; charset=utf-8'
            self.send_file(f,ctype);return
        if p=='/':
            b=control_page().encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
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
