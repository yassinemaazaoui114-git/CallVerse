"""Style RL pipeline: writer, simulator, bandit, hardened verifier, end-to-end. Simulated feedback only."""
import random

import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from callverse.data.atlas.seed import seed as seed_atlas
from callverse.learning import simulator as sim
from callverse.learning.style_policy import StylePolicy, group_key, rule_based
from callverse.learning.style_writer import STYLES, write
from callverse.quality.reward import check_correctness, evaluate_response, verify_facts
from callverse.slm.check import check_reply

TEXTS = ["terrible awful broken refund now", "bad slow not happy", "ok fine average",
         "good nice works", "excellent perfect love it thank you"] * 4
MODEL = make_pipeline(TfidfVectorizer(), LogisticRegression(max_iter=500)).fit(TEXTS, [1, 2, 3, 4, 5] * 4)
KW = {"model": MODEL, "stacker": False}


@pytest.fixture(scope="module")
def situations():
    seed_atlas()                      # ShopNova is seeded per test by conftest; Atlas here
    return sim.make_situations()


def test_every_style_passes_the_rule_check(situations):
    for s in situations:
        for st in STYLES:
            r = write(s["decision"], st)
            assert check_reply(r, s["decision"])["passed"], (s["scenario_id"], st, check_reply(r, s["decision"]))
    assert write(situations[0]["decision"], "apology_first").startswith("I am sorry")
    assert "Next step:" in write(situations[0]["decision"], "apology_next_step")
    with pytest.raises(ValueError):
        write(situations[0]["decision"], "shouty")


def test_persona_sets_are_disjoint_and_seeded():
    a, b = sim.make_personas(5, 101, "train"), sim.make_personas(5, 303, "eval")
    assert {p["id"] for p in a}.isdisjoint({p["id"] for p in b})
    assert sim.make_personas(5, 101, "train") == a
    assert all(p["source"] == "simulated" for p in a)


def test_simulator_feedback_is_sensitive(situations):
    rng = random.Random(0)
    personas = sim.make_personas(6, 101, "t")
    clean = [sim.record_for(s, p, "short", None, rng)["rating"] for s in situations for p in personas]
    wrong = [sim.record_for(s, p, "short", "unapproved_refund", rng)["rating"] for s in situations for p in personas]
    assert sum(clean) / len(clean) > sum(wrong) / len(wrong) + 0.5
    upset = [p for p in sim.make_personas(30, 7, "u") if p["emotion"] in sim.UPSET]
    sorry = [sim.record_for(situations[0], p, "apology_first", None, rng)["rating"] for p in upset]
    short = [sim.record_for(situations[0], p, "short", None, rng)["rating"] for p in upset]
    assert sum(sorry) > sum(short)
    rec = sim.record_for(situations[0], personas[0], "short", None, rng)
    assert rec["source"] == "simulated" and 1 <= rec["rating"] <= 5 and rec["messages"][1]["role"] == "assistant"


def test_bandit_updates_persist_and_learn(tmp_path):
    pol = StylePolicy(seed=1)
    sit = {"company": "shopnova", "emotion": "anger", "outcome": "approve", "days_late": 6}
    assert pol.choose(sit) in STYLES
    pol.update(sit, "short", None)
    assert pol.n_updates == 0                      # UNKNOWN reward is not learned from
    rng = random.Random(0)
    for _ in range(300):                           # toy world: apology_first wins for this group
        st = pol.choose(sit)
        pol.update(sit, st, 1 if (st == "apology_first") == (rng.random() < 0.8) else -1)
    assert pol.best(sit) == "apology_first"
    pol.save(tmp_path / "p.json")
    again = StylePolicy.load(tmp_path / "p.json")
    assert again.best(sit) == "apology_first" and again.n_updates == pol.n_updates
    assert group_key(sit) == "shopnova|upset|approve|late"
    assert rule_based(sit) == "apology_first" and rule_based({"emotion": "joy"}) == "short"
    assert StylePolicy(seed=3).choose(sit) == StylePolicy(seed=3).choose(sit)


def _rec(decision, reply, company="shopnova", emotion="neutral"):
    return {"ticket_id": "T", "company": company, "style": "short", "situation": {"emotion": emotion},
            "messages": [{"role": "user", "text": "ok fine"}, {"role": "assistant", "text": reply}], "decision": decision}


def test_connector_verification_distinguishes_trusted_from_verified(situations):
    good = next(s for s in situations if s["decision"]["rule_id"] == "R-REF-03")["decision"]
    rec = _rec(good, write(good, "short"))
    assert verify_facts(rec)["status"] == "verified"
    assert check_correctness(rec)["status"] == "PASS"
    lie = {**good, "facts": {**good["facts"], "days_late": 9}}            # record says 9, connector says 6
    assert verify_facts(_rec(lie, write(lie, "short")))["status"] == "mismatch"
    assert check_correctness(_rec(lie, write(lie, "short")))["status"] == "FAIL"
    too_much = {**good, "facts": {**good["facts"], "amount_tnd": 500.0, "amount": 500.0},
                "must_say": ["Your refund of 500.00 TND is approved."]}
    out = check_correctness(_rec(too_much, write(too_much, "short")))
    assert out["status"] == "FAIL" and any("exceeds payable" in e for e in out["evidence"])
    ghost = {**good, "order_id": 9999}
    assert check_correctness(_rec(ghost, write(ghost, "short")))["status"] == "FAIL"
    nowhere = _rec({**good, "company": "nova"}, write(good, "short"), company="nova")   # no connector -> UNKNOWN, never PASS
    assert check_correctness(nowhere)["status"] == "UNKNOWN"


def test_wrong_booking_fact_fails(situations):
    d = next(s for s in situations if s["decision"]["rule_id"] == "AT-HOT-02")["decision"]
    assert check_correctness(_rec(d, write(d, "short"), company="atlas"))["status"] == "PASS"
    wrong = {**d, "facts": {**d["facts"], "deposit_type": "no_deposit"}}
    out = check_correctness(_rec(wrong, write(wrong, "short"), company="atlas"))
    assert out["status"] == "FAIL" and any("deposit_type" in e for e in out["evidence"])


def test_fabricated_action_and_delivery_promise_fail(situations):
    d = next(s for s in situations if s["reason"] == "order_status" and s["decision"]["outcome"] == "info")["decision"]
    base = write(d, "short")
    for kind in sim.CORRUPTIONS:
        out = check_correctness(_rec(d, sim.corrupt(base, d, kind)))
        assert out["status"] == "FAIL", (kind, out)
    out = evaluate_response(_rec(d, sim.corrupt(base, d, "fabricated_action"), emotion="joy"), **KW)
    assert out["reward"] == -1


def test_end_to_end_episode(situations):
    personas, rng, pol = sim.make_personas(2, 303, "e2e"), random.Random(0), StylePolicy(seed=0)
    seen = set()
    for s in situations[:12]:
        probe = sim.record_for(s, personas[0], "short", None, rng)
        style = pol.choose(probe["situation"])
        rec = sim.record_for(s, personas[0], style, None, rng)
        out = evaluate_response(rec, **KW)
        assert set(out) == {"satisfaction", "correctness", "reward", "train", "evidence"}
        assert out["correctness"] == "PASS" and out["reward"] in (1, -1)
        pol.update(rec["situation"], style, out["reward"])
        seen.add(out["reward"])
    assert pol.n_updates == 12
