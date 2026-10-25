"""Build a corpus of CLOSED conversations in the prototype's real trace format, for developing and testing M7.

    python -m v3.m7.make_corpus --split dev  --n 120 --out <dir>     # used to build / tune M7
    python -m v3.m7.make_corpus --split test --n 120 --out <dir>     # held out: evaluated once, never tuned on

What is REAL here: the prototype pipeline itself (callverse/pipeline.py): Intake with its local models (no API),
router, queues, the Coordinator's checks and decisions, policy search (bge-small), the platform writes, the
Layer 3 stub and the SLM writer's rule check (the SLM is offline, so the reply is its template, as when Ollama
is not running).
What is SCRIPTED: the agents' LLM (no API key in this sandbox). A small fake LLM plays Agent A / Agent B and
follows a "behaviour" chosen per conversation. Some behaviours plant a known defect (wrong amount, a claim that
contradicts the data, a rule id that no longer exists, no rule search, a provider error...). The planted
defects are written to ground_truth.json so M7's reviewer can be checked against them.
The client messages are written for this corpus (EN and FR, calm and angry). No real customer data.

Every run uses a temporary database and its own trace folder: the real DB and traces/ are never touched.
"""

import argparse
import json
import random
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[4]                 # repository root
sys.path.insert(0, str(ROOT))

SPLIT_SEED = {"dev": 11, "test": 22}

# Client messages per intent. {o} = order id. Written for this corpus.
MESSAGES = {
    "status": [("en", "calm", "Hi, where is my order {o}?"),
               ("en", "angry", "WHERE IS MY ORDER {o}??? I have been waiting for ages, this is ridiculous."),
               ("fr", "calm", "Bonjour, où en est ma commande {o} ?"),
               ("en", "calm", "Could you give me the status of order {o}, please?")],
    "refund": [("en", "calm", "Order {o} is a week late. I want my money back."),
               ("en", "angry", "Order {o} still has not arrived. Refund me NOW, I am done with ShopNova."),
               ("fr", "calm", "Ma commande {o} a beaucoup de retard, je veux être remboursé."),
               ("en", "calm", "My order {o} is very late, I would like a full refund please.")],
    "notify": [("en", "calm", "Hi, can you let me know when my order {o} arrives?"),
               ("en", "calm", "Please tell me when order {o} is out for delivery."),
               ("fr", "calm", "Pouvez-vous me prévenir quand ma commande {o} sera livrée ?")],
    "damaged": [("en", "angry", "My order {o} arrived broken. The screen is cracked!"),
                ("en", "calm", "Order {o} arrived damaged, what can I do?")],
}

# Behaviours of the scripted agents and the defect each one plants (None = clean run).
BEHAVIOURS = {
    "clean": None,
    "wrong_amount": "agent_wrong_amount",          # first refund amount > what is left: R-REF-05 send-back
    "ungrounded_claim": "agent_claim_contradicts_data",  # claims 8 days late: condition false, 3 send-backs
    "stale_rule_id": "agent_cites_missing_rule",   # cites R-REF-02 (not in the policy file), then corrects
    "no_search": "rule_not_searched",              # proposes without search_policy
    "unconfirmed": "user_not_confirmed",           # user_confirmed False -> ask_user
    "no_tool_first": "agent_answered_without_tools",  # Agent A answers without a tool; pipeline retries
    "provider_error": "pipeline_error",            # the LLM provider fails -> escalate
}
WEIGHTS = {"clean": 0.55, "wrong_amount": 0.08, "ungrounded_claim": 0.07, "stale_rule_id": 0.07,
           "no_search": 0.07, "unconfirmed": 0.05, "no_tool_first": 0.06, "provider_error": 0.05}


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def tool_reply(name, arguments, n=0):
    tc = SimpleNamespace(id=f"c{n}", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tc])


def tool_results(messages):
    """The tool outputs the agent has seen so far, in order (parsed JSON)."""
    out = []
    for m in messages:
        if m.get("role") == "tool":
            try:
                out.append(json.loads(m["content"]))
            except (TypeError, ValueError):
                out.append({})
    return out


def make_fake_llm(behaviour: str, order_id: int, intent: str, quote: str):
    """A stateless fake LLM for both agents (step = number of tool results already seen, as in tests/test_demo.py).
    It "reads" the facts only from the tool results it was given, like a real agent."""

    def fake(role_key, messages, tools=None):
        if behaviour == "provider_error":
            raise RuntimeError("provider returned 503 (scripted)")
        system = messages[0]["content"]
        convo = json.dumps(messages[1:], ensure_ascii=False)
        seen = tool_results(messages)
        step = len(seen)
        sent_back = "was sent back" in convo
        if system.startswith("You are Agent A"):
            if behaviour == "no_tool_first" and "Check it with your tools" not in convo:
                return text_reply("Could you give me your order number?")
            asked_by_b = "Delivery status" in messages[1]["content"]
            if step == 0:
                return tool_reply("get_tracking", {"order_id": order_id})
            if intent == "notify" and not asked_by_b:
                if step == 1:
                    return tool_reply("search_policy", {"query": "delivery notification"}, 1)
                if step == 2:
                    event = "out_for_delivery" if "out for delivery" in quote else "delivered"
                    return tool_reply("propose_subscription", {"order_id": order_id, "event": event,
                                                               "user_quote": quote}, 2)
                return text_reply("Sent for checking.")
            t = seen[0] if seen else {}
            if intent in ("refund", "damaged") and not asked_by_b:
                return text_reply(f"Order {order_id}: {t.get('status')}. Your request is passed on. [HANDOVER: B]")
            return text_reply(f"Order {order_id}: status {t.get('status')}, days late {t.get('days_late')}, "
                              f"delivered {t.get('delivered')}.")

        # Agent B: get_order -> ask_agent(A) -> get_refunds -> search_policy -> decide.
        plan = [lambda: tool_reply("get_order", {"order_id": order_id}),
                lambda: tool_reply("ask_agent", {"agent": "A", "question": f"Delivery status of order {order_id}?"}, 1),
                lambda: tool_reply("get_refunds", {"order_id": order_id}, 2)]
        if behaviour != "no_search":
            plan.append(lambda: tool_reply("search_policy", {"query": "refund for a late order"}, 3))
        if step < len(plan):
            return plan[step]()
        if step > len(plan):
            return text_reply("Sent for checking.")
        order, ask, refunds = seen[0], seen[1], seen[2]
        facts = (ask.get("facts") or {}) if isinstance(ask, dict) else {}
        days_late, delivered = facts.get("days_late"), facts.get("delivered")
        paid, refunded = order.get("paid", 0), refunds.get("refunded_total", 0)
        left = round((paid or 0) - (refunded or 0), 2)
        if intent == "damaged":
            return text_reply("Please send a photo of the damage (R-DMG-01).")
        late_rule_ok = isinstance(days_late, int) and days_late > 5 and delivered is False and left > 0
        claim_late = behaviour == "ungrounded_claim"
        if not late_rule_ok and not claim_late:
            return text_reply("No refund applies for this delay (R-DEL-02); here is the delivery status.")
        amount = left if left > 0 else paid
        rule = "R-REF-03"
        claimed = {"days_late": days_late, "delivered": delivered, "paid": paid, "refunded_total": refunded}
        if claim_late:
            claimed = {**claimed, "days_late": 8, "delivered": False}
        if behaviour == "wrong_amount" and not sent_back:
            amount = round(paid + 20, 2)
        if behaviour == "stale_rule_id" and not sent_back:
            rule = "R-REF-02"
        args = {"order_id": order_id, "amount": amount, "rule_id": rule, "facts_used": claimed,
                "user_confirmed": behaviour != "unconfirmed", "user_quote": quote}
        return tool_reply("propose_refund", args, 4)

    return fake


def pick_order(intent, behaviour, orders, rng):
    """An order that fits the intent (late orders for refunds, undelivered ones for notifications...).
    About 10% of refund requests are about a cancelled / refunded order (an edge case real clients also send)."""
    open_ = [o for o in orders if o["status"] not in ("cancelled", "refunded")]
    if intent == "refund" and behaviour == "ungrounded_claim":
        # the agent will claim "8 days late, not delivered": pick an order where that is false
        pool = [o for o in open_ if o["days_late"] <= 5 or o["delivered"]] or open_
    elif intent == "refund":
        pool = [o for o in orders if o["days_late"] > 0 and not o["delivered"]] or orders
        pool = [o for o in pool if o in open_] if rng.random() < 0.9 else pool
        if rng.random() < 0.7:
            pool = [o for o in pool if o["days_late"] > 5] or pool
    elif intent == "notify":
        pool = [o for o in orders if not o["delivered"] and o["status"] not in ("cancelled", "refunded")] or orders
    elif intent == "damaged":
        pool = [o for o in orders if o["delivered"]] or orders
    else:
        pool = orders
    return rng.choice(pool)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=list(SPLIT_SEED), required=True)
    p.add_argument("--n", type=int, default=120)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)

    from contextlib import closing

    from callverse import pipeline, trace
    from callverse.data import db
    from callverse.data.seed import seed
    from callverse.intake import intake
    from callverse.slm import writer
    from callverse.tools.shopnova_tools import get_order, get_tracking

    def slm_offline(*args, **kwargs):          # as when Ollama is not running: the writer uses its template
        raise ConnectionError("SLM offline (corpus build)")
    writer.llm = SimpleNamespace(chat=slm_offline)

    out = Path(a.out) / a.split
    (out / "traces").mkdir(parents=True, exist_ok=True)
    db.use_db(Path(tempfile.mkdtemp()) / "shopnova_corpus.db")
    seed()
    with closing(db.connect()) as con:
        ids = [r[0] for r in con.execute("SELECT id FROM orders ORDER BY id")]
    orders = [{**get_tracking(i), "id": i, "paid": get_order(i)["paid"]} for i in ids]

    rng = random.Random(SPLIT_SEED[a.split])
    intents = ["status"] * 3 + ["refund"] * 4 + ["notify"] * 2 + ["damaged"]
    truth = []
    for k in range(a.n):
        intent = rng.choice(intents)
        lang, tone, tmpl = rng.choice(MESSAGES[intent])
        behaviour = rng.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0]
        if behaviour == "no_tool_first" and intent not in ("status", "notify"):
            behaviour = "clean"
        if behaviour in ("wrong_amount", "stale_rule_id", "no_search", "unconfirmed", "ungrounded_claim") \
                and intent != "refund":
            behaviour = "clean"
        o = pick_order(intent, behaviour, orders, rng)
        conv_id = f"{a.split}-{k:04d}"
        text = tmpl.format(o=o["id"])
        trace.start_run(conv_id, trace_dir=out / "traces")
        ticket = intake.process(text, use_llm=False)
        result = pipeline.handle_ticket(ticket, chat_fn=make_fake_llm(behaviour, o["id"], intent, text))
        truth.append({"conversation_id": conv_id, "intent": intent, "lang": lang, "tone": tone,
                      "behaviour": behaviour, "planted_defect": BEHAVIOURS[behaviour], "order_id": o["id"],
                      "outcome": result["decision"]["outcome"], "route": result["route"]["agent"]})
        print(conv_id, intent, lang, tone, behaviour, "->", result["route"]["agent"], result["decision"]["outcome"])
    (out / "ground_truth.json").write_text(json.dumps(
        {"split": a.split, "seed": SPLIT_SEED[a.split], "n": a.n,
         "note": "SCRIPTED agents (fake LLM) on the real prototype pipeline; planted defects listed per conversation",
         "conversations": truth}, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
