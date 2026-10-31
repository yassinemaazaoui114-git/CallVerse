# RL3 report — Agent F satisfaction predictor (Semah)

## 1. In plain words
Agent F reads a finished conversation and guesses how satisfied the user is, from 1 to 5. It learned from real
product reviews with real star ratings, and it uses real ShopNova (Olist) data showing that late deliveries get
low scores. It runs in about 2 milliseconds on a normal CPU. It has not yet been checked on the team's own rated
conversations, because that file is not in the repo.

## 2. Done
- `callverse/quality/satisfaction.py` — `predict_satisfaction(record) -> {"score": float}` per RL_interface_spec v1.
- `benchmarks/agent_f/` — benchmark (model choice on validation), train (+ one test read), Olist delay table,
  `evaluate_rated.py` (MAE, Spearman, spec baselines, p95, worst errors).
- `tests/test_satisfaction.py` (5 tests), `docs/agent_f.md` (model card), `requirements.txt` (+scikit-learn).

## 3. Evidence
- Amazon test n=5000: MAE 0.644, Spearman 0.80; baseline predict-mean MAE 1.20. Results in `benchmarks/agent_f/results/`.
- Latency: mean 2.1 ms, p95 3.4 ms (CPU).
- Tests: 5/5 `tests/test_satisfaction.py`.

## 4. Problems
- Blend weights 0.5/0.5 are a fixed guess (no real data to fit them without touching the test set).
- Without the stacker, the score ignores `style` → constant reward across styles for the RL.
- Domain gap: reviews vs support chats.

## 5. Questions for the Brain
- Where is the Notion 31 rated set and in what format? (Assumed: JSONL of conversation records + `"rating"`.)
- OK to fit the stacker on Mahmoud's simulated ratings (flagged), so F becomes style-sensitive?

## 6. Next step
Run `evaluate_rated` on the team set once; fit the stacker when RL4 data exists; RL6 evaluation with Yassine.
