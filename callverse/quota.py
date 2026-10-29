"""Quota guard (T10b, moved here from scripts/quota_check.py in the T17 follow-up, Q6): one tiny real call per
model of a role ("Say OK.", a few tokens), to know BEFORE work starts if the free quotas are there.

- check_models(role_key) checks every model of models.<role> in config.yaml, each one alone (the backup chain
  is not used here). Result per model: ok, daily_limit (the 429 names a daily quota) or error.
- T13: with CALLVERSE_<ROLE>_SET=local only the LOCAL test models are checked (no API ping, no quota used);
  if CALLVERSE_FORCE_<ROLE>_MODEL is also set, only that model (the one the run will use), and it is kept.
- T17: stop_at_first_ok=True stops at the first model that answers: the ShopNova chat
  (callverse/channels/web_chat.py) only needs to know that Agent B has at least one model left.
- T17 follow-up (Q5): each result also says how many tokens its ping used (read from the llm_call trace line),
  so the chat can save them as SYSTEM tokens, not counted in any ticket.

Users: scripts/quota_check.py (before a long run) and the web chat channel.
"""

import os

from callverse import llm, trace
from callverse.config import load_config


def force_env(role_key: str) -> str:
    """Name of the env var that keeps one model of a role alone (e.g. CALLVERSE_FORCE_AGENT_B_MODEL)."""
    return f"CALLVERSE_FORCE_{role_key.upper()}_MODEL"


def models_to_check(cfg: dict, role_key: str = "agents") -> list[dict]:
    """Default set: every model of models.<role> (as before). Local set: the local models the run will use."""
    if llm.model_set(role_key) == "local":
        return llm.models_for(role_key, cfg)
    return cfg["models"][role_key]


def check_models(role_key: str = "agents", stop_at_first_ok: bool = False) -> list[dict]:
    """[{model, provider, status: ok | daily_limit | error, detail, tokens}] for every model of the role to check."""
    results = []
    env = force_env(role_key)
    # T13: keep the caller's forced model. Before, it was removed after the check, so a forced run
    # (e.g. one local candidate alone) silently went back to the full chain.
    forced_before = os.environ.get(env)
    for entry in models_to_check(load_config(), role_key):
        model = entry["model"]
        before = len(llm.DAILY_LIMIT_HITS)
        used = []   # total tokens of this ping, from its llm_call trace line

        def count(record):
            if record["step"] == "llm_call":
                used.append((record["data"].get("tokens") or {}).get("total") or 0)

        os.environ[env] = model
        trace.add_listener(count)
        try:
            llm.chat(role_key, [{"role": "user", "content": "Say OK."}])
            status, detail = "ok", ""
        except Exception as e:
            daily = len(llm.DAILY_LIMIT_HITS) > before
            status, detail = ("daily_limit" if daily else "error"), f"{type(e).__name__}: {str(e)[:160]}"
        finally:
            trace.remove_listener(count)
            if forced_before is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = forced_before
        results.append({"model": model, "provider": entry.get("provider"), "status": status, "detail": detail,
                        "tokens": sum(used)})
        if stop_at_first_ok and status == "ok":
            break
    trace.log("quota_check", "quota", {"role": role_key, "results": results})
    return results
