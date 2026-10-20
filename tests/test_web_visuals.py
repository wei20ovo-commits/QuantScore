"""Presentation tests on explicit artificial data, not real acceptance."""
from unittest.mock import MagicMock, patch

import pandas as pd
from app.web_visuals import structure_totals, candle_chart, home_dashboard

def test_structure_cards_use_existing_points_without_normalization():
    rules=[dict(rule_type='POSITIVE',category='C',score=4,max_score=6,status='PARTIAL'),
           dict(rule_type='POSITIVE',category='C',score=None,max_score=8,status='UNKNOWN'),
           dict(rule_type='POSITIVE',category='D',score=5,max_score=5,status='PASS'),
           dict(rule_type='RISK',category='C',score=0,max_score=0,status='PASS')]
    assert structure_totals(rules,{'C'})==(4,14,1)
    assert structure_totals(rules,{'E','F'})==(0,0,0)

def test_candle_chart_preserves_input_prices_and_moving_averages():
    rows=[dict(date='2024-01-02',open_adj=10,high_adj=12,low_adj=9,close_adj=11,volume=123,
               M5=10.5,M30=10.1,M60=None)]
    fig=candle_chart(rows)
    assert [x.type for x in fig.data]==['candlestick','scatter','scatter','scatter','bar']
    assert list(fig.data[0].close)==[11]
    assert list(fig.data[1].y)==[10.5]
    assert list(fig.data[4].y)==[123]
    assert pd.isna(fig.data[3].y[0])


def test_history_wording_never_presents_saved_score_as_current():
    class Column:
        def __enter__(self):return self
        def __exit__(self,*_):return False
    rendered=[]
    fake=MagicMock()
    fake.columns.side_effect=lambda value,**kwargs:(
        [Column() for _ in range(value)]
        if isinstance(value,int) else [Column() for _ in value])
    fake.html.side_effect=lambda value:rendered.append(value)
    fake.button.return_value=False
    data={'name':'平安银行','symbol':'000001.SZ','evaluation_date':'2026-09-30',
          'risk_level':'LOW','final_quant_score':80,
          'rules':[{'rule_type':'POSITIVE','category':'C','score':4,
                    'max_score':5,'status':'PASS'}],
          'price':{'close':10}}
    with patch('app.web_visuals.st',fake):
        home_dashboard([], [{'data':data,'analyzed_at':'2026-10-20 12:00:00'}])
    output=' '.join(rendered)
    assert '历史评分预览' in output
    assert '历史评价日期 2026-09-30' in output
    assert '不代表当前评分' in output
    assert '最近历史评分' in output
    assert '评价日期' in output
    assert '分析时间' not in output
    assert '2026-09-30' in output
    assert '2026-10-20 12:00:00' not in output
    assert '非当前评分' in output
