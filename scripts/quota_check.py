"""Quota guard (T10b): one tiny real call per agents model, to know BEFORE a long run if the free quotas are there.

Usage (from the repo root):
    python -m scripts.quota_check

Each model of models.agents in config.yaml gets "Say OK." (a few tokens), alone (the backup chain is not
used here). Result per model: OK, DAILY LIMIT (the 429 names a daily quota: stop, do not start a long run),
or another error. Exit code 0 = all OK, 2 = a daily limit, 1 = another problem.
"""

import os
import sys

from callverse import llm, trace
from callverse.config import load_config


def check_models() -> list[dict]:
    """[{model, status: ok | daily_limit | error, detail}] for every agents model."""
    results = []
    for entry in load_config()["models"]["agents"]:
        model = entry["model"]
        before = len(llm.DAILY_LIMIT_HITS)
        os.environ["CALLVERSE_FORCE_AGENTS_MODEL"] = model
        try:
            llm.chat("agents", [{"role": "user", "content": "Say OK."}])
            status, detail = "ok", ""
        except Exception as e:
            daily = len(llm.DAILY_LIMIT_HITS) > before
            status, detail = ("daily_limit" if daily else "error"), f"{type(e).__name__}: {str(e)[:160]}"
        finally:
            os.environ.pop("CALLVERSE_FORCE_AGENTS_MODEL", None)
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
