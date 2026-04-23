"""Streamlit 主入口"""

import html
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
from web.page_balance import render_balance
from db.database import load_import_snapshots
from web._cache import bump_data_version

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
.stApp {
    background:
        radial-gradient(1100px 520px at 18% -8%, rgba(212, 175, 55, 0.09) 0%, transparent 58%),
        radial-gradient(900px 420px at 92% 6%, rgba(15, 23, 42, 0.04) 0%, transparent 52%),
        linear-gradient(180deg, #F4F6FA 0%, #FFFFFF 38%, #FAFAF9 100%);
    min-height: 100vh;
}

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

/* 主内容区：轻量「纸张」感，与侧栏深色形成层次 */
[data-testid="stAppViewContainer"] .main .block-container {
    background: rgba(255, 255, 255, 0.72);
    border: 1px solid rgba(226, 232, 240, 0.75);
    border-radius: var(--radius-lg);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 12px 40px -18px rgba(15, 23, 42, 0.08);
}

/* ───────── Sidebar ───────── */
section[data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(168deg, #0E1628 0%, #0B1220 42%, #070C14 100%);
    border-right: 1px solid rgba(255,255,255,0.06);
    box-shadow: inset -1px 0 0 rgba(212, 175, 55, 0.07);
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
    margin-bottom: 0.75rem; letter-spacing: 0.2px;
}
[data-testid="stSidebar"] .brand-panel {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.65rem 0.7rem;
    margin: 0.35rem 0 0.35rem;
    background: linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 100%);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
    box-shadow: 0 1px 0 rgba(212, 175, 55, 0.12);
}
[data-testid="stSidebar"] .brand-panel .avatar {
    width: 32px;
    height: 32px;
    border-radius: 8px;
    background: linear-gradient(145deg, #E8C547 0%, var(--color-accent) 45%, var(--color-accent-700) 100%);
    color: #0B1220;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 0.88rem;
    flex-shrink: 0;
    box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.35), 0 2px 8px rgba(212, 175, 55, 0.25);
}
[data-testid="stSidebar"] .brand-panel .who {
    display: flex;
    flex-direction: column;
    line-height: 1.2;
    min-width: 0;
}
[data-testid="stSidebar"] .brand-panel .who .nm {
    color: #F8FAFC;
    font-size: 0.86rem;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
[data-testid="stSidebar"] .brand-panel .who .id {
    color: #64748B;
    font-size: 0.7rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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
    letter-spacing: -0.02em;
    margin: 0 0 1.25rem 0 !important;
    padding-bottom: 0.75rem;
    border-bottom: none;
    position: relative;
}
.main h1::after {
    content: "";
    position: absolute;
    left: 0;
    bottom: 0;
    width: 52px;
    height: 3px;
    border-radius: 2px;
    background: linear-gradient(90deg, var(--color-accent) 0%, rgba(212, 175, 55, 0.25) 100%);
}
.main h1 + * {
    margin-top: 0.15rem;
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

/* ───────── Login / 密码表单 ───────── */
.rc-login-hero {
    position: relative;
    max-width: 480px;
    margin: 2.5rem auto 0;
    padding: 2rem 1.25rem 0.25rem;
    text-align: center;
}
.rc-login-hero .rc-login-glow {
    position: absolute;
    inset: -28% -35% auto;
    height: 300px;
    background: radial-gradient(ellipse 70% 55% at 50% 40%, rgba(212, 175, 55, 0.18) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}
.rc-login-hero .rc-login-inner {
    position: relative;
    z-index: 1;
}
.rc-login-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.38rem 0.9rem;
    border: 1px solid rgba(226, 232, 240, 0.95);
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: var(--color-ink-soft);
    background: rgba(255, 255, 255, 0.85);
    box-shadow: var(--shadow-sm);
}
.rc-login-badge span.dot {
    width: 7px;
    height: 7px;
    border-radius: 2px;
    background: linear-gradient(145deg, #E8C547, var(--color-accent));
    box-shadow: 0 0 0 1px rgba(212, 175, 55, 0.35);
}
.rc-login-h1 {
    margin: 1rem 0 0.35rem;
    font-size: clamp(1.38rem, 3.6vw, 1.72rem);
    font-weight: 700;
    letter-spacing: -0.03em;
    color: var(--color-ink);
    line-height: 1.25;
}
.rc-login-sub {
    margin: 0;
    color: var(--color-mute);
    font-size: 0.9rem;
    line-height: 1.5;
}
.rc-login-foot {
    text-align: center;
    font-size: 0.72rem;
    color: var(--color-mute);
    margin: 1.75rem auto 2rem;
    max-width: 420px;
    letter-spacing: 0.04em;
}

[data-testid="stForm"] {
    max-width: 420px;
    margin: 1.5rem auto 0;
    background: rgba(255, 255, 255, 0.88);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border: 1px solid rgba(228, 231, 235, 0.95);
    border-radius: var(--radius-lg);
    padding: 2rem 2rem 1.65rem;
    box-shadow:
        0 1px 2px rgba(15, 23, 42, 0.05),
        0 18px 48px -20px rgba(15, 23, 42, 0.14);
    position: relative;
    overflow: hidden;
}
[data-testid="stForm"]::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--color-accent-700), var(--color-accent), #F0E6B8);
    z-index: 1;
}
[data-testid="stForm"] .stButton > button {
    background: linear-gradient(180deg, #0F172A 0%, #020617 100%) !important;
    color: #FFFFFF !important;
    border: none !important;
    width: 100%;
    padding: 0.62rem 1rem !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
}
[data-testid="stForm"] .stButton > button:hover {
    background: linear-gradient(180deg, #1E293B 0%, #0F172A 100%) !important;
    box-shadow: 0 4px 14px -4px rgba(15, 23, 42, 0.25);
}
[data-testid="stForm"] label,
[data-testid="stForm"] [data-testid="stWidgetLabel"] p {
    color: var(--color-ink-soft) !important;
    font-weight: 500 !important;
}
[data-testid="stForm"] input {
    border-radius: var(--radius-sm) !important;
}

/* ───────── Tabular numerals everywhere monetary numbers appear ───────── */
[data-testid="stMetricValue"], [data-testid="stDataFrame"] td,
[data-testid="stDataEditor"] td {
    font-variant-numeric: tabular-nums;
}

/* ───────── Status / Chip / KPI ───────── */
.rc-badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px; border-radius: 999px;
    font-size: 0.74rem; font-weight: 600;
    letter-spacing: 0.02em; line-height: 1.4;
    border: 1px solid transparent;
    background: #F1F5F9; color: #334155;
}
.rc-badge::before {
    content: ""; width: 6px; height: 6px; border-radius: 50%;
    background: currentColor; opacity: 0.85;
}
.rc-badge.is-done    { background:#DCFCE7; color:#15803D; }
.rc-badge.is-partial { background:#FEF3C7; color:#B45309; }
.rc-badge.is-unpaid  { background:#FEE2E2; color:#B91C1C; }
.rc-badge.is-undeliv { background:#E2E8F0; color:#475569; }
.rc-badge.is-prepaid { background:#DBEAFE; color:#1D4ED8; }

.rc-pill {
    display: inline-block;
    padding: 3px 10px; margin: 2px 4px 2px 0;
    border-radius: 12px;
    border: 1px solid var(--color-border);
    background: #FAFAF9; color: var(--color-ink-soft);
    font-size: 0.76rem; font-weight: 500;
    line-height: 1.5;
    max-width: 100%;
    white-space: normal; word-break: break-all;
    overflow-wrap: anywhere;
}
.rc-pills-wrap {
    display: flex; flex-wrap: wrap; gap: 0;
    margin: 0.25rem 0 0.6rem;
}

.rc-kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 0.6rem;
    margin: 0.5rem 0 1rem;
}
.rc-kpi {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.55rem 0.8rem;
}
.rc-kpi .lbl {
    font-size: 0.7rem; color: var(--color-mute);
    text-transform: uppercase; letter-spacing: 0.06em;
    font-weight: 600;
}
.rc-kpi .val {
    font-size: 1.05rem; color: var(--color-ink);
    font-weight: 700; font-variant-numeric: tabular-nums;
    margin-top: 2px;
}
.rc-kpi.is-accent .val { color: var(--color-accent-700); }

.rc-meta {
    display: flex; flex-wrap: wrap; gap: 0.4rem;
    margin: 0.15rem 0 0.5rem;
}
.rc-meta .k {
    color: var(--color-mute); font-size: 0.78rem; margin-right: 4px;
}
.rc-meta .v {
    color: var(--color-ink-soft); font-size: 0.82rem; font-weight: 500;
}
.rc-section-title {
    font-size: 0.82rem; color: var(--color-mute);
    font-weight: 600; letter-spacing: 0.06em;
    text-transform: uppercase;
    margin: 0.6rem 0 0.3rem;
}

/* expander 标题里的金额数字稍大、用 tabular-nums 对齐 */
.main [data-testid="stExpander"] summary {
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

/* ───────── Mobile-nav 容器：仅窄屏显示 ───────── */
.st-key-mobile_nav {
    margin: 0 0 1.1rem;
}
.st-key-mobile_nav [data-testid="stSelectbox"] > label {
    font-size: 0.74rem; color: var(--color-mute) !important;
    font-weight: 600; letter-spacing: 0.06em;
    text-transform: uppercase;
}
.st-key-mobile_nav [data-baseweb="select"] > div {
    background: var(--color-surface) !important;
    border-radius: var(--radius) !important;
    border: 1px solid var(--color-border) !important;
    box-shadow: var(--shadow-sm);
    min-height: 44px;
    font-weight: 600;
    color: var(--color-ink) !important;
}

/* 默认（桌面 ≥769px）：隐藏移动端导航 */
@media (min-width: 769px) {
    .st-key-mobile_nav { display: none !important; }
}

/* 移动端（≤768px）：隐藏侧边栏与顶部栏入口，仅留主区域页面切换器 */
@media (max-width: 768px) {
    section[data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"],
    button[data-testid="stBaseButton-header"] {
        display: none !important;
    }

    .block-container {
        padding: 1rem 0.9rem 2rem;
    }
}
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
    "结余合同",
    "历史记录",
]


def load_auth_config():
    """读取用户配置。

    ``cookie.key`` / ``cookie.name`` / ``cookie.expiry_days`` 允许通过环境
    变量或 ``st.secrets`` 覆盖，避免把密钥硬编码到 git 仓库里。

    优先级：环境变量 > st.secrets > yaml 里的默认值。
    """
    import os as _os

    config_path = ROOT / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    cookie = config.setdefault("cookie", {})

    def _override(key: str, env_name: str, secrets_key: str, cast=lambda x: x):
        val = _os.environ.get(env_name)
        if val is None:
            try:
                if hasattr(st, "secrets") and secrets_key in st.secrets:
                    val = st.secrets[secrets_key]
            except Exception:
                val = None
        if val is not None:
            try:
                cookie[key] = cast(val)
            except Exception:
                pass

    _override("key", "AUTH_COOKIE_KEY", "AUTH_COOKIE_KEY")
    _override("name", "AUTH_COOKIE_NAME", "AUTH_COOKIE_NAME")
    _override("expiry_days", "AUTH_COOKIE_EXPIRY_DAYS", "AUTH_COOKIE_EXPIRY_DAYS",
              cast=lambda v: int(v))
    return config


def _render_login(authenticator) -> None:
    """未登录时渲染的品牌头 + 登录表单。"""
    login_brand = """
<div class="rc-login-hero">
  <div class="rc-login-glow" aria-hidden="true"></div>
  <div class="rc-login-inner">
    <div class="rc-login-badge"><span class="dot" aria-hidden="true"></span>
      锐洋集团 · 销售提成审核系统</div>
    <h1 class="rc-login-h1">锐洋集团提成计算工具</h1>
    <p class="rc-login-sub">请使用授权账户登录以继续操作</p>
  </div>
</div>
"""
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
    foot = '<p class="rc-login-foot">内部系统 · 请妥善保管账户信息</p>'
    if hasattr(st, "html"):
        st.html(foot)
    else:
        st.markdown(foot, unsafe_allow_html=True)


def main():
    config = load_auth_config()

    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

    # ── 登录分支：已登录与未登录严格互斥，避免登录残留 DOM ──
    auth_status = st.session_state.get("authentication_status")

    if auth_status is not True:
        _render_login(authenticator)
        new_status = st.session_state.get("authentication_status")
        if new_status is True:
            # 登录刚刚成功：强制一次 rerun，让整个 DOM 从头渲染主界面
            st.rerun()
        if new_status is False:
            st.error("用户名或密码错误")
        return

    username = st.session_state.get("username", "")
    display_name = st.session_state.get("name", username)

    initial = (display_name[:1] if display_name else username[:1] or "U").upper()
    _dn = html.escape(str(display_name or ""))
    _un = html.escape(str(username or ""))
    sidebar_brand = (
        '<div class="brand-title">锐洋集团提成计算</div>'
        '<div class="brand-sub">销售提成审核工作台</div>'
        '<div class="brand-panel">'
        f'<div class="avatar" aria-hidden="true">{html.escape(initial)}</div>'
        '<div class="who">'
        f'<span class="nm">{_dn}</span>'
        f'<span class="id">@{_un}</span>'
        "</div></div>"
    )
    if "_current_page" not in st.session_state:
        st.session_state["_current_page"] = NAV_ITEMS[0]

    def _on_sidebar_nav():
        st.session_state["_current_page"] = st.session_state["_nav_sidebar"]

    def _on_mobile_nav():
        st.session_state["_current_page"] = st.session_state["_nav_mobile"]

    if "_nav_sidebar" not in st.session_state:
        st.session_state["_nav_sidebar"] = st.session_state["_current_page"]
    if "_nav_mobile" not in st.session_state:
        st.session_state["_nav_mobile"] = st.session_state["_current_page"]
    if st.session_state["_nav_sidebar"] != st.session_state["_current_page"]:
        st.session_state["_nav_sidebar"] = st.session_state["_current_page"]
    if st.session_state["_nav_mobile"] != st.session_state["_current_page"]:
        st.session_state["_nav_mobile"] = st.session_state["_current_page"]

    with st.sidebar:
        if hasattr(st, "html"):
            st.html(sidebar_brand)
        else:
            st.markdown(sidebar_brand, unsafe_allow_html=True)
        authenticator.logout("退出登录", "sidebar")
        st.divider()
        st.radio(
            "nav", NAV_ITEMS,
            key="_nav_sidebar", on_change=_on_sidebar_nav,
            label_visibility="collapsed",
        )

    with st.container(key="mobile_nav"):
        st.selectbox(
            "页面切换", NAV_ITEMS,
            key="_nav_mobile", on_change=_on_mobile_nav,
        )

    page = st.session_state["_current_page"]

    if "delivery_df" not in st.session_state:
        st.session_state.delivery_df = None
    if "payment_df" not in st.session_state:
        st.session_state.payment_df = None

    # 仅在首次登录后加载一次远端快照，之后整个 session 都直接用 session_state
    if st.session_state.get("_snapshot_loaded_for") != username:
        snap_dd, snap_pd = load_import_snapshots(username)
        changed = False
        if st.session_state.delivery_df is None and snap_dd is not None:
            st.session_state.delivery_df = snap_dd
            changed = True
        if st.session_state.payment_df is None and snap_pd is not None:
            st.session_state.payment_df = snap_pd
            changed = True
        st.session_state["_snapshot_loaded_for"] = username
        if changed:
            bump_data_version()

    page_map = {
        "数据导入": lambda: render_import(username),
        "销售员详情": lambda: render_salesperson(),
        "完成额度提成": lambda: render_quota(username),
        "利润提成": lambda: render_profit(username),
        "回款时效提成": lambda: render_payment(username),
        "总提成汇总": lambda: render_total(username),
        "结余合同": lambda: render_balance(username),
        "历史记录": lambda: render_history(username),
    }
    page_map[page]()


if __name__ == "__main__":
    main()
