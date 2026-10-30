"""Shared parts of every Atlas Travel page (T22): page setup, the travel style, the sidebar login, small helpers.

The Atlas app is the COMPANY's website (port 8503), built like the ShopNova app. It reads Atlas data for display
(callverse/data/atlas/atlas_app_reads.py) and reaches CallVerse ONLY through the web chat channel (web_chat.send with
company="atlas") and the finance decision (approvals.decide). It never calls an agent itself.

The app starts from app.py (st.navigation). The sidebar menu shows Home · My bookings · Help chat to Atlas users only,
and Admin dashboard · Approvals · Records only to atlas_admin. Hiding is only for comfort: each page checks the role
AND the company first (COMPANY below), and again before each write, so a ShopNova account of any role is refused.
"""

import os
import sys
from pathlib import Path

# Make `import callverse` work when Streamlit starts this app from apps/atlas/.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from callverse.auth import accounts  # noqa: E402
from callverse.tickets import store  # noqa: E402

COMPANY = "atlas"
HELP_PAGE = "pages/2_Help_chat.py"
NAV_FLAG = "_at_navigation"   # set by app.py: the page runs inside the app's navigation (the sidebar menu is drawn)
# The login cookie gets its own name: a browser shares cookies between the apps' ports on 127.0.0.1, and a ShopNova
# login must not be reused here (and the other way round).
COOKIE_SUFFIX = "_atlas"
USER = "user"                 # in MENU: a page for Atlas's clients, not for a permission

# The sidebar menu: (page file, label, icon, url path, USER or the admin permission).
MENU = [
    ("Home.py",                    "Home",            "🏠", "",                USER),
    ("pages/1_My_bookings.py",     "My bookings",     "🧳", "My_bookings",     USER),
    (HELP_PAGE,                    "Help chat",       "💬", "Help_chat",       USER),
    ("pages/3_Admin_dashboard.py", "Admin dashboard", "📊", "Admin_dashboard", "view_dashboard"),
    ("pages/4_Approvals.py",       "Approvals",       "✅", "Approvals",       "approve_refunds"),
    ("pages/5_Records.py",         "Records",         "🗂️", "Records",         "view_dashboard"),
]

# Same as ShopNova's app (T16/T17, T18): Intake + Agent A + SLM local, Agent B on Groq; finance decides in the app.
# setdefault: a value given by the start script (or a test) is kept.
os.environ.setdefault("CALLVERSE_AGENTS_SET", "local")
os.environ.setdefault("CALLVERSE_LAYER3_MODE", "queue")

# The travel look (T22 item 3): sky blue + white + an orange accent, rounded cards, the floating help button.
CSS = """
<style>
.at-logo {font-size: 1.6rem; font-weight: 800; color: #0369A1; margin-bottom: .2rem;}
.at-logo span {color: #F97316;}
.at-hero {background: linear-gradient(120deg, #0EA5E9, #38BDF8); color: white; border-radius: 18px;
          padding: 1.4rem 1.6rem; margin-bottom: 1rem;}
.at-hero h1 {color: white; font-size: 1.7rem; margin: 0;}
.at-hero p {color: #F0F9FF; margin: .3rem 0 0 0;}
.at-amount {font-weight: 700; color: #F97316; font-size: 1.1rem;}
.at-badge {display: inline-block; padding: .1rem .6rem; border-radius: 999px; background: #E0F2FE;
           color: #0369A1; font-size: .8rem; font-weight: 600;}
.at-help {position: fixed; right: 24px; bottom: 24px; z-index: 1000; background: #F97316; color: white !important;
          padding: .7rem 1.1rem; border-radius: 999px; font-weight: 700; text-decoration: none !important;
          box-shadow: 0 6px 18px rgba(3, 105, 161, .25);}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 16px;}
</style>
"""


def setup(title: str) -> dict | None:
    """Set up a page (title, style, sidebar login). Returns the logged-in Atlas USER account, or None."""
    st.set_page_config(page_title=f"{title} · Atlas Travel", page_icon="✈️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.markdown('<div class="at-logo">Atlas Travel <span>✈</span></div>', unsafe_allow_html=True)
        st.caption("Hotel stays in Portugal, flights in the US")
        menu = st.container()   # filled AFTER the login box, so a login or logout shows the right pages at once
    login_box()
    if st.session_state.get(NAV_FLAG):
        with menu:
            for path, label, icon, _, _ in menu_items(st.session_state):
                st.page_link(path, label=label, icon=icon)
    return accounts.check_role(st.session_state, "user", COMPANY)


def menu_items(session) -> list[tuple]:
    """The menu entries this session may see: the client pages for an Atlas user, the admin pages for atlas_admin."""
    def allowed(need: str):
        if need == USER:
            return accounts.check_role(session, "user", COMPANY)
        return accounts.check_permission(session, need, COMPANY)
    return [m for m in MENU if allowed(m[4]) is not None]


def all_pages() -> list:
    """Every page of the app for st.navigation (app.py). ALL are registered, so a typed URL reaches the page and its
    own check shows only "please log in"; the menu shows only the allowed ones."""
    return [st.Page(path, title=label, icon=icon, url_path=url or None, default=(url == ""))
            for path, label, icon, url, _ in MENU]


def user_setup(title: str) -> dict:
    """Set up a client page: the usual setup, then the role + company check (stops the page if it fails)."""
    setup(title)
    st.title(title)
    return accounts.require_role("user", COMPANY)


def admin_setup(title: str, perm: str) -> dict:
    """Set up an admin page: the usual setup, then the permission + company check (stops the page if it fails)."""
    setup(title)
    st.title(title)
    return accounts.require_permission(perm, COMPANY)


def open_ticket(ticket_id: str) -> None:
    """Show this ticket in the Help chat (the "New reply" button)."""
    st.session_state["chat_ticket_id"] = ticket_id
    st.session_state.pop("chat_booking", None)


def unread_notice(user: dict, shown_ticket: str | None = None, switch: bool = False) -> None:
    """"💬 New reply on T-00NN" with a button that opens that ticket (not for the ticket on screen).
    switch = True (My bookings): the button also goes to the Help chat page."""
    for t in store.unread_tickets(COMPANY, user["user_id"]):
        if t["id"] == shown_ticket:
            continue
        note, button = st.columns([4, 1])
        note.info(f"💬 New reply on {t['id']}")
        if button.button("Open", key=f"open_{t['id']}", on_click=open_ticket, args=(t["id"],)) and switch:
            st.switch_page(HELP_PAGE)


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


def help_button() -> None:
    """The floating "Need help? Chat with us" button (a plain link to the Help chat page)."""
    st.markdown('<a class="at-help" href="/Help_chat" target="_self">💬 Need help? Chat with us</a>',
                unsafe_allow_html=True)


def tnd(amount: float) -> str:
    return f"{amount:,.2f} TND"
