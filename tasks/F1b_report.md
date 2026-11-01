# F1b report — check Semah's agent F with his real model file

## 1. In plain words
Semah's model file works on our PC. We gave it 100 real Amazon reviews it had never trained on and asked it to guess
each star rating (1–5). It was off by about half a star on average and within one star 94 times out of 100, which is as
good as Semah's own result on 5000 reviews and far better than always guessing "3". It answers in about 1 millisecond
(the limit is 200 ms) and uses about 67 MB of memory. Nothing was trained, and the check was run once.

## 2. Done
- Step 0: committed `tasks/NEXT.md` + `tasks/F1b_agent_f_check.md` on `feat/t14d-request-match` ("NEXT: F1b (Brain)"), pushed;
  switched to `review/agent-f` (already up to date).
- Step 1: moved `models/satisfaction.pkl` → `models/agent_f/satisfaction.pkl` (git-ignored). Loads; made-up records give
  1.041 (angry, broken order) and 4.686 (happy).
- Step 2: downloaded only the Amazon **test** split with `benchmarks/agent_f/common.py` → `data/raw/amazon_reviews_multi_en/test.jsonl`
  (git-ignored). English only (`amazon_reviews_multi_en`).
- Step 3–5: new script `benchmarks/agent_f/check100.py` (one-shot check, no training). Sample = the project's own loader,
  `load("test", 100, seed=2026)` = plain seeded random draw, **not balanced** (his eval used the whole balanced test split;
  it has no sampling rule for a subset). Ids only → `benchmarks/agent_f/results/check100_ids.json`; numbers →
  `benchmarks/agent_f/results/check100.json`.
- Step 6: tests run, commit `9e00aab` pushed on `review/agent-f`. README: two lines under Agent F. **No merge.**

## 3. Evidence
| | value |
|---|---|
| Model file | 18,600,349 bytes (18.6 MB), SHA-256 `855f790f23694f4a6e5d66b5db59210535d074959fe737826e882081d680ccfa` |
| Test split download | 1,180,425 bytes (1.18 MB), 5000 reviews, 1000 per star |
| Sample (seed 2026, n=100) | stars 1:17 · 2:10 · 3:17 · 4:24 · 5:32 |

Scores on the 100 (score = expected stars from the class probabilities, as in his "expected" numbers; MAE / ±1 on the rounded score):

| | MAE | MAE raw | within ±1 | Spearman | exact |
|---|---|---|---|---|---|
| **Agent F, check100** | **0.55** | 0.5925 | **94 %** | **0.856** | 51 % |
| Baseline: training mean (3.0) | 1.32 | 1.32 | 51 % | — (constant) | 17 % |
| Baseline: delay-only rule | not possible: Amazon reviews have no delivery delay | | | | |
| His n=5000 (test_eval.json, expected) | 0.6054 | 0.6439 | 92.2 % | 0.802 | 48 % |

Size / speed on this PC (100 predictions, one record each, `predict_satisfaction(..., stacker=False)`):
- RAM (process working set): 163.0 MB before loading → 230.3 MB after → **+67 MB** for the model. Load time 0.11 s.
- **1.244 ms mean, 1.70 ms p95** per prediction (limit 200 ms).
- Tests: agent F **14/14**; full suite **1297/1297** (`.venv`, `--ignore=tests/data`, 139 s).
- Committed: `benchmarks/agent_f/check100.py`, `results/check100.json`, `results/check100_ids.json`, README. No model, no data.

## 4. Problems
- **sklearn version.** The pickle was made with scikit-learn **1.9.1**. The `.venv` has 1.9.1 (loads with no warning), but I
  ran the check with the system Python, which has **1.9.0** → `InconsistentVersionWarning` (no error). I did **not** re-run
  the check (run once). In `.venv` the two made-up records give the identical scores (1.041 / 4.686), so the result should
  be the same; RAM / ms were measured under the system Python.
- `psutil` is not installed; RAM is read with the Windows API through `ctypes` (no new library).
- The 100 reviews are a **subset of the same test split** Semah already scored (n=5000). So this check confirms that his file
  and his number match on our PC; it is not a new independent exam. The team's ~100 ratings stay the real final exam.
- n=100 is small: ±1 = 94 % has a 95 % range of roughly 88–97 %. The sample is not balanced (32 five-star, 10 two-star).
- Licence: Amazon reviews are non-commercial (already flagged in F1, accepted).

## 5. Questions for the Brain
1. Is the system-Python run (sklearn 1.9.0, warning only) acceptable, or do you want one re-run under `.venv` (1.9.1)?
   I would label it a version check, not a second exam.
2. Should agent F pin `scikit-learn==1.9.1` in `requirements.txt` (a pickle can break with another version)? That needs a task's OK.

## 6. Next step
Back to T14d (items 5–6, live runs on Monday). For agent F: wire it in only through RL1, and keep the team's ~100 ratings as the final exam.
