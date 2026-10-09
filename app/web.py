"""Run from the repository root: streamlit run app/web.py."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import streamlit as st
from app.data.models import DataError
from app.web_backend import analyze_stock, coverage_text, normalize_stock_code, number_text


def load_market_snapshot():
    from app.web_market import load_index_snapshots
    return load_index_snapshots()

def load_analysis(code):
    result = analyze_stock(code)
    if result['data_status']['status'] == 'UNAVAILABLE':
        from app.web_diagnostics import WebDataError
        raise WebDataError('暂时无法取得完整行情，请稍后重试。数据源返回不可用，本次不展示评分。',
                           result.get('web_diagnostics'))
    return result


# Spawn reimports this entrypoint without a Streamlit runtime. Workers must not
# register UI caches; the serving process retains the exact existing TTLs.
if __name__ != '__mp_main__':
    load_market_snapshot = st.cache_data(ttl=900, max_entries=4, show_spinner=False)(load_market_snapshot)
    load_analysis = st.cache_data(ttl=300, max_entries=64, show_spinner=False)(load_analysis)

def render_home(theme):
    from app.web_visuals import home_dashboard
    from app.web_pages import dashboard_summary
    from app.web_results import load_screening_snapshot
    dashboard_summary(load_screening_snapshot())
    # Saved backend Dashboard is immediately usable. Optional index acquisition
    # must not block navigation while a data source is slow/unreachable.
    snapshot = st.session_state.get('market_snapshot', [])
    if st.button('加载指数日线', key='load_indices', help='仅获取指数展示数据，不启动行业或全市场扫描'):
        try:
            with st.spinner('正在获取指数日线…'):
                snapshot = load_market_snapshot()
            st.session_state['market_snapshot'] = snapshot
        except Exception:
            snapshot = []
        if not snapshot:
            st.warning('指数数据暂不可用，后台分析概览仍可正常查看。')
    home_dashboard(snapshot, st.session_state.get('recent_analyses', []))

def render_result(data):
    status = data['data_status']
    if status['is_mock'] or status['status'] == 'UNAVAILABLE':
        st.error('真实行情不可用，本次不展示评分。请稍后重试。')
        return
    from app.web_visuals import dashboard
    dashboard(data)
    from app.web_pages import industry_summary
    industry_summary(data)
    from app.web_explanation import render_explanation
    render_explanation(data)
    with st.expander('评分与覆盖率 · 完整口径'):
        left, right = st.columns(2)
        left.metric('QuantScore', number_text(data['final_quant_score']))
        right.metric('Risk Level', data['risk_level'])
        left.metric('Positive Score', number_text(data['positive_score']))
        right.metric('Risk Penalty', number_text(data['risk_penalty']))
        st.write(f"正向覆盖率：{coverage_text(data['positive_coverage'])}")
        st.write(f"风险覆盖率：{coverage_text(data['risk_coverage'])}")
    st.html('<div id="rules"></div>')
    with st.expander(f'全部规则明细（{len(data["rules"])}条）'):
        st.caption('UNKNOWN表示数据或确认条件不足，不等于FAIL；—表示无法判断得分。')
        for rule in data['rules']:
            with st.container(border=True):
                st.write(f"**{rule['rule_id']} · {rule['name_cn']}**")
                st.write(f"status：{rule['status']}")
                if rule.get('applicable') is False:
                    st.caption('NOT_APPLICABLE · 当前对象不适用本条规则；保留引擎原始状态与得分。')
                if rule.get('reason_code'):
                    st.caption('数据 / 确认原因：' + str(rule['reason_code']))
                st.write(f"score：{number_text(rule['score'])} / max_score：{number_text(rule['max_score'])}")
                if rule['rule_type'] == 'RISK':
                    st.write(f"penalty：{number_text(rule['penalty'])} / max_penalty：{number_text(rule['max_penalty'])}")
                st.write(rule['explanation'])
                st.caption('raw_values · 点击展开原始值')
                st.json(rule['raw_values'], expanded=False)
    if data['warnings']:
        with st.expander('数据说明与限制'):
            for warning in data['warnings']:
                st.write(warning)

def main():
    st.set_page_config(page_title='QuantScore · 策略匹配工作台', page_icon='📊', layout='wide')
    st.html('<style>' + (ROOT/'app/web_style.css').read_text('utf-8') + '</style>')
    if 'theme' not in st.session_state:
        st.session_state['theme']='light'
    st.session_state.setdefault('view', 'home')
    with st.container(key='navigation'):
        brand, links, search, theme_col = st.columns([.9, 2.6, 1.55, .3], vertical_alignment='center')
        with brand: st.title('QuantScore')
        with search:
            with st.form('single_stock'):
                field, button = st.columns([2,1], vertical_alignment='bottom')
                with field: code = st.text_input('股票代码', value='600519', max_chars=12, label_visibility='collapsed', placeholder='股票代码，如600519')
                with button: submitted = st.form_submit_button('开始分析', key='analyze_submit', type='primary', use_container_width=True)
        with theme_col:
            if st.button('☾' if st.session_state['theme']=='light' else '☀', key='theme_toggle', help='切换 Light / Dark Mode'):
                st.session_state['theme']='dark' if st.session_state['theme']=='light' else 'light'; st.rerun()
        with links:
            nav=st.columns([.65, 1, 1, 1.5, 1])
            for col,label,view in zip(nav,['首页','单股分析','板块热度','策略匹配候选','规则中心'],['home','analysis','sectors','candidates','rules']):
                with col:
                    if st.button(label,key='nav_'+view):
                        st.session_state['view']=view
    theme=st.session_state['theme']
    st.html(f'<div class="theme-state theme-{theme}" data-theme="{theme}"></div>')
    st.html('<div id="overview"></div>')
    st.info('QuantScore 是策略匹配分析工具，不构成投资建议。')
    if submitted:
        st.session_state.pop('analysis', None)
        try:
            code = normalize_stock_code(code)
            with st.spinner('正在获取真实行情并逐条分析，首次运行可能需要数分钟…'):
                data = load_analysis(code)
                st.session_state['analysis'] = data
                st.session_state['view'] = 'analysis'
                if not data['data_status']['is_mock']:
                    from datetime import datetime
                    recent = [x for x in st.session_state.get('recent_analyses', []) if x['data']['symbol'] != data['symbol']]
                    st.session_state['recent_analyses'] = [{'data':data,'analyzed_at':datetime.now().strftime('%H:%M:%S')},*recent][:6]
        except DataError as exc:
            st.error(str(exc))
            if getattr(exc,'diagnostics',None):
                with st.expander('请求诊断 · 不含凭据'):
                    st.json(exc.diagnostics,expanded=False)
        except Exception: st.error('分析暂时未完成，请稍后重试。当前没有可展示的新结果。')
    st.html(f'<div class="view-state view-{st.session_state["view"]}"></div>')
    view=st.session_state['view']
    if view=='home':
        render_home(theme)
    elif view=='rules':
        from app.web_pages import rules_center
        rules_center()
    elif view in ('sectors','candidates'):
        from app.web_results import load_screening_snapshot
        from app.web_pages import sector_heat_page, candidates_page
        (sector_heat_page if view=='sectors' else candidates_page)(load_screening_snapshot())
    elif view=='analysis' and 'analysis' in st.session_state:
        render_result(st.session_state['analysis'])
    else:
        st.info('在顶部输入股票代码开始分析，结果将显示在这里。')
    from app.web_pages import status_legend
    status_legend()

if __name__ == '__main__': main()
