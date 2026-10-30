"""The Atlas Travel Coordinator (T21): the same safety gate as ShopNova's, with Atlas's rules. Rules only, NO LLM.

Why a second file and not more "if" in coordinator.py? The gate is the same idea (re-read the facts, check the rule,
ask finance, then write) but the money is different: a ShopNova refund has an amount proposed by the agent and
checked by the Coordinator; at Atlas the agent proposes NO amount at all. Keeping them apart also guarantees that
ShopNova's logic did not change by a single line.

An Atlas proposal, e.g.
    {"agent": "B", "action": "compensation", "params": {"booking_type": "flight", "booking_id": 7004},
     "rule_id": "AT-FLT-03", "facts_used": {...}, "user_confirmed": True, "user_quote": "..."}
has three possible actions: refund, compensation, cancel_hotel. review() checks, in this order:
  1. the action is known; the booking exists and is the ticket's booking (a proposal cannot move to another booking);
  2. the facts are RE-READ here (the agent's facts_used are only kept in the trace, for comparison);
  3. the cited rule exists, may justify this action, and its condition holds on the re-read facts.
     A hotel cancellation: the booking is confirmed, arrival is after today, and the rule is the one of its deposit;
  4. the AMOUNT IS COMPUTED BY THIS FILE from the rules (below), then AT-REF-01 (refund limit) is always checked,
     a compensation is paid once per booking, and AT-FLT-06 (extraordinary cause) blocks a compensation;
  5. the client confirmed, else ask the client. Decided by THIS file (client_confirmed), not by the agent's flag;
  6. finance: AT-ESC-01 (a refund above 1,500 TND, and every compensation);
  7. approve, then (only then) callverse/data/atlas/writes.py writes.

Amounts by code, because an LLM can misread a number and a wrong amount is real money:
  AT-FLT-01, AT-FLT-04, AT-HOT-02 : paid - refunded_total
  AT-HOT-04                       : 20 % of the total, at most what is left (AT-REF-01)
  AT-FLT-02, AT-FLT-03            : the band of the rule's text, by distance (and by delay above 3,500 km)
  hotel cancellation              : by deposit type (AT-HOT-01 / 02 / 03), see cancel_amount

The outcomes are ShopNova's, and so is what the pipeline does with them. AT-FLT-05 (meals) and AT-FLT-06 are
information only: they justify no action.
"""

import re
from datetime import date

from callverse import companies, trace
from callverse.config import load_config, sim_today
from callverse.coordinator.coordinator import INTERNAL_OUTCOMES, RECORDED_AS, _check
from callverse.data.atlas import reads, writes
from callverse.data.atlas.schema import BOOKING_TYPES
from callverse.data.layer3 import atlas_layer3_decide, layer3_mode
from callverse.data.writes import is_valid_amount
from callverse.kb.policies import check_condition, get_policy

COMPANY = "atlas"
CASE_WORD = "booking"     # the reply writer says "booking 7005", not "order 7005"

# The compensation bands of AT-FLT-02 and AT-FLT-03 (a test checks that each one is written in the rule's text).
SHORT_FLIGHT_KM, MEDIUM_FLIGHT_KM = 1500, 3500
BAND_SHORT, BAND_MEDIUM, BAND_LONG, BAND_LONG_3_TO_4_HOURS = 839.50, 1343.20, 2014.80, 1007.40
FOUR_HOURS_MIN = 240

ROOM_CHANGE_RULE, ROOM_CHANGE_SHARE = "AT-HOT-04", 0.20
FREE_CANCEL_DAYS = 2      # AT-HOT-02: a refundable deposit comes back if cancelled at least 2 days before arrival
CANCEL_RULES = {"no_deposit": "AT-HOT-01", "refundable": "AT-HOT-02", "non_refundable": "AT-HOT-03"}

# How a status code is said to the user.
HOTEL_WORDS = {"confirmed": "confirmed", "stayed": "completed", "cancelled": "cancelled",
               "no_show": "marked as a no-show"}
FLIGHT_WORDS = {"scheduled": "is scheduled", "on_time": "was on time", "delayed": "was delayed",
                "cancelled": "is cancelled"}

ESCALATE_SENTENCE = "Your request has been passed on to a colleague who will help you with it."

CONFIRMING_REASONS = ("refund_request", "compensation_request", "cancellation")   # Intake reasons that ask for an action
# A quoted sentence with one of these whole words is not a request: the client is asked first.
NEGATIVE_WORDS = re.compile(r"\b(?:not|don't|dont|do not|never|no longer|doesn't|didn't)\b", re.IGNORECASE)
SENTENCE_ENDS = ".!?\n"
ACTION_WORDS = {"refund": "a refund", "compensation": "a compensation", "cancel_hotel": "a hotel cancellation"}
ACTION_TOOLS = {"refund": "propose_refund", "compensation": "propose_compensation",
                "cancel_hotel": "propose_hotel_cancellation"}


def _rule(rule_id) -> dict | None:
    return get_policy(rule_id, COMPANY) if isinstance(rule_id, str) else None


def days_to_arrival(facts: dict) -> int:
    """Days from today to the hotel arrival date (not stored: today moves with the simulation clock)."""
    return (date.fromisoformat(facts["arrival_date"]) - sim_today()).days


def left_to_refund(facts: dict) -> float:
    return round(facts["paid_tnd"] - facts["refunded_total"], 2)


def compensation_amount(rule_id: str, facts: dict) -> float:
    """The band of AT-FLT-02 / AT-FLT-03. Above 3,500 km, a delay of 3 to 4 hours pays less than a cancellation."""
    km = facts["distance_km"]
    if km <= SHORT_FLIGHT_KM:
        return BAND_SHORT
    if km <= MEDIUM_FLIGHT_KM:
        return BAND_MEDIUM
    if rule_id == "AT-FLT-03" and facts["arrival_delay_min"] < FOUR_HOURS_MIN:
        return BAND_LONG_3_TO_4_HOURS
    return BAND_LONG


def cancel_amount(facts: dict) -> float:
    """What a hotel cancellation pays back: paid - refunded for a refundable deposit at least 2 days before
    arrival, else nothing (no deposit = nothing was paid; non-refundable, or too late = nothing comes back)."""
    if facts["deposit_type"] == "refundable" and days_to_arrival(facts) >= FREE_CANCEL_DAYS:
        return left_to_refund(facts)
    return 0.0


def amount_for(action: str, rule_id: str, facts: dict) -> float:
    """The amount of this action, from the rules. The only place an Atlas amount comes from."""
    if action == "compensation":
        return compensation_amount(rule_id, facts)
    if action == "cancel_hotel":
        return cancel_amount(facts)
    if rule_id == ROOM_CHANGE_RULE:
        return min(round(facts["total_tnd"] * ROOM_CHANGE_SHARE, 2), left_to_refund(facts))
    return left_to_refund(facts)


def read_facts(booking_type: str, booking_id: int) -> dict | None:
    """The facts the rules need, read by the Coordinator itself. None if the booking does not exist."""
    read = reads.get_flight_booking if booking_type == "flight" else reads.get_hotel_booking
    booking = read(booking_id)
    if "error" in booking:
        return None
    refunds = reads.get_refunds(booking_type, booking_id)["refunds"]
    return {**booking, "booking_type": booking_type, "booking_id": booking_id,
            "rules_paid": [r["rule_id"] for r in refunds if r["status"] in ("approved", "completed")],
            "compensated": reads.get_compensations(booking_type, booking_id)["compensated_total"] > 0}


def _cancel_problem(rule_id: str, facts: dict) -> str | None:
    """Why this hotel booking cannot be cancelled under this rule, or None."""
    if facts["booking_type"] != "hotel":
        return "only a hotel booking can be cancelled by this action"
    if facts["status"] != "confirmed":
        return f"only a confirmed booking can be cancelled; this one is {facts['status']}"
    if days_to_arrival(facts) <= 0:
        return f"the arrival date {facts['arrival_date']} has passed or is today: too late to cancel"
    right_rule = CANCEL_RULES[facts["deposit_type"]]
    if rule_id != right_rule:
        return f"a booking with deposit type {facts['deposit_type']} is cancelled under {right_rule}"
    return None


def _rule_holds(action: str, rule: dict, facts: dict) -> bool:
    """True if the rule's condition holds. A cancellation has not happened yet, so its rule reads the booking as if it
    were cancelled today. AT-HOT-02 late (under 2 days): its refund does not apply but the client may still cancel:
    cancel_amount then pays nothing, as the rule's text says ("After that there is no refund")."""
    seen = facts
    if action == "cancel_hotel":
        days = days_to_arrival(facts)
        if rule["id"] == "AT-HOT-02" and days < FREE_CANCEL_DAYS:
            return True
        seen = {**facts, "status": "cancelled", "days_before_arrival": days}
    try:
        return check_condition(rule["condition"], seen)
    except (ValueError, TypeError):   # a flight rule on a hotel booking (missing fact), or an empty delay
        return False


def _paid_before(action: str, rule_id: str, facts: dict) -> str | None:
    """Why this was already paid, or None: a compensation once per booking, a rule once per booking."""
    if action == "compensation" and facts["compensated"]:
        return "this booking already has a compensation"
    if action == "refund" and rule_id in facts["rules_paid"]:
        return f"rule {rule_id} was already paid for this booking"
    return None


def money_action(action: str) -> str:
    """What finance looks at: a cancellation's money is a refund."""
    return "compensation" if action == "compensation" else "refund"


def needs_finance(action: str, amount: float) -> bool:
    """AT-ESC-01, read from the policy file: a refund above 1,500 TND (exactly 1,500.00 is automatic), and every
    compensation."""
    rule = _rule(companies.get(COMPANY)["finance_rule"])
    return check_condition(rule["condition"], {"action": money_action(action), "amount": amount})


def reply_facts(checked: dict, action) -> dict:
    """The facts the reply may use (only what is verified, nothing the client should not see)."""
    out = {"booking_status": checked.get("status"), "flight_status": checked.get("flight_status")}
    if is_valid_amount(checked.get("amount")):
        out["amount_tnd"] = round(float(checked["amount"]), 2)
    if checked.get("layer3_decision"):
        out["layer3_decision"] = checked["layer3_decision"]
    return {k: v for k, v in out.items() if v is not None}


def _name(action) -> str:
    return "compensation" if action == "compensation" else "refund"


def client_confirmed(proposal: dict, case: dict) -> bool:
    """True when Intake's main reason says the client asks for money or a cancellation AND the agent's user_quote is
    really in the client's message (upper / lower case and outer spaces do not count), in a sentence that is not
    negative (quoted_sentence). An empty quote confirms nothing.

    Why code and not the agent's user_confirmed? In T21's live proof the model said false on "please refund me" while
    quoting those very words. Both checks read what Intake and the client gave, not what the model concluded.
    Why the negative words? The matcher reads "Please do not cancel my booking" as a cancellation, by meaning.
    """
    quote = proposal.get("user_quote")
    if case.get("main_reason") not in CONFIRMING_REASONS or not isinstance(quote, str) or not quote.strip():
        return False
    sentence = quoted_sentence(quote.strip().lower(), (case.get("user_message") or "").lower())
    return sentence is not None and NEGATIVE_WORDS.search(sentence.replace("’", "'")) is None


def quoted_sentence(quote: str, message: str) -> str | None:
    """The whole sentence of the message around the quote, or None if the quote is not in the message. The whole
    sentence, because a quote of "refund booking 7008" must not hide the "Do not" just before it."""
    start = message.find(quote)
    if start < 0:
        return None
    end = start + len(quote)
    before = max(message.rfind(mark, 0, start) for mark in SENTENCE_ENDS)
    after = [i for i in (message.find(mark, end - 1) for mark in SENTENCE_ENDS) if i >= 0]   # the quote's own "." counts
    return message[before + 1:min(after, default=len(message))]


def wrong_rule_reason(rule_id: str, action: str, allowed: dict) -> str:
    """The send-back for a rule that cannot justify this action. If it justifies another action, say which one and
    its tool: the agent has the right rule and the wrong tool, and a list of rules would lead it further away."""
    others = [a for a, rules in allowed.items() if a != action and rule_id in rules]
    if not others:
        return f"rule {rule_id} cannot justify a {action}; use one of {allowed[action]}"
    return (f"{rule_id} justifies {' or '.join(ACTION_WORDS[a] for a in others)}: "
            f"use {' or '.join(ACTION_TOOLS[a] for a in others)}")


def _cancel_next_step(rule_id, amount) -> str:
    if amount is not None:
        return ""
    return {"AT-HOT-01": "There is nothing to pay.",
            "AT-HOT-02": f"It is less than {FREE_CANCEL_DAYS} days before arrival, so nothing is paid back.",
            "AT-HOT-03": "This booking is non-refundable, so nothing is paid back."}.get(rule_id, "")


def user_words(outcome: str, action, rule_id, facts: dict, booking_id) -> tuple[list[str], str]:
    """(must_say, next_step) written TO THE USER for a decision. The SLM copies must_say word for word."""
    amount = facts.get("amount_tnd")
    money = f"{amount:.2f} TND" if amount is not None else None
    what = _name(action)
    finance_ok = facts.get("layer3_decision") == "approved"
    if outcome == "approve":
        paid = f"Your {what} of {money} for booking {booking_id} is approved"
        paid += " after a check by our finance team." if finance_ok else "."
        if action == "cancel_hotel":
            cancelled = f"Your hotel booking {booking_id} is cancelled."
            return ([cancelled, paid] if amount is not None else [cancelled]), _cancel_next_step(rule_id, amount)
        return [paid], ""
    if outcome == "layer3_refused":
        return ([f"We cannot approve a {what} of {money} for booking {booking_id}."],
                "Our finance team reviewed it and did not approve it.")
    if outcome == "layer3_pending":
        return ([f"Your {what} of {money} for booking {booking_id} needs approval from our finance team."],
                "We will reply here as soon as it has been reviewed.")
    if outcome == "ask_user":
        if action == "cancel_hotel":
            return [f"Please confirm that you want to cancel your hotel booking {booking_id}."], ""
        return [f"Please confirm that you want a {what} of {money} for booking {booking_id}."], ""
    if outcome == "escalate":
        return [ESCALATE_SENTENCE], ""
    return [], ""   # send_back / refused: internal, no words for the user


def _decision(outcome, action, booking_id, booking_type, rule_id, facts, must_say, next_step, reason,
              proposal_id) -> dict:
    """The decision in the usual shape, plus what tells the rest of the center it is Atlas's. `order_id` is the
    shared name of "the case's number": here, the booking."""
    return {"company": COMPANY, "case_word": CASE_WORD, "outcome": outcome, "action": action, "order_id": booking_id,
            "booking_type": booking_type, "rule_id": rule_id, "facts": facts, "must_say": must_say,
            "next_step": next_step, "reason": reason, "proposal_id": proposal_id}


def info_decision(booking_id, main_reason=None) -> dict:
    """A case WITHOUT a proposal (status questions, no rule applies): the status, read here, never from the agent's
    text. No compensation case gets a refusal sentence yet (T14): it gets the status only."""
    booking = reads.find_booking(booking_id) if booking_id is not None else None
    if booking is None:
        decision = _decision("info", "status", None, None, None, {}, [],
                             "Please tell us your booking number so we can check it.", "no booking number", None)
    elif "error" in booking:
        decision = _decision("info", "status", booking_id, None, None, {}, [f"We could not find booking {booking_id}."],
                             "Please check the booking number and send it again.", "unknown booking", None)
    elif booking["booking_type"] == "hotel":
        words = HOTEL_WORDS.get(booking["status"], str(booking["status"]).replace("_", " "))
        decision = _decision("info", "status", booking_id, "hotel", None, reply_facts(booking, "status"),
                             [f"Your hotel booking {booking_id} is {words}."], "", "status from the booking", None)
    else:
        flight_status = booking["flight_status"]
        words = FLIGHT_WORDS.get(flight_status, f"is {str(flight_status).replace('_', ' ')}")
        meal = (main_reason == "delay_disruption" and check_condition(_rule("AT-FLT-05")["condition"], booking))
        decision = _decision("info", "status", booking_id, "flight", "AT-FLT-05" if meal else None,
                             reply_facts(booking, "status"), [f"Your flight booking {booking_id} {words}."],
                             "Our rules give a meal to clients waiting for a delay like this one." if meal else "",
                             "status from the booking", None)
    trace.log("coordinator_decision", "coordinator", decision)
    return decision


def off_topic_decision() -> dict:
    """Not about a booking: a polite redirect to what Atlas's support can do. No facts at all."""
    decision = _decision("info", "redirect", None, None, None, {},
                         ["I can help with your Atlas Travel bookings: flights, hotel stays, refunds and compensation."],
                         "If your question is about a booking, please send us the booking number.", "off topic", None)
    trace.log("coordinator_decision", "coordinator", decision)
    return decision


def escalate_decision(order_id, reason: str) -> dict:
    """A human colleague takes over: a route with no agent yet (rebooking, assistance), or an error before a decision."""
    must_say, next_step = user_words("escalate", None, None, {}, order_id)
    decision = _decision("escalate", None, None, None, None, {}, must_say, next_step, reason, None)
    trace.log("coordinator_decision", "coordinator", decision)
    return decision


def for_user(decision: dict) -> dict:
    """A decision the user may get a reply for: an internal outcome left at the end of the loop is said as "escalate"."""
    if decision["outcome"] not in INTERNAL_OUTCOMES:
        return decision
    must_say, next_step = user_words("escalate", decision["action"], decision["rule_id"], decision["facts"],
                                     decision["order_id"])
    out = {**decision, "outcome": "escalate", "must_say": must_say, "next_step": next_step,
           "reason": f"internal outcome {decision['outcome']} at the end of the case: {decision['reason']}"}
    trace.log("internal_outcome_to_escalate", "coordinator",
              {"from": decision["outcome"], "proposal_id": decision["proposal_id"]})
    return out


def said_to_user(ticket: dict, decision: dict | None) -> dict:
    """What the client is told: the Coordinator's decision, else the redirect or the status."""
    if decision:
        return for_user(decision)
    if ticket.get("main_reason") == "other" and ticket.get("order_id") is None:
        return off_topic_decision()
    return info_decision(ticket.get("order_id"), ticket.get("main_reason"))


def review(proposal: dict, case: dict) -> dict:
    """Check one proposal and return the decision (see the steps at the top of this file)."""
    is_dict = isinstance(proposal, dict)
    action = proposal.get("action") if is_dict else None
    params = proposal.get("params") if is_dict and isinstance(proposal.get("params"), dict) else {}
    rule_id = proposal.get("rule_id") if is_dict else None
    booking_id, booking_type = params.get("booking_id"), params.get("booking_type")
    facts: dict = {}

    # 0. Record the proposal first (audit trail), unless it was already recorded.
    proposal_id = proposal.get("proposal_id") if is_dict else None
    if proposal_id is None:
        recorded = writes.record_proposal(proposal)
        proposal_id = recorded.get("id")
        if proposal_id is None:
            return _finish("send_back", case, None, action, booking_id, booking_type, rule_id, facts,
                           f"proposal could not be recorded: {recorded.get('error')}")

    def done(outcome: str, reason: str) -> dict:
        return _finish(outcome, case, proposal_id, action, booking_id, booking_type, rule_id, facts, reason)

    # 1. Known action, existing booking, the ticket's own booking.
    allowed = companies.get(COMPANY)["allowed_rules"]
    if not _check("action_known", action in allowed, None, {"action": action}, f"allowed actions: {list(allowed)}"):
        return done("send_back", f"unknown action '{action}' (allowed: {', '.join(allowed)})")
    well_formed = (isinstance(booking_id, int) and not isinstance(booking_id, bool) and booking_type in BOOKING_TYPES)
    read = read_facts(booking_type, booking_id) if well_formed else None
    if not _check("booking_exists", read is not None, None, {"booking_id": booking_id, "booking_type": booking_type},
                  "read from atlas.db"):
        return done("send_back", f"{booking_type} booking {booking_id} not found")
    own = (booking_id, booking_type) == (case.get("order_id"), case.get("booking_type"))
    if not _check("booking_of_the_case", own, None, {"booking_id": booking_id}, f"the ticket's booking is "
                  f"{case.get('booking_type')} {case.get('order_id')}"):
        return done("send_back", f"this case is about {case.get('booking_type')} booking {case.get('order_id')}")

    # 2. Facts re-read from the data.
    facts = read
    _check("facts_from_data", True, None, facts, f"agent claimed: {proposal.get('facts_used')}")

    # 3. The cited rule: exists, may justify this action, its condition holds.
    rule = _rule(rule_id)
    if not _check("rule_exists", rule is not None, rule_id, {}, "looked up in the policy file"):
        return done("send_back", f"rule {rule_id} does not exist")
    if not _check("rule_fits_action", rule_id in allowed[action], rule_id, {"action": action},
                  f"rules that can justify '{action}': {allowed[action]}"):
        return done("send_back", wrong_rule_reason(rule_id, action, allowed))
    searched = case.get("searched_rules")
    if searched is not None and rule_id not in searched:
        trace.log("rule_not_searched", "coordinator", {"rule_id": rule_id, "searched": sorted(searched),
                                                        "proposal_id": proposal_id})
    if action == "cancel_hotel":
        problem = _cancel_problem(rule_id, facts)
        if not _check("hotel_can_be_cancelled", problem is None, rule_id, facts, problem or "confirmed, before arrival"):
            return done("send_back", problem)
    if not _check("rule_condition", _rule_holds(action, rule, facts), rule_id, facts, rule["condition"]):
        return done("send_back", f"{rule_id} does not apply: its condition '{rule['condition']}' is false for this booking")

    # 4. The money: by code, then the limits that always apply.
    problem = _paid_before(action, rule_id, facts)
    if not _check("not_paid_before", problem is None, rule_id, {"action": action}, problem or "nothing paid under it"):
        return done("send_back", problem)
    if action == "compensation":
        extraordinary = check_condition(_rule("AT-FLT-06")["condition"], facts)
        if not _check("not_extraordinary", not extraordinary, "AT-FLT-06", facts, "weather, air system or security"):
            return done("send_back", "AT-FLT-06: an extraordinary cause, no compensation is paid")
    facts["amount"] = amount_for(action, rule_id, facts)
    if action == "cancel_hotel":
        valid = is_valid_amount(facts["amount"]) or facts["amount"] == 0
    else:
        valid = is_valid_amount(facts["amount"])
    if not _check("amount_by_code", valid, rule_id, {"amount": facts["amount"]}, "computed from the rules"):
        return done("send_back", f"{rule_id}: nothing is left to pay for this booking")
    if action != "compensation":
        limit = _rule("AT-REF-01")
        if not _check("refund_limit", check_condition(limit["condition"], facts), "AT-REF-01", facts, limit["condition"]):
            return done("send_back", f"AT-REF-01: {facts['amount']} TND is more than what is left to refund")
    stored = writes.set_proposal_amount(proposal_id, facts["amount"])
    if "error" in stored:
        return done("refused", stored["error"])

    # 5. The client must have asked for it.
    if not _check("user_confirmed", client_confirmed(proposal, case), None,
                  {"user_quote": proposal.get("user_quote"), "main_reason": case.get("main_reason"),
                   "agent_said": proposal.get("user_confirmed")}, "a request reason + the quote is in the message, not negative"):
        return done("ask_user", "the client has not confirmed the request yet")

    # 6. Finance (Layer 3) decides first when AT-ESC-01 says so.
    if needs_finance(action, facts["amount"]):
        if layer3_mode() == "queue":
            facts["layer3_decision"] = "pending"
            trace.log("coordinator_check", "coordinator",
                      {"check": "layer3", "rule_id": "AT-ESC-01", "facts": facts, "result": "pending",
                       "detail": "layer3 mode queue: waiting for the Atlas admin"})
            return done("layer3_pending", f"AT-ESC-01: the {_name(action)} of {facts['amount']} TND waits for finance")
        finance = atlas_layer3_decide(booking_type, booking_id, money_action(action), facts["amount"],
                                      f"{action} under {rule_id}")
        facts["layer3_decision"] = finance.get("decision")
        if not _check("layer3", finance.get("decision") == "approved", "AT-ESC-01", facts, f"finance: {finance}"):
            if finance.get("decision") == "refused":
                return done("layer3_refused", f"AT-ESC-01: finance refused the {_name(action)} of {facts['amount']} TND")
            return done("escalate", f"Layer 3 error: {finance.get('error')}")

    # 7. Approve, then (only then) the write.
    return done("approve", f"all checks passed under {rule_id}")


def _write(action, booking_type, booking_id, amount, rule_id, proposal_id) -> dict:
    if action == "refund":
        return writes.create_refund(booking_type, booking_id, amount, rule_id, proposal_id)
    if action == "compensation":
        return writes.create_compensation(booking_type, booking_id, amount, rule_id, proposal_id)
    return writes.cancel_hotel_booking(booking_id, proposal_id)


def _finish(outcome, case, proposal_id, action, booking_id, booking_type, rule_id, facts, reason) -> dict:
    """Apply the send-back limit, record the decision, write on approve, trace and return the decision."""
    if outcome == "send_back" and case["send_backs"] >= load_config()["coordinator"]["max_send_backs"]:
        outcome, reason = "escalate", f"too many send-backs ({case['send_backs']}); last reason: {reason}"

    if proposal_id is not None and outcome != "layer3_pending":   # pending = not decided yet
        stored = writes.record_decision(proposal_id, RECORDED_AS.get(outcome, outcome), reason)
        if "error" in stored:   # e.g. already decided: never decide twice, never write
            outcome, reason = "refused", stored["error"]

    if outcome == "send_back":
        case["send_backs"] += 1

    if outcome == "approve":
        row = _write(action, booking_type, booking_id, facts["amount"], rule_id, proposal_id)
        if "error" in row:      # a safety net refused the write: a human must look
            outcome, reason = "escalate", f"write refused by the platform: {row['error']}"
        elif action == "cancel_hotel":
            facts["status"] = "cancelled"

    said = reply_facts(facts, action)
    must_say, next_step = user_words(outcome, action, rule_id, said, booking_id)
    decision = _decision(outcome, action, booking_id, booking_type, rule_id, said, must_say, next_step, reason,
                         proposal_id)
    trace.log("coordinator_decision", "coordinator", {**decision, "checked_facts": facts, "case": _plain(case)})
    return decision


def _plain(case: dict) -> dict:
    """The case for the trace (a set is not JSON)."""
    return {k: sorted(v) if isinstance(v, set) else v for k, v in case.items()}


# ---------- finance's decision, later (callverse/channels/approvals.py) ----------

def recheck(proposal: dict) -> tuple[dict, str | None]:
    """The checks again, on fresh data, before finance's approval is written. (facts, None) if they all pass, or
    (facts, reason in plain words) for the first one that fails."""
    action, rule_id = proposal.get("action"), proposal.get("rule_id")
    params = proposal.get("params") or {}
    booking_type, booking_id = params.get("booking_type"), params.get("booking_id")
    allowed = companies.get(COMPANY)["allowed_rules"]
    facts = read_facts(booking_type, booking_id) if booking_type in BOOKING_TYPES and booking_id else None
    if facts is None:
        return {}, f"{booking_type} booking {booking_id} does not exist any more"
    rule = _rule(rule_id)
    if rule is None or rule_id not in allowed.get(action, []):
        return facts, f"rule {rule_id} cannot justify a {action}"
    if action == "cancel_hotel" and (problem := _cancel_problem(rule_id, facts)):
        return facts, problem
    if not _rule_holds(action, rule, facts):
        return facts, f"rule {rule_id} does not apply any more: its condition '{rule['condition']}' is false now"
    if problem := _paid_before(action, rule_id, facts):
        return facts, problem
    facts["amount"] = amount_for(action, rule_id, facts)
    if params.get("amount") is None or round(float(params["amount"]), 2) != round(float(facts["amount"]), 2):
        return facts, f"the amount changed: the rules now give {facts['amount']} TND, the proposal {params.get('amount')} TND"
    return facts, None


def finance_decision(proposal: dict, facts: dict, approved: bool, booking_status: str | None = None) -> dict:
    """The decision told to the client after finance decided. The admin's reason is not in it."""
    params = proposal.get("params") or {}
    action, rule_id = proposal["action"], proposal["rule_id"]
    booking_id, booking_type = params.get("booking_id"), params.get("booking_type")
    checked = {**facts, "amount": params.get("amount"), "layer3_decision": "approved" if approved else "refused"}
    if booking_status:
        checked["status"] = booking_status
    outcome = "approve" if approved else "layer3_refused"
    said = reply_facts(checked, action)
    must_say, next_step = user_words(outcome, action, rule_id, said, booking_id)
    return _decision(outcome, action, booking_id, booking_type, rule_id, said, must_say, next_step,
                     "decided by the Atlas admin (Layer 3)", proposal["id"])
