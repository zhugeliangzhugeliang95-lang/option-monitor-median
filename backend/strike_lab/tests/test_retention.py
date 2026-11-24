from datetime import datetime
from fastapi.testclient import TestClient

from app import main
from app.retention import LatestSnapshot, market_window
from quote_fixture import goog


def at(stamp):
    return datetime.fromisoformat(stamp+'+00:00')


def test_holiday_early_close_weekend_and_dst():
    holiday=market_window(at('2026-11-26T16:00'))
    assert not holiday['isOpen'] and holiday['expiresAt'].startswith('2026-11-27T14:30')
    assert market_window(at('2026-11-27T17:59'))['isOpen']
    early=market_window(at('2026-11-27T18:00'))
    assert not early['isOpen'] and early['expiresAt'].startswith('2026-11-30T14:30')
    assert market_window(at('2026-11-30T13:30'))==early
    assert market_window(at('2026-03-09T13:30'))['isOpen']


def test_close_restart_and_expiry_without_new_quotes(monkeypatch):
    client=TestClient(main.app)
    clock=[at('2026-11-27T17:55')]
    monkeypatch.setattr(main,'utc_now',lambda:clock[0])
    main.maintain()
    first=main.remember(goog(),'FUTU')
    study=goog()
    study.rows[0].call.last+=1
    final=main.remember(study,'FUTU')
    assert first['id']!=final['id']
    path=main.latest.path
    assert client.get('/api/studies/'+first['id']+'/export').status_code==404
    main.remember(goog(),'MANUAL')
    main.futu_cache['GOOG']=(0,{})
    clock[0]=at('2026-11-27T18:00')
    assert client.get('/api/market-session').json()['latestId']==final['id']
    assert not main.records and not main.futu_cache
    assert client.post('/api/futu',json={'symbol':'SPY'}).status_code==409
    main.latest=LatestSnapshot(path)
    assert client.get('/api/studies/'+final['id']+'/export').json()==final
    clock[0]=at('2026-11-30T14:30')
    assert client.get('/api/market-session').json()['latestId'] is None
    assert not path.exists()
    assert client.get('/api/studies/'+final['id']+'/export').status_code==404

def test_after_hours_manual_symbol_switch_preserves_one_snapshot(monkeypatch):
    clock=at('2026-11-27T19:00')
    monkeypatch.setattr(main,'utc_now',lambda:clock)
    calls=[]
    async def gateway(symbol):
        calls.append(symbol)
        return dict(input=goog().model_dump(mode='json')|dict(symbol=symbol),notes=[],
                    receivedAt=clock.isoformat(),stockUpdatedAt=None)
    monkeypatch.setattr(main,'gateway',gateway)
    client=TestClient(main.app)
    assert client.post('/api/futu',json={'symbol':'MU'}).status_code==409
    result=client.post('/api/futu',json={'symbol':'mu','manual':True})
    assert result.status_code==200 and calls==['MU']
    item=result.json()
    assert item['report']['symbol']=='MU' and item['expiresAt'].startswith('2026-11-30T14:30')
    assert client.get('/api/market-session').json()['latestId']==item['id']
    assert not main.futu_cache
