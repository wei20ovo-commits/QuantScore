"""Small genuine smoke, then full SH/SZ dry run; no mock, no candidate cap."""
from pathlib import Path
import sys,json,argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.screening.service import ScreeningService

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--full',action='store_true')
    args=parser.parse_args()
    out=ROOT/'outputs/stage3c'
    small=ScreeningService().run(industry_ids=['C15','C25','H61'],output_dir=out/'small_live')
    print('SMALL',small['status'],small['stats'],flush=True)
    sectors={s['sector_id']:s for s in small['sectors']}
    verified=(not small['is_mock'] and set(sectors)=={'C15','C25','H61'}
              and sectors['H61']['sector_heat'] is None and sectors['H61']['data_status']=='DATA_INCOMPLETE'
              and sectors['C15']['data_status']=='VALID' and sectors['C25']['data_status']=='VALID'
              and small['stats']['stock_analyzed']==small['stats']['stock_expected']
              and small['stats']['stock_analyzed']>0 and small['stats']['provider_error']==0)
    (out/'small_live_gate.json').write_text(json.dumps(dict(verified=verified,trade_date=small['trade_date']),indent=2),encoding='utf-8')
    if not verified:
        raise RuntimeError('Small real smoke did not satisfy acceptance; full dry run must not start')
    # Both backend entry points invoke real Providers, using ordinary valid cache.
    from app.cli import main as cli
    from contextlib import redirect_stdout,redirect_stderr
    with (out/'cli_screen.json').open('w',encoding='utf-8') as stdout,(out/'cli_screen_error.txt').open('w',encoding='utf-8') as stderr:
        with redirect_stdout(stdout),redirect_stderr(stderr):
            exit_code=cli(['screen','--industry','H61','--json','--output-dir',str(out/'cli_live')])
    (out/'cli_exit.txt').write_text(str(exit_code),encoding='utf-8')
    from fastapi.testclient import TestClient
    from app.api import create_app
    response=TestClient(create_app()).get('/api/screen',params={'industry_id':'H61'})
    (out/'api_screen.json').write_text(json.dumps(response.json(),ensure_ascii=False,indent=2),encoding='utf-8')
    if exit_code!=0 or response.status_code!=200 or response.json()['is_mock'] or response.json()['status']=='DATA_ERROR':
        raise RuntimeError('Real CLI/API screening acceptance failed')
    print('CLI_API_SUCCESS',flush=True)
    if args.full:
        full=ScreeningService().run(output_dir=out/'full_market')
        print('FULL',full['status'],full['stats'],flush=True)
        if full['stats']['industry_total']!=full['industry_universe_total']:
            raise RuntimeError('Incomplete sector universe scan')

if __name__=='__main__':main()
