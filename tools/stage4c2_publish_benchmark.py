"""Export a portable verified benchmark from a read-only formal history cache.

No network, prices generated, cache modification or absolute runtime paths.
Run explicitly when publishing a new same-day context; Web never runs this tool.
"""
import argparse
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sqlite3
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.data.validators import DataValidator


def publish(source,root=ROOT):
    root=Path(root).resolve();source=(root/source).resolve()
    if not source.is_relative_to(root): raise ValueError('Source must be inside project')
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT metadata,payload FROM history_v1 WHERE key=?',
                       (json.dumps(['baostock','000001.SH','NONE']),)).fetchone()
    if row is None: raise ValueError('Benchmark not in formal history')
    meta=json.loads(row[0])
    if any(meta.get(k)!=v for k,v in [('data_status','VALID'),('provider','baostock'),
                                    ('symbol','000001.SH'),('adjustment','NONE')]):
        raise ValueError('Invalid source metadata')
    frame=DataValidator.validate(pd.read_json(StringIO(row[1]),orient='table'),suffixes=('',))
    day=str(frame.date.max().date())
    if not frame.symbol.eq('000001.SH').all() or day!=meta['end_date']:
        raise ValueError('Benchmark identity/date mismatch')
    directory=root/'data/published/market_context';directory.mkdir(parents=True,exist_ok=True)
    path=directory/'benchmark.csv'
    frame.to_csv(path,index=False,date_format='%Y-%m-%d')
    recovered=DataValidator.validate(pd.read_csv(path,float_precision='round_trip'),suffixes=('',))
    # All actual numeric evidence must survive CSV export exactly.
    for field in frame.select_dtypes('number').columns:
        pd.testing.assert_series_equal(frame[field],recovered[field],check_dtype=False,check_exact=True)
    manifest=dict(provider='baostock',symbol='000001.SH',adjustment_type='NONE',
        data_status='VALID',is_mock=False,trade_date=day,rows=len(frame),
        file=path.relative_to(root).as_posix(),sha256=sha256(path.read_bytes()).hexdigest(),
        retrieved_at_epoch=meta['fetched_at'],source_cache=source.relative_to(root).as_posix(),
        source_payload_sha256=sha256(row[1].encode()).hexdigest(),source_validation=meta['validation'],
        publication='Read-only export of Stage3C.1 verified real benchmark; no network or price transformation')
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
    return {k:manifest[k] for k in ('provider','trade_date','rows','file','sha256')}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',default='outputs/stage3c1/final_history.sqlite3')
    print(json.dumps(publish(parser.parse_args().source),ensure_ascii=True))
