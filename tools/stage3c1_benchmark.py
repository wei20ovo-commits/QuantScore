"""Fixed real-data transport replay. Not a live network benchmark or mock data.

Normalized frames are read from the retained BaoStock SQLite evidence. The
production engines are re-executed over all members, without sampling. Transport
counts are normalized frame requests, not SDK field-group/page requests.
"""
import argparse
from collections import defaultdict
from io import StringIO
import json
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import patch
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if '--label' in sys.argv and sys.argv[sys.argv.index('--label')+1]=='baseline':
    # The baseline is the current audited clean HEAD, not superseded history.
    # Freeze it before implementation edits; never reset/checkout the workspace.
    import app.screening
    snapshot=ROOT/'outputs/stage3c1/baseline_source'
    if not (snapshot/'service.py').exists():
        raise RuntimeError('Baseline source snapshot missing; see Stage3C1 report')
    app.screening.__path__.insert(0,str(snapshot))
from app.data.baostock_provider import BaoStockProvider
from app.data.cache import DataCache
from app.screening.live import LiveScreeningAdapter
from app.screening.profiling import RunProfile, instrument_engines
from app.screening.service import ScreeningService

DAY = '2026-09-30'
SECTORS = ['C15', 'C26', 'H61']


class RecordedTransport(BaoStockProvider):
    """Read-only real normalized response store; missing evidence raises."""
    def __init__(self, path):
        super().__init__()
        self.path = str(path)
        self.index = defaultdict(list)
        self.frames = {}
        self.requests = []
        self.profile = RunProfile()
        with sqlite3.connect(self.path) as db:
            for encoded, in db.execute('SELECT key FROM frames'):
                k = json.loads(encoded)
                if k['provider'] == 'baostock':
                    self.index[(k['symbol'], k['adjustment'])].append((k, encoded))

    def read(self, encoded):
        if encoded not in self.frames:
            with sqlite3.connect(self.path) as db:
                payload, = db.execute('SELECT payload FROM frames WHERE key=?', (encoded,)).fetchone()
            self.frames[encoded] = pd.read_json(StringIO(payload), orient='table')
        return self.frames[encoded].copy(deep=True)

    def range(self, symbol, adjustments, start, end):
        options = [item for adj in adjustments for item in self.index[(symbol, adj)]
                   if pd.Timestamp(item[0]['start_date']) <= pd.Timestamp(start)
                   and pd.Timestamp(item[0]['end_date']) >= pd.Timestamp(end)]
        if not options:
            raise ValueError(f'Missing real archive: {symbol} {adjustments} {start} {end}')
        # Latest source anchor, largest range: same inputs across every run.
        key, encoded = sorted(options, key=lambda item: (item[0]['end_date'],
                                    -pd.Timestamp(item[0]['start_date']).value), reverse=True)[0]
        frame = self.read(encoded)
        return frame.loc[pd.to_datetime(frame.date).between(pd.Timestamp(start), pd.Timestamp(end))].reset_index(drop=True)

    def _call(self, method, **kwargs):
        start = time.perf_counter()
        self.requests.append(dict(method=method, parameters={k:str(v) for k,v in kwargs.items()}))
        with self.profile.phase('recorded_transport_read'):
            if method == 'query_stock_industry':
                return self.read(next(e for k,e in self.index[('SH_SZ','industry_context:membership')] if k['end_date'] == DAY))
            if method == 'query_stock_basic':
                frame = self.read(next(e for k,e in self.index[('all','industry_context:metadata')] if k['end_date'] == DAY))
                return frame if not kwargs.get('code') else frame.loc[frame.code.eq(kwargs['code'])].copy()
            if method == 'query_trade_dates':
                frames = [self.read(e) for entries in self.index.values() for k,e in entries
                          if k['adjustment'] in ('calendar','industry_context:calendar','industry_context:recent_calendar')]
                frame = pd.concat(frames).drop_duplicates('calendar_date').sort_values('calendar_date')
                dates = pd.to_datetime(frame.calendar_date)
                lo, hi = pd.Timestamp(kwargs['start']), pd.Timestamp(kwargs['end'])
                sliced = frame.loc[dates.between(lo,hi)].reset_index(drop=True)
                if set(pd.date_range(lo,hi)) - set(pd.to_datetime(sliced.calendar_date)):
                    raise ValueError('Recorded calendar does not cover requested dates')
                return sliced
            return self.range(kwargs['symbol'],kwargs['adjustments'],kwargs['start'],kwargs['end'])

    def query_trade_dates(self, start_date, end_date, exchange=''):
        return self._call('query_trade_dates',start=start_date,end=end_date)

    def fetch_stock_daily(self, symbol, start_date, end_date, adjustment='raw'):
        return self._call('normalized_history',symbol=symbol,adjustments=(adjustment,'industry_context:'+adjustment),
                          start=start_date,end=end_date,adjustment=adjustment)

    def fetch_benchmark(self, start_date, end_date):
        return self._call('normalized_benchmark',symbol='000001.SH',adjustments=('NONE','industry_context:benchmark'),start=start_date,end=end_date)


def run(label, cache_path, output, optimized=False):
    provider = RecordedTransport(ROOT/'data/cache/market.sqlite3')
    cache = DataCache(cache_path, ttl=86400)
    from app.screening.history_cache import HistoryCache
    from app.screening.score_cache import ScoreMemo
    from app.screening.runtime import RuntimeLimits
    family='final' if label in ('optimized_final','warm_after_final') else 'optimized'
    adapter = LiveScreeningAdapter(provider, cache,
                  history_cache=HistoryCache(output/(family+'_history.sqlite3'),ttl=86400) if optimized else None,
                  score_memo=ScoreMemo(output/(family+'_scores.sqlite3')) if optimized else None) if optimized else LiveScreeningAdapter(provider,cache)
    adapter.mode = 'real-normalized-transport-replay'
    profile = RunProfile()
    for name in ('sector','stock','prepare'):
        profile.wrap(adapter,name,name+'_phase')
    profile.wrap(adapter.analysis_service,'_load','stock_data_fetch') if hasattr(adapter,'analysis_service') else None
    start = time.perf_counter()
    # Replay the original acquisition clock, not today's calendar. No invented
    # future calendar rows or prices are inserted into the historical evidence.
    with instrument_engines(profile), patch.object(pd.Timestamp, 'now',
            return_value=pd.Timestamp('2026-10-02 18:00:00',tz='Asia/Shanghai')):
        options=dict(industry_ids=SECTORS,output_dir=output/label)
        if optimized:options.update(optimized=True,runtime_limits=RuntimeLimits(stock_seconds=1800))
        result = ScreeningService(adapter).run(**options)
    duration = time.perf_counter()-start
    report = dict(label=label, duration_seconds=duration, mode=adapter.mode,
                  trade_date=result['trade_date'], stats=result['stats'],
                  profile=profile.to_dict(), metrics=result['performance'],
                  normalized_requests=provider.requests,
                  source='retained real BaoStock normalized SQLite frames',
                  is_live_network=False)
    (output/('profiling_'+label+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(label, duration, result['stats'], flush=True)
    return result, report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',default='baseline')
    parser.add_argument('--trace-errors',action='store_true')
    args=parser.parse_args()
    if args.trace_errors:
        import threading,traceback
        def trace(frame,event,arg):
            if event=='exception' and isinstance(arg[1],RuntimeError) and 'dictionary changed' in str(arg[1]):
                traceback.print_stack(frame)
            return trace
        sys.settrace(trace);threading.settrace(trace)
    output=ROOT/'outputs/stage3c1';output.mkdir(parents=True,exist_ok=True)
    name=('final_cache.sqlite3' if args.label in ('optimized_final','warm_after_final') else
          'optimized_cache.sqlite3' if args.label!='baseline' else 'baseline_cache.sqlite3')
    run(args.label,output/name,output,optimized=args.label!='baseline')

if __name__=='__main__':main()
