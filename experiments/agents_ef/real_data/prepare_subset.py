"""Build a small, representative, leak-free evaluation subset from a REAL customer-support dataset.

    python -m real_data.prepare_subset --input <file.csv|.jsonl|.json> --text text --intent intent \
        [--lang lang] [--scenario scenario] [--rating csat] [--conv-id conversation_id] \
        [--timestamp created_at] [--handle-time handle_min] --n 800 --out $CALLVERSE_DATA_DIR/subset

Why each step is here:
- Column names are passed in, because the real schema is not known in this repository yet.
- Dedup BEFORE splitting: the same text in train and test would inflate scores (leakage).
- Group-aware split: all messages of one conversation go to ONE split (a conversation leaks its own label).
- Stratified on language x intent: small classes (e.g. French refunds) stay represented in every split.
- Near-duplicate check (TF-IDF cosine >= 0.9, test vs train): templated/bot texts leak even when not identical.
- Satisfaction labels are used ONLY if a real rating column is given. Intents/scenarios are never turned into
  satisfaction labels.
- Arrival rates / service times are estimated ONLY if timestamps / handle times exist; otherwise they are
  reported as "not available" and the simulator keeps its assumptions.
Outputs (write them OUTSIDE git: they contain real customer text):
  train.jsonl, val.jsonl, test.jsonl   the subset, one record per message
  profile.json                         aggregated statistics only (no text) -> safe to share/commit
  e_calibration.json                   what the Agent E simulator may take from the data (see calibration.py)
"""

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FR_WORDS = {"le", "la", "les", "des", "est", "et", "je", "vous", "pas", "une", "mon", "ma", "mes", "pour",
            "commande", "remboursement", "colis", "bonjour", "merci", "livraison", "avec", "sur", "que", "qui"}
EN_WORDS = {"the", "is", "and", "my", "your", "not", "for", "order", "refund", "package", "hello", "thanks",
            "delivery", "with", "on", "that", "what", "where", "you", "it"}
SPLITS = {"train": 0.6, "val": 0.2, "test": 0.2}


# ---------- loading ----------
def load_rows(path: Path) -> list[dict]:
    """CSV, JSON lines or a JSON list. Parquet only if pyarrow is installed (not required)."""
    suf = path.suffix.lower()
    if suf == ".csv":
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    if suf in (".jsonl", ".ndjson"):
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    if suf == ".json":
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else d.get("data") or d.get("messages") or d.get("rows")
    if suf == ".parquet":
        import pyarrow.parquet as pq          # optional, only if the data comes as parquet
        return pq.read_table(path).to_pylist()
    raise ValueError(f"unsupported file type: {suf}")


def guess_lang(text: str) -> str:
    """Tiny word-list heuristic, used only when the data has no language column (flagged in profile.json)."""
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", text.lower())
    fr, en = sum(w in FR_WORDS for w in words), sum(w in EN_WORDS for w in words)
    if fr == en == 0:
        return "fr" if re.search(r"[àâçéèêëîïôûùœ]", text.lower()) else "unknown"
    return "fr" if fr > en else "en"


def norm_text(t: str) -> str:
    t = re.sub(r"\d+", "0", t.lower())         # order numbers etc. do not make a message "different"
    return re.sub(r"\W+", " ", t).strip()


def parse_rating(v):
    """Real rating -> 1..5. Accepts 1-5, 0-10 (NPS-like, rescaled) and 'positive/neutral/negative' is NOT accepted
    (that is sentiment, not satisfaction)."""
    if v is None or str(v).strip() == "":
        return None
    try:
        x = float(v)
    except ValueError:
        return None
    if 1 <= x <= 5:
        return x
    if 0 <= x <= 10:
        return 1 + 4 * x / 10
    return None


def normalise(raw: list[dict], a) -> tuple[list[dict], dict]:
    rows = []
    lang_source = f"fixed --lang-value {a.lang_value}" if a.lang_value else (
        "column" if a.lang else "heuristic (no language column)")
    for i, r in enumerate(raw):
        text = str(r.get(a.text) or "").strip()
        if not text:
            continue
        lang = (a.lang_value if a.lang_value else
                str(r.get(a.lang) or "").strip().lower()[:2] if a.lang else guess_lang(text))
        rows.append({
            "id": str(r.get(a.id_col) or i),
            "conv": str(r.get(a.conv_id) or f"row{i}") if a.conv_id else f"row{i}",
            "text": text, "lang": lang or "unknown",
            "intent": str(r.get(a.intent) or "unknown") if a.intent else "unknown",
            "scenario": str(r.get(a.scenario) or "") if a.scenario else "",
            "rating": parse_rating(r.get(a.rating)) if a.rating else None,
            "ts": r.get(a.timestamp) if a.timestamp else None,
            "handle_min": _float(r.get(a.handle_time)) if a.handle_time else None,
        })
    return rows, {"lang_source": lang_source}


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- sampling and splitting ----------
def dedup(rows):
    seen, out, dropped = set(), [], 0
    for r in rows:
        h = hashlib.sha1(norm_text(r["text"]).encode()).hexdigest()
        if h in seen:
            dropped += 1
            continue
        seen.add(h)
        r["hash"] = h
        out.append(r)
    return out, dropped


def stratum(r):
    """language x intent, plus the rounded rating when real ratings exist (keeps rare 2- and 3-star cases)."""
    return (r["lang"], r["intent"], round(r["rating"]) if r["rating"] is not None else None)


def stratified_groups(rows, n_target, seed, min_per_stratum=6):
    """Pick whole conversations until ~n_target messages, proportional to language x intent strata, with a floor
    so rare strata are still present. Returns the chosen rows."""
    rng = np.random.default_rng(seed)
    convs = defaultdict(list)
    for r in rows:
        convs[r["conv"]].append(r)
    strata = defaultdict(list)                   # stratum of a conversation = its first message's lang x intent
    for c, rs in convs.items():
        strata[stratum(rs[0])].append(c)
    total = sum(len(v) for v in convs.values())
    chosen = []
    for key, cs in sorted(strata.items()):
        n_msgs = sum(len(convs[c]) for c in cs)
        want = max(min_per_stratum, round(n_target * n_msgs / total))
        got = 0
        for c in rng.permutation(cs):
            if got >= want:
                break
            chosen.extend(convs[c])
            got += len(convs[c])
    return chosen


def split(rows, seed):
    """Group-aware, stratified split of the chosen subset: conversations never cross splits."""
    rng = np.random.default_rng(seed + 1)
    convs = defaultdict(list)
    for r in rows:
        convs[r["conv"]].append(r)
    strata = defaultdict(list)
    for c, rs in convs.items():
        strata[stratum(rs[0])].append(c)
    out = {s: [] for s in SPLITS}
    for key, cs in sorted(strata.items()):
        cs = list(rng.permutation(cs))
        n = len(cs)
        n_te = max(1, round(n * SPLITS["test"])) if n >= 3 else 0
        n_va = max(1, round(n * SPLITS["val"])) if n >= 3 else 0
        for i, c in enumerate(cs):
            s = "test" if i < n_te else "val" if i < n_te + n_va else "train"
            out[s].extend(convs[c])
    return out


def drop_near_duplicates(parts, thr=0.9) -> dict:
    """Remove val/test messages whose character n-gram TF-IDF cosine to some TRAIN message is >= thr.
    Support data is full of templates ("where is my order N"); keeping them in TEST measures memorisation."""
    removed = {"val": 0, "test": 0}
    if not parts["train"]:
        return removed
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit([r["text"] for r in parts["train"]])
    B = vec.transform([r["text"] for r in parts["train"]])
    for s in ("val", "test"):
        if not parts[s]:
            continue
        sim = (vec.transform([r["text"] for r in parts[s]]) @ B.T).max(axis=1).toarray().ravel()
        keep = [r for r, x in zip(parts[s], sim) if x < thr]
        removed[s] = len(parts[s]) - len(keep)
        parts[s] = keep
    return removed


def leakage_report(parts) -> dict:
    """Exact (normalised) duplicates and conversation ids across splits + TF-IDF near-duplicates test vs train."""
    rep = {}
    for a_, b_ in (("train", "val"), ("train", "test"), ("val", "test")):
        ha, hb = {r["hash"] for r in parts[a_]}, {r["hash"] for r in parts[b_]}
        ca, cb = {r["conv"] for r in parts[a_]}, {r["conv"] for r in parts[b_]}
        rep[f"{a_}_vs_{b_}"] = {"same_text": len(ha & hb), "same_conversation": len(ca & cb)}
    if parts["train"] and parts["test"]:
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1).fit(
            [r["text"] for r in parts["train"]])
        A, B = vec.transform([r["text"] for r in parts["test"]]), vec.transform([r["text"] for r in parts["train"]])
        sim = (A @ B.T).max(axis=1).toarray().ravel()
        rep["test_near_duplicates_of_train_cos>=0.9"] = int((sim >= 0.9).sum())
        rep["test_max_cos_to_train_median"] = float(np.median(sim))
    return rep


# ---------- profiling (aggregates only, no text) ----------
def profile(rows, parts, meta, dropped_dups, n_input) -> dict:
    def dist(rs, key):
        c = Counter(r[key] for r in rs)
        n = max(1, len(rs))
        return {k: {"n": v, "share": round(v / n, 4)} for k, v in c.most_common()}

    lens = [len(r["text"].split()) for r in rows]
    ratings = [r["rating"] for r in rows if r["rating"] is not None]
    ts = [r["ts"] for r in rows if r["ts"]]
    ht = [r["handle_min"] for r in rows if r["handle_min"] is not None]
    p = {
        "n_input_rows": n_input, "n_after_dedup": len(rows), "exact_duplicates_dropped": dropped_dups,
        "language": dist(rows, "lang"), "language_source": meta["lang_source"],
        "intent": dist(rows, "intent"),
        "lang_x_intent": {f"{k[0]}|{k[1]}": v for k, v in Counter((r["lang"], r["intent"]) for r in rows).items()},
        "words_per_message": {"mean": float(np.mean(lens)), "p50": float(np.median(lens)),
                              "p95": float(np.percentile(lens, 95))} if lens else {},
        "messages_per_conversation": float(np.mean(list(Counter(r["conv"] for r in rows).values()))),
        "satisfaction_labels": {"present": bool(ratings), "n": len(ratings),
                                "distribution_1to5": dict(Counter(round(x) for x in ratings))},
        "timestamps": {"present": bool(ts), "n": len(ts)},
        "handle_time": {"present": bool(ht), "n": len(ht)},
        "splits": {s: {"n": len(v), "conversations": len({r['conv'] for r in v}),
                       "language": dist(v, "lang"), "intent": dist(v, "intent")} for s, v in parts.items()},
    }
    # class imbalance: largest / smallest intent class in the subset
    ic = Counter(r["intent"] for r in sum(parts.values(), []))
    if ic:
        p["intent_imbalance_ratio"] = round(max(ic.values()) / max(1, min(ic.values())), 2)
    return p


def e_calibration(rows, mapping) -> dict:
    """What Agent E may take from the data. Queue mix from intents (via an editable mapping); language mix;
    arrival profile / service time ONLY if the data has timestamps / handle times."""
    q_counts = Counter(mapping.get(r["intent"], mapping.get("_default", "A_status")) for r in rows)
    n = sum(q_counts.values())
    cal = {"source": f"{len(rows)} deduplicated rows of the --input dataset (see profile.json)",
           "queue_share": {q: round(q_counts.get(q, 0) / n, 4) for q in ("A_status", "B_refund", "C_urgent",
                                                                          "D_availability")},
           "language_share": {k: round(v / len(rows), 4) for k, v in Counter(r["lang"] for r in rows).items()},
           "intent_to_queue_mapping": mapping}
    ts = sorted(_hour(r["ts"]) for r in rows if r["ts"] and _hour(r["ts"]) is not None)
    if len(ts) >= 200:
        h = Counter(ts)
        cal["hourly_arrival_share"] = {str(k): round(v / len(ts), 4) for k, v in sorted(h.items())}
    else:
        cal["hourly_arrival_share"] = "NOT AVAILABLE (no or too few timestamps); simulator keeps its assumption"
    ht = [r["handle_min"] for r in rows if r["handle_min"] is not None]
    cal["service_min_by_queue"] = "NOT AVAILABLE (no handle times); simulator keeps its assumption"
    if len(ht) >= 200:
        by_q = defaultdict(list)
        for r in rows:
            if r["handle_min"] is not None:
                by_q[mapping.get(r["intent"], mapping.get("_default", "A_status"))].append(r["handle_min"])
        cal["service_min_by_queue"] = {q: float(np.median(v)) for q, v in by_q.items() if len(v) >= 30}
    return cal


def _hour(v):
    m = re.search(r"[T ](\d{2}):\d{2}", str(v))
    return int(m.group(1)) if m else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--intent")
    ap.add_argument("--lang")
    ap.add_argument("--lang-value", dest="lang_value", help="whole dataset is one language (e.g. pt for Olist)")
    ap.add_argument("--scenario")
    ap.add_argument("--rating", help="ONLY a genuine satisfaction rating column (CSAT/stars/NPS)")
    ap.add_argument("--conv-id", dest="conv_id")
    ap.add_argument("--id-col", dest="id_col", default="id")
    ap.add_argument("--timestamp")
    ap.add_argument("--handle-time", dest="handle_time")
    ap.add_argument("--mapping", default=str(Path(__file__).with_name("intent_to_queue.json")))
    ap.add_argument("--n", type=int, default=800)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True, help="folder OUTSIDE git (real customer text)")
    a = ap.parse_args(argv)

    raw = load_rows(Path(a.input))
    rows, meta = normalise(raw, a)
    rows, dropped = dedup(rows)
    chosen = stratified_groups(rows, a.n, a.seed)
    parts = split(chosen, a.seed)
    near = drop_near_duplicates(parts)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for s, rs in parts.items():
        with open(out / f"{s}.jsonl", "w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps({k: v for k, v in r.items() if k != "hash"}, ensure_ascii=False) + "\n")
    prof = profile(rows, parts, meta, dropped, len(raw))
    prof["leakage"] = leakage_report(parts)
    prof["leakage"]["near_duplicates_removed"] = near
    (out / "profile.json").write_text(json.dumps(prof, indent=2, ensure_ascii=False))
    mapping = json.loads(Path(a.mapping).read_text())
    (out / "e_calibration.json").write_text(json.dumps(e_calibration(rows, mapping), indent=2))
    print(json.dumps({"subset": {s: len(v) for s, v in parts.items()},
                      "satisfaction_labels": prof["satisfaction_labels"]["present"],
                      "timestamps": prof["timestamps"]["present"], "leakage": prof["leakage"]}, indent=1))
    return prof


if __name__ == "__main__":
    main()
