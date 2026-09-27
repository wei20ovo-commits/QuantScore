import bisect
from app.rules.base import require, indicators, divide, result, UnknownData, ambiguous_boundary


def c1(ctx, rule, p):
    w=p['C1']['days']; require(ctx.bars,['close_adj'],60+w-1)
    d=indicators(ctx.bars,p).iloc[-w:]
    checks=(d.close_adj>=d.M60*(1-p['C1']['above_tolerance']))
    count=int(checks.sum()); score=p['C1']['scores_by_count'][count]
    return result(rule,score=score,raw={'close':d.close_adj.tolist(),'M60':d.M60.tolist(),'days_above':count},
                  conditions={'daily_above':checks.tolist()},explanation=f'最近{w}日中{count}日不低于M60容差线，得{score}/{rule["max_score"]}分。')


def c2(ctx, rule, p):
    lag=p['GLOBAL']['slope_window']; require(ctx.bars,['close_adj'],60+lag)
    d=indicators(ctx.bars,p); slope=divide(d.M60.iloc[-1],d.M60.iloc[-1-lag])-1
    q=p['C2']; i=bisect.bisect_right(q['boundaries'],round(slope,12))
    score=q['scores'][i]
    return result(rule,score=score,raw={'M60':float(d.M60.iloc[-1]),'M60_lag':float(d.M60.iloc[-1-lag]),'slope':slope},
                  conditions={'tier_index':i},explanation=f'M60十日变化{slope:.2%}，得{score}分。')


def c3(ctx, rule, p):
    require(ctx.bars,['close_adj'],60); d=indicators(ctx.bars,p).iloc[-1]
    full=bool(d.close_adj>d.M5>d.M30>d.M60)
    partial=bool(d.close_adj>d.M5>d.M60)
    score=p['C3']['scores'][2 if full else 1 if partial else 0]
    return result(rule,score=score,raw={k:float(d[k]) for k in ['close_adj','M5','M30','M60']},
                  conditions={'close_gt_M5_gt_M30_gt_M60':full,'close_gt_M5_gt_M60':partial},explanation=f'完整多头结构={full}，部分结构={partial}；仅取一个档位，得{score}分。')


def cross_events(df,p,days):
    require(df,['close_adj'],60+days)
    d=indicators(df,p); events=[]; q=p['C4']
    for j in range(len(d)-days,len(d)):
        if d.close_adj.iloc[j-1]<=d.M60.iloc[j-1] and d.close_adj.iloc[j]>=d.M60.iloc[j]*(1+q['breakout_margin']):
            events.append(j)
    return d,events


def c4(ctx,rule,p):
    q=p['C4']; d,events=cross_events(ctx.bars,p,q['search_days'])
    details=[]; best=0
    for j in events:
        subsequent=d.iloc[j+1:min(len(d),j+1+q['confirmation_days'])]
        count=int((subsequent.close_adj>=subsequent.M60).sum())
        confirmed=count>=q['confirmation_count']
        pending=len(subsequent)<q['confirmation_days']
        if not confirmed and not pending:
            # The spec has no score for an exhausted failed confirmation window.
            details.append({'date':str(d.date.iloc[j].date()),'cross_close':float(d.close_adj.iloc[j]),'cross_m60':float(d.M60.iloc[j]),'confirmation_count':count,'expired_unconfirmed':True})
        else:
            best=max(best,q['scores'][2 if confirmed else 1])
            details.append({'date':str(d.date.iloc[j].date()),'cross_close':float(d.close_adj.iloc[j]),'cross_m60':float(d.M60.iloc[j]),'confirmation_count':count,'confirmed':confirmed})
    recent=d.iloc[-1-q['reclaim_days']:-1]
    prior_below=bool((recent.close_adj<recent.M60).any())
    above=bool(d.close_adj.iloc[-1]>=d.M60.iloc[-1]*(1+q['breakout_margin']))
    ret=divide(d.close_adj.iloc[-1],d.close_adj.iloc[-2])-1
    strong=ret>=q['strong_return']; near=None
    if {'close_raw','limit_up_price'} <= set(d.columns):
        require(d,['close_raw','limit_up_price'],1)
        near=bool(d.close_raw.iloc[-1]>=d.limit_up_price.iloc[-1]*(1-p['GLOBAL']['near_limit_tol']))
    reclaim=prior_below and above and (strong or near is True)
    if reclaim: best=q['scores'][2]
    raw={'events':details,'return_1d':ret,'close':float(d.close_adj.iloc[-1]),'M60':float(d.M60.iloc[-1]),'near_limit':near}
    conditions={'prior_1_3_day_below':prior_below,'close_ge_M60_101pct':above,'strong_return':strong,'reclaim':reclaim,'limit_proxy_used':near is None}
    if best==0 and any(x.get('expired_unconfirmed') for x in details):
        return result(rule,'FAIL',raw=raw,conditions=conditions,reason_code='CONFIRMATION_FAILED',explanation='M60穿越后已满3日但不足2日站上，确认失败，得0分。')
    return result(rule,score=best,raw=raw,conditions=conditions,
                  event_id=f'C4:{details[-1]["date"]}' if details else None,
                  explanation=f'M60穿越事件{len(events)}个；快速收复={reclaim}；得{best}分。'+('缺涨停价，快速收复使用规范允许的日涨幅代理。' if near is None else ''))


def a1(ctx,rule,p):
    q=p['A1']; require(ctx.benchmark,['close_adj'],20+q['trend_lag'])
    d=indicators(ctx.benchmark,p); above=bool(d.close_adj.iloc[-1]>d.M20.iloc[-1]); up=bool(d.M20.iloc[-1]>d.M20.iloc[-1-q['trend_lag']])
    score=q['scores'][int(above)+int(up)]
    return result(rule,score=score,raw={'close':float(d.close_adj.iloc[-1]),'M20':float(d.M20.iloc[-1]),'M20_lag':float(d.M20.iloc[-1-q['trend_lag']])},conditions={'above_m20':above,'m20_up':up},explanation=f'大盘站上M20={above}，M20抬升={up}；得{score}分。')


def a2(ctx,rule,p):
    lag=p['GLOBAL']['slope_window']; require(ctx.benchmark,['close_adj'],60+lag)
    d=indicators(ctx.benchmark,p); slope=divide(d.M60.iloc[-1],d.M60.iloc[-1-lag])-1; above=bool(d.close_adj.iloc[-1]>d.M60.iloc[-1]); q=p['A2']
    score=q['scores'][2 if above and round(slope,12)>=q['slope_full'] else 1 if above and round(slope,12)>=q['slope_partial'] else 0]
    return result(rule,score=score,raw={'close':float(d.close_adj.iloc[-1]),'M60':float(d.M60.iloc[-1]),'M60_lag':float(d.M60.iloc[-1-lag]),'slope':slope},conditions={'above_m60':above},explanation=f'大盘M60十日变化{slope:.2%}，站上M60={above}，得{score}分。')


def a3(ctx,rule,p):
    q=p['A3']; require(ctx.benchmark,['close_adj'],q['return_days']+1)
    c=ctx.benchmark.close_adj; ret=divide(c.iloc[-1],c.iloc[-1-q['return_days']])-1
    i=bisect.bisect_right(q['boundaries'],round(ret,12))
    score=q['scores'][i]
    return result(rule,score=score,raw={'close':float(c.iloc[-1]),'close_lag':float(c.iloc[-1-q['return_days']]),'return_5d':ret},conditions={'tier_index':i},explanation=f'大盘5日收益{ret:.2%}，得{score}分。')
