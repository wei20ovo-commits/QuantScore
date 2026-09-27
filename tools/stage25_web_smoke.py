"""Live browser verification; connects only to the real local Streamlit app."""
import json
from datetime import datetime,timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    out=root/'outputs/web';out.mkdir(parents=True,exist_ok=True)
    report={'run_at':datetime.now(timezone.utc).isoformat(),'mock_used':False,'screens':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:8501',wait_until='domcontentloaded')
        page.get_by_role('button',name='开始分析',exact=True).wait_for(timeout=60000)
        page.get_by_role('textbox',name='股票代码').fill('600519')
        page.get_by_role('button',name='开始分析',exact=True).click()
        page.get_by_role('heading',name='贵州茅台 · 600519.SH',exact=True).wait_for(timeout=600000)
        page.get_by_text('主要风险原因',exact=True).wait_for(timeout=10000)
        text=page.locator('body').inner_text()
        assert '数据源：baostock' in text and '不构成投资建议' in text
        assert all(x in text for x in ['QuantScore','Risk Level','Positive Score','Risk Penalty','正向覆盖率','风险覆盖率'])
        (out/'desktop_text.txt').write_text(text,encoding='utf-8')
        for name,width,height in [('desktop',1440,1000),('mobile',390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            page.wait_for_timeout(1200)
            overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
            assert not overflow, name+' horizontal overflow'
            page.screenshot(path=str(out/f'{name}.png'),full_page=True)
            report['screens'].append({'name':name,'width':width,'height':height,'horizontal_overflow':overflow})
        page.get_by_text('全部规则明细',exact=False).first.click()
        page.get_by_text('raw_values · 点击展开原始值',exact=True).first.wait_for(timeout=10000)
        detail=page.locator('body').inner_text()
        assert 'max_score' in detail and 'status：' in detail
        page.screenshot(path=str(out/'mobile_rules.png'))
        report.update(status='PASS',symbol='600519.SH',name='贵州茅台',provider='baostock',rule_details=True,page_errors=errors)
        assert not errors
        browser.close()
    (out/'stage25_web_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
