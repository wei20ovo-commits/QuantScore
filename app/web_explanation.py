"""Streamlit adapter. Credentials never enter session state or rendered messages."""
import streamlit as st
from app.explanation import (DISCLAIMER, MODES, REASONS, ExplanationConfig,
                             ExplanationService, build_context, context_fingerprint)


def explanation_config():
    # Streamlit secrets can be absent both locally and on Community Cloud.
    return ExplanationConfig.from_sources(secrets=st.secrets)


def render_explanation(data):
    # Native Streamlit text/expanded summaries retain light theme colors in the
    # project's CSS-driven Dark Mode. Scope the fix to this new panel only.
    st.html('''<style>
    .stApp:has(.theme-dark) .st-key-explanation_panel summary {
        background: #16243b !important; color: #d9e7fb !important;
    }
    .stApp:has(.theme-dark) .st-key-explanation_panel summary p,
    .stApp:has(.theme-dark) .st-key-explanation_panel summary svg,
    .stApp:has(.theme-dark) .st-key-explanation_panel [data-testid="stText"],
    .stApp:has(.theme-dark) .st-key-explanation_panel [data-testid="stText"] span,
    .stApp:has(.theme-dark) .st-key-explanation_panel pre {
        color: #d9e7fb !important;
    }
    </style>''')
    with st.container(key='explanation_panel'):
        _render_panel(data)


def _render_panel(data):
    with st.expander('AI Explanation · 既有规则解释', expanded=True):
        mode = st.selectbox('解释模式', MODES, key='explanation_mode')
        st.caption('Standard Rules 不调用模型。AI Explanation 由按钮触发；Auto 在配置有效时自动调用一次。'
                   '启用模型会向配置的服务发送已计算的规则证据，不发送原始 K 线。')
        try:
            fingerprint = context_fingerprint(build_context(data))
        except Exception:
            fingerprint = ''
        # Standard mode does not even load API configuration or create a provider.
        config = ExplanationConfig() if mode == 'Standard Rules' else explanation_config()
        cache_key = (fingerprint, mode, config.valid, config.model, config.base_url)
        if st.session_state.get('explanation_cache_key') != cache_key:
            st.session_state.pop('explanation_result', None)
            st.session_state['explanation_cache_key'] = cache_key
        triggered = False
        if mode == 'AI Explanation':
            if not config.valid:
                st.caption(REASONS['NO_CONFIGURATION'])
            triggered = st.button('生成 AI 解释', key='generate_ai_explanation', disabled=not config.valid)
        result = st.session_state.get('explanation_result')
        if triggered or result is None:
            with st.spinner('正在组织既有规则解释…'):
                result = ExplanationService(config).explain(data, mode, triggered=triggered)
            st.session_state['explanation_result'] = result
        st.caption('当前展示：' + result.source)
        if result.reason_code:
            st.caption(REASONS.get(result.reason_code, REASONS['PROVIDER_ERROR']))
        st.caption('AI 仅组织规则证据的展示顺序；事实、分数、风险及说明由本地从既有结果填入。')
        for title, lines in result.sections:
            with st.expander(title, expanded=title == '当前策略匹配概况'):
                for line in lines:
                    st.text(line)  # No untrusted HTML or Markdown from model/source.
        st.caption(DISCLAIMER)
