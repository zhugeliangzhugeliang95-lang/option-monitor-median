from decimal import Decimal
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from app.engine import compute, summary
from app.models import NewConfig
from app.call_comparison import compare_calls
from app.api import app
from app.service import create_monitor,save_snapshot
from app.db import Session

STRIKES=(123,124.5,127,129.5,133,134,135)
VALUES=(129.33,130.11,131.06,129.18,128.98,130.51,131.02)

def test_user_seven_values_end_to_end(cfg,sample):
    cfg.nBelow=cfg.nAbove=3
    s=sample(STRIKES,130.89)
    for l in s.legs:
        i=STRIKES.index(float(l.contract.strike))
        l.quote.bid=l.quote.ask=l.quote.last=20+(VALUES[i]-float(l.contract.strike) if l.contract.right=='C' else 0)
    r=compute(cfg,s)
    assert r['composition']==[str(x) for x in STRIKES]
    assert r['centerStrike']=='129.5'
    assert set(r['modes'])=={'MID','LAST'}
    for a in r['modes'].values():
        assert a['rawMedian']==pytest.approx(130.11)
        assert a['min']==pytest.approx(128.98)
        assert a['max']==pytest.approx(131.06)
        assert a['rawGapBps']==pytest.approx(10000*(130.11-130.89)/130.89)
        assert a['complete'] and a['computableCount']==7 and a['validCount']==7
        assert 'rawMean' not in a

def test_default_seven():
    c=NewConfig()
    assert (c.nBelow,c.nAbove,c.optionPricePreset)==(3,3,'MID')

def test_tie_lower_strike(cfg,sample):
    cfg.nBelow=cfg.nAbove=3
    r=compute(cfg,sample((100,110,120,130,140,150,160,170),135))
    assert r['centerStrike']=='130'
    assert r['composition']==['100','110','120','130','140','150','160']

def test_missing_center_leg_not_replaced(cfg,sample):
    cfg.nBelow=cfg.nAbove=3
    s=sample((120,*STRIKES,140),130.89)
    s.legs=[l for l in s.legs if not (l.contract.strike==Decimal('129.5') and l.contract.right=='P')]
    r=compute(cfg,s); a=r['modes']['MID']
    assert r['composition']==[str(x) for x in STRIKES]
    assert a['requestedCount']==7 and a['computableCount']==6 and not a['complete']
    assert a['rows'][3]['value'] is None

def test_short_chain_does_not_fill_other_side(cfg,sample):
    cfg.nBelow=cfg.nAbove=3
    r=compute(cfg,sample((129.5,133,134,135,140,145),130.89))
    assert r['composition']==['129.5','133','134','135']
    assert r['modes']['MID']['requestedCount']==7
    assert not r['modes']['MID']['complete']

def test_even_partial_and_outlier():
    rows=[dict(value=x,qualityEligible=True) for x in (1,2,3,1000)]
    a=summary(rows,7)
    assert a['rawMedian']==2.5 and a['min']==1 and a['max']==1000 and not a['complete']

def goog_snapshot(sample):
    s=sample((275,277.5,280),277.5)
    quotes={275:(7.59,3.67),277.5:(5.85,4.72),280:(4.66,6.13)}
    for l in s.legs:
        l.quote.bid=l.quote.ask=l.quote.last=quotes[float(l.contract.strike)][l.contract.right=='P']
    return s

@pytest.mark.parametrize('basis',['MID','LAST'])
def test_attachment_goog_example(cfg,sample,basis):
    cfg.nBelow=cfg.nAbove=3
    r=compare_calls(cfg,goog_snapshot(sample),list(map(Decimal,['275','277.5','280'])),basis)
    assert [x['referenceCall'] for x in r['rows']]==pytest.approx([7.4,5.945,4.47])
    assert [x['premiumPct'] for x in r['rows']]==pytest.approx([2.5675675676,-1.5979814971,4.2505592841])
    assert [x['rank'] for x in r['rows']]==[2,1,3]
    assert r['cheapestStrikes']==['277.5'] and r['qualityEligible']

def test_uneven_strike_replication(cfg,sample):
    cfg.nBelow=cfg.nAbove=3
    s=sample((100,105,120),105)
    for l in s.legs:l.quote.last=30+130-float(l.contract.strike) if l.contract.right=='C' else 30
    r=compare_calls(cfg,s,list(map(Decimal,['100','105','120'])),'LAST')
    assert [x['premiumPct'] for x in r['rows']]==pytest.approx([0,0,0])
    assert r['rows'][1]['weights'][0]['weight']==pytest.approx(.75)
    assert r['cheapestStrikes']==['100','105','120']

def test_comparison_missing_input_blocks_ranking(cfg,sample):
    cfg.nBelow=cfg.nAbove=3;s=goog_snapshot(sample);s.legs[0].quote.last=None
    r=compare_calls(cfg,s,list(map(Decimal,['275','277.5','280'])),'LAST')
    assert not r['rankAvailable'] and not r['qualityEligible']
    assert all(x['referenceCall'] is None for x in r['rows'])

def test_cross_strike_time_mismatch(cfg,sample):
    cfg.nBelow=cfg.nAbove=3;s=goog_snapshot(sample)
    for l in s.legs[:2]:l.quote.lastAt-=timedelta(seconds=2)
    r=compare_calls(cfg,s,list(map(Decimal,['275','277.5','280'])),'LAST')
    assert 'CROSS_STRIKE_TIME_SKEW' in r['reasons'] and not r['qualityEligible']

def test_cross_strike_contract_mismatch(cfg,sample):
    cfg.nBelow=cfg.nAbove=3;s=goog_snapshot(sample)
    for l in s.legs[:2]:l.contract.multiplier=Decimal('10')
    r=compare_calls(cfg,s,list(map(Decimal,['275','277.5','280'])),'LAST')
    assert not r['rankAvailable'] and 'CROSS_STRIKE_MISMATCH_multiplier' in r['reasons']

def test_nonpositive_reference_blocks_ranking(cfg,sample):
    cfg.nBelow=cfg.nAbove=3;s=goog_snapshot(sample)
    for l in s.legs:l.quote.last=0
    r=compare_calls(cfg,s,list(map(Decimal,['275','277.5','280'])),'LAST')
    assert not r['rankAvailable'] and 'NONPOSITIVE_REFERENCE_CALL' in r['reasons']

def test_comparison_api_ownership_and_validation(cfg,sample):
    cfg.nBelow=cfg.nAbove=3
    with Session() as db:
        m=create_monitor(db,cfg); other=create_monitor(db,cfg)
        s=goog_snapshot(sample);s.monitorId=m.id
        result=save_snapshot(db,s)
    client=TestClient(app)
    body=dict(snapshotId=result['snapshotId'],basis='LAST',strikes=['275','277.5','280'])
    r=client.post(f'/api/monitors/{m.id}/call-comparison',json=body)
    assert r.status_code==200 and r.json()['cheapestStrikes']==['277.5']
    assert client.post(f'/api/monitors/{other.id}/call-comparison',json=body).status_code==404
    for patch in ({'basis':'BID'},{'strikes':[275,275,280]},{'strikes':[1,2,3]},{'strikes':[275,280]}):
        assert client.post(f'/api/monitors/{m.id}/call-comparison',json=body|patch).status_code==422
    assert client.patch(f'/api/monitors/{m.id}',json={'optionPricePreset':'ASK'}).status_code==422
