"""Offline presentation regressions. No fixture is used by the live page."""
from pathlib import Path
from unittest.mock import patch
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_stage2_service import service
from app.web_visuals import candle_chart, sparkline

WEB=Path(__file__).resolve().parents[1]/'app/web.py'

def test_theme_navigation_and_real_result_session_history(service):
    data=service.analyze('000001').to_dict()
    data['data_status']['is_mock']=False  # presentation fixture, not network evidence
    st.cache_data.clear()
    with patch('app.web_market.load_index_snapshots',return_value=[]),patch('app.web_backend.analyze_stock',return_value=data):
        app=AppTest.from_file(str(WEB)).run()
        app.button(key='theme_toggle').click().run()
        assert app.session_state['theme']=='dark'
        app.button(key='analyze_submit').click().run(timeout=20)
        assert app.session_state['view']=='analysis'
        assert len(app.session_state['recent_analyses'])==1
        app.button(key='nav_home').click().run()
        assert app.session_state['view']=='home'
        assert app.session_state['recent_analyses'][0]['data']['symbol']=='000001.SZ'
        app.button(key='nav_analysis').click().run()
        assert app.metric and not app.exception
    st.cache_data.clear()

def test_dark_chart_does_not_alter_values():
    rows=[dict(date='2024-01-01',open_adj=10,high_adj=11,low_adj=9,close_adj=10.5,volume=100,M5=10,M30=9,M60=8)]
    light=candle_chart(rows,'light');dark=candle_chart(rows,'dark')
    assert dark.layout.paper_bgcolor=='#101f35'
    assert light.layout.paper_bgcolor=='#ffffff'
    assert list(light.data[0].close)==list(dark.data[0].close)

def test_market_sparkline_uses_input_sequence():
    import base64
    html=sparkline([10,20,15],'#123456')
    svg=base64.b64decode(html.split('base64,')[1].split('"')[0]).decode()
    assert '0.00,40.00 65.00,6.00 130.00,23.00' in svg
    assert sparkline([], '#123456')==''
