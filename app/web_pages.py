"""Product views over saved results and ACTIVE rules; presentation only."""
from html import escape

import pandas as pd
import streamlit as st

from app.web_backend import number_text
from app.web_results import STATUS_HELP, RUN_HELP, active_rules, candidate_rows, sector_rows, display_score


def result_table(rows, column_config=None):
    frame = pd.DataFrame(rows)
    if st.session_state.get('theme') == 'dark':
        # Canvas tables use the native Streamlit theme; explicitly style real
        # cells so the preserved CSS theme switch also covers new product views.
        frame = frame.style.set_properties(**{'background-color': '#101f35', 'color': '#d6e6ff'}).format(na_rep='—')
    st.dataframe(frame, hide_index=True, width='stretch', column_config=column_config)


def status_legend():
    with st.expander('数据状态说明 · 不可评不等于不匹配'):
        for status, meaning in STATUS_HELP.items():
            st.write(f'**{status}** — {meaning}')
        st.caption('规则 PASS / PARTIAL / FAIL 等是匹配状态，与数据质量状态分别展示。数据错误 ≠ 0分。')


def result_metadata(snapshot):
    if not snapshot.available:
        (st.error if snapshot.status == 'DATA_ERROR' else st.info)(snapshot.message)
        st.caption(f'数据状态：{snapshot.status} · 只读后台预计算结果 · 非实时')
        return False
    st.caption(f'历史数据 / 非实时 · 最近已保存交易日：{snapshot.payload["trade_date"]} '
               f'· 生成时间：{snapshot.generated_at} · 数据源：{snapshot.providers}')
    st.caption(f'后台状态：{snapshot.payload["status"]}（{RUN_HELP[snapshot.payload["status"]]}） '
               f'· 正式结果：{snapshot.source}')
    return True


def dashboard_summary(snapshot):
    st.html('<div class="home-section-head dense"><strong>后台分析概览</strong><small>预计算结果 · 只读展示</small></div>')
    if not result_metadata(snapshot):
        return
    stats = snapshot.payload['stats']
    items = [('可评分行业', stats['industry_scoreable'], f"行业总数 {stats['industry_total']}"),
             ('Heat ≥70 行业', stats['industry_candidate'], '后台已判定的合格行业'),
             ('策略匹配候选', stats['strategy_match_candidates'], '规则匹配，不是推荐'),
             ('不可评行业 / 股票', f"{stats['industry_invalid']} / {stats['stock_incomplete'] + stats['stock_error']}", '缺项与数据异常保留')]
    cards = ''.join(f'<article class="summary-card"><div class="summary-label">{escape(label)}</div>'
                    f'<strong>{escape(str(value))}</strong><small>{escape(note)}</small></article>' for label, value, note in items)
    st.html('<section class="summary-grid">' + cards + '</section>')
    st.caption('策略匹配候选 ≠ 推荐股票。结果仅表示符合用户定义规则，不构成投资建议。')


def sector_heat_page(snapshot):
    st.subheader('板块热度 · SectorHeat')
    st.caption('按最近正式后台结果查看行业热度与 S1–S7；页面不联网扫描成分股。')
    if not result_metadata(snapshot):
        return
    search, order = st.columns([3, 1])
    with search:
        query = st.text_input('搜索行业名称或代码', key='sector_search', placeholder='如：C15、酒、住宿')
    with order:
        direction = st.selectbox('Heat 排序', ['从高到低', '从低到高'], key='sector_sort')
    rows = sector_rows(snapshot, query, direction == '从高到低')
    if not rows:
        st.info('没有与搜索条件一致的行业。')
        return
    result_table(rows, {'SectorHeat': st.column_config.NumberColumn(format='%.0f')})
    st.caption('— / 空白表示不可评分；有效数据下的 0 分表示未命中规则。排序仅用于展示。')
    identifiers = [row['行业代码'] for row in rows]
    sectors = {row['sector_id']: row for row in snapshot.payload['sectors']}
    selected = st.selectbox('查看行业详情', identifiers,
                            format_func=lambda key: sectors[key]['sector_name'], key='sector_detail')
    sector = sectors[selected]
    context = sector.get('context') or {}
    heat = context.get('sector_heat') or {}
    with st.container(border=True):
        st.write(f"**{sector['sector_name']} · SectorHeat {number_text(display_score(sector.get('sector_heat'), sector['data_status']))}**")
        st.write(f"数据状态：{sector['data_status']} — {STATUS_HELP[sector['data_status']]}")
        st.caption(f"成分股 {sector.get('constituent_count', '暂无数据')} · 交易日 {sector['trade_date']}")
        if heat:
            st.caption(f"已判定分数（诊断）：{number_text(heat.get('available_score'))} / "
                       f"{number_text(heat.get('available_max_score'))}；不会冒充完整 SectorHeat。")
            for index in range(1, 8):
                rule = heat.get(f's{index}') or {}
                with st.expander(f"S{index} · {rule.get('rule_name', '暂无数据')} · {rule.get('status', 'UNKNOWN')}"):
                    data_status = rule.get('data_status', 'UNKNOWN')
                    st.write(f"数据状态：{data_status} · 得分 {number_text(display_score(rule.get('score'), data_status))} / {number_text(rule.get('max_score'))}")
                    st.write(rule.get('explanation', '尚无合法规则结果。'))
                    st.caption(f"源日期：{rule.get('source_date', '暂无数据')} · 区间：{rule.get('threshold_band') or '—'}")
                    st.json(rule.get('raw_inputs', {}), expanded=False)
        else:
            st.info('上游没有生成完整 S1–S7 结果，不能以零分填充。')
        with st.expander('行业数据来源 / 错误原因'):
            st.json({'provenance': context.get('provenance'), 'reason_code': context.get('reason_code'),
                     'error': sector.get('error')}, expanded=False)


def candidates_page(snapshot):
    st.subheader('策略匹配候选 · Strategy Match Candidates')
    st.caption('直接读取后台 MATCHED 结果；不重新评分、不添加 Coverage 门槛、不限制候选 Universe。')
    if not result_metadata(snapshot):
        return
    rows = candidate_rows(snapshot)
    if not rows:
        st.html('<div class="product-empty"><b>本批次策略匹配候选：0</b>'
                '<p>本次后台结果没有产生 MATCHED 股票。数据不可评对象另行保留，不会当作低分股票。</p></div>')
    else:
        result_table(rows)
    st.caption('策略匹配候选 ≠ 推荐股票。排列沿用后台 ENGINEERING_DISPLAY_ORDER，不表示收益预测或推荐顺序。')
    with st.expander('本批次扫描与数据质量说明'):
        stats = snapshot.payload['stats']
        st.write({'预期股票': stats['stock_expected'], '已分析股票': stats['stock_analyzed'],
                  '股票数据不完整': stats['stock_incomplete'], '股票数据错误': stats['stock_error'],
                  '不可评行业': stats['industry_invalid'], '股票数据状态计数': stats.get('quality_counts', {})})


def rules_center():
    st.subheader('规则中心 · ACTIVE V1.4')
    st.caption('当前冻结定义与实现审计；评分语义来源 v1.3。旧 AutoScreenScore 已替代，不用于候选判定。')
    try:
        rules = active_rules()
    except (OSError, ValueError, KeyError, TypeError):
        st.error('当前规则登记文件不可读，请检查发布配置。')
        return
    category, search = st.columns([1, 3])
    with category:
        group = st.selectbox('规则分类', ['全部', 'A', 'B', 'C', 'D', 'E', 'F', 'R', 'S'], key='rule_group')
    with search:
        query = st.text_input('搜索规则名称或编号', key='rule_search')
    rules = [rule for rule in rules if (group == '全部' or rule['category'] == group)
             and query.casefold() in (rule['rule_id'] + ' ' + rule['name_cn']).casefold()]
    st.caption(f'当前显示 {len(rules)} 条 ACTIVE 规则；实现状态与执行时 PARTIAL 状态不同。')
    result_table([{'Rule ID': r['rule_id'], '名称': r['name_cn'], '类型': r['rule_type'],
                               '实现状态': r['code_status'], '最高分': r['max_score'], '最大扣分': r['max_penalty'],
                               '数据要求': ' / '.join(r['required_fields'])} for r in rules])
    for rule in rules:
        with st.expander(f"{rule['rule_id']} · {rule['name_cn']} · {rule['code_status']}"):
            st.write('作用与当前定义：' + rule['purpose'])
            st.write(f"最高得分 {rule['max_score']} · 最大扣分 {rule['max_penalty']} · 来源类型 {rule['source_type']}")
            st.write('数据要求：' + ' / '.join(rule['required_fields']))
            st.caption(rule['active_source'])


def industry_summary(data):
    context = data.get('industry_context') or {}
    primary = context.get('primary_industry') or {}
    heat = context.get('sector_heat') or {}
    b = {rule['rule_id']: rule for rule in data['rules'] if rule['rule_id'] in ('B1', 'B2')}
    status = context.get('data_status', 'UNKNOWN')
    items = [('Primary Industry', primary.get('sector_name') or primary.get('name') or '暂无数据', status),
             ('SectorHeat', number_text(display_score(heat.get('total_score'), heat.get('overall_status', 'UNKNOWN'))),
              heat.get('overall_status', status))]
    items.extend((key, number_text(b.get(key, {}).get('score')), b.get(key, {}).get('status', 'UNKNOWN')) for key in ['B1', 'B2'])
    st.html('<section class="industry-grid">' + ''.join(
        f'<article class="summary-card"><div class="summary-label">{escape(label)}</div>'
        f'<b>{escape(str(value))}</b><small>{escape(str(state))}</small></article>' for label, value, state in items) + '</section>')
    st.caption(f"行业数据状态：{status} · 行业日期：{heat.get('trade_date') or primary.get('as_of') or '暂无数据'} · B1/B2直接来自单股规则引擎。")
