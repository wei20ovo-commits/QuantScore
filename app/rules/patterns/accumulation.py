from app.rules.base import require,indicators,result,UnknownData,divide
from app.rules.periods import completed_periods,peaks
from app.rules.trend.platform_belt import platform


def e1(ctx,rule,p):
    q=p['E1']; d=ctx.bars; minimum=q['min_run_days']
    require(d,['open_adj','high_adj','low_adj','close_adj'],minimum+1)
    d=indicators(d,p); returns=d.close_adj.pct_change(fill_method=None)
    start_scan=max(1,len(d)-q['search_days'])
    require(d,['open_adj','high_adj','low_adj','close_adj'],len(d)-start_scan+1)
    run=[]; exceptions=0; transitions=0; invalid_reason=None; last_break=None
    # Chronological resets prevent dropping an offending candle from the
    # middle of a continuous structure to manufacture a legal suffix.
    for i in range(start_scan,len(d)):
        ret=round(float(returns.iloc[i]),12); body=abs(float(d.close_adj.iloc[i]-d.open_adj.iloc[i]))/float(d.close_adj.iloc[i-1])
        invalid_reason=None
        if ret>=q['big_bull_return_min'] or ret<=q['small_bear_min']:
            invalid_reason='BIG_BULL' if ret>=q['big_bull_return_min'] else 'LARGE_DROP'
        is_transition=q['small_bull_max']<=ret<q['big_bull_return_min']
        is_doji=round(body,12)<=q['doji_body_max']; small=0<ret<q['small_bull_max']
        exception=not is_transition and (is_doji or q['small_bear_min']<ret<=0)
        if not run and not exception:
            exceptions=0; transitions=0
        transitions+=int(is_transition); exceptions+=int(exception)
        if invalid_reason is None and transitions>q['max_transitions']: invalid_reason='TOO_MANY_TRANSITIONS'
        if invalid_reason is None and exceptions>q['max_exceptions']: invalid_reason='TOO_MANY_EXCEPTIONS'
        if invalid_reason:
            last_break={'date':str(d.date.iloc[i].date()),'reason':invalid_reason,'return':ret}
            run=[]; exceptions=0; transitions=0
            continue
        # A preceding flat stretch is not part of a new small-bull run.
        # Exceptions may occur inside a started run, not seed one themselves.
        if not run and exception: continue
        run.append({'date':str(d.date.iloc[i].date()),'return':ret,'body_ratio':body,'small_bull':small and not is_doji,'exception':exception,'transition':is_transition})
    raw={'run':run,'length':len(run),'invalid_reason':invalid_reason,'last_break':last_break,'transition_count':transitions,'exception_count':exceptions}
    if len(run)<minimum:
        state='INVALIDATED' if invalid_reason else 'CANDIDATE'
        return result(rule,state,raw=raw,conditions={'minimum_run':False},explanation='连续小连阳不足7日；大阳、大跌、第2根过渡阳或第2根例外终止本段，不能拼接中断前后的K线。')
    # Low-zone evaluated at the beginning of the run, never inferred from M60 alone.
    start=len(d)-len(run); prefix=d.iloc[:start+1]
    require(prefix,['close_adj','high_adj','low_adj'],p['GLOBAL']['position_window'])
    zone=prefix.tail(p['GLOBAL']['position_window'])
    position=divide(prefix.close_adj.iloc[-1]-zone.low_adj.min(),zone.high_adj.max()-zone.low_adj.min())
    low=position<=p['GLOBAL']['low_zone_position'] and prefix.close_adj.iloc[-1]<=prefix.M60.iloc[-1]*p['GLOBAL']['low_zone_m60_ratio']
    preceding=platform(d.iloc[:-1],p) if len(d)>64 else None
    started=None if preceding is None else bool(d.close_adj.iloc[-1]>d.M60.iloc[-1] and d.close_adj.iloc[-1]>preceding['platform_high'])
    raw.update(position_at_start=position,started=started,platform_high=None if preceding is None else preceding['platform_high'])
    score=q['scores'][1] if low and started is not True else 0
    return result(rule,score=score,raw=raw,conditions={'LOW_ZONE_at_start':bool(low),'minimum_run':True,'started':started},explanation=f'连续{len(run)}日，例外最多1根；底部前置={low}，正式启动={started}，得{score}分。站上M60本身不等于启动。')


def e2(ctx,rule,p):
    q=p['E2']; d=completed_periods(ctx,'W').tail(q['search_weeks']).reset_index(drop=True)
    require(d,['high_adj','low_adj','close_adj','volume'],q['minimum_weeks'])
    points=peaks(d.high_adj,p['GLOBAL']['local_peak_side'])
    # The ±2 reference neighborhood must have ended before the current week.
    points=[i for i in points if i+q['high_zone_week_radius']<len(d)-1]
    if not points:
        return result(rule,'FAIL',raw={'completed_weeks':len(d)},conditions={'previous_peak':False},explanation='完整周线中没有已结束且已确认的上一轮高点，条件不成立。')
    i=points[-1]; radius=q['high_zone_week_radius']; around=d.iloc[max(0,i-radius):i+radius+1]
    ref=float(around.volume.max()); peak=float(d.high_adj.iloc[i]); low=float(d.low_adj.iloc[i+1:].min())
    if peak<=low:
        return result(rule,'FAIL',raw={'previous_high':peak,'post_low':low},conditions={'bottom_zone':False},explanation='高点之后未形成可定义的底部价格区间。')
    position=divide(d.close_adj.iloc[-1]-low,peak-low); bottom=position<=q['bottom_position_max']; reversal=float(d.volume.iloc[-1])>ref
    raw={'peak_date':str(d.date.iloc[i].date()),'reference_weeks':[{'date':str(row.date.date()),'volume':float(row.volume)} for row in around.itertuples()],
         'previous_cycle_peak_volume':ref,'current_week_volume':float(d.volume.iloc[-1]),'bottom_position':position}
    state='CONFIRMED' if bottom and reversal else 'CANDIDATE' if bottom else 'FAIL'
    return result(rule,state,score=q['scores'][1] if state=='CONFIRMED' else 0,raw=raw,conditions={'bottom_zone':bottom,'volume_exceeds_previous_cycle':reversal},explanation='取最近已结束高点前后各2周最大周量；当前完整周量超过即确认，不要求连续放量或先缩量N周。')


def e3(ctx,rule,p):
    q=p['E3']; require(ctx.bars,['close_adj','volume'],2*q['minimum_group']+1)
    require(ctx.bars,['close_adj','volume'],len(ctx.bars))
    d=ctx.bars; ret=d.close_adj.pct_change(fill_method=None); candidates=[]; sufficient=False
    # No fixed duration/scan cap: all supplied past daily windows are eligible.
    for start in range(1,len(d)-2*q['minimum_group']+1):
        r=ret.iloc[start:]; v=d.volume.iloc[start:]; up=v[r>0]; down=v[r<0]
        if min(len(up),len(down))<q['minimum_group']: continue
        sufficient=True; small=float((r.abs().round(12)<=q['damping_small_move_pct']).mean()); ratio=divide(up.mean(),down.mean())
        if small>=q['small_move_fraction_min'] and ratio>1:
            candidates.append({'length':len(r),'small_move_fraction':small,'up_count':len(up),'down_count':len(down),
                               'avg_up_volume':float(up.mean()),'avg_down_volume':float(down.mean()),'volume_ratio':ratio})
    if not sufficient: raise UnknownData('阻尼证据不足：至少3个上涨日和3个下跌日')
    if not candidates: return result(rule,raw={'tested_history':len(d)},conditions={'damping':False},explanation='样本充分，但80%小幅波动与上涨均量大于下跌均量未同时成立。')
    raw=candidates[0]; score=q['scores'][2] if raw['volume_ratio']>=q['full_volume_ratio'] else q['scores'][1]
    return result(rule,score=score,raw=raw,conditions={'small_moves':True,'up_volume_gt_down_volume':True,'shrinking_amplitude_required':False},explanation=f'最长有效窗口{raw["length"]}日，至少80%日绝对涨跌幅不超过5%；上涨量大于下跌量；得{score}分，不要求振幅逐级缩小。')
