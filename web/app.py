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
from web.page_salesperson import render_salesperson
from db.database import load_import_snapshots

st.set_page_config(
    page_title="锐洋集团提成计算工具",
    layout="wide",
    initial_sidebar_state="expanded",
)

GLOBAL_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ───────── Design Tokens ───────── */
:root {
    --color-ink:        #0F172A;   /* primary text */
    --color-ink-soft:   #475569;   /* secondary text */
    --color-mute:       #94A3B8;   /* tertiary / labels */
    --color-bg:         #FFFFFF;
    --color-surface:    #FAFAF9;   /* card surface */
    --color-surface-2:  #F4F4F5;   /* subtle stripe */
    --color-border:     #E5E7EB;
    --color-border-soft:#EEF0F3;
    --color-accent:     #D4AF37;   /* gold CTA */
    --color-accent-700: #B8941F;
    --color-accent-50:  #FBF5DD;
    --color-success:    #16A34A;
    --color-warning:    #F59E0B;
    --color-danger:     #DC2626;
    --radius-sm: 6px;
    --radius:    10px;
    --radius-lg: 14px;
    --shadow-sm: 0 1px 2px rgba(15,23,42,0.04);
    --shadow:    0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04);
    --shadow-lg: 0 10px 30px rgba(15,23,42,0.08);
    --transition: 200ms cubic-bezier(0.4, 0, 0.2, 1);
}

/* ───────── Base ───────── */
html, body, [class*="stApp"], [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI",
                 "PingFang SC", "Microsoft YaHei", sans-serif !important;
    color: var(--color-ink);
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
}
.stApp { background: var(--color-bg); }

/* ───────── 隐藏 Streamlit Cloud / 框架的品牌元素 ───────── */
header[data-testid="stHeader"]            { display: none !important; height: 0 !important; }
[data-testid="stToolbar"]                 { display: none !important; }
[data-testid="stToolbarActions"]          { display: none !important; }
[data-testid="stDecoration"]              { display: none !important; }
[data-testid="stStatusWidget"]            { display: none !important; }
[data-testid="manage-app-button"]         { display: none !important; }
.stDeployButton                            { display: none !important; }
button[data-testid="stBaseButton-header"] { display: none !important; }
#MainMenu                                  { display: none !important; }
footer                                     { display: none !important; }
a[href*="streamlit.io"]                    { display: none !important; }
iframe[title*="streamlit"]                 { display: none !important; }
.viewerBadge_container__1QSob,
.viewerBadge_link__1S137,
[class*="viewerBadge"]                     { display: none !important; }
/* GitHub Fork 按钮（来自 Cloud viewer） */
[class*="ProfileContainer"],
[data-testid="stAppViewBlockContainer"] > div > div > a[href*="github.com"]:first-child { display: none !important; }

/* 右下角 "Manage app" 浮动按钮（多版本兼容） */
[data-testid="manage-app-button"],
[data-testid="stAppDeployButton"],
[data-testid="stAppViewBadge"],
[data-testid="stViewerBadge"],
[class*="manageAppButton"],
[class*="ManageApp"],
[class*="manage-app"],
button[title*="Manage" i],
button[aria-label*="Manage" i],
a[href*="share.streamlit.io"],
a[href*="streamlit.io/cloud"],
a[href*="streamlit.io"]                       { display: none !important; }
/* Cloud Viewer 注入的 iframe / 浮动条 */
iframe[src*="share.streamlit.io"],
iframe[src*="streamlitapp.com"] { display: none !important; }
/* 兜底：任何固定到右下角且 z-index 高的浮动小窗 */
.stApp > div:last-child > div[style*="position: fixed"][style*="bottom"][style*="right"],
body > div[style*="position: fixed"][style*="bottom"][style*="right"] {
    display: none !important;
}

.block-container {
    padding: 2rem 2.5rem 3rem;
    max-width: 1480px;
}

/* ───────── Sidebar ───────── */
section[data-testid="stSidebar"] > div:first-child {
    background: #0B1220;
    border-right: 1px solid rgba(255,255,255,0.05);
}
[data-testid="stSidebar"] { min-width: 232px; }

[data-testid="stSidebar"] .brand-title {
    font-size: 1.0rem;
    font-weight: 700;
    color: #FFFFFF !important;
    letter-spacing: 0.4px;
    padding: 0.4rem 0 0.1rem;
    display: flex; align-items: center; gap: 0.5rem;
}
[data-testid="stSidebar"] .brand-title::before {
    content: ''; width: 8px; height: 8px; border-radius: 2px;
    background: var(--color-accent);
}
[data-testid="stSidebar"] .brand-sub {
    font-size: 0.75rem; color: #64748B !important;
    margin-bottom: 0.6rem; letter-spacing: 0.2px;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.06) !important;
    margin: 0.8rem 0 !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span {
    color: #CBD5E1;
}

/* nav radio: looks like menu items */
[data-testid="stSidebar"] [role="radiogroup"] {
    gap: 2px !important;
}
[data-testid="stSidebar"] [role="radiogroup"] > label {
    width: 100%;
    padding: 0.55rem 0.75rem;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background var(--transition), color var(--transition);
    color: #CBD5E1 !important;
    font-size: 0.9rem;
    font-weight: 500;
}
[data-testid="stSidebar"] [role="radiogroup"] > label:hover {
    background: rgba(255,255,255,0.04);
    color: #FFFFFF !important;
}
[data-testid="stSidebar"] [role="radiogroup"] > label[data-checked="true"],
[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {
    background: rgba(212,175,55,0.10);
    color: var(--color-accent) !important;
    border-left: 2px solid var(--color-accent);
    padding-left: calc(0.75rem - 2px);
}
[data-testid="stSidebar"] [role="radiogroup"] > label > div:first-child {
    display: none !important;       /* hide radio dot */
}

/* sidebar logout button */
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    color: #CBD5E1 !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: var(--radius-sm) !important;
    font-weight: 500 !important;
    width: 100%;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.05) !important;
    color: #FFFFFF !important;
    border-color: rgba(255,255,255,0.18) !important;
}

/* ───────── Headings ───────── */
.main h1 {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: var(--color-ink) !important;
    letter-spacing: -0.01em;
    margin: 0 0 1.25rem 0 !important;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid var(--color-border-soft);
}
.main h2, .main h3 {
    font-weight: 600 !important;
    color: var(--color-ink) !important;
    letter-spacing: -0.005em;
}
.main h2 { font-size: 1.05rem !important; margin: 0 0 0.6rem 0 !important; }
.main h3 { font-size: 0.95rem !important; margin: 0 0 0.4rem 0 !important; }
.main p, .main label, .main li { color: var(--color-ink); }
.main small, .stCaption, [data-testid="stCaptionContainer"] {
    color: var(--color-mute) !important;
}

/* ───────── Metrics ───────── */
div[data-testid="stMetric"] {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    padding: 1rem 1.15rem;
    box-shadow: var(--shadow-sm);
    transition: border-color var(--transition), box-shadow var(--transition);
}
div[data-testid="stMetric"]:hover {
    border-color: #D4D4D8;
    box-shadow: var(--shadow);
}
div[data-testid="stMetric"] label {
    color: var(--color-mute) !important;
    font-size: 0.78rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: var(--color-ink) !important;
    font-weight: 700;
    font-size: 1.5rem;
    font-variant-numeric: tabular-nums;
}
div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
    font-size: 0.78rem;
}

/* ───────── Buttons ───────── */
.stButton > button, .stDownloadButton > button {
    border-radius: var(--radius-sm);
    font-weight: 500;
    border: 1px solid var(--color-border);
    background: #FFFFFF;
    color: var(--color-ink);
    transition: all var(--transition);
    box-shadow: var(--shadow-sm);
    cursor: pointer;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: var(--color-ink);
    color: var(--color-ink);
    background: var(--color-surface);
}
.stButton > button:focus, .stDownloadButton > button:focus {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
    box-shadow: none;
}
.stButton > button[kind="primary"] {
    background: var(--color-ink) !important;
    color: #FFFFFF !important;
    border-color: var(--color-ink) !important;
}
.stButton > button[kind="primary"]:hover {
    background: #000000 !important;
    border-color: #000000 !important;
}

/* ───────── Containers (with border) ───────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: var(--radius) !important;
    border-color: var(--color-border) !important;
    background: var(--color-bg);
    box-shadow: var(--shadow-sm);
}

/* ───────── Expander ───────── */
.main [data-testid="stExpander"] {
    border: 1px solid var(--color-border) !important;
    border-radius: var(--radius) !important;
    background: var(--color-bg);
    box-shadow: var(--shadow-sm);
    overflow: hidden;
}
.main [data-testid="stExpander"] summary {
    padding: 0.7rem 1rem;
    font-weight: 500;
    color: var(--color-ink);
    transition: background var(--transition);
    cursor: pointer;
}
.main [data-testid="stExpander"] summary:hover {
    background: var(--color-surface);
}

/* ───────── Tabs ───────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0.25rem;
    border-bottom: 1px solid var(--color-border);
}
.stTabs [data-baseweb="tab"] {
    height: 38px;
    padding: 0 0.9rem;
    font-weight: 500;
    color: var(--color-ink-soft);
    border-radius: 0;
    background: transparent;
    transition: color var(--transition);
}
.stTabs [data-baseweb="tab"]:hover { color: var(--color-ink); }
.stTabs [aria-selected="true"] {
    color: var(--color-ink) !important;
    border-bottom: 2px solid var(--color-accent) !important;
}

/* ───────── DataFrame / data_editor ───────── */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    overflow: hidden;
    box-shadow: var(--shadow-sm);
}
[data-testid="stDataFrame"] [data-baseweb="table-cell"]:hover,
[data-testid="stDataEditor"] [data-baseweb="table-cell"]:hover {
    background: var(--color-surface) !important;
}

/* ───────── Inputs ───────── */
.stTextInput input, .stNumberInput input,
.stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
    border-radius: var(--radius-sm) !important;
    border-color: var(--color-border) !important;
    transition: border-color var(--transition), box-shadow var(--transition);
}
.stTextInput input:focus, .stNumberInput input:focus,
.stTextArea textarea:focus {
    border-color: var(--color-ink) !important;
    box-shadow: 0 0 0 3px rgba(15,23,42,0.06) !important;
}

/* ───────── Alerts ───────── */
[data-testid="stAlert"] {
    border-radius: var(--radius);
    border: 1px solid var(--color-border);
    box-shadow: var(--shadow-sm);
}

/* ───────── Divider ───────── */
.main hr { border-color: var(--color-border-soft) !important; }

/* ───────── Login form ───────── */
[data-testid="stForm"] {
    max-width: 400px;
    margin: 4rem auto 0;
    background: #FFFFFF;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 2rem 1.8rem 1.5rem;
    box-shadow: var(--shadow-lg);
}
[data-testid="stForm"] .stButton > button {
    background: var(--color-ink);
    color: #FFFFFF;
    border-color: var(--color-ink);
    width: 100%;
    padding: 0.55rem 1rem;
}
[data-testid="stForm"] .stButton > button:hover {
    background: #000;
    border-color: #000;
}

/* ───────── Tabular numerals everywhere monetary numbers appear ───────── */
[data-testid="stMetricValue"], [data-testid="stDataFrame"] td,
[data-testid="stDataEditor"] td {
    font-variant-numeric: tabular-nums;
}

/* ───────── Reduced motion ───────── */
@media (prefers-reduced-motion: reduce) {
    * { transition: none !important; animation: none !important; }
}

/* ───────── Scrollbar ───────── */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #E2E8F0; border-radius: 6px; }
::-webkit-scrollbar-thumb:hover { background: #CBD5E1; }
</style>
"""
if hasattr(st, "html"):
    st.html(GLOBAL_CSS)
else:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

NAV_ITEMS = [
    "数据导入",
    "销售员详情",
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

    if st.session_state.get("authentication_status") is not True:
        login_brand = """<div style="max-width:400px;margin:5rem auto 0;text-align:center;"><div style="display:inline-flex;align-items:center;gap:.55rem;padding:.35rem .75rem;border:1px solid #E5E7EB;border-radius:999px;font-size:.74rem;font-weight:600;letter-spacing:.06em;color:#475569;background:#FAFAF9;"><span style="width:6px;height:6px;border-radius:2px;background:#D4AF37;"></span>锐洋集团 · 销售提成审核系统</div><h2 style="margin:1rem 0 .25rem;font-size:1.6rem;font-weight:700;letter-spacing:-.01em;color:#0F172A;">锐洋集团提成计算工具</h2><p style="margin:0;color:#94A3B8;font-size:.88rem;">请使用授权账户登录以继续</p></div>"""
        if hasattr(st, "html"):
            st.html(login_brand)
        else:
            st.markdown(login_brand, unsafe_allow_html=True)

    authenticator.login(
        location="main",
        fields={
            "Form name": "账户登录",
            "Username": "用户名",
            "Password": "密码",
            "Login": "登 录",
            "Captcha": "验证码",
        },
    )

    if st.session_state.get("authentication_status") is None:
        return

    if st.session_state.get("authentication_status") is False:
        st.error("用户名或密码错误")
        return

    username = st.session_state.get("username", "")
    display_name = st.session_state.get("name", username)

    initial = (display_name[:1] if display_name else username[:1] or "U").upper()
    sidebar_brand = (
        '<div class="brand-title">锐洋集团提成计算</div>'
        '<div class="brand-sub">销售提成审核工作台</div>'
        '<div style="display:flex;align-items:center;gap:.6rem;'
        'padding:.55rem .65rem;margin:.4rem 0 .25rem;'
        'background:rgba(255,255,255,.04);'
        'border:1px solid rgba(255,255,255,.06);border-radius:8px;">'
        f'<div style="width:28px;height:28px;border-radius:6px;'
        f'background:#D4AF37;color:#0B1220;display:flex;'
        f'align-items:center;justify-content:center;'
        f'font-weight:700;font-size:.85rem;">{initial}</div>'
        '<div style="display:flex;flex-direction:column;line-height:1.15;">'
        f'<span style="color:#FFF;font-size:.85rem;font-weight:600;">{display_name}</span>'
        f'<span style="color:#64748B;font-size:.7rem;">@{username}</span>'
        '</div></div>'
    )
    with st.sidebar:
        if hasattr(st, "html"):
            st.html(sidebar_brand)
        else:
            st.markdown(sidebar_brand, unsafe_allow_html=True)
        authenticator.logout("退出登录", "sidebar")
        st.divider()
        page = st.radio("nav", NAV_ITEMS, label_visibility="collapsed")

    if "delivery_df" not in st.session_state:
        st.session_state.delivery_df = None
    if "payment_df" not in st.session_state:
        st.session_state.payment_df = None

    snap_dd, snap_pd = load_import_snapshots(username)
    if st.session_state.delivery_df is None and snap_dd is not None:
        st.session_state.delivery_df = snap_dd
    if st.session_state.payment_df is None and snap_pd is not None:
        st.session_state.payment_df = snap_pd

    page_map = {
        "数据导入": lambda: render_import(username),
        "销售员详情": lambda: render_salesperson(),
        "完成额度提成": lambda: render_quota(username),
        "利润提成": lambda: render_profit(username),
        "回款时效提成": lambda: render_payment(username),
        "总提成汇总": lambda: render_total(username),
        "历史记录": lambda: render_history(username),
    }
    page_map[page]()


if __name__ == "__main__":
    main()
