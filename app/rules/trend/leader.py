from app.rules.base import Context,require,indicators,result,UnknownData


def b3(ctx,rule,p):
    members=ctx.metadata.get('sector_bars'); target=ctx.metadata.get('stock_id'); q=p['B3']
    if members is None or target not in members or len(members)<q['minimum_constituents']:
        raise UnknownData('B3需要至少10只完整成分股日线和stock_id')
    cutoff=ctx.bars.date.iloc[-1]; dates=ctx.bars.date.tail(q['leader_lookback_days']).tolist(); earliest=None; leaders=[]; data={}
    for name,bars in members.items():
        d=Context(bars,as_of=str(cutoff)).prepared().bars
        require(d,['close_adj','low_adj','close_raw','limit_up_price'],q['leader_lookback_days']+4)
        if d.date.tail(len(dates)).tolist()!=dates: raise UnknownData('成分股窗口交易日期不一致')
        d=indicators(d,p); data[name]=d
        hits=d.loc[d.date.isin(dates)&(d.close_raw>=d.limit_up_price*(1-p['GLOBAL']['near_limit_tol']))]
        if hits.empty: continue
        first=hits.date.iloc[0]
        if earliest is None or first<earliest: earliest=first; leaders=[name]
        elif first==earliest: leaders.append(name)
    if earliest is None or target not in leaders:
        return result(rule,raw={'first_limit_day':str(earliest.date()) if earliest is not None else None,'leaders':leaders},conditions={'leader_candidate':False},explanation='目标股不属于最近窗口内最早封停组。')
    after=data[target].loc[data[target].date>earliest]; broken=bool((after.low_adj<after.M5).any())
    return result(rule,'INVALIDATED' if broken else 'PASS',score=0 if broken else q['scores'][1],raw={'first_limit_day':str(earliest.date()),'leaders':leaders,'lows':after.low_adj.tolist(),'M5':after.M5.tolist()},conditions={'leader_candidate':True,'m5_intact':not broken},explanation='最早封板组资格按后续每日日内最低价检查；盘中跌破M5立即失去领涨资格。')
