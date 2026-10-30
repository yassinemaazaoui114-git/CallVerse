"""Create the demo logins (T17): writes config/accounts.yaml (git-ignored). Run it YOURSELF, in your own terminal.

Usage (from the repo root, with the .venv active):
    python -m scripts.create_demo_accounts

T22: when config/accounts.yaml already exists, only the MISSING accounts are added (a password is asked for those
only), every existing hash and the cookie key are kept, and the old entries get their company. So this is safe to
run again, e.g. once to add the 6 Atlas accounts (hedi, sonia, tarek, lobna, nizar, atlas_admin).

For each new account you either type a password twice (hidden, nothing is shown) or press Enter to get a random
one, shown ONCE on the screen: note it down.
Only the bcrypt HASH of each password is written to the file; the passwords themselves are never stored.
A new file also gets a random cookie key (keeps you logged in for one day in the browser).
Claude Code never runs this script with real passwords and never sees them.
"""

import getpass
import secrets
import sys
from pathlib import Path

import bcrypt
import yaml

from callverse.auth.accounts import DEFAULT_ACCOUNTS_PATH, DEMO_ACCOUNTS, demo_company

MIN_LENGTH = 8


def ask_password(username: str) -> tuple[str, bool]:
    """(password, was_random). Empty input = a random password."""
    while True:
        first = getpass.getpass(f"Password for {username} (Enter = random): ")
        if not first:
            return secrets.token_urlsafe(9), True
        if len(first) < MIN_LENGTH:
            print(f"  At least {MIN_LENGTH} characters, please.")
            continue
        if getpass.getpass("  Type it again: ") == first:
            return first, False
        print("  The two passwords are different, try again.")


def add_missing(data: dict, ask=ask_password) -> tuple[list[str], list[tuple[str, str]]]:
    """Add the demo accounts that are not in `data` yet, and the company of the old entries. An existing entry keeps
    its hash. Returns (usernames added, [(username, random password shown once)])."""
    usernames, added, shown = data["credentials"]["usernames"], [], []
    for username, name, email, role, user_id in DEMO_ACCOUNTS:
        company = demo_company(username, role)
        if username in usernames:
            usernames[username].setdefault("company", company)
            continue
        password, random_one = ask(username)
        usernames[username] = {"name": name, "email": email, "roles": [role], "user_id": user_id, "company": company,
                               "password": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()}
        added.append(username)
        if random_one:
            shown.append((username, password))
    return added, shown


def load_or_new(path: Path) -> dict:
    """The existing accounts file, or a new empty one with a random cookie key."""
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    return {"credentials": {"usernames": {}},
            "cookie": {"name": "callverse_auth", "key": secrets.token_hex(32), "expiry_days": 1}}


def main(path: Path = DEFAULT_ACCOUNTS_PATH, ask=ask_password) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    data = load_or_new(path)
    added, shown = add_missing(data, ask)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Demo accounts (T17). Git-ignored. Passwords are bcrypt hashes only.\n"
                    + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Written: {path} ({len(data['credentials']['usernames'])} accounts, {len(added)} new)")
    if shown:
        print("Random passwords (shown once, note them now):")
        for username, password in shown:
            print(f"  {username:<11} {password}")


if __name__ == "__main__":
    main()
