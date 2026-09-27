"""SQLite + JSON 缓存，不反序列化 pickle，不保存凭据。"""
from dataclasses import asdict, dataclass
from io import StringIO
import json
from pathlib import Path
import sqlite3
import time
import pandas as pd


@dataclass(frozen=True)
class CacheKey:
    provider: str
    symbol: str
    start_date: str
    end_date: str
    adjustment: str

    def encode(self):
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)


class DataCache:
    def __init__(self, path=None, ttl=3600, clock=time.time):
        self.path = Path(path) if path else Path(__file__).resolve().parents[2] / 'data/cache/market.sqlite3'
        self.ttl, self.clock = ttl, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS frames (key TEXT PRIMARY KEY, payload TEXT NOT NULL, last_updated REAL NOT NULL)')

    def freeze_score(self, symbol, snapshot):
        # INSERT OR IGNORE makes a historical decision immutable across refreshes.
        payload = json.dumps(asdict(snapshot), sort_keys=True, allow_nan=False)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS score_snapshots (symbol TEXT, day TEXT, version TEXT, payload TEXT, PRIMARY KEY(symbol,day,version))')
            db.execute('INSERT OR IGNORE INTO score_snapshots VALUES (?,?,?,?)', (symbol,snapshot.signal_date,snapshot.spec_version,payload))

    def score_snapshots(self, symbol):
        from app.rules.risks.should_rise import ScoreSnapshot
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS score_snapshots (symbol TEXT, day TEXT, version TEXT, payload TEXT, PRIMARY KEY(symbol,day,version))')
            rows = db.execute('SELECT payload FROM score_snapshots WHERE symbol=? ORDER BY day', (symbol,)).fetchall()
        return [ScoreSnapshot(**json.loads(row[0])) for row in rows]

    def get(self, key, *, force_refresh=False):
        if force_refresh:
            return None
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT payload,last_updated FROM frames WHERE key=?', (key.encode(),)).fetchone()
        if row is None or self.clock() - row[1] >= self.ttl:
            return None
        frame = pd.read_json(StringIO(row[0]), orient='table')
        frame.attrs['last_updated'] = row[1]
        frame.attrs['cache_hit'] = True
        return frame

    def put(self, key, frame):
        updated = self.clock()
        payload = frame.to_json(orient='table', date_format='iso', index=False, double_precision=15)
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR REPLACE INTO frames VALUES (?,?,?)', (key.encode(), payload, updated))
        frame.attrs['last_updated'] = updated
        frame.attrs['cache_hit'] = False
        return frame
