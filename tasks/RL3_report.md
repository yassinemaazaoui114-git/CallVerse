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
- Tests: 5/5 `tests/test_satisfaction.py`. Full suite: 975 passed, 78 failed; `main` alone gives 970 passed,
  78 failed in this sandbox (missing `sentence_transformers` / local models) -> no Agent F regression.
- Team real rated set (Notion 31): not found in the repo or any remote branch -> no real-conversation result yet.

## 4. Problems
- Blend weights 0.5/0.5 are a fixed guess (no real data to fit them without touching the test set).
- Without the stacker, the score ignores `style` → constant reward across styles for the RL. Fix proposed in
  `docs/agent_f.md` ("Style-insensitive reward").
- Domain gap: reviews vs support chats.

## 5. Questions for the Brain
- Where is the Notion 31 rated set and in what format? (Assumed: JSONL of conversation records + `"rating"`.)
- OK to fit the small stacker (style x emotion) on Mahmoud's TRAINING-persona ratings only?
- Can we get the Kaggle `ddosad` support CSAT set (real, closer domain) despite the shared-data risk?
- (old) OK to fit the stacker on Mahmoud's simulated ratings (flagged), so F becomes style-sensitive?

## 6. Next step
Run `evaluate_rated` on the team set once; fit the stacker when RL4 data exists; RL6 evaluation with Yassine.

## Update — full style-RL pipeline (branch feature/agent-f-rlhf-e2e)
Built, all offline and plain code: style writer (3 styles), simulated-feedback simulator (personas, 69 code-made
decisions, corruptions), Thompson-sampling style bandit, connector-verified correctness (PASS only when the facts
are re-read from the company's tools), response-aware satisfaction candidate, RL evaluation vs baselines, demo.
Numbers in docs/agent_f.md ("Style RL end to end"). Tests: 28/28 Agent F + RL tests. Everything is SIMULATED
feedback: the ~100 real rated conversations are still missing, so no real-customer claim is made.
Open: bandit does not beat the best fixed style on eval personas (see docs); stacker candidate not promoted.

## Update 2 — performance round (same branch, see docs/agent_f.md for every table)
- Satisfaction: HistGradientBoosting selected on VAL (MAE 0.656) over Ridge / ExtraTrees / RandomForest; EVAL once:
  MAE 0.688, Spearman 0.60 (fixed model 0.999 / 0.01, mean 0.856). Simulated labels only.
- Correctness: 0 / 291 false-PASS on EVAL (95 % CI 0-1.3 %) after three adversarial rounds; 2 real gaps fixed
  (stated delay / amount must equal the decision's fact), 12 mislabeled corruptions fixed in the simulator.
- RL: Beta/Gaussian Thompson, LinUCB (alpha on VAL), epsilon-greedy, supervised and counterfactual policies, 3-5 seeds.
  All learned policies win on VAL and lose on EVAL (3.47 vs fixed apology_next_step 3.59): the style preference is
  the hidden persona archetype. 40-persona check sets show the 6-persona flip was a persona-mix artefact: the mood rule
  learned on TRAIN scores 3.62 / 3.56 vs 3.50 / 3.55 for the best fixed style (small gain). Deployed: mood rule,
  fixed `apology_next_step` as fallback.
- Real writer: `write_with_slm` (Qwen via Ollama) with template fallback; Ollama absent here -> tested with a mocked model.
- Still missing: the ~100 real rated conversations (no real-customer claim is made anywhere).
