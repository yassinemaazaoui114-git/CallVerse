"""TASK3 data: (A) writer fine-tune examples from REAL tweets, split by thread; (B) scorer rows from 4 REAL sources.
Writes kaggle_upload/ (train + dev only; never test) and data/processed/lean/ (all splits, incl. local test sets)."""
import hashlib
import json
import random
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import PROC, RAW, ROOT, SEED, anonymise, read_jsonl, write_jsonl  # noqa: E402
from p2_build_real_messages import COMPANY, clean  # noqa: E402
from p6_followup import late_bucket, olist_splits  # noqa: E402
from realism import is_english, map_reason, message_features  # noqa: E402
from simulator.prompts import compact_roleplay_system  # noqa: E402

OUT = PROC / "lean"
UP = ROOT / "kaggle_upload" / "data"
OUT.mkdir(parents=True, exist_ok=True)
UP.mkdir(parents=True, exist_ok=True)
N_WRITER = 5000
ANGRY = re.compile(r"worst|terrible|ridiculous|wtf|awful|disgust|pathetic|unacceptable|never again|joke|useless|horrible|furious|angry|screw", re.I)
HAPPY = re.compile(r"thank|thanks|love|great|awesome|amazing|appreciate|kudos|shout ?out", re.I)


def test_thread(tid):  # 10% of threads held out (by hash), never used for training
    return int(hashlib.md5(str(tid).encode()).hexdigest(), 16) % 10 == 0


def card_from(text, company, reason):
    f = message_features(text)
    mood = "angry" if (ANGRY.search(text) or f["has_caps_word"] or "!!" in text) else "grateful" if HAPPY.search(text) else \
        "confused" if f["has_question"] else "calm"
    typo = "high" if (f["all_lowercase"] and f["has_spelling_error"]) else "medium" if (f["has_spelling_error"] or f["all_lowercase"]) else "low"
    return {"company": company, "reason": reason, "mood": mood, "typo_level": typo}


def writer_examples():
    d = pd.read_pickle(RAW / "customer-support-on-twitter" / "twcs.pkl")
    by_id = d.set_index("tweet_id")
    firsts = pd.DataFrame(read_jsonl(PROC / "real_messages" / "first_messages.jsonl"))
    firsts["tid"] = firsts.id.str[3:].astype(int)
    brand = d[~d.inbound & d.author_id.isin(COMPANY) & d.in_response_to_tweet_id.notna()]
    first_reply = brand.sort_values("tweet_id").groupby("in_response_to_tweet_id").tweet_id.first()
    firsts["reply_id"] = first_reply.reindex(firsts.tid).values
    cust = d[d.inbound & d.in_response_to_tweet_id.notna()][["tweet_id", "author_id", "text", "in_response_to_tweet_id"]]
    fu = cust.merge(firsts[["tid", "reply_id", "text", "reply_text", "company", "reason"]].dropna(subset=["reply_id"]),
                    left_on="in_response_to_tweet_id", right_on="reply_id", suffixes=("", "_first"))
    fu = fu[fu.author_id.values == by_id.author_id.reindex(fu.tid).values]  # same customer continues the thread
    fu["clean"] = fu.text.map(clean)
    fu = fu[fu.clean.str.len() > 3]
    fu = fu[fu.clean.map(is_english)]
    rows = []
    for r in firsts.itertuples():
        rows.append({"thread": f"tw{r.tid}", "company": r.company, "reason": r.reason, "history": [], "target": r.text, "src": "twcs-first"})
    for r in fu.itertuples():
        rows.append({"thread": f"tw{r.tid}", "company": r.company, "reason": r.reason,
                     "history": [{"role": "customer", "text": r.text_first}, {"role": "agent", "text": r.reply_text}],
                     "target": r.clean, "src": "twcs-followup"})
    a = pd.read_csv(RAW / "twitter-airline-sentiment" / "Tweets.csv")
    for r in a.itertuples():
        t = anonymise(re.sub(r"^(\s*@\w+)+", "", r.text)).strip()
        if len(t) > 3 and is_english(t):
            rows.append({"thread": f"al{r.tweet_id}", "company": "atlas", "reason": map_reason(t, "atlas")[0], "history": [],
                         "target": t, "src": "airline-sentiment"})
    df = pd.DataFrame(rows)
    df = df[df.target.str.split().str.len().between(2, 60)]
    df["test"] = df.thread.map(test_thread)
    rng = np.random.RandomState(SEED)
    tr = df[~df.test]
    want = {"twcs-first": 2400, "airline-sentiment": 1000, "twcs-followup": 1600}
    pick = pd.concat([g.sample(min(want[s], len(g)), random_state=rng) for s, g in tr.groupby("src")])
    ex = []
    for r in pick.itertuples():
        card = card_from(r.target, r.company, r.reason)
        msgs = [{"role": "system", "content": compact_roleplay_system(card)}]
        if not r.history:
            msgs.append({"role": "user", "content": "(The support chat has opened. Write your first message.)"})
        else:
            msgs += [{"role": "assistant", "content": r.history[0]["text"]}, {"role": "user", "content": r.history[1]["text"]}]
        msgs.append({"role": "assistant", "content": r.target})
        ex.append({"thread": r.thread, "src": r.src, "messages": msgs})
    random.Random(SEED).shuffle(ex)
    write_jsonl(ex, UP / "writer_train.jsonl")
    held = df[df.test]
    write_jsonl(held[["thread", "company", "reason", "src", "target"]].to_dict("records"), OUT / "writer_heldout_real.jsonl")
    return {"writer_train": len(ex), "by_src": pick.src.value_counts().to_dict(), "heldout_threads_real_msgs": int(len(held)),
            "train_threads": int(pick.thread.nunique()), "overlap_threads": int(len(set(pick.thread) & set(held.thread)))}


# ------------------------------------------------------------------ scorer rows
def row(src, text, label, rid, split, reason="", bucket="", turns=""):
    feats = f"[{src}] reason: {reason or 'n/a'} | wait/lateness: {bucket or 'n/a'} | turns: {turns or 'n/a'} | "
    return {"id": rid, "source": src, "split": split, "label": int(label), "reason": reason, "bucket": bucket,
            "text": (feats + (text or "(no text)"))[:2000]}


def scorer_rows():
    rs = PROC / "real_scores"
    out = []
    # CSAT (Flipkart): train/dev splits; test = the 1,000-row large test sample used for the phi4-mini baseline
    from p7_large import N, samples  # noqa: E402
    S = samples(N)
    test_ids = set(S[("csat", "test")].id)
    for part in ("train", "dev", "test"):
        for r in read_jsonl(rs / f"csat_allrows_{part}.jsonl"):
            if part == "test" and r["id"] not in test_ids:
                continue
            out.append(row("csat", r["remark"] if isinstance(r["remark"], str) else "", r["score"], r["id"], part,
                           r["reason"], r["delay_bucket"]))
    # USS travel dialogues (annotators)
    for part in ("train", "dev", "test"):
        for r in read_jsonl(rs / f"conv_{part}.jsonl"):
            t = " ".join(("U: " if x["role"] == "user" else "A: ") + x["text"] for x in r["turns"])
            out.append(row("uss", t[-1800:], r["score"], r["id"], part, turns=str(r["n_user_turns"])))
    # Olist (Portuguese comments kept as written; lateness from dates)
    tr, dv, te = olist_splits()
    rev = pd.read_csv(RAW / "brazilian-ecommerce" / "olist_order_reviews_dataset.csv").drop_duplicates("review_id").set_index("review_id")
    for part, d in (("train", tr), ("dev", dv), ("test", te.sample(500, random_state=SEED))):
        cm = rev.review_comment_message.reindex(d.review_id)
        for r, c in zip(d.itertuples(), cm.values):
            out.append(row("olist", anonymise(c) if isinstance(c, str) else "", r.score, r.id, part, bucket=r.late_bucket))
    # TripAdvisor hotel reviews
    t = pd.read_csv(RAW / "trip-advisor-hotel-reviews" / "tripadvisor_hotel_reviews.csv").reset_index()
    ttr, rest = train_test_split(t, test_size=0.30, random_state=SEED, stratify=t.Rating)
    tdv, tte = train_test_split(rest, test_size=0.50, random_state=SEED, stratify=rest.Rating)
    for part, d in (("train", ttr), ("dev", tdv), ("test", tte.sample(500, random_state=SEED))):
        for r in d.itertuples():
            out.append(row("tripadvisor", anonymise(r.Review), r.Rating, f"trip_{r.index}", part))
    df = pd.DataFrame(out)
    for part in ("train", "dev", "test"):
        write_jsonl(df[df.split == part].to_dict("records"), OUT / f"scorer_{part}.jsonl")
    write_jsonl(df[df.split.isin(["train", "dev"])].to_dict("records"), UP / "scorer_traindev.jsonl")
    return df.groupby(["source", "split"]).size().unstack().to_dict()


if __name__ == "__main__":
    info = {"writer": writer_examples(), "scorer": scorer_rows()}
    (OUT / "build_info.json").write_text(json.dumps(info, indent=1, default=str), encoding="utf-8")
    print(json.dumps(info, default=str))
