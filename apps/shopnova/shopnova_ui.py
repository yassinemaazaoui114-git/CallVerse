"""Shared parts of every ShopNova page (T17): page setup, the approved style, the sidebar login, small helpers.

The ShopNova app is the COMPANY's website (port 8501). It reads ShopNova data for display
(callverse/data/shop_reads.py), buys through writes.create_order, and reaches CallVerse ONLY through the
web chat channel (callverse/channels/web_chat.py). It never calls an agent itself.

T18: the app starts from app.py (st.navigation). The sidebar menu shows Home · Shop · My orders · Help chat to
everyone and the admin pages (Admin dashboard · Manage · Refund approvals) only to an account with their
permission. Hiding is only for comfort: each admin page calls require_permission first and again before writes.
"""

import os
import sys
from pathlib import Path

# Make `import callverse` work when Streamlit starts this app from apps/shopnova/.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from callverse.auth import accounts  # noqa: E402
from callverse.tickets import store  # noqa: E402

COMPANY = "shopnova"
HELP_PAGE = "pages/3_Help_chat.py"
NAV_FLAG = "_sn_navigation"   # set by app.py: the page runs inside the app's navigation (the sidebar menu is drawn)

# The sidebar menu (T18): (page file, label, icon, url path, permission or None = everyone).
MENU = [
    ("Home.py",                     "Home",             "🏠", "",                 None),
    ("pages/1_Shop.py",             "Shop",             "🛍️", "Shop",             None),
    ("pages/2_My_orders.py",        "My orders",        "📦", "My_orders",        None),
    (HELP_PAGE,                     "Help chat",        "💬", "Help_chat",        None),
    ("pages/4_Admin_dashboard.py",  "Admin dashboard",  "📊", "Admin_dashboard",  "view_dashboard"),
    ("pages/5_Manage.py",           "Manage",           "🗂️", "Manage",           "view_dashboard"),
    ("pages/6_Refund_approvals.py", "Refund approvals", "✅", "Refund_approvals", "approve_refunds"),
]

# T16/T17 item 8: Intake + Agent A + SLM run locally, Agent B stays on Groq (its own model list).
# setdefault: a value given by the start script (or a test) is kept.
os.environ.setdefault("CALLVERSE_AGENTS_SET", "local")
# T18: in the app, refunds above 300 TND wait for the ShopNova admin (the real Layer 3 queue), not the stub.
os.environ.setdefault("CALLVERSE_LAYER3_MODE", "queue")

# The approved mock: warm and light (cream, navy, coral), rounded cards, the floating help button.
CSS = """
<style>
.sn-logo {font-size: 1.6rem; font-weight: 800; color: #1F2A44; margin-bottom: .2rem;}
.sn-logo span {color: #FF6B4A;}
.sn-hero {background: #1F2A44; color: #FBF7F2; border-radius: 18px; padding: 1.4rem 1.6rem; margin-bottom: 1rem;}
.sn-hero h1 {color: #FBF7F2; font-size: 1.7rem; margin: 0;}
.sn-hero p {color: #F3ECE3; margin: .3rem 0 0 0;}
.sn-card-icon {font-size: 2.2rem; line-height: 1;}
.sn-price {font-weight: 700; color: #FF6B4A; font-size: 1.1rem;}
.sn-muted {color: #6B7280; font-size: .85rem;}
.sn-badge {display: inline-block; padding: .1rem .6rem; border-radius: 999px; background: #F3ECE3;
           color: #1F2A44; font-size: .8rem; font-weight: 600;}
.sn-help {position: fixed; right: 24px; bottom: 24px; z-index: 1000; background: #FF6B4A; color: white !important;
          padding: .7rem 1.1rem; border-radius: 999px; font-weight: 700; text-decoration: none !important;
          box-shadow: 0 6px 18px rgba(31, 42, 68, .25);}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 16px;}
</style>
"""


def setup(title: str) -> dict | None:
    """Set up a page (title, style, sidebar login). Returns the logged-in USER account, or None."""
    st.set_page_config(page_title=f"{title} · ShopNova", page_icon="✦", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.markdown('<div class="sn-logo">ShopNova <span>✦</span></div>', unsafe_allow_html=True)
        st.caption("Electronics, delivered across Tunisia")
        menu = st.container()   # filled AFTER the login box, so a login or logout shows the right pages at once
    login_box()
    if st.session_state.get(NAV_FLAG):
        with menu:
            for path, label, icon, _, perm in menu_items(st.session_state):
                st.page_link(path, label=label, icon=icon)
    return accounts.check_role(st.session_state, "user")


def menu_items(session) -> list[tuple]:
    """The menu entries this session may see: everyone's pages, plus the admin pages it has the permission for."""
    return [m for m in MENU if m[4] is None or accounts.check_permission(session, m[4]) is not None]


def all_pages() -> list:
    """Every page of the app for st.navigation (app.py). ALL are registered, so a typed URL of an admin page
    reaches that page and its require_permission shows only "please log in"; the menu shows only allowed ones."""
    return [st.Page(path, title=label, icon=icon, url_path=url or None, default=(url == ""))
            for path, label, icon, url, _ in MENU]


def admin_setup(title: str, perm: str) -> dict:
    """Set up an admin page: the usual setup, then the permission check (stops the page if it fails)."""
    setup(title)
    st.title(title)
    return accounts.require_permission(perm)


def open_ticket(ticket_id: str) -> None:
    """Show this ticket in the Help chat (the "New reply" button)."""
    st.session_state["chat_ticket_id"] = ticket_id
    st.session_state.pop("chat_order", None)


def unread_notice(user: dict, shown_ticket: str | None = None, switch: bool = False) -> None:
    """T18 item 17: "💬 New reply on T-00NN" with a button that opens that ticket (not for the ticket on screen).
    switch = True (My orders): the button also goes to the Help chat page."""
    for t in store.unread_tickets(COMPANY, user["user_id"]):
        if t["id"] == shown_ticket:
            continue
        note, button = st.columns([4, 1])
        note.info(f"💬 New reply on {t['id']}")
        if button.button("Open", key=f"open_{t['id']}", on_click=open_ticket, args=(t["id"],)) and switch:
            st.switch_page(HELP_PAGE)


def login_box() -> None:
    """Login / logout in the sidebar (streamlit-authenticator: bcrypt check, a one-day cookie)."""
    auth = accounts.authenticator()
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
    st.markdown('<a class="sn-help" href="/Help_chat" target="_self">💬 Need help? Chat with us</a>',
                unsafe_allow_html=True)


def tnd(amount: float) -> str:
    return f"{amount:,.2f} TND"
