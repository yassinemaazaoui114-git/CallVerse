"""The ShopNova admin's Manage pages (products, orders, clients, refunds, admin log) for the web UI: thin
wrappers around the core's own functions, the same ones the Streamlit Manage page calls.

- reads: callverse.data.admin_reads (products_page, orders_page, users_page, refunds_page, admin_log, the
  option lists);
- writes: callverse.data.writes (create_product, update_product, deactivate_product, reactivate_product,
  admin_set_order_status, create_user, update_user). Every write takes the admin's USERNAME (from the account,
  never from the browser), runs the core's own checks inside one transaction and logs an admin_actions row.
  The core answers {"error": reason} when it refuses: by its contract nothing was written then.

No SQL and no business rule here. The order "moves" offered to the admin are the core's own constants
(seed.STATUS_MOVES, writes.ADMIN_CANCEL_FROM, writes.PAID_CANCEL_MESSAGE), read the way the Streamlit page reads
them; the core checks them again when the write runs.

Duplicate submissions: a browser sends a `client_id` with every write; an identical request with the same id
(same admin, same target, same payload) gets the recorded answer instead of a second write (a "create" twice
would otherwise make two products). The same id with another payload is refused. Records live KEEP_SECONDS.
"""

import threading
import time

from callverse.data import admin_reads, writes
from callverse.data.seed import ORDER_STATUSES, STATUS_MOVES

KEEP_SECONDS = 15 * 60
MAX_RECORDS = 500

# which permission each table needs: the same split as the Streamlit Manage page
TABLE_PERMISSION = {"products": "edit_catalogue", "orders": "edit_orders", "users": "edit_users",
                    "refunds": "view_dashboard", "log": "view_dashboard"}
READERS = {"products": admin_reads.products_page, "orders": admin_reads.orders_page,
           "users": admin_reads.users_page, "refunds": admin_reads.refunds_page}

# the limits the core applies (shown to the browser so its form can check before sending)
LIMITS = {"max_name": writes.MAX_NAME_LEN, "max_price": writes.MAX_PRICE_TND, "max_stock": writes.MAX_STOCK}


# ---------- reads ----------

def page(table: str, search: str, page_no: int) -> dict:
    """One page of a Manage table, as admin_reads pages it ({items, total, page, pages}) + page_size."""
    found = READERS[table](search or "", max(1, int(page_no)))
    if table == "orders":
        found["items"] = [{**row, **order_moves(row)} for row in found["items"]]
    return {"table": table, **found, "page_size": admin_reads.PAGE_SIZE}


def log(limit: int = 50) -> dict:
    rows = admin_reads.admin_log(limit)
    return {"table": "log", "items": rows, "total": len(rows), "page": 1, "pages": 1, "page_size": limit}


def options() -> dict:
    """The option lists of the forms: the shop's categories, the cities served, the order statuses, the limits."""
    return {"categories": admin_reads.product_categories(), "cities": admin_reads.cities(),
            "statuses": list(ORDER_STATUSES), "limits": LIMITS}


def order_moves(order: dict) -> dict:
    """The status moves the admin may ask for on this order, exactly as the Streamlit page lists them: the
    carrier's moves (STATUS_MOVES) plus "cancelled" while the order is not shipped yet AND nothing is paid.
    `cancel_blocked` carries the core's own sentence when the order could be cancelled but is paid."""
    status, paid = order.get("status"), order.get("paid") or 0
    moves = list(STATUS_MOVES.get(status, ()))
    blocked = None
    if status in writes.ADMIN_CANCEL_FROM:
        if paid:
            blocked = writes.PAID_CANCEL_MESSAGE
        else:
            moves.append("cancelled")
    return {"moves": moves, "cancel_blocked": blocked}


def product(product_id: int) -> dict | None:
    return admin_reads.product_row(product_id)


def user(user_id: int) -> dict | None:
    return admin_reads.user_row(user_id)


def order(order_id: int) -> dict | None:
    found = admin_reads.order_row(order_id)
    return {**found, **order_moves(found)} if found else None


# ---------- the core's refusals, as HTTP answers ----------

FIELD_WORDS = ("name", "price", "stock", "category", "email", "phone", "city", "status")


def classify(error: str) -> tuple[int, str, str | None]:
    """(status, code, field) for a core refusal. "not found" is 404; a rule that forbids the change (a move
    that is not allowed, a paid order, already active…) is 409 `refused`; a bad value is 400 `invalid` with
    the field the core's sentence names first (its wording, e.g. "price must be a number above 0 …")."""
    text = (error or "").lower()
    if "not found" in text:
        return 404, "not_found", None
    field = next((f for f in FIELD_WORDS if text.startswith(f) or f" {f} " in f" {text} "[:40]), None)
    if "already used" in text:   # a value another client has (email, phone): a field problem, not a rule
        return 400, "invalid", field
    if any(w in text for w in ("not allowed", "already", "can be cancelled", "never set by hand", "must be refunded",
                               "nothing to change", "cannot be changed")):
        return 409, "refused", None
    return 400, "invalid", field


# ---------- duplicate submissions ----------

class Writes:
    """Recorded answers per (admin, client_id), bound to the target and payload of the request."""

    def __init__(self):
        self._results: dict[tuple, tuple[float, tuple, dict]] = {}
        self._running: set = set()
        self._lock = threading.Lock()

    def _prune(self) -> None:
        cutoff = time.monotonic() - KEEP_SECONDS
        for key, (at, _, _) in list(self._results.items()):
            if at < cutoff:
                del self._results[key]
        while len(self._results) > MAX_RECORDS:
            del self._results[min(self._results, key=lambda k: self._results[k][0])]

    def recorded(self, admin: str, client_id: str | None, payload: tuple) -> tuple[str | None, dict | None]:
        """("same", result) for the identical earlier request, ("mismatch", None) for a reused id with another
        payload, ("running", None) while that request is still in flight, (None, None) when the id is new."""
        if not client_id:
            return None, None
        with self._lock:
            self._prune()
            key = (admin, client_id)
            if key in self._running:
                return "running", None
            found = self._results.get(key)
            if found is None:
                return None, None
            return ("same", found[2]) if found[1] == payload else ("mismatch", None)

    def begin(self, admin: str, client_id: str | None) -> None:
        if client_id:
            with self._lock:
                self._running.add((admin, client_id))

    def end(self, admin: str, client_id: str | None, payload: tuple, result: dict | None) -> None:
        if client_id:
            with self._lock:
                self._running.discard((admin, client_id))
                if result is not None:
                    self._results[(admin, client_id)] = (time.monotonic(), payload, result)


_writes = Writes()


def writes_registry() -> Writes:
    return _writes


def reset_registry() -> None:
    """Tests only."""
    global _writes
    _writes = Writes()


# ---------- the writes themselves ----------

def run(kind: str, admin: str, client_id: str | None, payload: tuple, call) -> dict:
    """Run one core write once per (admin, client_id, payload). `call()` returns the core's dict. Raises
    Refused(status, code, message, field) when the core refuses (nothing written), Duplicate for a reused id."""
    kind_payload = (kind, *payload)
    state, recorded = _writes.recorded(admin, client_id, kind_payload)
    if state == "same":
        return {**recorded, "recorded": True}
    if state == "mismatch":
        raise Duplicate("client_id_reused", "This request id was already used for another change.")
    if state == "running":
        raise Duplicate("write_in_progress", "This change is still being processed. Check the list in a moment.")
    _writes.begin(admin, client_id)
    result = None
    try:
        out = call()
        if "error" in out:
            status, code, field = classify(str(out["error"]))
            raise Refused(status, code, str(out["error"]), field)
        result = {"ok": True, "row": out}
        return result
    finally:
        _writes.end(admin, client_id, kind_payload, result)


class Refused(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field


class Duplicate(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message
