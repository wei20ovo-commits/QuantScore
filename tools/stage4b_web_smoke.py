"""Actual production Web browser smoke. No injected analysis or paid AI calls.

AI success/error behavior is separately tested with labeled offline transports.
This smoke verifies genuine 600519 core analysis + Standard Rules UI/fallback.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8506')
    args = parser.parse_args()
    output = ROOT / 'outputs/stage4b'
    output.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'url': args.url,
              'is_mock': False, 'real_ai_api_verified': False, 'paid_ai_calls': 0,
              'status': 'RUNNING', 'screenshots': []}
    def save():
        (output / 'web_smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    save()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page_errors = []
            page.on('pageerror', lambda exc: page_errors.append(type(exc).__name__))
            page.goto(args.url, wait_until='domcontentloaded')
            page.get_by_role('heading', name='QuantScore', exact=True).wait_for(timeout=90000)
            page.get_by_role('textbox', name='股票代码', exact=True).fill('600519')
            page.get_by_role('button', name='开始分析', exact=True).click()
            page.get_by_role('heading', name='贵州茅台 · 600519.SH', exact=True).wait_for(timeout=900000)
            page.get_by_text('AI Explanation · 既有规则解释', exact=True).wait_for(timeout=60000)
            page.locator('.st-key-explanation_panel').wait_for(timeout=60000)
            def ready():
                page.locator('.stApp[data-test-script-state="notRunning"]').wait_for(timeout=900000)
                page.wait_for_function('!document.querySelector(\'[data-stale="true"]\')')
                page.wait_for_timeout(1500)
            def capture(name):
                ready()
                # Streamlit scrolls inside its main container; full_page alone
                # captures only the initial viewport. Focus the new panel itself.
                page.get_by_text('AI Explanation · 既有规则解释', exact=True).scroll_into_view_if_needed()
                page.wait_for_timeout(800)
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), name
                page.screenshot(path=str(output / (name + '.png')), full_page=True)
                report['screenshots'].append(name + '.png')
                save()
            ready()
            text = page.locator('body').inner_text()
            assert '当前展示：Standard Rules' in text
            assert '这是对既有规则结果的解释，不构成投资建议。' in text
            assert page.locator('.js-plotly-plot').count() > 0
            report['standard_rules'] = {'status': 'PASS', 'analysis_text': text}
            capture('standard_light')
            page.get_by_role('button', name='☾', exact=True).click()
            page.locator('.theme-dark').wait_for(state='attached')
            ready()
            colors = page.locator('.st-key-explanation_panel').evaluate('''el => ({
                text: getComputedStyle(el.querySelector('[data-testid="stText"] span')).color,
                header: getComputedStyle(el.querySelector('summary')).backgroundColor
            })''')
            assert colors['text'] == 'rgb(217, 231, 251)', colors
            assert colors['header'] == 'rgb(22, 36, 59)', colors
            report['dark_panel_colors'] = colors
            capture('standard_dark')
            page.set_viewport_size({'width': 390, 'height': 844})
            capture('standard_mobile')
            report['page_errors'] = page_errors
            assert not page_errors
            report['status'] = 'PASS'
            browser.close()
    except Exception as exc:
        report['status'] = 'FAIL'
        report['error_type'] = type(exc).__name__  # No potentially sensitive exception text.
        raise
    finally:
        report['completed_at'] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == '__main__':
    main()
