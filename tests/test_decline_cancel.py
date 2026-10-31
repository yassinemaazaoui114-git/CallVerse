"""T14a tests: "say no with the reason" (decline, written by code) and the ShopNova cancellation (rule R-CAN-01).

Every row of the decline table; cancel of a paid / cash on delivery / > 300 TND / shipped order; a negative sentence;
a quote that is not in the message; the one-transaction rollback; the allow-lists; the Intake reason list.
No API call: fake LLM for the agents, the SLM is offline (conftest: the template writes the reply).
"""

import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from callverse import companies, pipeline
from callverse.agents.agent_b import AgentB
from callverse.channels import approvals, web_chat
from callverse.coordinator.coordinator import cancel_confirmed, new_case, no_proposal_decision, review
from callverse.data import admin_reads, db, writes
from callverse.intake import intake, reasons
from callverse.kb import search
from callverse.kb.policies import check_condition, get_policy
from callverse.slm.check import check_reply
from callverse.slm.templates import render
from callverse.slm.writer import polish
from callverse.tickets import store
from callverse.tools import proposal_tools, registry
from callverse.tools.shopnova_tools import get_order, get_refunds

ASK = "Please cancel my order"


def cancel(order_id=4511, quote=ASK):
    return {"agent": "B", "action": "cancel", "params": {"order_id": order_id}, "rule_id": "R-CAN-01",
            "facts_used": {"order_id": order_id}, "user_confirmed": False, "user_quote": quote}


def case(order_id=4511, message=None, reason="cancel_order"):
    return {**new_case("T-1"), "order_id": order_id, "main_reason": reason,
            "user_message": message if message is not None else f"{ASK} {order_id}, thanks."}


def stock(product_id):
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()[0]


def set_paid(order_id, amount):
    with closing(sqlite3.connect(db.db_path())) as con:
        con.execute("UPDATE orders SET paid = ?, total = ? WHERE id = ?", (amount, amount, order_id))
        con.commit()


def admin_log():
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute("SELECT admin, action FROM admin_actions ORDER BY id").fetchall()


# ---------- rule R-CAN-01 ----------

def test_rule_text_and_condition():
    rule = get_policy("R-CAN-01")
    assert rule["text"] == ("An order can be cancelled while it is still being processed (not yet shipped). "
                            "If it was paid, the full amount paid is refunded.")
    assert check_condition(rule["condition"], {"status": "processing"})
    assert not check_condition(rule["condition"], {"status": "shipped"})


def test_a_cancel_question_finds_the_rule_in_the_top_2():
    assert "R-CAN-01" in [r["id"] for r in search.search_policy("Can I cancel my order before it ships?", 2)]


# ---------- the Intake reason ----------

def test_cancel_order_is_a_shopnova_reason_routed_to_b():
    shopnova = companies.get("shopnova")
    assert "cancel_order" in shopnova["reasons"] and "cancel_order" in reasons.REASONS
    assert shopnova["routes"]["cancel_order"] == "B"
    assert pipeline.handover_text("cancel_order") == "Your request is passed on for a cancellation check."
    assert len(reasons.load_examples()["cancel_order"]) == 10


def test_cancel_and_refund_is_a_cancellation():
    assert intake.pick_main_reason(["refund_request", "cancel_order"]) == "cancel_order"
    assert intake.pick_main_reason(["cancel_order", "damaged_item"]) == "damaged_item"


@pytest.mark.parametrize("message", ["I want to cancel order 4510.", "Please cancel my order", "pls cancle it now order 4511"])
def test_a_sentence_that_says_cancel_is_a_cancellation(message):
    assert reasons.match_reasons(message)["reasons"][0]["reason"] == "cancel_order"


def test_a_past_cancellation_is_not_a_new_cancel_request():
    found = [r["reason"] for r in reasons.match_reasons("I cancelled it last week, when will I get my refund?")["reasons"]]
    assert found == ["refund_request"]


@pytest.mark.parametrize("sentence", ["I want to cancel my subscription.", "Please cancel my membership",
                                      "How do I cancel Prime?", "cancel my account now", "I want to cancel my plan"])
def test_the_cancel_word_stays_out_of_subscriptions_and_accounts(sentence):
    assert reasons.CANCEL_WORD_RE.search(sentence) and reasons.NOT_AN_ORDER_RE.search(sentence)
    scores = reasons.match_reasons(sentence)["sentence_scores"][0]["scores"]
    found = reasons.match_reasons(sentence)["reasons"]
    assert not found or found[0]["reason"] == max(scores, key=scores.get)     # by meaning only


def test_atlas_has_no_cancel_order_reason():
    assert "cancel_order" not in companies.get("atlas")["reasons"]


# ---------- the decline table (no proposal) ----------

@pytest.mark.parametrize("reason, order_id, rule_id, sentences, next_step", [
    ("return_item", 4505, "R-RET-01", ["Returns are possible within 14 days of delivery.",
                                       "Order 4505 was delivered 25 days ago, so it can no longer be returned."], ""),
    ("refund_request", 4505, "R-RET-01", ["Returns are possible within 14 days of delivery.",   # Intake said "refund"
                                          "Order 4505 was delivered 25 days ago, so it can no longer be returned."], ""),
    ("refund_request", 4506, "R-REF-05", ["Order 4506 has already been fully refunded (189.00 TND), so no further "
                                          "refund is possible."], ""),
    ("refund_request", 4510, "R-REF-03", ["Order 4510 is on its way and is not late: it is due by 2026-10-10.",
                                          "A refund for a late delivery is possible when an order is more than 5 days "
                                          "late."], ""),
    ("cancel_order", 4510, "R-CAN-01", ["Order 4510 is already on its way, so it can no longer be cancelled.",
                                        "An order can be cancelled only while it is being processed."],
     "Once it is delivered, you can return it within 14 days."),
    ("cancel_order", 4505, "R-CAN-01", ["Order 4505 is already delivered, so it can no longer be cancelled.",
                                        "An order can be cancelled only while it is being processed."], ""),
])
def test_decline_rows(reason, order_id, rule_id, sentences, next_step):
    d = no_proposal_decision(reason, order_id)
    assert (d["outcome"], d["rule_id"], d["order_id"]) == ("decline", rule_id, order_id)
    assert d["must_say"] == sentences and d["next_step"] == next_step
    assert d["proposal_id"] is None
    reply = polish(render(d), d)                # the template says the same, and passes the rule check
    assert all(s in reply for s in sentences) and check_reply(reply, d)["passed"]


def set_order(order_id, status, delivered_date=None):
    with closing(sqlite3.connect(db.db_path())) as con:
        con.execute("UPDATE orders SET status = ?, delivered_date = ? WHERE id = ?", (status, delivered_date, order_id))
        con.commit()


ON_THE_WAY = "Once it is delivered, you can return it within 14 days."
STILL_RETURN = "You can still return it within 14 days of delivery."


@pytest.mark.parametrize("status, delivered_date, next_step", [
    ("shipped", None, ON_THE_WAY),
    ("out_for_delivery", None, ON_THE_WAY),
    ("stuck_at_depot", None, ON_THE_WAY),
    ("delivered", "2026-09-25", STILL_RETURN),     # exactly 14 days ago
    ("delivered", "2026-09-24", ""),               # 15 days ago
    ("refunded", None, ""),
    ("cancelled", None, ""),
])
def test_r_can_01_next_step_by_status(status, delivered_date, next_step):
    set_order(4510, status, delivered_date)
    assert no_proposal_decision("cancel_order", 4510)["next_step"] == next_step   # no proposal
    d = review(cancel(4510), case(4510))                                          # a proposal: the same words
    assert d["outcome"] == "decline" and d["next_step"] == next_step
    assert check_reply(render(d), d)["passed"]


def test_cancel_processing_without_a_proposal_asks_first():
    d = no_proposal_decision("cancel_order", 4511)
    assert d["outcome"] == "ask_user" and d["rule_id"] is None
    assert d["must_say"] == ["Please confirm that you want to cancel order 4511."]
    assert get_order(4511)["status"] == "processing"


@pytest.mark.parametrize("reason, order_id", [
    ("return_item", 4508 + 1000000),      # unknown order
    ("return_item", None),                # no order number
    ("return_item", 4510),                # not delivered: no decline in the table
    ("order_status", 4505),               # another reason
    ("refund_request", 4512),             # late: not a "no"
    ("refund_request", 4509 + 1000000),   # unknown order
])
def test_no_decline_keeps_todays_behaviour(reason, order_id):
    assert no_proposal_decision(reason, order_id) is None


def test_return_inside_14_days_is_not_declined(monkeypatch):
    assert no_proposal_decision("return_item", 4509) is not None     # 15 days ago
    with closing(sqlite3.connect(db.db_path())) as con:
        con.execute("UPDATE orders SET delivered_date = '2026-09-25' WHERE id = 4509")   # exactly 14 days ago
        con.commit()
    assert no_proposal_decision("return_item", 4509) is None


def test_a_cancelled_order_is_not_called_due():
    """Cash on delivery, cancelled: nothing paid, nothing to deliver: R-REF-03's "not late" would be wrong."""
    assert writes.set_order_status(4514, "cancelled")["new_status"] == "cancelled"
    assert no_proposal_decision("refund_request", 4514) is None


def test_the_pipeline_declines_when_no_proposal_was_made():
    llm = lambda role, messages, tools=None: SimpleNamespace(content="Too late, sorry.", tool_calls=None)
    ticket = {"ticket_id": "T-1", "text": "I want to return order 4505.", "order_id": 4505, "main_reason": "return_item",
              "priority_label": "low"}
    out = pipeline.handle_ticket(ticket, chat_fn=llm)
    assert out["decision"]["outcome"] == "decline" and out["decision"]["rule_id"] == "R-RET-01"
    assert "Order 4505 was delivered 25 days ago, so it can no longer be returned." in out["final_reply"]


# ---------- the cancel action ----------

def test_cancel_processing_paid_cancels_refunds_and_gives_the_stock_back():
    before = stock(3), stock(2)
    d = review(cancel(), case())
    assert d["outcome"] == "approve" and d["rule_id"] == "R-CAN-01"
    assert d["must_say"] == ["Your order 4511 is now cancelled.", "Your refund of 54.40 TND is approved."]
    assert get_order(4511)["status"] == "cancelled"
    rows = get_refunds(4511)["refunds"]
    assert [(r["amount"], r["rule_id"], r["status"]) for r in rows] == [(54.40, "R-CAN-01", "approved")]
    assert (stock(3), stock(2)) == (before[0] + 1, before[1] + 1)
    assert admin_log() == [("coordinator", "cancel_order_by_user")]
    assert admin_reads.proposal(d["proposal_id"])["user_confirmed"] == 1        # stored as decided by code
    assert check_reply(render(d), d)["passed"]


def test_cancel_cash_on_delivery_has_no_refund_row():
    before = stock(5)
    d = review(cancel(4514), case(4514))
    assert d["outcome"] == "approve" and d["must_say"] == ["Your order 4514 is now cancelled."]
    assert "amount_tnd" not in d["facts"]
    assert get_order(4514)["status"] == "cancelled" and get_refunds(4514)["refunds"] == []
    assert stock(5) == before + 1


def test_cancel_refunds_only_what_is_left():
    set_paid(4511, 54.40)
    with closing(sqlite3.connect(db.db_path())) as con:
        con.execute("INSERT INTO refunds (order_id, amount, status, created_at) VALUES (4511, 4.40, 'approved', '2026-10-08')")
        con.commit()
    d = review(cancel(), case())
    assert d["facts"]["amount_tnd"] == 50.00


def test_cancel_shipped_is_declined_not_sent_back():
    c = case(4510)
    d = review(cancel(4510), c)
    assert d["outcome"] == "decline" and d["rule_id"] == "R-CAN-01" and c["send_backs"] == 0
    assert d["next_step"] == "Once it is delivered, you can return it within 14 days."
    assert "no longer be cancelled" in d["must_say"][0]
    assert admin_reads.proposal(d["proposal_id"])["decision"] == "decline"
    assert get_order(4510)["status"] == "shipped" and get_refunds(4510)["refunds"] == []


@pytest.mark.parametrize("message, quote, confirmed, why", [
    ("Please cancel my order 4511.", "cancel my order 4511", True, "cancel request + quote found"),
    ("PLEASE CANCEL ORDER 4511", "please cancel order 4511", True, "cancel request + quote found"),
    ("It didn't arrive so please cancel order 4511", "please cancel order 4511", True, "cancel request + quote found"),
    ("Do not cancel order 4511.", "cancel order 4511", False, "negative sentence"),
    ("Please don’t cancel order 4511.", "cancel order 4511", False, "negative sentence"),
    ("Never cancel order 4511!", "cancel order 4511", False, "negative sentence"),
    ("I do not want to cancel order 4511.", "cancel order 4511", False, "negative sentence"),
    ("Is it on its way? I hope so.", "cancel order 4511", False, "quote not in the message"),
    ("Please cancel order 4511.", "", False, "no quote"),
])
def test_the_confirmation_is_decided_by_code(message, quote, confirmed, why):
    assert cancel_confirmed({"user_quote": quote}, case(message=message)) == (confirmed, why)


def test_the_main_reason_must_be_cancel_order():
    c = case(reason="refund_request", message="cancel order 4511")
    assert cancel_confirmed({"user_quote": "cancel order 4511"}, c)[0] is False


def test_a_negative_sentence_asks_the_client_and_cancels_nothing():
    d = review(cancel(quote="cancel order 4511"), case(message="Please do not cancel order 4511."))
    assert d["outcome"] == "ask_user"
    assert d["must_say"] == ["Please confirm that you want to cancel order 4511."]
    assert get_order(4511)["status"] == "processing" and get_refunds(4511)["refunds"] == []


def test_a_quote_not_in_the_message_asks_the_client():
    d = review(cancel(quote="cancel it now"), case(message="Where is order 4511?"))
    assert d["outcome"] == "ask_user" and get_order(4511)["status"] == "processing"


def test_only_the_order_of_the_ticket_can_be_cancelled():
    d = review(cancel(4514), case(4511))
    assert d["outcome"] == "send_back" and get_order(4514)["status"] == "processing"


def test_above_300_stub_mode_finance_approves():
    set_paid(4511, 378.00)
    d = review(cancel(), case())
    assert d["outcome"] == "approve" and d["facts"]["layer3_decision"] == "approved"
    assert "after a check by our finance team." in d["must_say"][1]
    assert get_order(4511)["status"] == "cancelled" and get_refunds(4511)["refunds"][0]["amount"] == 378.00


def test_above_300_stub_mode_finance_refuses_and_nothing_is_written():
    set_paid(4511, 600.00)
    d = review(cancel(), case())
    assert d["outcome"] == "layer3_refused"
    assert get_order(4511)["status"] == "processing" and get_refunds(4511)["refunds"] == []


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "queue")
    store.use_db(tmp_path / "callverse_test.db")
    yield
    store.use_db(store.DEFAULT_DB_PATH)


def pending_cancel():
    set_paid(4511, 378.00)
    d = review(cancel(), case())
    assert d["outcome"] == "layer3_pending" and d["facts"]["amount_tnd"] == 378.00
    assert get_order(4511)["status"] == "processing"
    assert admin_reads.proposal(d["proposal_id"])["decision"] is None
    ticket = store.create_ticket("shopnova", 3)
    store.add_message(ticket["id"], "user", f"{ASK} 4511, thanks.")
    return store.create_approval(ticket["id"], 4511, d["facts"]["amount_tnd"], d["proposal_id"])


def test_above_300_queue_mode_admin_approves_in_one_transaction(queue):
    approval = pending_cancel()
    before = stock(3)
    out = approvals.decide(approval["id"], "shop_admin", True)
    assert out["outcome"] == "approve" and "Your order 4511 is now cancelled." in out["reply"]
    assert get_order(4511)["status"] == "cancelled" and stock(3) == before + 1
    assert out["refund"]["amount"] == 378.00 and out["refund"]["rule_id"] == "R-CAN-01"
    assert admin_log() == [("shop_admin", "approve_cancel")]
    assert out["ticket"]["status"] == "Solved"


def test_above_300_queue_mode_admin_refuses_and_the_order_stays(queue):
    approval = pending_cancel()
    out = approvals.decide(approval["id"], "shop_admin", False, "not now")
    assert out["outcome"] == "layer3_refused" and get_order(4511)["status"] == "processing"
    assert get_refunds(4511)["refunds"] == [] and "not now" not in out["reply"]


def test_above_300_queue_mode_a_shipped_order_fails_the_recheck(queue):
    approval = pending_cancel()
    writes.set_order_status(4511, "shipped")
    out = approvals.decide(approval["id"], "shop_admin", True)
    assert "does not apply any more" in out["error"]
    assert get_refunds(4511)["refunds"] == [] and store.get_approval(approval["id"])["status"] == "pending"


# ---------- writes: all or nothing, safety nets ----------

def approved_cancel(order_id=4511):
    pid = writes.record_proposal(cancel(order_id))["id"]
    writes.record_decision(pid, "approve", "test")
    return pid


def test_one_transaction_a_failing_log_writes_nothing(monkeypatch):
    pid = approved_cancel()
    before = stock(3)

    def broken(*args):
        raise RuntimeError("disk full")
    monkeypatch.setattr(writes, "_log_action", broken)
    out = writes.cancel_order_by_user(4511, pid, 54.40)
    assert "nothing was written" in out["error"]
    assert get_order(4511)["status"] == "processing" and get_refunds(4511)["refunds"] == [] and stock(3) == before


@pytest.mark.parametrize("order_id, amount, word", [(4511, 10.0, "amount"), (4511, 0, "amount"), (4514, 54.40, "for order")])
def test_safety_nets_refuse_a_wrong_amount_or_order(order_id, amount, word):
    pid = approved_cancel()
    assert word in writes.cancel_order_by_user(order_id, pid, amount)["error"]
    assert get_order(4511)["status"] == "processing"


def test_safety_nets_refuse_an_unapproved_proposal_and_a_second_use():
    pid = writes.record_proposal(cancel())["id"]
    assert "not approved" in writes.cancel_order_by_user(4511, pid, 54.40)["error"]
    pid = approved_cancel()
    assert "error" not in writes.cancel_order_by_user(4511, pid, 54.40)
    assert "not processing" in writes.cancel_order_by_user(4511, pid, 54.40)["error"]
    assert len(get_refunds(4511)["refunds"]) == 1


def test_a_refund_proposal_cannot_pay_a_cancel():
    pid = writes.record_proposal({"agent": "B", "action": "refund", "params": {"order_id": 4511, "amount": 54.40},
                                  "rule_id": "R-REF-03", "facts_used": {}, "user_confirmed": True})["id"]
    writes.record_decision(pid, "approve", "test")
    assert "not 'cancel'" in writes.cancel_order_by_user(4511, pid, 54.40)["error"]


# ---------- the tool and the allow-lists ----------

def test_the_tool_writes_nothing_and_checks_the_shape():
    assert proposal_tools.propose_cancellation(4511, "cancel it") == {"status": "submitted to Coordinator"}
    assert get_order(4511)["status"] == "processing"
    assert "order_id" in proposal_tools.propose_cancellation("4511", "cancel it")["error"]
    assert "user_quote" in proposal_tools.propose_cancellation(4511, " ")["error"]


def test_only_shopnova_b_has_the_cancel_tool():
    assert "propose_cancellation" in registry.ALLOW_LISTS["B"]
    assert "propose_cancellation" not in registry.ALLOW_LISTS["A"]
    assert "propose_cancellation" not in registry.ATLAS_ALLOW_LISTS["B"]
    assert "error" in registry.run_tool("A", "propose_cancellation", {"order_id": 4511, "user_quote": "x"})
    atlas = registry.run_tool("B", "propose_cancellation", {"order_id": 4511, "user_quote": "x"}, company="atlas")
    assert "not allowed" in atlas["error"]
    assert "cancel_order_by_user" not in registry.TOOL_FUNCTIONS


def call(name, arguments):
    tool = SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tool])


def cancel_llm(order_id, quote):
    steps = iter([call("propose_cancellation", {"order_id": order_id, "user_quote": quote})])

    def fake(role_key, messages, tools=None):
        return next(steps, None) or SimpleNamespace(content="It is sent for checking.", tool_calls=None)
    return fake


def test_agent_b_gives_a_cancel_proposal_in_the_platform_shape():
    result = AgentB(chat_fn=cancel_llm(4511, ASK)).run("Please cancel order 4511")
    assert result["proposal"] == cancel(quote=ASK)


def test_the_whole_path_cancels_and_tells_the_client():
    ticket = {"ticket_id": "T-1", "text": f"{ASK} 4511, thanks.", "order_id": 4511, "main_reason": "cancel_order",
              "priority_label": "low"}
    out = pipeline.handle_ticket(ticket, chat_fn=cancel_llm(4511, ASK))
    assert out["decision"]["outcome"] == "approve" and get_order(4511)["status"] == "cancelled"
    assert "Your order 4511 is now cancelled." in out["final_reply"]
    assert "Your refund of 54.40 TND is approved." in out["final_reply"]


def test_a_decline_is_a_solved_ticket_with_the_rule_in_the_steps(tmp_path, monkeypatch):
    store.use_db(tmp_path / "callverse_test.db")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    llm = lambda role, messages, tools=None: SimpleNamespace(content="Sorry.", tool_calls=None)
    try:
        out = web_chat.send(2, "shopnova", "I want to cancel order 4510.", chat_fn=llm)
        assert out["outcome"] == "decline" and out["status"] == "Solved"
        decisions = [s["data"] for s in store.steps(out["ticket_id"]) if s["step"] == "coordinator"
                     and s["data"].get("trace_step") == "coordinator_decision"]
        assert decisions[-1]["rule_id"] == "R-CAN-01"
    finally:
        store.use_db(store.DEFAULT_DB_PATH)


def test_agent_a_does_not_see_the_cancel_tool():
    assert "propose_cancellation" not in [s["function"]["name"] for s in registry.schemas_for("A")]
