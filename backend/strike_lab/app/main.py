import asyncio,csv,io,json,os,sys,time,hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from collections import OrderedDict
from datetime import datetime,timezone
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import Field
from .models import Model,StudyInput,CompareRequest,FutuRequest
from .engine import implied_spot,analyze,compare,VERSION,close_at
from .retention import LatestSnapshot,market_window
ROOT=Path(__file__).resolve().parent
latest=LatestSnapshot(ROOT.parent/'runtime'/'latest-market.json')
last_window=None

QUOTE_INTERVAL_SECONDS=10

def utc_now():
    return datetime.now(timezone.utc)

def maintain():
    global last_window,status_cache
    now=utc_now()
    window=market_window(now)
    if window!=last_window:
        records.clear()
        futu_cache.clear()
        status_cache=None
        last_window=window
    latest.current(now)
    return window

async def maintain_loop():
    while True:
        window=maintain()
        boundary=window['closedAt'] if window['isOpen'] else window['expiresAt']
        seconds=(datetime.fromisoformat(boundary)-utc_now()).total_seconds()
        await asyncio.sleep(max(.05,min(60,seconds)))

@asynccontextmanager
async def lifespan(app):
    maintain()
    task=asyncio.create_task(maintain_loop())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)

app=FastAPI(title='执行价研究室 · 独立版',version='1.6.0',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','[::1]','testserver'])
records=OrderedDict();futu_cache={};futu_lock=asyncio.Lock();last_attempt=0.;status_cache=None

def remember(study,source,notes=None,report=None,extra=None,request_window=None):
    payload=study.model_dump(mode='json') if study else None
    result=report if report is not None else analyze(study)
    result['notes']=(notes or [])+result['notes']
    key=hashlib.sha256(json.dumps([payload,result,source],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    item=dict(id=key,source=source,input=payload,report=result,createdAt=datetime.now(timezone.utc).isoformat(),**(extra or {}))
    window=maintain()
    if source=='FUTU':
        if request_window is not None and request_window!=window:
            raise HTTPException(409,'交易时段已切换，请重新获取报价。')
        return latest.save(item,window['expiresAt'])
    records[key]=item;records.move_to_end(key)
    while len(records)>(8 if window['isOpen'] else 1):records.popitem(last=False)
    return item

def get_record(key):
    maintain()
    if latest.item and latest.item['id']==key:
        item=latest.item
        report=item['report']
        for mode in report['modes'].values():
            spot=mode.get('impliedSpot')
            if spot is not None and 'mean' not in spot:
                spot['mean']=implied_spot(mode['rows'], report['rate'], report['T'])['mean']
        return item
    if key not in records:raise HTTPException(404,'该研究快照已失效，请重新读取报价或导入文件。')
    return records[key]

@app.middleware('http')
async def local_write(request:Request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin');port=os.getenv('STRIKE_LAB_PORT','3200')
        if request.scope.get('root_path') == '/api/strike-lab':
            port=os.getenv('FRONTEND_PORT','3000')
        if origin and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
            return JSONResponse({'detail':'只接受本机研究室页面的写入请求'},403)
    response=await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(ValueError)
async def invalid(request,exc):return JSONResponse({'detail':str(exc)[:600]},422)
@app.get('/api/health')
def health():return dict(status='OK',application='option-value-lab',version=VERSION,independent=True,processId=os.getpid(),projectId=hashlib.sha256(str(ROOT.parent).encode()).hexdigest()[:16])
@app.post('/api/analyze')
async def calculate(study:StudyInput):return remember(study,'MANUAL',['人工输入；未独立核实数据来源和事件时间。'])
@app.post('/api/studies/{key}/compare')
async def compare_study(key:str,body:CompareRequest):
    item=get_record(key)
    return dict(studyId=key,source=item['source'],valuationAt=item['report']['valuationAt'],
                **compare(StudyInput.model_validate(item['input']),body.strikes,body.basis))
@app.get('/api/studies/{key}/export')
async def export(key:str):
    return JSONResponse(get_record(key),headers={'Content-Disposition':f'attachment; filename="strike-study-{key}.json"'})

class ImportRequest(Model):
    content:str=Field(max_length=1000000)
    format:str=Field(pattern='^(json|csv)$')
    settings:dict=Field(default_factory=dict)
@app.post('/api/import')
async def import_data(body:ImportRequest):
    if body.format=='json':
        try:data=json.loads(body.content)
        except json.JSONDecodeError:raise ValueError('JSON 格式不正确')
        if not isinstance(data,dict):raise ValueError('JSON 顶层应为对象')
        data=data.get('input',data)
        if data is None:raise ValueError('示意例不含原始报价，无法作为行情导入')
    else:
        reader=csv.DictReader(io.StringIO(body.content.lstrip('\ufeff')))
        if reader.fieldnames:reader.fieldnames=[f.strip() for f in reader.fieldnames]
        if reader.fieldnames and len(set(reader.fieldnames))!=len(reader.fieldnames):raise ValueError('CSV 列名不能重复')
        if not reader.fieldnames or 'strike' not in reader.fieldnames:raise ValueError('CSV 必须包含 strike 列')
        allowed={'strike'}|{side+'_'+key for side in ('call','put') for key in ('last','bid','ask','lastAt','bookAt')}
        if set(reader.fieldnames)-allowed:
            raise ValueError('CSV 含不支持的列：'+', '.join(sorted(set(reader.fieldnames)-allowed))+'；含合约规格的完整数据请使用 JSON 导入')
        rows=[]
        for raw in reader:
            if None in raw:raise ValueError(f'CSV 第 {reader.line_num} 行的列数超过表头，请检查逗号或引号')
            if not any((v or '').strip() for v in raw.values()):continue
            row={'strike':raw.get('strike')}
            for side in ('call','put'):
                quote={k:raw[side+'_'+k].strip() for k in ('last','bid','ask','lastAt','bookAt') if (raw.get(side+'_'+k) or '').strip()}
                row[side]=quote or None
            rows.append(row)
            if len(rows)>500:raise ValueError('一次最多导入 500 档')
        data={**body.settings,'rows':rows}
    return remember(StudyInput.model_validate(data),'MANUAL',['本机导入数据；保留输入估值时刻，来源及同步性未独立核实。'])

async def gateway(argument):
    proc=await asyncio.create_subprocess_exec(sys.executable,'-m','app.futu_gateway',argument,cwd=ROOT.parent,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    try:stdout,_=await asyncio.wait_for(proc.communicate(),timeout=30)
    except (TimeoutError,asyncio.CancelledError) as e:
        if proc.returncode is None:proc.kill()
        await proc.wait()
        if isinstance(e,asyncio.CancelledError):raise
        raise HTTPException(504,'富途响应超时，本次取数已停止；未使用示例数据替代。')
    try:value=json.loads(stdout)
    except (ValueError,UnicodeDecodeError):raise HTTPException(502,'行情服务未返回有效数据。')
    if 'error' in value:raise HTTPException(503,value['detail'])
    return value

@app.get('/api/futu/status')
async def futu_status():
    global status_cache
    if status_cache and time.monotonic()-status_cache[0]<15:return status_cache[1]
    if futu_lock.locked():raise HTTPException(409,'正在获取报价，请稍后检查连接。')
    async with futu_lock:
        value=await gateway('--status')
        status_cache=(time.monotonic(),value)
        return value

def quote_cache_valid(cached,now=None):
    if not cached or time.monotonic()-cached[0]>=QUOTE_INTERVAL_SECONDS:return False
    now=now or datetime.now(timezone.utc)
    try:
        end=close_at(cached[1]['input']['expiration'])
        return end is not None and now<end
    except (KeyError,ValueError):return False

@app.get('/api/market-session')
async def market_session():
    window=maintain()
    return JSONResponse(dict(**window, latestId=latest.item['id'] if latest.item else None),
                        headers={'Cache-Control':'no-store'})

@app.post('/api/futu')
async def futu(body:FutuRequest):
    global last_attempt
    window=maintain()
    if not window['isOpen'] and not body.manual:
        raise HTTPException(409,'休市期间暂停自动刷新，可点击获取报价手动查询。')
    symbol=body.symbol.upper().removeprefix('US.');cached=futu_cache.get(symbol)
    if quote_cache_valid(cached):
        value=cached[1];study=StudyInput.model_validate({**value['input'],'rate':body.rate})
        return remember(study,'FUTU',value['notes'],request_window=window,extra={'receivedAt':value['receivedAt'],'stockUpdatedAt':value['stockUpdatedAt'],'cached':True,'connection':value.get('connection'),'stockAnchor':value.get('stockAnchor')})
    if futu_lock.locked():raise HTTPException(409,'正在获取另一笔报价，请稍后重试。')
    async with futu_lock:
        delay=QUOTE_INTERVAL_SECONDS-(time.monotonic()-last_attempt)
        if delay>0:await asyncio.sleep(delay)
        if maintain()!=window:raise HTTPException(409,'交易时段已切换。')
        last_attempt=time.monotonic()
        value=await gateway(symbol)
        if maintain()!=window:raise HTTPException(409,'交易时段已切换，本次报价已丢弃。')
        futu_cache.clear()
        if window['isOpen']:
            futu_cache[symbol]=(last_attempt,value)
        study=StudyInput.model_validate({**value['input'],'rate':body.rate})
        return remember(study,'FUTU',value['notes'],request_window=window,extra={'receivedAt':value['receivedAt'],'stockUpdatedAt':value['stockUpdatedAt'],'cached':False,'connection':value.get('connection'),'stockAnchor':value.get('stockAnchor')})

@app.get('/')
def index(request: Request):
    mounted = request.scope.get('root_path') == '/api/strike-lab'
    html = (ROOT/'static/index.html').read_text(encoding='utf-8')
    base = '/api/strike-lab/' if mounted else '/'
    navigation = '<a href="/">返回监测总览</a>' if mounted else '本地工作台'
    return HTMLResponse(html.replace('<!-- base -->', f'<base href="{base}">')
                        .replace('<!-- workspace -->', navigation))
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
