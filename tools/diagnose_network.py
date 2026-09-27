"""Bounded real SDK diagnostics. Never mutates machine proxy settings."""
import json, os, re, inspect, multiprocessing as mp, traceback, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT=Path(__file__).resolve().parents[1]
KEYS=('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy')

def redact(text):
    text=re.sub(r'(https?://)[^/\s@]+@',r'\1[REDACTED]@',str(text))
    return re.sub(r'(?i)((?:token|api_key|password|cookie)[=:\s]+)[^&\s\"\x27]+',r'\1[REDACTED]',text)

def proxy_summary():
    def safe(value):
        if value is None:return None
        return redact(value)
    return {'environment':{k:safe(os.environ.get(k)) for k in KEYS},
            'urllib_effective':{k:safe(v) for k,v in urllib.request.getproxies().items()}}

def worker(conn,method,kwargs,direct):
    import requests, akshare
    before=dict(os.environ);original_init=requests.sessions.Session.__init__
    original_send=requests.sessions.Session.send
    requests_seen=[]
    def init(self,*a,**kw):
        original_init(self,*a,**kw)
        if direct:self.trust_env=False
    def send(self,request,**kw):
        kw['timeout']=10
        parts=urlsplit(request.url)
        requests_seen.append({'endpoint':urlunsplit((parts.scheme,parts.netloc,parts.path,'','')),
                              'trust_env':self.trust_env,'proxies':{k:redact(v) for k,v in (kw.get('proxies') or {}).items()}})
        return original_send(self,request,**kw)
    output={'method':method,'mode':'direct_process_only' if direct else 'normal','proxy_configuration':proxy_summary()}
    try:
        requests.sessions.Session.__init__=init;requests.sessions.Session.send=send
        frame=getattr(akshare,method)(**kwargs)
        output.update(status='SUCCESS' if len(frame) else 'EMPTY',rows=len(frame),columns=list(frame))
        output['last_row']=json.loads(frame.tail(1).to_json(orient='records',date_format='iso',force_ascii=False))
    except Exception as exc:
        chain=[];seen=set()
        def collect(e):
            if not isinstance(e,BaseException) or id(e) in seen:return
            seen.add(id(e));chain.append({'type':type(e).__name__,'message':redact(e)})
            collect(e.__cause__);collect(e.__context__);collect(getattr(e,'reason',None))
            for arg in e.args:collect(arg)
        collect(exc)
        output.update(status='FAILED',exception_chain=chain,traceback=redact(traceback.format_exc()))
    finally:
        requests.sessions.Session.__init__=original_init;requests.sessions.Session.send=original_send
        output.update(requests=requests_seen,environment_unchanged=dict(os.environ)==before,
                      session_methods_restored=requests.sessions.Session.__init__ is original_init)
    conn.send(output);conn.close()

def main():
    import akshare
    ctx=mp.get_context('spawn');cases=[]
    end=datetime.now().strftime('%Y%m%d')
    for method,kwargs in [('stock_zh_a_hist',dict(symbol='600519',period='daily',start_date='20230101',end_date=end,adjust='',timeout=10)),
                          ('stock_zh_a_hist',dict(symbol='600519',period='daily',start_date='20230101',end_date=end,adjust='qfq',timeout=10)),
                          ('stock_zh_index_daily_em',dict(symbol='sh000001',start_date='20230101',end_date=end))]:
        for direct in (False,True):
            recv,send=ctx.Pipe(False);process=ctx.Process(target=worker,args=(send,method,kwargs,direct));process.start();send.close()
            if recv.poll(35):row=recv.recv()
            else:row={'method':method,'mode':'direct_process_only' if direct else 'normal','status':'TIMEOUT'}
            process.join(.2)
            if process.is_alive():process.terminate();process.join()
            recv.close();row['adjustment']=kwargs.get('adjust','NONE');cases.append(row)
            print(method,row['mode'],row['status'],flush=True)
    result={'run_at':datetime.now(timezone.utc).isoformat(),'akshare_version':akshare.__version__,
            'parent_proxy_configuration':proxy_summary(),'signatures':{m:str(inspect.signature(getattr(akshare,m))) for m in ('stock_zh_a_hist','stock_zh_index_daily_em')},'cases':cases}
    path=ROOT/'outputs/runtime/stage2_1_network_diagnosis.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Evidence:',str(path.relative_to(ROOT)))
if __name__=='__main__':main()
