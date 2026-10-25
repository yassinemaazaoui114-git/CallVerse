"""Run the REAL prototype Intake (local models only, no API) on a few written test messages and save the tickets.

    python -m v4.d.make_intake_fixture        (from experiments/agents_ef; ~1 min, loads Intake's local models)
Output: v4/d/fixtures/intake_tickets.json. The messages are written for this fixture (no customer data). Intake
reads the order facts through its tools on a TEMPORARY copy of the placeholder database (the real DB is untouched).
Integration tests read this file, so they use genuine Intake output without loading the models every time.
"""

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))                 # repository root

MESSAGES = [
    "Hi, where is my order 4510?",
    "Order 4512 is a week late. I want my money back.",
    "My order 4515 arrived broken, the screen is cracked!!",
    "Order 4513 arrived damaged, what can I do?",
    "I want to return order 4511, it does not fit.",
    "Bonjour, où en est ma commande 4514 ?",
    "WHERE IS MY ORDER 4512??? This is ridiculous.",
    "Can you tell me when order 4510 arrives?",
    "Do you sell phone cases for the new model?",
    "Order 4515 is very late, I want a full refund.",
    "My parcel 4516 never arrived and the tracking has not moved for days.",
    "The charger from order 4517 stopped working after one day, it is broken.",
]


def main():
    from callverse import trace
    from callverse.data import db
    from callverse.data.seed import seed
    from callverse.intake import intake

    tmp = Path(tempfile.mkdtemp())
    db.use_db(tmp / "shopnova_fixture.db")
    seed()
    trace.start_run("intake_fixture", trace_dir=tmp)
    keep = ("ticket_id", "text", "order_id", "main_reason", "reasons", "priority_label", "priority_score",
            "emotion", "sentiment", "style")
    out = [{k: t.get(k) for k in keep} for t in (intake.process(m, use_llm=False) for m in MESSAGES)]
    (HERE / "fixtures").mkdir(exist_ok=True)
    (HERE / "fixtures" / "intake_tickets.json").write_text(json.dumps(
        {"source": "callverse.intake.intake.process(text, use_llm=False) on a temporary seeded DB",
         "messages_written_for_fixture": True, "tickets": out}, indent=1, ensure_ascii=False, default=str))
    for t in out:
        print(t["main_reason"], t["priority_label"], round(t["priority_score"] or 0, 3), "|", t["text"][:50])


if __name__ == "__main__":
    main()
