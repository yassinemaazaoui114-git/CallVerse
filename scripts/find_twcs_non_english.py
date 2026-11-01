"""Find REAL non-English first tweets in Customer Support on Twitter (TWCS), shop brands only (T14b, read-only helper).

    python -m scripts.find_twcs_non_english

Same source and style as scripts/build_twcs_candidates.py (Kaggle "Customer Support on Twitter", Thought Vector,
CC BY-NC-SA 4.0; the zip stays in data/raw/twcs/, git-ignored). The English filter is turned around: a first tweet is kept when
a simple stop-word guess (callverse/intake/language.py) says Spanish, French, Italian or German. @handles and links are
removed, nothing else is changed. Two passes in chunks, so RAM stays low.

Output: data/raw/twcs/lang_candidates.json (git-ignored): up to 15 random tweets per language (seed 2026) with tweet_id,
brand and text, plus how many were found. NOTHING here is a test set: the Brain reads the file and picks later.
"""

import json
import random
import zipfile

import pandas as pd

from callverse.intake.language import detect
from scripts.build_twcs_candidates import CHUNK, RAW, SEED, SHOP_BRANDS, clean, csv_member

OUT = RAW / "lang_candidates.json"
LANGUAGES = ("es", "fr", "it", "de")
PER_LANGUAGE = 15
MIN_WORDS = 5


def main() -> None:
    zips = sorted(RAW.glob("*.zip"))
    if not zips:
        raise SystemExit(f"No zip in {RAW}")
    zf = zipfile.ZipFile(zips[0])
    member = csv_member(zf)
    cols = ["tweet_id", "author_id", "inbound", "text", "response_tweet_id", "in_response_to_tweet_id"]

    # pass 1: first user tweets (not replies) whose words look Spanish / French / Italian / German; remember their replies
    firsts, reply_of = {}, {}
    for chunk in pd.read_csv(zf.open(member), usecols=cols, chunksize=CHUNK, dtype=str):
        chunk = chunk[(chunk["inbound"].str.lower() == "true") & chunk["in_response_to_tweet_id"].isna()]
        for row in chunk.itertuples(index=False):
            text = clean(str(row.text))
            if len(text.split()) < MIN_WORDS or not isinstance(row.response_tweet_id, str):
                continue
            lang = detect(text)
            if lang not in LANGUAGES:
                continue
            firsts[row.tweet_id] = {"tweet_id": row.tweet_id, "text": text, "language": lang}
            for rid in row.response_tweet_id.split(","):
                reply_of[rid.strip()] = row.tweet_id
    print("pass 1:", len(firsts), "non-English-looking first tweets")

    # pass 2: who answered (the brand)
    for chunk in pd.read_csv(zf.open(member), usecols=["tweet_id", "author_id", "inbound"], chunksize=CHUNK, dtype=str):
        chunk = chunk[(chunk["inbound"].str.lower() == "false") & chunk["tweet_id"].isin(reply_of.keys())]
        for row in chunk.itertuples(index=False):
            first = firsts.get(reply_of[row.tweet_id])
            if first is not None and "brand" not in first:
                first["brand"] = row.author_id

    rng = random.Random(SEED)
    out = {"_note": "REAL tweets from TWCS (Kaggle, Thought Vector, CC BY-NC-SA 4.0); first user tweet of a thread; "
                    "shop brands only; the language is a stop-word guess (it can be wrong). @handles and links removed, "
                    "nothing else changed. Candidates only, NOT a test set (git-ignored). Seed 2026.",
           "found": {}, "candidates": {}}
    for lang in LANGUAGES:
        pool = [f for f in firsts.values() if f.get("brand") in SHOP_BRANDS and f["language"] == lang]
        rng.shuffle(pool)
        out["found"][lang] = len(pool)
        out["candidates"][lang] = [{"tweet_id": f["tweet_id"], "brand": f["brand"], "text": f["text"]}
                                   for f in pool[:PER_LANGUAGE]]
        print(lang, len(pool), "found ->", len(out["candidates"][lang]))
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
