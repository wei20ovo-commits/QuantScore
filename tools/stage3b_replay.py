"""Offline replay and independent, fixed manual worksheet comparison."""
from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.sector.replay import replay,write_results

def main():
    archive=ROOT/'outputs/stage35';out=ROOT/'outputs/stage3b'
    results=replay(archive);write_results(results,out)
    # Human worksheet read from Stage35 CSVs and SSOT, not computed by scoring code.
    manual=[('S1','0.2037460827% in [0,0.5%)',5),('S2','2.0161259615% in [2%,4%)',12),
            ('S3','4/17 < 50%',0),('S4','0 sealed; 17 valid',0),('S5','0.8080713148 < 0.9',0),
            ('S6','4 daily wins -> 8',8),('S7','0/17 < 5%',0),('TOTAL','5+12+0+0+0+8+0=25',25)]
    result=next(r for r in results if r.sector_id=='C25');rows=[]
    for rid,working,value in manual:
        actual=result.total_score if rid=='TOTAL' else getattr(result,rid.lower()).score
        rows.append(dict(sector='C25',rule_id=rid,manual_working=working,manual_score=value,engine_score=actual,match=value==actual))
    pd.DataFrame(rows).to_csv(out/'manual_crosscheck.csv',index=False)
    if not all(r['match'] for r in rows):raise ValueError('Manual worksheet mismatch; do not rewrite expected values')
    paths=list(archive.glob('s*_inputs.csv'))+[archive/'s4_constituent_details.csv',archive/'s5_daily_amounts.csv',archive/'s6_daily_comparisons.csv']
    (out/'replay_source_hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2),encoding='utf-8')
    print('Replay and independent manual worksheet: PASS')

if __name__=='__main__':main()
