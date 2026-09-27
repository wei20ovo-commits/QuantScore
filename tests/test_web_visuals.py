"""Presentation tests on explicit artificial data, not real acceptance."""
import pandas as pd
from app.web_visuals import structure_totals, candle_chart

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
