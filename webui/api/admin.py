"""Admin approvals for the API (step 4 ShopNova, step 5 Atlas): the Layer 3 queue, read with the existing
functions and decided with callverse.channels.approvals.decide(approval_id, admin, approve, reason, company=...).
Every function takes the COMPANY (shopnova / atlas); it comes from the route, which took it from the account.

What this module adds is transport only:
- reads: store.approvals(status, company="shopnova") and admin_reads.approval_facts (the same as the Streamlit
  Refund approvals page), shaped for JSON;
- a decision = decide() called with the ADMIN'S USERNAME FROM THE ACCOUNT (never from the browser), the
  company fixed to shopnova (an Atlas approval is "not found"), and the three browser inputs only: approval id,
  approve / refuse, reason. decide() keeps all its own rules (pending check, reason required to refuse, the
  Coordinator's re-check on fresh data, the one transaction, the new customer reply, the unread notice);
- the channel module is imported lazily (it pulls in the pipeline and the LLM layer): a Console-only process
  never loads it;
- duplicate protection in THIS process: one decision at a time per approval id (a second request while one is
  running gets 409 `decision_in_progress`; the recorded-state route shows what is in flight), and the result of a
  decision is kept for KEEP_SECONDS under its `client_id`, bound to admin, company, approval, choice and reason:
  an identical request asked again gets the recorded result, a reused id with other content is refused;
- an UNEXPECTED exception after decide() started is not a refusal: the core may have written part of the
  decision (its transaction, then the approval record, then the customer reply). The route then re-reads the
  evidence with the existing functions (`evidence()`) and answers 500 `decision_uncertain` with the stage
  reached; the browser shows that, never "nothing was done". Across processes (this API and the Streamlit app at the same time) the core's own
  guards decide once: `admin_decide_refund` refuses an already decided proposal inside one SQLite transaction and
  `close_approval` only closes a pending row; the loser gets "already decided", nothing is paid twice.
- the decision's error dict is mapped to HTTP codes; the outcome text passes through as it is.
"""

import threading
import time

from callverse import companies
from callverse.data import admin_reads
from callverse.tickets import store

KEEP_SECONDS = 15 * 60
COMPANY = companies.DEFAULT
ATLAS = "atlas"

_slm_fn = None       # tests / the demo fixture: a fake reply writer (None = the real SLM through Ollama)
_decide_fn = None    # resolved lazily: callverse.channels.approvals.decide


def use_slm_fn(fn) -> None:
    global _slm_fn
    _slm_fn = fn


def decide_fn():
    global _decide_fn
    if _decide_fn is None:
        from callverse.channels import approvals   # lazy on purpose (imports the pipeline + LLM layer)
        _decide_fn = approvals.decide
    return _decide_fn


def use_decide_fn(fn) -> None:
    """Tests only: replace the channel's decide (None = the real one)."""
    global _decide_fn
    _decide_fn = fn


# ---------- reads ----------

def _proposal(company: str, proposal_id) -> dict | None:
    """The proposal row of the company's own data (ShopNova: admin_reads; Atlas: atlas writes.get_proposal)."""
    if not proposal_id:
        return None
    if company == ATLAS:
        from callverse.data.atlas import writes as atlas_writes
        return atlas_writes.get_proposal(proposal_id)
    return admin_reads.proposal(proposal_id)


def _facts(approval: dict, company: str) -> dict:
    """What the admin sees next to an approval, with the same function as the company's Streamlit page."""
    if company == ATLAS:
        from callverse.data.atlas import atlas_app_reads
        return atlas_app_reads.approval_facts(approval)
    return admin_reads.approval_facts(approval["order_id"], approval["proposal_id"])


PROPOSAL_KEYS = ("id", "agent", "action", "params", "rule_id", "facts_used", "user_confirmed", "decision",
                 "decision_reason", "created_at", "decided_at", "confirmed_by_code", "confirmation_reason")


def _with_facts(approval: dict, company: str) -> dict:
    """An approval row + what the admin needs next to it, JSON-safe."""
    proposal = _proposal(company, approval["proposal_id"]) or {}
    return {**approval, "facts": _facts(approval, company),
            "proposal": {k: proposal.get(k) for k in PROPOSAL_KEYS} if proposal else None}


def pending(company: str = COMPANY) -> list[dict]:
    return [_with_facts(a, company) for a in store.approvals("pending", company=company)]


def decided(company: str = COMPANY) -> list[dict]:
    return [_with_facts(a, company) for a in store.approvals(company=company) if a["status"] != "pending"]


def one(approval_id: int, company: str = COMPANY) -> dict | None:
    """One approval of this company with facts, or None (missing or another company's: the same answer)."""
    approval = store.get_approval(approval_id)
    if approval is None or approval["company"] != company:
        return None
    return _with_facts(approval, company)


# ---------- evidence: what a decision has actually written ----------

STAGES = {
    "nothing_written": "No write found: the proposal is undecided, no refund row, the approval is pending.",
    "company_written_approval_pending": "PARTIAL: the company's transaction is committed (proposal decided"
                                        " and, for an approval, the money row written) but the approval record"
                                        " is still pending and the customer was not told.",
    "approval_closed_notification_unconfirmed": "The company's transaction and the approval record are done, but"
                                                " the customer's reply for THIS approval is not confirmed: no"
                                                " decision step of this approval is recorded on the ticket. Check"
                                                " the ticket before telling the customer again.",
    "complete": "Complete: transaction, approval record and the customer reply of this approval are recorded.",
}


def _money_row(approval: dict, company: str) -> dict | None:
    """The money row this approval's proposal wrote, if any: ShopNova = the refund of the order; Atlas = the
    refund OR the compensation of the booking (by the approval's action), matched on the proposal id."""
    if company == ATLAS:
        from callverse.data.atlas import reads as atlas_reads_core
        kind, booking = approval.get("booking_type"), approval["order_id"]
        if not kind:
            return None
        if approval.get("action") == "compensation":
            rows = atlas_reads_core.get_compensations(kind, booking).get("compensations", [])
        else:
            rows = atlas_reads_core.get_refunds(kind, booking).get("refunds", [])
    else:
        from callverse.tools.shopnova_tools import get_refunds
        rows = get_refunds(approval["order_id"]).get("refunds", [])
    return next((r for r in rows if r.get("proposal_id") == approval["proposal_id"]), None)


def evidence(approval_id: int, company: str = COMPANY) -> dict:
    """Re-read, with the existing functions, everything a decision writes: the approval row (store), the proposal
    decision (admin_reads), the refund row of this proposal (shopnova_tools.get_refunds), the ticket, its last
    message and its steps (store). Then name the STAGE the decision reached. Used after an unexpected exception
    and by the recorded-state route, so the browser never has to guess from the approval row alone.

    The customer notification is judged by DURABLE evidence tied to the approval: decide() saves the trace of a
    completed decision as steps of the ticket, among them the `layer3_decision` line carrying this approval's id
    (written only once the reply was saved). Ticket status and the unread flag are NOT used: the customer reading
    the reply or a later message reopening the ticket must not turn a completed decision into "unconfirmed", and
    an unrelated assistant message must not pass for this approval's reply. Without that step the notification is
    reported as UNCONFIRMED, never as missing."""
    approval = store.get_approval(approval_id)
    if approval is None or approval["company"] != company:
        return {"stage": "unknown", "approval": None}
    proposal = _proposal(company, approval["proposal_id"])
    refund = _money_row(approval, company)   # "refund" key kept: the money row (a compensation at Atlas)
    ticket = store.get_ticket(approval["ticket_id"])
    messages = store.messages(approval["ticket_id"]) if ticket else []
    last = messages[-1] if messages else None
    steps = store.steps(approval["ticket_id"]) if ticket else []
    decision_step = next((s for s in steps if s["step"] == "layer3"
                          and s["data"].get("trace_step") == "layer3_decision"
                          and s["data"].get("approval_id") == approval["id"]), None)
    decided_proposal = bool(proposal and proposal.get("decision") is not None)
    closed = approval["status"] != "pending"
    if not decided_proposal and refund is None and not closed:
        stage = "nothing_written"
    elif (decided_proposal or refund is not None) and not closed:
        stage = "company_written_approval_pending"
    elif closed and decision_step is None:
        stage = "approval_closed_notification_unconfirmed"
    else:
        stage = "complete"
    return {"stage": stage, "stage_words": STAGES[stage], "approval": approval, "action": approval.get("action") or "refund",
            "proposal_decision": proposal.get("decision") if proposal else None,
            "refund": refund, "money": refund, "ticket_status": ticket["status"] if ticket else None,
            "notification": "confirmed" if decision_step else "unconfirmed",
            "decision_step_at": decision_step.get("at_real") if decision_step else None,
            "last_message": {"sender": last["sender"], "at_real": last.get("at_real")} if last else None}


# ---------- decisions ----------

class Decisions:
    """In-flight guard + recorded results per client_id (this process).

    A client_id is bound to the whole request: authenticated admin, company, approval id, the choice and the
    normalised reason. The recorded result is returned only for an IDENTICAL request; the same id with another
    choice or reason is refused (it is not a retry). The in-flight entry says what is running, so a browser whose
    answer was lost can see "still processing" instead of guessing."""

    def __init__(self):
        self._running: dict[tuple[str, int], dict] = {}            # (company, approval id) -> {admin, client_id, approve, reason, started_at}
        self._results: dict[tuple, tuple[float, tuple, dict]] = {}   # key -> (at, payload, result)
        self._lock = threading.Lock()

    @staticmethod
    def _key(company: str, admin: str, approval_id: int, client_id: str) -> tuple:
        return (company, admin, int(approval_id), client_id)

    @staticmethod
    def payload(approve: bool, reason: str) -> tuple:
        return (bool(approve), (reason or "").strip())

    def _prune(self) -> None:
        cutoff = time.monotonic() - KEEP_SECONDS
        for key, (at, _, _) in list(self._results.items()):
            if at < cutoff:
                del self._results[key]

    def recorded(self, company: str, admin: str, approval_id: int, client_id: str | None,
                 approve: bool, reason: str) -> tuple[str | None, dict | None]:
        """("same", result) for an identical earlier request, ("mismatch", None) for a reused id with other
        content, (None, None) when the id is new."""
        if not client_id:
            return None, None
        with self._lock:
            self._prune()
            found = self._results.get(self._key(company, admin, approval_id, client_id))
            if found is None:
                return None, None
            _, payload, result = found
            return ("same", result) if payload == self.payload(approve, reason) else ("mismatch", None)

    def in_flight(self, company: str, approval_id: int) -> dict | None:
        with self._lock:
            found = self._running.get((company, int(approval_id)))
            return dict(found) if found else None

    def begin(self, company: str, approval_id: int, info: dict) -> bool:
        with self._lock:
            if (company, int(approval_id)) in self._running:
                return False
            self._running[(company, int(approval_id))] = {**info, "started_at": _now()}
            return True

    def record(self, company: str, admin: str, approval_id: int, client_id: str | None, approve: bool,
               reason: str, result: dict) -> None:
        if client_id:
            with self._lock:
                self._results[self._key(company, admin, approval_id, client_id)] = (
                    time.monotonic(), self.payload(approve, reason), result)

    def end(self, company: str, approval_id: int) -> None:
        with self._lock:
            self._running.pop((company, int(approval_id)), None)

    def clear(self) -> None:
        with self._lock:
            self._running.clear()
            self._results.clear()


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def run_decision(admin: str, approval_id: int, approve: bool, reason: str, company: str = COMPANY) -> dict:
    """Call the channel's decide() for this company with the admin's username. Returns its dict as it is.
    decide() takes Atlas's own path for an Atlas approval (atlas re-check, atlas writes, refund / compensation /
    cancellation): nothing here assumes the action is a refund."""
    return decide_fn()(int(approval_id), admin, bool(approve), reason, slm_chat_fn=_slm_fn, company=company)


def result_view(out: dict) -> dict:
    """The response body of a completed decision (the channel's result, trimmed)."""
    return {"approval": out["approval"], "outcome": out["outcome"], "ticket": out["ticket"],
            "refund": out.get("refund"), "compensation": out.get("compensation"), "reply_source": out.get("reply_source")}


def classify(out: dict) -> tuple[int, str]:
    """(HTTP status, error code) for a decide() error dict: an EXPLICIT refusal by the core, which by its
    contract wrote nothing (the words themselves are passed through)."""
    error = str(out.get("error", ""))
    if out.get("recheck_failed"):
        return 409, "recheck_refused"
    if "not found" in error:
        return 404, "not_found"
    if "already" in error:
        return 409, "already_decided"
    if "reason is required" in error:
        return 400, "reason_required"
    return 409, "write_refused"
