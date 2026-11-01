"""ShopNova admin approvals for the API (step 4): the Layer 3 queue, read with the existing functions and decided
with callverse.channels.approvals.decide(approval_id, admin, approve, reason).

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

def _with_facts(approval: dict) -> dict:
    """An approval row + what the admin needs next to it (admin_reads.approval_facts), JSON-safe."""
    facts = admin_reads.approval_facts(approval["order_id"], approval["proposal_id"])
    proposal = admin_reads.proposal(approval["proposal_id"]) or {}
    return {**approval, "facts": facts,
            "proposal": {k: proposal.get(k) for k in ("id", "agent", "action", "params", "rule_id", "facts_used",
                                                       "user_confirmed", "decision", "decision_reason", "created_at",
                                                       "decided_at")} if proposal else None}


def pending() -> list[dict]:
    return [_with_facts(a) for a in store.approvals("pending", company=COMPANY)]


def decided() -> list[dict]:
    return [_with_facts(a) for a in store.approvals(company=COMPANY) if a["status"] != "pending"]


def one(approval_id: int) -> dict | None:
    """One ShopNova approval with facts, or None (missing or another company's: the same answer)."""
    approval = store.get_approval(approval_id)
    if approval is None or approval["company"] != COMPANY:
        return None
    return _with_facts(approval)


# ---------- evidence: what a decision has actually written ----------

STAGES = {
    "nothing_written": "No write found: the proposal is undecided, no refund row, the approval is pending.",
    "company_written_approval_pending": "PARTIAL: the company's transaction is committed (proposal decided"
                                        " and, for an approval, the refund row written) but the approval record"
                                        " is still pending and the customer was not told.",
    "approval_closed_reply_missing": "PARTIAL: the company's transaction and the approval record are done, but"
                                     " the customer's reply / ticket update is missing.",
    "complete": "Complete: transaction, approval record and customer reply are all recorded.",
}


def evidence(approval_id: int) -> dict:
    """Re-read, with the existing functions, everything a decision writes: the approval row (store), the proposal
    decision (admin_reads), the refund row of this proposal (shopnova_tools.get_refunds), the ticket and its last
    message (store). Then name the STAGE the decision reached. Used after an unexpected exception and by the
    recorded-state route, so the browser never has to guess from the approval row alone."""
    from callverse.tools.shopnova_tools import get_refunds
    approval = store.get_approval(approval_id)
    if approval is None:
        return {"stage": "unknown", "approval": None}
    proposal = admin_reads.proposal(approval["proposal_id"]) if approval["proposal_id"] else None
    refunds = get_refunds(approval["order_id"])
    refund = next((r for r in refunds.get("refunds", []) if r.get("proposal_id") == approval["proposal_id"]), None)
    ticket = store.get_ticket(approval["ticket_id"])
    messages = store.messages(approval["ticket_id"]) if ticket else []
    last = messages[-1] if messages else None
    decided_proposal = bool(proposal and proposal.get("decision") is not None)
    closed = approval["status"] != "pending"
    replied = bool(ticket and ticket["status"] == "Solved" and last and last["sender"] == "assistant"
                   and ticket.get("user_unread") == 1)
    if not decided_proposal and refund is None and not closed:
        stage = "nothing_written"
    elif (decided_proposal or refund is not None) and not closed:
        stage = "company_written_approval_pending"
    elif closed and not replied:
        stage = "approval_closed_reply_missing"
    else:
        stage = "complete"
    return {"stage": stage, "stage_words": STAGES[stage], "approval": approval,
            "proposal_decision": proposal.get("decision") if proposal else None,
            "refund": refund, "ticket_status": ticket["status"] if ticket else None,
            "last_message": {"sender": last["sender"], "at_real": last.get("at_real")} if last else None}


# ---------- decisions ----------

class Decisions:
    """In-flight guard + recorded results per client_id (this process).

    A client_id is bound to the whole request: authenticated admin, company, approval id, the choice and the
    normalised reason. The recorded result is returned only for an IDENTICAL request; the same id with another
    choice or reason is refused (it is not a retry). The in-flight entry says what is running, so a browser whose
    answer was lost can see "still processing" instead of guessing."""

    def __init__(self):
        self._running: dict[int, dict] = {}                        # approval id -> {admin, client_id, approve, reason, started_at}
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

    def in_flight(self, approval_id: int) -> dict | None:
        with self._lock:
            return dict(self._running[int(approval_id)]) if int(approval_id) in self._running else None

    def begin(self, approval_id: int, info: dict) -> bool:
        with self._lock:
            if int(approval_id) in self._running:
                return False
            self._running[int(approval_id)] = {**info, "started_at": _now()}
            return True

    def record(self, company: str, admin: str, approval_id: int, client_id: str | None, approve: bool,
               reason: str, result: dict) -> None:
        if client_id:
            with self._lock:
                self._results[self._key(company, admin, approval_id, client_id)] = (
                    time.monotonic(), self.payload(approve, reason), result)

    def end(self, approval_id: int) -> None:
        with self._lock:
            self._running.pop(int(approval_id), None)

    def clear(self) -> None:
        with self._lock:
            self._running.clear()
            self._results.clear()


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def run_decision(admin: str, approval_id: int, approve: bool, reason: str) -> dict:
    """Call the channel's decide() for ShopNova with the admin's username. Returns its dict as it is."""
    return decide_fn()(int(approval_id), admin, bool(approve), reason, slm_chat_fn=_slm_fn, company=COMPANY)


def result_view(out: dict) -> dict:
    """The response body of a completed decision (the channel's result, trimmed)."""
    return {"approval": out["approval"], "outcome": out["outcome"], "ticket": out["ticket"],
            "refund": out.get("refund"), "reply_source": out.get("reply_source")}


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
