"""Persistent validated range cache, with overlap/adjustment-anchor protection.

Only the screening adapter opts in. No changes to single-stock score semantics.
Old history can be reused after TTL only after a real overlap validation. Any
price/field correction in the overlap triggers a full refresh. force_refresh
always bypasses persistence; the run memo still prevents duplicate refreshes.
"""
from io import StringIO
import json
from pathlib import Path
import sqlite3
import threading
import time
import pandas as pd
from app.data.validators import DataValidator
from app.data.models import DataError


class HistoryCache:
    def __init__(self, path, ttl=3600, clock=time.time, control=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl, self.clock, self.control = ttl, clock, control
        self.lock = threading.RLock()
        self.memory = {}
        self.metrics = dict(hits=0, cold_fetches=0, incremental_fetches=0,
                            prefix_fetches=0, anchor_refreshes=0, failures=0)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS history_v1 '
                       '(key TEXT PRIMARY KEY, metadata TEXT NOT NULL, payload TEXT NOT NULL)')

    def check(self):
        if self.control:
            self.control.check()

    @staticmethod
    def slice(frame, lo, hi):
        return frame.loc[frame.date.between(lo,hi)].reset_index(drop=True).copy(deep=True)

    def fetch(self, provider, symbol, adjustment, start, end, callback, *, refresh=False):
        key = json.dumps([provider,symbol,adjustment])
        lo, hi = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        with self.lock:
            self.check()
            record = self.memory.get(key)
            from_memory = record is not None
            if record is None and not refresh:
                with sqlite3.connect(self.path) as db:
                    row = db.execute('SELECT metadata,payload FROM history_v1 WHERE key=?',(key,)).fetchone()
                if row:
                    meta = json.loads(row[0])
                    record = (meta,pd.read_json(StringIO(row[1]),orient='table')) if meta['data_status']=='VALID' else None
            def get(a,b):
                self.check()
                frame = DataValidator.validate(callback(a,b),suffixes=('',))
                self.check()
                if 'symbol' in frame and not frame.symbol.eq(symbol).all():
                    raise DataError('Cached history symbol inconsistent')
                if frame.date.min()<a or frame.date.max()>b:
                    raise DataError('Cached history outside requested dates')
                return frame
            try:
                if record and (not refresh or from_memory):
                    meta, frame = record
                    old_lo,old_hi = pd.Timestamp(meta['start_date']),pd.Timestamp(meta['end_date'])
                    if old_lo<=lo and old_hi>=hi and (from_memory or self.clock()-meta['fetched_at']<self.ttl):
                        self.metrics['hits']+=1
                        self.memory[key]=record
                        value=self.slice(frame,lo,hi);value.attrs.update(meta,cache_hit=True)
                        return value
                    target_lo,target_hi=min(lo,old_lo),max(hi,old_hi)
                    if target_lo<old_lo:
                        # First full-stock evaluation extends the sector window.
                        # A full validated response guarantees a single qfq anchor.
                        frame=get(target_lo,target_hi)
                        self.metrics['prefix_fetches']+=1
                        lo_store,hi_store=target_lo,target_hi
                        return self._store(key,provider,symbol,adjustment,frame,lo_store,hi_store,lo,hi)
                    # Revalidate a pre-existing overlap at the new source anchor.
                    # Include the prior final quote even after a long holiday.
                    overlap_start=max(old_lo,frame.date.max()-pd.Timedelta(days=14))
                    tail=get(overlap_start,target_hi)
                    overlap=frame.date.isin(tail.date)
                    common=sorted(set(frame.columns)&set(tail.columns))
                    try:
                        if not overlap.any():
                            raise AssertionError('No adjustment-anchor overlap')
                        pd.testing.assert_frame_equal(frame.loc[overlap,common].reset_index(drop=True),
                            tail.loc[tail.date.isin(frame.date),common].reset_index(drop=True),
                            check_dtype=False,check_exact=True)
                    except AssertionError:
                        self.metrics['anchor_refreshes']+=1
                        frame=get(target_lo,target_hi)
                    else:
                        frame=pd.concat([frame.loc[~frame.date.isin(tail.date)],tail]).sort_values('date').reset_index(drop=True)
                        self.metrics['incremental_fetches']+=1
                        if target_lo<old_lo:
                            # Prefix extension is rare (sector -> full stock).
                            # Fetch full range for qfq rather than merge an
                            # unverified older adjustment segment.
                            if adjustment=='qfq':
                                frame=get(target_lo,target_hi)
                            else:
                                prefix=get(target_lo,old_lo-pd.Timedelta(days=1))
                                frame=pd.concat([prefix,frame]).sort_values('date').reset_index(drop=True)
                            self.metrics['prefix_fetches']+=1
                    lo_store,hi_store=target_lo,target_hi
                else:
                    frame=get(lo,hi)
                    lo_store,hi_store=lo,hi
                    self.metrics['cold_fetches']+=1
                return self._store(key,provider,symbol,adjustment,frame,lo_store,hi_store,lo,hi)
            except Exception:
                self.metrics['failures']+=1
                # Do not advance coverage or overwrite the last good record.
                raise

    def _store(self,key,provider,symbol,adjustment,frame,lo_store,hi_store,lo,hi):
        frame=DataValidator.validate(frame,suffixes=('',))
        meta=dict(provider=provider,symbol=symbol,adjustment=adjustment,
                  start_date=str(lo_store.date()),end_date=str(hi_store.date()),
                  fetched_at=self.clock(),data_status='VALID',
                  validation='OHLC/date/symbol + exact overlap; qfq anchor changes force full refresh')
        payload=frame.to_json(orient='table',date_format='iso',index=False,double_precision=15)
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR REPLACE INTO history_v1 VALUES(?,?,?)',(key,json.dumps(meta),payload))
        self.memory[key]=(meta,frame.copy(deep=True))
        value=self.slice(frame,lo,hi);value.attrs.update(meta,cache_hit=False)
        return value

    def bind(self, provider, *, refresh=False):
        """Wrap only normalized data methods, leaving SDK validation unchanged."""
        original=getattr(provider,'_screening_daily_original',provider.fetch_stock_daily)
        benchmark=getattr(provider,'_screening_benchmark_original',provider.fetch_benchmark)
        provider._screening_daily_original=original
        provider._screening_benchmark_original=benchmark
        def daily(symbol,start,end,adjustment='raw'):
            return self.fetch(provider.name,symbol,adjustment,start,end,
                              lambda a,b:original(symbol,a,b,adjustment),refresh=refresh)
        def index(start,end):
            return self.fetch(provider.name,'000001.SH','NONE',start,end,benchmark,refresh=refresh)
        provider.fetch_stock_daily=daily
        provider.fetch_benchmark=index
