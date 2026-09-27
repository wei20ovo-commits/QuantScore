"""V1.3 nearest legal complete N structure, with irreversible M5 invalidation."""
from app.rules.base import require, indicators, result, UnknownData, divide


def detect_n(ctx,p):
    q=p['F1-N']; w=p['GLOBAL']['volume_window']; days=q['search_days']
    require(ctx.bars,['close_adj','high_adj','low_adj','volume','close_raw','limit_up_price'],w+days)
    d=indicators(ctx.bars,p); starts=[]
    for j in range(len(d)-days,len(d)):
        near=bool(d.close_raw.iloc[j]>=d.limit_up_price.iloc[j]*(1-p['GLOBAL']['near_limit_tol']))
        ret=divide(d.close_adj.iloc[j],d.close_adj.iloc[j-1])-1
        vr=divide(d.volume.iloc[j],d.volume.iloc[j-w:j].mean())
        if near or (ret>=q['first_return'] and vr>=q['volume_min']):
            starts.append(j)
    # A second launch may itself qualify as first_start. Explicit external event
    # identity disambiguates only the start date, never supplies a PASS decision.
    supplied=ctx.metadata.get('n_first_start_date')
    if supplied is not None:
        starts=[j for j in starts if str(d.date.iloc[j].date())==str(supplied)]
        if not starts:
            raise UnknownData('指定N板首次启动日未通过规范first_start条件', 'INVALID_EVENT')
    if not starts:
        return {'status':'FAIL','score':0,'raw':{'first_start_dates':[]},'conditions':{'first_start':False},'applicable':False}
    inspected=[_inspect_n(d,j,p) for j in reversed(starts)]
    priority=['CONFIRMED','CANDIDATE','INVALIDATED','UNKNOWN','FAIL']
    selected=next(e for state in priority for e in inspected if e['status']==state)
    selected['raw']['selection_candidates']=[{'first_start_date':e['raw']['first_start_date'],'status':e['status']} for e in inspected]
    return selected


def _inspect_n(d,j,p):
    q=p['F1-N']; w=p['GLOBAL']['volume_window']
    start_date=str(d.date.iloc[j].date()); rows=[]
    raw={'first_start_date':start_date,'exchange_days':rows,'first_close':float(d.close_adj.iloc[j]),'first_volume':float(d.volume.iloc[j])}
    event_id='N:'+start_date
    for k in range(j+1,min(len(d),j+q['exchange_days_max']+2)):
        length=k-j-1
        if q['exchange_days_min']<=length<=q['exchange_days_max']:
            exchange=d.iloc[j+1:k]; ceiling=float(exchange.high_adj.max())
            vr=divide(d.volume.iloc[k],d.volume.iloc[k-w:k].mean())
            near=bool(d.close_raw.iloc[k]>=d.limit_up_price.iloc[k]*(1-p['GLOBAL']['near_limit_tol']))
            second=bool(d.close_adj.iloc[k]>ceiling*(1+q['breakout_margin']) and (vr>=q['volume_min'] or near))
            if second:
                raw.update({'second_start_date':str(d.date.iloc[k].date()),'exchange_high':ceiling,'second_close':float(d.close_adj.iloc[k]),'second_volume_ratio':vr})
                return {'status':'CONFIRMED','score':q['scores'][2],'raw':raw,'conditions':{'first_start':True,'m5_integrity':True,'second_start':True},'event_id':event_id,'applicable':True}
        if k-j>q['exchange_days_max']:
            return {'status':'INVALIDATED','score':0,'raw':raw,'conditions':{'expired':True},'event_id':event_id,'reason_code':'EXPIRED','applicable':False}
        low=float(d.low_adj.iloc[k]); ma=float(d.M5.iloc[k]); broken=low<ma
        rows.append({'date':str(d.date.iloc[k].date()),'day_no':k-j,'low':low,'M5':ma,'close':float(d.close_adj.iloc[k]),'hard_break':broken})
        if broken:
            raw['break']=rows[-1]
            return {'status':'INVALIDATED','score':0,'raw':raw,'conditions':{'first_start':True,'hard_break':True,'m5_integrity':False},'event_id':event_id,'applicable':True}
    if len(rows)<q['exchange_days_min']:
        return {'status':'UNKNOWN','score':None,'raw':raw,'conditions':{'minimum_exchange_days':False},'event_id':event_id,'reason_code':'DATA_INSUFFICIENT','applicable':True}
    return {'status':'CANDIDATE','score':q['scores'][1],'raw':raw,'conditions':{'first_start':True,'m5_integrity':True,'second_start':False},'event_id':event_id,'applicable':True}


def f1n(ctx,rule,p):
    e=detect_n(ctx,p)
    return result(rule,e['status'],score=e['score'],raw=e['raw'],conditions=e['conditions'],event_id=e.get('event_id'),reason_code=e.get('reason_code'),applicable=e['applicable'],explanation=f'N板状态={e["status"]}；换手期按逐日low与当日M5判断，盘中破位不因收盘收回恢复。多起点由近到远，优先最近完整合法结构；单个失败候选不阻断更早合法结构。')


def r11(ctx,rule,p):
    e=detect_n(ctx,p)
    if e['status']=='UNKNOWN':
        return result(rule,'UNKNOWN',raw=e['raw'],conditions=e['conditions'],event_id=e.get('event_id'),reason_code=e.get('reason_code'),applicable=e['applicable'],explanation='N板事件识别未完成，无法可靠确认换手期风险。')
    broken=e['conditions'].get('hard_break',False)
    return result(rule,penalty=p['R11']['penalty'] if broken else 0,raw=e['raw'],conditions={'hard_break':broken},event_id=e.get('event_id'),applicable=e['applicable'],explanation='N板换手盘中跌破M5，即使收盘收回仍先取消F1-N正分，再扣8分。' if broken else '可判断的N板事件未出现换手期M5硬破位，扣0分。')
