"""T30 (RL5): the style policy (bandit), the style_log table, the reward sources and the pipeline switch.

Every reward in this file is SYNTHETIC (a made-up world), except where a test builds a fake rating sheet.
"""

import json
import random
import zipfile

import pytest

from callverse import pipeline, trace
from callverse.config import load_config
from callverse.learning import rewards, style_policy
from callverse.learning.style_policy import MIN_OBS, STYLES, StylePolicy, group_of
from callverse.tickets import store

ANGRY = {"company": "shopnova", "outcome": "info", "emotion": "anger", "sentiment": "negative"}
CALM = {"company": "shopnova", "outcome": "info", "emotion": "neutral", "sentiment": "neutral"}


@pytest.fixture
def tickets_db(tmp_path):
    store.use_db(tmp_path / "callverse_test.db")
    yield
    store.use_db(store.DEFAULT_DB_PATH)


def events(step):
    return [json.loads(x)["data"] for x in trace.current_path().read_text(encoding="utf-8").splitlines()
            if json.loads(x)["step"] == step]


# --- step 2: the policy -----------------------------------------------------------------------------------------

def test_group_key_is_coarse():
    assert group_of(ANGRY) == "shopnova|info|angry"
    assert group_of(CALM) == "shopnova|info|other"
    assert group_of({"company": "atlas", "outcome": "ask_proof", "emotion": "sadness"}) == "atlas|ask|other"
    assert group_of({"company": "atlas", "outcome": "escalate"}) == "atlas|other|other"
    # a negative sentiment alone is not "angry" (almost every complaint has one)
    assert group_of({"company": "shopnova", "outcome": "decline", "emotion": "sadness", "sentiment": "negative"}) == \
        "shopnova|decline|other"
    assert group_of({"company": "shopnova", "outcome": "decline", "emotion": "disgust"}) == "shopnova|decline|angry"


def test_explores_every_style_before_min_obs():
    policy, rng = StylePolicy(), random.Random(1)
    seen = []
    for _ in range(3):
        style = policy.choose(CALM, rng)
        seen.append(style)
        policy.update(CALM, style, 0.0)
    assert sorted(seen) == sorted(STYLES)   # least-tried first: each style once
    assert policy.observations(group_of(CALM)) == 3 < MIN_OBS


def test_converges_on_the_synthetic_world():
    """SYNTHETIC reward: warm is best for angry users, short for calm ones."""
    policy, rng = StylePolicy(), random.Random(7)
    for _ in range(400):
        for sit in (ANGRY, CALM):
            style = policy.choose(sit, rng)
            policy.update(sit, style, rewards.synthetic(sit, style, rng))
    assert policy.best(ANGRY) == "warm"
    assert policy.best(CALM) == "short"
    late = [policy.choose(ANGRY, rng) for _ in range(200)]
    assert late.count("warm") > 120   # mostly exploits the best style now


def test_seedable():
    def run(seed):
        policy, rng = StylePolicy(), random.Random(seed)
        out = []
        for _ in range(50):
            s = policy.choose(ANGRY, rng)
            policy.update(ANGRY, s, rewards.synthetic(ANGRY, s, rng))
            out.append(s)
        return out
    assert run(3) == run(3)


def test_default_style_without_data_and_bad_inputs():
    policy = StylePolicy()
    assert policy.best(CALM) == style_policy.DEFAULT_STYLE
    with pytest.raises(ValueError):
        policy.update(CALM, "rude", 1.0)
    with pytest.raises(ValueError):
        policy.update(CALM, "short", 4.0)   # rewards are 0..1


def test_save_and_load(tmp_path):
    policy = StylePolicy(tmp_path / "p.json")
    policy.update(CALM, "short", 1.0)
    policy.save()
    again = StylePolicy.load(tmp_path / "p.json")
    assert again.stats == policy.stats
    assert again.best_per_group()["shopnova|info|other"]["mean"]["short"] == 1.0
    assert StylePolicy.load(tmp_path / "missing.json").stats == {}


def test_flat_world_does_not_break():
    """SYNTHETIC world where all styles are equal: no crash, every style still tried, no reward lost.
    Note: Thompson sampling is NOT uniform here: a style with bad early luck is tried less (the T30 report says so).
    That costs nothing in this world, because every style has the same reward."""
    for seed in range(5):
        policy, rng = StylePolicy(), random.Random(seed)
        counts, total = dict.fromkeys(STYLES, 0), 0.0
        for _ in range(600):
            s = policy.choose(CALM, rng)
            counts[s] += 1
            r = rewards.synthetic(CALM, s, rng, rewards.FLAT_MEANS)
            total += r
            policy.update(CALM, s, r)
        assert min(counts.values()) >= MIN_OBS, counts
        assert abs(total / 600 - 0.6) < 0.06


# --- step 3: style_log ------------------------------------------------------------------------------------------

def test_style_log_rows(tickets_db):
    first = store.add_style_log(CALM, group_of(CALM), "short", reply="Hello.", ticket_id="T-0001")
    store.add_style_log(ANGRY, group_of(ANGRY), "warm", reward=1.0, source="synthetic")
    rows = store.style_log()
    assert rows[0]["reward"] is None and rows[0]["source"] is None and rows[0]["situation"] == CALM
    assert store.set_style_reward(first, 0.75, "real")
    assert [r["id"] for r in store.style_log("real")] == [first]
    assert store.style_log("synthetic")[0]["grp"] == "shopnova|info|angry"
    with pytest.raises(ValueError):
        store.add_style_log(CALM, "g", "short", reward=1.0)   # a reward needs its source
    with pytest.raises(ValueError):
        store.add_style_log(CALM, "g", "short", reward=1.0, source="guess")


def test_style_log_is_added_to_an_old_db_file(tmp_path):
    import sqlite3
    old = tmp_path / "old.db"
    con = sqlite3.connect(old)
    con.execute("CREATE TABLE notes (x TEXT)")   # a file made before T30, without style_log
    con.commit()
    con.close()
    store.use_db(old)
    try:
        assert store.style_log() == []
        store.add_style_log(CALM, "g", "warm")
        assert len(store.style_log()) == 1
    finally:
        store.use_db(store.DEFAULT_DB_PATH)


# --- step 4: reward sources ------------------------------------------------------------------------------------

def test_agent_f_reward_and_constant_warning():
    fake = lambda record: {"correctness": "PASS", "satisfaction": 3.0}
    assert rewards.from_agent_f({}, evaluate=fake) == 0.5
    assert rewards.from_agent_f({}, evaluate=lambda r: {"correctness": "FAIL", "satisfaction": 5.0}) == 0.0
    same = [{"situation_id": "p01", "style": s, "reward": 0.5} for s in STYLES]
    assert rewards.constant_across_styles(same)
    assert not rewards.constant_across_styles(same + [{"situation_id": "p01", "style": "warm", "reward": 1.0}])
    assert not rewards.constant_across_styles([])   # nothing compared: not "constant"


def write_xlsx(path, tabs):
    """A minimal real .xlsx (inline strings) with one tab per rater, in the RL1 sheet layout."""
    def cell(ref, value):
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    sheets, rels, wb = {}, [], []
    for n, (name, rows) in enumerate(tabs.items(), 1):
        xml_rows = []
        for r, row in enumerate(rows, 1):
            xml_rows.append(f'<row r="{r}">' + "".join(cell(f"{col}{r}", v) for col, v in row.items()) + "</row>")
        sheets[f"xl/worksheets/sheet{n}.xml"] = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(xml_rows) + "</sheetData></worksheet>")
        rels.append(f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml" Type="x"/>')
        wb.append(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml",
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(wb) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(rels) + "</Relationships>")
        for name, xml in sheets.items():
            z.writestr(name, xml)


HEADER = {"A": "#", "B": "Company", "E": "Reply A", "F": "Stars A", "G": "Reply B", "H": "Stars B", "I": "Reply C",
          "J": "Stars C"}
KEY = {"p01": {"A": ["warm_next_step"], "B": ["warm"], "C": ["short"]},
       "a06": {"A": ["short"], "B": ["warm_next_step", "warm"]}}


def rater(stars_p01, stars_a06):
    return [{"A": "Name"}, HEADER, {"A": "p01", "F": stars_p01[0], "H": stars_p01[1], "J": stars_p01[2]},
            {"A": "a06", "F": stars_a06[0], "H": stars_a06[1]}]


def test_ratings_are_mapped_back_to_styles(tmp_path):
    sheet, key = tmp_path / "filled.xlsx", tmp_path / "key.json"
    key.write_text(json.dumps(KEY))
    write_xlsx(sheet, {"README": [{"A": "READ ME"}], "Ann": rater(("5", "3", "1"), ("2", "4")),
                       "Bob": rater(("4.0", "4.0", "2.0"), ("1", "5"))})
    rows = rewards.from_ratings(sheet, key)
    ann = {(r["situation_id"], r["style"]): r["reward"] for r in rows if r["rater"] == "Ann"}
    assert ann[("p01", "warm_next_step")] == 1.0 and ann[("p01", "short")] == 0.0 and ann[("p01", "warm")] == 0.5
    assert ann[("a06", "warm")] == ann[("a06", "warm_next_step")] == 0.75   # one letter shown for 2 styles
    assert len(rows) == 2 * (3 + 3)


def test_identical_tabs_are_rejected(tmp_path):
    """The first returned file had 6 identical tabs: a synthetic copy of that case."""
    sheet, key = tmp_path / "copied.xlsx", tmp_path / "key.json"
    key.write_text(json.dumps(KEY))
    same = rater(("4", "3", "2"), ("1", "5"))
    write_xlsx(sheet, {name: same for name in ("Yassine", "Dali", "Semah", "Mahmoud", "Molka", "Ayoub")})
    with pytest.raises(rewards.RatingSheetError, match="identical"):
        rewards.from_ratings(sheet, key)


def test_one_value_everywhere_is_rejected(tmp_path):
    sheet, key = tmp_path / "flat.xlsx", tmp_path / "key.json"
    key.write_text(json.dumps(KEY))
    write_xlsx(sheet, {"Ann": rater(("3", "3", "3"), ("3", "3")), "Bob": rater(("3", "3", "3"), ("3", ""))})
    with pytest.raises(rewards.RatingSheetError, match="same value"):
        rewards.from_ratings(sheet, key)


def test_empty_sheet_is_rejected(tmp_path):
    sheet, key = tmp_path / "empty.xlsx", tmp_path / "key.json"
    key.write_text(json.dumps(KEY))
    write_xlsx(sheet, {"Ann": rater(("", "", ""), ("", ""))})
    with pytest.raises(rewards.RatingSheetError, match="no ratings"):
        rewards.from_ratings(sheet, key)


# --- step 7: the pipeline switch -------------------------------------------------------------------------------

def tickets():
    """10 tickets whose decision is made by code (no agent, SLM offline -> the writer's template)."""
    out = []
    for n, order in enumerate([4505, 4506, 4507, 4508, 4510, 4511, 4512, 4513]):
        angry = n % 2 == 0
        out.append({"ticket_id": f"T-{n}", "company": "shopnova", "main_reason": "order_status", "order_id": order,
                    "priority_label": "low", "style": {"formality": "neutral", "length": "short", "shouting": angry},
                    "emotion": {"label": "anger" if angry else "neutral"},
                    "sentiment": {"label": "negative" if angry else "neutral"}})
    out.append({"ticket_id": "T-8", "company": "shopnova", "main_reason": "damaged_item", "order_id": 4512})
    out.append({"ticket_id": "T-9", "company": "atlas", "main_reason": "other", "order_id": None})
    return out


def run_all():
    return [pipeline.final_reply(dict(t), None) for t in tickets()]


def switch_on(monkeypatch, tmp_path, on=True):
    cfg = json.loads(json.dumps(load_config()))
    cfg["learning"] = {"style_policy": on, "style_policy_file": str(tmp_path / "policy.json")}
    monkeypatch.setattr(pipeline, "load_config", lambda: cfg)


def test_switch_is_off_by_default():
    assert load_config()["learning"]["style_policy"] is False


def test_off_is_identical_to_main(monkeypatch, tickets_db):
    monkeypatch.delenv("CALLVERSE_REPLY_STYLE", raising=False)
    now = run_all()
    monkeypatch.setattr(pipeline, "policy_style", lambda ticket, said: (said, None))   # main had no policy step
    before = run_all()
    assert json.dumps(now, sort_keys=True) == json.dumps(before, sort_keys=True)
    assert all("reply_style" not in said for said, _, _ in now)
    assert events("style_policy") == [] and store.style_log() == []


def test_on_sets_only_the_style(monkeypatch, tmp_path, tickets_db):
    monkeypatch.delenv("CALLVERSE_REPLY_STYLE", raising=False)
    off = run_all()
    switch_on(monkeypatch, tmp_path)
    on = run_all()
    for (said_off, _, _), (said_on, reply, _), t in zip(off, on, tickets()):
        assert {k: v for k, v in said_on.items() if k != "reply_style"} == said_off   # decision fields unchanged
        if said_off.get("action") == "redirect":
            assert "reply_style" not in said_on   # the fixed off-topic text has no style
        else:
            assert said_on["reply_style"] in STYLES
    logged = store.style_log()
    assert len(logged) == 9 and all(r["reward"] is None and r["source"] is None for r in logged)
    assert logged[0]["ticket_id"] == "T-0" and logged[0]["grp"] == "shopnova|info|angry"
    assert len(events("style_policy")) == 9


def test_on_uses_the_trained_policy(monkeypatch, tmp_path, tickets_db):
    monkeypatch.delenv("CALLVERSE_REPLY_STYLE", raising=False)
    policy = StylePolicy(tmp_path / "policy.json")
    angry = {"company": "shopnova", "outcome": "info", "emotion": "anger"}
    for _ in range(200):
        policy.update(angry, "warm", 1.0)
        policy.update(angry, "short", 0.0)
        policy.update(angry, "warm_next_step", 0.0)
    policy.save()
    switch_on(monkeypatch, tmp_path)
    said, _, _ = pipeline.final_reply(dict(tickets()[0]), None)
    assert said["reply_style"] == "warm"


def test_a_style_already_set_wins(monkeypatch, tmp_path, tickets_db):
    monkeypatch.setenv("CALLVERSE_REPLY_STYLE", "short")
    switch_on(monkeypatch, tmp_path)
    said, _, _ = pipeline.final_reply(dict(tickets()[0]), None)
    assert "reply_style" not in said and store.style_log() == []


def test_policy_error_means_no_style(monkeypatch, tmp_path, tickets_db):
    monkeypatch.delenv("CALLVERSE_REPLY_STYLE", raising=False)
    off = run_all()

    def broken(self, situation, rng=None):
        raise RuntimeError("policy file is broken")
    monkeypatch.setattr(StylePolicy, "choose", broken)
    switch_on(monkeypatch, tmp_path)
    assert json.dumps(run_all(), sort_keys=True) == json.dumps(off, sort_keys=True)
    assert events("style_policy_error") and store.style_log() == []


def test_style_log_error_never_breaks_the_reply(monkeypatch, tmp_path, tickets_db):
    monkeypatch.delenv("CALLVERSE_REPLY_STYLE", raising=False)
    switch_on(monkeypatch, tmp_path)

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(store, "add_style_log", broken)
    said, reply, _ = pipeline.final_reply(dict(tickets()[0]), None)
    assert reply and said["reply_style"] in STYLES
    assert "style_log" in events("style_policy_error")[0]["error"]


# --- steps 5 and 6: offline training, importer, baselines (SYNTHETIC unless rated by a fake sheet) ----------------

def fake_cases():
    """6 hand-made situations (2 angry, 4 calm), each with a cached reply per style. Not real data."""
    out = []
    for n, (company, outcome, emotion) in enumerate([("shopnova", "info", "anger"), ("atlas", "decline", "anger"),
                                                     ("shopnova", "info", "neutral"), ("shopnova", "decline", "sadness"),
                                                     ("atlas", "info", "neutral"), ("atlas", "approve", "joy")]):
        sit = {"company": company, "outcome": outcome, "emotion": emotion, "sentiment": "negative"}
        out.append({"situation_id": f"x{n}", "situation": sit, "ticket": {"ticket_id": f"T-{n}", "text": "hi"},
                    "decision": {"outcome": outcome}, "replies": {s: f"reply {s} {n}" for s in STYLES}})
    return out


def test_train_synthetic_logs_labelled_rows(tickets_db):
    from scripts.train_style_policy import train
    result = train(fake_cases(), "synthetic", 120, seed=2)
    assert result["used"] == 120 and result["warning"] is None
    rows = store.style_log()
    assert len(rows) == 120 and {r["source"] for r in rows} == {"synthetic"}
    assert rows[0]["reply"].startswith("reply ") and "situation_id" in rows[0]["situation"]
    assert {c["source"] for c in result["curve"]} == {"synthetic"}


def test_train_agent_f_warns_when_the_reward_ignores_the_style(tickets_db):
    from scripts.train_style_policy import train
    constant = lambda record: {"correctness": "PASS", "satisfaction": 3.4}   # like today's agent F: same for every style
    result = train(fake_cases(), "agent_f", 60, seed=1, log=False, evaluate=constant)
    assert "nothing to learn" in result["warning"]
    assert store.style_log() == []   # log=False


def test_import_then_train_on_ratings(monkeypatch, tmp_path, tickets_db):
    import scripts.import_ratings as importer
    from scripts.train_style_policy import train
    cases = [{**c, "situation_id": sid} for c, sid in zip(fake_cases(), ("p01", "a06"))]
    monkeypatch.setattr(importer, "load_situations", lambda: cases)
    sheet, key = tmp_path / "filled.xlsx", tmp_path / "key.json"
    key.write_text(json.dumps(KEY))
    write_xlsx(sheet, {"Ann": rater(("5", "3", "1"), ("2", "4")), "Bob": rater(("4", "4", "2"), ("1", "5"))})
    result = importer.import_file(sheet, key)
    assert result["saved"] == 12 and result["raters"] == {"Ann": 6, "Bob": 6}
    real = store.style_log("real")
    assert len(real) == 12 and {r["situation"]["situation_id"] for r in real} == {"p01", "a06"}
    trained = train(cases, "ratings", 200, seed=1, log=False)
    assert trained["used"] > 0 and {c["source"] for c in trained["curve"]} == {"real"}


def test_training_on_ratings_never_writes_style_log_rows(monkeypatch, tmp_path, tickets_db):
    """T31 (replay fix): ratings training replays rows that are already in style_log; it must not log them again as
    "real", or a second training would count them twice. log=True on purpose: the "ratings" source ignores it."""
    import scripts.import_ratings as importer
    from scripts.train_style_policy import train
    cases = [{**c, "situation_id": sid} for c, sid in zip(fake_cases(), ("p01", "a06"))]
    monkeypatch.setattr(importer, "load_situations", lambda: cases)
    sheet, key = tmp_path / "filled.xlsx", tmp_path / "key.json"
    key.write_text(json.dumps(KEY))
    write_xlsx(sheet, {"Ann": rater(("5", "3", "1"), ("2", "4")), "Bob": rater(("4", "4", "2"), ("1", "5"))})
    imported = importer.import_file(sheet, key)["saved"]
    for seed in (1, 2):   # train twice
        assert train(cases, "ratings", 200, seed=seed, log=True)["used"] > 0
        assert len(store.style_log("real")) == imported == 12
    assert len(store.style_log()) == imported   # no row of any other source either


def test_import_rejects_identical_tabs_and_saves_nothing(monkeypatch, tmp_path, tickets_db):
    import scripts.import_ratings as importer
    monkeypatch.setattr(importer, "load_situations", lambda: fake_cases())
    sheet, key = tmp_path / "copied.xlsx", tmp_path / "key.json"
    key.write_text(json.dumps(KEY))
    same = rater(("4", "3", "2"), ("1", "5"))
    write_xlsx(sheet, {n: same for n in ("A1", "A2", "A3")})
    with pytest.raises(rewards.RatingSheetError):
        importer.import_file(sheet, key)
    assert store.style_log() == []


def test_train_on_ratings_without_ratings_stops(tickets_db):
    from scripts.train_style_policy import train
    with pytest.raises(SystemExit, match="import_ratings"):
        train(fake_cases(), "ratings", 10, seed=1, log=False)


def test_bandit_beats_random_and_the_worst_fixed_style():
    """SYNTHETIC world, 300 rounds x 3 seeds (the T30 baseline table)."""
    from scripts.train_style_policy import baselines
    rows = {r["strategy"]: r for r in baselines(fake_cases(), 300, seeds=(1, 2, 3))}
    assert all(r["source"] == "synthetic" for r in rows.values())
    worst_fixed = min(rows[s]["mean_reward"] for s in STYLES)
    assert rows["bandit"]["mean_reward"] > rows["random"]["mean_reward"]
    assert rows["bandit"]["mean_reward"] > worst_fixed
    assert rows["bandit"]["regret"] < rows["random"]["regret"]


def test_baselines_on_a_flat_world_do_not_break():
    from scripts.train_style_policy import baselines
    rows = baselines(fake_cases(), 300, seeds=(1, 2, 3), means=rewards.FLAT_MEANS)
    assert all(abs(r["mean_reward"] - 0.6) < 0.07 for r in rows)
