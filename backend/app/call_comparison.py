"""Three-strike relative call value, matching the supplied October 30 worksheet.
All amounts are per share. This is a gross relative valuation, not an order price.
"""
from decimal import Decimal
from .engine import compute, price_selector, event_times
from .models import Config, Snapshot, Model
from pydantic import Field, field_validator
from typing import Literal

class ComparisonRequest(Model):
    snapshotId: int = Field(gt=0)
    basis: Literal['LAST','MID'] = 'LAST'
    strikes: list[Decimal] = Field(min_length=3,max_length=3)
    @field_validator('strikes')
    @classmethod
    def distinct(cls,v):
        if any(not k.is_finite() or k<=0 for k in v) or len(set(v))!=3:
            raise ValueError('请选择三个不同的正数行权价')
        return sorted(v)

def compare_calls(cfg:Config,snapshot:Snapshot,strikes:list[Decimal],basis:str):
    result=compute(cfg,snapshot)
    by_strike={Decimal(r['strike']):r for r in result['modes'][basis]['rows']}
    if len(set(strikes))!=3 or any(k not in by_strike for k in strikes):
        raise ValueError('请选择当前选档中的三个不同行权价')
    selected=[by_strike[k] for k in sorted(strikes)]
    reasons=sorted({reason for r in selected for reason in r['reasons']})
    legs=[leg for r in selected for leg in (r['call'],r['put']) if leg]
    # Replication requires the same underlying, term and deliverable across all six legs.
    for field in ('underlyingId','expiration','currency','exercise','settlement','multiplier','deliverable','adjusted','pricingAt','lastTradingAt'):
        if len({str(l['contract'][field]) for l in legs})>1:
            reasons.append('CROSS_STRIKE_MISMATCH_'+field)
    times=[]
    from .models import Leg
    for l in legs: times.extend(t for t in event_times(Leg.model_validate(l).quote,basis) if t)
    if times and (max(times)-min(times)).total_seconds()>cfg.maxSkewSeconds:
        reasons.append('CROSS_STRIKE_TIME_SKEW')
    comparable=all(r['value'] is not None for r in selected) and not any(r.startswith('CROSS_STRIKE_MISMATCH_') for r in reasons)
    prices=[]
    for r in selected:
        prices.append(tuple(price_selector(Leg.model_validate(r[k]).quote,basis) if r[k] else None for k in ('call','put')))
    rows=[]
    for i,r in enumerate(selected):
        others=[j for j in range(3) if j!=i]; j,k=others
        ki,kj,kk=(Decimal(selected[x]['strike']) for x in (i,j,k))
        w=(kk-ki)/(kk-kj); v=1-w
        ref=(float(w)*(prices[j][0]-prices[j][1])+float(v)*(prices[k][0]-prices[k][1])+prices[i][1]) if comparable else None
        premium=(prices[i][0]-ref)/ref*100 if ref is not None and ref>0 else None
        rows.append(dict(strike=r['strike'],marketCall=prices[i][0],referenceCall=ref,premiumPct=premium,
                         weights=[dict(strike=selected[j]['strike'],weight=float(w)),dict(strike=selected[k]['strike'],weight=float(v))]))
    can_rank=all(r['premiumPct'] is not None for r in rows)
    for r in rows:
        r['rank']=1+sum(x['premiumPct']<r['premiumPct']-1e-9 for x in rows) if can_rank else None
    if any(r['referenceCall'] is not None and r['referenceCall']<=0 for r in rows): reasons.append('NONPOSITIVE_REFERENCE_CALL')
    return dict(basis=basis,valuationAt=snapshot.valuationAt.isoformat(),expiration=result['expiration'],
                feedType=result['feedType'],rows=rows,reasons=sorted(set(reasons)),
                qualityEligible=comparable and not reasons,rankAvailable=can_rank,
                cheapestStrikes=[r['strike'] for r in rows if r['rank']==1],
                warning='仅为所选三档的未扣成本相对估值。成交价可能不同步；MID不是可成交价。点差、费用及美式期权提前行权可能改变排名，不代表买入建议。')
