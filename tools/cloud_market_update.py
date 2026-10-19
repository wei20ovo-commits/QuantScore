"""CLI for the disabled hosted candidate. Logs only a bounded safe summary."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--slice',type=int,choices=(1,2,3,4),required=True)
    parser.add_argument('--bundle')
    parser.add_argument('--seconds',type=int,default=14400)
    args=parser.parse_args()
    from app.cloud_update import run_slice
    result=run_slice(ROOT,slice_index=args.slice,producer=os.environ.get('GITHUB_RUN_ID','0'),
                     bundle=args.bundle,run_seconds=args.seconds)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    if result['status'] in ('BLOCKED','BUDGET_EXHAUSTED'):
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
