"""有限公网验证：最多一次分析和一次成功后的缓存复验，仅保存白名单证据。"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://quantscore-grrgr4oqy5pfhfqnyp9q9b.streamlit.app/'
BASELINE = '8b57a7989612dd37727e8b1941bfacdb04477135'
OUT = ROOT / 'outputs/product_closure' / ('public_wake_verify' if '--wake-once' in sys.argv else 'public_verify')


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    keys = {'git_commit', 'code_fingerprint', 'source_modified', 'request_id',
            'cached_origin_request_id', 'diagnostic_version', 'event_type', 'layer',
            'outcome', 'reason_code', 'total_latency_seconds', 'web_cache',
            'stock_trade_date', 'industry_snapshot_date', 'benchmark_snapshot_date',
            'provider_requests', 'provider_timeouts', 'cache_hits', 'cache_misses',
            'web_deadline_seconds', 'total_backend_seconds', 'last_completed_stage',
            'raw_measurement', 'qfq_measurement', 'raw_fetch_seconds', 'qfq_fetch_seconds',
            'industry_data_status', 'benchmark_data_status', 'deployment', 'events',
            'stage', 'status', 'seconds', 'provider', 'method', 'adjustment',
            'raw_seconds','qfq_seconds','provider_timeout_count','provider_retry_count',
            'observed_provider_timeout_events','observed_fetch_retry_events',
            'data_cache_hits','data_cache_misses','partial_events',
            'provider_error_categories','data_error_categories','last_observed_stage'}
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k in keys}
    if isinstance(value, list):
        return [clean(v) for v in value[-100:]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.: -]{1,100}', value):
        return value
    return 'REDACTED'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    temp = OUT / 'browser_tmp'
    temp.mkdir(exist_ok=True)
    os.environ.update({k: str(temp) for k in ('TMP', 'TEMP', 'TMPDIR')})
    import tempfile
    tempfile.tempdir = str(temp)
    from playwright.sync_api import sync_playwright
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    from streamlit.proto.BackMsg_pb2 import BackMsg
    report = {'started_at_utc': now(), 'expected_revision': BASELINE,
              'deployment_identity': None, 'deployment_sha_status': 'UNEXPOSED',
              'cloud_management_access': 'NO_AUTHENTICATED_OWNER_SESSION',
              'intentional_clicks': 0, 'protocol_submissions': 0, 'runs': [],
              'ai_calls': 0, 'full_market_scan_submitted': False,
              'server_cache_reset': False, 'browser_automatic_retry': False,
              'scope':'IDENTITY_HOME_ONLY' if '--identity-only' in sys.argv else 'STOCK_ANALYSIS',
              'status': 'RUNNING', 'browser_closed': False}
    finished = []
    active = {'run': None, 'rule': None}

    def safe_fact(value):
        # Existing engine output only, never arbitrary response/log contents.
        if isinstance(value,dict):return {str(k):safe_fact(v) for k,v in value.items()}
        if isinstance(value,list):return [safe_fact(v) for v in value]
        if isinstance(value,str):
            if re.search(r'sk-[A-Za-z0-9]{20,}|[A-Za-z]:[/\\]|/(?:home|Users)/',value):return 'REDACTED'
            return value
        return value

    def save():
        (OUT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')

    def socket(ws):
        def inbound(data):
            if not isinstance(data, bytes):
                return
            try:
                msg = ForwardMsg(); msg.ParseFromString(data)
                if msg.WhichOneof('type') == 'script_finished':
                    finished.append(monotonic())
                if msg.WhichOneof('type') == 'delta' and msg.delta.WhichOneof('type') == 'new_element':
                    el = msg.delta.new_element
                    row=active['run']
                    kind=el.WhichOneof('type')
                    if row is not None and kind=='metric' and el.metric.label in ('QuantScore','Risk Level','Positive Score','Risk Penalty'):
                        row.setdefault('metrics',{})[el.metric.label]=safe_fact(el.metric.body)
                    if row is not None and kind=='selectbox' and el.selectbox.label=='解释模式':
                        row['ai_mode_options']=list(el.selectbox.options)
                    if row is not None and kind=='markdown':
                        body=el.markdown.body
                        match=re.fullmatch(r'\*\*([A-Z][0-9]+(?:-[A-Z])?) · (.+)\*\*',body)
                        if match:
                            active['rule']=match[1]
                            row.setdefault('observed_rules',{})[match[1]]={'rule_id':match[1],'name_cn':safe_fact(match[2])}
                        elif active['rule'] and body.startswith(('status：','score：','penalty：')):
                            row['observed_rules'][active['rule']][body.split('：',1)[0]]=safe_fact(body.split('：',1)[1])
                    obj = None
                    if el.WhichOneof('type') == 'json':
                        obj = json.loads(el.json.body)
                    elif el.WhichOneof('type') == 'code':
                        obj = json.loads(el.code.code_text)
                    if isinstance(obj, dict):
                        if 'git_commit' in obj and 'code_fingerprint' in obj:
                            report['deployment_identity'] = clean(obj)
                        elif 'request_id' in obj and active['run'] is not None:
                            active['run']['diagnostics'] = clean(obj)
                        elif row is not None and active['rule'] and kind=='json':
                            row['observed_rules'][active['rule']]['raw_values']=safe_fact(obj)
            except Exception:
                pass
        def outbound(data):
            if not isinstance(data, bytes):
                return
            try:
                msg = BackMsg(); msg.ParseFromString(data)
                if msg.WhichOneof('type') == 'rerun_script':
                    if any('analyze_submit' in w.id and w.trigger_value for w in msg.rerun_script.widget_states.widgets):
                        report['protocol_submissions'] += 1
            except Exception:
                pass
        ws.on('framereceived', inbound)
        ws.on('framesent', outbound)

    with sync_playwright() as pw:
        browser = None
        try:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('websocket', socket)
            response = page.goto(URL, wait_until='domcontentloaded', timeout=60000)
            report['http_status'] = response.status if response else None
            report['public_wake_clicks'] = 0
            if report['http_status'] == 502:
                raise RuntimeError('PUBLIC_HTTP_502_NO_RETRY')
            start = monotonic(); app = None
            while monotonic() - start < 60:
                matches = [f for f in page.frames if f.locator('.stApp').count()]
                if matches:
                    app = matches[0]; break
                if '--wake-once' in sys.argv and report['public_wake_clicks'] == 0:
                    wake = page.get_by_role('button', name=re.compile(r'^(Yes, get this app back up!|Wake up(?:.*)?|唤醒(?:.*)?)$', re.I))
                    if wake.count() == 1:
                        report['public_wake_button_found'] = True
                        report['public_wake_clicked_at_utc'] = now()
                        report['public_wake_clicks'] = 1
                        wake.click(timeout=10000)
                        start = monotonic()
                        save()
                page.wait_for_timeout(500)
            if app is None:
                report['visible_platform_markers'] = [s for s in ('Oh no.', 'Error', 'You do not have access', 'This app has gone to sleep', 'Wake up') if s in page.locator('body').inner_text()]
                report['public_wake_button_found'] = report.get('public_wake_button_found', False)
                report['status'] = 'BLOCKED'
                raise RuntimeError('PUBLIC_APP_NOT_AVAILABLE')
            app.get_by_role('heading', name='QuantScore', exact=True).wait_for(timeout=60000)
            app.locator('.stApp[data-test-script-state="notRunning"]').wait_for(timeout=30000)
            report['home_ready_at_utc'] = now()
            report['owner_manage_app_visible'] = any(f.get_by_text('Manage app', exact=True).count() > 0 for f in page.frames)
            report['deployment_expander_present'] = app.get_by_text('部署版本 · 可核验', exact=True).count() > 0
            if report['deployment_expander_present']:
                app.get_by_text('部署版本 · 可核验', exact=True).click()
                for block in app.get_by_test_id('stCode').all():
                    try:
                        obj = json.loads(block.inner_text())
                        if 'git_commit' in obj:
                            report['deployment_identity'] = clean(obj)
                    except (ValueError, TypeError):
                        pass
            identity = report['deployment_identity'] or {}
            revision = identity.get('git_commit')
            report['deployment_sha_status'] = 'MATCH' if revision == BASELINE else ('MISMATCH' if revision and revision != 'UNKNOWN' else 'UNEXPOSED')
            save()
            if report['deployment_sha_status']=='MISMATCH':
                raise RuntimeError('DEPLOYMENT_NOT_UPDATED')
            for index in range(0 if '--identity-only' in sys.argv else 2):
                record = {'request_number': index + 1, 'stock': '600519', 'started_at_utc': now(), 'status': 'RUNNING', 'diagnostics': None}
                report['runs'].append(record); active['run'] = record; active['rule']=None
                app.get_by_role('textbox', name='股票代码', exact=True).fill('600519')
                before = len(finished); started = monotonic()
                report['intentional_clicks'] += 1
                app.get_by_role('button', name='开始分析', exact=True).click()
                save()
                while monotonic() - started < 260:
                    page.wait_for_timeout(500)
                    if report['protocol_submissions'] > 2:
                        raise RuntimeError('UNEXPECTED_EXTRA_SUBMISSION')
                    if len(finished) > before and app.locator('.stApp[data-test-script-state="notRunning"]').count():
                        if app.get_by_test_id('stAlertContentError').count():
                            record['status'] = 'UNAVAILABLE'; break
                        if app.get_by_role('heading', name=re.compile('贵州茅台')).count() and app.get_by_test_id('stPlotlyChart').count():
                            record['status'] = 'ANALYSIS_SUCCESS'; break
                else:
                    record['status'] = 'CLIENT_260S_WAIT_LIMIT'
                record['elapsed_seconds'] = round(monotonic() - started, 3)
                record['completed_at_utc'] = now()
                text = app.locator('body').inner_text(timeout=5000)
                record['visible_error_markers'] = [s for s in ('数据源返回不可用', '达到运行时限', '未返回完整结果', '数据源或快照暂不可用', '分析暂时未完成') if s in text]
                record['trade_dates'] = sorted(set(re.findall(r'数据日期[：:\s]+(\d{4}-\d{2}-\d{2})', text)))
                record['rules_41_present']=app.get_by_text('全部规则明细（41条）',exact=True).count()>0
                record['ai_modes_present']=all(label in record.get('ai_mode_options',[]) for label in ('Standard Rules','AI Explanation','Auto'))
                for block in app.get_by_test_id('stCode').all():
                    try:
                        obj = json.loads(block.inner_text())
                        if 'request_id' in obj:
                            record['diagnostics'] = clean(obj)
                    except (ValueError, TypeError):
                        pass
                save()
                if record['status'] != 'ANALYSIS_SUCCESS':
                    break
            active['run']=None
            # UI reruns only; these controls never submit another analysis.
            report['theme_and_mobile_checks']={}
            for theme,label in [('dark','☾'),('light','☀')]:
                control=app.get_by_role('button',name=label,exact=True)
                if control.count():
                    control.click(timeout=10000)
                    # This is an empty, zero-height CSS state marker, not a
                    # visible card. Waiting for visibility always times out.
                    app.locator('.theme-'+theme).wait_for(state='attached',timeout=15000)
                    colour=app.locator('.stApp').evaluate('(e)=>getComputedStyle(e).backgroundColor')
                    report['theme_and_mobile_checks'][theme]=True
                    report['theme_and_mobile_checks'][theme+'_background']=colour
            page.set_viewport_size({'width':390,'height':844})
            report['theme_and_mobile_checks']['mobile_390']=app.get_by_role('button',name='开始分析',exact=True).is_visible()
            report['theme_and_mobile_checks']['mobile_no_horizontal_overflow']=app.locator('body').evaluate('(e)=>e.scrollWidth<=window.innerWidth+2')
            if '--identity-only' in sys.argv:
                report['status']='PASS' if report['deployment_sha_status']=='MATCH' and all(report['theme_and_mobile_checks'].get(k) for k in ('dark','light','mobile_390','mobile_no_horizontal_overflow')) else 'PARTIAL'
            else:
                report['status'] = 'PASS' if len(report['runs']) == 2 and all(r['status'] == 'ANALYSIS_SUCCESS' for r in report['runs']) and (report['runs'][1].get('diagnostics') or {}).get('web_cache') == 'HIT' and report['deployment_sha_status'] == 'MATCH' else 'PARTIAL'
        except Exception as exc:
            report['status'] = 'BLOCKED' if '--wake-once' in sys.argv and not report['runs'] else 'PARTIAL'
            report['error_type'] = type(exc).__name__
            if isinstance(exc, RuntimeError) and re.fullmatch('[A-Z0-9_]+', str(exc)):
                report['reason_code'] = str(exc)
        finally:
            if browser is not None:
                browser.close()
                report['browser_closed'] = True
            report['completed_at_utc'] = now(); save()
    print(json.dumps({'status': report['status'], 'deployment_sha_status': report['deployment_sha_status'], 'intentional_clicks': report['intentional_clicks'], 'protocol_submissions': report['protocol_submissions'], 'reason_code': report.get('reason_code'), 'browser_closed': report['browser_closed']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
