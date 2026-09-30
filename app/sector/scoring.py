"""Deterministic scoring only. No provider, network, cache or stock-engine calls."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import math
import yaml
from .models import SectorRuleInput, SectorRuleResult, SectorHeatResult

class InvalidInput(ValueError):
    pass

def number(raw, key):
    value=raw[key]
    if isinstance(value,bool) or not math.isfinite(float(value)):
        raise InvalidInput(f'{key}: invalid finite number')
    return Decimal(str(value))

def count(raw,key):
    n=number(raw,key)
    if n<0 or n!=int(n):raise InvalidInput(f'{key}: invalid count')
    return int(n)

def consistent(actual,expected,label):
    # Serialization/float arithmetic tolerance only, never a trading threshold.
    if not math.isclose(float(actual),float(expected),rel_tol=1e-10,abs_tol=1e-12):
        raise InvalidInput(f'{label}: inconsistent derived value')

class SectorHeatEngine:
    def __init__(self, config_path=None):
        path=config_path or Path(__file__).resolve().parents[2]/'config/sector_heat.yaml'
        self.config=yaml.safe_load(Path(path).read_text(encoding='utf-8'))
        self.rules=self.config['rules']

    def score_rule(self, rule_id, data: SectorRuleInput, trade_date: str):
        cfg=self.rules[rule_id];raw=deepcopy(data.raw_inputs)
        def unknown(reason, status='DATA_INCONSISTENT'):
            return SectorRuleResult(rule_id,cfg['name'],raw,None,None,cfg['max_score'],'UNKNOWN',status,
                                    f'{cfg["name"]}暂不可评分：{reason}；缺项不计为0分。',data.source_date,reason)
        if str(data.data_status)!='VALID':return unknown(str(data.data_status),str(data.data_status))
        if data.source_date!=trade_date:return unknown('SOURCE_DATE_MISMATCH','DATA_STALE')
        try:
            if 'min_coverage' in cfg:
                coverage=number(raw,'coverage')
                if not 0<=coverage<=1:raise InvalidInput('coverage outside [0,1]')
                if coverage<Decimal(str(cfg['min_coverage'])):return unknown('INSUFFICIENT_COVERAGE')
            if rule_id in ('S1','S2'):
                period='1d' if rule_id=='S1' else '5d'
                sector=number(raw,'sector_return_'+period);benchmark=number(raw,'benchmark_return_'+period)
                value=number(raw,'sector_excess_return_'+period)
                consistent(value,sector-benchmark,'excess')
                if rule_id=='S2' and count(raw,'return_intervals')!=cfg['days']:return unknown('INCOMPLETE_FIVE_DAY_WINDOW')
                detail=f'行业{period}收益={sector:.6%}，上证指数收益={benchmark:.6%}，超额={value:.6%}'
            elif rule_id in ('S3','S4','S7'):
                valid_key={'S3':'valid_constituents','S4':'valid_limit_count','S7':'valid_return_count'}[rule_id]
                expected_key='expected_constituents' if rule_id=='S3' else 'expected_count'
                valid=count(raw,valid_key);expected=count(raw,expected_key)
                if not 0<valid<=expected:raise InvalidInput('invalid constituent counts')
                if valid<cfg['min_members']:return unknown('INSUFFICIENT_MEMBERS')
                if rule_id=='S3':
                    n=count(raw,'advancing_constituents');value=number(raw,'breadth')
                    consistent(number(raw,'coverage'),Decimal(valid)/expected,'coverage')
                    denominator=valid
                elif rule_id=='S7':
                    n=count(raw,'strong_count');value=number(raw,'strong_ratio');denominator=expected
                else:
                    n=count(raw,'limit_up_count');value=number(raw,'limit_up_ratio');denominator=valid
                    details=raw['limit_details']
                    if len(details)!=expected or len({r['symbol'] for r in details})!=expected:raise InvalidInput('limit constituents missing/duplicate')
                    usable=[r for r in details if r['status']=='VALID']
                    if len(usable)!=valid:raise InvalidInput('valid limit count differs from evidence')
                    for r in usable:
                        if r['date']!=trade_date or not r.get('rule_source'):raise InvalidInput('unverified limit source/date')
                        up=number(r,'calculated_limit_up');close=number(r,'actual_close')
                        if up<=0 or close<=0:raise InvalidInput('invalid limit/close price')
                        if not isinstance(r['closed_at_limit_up'],bool) or r['closed_at_limit_up']!=(close>=up):raise InvalidInput('close-based limit status mismatch')
                    if n!=sum(r['closed_at_limit_up'] for r in usable):raise InvalidInput('limit count differs from close evidence')
                if n>valid:raise InvalidInput('numerator exceeds valid members')
                consistent(value,Decimal(n)/denominator,'constituent ratio')
                detail=f'计数={n}，有效成分={valid}，预期成分={expected}，比例={value:.6%}'
            elif rule_id=='S5':
                today=number(raw,'sector_amount_today');mean=number(raw,'sector_amount_prior_20d_mean');value=number(raw,'amount_ratio')
                daily=raw['daily_amounts']
                if len(daily)!=cfg['days']+1 or len({r['date'] for r in daily})!=len(daily):raise InvalidInput('incomplete/duplicate 20-day history')
                if sorted(r['date'] for r in daily)!=[r['date'] for r in daily] or daily[-1]['date']!=trade_date:raise InvalidInput('amount dates not aligned')
                for r in daily:
                    if r['status']!='VALID' or number(r,'coverage')<Decimal(str(cfg['min_coverage'])):raise InvalidInput('amount history incomplete')
                    if number(r,'sector_amount')<0:raise InvalidInput('negative amount')
                if today<0 or mean<=0:raise InvalidInput('invalid amount denominator')
                consistent(today,number(daily[-1],'sector_amount'),'today amount')
                consistent(mean,sum(number(r,'sector_amount') for r in daily[:-1])/cfg['days'],'prior20 mean')
                consistent(value,today/mean,'amount ratio')
                detail=f'当日成交额={today}，前20交易日均额={mean}，比值={value:.6f}'
            else:
                daily=raw['daily_comparisons'];days=raw['expected_trade_dates']
                if len(days)!=cfg['days'] or len(set(days))!=len(days) or days!=sorted(days) or days[-1]!=trade_date:raise InvalidInput('invalid five-session calendar')
                if [r['date'] for r in daily]!=days:raise InvalidInput('missing/duplicate comparison day')
                wins=0
                for r in daily:
                    if r['status']!='VALID' or number(r,'coverage')<Decimal(str(cfg['min_coverage'])):raise InvalidInput('daily data incomplete')
                    win=number(r,'sector_return')>number(r,'benchmark_return')
                    if not isinstance(r['sector_win'],bool) or r['sector_win']!=win:raise InvalidInput('daily comparison mismatch')
                    wins+=int(win)
                if count(raw,'win_days')!=wins:raise InvalidInput('win count differs from daily evidence')
                value=Decimal(wins);detail=f'最近5个真实交易日逐日胜出={wins}天'
            if rule_id=='S4':
                band=next(b for b in cfg['bands'] if n>=b['count'] and value>=Decimal(str(b['ratio'])))
                score=band['score'];label=f'count>={band["count"]}, ratio>={band["ratio"]}'
            elif rule_id=='S6':score=cfg['scores'][int(value)];label=f'win_days={int(value)}'
            else:
                score=0;label=f'x<{cfg["bands"][0][0]}'
                for i,(lower,points) in enumerate(cfg['bands']):
                    if value>=Decimal(str(lower)):
                        score=points;upper=cfg['bands'][i+1][0] if i+1<len(cfg['bands']) else '+inf';label=f'[{lower},{upper})'
            status='PASS' if score==cfg['max_score'] else ('PARTIAL' if score else 'FAIL')
            return SectorRuleResult(rule_id,cfg['name'],raw,label,score,cfg['max_score'],status,'VALID',
                f'{detail}；落入{label}，因此{rule_id}得{score}/{cfg["max_score"]}分（V1工程阈值）。',data.source_date)
        except (KeyError,TypeError,ValueError,ArithmeticError) as exc:
            return unknown(str(exc))

    def evaluate(self,sector_id,sector_name,trade_date,inputs,provenance):
        results={rid.lower():self.score_rule(rid,inputs.get(rid,SectorRuleInput({},trade_date,'DATA_ERROR')),trade_date) for rid in self.rules}
        scored=[r for r in results.values() if r.score is not None]
        available=sum(r.score for r in scored);maximum=sum(r.max_score for r in results.values());am=sum(r.max_score for r in scored)
        complete=len(scored)==len(self.rules)
        return SectorHeatResult(sector_id,sector_name,trade_date,**results,total_score=available if complete else None,max_score=maximum,
            available_score=available,available_max_score=am,score_coverage=am/maximum,overall_status='VALID' if complete else 'DATA_INCOMPLETE',provenance=deepcopy(provenance))
