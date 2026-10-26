"""Worker F v5 — shared helpers: data paths, loading, metrics, paired bootstrap, Holm correction.

Why this file exists
  Every v5 F script (Ridge grid, neural training, evaluation, figures) must use the SAME splits, the SAME
  metric code and the SAME confidence-interval method, so their numbers can be compared. Metrics are imported
  from v3/f/bench_uss.py (not re-written) so v5 numbers are directly comparable with V3/V4.

Data: USS dialogue-level satisfaction (mean of 3-7 annotators' OVERALL ratings, 1-5), splits by dialogue
  TRAIN 4,740 / VAL 1,016 / TEST 1,016 (made by v3/f/uss_data.py, seed 13).
"""

import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent                       # v5/f
ROOT = HERE.parents[1]                                       # experiments/agents_ef
sys.path.insert(0, str(ROOT))

SCRATCH = Path("/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad")
FV3 = Path(os.environ.get("FV3", SCRATCH / "f_v3"))
FV5 = Path(os.environ.get("FV5", SCRATCH / "f_v5"))         # v5 checkpoints / large files (outside git)
DATA = FV3 / "data_uss"
V3_RESULTS = ROOT / "v3" / "f" / "results" / "uss"
RESULTS = HERE / "results"
FIG = HERE / "figures"
FREEZE = RESULTS / "FREEZE_candidates.json"                  # written BEFORE any v5 TEST scoring

DISSATISFIED = 2.5                                           # label <= 2.5 = dissatisfied subset (task spec)
HIGHLY_SATISFIED = 4.0                                       # label >= 4 = highly satisfied subset


def load(split, folder=DATA):
    return [json.loads(line) for line in open(Path(folder) / f"{split}.jsonl", encoding="utf-8")]


def y_of(rows):
    return np.array([r["rating"] for r in rows], float)


def metrics(y, p):
    """V3 metric set (MAE, RMSE, QWK on rounded labels, Spearman, per-class, confusion...)."""
    from v3.f.bench_uss import metrics as m3
    return m3(y, p)


def to_int(y):
    from v3.f.bench_uss import to_int as t
    return t(y)


def qwk(y, p):
    from sklearn.metrics import cohen_kappa_score
    return float(cohen_kappa_score(to_int(y), to_int(np.clip(p, 1, 5)), weights="quadratic", labels=[1, 2, 3, 4, 5]))


def spearman(y, p):
    from scipy.stats import spearmanr
    return float(spearmanr(y, p).statistic) if np.std(p) > 0 else float("nan")


def mae(y, p):
    return float(np.abs(np.clip(p, 1, 5) - y).mean())


def slope(y, p):
    """OLS slope of prediction on label: 1 = no shrinkage, 0 = constant prediction (regression to the mean)."""
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), 1, 5)
    return float(np.cov(y, p, bias=True)[0, 1] / np.var(y))


def paired_bootstrap(y, pa, pb, stat="mae", n=2000, seed=0, groups=None):
    """Paired bootstrap over TEST dialogues (each dialogue = one unit; splits are by dialogue, so units are
    independent). Returns diff = stat(b) - stat(a) with a 95% percentile CI and a two-sided bootstrap p-value.
    For MAE a negative diff means b is better; for Spearman/QWK a positive diff means b is better."""
    y, pa, pb = (np.asarray(v, float) for v in (y, pa, pb))
    pa, pb = np.clip(pa, 1, 5), np.clip(pb, 1, 5)
    f = {"mae": lambda yy, pp: np.abs(pp - yy).mean(), "spearman": spearman, "qwk": qwk,
         "rmse": lambda yy, pp: np.sqrt(((pp - yy) ** 2).mean())}[stat]
    rng = np.random.default_rng(seed)
    obs = f(y, pb) - f(y, pa)
    diffs = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        diffs.append(f(y[i], pb[i]) - f(y[i], pa[i]))
    diffs = np.array(diffs)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    # two-sided p: share of bootstrap diffs on the other side of 0 (centred percentile method), x2
    p = float(min(1.0, 2 * min((diffs <= 0).mean(), (diffs >= 0).mean())))
    return {"stat": stat, "a": float(f(y, pa)), "b": float(f(y, pb)), "diff_b_minus_a": float(obs),
            "ci95": [float(lo), float(hi)], "p_boot": p, "n_boot": n, "n": int(len(y))}


def holm(pvals: dict) -> dict:
    """Holm-Bonferroni step-down adjusted p-values for a dict {name: p}."""
    names = sorted(pvals, key=lambda k: pvals[k])
    m, out, run = len(names), {}, 0.0
    for i, k in enumerate(names):
        run = max(run, min(1.0, (m - i) * pvals[k]))
        out[k] = run
    return out


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=float))


def test_scoring_allowed(model_name: str) -> None:
    """Guard: TEST may only be scored for a model listed in the freeze file (written before any TEST scoring)."""
    if not FREEZE.exists():
        raise RuntimeError("TEST scoring refused: freeze file missing (" + str(FREEZE) + ")")
    fr = json.loads(FREEZE.read_text())
    if model_name not in fr["candidates"]:
        raise RuntimeError(f"TEST scoring refused: {model_name} not in the frozen candidate list")
