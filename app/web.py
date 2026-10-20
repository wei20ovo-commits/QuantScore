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
    from app.web_observability import mark_analysis_execution
    mark_analysis_execution()
    from app.web_market import load_index_snapshots
    from app.web_runtime import bounded_web_call
    return bounded_web_call(load_index_snapshots,(),root=ROOT)

def load_analysis(code):
    from app.web_observability import mark_analysis_execution
    mark_analysis_execution()
    result = analyze_stock(code)
    if result['data_status'].get('is_mock') or result['data_status']['status'] == 'UNAVAILABLE':
        from app.web_diagnostics import WebDataError
        raise WebDataError('暂时无法取得完整行情，请稍后重试。数据源返回不可用，本次不展示评分。',
                           result.get('web_diagnostics'))
    return result


# Spawn reimports this entrypoint without a Streamlit runtime. Workers must not
# register UI caches; the serving process retains the exact existing TTLs.
if __name__ != '__mp_main__':
    load_market_snapshot = st.cache_data(ttl=900, max_entries=4, show_spinner=False)(load_market_snapshot)
    load_analysis = st.cache_data(ttl=300, max_entries=64, show_spinner=False)(load_analysis)


def load_index_task(_code):
    indices=load_market_snapshot()
    return {'data_status':{'status':'AVAILABLE' if indices else 'UNAVAILABLE','is_mock':False},'indices':indices}


@st.fragment(run_every='2s')
def pending_indices():
    from app.web_tasks import task_manager
    state=task_manager(str(ROOT)).poll(st.session_state.get('index_task'))
    if not state:return
    if state['status']=='RUNNING':
        st.caption(f'指数日线后台加载中 · 请求 {state["request_id"]} · {state["elapsed_seconds"]:.0f}秒；不启动全市场扫描。')
    elif st.session_state.get('handled_index_task')!=state['request_id']:
        st.session_state['handled_index_task']=state['request_id']
        if state['status']=='SUCCESS':st.session_state['market_snapshot']=state['result']['indices']
        st.session_state['index_task_status']=state['status']
        st.rerun()
    elif state['status']!='SUCCESS':
        st.warning('指数刷新未完成。下方保留原来已取得的日线及其实际日期，不冒充最新数据。')

def render_home(theme):
    from app.web_visuals import home_dashboard
    from app.web_pages import dashboard_summary
    from app.web_results import load_screening_snapshot
    screening=load_screening_snapshot()
    dashboard_summary(screening)
    # Saved backend Dashboard is immediately usable. Optional index acquisition
    # must not block navigation while a data source is slow/unreachable.
    from app.web_market import published_index_snapshots
    snapshot = st.session_state.get('market_snapshot')
    if snapshot is None:
        snapshot=published_index_snapshots()
    if st.button('加载指数日线', key='load_indices', help='仅获取指数展示数据，不启动行业或全市场扫描'):
        from app.web_tasks import task_manager
        st.session_state['index_task']=task_manager(str(ROOT)).submit('INDEX_DISPLAY',load_index_task,cache_observable=True)
    if st.session_state.get('index_task'):pending_indices()
    from app.web_freshness import home_dates
    home_dates(snapshot,screening.payload.get('trade_date'))
    home_dashboard(snapshot, st.session_state.get('recent_analyses', []))

def render_result(data):
    status = data['data_status']
    if status['is_mock'] or status['status'] == 'UNAVAILABLE':
        st.error('真实行情不可用，本次不展示评分。请稍后重试。')
        return
    from app.web_visuals import dashboard
    from app.web_freshness import analysis_dates
    analysis_dates(data,st.session_state.get('request_diagnostics'))
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


def accept_task(state):
    """Apply a terminal result once. No late scores or automatic resubmission."""
    rid=state['request_id']
    if st.session_state.get('handled_task')==rid:return
    st.session_state['handled_task']=rid
    st.session_state['request_diagnostics']=state['diagnostics']
    st.session_state['task_terminal']=state
    if state['status']=='SUCCESS':
        data=state['result']
        st.session_state['analysis']=data
        from datetime import datetime
        recent=[x for x in st.session_state.get('recent_analyses',[]) if x['data']['symbol']!=data['symbol']]
        st.session_state['recent_analyses']=[{'data':data,'analyzed_at':datetime.now().strftime('%H:%M:%S')},*recent][:6]
    else:st.session_state.pop('analysis',None)


@st.fragment(run_every='1s')
def pending_analysis():
    """Only poll memory; never enter a provider/cache lock on the script thread."""
    from app.web_tasks import task_manager
    rid=st.session_state.get('analysis_task')
    if not rid:return
    state=task_manager(str(ROOT)).poll(rid)
    if state is None:return
    if state['status']!='RUNNING':
        accept_task(state)
        st.rerun()
    st.info('正在后台分析真实行情，最长等待240秒。你可以浏览其他页面；此处会自动更新状态。')
    st.caption(f'请求标识：{rid} · 已等待 {state["elapsed_seconds"]:.0f} 秒')
    st.caption('若浏览器断开或服务重启，请重新打开当前链接核对状态；网站不能保证断网期间向浏览器送达通知。')
    st.button('检查请求状态',key='check_analysis_status')


def render_task_state():
    from app.web_tasks import task_manager
    rid=st.session_state.get('analysis_task')
    if not rid:return
    state=task_manager(str(ROOT)).poll(rid)
    if not state:return
    if state['status']=='RUNNING':
        pending_analysis()
    else:
        accept_task(state)
        label={'SUCCESS':'分析完成','FAILURE':'分析失败','TIMEOUT':'分析超时',
               'INTERRUPTED':'分析中断','BUSY':'服务繁忙'}[state['status']]
        (st.success if state['status']=='SUCCESS' else st.error)(label+' · '+(state['message'] or '本次真实规则分析已返回。'))
        st.caption(f'请求标识：{rid} · 总耗时 {state["elapsed_seconds"] if state["elapsed_seconds"] is not None else "UNKNOWN"} 秒')
        if state['status']!='SUCCESS' and state['diagnostics']:
            from app.web_freshness import render_notice
            d=state['diagnostics']
            render_notice('行业快照',d.get('industry_snapshot_date'),reference=d.get('stock_trade_date'),status=d.get('industry_data_status'))
            render_notice('指数快照',d.get('benchmark_snapshot_date'),reference=d.get('stock_trade_date'),status=d.get('benchmark_data_status'))
            with st.expander('请求诊断 · 不含凭据'):
                st.json(state['diagnostics'],expanded=False)

def main():
    st.set_page_config(page_title='QuantScore · 策略匹配工作台', page_icon='📊', layout='wide')
    st.html('<style>' + (ROOT/'app/web_style.css').read_text('utf-8') + '</style>')
    if 'theme' not in st.session_state:
        st.session_state['theme']='light'
    st.session_state.setdefault('view', 'home')
    if not st.session_state.get('analysis_task'):
        value=st.query_params.get('request')
        import re
        if isinstance(value,str) and re.fullmatch('[a-f0-9]{32}',value):
            st.session_state['analysis_task']=value
            st.session_state['view']='analysis'
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
    from app.web_deployment import deployment_identity
    identity=deployment_identity(ROOT)
    with st.expander('部署版本 · 可核验'):
        import json
        st.code(json.dumps(identity,ensure_ascii=False,indent=2),language='json')
    if submitted:
        from app.web_tasks import task_manager
        manager=task_manager(str(ROOT))
        rid=manager.submit(code,load_analysis,deployment=identity,preprocess=normalize_stock_code,cache_observable=True)
        previous=st.session_state.get('analysis_task')
        if rid!=previous:
            st.session_state.pop('analysis', None)
            st.session_state.pop('request_diagnostics', None)
            st.session_state.pop('handled_task', None)
        st.session_state['analysis_task']=rid
        st.session_state['view']='analysis'
        st.query_params['request']=rid
        manager.wait_briefly(rid)
    render_task_state()
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
        if st.session_state.get('request_diagnostics'):
            with st.expander('请求诊断 · 不含凭据'):
                import json
                st.code(json.dumps(st.session_state['request_diagnostics'],ensure_ascii=False,indent=2),language='json')
    else:
        st.info('在顶部输入股票代码开始分析，结果将显示在这里。')
    from app.web_pages import status_legend
    status_legend()
    from app.web_feedback import render_feedback
    render_feedback()

if __name__ == '__main__': main()
