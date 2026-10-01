from pathlib import Path
import sys,json,time,socket
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import baostock as bs
import pandas as pd
if __name__=='__main__':
 socket.setdefaulttimeout(12);out=ROOT/'outputs/stage3b1_recovery';end=json.loads((out/'date_context.json').read_text(encoding='utf-8'))['latest_completed_trade_date'];start=str((pd.Timestamp(end)-pd.Timedelta(days=40)).date());fields='date,code,close';rows=[]
 for add in ['', 'open','high','low','preclose','volume','amount','turn','tradestatus','pctChg','isST','adjustflag']:
  if add:fields+=','+add
  for attempt in range(1,4):
   login=bs.login()
   try:
    r=bs.query_history_k_data_plus('sh.600519',fields,start_date=start,end_date=end,frequency='d',adjustflag='3');data=[]
    while r.error_code=='0' and r.next():data.append(r.get_row_data())
    rows.append(dict(added_field=add or 'minimal',fields=fields,symbol='sh.600519',start_date=start,end_date=end,frequency='d',adjustflag='3',login_code=login.error_code,login_msg=login.error_msg,query_error_code=r.error_code,query_error_msg=r.error_msg,returned_rows=len(data),attempt=attempt,timestamp=pd.Timestamp.now(tz='UTC').isoformat()));print(rows[-1],flush=True)
   finally:bs.logout()
   pd.DataFrame(rows).to_csv(out/'incremental_fields.csv',index=False)
   time.sleep(.5)
   if r.error_code=='0' and data:break
