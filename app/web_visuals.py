"""Presentation only: existing scores, real daily bars, no strategy changes."""
from html import escape
import pandas as pd
import streamlit as st
from app.web_backend import coverage_text, number_text

def e(value):
    return escape(str(value))

def sparkline(values, color):
    """A visual trace of actual returned close values, not a decorative chart."""
    if len(values)<2:return ''
    low,high=min(values),max(values)
    points=' '.join(f'{i*130/(len(values)-1):.2f},{40-(v-low)/(high-low or 1)*34:.2f}' for i,v in enumerate(values))
    import base64
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 130 46"><polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    encoded=base64.b64encode(svg.encode()).decode()
    return f'<img class="index-trace" alt="最近交易日真实收盘走势" src="data:image/svg+xml;base64,{encoded}">'

def home_dashboard(snapshot, recent):
    st.html('''<section class="home-hero compact final-hero"><div class="hero-copy"><div class="eyebrow">QUANTSCORE / RESEARCH WORKSPACE</div><h2>用数据看结构，<br>用规则看清每一分。</h2><p>趋势、成交量、形态与风险，一份可追溯的单股分析。</p><div class="hero-badges"><span>真实日线</span><span>规则透明</span><span>解释可追溯</span></div></div><div class="hero-system"><div class="system-core">Q<span>QuantScore</span></div><div class="system-node blue">↗ 趋势结构<small>均线与突破条件</small></div><div class="system-node cyan">▥ 成交量结构<small>量价关系与持续性</small></div><div class="system-node purple">◇ 形态识别<small>逐条匹配冻结规则</small></div><div class="system-node amber">◈ 风险信号<small>保留未知与失效状态</small></div></div></section>''')
    st.html('<div class="home-section-head dense"><div><strong>市场概览</strong></div><small>最近交易日 · BaoStock日线 · 非实时行情</small></div>')
    if snapshot:
        cards=[]
        for item in snapshot:
            rising=item['change']>=0; color='#ef5266' if rising else '#1bb797'
            cards.append(f'<article class="market-card"><div class="market-top"><b>{e(item["name"])}</b><span class="day-label">最近交易日</span></div><div class="index-body"><div><div class="market-value">{item["close"]:,.2f}</div><div class="market-change" style="color:{color}">{item["change"]:+.2f}　{item["percent"]:+.2f}%</div></div>{sparkline(item["trend"],color)}</div><div class="market-meta">{e(item["symbol"])} · {e(item["date"])}</div></article>')
        st.html('<div class="market-grid">'+''.join(cards)+'</div>')
    else:
        st.html('<div class="market-empty">点击“加载指数日线”查看真实指数数据；未加载时不展示行情数字。</div>')
    tools=st.columns(4)
    for col,title,desc,icon,accent,view in zip(tools,['单股分析','规则中心','策略匹配候选','板块热度'],['真实日线与多维规则匹配','评分依据、权重与实现状态','后台正式候选结果','真实行业 S1–S7 评分'],['↗','≡','☆','◈'],['blue','purple','amber','cyan'],['analysis','rules','candidates','sectors']):
        with col:
            st.html(f'<div class="tool-card compact final-tool {accent}"><div class="tool-icon">{icon}</div><div><div class="tool-title">{title}</div><div class="tool-desc">{desc}</div></div></div>')
            if view and st.button('打开'+title,key='open_'+view,use_container_width=True):
                st.session_state['view']=view;st.rerun()
    left,right=st.columns([1.05,1.4],gap='medium')
    with left:
        if recent:
            data=recent[0]['data'];score=data['final_quant_score']
            parts=[]
            for title,cats in [('趋势',{'C'}),('量能',{'D'}),('形态',{'E','F'})]:
                value,maximum,_=structure_totals(data['rules'],cats)
                parts.append(f'<span>{title}<b>{value:g} <small>/ {maximum:g}</small></b></span>')
            st.html(f'<div class="home-panel preview-final"><div class="panel-title">QuantScore 评分预览</div><div class="preview-row"><div><h3>{e(data["name"])}</h3><div class="muted">{e(data["symbol"])} · {e(data["evaluation_date"])}</div><div class="muted">风险等级 {e(data["risk_level"])}</div></div><div class="score-ring" style="--arc:{max(0,min(100,score))*3.6}deg"><div><b>{score:g}</b><small>/ 100</small></div></div></div><div class="composition-values">{"".join(parts)}</div><div class="panel-sub">来自本会话最近一次真实分析</div></div>')
        else:
            st.html('<div class="home-panel preview-final"><div class="panel-title">QuantScore 评分预览</div><div class="preview-intro"><span class="preview-symbol">Q</span><div><h3>从一只股票开始</h3><p>分析后在这里回看真实评分与结构分项。</p></div></div><div class="preview-legend"><span>趋势结构</span><span>成交量结构</span><span>形态结构</span><span>风险等级</span></div></div>')
    with right:
        rows=[]
        for item in recent:
            d=item['data'];price=d.get('price',{}).get('close');price_text='暂无数据' if price is None else f'{price:,.2f}'
            rows.append(f'<div class="recent-row"><span><b>{e(d["name"])}</b><small>{e(d["symbol"])}</small></span><span>{price_text}</span><span class="recent-score">{number_text(d["final_quant_score"])}</span><span>{e(item["analyzed_at"])}</span></div>')
        body=''.join(rows) if rows else '<div class="recent-empty compact">尚无分析记录<small>　完成分析后自动保留在本会话，无热门排行。</small></div>'
        st.html('<div class="home-panel preview-final"><div class="panel-title">最近分析 <span class="panel-sub">仅当前会话</span></div><div class="recent-row recent-header"><span>股票 / 代码</span><span>日线收盘</span><span>评分</span><span>分析时间</span></div>'+body+'</div>')
    st.html('<div class="home-footnotes"><span>◉ 真实行情与原始规则可追溯</span><span>≡ 原规则权重保持不变</span><span>◷ 日线分析，不提供实时行情</span></div>')

def structure_totals(rules, categories):
    selected = [r for r in rules if r['rule_type']=='POSITIVE' and r['category'] in categories]
    return sum(r['score'] or 0 for r in selected), sum(r['max_score'] for r in selected), sum(r['status']=='UNKNOWN' for r in selected)

def candle_chart(records, theme="light"):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    d=pd.DataFrame(records)
    dates=pd.to_datetime(d.date).dt.strftime('%Y-%m-%d')
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.035,row_heights=[.77,.23])
    fig.add_trace(go.Candlestick(x=dates,open=d.open_adj,high=d.high_adj,low=d.low_adj,close=d.close_adj,
                                increasing_line_color='#ef5266',decreasing_line_color='#22ad91',name='前复权日K'),row=1,col=1)
    for key,color in [('M5','#1768ff'),('M30','#ff9e40'),('M60','#875bff')]:
        fig.add_trace(go.Scatter(x=dates,y=d[key],name=key,line=dict(color=color,width=1.5)),row=1,col=1)
    colors=['#ef7a87' if c>=o else '#65cbb7' for c,o in zip(d.close_adj,d.open_adj)]
    fig.add_trace(go.Bar(x=dates,y=d.volume,name='成交量（股）',marker_color=colors,showlegend=False),row=2,col=1)
    dark=theme=='dark'
    background='#101f35' if dark else '#ffffff'
    fig.update_layout(height=470,margin=dict(l=8,r=52,t=38,b=32),paper_bgcolor=background,plot_bgcolor=background,
                      font=dict(color='#a4b6d0' if dark else '#70819b',size=11),legend=dict(orientation='h',y=1.13,x=0,font=dict(color='#b9cae2' if dark else '#70819b')),
                      xaxis_rangeslider_visible=False,hovermode='x unified',dragmode='pan')
    fig.update_xaxes(type='category',nticks=5,showgrid=False,tickfont_size=10,automargin=True)
    fig.update_yaxes(side='right',gridcolor='#20344f' if dark else '#eff3f8',zeroline=False,nticks=5,automargin=True)
    return fig

def dashboard(data):
    """Render the real-data result state as a complete finance dashboard.

    This is presentation-only: every value is read from the existing analysis
    contract; no scoring, provider, or rule behavior is changed here.
    """
    status=data['data_status']; quote=data.get('price',{}); change=data.get('quote_change')
    color='neutral' if not change else ('up' if change['amount']>=0 else 'down')
    change_text='涨跌幅暂不可用' if not change else f"{change['amount']:+.2f}　{change['percent']:+.2f}%"
    price='—' if quote.get('close') is None else f"{quote['close']:,.2f}"
    primary=(data.get('industry_context') or {}).get('primary_industry') or {}
    industry_tag='' if not primary.get('name') else f'<span>{e(primary["name"])}</span>'
    # Stock quote header: only fields present in the real data contract are shown.
    st.html(f'''<section class="quote dashboard-card"><div class="quote-name"><div class="stock-icon">{e(data['name'][:1])}</div><div><h2>{e(data['name'])}<span> · {e(data['symbol'])}</span></h2><div class="tags"><span>{e(data['symbol'][-2:])} · A股</span>{industry_tag}<span>日线分析</span></div></div></div><div class="quote-price"><div class="price {color}">{price} <small>元</small></div><div class="change {color}">{change_text}</div><div class="muted">最新日线收盘 · {e(data['evaluation_date'])}（非实时）</div></div><div class="quote-meta"><span class="source-pill">数据源：{e(status['provider'])}</span><span class="muted">数据日期 {e(data['evaluation_date'])}</span></div></section>''')
    st.caption(f"真实行情 · {data['evaluation_date']} · {status['provider']} · 结果最多缓存5分钟")
    # Five horizontal dashboard cards. Structure cards aggregate existing rule points only.
    cards=[f'<div class="score-card primary"><div class="score-label">综合评分 · QuantScore</div><div class="score-value">{number_text(data["final_quant_score"])} <small>/ 100</small></div><div class="score-foot">正向 {number_text(data["positive_score"])} · 风险扣分 {number_text(data["risk_penalty"])}</div></div>']
    for label,cats,accent in [('趋势结构',{'C'},'#1768f5'),('成交量结构',{'D'},'#02b9d8'),('形态结构',{'E','F'},'#7856ff')]:
        score,maximum,unknown=structure_totals(data['rules'],cats)
        width=0 if not maximum else min(100,score/maximum*100)
        cards.append(f'<div class="score-card" style="--accent:{accent}"><div class="score-label">{label}</div><div class="score-value">{score:g} <small>/ {maximum:g} 分</small></div><div class="meter"><i style="width:{width}%"></i></div><div class="score-foot">原规则得分合计 · {unknown} 项未知</div></div>')
    cards.append(f'<div class="score-card risk-card"><div class="score-label">风险 · Risk Level</div><div class="score-value">{e(data["risk_level"])}</div><div class="score-foot">已确认扣分 {number_text(data["risk_penalty"])} · 未知不等于无风险</div></div>')
    st.html('<section class="score-grid dashboard-score-grid">'+''.join(cards)+'</section>')
    if data['score_status']=='INSUFFICIENT':
        st.warning('可判断信息不足：当前评分不是完整策略结论。结构卡片为原规则得分合计，未折算为新的百分制评分。')
    left,right=st.columns([1.85,1],gap='medium')
    with left:
        with st.container(border=True, key='market_chart'):
            st.html('<div class="panel-title">行情走势 <span class="tags"><span>日K · 前复权</span></span></div><div class="panel-sub">最近120个交易日 · 均线沿用现有特征 · 成交量单位：股</div>')
            if data.get('chart'):
                st.plotly_chart(candle_chart(data['chart'],st.session_state.get('theme','light')),use_container_width=True,theme=None,config={'displayModeBar':False,'scrollZoom':False})
                st.caption(f"图表来源：{data.get('chart_provider',status['provider'])}；K线及均线为前复权，顶部收盘价为未复权。")
            else:
                st.info(data.get('chart_warning','暂无可展示的真实行情图数据。'))
    with right:
        with st.container(border=True, key='core_judgment'):
            st.html('<div class="panel-title">核心判断 <a href="#rules" style="float:right;font-size:12px;color:#1768f5">查看全部规则 →</a></div>')
            hits=[r for r in data['rules'] if (r['score'] or 0)>0 or (r.get('penalty') or 0)>0]
            positives=sorted([r for r in hits if (r['score'] or 0)>0],key=lambda r:r['score'],reverse=True)[:3]
            risks=sorted([r for r in hits if (r.get('penalty') or 0)>0],key=lambda r:r['penalty'],reverse=True)[:2]
            for r in positives+risks:
                risk=(r.get('penalty') or 0)>0
                points=f"−{r['penalty']:g}" if risk else f"+{r['score']:g}"
                st.html(f'<div class="rule-row"><div class="rule-icon {"risk" if risk else ""}">{"↓" if risk else "↑"}</div><div class="rule-copy"><div class="rule-name">{e(r["name_cn"])} <span class="muted">{e(r["rule_id"])}</span></div><div class="rule-desc">{e(r["explanation"])}</div></div><div class="rule-points {"up" if risk else "down"}">{points}</div></div>')
            if not hits: st.write('暂无已确认的得分或扣分规则。')
    unknown=sum(r['status']=='UNKNOWN' for r in data['rules'])
    st.html(f'<div class="conclusion"><div style="flex:1"><div class="panel-title">综合结论</div><p>当前规则匹配得分 {number_text(data["final_quant_score"])} 分，已判断风险等级 {e(data["risk_level"])}。正向得分 {number_text(data["positive_score"])}，风险扣分 {number_text(data["risk_penalty"])}；仍有 {unknown} 条规则为 UNKNOWN。请结合规则解释与覆盖率阅读，不将缺少证据理解为条件不成立。</p></div><div class="conclusion-badge">策略匹配分析工具<br>不构成投资建议<br>数据日期 {e(data["evaluation_date"])}</div></div>')
    sections=st.columns([1,1.35],gap='medium')
    with sections[0]:
        st.html(f'<div class="home-panel composition"><div class="panel-title">评分构成</div><div class="composition-values"><span>正向得分<b>{number_text(data["positive_score"])}</b></span><span>风险扣分<b>{number_text(data["risk_penalty"])}</b></span><span>最终得分<b>{number_text(data["final_quant_score"])}</b></span></div><div class="panel-sub">沿用原引擎结果，不重新加权或换算。</div></div>')
    with sections[1]:
        count=len(data['rules'])
        st.html(f'<div class="home-panel composition"><div class="panel-title">其他信息</div><div class="info-row"><span>已完成判断 / 规则总数</span><strong>{count-unknown} / {count}</strong></div><div class="info-row"><span>数据日期 · 来源</span><strong>{e(data["evaluation_date"])} · {e(status["provider"])}</strong></div><div class="info-row"><span>正向 / 风险覆盖率</span><strong>{coverage_text(data["positive_coverage"])} / {coverage_text(data["risk_coverage"])}</strong></div><div class="info-row"><span>市值 / 估值</span><strong>未接入</strong></div></div>')
    with st.expander('主要正向原因 / 主要风险原因 · 完整说明'):
        for title,key in [('主要正向原因','top_positive_reasons'),('主要风险原因','top_risk_reasons')]:
            st.subheader(title)
            for reason in data[key]:st.write('• '+reason)
