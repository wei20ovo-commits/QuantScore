import bisect
from app.rules.base import require, indicators, divide, result, UnknownData, ambiguous_boundary
from app.rules.trend.basic import cross_events


def d1(ctx,rule,p):
    q=p['D1']; d,crosses=cross_events(ctx.bars,p,q['search_days'])
    require(d,['close_adj'],60+q['search_days']+p['C4']['reclaim_days']-1)
    require(d,['high_adj','close_adj','volume'],q['resistance_days']+q['search_days'])
    events=[]
    for j in range(len(d)-q['search_days'],len(d)):
        resistance=float(d.high_adj.iloc[j-q['resistance_days']:j].max())
        price_break=bool(d.close_adj.iloc[j]>=resistance*(1+q['breakout_margin']))
        # Rapid reclaim is also an M60 event, even if yesterday already closed
        # slightly above M60. Evaluate its explicit conditions at the event date.
        cq=p['C4']; before=d.iloc[j-cq['reclaim_days']:j]
        reclaim_position=bool((before.close_adj<before.M60).any() and d.close_adj.iloc[j]>=d.M60.iloc[j]*(1+cq['breakout_margin']))
        strong=divide(d.close_adj.iloc[j],d.close_adj.iloc[j-1])-1>=cq['strong_return']
        near=False
        if reclaim_position and not strong and {'close_raw','limit_up_price'}<=set(d.columns):
            require(d.iloc[:j+1],['close_raw','limit_up_price'],1)
            near=bool(d.close_raw.iloc[j]>=d.limit_up_price.iloc[j]*(1-p['GLOBAL']['near_limit_tol']))
        reclaim=reclaim_position and (strong or near)
        if price_break or j in crosses or reclaim:
            vr=divide(d.volume.iloc[j],d.volume.iloc[j-q['resistance_days']:j].mean())
            events.append({'date':str(d.date.iloc[j].date()),'close':float(d.close_adj.iloc[j]),'resistance':resistance,'volume':float(d.volume.iloc[j]),'previous_mean_volume':float(d.volume.iloc[j-q['resistance_days']:j].mean()),'volume_ratio_20':vr,'price_break':price_break,'m60_cross':j in crosses,'m60_reclaim':reclaim})
    if not events:
        return result(rule,raw={'searched_days':q['search_days'],'closes':d.close_adj.tail(q['search_days']).tolist()},conditions={'breakout':False},explanation='最近5日无M60突破或20日压力位突破，得0分。')
    e=events[-1]; score=q['scores'][bisect.bisect_right(q['volume_levels'],e['volume_ratio_20'])]
    return result(rule,score=score,raw=e,conditions={'breakout':True,'latest_event_only':True},event_id='D1:'+e['date'],explanation=f'最新突破日量比{e["volume_ratio_20"]:.2f}，得{score}分；同日两种突破不重复计分。')


def d2(ctx,rule,p):
    from app.rules.base import Context, load_config
    registry, _ = load_config()
    q = p['D2']
    require(ctx.bars, ['close_adj', 'high_adj', 'low_adj', 'volume'], 70)
    d = indicators(ctx.bars, p)
    events = []
    for j in range(max(69, len(d)-q['search_days']), len(d)-1):
        event = d1(Context(d.iloc[:j+1]), registry['D1'], p)
        if not event.conditions.get('breakout') or event.raw_values['date'] != str(d.date.iloc[j].date()):
            continue
        follow = d.iloc[j+1:min(j+1+q['pullback_days_max'], len(d))]
        # The first retreat starts the observed pullback; never read beyond as_of.
        retreat = follow.low_adj < d.close_adj.iloc[j]
        if not retreat.any():
            continue
        pull = follow.loc[retreat.index[retreat][0]:]
        level = max(float(d.M60.iloc[j]), event.raw_values['resistance'])
        intact = bool((pull.close_adj >= level*q['support_ratio']).all())
        drop = divide(d.close_adj.iloc[j]-pull.low_adj.min(), d.close_adj.iloc[j])
        ratio = divide(pull.volume.mean(), d.volume.iloc[j])
        ratio, drop = round(ratio, 12), round(drop, 12)
        score = (q['scores'][0] if ratio<q['volume_levels'][0] and drop<=q['pullback_max'] else
                 q['scores'][1] if ratio<q['volume_levels'][1] and drop<=q['pullback_max'] else
                 q['scores'][2] if ratio<q['volume_levels'][2] else 0) if intact else 0
        events.append((score, {'event_date':event.raw_values['date'], 'breakout_level':level,
                              'pullback_drop':drop, 'vol_ratio':ratio, 'support_intact':intact,
                              'pullback_dates':[str(x.date()) for x in pull.date]}))
    if not events:
        return result(rule, conditions={'pullback':False}, explanation='最近10日未找到突破后1至5日首次回踩。')
    score, raw = events[-1]
    return result(rule, score=score, raw=raw, conditions={'support_intact':raw['support_intact']},
                  event_id='D2:'+raw['event_date'], explanation=f'冻结突破支撑位，回踩量比{raw["vol_ratio"]:.2f}，得{score}分；结构冲突由统一引擎取消。')


def d3(ctx,rule,p):
    q=p['D3']; require(ctx.bars,['close_adj','volume'],q['days']+1)
    d=ctx.bars.tail(q['days']+1); delta=d.close_adj.diff().iloc[1:]; volume=d.volume.iloc[1:]
    up=volume[delta>0]; down=volume[delta<0]
    if min(len(up),len(down))<q['minimum_group']:
        raise UnknownData('上涨日和下跌日至少各2天；平盘日剔除',raw={'up_count':len(up),'down_count':len(down)})
    ratio=divide(up.mean(),down.mean())
    score=q['scores'][bisect.bisect_right(q['boundaries'],round(ratio,12))]
    return result(rule,score=score,raw={'up_volumes':up.tolist(),'down_volumes':down.tolist(),'up_mean':float(up.mean()),'down_mean':float(down.mean()),'ratio':ratio},conditions={'sufficient_groups':True},explanation=f'近10日上涨日均量/下跌日均量={ratio:.2f}，得{score}分。')


def d4(ctx,rule,p):
    q=p['D4']; n=q['recent_days']; count=n+q['reference_days']
    require(ctx.bars,['close_adj','high_adj','low_adj','volume'],count)
    # Exclusion cannot be guessed from a fixed 10% price return.
    require(ctx.bars,['close_raw','limit_up_price'],n)
    d=ctx.bars; recent=d.tail(n)
    near=bool((recent.close_raw>=recent.limit_up_price*(1-p['GLOBAL']['near_limit_tol'])).any())
    if near:
        return result(rule,'FAIL',reason_code='NOT_APPLICABLE',applicable=False,raw={'close_raw':recent.close_raw.tolist(),'limit_up_price':recent.limit_up_price.tolist()},conditions={'recent_limit_start':True},explanation='最近3日含涨停，整理期规则前置明确不成立，得0分。')
    ratio=divide(recent.volume.mean(),d.volume.iloc[-count:-n].mean())
    width=divide(recent.high_adj.max()-recent.low_adj.min(),recent.close_adj.mean())
    idx=bisect.bisect_right(q['volume_levels'],round(ratio,12))
    score=q['scores'][idx] if width<=q['range_max'] else 0
    return result(rule,score=score,raw={'recent_volumes':recent.volume.tolist(),'previous_volumes':d.volume.iloc[-count:-n].tolist(),'volume_ratio':ratio,'range3':width,'high3':recent.high_adj.tolist(),'low3':recent.low_adj.tolist(),'close3':recent.close_adj.tolist()},conditions={'consolidation_range_le_8pct':width<=q['range_max'],'recent_limit_start':False},explanation=f'3日振幅{width:.2%}，3日均量/此前10日均量={ratio:.2f}；得{score}分。')


def d5(ctx,rule,p):
    require(ctx.bars,['turnover_rate'],1); turn=float(ctx.bars.turnover_rate.iloc[-1]); q=p['D5']; b=q['boundaries']
    i=2 if b[1]<=turn<b[2] else 3 if b[2]<=turn<b[3] else 1 if b[0]<=turn<b[1] else 4 if b[3]<=turn<b[4] else 0
    score=q['scores'][i]
    return result(rule,score=score,raw={'turnover_rate_pct':turn},conditions={'tier_index':i},explanation=f'当日换手率{turn:.2f}%，按区间得{score}分；高位风险由R1独立评价。')
