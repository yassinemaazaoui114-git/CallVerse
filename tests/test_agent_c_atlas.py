"""P20 tests: Agent C at Atlas Travel (offline, fake LLM). New flight after a cancellation (AT-FLT-01) and special
assistance with the client's explicit yes (AT-AST-01). The Atlas data has no later flight on the cancelled routes,
so the tests add one scheduled flight to their own copy of atlas.db."""

import json
import shutil
from contextlib import closing
from types import SimpleNamespace

import pytest

from callverse import pipeline
from callverse.agents.agent_c import AgentC
from callverse.coordinator import atlas_coordinator as gate
from callverse.coordinator.coordinator import new_case
from callverse.data.atlas import db as atlas_db
from callverse.data.atlas.seed import seed
from callverse.queues.router import route
from callverse.tools import registry
from callverse.tools.atlas_c_tools import find_alternative_flights


@pytest.fixture(scope="module")
def atlas_template(tmp_path_factory):
    return seed(tmp_path_factory.mktemp("atlas_c") / "atlas.db")


@pytest.fixture(autouse=True)
def fresh_atlas(tmp_path, atlas_template):
    shutil.copyfile(atlas_template, tmp_path / "atlas.db")
    atlas_db.use_db(tmp_path / "atlas.db")
    yield
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)


def add_later_flight(flight_id=9901):
    """A scheduled ATL -> LAX flight after cancelled booking 7005's flight (2026-10-08 14:40)."""
    with closing(atlas_db.connect()) as con:
        row = dict(con.execute("SELECT * FROM flights WHERE id = 7005").fetchone())
        row.update(id=flight_id, flight_number=999, scheduled_departure="2026-10-12 09:00", departure_delay_min=None,
                   arrival_delay_min=None, cancelled=0, cancellation_reason=None, main_delay_cause=None,
                   status="scheduled")
        con.execute(f"INSERT INTO flights ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        con.commit()


def case(booking_id, yes):
    return {**new_case("T-1"), "order_id": booking_id, "booking_type": "flight", "main_reason": "rebooking",
            "client_said_yes": yes}


def rebook(new_flight_id=9901, confirmed=True):
    return {"agent": "C", "action": "rebook", "rule_id": "AT-FLT-01", "facts_used": {}, "user_confirmed": confirmed,
            "user_quote": "yes, put me on the next flight",
            "params": {"booking_type": "flight", "booking_id": 7005, "new_flight_id": new_flight_id}}


def wheelchair(booking_id=7010, confirmed=True):
    return {"agent": "C", "action": "assistance", "rule_id": "AT-AST-01", "facts_used": {}, "user_confirmed": confirmed,
            "user_quote": "yes, I need a wheelchair", "params": {"booking_type": "flight", "booking_id": booking_id,
                                                                  "kind": "wheelchair"}}


def scalar(sql, *args):
    with closing(atlas_db.connect()) as con:
        return con.execute(sql, args).fetchone()[0]


def test_atlas_routes_rebooking_and_assistance_to_c():
    for reason in ("rebooking", "special_assistance"):
        assert route({"ticket_id": "T", "main_reason": reason, "company": "atlas", "order_id": 7005,
                      "priority_label": "high"})["agent"] == "C"
    names = [t["function"]["name"] for t in registry.schemas_for("C", "atlas")]
    assert "propose_rebooking" in names and "propose_refund" not in names


def test_alternatives_are_later_flights_on_the_same_route():
    assert find_alternative_flights(7005)["flights"] == []          # the real schedule has none
    add_later_flight()
    assert [f["id"] for f in find_alternative_flights(7005)["flights"]] == [9901]


def test_rebook_waits_for_the_yes_then_moves_the_booking():
    add_later_flight()
    asked = gate.review(rebook(), case(7005, yes=False))
    assert asked["outcome"] == "ask_user" and "flight" in asked["must_say"][0]
    assert scalar("SELECT flight_id FROM flight_bookings WHERE id = 7005") == 7005
    done = gate.review(rebook(), case(7005, yes=True))
    assert done["outcome"] == "approve"
    assert scalar("SELECT flight_id FROM flight_bookings WHERE id = 7005") == 9901
    assert scalar("SELECT status FROM flight_bookings WHERE id = 7005") == "confirmed"
    assert scalar("SELECT old_flight_id FROM rebookings") == 7005


def test_rebook_refused_when_the_rule_or_the_flight_does_not_fit():
    add_later_flight()
    wrong_flight = gate.review(rebook(new_flight_id=7004), case(7005, yes=True))
    assert wrong_flight["outcome"] == "send_back" and "not a later flight" in wrong_flight["reason"]
    not_cancelled = gate.review({**rebook(), "params": {**rebook()["params"], "booking_id": 7004}},
                                case(7004, yes=True))
    assert not_cancelled["outcome"] == "send_back"
    other_booking = gate.review(rebook(), case(7008, yes=True))
    assert other_booking["outcome"] == "send_back" and "this case is about" in other_booking["reason"]


def test_wheelchair_needs_the_yes_and_48_hours():
    asked = gate.review(wheelchair(), case(7010, yes=False))
    assert asked["outcome"] == "ask_user" and "wheelchair" in asked["must_say"][0]
    again = gate.review(wheelchair(), case(7010, yes=True))     # booking 7010 already has a wheelchair (seed)
    assert again["outcome"] == "escalate" and "already requested" in again["reason"]
    past = gate.review(wheelchair(booking_id=7004), case(7004, yes=True))   # flight already flown: AT-AST-01 false
    assert past["outcome"] == "send_back"


def tool_call_reply(name, args):
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    return SimpleNamespace(content=None, tool_calls=[tc])


def test_agent_c_at_atlas_end_to_end():
    add_later_flight()
    steps = iter([tool_call_reply("get_flight_booking", {"booking_id": 7005}),
                  tool_call_reply("find_alternative_flights", {"booking_id": 7005}),
                  tool_call_reply("propose_rebooking", {"booking_id": 7005, "new_flight_id": 9901,
                                                        "user_confirmed": False, "user_quote": "my flight was cancelled"})])

    def fake(role_key, messages, tools=None, **kw):
        assert messages[0]["content"].startswith("You are Agent C - Urgent & Special Help of Atlas")
        return next(steps, None) or SimpleNamespace(content="A new flight is being checked.", tool_calls=None)
    ticket = {"ticket_id": "T-1", "company": "atlas", "text": "My flight 7005 was cancelled, I need another flight.",
              "order_id": 7005, "booking_type": "flight", "main_reason": "rebooking", "priority_label": "high"}
    out = pipeline.handle_ticket(ticket, chat_fn=fake)
    assert out["handover"] == "C" and out["decision"]["outcome"] == "ask_user"
    assert out["proposal"]["action"] == "rebook"
