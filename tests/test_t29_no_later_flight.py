"""T29 step 2 (F6): Atlas Agent C must not invent a flight.

When find_alternative_flights finds no later flight on the route (booking 7005 on the real data), C may not propose a
rebooking: propose_rebooking is refused by code, and the pipeline hands the case to a human colleague with one fixed
sentence ("There is no later flight on this route ..."). Nothing is written. A booking that HAS a later flight still
gets C's offer (positive control). Fake LLM, own copy of atlas.db.
"""

import json
import shutil
from contextlib import closing
from types import SimpleNamespace

import pytest

from callverse import pipeline
from callverse.coordinator import atlas_special
from callverse.data.atlas import db as atlas_db
from callverse.data.atlas.seed import seed
from callverse.tools import atlas_c_tools


@pytest.fixture(scope="module")
def atlas_template(tmp_path_factory):
    return seed(tmp_path_factory.mktemp("atlas_t29") / "atlas.db")


@pytest.fixture(autouse=True)
def fresh_atlas(tmp_path, atlas_template):
    shutil.copyfile(atlas_template, tmp_path / "atlas.db")
    atlas_db.use_db(tmp_path / "atlas.db")
    yield
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)


def add_later_flight(flight_id=9901):
    """A scheduled ATL -> LAX flight after cancelled booking 7005's flight (as in test_agent_c_atlas.py)."""
    with closing(atlas_db.connect()) as con:
        row = dict(con.execute("SELECT * FROM flights WHERE id = 7005").fetchone())
        row.update(id=flight_id, flight_number=999, scheduled_departure="2026-10-12 09:00", departure_delay_min=None,
                   arrival_delay_min=None, cancelled=0, cancellation_reason=None, main_delay_cause=None,
                   status="scheduled")
        con.execute(f"INSERT INTO flights ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        con.commit()


def scalar(sql, *args):
    with closing(atlas_db.connect()) as con:
        return con.execute(sql, args).fetchone()[0]


def rebooking_rows() -> int:
    """Rows in the rebookings table (made by the first rebooking write: no table = 0 rows)."""
    with closing(atlas_db.connect()) as con:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rebookings'").fetchone() is None:
            return 0
        return con.execute("SELECT COUNT(*) FROM rebookings").fetchone()[0]


def call(name, args):
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    return SimpleNamespace(content=None, tool_calls=[tc])


def c_llm(new_flight_id):
    """Fake Agent C: reads 7005, looks for flights, then proposes a rebooking anyway (an invented flight if none)."""
    steps = iter([call("get_flight_booking", {"booking_id": 7005}),
                  call("find_alternative_flights", {"booking_id": 7005}),
                  call("propose_rebooking", {"booking_id": 7005, "new_flight_id": new_flight_id,
                                             "user_confirmed": False, "user_quote": "I need another flight"})])

    def fake(role_key, messages, tools=None, **kw):
        return next(steps, None) or SimpleNamespace(content="A new flight is being checked.", tool_calls=None)
    return fake


def no_slm(role_key, messages, tools=None, **kw):
    raise RuntimeError("SLM off in this test: the template is used")


TICKET = {"ticket_id": "T-29", "company": "atlas", "text": "My flight 7005 was cancelled, I need another flight.",
          "order_id": 7005, "booking_type": "flight", "main_reason": "rebooking", "priority_label": "high"}


def test_propose_rebooking_is_refused_by_code_when_no_later_flight():
    assert atlas_c_tools.find_alternative_flights(7005)["flights"] == []          # the real schedule has none
    out = atlas_c_tools.propose_rebooking(7005, 7004, False, "I need another flight")
    assert "error" in out and "no later flight on this route" in out["error"]


def test_booking_7005_goes_to_a_colleague_with_no_rebooking():
    out = pipeline.handle_ticket(dict(TICKET), chat_fn=c_llm(7004), slm_chat_fn=no_slm)
    decision = out["decision"]
    assert out["proposal"] is None and out["proposals"] == []                  # no propose_rebooking accepted
    assert decision["outcome"] == "escalate" and decision["reason"] == "no later flight on this route"
    assert decision["must_say"] == [atlas_special.no_later_flight_sentence(7005)]
    assert atlas_special.no_later_flight_sentence(7005) in out["final_reply"]
    assert rebooking_rows() == 0                       # nothing written
    assert scalar("SELECT flight_id FROM flight_bookings WHERE id = 7005") == 7005


def test_positive_control_a_later_flight_still_gets_the_offer():
    add_later_flight()
    out = pipeline.handle_ticket(dict(TICKET), chat_fn=c_llm(9901), slm_chat_fn=no_slm)
    assert out["proposal"]["action"] == "rebook" and out["proposal"]["params"]["new_flight_id"] == 9901
    assert out["decision"]["outcome"] == "ask_user"                             # waits for the user's yes
    assert rebooking_rows() == 0
