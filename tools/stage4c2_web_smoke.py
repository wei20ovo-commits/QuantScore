"""Actual local Web analysis and read-only public deployment check.

No routes, mocks, data injection, AI calls, credentials, publish or browser HAR.
Client timings are not called public/server-cold benchmarks.
"""
import json
import os
from pathlib import Path
import re
from time import monotonic

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/stage4c2/web'
PUBLIC='https://quantscore-grrgr4oqy5pfhfqnyp9q9b.streamlit.app/'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    temporary=ROOT/'outputs/tmp/stage4c2-browser';temporary.mkdir(parents=True,exist_ok=True)
    os.environ.update({k:str(temporary) for k in ('TMP','TEMP','TMPDIR')})
    import tempfile
    tempfile.tempdir=str(temporary)
    from playwright.sync_api import sync_playwright
    report=dict(status='RUNNING',local_url='http://127.0.0.1:8503/',public_url=PUBLIC,
                is_mock=False,ai_calls=0,full_market_scan_triggered=False,
                public_optimized_cold_seconds=None,public_optimized_warm_seconds=None,
                public_optimized_status='NOT_DEPLOYED_NO_COMMIT_PUSH',
                public_limitation='Local modifications cannot reach Community Cloud under current no-commit/no-push instruction',
                local_cold_definition='First click in fresh browser; persistent market cache state not forced',
                local_warm_definition='Same-session second click; existing st.cache_data may serve result')
    def save():
        (OUT/'web_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    def check_text(frame):
        text=frame.locator('body').inner_text()
        if re.search(r'\bsk-[\w-]{12,}|\bBearer\s+\S+',text):raise RuntimeError('SENSITIVE_CONTENT_BLOCKED')
        return text
    save()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        try:
            response=page.goto(report['local_url'],wait_until='domcontentloaded',timeout=30000)
            report['local_http_status']=response.status
            page.get_by_role('heading',name='QuantScore',exact=True).wait_for(timeout=30000)
            page.locator('.stApp[data-test-script-state="notRunning"]').wait_for(timeout=30000)
            for run in ('client_first','same_session_warm'):
                page.get_by_role('textbox',name='股票代码',exact=True).fill('600519')
                t=monotonic();page.get_by_role('button',name='开始分析',exact=True).click()
                page.wait_for_timeout(400)
                page.locator('.stApp[data-test-script-state="notRunning"]').wait_for(timeout=280000)
                page.get_by_role('heading',name='贵州茅台 · 600519.SH',exact=True).wait_for(timeout=5000)
                page.locator('.js-plotly-plot').first.wait_for(timeout=30000)
                report[run+'_local_web_seconds']=round(monotonic()-t,3)
                text=check_text(page)
                assert 'baostock' in text.lower() and '2026-09-30' in text
                assert '当前展示：Standard Rules' in text
                report[run+'_real_analysis']='PASS'
                save();print(json.dumps({run:report[run+'_local_web_seconds']}),flush=True)
            page.screenshot(path=str(OUT/'analysis_light.png'),full_page=True)
            report['plotly_traces']=page.locator('.js-plotly-plot').first.evaluate(
                '(el)=>el.data.map(t=>({name:t.name,type:t.type,points:t.x.length}))')
            page.get_by_role('button',name='☾',exact=True).click()
            page.locator('.theme-dark').wait_for(state='attached')
            page.locator('.stApp[data-test-script-state="notRunning"]').wait_for(timeout=30000)
            check_text(page);page.screenshot(path=str(OUT/'analysis_dark.png'),full_page=True)
            report['local_light_dark']='PASS'
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(300);check_text(page)
            page.screenshot(path=str(OUT/'analysis_mobile.png'),full_page=True)
            report['local_mobile']='PASS' if not page.locator('html').evaluate('(el)=>el.scrollWidth>innerWidth') else 'FAIL'
            # Never start another long analysis on the unchanged cloud build.
            cloud=browser.new_page(viewport={'width':1440,'height':1000})
            t=monotonic();response=cloud.goto(PUBLIC,wait_until='domcontentloaded',timeout=90000)
            report['public_home_http_status']=response.status if response else None
            for _ in range(60):
                frames=[f for f in cloud.frames if f.locator('.stApp').count()]
                if frames:
                    frame=frames[0];break
                cloud.wait_for_timeout(1000)
            else:raise RuntimeError('PUBLIC_HOME_NOT_AWAKE')
            frame.get_by_role('heading',name='QuantScore',exact=True).wait_for(timeout=45000)
            frame.locator('.stApp[data-test-script-state="notRunning"]').wait_for(timeout=45000)
            check_text(frame);cloud.screenshot(path=str(OUT/'public_home_read_only.png'),full_page=True)
            report['public_home_ready_seconds']=round(monotonic()-t,3)
            report['public_stock_analysis_triggered']=False
            report['local_verification_status']='PASS' if report['local_mobile']=='PASS' else 'PARTIAL'
            # Aggregate acceptance remains incomplete without the optimized
            # public deployment, even when the actual local browser succeeds.
            report['status']='PARTIAL'
        except Exception as exc:
            report.update(status='PARTIAL',error_type=type(exc).__name__)
        finally:
            save();browser.close()
    print(json.dumps({'status':report['status'],'public_optimized_status':report['public_optimized_status']}),flush=True)
    return report


if __name__=='__main__':main()
