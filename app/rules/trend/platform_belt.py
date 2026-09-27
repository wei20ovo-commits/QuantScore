from app.rules.base import require,indicators,result,UnknownData,divide
from app.rules.periods import completed_periods,close_troughs


def platform(df,p):
    q=p['C5']; minimum=q['minimum_samples']
    require(df,['close_adj','high_adj','low_adj'],60+minimum-1)
    d=indicators(df,p); best=None
    maximum=min(q['search_days_max'],len(d)-59)
    for length in range(minimum,maximum+1):
        segment=d.tail(length)
        if (segment.close_adj<segment.M60).any(): break
        distance=segment.close_adj/segment.M60-1
        fraction=float(((distance>=0)&(distance.round(12)<=q['m60_platform_max_distance_pct'])).mean())
        if fraction>=q['near_fraction_min']:
            best={'length':length,'start_date':str(segment.date.iloc[0].date()),'end_date':str(segment.date.iloc[-1].date()),
                  'near_fraction':fraction,'platform_high':float(segment.high_adj.max()),'closes':segment.close_adj.tolist(),
                  'M60':segment.M60.tolist(),'distances':distance.tolist()}
    return best


def c5(ctx,rule,p):
    evidence=platform(ctx.bars,p)
    d=indicators(ctx.bars,p); minimum=p['C5']['minimum_samples']
    below=d.close_adj<d.M60; breaks=d.index[below].tolist()
    last_break=breaks[-1] if breaks else None
    new_start=last_break+1 if last_break is not None else 59
    continuous=len(d)-new_start
    previous=None
    if last_break is not None:
        break_start=last_break
        while break_start>0 and below.iloc[break_start-1]: break_start-=1
        if break_start>=60+minimum-1:
            previous=platform(d.iloc[:break_start],p)
    state='PASS' if evidence else 'INVALIDATED' if previous else 'FAIL'
    raw=evidence.copy() if evidence else {'closes':d.close_adj.tail(minimum).tolist(),'M60':d.M60.tail(minimum).tolist()}
    raw.update(last_break_date=None if last_break is None else str(d.date.iloc[last_break].date()),
               previous_platform=previous,previous_platform_status='INVALIDATED' if previous else None,
               new_segment_start_date=str(d.date.iloc[new_start].date()) if new_start<len(d) else None,
               consecutive_days=continuous)
    return result(rule,state,score=p['C5']['scores'][1] if evidence else 0,raw=raw,
                  conditions={'all_closes_ge_M60':bool((d.close_adj.tail(minimum)>=d.M60.tail(minimum)).all()),'platform_complete':bool(evidence)},
                  explanation='至少5日且全部收盘>=M60，至少80%日距离<=8%；跌破立即终止旧平台并取消正分；收复仅归C4，新C5从收复日起重新累计5日，不设置量能条件。')


def belts(ctx,p):
    output={}; side=p['GLOBAL']['confirmed_close_trough_side']
    for tf,window in [('D',p['C6']['search_days']),('W',p['C6']['search_weeks']),('M',p['C6']['search_months'])]:
        try:
            d=completed_periods(ctx,tf).tail(window).reset_index(drop=True)
            require(d,['close_adj'],2*side+3)
            points=close_troughs(d.close_adj,side)
            if len(points)<2:
                output[tf]={'status':'FAIL','reason':'NO_TWO_CONFIRMED_TROUGHS','score':0,'trough_indices':points}; continue
            i,j=points[-2:]; c1=float(d.close_adj.iloc[i]); c2=float(d.close_adj.iloc[j])
            base={'T1':{'date':str(d.date.iloc[i].date()),'close':c1},'T2':{'date':str(d.date.iloc[j].date()),'close':c2},'evaluation_date':str(d.date.iloc[-1].date())}
            if c2<=c1:
                output[tf]={**base,'status':'FAIL','reason':'NOT_RISING','score':0}; continue
            slope=(c2-c1)/(j-i); support=c1+slope*(len(d)-1-i)
            # Only test times at which T2 was already confirmed.
            breaks=[k for k in range(j+side,len(d)) if d.close_adj.iloc[k]<c1+slope*(k-i)]
            broken=bool(breaks)
            output[tf]={**base,'status':'INVALIDATED' if broken else 'CONFIRMED','score':0 if broken else p['C6']['scores_per_tf'],
                        'support':float(support),'close':float(d.close_adj.iloc[-1]),'slope':slope,
                        'break_date':str(d.date.iloc[breaks[0]].date()) if broken else None,'source':'CLOSE_ONLY'}
        except UnknownData as exc:
            output[tf]={'status':'UNKNOWN','reason':str(exc),'score':None}
    return output


def c6(ctx,rule,p):
    tf=belts(ctx,p); known=[v for v in tf.values() if v['status']!='UNKNOWN']
    score=sum(v['score'] or 0 for v in tf.values())
    state='UNKNOWN' if not known else 'PARTIAL' if len(known)<len(tf) or 0<score<rule['max_score'] else 'PASS' if score else 'INVALIDATED' if any(v['status']=='INVALIDATED' for v in known) else 'FAIL'
    return result(rule,state,score=score,raw={'timeframes':tf,'timeframe_scores':{k:v['score'] or 0 for k,v in tf.items()}},
                  conditions={'close_only':True,'broken_timeframes':[k for k,v in tf.items() if v['status']=='INVALIDATED']},
                  reason_code='DATA_INSUFFICIENT' if len(known)<len(tf) else None,explanation=f'日/周/月分别取最近两个已确认收盘波谷；仅完整周期收盘可破位；得{score}分，分周期状态见明细。')


def r8(ctx,rule,p):
    tf=belts(ctx,p); known=[v for v in tf.values() if v['status']!='UNKNOWN']
    broken=[k for k,v in tf.items() if v['status']=='INVALIDATED']
    penalty=max((p['R8']['penalties'][k] for k in broken),default=0)
    state='UNKNOWN' if not known else 'PARTIAL' if len(known)<len(tf) else 'PASS' if penalty else 'FAIL'
    return result(rule,state,penalty=penalty,raw={'timeframes':tf},conditions={'broken_timeframes':broken,'low_used_for_break':False},applicable=True,
                  reason_code='DATA_INSUFFICIENT' if len(known)<len(tf) else None,explanation=f'仅按已完成周期收盘判破位；破位周期{broken}，多个周期只取最高扣分{penalty}。')
