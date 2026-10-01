from pathlib import Path
import sys,json,socket,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import baostock as bs
OUT=ROOT/'outputs/stage3b1_recovery'
F='date,code,open,high,low,close,preclose,pctChg,volume,amount,adjustflag,turn,tradestatus,isST'
if __name__=='__main__':
 socket.setdefaulttimeout(45);records=[]
 for a,b in [('2000-01-01','2003-12-31'),('2022-01-01','2025-12-31')]:
  for flag in ['3','2']:
   t=time.monotonic();login=bs.login()
   try:
    r=bs.query_history_k_data_plus('sh.600519',F,start_date=a,end_date=b,frequency='d',adjustflag=flag);data=[]
    while r.error_code=='0' and r.next():data.append(r.get_row_data())
    row=dict(start=a,end=b,flag=flag,login_code=login.error_code,error_code=r.error_code,error_msg=r.error_msg,rows=len(data),elapsed=time.monotonic()-t);records.append(row);print(row,flush=True)
   finally:bs.logout()
   (OUT/'bounded_window_tests.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');time.sleep(.3)
