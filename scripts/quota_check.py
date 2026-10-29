"""Quota guard (T10b): one tiny real call per agents model, to know BEFORE a long run if the free quotas are there.

Usage (from the repo root):
    python -m scripts.quota_check

Each model of models.agents in config.yaml gets "Say OK." (a few tokens), alone (the backup chain is not
used here). Result per model: OK, DAILY LIMIT (the 429 names a daily quota: stop, do not start a long run),
or another error. Exit code 0 = all OK, 2 = a daily limit, 1 = another problem.

T13: with CALLVERSE_AGENTS_SET=local only the LOCAL test models are checked (no API ping, no quota used);
if CALLVERSE_FORCE_AGENTS_MODEL is also set, only that local model (the one the run will use).

T17: the script checks the agents list AND Agent B's own list (agent_b, T16). The check itself is in
callverse/quota.py (T17 follow-up, Q6), also used by the ShopNova chat (callverse/channels/web_chat.py).
"""

import os  # noqa: F401  (kept: the tests check os.environ through this module)
import sys

from callverse import llm, trace  # noqa: F401  (kept: the tests replace llm.chat / trace.log through this module)
# T17 follow-up (Q6): the logic lives in callverse/quota.py; this script only prints its results.
from callverse.quota import check_models, force_env, models_to_check  # noqa: F401

FORCE_ENV = "CALLVERSE_FORCE_AGENTS_MODEL"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    trace.start_run()
    results = []
    for role_key in ("agents", "agent_b"):
        print(f"[{role_key}]")
        role_results = check_models(role_key)
        results += role_results
        for r in role_results:
            print(f"{r['model']:<24} {r['status'].upper():<12} {r['detail']}")
    if any(r["status"] == "daily_limit" for r in results):
        print("STOP: a daily limit is reached. Do not start a long run now.")
        sys.exit(2)
    sys.exit(0 if all(r["status"] == "ok" for r in results) else 1)


if __name__ == "__main__":
    main()
