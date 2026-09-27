"""Attach implementation contracts to the faithful rule extraction."""
from pathlib import Path
import re
import yaml
from app.engine.rule_engine import EVALUATORS
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'config/scoring_rules.yaml'
registry=yaml.safe_load(path.read_text(encoding='utf-8'))
params_path=ROOT/'config/parameters.yaml'
params=yaml.safe_load(params_path.read_text(encoding='utf-8'))
for rule in registry['rules']:
    rid=rule['rule_id']
    if rid in EVALUATORS:
        function=EVALUATORS[rid]
        rule['evaluator']=function.__module__+':'+function.__name__
        rule['code_status']='IMPLEMENTED'
    # Keep all unimplemented thresholds accessible by rule, without pretending
    # prose predicates are executable. Actual handlers use numeric parameters.
    params.setdefault(rid,{})
    params[rid]['spec_definition']=rule['definition']
    params[rid]['spec_scoring_levels']=rule['scoring_levels']['spec_text']
    rule['scoring_levels']['executable_parameters']=f'parameters.yaml#{rid}'
    lines=[x.strip() for x in rule['scoring_levels']['spec_text'].splitlines() if x.strip()]
    if lines[:2]==['条件','得分/扣分']:
        lines=lines[2:]
    if len(lines)%2:
        raise ValueError(f'Unpaired scoring table cells: {rid}')
    levels=[]
    for condition,award in zip(lines[::2],lines[1::2]):
        positive=re.search(r'\+(\d+)',award)
        negative=re.search(r'-(\d+)',award)
        levels.append({'condition_spec':condition,'award_spec':award,
                       'score':int(positive.group(1)) if positive else 0 if re.search(r'\b0\b',award) and rid[0]!='R' else None,
                       'penalty':int(negative.group(1)) if negative else 0 if re.search(r'\b0\b',award) and rid[0]=='R' else None,
                       'status_tokens':re.findall(r'\b(?:PASS|PARTIAL|FAIL|UNKNOWN|CANDIDATE|FORMED|CONFIRMED|INVALIDATED|EXPIRED|TERMINATED|PENDING|NOT_APPLICABLE)\b',condition+' '+award)})
    rule['scoring_levels']['levels']=levels
    rule['parameters']['global_ref']='parameters.yaml#GLOBAL'
path.write_text(yaml.safe_dump(registry,allow_unicode=True,sort_keys=False),encoding='utf-8')
params_path.write_text(yaml.safe_dump(params,allow_unicode=True,sort_keys=False),encoding='utf-8')
print('Registry finalized:',len(registry['rules']),'rules;',len(EVALUATORS),'evaluators')
