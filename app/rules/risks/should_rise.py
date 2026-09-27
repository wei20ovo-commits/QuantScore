"""R7 reads immutable earlier score snapshots; never recomputes their score."""
from dataclasses import dataclass,asdict
import hashlib,json,math
import pandas as pd
from app.rules.base import require,result,UnknownData,divide


@dataclass(frozen=True)
class ScoreSnapshot:
    signal_date: str
    close: float
    quant_score: float
    risk_level: str
    spec_version: str
    evidence_hash: str
    assumption_version: str = 'v1.3'
    data_contract_version: str = '1.4'

    def __post_init__(self):
        if not math.isfinite(self.close) or self.close<=0 or not 0<=self.quant_score<=100:
            raise ValueError('Invalid frozen score/price')
        if self.risk_level not in ('LOW','MEDIUM','HIGH') or not self.evidence_hash:
            raise ValueError('Invalid frozen risk/evidence')
        if pd.isna(pd.Timestamp(self.signal_date)): raise ValueError('Invalid signal date')

    @classmethod
    def freeze(cls,report,bars):
        if report.get('evaluation_date')!=str(bars.date.iloc[-1].date()):
            raise ValueError('Report evaluation date must match frozen bars')
        payload=json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False)
        return cls(str(bars.date.iloc[-1].date()),float(bars.close_adj.iloc[-1]),float(report['quant_score']),report['risk_level'],report['spec_version'],hashlib.sha256(payload.encode()).hexdigest())


def r7(ctx,rule,p):
    supplied=ctx.metadata.get('score_snapshots')
    if supplied is None: raise UnknownData('需要历史冻结评分快照；不得用未来行情重算信号日', 'AWAITING_FORWARD_CONFIRMATION' if ctx.metadata.get('provider') else 'DATA_INSUFFICIENT')
    q=p['R7']; outcomes=[]
    for snapshot in supplied:
        if not isinstance(snapshot,ScoreSnapshot): raise UnknownData('快照必须为冻结ScoreSnapshot对象','INVALID_SNAPSHOT')
        if pd.Timestamp(snapshot.signal_date)>ctx.bars.date.iloc[-1]: continue
        if snapshot.spec_version not in ('1.3','1.4'): raise UnknownData('快照版本不是兼容冻结规范V1.3/V1.4','INVALID_SNAPSHOT')
        signal=ctx.bars.loc[ctx.bars.date==pd.Timestamp(snapshot.signal_date)]
        if len(signal)!=1 or not math.isclose(float(signal.close_adj.iloc[0]),snapshot.close,rel_tol=1e-12,abs_tol=1e-12):
            raise UnknownData('冻结信号日价格与输入历史不一致；不能混用复权口径','INVALID_SNAPSHOT')
        if snapshot.quant_score<q['should_rise_score_threshold'] or snapshot.risk_level=='HIGH': continue
        raw=asdict(snapshot); subsequent=ctx.bars.loc[ctx.bars.date>pd.Timestamp(snapshot.signal_date)].head(q['should_rise_observation_days'])
        if len(subsequent)<q['should_rise_observation_days']:
            outcomes.append({'state':'UNKNOWN','raw':raw,'code':'AWAITING_FORWARD_CONFIRMATION'}); continue
        require(subsequent,['high_adj','close_adj'],q['should_rise_observation_days'])
        highs=subsequent.high_adj.tolist(); maxhigh=float(subsequent.high_adj.max()); threshold=snapshot.close*(1+q['should_rise_min_upside_pct'])
        max_close=divide(subsequent.close_adj.max(),snapshot.close)-1
        raw.update(forward_highs=highs,forward_closes=subsequent.close_adj.tolist(),threshold_price=threshold,max_close_return=max_close,max_high_return=divide(maxhigh,snapshot.close)-1,confirmed_on=str(subsequent.date.iloc[-1].date()))
        if maxhigh>=threshold:
            outcomes.append({'state':'INVALIDATED','penalty':0,'raw':raw}); continue
        penalty=q['penalties'][1 if max_close<=0 else 0]
        outcomes.append({'state':'PASS','penalty':penalty,'raw':raw})
    if not outcomes: return result(rule,raw={'snapshot_count':len(supplied)},conditions={'eligible_signal':False},applicable=False,explanation='冻结快照中没有QuantScore>=80且Risk Level非HIGH的历史信号。')
    outcomes.sort(key=lambda e:e['raw']['signal_date'],reverse=True)
    known=[e for e in outcomes if e['state']!='UNKNOWN']
    event=known[0] if known else outcomes[0]
    return result(rule,event['state'],penalty=event.get('penalty',0),raw=event['raw'],conditions={'eligible_signal':True,'three_completed_days':event.get('code')!='AWAITING_FORWARD_CONFIRMATION'},
                  reason_code=event.get('code'),event_id='R7:'+event['raw']['signal_date'],applicable=True,
                  explanation='冻结信号日评分；仅在随后3个完整交易日结束后判断最高价是否达到信号收盘价103%。等待期不得提前扣分或回写历史评分。')
