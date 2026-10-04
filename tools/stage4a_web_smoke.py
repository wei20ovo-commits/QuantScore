"""Actual browser acceptance. No mocked routes, data or injected stock results."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8505')
    args = parser.parse_args()
    output = ROOT / 'outputs/stage4a'
    output.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'is_mock': False,
              'url': args.url, 'screenshots': [], 'pages': {}, 'status': 'RUNNING'}
    def save():
        (output / 'web_smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    save()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            page.goto(args.url, wait_until='domcontentloaded')
            page.get_by_text('后台分析概览', exact=True).wait_for(timeout=180000)
            page.get_by_text('最近分析', exact=False).first.wait_for(timeout=240000)
            def ready():
                page.locator('.stApp[data-test-script-state="notRunning"]').wait_for(timeout=900000)
                page.wait_for_function('!document.querySelector(\'[data-stale="true"]\')')
                page.wait_for_timeout(1800)  # Native dataframe/canvas asynchronous paint.
            def capture(name):
                ready()
                page.get_by_role('heading', name='QuantScore', exact=True).scroll_into_view_if_needed()
                page.wait_for_timeout(800)
                overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
                assert not overflow, name
                page.screenshot(path=str(output / f'{name}.png'), full_page=True)
                report['screenshots'].append({'name': name, 'width': page.viewport_size['width'], 'overflow': overflow})
                save()
            def navigate(label, heading):
                page.get_by_role('button', name=label, exact=True).click()
                page.get_by_role('heading', name=heading, exact=True).wait_for(timeout=30000)
                ready()
                report['pages'][label] = {'status': 'PASS', 'text': page.locator('body').inner_text()}
                save()
            capture('home_light')
            page.get_by_role('button', name='☾', exact=True).click()
            page.locator('.theme-dark').wait_for(state='attached')
            capture('home_dark')
            navigate('板块热度', '板块热度 · SectorHeat')
            assert '最近已保存交易日' in report['pages']['板块热度']['text']
            capture('sector_dark')
            page.get_by_label('搜索行业名称或代码').fill('C15')
            page.get_by_label('搜索行业名称或代码').press('Enter')
            page.wait_for_timeout(700)
            page.get_by_text('S1 · 板块1日相对强度 · PARTIAL', exact=False).first.click()
            capture('sector_detail_dark')
            navigate('策略匹配候选', '策略匹配候选 · Strategy Match Candidates')
            page.get_by_text('本批次策略匹配候选：0', exact=True).wait_for()
            capture('candidates_dark')
            navigate('规则中心', '规则中心 · ACTIVE V1.4')
            capture('rules_dark')
            page.get_by_role('button', name='☀', exact=True).click()
            page.locator('.theme-light').wait_for(state='attached')
            capture('rules_light')
            navigate('单股分析', 'QuantScore')
            page.get_by_role('textbox', name='股票代码', exact=True).fill('600519')
            page.get_by_role('button', name='开始分析', exact=True).click()
            try:
                page.get_by_role('heading', name='贵州茅台 · 600519.SH', exact=True).wait_for(timeout=900000)
            except Exception:
                report['analysis_failure_text'] = page.locator('body').inner_text()
                page.screenshot(path=str(output / 'analysis_failure.png'), full_page=True)
                raise
            page.locator('.js-plotly-plot').wait_for(timeout=30000)
            capture('analysis_light')
            text = page.locator('body').inner_text()
            assert 'baostock' in text and 'Primary Industry' in text and 'B1' in text and 'B2' in text
            report['analysis'] = {'status': 'PASS', 'symbol': '600519.SH', 'name': '贵州茅台', 'text': text}
            report['chart_traces'] = page.locator('.js-plotly-plot').evaluate('(el)=>el.data.map(t=>({type:t.type,name:t.name,points:t.x.length}))')
            report['pages']['单股分析'] = {'status': 'PASS'}
            page.get_by_role('button', name='☾', exact=True).click()
            page.locator('.theme-dark').wait_for(state='attached')
            page.wait_for_function("document.querySelector('.js-plotly-plot')?._fullLayout.paper_bgcolor === '#101f35'")
            capture('analysis_dark')
            page.set_viewport_size({'width': 390, 'height': 844})
            capture('analysis_mobile')
            navigate('板块热度', '板块热度 · SectorHeat')
            capture('sector_mobile')
            navigate('策略匹配候选', '策略匹配候选 · Strategy Match Candidates')
            capture('candidates_mobile')
            navigate('首页', 'QuantScore')
            page.get_by_text('最近分析', exact=False).first.wait_for(timeout=180000)
            capture('home_mobile')
            report['pages']['首页'] = {'status': 'PASS'}
            assert not errors, errors
            report.update(status='PASS', page_errors=errors, completed_at=datetime.now(timezone.utc).isoformat())
            browser.close()
    except Exception as exc:
        report.update(status='FAIL', error=str(exc), completed_at=datetime.now(timezone.utc).isoformat())
        raise
    finally:
        save()
    print(json.dumps({'status': report['status'], 'screenshots': report['screenshots']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
