"""The Coordinator's checks for the proposals of Agents C and D (P20). Rules only, NO LLM, like coordinator.py.

coordinator.review() sends these actions here:
    replace     (Agent C, rule R-RPL-01)  a free new unit of an order's item, from stock
    hold        (Agent C, rule R-HLD-01)  keep units of a product for the client for 1-3 days
    assistance  (Agent C, rule R-AST-01)  a hard or disputed case for a human colleague
    promotion   (Agent D, rule R-PRM-01)  a discount for an overstocked product, for the OWNER to decide

Same steps as for a refund:
  1. record the proposal (audit), known action, the cited rule is the action's rule;
  2. RE-READ the facts itself (get_order, get_tracking, stock_facts): the agent's facts_used are only traced;
  3. the rule's condition must hold on those facts (check_condition, no eval), else send_back;
  4. C: the client must have said yes, else ask_user: NOTHING changes until the client says yes. Two things are
     needed: the agent's user_confirmed AND the message answers C's own question (case["client_said_yes"]);
     D: no client; the owner decides -> owner_pending (the promotion is stored as "pending", nothing else);
  5. approve -> only then the platform writes (writes.create_replacement / create_hold / create_assistance_request).
"""

from callverse import trace
from callverse.config import load_config
from callverse.data import writes
from callverse.kb.policies import check_condition, get_policy
from callverse.tools.shopnova_tools import get_order, get_tracking
from callverse.tools.stock_tools import stock_facts

C_ACTIONS = ("replace", "hold", "assistance")
ACTIONS = C_ACTIONS + ("promotion",)
RULE_OF = {"replace": "R-RPL-01", "hold": "R-HLD-01", "assistance": "R-AST-01", "promotion": "R-PRM-01"}


def _check(name: str, ok: bool, rule_id, facts: dict, detail: str) -> bool:
    trace.log("coordinator_check", "coordinator", {"check": name, "rule_id": rule_id, "facts": facts,
                                                   "result": "pass" if ok else "fail", "detail": detail})
    return ok


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def read_facts(action: str, params: dict, case: dict) -> tuple[dict, str | None]:
    """(facts the rule needs, read by the Coordinator itself, or None + the reason they cannot be read)."""
    facts: dict = {}
    order_id = params.get("order_id")
    if action in ("replace", "hold") or (action == "assistance" and order_id is not None):
        if not _int(order_id) or "error" in (order := get_order(order_id)):
            return facts, f"order {order_id} not found"
        tracking = get_tracking(order_id)
        facts.update(order_id=order_id, status=order["status"], days_late=tracking["days_late"],
                     delivered=tracking["delivered"], proof_received=bool(case.get("proof_received")))
        order_products = [i.get("product_id") for i in order["items"]]
    if action in ("replace", "hold", "promotion"):
        stock = stock_facts(params.get("product_id"))
        if "error" in stock:
            return facts, stock["error"]
        if not stock["active"]:
            return facts, f"product {stock['product_id']} is not on sale"
        facts.update(product_id=stock["product_id"], product_name=stock["name"], stock=stock["stock"],
                     units_sold_30d=stock["units_sold_30d"], days_of_cover=stock["days_of_cover"])
    if action == "replace":
        facts.update(qty=params.get("qty"), in_order=params.get("product_id") in order_products)
    if action == "hold":
        facts.update(qty=params.get("qty"), hold_days=params.get("hold_days"))
    if action == "assistance":
        reason = params.get("reason")
        facts["has_reason"] = isinstance(reason, str) and bool(reason.strip())
    if action == "promotion":
        facts["discount_pct"] = params.get("discount_pct")
    for name in ("qty", "hold_days"):
        if name in facts and not _int(facts[name]):
            return facts, f"{name} must be a whole number"
    if action == "promotion" and (isinstance(facts["discount_pct"], bool)
                                  or not isinstance(facts["discount_pct"], (int, float))):
        return facts, "discount_pct must be a number"
    return facts, None


def user_words(outcome: str, action: str, facts: dict, row: dict | None) -> tuple[list[str], str]:
    """(must_say, next_step) written TO THE CLIENT, from verified facts and the written row only."""
    name, qty = facts.get("product_name", "item"), facts.get("qty") or 1
    order_id = facts.get("order_id")
    if outcome == "approve" and action == "replace" and row:
        return ([f"A free replacement {name} for order {order_id} is being prepared as new order "
                 f"{row['new_order_id']}."], "")
    if outcome == "approve" and action == "hold" and row:
        units = "1 unit" if qty == 1 else f"{qty} units"
        return [f"We are keeping {units} of {name} for you until {row['held_until']}."], ""
    if outcome == "approve" and action == "assistance":
        return ["Your case has been passed to a colleague of our special help team."], ""
    if outcome == "ask_user":
        question = {"replace": f"Please confirm that you want a free replacement {name} for order {order_id}.",
                    "hold": f"Please confirm that you want us to keep {name} for you for {facts.get('hold_days')} days.",
                    "assistance": "Please confirm that you want a colleague of our special help team to take "
                                  "over your case."}[action]
        return [question], ""
    if outcome == "escalate":
        return ["Your case needs an extra check, so it has been passed on for review."], ""
    return [], ""   # send_back / refused / owner_pending: nothing for the client


def review(proposal: dict, case: dict) -> dict:
    """Check one C or D proposal and return the decision dict (same keys as coordinator.review)."""
    action = proposal.get("action")
    params = proposal.get("params") if isinstance(proposal.get("params"), dict) else {}
    rule_id = proposal.get("rule_id")
    facts: dict = {}

    proposal_id = proposal.get("proposal_id")
    if proposal_id is None:
        recorded = writes.record_proposal(proposal)
        proposal_id = recorded.get("id")
        if proposal_id is None:
            return _finish("send_back", case, None, proposal, facts, f"not recorded: {recorded.get('error')}")

    def done(outcome: str, reason: str, row: dict | None = None) -> dict:
        return _finish(outcome, case, proposal_id, proposal, facts, reason, row)

    # 1. Known action, and the rule is that action's rule.
    if not _check("action_known", action in ACTIONS, None, {"action": action}, f"C/D actions: {list(ACTIONS)}"):
        return done("send_back", f"unknown action '{action}'")
    if not _check("rule_fits_action", rule_id == RULE_OF[action], rule_id, {"action": action},
                  f"'{action}' is justified only by {RULE_OF[action]}"):
        return done("send_back", f"rule {rule_id} cannot justify a {action}; use {RULE_OF[action]}")

    # 2. Facts re-read from the data.
    facts, problem = read_facts(action, params, case)
    if not _check("facts_from_data", problem is None, None, facts, f"agent claimed: {proposal.get('facts_used')}"):
        return done("send_back", problem)

    # 3. The rule's condition on those facts.
    rule = get_policy(rule_id)
    try:
        holds = check_condition(rule["condition"], facts)
    except ValueError as e:
        holds = False
        trace.log("coordinator_check", "coordinator", {"check": "rule_condition_error", "rule_id": rule_id,
                                                        "detail": str(e)})
    if not _check("rule_condition", holds, rule_id, facts, rule["condition"]):
        return done("send_back", f"{rule_id} does not apply: its condition '{rule['condition']}' is false for the "
                                 f"data ({_short(facts)})")

    # 4. D: the owner decides. C: the client must have said yes.
    if action == "promotion":
        row = writes.create_promotion(params["product_id"], params["discount_pct"], proposal.get("note"), proposal_id)
        if "error" in row:
            return done("send_back", f"promotion not stored: {row['error']}")
        trace.log("coordinator_check", "coordinator", {"check": "owner", "rule_id": rule_id, "facts": facts,
                                                        "result": "pending", "detail": "the owner decides"})
        return done("owner_pending", f"R-PRM-01: promotion {row['id']} waits for the owner", row)
    # The yes must come from the CONVERSATION, not from the model: case["client_said_yes"] is set by the pipeline only
    # when this message answers a question Agent C asked before (ticket continue_agent = "C"). In the P20 eval the
    # fine-tuned model set user_confirmed true for "I need it tomorrow" (no yes), so the model's flag alone is not enough.
    said_yes = proposal.get("user_confirmed") is True and case.get("client_said_yes") is True
    if not _check("user_confirmed", said_yes, None,
                  {"user_quote": proposal.get("user_quote"), "agent_flag": proposal.get("user_confirmed"),
                   "answers_c_question": case.get("client_said_yes", False)},
                  "user_confirmed true AND the message answers Agent C's question"):
        return done("ask_user", "the client has not said yes yet: nothing changes before that")

    # 5. Approve, then (only then) the platform writes.
    return done("approve", f"all checks passed under {rule_id}")


def _short(facts: dict) -> str:
    keys = ("status", "days_late", "delivered", "proof_received", "in_order", "stock", "qty", "hold_days",
            "days_of_cover", "discount_pct", "has_reason")
    return ", ".join(f"{k} {facts[k]}" for k in keys if k in facts)


def _finish(outcome, case, proposal_id, proposal, facts, reason, row=None) -> dict:
    """Send-back limit, record the decision, write on approve, trace and return the decision."""
    action, params = proposal.get("action"), proposal.get("params") or {}
    if outcome == "send_back" and case["send_backs"] >= load_config()["coordinator"]["max_send_backs"]:
        outcome, reason = "escalate", f"too many send-backs ({case['send_backs']}); last reason: {reason}"
    if proposal_id is not None and outcome != "owner_pending":   # pending = the owner decides later
        stored = writes.record_decision(proposal_id, outcome, reason)
        if "error" in stored:
            outcome, reason = "refused", stored["error"]
    if outcome == "send_back":
        case["send_backs"] += 1
    if outcome == "approve":
        if action == "replace":
            row = writes.create_replacement(params["order_id"], params["product_id"], params["qty"], proposal_id)
        elif action == "hold":
            row = writes.create_hold(params["order_id"], params["product_id"], params["qty"], params["hold_days"],
                                     proposal_id)
        else:
            row = writes.create_assistance_request(params.get("order_id"), params["reason"], proposal_id)
        if "error" in row:
            outcome, reason, row = "escalate", f"write refused by the platform: {row['error']}", None

    must_say, next_step = user_words(outcome, action, facts, row)
    reply_facts = {k: facts[k] for k in ("product_name", "stock", "qty", "hold_days") if k in facts}
    if row and outcome == "approve":
        reply_facts.update({k: row[k] for k in ("new_order_id", "held_until") if k in row})
    decision = {"outcome": outcome, "action": action, "order_id": facts.get("order_id", params.get("order_id")),
                "rule_id": proposal.get("rule_id"), "facts": reply_facts, "must_say": must_say,
                "next_step": next_step, "reason": reason, "proposal_id": proposal_id}
    if outcome == "owner_pending" and row:
        decision["promotion_id"] = row["id"]
    trace.log("coordinator_decision", "coordinator", {**decision, "checked_facts": facts, "case": dict(case)})
    return decision
