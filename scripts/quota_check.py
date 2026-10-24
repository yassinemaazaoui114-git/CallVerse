"""Quota guard (T10b): one tiny real call per agents model, to know BEFORE a long run if the free quotas are there.

Usage (from the repo root):
    python -m scripts.quota_check

Each model of models.agents in config.yaml gets "Say OK." (a few tokens), alone (the backup chain is not
used here). Result per model: OK, DAILY LIMIT (the 429 names a daily quota: stop, do not start a long run),
or another error. Exit code 0 = all OK, 2 = a daily limit, 1 = another problem.

T13: with CALLVERSE_AGENTS_SET=local only the LOCAL test models are checked (no API ping, no quota used);
if CALLVERSE_FORCE_AGENTS_MODEL is also set, only that local model (the one the run will use).
"""

import os
import sys

from callverse import llm, trace
from callverse.config import load_config

FORCE_ENV = "CALLVERSE_FORCE_AGENTS_MODEL"


def models_to_check(cfg: dict) -> list[dict]:
    """Default set: every model of models.agents (as before). Local set: the local models the run will use."""
    if llm.model_set("agents") == "local":
        return llm.models_for("agents", cfg)
    return cfg["models"]["agents"]


def check_models() -> list[dict]:
    """[{model, status: ok | daily_limit | error, detail}] for every agents model to check."""
    results = []
    # T13: keep the caller's forced model. Before, it was removed after the check, so a forced run
    # (e.g. one local candidate alone) silently went back to the full chain.
    forced_before = os.environ.get(FORCE_ENV)
    for entry in models_to_check(load_config()):
        model = entry["model"]
        before = len(llm.DAILY_LIMIT_HITS)
        os.environ[FORCE_ENV] = model
        try:
            llm.chat("agents", [{"role": "user", "content": "Say OK."}])
            status, detail = "ok", ""
        except Exception as e:
            daily = len(llm.DAILY_LIMIT_HITS) > before
            status, detail = ("daily_limit" if daily else "error"), f"{type(e).__name__}: {str(e)[:160]}"
        finally:
            if forced_before is None:
                os.environ.pop(FORCE_ENV, None)
            else:
                os.environ[FORCE_ENV] = forced_before
        results.append({"model": model, "status": status, "detail": detail})
    trace.log("quota_check", "quota", {"results": results})
    return results


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    trace.start_run()
    results = check_models()
    for r in results:
        print(f"{r['model']:<24} {r['status'].upper():<12} {r['detail']}")
    if any(r["status"] == "daily_limit" for r in results):
        print("STOP: a daily limit is reached. Do not start a long run now.")
        sys.exit(2)
    sys.exit(0 if all(r["status"] == "ok" for r in results) else 1)


if __name__ == "__main__":
    main()
