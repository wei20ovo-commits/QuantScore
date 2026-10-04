"""Atomic manifest and immutable per-object evidence for resumable runs."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


class CheckpointStore:
    version=1
    def __init__(self,directory):
        self.root=Path(directory)
        self.root.mkdir(parents=True,exist_ok=True)
        self.written={}

    def atomic(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        text=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        temporary=path.with_suffix(path.suffix+'.tmp')
        temporary.write_text(text,encoding='utf-8')
        temporary.replace(path)
        return hashlib.sha256(text.encode()).hexdigest()

    def save(self,result,universe,selected):
        references={}
        for kind,key in [('sectors','sector_id'),('stocks','symbol')]:
            refs=[]
            for row in result[kind]:
                identity=(kind,row[key])
                relative=f'checkpoint_objects/{kind}/{row[key]}.json'
                if identity not in self.written:
                    self.written[identity]=self.atomic(self.root/relative,row)
                refs.append(dict(id=row[key],path=relative,sha256=self.written[identity]))
            references[kind]=refs
        summary={k:v for k,v in result.items() if k not in ('sectors','stocks','candidates')}
        payload=dict(checkpoint_version=self.version,result=summary,universe=universe,
                     universe_sha256=digest(universe),selected=selected,objects=references,
                     eligible_industries=[r['sector_id'] for r in result['sectors'] if r['candidate_status']=='ELIGIBLE'])
        self.atomic(self.root/'checkpoint.json',payload)

    def load(self,*,day,policy,universe,selected):
        d=json.loads((self.root/'checkpoint.json').read_text('utf-8'))
        r=d['result']
        if (d.get('checkpoint_version')!=self.version or r['trade_date']!=day
                or any(r.get(k)!=v for k,v in [('spec_version','1.4'),('assumption_version','v1.3'),('data_contract_version','1.4')])
                or digest(r['policy'])!=digest(asdict(policy)) or d['universe_sha256']!=digest(universe)
                or d['selected']!=selected):
            raise ValueError('CHECKPOINT_INCOMPATIBLE: date/version/policy/universe/selection')
        result=deepcopy(r)
        for kind in ('sectors','stocks'):
            result[kind]=[]
            identities=set()
            for item in d['objects'][kind]:
                path=(self.root/item['path']).resolve()
                if not path.is_relative_to(self.root.resolve()) or item['id'] in identities:
                    raise ValueError('CHECKPOINT_INCONSISTENT: path or duplicate object')
                payload=path.read_bytes()
                if hashlib.sha256(payload).hexdigest()!=item['sha256']:
                    raise ValueError('CHECKPOINT_INCONSISTENT: object digest')
                row=json.loads(payload)
                if row.get('trade_date')!=day or row.get('sector_id' if kind=='sectors' else 'symbol')!=item['id']:
                    raise ValueError('CHECKPOINT_INCONSISTENT: object identity/date')
                if kind=='sectors' and item['id'] not in selected:
                    raise ValueError('CHECKPOINT_INCONSISTENT: sector selection')
                if kind=='stocks' and item['id'] not in universe.get(row['primary_industry'],{}).get('symbols',[]):
                    raise ValueError('CHECKPOINT_INCONSISTENT: primary membership')
                identities.add(item['id'])
                result[kind].append(row)
                self.written[(kind,item['id'])]=item['sha256']
        result['candidates']=[]
        result['status']='RUNNING'
        return result
