"""Layer 3 stub (finance): decisions by amount, errors, trace, no DB change."""

import json
import sqlite3
from contextlib import closing

import pytest

from callverse import trace
from callverse.data import db
from callverse.data.layer3 import layer3_decide


@pytest.mark.parametrize("amount, decision", [
    (59.90, "not_required"), (300, "not_required"), (350, "approved"),
    (500, "approved"), (500.01, "refused"), (600, "refused"),
])
def test_decisions(amount, decision):
    result = layer3_decide(4512, amount, "test")
    assert result["decision"] == decision
    assert result["rule_id"] == "R-ESC-01" and result["order_id"] == 4512 and result["amount"] == amount
    assert result["by"] == (None if decision == "not_required" else "finance")


def test_errors():
    assert "error" in layer3_decide(4512, 0, "test")
    assert "error" in layer3_decide(4512, -5, "test")
    assert "error" in layer3_decide(9999, 350, "test")


def test_traced_and_no_db_change():
    def snapshot():
        with closing(sqlite3.connect(db.db_path())) as con:
            return [con.execute(f"SELECT * FROM {t}").fetchall() for t in ("orders", "refunds", "events")]
    before = snapshot()
    layer3_decide(4513, 350, "test")
    assert snapshot() == before
    last = json.loads(trace.current_path().read_text(encoding="utf-8").splitlines()[-1])
    assert last["step"] == "layer3_decision" and last["actor"] == "layer3"
