"""The owner's screens for Agent D (T27): ShopNova's Promotions, Atlas's Hotel deals and the "Check now" scan.

Transport only, like admin.py. Every read and every decision calls the EXISTING core functions, the same ones the
Streamlit pages use (apps/shopnova/pages/6_Refund_approvals.py, apps/atlas/pages/4_Approvals.py):
- reads:     callverse.channels.approvals.promotions(status)   /  atlas_deals(status)  (= atlas writes.hotel_deals)
- decisions: callverse.channels.approvals.decide_promotion(...) /  decide_atlas_deal(...)
- scan:      callverse.channels.approvals.run_stock_scan(company)  (= AgentD(...).scan() / scan_atlas())
Nothing here decides anything: the core keeps its own rules (pending check, reason required to refuse, one
transaction, the admin log). What this module adds:
- next to each row, the facts Agent D used (days of cover, sold in 30 days; occupancy, capacity), read from the
  proposal row with the existing readers (admin_reads.proposal / atlas writes.get_proposal);
- the double-click guard of admin.py (admin.Decisions): one decision at a time per row, and an identical request
  sent again with the same client_id gets the recorded answer instead of a second run;
- one scan at a time per company (a second click while a scan runs gets 409 scan_in_progress).
The channel module is imported lazily (it pulls in the pipeline): a Console-only process never loads it.
"""

import threading

ATLAS = "atlas"
SHOPNOVA = "shopnova"

# The keys the Decisions guard is given instead of a company: a promotion id and an approval id never share a slot.
PROMOTION_SLOT = "shopnova:promotion"
DEAL_SLOT = "atlas:hotel_deal"


def _channel():
    from callverse.channels import approvals   # lazy on purpose (imports the pipeline + LLM layer)
    return approvals


# ---------- reads ----------

def _shop_proposal(proposal_id) -> dict:
    from callverse.data import admin_reads
    return (admin_reads.proposal(proposal_id) if proposal_id else None) or {}


def _atlas_proposal(proposal_id) -> dict:
    from callverse.data.atlas import writes as atlas_writes
    return (atlas_writes.get_proposal(proposal_id) if proposal_id else None) or {}


def _promotion_view(row: dict) -> dict:
    """A promotions row + Agent D's facts (stock and demand when it proposed), JSON-safe."""
    facts = _shop_proposal(row.get("proposal_id")).get("facts_used") or {}
    return {**row, "facts": {k: facts.get(k) for k in ("stock", "units_sold_30d", "days_of_cover")}}


def _deal_view(row: dict) -> dict:
    """A hotel_deals row + Agent D's facts (capacity, lowest occupancy) and the first / last night."""
    facts = _atlas_proposal(row.get("proposal_id")).get("facts_used") or {}
    nights = sorted(row.get("nights") or [])
    return {**row, "facts": {k: facts.get(k) for k in ("capacity", "min_occupancy_pct")},
            "first_night": nights[0] if nights else None, "last_night": nights[-1] if nights else None}


def promotions(status: str) -> list[dict]:
    """status "pending" or "decided" (everything not pending), newest decisions first (the core's order)."""
    if status == "pending":
        rows = _channel().promotions("pending")
    else:
        rows = [p for p in _channel().promotions() if p["status"] != "pending"]
    return [_promotion_view(r) for r in rows]


def deals(status: str) -> list[dict]:
    if status == "pending":
        rows = _channel().atlas_deals("pending")
    else:
        rows = [d for d in _channel().atlas_deals() if d["status"] != "pending"]
    return [_deal_view(r) for r in rows]


def one_promotion(promotion_id: int) -> dict | None:
    found = next((p for p in _channel().promotions() if p["id"] == int(promotion_id)), None)
    return _promotion_view(found) if found else None


def one_deal(deal_id: int) -> dict | None:
    found = next((d for d in _channel().atlas_deals() if d["id"] == int(deal_id)), None)
    return _deal_view(found) if found else None


# ---------- decisions ----------

def decide_promotion(admin: str, promotion_id: int, approve: bool, reason: str) -> dict:
    """The core's decision (writes.admin_decide_promotion in one transaction). The promotion row or {"error"}."""
    return _channel().decide_promotion(int(promotion_id), admin, bool(approve), reason)


def decide_deal(admin: str, deal_id: int, approve: bool, reason: str) -> dict:
    return _channel().decide_atlas_deal(int(deal_id), admin, bool(approve), reason)


def classify(out: dict) -> tuple[int, str]:
    """(HTTP status, error code) for a refusal by the core (its words are passed through)."""
    error = str(out.get("error", ""))
    if "not found" in error:
        return 404, "not_found"
    if "already" in error:
        return 409, "already_decided"
    if "reason is required" in error:
        return 400, "reason_required"
    return 409, "write_refused"


# ---------- Check now ----------

class Scans:
    """One Agent D scan at a time per company (this process). A scan writes proposals, so two at once could
    propose the same promotion twice; the core refuses a second open deal / promotion anyway, this keeps it clean."""

    def __init__(self):
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def begin(self, company: str) -> bool:
        with self._lock:
            if company in self._running:
                return False
            self._running.add(company)
            return True

    def end(self, company: str) -> None:
        with self._lock:
            self._running.discard(company)


_scan_fn = None   # tests: a fake scan (None = the real one)


def use_scan_fn(fn) -> None:
    global _scan_fn
    _scan_fn = fn


def run_scan(company: str) -> dict:
    """Agent D's scan once (template wording, no model), as counts: the same function as the Streamlit button.
    ShopNova: {short, over, proposed}; Atlas: {overbooked, low, proposed}."""
    if _scan_fn is not None:
        return _scan_fn(company)
    return _channel().run_stock_scan(company)
