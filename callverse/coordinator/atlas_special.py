"""The Atlas Coordinator's checks for Agent C's proposals (P20). Rules only, NO LLM, like atlas_coordinator.py.

    rebook      (rule AT-FLT-01)  the booked flight is cancelled; the new flight is on the same route, leaves later,
                                  is not cancelled and is still to come; the booking was not rebooked before
    assistance  (rule AT-AST-01)  e.g. a wheelchair, asked at least 48 hours before departure; not asked before
Steps: record -> the ticket's own flight booking -> facts re-read -> rule condition -> the client's yes -> write.
The client's yes = the agent's user_confirmed AND the message answers C's own question (case["client_said_yes"],
set by the pipeline). Mobility needs are sensitive (spec): never on the model's word alone.
"""

from callverse import trace
from callverse.config import load_config
from callverse.coordinator.atlas_coordinator import COMPANY, _decision, read_facts
from callverse.coordinator.coordinator import _check
from callverse.data.atlas import reads, writes
from callverse.kb.policies import check_condition, get_policy
from callverse.tools.atlas_c_tools import ASSISTANCE_KINDS, RULES, alternatives

ACTIONS = tuple(RULES) + ("hotel_deal",)   # hotel_deal = Agent D's (AT-DEAL-01), see review_deal


def user_words(outcome: str, action: str, facts: dict, booking_id) -> tuple[list[str], str]:
    new = facts.get("new_flight") or {}
    if outcome == "approve" and action == "rebook":
        return [f"Your booking {booking_id} is moved to flight {new.get('carrier_name')} {new.get('flight_number')} "
                f"leaving on {new.get('scheduled_departure')}."], ""
    if outcome == "approve" and action == "assistance":
        return [f"A {facts.get('kind')} is requested for your flight booking {booking_id}."], ""
    if outcome == "ask_user" and action == "rebook":
        return [f"Please confirm that you want to move booking {booking_id} to flight {new.get('carrier_name')} "
                f"{new.get('flight_number')} leaving on {new.get('scheduled_departure')}."], ""
    if outcome == "ask_user" and action == "assistance":
        return [f"Please confirm that you want a {facts.get('kind')} for your flight booking {booking_id}."], ""
    if outcome == "escalate":
        return ["Your request has been passed on to a colleague who will help you with it."], ""
    return [], ""


def review_deal(proposal: dict, case: dict) -> dict:
    """Agent D's hotel deal (AT-DEAL-01): facts re-read (derived capacity, coming occupancy), rule condition, then
    "owner_pending": the deal is stored as pending and only the owner approves it. Nothing else is written."""
    from callverse.tools.capacity_tools import hotel_facts
    params = proposal.get("params") if isinstance(proposal.get("params"), dict) else {}
    recorded = writes.record_proposal(proposal)
    pid = recorded.get("id")
    facts = hotel_facts(params.get("hotel_id")) if isinstance(params.get("hotel_id"), int) else {"error": "bad id"}
    facts = {**facts, "discount_pct": params.get("discount_pct")}

    def out(outcome, reason, row=None):
        if outcome != "owner_pending" and pid:
            writes.record_decision(pid, outcome, reason)
        d = _decision(outcome, "hotel_deal", None, "hotel", proposal.get("rule_id"), {}, [], "", reason, pid)
        if row:
            d["deal_id"] = row["id"]
        trace.log("coordinator_decision", "coordinator", {**d, "checked_facts": {k: facts.get(k) for k in (
            "hotel_id", "capacity", "min_occupancy_pct", "discount_pct")}})
        return d

    if pid is None or "error" in facts or proposal.get("rule_id") != "AT-DEAL-01":
        return out("send_back", facts.get("error") or "a hotel deal is justified only by AT-DEAL-01")
    rule = get_policy("AT-DEAL-01", COMPANY)
    try:
        holds = facts["min_occupancy_pct"] is not None and check_condition(rule["condition"], facts)
    except ValueError:
        holds = False
    if not _check("rule_condition", holds, "AT-DEAL-01", {k: facts.get(k) for k in ("min_occupancy_pct", "discount_pct")},
                  rule["condition"]):
        return out("send_back", f"AT-DEAL-01 does not apply: '{rule['condition']}' is false for this hotel")
    row = writes.create_hotel_deal(params["hotel_id"], facts["low_nights"], params["discount_pct"], proposal.get("note"),
                                   pid)
    if "error" in row:
        return out("send_back", f"deal not stored: {row['error']}")
    return out("owner_pending", f"AT-DEAL-01: deal {row['id']} waits for the owner", row)


def review(proposal: dict, case: dict) -> dict:
    action = proposal.get("action")
    if action == "hotel_deal":
        return review_deal(proposal, case)
    params = proposal.get("params") if isinstance(proposal.get("params"), dict) else {}
    booking_id, rule_id = params.get("booking_id"), proposal.get("rule_id")
    facts: dict = {}
    recorded = writes.record_proposal(proposal)
    proposal_id = recorded.get("id")

    def done(outcome, reason):
        return _finish(outcome, case, proposal_id, proposal, facts, reason)

    if proposal_id is None:
        return done("send_back", f"not recorded: {recorded.get('error')}")
    if not _check("rule_fits_action", action in ACTIONS and rule_id == RULES.get(action), rule_id,
                  {"action": action}, f"C actions at Atlas: {RULES}"):
        return done("send_back", f"'{action}' is justified only by {RULES.get(action)}")
    read = read_facts("flight", booking_id) if isinstance(booking_id, int) and not isinstance(booking_id, bool) else None
    if not _check("booking_exists", read is not None, None, {"booking_id": booking_id}, "read from atlas.db"):
        return done("send_back", f"flight booking {booking_id} not found")
    own = (booking_id, "flight") == (case.get("order_id"), case.get("booking_type"))
    if not _check("booking_of_the_case", own, None, {"booking_id": booking_id},
                  f"the ticket's booking is {case.get('booking_type')} {case.get('order_id')}"):
        return done("send_back", f"this case is about {case.get('booking_type')} booking {case.get('order_id')}")
    facts = dict(read)

    if action == "rebook":
        new = reads.get_flight(params.get("new_flight_id")) if isinstance(params.get("new_flight_id"), int) else None
        offered = {f["id"] for f in alternatives(read)}
        facts["new_flight"] = new if new and "error" not in new else None
        if not _check("new_flight_fits", params.get("new_flight_id") in offered, rule_id,
                      {"new_flight_id": params.get("new_flight_id"), "alternatives": sorted(offered)},
                      "same route, later, not cancelled, scheduled"):
            return done("send_back", f"flight {params.get('new_flight_id')} is not a later flight on this route "
                                     f"(alternatives: {sorted(offered) or 'none'})")
    else:
        facts["kind"] = params.get("kind")
        if not _check("kind_known", facts["kind"] in ASSISTANCE_KINDS, rule_id, {"kind": facts["kind"]},
                      f"kinds: {ASSISTANCE_KINDS}"):
            return done("send_back", f"kind must be one of {list(ASSISTANCE_KINDS)}")

    rule = get_policy(rule_id, COMPANY)
    try:
        holds = check_condition(rule["condition"], facts)
    except ValueError:
        holds = False
    if not _check("rule_condition", holds, rule_id, {k: facts.get(k) for k in ("cancelled", "hours_before_departure")},
                  rule["condition"]):
        return done("send_back", f"{rule_id} does not apply: '{rule['condition']}' is false for this booking")

    said_yes = proposal.get("user_confirmed") is True and case.get("client_said_yes") is True
    if not _check("user_confirmed", said_yes, None, {"user_quote": proposal.get("user_quote"),
                                                     "answers_c_question": case.get("client_said_yes", False)},
                  "user_confirmed true AND the message answers Agent C's question"):
        return done("ask_user", "the client has not said yes yet: nothing changes before that")
    return done("approve", f"all checks passed under {rule_id}")


def _finish(outcome, case, proposal_id, proposal, facts, reason) -> dict:
    action, params = proposal.get("action"), proposal.get("params") or {}
    booking_id = params.get("booking_id")
    if outcome == "send_back" and case["send_backs"] >= load_config()["coordinator"]["max_send_backs"]:
        outcome, reason = "escalate", f"too many send-backs ({case['send_backs']}); last reason: {reason}"
    if proposal_id is not None:
        stored = writes.record_decision(proposal_id, outcome, reason)
        if "error" in stored:
            outcome, reason = "refused", stored["error"]
    if outcome == "send_back":
        case["send_backs"] += 1
    if outcome == "approve":
        row = (writes.rebook_flight(booking_id, params["new_flight_id"], proposal_id) if action == "rebook"
               else writes.request_assistance(booking_id, params["kind"], proposal_id))
        if "error" in row:
            outcome, reason = "escalate", f"write refused by the platform: {row['error']}"
    must_say, next_step = user_words(outcome, action, facts, booking_id)
    reply_facts = {k: v for k, v in {"kind": facts.get("kind"),
                                     "new_departure": (facts.get("new_flight") or {}).get("scheduled_departure")}.items()
                   if v is not None}
    decision = _decision(outcome, action, booking_id, "flight", proposal.get("rule_id"), reply_facts, must_say,
                         next_step, reason, proposal_id)
    trace.log("coordinator_decision", "coordinator", {**decision, "case": dict(case)})
    return decision
