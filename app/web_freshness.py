"""Presentation of observed dates; no new trading-calendar or score rules."""
from datetime import datetime
from zoneinfo import ZoneInfo
from app.web_diagnostics import date_only


def date_notice(day, *, reference=None, status=None, now=None):
    day=date_only(day)
    reference=date_only(reference)
    today=(now or datetime.now(ZoneInfo('Asia/Shanghai'))).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    if isinstance(status,str):status=status.removeprefix('BENCHMARK_SNAPSHOT_')
    if status in {'DATA_ERROR','DATA_INCONSISTENT','DATA_INCOMPLETE'}:
        return 'error', f'{status}：数据读取、校验或完整性存在问题，不能作为零分或可靠判断。'
    if day and day>today:
        return 'error', f'数据日期 {day} 晚于当前日期，展示日期存在异常，需核查。'
    if reference and reference>today:
        return 'error', f'评价日期 {reference} 晚于当前日期，展示日期存在异常，需核查。'
    if status=='DATA_STALE' or (reference and day and day!=reference):
        return 'warning', f'DATA_STALE：数据日期 {day or "UNKNOWN"} 与评价日期 {reference or "UNKNOWN"} 不一致，不用于当前行业判断。'
    if day is None:
        return 'warning', 'UNKNOWN：数据日期尚未确认，不能判断是否为最新行情。'
    if status=='UNKNOWN':
        return 'warning', f'UNKNOWN：已记录数据日期 {day}，但上游状态尚不能确认；日期已知不代表数据可用。'
    if reference:
        return 'caption', f'实际数据日期：{day} · 与评价日期一致 · 非实时。'
    if day<today:
        return 'warning', f'历史数据：{day}，不是今日行情。最新交易日尚未核实；以下仅为该日记录，不代表当前仍满足规则。'
    return 'caption', f'实际数据日期：{day} · 日线数据，非实时；是否最终收盘数据仍以上游校验为准。'


def render_notice(label, day, **kwargs):
    import streamlit as st
    level,text=date_notice(day,**kwargs)
    getattr(st,level)(label+' · '+text)


def analysis_dates(data, diagnostics=None):
    import streamlit as st
    diagnostic=diagnostics or data.get('web_diagnostics') or {}
    context=data.get('industry_context') or {}
    primary=context.get('primary_industry') or {}
    heat=context.get('sector_heat') or {}
    day=date_only(data.get('evaluation_date'))
    industry=date_only(diagnostic.get('industry_snapshot_date')) or date_only(heat.get('trade_date')) or date_only(primary.get('as_of'))
    benchmark=date_only(diagnostic.get('benchmark_snapshot_date'))
    st.caption(f'数据日期核对：股票 {day or "UNKNOWN"} · 行业 {industry or "UNKNOWN"} · 指数 {benchmark or "UNKNOWN"}')
    render_notice('股票日线',day)
    render_notice('行业快照',industry,reference=day,status=context.get('data_status'))
    render_notice('指数快照',benchmark,reference=day,status=diagnostic.get('benchmark_data_status'))
    if industry and benchmark and industry!=benchmark:
        st.warning('行业与指数快照日期不同步；缺失或过期上下文不会补成有效数据，B1/B2以规则引擎的 UNKNOWN 等真实结果为准。')


def home_dates(indices, sector_day):
    import streamlit as st
    for item in indices or []:
        render_notice(item.get('name','指数'), item.get('date'))
        if date_only(sector_day) and date_only(item.get('date')) and item['date']!=sector_day:
            st.warning(f'行业快照 {sector_day} 与指数 {item["date"]} 日期不同步；两者均按各自日期展示。')
