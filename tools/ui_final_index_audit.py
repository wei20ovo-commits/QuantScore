from pathlib import Path
import json,pandas as pd
from app.data.baostock_provider import BaoStockProvider
if __name__=='__main__':
 p=BaoStockProvider();out=[]
 for name,code in [('上证指数','sh.000001'),('深证成指','sz.399001'),('创业板指','sz.399006'),('沪深300','sh.000300'),('科创50','sh.000688')]:
  r={'name':name,'code':code}
  try:
   basic=p._call('query_stock_basic',code=code)
   r['basic']=basic.to_dict('records')
   d=p._history(code[3:]+'.'+code[:2].upper(),'2026-08-01','2026-09-26','raw',index=True)
   r.update(status='PASS',rows=len(d),last_date=str(d.date.iloc[-1].date()),close=float(d.close.iloc[-1]))
  except Exception as exc:r.update(status='UNAVAILABLE',error=str(exc))
  out.append(r);print(json.dumps(r,ensure_ascii=False),flush=True)
 Path('outputs/runtime/ui_final_index_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
