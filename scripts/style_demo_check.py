"""T33: style policy demo check. 5 demo messages, each run twice: style policy OFF, then ON. Yassine reads the replies
side by side and decides ON or OFF for the demo.

Usage (from the repo root; Ollama running, local models):
    set CALLVERSE_AGENTS_SET=local
    python -m scripts.style_demo_check

What it does, for each message:
  1. fresh ShopNova + Atlas data and clock (scripts.run_t14c.run_one: the same door as the apps, web_chat.send);
  2. run with the policy OFF (config.yaml as it is: learning.style_policy false);
  3. fresh data again, run with the policy ON. The switch is turned on ONLY inside this process: the loaded config is
     patched in memory, config.yaml is never changed. The policy is the one trained on REAL ratings
     (out/rl5_policy.json, T31). Its random draw uses a fixed seed, so a re-run picks the same style;
  4. compare the decision the reply writer got in both runs: every key except reply_style must be the same.
The checks of run_t14c (no crash, no leak, no wrong write) run on every reply.

Tickets go to their own file (out/t33_tickets.db, deleted at the end), so callverse.db is not touched.
Output: out/t33_style_demo.md (side by side) and out/t33_style_demo.json (everything).
"""

import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from callverse import pipeline, trace  # noqa: E402
from callverse.config import load_config  # noqa: E402
from callverse.intake import intake  # noqa: E402
from callverse.slm.writer import warm_up  # noqa: E402
from callverse.tickets import store  # noqa: E402
from scripts import run_t14c  # noqa: E402

OUT = ROOT / "out"
TICKETS_DB = OUT / "t33_tickets.db"
POLICY_FILE = "out/rl5_policy.json"   # trained on the team's REAL ratings (T31)
SEED = 33

# The 5 messages. Demo flows from docs/DEMO_RUNBOOK.md where one fits (F4, F3); the demo has no decline and no angry
# message, so those come from the practice (dev) sets, never from tests/data (locked). The only Atlas "ask" message
# we have is in a locked set, so the Atlas compensation flow F3 (waits for the admin) takes that place.
MESSAGES = [
    {"id": "F4", "label": "ShopNova status (demo F4, amira)", "company": "shopnova", "user_id": 3, "order_id": 4511,
     "text": "Hi, where is my order 4511?"},
    {"id": "t05", "label": "ShopNova decline (dev decline_practice t05)", "company": "shopnova", "user_id": 2,
     "order_id": 4510, "text": "what happened to my order 4510? Refund if you can't deliver"},
    {"id": "p06", "label": "Angry client (dev t14b_practice p06)", "company": "shopnova", "user_id": 1, "order_id": 4512,
     "text": "I FUCKING HATE YOU THIS IS THE THIRD TIME IN A ROW YOU ARE LATE WITH ONE OF MY PACKAGES Order 4512."},
    {"id": "a07", "label": "Atlas decline (dev t14c_practice a07)", "company": "atlas", "user_id": 2, "booking_id": 7002,
     "text": "I cancelled booking 7002 and I want my money back."},
    {"id": "F3", "label": "Atlas compensation, waits for the admin (demo F3, nizar)", "company": "atlas", "user_id": 5,
     "booking_id": 7004, "text": "My flight 7004 was very delayed. I want compensation."},
]

seen: list[dict] = []   # what policy_style got and gave, one entry per call (filled by the wrapper below)
original_policy_style = pipeline.policy_style


def recording_policy_style(ticket, said, rng=None):
    """Wraps pipeline.policy_style: same result, plus a record of the decision before and after, and a fixed seed."""
    out, chosen = original_policy_style(ticket, said, random.Random(SEED))
    seen.append({"before": copy.deepcopy(said), "after": copy.deepcopy(out),
                 "style": out.get("reply_style"), "group": (chosen or {}).get("group")})
    return out, chosen


def without_style(decision: dict) -> dict:
    return {k: v for k, v in decision.items() if k != "reply_style"}


def run(message: dict, on: bool) -> dict:
    """One message with the policy OFF or ON. The config is patched in memory only."""
    cfg = copy.deepcopy(load_config())
    if on:
        cfg["learning"] = {**cfg.get("learning", {}), "style_policy": True, "style_policy_file": POLICY_FILE}
    pipeline.load_config = lambda: cfg
    random.seed(SEED)
    seen.clear()
    try:
        result = run_t14c.run_one({**message, "expect": {}})
    finally:
        pipeline.load_config = load_config
    call = seen[-1] if seen else {}
    return {**result, "style": call.get("style"), "group": call.get("group"),
            "decision": without_style(call.get("after") or {}),
            "only_style_changed": bool(call) and without_style(call["after"]) == without_style(call["before"])}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    TICKETS_DB.unlink(missing_ok=True)
    store.use_db(TICKETS_DB)
    trace_path = trace.start_run()
    intake.load_models()
    warm = warm_up()
    if not warm["ok"]:
        print(f"Warning: {warm['warning']} ({warm['error']})")
    pipeline.policy_style = recording_policy_style

    rows = []
    for m in MESSAGES:
        off, on = run(m, on=False), run(m, on=True)
        same = off["decision"] == on["decision"]
        rows.append({"message": m, "off": off, "on": on, "decision_unchanged": same})
        print(f"{m['id']:<4} group={on['group']} style={on['style']} decision unchanged={'yes' if same else 'NO'} "
              f"OFF {off['seconds']} s / ON {on['seconds']} s  problems OFF={off['problems']} ON={on['problems']}",
              flush=True)

    runs = [r[k] for r in rows for k in ("off", "on")]
    count = lambda word: sum(any(p.startswith(word) for p in r["problems"]) for r in runs)
    avg = lambda k: round(sum(r[k]["seconds"] for r in rows) / len(rows), 1)
    summary = {"messages": len(rows), "decisions_unchanged": sum(r["decision_unchanged"] for r in rows),
               "policy_changed_only_style": sum(r["on"]["only_style_changed"] for r in rows),
               "wrong_writes": count("WRONG WRITE"), "leaks": count("internal words"), "crashes": count("CRASH"),
               "groq_tokens": sum(r["groq_tokens"] for r in runs), "avg_seconds_off": avg("off"),
               "avg_seconds_on": avg("on"), "policy_file": POLICY_FILE, "trace": str(trace_path)}

    lines = ["# T33 — style policy OFF vs ON on 5 demo messages", "",
             f"Policy: `{POLICY_FILE}` (trained on REAL ratings). Local models. Seed {SEED}. config.yaml stays OFF.", "",
             f"Decisions unchanged: **{summary['decisions_unchanged']}/{len(rows)}** · policy changed only the style: "
             f"{summary['policy_changed_only_style']}/{len(rows)} · wrong writes {summary['wrong_writes']} · leaks "
             f"{summary['leaks']} · crashes {summary['crashes']} · Groq tokens {summary['groq_tokens']} · avg reply time "
             f"OFF {summary['avg_seconds_off']} s, ON {summary['avg_seconds_on']} s", ""]
    for r in rows:
        m, off, on = r["message"], r["off"], r["on"]
        lines += [f"## {m['id']} — {m['label']}", "", f"**Client:** {m['text']}", "",
                  f"- Group: `{on['group']}` · style chosen: **{on['style']}** · outcome: {on['outcome']} · "
                  f"decision unchanged: **{'yes' if r['decision_unchanged'] else 'NO'}**",
                  f"- Time: OFF {off['seconds']} s, ON {on['seconds']} s · reply source: OFF {off['reply_source']}, "
                  f"ON {on['reply_source']}", "",
                  f"**OFF:** {off['reply']}", "", f"**ON ({on['style']}):** {on['reply']}", ""]
        if off["problems"] or on["problems"]:
            lines += [f"Problems: OFF {off['problems']} · ON {on['problems']}", ""]
    (OUT / "t33_style_demo.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "t33_style_demo.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1,
                                                        ensure_ascii=False, default=str), encoding="utf-8")
    print("\n" + "\n".join(lines[:5]))
    print(f"Saved out/t33_style_demo.md and .json   Trace: {trace_path}")
    store.use_db(store.DEFAULT_DB_PATH)
    TICKETS_DB.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
