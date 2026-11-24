"""Pure, point-in-time research math. No network, storage or clock calls."""
from math import exp
from statistics import mean, median
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from zoneinfo import ZoneInfo
from .models import StudyInput,Row,Leg
VERSION='strike-lab-1.6'
BASIS=('LAST','MID')

@lru_cache(maxsize=1)
def calendar():
    import exchange_calendars as xc
    return xc.get_calendar('XNYS')

def close_at(day):
    cal=calendar()
    if not cal.is_session(str(day)):return None
    return cal.session_close(str(day)).to_pydatetime()

def select_strikes(strikes,spot):
    keys=sorted(set(Decimal(str(x)) for x in strikes))
    if spot is None or not keys:return [],None
    anchor=Decimal(str(spot));center=min(keys,key=lambda k:(abs(k-anchor),k));i=keys.index(center)
    return keys[max(0,i-3):i+4],center

def price(q:Leg|None,basis):
    if q is None:return None
    if basis=='LAST':return q.last
    if q.bid is None or q.ask is None:return None
    return (q.bid+q.ask)/2

def quote_issues(q,basis,study):
    if q is None:return ['缺少合约或报价']
    errors=[]
    if price(q,basis) is None:errors.append('缺少成交价' if basis=='LAST' else '缺少双边买卖报价')
    if q.bid is not None and q.ask is not None and q.bid>q.ask:errors.append('买价高于卖价')
    t=q.lastAt if basis=='LAST' else q.bookAt
    if t is None:errors.append('缺少独立成交事件时间' if basis=='LAST' else '缺少盘口事件时间')
    else:
        age=(study.valuationAt-t).total_seconds()
        if age>study.maxAgeSeconds:errors.append('报价过旧')
        if age<-.1:errors.append('报价晚于估值时刻')
    if q.updatedAt:
        age=(study.valuationAt-q.updatedAt).total_seconds()
        if age>study.maxAgeSeconds:errors.append('快照更新时间较旧')
        if age<-.1:errors.append('快照更新时间晚于估值时刻')
    return errors

def contract_errors(row,study):
    c,p=row.call,row.put;issues=list(row.issues)
    if c is None or p is None:return issues+['缺少 Call / Put 配对']
    for field in ('currency','multiplier','exercise'):
        if getattr(c,field)!=getattr(p,field):issues.append('合约规格不匹配：'+field)
    for leg in (c,p):
        if leg.adjusted:issues.append('调整合约不支持')
        if leg.currency!='USD':issues.append('仅支持 USD 每股报价')
        if leg.underlying and leg.underlying.removeprefix('US.')!=study.symbol.removeprefix('US.'):issues.append('标的不匹配')
        if leg.expiration and leg.expiration!=study.expiration:issues.append('到期日不匹配')
    return sorted(set(issues))

def term(study):
    if study.expiration<study.valuationAt.astimezone(ZoneInfo('America/New_York')).date():
        return None,None,'到期日早于估值日'
    if study.timeRule=='days':return study.remainingDays/365,None,'人工剩余天数 / 365'
    end=study.pricingAt if study.timeRule=='timestamp' else close_at(study.expiration)
    if end is None:return None,None,'所选到期日不是常规交易日，请指定定价参考时刻'
    seconds=(end-study.valuationAt).total_seconds()
    if seconds<0:return None,end.isoformat(),'合约已超过定价参考时刻'
    if seconds>3650*86400:return None,end.isoformat(),'期限超过支持范围（3650 天）'
    return seconds/(365*86400),end.isoformat(),('用户指定定价时刻' if study.timeRule=='timestamp' else '交易日历常规收盘（含半日市），作为研究假设，非 API 核实的期权截止时刻')

def row_result(row,study,basis,T):
    c,p=price(row.call,basis),price(row.put,basis);fatal=contract_errors(row,study)
    if T is None:fatal.append('期限无效')
    issues=fatal+quote_issues(row.call,basis,study)+quote_issues(row.put,basis,study)
    times=[getattr(q,'lastAt' if basis=='LAST' else 'bookAt') for q in (row.call,row.put) if q]
    times=[t for t in times if t]
    if times and (max(times)-min(times)).total_seconds()>study.maxSkewSeconds:issues.append('Call / Put 事件时间不同步')
    comparable = not fatal and c is not None and p is not None
    return dict(strike=str(row.strike),call=c,put=p,comparable=comparable,
                qualityPassed=comparable and not issues,issues=list(dict.fromkeys(issues)),
                callQuote=row.call.model_dump(mode='json') if row.call else None,putQuote=row.put.model_dump(mode='json') if row.put else None)

def implied_spot(rows, rate, term_years):
    values = [row['call'] - row['put'] + float(row['strike']) * exp(-rate * term_years)
              for row in rows if row['comparable']]
    return dict(count=len(values), median=median(values) if values else None,
                mean=mean(values) if values else None,
                min=min(values, default=None), max=max(values, default=None))

def analyze(study:StudyInput):
    keys,center=select_strikes([r.strike for r in study.rows],study.spot)
    by_key={r.strike:r for r in study.rows};visible=[by_key[k] for k in keys] if center is not None else sorted(study.rows,key=lambda r:r.strike)
    T,end,time_note=term(study);modes={}
    for basis in BASIS:
        rows=[row_result(r,study,basis,T) for r in visible]
        modes[basis]=dict(rows=rows)
        if center is not None:
            modes[basis]['impliedSpot'] = implied_spot(rows, study.rate, T)
            modes[basis]['comparison']=rank_calls(study, rows, by_key, basis, 7)
    return dict(modelVersion=VERSION,symbol=study.symbol,spot=study.spot,expiration=study.expiration.isoformat(),
                valuationAt=study.valuationAt.isoformat(),pricingAt=end,rate=study.rate,T=T,timeNote=time_note,
                center=str(center) if center is not None else None,selectedStrikes=[str(k) for k in keys],
                candidateCount=len(study.rows),modes=modes,
                notes=['Call 和 Put 使用同一取价方式，单位为每股美元。',
                       '美式期权提前行权、股息和交易成本未建模；结果为相对估值，不是未来股价预测。']+
                       ([] if study.spot else ['缺少正股现价：暂不选择七档。仍可比较给定候选期权的相对价格。']))

def compare(study:StudyInput,selection,basis):
    result=analyze(study);visible={Decimal(r['strike']):r for r in result['modes'][basis]['rows']}
    if len(set(selection))!=3 or any(k not in visible for k in selection):raise ValueError('必须选择当前报价表内三个不同行权价')
    selected=[visible[k] for k in sorted(selection)]
    return rank_calls(study, selected, {r.strike:r for r in study.rows}, basis, 3)


def rank_calls(study, rows, originals, basis, expected):
    errors={issue for row in rows for issue in row['issues']}
    if len(rows)!=expected:
        errors.add(f'中心档前后档位不足，仅有 {len(rows)} / {expected} 档')
    legs=[q for row in rows for q in (originals[Decimal(row['strike'])].call,
                                       originals[Decimal(row['strike'])].put) if q]
    for field in ('currency','multiplier','exercise'):
        if len({getattr(q,field) for q in legs})>1:
            errors.add('参与比较的合约规格不同：'+field)
    times=[q.lastAt if basis=='LAST' else q.bookAt for q in legs]
    times=[t for t in times if t is not None]
    if times and (max(times)-min(times)).total_seconds()>study.maxSkewSeconds:
        errors.add('各档事件时间不同步')

    output=[]
    for i,row in enumerate(rows):
        start=max(0,min(i-1,len(rows)-3))
        neighbors=[r for r in rows[start:start+3] if r is not row]
        reference=None
        terms=[]
        if len(neighbors)==2:
            left,right=neighbors
            ki,kj,kk=(Decimal(r['strike']) for r in (row,left,right))
            w=(kk-ki)/(kk-kj)
            v=1-w
            terms=[dict(strike=r['strike'],right=side,weight=float(weight),price=r[col])
                   for r,side,weight,col in ((left,'C',w,'call'),(right,'C',v,'call'),
                       (left,'P',-w,'put'),(row,'P',1,'put'),(right,'P',-v,'put'))]
            group=(row,left,right)
            specs={(q.currency,q.multiplier,q.exercise) for r in group
                   for q in (originals[Decimal(r['strike'])].call,originals[Decimal(r['strike'])].put) if q}
            if all(r['comparable'] for r in group) and len(specs)==1:
                reference=float(w)*(left['call']-left['put'])+float(v)*(right['call']-right['put'])+row['put']
        premium=None
        if reference is not None and reference>0:
            premium=(row['call']-reference)/reference*100
        elif reference is not None:
            errors.add('复制参考价非正，无法比较溢价率')
        output.append(dict(strike=row['strike'],market=row['call'],reference=reference,premiumPct=premium,
                           terms=terms,referenceStrikes=[r['strike'] for r in neighbors],rank=None))
    rankable=len(output)==expected and all(r['premiumPct'] is not None for r in output)
    if rankable:
        for r in output:
            r['rank']=1+sum(x['premiumPct']<r['premiumPct']-1e-9 for x in output)
    return dict(basis=basis,expectedCount=expected,rows=sorted(output,key=lambda r:r['rank'] or 99),
                rankable=rankable,lowest=[r['strike'] for r in output if r['rank']==1],
                qualityPassed=rankable and not errors,issues=sorted(errors),
                note='相对溢价按从低到高排序，未扣成本。不同档的参考组合可能不同。成交时间、买卖点差、费用及提前行权可能影响排序。')
