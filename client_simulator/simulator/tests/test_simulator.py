"""Unit tests with a mocked Ollama (no GPU needed). Run: python -m pytest simulator/tests -q"""
import json
from pathlib import Path

import pytest

import simulator.core as core
from simulator import apply_calibration, clean_turn, load_role_card, sample_traffic, score_conversation, simulate_turn
from simulator.prompts import breaks_role, roleplay_messages, score_messages

CARDS = Path(core.HERE) / "role_cards"


class FakeResp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._c}}


@pytest.fixture(autouse=True)
def llm_score_mode(monkeypatch):
    """Most tests exercise the LLM scoring path; scorer-mode tests switch it back explicitly."""
    monkeypatch.setitem(core.config()["scoring"], "score_mode", "llm")


@pytest.fixture
def mock_ollama(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "body": json})
        return FakeResp(fake_post.reply)

    fake_post.reply = "hi my order 4512 still hasnt arrived"
    monkeypatch.setattr(core.requests, "post", fake_post)
    return fake_post, calls


def card():
    return load_role_card(CARDS / "shopnova" / "SN-01.yaml")


def test_role_cards_load_and_cover_both_companies():
    for comp in ("shopnova", "atlas"):
        files = sorted((CARDS / comp).glob("*.yaml"))
        assert len(files) >= 10
        for f in files:
            c = load_role_card(f)
            assert c["company"] == comp and c["goal"]


def test_bad_role_card_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("id: X\ncompany: other\ngoal: g\n")
    with pytest.raises(ValueError):
        load_role_card(p)


def test_roleplay_roles_are_flipped():
    hist = [{"role": "customer", "text": "where is my laptop"}, {"role": "agent", "text": "Could you confirm your order number?"}]
    m = roleplay_messages(card(), hist)
    assert m[0]["role"] == "system" and "NOT an assistant" in m[0]["content"]
    assert [x["role"] for x in m[1:]] == ["user", "assistant", "user"]


def test_simulate_turn_calls_ollama_with_config_model(mock_ollama):
    fake, calls = mock_ollama
    out = simulate_turn(card(), [])
    assert out == "hi my order 4512 still hasnt arrived"
    assert calls[0]["url"].endswith("/api/chat")
    assert calls[0]["body"]["model"] == core.config()["model"]
    if core.config()["model"].startswith("qwen3"):
        assert calls[0]["body"]["think"] is False


def test_clean_turn_strips_prefix_quotes_and_agent_lines():
    assert clean_turn('Customer: "where is it?"') == "where is it?"
    assert clean_turn("where is it?\nAgent: let me check") == "where is it?"


def test_score_conversation_parses_and_calibrates(mock_ollama, monkeypatch):
    fake, calls = mock_ollama
    fake.reply = json.dumps({"score": 2, "comment": "took ages and still no laptop"})
    monkeypatch.setattr(core, "_load_json", lambda name: {"map": {"1": 1, "2": 1, "3": 4, "4": 5, "5": 5}}
                        if "calibration" in name else None)
    out = score_conversation(card(), [{"role": "customer", "text": "where is my laptop"},
                                      {"role": "agent", "text": "It is delayed."}])
    assert out["raw_score"] == 2 and out["score"] == 1 and out["valid_json"] and not out["breaks_role"]
    assert out["expected_score"] == 1.0


def test_score_conversation_invalid_json_falls_back(mock_ollama):
    fake, _ = mock_ollama
    fake.reply = "I would say 4 out of 5"
    out = score_conversation(card(), [], calibrate=False)
    assert out["raw_score"] == 4 and out["valid_json"] is False


def test_apply_calibration_identity_without_map():
    assert apply_calibration(3, calibration={}) == 3
    assert apply_calibration(3, calibration={"map": {"3": 4}}) == 4


def test_breaks_role_detects_assistant_phrases():
    assert breaks_role("Thank you for contacting us, how can I help?")
    assert not breaks_role("my parcel is late again")


def test_score_prompt_v2_includes_rubric_and_shots():
    rub = {"lines": ["Out of 100 real customers, 69 give 5"]}
    shots = [{"prompt": "card", "score": 1, "comment": "bad"}]
    m = score_messages("card", None, "v2", rubric=rub, shots=shots)
    assert "69 give 5" in m[0]["content"] and m[2]["role"] == "assistant"


def test_real_numbers_and_traffic_sampling():
    rn = json.loads((core.HERE / "real_numbers.json").read_text(encoding="utf-8"))
    for k in ("reason_mix", "arrivals_share_by_hour", "give_up_rate", "real_score_distribution"):
        assert k in rn and "source" in json.dumps(rn[k])
    t = sample_traffic(50, "atlas", seed=1)
    assert len(t) == 50 and all(0 <= x["hour"] < 24 for x in t)


def test_delay_aware_calibration_uses_wait_bucket():
    cal = {"models": {core.config()["model"]: {
        "map": {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5},
        "delay_aware": {"enabled": True, "bucket_maps": {"8 h+": {"1": 1, "2": 1, "3": 3, "4": 4, "5": 4}}}}}}
    assert apply_calibration(5, calibration=cal, role_card={"wait_minutes": 600}) == 4
    assert apply_calibration(5, calibration=cal, role_card={"wait_minutes": 3}) == 5   # no map for that bucket -> global
    assert apply_calibration(5, calibration=cal) == 5                                  # no wait time -> global


def test_fallback_profile_selects_fallback_files(monkeypatch):
    monkeypatch.setitem(core.config()["scoring"], "calibration_profile", "fallback")
    assert core._profile_files() == ("rubric_fallback.json", "calibration_fallback.json")
    cal = {"models": {core.config()["model"]: {"map": {"1": 1, "2": 1, "3": 4, "4": 5, "5": 5},
           "lateness_aware": {"enabled": True, "bucket_maps": {"8+ days late": {"1": 1, "2": 1, "3": 1, "4": 2, "5": 3}}}}}}
    assert apply_calibration(4, calibration=cal, role_card={"days_late": 10}) == 2
    assert apply_calibration(4, calibration=cal, role_card={}) == 5


def test_shipped_calibration_files_have_both_picks():
    for name in ("calibration.json", "calibration_fallback.json"):
        cal = json.loads((core.HERE / name).read_text(encoding="utf-8"))
        assert {"qwen3.5:4b", "phi4-mini:3.8b"} <= set(cal["models"])
        for m in cal["models"].values():
            assert set(m["map"]) == {"1", "2", "3", "4", "5"}


def test_expected_score_map_is_continuous(mock_ollama, monkeypatch):
    fake, _ = mock_ollama
    fake.reply = json.dumps({"score": 2, "comment": "waited all day"})
    cal = {"models": {core.config()["model"]: {"map": {"1": 1, "2": 1, "3": 3, "4": 5, "5": 5},
           "delay_aware": {"enabled": True, "method": "expected", "bucket_maps": {"8 h+": {"1": 1.0, "2": 2.6, "3": 3.0, "4": 4.9, "5": 5.0}}}}}}
    monkeypatch.setattr(core, "_load_json", lambda name: cal if "calibration" in name else None)
    out = score_conversation(dict(card(), wait_minutes=600), [])
    assert out["expected_score"] == 2.6 and out["score"] == 3


def test_scorer_mode_uses_cpu_scorer_and_writer_comment(mock_ollama, monkeypatch):
    fake, calls = mock_ollama
    fake.reply = "it took too long"
    monkeypatch.setitem(core.config()["scoring"], "score_mode", "scorer")
    monkeypatch.setattr(core, "_SCORER", lambda card, tr: (2.4, 2.61))
    out = score_conversation(dict(card(), wait_minutes=600), [{"role": "customer", "text": "where is my laptop"}])
    assert out["mode"] == "scorer" and out["raw_score"] == 2.4 and out["expected_score"] == 2.61 and out["score"] == 3
    assert out["comment"] == "it took too long" and len(calls) == 1      # only the comment uses the LLM


def test_scorer_text_layout_matches_training():
    from simulator.scorer import scorer_text
    t = scorer_text(dict(card(), wait_minutes=45), [{"role": "customer", "text": "hi"}, {"role": "agent", "text": "hello"}])
    assert t.startswith("[csat] reason: late_delivery | wait/lateness: 30 min-2 h | turns: 1 | U: hi A: hello")


def test_finetuned_prompt_style_uses_compact_card(mock_ollama, monkeypatch):
    fake, calls = mock_ollama
    monkeypatch.setitem(core.config()["roleplay"], "prompt_style", "finetuned")
    simulate_turn(card(), [])
    sys_msg = calls[0]["body"]["messages"][0]["content"]
    assert sys_msg.startswith("You are a customer of ShopNova") and "Write only your next message." in sys_msg


def _replies(seq, calls):
    it = iter(seq)

    def post(url, json=None, timeout=None):
        calls.append(json)
        return FakeResp(next(it))
    return post


def test_empty_reply_is_retried_once(mock_ollama, monkeypatch):
    fake, calls = mock_ollama
    monkeypatch.setattr(core.requests, "post", _replies(["", "my order is late"], calls))
    assert simulate_turn(card(), [], seed=1) == "my order is late" and len(calls) == 2


def test_assistant_style_reply_is_retried(mock_ollama, monkeypatch):
    fake, calls = mock_ollama
    monkeypatch.setattr(core.requests, "post", _replies(["Thank you for contacting us, how can I help?", "where is my laptop"], calls))
    assert simulate_turn(card(), [], seed=1) == "where is my laptop"


def test_meta_lines_are_stripped():
    assert clean_turn("Okay, here's my first message: Hi, where is order 4512?") == "Hi, where is order 4512?"
    assert clean_turn("Here is my reply:\nIt is 4512.") == "It is 4512."
    assert clean_turn("As a customer, I want my refund.") == "I want my refund."
    assert clean_turn("(sighs) still waiting") == "still waiting"


def test_repeated_opener_is_retried(mock_ollama, monkeypatch):
    fake, calls = mock_ollama
    core._OPENERS.clear()
    monkeypatch.setattr(core.requests, "post", _replies(["Are you kidding me, my tv broke", "Are you kidding me, laptop late",
                                                         "my parcel never came"], calls))
    simulate_turn(card(), [], seed=1)
    assert simulate_turn(card(), [], seed=2) == "my parcel never came"
    hist = [{"role": "customer", "text": "x"}, {"role": "agent", "text": "y"}]
    monkeypatch.setattr(core.requests, "post", _replies(["Are you kidding me, still nothing"], calls))
    assert simulate_turn(card(), hist, seed=3).startswith("Are you kidding")   # later turns are not checked


def test_typo_noise_only_when_card_asks_and_text_is_clean(mock_ollama, monkeypatch):
    fake, calls = mock_ollama
    fake.reply = "My laptop delivery is really late and nobody answers."
    monkeypatch.setitem(core.config()["roleplay"], "typo_noise_prob", {"medium": 1.0, "high": 1.0})
    monkeypatch.setitem(core.config()["roleplay"], "typo_lowercase_prob", 1.0)
    angry = dict(card(), typo_level="high")
    out = simulate_turn(angry, [], seed=4)
    assert out != fake.reply and out == out.lower() and not out.endswith(".")
    assert simulate_turn(dict(card(), typo_level="low"), [], seed=4) == fake.reply
    fake.reply = "my laptpo is late"            # already has a typo: unchanged
    assert simulate_turn(angry, [], seed=5) == "my laptpo is late"


def test_typo_noise_is_probabilistic(mock_ollama, monkeypatch):
    fake, _ = mock_ollama
    fake.reply = "My laptop delivery is really late and nobody answers."
    monkeypatch.setitem(core.config()["roleplay"], "typo_noise_prob", {"medium": 0.0, "high": 0.0})
    assert simulate_turn(dict(card(), typo_level="high"), [], seed=4) == fake.reply
