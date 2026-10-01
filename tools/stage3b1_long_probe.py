from pathlib import Path
import sys,socket,json,time,io
from contextlib import redirect_stdout
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import baostock as bs
import pandas as pd
from app.data.baostock_provider import BaoStockProvider
OUT=ROOT/'outputs/stage3b1_recovery'
FIELDS='date,code,open,high,low,close,preclose,pctChg,volume,amount,adjustflag,turn,tradestatus,isST'
def main():
 end=json.loads((OUT/'date_context.json').read_text(encoding='utf-8'))['latest_completed_trade_date'];rows=[]
 for timeout,fields in [(12,'date,code,close'),(12,FIELDS),(60,FIELDS)]:
  socket.setdefaulttimeout(timeout);log=io.StringIO();t=time.monotonic();entry=dict(kind='direct',socket_timeout=timeout,code='sh.600519',fields=fields,start_date='2000-01-01',end_date=end,frequency='d',adjustflag='3')
  with redirect_stdout(log):
   try:
    login=bs.login();entry.update(login_code=login.error_code,login_msg=login.error_msg)
    r=bs.query_history_k_data_plus(entry['code'],fields,start_date=entry['start_date'],end_date=end,frequency='d',adjustflag='3');entry.update(query_error_code=r.error_code,query_error_msg=r.error_msg);data=[]
    while r.error_code=='0' and r.next():data.append(r.get_row_data())
    entry.update(final_error_code=r.error_code,final_error_msg=r.error_msg,rows=len(data),last_date=data[-1][0] if data else None)
   finally:bs.logout()
  entry.update(elapsed=time.monotonic()-t,sdk_stdout=log.getvalue());rows.append(entry);(OUT/'long_window_tests.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');print(entry,flush=True)
 p=BaoStockProvider(timeout=150);t=time.monotonic();entry=dict(kind='current_wrapper',code='600519.SH',start_date='2000-01-01',end_date=end,adjustment='raw',actual_parameters=dict(code='sh.600519',fields=FIELDS,start_date='2000-01-01',end_date=end,frequency='d',adjustflag='3'))
 try:
  df=p.fetch_stock_daily('600519.SH','2000-01-01',end,'raw');entry.update(rows=len(df),last_date=str(df.date.max()),status='SUCCESS')
 except Exception as exc:entry.update(status='FAILED',error=str(exc))
 entry['elapsed']=time.monotonic()-t;rows.append(entry);(OUT/'long_window_tests.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');print(entry,flush=True)
if __name__=='__main__':main()
