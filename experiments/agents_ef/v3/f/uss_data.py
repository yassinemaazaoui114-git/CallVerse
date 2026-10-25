"""USS (User Satisfaction Simulation, Sun et al. SIGIR 2021) -> Agent F dialogue-satisfaction subsets.

    python v3/f/uss_data.py --raw <folder with SGD.txt MWOZ.txt ReDial.txt CCPE.txt JDDC.txt> \
        --out <f_v3 data folder, OUTSIDE git> --stats v3/f/results/uss_stats.json

Raw format (github.com/sunnweiwei/user-satisfaction-simulation, dataset/*.txt), one line per utterance:
    ROLE \t text \t action \t ratings "3,3,4" (USER lines only) [\t explanation (JDDC dialogue level)]
Dialogues are separated by blank lines. The last line of each dialogue is "USER \t OVERALL \t \t r1,r2,r3":
the DIALOGUE-LEVEL satisfaction given by several annotators. That is the Agent F target here.

Target (primary): mean of the annotators' OVERALL ratings (1-5), predicted AFTER the dialogue ends from the
full dialogue text (USER/SYSTEM turns, OVERALL line removed). No future information: the input is exactly
what exists when the interaction has ended.
Splits: 70/15/15 by DIALOGUE (each dialogue is one example), stratified per sub-dataset, fixed seed 13.
So no turn of a dialogue can leak across splits. Test is written once and only scored once.
"""

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np

FILES = {"SGD": "en", "MWOZ": "en", "ReDial": "en", "CCPE": "en", "JDDC": "zh"}


def parse(path):
    """Yield dialogues: {'turns': [(role, text, action, [ratings])], 'overall': [ratings], 'expl': str}."""
    dialogues, cur = [], []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.strip():
            if cur:
                dialogues.append(cur)
            cur = []
            continue
        cur.append(line.split("\t"))
    if cur:
        dialogues.append(cur)
    out = []
    for d in dialogues:
        turns, overall, expl = [], None, ""
        for parts in d:
            parts += [""] * (5 - len(parts))
            role, text, act, rat, ex = parts[:5]
            r = [int(x) for x in rat.split(",") if x.strip().isdigit()]
            if role == "USER" and text == "OVERALL":
                overall, expl = r, ex
            else:
                turns.append((role, text, act, r))
        out.append({"turns": turns, "overall": overall, "expl": expl})
    return out


def render(turns, lang):
    """Dialogue as plain text, one turn per line. 'Customer'/'Agent' tags match how CallVerse logs a chat."""
    tag = {"USER": "Customer", "SYSTEM": "Agent"} if lang == "en" else {"USER": "客户", "SYSTEM": "客服"}
    return "\n".join(f"{tag.get(role, role)}: {text}" for role, text, _, _ in turns)


def krippendorff_interval(units):
    """Krippendorff's alpha (interval metric) for a list of units, each a list of ratings (>=2 per unit)."""
    units = [u for u in units if len(u) >= 2]
    vals = np.concatenate([np.array(u, float) for u in units])
    n = len(vals)
    do = 0.0
    for u in units:
        u = np.array(u, float)
        m = len(u)
        do += ((u[:, None] - u[None, :]) ** 2).sum() / (m - 1)
    do /= n
    # sum over all ordered pairs of (x_i - x_j)^2 = 2 * (n * sum(x^2) - sum(x)^2), no n x n matrix needed
    de = 2 * (n * (vals ** 2).sum() - vals.sum() ** 2) / (n * (n - 1))
    return float(1 - do / de) if de > 0 else float("nan")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stats", required=True)
    ap.add_argument("--seed", type=int, default=13)
    a = ap.parse_args(argv)
    raw, out = Path(a.raw), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, stats = [], {"files": {}, "split_rule": "70/15/15 by dialogue, stratified per sub-dataset, seed 13"}
    for name, lang in FILES.items():
        p = raw / f"{name}.txt"
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        ds = parse(p)
        n_turn = sum(len(d["turns"]) for d in ds)
        user_ratings = [t[3] for d in ds for t in d["turns"] if t[0] == "USER" and t[3]]
        ov = [d["overall"] for d in ds if d["overall"]]
        texts = [render(d["turns"], lang) for d in ds]
        dup = len(texts) - len(set(texts))
        n_ann = Counter(len(o) for o in ov)
        mean_ov = [float(np.mean(o)) for o in ov]
        exact_agree = float(np.mean([len(set(o)) == 1 for o in ov]))
        pair_abs = float(np.mean([abs(x - y) for o in ov for i, x in enumerate(o) for y in o[i + 1:]]))
        # each annotator vs the mean of the others (how well ONE human predicts the panel): human-level MAE
        loo = [abs(o[i] - np.mean(o[:i] + o[i + 1:])) for o in ov if len(o) >= 2 for i in range(len(o))]
        stats["files"][name] = {
            "sha256": sha, "lang": lang, "dialogues": len(ds), "dialogues_with_overall": len(ov),
            "utterances_excl_overall": n_turn, "user_turns_rated": len(user_ratings),
            "avg_turns": round(n_turn / len(ds), 1),
            "annotators_per_dialogue": dict(sorted(n_ann.items())),
            "overall_rating_counts_all_annotations": dict(sorted(Counter(x for o in ov for x in o).items())),
            "overall_mean_rounded_counts": dict(sorted(Counter(int(np.clip(np.floor(m + 0.5), 1, 5))
                                                                 for m in mean_ov).items())),
            "overall_mean": round(float(np.mean(mean_ov)), 3), "overall_std": round(float(np.std(mean_ov)), 3),
            "turn_rating_counts_all_annotations": dict(sorted(Counter(x for r in user_ratings for x in r).items())),
            "overall_all_annotators_agree": round(exact_agree, 3),
            "overall_mean_pairwise_abs_diff": round(pair_abs, 3),
            "overall_krippendorff_alpha_interval": round(krippendorff_interval(ov), 3),
            "turn_krippendorff_alpha_interval": round(krippendorff_interval(user_ratings), 3),
            "human_loo_mae_vs_other_annotators_mean": round(float(np.mean(loo)), 3),
            "duplicate_dialogue_texts": dup,
            "has_dialogue_explanations": any(d["expl"] for d in ds),
        }
        seen = set()
        for i, (d, t) in enumerate(zip(ds, texts)):
            if not d["overall"] or t in seen:          # drop unrated and exact-duplicate dialogues
                continue
            seen.add(t)
            n_user = sum(1 for x in d["turns"] if x[0] == "USER")
            last_user = [x for x in d["turns"] if x[0] == "USER" and x[3]]
            rows.append({"id": f"{name}-{i}", "sub": name, "lang": lang, "text": t,
                         "rating": float(np.mean(d["overall"])), "ratings": d["overall"],
                         "n_turns": len(d["turns"]), "n_user_turns": n_user, "n_chars": len(t),
                         "turn_ratings_mean": [round(float(np.mean(x[3])), 3) for x in d["turns"]
                                               if x[0] == "USER" and x[3]],
                         "last_turn_rating": float(np.mean(last_user[-1][3])) if last_user else None})
    rng = random.Random(a.seed)
    split_counts = {}
    for name in FILES:
        sub = [r for r in rows if r["sub"] == name]
        rng.shuffle(sub)
        n = len(sub)
        cut1, cut2 = int(0.7 * n), int(0.85 * n)
        for j, r in enumerate(sub):
            r["split"] = "train" if j < cut1 else "val" if j < cut2 else "test"
        split_counts[name] = {"train": cut1, "val": cut2 - cut1, "test": n - cut2}
    for sp in ("train", "val", "test"):
        with open(out / f"{sp}.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                if r["split"] == sp:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ids = {sp: {r["id"] for r in rows if r["split"] == sp} for sp in ("train", "val", "test")}
    assert not (ids["train"] & ids["test"] or ids["train"] & ids["val"] or ids["val"] & ids["test"])
    stats["split_counts"] = split_counts
    stats["split_sha256"] = {sp: hashlib.sha256((out / f"{sp}.jsonl").read_bytes()).hexdigest()
                             for sp in ("train", "val", "test")}
    Path(a.stats).parent.mkdir(parents=True, exist_ok=True)
    Path(a.stats).write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=1)[:4000])


if __name__ == "__main__":
    main()
