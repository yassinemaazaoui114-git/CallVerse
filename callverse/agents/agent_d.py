"""Agent D - Availability & Supply (P20, official spec).

D compares stock with demand. It is RULES, not an LLM with tools, because every decision it makes is a comparison
of two numbers, and a rule gives the same answer every time and can be shown to the teacher:
    demand        = units sold in the last 30 days (stock_tools.units_sold)
    days_of_cover = stock / (units sold per day)
    shortage      = rule R-STK-01's condition  (stock <= 5 or days_of_cover < 14)
    overstock     = rule R-PRM-01's condition  (stock >= 50 and days_of_cover > 180)
The model is used for ONE thing only: the wording of the note to the owner. If the model fails, or its sentence
loses one of the numbers, a fixed template is used. The numbers never come from the model.

What D does with a finding:
- shortage -> it WARNS Agent A: shortage_note(order) gives one line for the ticket note of an order that holds a
  short product (pipeline.py adds it, traced as "stock_warning"). It changes nothing.
- overstock -> a promotion PROPOSAL (rule R-PRM-01, DEFAULT_DISCOUNT_PCT) for the Coordinator. The Coordinator
  re-checks it and stores it as "pending": the OWNER approves or refuses it (approvals page). D never changes a price.
"""

from callverse import llm, trace
from callverse.coordinator import coordinator
from callverse.tools.proposal_tools import promotion_proposal
from callverse.tools.stock_tools import stock_facts, stock_report

DEFAULT_DISCOUNT_PCT = 10        # within R-PRM-01's limit (at most 20 %)
MAX_PROMOTIONS_PER_SCAN = 3      # the owner gets a short list, not hundreds of products

WORDING_PROMPT = ("You write ONE short sentence for the owner of an online shop. Use exactly these numbers and add "
                  "no other number: product \"{name}\", {stock} units in stock, {sold} sold in the last 30 days, "
                  "proposed promotion {discount}%. Plain text, no Markdown.")


def template_note(f: dict, discount: float) -> str:
    return (f"{f['name']}: {f['stock']} units in stock and {f['units_sold_30d']} sold in the last 30 days, "
            f"so a {discount:g}% promotion is proposed.")


def word_note(f: dict, discount: float, chat_fn=None) -> tuple[str, str]:
    """(note for the owner, "model" or "template"). The model only words it; its numbers are checked."""
    chat = chat_fn or llm.chat
    try:
        reply = chat("agent_d", [{"role": "user", "content": WORDING_PROMPT.format(
            name=f["name"], stock=f["stock"], sold=f["units_sold_30d"], discount=f"{discount:g}")}])
        text = (reply.content or "").strip().replace("*", "")
    except Exception as e:   # no model reachable: the template is enough
        trace.log("agent_d_wording_failed", "agent_D", {"error": f"{type(e).__name__}: {e}"})
        text = ""
    needed = [str(f["stock"]), str(f["units_sold_30d"]), f"{discount:g}"]
    if text and len(text) <= 300 and all(n in text for n in needed):
        return text, "model"
    return template_note(f, discount), "template"


class AgentD:
    agent_id = "D"
    name = "Agent D - Availability & Supply"

    def __init__(self, chat_fn=None, use_model: bool = True, company: str = "shopnova"):
        self.chat = chat_fn
        self.use_model = use_model   # False = template wording only (no model call at all)
        self.company = company       # P20: "atlas" = hotel rooms instead of product stock (scan_atlas)

    def scan(self, propose: bool = True, case_id: str = "agent_d_scan") -> dict:
        """Compare stock with demand for every product. Returns {shortages, overstock, proposals, decisions}.
        propose=False only lists the findings (nothing is sent to the Coordinator)."""
        if self.company == "atlas":
            return self.scan_atlas(propose, case_id)
        report = stock_report()
        shortages = [f for f in report if f["shortage"]]
        overstock = sorted((f for f in report if f["overstock"]), key=lambda f: (-f["stock"], f["product_id"]))
        trace.log("agent_d_scan", "agent_D", {"products": len(report), "shortages": len(shortages),
                                              "overstock": len(overstock)})
        proposals, decisions = [], []
        if propose:
            for f in overstock[:MAX_PROMOTIONS_PER_SCAN]:
                case = coordinator.new_case(f"{case_id}_{f['product_id']}")   # one case per product: independent
                if self.use_model:
                    note, source = word_note(f, DEFAULT_DISCOUNT_PCT, self.chat)
                else:
                    note, source = template_note(f, DEFAULT_DISCOUNT_PCT), "template"
                facts = {k: f[k] for k in ("stock", "units_sold_30d", "days_of_cover")}
                proposal = promotion_proposal(f["product_id"], DEFAULT_DISCOUNT_PCT, facts, note)
                trace.log("proposal", "agent_D", {**proposal, "note_source": source})
                proposals.append(proposal)
                decisions.append(coordinator.review(proposal, case))
        return {"shortages": shortages, "overstock": overstock, "proposals": proposals, "decisions": decisions}


    def scan_atlas(self, propose: bool = True, case_id: str = "agent_d_atlas_scan") -> dict:
        """Atlas: compare the rooms booked on the coming nights with each hotel's capacity (derived from the data,
        tools/capacity_tools.py). Overbooking risk (AT-CAP-01) -> a warning for Agent A (atlas_overbooking_note);
        nights at 30 % or less (AT-DEAL-01) -> a deal PROPOSAL that waits for the owner. Template wording only."""
        from callverse.coordinator import atlas_coordinator
        from callverse.tools.capacity_tools import hotel_capacity_report
        report = hotel_capacity_report()
        overbooked = [h for h in report if h["overbooked_nights"]]
        low = [h for h in report if h["low_nights"]]
        trace.log("agent_d_scan", "agent_D", {"company": "atlas", "hotels": len(report), "overbooked": len(overbooked),
                                              "low_occupancy": len(low)})
        proposals, decisions = [], []
        if propose:
            for h in low:
                note = (f"{h['name']}: {len(h['low_nights'])} coming nights at 30% occupancy or less (lowest "
                        f"{h['min_occupancy_pct']:g}% of {h['capacity']} rooms), so a {DEFAULT_DISCOUNT_PCT}% deal is proposed.")
                proposal = {"agent": "D", "action": "hotel_deal",
                            "params": {"hotel_id": h["hotel_id"], "discount_pct": DEFAULT_DISCOUNT_PCT},
                            "rule_id": "AT-DEAL-01", "facts_used": {k: h[k] for k in ("capacity", "min_occupancy_pct")},
                            "user_confirmed": False, "user_quote": "", "note": note}
                trace.log("proposal", "agent_D", {**proposal, "note_source": "template"})
                proposals.append(proposal)
                case = {**coordinator.new_case(f"{case_id}_{h['hotel_id']}"), "booking_type": "hotel"}
                decisions.append(atlas_coordinator.review(proposal, case))
        return {"overbooked": overbooked, "low_occupancy": low, "proposals": proposals, "decisions": decisions,
                "shortages": [], "overstock": []}


def atlas_overbooking_note(booking: dict) -> str | None:
    """D's warning for Agent A about an Atlas hotel booking whose stay has a night at risk of overbooking (AT-CAP-01)."""
    from datetime import date, timedelta
    from callverse.tools.capacity_tools import hotel_facts
    if not isinstance(booking, dict) or "error" in booking or "hotel_id" not in booking:
        return None
    h = hotel_facts(booking["hotel_id"])
    if "error" in h or not h["overbooked_nights"]:
        return None
    first = date.fromisoformat(booking["arrival_date"])
    stay = {(first + timedelta(days=i)).isoformat() for i in range(int(booking["nights"]))}
    risky = sorted(stay & set(h["overbooked_nights"]))
    if not risky:
        return None
    return (f"[Agent D: overbooking risk (rule AT-CAP-01) at {h['name']} on {', '.join(risky)}: more rooms booked than "
            f"its {h['capacity']} rooms. Do not promise the room.]")


def availability(product_id, qty=1) -> dict:
    """Link (4) "C asks D: is it available?": D's answer from its stock rules (no model).
    {product_id, name, stock, qty, available, shortage, units_sold_30d} or {"error": ...}."""
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        return {"error": "qty must be a whole number of 1 or more"}
    f = stock_facts(product_id)
    if "error" in f:
        return f
    return {"agent": "D", "product_id": f["product_id"], "name": f["name"], "stock": f["stock"], "qty": qty,
            "available": f["active"] and f["stock"] >= qty, "shortage": f["shortage"],
            "units_sold_30d": f["units_sold_30d"]}


def shortage_note(order: dict) -> str | None:
    """D's warning for Agent A about an order: one line naming each product of the order that is short, else None."""
    if not isinstance(order, dict) or "error" in order:
        return None
    short = []
    for item in order.get("items") or []:
        pid = item.get("product_id")
        f = stock_facts(pid) if isinstance(pid, int) else {"error": "no id"}
        if "error" not in f and f["shortage"]:
            short.append(f"{f['name']} (product {pid}) has only {f['stock']} left")
    if not short:
        return None
    return "[Agent D: low stock (rule R-STK-01): " + "; ".join(short) + ". Do not promise a new unit.]"
