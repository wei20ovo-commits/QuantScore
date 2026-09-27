"""Real-browser final acceptance of current files; no routes or data are mocked."""
from pathlib import Path
from datetime import datetime,timezone
import json
from playwright.sync_api import sync_playwright
if __name__=='__main__':
 out=Path('outputs/web');out.mkdir(exist_ok=True)
 report={'run_at':datetime.now(timezone.utc).isoformat(),'mock_used':False,'screens':[]}
 with sync_playwright() as p:
  browser=p.chromium.launch(channel='msedge',headless=True)
  page=browser.new_page(viewport={'width':1440,'height':1700},device_scale_factor=1)
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('http://127.0.0.1:8502/',wait_until='domcontentloaded')
  page.locator('.market-card').first.wait_for(timeout=180000)
  page.get_by_text('最近分析',exact=False).first.wait_for(timeout=20000)
  assert 'LIVE' not in page.locator('body').inner_text()
  report['indices']=page.locator('.market-card').all_inner_texts()
  print('Home real indices loaded',flush=True)
  # Seed only by an actual user-equivalent analysis through the live UI.
  page.get_by_role('textbox',name='股票代码').fill('600519')
  page.get_by_role('button',name='开始分析',exact=True).click()
  page.get_by_role('heading',name='贵州茅台 · 600519.SH',exact=True).wait_for(timeout=600000)
  page.locator('.js-plotly-plot').wait_for(timeout=20000)
  report['analysis_text']=page.locator('body').inner_text()
  assert 'baostock' in report['analysis_text']
  assert len(page.locator('.score-card').all())==5
  report['chart_traces']=page.locator('.js-plotly-plot').evaluate('(el)=>el.data.map(t=>({type:t.type,name:t.name,points:t.x.length}))')
  assert [x['type'] for x in report['chart_traces']]==['candlestick','scatter','scatter','scatter','bar']
  def capture(name):
   if page.viewport_size['width']==1440:
    page.set_viewport_size({'width':1440,'height':1200 if name.startswith('home') else 1700})
   page.mouse.move(0,0)
   page.get_by_role('textbox',name='股票代码').scroll_into_view_if_needed()
   page.wait_for_timeout(1200)
   overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth')
   assert not overflow,name
   page.screenshot(path=str(out/(name+'.png')),full_page=True)
   report['screens'].append({'name':name,'width':page.viewport_size['width'],'overflow':overflow})
  capture('analysis_light_final')
  page.get_by_role('button',name='☾',exact=True).click()
  page.locator('.theme-dark').wait_for(state='attached')
  page.wait_for_function("document.querySelector('.js-plotly-plot')?._fullLayout.paper_bgcolor === '#101f35'")
  capture('analysis_dark_final')
  report['dark_chart_background']=page.locator('.js-plotly-plot').evaluate('(el)=>el._fullLayout.paper_bgcolor')
  page.get_by_role('button',name='首页',exact=True).click()
  page.locator('.market-card').first.wait_for(timeout=180000)
  page.locator('.recent-row').filter(has_text='贵州茅台').wait_for()
  capture('home_dark_final')
  page.get_by_role('button',name='☀',exact=True).click()
  page.locator('.theme-light').wait_for(state='attached')
  capture('home_light_final')
  page.set_viewport_size({'width':390,'height':844})
  capture('home_mobile_final')
  page.get_by_role('button',name='单股分析',exact=True).click()
  page.locator('.js-plotly-plot').wait_for()
  capture('mobile_final')
  assert page.get_by_role('button',name='开始分析',exact=True).bounding_box()['width']>=90
  page.locator('.js-plotly-plot').scroll_into_view_if_needed()
  page.screenshot(path=str(out/'mobile_chart_final.png'))
  page.get_by_role('textbox',name='股票代码').scroll_into_view_if_needed()
  page.get_by_role('button',name='☾',exact=True).click()
  page.locator('.theme-dark').wait_for(state='attached')
  capture('mobile_dark_final')
  assert not errors,errors
  report.update(status='PASS',page_errors=errors)
  browser.close()
 (out/'ui_final_browser_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'status':report['status'],'screens':report['screens']},ensure_ascii=False))
