"""V1.3 coverage measures reliability of judgment, not awarded points."""
from collections import Counter

def calculate(results,parameters):
    unique={r.rule_id:r for r in results}
    positives=[r for r in unique.values() if r.rule_type=='POSITIVE']
    risks=[r for r in unique.values() if r.rule_type=='RISK']
    def judged(r): return r.status!='UNKNOWN' and r.code_status!='NOT_IMPLEMENTED'
    weights={}
    for category,cap in parameters['SYSTEM']['category_caps'].items():
        group=[r for r in positives if r.category==category and judged(r)]
        if category=='F':
            f1=max((r.max_score for r in group if r.rule_id.startswith('F1-')),default=0)
            weight=min(f1,parameters['SYSTEM']['f1_coverage_cap'])+sum(r.max_score for r in group if not r.rule_id.startswith('F1-'))
        else: weight=sum(r.max_score for r in group)
        weights[category]=min(cap,weight)
    weight=sum(weights.values()); fraction=weight/parameters['SYSTEM']['positive_cap']
    breakdown={}
    for label,group in [('positive',positives),('risk',risks)]:
        breakdown[label]={'successful_judgment':sum(judged(r) for r in group),
            'data_insufficient':sum(r.reason_code in ('DATA_INSUFFICIENT','INVALID_DATA','ADJUSTMENT_UNVERIFIED','AWAITING_PERIOD_CLOSE','AWAITING_FORWARD_CONFIRMATION') for r in group),
            'manual':sum(r.source_type=='MANUAL' for r in group),
            'unknown':sum(r.status=='UNKNOWN' for r in group),
            'not_implemented':sum(r.code_status=='NOT_IMPLEMENTED' for r in group),
            'partial_implementation':sum(r.code_status=='PARTIAL' for r in group),
            'status_counts':dict(Counter(str(r.status) for r in group))}
    known=sum(judged(r) for r in risks); denominator=len(risks)
    risk_coverage=known/denominator if denominator else parameters['SYSTEM']['risk_empty_coverage']
    return {'positive_coverage':fraction,'coverage':100*fraction,'positive_successful_max_score':weight,
            'positive_denominator':parameters['SYSTEM']['positive_cap'],'category_coverage_weights':weights,
            'risk_coverage':risk_coverage,'risk_coverage_lower_bound':risk_coverage,'risk_coverage_upper_bound':risk_coverage,
            'risk_applicable_count':denominator,'risk_unknown_applicability_count':sum(r.applicable is None for r in risks),
            'risk_judged_count':known,'empty_execution_set':not risks,'breakdown':breakdown,
            'coverage_note':'V1.3：全部确定状态计入；F1及类别封顶；风险分母包含前置未触发、缺数据和未实现规则。','ambiguity':None}

