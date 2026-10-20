"""Optional hosted feedback form. No fake local submission or public Git issues."""
import os
import re
from urllib.parse import urlsplit

CATEGORIES=('页面使用困难','评分或解释看不懂','数据异常','新功能建议')
SETTING='QUANTSCORE_FEEDBACK_FORM_URL'


def validate_form_url(value):
    if not isinstance(value,str) or len(value)>1024 or any(ord(c)<33 for c in value):return None
    try:
        u=urlsplit(value)
        if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.query or u.fragment:return None
        rules={'forms.gle':r'/[A-Za-z0-9_-]+/?',
               'docs.google.com':r'/forms/d/e/[A-Za-z0-9_-]+/viewform/?',
               'tally.so':r'/r/[A-Za-z0-9_-]+/?'}
        pattern=rules.get(u.hostname)
        return value if pattern and re.fullmatch(pattern,u.path) else None
    except ValueError:return None


def feedback_url(secrets=None):
    value=os.environ.get(SETTING)
    if value is None and secrets is not None:
        try:value=secrets.get(SETTING)
        except Exception:pass
    return validate_form_url(value)


def render_feedback():
    import streamlit as st
    with st.expander('使用反馈 · 帮助我们改进'):
        st.write('遇到问题或有想法，可反馈：'+' / '.join(CATEGORIES)+'。')
        st.caption('请勿填写姓名、手机号、账户、持仓或 API Key。本站不会自动发送股票代码、请求标识或分析结果到反馈表单。')
        url=feedback_url(st.secrets)
        if url:
            st.link_button('打开反馈表单（外部）',url)
            st.caption('请在表单中选择问题类型并描述问题。是否保存成功，以外部表单的实际提交确认页面为准；打开链接不代表已提交。')
        else:
            st.info('反馈持久化服务尚未配置，当前不能提交或保存反馈。请等待维护者启用，本站不会显示虚假的提交成功。')
            with st.expander('维护者配置说明'):
                st.write('创建无需登录的 Google Forms 或 Tally 表单，包含上述四类问题和问题描述；关闭邮箱收集，不要求身份或账户信息。')
                st.write('将公开填写链接设为环境变量或 Streamlit secrets 中的 QUANTSCORE_FEEDBACK_FORM_URL。使用无查询参数的 HTTPS 填写链接，不使用管理或编辑链接。')
                st.write('先匿名实际提交一条测试反馈，并在表单后台确认已保存，再邀请用户使用。未完成此步骤前，不能宣称反馈渠道已上线。')
