"""P20 tests: Agent D at Atlas (hotel capacity derived from the bookings, overbooking warning, deals the owner
decides) and low-confidence tickets routed to Agent C. Offline."""

import shutil
from contextlib import closing

import pytest

from callverse import pipeline
from callverse.agents.agent_d import AgentD, atlas_overbooking_note
from callverse.data.atlas import db as atlas_db
from callverse.data.atlas import reads, writes
from callverse.data.atlas.seed import seed
from callverse.queues.router import confidence_margin, route
from callverse.tools.capacity_tools import hotel_capacity_report, hotel_facts


@pytest.fixture(scope="module")
def atlas_template(tmp_path_factory):
    return seed(tmp_path_factory.mktemp("atlas_d") / "atlas.db")


@pytest.fixture(autouse=True)
def fresh_atlas(tmp_path, atlas_template):
    shutil.copyfile(atlas_template, tmp_path / "atlas.db")
    atlas_db.use_db(tmp_path / "atlas.db")
    yield
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)


def overbook(hotel_id=1, night="2026-10-15", extra=30):
    """Add `extra` confirmed one-night bookings on `night` (a copy of one real booking of that hotel)."""
    with closing(atlas_db.connect()) as con:
        row = dict(con.execute("SELECT * FROM hotel_bookings WHERE hotel_id = ? LIMIT 1", (hotel_id,)).fetchone())
        start = con.execute("SELECT MAX(id) FROM hotel_bookings").fetchone()[0] + 1
        for i in range(extra):
            row.update(id=start + i, arrival_date=night, nights=1, status="confirmed", cancelled_date=None)
            con.execute(f"INSERT INTO hotel_bookings ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                        list(row.values()))
        con.commit()
    return start


def test_capacity_is_derived_from_past_nights():
    report = {h["hotel_id"]: h for h in hotel_capacity_report()}
    assert report[1]["capacity"] == 25 and report[2]["capacity"] == 26      # peaks of the real sample
    assert report[1]["overbooked_nights"] == [] and len(report[1]["nights"]) == 30
    assert "derived" in report[1]["capacity_source"]


def test_overbooking_risk_warns_agent_a():
    first = overbook()
    assert "2026-10-15" in hotel_facts(1)["overbooked_nights"]
    note = atlas_overbooking_note(reads.get_hotel_booking(first))
    assert "AT-CAP-01" in note and "2026-10-15" in note
    ticket = {"ticket_id": "T-1", "company": "atlas", "order_id": first, "booking_type": "hotel",
              "main_reason": "booking_status"}
    assert note in pipeline.ticket_note(ticket)


def test_deals_wait_for_the_owner_who_decides_once():
    out = AgentD(use_model=False, company="atlas").scan()
    assert len(out["proposals"]) == 2 and {d["outcome"] for d in out["decisions"]} == {"owner_pending"}
    deals = writes.hotel_deals("pending")
    assert len(deals) == 2 and all(d["nights"] for d in deals)
    again = AgentD(use_model=False, company="atlas").scan()            # one open deal per hotel
    assert {d["outcome"] for d in again["decisions"]} == {"send_back"}
    assert "reason is required" in writes.admin_decide_deal("owner", deals[0]["id"], False, "")["error"]
    assert writes.admin_decide_deal("owner", deals[0]["id"], True)["status"] == "approved"
    assert writes.get_proposal(deals[0]["proposal_id"])["decision"] == "approve"
    assert "already approved" in writes.admin_decide_deal("owner", deals[0]["id"], True)["error"]
    assert writes.admin_decide_deal("owner", deals[1]["id"], False, "high season")["status"] == "refused"


def test_deal_above_the_limit_is_sent_back():
    from callverse.coordinator import atlas_coordinator
    from callverse.coordinator.coordinator import new_case
    d = atlas_coordinator.review({"agent": "D", "action": "hotel_deal", "params": {"hotel_id": 1, "discount_pct": 35},
                                  "rule_id": "AT-DEAL-01", "facts_used": {}, "user_confirmed": False, "user_quote": ""},
                                 new_case("D"))
    assert d["outcome"] == "send_back" and writes.hotel_deals() == []


# ---------- low confidence -> Agent C ----------

def ticket(score, reason="late_delivery", order_id=4512):
    return {"ticket_id": "T", "main_reason": reason, "priority_label": "low", "order_id": order_id,
            "reasons": [{"reason": reason, "score": score, "sentence": "x"}]}


def test_low_confidence_cases_go_to_c(monkeypatch):
    # T26: the switch is OFF in config.yaml (null); this test turns it on with P20's value to check the routing.
    from callverse.config import load_config
    monkeypatch.setitem(load_config()["queues"], "low_confidence_margin", 0.02)
    assert confidence_margin(ticket(0.70)) == 0.01                        # ShopNova threshold 0.69
    assert route(ticket(0.70))["agent"] == "C" and route(ticket(0.70))["layer"] == "L2"
    assert route(ticket(0.80))["agent"] == "A"                            # sure enough: normal route
    assert route(ticket(0.70, order_id=None))["agent"] == "A"             # no case number: not a case for C
    assert route(ticket(0.70, reason="other"))["agent"] == "A"            # "other" has no score


def test_low_confidence_routing_is_off_in_the_demo_config():
    # T26: OFF until reviewed (2 wrong outcomes in the 72-message check): the normal route is kept.
    assert route(ticket(0.70))["agent"] == "A" and route(ticket(0.70))["layer"] == "L1"


def test_owner_buttons_go_through_the_channel():
    from callverse.channels import approvals
    assert approvals.run_stock_scan("atlas") == {"overbooked": 0, "low": 2, "proposed": 2}
    deal = approvals.atlas_deals("pending")[0]
    assert approvals.decide_atlas_deal(deal["id"], "owner", True)["status"] == "approved"
