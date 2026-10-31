"""P20 tests: Agent C (Urgent & Special Help) and Agent D (Availability & Supply), offline (fake LLM, no API).

What is checked:
- allow-lists: C sees only its reads and its three PROPOSAL tools; no write function is reachable by any agent;
- stock facts and D's rules (R-STK-01 shortage, R-PRM-01 overstock) on the seeded data;
- the Coordinator's checks for replace / hold / assistance: nothing is written before the client says yes
  (ask_user), a rule that does not hold is sent back, approve writes exactly once;
- D: promotions end "owner_pending"; only the owner's decision (one transaction) approves or refuses; the price
  never changes; the model only words the note (template when its numbers are wrong);
- D warns A: the shortage line in the Intake note;
- the pipeline: Agent A's [HANDOVER: C], the client's yes going back to C, and the Layer 2 switch.
"""

import json
from contextlib import closing
from types import SimpleNamespace

import pytest

from callverse import pipeline, trace
from callverse.agents import agent_a
from callverse.agents.agent_c import AgentC
from callverse.agents.agent_d import AgentD, shortage_note, word_note
from callverse.channels import approvals, web_chat
from callverse.coordinator import coordinator, special
from callverse.data import writes
from callverse.data.db import connect
from callverse.tickets import store
from callverse.tools import registry
from callverse.tools.stock_tools import stock_facts


def tool_call_reply(*calls):
    """A model reply asking for one or more tools: calls = (name, arguments) pairs."""
    tcs = [SimpleNamespace(id=f"call_{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a)))
           for i, (n, a) in enumerate(calls)]
    return SimpleNamespace(content=None, tool_calls=tcs)


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def steps():
    return [json.loads(x)["step"] for x in trace.current_path().read_text(encoding="utf-8").splitlines()]


def scalar(sql, *args):
    with closing(connect()) as con:
        return con.execute(sql, args).fetchone()[0]


def set_stock(product_id, stock):
    with closing(connect()) as con:
        con.execute("UPDATE products SET stock = ? WHERE id = ?", (stock, product_id))
        con.commit()


def c_proposal(action, params, confirmed=True):
    return {"agent": "C", "action": action, "params": params, "rule_id": special.RULE_OF[action], "facts_used": {},
            "user_confirmed": confirmed, "user_quote": "I need it tomorrow, it is a gift."}


REPLACE_4512 = {"order_id": 4512, "product_id": 1, "qty": 1}   # stuck at the depot, 8 days late, Wireless Earbuds


def yes_case(case_id="T-1"):
    """A case where the client's message answers Agent C's question (what the channel sets with continue_agent)."""
    return {**coordinator.new_case(case_id), "client_said_yes": True}


@pytest.fixture
def cd_tables():
    """The seeded test DB already has the C/D tables (seed creates them); this just makes the dependency visible."""
    with closing(connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM replacements").fetchone()[0] == 0


# ---------- allow-lists ----------

def test_agent_c_sees_its_reads_and_three_proposal_tools_only():
    names = [t["function"]["name"] for t in registry.schemas_for("C")]
    assert names == ["get_order", "get_facts_from_a", "check_availability_with_d", "search_policy",
                     "propose_replacement", "propose_hold", "propose_assistance"]
    assert "error" in registry.run_tool("C", "propose_refund", {"order_id": 4512})
    assert "error" in registry.run_tool("A", "propose_replacement", REPLACE_4512)
    assert "D" not in registry.ALLOW_LISTS          # D is rules, it has no tools


def test_no_write_function_is_a_tool():
    writes_names = {"create_replacement", "create_hold", "create_assistance_request", "create_promotion",
                    "admin_decide_promotion"}
    assert not writes_names & set(registry.TOOL_FUNCTIONS)
    for allowed in registry.ALLOW_LISTS.values():
        assert not writes_names & set(allowed)


def test_c_proposal_tool_writes_nothing_and_checks_the_shape(cd_tables):
    out = registry.run_tool("C", "propose_replacement", {**REPLACE_4512, "user_confirmed": "yes", "user_quote": ""})
    assert "user_confirmed must be true or false" in out["error"] and "user_quote" in out["error"]
    ok = registry.run_tool("C", "propose_replacement", {**REPLACE_4512, "user_confirmed": True, "user_quote": "yes"})
    assert ok == {"status": "submitted to Coordinator"}
    assert scalar("SELECT COUNT(*) FROM replacements") == 0 and scalar("SELECT stock FROM products WHERE id = 1") == 40


# ---------- stock facts and D's rules ----------

def test_stock_facts_on_the_seeded_data():
    earbuds = stock_facts(1)
    assert (earbuds["stock"], earbuds["units_sold_30d"], earbuds["days_of_cover"]) == (40, 2, 600.0)
    assert not earbuds["shortage"] and not earbuds["overstock"]          # 40 < 50: not overstocked
    case = stock_facts(2)                                                 # Phone Case: 120 left, 4 sold
    assert case["overstock"] and not case["shortage"]
    set_stock(1, 3)
    assert stock_facts(1)["shortage"]                                     # R-STK-01: 5 or fewer left
    assert "error" in stock_facts(999999) and "error" in stock_facts("1")


def test_d_warns_a_about_a_short_product_of_the_order():
    from callverse.tools.shopnova_tools import get_order
    assert shortage_note(get_order(4512)) is None
    set_stock(1, 2)
    note = shortage_note(get_order(4512))
    assert "Wireless Earbuds (product 1) has only 2 left" in note and "R-STK-01" in note
    ticket = {"ticket_id": "T-1", "order_id": 4512, "main_reason": "late_delivery"}
    assert note in pipeline.ticket_note(ticket)
    assert "stock_warning" in steps()


# ---------- Coordinator: Agent C's proposals ----------

def test_replace_waits_for_the_clients_yes_and_writes_nothing_before(cd_tables):
    d = coordinator.review(c_proposal("replace", REPLACE_4512, confirmed=False), yes_case("T-1"))
    assert d["outcome"] == "ask_user"
    # the model says "confirmed" but the message does not answer C's question: still only a question
    d = coordinator.review(c_proposal("replace", REPLACE_4512, confirmed=True), coordinator.new_case("T-9"))
    assert d["outcome"] == "ask_user"
    assert d["must_say"] == ["Please confirm that you want a free replacement Wireless Earbuds for order 4512."]
    assert scalar("SELECT COUNT(*) FROM replacements") == 0 and scalar("SELECT stock FROM products WHERE id = 1") == 40


def test_replace_approved_creates_a_free_order_and_takes_stock_once(cd_tables):
    case = yes_case("T-1")
    d = coordinator.review(c_proposal("replace", REPLACE_4512), case)
    assert d["outcome"] == "approve" and d["rule_id"] == "R-RPL-01"
    new_id = d["facts"]["new_order_id"]
    assert scalar("SELECT total FROM orders WHERE id = ?", new_id) == 0
    assert scalar("SELECT status FROM orders WHERE id = ?", new_id) == "processing"
    assert scalar("SELECT stock FROM products WHERE id = 1") == 39
    assert f"new order {new_id}" in d["must_say"][0]
    again = coordinator.review(c_proposal("replace", REPLACE_4512), yes_case("T-2"))
    assert again["outcome"] == "escalate" and "already has a replacement" in again["reason"]
    assert scalar("SELECT stock FROM products WHERE id = 1") == 39


def test_replace_sent_back_when_the_rule_does_not_hold(cd_tables):
    not_late = coordinator.review(c_proposal("replace", {"order_id": 4510, "product_id": 1, "qty": 1}),
                                  yes_case("T-1"))
    assert not_late["outcome"] == "send_back" and "R-RPL-01 does not apply" in not_late["reason"]
    other_item = coordinator.review(c_proposal("replace", {"order_id": 4512, "product_id": 4, "qty": 1}),
                                    yes_case("T-2"))
    assert other_item["outcome"] == "send_back"      # product 4 is not in order 4512
    refunded = coordinator.review(c_proposal("replace", {"order_id": 4506, "product_id": 4, "qty": 1}),
                                  yes_case("T-3"))
    assert refunded["outcome"] == "send_back"        # order 4506 is refunded
    set_stock(1, 0)
    no_stock = coordinator.review(c_proposal("replace", REPLACE_4512), yes_case("T-4"))
    assert no_stock["outcome"] == "send_back"
    wrong_rule = coordinator.review({**c_proposal("replace", REPLACE_4512), "rule_id": "R-REF-03"},
                                    yes_case("T-5"))
    assert wrong_rule["outcome"] == "send_back" and "use R-RPL-01" in wrong_rule["reason"]
    assert scalar("SELECT COUNT(*) FROM replacements") == 0


def test_hold_keeps_stock_for_up_to_3_days(cd_tables):
    d = coordinator.review(c_proposal("hold", {"order_id": 4510, "product_id": 4, "qty": 1, "hold_days": 3}),
                           yes_case("T-1"))
    assert d["outcome"] == "approve"
    assert d["must_say"] == ["We are keeping 1 unit of Smart Watch for you until 2026-10-12."]
    assert scalar("SELECT stock FROM products WHERE id = 4") == 14
    long = coordinator.review(c_proposal("hold", {"order_id": 4510, "product_id": 4, "qty": 1, "hold_days": 5}),
                              yes_case("T-2"))
    assert long["outcome"] == "send_back" and scalar("SELECT COUNT(*) FROM holds") == 1


def test_assistance_request_for_a_colleague(cd_tables):
    d = coordinator.review(c_proposal("assistance", {"order_id": 4512, "reason": "client disputes the refund"}),
                           yes_case("T-1"))
    assert d["outcome"] == "approve" and "special help team" in d["must_say"][0]
    assert scalar("SELECT reason FROM assistance_requests") == "client disputes the refund"
    empty = coordinator.review(c_proposal("assistance", {"order_id": 4512, "reason": " "}), yes_case("T-2"))
    assert empty["outcome"] == "send_back"


def test_writes_refuse_without_an_approved_matching_proposal(cd_tables):
    assert "error" in writes.create_replacement(4512, 1, 1, "P-9999")
    pid = writes.record_proposal(c_proposal("hold", {"order_id": 4510, "product_id": 4, "qty": 1, "hold_days": 2}))["id"]
    assert "not approved" in writes.create_hold(4510, 4, 1, 2, pid)["error"]
    writes.record_decision(pid, "approve", "test")
    assert "does not match" in writes.create_hold(4510, 4, 2, 2, pid)["error"]     # qty 2 was not approved
    assert writes.create_hold(4510, 4, 1, 2, pid)["status"] == "held"
    assert "already used" in writes.create_hold(4510, 4, 1, 2, pid)["error"]


def test_cd_tables_are_added_to_an_older_database():
    with closing(connect()) as con:
        con.executescript("DROP TABLE replacements; DROP TABLE holds; DROP TABLE assistance_requests;"
                          " DROP TABLE promotions;")
    d = coordinator.review(c_proposal("hold", {"order_id": 4510, "product_id": 4, "qty": 1, "hold_days": 1}),
                           yes_case("T-1"))
    assert d["outcome"] == "approve" and scalar("SELECT COUNT(*) FROM holds") == 1


# ---------- Agent D: promotions, the owner decides ----------

def test_scan_proposes_promotions_that_wait_for_the_owner(cd_tables):
    price = scalar("SELECT price FROM products WHERE id = 2")
    out = AgentD(use_model=False).scan()
    assert out["overstock"] and len(out["proposals"]) == len(out["decisions"]) <= 3
    assert {d["outcome"] for d in out["decisions"]} == {"owner_pending"}
    pending = approvals.promotions("pending")
    assert len(pending) == len(out["proposals"]) and all(p["discount_pct"] == 10 for p in pending)
    assert scalar("SELECT COUNT(*) FROM proposals WHERE action = 'promotion' AND decision IS NULL") == len(pending)
    again = AgentD(use_model=False).scan()           # one open promotion per product: sent back, nothing new
    assert {d["outcome"] for d in again["decisions"]} == {"send_back"}
    assert len(approvals.promotions("pending")) == len(pending)
    assert scalar("SELECT price FROM products WHERE id = 2") == price


def test_owner_approves_or_refuses_in_one_go(cd_tables):
    AgentD(use_model=False).scan()
    first, second = approvals.promotions("pending")[:2]
    assert "reason is required" in approvals.decide_promotion(second["id"], "owner", False, "")["error"]
    ok = approvals.decide_promotion(first["id"], "owner", True)
    assert ok["status"] == "approved" and ok["decided_by"] == "owner"
    assert scalar("SELECT decision FROM proposals WHERE id = ?", first["proposal_id"]) == "approve"
    assert scalar("SELECT action FROM admin_actions ORDER BY id DESC LIMIT 1") == "approve_promotion"
    assert "already approved" in approvals.decide_promotion(first["id"], "owner", True)["error"]
    no = approvals.decide_promotion(second["id"], "owner", False, "not this month")
    assert no["status"] == "refused"
    assert scalar("SELECT decision FROM proposals WHERE id = ?", second["proposal_id"]) == "layer3"


def test_promotion_above_the_rule_limit_is_sent_back(cd_tables):
    from callverse.tools.proposal_tools import promotion_proposal
    d = coordinator.review(promotion_proposal(2, 35, {}, "note"), coordinator.new_case("D"))
    assert d["outcome"] == "send_back" and "R-PRM-01" in d["reason"]
    assert approvals.promotions() == []


def test_model_only_words_the_note_and_its_numbers_are_checked():
    f = {"name": "Phone Case", "stock": 120, "units_sold_30d": 4}
    good = lambda role, messages, **kw: text_reply("Phone Case: 120 in stock, 4 sold in 30 days; try a 10% promotion.")
    assert word_note(f, 10, good) == ("Phone Case: 120 in stock, 4 sold in 30 days; try a 10% promotion.", "model")
    wrong = lambda role, messages, **kw: text_reply("Phone Case is selling slowly, try 15% off.")
    note, source = word_note(f, 10, wrong)
    assert source == "template" and "120 units in stock and 4 sold" in note

    def down(role, messages, **kw):
        raise ConnectionError("no model")
    assert word_note(f, 10, down)[1] == "template"


# ---------- Agent C in the pipeline ----------

def c_llm(confirmed: bool):
    """Fake models: Agent A hands over to C; C reads, checks the stock and proposes a replacement."""
    a_steps = iter([tool_call_reply(("get_tracking", {"order_id": 4512})),
                    text_reply("I am sorry. Your request is passed to our special help team. [HANDOVER: C]")])
    c_steps = iter([tool_call_reply(("get_order", {"order_id": 4512})),
                    tool_call_reply(("check_availability_with_d", {"product_id": 1})),
                    tool_call_reply(("propose_replacement", {**REPLACE_4512, "user_confirmed": confirmed,
                                                             "user_quote": "I need it tomorrow, it is a gift."}))])

    def fake(role_key, messages, tools=None, **kw):
        if role_key == "agent_c":
            assert messages[0]["content"].startswith("You are Agent C")
            return next(c_steps, None) or text_reply("A replacement is being checked.")
        return next(a_steps, None) or text_reply("ok")
    return fake


TICKET = {"ticket_id": "T-1", "text": "Order 4512 is late and I need it tomorrow for a gift!", "order_id": 4512,
          "main_reason": "late_delivery", "priority_label": "high"}


def test_a_hands_over_to_c_which_asks_the_client_first(cd_tables):
    out = pipeline.handle_ticket(dict(TICKET), chat_fn=c_llm(confirmed=False))
    assert out["handover"] == "C" and out["handover_text"] == "Your request is passed on to our special help team."
    assert out["decision"]["outcome"] == "ask_user" and out["proposal"]["action"] == "replace"
    assert scalar("SELECT COUNT(*) FROM replacements") == 0


def test_the_clients_yes_goes_back_to_c_and_is_approved(cd_tables):
    ticket = {**TICKET, "text": "Yes please, send the replacement.", "continue_agent": "C"}
    out = pipeline.handle_ticket(ticket, chat_fn=c_llm(confirmed=True))
    assert out["handover"] == "C" and out["decision"]["outcome"] == "approve"
    assert scalar("SELECT COUNT(*) FROM replacements") == 1


def test_agent_a_tag_parsing():
    a = agent_a.AgentA(chat_fn=lambda *a, **k: None)
    assert a.postprocess("Passed on. [HANDOVER: C]") == {"answer": "Passed on.", "handover": "C"}
    assert a.postprocess("Passed on. [handover: b]")["handover"] == "B"


def test_layer2_switch(monkeypatch, cd_tables):
    escalated = coordinator.escalate_decision(4512, "too many send-backs")
    real = pipeline.run_agent_with_coordinator

    def run(agent_cls, message, ticket, chat_fn=None):
        if agent_cls is AgentC:
            assert "[Layer 2:" in message
            return real(agent_cls, message, ticket, chat_fn)
        return {"answer": "x", "tool_calls": [], "handover": None}, [], escalated
    monkeypatch.setattr(pipeline, "run_agent_with_coordinator", run)
    on = pipeline.handle_ticket(dict(TICKET), chat_fn=c_llm(confirmed=False))   # switch ON (default, spec)
    assert on["handover"] == "C" and on["decision"]["outcome"] == "ask_user" and "layer2" in steps()
    cfg = pipeline.load_config()
    monkeypatch.setattr(pipeline, "load_config", lambda: {**cfg, "pipeline": {**cfg["pipeline"], "layer2_agent_c": False}})
    off = pipeline.handle_ticket(dict(TICKET), chat_fn=c_llm(confirmed=False))
    assert off["decision"]["outcome"] == "escalate"            # switch OFF: C is not called


def test_web_chat_sends_the_answer_to_c_after_its_question(tmp_path, cd_tables):
    store.use_db(tmp_path / "tickets.db")
    try:
        t = store.create_ticket("shopnova", 1)
        mid = store.add_message(t["id"], "user", "I need 4512 tomorrow")
        store.add_step(t["id"], mid, "coordinator", "coordinator",
                       {"trace_step": "coordinator_decision", "outcome": "ask_user", "action": "replace",
                        "order_id": 4512})
        t = store.update_ticket(t["id"], status="Waiting for user")
        assert web_chat.c_waiting_order(t) == (True, 4512)
        assert web_chat.c_waiting_order(store.update_ticket(t["id"], status="Solved")) == (False, None)
    finally:
        store.use_db(store.DEFAULT_DB_PATH)


def test_c_offer_written_as_text_gets_one_retry(cd_tables):
    """P20: C names its offer in text (no tool call) -> one more run with a note; then the real proposal counts."""
    assert pipeline.c_offer_in_text({"agent": "C", "tool_calls": [], "answer": '{"offer": "hold"}'})
    assert not pipeline.c_offer_in_text({"agent": "C", "tool_calls": [], "answer": "Please send your order number."})
    assert not pipeline.c_offer_in_text({"agent": "A", "tool_calls": [], "answer": "a replacement"})
    replies = iter([tool_call_reply(("get_order", {"order_id": 4512})),
                    text_reply('{"offer": "replacement", "user_confirmed": false}'),       # first run: text only
                    tool_call_reply(("propose_replacement", {**REPLACE_4512, "user_confirmed": False,
                                                             "user_quote": "I need it tomorrow"})),
                    text_reply("A replacement is being checked.")])
    seen = []

    def fake(role_key, messages, tools=None, **kw):
        seen.append(messages[-1]["content"] if messages[-1]["role"] == "user" else "")
        return next(replies)
    result, proposals, decision = pipeline.run_agent_with_coordinator(AgentC, "I need 4512 tomorrow", TICKET, fake)
    assert decision["outcome"] == "ask_user" and len(proposals) == 1
    assert "c_offer_retry" in steps() and any("no proposal tool was called" in s for s in seen)


# ---------- P20 gaps: the links C -> A, C -> D, C -> B (urgent refund) ----------

def test_can_meet_deadline_is_computed_from_a_facts():
    from callverse.agents.ask_c import can_meet
    on_time = {"status": "shipped", "delivered": False, "days_late": 0, "promised_date": "2026-10-10"}
    assert can_meet(on_time, "2026-10-10") == ("2026-10-10", True, "on time")
    assert can_meet(on_time, "2026-10-09")[1] is False
    stuck = {"status": "stuck_at_depot", "delivered": False, "days_late": 8, "promised_date": "2026-10-01"}
    assert can_meet(stuck, "2026-10-10")[:2] == (None, False)
    assert can_meet({"delivered": True, "delivered_date": "2026-09-14"}, "2026-10-10")[1] is True
    assert can_meet({"error": "no order"}, "2026-10-10")[1] is None


def test_c_asks_a_for_the_facts_and_d_for_the_stock():
    def a_model(role_key, messages, tools=None, **kw):
        assert role_key == "agent_c" and messages[0]["content"].startswith("You are Agent A")
        if messages[-1]["role"] == "user":
            return tool_call_reply(("get_tracking", {"order_id": 4510}))
        return text_reply("Order 4510 is on its way.")
    out = registry.run_tool("C", "get_facts_from_a", {"order_id": 4510, "deadline": "2026-10-12"}, chat_fn=a_model)
    assert out["facts"]["source"] == "get_tracking" and out["can_meet_deadline"] is True and out["eta"] == "2026-10-10"
    d = registry.run_tool("C", "check_availability_with_d", {"product_id": 1, "qty": 2})
    assert d["agent"] == "D" and d["available"] is True and d["stock"] == 40
    assert registry.run_tool("C", "check_availability_with_d", {"product_id": 1, "qty": 41})["available"] is False


def test_c_hands_a_money_request_to_b_as_urgent(tmp_path, cd_tables):
    b_steps = iter([tool_call_reply(("get_order", {"order_id": 4515}), ("get_refunds", {"order_id": 4515})),
                    tool_call_reply(("propose_refund", {"order_id": 4515, "amount": 378.0, "rule_id": "R-REF-03",
                                                        "facts_used": {"days_late": 8}, "user_confirmed": True,
                                                        "user_quote": "I want my money back now"}))])

    def fake(role_key, messages, tools=None, **kw):
        if role_key == "agent_c":
            if messages[-1]["role"] == "user":
                return tool_call_reply(("get_order", {"order_id": 4515}))
            return text_reply("I pass this on as urgent. [HANDOVER: B]")
        return next(b_steps, None) or text_reply("Sent for checking.")
    ticket = {**TICKET, "order_id": 4515, "text": "I need my money back now, urgent!", "continue_agent": "C"}
    out = pipeline.handle_ticket(ticket, chat_fn=fake)
    assert out["handover"] == "B" and ticket["urgent"] is True
    assert out["proposal"]["action"] == "refund"
    store.use_db(tmp_path / "t.db")
    try:
        t = store.create_ticket("shopnova", 2)
        normal = store.create_approval(t["id"], 4512, 59.9, "P-1")
        urgent = store.create_approval(t["id"], 4515, 378.0, "P-2", urgent=True)
        assert [a["id"] for a in store.approvals("pending")] == [urgent["id"], normal["id"]]
    finally:
        store.use_db(store.DEFAULT_DB_PATH)
