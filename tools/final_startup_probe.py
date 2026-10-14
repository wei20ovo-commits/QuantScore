"""Offline startup failure/cleanup reproduction; never starts an SDK worker."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    temp=ROOT/'outputs/tmp/final-engineering/startup';temp.mkdir(parents=True,exist_ok=True)
    os.environ.update({k:str(temp) for k in ('TMP','TEMP','TMPDIR')})
    import tempfile
    tempfile.tempdir=str(temp)
    from app.screening.batch_provider import BatchBaoStockProvider
    p=BatchBaoStockProvider();result=dict(scope='OFFLINE_CONTROL',network_requests=0)
    with patch('multiprocessing.context.SpawnProcess.start',side_effect=PermissionError('OFFLINE_START_REJECTION')):
        try:p._start()
        except Exception as exc:result['startup_error']=type(exc).__name__
    try:p.close();result['cleanup']='OK'
    except Exception as exc:result['cleanup']=type(exc).__name__
    label=sys.argv[1]
    (ROOT/'outputs/final_engineering'/f'startup_{label}.json').write_text(json.dumps(result,indent=2),'utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
