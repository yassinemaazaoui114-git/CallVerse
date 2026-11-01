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
  running gets 409 `decision_in_progress`), and the result of a decision is kept for KEEP_SECONDS under its
  `client_id`, so a browser whose response was lost can ask again with the same id and get the recorded result
  instead of running anything. Across processes (this API and the Streamlit app at the same time) the core's own
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


# ---------- decisions ----------

class Decisions:
    """In-flight guard + recorded results per client_id (this process)."""

    def __init__(self):
        self._running: set[int] = set()
        self._results: dict[tuple[str, int, str], tuple[float, dict]] = {}   # (admin, approval id, client id)
        self._lock = threading.Lock()

    def _prune(self) -> None:
        cutoff = time.monotonic() - KEEP_SECONDS
        for key, (at, _) in list(self._results.items()):
            if at < cutoff:
                del self._results[key]

    def recorded(self, admin: str, approval_id: int, client_id: str | None) -> dict | None:
        if not client_id:
            return None
        with self._lock:
            self._prune()
            found = self._results.get((admin, int(approval_id), client_id))
            return found[1] if found else None

    def begin(self, approval_id: int) -> bool:
        with self._lock:
            if int(approval_id) in self._running:
                return False
            self._running.add(int(approval_id))
            return True

    def end(self, admin: str, approval_id: int, client_id: str | None, result: dict) -> None:
        with self._lock:
            self._running.discard(int(approval_id))
            if client_id:
                self._results[(admin, int(approval_id), client_id)] = (time.monotonic(), result)

    def clear(self) -> None:
        with self._lock:
            self._running.clear()
            self._results.clear()


def run_decision(admin: str, approval_id: int, approve: bool, reason: str) -> dict:
    """Call the channel's decide() for ShopNova with the admin's username. Returns its dict as it is."""
    return decide_fn()(int(approval_id), admin, bool(approve), reason, slm_chat_fn=_slm_fn, company=COMPANY)


def classify(out: dict) -> tuple[int, str]:
    """(HTTP status, error code) for a decide() error dict; the words themselves are passed through."""
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
