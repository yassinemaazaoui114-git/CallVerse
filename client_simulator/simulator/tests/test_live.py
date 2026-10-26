"""Optional live test against a running Ollama. Run: CALLVERSE_LIVE=1 python -m pytest simulator/tests/test_live.py -q"""
import os
from pathlib import Path

import pytest

from simulator import load_role_card, score_conversation, simulate_turn

pytestmark = pytest.mark.skipif(os.environ.get("CALLVERSE_LIVE") != "1", reason="set CALLVERSE_LIVE=1 to run against Ollama")


def test_live_turn_and_score():
    card = load_role_card(Path(__file__).resolve().parents[1] / "role_cards" / "atlas" / "AT-02.yaml")
    first = simulate_turn(card, [], seed=1)
    assert 2 <= len(first.split()) <= 80
    out = score_conversation(card, [{"role": "customer", "text": first},
                                    {"role": "agent", "text": "Sorry, your flight is delayed by 4 hours. You are owed 250 EUR."}])
    assert 1 <= out["score"] <= 5 and 1 <= out["raw_score"] <= 5


def test_live_cpu_scorer():
    from simulator import core
    if not (core.HERE.parent / core.config()["scorer"]["model_dir"] / "scorer_int8.onnx").exists():
        pytest.skip("scorer weights not present (models/scorer)")
    from simulator.core import _scorer
    card = load_role_card(Path(__file__).resolve().parents[1] / "role_cards" / "shopnova" / "SN-01.yaml")
    raw, exp = _scorer()(dict(card, wait_minutes=3), [{"role": "customer", "text": "thanks, all solved quickly"}])
    raw2, exp2 = _scorer()(dict(card, wait_minutes=900), [{"role": "customer", "text": "worst service, still no laptop"}])
    assert 1 <= exp2 < exp <= 5
