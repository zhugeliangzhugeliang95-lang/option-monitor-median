from math import exp
from datetime import timedelta
from decimal import Decimal
import pytest
from pydantic import ValidationError
from app.engine import *
from app.models import *

def test_excel(): assert 6.62-1.88+152.5*exp(-.05*2/365)==pytest.approx(157.19822490096)
def test_only_mid_and_last_modes(cfg,sample):
    result=compute(cfg,sample())
    assert set(result['modes'])=={'MID','LAST'}
    assert [result['modes'][b]['rawMedian'] for b in ('MID','LAST')]==pytest.approx([602.85,602.9])
    row=result['modes']['MID']['rows'][0]
    assert row['syntheticLower']==pytest.approx(602.5)
    assert row['syntheticUpper']==pytest.approx(603.2)
def test_nearest_decimal_and_atm(cfg,sample):
    cfg.nBelow=2;cfg.nAbove=2
    r=compute(cfg,sample((590,595,600,605,610,615),600))
    assert r['composition']==['590','595','600','605','610']
def test_zero_and_one_side(cfg,sample):
    cfg.nBelow=0
    r=compute(cfg,sample());assert r['status']=='PLEASE_SET_COUNTS';assert r['modes']['MID']['rawMedian'] is None
    cfg.nAbove=1
    assert compute(cfg,sample((600,605),601))['composition']==['600','605']
def test_missing_leg_no_substitution(cfg,sample):
    s=sample((590,600)); s.legs=[l for l in s.legs if l.contract.id!='600P']
    r=compute(cfg,s); assert r['composition']==['590','600']
    assert r['modes']['MID']['computableCount']==1
    assert r['modes']['MID']['rows'][1]['value'] is None
    assert r['modes']['MID']['rows'][1]['reasons']==['MISSING_OR_AMBIGUOUS_LEG']
@pytest.mark.parametrize('field,value',[('expiration','2026-10-20'),('multiplier',Decimal(10)),('adjusted',True),('currency','EUR'),('settlement','CASH'),('deliverable','ODD'),('exercise','EUROPEAN')])
def test_no_mismatched_pairs(cfg,sample,field,value):
    s=sample();setattr(s.legs[1].contract,field,value)
    assert compute(cfg,s)['modes']['MID']['rawMedian'] is None
def test_median_by_strikes():
    rows=[{'value':v,'qualityEligible':True,'side':side} for v,side in [(100,'below'),(102,'below'),(110,'above')]]
    assert summary(rows,3)['rawMedian']==102

def test_missing_book_not_last(cfg,sample):
    s=sample();s.legs[0].quote.bid=None
    r=compute(cfg,s)
    assert r['modes']['MID']['rawMedian'] is None
    assert r['modes']['LAST']['rawMedian'] is not None

def test_reported_mid(cfg,sample):
    s=sample();q=s.legs[0].quote;q.bid=None;q.ask=None;q.reportedMid=4.1;q.reportedMidAt=s.valuationAt
    r=compute(cfg,s)['modes']['MID'];assert r['rawMedian']==pytest.approx(602.85);assert r['rows'][0]['syntheticLower'] is None

def test_stale_keeps_raw(cfg,sample):
    s=sample();s.legs[0].quote.bidAt-=timedelta(seconds=10)
    r=compute(cfg,s)['modes']['MID'];assert r['rawMedian'] is not None;assert r['validatedMedian'] is None

def test_stale_anchor_not_replaced(cfg,sample):
    s=sample();s.underlying.lastAt=None
    r=compute(cfg,s);assert not r['anchorStrictEligible'];assert r['anchor']==601;assert r['status']=='INVALID_SELECTION_ANCHOR'

def test_crossed_book_raw(cfg,sample):
    s=sample();s.legs[0].quote.bid=5
    r=compute(cfg,s)['modes']['MID'];assert r['rawMedian'] is not None;assert not r['strictEligible']

def test_timestamp_intraday_and_original_valuation(cfg,sample):
    cfg.timeRule='timestamp';s=sample();r=compute(cfg,s)
    assert r['modes']['MID']['rows'][0]['T']==pytest.approx(5/24/365)
    assert compute(cfg,s)['modes']['MID']['rows'][0]['T']==r['modes']['MID']['rows'][0]['T']

def test_expired(cfg,sample):
    cfg.timeRule='timestamp';s=sample()
    for l in s.legs:l.contract.pricingAt=s.valuationAt-timedelta(seconds=1)
    assert compute(cfg,s)['modes']['MID']['rawMedian'] is None

def test_no_expiry_rollover(cfg,sample):
    s=sample();s.valuationAt+=timedelta(days=1)
    assert compute(cfg,s)['status']=='NO_SAME_DAY_EXPIRY'

def test_nan_rejected():
    with pytest.raises(ValidationError): Quote(source='x',last=float('nan'))

def test_units(cfg,sample):
    s=sample();s.legs[0].quote.unit='PER_CONTRACT'
    assert compute(cfg,s)['modes']['MID']['rawMedian'] is None

def test_missing_timezone():
    with pytest.raises(ValidationError): Quote(source='x',lastAt='2026-10-19T10:00:00')

def test_excel_through_engine(cfg,sample):
    s=sample((152.5,),157.2);cfg.rate=.05
    for l in s.legs:
        l.quote.bid=l.quote.ask=l.quote.last=6.62 if l.contract.right=='C' else 1.88
    assert compute(cfg,s)['modes']['MID']['rawMedian']==pytest.approx(157.19822490096)

def test_negative_mid_input_not_computable(cfg,sample):
    s=sample();s.legs[0].quote.bid=-1
    assert compute(cfg,s)['modes']['MID']['rawMedian'] is None


STRIKES=tuple(range(440,461))
def test_atm_strike_exact_equal_adds_at(cfg,sample):
    cfg.nBelow=5;cfg.nAbove=5
    r=compute(cfg,sample(STRIKES,450))
    rows=r['modes']['MID']['rows']; sides=[x['side'] for x in rows]
    assert len(rows)==11 and (sides.count('below'),sides.count('at'),sides.count('above'))==(5,1,5)
    assert r['composition']==['445','446','447','448','449','450','451','452','453','454','455']
    a=r['modes']['MID']; assert a['requestedCount']==11 and a['computableCount']==11
    at=[x for x in rows if x['side']=='at'][0]; assert at['strike']=='450'
    assert a['rawMedian']==pytest.approx(sum(x['value'] for x in rows)/11)
def test_center_uses_nearest_when_spot_between_strikes(cfg,sample):
    cfg.nBelow=5;cfg.nAbove=5
    r=compute(cfg,sample(STRIKES,450.10))
    rows=r['modes']['MID']['rows']
    assert len(rows)==11 and 'at' in {x['side'] for x in rows} and r['modes']['MID']['requestedCount']==11
    assert r['composition']==['445','446','447','448','449','450','451','452','453','454','455']
def test_atm_near_chain_edge(cfg,sample):
    cfg.nBelow=5;cfg.nAbove=5
    r=compute(cfg,sample((447,448,449,450,451,452),450))
    sides=[x['side'] for x in r['modes']['MID']['rows']]
    assert (sides.count('below'),sides.count('at'),sides.count('above'))==(3,1,2)
    assert r['modes']['MID']['requestedCount']==11 and not r['modes']['MID']['strictEligible']
@pytest.mark.parametrize('spot,has_at',[(450,True),(450.0,True),(Decimal('450.00'),True),(450.10,True),(449.99,True)])
def test_atm_decimal_vs_float(spot,has_at):
    cs=[Contract(id=f'{k}C',underlyingId='SPY',expiration='2026-10-19',strike=Decimal(k),right='C') for k in ('449.5','450','450.5')]
    sides=[s for _,s in selected_strikes(cs,spot,1,1)]
    assert ('at' in sides)==has_at and sides.count('below')==1 and sides.count('above')==1
def test_atm_not_selected_when_counts_zero(cfg,sample):
    cfg.nBelow=0;cfg.nAbove=0
    r=compute(cfg,sample(STRIKES,450)); assert r['composition']==[] and r['status']=='PLEASE_SET_COUNTS'

def test_center_spot_450_01_selects_450(cfg,sample):
    cfg.nBelow=5;cfg.nAbove=5
    rows=compute(cfg,sample(STRIKES,450.01))['modes']['MID']['rows']; sides=[x['side'] for x in rows]
    assert len(rows)==11 and (sides.count('below'),sides.count('at'),sides.count('above'))==(5,1,5)
