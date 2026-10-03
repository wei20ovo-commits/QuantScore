"""Read-only observation of original PID; no provider imports or scan calls."""
import csv
import datetime as dt
import json
from pathlib import Path
import sqlite3
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/stage3c'
PID = 11468

PS = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
$all=Get-CimInstance Win32_Process
$ids=@(11468)
do {
 $extra=@($all | Where-Object { $_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids } | ForEach-Object ProcessId)
 $ids += $extra
} while ($extra.Count -gt 0)
$rows=@($all | Where-Object { $_.ProcessId -in $ids } | ForEach-Object {
 [PSCustomObject]@{pid=$_.ProcessId;parent_pid=$_.ParentProcessId;start_time=$_.CreationDate.ToString('o');
 cpu_seconds=([double]$_.KernelModeTime+[double]$_.UserModeTime)/10000000;
 memory_bytes=[long]$_.WorkingSetSize;thread_count=$_.ThreadCount;open_handles=$_.HandleCount;
 command_line=$_.CommandLine}
})
$tcp=@(Get-NetTCPConnection | Where-Object { $_.OwningProcess -in $ids } | ForEach-Object {
 [PSCustomObject]@{pid=$_.OwningProcess;remote_address=$_.RemoteAddress;remote_port=$_.RemotePort;state=$_.State.ToString()}
})
@{processes=$rows;connections=$tcp} | ConvertTo-Json -Depth 5 -Compress
'''


def main():
    samples=[]
    previous={}
    previous_children=set()
    anchor=time.monotonic()
    for i in range(5):
        if i:
            time.sleep(max(0,anchor+i*30-time.monotonic()))
        now=dt.datetime.now(dt.timezone.utc)
        result=subprocess.run(['powershell','-NoProfile','-Command',PS],capture_output=True,encoding='utf-8',errors='replace')
        if result.returncode:
            raise RuntimeError(result.stderr)
        tree=json.loads(result.stdout.lstrip('\ufeff'))
        full=json.loads((OUT/'full_market/screening_details.json').read_text('utf-8'))
        path=ROOT/'data/cache/market.sqlite3'
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
            key,payload,updated=db.execute('select key,payload,last_updated from frames order by last_updated desc limit 1').fetchone()
            rows=json.loads(payload).get('data',[])
        business_files=[p for p in (OUT/'full_market').rglob('*') if p.is_file() and not p.name.endswith('.tmp')]
        latest=max(business_files,key=lambda p:p.stat().st_mtime)
        children={p['pid'] for p in tree['processes'] if p['pid']!=PID}
        sample=dict(timestamp=now.isoformat(),sample_number=i+1,original_pid=PID,original_alive=any(p['pid']==PID for p in tree['processes']),
            processes=tree['processes'],connections=tree['connections'],child_pids=sorted(children),child_pid_count=len(children),
            child_pid_changes=None if not i else len(children.symmetric_difference(previous_children)),
            children_started=[] if not i else sorted(children-previous_children),children_exited=[] if not i else sorted(previous_children-children),
            sector_count=len(full['sectors']),stock_count=len(full['stocks']),
            last_sector_id=full['sectors'][-1]['sector_id'] if full['sectors'] else None,
            last_sector_name=full['sectors'][-1]['sector_name'] if full['sectors'] else None,
            last_sector_status=full['sectors'][-1]['data_status'] if full['sectors'] else None,
            checkpoint_mtime=dt.datetime.fromtimestamp((OUT/'full_market/screening_details.json').stat().st_mtime,dt.timezone.utc).isoformat(),
            latest_modified_business_file=str(latest.relative_to(ROOT)),latest_modified_business_time=dt.datetime.fromtimestamp(latest.stat().st_mtime,dt.timezone.utc).isoformat(),
            latest_cache_write=dt.datetime.fromtimestamp(updated,dt.timezone.utc).isoformat(),latest_cache_key=json.loads(key),
            latest_provider_response=dict(evidence='persisted cache frame; not current in-flight request',rows=len(rows),key=json.loads(key),persisted_at=dt.datetime.fromtimestamp(updated,dt.timezone.utc).isoformat()),
            checkpoint_metrics=full['performance'],run_start_time=full['start_time'],end_time=full.get('end_time'))
        for p in sample['processes']:
            before=previous.get(p['pid'])
            p['cpu_percent_one_core']=None if not before else 100*(p['cpu_seconds']-before[0])/(now.timestamp()-before[1])
            previous[p['pid']]=(p['cpu_seconds'],now.timestamp())
        previous_children=children
        samples.append(sample)
        (OUT/'runtime_samples_detail.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2),'utf-8')
        with (OUT/'runtime_samples.csv').open('w',encoding='utf-8-sig',newline='') as f:
            cols=['timestamp','pid','parent_pid','start_time','cpu_seconds','cpu_percent_one_core','memory_bytes','thread_count','open_handles','child_pid_count','child_pid_changes','sector_count','stock_count','last_sector_id','last_sector_name','latest_cache_write']
            w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader()
            for s in samples:
                for p in s['processes']:
                    w.writerow(dict(s,**p))
        print(json.dumps({k:sample[k] for k in ('timestamp','sector_count','stock_count','child_pids','latest_cache_write')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
