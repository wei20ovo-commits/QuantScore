"""Regressions found while auditing the WorkBuddy handoff; offline only."""
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import hashlib
import json

import pandas as pd
import pytest
from conftest import bars, evaluate
from test_stage2_service import service
from test_stage2_completion import probe
from v12_fixtures import dragon
from test_risks_and_patterns import n_board
from app.data.market_rule import MarketLimitResolver


def test_historical_request_cannot_manufacture_frozen_signal(service):
    d=service.provider_manager.fetch('000001').bars
    day=str(d.date.iloc[-4].date())
    first=service.analyze('000001',as_of=day)
    second=service.analyze('000001',as_of=day)
    assert first.r7_forward_confirmation is None and second.r7_forward_confirmation is None
    assert service.provider_manager.cache.score_snapshots('000001.SZ')==[]


@pytest.mark.parametrize('rid,data', [('F1-Y',dragon),('F1-N',lambda:n_board(confirmed=True))])
def test_f2_reads_existing_shape_event_dates(engine,rid,data):
    d=data()
    source=evaluate(engine,rid,d)
    assert source.score>0
    actual=evaluate(engine,'F2',d)
    assert actual.status!='UNKNOWN',actual.explanation
    assert actual.raw_values['event_date']==source.raw_values.get('jump_date',source.raw_values.get('second_start_date'))


@pytest.mark.parametrize('ratio,expected',[(.599999,5),(.799999,3),(.999999,1)])
def test_d2_left_limit_tiers(engine,ratio,expected):
    d=bars([10]*149+[11,10.8]);d.loc[149,'volume']=200;d.loc[150,'volume']=200*ratio
    assert evaluate(engine,'D2',d).score==expected


@pytest.mark.parametrize('turn,expected',[(4.99999,6),(9.99999,4),(10.,0)])
def test_f1x_left_limit_and_risk_warning(engine,turn,expected):
    r=evaluate(engine,'F1-X',probe(turn))
    assert r.score==expected
    assert r.conditions['high_turnover_warning']==(turn>=10)


def test_limit_apply_uses_verified_corporate_action_reference():
    d=pd.DataFrame({'date':pd.to_datetime(['2024-01-01','2024-01-02']),'close_raw':[20.,10.]})
    meta=dict(exchange='SH',board='MAIN',listing_date='2000-01-01',status_date='2024-01-02',
              is_st=False,rule_valid_from='2024-01-01',rule_valid_to='2024-01-31',
              rule_source='offline verified fixture',limit_ratio=.1,price_tick=.01,
              metadata_verified=True,rule_verified=True,special_session=False,
              normal_listing_period=True,reference_price_verified=True,reference_price=10.)
    out=MarketLimitResolver().apply(d,historical_metadata={'2024-01-02':meta})
    assert out.limit_up_price.iloc[-1]==11 and out.limit_down_price.iloc[-1]==9


def test_v14_word_version_contract_and_historical_integrity():
    root=Path(__file__).resolve().parents[1]
    hashes=json.loads((root/'docs/archive/pre_v1_4_spec_hashes.json').read_text('utf-8'))
    for name,digest in hashes.items():
        assert hashlib.sha256((root/'docs'/name).read_bytes()).hexdigest()==digest
    with ZipFile(next((root/'docs').glob('*V1.4*.docx'))) as z:
        assert z.testzip() is None
        xml=ET.fromstring(z.read('word/document.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    paras=[''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in xml.findall('.//w:p',ns)]
    assert 'spec_version=1.4' in '\n'.join(paras[:35])
    assert '仍标spec_version=1.3' not in '\n'.join(paras[:35])
    assert any('000001.SH' in p for p in paras[:35])
    for p in paras:
        if '所有新结果spec_version=1.3' in p:
            assert 'HISTORICAL' in p


def test_gitignore_protects_credentials_and_cache():
    root=Path(__file__).resolve().parents[1]
    lines=(root/'.gitignore').read_text('utf-8').splitlines()
    assert {'.env','.env.*','!.env.example','data/cache/*','outputs/runtime/*','!outputs/runtime/.gitkeep'}<=set(lines)
    assert (root/'.env.example').read_text('utf-8').strip()=='TUSHARE_TOKEN='
