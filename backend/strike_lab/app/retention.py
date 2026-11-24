"""One replaceable market snapshot, valid until the following regular open."""
import json
import os
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from .engine import calendar

NY = ZoneInfo('America/New_York')


@lru_cache(maxsize=4)
def session_times(day):
    cal = calendar()
    session = cal.date_to_session(str(day), direction='previous')
    previous = cal.previous_session(session)
    following = cal.next_session(session)
    return tuple(t.to_pydatetime() for t in (
        cal.session_open(previous), cal.session_close(previous), cal.session_open(session),
        cal.session_close(session), cal.session_open(following)))


def market_window(now):
    previous, previous_close, opening, closing, following = session_times(now.astimezone(NY).date())
    if now < opening:
        opening, closing, following = previous, previous_close, opening
    return dict(isOpen=opening <= now < closing, openedAt=opening.isoformat(),
                closedAt=closing.isoformat(), expiresAt=following.isoformat())


class LatestSnapshot:
    def __init__(self, path):
        self.path = path
        self.item = None
        self.loaded = False

    def current(self, now):
        if not self.loaded:
            self.path.with_suffix('.tmp').unlink(missing_ok=True)
            if self.path.exists():
                try:
                    item = json.loads(self.path.read_text(encoding='utf-8'))
                    deadline = datetime.fromisoformat(item['expiresAt'])
                    if deadline.tzinfo and item['source'] == 'FUTU' and item['report']['modes'] and item['id']:
                        self.item = item
                except (ValueError, KeyError, TypeError):
                    self.item = None
                if self.item is None:
                    self.path.unlink(missing_ok=True)
            self.loaded = True
        if self.item and datetime.fromisoformat(self.item['expiresAt']) <= now:
            self.path.unlink(missing_ok=True)
            self.item = None
        return self.item

    def save(self, item, expires_at):
        current = dict(item, expiresAt=expires_at)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as stream:
            json.dump(current, stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        os.replace(temp, self.path)
        self.item = current
        self.loaded = True
        return current
