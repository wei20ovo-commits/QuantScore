from app.rules.base import require,indicators,result,divide,high_zone,UnknownData


def f1x(ctx,rule,p):
    from app.rules.trend.platform_belt import platform
    d = indicators(ctx.bars,p)
    require(d, ['close_adj','high_adj','low_adj'], 140)
    require(d, ['close_raw','high_raw','turnover_rate'], 21)
    q = p['F1-X']
    passes = []
    current = None
    # Replay in chronological order: suppressed occurrences are not prior PASS.
    for j in range(119,len(d)):
        prefix=d.iloc[:j+1]
        require(prefix,['close_raw','high_raw','turnover_rate'],2)
        row=prefix.iloc[-1]
        high,_=high_zone(prefix,p)
        distance=divide(row.close_adj,row.M60)-1
        location=not high and row.close_adj>row.M60 and (abs(distance)<=p['GLOBAL']['near_m60_pct'] or bool(platform(prefix,p)))
        gain=round(divide(row.high_raw,prefix.close_raw.iloc[-2])-1,12)
        retreat=round(1-divide(row.close_raw,row.high_raw),12)
        shape=location and q['intraday_gain_min']<=gain<=q['intraday_gain_max'] and retreat>=q['pullback_min']
        if shape:
            require(prefix,['limit_up_price'],1)
            shape = row.close_raw < row.limit_up_price*(1-p['GLOBAL']['near_limit_tol'])
        first=not any(j-q['first_signal_days']<=i<j for i in passes)
        score=(q['scores'][0] if row.turnover_rate<q['turnover_levels'][0] else q['scores'][1] if row.turnover_rate<q['turnover_levels'][1] else 0) if shape and first else 0
        if score==q['scores'][0]: passes.append(j)
        current=(score,{'event_date':str(row.date.date()),'intraday_gain':gain,'pullback_from_high':retreat,'turnover_rate':float(row.turnover_rate),'dist_m60':distance}, {'launch_location':bool(location),'first_signal':first,'shape':bool(shape)})
    score,raw,conditions=current
    conditions['high_turnover_warning'] = bool(conditions['shape'] and raw['turnover_rate'] >= q['turnover_levels'][1])
    return result(rule,score=score,raw=raw,conditions=conditions,explanation=f'仙人指路首次信号={conditions["first_signal"]}，得{score}分；高换手提示={conditions["high_turnover_warning"]}；缺可靠涨停价不使用固定10%替代。')


def f2(ctx,rule,p):
    from app.engine.rule_engine import RuleEngine
    from app.engine.conflicts import resolve
    from app.rules.trend.platform_belt import platform
    engine=RuleEngine(parameters=p)
    ids=('F1-N','F1-T','F1-O','F1-X','F1-Y','R11','R12','R3','F3')
    evaluated=resolve([engine.evaluate(rid,ctx) for rid in ids])
    hits=[r for r in evaluated if r.rule_id.startswith('F1-') and (r.score or 0)>0]
    if not hits:
        if any(r.status=='UNKNOWN' for r in evaluated if r.rule_id.startswith('F1-')):
            raise UnknownData('主启动形态数据不完整，不能确认F2前置')
        return result(rule,conditions={'F1_hit':False},explanation='无有效F1命中，不独立得分。')
    hit=max(hits,key=lambda r:r.score)
    event_fields={'F1-N':('second_start_date','first_start_date'), 'F1-Y':('jump_date',)}
    day=next((hit.raw_values[k] for k in event_fields.get(hit.rule_id,('event_date',)) if hit.raw_values.get(k)),None)
    if day is None:
        raise UnknownData('F1缺事件日期，不能用当前日替代位置')
    d=ctx.bars.loc[ctx.bars.date<=__import__('pandas').Timestamp(day)]
    require(d,['close_adj'],60)
    high,raw=high_zone(d,p)
    features=indicators(d,p)
    distance=round(divide(d.close_adj.iloc[-1],features.M60.iloc[-1])-1,12)
    plat=bool(platform(d,p))
    q=p['F2']
    score=0 if high else q['scores'][0] if plat and 0<=distance<q['platform_distance_max'] else q['scores'][1] if abs(distance)<q['near_distance_max'] else q['scores'][2]
    return result(rule,score=score,raw={**raw,'event_date':day,'F1_rule':hit.rule_id,'dist_m60':distance},conditions={'platform':plat,'HIGH_ZONE':bool(high)},explanation=f'按F1事件日而非当前日判断位置，得{score}分。')


def price_shapes(d,p):
    require(d,['open_raw','high_raw','low_raw','close_raw','limit_up_price'],1)
    row=d.iloc[-1]; limit=float(row.limit_up_price); tol=p['GLOBAL']['near_limit_tol']; q=p['F1-O']
    final=bool(row.close_raw>=limit*(1-tol)); touch=bool(row.high_raw>=limit*(1-tol))
    opened=bool(row.low_raw<=limit*p['F1-T']['open_board_ratio'])
    near_all=all(abs(float(row[field])/limit-1)<=q['price_tolerance'] for field in ('open_raw','high_raw','close_raw'))
    one_line=near_all and (row.high_raw-row.low_raw)/limit<=q['one_line_range_max']
    one_t=near_all and row.low_raw<=limit*q['one_t_low_ratio']
    return {'final_limit':final,'touch_limit':touch,'opened_at_least_2pct':opened,'t_shape':final and touch and opened,
            'one_line':bool(one_line),'one_line_t':bool(one_t)}, {k:float(row[k]) for k in ['open_raw','high_raw','low_raw','close_raw','limit_up_price']}


def abnormal_trade(d,p):
    w=p['GLOBAL']['volume_window']; require(d,['volume','turnover_rate'],w+1)
    vr=divide(d.volume.iloc[-1],d.volume.iloc[-w-1:-1].mean()); turn=float(d.turnover_rate.iloc[-1]); q=p['R12']
    # Continuous tier threshold is left-closed in V1.3.
    abnormal_turn=turn>=q['turnover_threshold']; abnormal_volume=vr>=q['volume_threshold']
    return q['penalties'][int(abnormal_turn)+int(abnormal_volume)],{'volume_ratio_20':vr,'turnover_rate_pct':turn}, {'abnormal_turnover':abnormal_turn,'abnormal_volume':abnormal_volume}


def f1t(ctx,rule,p):
    shape,raw=price_shapes(ctx.bars,p)
    # Price recognition is independent of trading abnormalities; cancellation
    # is exclusively handled by R12 + the conflicts layer.
    return result(rule,score=p['F1-T']['scores'][1] if shape['t_shape'] else 0,raw={**raw,'event_date':str(ctx.bars.date.iloc[-1].date())},conditions=shape,
                  explanation='按收盘封停、最高价触停、最低价较涨停价至少低2%识别完整T板；不要求开盘涨停。异常成交由R12另评。')


def f1o(ctx,rule,p):
    shape,raw=price_shapes(ctx.bars,p); q=p['F1-O']; w=p['GLOBAL']['volume_window']
    if not (shape['one_line'] or shape['one_line_t']):
        return result(rule,raw=raw,conditions=shape,explanation='一字板及一字T价格结构均不成立。')
    high,position=high_zone(ctx.bars,p)
    if high: return result(rule,raw={**raw,**position},conditions={**shape,'HIGH_ZONE':True},explanation='高位不适用干净底部启动，得0分。')
    require(ctx.bars,['volume','turnover_rate'],w+1)
    reference=float(ctx.bars.volume.iloc[-w-1:-1].mean()); prior=float(ctx.bars.volume.iloc[-q['pre_days']-1:-1].mean())
    clean_pre=prior<=reference*q['one_word_pre_volume_ratio']; turn=float(ctx.bars.turnover_rate.iloc[-1])
    current_vr=divide(ctx.bars.volume.iloc[-1],reference); clean_turn=turn<=q['one_word_max_turnover_pct']
    abnormal,_,_=abnormal_trade(ctx.bars,p)
    score=q['scores'][3] if shape['one_line'] and clean_pre and clean_turn else q['scores'][2] if shape['one_line_t'] and clean_pre and clean_turn else q['scores'][1]
    raw.update(previous3_mean=prior,previous20_mean=reference,volume_ratio_20=current_vr,turnover_rate_pct=turn,event_date=str(ctx.bars.date.iloc[-1].date()))
    if abnormal: score=0
    return result(rule,score=score,raw=raw,conditions={**shape,'pre_volume_clean':clean_pre,'clean_turnover':clean_turn,'R12_abnormal':bool(abnormal)},explanation=f'前3日均量不超过前20日均量1.2倍={clean_pre}，换手不超过5%={clean_turn}；得{score}分。')


def r12(ctx,rule,p):
    shapes,raw=price_shapes(ctx.bars,p)
    candidate=shapes['t_shape'] or shapes['one_line'] or shapes['one_line_t']
    if not candidate:
        return result(rule,raw=raw,conditions={'applicable_pattern':False},applicable=False,explanation='无T板/一字板候选，R12前置明确不成立。')
    penalty,trade,conditions=abnormal_trade(ctx.bars,p)
    return result(rule,penalty=penalty,raw={**raw,**trade},conditions=conditions,applicable=True,explanation=f'T/一字候选的异常成交独立扣{penalty}分；对应正分由冲突层取消。')


def f3(ctx,rule,p):
    q=p['F3']; w=p['GLOBAL']['volume_window']; require(ctx.bars,['close_adj','high_adj','low_adj','volume','close_raw','limit_up_price'],w+q['search_days'])
    d=indicators(ctx.bars,p); events=[]; missing_high=False
    for j in reversed(range(len(d)-q['search_days'],len(d))):
        vr=divide(d.volume.iloc[j],d.volume.iloc[j-w:j].mean())
        near=bool(d.close_raw.iloc[j]>=d.limit_up_price.iloc[j]*(1-p['GLOBAL']['near_limit_tol']))
        if not near or vr>q['low_volume_limit_ratio20']: continue
        ret20=divide(d.close_adj.iloc[j],d.close_adj.iloc[j-20])-1
        try: high=ret20>=p['GLOBAL']['high_zone_ret20'] or high_zone(d,p,j)[0]
        except UnknownData: missing_high=True; continue
        if not high: continue
        ref=float(d.volume.iloc[max(0,j-q['rise_reference_days']+1):j+1].mean()); rows=[]; event=None
        for k in range(j+1,min(len(d),j+q['exchange_days_max']+2)):
            length=k-j-1
            if q['exchange_days_min']<=length<=q['exchange_days_max']:
                exchange=d.iloc[j+1:k]; ratio=divide(exchange.volume.mean(),ref)
                ret=divide(d.close_adj.iloc[k],d.close_adj.iloc[k-1])-1
                continuation=bool(d.close_adj.iloc[k]>exchange.high_adj.max() or (ret>=q['continuation_return_proxy'] and d.close_adj.iloc[k]>d.M5.iloc[k]))
                if ratio>=q['exchange_volume_vs_rise_min'] and continuation:
                    event={'status':'CONFIRMED','score':q['scores_by_days'][length],'L':length,'exchange_ratio':ratio,'event_date':str(d.date.iloc[k].date())}; break
            if k-j>q['exchange_days_max']:
                event={'status':'INVALIDATED','score':0,'reason':'EXPIRED'}; break
            rows.append({'date':str(d.date.iloc[k].date()),'low':float(d.low_adj.iloc[k]),'M5':float(d.M5.iloc[k]),'volume':float(d.volume.iloc[k])})
            if d.low_adj.iloc[k]<d.M5.iloc[k]:
                event={'status':'INVALIDATED','score':0,'reason':'M5_HARD_BREAK'}; break
        if event is None:
            ratio=divide(sum(r['volume'] for r in rows)/len(rows),ref) if rows else 0
            legal=len(rows)>=q['exchange_days_min'] and ratio>=q['exchange_volume_vs_rise_min']
            event={'status':'CANDIDATE','score':q['candidate_score'] if legal else 0,'L':len(rows),'exchange_ratio':ratio}
        event.update(first_start_date=str(d.date.iloc[j].date()),rise_volume_ref=ref,exchange_days=rows)
        events.append(event)
    if not events:
        if missing_high: raise UnknownData('低量涨停存在，但高位前置历史不足')
        return result(rule,raw={'searched_days':q['search_days']},conditions={'first_start':False},explanation='未找到高位低量涨停后的合法中继结构。')
    event=next((e for e in events if e['status']=='CONFIRMED'),events[0])
    return result(rule,event['status'],score=event['score'],raw=event,conditions={'m5_integrity':event.get('reason')!='M5_HARD_BREAK','continuation':event['status']=='CONFIRMED'},event_id='F3:'+event['first_start_date'],explanation=f'低量涨停后2~6日放量整理、盘中M5不破；状态{event["status"]}，得{event["score"]}分。')
