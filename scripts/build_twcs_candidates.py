"""Pick REAL user messages from Customer Support on Twitter (TWCS) as candidates for CallVerse test sets.

    python -m scripts.build_twcs_candidates

Source: Kaggle "Customer Support on Twitter" (Thought Vector), CC BY-NC-SA 4.0. The zip stays in data/raw/twcs/
(git-ignored). Written by the Brain, 2026-10-31 (real data first: Yassine's rule).

What it does (two passes over the CSV, in chunks, so RAM stays low):
  1. keeps the FIRST tweet of a user thread (inbound, not a reply), English-looking, >= 5 words, that matches one of
     the CASES keyword rules below;
  2. finds which brand answered it (author of the reply tweet) and keeps shopping brands (ShopNova cases) and
     airline / travel brands (Atlas cases, for later).
Cleaning is minimal: @handles and links removed, spaces squeezed. Everything else (typos, slang, anger) is kept.
Output: data/raw/twcs/candidates.json (git-ignored): up to 150 random tweets per case and company, seed 2026, with
tweet_id, brand and text. The Brain reads it and proposes the sets; nothing here is a test set yet.
"""

import json
import random
import re
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "twcs"
OUT = RAW / "candidates.json"
SEED, PER_CASE, CHUNK = 2026, 150, 200_000

SHOP_BRANDS = {"AmazonHelp", "ArgosHelpers", "AskTarget", "Tesco", "sainsburys", "AskeBay", "UPSHelp", "USPSHelp"}
TRAVEL_BRANDS = {"Delta", "AmericanAir", "British_Airways", "SouthwestAir", "AlaskaAir", "VirginAtlantic", "JetBlue",
                 "united", "VirginAmerica", "AirAsiaSupport", "Hilton", "MarriottIntl"}

# case -> regex on the lower-case text (a tweet may match several cases; each is kept under every match)
CASES = {
    "return_late": r"\breturn\w*\b.*\b(days?|window|period|policy|too late|expired|deadline)\b",
    "refund": r"\brefund\w*\b",
    "refund_again": r"\brefund\w*\b.*\b(again|already|twice|second|double)\b|\b(again|already|twice|double)\b.*\brefund\w*\b",
    "cancel_order": r"\bcancel\w*\b.*\b(order|purchase|item|package)\b|\b(order|purchase)\b.*\bcancel\w*\b",
    "late_order": r"\b(late|delayed|still (not|hasn'?t|haven'?t)|not (arrived|delivered|here)|hasn'?t (arrived|come)|where is my)\b",
    "damaged": r"\b(damaged|broken|smashed|cracked|crushed)\b",
    "flight_delay_cancel": r"\b(delay\w*|cancel\w*)\b.*\b(flight|plane|gate)\b|\b(flight|plane)\b.*\b(delay\w*|cancel\w*)\b",
    "compensation": r"\b(compensat\w*|reimburs\w*)\b",
    "assistance": r"\b(wheelchair|disabilit\w*|assistance|blind|deaf|mobility)\b",
}
SHOP_CASES = ["return_late", "refund", "refund_again", "cancel_order", "late_order", "damaged"]
TRAVEL_CASES = ["flight_delay_cancel", "compensation", "refund", "assistance"]
HANDLE, LINK = re.compile(r"@\w+"), re.compile(r"https?://\S+")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", LINK.sub("", HANDLE.sub("", text))).strip()


def english_like(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) / len(letters) > 0.95


def csv_member(zf: zipfile.ZipFile) -> str:
    """The big twcs.csv inside the zip (the largest .csv; Kaggle also ships a small sample.csv)."""
    csvs = [i for i in zf.infolist() if i.filename.lower().endswith(".csv")]
    return max(csvs, key=lambda i: i.file_size).filename


def main() -> None:
    zips = sorted(RAW.glob("*.zip"))
    if not zips:
        raise SystemExit(f"No zip in {RAW}")
    zf = zipfile.ZipFile(zips[0])
    member = csv_member(zf)
    cols = ["tweet_id", "author_id", "inbound", "text", "response_tweet_id", "in_response_to_tweet_id"]
    compiled = {k: re.compile(v) for k, v in CASES.items()}

    # pass 1: first user tweets that match a case; remember the ids of their replies
    firsts, reply_of = {}, {}
    for chunk in pd.read_csv(zf.open(member), usecols=cols, chunksize=CHUNK, dtype=str):
        chunk = chunk[(chunk["inbound"].str.lower() == "true") & chunk["in_response_to_tweet_id"].isna()]
        for row in chunk.itertuples(index=False):
            text = clean(str(row.text))
            if len(text.split()) < 5 or not english_like(text):
                continue
            low = text.lower()
            cases = [k for k, rx in compiled.items() if rx.search(low)]
            if not cases or not isinstance(row.response_tweet_id, str):
                continue
            firsts[row.tweet_id] = {"tweet_id": row.tweet_id, "text": text, "cases": cases}
            for rid in row.response_tweet_id.split(","):
                reply_of[rid.strip()] = row.tweet_id
    print("pass 1:", len(firsts), "matching first tweets")

    # pass 2: who answered (the brand)
    for chunk in pd.read_csv(zf.open(member), usecols=["tweet_id", "author_id", "inbound"], chunksize=CHUNK, dtype=str):
        chunk = chunk[(chunk["inbound"].str.lower() == "false") & chunk["tweet_id"].isin(reply_of.keys())]
        for row in chunk.itertuples(index=False):
            first = firsts.get(reply_of[row.tweet_id])
            if first is not None and "brand" not in first:
                first["brand"] = row.author_id

    rng = random.Random(SEED)
    out = {"_note": "REAL tweets from TWCS (Kaggle, Thought Vector, CC BY-NC-SA 4.0); first user tweet of a thread; "
                    "@handles and links removed, nothing else changed. Candidates only (git-ignored). Seed 2026.",
           "shopnova": {}, "atlas": {}}
    for company, brands, cases in (("shopnova", SHOP_BRANDS, SHOP_CASES), ("atlas", TRAVEL_BRANDS, TRAVEL_CASES)):
        for case in cases:
            pool = [f for f in firsts.values() if f.get("brand") in brands and case in f["cases"]]
            rng.shuffle(pool)
            out[company][case] = [{"tweet_id": f["tweet_id"], "brand": f["brand"], "text": f["text"]}
                                  for f in pool[:PER_CASE]]
            print(company, case, len(pool), "found ->", len(out[company][case]))
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
