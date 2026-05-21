"""
IBKR Research Dashboard — Streamlit entry point.

Layout: hybrid split (TradingView left, Claude AI right).
Either panel expandable to full-screen via ⤢ button or F key.
"""
import streamlit as st

from components.chat import render_chat
from components.tradingview import tradingview_chart
from tools import gdrive_cache, ibkr_client

st.set_page_config(
    page_title="IBKR Research",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Custom CSS: dark theme + panel layout ---
st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #0f1117;
        color: #e2e8f0;
    }
    [data-testid="stSidebar"] { background-color: #0f1117; }
    header[data-testid="stHeader"] { background-color: #0f1117; }

    .panel-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 10px;
        background: #1a2035;
        border-radius: 6px 6px 0 0;
        margin-bottom: 4px;
    }
    .panel-title {
        font-size: 12px;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .expand-btn-label {
        font-size: 12px;
        color: #64748b;
        cursor: pointer;
    }

    /* Assistant message text: white */
    [data-testid="stChatMessageContent"] p,
    [data-testid="stChatMessageContent"] li,
    [data-testid="stChatMessageContent"] span,
    [data-testid="stChatMessageContent"] td,
    [data-testid="stChatMessageContent"] th {
        color: #ffffff !important;
    }

    /* Status indicators */
    .auth-status {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        padding: 3px 10px;
        border-radius: 12px;
        background: #1e2532;
        margin-right: 8px;
    }
    .auth-status.ok   { border: 1px solid #22c55e; color: #22c55e; }
    .auth-status.warn { border: 1px solid #f59e0b; color: #f59e0b; }
    .auth-status.err  { border: 1px solid #ef4444; color: #ef4444; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Session state ---
if "tv_symbol" not in st.session_state:
    st.session_state.tv_symbol = "AAPL"
if "fullscreen" not in st.session_state:
    st.session_state.fullscreen = None  # None | "chart" | "ai"
if "gdrive_ready" not in st.session_state:
    st.session_state.gdrive_ready = False
if "ibkr_ready" not in st.session_state:
    st.session_state.ibkr_ready = False


# --- Startup auth checks (run once per session) ---
def _check_gdrive():
    try:
        gdrive_cache._get_service()
        st.session_state.gdrive_ready = True
    except Exception:
        st.session_state.gdrive_ready = False


def _check_ibkr():
    st.session_state.ibkr_ready = ibkr_client.ping()


if not st.session_state.gdrive_ready:
    _check_gdrive()
if not st.session_state.ibkr_ready:
    _check_ibkr()


def set_symbol(symbol: str):
    if symbol and symbol != st.session_state.tv_symbol:
        st.session_state.tv_symbol = symbol
        st.rerun()


# --- Top bar ---
top_left, top_right = st.columns([3, 1])
with top_left:
    gdrive_cls = "ok" if st.session_state.gdrive_ready else "err"
    gdrive_label = "● Google Drive" if st.session_state.gdrive_ready else "✕ Google Drive"
    ibkr_cls = "ok" if st.session_state.ibkr_ready else "err"
    ibkr_label = "● IBKR" if st.session_state.ibkr_ready else "✕ IBKR"
    ibkr_hint = "" if st.session_state.ibkr_ready else " — start Docker &amp; auth at https://localhost:5055"

    status_col, retry_col = st.columns([5, 1])
    with status_col:
        st.markdown(
            "<span style='color:#7c3aed;font-weight:bold;font-size:16px'>IBKR Research</span>"
            "<span style='color:#64748b;font-size:12px;margin-left:12px'>Market Data · Analysis · Backtesting</span>"
            "<br/>"
            f"<span class='auth-status {gdrive_cls}'>{gdrive_label}</span>"
            f"<span class='auth-status {ibkr_cls}'>{ibkr_label}{ibkr_hint}</span>",
            unsafe_allow_html=True,
        )
    with retry_col:
        if not st.session_state.ibkr_ready and st.button("↺ Retry IBKR", key="retry_ibkr"):
            _check_ibkr()
            st.rerun()

with top_right:
    mode = st.radio(
        "View",
        options=["Split", "Chart", "AI"],
        horizontal=True,
        label_visibility="collapsed",
        index=["Split", "Chart", "AI"].index(
            st.session_state.get("view_mode", "Split")
        ),
    )
    st.session_state.view_mode = mode

st.divider()

# --- Layout ---
view = st.session_state.get("view_mode", "Split")
panel_height = 680

if view == "Split":
    col_chart, col_ai = st.columns([1, 1], gap="small")

    with col_chart:
        st.markdown(
            f"<div class='panel-header'>"
            f"<span class='panel-title'>TradingView — {st.session_state.tv_symbol}</span>"
            f"<span class='expand-btn-label' title='Switch to Chart view'>⤢</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        tradingview_chart(symbol=st.session_state.tv_symbol, height=panel_height)

    with col_ai:
        st.markdown(
            "<div class='panel-header'>"
            "<span class='panel-title'>Claude AI</span>"
            "<span class='expand-btn-label' title='Switch to AI view'>⤢</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        render_chat(on_symbol_change=set_symbol)

elif view == "Chart":
    st.markdown(
        f"<div class='panel-header'>"
        f"<span class='panel-title'>TradingView — {st.session_state.tv_symbol}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    tradingview_chart(symbol=st.session_state.tv_symbol, height=panel_height + 100)

elif view == "AI":
    st.markdown(
        "<div class='panel-header'>"
        "<span class='panel-title'>Claude AI — Full Screen</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    render_chat(on_symbol_change=set_symbol)
