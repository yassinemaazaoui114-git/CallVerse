"""Real-data pipeline checks on a FAKE fixture (made up here; no real customer text is in the repository).

What must hold for any real dataset: no conversation or identical text crosses splits, small language x intent
strata survive, intents never become satisfaction labels, and the simulator only takes what the data supports.
"""

import json
import random

import pytest

from real_data.calibration import env_config
from real_data.prepare_subset import guess_lang, main, parse_rating

EN = ["where is my order {n}", "I want a refund for order {n}", "my parcel {n} arrived damaged",
      "is the blue lamp in stock", "order {n} is late again"]
FR = ["où est ma commande {n}", "je veux un remboursement pour la commande {n}", "mon colis {n} est arrivé abîmé",
      "la lampe bleue est-elle disponible", "la commande {n} est encore en retard"]
WORDS_EN = "today yesterday urgent help asap still waiting again thanks seriously email phone app card gift".split()
WORDS_FR = "aujourd'hui hier urgent aide vite toujours attente encore merci vraiment mail téléphone carte".split()
INTENTS = ["order_status", "refund_request", "damaged_item", "availability", "late_delivery"]


def fake_dataset(tmp_path, n_conv=600, with_rating=False, with_ts=False, dup_rate=0.1):
    rng = random.Random(0)
    rows = []
    for c in range(n_conv):
        fr = rng.random() < 0.3                                  # ~30% French like the 5,600/2,400 subset
        k = rng.choices(range(5), weights=[40, 25, 5, 15, 15])[0]   # imbalanced intents
        for turn in range(rng.randint(1, 3)):
            extra = " ".join(rng.choices(WORDS_FR if fr else WORDS_EN, k=rng.randint(2, 6)))
            text = (FR if fr else EN)[k].format(n=rng.randint(1000, 9999)) + " " + extra
            if rng.random() < dup_rate:
                text = (FR if fr else EN)[k].format(n=1)                 # templated duplicates
            r = {"id": f"m{len(rows)}", "conversation_id": f"c{c}", "text": text, "intent": INTENTS[k],
                 "lang": "fr" if fr else "en"}
            if with_rating:
                r["csat"] = rng.randint(1, 5)
            if with_ts:
                r["created_at"] = f"2026-01-0{1 + c % 7}T{8 + c % 10:02d}:{turn:02d}:00"
            rows.append(r)
    p = tmp_path / "fake.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    return p


def run(tmp_path, data, extra=()):
    out = tmp_path / "out"
    prof = main(["--input", str(data), "--text", "text", "--intent", "intent", "--lang", "lang",
                 "--conv-id", "conversation_id", "--n", "500", "--out", str(out), *extra])
    return prof, out


def test_no_leakage_and_strata_kept(tmp_path):
    prof, out = run(tmp_path, fake_dataset(tmp_path))
    for pair, v in prof["leakage"].items():
        if pair.endswith(("_val", "_test")):
            assert v == {"same_text": 0, "same_conversation": 0}, pair
    for s in ("train", "val", "test"):
        langs = prof["splits"][s]["language"]
        assert "fr" in langs and "en" in langs
    assert len(prof["splits"]["test"]["intent"]) == 5                 # rare 'damaged_item' still in TEST
    assert 400 <= sum(v["n"] for v in prof["splits"].values()) <= 700
    assert prof["exact_duplicates_dropped"] > 0
    assert prof["leakage"]["near_duplicates_removed"]["test"] >= 0
    assert prof["leakage"]["test_near_duplicates_of_train_cos>=0.9"] == 0      # removed before reporting


def test_intents_are_never_satisfaction_labels(tmp_path):
    prof, out = run(tmp_path, fake_dataset(tmp_path))
    assert prof["satisfaction_labels"]["present"] is False
    rows = [json.loads(line) for line in open(out / "test.jsonl")]
    assert all(r["rating"] is None for r in rows)


def test_real_ratings_are_used_when_present(tmp_path):
    prof, _ = run(tmp_path, fake_dataset(tmp_path, with_rating=True), ["--rating", "csat"])
    assert prof["satisfaction_labels"]["present"] and prof["satisfaction_labels"]["n"] > 0


def test_simulator_takes_only_what_the_data_supports(tmp_path):
    _, out = run(tmp_path, fake_dataset(tmp_path))
    cal = json.loads((out / "e_calibration.json").read_text())
    assert isinstance(cal["hourly_arrival_share"], str) and "NOT AVAILABLE" in cal["hourly_arrival_share"]
    assert isinstance(cal["service_min_by_queue"], str)
    base, new = env_config("balanced"), env_config("balanced", str(out / "e_calibration.json"))
    assert sum(new.base_rate) == pytest.approx(sum(base.base_rate), rel=1e-3)   # total load unchanged
    assert new.service_min == base.service_min                                   # no handle times -> unchanged
    assert new.base_rate[0] > new.base_rate[2]            # order_status + late (A) dominate damaged (C)


def test_timestamps_enable_hourly_profile(tmp_path):
    _, out = run(tmp_path, fake_dataset(tmp_path, with_ts=True), ["--timestamp", "created_at"])
    cal = json.loads((out / "e_calibration.json").read_text())
    assert isinstance(cal["hourly_arrival_share"], dict)


def test_helpers():
    assert guess_lang("bonjour, où est ma commande ?") == "fr"
    assert guess_lang("hello, where is my order?") == "en"
    assert parse_rating("4") == 4 and parse_rating("10") == 5 and parse_rating("positive") is None
