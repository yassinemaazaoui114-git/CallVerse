"""Quota guard (T10b): one tiny real call per agents model, to know BEFORE a long run if the free quotas are there.

Usage (from the repo root):
    python -m scripts.quota_check

Each model of models.agents in config.yaml gets "Say OK." (a few tokens), alone (the backup chain is not
used here). Result per model: OK, DAILY LIMIT (the 429 names a daily quota: stop, do not start a long run),
or another error. Exit code 0 = all OK, 2 = a daily limit, 1 = another problem.

T13: with CALLVERSE_AGENTS_SET=local only the LOCAL test models are checked (no API ping, no quota used);
if CALLVERSE_FORCE_AGENTS_MODEL is also set, only that local model (the one the run will use).

T17: the same check works for any model role (check_models("agent_b") = Agent B's own Groq list, T16), and
stop_at_first_ok=True stops at the first model that answers: the ShopNova chat (callverse/channels/web_chat.py)
only needs to know that B has at least one model left, so it pays for one tiny call, not one per model.
The script itself checks the agents list AND Agent B's list.
"""

import os
import sys

from callverse import llm, trace
from callverse.config import load_config

FORCE_ENV = "CALLVERSE_FORCE_AGENTS_MODEL"


def force_env(role_key: str) -> str:
    """Name of the env var that keeps one model of a role alone (e.g. CALLVERSE_FORCE_AGENT_B_MODEL)."""
    return f"CALLVERSE_FORCE_{role_key.upper()}_MODEL"


def models_to_check(cfg: dict, role_key: str = "agents") -> list[dict]:
    """Default set: every model of models.<role> (as before). Local set: the local models the run will use."""
    if llm.model_set(role_key) == "local":
        return llm.models_for(role_key, cfg)
    return cfg["models"][role_key]


def check_models(role_key: str = "agents", stop_at_first_ok: bool = False) -> list[dict]:
    """[{model, status: ok | daily_limit | error, detail}] for every model of the role to check."""
    results = []
    env = force_env(role_key)
    # T13: keep the caller's forced model. Before, it was removed after the check, so a forced run
    # (e.g. one local candidate alone) silently went back to the full chain.
    forced_before = os.environ.get(env)
    for entry in models_to_check(load_config(), role_key):
        model = entry["model"]
        before = len(llm.DAILY_LIMIT_HITS)
        os.environ[env] = model
        try:
            llm.chat(role_key, [{"role": "user", "content": "Say OK."}])
            status, detail = "ok", ""
        except Exception as e:
            daily = len(llm.DAILY_LIMIT_HITS) > before
            status, detail = ("daily_limit" if daily else "error"), f"{type(e).__name__}: {str(e)[:160]}"
        finally:
            if forced_before is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = forced_before
        results.append({"model": model, "status": status, "detail": detail})
        if stop_at_first_ok and status == "ok":
            break
    trace.log("quota_check", "quota", {"role": role_key, "results": results})
    return results


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
