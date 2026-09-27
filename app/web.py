"""Run from the repository root: streamlit run app/web.py."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import streamlit as st
from app.data.models import DataError
from app.web_backend import analyze_stock, coverage_text, normalize_stock_code, number_text


@st.cache_data(ttl=900, max_entries=4, show_spinner=False)
def load_market_snapshot():
    from app.web_market import load_index_snapshots
    return load_index_snapshots()

@st.cache_data(ttl=300, max_entries=64, show_spinner=False)
def load_analysis(code):
    result = analyze_stock(code)
    if result['data_status']['status'] == 'UNAVAILABLE':
        raise DataError('暂时无法取得完整行情，请稍后重试。数据源返回不可用，本次不展示评分。')
    return result

def render_home(theme):
    from app.web_visuals import home_dashboard
    try:
        snapshot = load_market_snapshot()
    except Exception:
        snapshot = []
    home_dashboard(snapshot, st.session_state.get('recent_analyses', []))

def render_result(data):
    status = data['data_status']
    if status['is_mock'] or status['status'] == 'UNAVAILABLE':
        st.error('真实行情不可用，本次不展示评分。请稍后重试。')
        return
    from app.web_visuals import dashboard
    dashboard(data)
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
    st.set_page_config(page_title='QuantScore · 单股策略匹配', page_icon='📊', layout='wide')
    st.html('<style>' + (ROOT/'app/web_style.css').read_text('utf-8') + '</style>')
    if 'theme' not in st.session_state:
        st.session_state['theme']='light'
    st.session_state.setdefault('view', 'home')
    with st.container(key='navigation'):
        brand, links, search, theme_col = st.columns([1.0, 1.65, 1.55, .38], vertical_alignment='center')
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
            nav=st.columns(4)
            for col,label,view in zip(nav,['首页','单股分析','规则明细','自选股'],['home','analysis','rules','watchlist']):
                with col:
                    if st.button(label,key='nav_'+view,disabled=view=='watchlist',help='暂未开放' if view=='watchlist' else None):
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
        except DataError as exc: st.error(str(exc))
        except Exception: st.error('分析暂时未完成，请稍后重试。当前没有可展示的新结果。')
    st.html(f'<div class="view-state view-{st.session_state["view"]}"></div>')
    view=st.session_state['view']
    if view=='home':
        render_home(theme)
    elif view=='rules' and 'analysis' not in st.session_state:
        from app.services.stock_analysis_service import StockAnalysisService
        st.subheader('规则明细 · V1.4')
        st.caption('规范中的原始规则与权重；输入股票代码后可查看实际命中结果。')
        for rule in StockAnalysisService().rules():
            with st.expander(rule['rule_id']+' · '+rule['name_cn']):
                st.write({'来源':rule['source_type'],'最高得分':rule['max_score'],'最高扣分':rule['max_penalty'],'实现状态':rule['code_status']})
    elif 'analysis' in st.session_state:
        render_result(st.session_state['analysis'])
    else:
        st.info('在顶部输入股票代码开始分析，结果将显示在这里。')

if __name__ == '__main__': main()
