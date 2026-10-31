"""CallVerse Client Simulator: realistic customer turns and a calibrated 1-5 satisfaction score.

    from simulator import load_role_card, simulate_turn, score_conversation
    card = load_role_card("simulator/role_cards/shopnova/SN-01.yaml")
    msg = simulate_turn(card, [])                       # first customer message
    out = score_conversation(card, transcript)          # {"score", "raw_score", "comment", ...}
"""
import collections
import json
import math
import random
import re
from pathlib import Path

import requests
import yaml

from .prompts import SCORE_SCHEMA, breaks_role, compact_roleplay_system, role_card_text, roleplay_messages, score_messages

HERE = Path(__file__).resolve().parent
_CFG = None


def config(path=None):
    global _CFG
    if _CFG is None or path:
        _CFG = yaml.safe_load(Path(path or HERE / "config.yaml").read_text(encoding="utf-8"))
    return _CFG


def _load_json(name):
    p = HERE / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_role_card(path):
    card = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for k in ("id", "company", "goal"):
        if k not in card:
            raise ValueError(f"role card {path} is missing '{k}'")
    if card["company"] not in ("shopnova", "atlas"):
        raise ValueError("company must be 'shopnova' or 'atlas'")
    return card


def _chat(messages, temperature, num_predict, fmt=None, model=None, seed=None):
    cfg = config()
    body = {"model": model or cfg["model"], "messages": messages, "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": cfg.get("num_ctx", 4096)}}
    if seed is not None:
        body["options"]["seed"] = seed
    if fmt:
        body["format"] = fmt
    if body["model"].startswith("qwen3"):
        body["think"] = False  # as in the Phase 3 tests; otherwise qwen3.x spends the token budget on hidden thinking
    r = requests.post(cfg["ollama_url"].rstrip("/") + "/api/chat", json=body, timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"]


_META = re.compile(r"^\s*(?:(?:ok(?:ay)?|sure|alright|here goes)[,!.]?\s*)?(?:here'?s|here is|this is)\s+(?:my|the|a)\s+"
                   r"(?:first\s+|next\s+|follow[- ]up\s+|customer\s+)?(?:message|reply|response|turn)[^:\n]{0,40}:\s*", re.I)
_AS_A = re.compile(r"^\s*as (?:a|the) (?:customer|client|user)[^,:]{0,30}[,:]\s*", re.I)
_STAGE = re.compile(r"^\s*[\(\[\*][^\)\]\*]{0,80}[\)\]\*]\s*")   # (sighs) / [angry] / *types fast*
STATS = {"calls": 0, "meta_stripped": 0, "retried_empty": 0, "retried_assistant": 0, "retried_opener": 0, "typo_noise": 0, "returned_empty": 0}
_OPENERS = collections.deque(maxlen=50)   # first words of recent FIRST messages, across conversations


def clean_turn(text):
    """Keep only the customer's message: drop meta lines ("Here's my first message:", "As a customer, ..."), stage
    directions, a 'Customer:' prefix, quotes, and anything after an 'Agent:' line."""
    t = text.strip()
    t = re.split(r"\n\s*(agent|support|assistant)\s*:", t, flags=re.I)[0]
    before = t
    for _ in range(2):
        t = _META.sub("", t)
        t = _AS_A.sub("", t)
        t = _STAGE.sub("", t)
        t = re.sub(r"^(customer|me|user)\s*:\s*", "", t, flags=re.I).strip()
    if t != before.strip():
        STATS["meta_stripped"] += 1
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    return t


def opener(t):
    return " ".join(re.findall(r"[a-z']+", t.lower())[:3])


_SPELL = None


def has_typo(t):
    global _SPELL
    try:
        if _SPELL is None:
            from spellchecker import SpellChecker
            _SPELL = SpellChecker()
    except Exception:
        return True  # no spell checker available: do not add noise
    words = [w.lower() for w in re.findall(r"[A-Za-z']+", re.sub(r"<[A-Z_]+>", " ", t)) if len(w) > 2 and not w[0].isupper()]
    return bool(words) and bool(_SPELL.unknown(words))


def add_typos(t, level, rng):
    """Light, realistic typo noise for cards that ask for typos (only used when the model wrote perfectly)."""
    words = t.split()
    cand = [i for i, w in enumerate(words) if len(w) >= 5 and w.isalpha()]
    if cand:
        i = rng.choice(cand)
        w = words[i]
        j = rng.randrange(1, len(w) - 2)
        words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2:]     # swap two neighbouring letters
    t = " ".join(words).replace("'", "").replace("’", "")
    if level == "high" and rng.random() < config()["roleplay"].get("typo_lowercase_prob", 0.3):
        t = t.lower().rstrip(".")
    return t


def real_examples(company, k=5, seed=0):
    """k real, anonymised first messages (Customer Support on Twitter, CC BY-NC-SA 4.0) for the prompted writer."""
    ex = _load_json("real_examples.json") or {}
    pool = ex.get(company, [])
    return random.Random(seed).sample(pool, min(k, len(pool))) if pool else None


def simulate_turn(role_card, history, examples=None, seed=None):
    """history: list of {"role": "customer"|"agent", "text": str}. Returns the next customer message.
    prompt_style "finetuned": compact role card (the fine-tuned writer's training format);
    "examples": full role card + 5 real example messages (prompted small writer)."""
    rp = config()["roleplay"]
    style = rp.get("prompt_style", "examples")
    if style == "finetuned":
        msgs = roleplay_messages(role_card, history)
        msgs[0] = {"role": "system", "content": compact_roleplay_system(role_card)}
    else:
        if examples is None and rp.get("n_examples", 0):
            examples = real_examples(role_card["company"], rp["n_examples"], seed or 0)
        msgs = roleplay_messages(role_card, history, examples)
    STATS["calls"] += 1
    first = not any(h["role"] == "customer" for h in history)
    out = ""
    for attempt in range(rp.get("retries", 1) + 1):   # retry once on empty, assistant-style or repeated-opener output
        out = clean_turn(_chat(msgs, rp["temperature"], rp["num_predict"], seed=None if seed is None else seed + attempt))
        last = attempt == rp.get("retries", 1)
        if not out:
            if not last:
                STATS["retried_empty"] += 1
            continue
        if breaks_role(out) and not last:
            STATS["retried_assistant"] += 1
            continue
        if first and rp.get("avoid_repeat_openers", True) and opener(out) in _OPENERS and not last:
            STATS["retried_opener"] += 1
            continue
        break
    if not out:
        STATS["returned_empty"] += 1
        return out
    if first:
        _OPENERS.append(opener(out))
    level = role_card.get("typo_level", "low")
    rng = random.Random(f"{seed}|{out}")   # per message: the same seed must not give the same draw for every turn
    prob = (rp.get("typo_noise_prob") or {"medium": 0.25, "high": 0.4}).get(level, 0)
    if rp.get("typo_noise", True) and level in ("medium", "high") and not has_typo(out) and rng.random() < prob:
        out = add_typos(out, level, rng)
        STATS["typo_noise"] += 1
    return out


def _situation(card):
    s = role_card_text(card)
    if card.get("wait_minutes") is not None:
        s += f"\nYou waited {card['wait_minutes']} minutes for the first answer."
    if card.get("days_late") is not None:
        d = card["days_late"]
        s += ("\nYour order never arrived." if d == "never" else
              f"\nYour order arrived {d} days after the promised date." if float(d) > 0 else "\nYour order arrived on time.")
    return s


def parse_json_score(text):
    try:
        j = json.loads(text)
        s = int(round(float(j["score"])))
        if 1 <= s <= 5:
            return s, str(j.get("comment", "")).strip(), True
    except Exception:
        pass
    m = re.search(r'"?score"?\s*[:=]\s*([1-5])', text) or re.search(r"\b([1-5])\b", text)
    return (int(m.group(1)) if m else None), "", False


PROFILES = {"main": ("rubric.json", "calibration.json"), "fallback": ("rubric_fallback.json", "calibration_fallback.json")}
DELAY_BUCKETS = [(5, "0-5 min"), (30, "5-30 min"), (120, "30 min-2 h"), (480, "2-8 h"), (float("inf"), "8 h+")]


def _profile_files():
    sc = config()["scoring"]
    return PROFILES[sc.get("calibration_profile", "main")]


def delay_bucket(wait_minutes):
    if wait_minutes is None or wait_minutes < 0:
        return None
    return next(lab for hi, lab in DELAY_BUCKETS if wait_minutes <= hi)


def late_bucket(days_late):
    if days_late is None:
        return None
    if days_late == "never":
        return "never delivered"
    d = float(days_late)
    return "on time or early" if d <= 0 else "1-3 days late" if d <= 3 else "4-7 days late" if d <= 7 else "8+ days late"


def apply_calibration(raw, calibration=None, role_card=None):
    """Map the model's raw 1-5 score with the configured model's calibration (identity if none).
    main profile: per waiting-time bucket when the role card has `wait_minutes` and the delay-aware map is enabled.
    fallback profile: per delivery-lateness bucket when the card has `days_late` and that map is enabled."""
    cal = calibration if calibration is not None else _load_json(_profile_files()[1])
    if not cal or raw is None:
        return raw
    entry = cal if "map" in cal else (cal.get("models", {}).get(config()["model"]) or {})
    mp = entry.get("map")
    card = role_card or {}
    da = entry.get("delay_aware") or {}
    if da.get("enabled") and delay_bucket(card.get("wait_minutes")) in da.get("bucket_maps", {}):
        mp = da["bucket_maps"][delay_bucket(card.get("wait_minutes"))]
    la = entry.get("lateness_aware") or {}
    if la.get("enabled") and late_bucket(card.get("days_late")) in la.get("bucket_maps", {}):
        mp = la["bucket_maps"][late_bucket(card.get("days_late"))]
    return mp[str(int(raw))] if mp else raw   # int, or float for the delay-aware expected-score map


_SCORER = None


def _scorer():
    global _SCORER
    if _SCORER is None:
        from .scorer import OnnxScorer
        sc = config()["scorer"]
        _SCORER = OnnxScorer(sc["model_dir"], sc.get("model_file", "scorer_int8.onnx"), sc.get("calibration_file"),
                             sc.get("source_tag", "csat"), calibration=sc.get("calibration", "dev"))
    return _SCORER


def _writer_comment(role_card, transcript, score):
    msgs = [{"role": "system", "content": compact_roleplay_system(role_card)},
            {"role": "user", "content": "The chat is over:\n" + "\n".join(
                ("Customer: " if t["role"] == "customer" else "Agent: ") + t["text"] for t in transcript[-6:])
             + f"\nYou rated it {score} out of 5. Write one short line saying why, as the customer."}]
    return clean_turn(_chat(msgs, 0.7, 40))


def score_conversation(role_card, transcript, calibrate=True):
    """score_mode "scorer" (default): fine-tuned CPU scorer (no GPU); "llm": the writer LLM with the rubric prompt."""
    if config()["scoring"].get("score_mode", "llm") == "scorer":
        raw, expected = _scorer()(role_card, transcript)
        expected = expected if calibrate else raw
        score = int(math.floor(expected + 0.5))
        comment = _writer_comment(role_card, transcript, score) if config()["scorer"].get("comment_from_writer") else ""
        return {"score": score, "expected_score": round(expected, 3), "raw_score": round(raw, 3), "comment": comment,
                "valid_json": True, "breaks_role": breaks_role(comment), "mode": "scorer"}
    return _score_with_llm(role_card, transcript, calibrate)


def _score_with_llm(role_card, transcript, calibrate=True):
    """transcript: list of {"role": "customer"|"agent", "text": str}.
    Returns {"score": calibrated integer 1-5, "expected_score": calibrated continuous 1-5 (use this for agent E's reward),
             "raw_score": model's 1-5, "comment": str, "valid_json": bool, "breaks_role": bool}."""
    sc = config()["scoring"]
    rubric = _load_json(_profile_files()[0])
    version = "v2" if sc["prompt_version"] == "s2" and rubric else "v1"
    msgs = score_messages(_situation(role_card), transcript, version, rubric=rubric, shots=(rubric or {}).get("shots"))
    fmt = SCORE_SCHEMA if sc.get("structured_output") else None
    text = _chat(msgs, sc["temperature"], sc["num_predict"], fmt=fmt)
    raw, comment, valid = parse_json_score(text)
    if raw is None:
        raw = 5  # real CSAT majority class; flagged through valid_json=False
    expected = float(apply_calibration(raw, role_card=role_card)) if calibrate else float(raw)
    score = int(math.floor(expected + 0.5))
    return {"score": score, "expected_score": round(expected, 3), "raw_score": raw, "comment": comment,
            "valid_json": valid, "breaks_role": breaks_role(comment)}


def sample_traffic(n, company, seed=0):
    """Sample n (reason, hour_of_day, weekday) tuples from the real numbers in real_numbers.json."""
    rn = _load_json(config()["real_numbers_file"])
    rng = random.Random(seed)
    mix = rn["reason_mix"][company]["values"]
    hours = rn["arrivals_share_by_hour"]["values"]
    days = rn["arrivals_share_by_weekday"]["values"]
    pick = lambda d: rng.choices(list(d), weights=list(d.values()))[0]  # noqa: E731
    return [{"reason": pick(mix), "hour": int(pick(hours)), "weekday": pick(days),
             "gives_up": rng.random() < rn["give_up_rate"]["value"]} for _ in range(n)]
