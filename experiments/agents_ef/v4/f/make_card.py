"""Validation cards for the satisfaction scorers (what each model was measured on), read by M7 v4 and AgentF.

    python -m v4.f.make_card --fv3 <f_v3>

A card holds only MEASURED numbers: USS TEST predictions stored by the V3 benchmark (best seed by VAL) against the
USS TEST labels, the mean baseline (TRAIN mean of the same languages) and a bootstrap 95% CI of Spearman
(v3/m7/report.card_from_f, unchanged). v4 adds `corpus` ("uss": NOT CallVerse) so M7 can tell that the domain is not
validated. Output: v4/f/results/card_<model>.json
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v3.m7.report import card_from_f  # noqa: E402

CARDS = {"tfidf_ridge_tail256": "tfidf_ridge_tail256tok.json",
         "e5small_trim_ft_L6_frac0.5_len256": "e5small_trim_ft_L6_frac0.5_len256.json",
         "tinybert_ft_en_frac0.5_len128": "tinybert_ft_en_frac0.5_len128.json"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fv3", required=True)
    a = ap.parse_args(argv)
    for model, res in CARDS.items():
        card = card_from_f(HERE.parents[1] / "v3/f/results/uss" / res, Path(a.fv3) / "data_uss/test.jsonl",
                           "human_annotation", "task_oriented_dialogue")
        card.update(corpus="uss", model_key=model,
                    languages_validated=["en"] if "tinybert" in model else ["en", "zh"],
                    note="USS = third-party annotator judgements of task-oriented dialogues (EN) and JDDC "
                         "e-commerce service (ZH); not customer ratings, not CallVerse conversations")
        (HERE / "results" / f"card_{model}.json").write_text(json.dumps(card, indent=1))
        print(model, {k: card[k] for k in ("test_n", "mae", "mae_mean_baseline", "spearman", "spearman_ci_low")})


if __name__ == "__main__":
    main()
