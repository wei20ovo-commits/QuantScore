import bisect
from app.rules.base import require, indicators, divide, result, high_zone


def r1(ctx,rule,p):
    require(ctx.bars,['turnover_rate'],1); high,raw=high_zone(ctx.bars,p)
    turn=float(ctx.bars.turnover_rate.iloc[-1]); q=p['R1']
    penalty=q['penalties'][bisect.bisect_right(q['turnover_levels'],turn)] if high else 0
    return result(rule,penalty=penalty,raw={**raw,'turnover_rate_pct':turn},conditions={'HIGH_ZONE':bool(high),'hard_high':bool(high and turn>=q['hard_high_turnover'])},applicable=bool(high),explanation=f'高位={high}，换手率{turn:.2f}%，仅扣最高档{penalty}分。')


def r2(ctx,rule,p):
    w=p['GLOBAL']['volume_window']; require(ctx.bars,['volume'],w+1); high,raw=high_zone(ctx.bars,p)
    volume=float(ctx.bars.volume.iloc[-1]); mean=float(ctx.bars.volume.iloc[-w-1:-1].mean()); vr=divide(volume,mean); q=p['R2']
    penalty=q['penalties'][bisect.bisect_right(q['volume_levels'],vr)] if high else 0
    return result(rule,penalty=penalty,raw={**raw,'volume':volume,'previous_mean_volume':mean,'volume_ratio_20':vr},conditions={'HIGH_ZONE':bool(high)},applicable=bool(high),explanation=f'高位={high}，量比{vr:.2f}，仅扣最高档{penalty}分。')


def r3(ctx,rule,p):
    import math
    from app.rules.base import UnknownData
    d = ctx.bars
    q=p['R3']
    high, raw = high_zone(d, p)
    if not high:
        return result(rule, conditions={'HIGH_ZONE':False}, explanation='非高位，不适用出货板风险。')
    require(d, ['high_raw','close_raw','limit_up_price'], 1)
    raw.update(high_raw=float(d.high_raw.iloc[-1]), close_raw=float(d.close_raw.iloc[-1]),
               limit_up_price=float(d.limit_up_price.iloc[-1]))
    failed = bool(d.high_raw.iloc[-1]>=d.limit_up_price.iloc[-1]*(1-p['GLOBAL']['near_limit_tol']) and round(divide(d.close_raw.iloc[-1],d.limit_up_price.iloc[-1]),12)<=q['failed_seal_ratio'])
    if not failed:
        return result(rule, conditions={'HIGH_ZONE':True,'failed_seal':False}, explanation='当前未出现触板后封板失败。')
    require(d, ['close_adj'], q['strong_days']+1)
    strong = divide(d.close_adj.iloc[-1],d.close_adj.iloc[-q['strong_days']-1])-1 >= q['strong_return']
    if not strong:
        require(d, ['close_raw','limit_up_price'], q['strong_days'])
        strong = int((d.close_raw.tail(q['strong_days'])>=d.limit_up_price.tail(q['strong_days'])*(1-p['GLOBAL']['near_limit_tol'])).sum())>=q['near_limit_count']
    if not strong:
        return result(rule, conditions={'strong_context':False}, explanation='过去5日无至少两次近涨停，累计涨幅亦不足25%。')
    features = indicators(d,p)
    turn = float(d.turnover_rate.iloc[-1]) if 'turnover_rate' in d else float('nan')
    vr = float(features.volume_ratio_20.iloc[-1]) if 'volume_ratio_20' in features else float('nan')
    large = (math.isfinite(turn) and turn>=q['large_turnover']) or (math.isfinite(vr) and vr>=q['large_volume_ratio'])
    if not large and not (math.isfinite(turn) and math.isfinite(vr)):
        raise UnknownData('量能与换手不足以判断大成交')
    penalty = q['penalties'][1 if large else 0]
    raw.update(turnover_rate=turn if math.isfinite(turn) else None, volume_ratio_20=vr if math.isfinite(vr) else None)
    return result(rule, penalty=penalty, raw=raw, conditions={'failed_seal':True,'large_trade':bool(large),'hard_high':bool(large)}, explanation=f'高位强势背景下触板未封，扣{penalty}分。')


def r5(ctx,rule,p):
    d = ctx.bars
    q=p['R5']
    require(d, ['open_adj','high_adj','low_adj','close_adj'], 3)
    high_c, raw = high_zone(d,p)
    high_b = False if high_c else high_zone(d.iloc[:-1],p)[0]
    if not (high_b or high_c):
        return result(rule, conditions={'HIGH_ZONE':False}, explanation='第二和第三日均非高位。')
    a,b,c = [d.iloc[i] for i in (-3,-2,-1)]
    ar = round(divide(a.close_adj-a.open_adj,a.open_adj),12)
    br = round(abs(divide(b.close_adj-b.open_adj,b.open_adj)),12)
    cr = round(divide(c.close_adj-c.open_adj,c.open_adj),12)
    shape = ar>=q['bull_body_min'] and round(divide(b.open_adj,a.close_adj),12)>=q['gap_ratio'] and br<=q['small_body_max'] and cr<=q['bear_body_max']
    confirmed = bool(c.close_adj<(a.open_adj+a.close_adj)/2)
    penalty = q['penalties'][int(confirmed)] if shape else 0
    return result(rule, 'PASS' if penalty==10 else 'CANDIDATE' if penalty else 'FAIL', penalty=penalty,
                  raw={**raw,'A_body_return':ar,'B_body_return':br,'C_body_return':cr,'A_mid':float((a.open_adj+a.close_adj)/2),
                       'candles':[{k:float(row[k]) for k in ('open_adj','high_adj','low_adj','close_adj')} for row in (a,b,c)]},
                  conditions={'consecutive_three_bars':True,'shape':bool(shape),'confirmed':confirmed},
                  explanation=f'连续三K高位反转，实体中点确认={confirmed}，扣{penalty}分。')


def r9(ctx,rule,p):
    # 33 closes also establish whether the earlier break was a single-day event.
    require(ctx.bars,['close_adj','low_adj'],33); d=indicators(ctx.bars,p); q=p['R9']
    below=(d.close_adj<d.M30*(1-q['m30_break_margin']))
    now=bool(below.iloc[-1]); prior=bool(below.iloc[-2])
    recovered=bool(d.close_adj.iloc[-1]>d.M30.iloc[-1]*(1+q['reclaim_margin']))
    single_prior=any(bool(below.iloc[-1-k]) and not bool(below.iloc[-2-k])
                     and not bool(below.iloc[-k:-1].any())
                     for k in range(1,q['reclaim_days']+1))
    raw={'close':d.close_adj.tail(3).tolist(),'low':d.low_adj.tail(3).tolist(),'M30':d.M30.tail(3).tolist()}
    conditions={'below_today':now,'below_yesterday':prior,'recovered':recovered,'single_break_in_recovery_window':single_prior}
    if recovered and single_prior:
        return result(rule,'INVALIDATED',raw=raw,conditions=conditions,applicable=True,explanation='原单日M30破位在2日内收盘超过M30的101%，当前原事件失效，扣0分。')
    warning=bool(d.low_adj.iloc[-1]<d.M30.iloc[-1] and d.close_adj.iloc[-1]>=d.M30.iloc[-1])
    penalty=q['penalties'][3 if now and prior else 2 if now else 1 if warning else 0]
    return result(rule,penalty=penalty,raw=raw,conditions={**conditions,'intraday_warning':warning},applicable=True,explanation=f'M30有效跌破当日={now}，前日={prior}；盘中警告={warning}，仅扣{penalty}分。')
