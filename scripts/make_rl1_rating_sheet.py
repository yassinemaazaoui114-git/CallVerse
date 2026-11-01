"""RL1: the rating sheet for the team. 30 real situations x 3 reply styles, written by the local SLM (0 Groq / API calls).

Usage (repo root; Ollama running):
    python -m scripts.make_rl1_rating_sheet

Where the situations come from: the real tweets of the T14b / T14c practice sets and the T14c held-out set (now spent, used as
dev here: tests/dev/t14b_practice_messages.json, tests/dev/t14c_practice_messages.json, tests/data/t14c_heldout_messages.json).
Their decisions are NOT re-made by agents: the earlier runs (out/t14b_after.json, out/t14c_practice_run1.json,
out/t14c_heldout.json) left a trace file each, with Intake's ticket and the Coordinator's decision (made by rules, from the seeded
orders and bookings). This script reads those two events per message. The off-topic redirect is left out (fixed text, no style).
30 of the rest are kept: when there are more, the script drops the one from the most common kind of decision first.

For each situation the decision is written 3 times with the real local SLM: reply_style short / apology_first / apology_next_step.

Writes (all in out/, git-ignored):
    rl1_rating_sheet.csv  situation_id, company, user message, decision summary, reply A, reply B, reply C
                          (the letters are shuffled per row, seed 2026)
    rl1_rating_key.json   which letter is which style, per situation. NOT in the sheet: the raters must not see it.
    rl1_samples.json      all 90 replies with style, check result, SLM or template, word count, seconds
    rl1_stats.json        per style: check pass rate, average words, share with an apology, seconds per reply
"""

import csv
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from callverse import trace  # noqa: E402
from callverse.pipeline import reply_style as intake_style  # noqa: E402
from callverse.slm import writer  # noqa: E402
from callverse.slm.reply_styles import REPLY_STYLES  # noqa: E402

OUT = ROOT / "out"
SEED = 2026
HOW_MANY = 30
# (messages file, earlier run result file). The run file's summary names the trace of that run.
SOURCES = [("tests/dev/t14b_practice_messages.json", "out/t14b_after.json"),
           ("tests/dev/t14c_practice_messages.json", "out/t14c_practice_run1.json"),
           ("tests/data/t14c_heldout_messages.json", "out/t14c_heldout.json")]
APOLOGY_RE = re.compile(r"sorry|apolog", re.IGNORECASE)


def read_trace(path: str) -> dict[str, dict]:
    """{ticket text: {"ticket": Intake's ticket, "decision": the Coordinator's last decision for it}} from one run's trace."""
    found, current = {}, None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["step"] == "intake_ticket":
            current = event["data"]["text"]
            found[current] = {"ticket": event["data"], "decision": None}
        elif event["step"] == "coordinator_decision" and current is not None:
            found[current]["decision"] = event["data"]   # the last one of the ticket wins (after any send-back)
    return found


def gather() -> list[dict]:
    """Every situation we can use: id, company, text, ticket, decision."""
    out = []
    for messages_file, run_file in SOURCES:
        messages = json.loads((ROOT / messages_file).read_text(encoding="utf-8"))["messages"]
        run = json.loads((ROOT / run_file).read_text(encoding="utf-8"))
        traced = read_trace(run["summary"]["trace"])
        for m in messages:
            item = traced.get(m["text"])
            if not item or not item["decision"]:
                continue
            decision = item["decision"]
            if decision.get("action") == "redirect":
                continue   # fixed text, the style does not apply
            out.append({"id": m["id"], "company": m.get("company", "shopnova"), "text": m["text"],
                        "ticket": item["ticket"], "decision": decision})
    return out


def kind(item: dict) -> tuple:
    d = item["decision"]
    return (item["company"], d["outcome"], d["action"], d.get("rule_id"))


def choose(items: list[dict]) -> list[dict]:
    """Keep HOW_MANY: while there are more, drop the last item of the most common kind (fixed order, no randomness)."""
    items = list(items)
    while len(items) > HOW_MANY:
        common = Counter(kind(i) for i in items).most_common(1)[0][0]
        drop = [i for i in items if kind(i) == common][-1]
        items.remove(drop)
    return items


def summary(item: dict) -> str:
    """One line for the raters: what was decided (the Coordinator's own sentences)."""
    d = item["decision"]
    said = " ".join(d.get("must_say") or []) or d.get("reason", "")
    step = f" Next step: {d['next_step']}" if d.get("next_step") else ""
    return f"[{item['company']} / {d['outcome']}] {said}{step}"


def write_all(items: list[dict]) -> list[dict]:
    samples = []
    for n, item in enumerate(items, 1):
        base = {**item["decision"], "style": intake_style(item["ticket"])}
        for name in REPLY_STYLES:
            start = time.perf_counter()
            result = writer.write_reply({**base, "reply_style": name})   # the real local SLM (role "slm")
            seconds = round(time.perf_counter() - start, 2)
            how = "template" if result["used_template"] else ("slm" if result["attempts"] == 1 else "slm_retry")
            samples.append({"situation_id": item["id"], "company": item["company"], "reply_style": name,
                            "reply": result["reply"], "check_passed": result["check"]["passed"], "source": how,
                            "words": len(result["reply"].split()), "has_apology": bool(APOLOGY_RE.search(result["reply"])),
                            "seconds": seconds})
        print(f"{n}/{len(items)} {item['id']} done", flush=True)
    return samples


def stats(samples: list[dict]) -> dict:
    out = {}
    for name in REPLY_STYLES:
        rows = [s for s in samples if s["reply_style"] == name]
        n = len(rows)
        out[name] = {"replies": n,
                     "check_pass_first_try": round(sum(s["source"] == "slm" and s["check_passed"] for s in rows) / n, 3),
                     "check_pass_after_retry": round(sum(s["source"] == "slm_retry" and s["check_passed"] for s in rows) / n, 3),
                     "template": round(sum(s["source"] == "template" for s in rows) / n, 3),
                     "avg_words": round(sum(s["words"] for s in rows) / n, 1),
                     "max_words": max(s["words"] for s in rows),
                     "with_apology": round(sum(s["has_apology"] for s in rows) / n, 3),
                     "avg_seconds": round(sum(s["seconds"] for s in rows) / n, 2)}
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    trace.start_run("rl1_rating_sheet")
    items = choose(gather())
    print(f"{len(items)} situations:", " ".join(i["id"] for i in items), flush=True)
    print("warm-up:", writer.warm_up(), flush=True)
    samples = write_all(items)

    rng = random.Random(SEED)
    key, rows = {}, []
    for item in items:
        order = list(REPLY_STYLES)
        rng.shuffle(order)   # which style gets letter A, B, C in this row
        key[item["id"]] = dict(zip("ABC", order))
        reply = {s["reply_style"]: s["reply"] for s in samples if s["situation_id"] == item["id"]}
        rows.append([item["id"], item["company"], item["text"], summary(item)] + [reply[key[item["id"]][c]] for c in "ABC"])

    with open(OUT / "rl1_rating_sheet.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer_csv = csv.writer(f)
        writer_csv.writerow(["situation_id", "company", "user_message", "decision", "reply_A", "reply_B", "reply_C"])
        writer_csv.writerows(rows)
    (OUT / "rl1_rating_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    (OUT / "rl1_samples.json").write_text(json.dumps(samples, indent=1, ensure_ascii=False), encoding="utf-8")
    result = stats(samples)
    (OUT / "rl1_stats.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
