from app.rules.base import Context, UnknownData, load_config, result
from app.rules.trend.basic import a1,a2,a3,c1,c2,c3,c4
from app.rules.volume.basic import d1,d2,d3,d4,d5
from app.rules.risks.basic import r1,r2,r3,r5,r9
from app.rules.patterns.double_top import r4
from app.rules.patterns.n_board import f1n,r11
from app.rules.trend.platform_belt import c5,c6,r8
from app.rules.patterns.accumulation import e1,e2,e3
from app.rules.patterns.launch import f1t,f1o,f1x,f2,f3,r12
from app.rules.patterns.dragon_gate import f1y
from app.rules.risks.should_rise import r7
from app.rules.trend.leader import b3
from app.rules.trend.industry import b1,b2

EVALUATORS={'D2':d2,'F1-X':f1x,'F2':f2,'R3':r3,'R5':r5,'A1':a1,'A2':a2,'A3':a3,'C1':c1,'C2':c2,'C3':c3,'C4':c4,
            'D1':d1,'D3':d3,'D4':d4,'D5':d5,'R1':r1,'R2':r2,'R4':r4,'R9':r9,'R11':r11,'F1-N':f1n,
            'B1':b1,'B2':b2,'B3':b3,'C5':c5,'C6':c6,'E1':e1,'E2':e2,'E3':e3,'F1-T':f1t,'F1-O':f1o,'F1-Y':f1y,'F3':f3,'R7':r7,'R8':r8,'R12':r12}


class RuleEngine:
    def __init__(self,registry=None,parameters=None):
        default_registry,default_parameters=load_config()
        self.registry=default_registry if registry is None else registry
        self.parameters=default_parameters if parameters is None else parameters

    def evaluate(self,rule_id,context:Context):
        rule=self.registry[rule_id]
        if rule['source_type']=='MANUAL':
            return result(rule,'UNKNOWN',reason_code='MANUAL_REQUIRED',data_provenance=context.metadata.get('data_provenance',[]),explanation='人工规则未提交人工证据，自动执行不能判PASS。')
        if rule_id not in EVALUATORS:
            return result(rule,'UNKNOWN',reason_code='NOT_IMPLEMENTED',raw={'required_fields':rule['required_fields']},data_provenance=context.metadata.get('data_provenance',[]),explanation='当前阶段未实现此规则；保留规范定义与接口，不以简化算法代替。')
        try:
            prepared=context.prepared()
            if rule_id.startswith('A') and prepared.benchmark is not None and len(prepared.benchmark) and len(prepared.bars) and prepared.benchmark.date.iloc[-1]!=prepared.bars.date.iloc[-1]:
                raise UnknownData('基准指数缺少评价日行情，不能使用陈旧数据', 'DATA_INSUFFICIENT')
            output=EVALUATORS[rule_id](prepared,rule,self.parameters)
        except UnknownData as exc:
            output=result(rule,'UNKNOWN',raw=exc.raw,reason_code=exc.code,explanation=str(exc))
        if not output.raw_values:
            output.raw_values = {'observed_rows':len(context.bars)}
        output.data_provenance = context.metadata.get('data_provenance',[])
        output.to_dict()
        return output

    def evaluate_all(self,context,include_sector=False):
        return [self.evaluate(rid,context) for rid,rule in self.registry.items()
                if include_sector or rule['rule_type']!='SECTOR']
