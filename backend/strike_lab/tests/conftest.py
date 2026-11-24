from datetime import datetime, timezone

import pytest

from app import main
from app.retention import LatestSnapshot


@pytest.fixture(autouse=True)
def isolated_session(tmp_path, monkeypatch):
    # Keep API tests independent of today's trading hours and the running desktop app.
    now=datetime(2026,10,30,19,59,tzinfo=timezone.utc)
    monkeypatch.setattr(main,'utc_now',lambda: now)
    monkeypatch.setattr(main,'latest',LatestSnapshot(tmp_path/'latest-market.json'))
    monkeypatch.setattr(main,'records',main.OrderedDict())
    monkeypatch.setattr(main,'futu_cache',{})
    monkeypatch.setattr(main,'last_window',None)
    main.maintain()
