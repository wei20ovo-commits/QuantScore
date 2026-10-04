"""Reuse an unchanged full ScoreEngine result, never approximate a score.

The fingerprint includes all prepared frames, business metadata, frozen R7
snapshots, registry, parameters and versions. Acquisition-only provenance is
excluded from the key and refreshed on return. Changed inputs re-run the engine.
"""
from dataclasses import asdict,is_dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from copy import deepcopy
import pandas as pd
import numpy as np
from datetime import date,datetime

TRANSPORT_FIELDS={'provenance','data_provenance','retrieved_at','requests','cache_hit',
                  'last_updated','fetch_time','fetched_at','provider_attempts'}

def stable(value):
    if isinstance(value,pd.DataFrame):
        return dict(columns=list(value.columns),dtypes=list(map(str,value.dtypes)),
                    values_sha256=hashlib.sha256(pd.util.hash_pandas_object(value,index=True).values.tobytes()).hexdigest())
    if is_dataclass(value):return stable(asdict(value))
    if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in TRANSPORT_FIELDS}
    if isinstance(value,(list,tuple)):return [stable(v) for v in value]
    if isinstance(value,(pd.Timestamp,np.datetime64,date,datetime)):return str(value)
    if isinstance(value,np.generic):return stable(value.item())
    if isinstance(value,float) and not np.isfinite(value):return str(value)
    return value


class ScoreMemo:
    def __init__(self,path,control=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.hits=self.misses=0
        self.control=control
        root=Path(__file__).resolve().parents[1]
        sources=sorted(p for directory in ('engine','rules','features') for p in (root/directory).rglob('*.py'))
        self.source_digest=hashlib.sha256(b''.join(str(p.relative_to(root)).encode()+p.read_bytes() for p in sources)).hexdigest()
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS score_memo_v1 (key TEXT PRIMARY KEY,payload TEXT NOT NULL)')

    def key(self,context,engine):
        h=hashlib.sha256()
        for frame in (context.bars,context.benchmark):
            if frame is None:
                h.update(b'None');continue
            h.update(json.dumps(list(zip(frame.columns,map(str,frame.dtypes)))).encode())
            h.update(pd.util.hash_pandas_object(frame,index=True).values.tobytes())
        business=dict(metadata=stable(context.metadata),as_of=context.as_of,
                      registry=engine.rule_engine.registry,parameters=engine.rule_engine.parameters,
                      spec_version='1.4',assumption_version='v1.3',data_contract_version='1.4',memo_version=1)
        business['score_source_sha256']=self.source_digest
        h.update(json.dumps(business,sort_keys=True,ensure_ascii=False,allow_nan=False).encode())
        return h.hexdigest()

    def bind(self,engine,profile=None):
        original=engine.evaluate
        def evaluate(context):
            key=self.key(context,engine)
            with sqlite3.connect(self.path) as db:
                row=db.execute('SELECT payload FROM score_memo_v1 WHERE key=?',(key,)).fetchone()
            if row:
                self.hits+=1
                output=json.loads(row[0])
                for rule in output['rules']:
                    rule['data_provenance']=deepcopy(context.metadata.get('data_provenance',[]))
                return output
            self.misses+=1
            if self.control:
                from .runtime import bounded_score
                if profile:
                    with profile.phase('QuantScore'):
                        output=bounded_score(context,engine,self.control)
                else:
                    output=bounded_score(context,engine,self.control)
            else:
                output=original(context)
            payload=json.dumps(output,ensure_ascii=False,allow_nan=False)
            with sqlite3.connect(self.path) as db:
                db.execute('INSERT OR REPLACE INTO score_memo_v1 VALUES(?,?)',(key,payload))
            return output
        engine.evaluate=evaluate
