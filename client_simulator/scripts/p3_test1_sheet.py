"""Test 1: build a blind judging sheet (model names hidden, order shuffled) with automatic checks.
python p3_test1_sheet.py sheet MODEL...  -> results/p3_test1_blind_sheet.md + results/p3_test1_key.json
python p3_test1_sheet.py score           -> joins results/p3_test1_judgement.json with the key -> results/p3_test1_scores.json"""
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CACHE, RESULTS, load_json, read_jsonl, save_json  # noqa: E402
from llm import short
from realism import message_features
from simulator.prompts import POLITE_MARKERS, breaks_role

PFX = os.environ.get("TEST1_PREFIX", "p3")  # p8 = TASK3 small writers
CARD_DESC = {"T1-calm": "calm, correct spelling", "T1-angry": "angry, TYPOS card (should have typos)",
             "T1-formal": "formal, correct spelling"}


def auto_checks(card, first, reply):
    out = {}
    for k, t in (("first", first), ("reply", reply)):
        f = message_features(t)
        low = t.lower()
        out[k] = {"words": f["words"], "assistant_phrase": breaks_role(t),
                  "polite_markers": sum(low.count(p) for p in POLITE_MARKERS),
                  "spelling_error": f["has_spelling_error"], "all_lowercase": f["all_lowercase"],
                  "perfect_on_typos_card": card == "T1-angry" and not f["has_spelling_error"] and not f["all_lowercase"],
                  "too_long": f["words"] > 60}
    return out


def sheet(models):
    rows = {(r["model"], r["item"]): r["text"].strip() for r in read_jsonl(CACHE / "test1.jsonl")}
    items = []
    for m in models:
        for card in CARD_DESC:
            first, reply = rows.get((m, f"{card}:first")), rows.get((m, f"{card}:reply"))
            if first is None:
                continue
            items.append({"model": short(m), "card": card, "first": first, "reply": reply,
                          "auto": auto_checks(card, first, reply)})
    random.Random(7).shuffle(items)
    key = {}
    lines = ["# Test 1 blind sheet (model names hidden; shuffled)\n",
             "Agent turn between the two messages: \"Could you confirm your order number?\"\n"]
    for i, it in enumerate(items):
        code = f"X{i + 1:02d}"
        key[code] = {"model": it["model"], "card": it["card"], "auto": it["auto"], "first": it["first"], "reply": it["reply"]}
        a = it["auto"]
        lines += [f"## {code} - card {it['card']} ({CARD_DESC[it['card']]})",
                  f"**First:** {it['first']}", "", f"**Reply:** {it['reply']}", "",
                  f"auto: first {a['first']}; reply {a['reply']}", ""]
    (RESULTS / f"{PFX}_test1_blind_sheet.md").write_text("\n".join(lines), encoding="utf-8")
    save_json(key, RESULTS / f"{PFX}_test1_key.json")
    print(len(items), "items")


def score():
    key = load_json(RESULTS / f"{PFX}_test1_key.json")
    j = load_json(RESULTS / f"{PFX}_test1_judgement.json")
    per = {}
    for code, v in key.items():
        s = j[code]
        d = per.setdefault(v["model"], {"realism": 0, "role": 0, "cards": {}})
        d["realism"] += s["realism"]
        d["role"] += s["role"]
        d["cards"][v["card"]] = {"code": code, **s}
    save_json({"judged_by": "Claude Code (blind: codes only, shuffled order; automatic checks shown next to each output)",
               "scale": "realism 0-2 and stays-in-role 0-2 per card, 3 cards -> totals 0-6", "per_model": per},
              RESULTS / f"{PFX}_test1_scores.json")
    for m, d in per.items():
        print(m, d["realism"], d["role"])


if __name__ == "__main__":
    sheet(sys.argv[2:]) if sys.argv[1] == "sheet" else score()
