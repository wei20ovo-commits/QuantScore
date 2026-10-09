"""Bounded real Web-path diagnosis. No secrets, raw WS frames or exception text."""
import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from time import monotonic

ROOT=Path(__file__).resolve().parents[1]
URL='https://quantscore-grrgr4oqy5pfhfqnyp9q9b.streamlit.app/'


def live(out):
    from app.data.cache import DataCache
    from app.web_backend import _analyze_inprocess
    from app.web_runtime import bounded_web_call
    from app.web_diagnostics import WebDataError
    cache=DataCache(out/'live_cache.sqlite3')
    before=monotonic()
    try:
        result=bounded_web_call(_analyze_inprocess,('600519',ROOT,cache),root=ROOT)
        report={'kind':'REAL_LOCAL_WEB_PATH','is_mock':False,
                'status':result['data_status']['status'],
                'symbol':result['symbol'],'name':result['name'],
                'trade_date':result['evaluation_date'],
                'quant_score':result['final_quant_score'],'risk':result['risk_level'],
                'rule_count':len(result['rules']),'chart_rows':len(result.get('chart',[])),
                'industry_data_status':result['industry_context'].get('data_status'),
                'industry_reason':result['industry_context'].get('reason_code'),
                'B1_B2':[{'rule_id':r['rule_id'],'status':r['status'],'score':r['score'],
                          'reason_code':r.get('reason_code')} for r in result['rules'] if r['rule_id'] in ('B1','B2')],
                'diagnostics':result.get('web_diagnostics'),
                'latency':result.get('web_latency')}
    except WebDataError as exc:
        report={'kind':'REAL_LOCAL_WEB_PATH','is_mock':False,'status':'FAILED',
                'diagnostics':exc.diagnostics}
    report['total_seconds']=round(monotonic()-before,4)
    (out/'local_live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'kind':report['kind'],'status':report['status'],'seconds':report['total_seconds']}),flush=True)


def public(out):
    from playwright.sync_api import sync_playwright
    from streamlit.proto.BackMsg_pb2 import BackMsg
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    report={'kind':'REAL_PUBLIC','ai_calls':0,'full_market_scan_submitted':False,
            'stock_submissions':0,'cloud_revision':None,'status':'RUNNING'}
    acks=[];safe_errors=[]
    def save(): (out/'public.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    def socket(ws):
        def sent(data):
            if not isinstance(data,bytes):return
            try:
                msg=BackMsg();msg.ParseFromString(data)
                if msg.WhichOneof('type')=='rerun_script':
                    for w in msg.rerun_script.widget_states.widgets:
                        if 'analyze_submit' in w.id and w.trigger_value:report['stock_submissions']+=1
            except Exception:pass
        def received(data):
            if not isinstance(data,bytes):return
            try:
                msg=ForwardMsg();msg.ParseFromString(data)
                if msg.WhichOneof('type')=='script_finished':acks.append(monotonic())
            except Exception:pass
        ws.on('framesent',sent);ws.on('framereceived',received)
    def safe(frame):
        text=frame.locator('body').inner_text(timeout=5000)
        if re.search(r'\bsk-[\w-]{12,}|\bBearer\s+\S+',text):raise RuntimeError('SENSITIVE_CONTENT_BLOCKED')
        return text
    save()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000});page.on('websocket',socket)
        page.on('pageerror',lambda _:safe_errors.append('PAGE_SCRIPT_ERROR'))
        frame=page;start=monotonic()
        try:
            response=page.goto(URL,wait_until='domcontentloaded',timeout=60000)
            report['http_status']=response.status if response else None
            for _ in range(60):
                matches=[f for f in page.frames if f.locator('.stApp').count()]
                if matches:frame=matches[0];break
                page.wait_for_timeout(1000)
            frame.get_by_role('heading',name='QuantScore',exact=True).wait_for(timeout=60000)
            until=monotonic()+30
            while not acks and monotonic()<until:page.wait_for_timeout(250)
            report['home_seconds']=round(monotonic()-start,4)
            frame.get_by_role('textbox',name='股票代码',exact=True).fill('600519')
            before=len(acks);start=monotonic()
            frame.get_by_role('button',name='开始分析',exact=True).click()
            last=start
            while monotonic()-start<255:
                page.wait_for_timeout(500);text=safe(frame)
                errors=frame.get_by_test_id('stAlertContentError')
                if errors.count() and len(acks)>before:
                    # Only fixed known UI phrases, never arbitrary response text.
                    phrases=['数据源返回不可用','达到运行时限','未返回完整结果','数据源或快照暂不可用','分析暂时未完成']
                    report.update(status='UNAVAILABLE',visible_error=[x for x in phrases if x in text]);break
                if len(acks)>before and '贵州茅台' in text and frame.locator('.js-plotly-plot').count():
                    report.update(status='ANALYSIS_SUCCESS',chart_visible=True);break
                if monotonic()-last>30:
                    report['waiting_seconds']=round(monotonic()-start,3);save();last=monotonic()
                    print(json.dumps({'kind':'REAL_PUBLIC','waiting_seconds':report['waiting_seconds']}),flush=True)
            else:report['status']='CLIENT_WAIT_LIMIT'
            report['analysis_seconds']=round(monotonic()-start,4)
            text=safe(frame)
            report['trade_dates']=sorted(set(re.findall(r'数据日期[：:\s]+(\d{4}-\d{2}-\d{2})',text)))
            report['industry_cards']=frame.locator('.industry-grid .summary-card').evaluate_all(
                '(els)=>els.map(el=>({label:el.querySelector(".summary-label")?.textContent,value:el.querySelector("b")?.textContent,status:el.querySelector("small")?.textContent}))')
            report['diagnostic_expander_present']='请求诊断' in text
            if report['diagnostic_expander_present']:
                frame.get_by_text('请求诊断 · 不含凭据',exact=True).click();safe(frame)
            page.screenshot(path=str(out/'public.png'),full_page=True)
        except Exception as exc:
            report.update(status='TRANSPORT_OR_BROWSER_FAILURE',error_type=type(exc).__name__)
        finally:
            report['page_errors']=safe_errors;save();browser.close()
    print(json.dumps({'kind':'REAL_PUBLIC','status':report['status'],'seconds':report.get('analysis_seconds')}),flush=True)


def adjustment_check(out):
    """One real fallback request, inspect validation only; never score it."""
    import numpy as np
    import pandas as pd
    from app.data.akshare_provider import AKShareProvider
    from app.data.validators import DataValidator
    from app.web_diagnostics import error_reason
    source=AKShareProvider();before=monotonic()
    report={'kind':'REAL_AKSHARE_VALIDATION_ONLY','is_mock':False,'scored':False}
    try:
        end=pd.Timestamp.now(tz='Asia/Shanghai').strftime('%Y%m%d')
        frame=source._call('stock_zh_a_hist',symbol='600519',period='daily',start_date='20000101',
                           end_date=end,adjust='qfq',timeout=source.timeout)
        frame=frame.rename(columns={'日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close'})
        values=frame[['open','high','low','close']].apply(pd.to_numeric,errors='raise')
        invalid=(~np.isfinite(values.to_numpy()) | (values.to_numpy()<=0)).any(axis=1)
        report.update(rows=len(frame),last_trade_date=str(pd.to_datetime(frame.date).max().date()),
                      invalid_price_rows=int(invalid.sum()),min_close=float(values.close.min()),
                      first_invalid_date=str(pd.to_datetime(frame.loc[invalid,'date']).min().date()) if invalid.any() else None)
        try:DataValidator.validate(frame,suffixes=('',));report['validation']='PASS'
        except Exception as exc:report.update(validation='REJECTED',reason_code=error_reason(exc))
    except Exception as exc:report.update(status='FAILED',reason_code=error_reason(exc))
    report['seconds']=round(monotonic()-before,4)
    (out/'adjustment_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--public',action='store_true')
    parser.add_argument('--adjustment-check',action='store_true');args=parser.parse_args()
    out=ROOT/'outputs/stage4c5'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');out.mkdir(parents=True)
    temp=ROOT/'outputs/tmp/stage4c5';temp.mkdir(parents=True,exist_ok=True)
    os.environ.update({k:str(temp) for k in ('TEMP','TMP','TMPDIR')})
    import tempfile
    tempfile.tempdir=str(temp)
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    print(json.dumps({'evidence':out.relative_to(ROOT).as_posix()}),flush=True)
    (adjustment_check if args.adjustment_check else public if args.public else live)(out)


if __name__=='__main__':main()
