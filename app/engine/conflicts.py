"""Pure, auditable resolution; input RuleResults are never modified."""
from copy import deepcopy
from app.models.schemas import Status


def resolve(results):
    unique={}
    for item in results:
        r=deepcopy(item)
        if r.rule_id in unique:
            previous=unique[r.rule_id]
            if previous.to_dict()!=r.to_dict():
                raise ValueError(f'Conflicting duplicate result for {r.rule_id}; evaluate one as-of snapshot')
            continue
        unique[r.rule_id]=r
    def cancel(rid,reason,status=None):
        target=unique.get(rid)
        if target is not None and target.score is not None:
            target.adjustments.append({'reason':reason,'previous_score':target.score,'effective_score':0})
            target.score=0
            if status: target.status=Status(status)
            target.explanation+=' 冲突处理：'+reason+'；正向分清零。'
    cancellations={'R11':['F1-N','D2'],'R12':['F1-T','F1-O'],'R3':['F1-T','F1-O'],'R10':['E4','E5'],'R8':['D2']}
    for risk,targets in cancellations.items():
        r=unique.get(risk)
        if r and r.penalty is not None and r.penalty>0:
            for rid in targets:
                cancel(rid,f'{risk}否定正向条件','INVALIDATED')
    r8=unique.get('R8'); c6=unique.get('C6')
    if r8 and c6 and (r8.penalty or 0)>0 and c6.score is not None:
        # Never erase intact weekly/monthly points on a daily-only break.
        components=c6.raw_values.get('timeframe_scores')
        broken=r8.conditions.get('broken_timeframes')
        if components is None or broken is None:
            c6.status=Status.UNKNOWN; c6.score=c6.penalty=None; c6.reason_code='MISSING_CONFLICT_DETAIL'
            c6.explanation+=' 缺少分周期安全带明细，不能决定应取消的分值。'
        else:
            prior=c6.score
            c6.score=sum(value for tf,value in components.items() if tf not in broken)
            c6.adjustments.append({'reason':'R8分周期取消','previous_score':prior,'effective_score':c6.score})
    f1=[r for rid,r in unique.items() if rid.startswith('F1-') and r.score is not None and r.score>0]
    f3=unique.get('F3')
    if f3 and (f3.score or 0)>0:
        # Cross-stage relation requires actual event dates, not just rule names.
        day=f3.raw_values.get('event_date')
        for item in f1:
            if day is not None and item.raw_values.get('event_date')==day:
                cancel(item.rule_id,'F3同日不得再次作为F1启动计分')
        f1=[r for r in f1 if (r.score or 0)>0]
    if f1:
        winner=max(f1,key=lambda r:r.score)
        for item in f1:
            if item is not winner: cancel(item.rule_id,f'F1互斥，只保留{winner.rule_id}最高分')
    else:
        cancel('F2','无有效F1，F2不能独立得分')
    return list(unique.values())
