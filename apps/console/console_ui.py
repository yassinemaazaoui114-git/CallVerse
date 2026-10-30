"""Shared parts of every CallVerse Console page (T19): page setup, the approved style, the sidebar login, the menu.

The Console is the CENTER's own screen (port 8502), for the CallVerse supervisor only: every ticket of every
company, how the agents worked on each one, and the KPIs. It is READ-ONLY: every number comes from
callverse/console/reads.py, which opens callverse.db and the company's data in SQLite read-only mode. It loads no
model and never calls the pipeline (the ShopNova app's chat does that, through the web chat channel).

Every page calls setup(title) first: it draws the sidebar (login + menu) and then require_role("supervisor"), so
an admin, a user or no login sees only "please log in" and nothing else of the page.
"""

import sys
from pathlib import Path

# Make `import callverse` work when Streamlit starts this app from apps/console/.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from callverse.auth import accounts  # noqa: E402

NAV_FLAG = "_cv_navigation"   # set by app.py: the page runs inside the app's navigation (the sidebar menu is drawn)
TICKET_KEY = "console_ticket"  # the ticket the Ticket detail page shows (set by a click on Live tickets)
DETAIL_PAGE = "pages/2_Ticket_detail.py"
# The login cookie gets its own name: the ShopNova app runs on the same host (127.0.0.1), and a browser shares
# cookies between ports, so a ShopNova login must not be reused here (and the other way round).
COOKIE_SUFFIX = "_console"

# The sidebar menu: (page file, label, icon, url path). Every page is for the supervisor only.
MENU = [
    ("pages/1_Live_tickets.py",  "Live tickets",  "📡", ""),
    (DETAIL_PAGE,                "Ticket detail", "🔎", "Ticket_detail"),
    ("pages/3_Agents.py",        "Agents",        "🤖", "Agents"),
    ("pages/4_Dashboard.py",     "Dashboard",     "📊", "Dashboard"),
]

TEAL, TEAL_DARK, AMBER, RED, SLATE = "#2DD4BF", "#0F766E", "#F59E0B", "#F87171", "#94A3B8"

# The approved mock: a dark control room (navy / charcoal), teal accents, compact tables.
CSS = """
<style>
.cv-logo {font-size: 1.45rem; font-weight: 800; color: #E2E8F0; letter-spacing: .02em; margin-bottom: .1rem;}
.cv-logo span {color: #2DD4BF;}
.cv-muted {color: #94A3B8; font-size: .82rem;}
.cv-badge {display: inline-block; padding: .05rem .55rem; border-radius: 999px; background: #134E4A; color: #99F6E4;
           font-size: .78rem; font-weight: 600; margin-right: .25rem;}
.cv-card-line {display: flex; justify-content: space-between; font-size: .88rem; padding: .08rem 0;}
.cv-card-line b {color: #E2E8F0;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 10px;}
div[data-testid="stMetricValue"] {font-size: 1.55rem;}
h1 {font-size: 1.7rem !important;}
</style>
"""


def setup(title: str) -> dict:
    """Set up a Console page (title, style, sidebar login, menu) and check the supervisor login.
    Returns the supervisor account; for anyone else the page shows only "please log in" and stops."""
    st.set_page_config(page_title=f"{title} · CallVerse Console", page_icon="🛰️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.markdown('<div class="cv-logo">CallVerse <span>Console</span></div>', unsafe_allow_html=True)
        st.caption("The center's control room · read only")
        menu = st.container()   # filled AFTER the login box (a login or logout shows the right menu at once)
    login_box()
    if st.session_state.get(NAV_FLAG):
        with menu:
            for path, label, icon, _ in MENU:
                st.page_link(path, label=label, icon=icon)
    st.title(title)
    return accounts.require_role("supervisor")


def all_pages() -> list:
    """Every page for st.navigation (app.py); Live tickets is the start page."""
    return [st.Page(path, title=label, icon=icon, url_path=url or None, default=(url == ""))
            for path, label, icon, url in MENU]


def login_box() -> None:
    """Login / logout in the sidebar (streamlit-authenticator: bcrypt check, a one-day cookie of its own)."""
    auth = accounts.authenticator(COOKIE_SUFFIX)
    if auth is None:
        st.sidebar.info(accounts.NO_ACCOUNTS_MESSAGE)
        return
    if st.session_state.get("authentication_status"):
        found = accounts.account(st.session_state.get("username"))
        st.sidebar.success(f"Hello, {found['name'] if found else st.session_state.get('username')}")
        auth.logout("Log out", location="sidebar")
        return
    try:
        auth.login(location="sidebar", fields={"Form name": "Log in", "Username": "Username",
                                               "Password": "Password", "Login": "Log in"})
    except Exception as e:   # e.g. a broken cookie: show it, never crash the page
        st.sidebar.error(f"Login problem: {type(e).__name__}")
    if st.session_state.get("authentication_status") is False:
        st.sidebar.error("Wrong username or password.")


def period_picker(key: str):
    """The period radio of the Agents and Dashboard pages (default All). Returns the days (None = all)."""
    from callverse.console import reads
    label = st.radio("Period", list(reads.PERIODS), index=0, horizontal=True, key=key)
    return reads.PERIODS[label]


def open_ticket(ticket_id: str) -> None:
    """Show this ticket on the Ticket detail page."""
    st.session_state[TICKET_KEY] = ticket_id


def seconds_text(value) -> str:
    return "—" if value is None else f"{value:.1f} s"
