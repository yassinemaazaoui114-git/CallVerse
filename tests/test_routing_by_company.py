"""T21 tests: one center, two companies. Atlas Travel goes through the same pipeline; ShopNova behaves as before.

No API call: the agents get a fake LLM, the SLM is offline (conftest: its template is used), the quota check is
replaced. Intake runs its local models. The practice messages are read from tests/dev (a practice set, not held-out).
"""

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from callverse import companies, pipeline
from callverse.agents import agent_a, agent_b
from callverse.agents.agent_a import AgentA
from callverse.agents.agent_b import AgentB
from callverse.channels import approvals, web_chat
from callverse.console import reads as console
from callverse.coordinator import atlas_coordinator as gate
from callverse.coordinator.coordinator import new_case
from callverse.coordinator.coordinator import review as shopnova_review
from callverse.data.atlas import db as atlas_db
from callverse.data.atlas import reads, writes
from callverse.data.atlas.seed import seed
from callverse.intake import extract, intake, llm_fallback, priority, reasons
from callverse.kb import search
from callverse.kb.policies import check_condition, get_policy
from callverse.queues.router import route
from callverse.slm import check, writer
from callverse.tickets import store
from callverse.tools import proposal_tools, registry

PRACTICE = json.loads(open("tests/dev/atlas_practice_messages.json", encoding="utf-8").read())["messages"]
CLIENT_QUOTE = "as the client wrote it"


@pytest.fixture(scope="module")
def atlas_template(tmp_path_factory):
    return seed(tmp_path_factory.mktemp("atlas_template") / "atlas.db")


@pytest.fixture(autouse=True)
def fresh_center(tmp_path, atlas_template, monkeypatch):
    """A fresh atlas.db and tickets database per test; Agent B's quota is "there"."""
    shutil.copyfile(atlas_template, tmp_path / "atlas.db")
    atlas_db.use_db(tmp_path / "atlas.db")
    store.use_db(tmp_path / "callverse.db")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    yield
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)
    store.use_db(store.DEFAULT_DB_PATH)


@pytest.fixture
def queue(monkeypatch):
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "queue")


def sql(statement: str, *params) -> list:
    con = atlas_db.connect()
    try:
        rows = con.execute(statement, params).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def rows_for(table: str, booking_id: int) -> list:
    return sql(f"SELECT * FROM {table} WHERE booking_id = ? AND proposal_id IS NOT NULL", booking_id)


def tool_call(name, arguments, call_id="call_1"):
    call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[call])


def text(answer):
    return SimpleNamespace(content=answer, tool_calls=None)


def quoting_the_client(reply, messages):
    """A scripted proposal quotes the client's real words, as the real agent does (the Coordinator checks the quote)."""
    for call in reply.tool_calls or []:
        arguments = json.loads(call.function.arguments)
        if arguments.get("user_quote") == CLIENT_QUOTE:
            arguments["user_quote"] = messages[1]["content"].split("\n\n")[0]
            call.function.arguments = json.dumps(arguments)
    return reply


def scripted(*steps):
    """A fake LLM that gives these replies in order, then a final text."""
    replies = iter(steps)

    def fake(role_key, messages, tools=None):
        return quoting_the_client(next(replies, None) or text("It is sent for checking."), messages)
    return fake


def proposal_args(booking_type, booking_id, rule_id, confirmed=True):
    return {"booking_type": booking_type, "booking_id": booking_id, "rule_id": rule_id, "facts_used": {"read": True},
            "user_confirmed": confirmed, "user_quote": CLIENT_QUOTE}


def propose(tool, booking_type, booking_id, rule_id, confirmed=True):
    """A fake Agent B that calls one proposal tool, then answers."""
    return scripted(tool_call(tool, proposal_args(booking_type, booking_id, rule_id, confirmed)))


def read_then_answer(tool, booking_id):
    return scripted(tool_call(tool, {"booking_id": booking_id}))


def proposal(action, booking_type, booking_id, rule_id, confirmed=True):
    return proposal_tools.atlas_proposal("B", action, proposal_args(booking_type, booking_id, rule_id, confirmed))


def case_for(booking_type, booking_id):
    return {**new_case("T-1"), "order_id": booking_id, "booking_type": booking_type, "main_reason": "refund_request",
            "user_message": f"Please: {CLIENT_QUOTE}."}


def review(action, booking_type, booking_id, rule_id, confirmed=True):
    return gate.review(proposal(action, booking_type, booking_id, rule_id, confirmed), case_for(booking_type, booking_id))


def send(user_id, message, chat_fn, **kw):
    return web_chat.send(user_id, "atlas", message, chat_fn=chat_fn, **kw)


# ---------- ShopNova is unchanged ----------

def sha(text_value: str) -> str:
    return hashlib.sha256(text_value.encode()).hexdigest()


def test_shopnova_prompts_are_byte_identical_to_main():
    """Fingerprints taken on main (1a1c6ee) before T21 touched any code."""
    assert sha(agent_a.SYSTEM_PROMPT) == "3b102f36fb9db23facab8bd358a10f731f28e454ade59c49e84e66fbda2bc2dc"
    assert sha(agent_b.SYSTEM_PROMPT) == "054a224631ae0d5184d5d1cd4c6f95d8e489838646037e1407f7ffbc55c49aa8"
    assert sha(llm_fallback.PROMPT) == "e74367e65a93afdffc806e2f2e4035b3cea0c145a468027790acebfc56475f17"
    assert sha(writer.SYSTEM_PROMPT) == "2a468702bf7f0393fb322bfcca84e48529e466067a6e88f432590dd0655448f2"


def test_shopnova_agents_use_those_prompts():
    assert AgentA().system_prompt() == agent_a.SYSTEM_PROMPT.format(today="2026-10-09")
    assert AgentB().system_prompt() == agent_b.SYSTEM_PROMPT.format(today="2026-10-09")


def test_shopnova_tool_schemas_are_identical_to_main():
    assert sha(json.dumps(registry.TOOL_SCHEMAS, sort_keys=True)) == (
        "d49abf10a9c8b26e2282479fa359d2c5a80ddb778619fb1484775f2176dd14d9")


def test_shopnova_reply_messages_are_identical_to_main():
    decision = {"outcome": "approve", "action": "refund", "order_id": 4512,
                "facts": {"amount_tnd": 59.9, "days_late": 7}, "must_say": ["Your refund of 59.90 TND is approved."],
                "next_step": "Your order 4512 is now refunded.", "style": {"formality": "neutral", "length": "short"}}
    assert sha(json.dumps(writer.build_messages(decision), ensure_ascii=False)) == (
        "7846ceadc377ec0744813f54a2e33a5f3ff84abff940c7e67f8aade852695468")


def test_shopnova_routes_reasons_and_rules_are_unchanged():
    shopnova = companies.get("shopnova")
    assert shopnova["routes"] == {"order_status": "A", "late_delivery": "A", "refund_request": "B", "return_item": "B",
                                  "damaged_item": "B", "other": "A"}
    assert shopnova["reasons"] == reasons.REASONS
    assert shopnova["reason_threshold"] == 0.66
    assert shopnova["main_reason_order"] == ["damaged_item", "refund_request", "return_item", "late_delivery",
                                             "order_status", "other"]
    assert shopnova["allowed_rules"] == {"refund": ["R-REF-03", "R-RET-01", "R-DMG-01"],
                                         "subscribe": ["R-NOT-01", "R-DEL-02"]}
    assert get_policy("R-ESC-01")["condition"] == "amount > 300"


def test_shopnova_extract_does_not_read_booking_words():
    text_value = "booking 7005 and my parcel 4512"
    assert extract.extract(text_value)["order_id"] == 4512
    assert extract.extract(text_value, "atlas")["order_id"] == 7005


def test_a_shopnova_ticket_keeps_the_keys_it_had():
    ticket = intake.process("Where is my order 4510?", use_llm=False)
    assert ticket["company"] == "shopnova" and "booking_type" not in ticket
    assert set(ticket["facts"]) == {"days_late", "delivered", "paid"}


def test_a_ticket_without_a_company_is_shopnova():
    assert companies.of({}) == companies.of(None) == "shopnova"
    assert route({"main_reason": "refund_request", "priority_label": "low"})["agent"] == "B"


def test_an_unknown_company_is_an_error_not_shopnova():
    with pytest.raises(ValueError, match="unknown company"):
        companies.get("nowhere")


# ---------- the company comes from the channel ----------

def test_the_company_is_never_guessed_from_the_text():
    ticket = intake.process("I am an Atlas Travel client, my flight booking 7005 was cancelled", use_llm=False)
    assert ticket["company"] == "shopnova"
    assert intake.process("Where is my ShopNova order 4510?", use_llm=False, company="atlas")["company"] == "atlas"


def test_the_ticket_keeps_its_company_from_the_channel():
    out = send(5, "Hi, is my flight booking 7010 still on schedule?", read_then_answer("get_flight_booking", 7010))
    assert store.get_ticket(out["ticket_id"])["company"] == "atlas"


# ---------- bookings 7011, 7012 ----------

def test_the_two_new_scripted_bookings():
    b = reads.get_hotel_booking(7011)
    assert (b["user_id"], b["hotel_id"], b["booked_date"], b["arrival_date"], b["nights"], b["adults"], b["meal"],
            b["room_reserved"], b["room_assigned"], b["deposit_type"], b["price_per_night_tnd"], b["total_tnd"],
            b["paid_tnd"], b["status"]) == (1, 1, "2026-09-25", "2026-10-20", 2, 2, "BB", "A", "A", "refundable",
                                            110.00, 220.00, 220.00, "confirmed")
    b = reads.get_hotel_booking(7012)
    assert (b["user_id"], b["hotel_id"], b["booked_date"], b["arrival_date"], b["nights"], b["adults"], b["meal"],
            b["room_reserved"], b["room_assigned"], b["deposit_type"], b["price_per_night_tnd"], b["total_tnd"],
            b["paid_tnd"], b["status"]) == (2, 2, "2026-09-15", "2026-10-25", 4, 2, "HB", "D", "D", "non_refundable",
                                            100.00, 400.00, 400.00, "confirmed")


def test_booking_ids_are_unique_across_the_two_tables():
    assert not sql("SELECT h.id FROM hotel_bookings h JOIN flight_bookings f ON f.id = h.id")


# ---------- Intake ----------

@pytest.mark.parametrize("message, number", [
    ("booking 7005 please", 7005), ("my reservation 20417", 20417), ("flight booking 30588", 30588),
    ("order 7003", 7003), ("I paid 1500 TND for booking 7005", 7005), ("cancel #7011", 7011),
])
def test_atlas_extract(message, number):
    assert extract.extract(message, "atlas")["order_id"] == number


@pytest.mark.parametrize("number, kind", [(7003, "hotel"), (7005, "flight"), (7012, "hotel"), (7010, "flight"),
                                          (20001, "hotel"), (30001, "flight"), (99999, None)])
def test_the_booking_type_comes_from_the_data(number, kind):
    assert reads.booking_type(number) == kind


def test_a_message_cannot_choose_the_booking_type():
    ticket = intake.process("my hotel booking 7005 was cancelled", use_llm=False, company="atlas")
    assert ticket["booking_type"] == "flight"


def test_atlas_facts_are_read_not_written():
    before = sql("SELECT COUNT(*) FROM proposals")[0][0]
    ticket = intake.process("Booking 7005: my flight was cancelled.", use_llm=False, company="atlas")
    assert ticket["facts"]["status"] == "cancelled" and ticket["facts"]["paid"] == 1500.00
    assert sql("SELECT COUNT(*) FROM proposals")[0][0] == before


def test_atlas_threshold_comes_from_leave_one_out_on_its_examples():
    row = reasons.leave_one_out([0.68], "atlas")[0]
    assert (row["exact"], row["wrong"], row["needs_llm"], row["total"]) == (58, 10, 12, 80)
    assert companies.get("atlas")["reason_threshold"] == 0.68


def test_shopnova_leave_one_out_is_unchanged():
    row = reasons.leave_one_out([0.66])[0]
    assert (row["exact"], row["wrong"], row["needs_llm"], row["total"]) == (47, 4, 9, 60)


@pytest.mark.parametrize("message, reason", [
    ("I want the compensation for my delayed flight", "compensation_request"),
    ("I use a wheelchair and need help at the airport", "special_assistance"),
    ("Please cancel my hotel reservation", "cancellation"),
])
def test_atlas_matcher_finds_atlas_reasons(message, reason):
    assert reasons.match_reasons(message, company="atlas")["reasons"][0]["reason"] == reason


def test_atlas_examples_are_not_shopnova_reasons():
    assert set(reasons.load_examples("atlas")) == set(companies.get("atlas")["reasons"])
    assert "order_status" not in reasons.example_vectors("atlas")


def test_atlas_main_reason_order():
    assert intake.pick_main_reason(["delay_disruption", "special_assistance"], "atlas") == "special_assistance"
    assert intake.pick_main_reason(["refund_request", "compensation_request"], "atlas") == "compensation_request"
    assert intake.pick_main_reason(["cancellation", "refund_request"], "atlas") == "refund_request"


def test_llm_fallback_uses_the_company_list():
    def fake(role_key, messages, tools=None):
        assert "Atlas Travel" in messages[0]["content"] and "ShopNova" not in messages[0]["content"]
        return text('{"reasons": ["rebooking", "order_status"], "order_id": 7005}')
    answer = llm_fallback.classify("change my trip", chat_fn=fake, company="atlas")
    assert answer["reasons"] == ["rebooking"] and answer["order_id"] == 7005    # a ShopNova reason is dropped


@pytest.mark.parametrize("hours, pressure", [(23, 1.0), (24, 1.0), (24.5, 0.5), (72, 0.5), (72.5, 0.0), (500, 0.0),
                                             (-3, 0.0), (None, 0.0), (0, 1.0)])
def test_atlas_time_pressure(hours, pressure):
    assert priority.compute(["other"], {"hours_to_start": hours}, 0.0, "atlas")["time_pressure"] == pressure


def test_atlas_priority_uses_the_same_weights_and_labels():
    p = priority.compute(["special_assistance"], {"hours_to_start": 10}, 0.5, "atlas")
    assert p["severity"] == 0.7
    assert p["priority_score"] == round(0.6 * 0.7 + 0.25 * 1.0 + 0.15 * 0.5, 3)
    assert p["priority_label"] == "high"


@pytest.mark.parametrize("reason, severity", [
    ("special_assistance", 0.7), ("rebooking", 0.6), ("delay_disruption", 0.5), ("refund_request", 0.5),
    ("cancellation", 0.4), ("compensation_request", 0.4), ("booking_status", 0.2), ("other", 0.2)])
def test_atlas_severity_base(reason, severity):
    assert priority.compute([reason], {}, 0.0, "atlas")["severity"] == severity


# ---------- routes ----------

@pytest.mark.parametrize("reason, agent", [
    ("booking_status", "A"), ("delay_disruption", "A"), ("other", "A"), ("refund_request", "B"),
    ("compensation_request", "B"), ("cancellation", "B"), ("rebooking", "escalate"), ("special_assistance", "escalate"),
])
def test_atlas_routes(reason, agent):
    assert route({"company": "atlas", "main_reason": reason, "priority_label": "low"})["agent"] == agent


def no_llm(role_key, messages, tools=None):
    raise AssertionError("no LLM call expected")


def test_an_escalate_route_runs_no_agent():
    ticket = intake.process("I use a wheelchair, I need help at the airport for my flight 7010.", use_llm=False,
                            company="atlas")
    out = pipeline.handle_ticket(ticket, chat_fn=no_llm)
    assert out["decision"]["outcome"] == "escalate" and out["proposal"] is None
    assert "Your request has been passed on to a colleague who will help you with it." in out["final_reply"]


# ---------- agents and tools ----------

def test_atlas_prompts_are_atlas_and_keep_the_safety_lines():
    a = AgentA(company="atlas").system_prompt()
    b = AgentB(company="atlas").system_prompt()
    assert "Atlas Travel" in a and "ShopNova" not in a and "[HANDOVER: B]" in a
    assert "Atlas Travel" in b and "ShopNova" not in b
    for line in ("Never give an amount", "MUST call the proposal tool", "never promise money", "no Markdown",
                 "Use only facts from tools", "e.g. (rule AT-FLT-01)"):
        assert line in b


def tool_names(agent, company):
    return [t["function"]["name"] for t in registry.schemas_for(agent, company)]


def test_atlas_allow_lists():
    assert tool_names("A", "atlas") == ["get_user", "get_hotel_booking", "get_flight_booking", "get_flight",
                                        "get_company_profile", "search_policy"]
    assert tool_names("B", "atlas") == ["get_hotel_booking", "get_flight_booking", "get_refunds", "search_policy",
                                        "propose_refund", "propose_compensation", "propose_hotel_cancellation",
                                        "ask_agent"]


@pytest.mark.parametrize("agent", ["A", "B"])
def test_atlas_tools_are_never_run_for_a_shopnova_agent(agent):
    assert "refused" not in str(registry.run_tool("B", "get_order", {"order_id": 4512}))
    assert "not allowed" in registry.run_tool(agent, "get_flight_booking", {"booking_id": 7005})["error"]


@pytest.mark.parametrize("agent", ["A", "B"])
def test_shopnova_tools_are_never_run_for_an_atlas_agent(agent):
    assert "not allowed" in registry.run_tool(agent, "get_order", {"order_id": 4512}, company="atlas")["error"]
    assert "not allowed" in registry.run_tool(agent, "get_tracking", {"order_id": 4512}, company="atlas")["error"]


def test_atlas_a_and_b_keep_their_jobs():
    assert "not allowed" in registry.run_tool("A", "propose_refund", {}, company="atlas")["error"]
    assert "not allowed" in registry.run_tool("A", "get_refunds", {}, company="atlas")["error"]
    assert "not allowed" in registry.run_tool("B", "get_user", {"user_id": 1}, company="atlas")["error"]


def test_a_shopnova_agent_sees_no_atlas_tool():
    assert not set(tool_names("B", "shopnova")) & {"propose_compensation", "propose_hotel_cancellation",
                                                   "get_flight_booking", "get_hotel_booking"}


@pytest.mark.parametrize("tool", list(proposal_tools.ATLAS_SCHEMAS))
def test_atlas_proposal_tools_have_no_amount(tool):
    parameters = proposal_tools.ATLAS_SCHEMAS[tool]["function"]["parameters"]
    assert "amount" not in parameters["properties"]
    assert parameters["required"] == ["booking_type", "booking_id", "rule_id", "facts_used", "user_confirmed",
                                      "user_quote"]


def test_an_amount_from_the_agent_is_refused():
    args = {**proposal_args("flight", 7005, "AT-FLT-01"), "amount": 99999}
    result = registry.run_tool("B", "propose_refund", args, company="atlas")
    assert "error" in result and "amount" in result["error"]


def test_a_proposal_writes_nothing():
    assert "status" in registry.run_tool("B", "propose_refund", proposal_args("flight", 7005, "AT-FLT-01"), company="atlas")
    assert not sql("SELECT 1 FROM proposals") and not rows_for("refunds", 7005)


def test_a_shopnova_rule_does_not_exist_for_atlas():
    result = registry.run_tool("B", "propose_refund", proposal_args("flight", 7005, "R-REF-03"), company="atlas")
    assert "does not exist" in result["error"]


def test_ask_agent_keeps_the_company():
    chat = scripted(tool_call("get_flight_booking", {"booking_id": 7004}), text("It arrived late."))
    out = registry.run_tool("B", "ask_agent", {"agent": "A", "question": "Status of 7004?"}, chat_fn=chat, company="atlas")
    assert out["facts"]["source"] == "get_flight_booking" and out["facts"]["arrival_delay_min"] == 200


def test_the_model_cannot_choose_the_company_of_ask_agent():
    chat = scripted(text("nothing"))
    out = registry.run_tool("B", "ask_agent", {"agent": "A", "question": "?", "company": "atlas"}, chat_fn=chat)
    assert out["facts"] == {"error": "Agent A did not read the tracking data"}   # ShopNova's path, not Atlas's


# ---------- rule search per company ----------

def test_rule_search_stays_in_the_company():
    atlas = search.company_search_tool("atlas", "my flight was cancelled, I want my money back")
    assert atlas["results"] and all(r["id"].startswith("AT-") for r in atlas["results"])
    assert atlas["results"][0]["id"] == "AT-FLT-01"


def test_atlas_search_policy_tool_finds_atlas_rules_only():
    out = registry.run_tool("B", "search_policy", {"query": "hotel room different from the one booked"}, company="atlas")
    assert out["results"][0]["id"] == "AT-HOT-04"


def test_shopnova_search_is_unchanged():
    assert all(r["id"].startswith("R-") for r in search.search_policy("my parcel is late, refund me"))


def test_each_company_has_its_own_cache_file():
    assert companies.path("atlas", "policy_cache") != companies.path("shopnova", "policy_cache")
    assert companies.path("atlas", "reason_cache") != companies.path("shopnova", "reason_cache")
    assert search.policy_vectors("atlas").shape[0] == 14


# ---------- the Coordinator: amounts by code ----------

@pytest.mark.parametrize("action, kind, booking, rule, amount", [
    ("refund", "flight", 7005, "AT-FLT-01", 1500.00),
    ("refund", "flight", 7008, "AT-FLT-01", 690.00),
    ("refund", "hotel", 7009, "AT-HOT-02", 450.00),
    ("refund", "hotel", 7003, "AT-HOT-04", 72.00),
    ("cancel_hotel", "hotel", 7011, "AT-HOT-02", 220.00),
])
def test_refund_amounts_are_computed_by_code(action, kind, booking, rule, amount):
    decision = review(action, kind, booking, rule)
    assert decision["outcome"] == "approve" and decision["facts"]["amount_tnd"] == amount
    assert sql("SELECT amount FROM refunds WHERE proposal_id = ?", decision["proposal_id"])[0]["amount"] == amount


def test_at_flt_04_refund_is_what_is_left(queue):
    decision = review("refund", "flight", 7006, "AT-FLT-04")
    assert decision["outcome"] == "layer3_pending" and decision["facts"]["amount_tnd"] == 1900.00


def test_full_refund_takes_off_what_was_already_refunded():
    sql("INSERT INTO refunds (booking_type, booking_id, amount, status) VALUES ('flight', 7008, 90, 'completed')")
    assert review("refund", "flight", 7008, "AT-FLT-01")["facts"]["amount_tnd"] == 600.00


def test_room_change_refund_is_capped_by_the_limit():
    sql("INSERT INTO refunds (booking_type, booking_id, amount, status) VALUES ('hotel', 7003, 300, 'completed')")
    assert review("refund", "hotel", 7003, "AT-HOT-04")["facts"]["amount_tnd"] == 60.00


def test_room_change_is_paid_once_even_if_money_is_left():
    assert review("refund", "hotel", 7003, "AT-HOT-04")["outcome"] == "approve"
    again = review("refund", "hotel", 7003, "AT-HOT-04")
    assert again["outcome"] == "send_back" and len(rows_for("refunds", 7003)) == 1


def test_room_change_money_comes_back_rounded_to_two_decimals():
    sql("UPDATE hotel_bookings SET total_tnd = 333.33, paid_tnd = 333.33 WHERE id = 7003")
    assert review("refund", "hotel", 7003, "AT-HOT-04")["facts"]["amount_tnd"] == 66.67


@pytest.mark.parametrize("km, rule, delay, amount", [
    (1500, "AT-FLT-02", None, 839.50), (1500.1, "AT-FLT-02", None, 1343.20), (3500, "AT-FLT-02", None, 1343.20),
    (3500.1, "AT-FLT-02", None, 2014.80), (1200, "AT-FLT-03", 200, 839.50), (2000, "AT-FLT-03", 200, 1343.20),
    (4000, "AT-FLT-03", 180, 1007.40), (4000, "AT-FLT-03", 239, 1007.40), (4000, "AT-FLT-03", 240, 2014.80),
])
def test_compensation_bands(km, rule, delay, amount):
    assert gate.compensation_amount(rule, {"distance_km": km, "arrival_delay_min": delay}) == amount


def test_every_band_is_written_in_the_rule_text():
    for rule_id, bands in (("AT-FLT-02", ("839.50", "1,343.20", "2,014.80")),
                           ("AT-FLT-03", ("839.50", "1,343.20", "2,014.80", "1,007.40"))):
        assert all(band in get_policy(rule_id, "atlas")["text"] for band in bands)
    assert [f"{gate.BAND_SHORT:.2f}", f"{gate.BAND_MEDIUM:.2f}", f"{gate.BAND_LONG:.2f}",
            f"{gate.BAND_LONG_3_TO_4_HOURS:.2f}"] == ["839.50", "1343.20", "2014.80", "1007.40"]


@pytest.mark.parametrize("booking, rule, amount", [(7004, "AT-FLT-03", 839.50), (7005, "AT-FLT-02", 1343.20)])
def test_compensation_amount_on_scripted_bookings(queue, booking, rule, amount):
    decision = review("compensation", "flight", booking, rule)
    assert decision["outcome"] == "layer3_pending" and decision["facts"]["amount_tnd"] == amount
    assert decision["must_say"] == [f"Your compensation of {amount:.2f} TND for booking {booking} needs approval from "
                                    "our finance team."]


def test_compensation_blocked_by_an_extraordinary_cause():
    decision = review("compensation", "flight", 7008, "AT-FLT-02")      # weather
    assert decision["outcome"] == "send_back" and not rows_for("compensations", 7008)


def test_extraordinary_rule_blocks_even_if_the_condition_text_changed(monkeypatch):
    real = gate._rule_holds
    monkeypatch.setattr(gate, "_rule_holds", lambda *a: True if a[1]["id"] == "AT-FLT-02" else real(*a))
    decision = review("compensation", "flight", 7008, "AT-FLT-02")
    assert decision["outcome"] == "send_back" and "AT-FLT-06" in decision["reason"]


def test_compensation_blocked_by_14_days_notice():
    sql("UPDATE flight_bookings SET notice_days = 14 WHERE id = 7005")
    assert review("compensation", "flight", 7005, "AT-FLT-02")["outcome"] == "send_back"


def test_compensation_allowed_at_13_days_notice(queue):
    sql("UPDATE flight_bookings SET notice_days = 13 WHERE id = 7005")
    assert review("compensation", "flight", 7005, "AT-FLT-02")["outcome"] == "layer3_pending"


def test_compensation_for_a_short_delay_is_sent_back():
    assert review("compensation", "flight", 7007, "AT-FLT-03")["outcome"] == "send_back"


def test_compensation_for_an_air_system_delay_is_sent_back():
    assert review("compensation", "flight", 7006, "AT-FLT-03")["outcome"] == "send_back"


# ---------- the Coordinator: the other checks ----------

def test_a_proposal_on_another_booking_is_sent_back():
    decision = gate.review(proposal("refund", "flight", 7005, "AT-FLT-01"), case_for("flight", 7008))
    assert decision["outcome"] == "send_back" and not rows_for("refunds", 7005)


def test_the_wrong_booking_type_is_sent_back():
    assert review("refund", "hotel", 7005, "AT-FLT-01")["outcome"] == "send_back"


def test_a_rule_that_cannot_justify_the_action_is_sent_back():
    assert review("refund", "flight", 7005, "AT-FLT-02")["outcome"] == "send_back"
    assert review("compensation", "flight", 7005, "AT-FLT-01")["outcome"] == "send_back"


def test_a_rule_whose_condition_is_false_is_sent_back():
    assert review("refund", "flight", 7007, "AT-FLT-01")["outcome"] == "send_back"


@pytest.mark.parametrize("rule_id", ["AT-FLT-05", "AT-FLT-06", "AT-REF-01", "AT-ESC-01", "AT-AST-01", "AT-HOT-05"])
@pytest.mark.parametrize("action", ["refund", "compensation", "cancel_hotel"])
def test_information_rules_justify_no_action(action, rule_id):
    assert rule_id not in companies.get("atlas")["allowed_rules"][action]


def test_an_unknown_action_is_sent_back():
    assert review("buy_a_plane", "flight", 7005, "AT-FLT-01")["outcome"] == "send_back"


def test_an_unconfirmed_request_asks_the_client():
    case = {**case_for("flight", 7005), "main_reason": "booking_status"}
    decision = gate.review(proposal("refund", "flight", 7005, "AT-FLT-01"), case)
    assert decision["outcome"] == "ask_user" and not rows_for("refunds", 7005)
    assert decision["must_say"] == ["Please confirm that you want a refund of 1500.00 TND for booking 7005."]


def test_the_code_confirms_what_the_agent_left_false():
    assert review("refund", "flight", 7005, "AT-FLT-01", confirmed=False)["outcome"] == "approve"
    assert rows_for("refunds", 7005)[0]["amount"] == 1500.00


def test_the_agents_true_is_not_enough():
    case = {**case_for("flight", 7005), "user_message": "My flight was cancelled."}
    decision = gate.review(proposal("refund", "flight", 7005, "AT-FLT-01", confirmed=True), case)
    assert decision["outcome"] == "ask_user" and not rows_for("refunds", 7005)


@pytest.mark.parametrize("reason", ["refund_request", "compensation_request", "cancellation"])
def test_a_request_reason_with_a_real_quote_confirms(reason):
    assert gate.client_confirmed({"user_quote": "refund me"}, {"main_reason": reason, "user_message": "Please refund me."})


@pytest.mark.parametrize("reason", ["booking_status", "delay_disruption", "rebooking", "special_assistance", "other", None])
def test_any_other_reason_does_not_confirm(reason):
    assert not gate.client_confirmed({"user_quote": "refund me", "user_confirmed": True},
                                     {"main_reason": reason, "user_message": "Please refund me."})


@pytest.mark.parametrize("quote", ["REFUND ME", "  refund me  ", "Please refund me."])
def test_the_quote_ignores_case_and_outer_spaces(quote):
    assert gate.client_confirmed({"user_quote": quote}, {"main_reason": "refund_request", "user_message": "Please refund me."})


@pytest.mark.parametrize("quote", ["", "   ", None, 7005, "refund me twice"])
def test_an_empty_or_invented_quote_confirms_nothing(quote):
    assert not gate.client_confirmed({"user_quote": quote, "user_confirmed": True},
                                     {"main_reason": "refund_request", "user_message": "Please refund me."})


@pytest.mark.parametrize("message", ["Please do not cancel my booking 7011.",
                                     "Do not refund booking 7008, I don't want my money back."])
def test_a_negative_sentence_does_not_confirm(message):
    for reason in ("cancellation", "refund_request"):
        assert not gate.client_confirmed({"user_quote": message, "user_confirmed": True},
                                         {"main_reason": reason, "user_message": message})


@pytest.mark.parametrize("sentence", [
    "I do not want a refund", "I don't want a refund", "I dont want a refund", "NEVER refund me", "I no longer want a refund",
    "It doesn't need a refund", "I didn't ask for a refund", "I am not asking for a refund", "I don’t want a refund"])
def test_every_negative_word_stops_the_confirmation(sentence):
    assert not gate.client_confirmed({"user_quote": sentence}, {"main_reason": "refund_request", "user_message": sentence})


def test_a_fragment_cannot_hide_the_negative_word():
    case = {"main_reason": "refund_request", "user_message": "Do not refund booking 7008, I don't want my money back."}
    assert not gate.client_confirmed({"user_quote": "refund booking 7008"}, case)
    assert not gate.client_confirmed({"user_quote": "my money back"}, case)


@pytest.mark.parametrize("message", ["Notify me and refund me.", "I want a refund, it is a notable problem.",
                                     "Refund my nonrefundable extras.", "Please refund me, I knot my tie."])
def test_a_negative_word_inside_another_word_does_not_count(message):
    assert gate.client_confirmed({"user_quote": message}, {"main_reason": "refund_request", "user_message": message})


def test_only_the_quoted_sentence_counts():
    case = {"main_reason": "refund_request", "user_message": "I do not like this hotel. Please refund me!"}
    assert gate.client_confirmed({"user_quote": "Please refund me"}, case)
    assert not gate.client_confirmed({"user_quote": "I do not like this hotel"}, case)


def test_a_quote_with_its_full_stop_stops_at_that_sentence():
    case = {"main_reason": "refund_request", "user_message": "Refund booking 7008. I will not fly with you again."}
    assert gate.client_confirmed({"user_quote": "Refund booking 7008."}, case)


def test_a_quote_over_two_sentences_keeps_both():
    case = {"main_reason": "refund_request", "user_message": "Do not wait. Refund me now."}
    assert not gate.client_confirmed({"user_quote": "wait. Refund me"}, case)


@pytest.mark.parametrize("message_id, quote", [("a04", "My flight 7008 was cancelled, please refund me."),
                                               ("a08", "I want something back."), ("a09", None), ("a10", None)])
def test_the_practice_requests_still_confirm(message_id, quote):
    message = next(m["text"] for m in PRACTICE if m["id"] == message_id)
    assert gate.client_confirmed({"user_quote": quote or message}, {"main_reason": "refund_request", "user_message": message})


def test_a_negative_request_asks_the_client_and_pays_nothing(queue):
    message = "Please do not cancel my booking 7011."
    out = send(1, message, propose("propose_hotel_cancellation", "hotel", 7011, "AT-HOT-02"))
    assert out["outcome"] == "ask_user" and not rows_for("refunds", 7011)
    assert reads.get_hotel_booking(7011)["status"] == "confirmed"


def test_a_shopnova_negative_sentence_still_uses_the_agents_flag():
    args = {"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 59.90}, "rule_id": "R-REF-03",
            "facts_used": {"days_late": 6}, "user_confirmed": True, "user_quote": "I do not want to wait, refund me"}
    assert shopnova_review(args, new_case("T-1"))["outcome"] == "approve"


def test_a_case_without_a_message_confirms_nothing():
    assert not gate.client_confirmed({"user_quote": "refund me"}, {"main_reason": "refund_request"})


def test_shopnova_still_uses_the_agents_flag():
    args = {"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 59.90}, "rule_id": "R-REF-03",
            "facts_used": {"days_late": 6}, "user_quote": "words the client never wrote"}
    assert shopnova_review({**args, "user_confirmed": False}, new_case("T-1"))["outcome"] == "ask_user"
    assert shopnova_review({**args, "user_confirmed": True}, new_case("T-2"))["outcome"] == "approve"


def test_a_shopnova_case_gets_no_atlas_confirmation(queue):
    chat = scripted(tool_call("propose_refund", {"order_id": 4512, "amount": 59.90, "rule_id": "R-REF-03",
                                                 "facts_used": {"days_late": 6}, "user_confirmed": False,
                                                 "user_quote": "I want a refund"}))
    out = web_chat.send(1, "shopnova", "My order 4512 is late, I want a refund", chat_fn=chat)
    assert out["outcome"] == "ask_user"


@pytest.mark.parametrize("action, rule_id, hint", [
    ("compensation", "AT-HOT-04", "AT-HOT-04 justifies a refund: use propose_refund"),
    ("refund", "AT-FLT-02", "AT-FLT-02 justifies a compensation: use propose_compensation"),
    ("refund", "AT-HOT-03", "AT-HOT-03 justifies a hotel cancellation: use propose_hotel_cancellation"),
    ("compensation", "AT-HOT-02",
     "AT-HOT-02 justifies a refund or a hotel cancellation: use propose_refund or propose_hotel_cancellation")])
def test_a_rule_of_another_action_names_that_action_and_its_tool(action, rule_id, hint):
    decision = review(action, "hotel", 7003, rule_id)
    assert decision["outcome"] == "send_back" and decision["reason"] == hint


def test_a_rule_of_no_action_keeps_the_list_of_rules():
    assert review("refund", "flight", 7005, "AT-FLT-05")["reason"].startswith("rule AT-FLT-05 cannot justify a refund; use one of")


def test_the_hint_only_names_real_actions_and_tools():
    assert set(gate.ACTION_TOOLS) == set(gate.ACTION_WORDS) == set(companies.get("atlas")["allowed_rules"])
    assert set(gate.ACTION_TOOLS.values()) <= set(tool_names("B", "atlas"))


def test_three_send_backs_become_escalate():
    case = case_for("flight", 7007)
    outcomes = [gate.review(proposal("refund", "flight", 7007, "AT-FLT-01"), case)["outcome"] for _ in range(3)]
    assert outcomes == ["send_back", "send_back", "escalate"]


def test_a_proposal_is_decided_once():
    first = review("refund", "flight", 7005, "AT-FLT-01")
    again = gate.review({**proposal("refund", "flight", 7005, "AT-FLT-01"), "proposal_id": first["proposal_id"]},
                        case_for("flight", 7005))
    assert again["outcome"] == "refused" and len(rows_for("refunds", 7005)) == 1


def test_a_fully_refunded_booking_gets_nothing_more():
    assert review("refund", "flight", 7008, "AT-FLT-01")["outcome"] == "approve"
    assert review("refund", "flight", 7008, "AT-FLT-01")["outcome"] == "send_back"
    assert len(rows_for("refunds", 7008)) == 1


# ---------- finance limit: AT-ESC-01 ----------

def test_refund_of_exactly_1500_is_automatic(queue):
    assert review("refund", "flight", 7005, "AT-FLT-01")["outcome"] == "approve"


def test_refund_of_1500_01_waits_for_finance(queue):
    sql("UPDATE flight_bookings SET paid_tnd = 1500.01 WHERE id = 7005")
    decision = review("refund", "flight", 7005, "AT-FLT-01")
    assert decision["outcome"] == "layer3_pending" and not rows_for("refunds", 7005)


def test_every_compensation_waits_for_finance(queue):
    assert gate.needs_finance("compensation", 0.01)
    assert review("compensation", "flight", 7004, "AT-FLT-03")["outcome"] == "layer3_pending"
    assert not rows_for("compensations", 7004)


def test_a_cancellation_refund_counts_as_a_refund_for_the_limit():
    assert not gate.needs_finance("cancel_hotel", 1500.00)
    assert gate.needs_finance("cancel_hotel", 1500.01)


def test_the_amount_is_on_the_pending_proposal(queue):
    decision = review("compensation", "flight", 7004, "AT-FLT-03")
    stored = writes.get_proposal(decision["proposal_id"])
    assert stored["params"]["amount"] == 839.50 and stored["decision"] is None


def test_stub_approves_a_refund_up_to_its_maximum():
    decision = review("refund", "flight", 7006, "AT-FLT-04")            # 1,900 TND
    assert decision["outcome"] == "approve" and decision["facts"]["layer3_decision"] == "approved"
    assert "after a check by our finance team" in decision["must_say"][0]


def test_stub_refuses_a_refund_above_its_maximum():
    sql("UPDATE flight_bookings SET paid_tnd = 2500 WHERE id = 7006")
    decision = review("refund", "flight", 7006, "AT-FLT-04")
    assert decision["outcome"] == "layer3_refused" and not rows_for("refunds", 7006)
    assert writes.get_proposal(decision["proposal_id"])["decision"] == "layer3"


def test_stub_refuses_every_compensation():
    decision = review("compensation", "flight", 7004, "AT-FLT-03")
    assert decision["outcome"] == "layer3_refused" and not rows_for("compensations", 7004)


# ---------- hotel cancellation ----------

def hotel(status="confirmed"):
    return sql("SELECT status, cancelled_date FROM hotel_bookings WHERE id = 7011")[0]


def test_cancel_refundable_pays_back():
    decision = review("cancel_hotel", "hotel", 7011, "AT-HOT-02")
    assert decision["outcome"] == "approve"
    assert tuple(hotel()) == ("cancelled", "2026-10-09")
    assert decision["must_say"] == ["Your hotel booking 7011 is cancelled.",
                                    "Your refund of 220.00 TND for booking 7011 is approved."]


def test_cancel_non_refundable_pays_nothing():
    decision = review("cancel_hotel", "hotel", 7012, "AT-HOT-03")
    assert decision["outcome"] == "approve" and not rows_for("refunds", 7012)
    assert sql("SELECT status FROM hotel_bookings WHERE id = 7012")[0][0] == "cancelled"
    assert decision["next_step"] == "This booking is non-refundable, so nothing is paid back."


def test_cancel_no_deposit_pays_nothing():
    sql("UPDATE hotel_bookings SET deposit_type = 'no_deposit', paid_tnd = 0 WHERE id = 7011")
    decision = review("cancel_hotel", "hotel", 7011, "AT-HOT-01")
    assert decision["outcome"] == "approve" and not rows_for("refunds", 7011)
    assert decision["next_step"] == "There is nothing to pay."


@pytest.mark.parametrize("arrival, refund", [("2026-10-11", 220.00), ("2026-10-10", None)])
def test_refundable_needs_two_days(arrival, refund):
    sql("UPDATE hotel_bookings SET arrival_date = ? WHERE id = 7011", arrival)
    decision = review("cancel_hotel", "hotel", 7011, "AT-HOT-02")
    assert decision["outcome"] == "approve" and decision["facts"].get("amount_tnd") == refund
    assert hotel()["status"] == "cancelled"
    assert len(rows_for("refunds", 7011)) == (1 if refund else 0)


def test_only_a_confirmed_booking_can_be_cancelled():
    assert review("cancel_hotel", "hotel", 7003, "AT-HOT-02")["outcome"] == "send_back"


@pytest.mark.parametrize("arrival", ["2026-10-09", "2026-10-01"])
def test_too_late_to_cancel(arrival):
    sql("UPDATE hotel_bookings SET arrival_date = ? WHERE id = 7011", arrival)
    assert review("cancel_hotel", "hotel", 7011, "AT-HOT-02")["outcome"] == "send_back"
    assert hotel()["status"] == "confirmed"


def test_cancel_under_the_wrong_deposit_rule_is_sent_back():
    decision = review("cancel_hotel", "hotel", 7011, "AT-HOT-03")
    assert decision["outcome"] == "send_back" and "AT-HOT-02" in decision["reason"] and hotel()["status"] == "confirmed"


def test_a_flight_cannot_be_cancelled_by_this_action():
    assert review("cancel_hotel", "flight", 7010, "AT-HOT-02")["outcome"] == "send_back"


def test_a_big_cancellation_waits_for_finance_and_changes_nothing(queue):
    sql("UPDATE hotel_bookings SET total_tnd = 1600, paid_tnd = 1600 WHERE id = 7011")
    decision = review("cancel_hotel", "hotel", 7011, "AT-HOT-02")
    assert decision["outcome"] == "layer3_pending" and hotel()["status"] == "confirmed"


def test_cancel_and_refund_are_one_transaction(monkeypatch):
    def broken_insert(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")
    decision = review("cancel_hotel", "hotel", 7012, "AT-HOT-03")      # a first good one: the function works
    assert decision["outcome"] == "approve"
    monkeypatch.setattr(writes, "_insert_money", broken_insert)
    with pytest.raises(sqlite3.OperationalError):
        review("cancel_hotel", "hotel", 7011, "AT-HOT-02")
    assert tuple(hotel()) == ("confirmed", None) and not rows_for("refunds", 7011)   # no half cancellation


# ---------- Atlas writes: safety nets ----------

def approved(action, kind, booking, rule, amount):
    proposal_id = writes.record_proposal(proposal(action, kind, booking, rule))["id"]
    writes.set_proposal_amount(proposal_id, amount)
    writes.record_decision(proposal_id, "approve", "test")
    return proposal_id


def test_proposal_ids_have_their_own_prefix():
    assert writes.record_proposal(proposal("refund", "flight", 7005, "AT-FLT-01"))["id"] == "AP-0001"


def test_refund_needs_an_approved_proposal():
    proposal_id = writes.record_proposal(proposal("refund", "flight", 7005, "AT-FLT-01"))["id"]
    assert "not approved" in writes.create_refund("flight", 7005, 10, "AT-FLT-01", proposal_id)["error"]
    assert "required" in writes.create_refund("flight", 7005, 10, "AT-FLT-01", None)["error"]
    assert "not found" in writes.create_refund("flight", 7005, 10, "AT-FLT-01", "AP-9999")["error"]


def test_refund_must_be_the_approved_amount():
    proposal_id = approved("refund", "flight", 7005, "AT-FLT-01", 10.00)
    assert "does not match" in writes.create_refund("flight", 7005, 1500, "AT-FLT-01", proposal_id)["error"]


def test_refund_must_be_the_approved_booking():
    proposal_id = approved("refund", "flight", 7005, "AT-FLT-01", 10.00)
    assert "safety net" in writes.create_refund("flight", 7008, 10, "AT-FLT-01", proposal_id)["error"]


def test_refund_must_be_the_approved_action():
    proposal_id = approved("compensation", "flight", 7005, "AT-FLT-02", 10.00)
    assert "not 'refund'" in writes.create_refund("flight", 7005, 10, "AT-FLT-02", proposal_id)["error"]


def test_a_proposal_pays_once():
    proposal_id = approved("refund", "flight", 7005, "AT-FLT-01", 10.00)
    assert "id" in writes.create_refund("flight", 7005, 10, "AT-FLT-01", proposal_id)
    assert "already used" in writes.create_refund("flight", 7005, 10, "AT-FLT-01", proposal_id)["error"]


def test_refund_cannot_pass_the_limit():
    proposal_id = approved("refund", "flight", 7008, "AT-FLT-01", 690.01)
    assert "AT-REF-01" in writes.create_refund("flight", 7008, 690.01, "AT-FLT-01", proposal_id)["error"]


def test_compensation_is_paid_once_per_booking():
    first = approved("compensation", "flight", 7004, "AT-FLT-03", 839.50)
    second = approved("compensation", "flight", 7004, "AT-FLT-03", 839.50)
    row = writes.create_compensation("flight", 7004, 839.50, "AT-FLT-03", first)
    assert (row["status"], row["amount"]) == ("approved", 839.50)
    assert "already has a compensation" in writes.create_compensation("flight", 7004, 839.50, "AT-FLT-03", second)["error"]


def test_compensation_needs_a_compensation_proposal():
    proposal_id = approved("refund", "flight", 7004, "AT-FLT-03", 839.50)
    assert "not 'compensation'" in writes.create_compensation("flight", 7004, 839.50, "AT-FLT-03", proposal_id)["error"]


def test_cancel_needs_its_own_approved_proposal():
    proposal_id = approved("refund", "hotel", 7011, "AT-HOT-02", 220.00)
    assert "safety net" in writes.cancel_hotel_booking(7011, proposal_id)["error"]
    assert hotel()["status"] == "confirmed"


def test_set_amount_refused_after_the_decision():
    proposal_id = approved("refund", "flight", 7005, "AT-FLT-01", 10.00)
    assert "already decided" in writes.set_proposal_amount(proposal_id, 1500)["error"]


def test_refused_writes_are_traced_and_never_raise():
    assert "error" in writes.create_refund("flight", 7005, float("nan"), "AT-FLT-01", "AP-0001")
    assert "error" in writes.record_decision("AP-9999", "approve", "x")
    assert "error" in writes.record_decision("AP-0001", "nonsense", "x")


# ---------- approvals: finance's real queue ----------

COMPENSATION_MESSAGE = "Flight 7004 got me to Chicago more than three hours late. I want the compensation I am owed."


def pending_compensation():
    out = send(5, COMPENSATION_MESSAGE, propose("propose_compensation", "flight", 7004, "AT-FLT-03"))
    return out, store.approvals("pending")[0]


def test_compensation_goes_to_the_queue(queue):
    out, approval = pending_compensation()
    assert out["outcome"] == "layer3_pending" and out["status"] == "Waiting for finance"
    assert (approval["company"], approval["booking_type"], approval["action"], approval["amount"], approval["order_id"]) == (
        "atlas", "flight", "compensation", 839.50, 7004)
    assert not rows_for("compensations", 7004)


def test_approve_writes_the_compensation_and_tells_the_client(queue):
    out, approval = pending_compensation()
    decided = approvals.decide(approval["id"], "atlas_admin", True)
    assert decided["outcome"] == "approve" and decided["approval"]["status"] == "approved"
    assert decided["compensation"]["amount"] == 839.50 and decided["compensation"]["status"] == "approved"
    assert "Your compensation of 839.50 TND for booking 7004 is approved after a check by our finance team." in decided["reply"]
    ticket = store.get_ticket(out["ticket_id"])
    assert (ticket["status"], ticket["user_unread"]) == ("Solved", 1)
    assert store.messages(out["ticket_id"])[-1]["text"] == decided["reply"]


def test_refuse_pays_nothing_and_hides_the_reason(queue):
    out, approval = pending_compensation()
    decided = approvals.decide(approval["id"], "atlas_admin", False, "secret internal reason")
    assert decided["outcome"] == "layer3_refused" and not rows_for("compensations", 7004)
    assert "secret" not in decided["reply"] and "We cannot approve a compensation of 839.50 TND" in decided["reply"]
    assert writes.get_proposal(approval["proposal_id"])["decision"] == "layer3"


def test_refuse_needs_a_reason(queue):
    _, approval = pending_compensation()
    assert "reason" in approvals.decide(approval["id"], "atlas_admin", False)["error"]
    assert store.get_approval(approval["id"])["status"] == "pending"


def test_a_decision_is_made_once(queue):
    _, approval = pending_compensation()
    assert "error" not in approvals.decide(approval["id"], "atlas_admin", True)
    assert "already approved" in approvals.decide(approval["id"], "atlas_admin", True)["error"]
    assert len(rows_for("compensations", 7004)) == 1


def test_recheck_on_fresh_data_stops_a_stale_approval(queue):
    _, approval = pending_compensation()
    sql("UPDATE flights SET main_delay_cause = 'weather' WHERE id = 7004")   # the data changed while it waited
    decided = approvals.decide(approval["id"], "atlas_admin", True)
    assert decided["recheck_failed"] and "does not apply any more" in decided["error"]
    assert store.get_approval(approval["id"])["status"] == "pending" and not rows_for("compensations", 7004)


def test_recheck_stops_a_changed_amount(queue):
    _, approval = pending_compensation()
    sql("UPDATE flights SET distance_km = 2000 WHERE id = 7004")
    assert "the amount changed" in approvals.decide(approval["id"], "atlas_admin", True)["error"]


def test_a_write_failure_leaves_everything_pending(queue, monkeypatch):
    _, approval = pending_compensation()

    def broken_insert(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(writes, "_insert_money", broken_insert)
    assert "nothing was written" in approvals.decide(approval["id"], "atlas_admin", True)["error"]
    assert store.get_approval(approval["id"])["status"] == "pending"
    assert writes.get_proposal(approval["proposal_id"])["decision"] is None


def test_approved_big_cancellation_is_one_transaction(queue):
    sql("UPDATE hotel_bookings SET total_tnd = 1600, paid_tnd = 1600 WHERE id = 7011")
    out = send(1, "Please cancel my hotel booking 7011", propose("propose_hotel_cancellation", "hotel", 7011, "AT-HOT-02"))
    assert out["outcome"] == "layer3_pending" and hotel()["status"] == "confirmed"
    decided = approvals.decide(store.approvals("pending")[0]["id"], "atlas_admin", True)
    assert hotel()["status"] == "cancelled" and decided["refund"]["amount"] == 1600.00
    assert "Your hotel booking 7011 is cancelled." in decided["reply"]


def test_the_shopnova_admin_never_sees_an_atlas_case(queue):
    pending_compensation()
    assert store.approvals("pending", company="shopnova") == []
    assert len(store.approvals("pending", company="atlas")) == 1


def test_old_approvals_are_shopnova_refunds(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE approvals (id INTEGER PRIMARY KEY, ticket_id TEXT NOT NULL, order_id INTEGER NOT NULL,
        amount REAL NOT NULL, proposal_id TEXT, status TEXT NOT NULL, decided_by TEXT, decided_at TEXT, reason TEXT);
        INSERT INTO approvals (ticket_id, order_id, amount, status) VALUES ('T-0001', 4515, 378, 'pending');""")
    con.commit()
    con.close()
    store.use_db(path)
    row = store.get_approval(1)
    assert (row["company"], row["booking_type"], row["action"]) == ("shopnova", None, "refund")
    assert store.pending_approval_for_order(4515)["id"] == 1
    assert store.pending_approval_for_order(4515, "atlas") is None


def test_the_pending_guard_is_per_company_and_booking(queue):
    _, approval = pending_compensation()
    again = send(5, "Any news about booking 7004?", no_llm)
    assert again["outcome"] == "approval_pending" and "already with our finance team" in again["reply"]
    assert store.pending_approval_for_order(7004, "shopnova") is None


# ---------- replies ----------

def test_atlas_reply_writer_gets_the_company():
    decision = gate.info_decision(7010)
    system = writer.build_messages({**decision, "style": {}})[0]["content"]
    assert "Atlas Travel customer service" in system and companies.get("atlas")["description"] in system
    assert "ShopNova" not in system and "AT-FLT-01" in system


def test_atlas_reply_writer_says_booking():
    user = writer.build_messages({**gate.info_decision(7010), "style": {}})[1]["content"]
    assert '"booking 7010"' in user and '"booking_number": 7010' in user and "order" not in user


@pytest.mark.parametrize("outcome, action, words", [
    ("approve", "refund", "Your refund of 100.00 TND for booking 7005 is approved."),
    ("approve", "compensation", "Your compensation of 100.00 TND for booking 7005 is approved."),
    ("layer3_pending", "compensation", "Your compensation of 100.00 TND for booking 7005 needs approval from our finance team."),
    ("layer3_pending", "refund", "Your refund of 100.00 TND for booking 7005 needs approval from our finance team."),
    ("layer3_refused", "refund", "We cannot approve a refund of 100.00 TND for booking 7005."),
])
def test_atlas_sentences(outcome, action, words):
    assert gate.user_words(outcome, action, None, {"amount_tnd": 100.0}, 7005)[0] == [words]


def template_reply(decision):
    return writer.write_reply({**decision, "style": {}})   # the SLM is offline in tests: the template is used


@pytest.mark.parametrize("make", [
    lambda: gate.info_decision(7010), lambda: gate.info_decision(7003), lambda: gate.info_decision(None),
    lambda: gate.info_decision(99999), gate.off_topic_decision, lambda: gate.escalate_decision(7010, "route"),
    lambda: review("refund", "flight", 7008, "AT-FLT-01"), lambda: review("cancel_hotel", "hotel", 7011, "AT-HOT-02"),
    lambda: review("cancel_hotel", "hotel", 7012, "AT-HOT-03"), lambda: gate.for_user(review("refund", "flight", 7007, "AT-FLT-01")),
])
def test_every_atlas_reply_passes_the_rule_check(make):
    written = template_reply(make())
    assert written["check"]["passed"], written
    assert "order" not in written["reply"].lower()


def test_a_cancellation_with_its_refund_may_say_the_refund_is_approved():
    decision = {**review("cancel_hotel", "hotel", 7011, "AT-HOT-02"), "style": {}}
    assert check.check_reply(" ".join(decision["must_say"]), decision)["passed"]


def test_a_pending_refund_may_not_be_called_approved():
    decision = {"outcome": "layer3_pending", "action": "refund", "order_id": 7006, "facts": {}, "must_say": [], "next_step": ""}
    assert not check.check_reply("Your refund for booking 7006 is approved.", decision)["passed"]


def test_an_atlas_rule_id_never_reaches_the_client():
    decision = {"outcome": "info", "order_id": 7005, "facts": {}, "must_say": [], "next_step": ""}
    assert not check.check_reply("Booking 7005 falls under AT-FLT-01.", decision)["passed"]


def test_off_topic_is_per_company():
    ticket = {"ticket_id": "T-1", "company": "atlas", "main_reason": "other", "order_id": None}
    said, reply, _ = pipeline.final_reply(ticket, None)
    assert said["must_say"] == ["I can help with your Atlas Travel bookings: flights, hotel stays, refunds and compensation."]
    assert "Atlas Travel" in reply


def test_a_decision_with_an_error_in_the_agents_says_the_colleague_sentence():
    def broken(role_key, messages, tools=None):
        raise RuntimeError("provider down")
    ticket = intake.process("Booking 7005: my flight was cancelled and I want my money back.", use_llm=False, company="atlas")
    out = pipeline.handle_ticket(ticket, chat_fn=broken)
    assert out["decision"]["outcome"] == "escalate"
    assert "passed on to a colleague" in out["final_reply"]


def test_meals_are_information_only():
    decision = gate.info_decision(7004, "delay_disruption")
    assert decision["rule_id"] == "AT-FLT-05" and "meal" in decision["next_step"]
    assert decision["proposal_id"] is None and not rows_for("compensations", 7004) and not rows_for("refunds", 7004)
    assert template_reply(decision)["check"]["passed"]


def test_no_meal_sentence_on_a_status_question():
    assert gate.info_decision(7004, "booking_status")["next_step"] == ""


def test_no_compensation_case_gets_the_status_only():
    decision = gate.info_decision(7007, "compensation_request")
    assert decision["must_say"] == ["Your flight booking 7007 was delayed."] and decision["next_step"] == ""


# ---------- the channel, one path per practice message ----------

def run_flow(message_id, chat):
    m = next(x for x in PRACTICE if x["id"] == message_id)
    return send(m["user_id"], m["text"], chat), m["expect"]


@pytest.mark.parametrize("message_id, chat, check_after", [
    ("a03", propose("propose_refund", "flight", 7005, "AT-FLT-01"), 7005),
    ("a04", propose("propose_refund", "flight", 7008, "AT-FLT-01"), 7008),
    ("a08", propose("propose_refund", "hotel", 7003, "AT-HOT-04"), 7003),
])
def test_channel_refund_paths(queue, message_id, chat, check_after):
    out, expect = run_flow(message_id, chat)
    assert out["outcome"] == expect["outcome"] == "approve" and out["status"] == "Solved"
    rows = rows_for("refunds", check_after)
    assert len(rows) == expect["refund_rows"] and rows[0]["amount"] == expect["refund_amount"]


def test_channel_a01_status(queue):
    out, expect = run_flow("a01", read_then_answer("get_flight_booking", 7010))
    assert out["outcome"] == expect["outcome"] and "7010" in out["reply"]
    assert store.get_ticket(out["ticket_id"])["lead_agent"] == "A"


def test_channel_a02_compensation(queue):
    out, expect = run_flow("a02", propose("propose_compensation", "flight", 7004, "AT-FLT-03"))
    assert out["outcome"] == expect["outcome"]
    assert len(store.approvals("pending")) == expect["approvals_pending"]
    assert store.approvals("pending")[0]["amount"] == expect["approval_amount"]


@pytest.mark.parametrize("message_id, tool", [("a05", "get_flight_booking"), ("a06", "get_flight_booking"),
                                              ("a07", "get_flight_booking")])
def test_channel_no_compensation_paths(queue, message_id, tool):
    booking = {"a05": 7008, "a06": 7007, "a07": 7006}[message_id]
    out, expect = run_flow(message_id, read_then_answer(tool, booking))
    assert out["outcome"] == "info" and not rows_for("compensations", booking)
    assert not store.approvals("pending")
    assert not any(n in out["reply"] for n in ("839", "1,343", "2,014", "1343", "2014"))


def test_channel_a09_cancel_pays_back(queue):
    out, expect = run_flow("a09", propose("propose_hotel_cancellation", "hotel", 7011, "AT-HOT-02"))
    assert out["outcome"] == expect["outcome"] and hotel()["status"] == expect["booking_status_after"]
    assert rows_for("refunds", 7011)[0]["amount"] == expect["refund_amount"]


def test_channel_a10_cancel_pays_nothing(queue):
    out, expect = run_flow("a10", propose("propose_hotel_cancellation", "hotel", 7012, "AT-HOT-03"))
    assert sql("SELECT status FROM hotel_bookings WHERE id = 7012")[0][0] == expect["booking_status_after"]
    assert len(rows_for("refunds", 7012)) == expect["refund_rows"] and "non-refundable" in out["reply"]


def test_channel_a11_goes_to_a_colleague(queue):
    out, expect = run_flow("a11", no_llm)
    assert out["outcome"] == expect["outcome"] and out["status"] == "Escalated"
    assert store.get_ticket(out["ticket_id"])["lead_agent"] is None


def test_channel_a12_another_clients_booking(queue):
    out, expect = run_flow("a12", no_llm)
    assert out["outcome"] == expect["outcome"] and "not on your account" in out["reply"]
    assert "flown" not in out["reply"] and "delayed" not in out["reply"]


def test_every_practice_message_has_a_path_in_this_file():
    assert [m["id"] for m in PRACTICE] == [f"a{i:02d}" for i in range(1, 13)]


def test_a_booking_that_does_not_exist_is_not_on_the_account(queue):
    assert send(1, "What about booking 99999?", no_llm)["outcome"] == "not_your_order"


def test_a_shopnova_order_number_means_nothing_at_atlas(queue):
    # Intake runs before the identity check and finds no Atlas reason here, so its fallback is called (as at ShopNova).
    # That is the only LLM call allowed: no agent runs on a number that is not on this account.
    def only_the_fallback(role_key, messages, tools=None):
        assert tools is None and messages[0]["content"] == llm_fallback.ATLAS_PROMPT
        return text('{"reasons": ["booking_status"], "order_id": null}')
    assert send(1, "Where is order 4512?", only_the_fallback)["outcome"] == "not_your_order"


def test_a_handover_from_a_to_b_stays_at_atlas(queue):
    # A reads first: with no tool at all, the T10 safety net would run A once more (as at ShopNova).
    steps = iter([tool_call("get_flight_booking", {"booking_id": 7008}), text("Passed on for checking. [HANDOVER: B]"),
                  tool_call("propose_refund", proposal_args("flight", 7008, "AT-FLT-01"))])

    def fake(role_key, messages, tools=None):
        if "Agent B" in messages[0]["content"] or "Agent A" in messages[0]["content"]:
            assert "Atlas Travel" in messages[0]["content"]
        return quoting_the_client(next(steps, None) or text("It is sent for checking."), messages)
    ticket = {**intake.process("Is booking 7008 ok?", use_llm=False, company="atlas"), "main_reason": "booking_status"}
    out = pipeline.handle_ticket(ticket, chat_fn=fake)
    # B did the work at Atlas. Its reason is not a request, so the client is asked first: nothing is paid yet.
    assert out["handover"] == "B" and out["decision"]["outcome"] == "ask_user" and not rows_for("refunds", 7008)
    assert out["handover_text"] == "Your request is passed on for a refund check."


def test_a_sent_back_agent_corrects_its_proposal(queue):
    chat = scripted(tool_call("propose_refund", proposal_args("flight", 7008, "AT-FLT-02")),   # the wrong rule
                    text("Sorry."), tool_call("propose_refund", proposal_args("flight", 7008, "AT-FLT-01")))
    out = send(4, "My flight 7008 was cancelled, please refund me.", chat)
    assert out["outcome"] == "approve" and rows_for("refunds", 7008)[0]["amount"] == 690.00


def test_a_refund_rule_cited_for_a_compensation_ends_as_a_refund(queue):
    chat = scripted(tool_call("propose_compensation", proposal_args("hotel", 7003, "AT-HOT-04", confirmed=False)),
                    text("Sorry."), tool_call("propose_refund", proposal_args("hotel", 7003, "AT-HOT-04", confirmed=False)))
    seen = []

    def spy(role_key, messages, tools=None):
        seen.append(messages[1]["content"])
        return chat(role_key, messages, tools)
    message = next(m["text"] for m in PRACTICE if m["id"] == "a08")
    assert send(3, message, spy)["outcome"] == "approve"
    assert rows_for("refunds", 7003)[0]["amount"] == 72.00 and not rows_for("compensations", 7003)
    assert any("AT-HOT-04 justifies a refund: use propose_refund" in m for m in seen)


def test_the_client_was_not_asked_again_on_a_clear_request(queue):
    chat = propose("propose_refund", "flight", 7008, "AT-FLT-01", confirmed=False)
    out = send(4, "My flight 7008 was cancelled, please refund me.", chat)
    assert out["outcome"] == "approve" and rows_for("refunds", 7008)[0]["amount"] == 690.00


def test_the_intake_note_is_not_the_clients_words(queue):
    args = {**proposal_args("flight", 7008, "AT-FLT-01"), "user_quote": "main reason = refund_request"}
    out = send(4, "My flight 7008 was cancelled, please refund me.", scripted(tool_call("propose_refund", args)))
    assert out["outcome"] == "ask_user" and not rows_for("refunds", 7008)


def test_a_proposal_on_another_clients_booking_never_pays(queue):
    chat = scripted(*[tool_call("propose_refund", proposal_args("flight", 7005, "AT-FLT-01")) for _ in range(3)])
    out = send(4, "My flight 7008 was cancelled, please refund me.", chat)   # 7005 is Hedi's, the agent went wrong
    assert out["outcome"] == "escalate" and out["status"] == "Escalated" and not rows_for("refunds", 7005)


def test_quota_empty_gives_the_busy_reply(queue, monkeypatch):
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: False)
    assert send(5, "Hi, is my flight booking 7010 still on schedule?", no_llm)["outcome"] == "busy"


def test_live_text_for_bookings():
    assert web_chat.live_text({"step": "tool_call", "data": {"tool": "get_flight_booking"}}) == "Checking your booking…"
    assert web_chat.live_text({"step": "tool_call", "data": {"tool": "get_order"}}) == "Checking your order…"


# ---------- the Console reads both companies ----------

def test_console_shows_both_companies():
    assert console.companies() == ["atlas", "shopnova"]


def test_console_shows_an_atlas_ticket_with_the_clients_name(queue):
    out = send(5, "Hi, is my flight booking 7010 still on schedule?", read_then_answer("get_flight_booking", 7010))
    rows = console.live_tickets(company="atlas")
    assert [r["id"] for r in rows] == [out["ticket_id"]] and rows[0]["user"] == "Nizar Haddad (5)"
    assert console.live_tickets(company="shopnova") == []


def test_console_timeline_of_an_atlas_ticket(queue):
    out, approval = pending_compensation()
    approvals.decide(approval["id"], "atlas_admin", True)
    detail = console.ticket_detail(out["ticket_id"])
    titles = [console.describe_step(s)[1] for turn in detail["turns"] for s in turn["steps"]]
    assert any("Proposal: compensation" in t for t in titles)
    assert any("Layer 3: the Atlas admin decided" in t for t in titles)
    proposal_detail = next(console.describe_step(s)[2] for turn in detail["turns"] for s in turn["steps"]
                           if console.kind_of(s) == "proposal")
    assert "flight booking 7004" in proposal_detail and "None" not in proposal_detail.split("·")[0]


def shopnova_refund_ticket() -> dict:
    """A ShopNova ticket with a refund of 59.90 paid, saved the way the channel saves it. Returns the decision."""
    ticket = store.create_ticket("shopnova", 1)
    message_id = store.add_message(ticket["id"], "user", "My order 4512 is late, I want a refund.")
    decision = shopnova_review({"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 59.90},
                                "rule_id": "R-REF-03", "facts_used": {"days_late": 6}, "user_confirmed": True,
                                "user_quote": "I want a refund"}, new_case(ticket["id"]))
    store.add_step(ticket["id"], message_id, "coordinator", "coordinator", {"trace_step": "coordinator_decision", **decision})
    return decision


def test_console_money_totals_include_atlas_per_company(queue):
    shopnova_refund_ticket()
    send(1, "Booking 7005: my flight was cancelled and I want my money back.",
         propose("propose_refund", "flight", 7005, "AT-FLT-01"))
    _, approval = pending_compensation()
    approvals.decide(approval["id"], "atlas_admin", True)
    d = console.dashboard()
    assert d["money_per_company"] == [
        {"company": "atlas", "refunds_paid": 1, "refunds_tnd": 1500.00, "compensations_paid": 1,
         "compensations_tnd": 839.50, "finance_tnd": 839.50},
        {"company": "shopnova", "refunds_paid": 1, "refunds_tnd": 59.90, "compensations_paid": 0,
         "compensations_tnd": 0, "finance_tnd": 0}]
    assert (d["refunds_paid"], d["refunds_tnd"]) == (2, 1559.90)
    assert (d["compensations_paid"], d["compensations_tnd"], d["finance_tnd"]) == (1, 839.50, 839.50)


def test_console_counts_a_hotel_cancellation_refund(queue):
    send(1, "Please cancel my hotel booking 7011, I can't travel anymore.",
         propose("propose_hotel_cancellation", "hotel", 7011, "AT-HOT-02"))
    assert console.dashboard()["money_per_company"][0]["refunds_tnd"] == 220.00


def test_console_does_not_count_a_pending_compensation(queue):
    pending_compensation()
    d = console.dashboard()
    assert (d["compensations_paid"], d["compensations_tnd"], d["finance_pending"]) == (0, 0, 1)


def test_console_never_counts_one_companys_money_for_the_other():
    decision = shopnova_refund_ticket()
    sql("INSERT INTO refunds (booking_type, booking_id, amount, status, proposal_id) VALUES ('flight', 4512, 999, "
        "'approved', ?)", decision["proposal_id"])   # the same proposal id and number, in the other company's data
    assert [c["company"] for c in console.dashboard()["money_per_company"]] == ["shopnova"]
    assert console.dashboard()["refunds_tnd"] == 59.90


def test_console_opens_atlas_read_only():
    with closing(console.connect_ro(atlas_db.db_path())) as con, pytest.raises(sqlite3.OperationalError, match="readonly"):
        con.execute("DELETE FROM refunds")


def test_console_money_works_without_the_atlas_file(tmp_path, queue):
    send(1, "Booking 7005: my flight was cancelled and I want my money back.",
         propose("propose_refund", "flight", 7005, "AT-FLT-01"))
    missing = tmp_path / "no_atlas.db"
    atlas_db.use_db(missing)
    assert console.dashboard()["refunds_tnd"] == 0 and not missing.exists()


def test_console_filter_keeps_shopnova_tickets_apart(queue):
    store.create_ticket("shopnova", 1)
    send(5, "Hi, is my flight booking 7010 still on schedule?", read_then_answer("get_flight_booking", 7010))
    assert {r["company"] for r in console.live_tickets()} == {"shopnova", "atlas"}
    assert len(console.live_tickets(company="shopnova")) == 1


def test_finance_rule_is_read_from_the_policy_file():
    assert companies.get("atlas")["finance_rule"] == "AT-ESC-01"
    assert check_condition(get_policy("AT-ESC-01", "atlas")["condition"], {"action": "compensation", "amount": 1})
    assert "1,500 TND" in get_policy("AT-ESC-01", "atlas")["text"] and "every compensation" in get_policy("AT-ESC-01", "atlas")["text"]
