"""Scheduler entry: project-local temp files, explicit full scan, safe status."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    temp=ROOT/'outputs/runtime/market-update/tmp';temp.mkdir(parents=True,exist_ok=True)
    os.environ.update({key:str(temp) for key in ('TMP','TEMP','TMPDIR')})
    import tempfile
    tempfile.tempdir=str(temp)
    from app.market_update import daily_update
    from app.screening.runtime import RuntimeLimits
    result=daily_update(ROOT,execute=True,resume=os.environ.get('UPDATE_RESUME','').lower()=='true',
                        limits=RuntimeLimits(run_seconds=43200))
    print(json.dumps(result,ensure_ascii=False))
    return int(result['status'] not in ('PUBLISHED','MARKET_NOT_CLOSED','NON_TRADING_DAY'))

if __name__=='__main__':raise SystemExit(main())
