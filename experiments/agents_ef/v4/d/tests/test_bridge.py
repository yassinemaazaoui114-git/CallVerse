"""Worker D tests: ticket mapping, ticket book, and the independent proposal check vs the simulator's own mask.

    python -m pytest v4/d/tests -q         (from experiments/agents_ef)
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v3.e.env_v3 import EnvV3  # noqa: E402
from v3.e.scenarios_v3 import HELDOUT_FAMILIES, TRAIN_FAMILIES  # noqa: E402
from v4.d import bridge  # noqa: E402
from v4.d.bridge import CapacityState, TicketBook, apply, validate  # noqa: E402


def state_of(env) -> CapacityState:
    return CapacityState(alloc=env.alloc.copy(), t_step=env.t, fallback_on=bool(env.fallback),
                         fallback_steps_used=int(env.kpi["fallback_steps"]), budget_spent=float(env.spent),
                         capacity=int(env.available_capacity()))


def test_every_prototype_reason_has_an_agent_e_queue():
    assert bridge.check_mapping() == []
    assert bridge.E_QUEUE_OF_REASON["damaged_item"] == bridge.URGENT
    assert bridge.prototype_routes()["damaged_item"] == "B"          # prototype: urgent problems go to Agent B


@pytest.mark.parametrize("family", TRAIN_FAMILIES + HELDOUT_FAMILIES)
def test_independent_validator_agrees_with_simulator_mask(family):
    """On real simulator states (random valid play, 13 families), the rule check written from ConfigV3 gives the
    same allowed set as EnvV3.action_mask for all 17 actions, and apply() moves sessions like the simulator."""
    rng = np.random.default_rng(7)
    env = EnvV3()
    env.reset(seed=4242, family=family)
    checked = 0
    for _ in range(96):
        mask = env.action_mask()
        st = state_of(env)
        for a in range(17):
            ok, why = validate(st, a)
            assert ok == bool(mask[a]), (family, env.t, a, why)
            checked += 1
        a = int(rng.choice(np.flatnonzero(mask)))
        if a not in (0, 13, 14):
            expect = apply(st, a, env._load()).alloc
        else:
            expect = st.alloc
        _, _, done, _, _ = env.step(a)
        if a in (15, 16) or 1 <= a <= 12:
            # the simulator may also remove sessions after a capacity failure; compare only when none happened
            if env.alloc.sum() == expect.sum():
                assert np.array_equal(env.alloc, expect), (family, a)
        if done:
            break
    assert checked >= 17 * 90


def test_urgent_minimum_and_budget_are_refused_with_reasons():
    st = CapacityState(alloc=np.array([6, 4, 2, 4]), t_step=10)
    for a in (7, 8, 9):                                   # moves FROM C_urgent (i == 2)
        ok, why = validate(st, a)
        assert not ok and "C_urgent" in why[0]
    full = CapacityState(alloc=np.array([6, 6, 6, 6]), t_step=10, capacity=24)
    assert validate(full, bridge.ACT)[0] is False
    rich = CapacityState(alloc=np.array([4, 3, 2, 5]), t_step=95, budget_spent=1766.0)
    ok, why = validate(rich, bridge.ACT)
    assert not ok and "budget" in why[0]
    assert validate(st, 99) == (False, ["unknown action 99"])
    with pytest.raises(ValueError):
        apply(st, 7, np.ones(4))
    assert np.array_equal(st.alloc, [6, 4, 2, 4])          # input never changed


def test_ticket_book_orders_and_snapshots_like_the_prototype_queue():
    tb = TicketBook()
    tickets = [("T1", "order_status", "low", 0.2, 0.0), ("T2", "damaged_item", "high", 0.9, 1.0),
               ("T3", "damaged_item", "medium", 0.5, 2.0), ("T4", "refund_request", "high", 0.8, 3.0),
               ("T5", "weird_reason", "low", 0.1, 4.0)]
    for tid, reason, lab, sc, t in tickets:
        tb.add({"ticket_id": tid, "main_reason": reason, "priority_label": lab, "priority_score": sc}, t)
    tb.end_step()
    snap = tb.snapshot(5.0, CapacityState())
    assert [len(q["waiting"]) for q in snap["queues"]] == [1, 1, 2, 1]      # unknown reason -> D_availability
    assert snap["queues"][2]["arrivals_last_step"] == 2 and snap["queues"][2]["waiting"][0]["waited_min"] == 4.0
    assert all("text" not in w for q in snap["queues"] for w in q["waiting"])  # aggregate only, no message text
    tb.serve(2, 1)
    assert [w[0] for w in tb.waiting[2]] == ["T3"]                           # high served before medium
