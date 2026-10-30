"""Demo logins and roles (T17): who is logged in, and may they do this?

- The accounts live in config/accounts.yaml (git-ignored): streamlit-authenticator's format, passwords as
  bcrypt HASHES only. Yassine creates it himself with scripts/create_demo_accounts.py; Claude Code never sees
  a password. config/accounts.example.yaml (committed) shows the same accounts without any password.
- Roles (docs/ui_design.md section 4): user (a company's client), admin (a company's back office, T18), supervisor
  (Console, T19). Each "user" account is linked to its user id in its company's data (sara -> 1 ... leila -> 5,
  hedi -> 1 ... nizar -> 5: the same numbers, two different databases).
- T22: every account has a company (shopnova / atlas; the supervisor has none: it serves the whole center). Each app
  says which company it is, and an account of another company is refused: ShopNova's admin can never approve an Atlas
  case, and Sara (user 1) can never see the bookings of Hedi (user 1 too). No company in an old accounts file = shopnova.
- require_role(role) is called at the top of every protected page AND again just before every write, so a
  hidden button is never the only protection. T18: admin pages use require_permission(perm) the same way.
- The role and the user id always come from the accounts FILE (looked up by the logged-in username), never
  from something the browser could change.
"""

import copy
from pathlib import Path

import yaml

from callverse import companies
from callverse.config import PROJECT_ROOT

DEFAULT_ACCOUNTS_PATH = PROJECT_ROOT / "config" / "accounts.yaml"
EXAMPLE_PATH = PROJECT_ROOT / "config" / "accounts.example.yaml"
_accounts_path = DEFAULT_ACCOUNTS_PATH

ROLES = ("user", "admin", "supervisor")
# T18 (option A, docs/ui_design.md section 4): what each role may do in the ShopNova back office, checked PER ACTION,
# so a separate finance role can be added later in a few lines. user and supervisor: none of these.
PERMISSIONS = {"admin": ("view_dashboard", "edit_catalogue", "edit_orders", "edit_users", "approve_refunds")}
ALL_PERMISSIONS = tuple(sorted({p for perms in PERMISSIONS.values() for p in perms}))
LOGIN_MESSAGE = "Please log in to see this page."
NO_ACCOUNTS_MESSAGE = "No accounts yet: run `python -m scripts.create_demo_accounts` once (see README)."

# The demo accounts: (username, name, email, role, user id). The users are the scripted users 1-5 of their company.
DEMO_ACCOUNTS = [
    ("sara",       "Sara Ben Ali",       "sara@example.com",    "user",       1),
    ("youssef",    "Youssef Trabelsi",   "youssef@example.com", "user",       2),
    ("amira",      "Amira Gharbi",       "amira@example.com",   "user",       3),
    ("karim",      "Karim Jaziri",       "karim@example.com",   "user",       4),
    ("leila",      "Leila Mansour",      "leila@example.com",   "user",       5),
    ("admin",      "ShopNova Admin",     None,                  "admin",      None),
    ("supervisor", "CallVerse Supervisor", None,                "supervisor", None),
    ("hedi",       "Hedi Karoui",        "hedi@example.com",    "user",       1),      # T22: Atlas Travel's accounts
    ("sonia",      "Sonia Belhaj",       "sonia@example.com",   "user",       2),
    ("tarek",      "Tarek Mzali",        "tarek@example.com",   "user",       3),
    ("lobna",      "Lobna Cherif",       "lobna@example.com",   "user",       4),
    ("nizar",      "Nizar Haddad",       "nizar@example.com",   "user",       5),
    ("atlas_admin", "Atlas Admin",       None,                  "admin",      None),
]
ATLAS_ACCOUNTS = ("hedi", "sonia", "tarek", "lobna", "nizar", "atlas_admin")   # T22


def demo_company(username: str, role: str) -> str | None:
    """The company a NEW demo account gets (the account script writes it in the file)."""
    if role == "supervisor":
        return None
    return "atlas" if username in ATLAS_ACCOUNTS else companies.DEFAULT


def use_accounts(path: str | Path) -> None:
    """Point the app at another accounts file (used by the tests)."""
    global _accounts_path
    _accounts_path = Path(path)


def accounts_path() -> Path:
    return _accounts_path


def load_accounts() -> dict | None:
    """The whole accounts file as a dict, or None if it does not exist yet (read on every call: small file)."""
    if not _accounts_path.exists():
        return None
    return yaml.safe_load(_accounts_path.read_text(encoding="utf-8"))


def account(username: str | None) -> dict | None:
    """{username, name, role, user_id} of one account, or None. Never returns the password hash."""
    data = load_accounts()
    entry = (data or {}).get("credentials", {}).get("usernames", {}).get(username) if username else None
    if not entry:
        return None
    roles = entry.get("roles") or []
    return {"username": username, "name": entry.get("name"), "role": roles[0] if roles else None,
            "user_id": entry.get("user_id")}


def company_of(found: dict) -> str | None:
    """The company of an account given by account(), from the file. The supervisor has none; no company in an old
    file = shopnova."""
    if found["role"] == "supervisor":
        return None
    return load_accounts()["credentials"]["usernames"][found["username"]].get("company") or companies.DEFAULT


def _in_company(found: dict, company: str) -> bool:
    """True if this account belongs to the app's company. The supervisor serves the whole center."""
    return found["role"] == "supervisor" or company_of(found) == company


def check_role(session, role: str, company: str = companies.DEFAULT) -> dict | None:
    """The logged-in account if it has `role` in the app's `company`, else None. session = st.session_state (or a
    dict in tests). Logged in = streamlit-authenticator set authentication_status True after a password (or cookie)
    check.
    """
    if role not in ROLES:
        raise ValueError(f"unknown role '{role}' (allowed: {', '.join(ROLES)})")
    if session.get("authentication_status") is not True:
        return None
    found = account(session.get("username"))
    if found is None or found["role"] != role or not _in_company(found, company):
        return None
    if role == "user" and not isinstance(found["user_id"], int):
        return None   # a client account must be linked to a user of its company
    return found


def require_role(role: str, company: str = companies.DEFAULT) -> dict:
    """For Streamlit pages: the logged-in account with `role` in `company`, or show only "please log in" and stop."""
    import streamlit as st
    found = check_role(st.session_state, role, company)
    if found is None:
        st.info(LOGIN_MESSAGE if load_accounts() is not None else NO_ACCOUNTS_MESSAGE)
        st.stop()
    return found


def check_permission(session, perm: str, company: str = companies.DEFAULT) -> dict | None:
    """The logged-in account if its role has permission `perm` (PERMISSIONS above) in the app's `company`, else
    None (T18)."""
    if perm not in ALL_PERMISSIONS:
        raise ValueError(f"unknown permission '{perm}' (allowed: {', '.join(ALL_PERMISSIONS)})")
    if session.get("authentication_status") is not True:
        return None
    found = account(session.get("username"))
    if found is None or perm not in PERMISSIONS.get(found["role"], ()) or not _in_company(found, company):
        return None
    return found


def require_permission(perm: str, company: str = companies.DEFAULT) -> dict:
    """For Streamlit pages: the logged-in account with `perm` in `company`, or show only "please log in" and stop.
    Called at the top of every admin page AND again just before every admin write."""
    import streamlit as st
    found = check_permission(st.session_state, perm, company)
    if found is None:
        st.info(LOGIN_MESSAGE if load_accounts() is not None else NO_ACCOUNTS_MESSAGE)
        st.stop()
    return found


def authenticator(cookie_name_suffix: str = ""):
    """The streamlit-authenticator object built from the accounts file, or None if there is no file yet."""
    data = load_accounts()
    if data is None:
        return None
    import streamlit_authenticator as stauth
    cookie = data.get("cookie", {})
    # deepcopy: the library may change the dict it gets (e.g. failed login counters); the file stays as it is.
    return stauth.Authenticate(copy.deepcopy(data["credentials"]),
                               cookie_name=cookie.get("name", "callverse_auth") + cookie_name_suffix,
                               cookie_key=cookie["key"], cookie_expiry_days=cookie.get("expiry_days", 1),
                               auto_hash=False)
