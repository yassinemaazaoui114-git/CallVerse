"""INTERIM router: used only while callverse/queues/router.py (task T04, Yassine's lane) does not exist.

It applies exactly the rules already APPROVED in tasks/T04_pipeline_router.md, nothing more:
  - main reason by precedence: damaged_item > refund_request > return_item > late_delivery > order_status > other
  - order_status -> A, late_delivery -> A, refund_request -> B, return_item -> B, damaged_item -> B, other -> A
  - layer L1 for A and B.
The rules are copied here (not in config.yaml) on purpose: T04 will put them in config.yaml under `queues`, and
this file is then no longer used (components.get("router") finds the real one). Every decision is traced.
"""

from callverse import trace

MAIN_REASON_ORDER = ["damaged_item", "refund_request", "return_item", "late_delivery", "order_status", "other"]
ROUTES = {"order_status": "A", "late_delivery": "A", "refund_request": "B",
          "return_item": "B", "damaged_item": "B", "other": "A"}


def main_reason(ticket: dict) -> str:
    """The first reason of MAIN_REASON_ORDER found in the ticket (T04 rule 1)."""
    found = {r["reason"] for r in ticket.get("reasons", [])} or {ticket.get("main_reason", "other")}
    return next((r for r in MAIN_REASON_ORDER if r in found), "other")


def route(ticket: dict) -> dict:
    reason = main_reason(ticket)
    decision = {"agent": ROUTES[reason], "layer": "L1", "reason": reason,
                "priority_label": ticket.get("priority_label"), "router": "interim (T04 rules)"}
    trace.log("route", "router_interim", {"ticket_id": ticket.get("ticket_id"), **decision})
    return decision
