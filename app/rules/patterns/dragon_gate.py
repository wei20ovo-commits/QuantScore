from app.rules.base import require,indicators,result,UnknownData,divide
from app.rules.periods import peaks


def gate_at(d,j,p):
    side=p['GLOBAL']['local_peak_side']; points=peaks(d.high_adj.iloc[:j],side)
    q=p['F1-Y']; candidates=[]
    for b in reversed(points):
        for a in reversed([i for i in points if i<b]):
            resistance=float(d.high_adj.iloc[a]+(d.high_adj.iloc[b]-d.high_adj.iloc[a])/(b-a)*(j-a))
            ma=float(d.M60.iloc[j]); distance=abs(resistance-ma)/ma
            if round(distance,12)<=q['dragon_gate_confluence_pct']:
                return {'P1_date':str(d.date.iloc[a].date()),'P2_date':str(d.date.iloc[b].date()),
                                   'P1_high':float(d.high_adj.iloc[a]),'P2_high':float(d.high_adj.iloc[b]),
                                   'resistance_price':resistance,'m60_price':ma,'confluence_distance':distance}
    return None


def f1y(ctx,rule,p):
    d=ctx.bars; q=p['F1-Y']; w=p['GLOBAL']['volume_window']
    require(d,['open_adj','high_adj','low_adj','close_adj'],len(d))
    require(d,['close_adj'],60)
    d=indicators(d,p); events=[]
    for j in reversed(range(max(59,len(d)-q['search_days']),len(d))):
        gate=gate_at(d,j,p)
        if not gate or not d.close_adj.iloc[j]>max(gate['resistance_price'],gate['m60_price']): continue
        raw={**gate,'jump_date':str(d.date.iloc[j].date()),'jump_close':float(d.close_adj.iloc[j])}
        k=j+1
        if k>=len(d):
            events.append({'status':'CANDIDATE','score':0,'raw':raw,'conditions':{'jump':True,'dragon_gate_breakout':True,'fake_fall':False}}); continue
        require(d.iloc[:k+1],['open_raw','close_raw','limit_up_price','limit_down_price','open_adj','close_adj','volume'],1)
        near_up=bool(d.open_raw.iloc[k]>=d.limit_up_price.iloc[k]*q['open_near_limit_up_ratio'])
        near_down=bool(d.close_raw.iloc[k]<=d.limit_down_price.iloc[k]*q['close_near_limit_down_ratio'])
        body_drop=1-divide(d.close_raw.iloc[k],d.open_raw.iloc[k])
        limit_span=1-divide(d.limit_down_price.iloc[k],d.limit_up_price.iloc[k])
        large=body_drop>=q['large_drop_body_min'] or limit_span<q['large_drop_body_min']
        require(d.iloc[:k+1],['volume'],w+1)
        fall_vr=divide(d.volume.iloc[k],d.volume.iloc[k-w:k].mean())
        huge=fall_vr>=q['huge_volume_ratio20'] or d.volume.iloc[k]>=d.volume.iloc[j]*q['huge_volume_vs_breakout']
        signature=near_up and near_down and large and huge
        if not signature:
            events.append({'status':'FAIL','score':0,'raw':raw,'conditions':{'jump':True,'dragon_gate_breakout':True,'fake_fall':False}})
            continue
        recovery_line=float(d.close_adj.iloc[k]+q['recovery_body_ratio']*(d.open_adj.iloc[k]-d.close_adj.iloc[k]))
        post=d.iloc[k+1:k+q['recovery_days_max']+1]
        recovered=(post.close_adj>post.M5)&(post.close_adj>=recovery_line)
        state='CONFIRMED' if recovered.any() else 'INVALIDATED' if len(post)>=q['recovery_days_max'] else 'CANDIDATE'
        raw.update(fake_fall_date=str(d.date.iloc[k].date()),body_drop=body_drop,fall_volume_ratio=fall_vr,fall_volume=float(d.volume.iloc[k]),
                   recovery_line=recovery_line,forward_closes=post.close_adj.tolist(),forward_M5=post.M5.tolist())
        events.append({'status':state,'score':q['scores'][1] if state=='CONFIRMED' else 0,'raw':raw,
                       'conditions':{'jump':True,'dragon_gate_breakout':True,'confluence':True,'near_limit_open':near_up,'near_down_close':near_down,'large_drop':large,'huge_volume':bool(huge),'fake_fall':True,'recovered':bool(recovered.any())}})
    if not events:
        return result(rule,raw={'searched_days':min(q['search_days'],len(d))},conditions={'dragon_gate_breakout':False,'dragon_gate_fake_fall':False},explanation='未发现已确认压力线与M60共同区后的单日巨量假摔完整签名。')
    event=next((e for e in events if e['status']=='CONFIRMED'),events[0])
    return result(rule,event['status'],score=event['score'],raw=event['raw'],conditions=event['conditions'],event_id='F1-Y:'+event['raw']['jump_date'],explanation=f'压力线与M60共同区、收盘同时越过两线、紧随次日近涨停开/近跌停收巨量、随后最多3日恢复；状态{event["status"]}，得{event["score"]}分。')
