"""Create the demo logins (T17): writes config/accounts.yaml (git-ignored). Run it YOURSELF, in your own terminal.

Usage (from the repo root, with the .venv active):
    python -m scripts.create_demo_accounts

For each account (sara, youssef, amira, karim, leila, admin, supervisor) you either type a password twice
(hidden, nothing is shown) or press Enter to get a random one, shown ONCE on the screen: note it down.
Only the bcrypt HASH of each password is written to the file; the passwords themselves are never stored.
Also writes a random cookie key (keeps you logged in for one day in the browser).
Claude Code never runs this script and never sees the passwords.
"""

import getpass
import secrets
import sys

import bcrypt
import yaml

from callverse.auth.accounts import DEFAULT_ACCOUNTS_PATH, DEMO_ACCOUNTS

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


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    path = DEFAULT_ACCOUNTS_PATH
    if path.exists() and input(f"{path} already exists. Replace it? (yes/no): ").strip().lower() != "yes":
        print("Nothing changed.")
        return

    usernames, shown = {}, []
    for username, name, email, role, user_id in DEMO_ACCOUNTS:
        password, random_one = ask_password(username)
        usernames[username] = {"name": name, "email": email, "roles": [role], "user_id": user_id,
                               "password": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()}
        if random_one:
            shown.append((username, password))

    data = {"credentials": {"usernames": usernames},
            "cookie": {"name": "callverse_auth", "key": secrets.token_hex(32), "expiry_days": 1}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Demo accounts (T17). Git-ignored. Passwords are bcrypt hashes only.\n"
                    + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Written: {path} ({len(usernames)} accounts)")
    if shown:
        print("Random passwords (shown once, note them now):")
        for username, password in shown:
            print(f"  {username:<11} {password}")


if __name__ == "__main__":
    main()
