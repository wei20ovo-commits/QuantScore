"""R4 v1.3: as-of structure, nearest P2 selection and reversible risk alert."""
from decimal import Decimal
from app.rules.base import require, indicators, result, UnknownData, high_zone, divide


def decimal(value):
    return Decimal(str(value))


def r4(ctx,rule,p):
    q=p['R4']; side=p['GLOBAL']['local_peak_side']; df=ctx.bars
    require(df,['open_adj','high_adj','low_adj','close_adj'],q['minimum_days'])
    if ctx.metadata.get('adjustment_consistent') is not True:
        raise UnknownData('R4需要明确确认全窗口复权口径一致', 'ADJUSTMENT_UNVERIFIED')
    # Reject holes over the actual scan and its pre-rise context.
    require(df,['open_adj','high_adj','low_adj','close_adj'],min(len(df),q['search_days']+q['pre_rise_days']))
    d=indicators(df,p); start=max(side,len(d)-q['search_days']); end=len(d)-1
    confirmed=[]; tentative=[]
    for j in range(start,end+1):
        h=float(d.high_adj.iloc[j]); left=d.high_adj.iloc[j-side:j]
        right=d.high_adj.iloc[j+1:min(len(d),j+side+1)]
        if h>=float(left.max()) and (right.empty or h>=float(right.max())):
            (confirmed if len(right)==side else tentative).append(j)
    structures=[]; unresolved=[]; checked=[]
    for p1 in confirmed:
        for p2 in confirmed+tentative:
            gap=p2-p1
            if not q['peak_gap_days_min']<=gap<=q['peak_gap_days_max']:
                continue
            h1=float(d.high_adj.iloc[p1]); h2=float(d.high_adj.iloc[p2])
            # Decimal comparisons preserve inclusive documented boundaries,
            # e.g. 20.6 versus 20 is exactly 3%, without a trading tolerance.
            diff_exact=abs(decimal(h2)-decimal(h1))/decimal(h1)
            diff=float(diff_exact)
            valley=float(d.low_adj.iloc[p1+1:p2].min())
            draw_exact=(decimal(min(h1,h2))-decimal(valley))/decimal(min(h1,h2))
            draw=float(draw_exact)
            conditions={'gap_valid':True,'height_diff_le_3pct':diff_exact<=decimal(q['peak_diff_max']),
                        'valley_drawdown_ge_5pct':draw_exact>=decimal(q['valley_drawdown_min']),
                        'P1_confirmed':True,'P2_confirmed':p2 in confirmed}
            if not conditions['height_diff_le_3pct'] or not conditions['valley_drawdown_ge_5pct']:
                continue
            date1=str(d.date.iloc[p1].date()); date2=str(d.date.iloc[p2].date())
            raw={'P1':{'date':date1,'high':h1,'close':float(d.close_adj.iloc[p1])},
                 'P2':{'date':date2,'high':h2,'close':float(d.close_adj.iloc[p2])},
                 'gap_days':gap,'peak_diff':diff,'Valley':valley,'neckline':valley,
                 'valley_drawdown':draw,'valley_date':str(d.date.iloc[p1+1+int(d.low_adj.iloc[p1+1:p2].argmin())].date())}
            pre_rise=None if p1<q['pre_rise_days'] else divide(d.close_adj.iloc[p1],d.close_adj.iloc[p1-q['pre_rise_days']])-1
            high_flags=[]
            for peak in (p1,p2):
                try:
                    flag, evidence=high_zone(d,p,peak)
                except UnknownData:
                    flag,evidence=None,{}
                high_flags.append(flag)
                raw['high_zone_'+('P1' if peak==p1 else 'P2')]=evidence
            high=True if (pre_rise is not None and pre_rise>=q['pre_rise_min']) or True in high_flags else None if None in high_flags or pre_rise is None else False
            raw['P1_pre20_return']=pre_rise; conditions['high_context']=high
            if high is False:
                checked.append({'raw_values':raw,'conditions':conditions})
                continue
            if high is None:
                unresolved.append({'reason':'高位前置数据不足','raw_values':raw,'conditions':conditions})
                continue
            # V1.3: a peak with incomplete right confirmation stays candidate.
            breakout_level=decimal(h1)*(1+decimal(q['effective_breakout_margin']))
            effective=decimal(d.close_adj.iloc[p2])>breakout_level
            conditions['P2_effective_breakout']=effective
            conditions['failed_breakout']=not effective
            # failed_breakout is only a descriptive alias for the explicit P2 test.
            post=d.iloc[p2+1:]; weak_end=min(len(d),p2+1+q['weakening_days'])
            weak=d.iloc[p2+1:weak_end]
            weakening=(weak.close_adj<weak.M5) | (weak.close_adj<=d.close_adj.iloc[p2]*(1-q['weakening_drop']))
            neckline_break=post.close_adj<valley
            upper=post.close_adj.map(lambda close: decimal(close)>breakout_level)
            consecutive=upper.rolling(q['invalidation_consecutive_days']).sum()==q['invalidation_consecutive_days']
            invalid=effective or bool(consecutive.any())
            state='INVALIDATED' if invalid else 'CONFIRMED' if bool(neckline_break.any()) else 'FORMED' if bool(weakening.any()) else 'CANDIDATE'
            if p2 in tentative:
                state='CANDIDATE'
            conditions.update({'weakened_within_3_days':bool(weakening.any()),'neckline_broken':bool(neckline_break.any()),'two_consecutive_closes_above_103pct':bool(consecutive.any())})
            raw['post_P2']=[{'date':str(row.date.date()),'close':float(row.close_adj),'M5':float(row.M5)} for row in post.itertuples()]
            raw['breakout_level']=h1*(1+q['effective_breakout_margin'])
            raw['transition_dates']={
                'formed':str(d.date.loc[weakening[weakening].index[0]].date()) if weakening.any() else None,
                'confirmed':str(d.date.loc[neckline_break[neckline_break].index[0]].date()) if neckline_break.any() else None,
                'invalidated':str(d.date.loc[consecutive[consecutive].index[0]].date()) if consecutive.any() else date2 if effective else None}
            structures.append({'status':state,'raw_values':raw,'conditions':conditions,'event_id':f'R4:{date1}:{date2}'})
    if unresolved and not structures:
        return result(rule,'UNKNOWN',raw={'structures':structures,'unresolved':unresolved},conditions={'high_context_evidence_complete':False},reason_code='DATA_INSUFFICIENT',
                      explanation='候选峰谷结构存在，但高位前置所需历史数据不足；多结构选择本身不再造成UNKNOWN。')
    if not structures:
        return result(rule,raw={'confirmed_peak_dates':[str(d.date.iloc[j].date()) for j in confirmed],'tentative_peak_dates':[str(d.date.iloc[j].date()) for j in tentative],'rejected_high_context':checked},conditions={'double_top_structure':False},applicable=False,explanation='可用窗口内未发现同时满足峰间隔、高度差、谷底回撤与高位前置的双顶结构，扣0分。')
    structures.sort(key=lambda e:(-int(e['raw_values']['P2']['date'].replace('-','')),
                                  abs(e['raw_values']['P2']['high']-e['raw_values']['P1']['high']),
                                  -int(e['raw_values']['P1']['date'].replace('-',''))))
    event=structures[0]; state=event['status']; raw=event['raw_values']; penalty=q['penalties'][state]
    raw['selection_candidates']=[{'event_id':e['event_id'],'P2_date':e['raw_values']['P2']['date'],'absolute_peak_difference':abs(e['raw_values']['P2']['high']-e['raw_values']['P1']['high']),'status':e['status']} for e in structures]
    alert=state in ('CANDIDATE','FORMED','CONFIRMED')
    return result(rule,state,penalty=penalty,raw=raw,conditions=event['conditions'],event_id=event['event_id'],applicable=True,
                  exit_risk_alert=alert,alert_type='DOUBLE_TOP_EXIT_RISK' if alert else None,alert_text=q['alert_text'] if alert else None,
                  explanation=f'两峰相隔{raw["gap_days"]}日，高度差{raw["peak_diff"]:.2%}，谷底回撤{raw["valley_drawdown"]:.2%}，颈线{raw["neckline"]:.4f}；状态{state}，仅扣当前最高严重档{penalty}分。'+('第二峰为最新日，未获右侧确认，仅为候选峰。' if not event['conditions']['P2_confirmed'] else ''))
