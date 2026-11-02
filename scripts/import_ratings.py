"""T30 (RL5): import the team's star ratings into style_log (source = real), so the style policy can learn from them.

    python -m scripts.import_ratings <filled file.xlsx> [--key out/rl1_rating_key.json] [--dry-run]
    python -m scripts.train_style_policy --source ratings        # then train on them

The file is the RL1 rating sheet the team returns (one tab per rater, Stars A / B / C). The key file says which letter
is which style. Each star rating becomes one style_log row: reward = (stars - 1) / 4, source = real, with the
situation (company, outcome, emotion, ...) and the reply that was rated.

The import STOPS with a clear message (nothing written) when the file cannot teach anything: identical tabs (the first
returned file had 6 copies of one tab), one value everywhere, or no stars at all.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from callverse.learning import rewards  # noqa: E402
from callverse.learning.style_policy import group_of  # noqa: E402
from scripts.train_style_policy import load_situations  # noqa: E402


def import_file(sheet: str | Path, key: str | Path, dry_run: bool = False) -> dict:
    """Read, check and (unless dry_run) save the ratings. Returns {"rows", "saved", "skipped", "raters"}.
    Raises rewards.RatingSheetError for an unusable file (nothing is saved then)."""
    rows = rewards.from_ratings(sheet, key)
    cases = {c["situation_id"]: c for c in load_situations()}
    saved, skipped = 0, []
    for r in rows:
        case = cases.get(r["situation_id"])
        if case is None:
            skipped.append(r["situation_id"])
            continue
        if not dry_run:
            from callverse.tickets import store
            sit = {**case["situation"], "situation_id": r["situation_id"], "rater": r["rater"]}
            store.add_style_log(sit, group_of(case["situation"]), r["style"], reply=case["replies"].get(r["style"]),
                                reward=r["reward"], source="real")
        saved += 1
    return {"rows": len(rows), "saved": saved, "skipped": sorted(set(skipped)),
            "raters": dict(Counter(r["rater"] for r in rows))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sheet", help="the filled rating file (.xlsx, or .csv for one rater)")
    ap.add_argument("--key", default=str(ROOT / "out" / "rl1_rating_key.json"))
    ap.add_argument("--db", help="tickets DB file (default: callverse/data/callverse.db)")
    ap.add_argument("--dry-run", action="store_true", help="check the file only, write nothing")
    args = ap.parse_args()
    if args.db:
        from callverse.tickets import store
        store.use_db(args.db)
    try:
        result = import_file(args.sheet, args.key, args.dry_run)
    except rewards.RatingSheetError as e:
        raise SystemExit(f"REJECTED: {e}")
    what = "checked (dry run, nothing saved)" if args.dry_run else "saved in style_log with source = real"
    print(f"{result['saved']} of {result['rows']} ratings {what}. Raters: {result['raters']}")
    if result["skipped"]:
        print(f"Skipped (situation not found in the RL1 runs): {result['skipped']}")


if __name__ == "__main__":
    main()
