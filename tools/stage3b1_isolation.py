"""Direct SDK evidence; no QuantScore wrapper in the isolation matrix."""
from pathlib import Path
import sys,json,time,socket,itertools
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
import baostock as bs
OUT=ROOT/'outputs/stage3b1_recovery';OUT.mkdir(exist_ok=True)
MIN='date,code,close'
FULL='date,code,open,high,low,close,preclose,pctChg,volume,amount,adjustflag,turn,tradestatus,isST'
NORMAL='date,code,open,high,low,close,volume,amount,turn'
rows=[]
def query(label,symbol,fields,start,end,flag='3',login=None,attempt=1):
    own=login is None
    if own:login=bs.login()
    entry=dict(case=label,symbol=symbol,start_date=start,end_date=end,fields=fields,frequency='d',adjustflag=flag,login_code=login.error_code,login_msg=login.error_msg,attempt=attempt,timestamp=datetime.now(timezone.utc).isoformat())
    try:
        r=bs.query_history_k_data_plus(symbol,fields,start_date=start,end_date=end,frequency='d',adjustflag=flag)
        entry.update(query_error_code=r.error_code,query_error_msg=r.error_msg,returned_fields=','.join(r.fields));data=[]
        while r.error_code=='0' and r.next():data.append(r.get_row_data())
        entry.update(final_error_code=r.error_code,final_error_msg=r.error_msg,returned_rows=len(data),last_date=data[-1][0] if data else None)
    except Exception as exc:entry.update(query_error_code='EXCEPTION',query_error_msg=repr(exc),returned_rows=0)
    finally:
        if own:bs.logout()
    rows.append(entry);pd.DataFrame(rows).to_csv(OUT/'baostock_isolation_matrix.csv',index=False)
    print(label,symbol,flag,entry.get('query_error_code'),entry.get('query_error_msg'),entry['returned_rows'],flush=True)
    time.sleep(.3);return entry

def main():
    socket.setdefaulttimeout(12)
    now=pd.Timestamp.now(tz='Asia/Shanghai');cutoff=now.normalize().tz_localize(None)-(pd.Timedelta(days=1) if now.hour<16 else pd.Timedelta(0))
    login=bs.login();r=bs.query_trade_dates(start_date=str((cutoff-pd.Timedelta(days=45)).date()),end_date=str(cutoff.date()));cal=[]
    while r.error_code=='0' and r.next():cal.append(r.get_row_data())
    meta=dict(system_date=str(now),calendar_login_code=login.error_code,calendar_login_msg=login.error_msg,calendar_error_code=r.error_code,calendar_error_msg=r.error_msg)
    bs.logout();df=pd.DataFrame(cal,columns=r.fields);df.to_csv(OUT/'calendar.csv',index=False)
    days=df.loc[df.is_trading_day.eq('1'),'calendar_date'];end=days.max();meta.update(latest_trade_date=end,latest_completed_trade_date=end,requested_end_date=end)
    (OUT/'date_context.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    start=days.tail(15).iloc[0]
    a=query('A_minimal','sh.600519',MIN,start,end)
    if a['query_error_code']=='0':
        fields=MIN
        for field in ['open','high','low','preclose','volume','amount','turn','tradestatus','pctChg','isST','adjustflag']:
            fields+=','+field;query('add_'+field,'sh.600519',fields,start,end)
    for symbol,flag,length,fields in itertools.product(['sh.600519','sh.600000','sz.000001'],['3','2'],[10,40,120],[MIN,NORMAL,FULL]):
        query('matrix',symbol,fields,str((pd.Timestamp(end)-pd.Timedelta(days=length)).date()),end,flag)
    for label,sequence in [('sequential_3',[('sh.600519','3'),('sh.600000','3'),('sz.000001','3')]),('raw_qfq',[('sh.600519','3'),('sh.600519','2')]),('qfq_raw',[('sh.600519','2'),('sh.600519','3')])]:
        login=bs.login()
        try:
            for symbol,flag in sequence:query(label,symbol,FULL,start,end,flag,login)
        finally:bs.logout()
    for attempt in range(1,4):
        e=query('conservative_retry','sh.600519',FULL,start,end,attempt=attempt)
        if e['query_error_code']=='0' and e['returned_rows']:break
        time.sleep(attempt)
    data=pd.DataFrame(rows);data.loc[data['case'].isin(['A_minimal','sequential_3','raw_qfq','qfq_raw'])].to_csv(OUT/'session_tests.csv',index=False)
    data.loc[data['case'].eq('conservative_retry')].to_csv(OUT/'retry_log.csv',index=False)
if __name__=='__main__':main()
