from app.engine.rule_engine import RuleEngine
from app.engine.conflicts import resolve
from app.engine.coverage import calculate


class ScoreEngine:
    def __init__(self,rule_engine=None):
        self.rule_engine=rule_engine or RuleEngine()

    def evaluate(self,context):
        output=self.aggregate(self.rule_engine.evaluate_all(context))
        from app.rules.base import UnknownData
        try:
            prepared=context.prepared()
            output['evaluation_date']=str(prepared.bars.date.iloc[-1].date()) if len(prepared.bars) else None
        except UnknownData:
            output['evaluation_date']=None
        return output

    def aggregate(self,results):
        p=self.rule_engine.parameters; q=p['SYSTEM']
        resolved=resolve(results)
        modules={category:min(cap,sum(r.score for r in resolved if r.category==category and r.rule_type=='POSITIVE' and r.score is not None))
                 for category,cap in q['category_caps'].items()}
        positive=min(q['positive_cap'],sum(modules.values()))
        penalty=sum(r.penalty for r in resolved if r.rule_type=='RISK' and r.penalty is not None)
        final=max(0,positive-penalty)
        by_id={r.rule_id:r for r in resolved}
        hard=any(r.conditions.get('hard_high') is True for r in resolved if r.rule_type=='RISK')
        if 'R3' in by_id and (by_id['R3'].penalty or 0)>=by_id['R3'].max_penalty:
            hard=True
        if 'R4' in by_id and by_id['R4'].status=='CONFIRMED' and any((by_id[rid].penalty or 0)>0 for rid in ('R1','R2') if rid in by_id):
            hard=True
        risk='HIGH' if hard or penalty>=q['risk_high'] else 'MEDIUM' if penalty>=q['risk_medium'] else 'LOW'
        coverage=calculate(resolved,p); c=coverage['positive_coverage']
        status='INSUFFICIENT' if c is None or c<q['coverage_partial'] else 'PARTIAL' if c<q['coverage_full'] else 'FULL'
        grade=None if status=='INSUFFICIENT' else next(label for floor,label in q['grades'] if final>=floor)
        return {'spec_version':'1.4','assumption_version':'v1.3','data_contract_version':'1.4','positive_score':positive,'risk_penalty':penalty,
                'final_score':final,'quant_score':final,'category_scores':modules,'risk_level':risk,
                'risk_level_scope':'OBSERVED_RULES_ONLY','hard_high_trigger':hard,'score_status':status,'match_level':grade,
                'sector_heat_score':None,'is_partial_result':any(r.status=='UNKNOWN' for r in resolved),**coverage,
                'top_positive_reasons':[r.explanation for r in sorted(resolved,key=lambda r:r.score or 0,reverse=True) if (r.score or 0)>0],
                'top_risk_reasons':[r.explanation for r in sorted(resolved,key=lambda r:r.penalty or 0,reverse=True) if (r.penalty or 0)>0],
                'exit_risk_alert':any(r.exit_risk_alert for r in resolved),
                'alerts':[{'rule_id':r.rule_id,'alert_type':r.alert_type,'text':r.alert_text} for r in resolved if r.exit_risk_alert],
                'rules':[r.to_dict() for r in resolved]}
