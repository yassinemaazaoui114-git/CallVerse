"""Integration: closed conversation (real prototype trace format) -> Agent F -> quality flags + owner report ->
F->E contract. Uses the real AgentF interface and the held-out M7 corpus when it is present on this machine."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v4.d.fe_contract import aggregate, from_agent_f  # noqa: E402

AEF = Path(__file__).resolve().parents[3]
CORPUS = Path("/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/m7_corpus/test/traces")
DEMO = AEF / "v4" / "f" / "demo_traces"
FV3 = Path("/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3")


@pytest.fixture(scope="module")
def agent_f():
    from v4.f.agent_f import AgentF
    scorer = FV3 / "ckpt" / "tfidf_ridge_tail256"
    return AgentF.load({"scorer": f"tfidf:{scorer}" if scorer.exists() else "none"})


def traces():
    files = sorted(CORPUS.glob("*.jsonl"))[:30] if CORPUS.exists() else []
    return files or sorted(DEMO.glob("*.jsonl"))


def test_closed_conversations_flow_through_agent_f_and_the_gate_stays_closed(agent_f):
    outs = [agent_f.process(p) for p in traces()]
    outs = [o for x in outs for o in (x if isinstance(x, list) else [x])]
    assert outs, "no traces found"
    for o in outs:
        assert o["grade"] in ("ok", "ok_minor", "review", "fail")
        ec = o["evidence_check"]
        assert ec is None or ec["n_ok"] == ec["n_refs"], o["conversation_id"]      # every evidence ref is real
        assert o["e_reward_eligible"]["eligible"] is False                        # no validated labels exist
        if o["satisfaction_validity"]["language"] != "en":
            assert o["predicted_satisfaction"] is None                            # unvalidated language: no score
    recs = [from_agent_f(o, agent_f.card) for o in outs]
    agg = aggregate(recs)
    assert agg["reward"] == {} and len(agg["refusals"]) == len(recs)
    rep = agent_f.owner_report(outs)
    assert "markdown" in rep and rep["json"]


def test_agent_f_never_writes_rules_or_traces(agent_f, tmp_path):
    import hashlib
    pol = AEF.parents[1] / "callverse" / "kb" / "policies_shopnova.json"
    before = hashlib.sha256(pol.read_bytes()).hexdigest()
    files = traces()[:5]
    tr_before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    for p in files:
        agent_f.process(p)
    assert hashlib.sha256(pol.read_bytes()).hexdigest() == before
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in tr_before.items())
