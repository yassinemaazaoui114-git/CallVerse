"""Integration: incoming structured ticket (REAL Intake output) -> queue statistics -> Agent E RL proposal ->
independent safety validation (Worker D rules, not E's mask) -> simulated resource update. Plus one closed-loop
simulated day: every proposal of the adapter must pass the independent check, and queue C never drops below 2."""

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v3.e.env_v3 import EnvV3  # noqa: E402
from v4.d.bridge import URGENT, CapacityState, TicketBook, apply, validate  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "intake_tickets.json"


RL_RUN = "dueling_double_dqn_equal_h64x64_150k_s0"          # a trained, hash-recorded V3 RL policy


@pytest.fixture(scope="module")
def adapter():
    from v4.e.adapter import AgentEAdapter
    ad = AgentEAdapter.load(RL_RUN, shield_target=None)
    assert ad.agent is not None, ad.info                     # the RL network really loaded
    return ad


def test_missing_checkpoint_falls_back_to_classical_rule_with_a_reason():
    from v4.e.adapter import AgentEAdapter
    tb = TicketBook()
    tb.end_step()
    prop = AgentEAdapter.load("no_such_run_xyz", shield_target=None).propose(tb.snapshot(0.0, CapacityState()))
    assert prop["policy"].startswith("backup:") and prop["fallback_reason"]


def test_real_intake_tickets_to_rl_proposal_to_validated_update(adapter):
    tickets = json.loads(FIX.read_text())["tickets"]
    tb = TicketBook()
    for k, t in enumerate(tickets):                       # 12 tickets arrive over the first two steps
        tb.add(t, arrived_min=k * 0.8)
    tb.end_step()
    state = CapacityState(alloc=np.array([5, 3, 2, 6]), t_step=2, budget_spent=32.0)
    snap = tb.snapshot(now_min=10.0, state=state)
    frozen = copy.deepcopy(snap)
    prop = adapter.propose(snap)
    assert snap == frozen                                  # the adapter never mutates its input
    for k in ("action_id", "action", "policy", "mask", "safety_veto", "audit"):
        assert k in prop
    assert prop["policy"].startswith("rl") or "dueling" in prop["policy"], prop["policy"]
    assert prop["fallback_reason"] is None and prop["q_values"] is not None
    assert prop["audit"]["model_sha256"] and prop["audit"]["latency_ms"] < 200
    ok, why = validate(state, prop["action_id"])
    assert ok, why                                         # independently valid
    load = np.array([len(q["waiting"]) + q["ewma_arrivals"] for q in snap["queues"]], float)
    new = apply(state, prop["action_id"], load)
    assert new.alloc[URGENT] >= 2 and new.alloc.sum() <= state.capacity
    assert np.array_equal(state.alloc, [5, 3, 2, 6])       # the update is a copy


@pytest.mark.parametrize("family", ["tracking_spike", "severe_overload", "combined_shock"])
def test_closed_loop_day_every_proposal_passes_independent_check(adapter, family):
    from v4.e.adapter import snapshot_from_env
    env = EnvV3()
    env.reset(seed=777_001, family=family)                 # not a manifest seed of V3 VAL/TEST
    done, refused, vetoes = False, 0, 0
    while not done:
        st = CapacityState(alloc=env.alloc.copy(), t_step=env.t, fallback_on=bool(env.fallback),
                           fallback_steps_used=int(env.kpi["fallback_steps"]), budget_spent=float(env.spent),
                           capacity=int(env.available_capacity()))
        prop = adapter.propose(snapshot_from_env(env))
        ok, why = validate(st, prop["action_id"])
        refused += not ok
        vetoes += bool(prop["safety_veto"])
        _, _, done, _, _ = env.step(prop["action_id"] if ok else 0)
        assert env.alloc[URGENT] >= 2
    k = env.kpis()
    assert refused == 0 and k["invalid_proposals"] == 0 and k["high_on_fallback"] == 0
    assert k["budget_ok"]
