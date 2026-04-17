"""Streamlit 主入口"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import yaml
import streamlit_authenticator as stauth

from web.page_import import render_import
from web.page_quota import render_quota
from web.page_profit import render_profit
from web.page_payment import render_payment
from web.page_total import render_total
from web.page_history import render_history

st.set_page_config(
    page_title="电缆提成计算工具",
    layout="wide",
    initial_sidebar_state="expanded",
)

GLOBAL_CSS = """
<style>
/* ── 全局 ── */
.block-container {
    padding: 2rem 2.5rem 3rem;
    max-width: 1400px;
}
header[data-testid="stHeader"] { background: transparent; }

/* ── 侧边栏 ── */
section[data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(180deg, #1a2332 0%, #243447 100%);
}
[data-testid="stSidebar"] {
    min-width: 220px;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span {
    color: #cfd8dc;
}
[data-testid="stSidebar"] .brand-title {
    font-size: 1.05rem; font-weight: 700; color: #ffffff !important;
    letter-spacing: 0.3px; padding: 0.6rem 0 0.2rem;
}
[data-testid="stSidebar"] .brand-sub {
    font-size: 0.78rem; color: #90a4ae !important; margin-bottom: 0.5rem;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.1); margin: 0.8rem 0;
}

/* ── 标题 ── */
.main h1 {
    font-size: 1.45rem !important; font-weight: 700 !important;
    color: #1e293b !important; margin-bottom: 1rem !important;
}
.main h2 {
    font-size: 1.05rem !important; font-weight: 600 !important;
    color: #334155 !important; margin-bottom: 0.5rem !important;
}

/* ── 指标卡片 ── */
div[data-testid="stMetric"] {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 1rem 1.2rem;
}
div[data-testid="stMetric"] label {
    color: #64748b !important; font-size: 0.82rem; font-weight: 500;
    letter-spacing: 0.3px;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: #1e293b !important; font-weight: 700;
}

/* ── 按钮 ── */
.stButton > button {
    border-radius: 8px; font-weight: 500;
    transition: all 0.15s;
}
.stDownloadButton > button {
    border-radius: 8px; font-weight: 500;
}

/* ── 分割线 ── */
.main hr { border-color: #e2e8f0 !important; }

/* ── Expander ── */
.main [data-testid="stExpander"] {
    border: 1px solid #e8ecf0; border-radius: 10px;
}

/* ── 登录页居中 ── */
[data-testid="stForm"] {
    max-width: 400px; margin: 5rem auto 0;
    background: #ffffff; border: 1px solid #e2e8f0;
    border-radius: 14px; padding: 2rem 1.8rem 1.5rem;
    box-shadow: 0 4px 20px rgba(0,0,0,0.05);
}
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

NAV_ITEMS = [
    "数据导入",
    "完成额度提成",
    "利润提成",
    "回款时效提成",
    "总提成汇总",
    "历史记录",
]


def load_auth_config():
    config_path = ROOT / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    config = load_auth_config()

    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

    authenticator.login(location="main")

    if st.session_state.get("authentication_status") is None:
        return

    if st.session_state.get("authentication_status") is False:
        st.error("用户名或密码错误")
        return

    username = st.session_state.get("username", "")
    display_name = st.session_state.get("name", username)

    with st.sidebar:
        st.markdown('<div class="brand-title">电缆提成计算</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="brand-sub">{display_name}</div>', unsafe_allow_html=True)
        authenticator.logout("退出登录", "sidebar")
        st.divider()
        page = st.radio("nav", NAV_ITEMS, label_visibility="collapsed")

    if "delivery_df" not in st.session_state:
        st.session_state.delivery_df = None
    if "payment_df" not in st.session_state:
        st.session_state.payment_df = None

    page_map = {
        "数据导入": lambda: render_import(),
        "完成额度提成": lambda: render_quota(username),
        "利润提成": lambda: render_profit(username),
        "回款时效提成": lambda: render_payment(username),
        "总提成汇总": lambda: render_total(username),
        "历史记录": lambda: render_history(username),
    }
    page_map[page]()


if __name__ == "__main__":
    main()
