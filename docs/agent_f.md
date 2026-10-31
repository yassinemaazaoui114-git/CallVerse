# Agent F (RL3) — satisfaction predictor · model card

**Contract** (RL_interface_spec v1): `callverse.quality.satisfaction.predict_satisfaction(record) -> {"score": float 1..5}`.
CPU only, no API, no database write. Measured: ~2 ms mean, p95 3.4 ms per record (limit 200 ms).

## How it scores
1. **Text** (user turns only): TF-IDF (word 1-2 + char 2-5 grams) + logistic regression → expected stars.
2. **Delay prior**: `situation.days_late` → mean real Olist score for that delay (table below).
3. **Blend**: 0.5 text + 0.5 delay if `days_late` known, else text. **Provisional weights** — no real rated
   conversations exist for fitting (the team set is test-only).
4. **Optional stacker** (`models/agent_f/stacker.pkl`, Ridge on text, delay, style, emotion): fit on Mahmoud's
   SIMULATED ratings (flagged) when they exist. Without it the reward does **not** depend on `style`.

## Data
| Use | Source | Real? | Licence |
|---|---|---|---|
| Text model | `SetFit/amazon_reviews_multi_en` (60k train sample, 5k val, 5k test; balanced 1-5) | real stars | Amazon Reviews Multi licence: non-commercial research |
| Delay prior | ShopNova Olist sample (`callverse/data/real/`), review score vs delivered − promised | real | CC BY-NC-SA 4.0 |
| Final check | team ratings (Notion 31, ~100) | real | test only, never trained on |

Olist delay table (`python -m benchmarks.agent_f.olist_delay`): on time 4.22 (n=1801) · 1-2 d 3.07 (27) ·
3-5 d 2.50 (32) · 6-10 d 1.57 (35) · >10 d 1.40 (48).
Earlier simulated-only F experiments (`research/agents-e-f-tiny-models`) are not used: synthetic labels.

## Results — Amazon reviews (real stars)
Validation (model choice): TF-IDF+logreg MAE 0.638, Spearman 0.75 · TF-IDF+ridge MAE 0.696 (float) · predict-mean MAE 1.20.
Held-out test, n=5000 (read once), expected-stars output: **MAE 0.644, Spearman 0.80**, rounded accuracy 0.48, within ±1 0.92.
MiniLM not benchmarked (sentence-transformers not installed in build env). Fine-tuning not justified at 2 ms / budget 200 ms.

## Verified state (2026-10-31)
- Artifact: `models/agent_f/satisfaction.pkl` (18.6 MB, git-ignored), from `train.py`; no `stacker.pkl` yet.
- Selection: on validation only, argmax MAE (logreg 0.638 vs ridge 0.659). Test read once after.
- Reproducible: fixed 60k train sample (seed 0), deterministic solvers; `olist_delay.py` rebuilds the table.
- Spec file `RL_interface_spec.md` is not in the repo (shared by upload only).

## Style-insensitive reward (open)
Today F reads only user turns + `days_late`, so the same ticket gets the same score for every `style`.
Proposed fix (F side only; Mahmoud's `react()` unchanged):
1. Mahmoud runs `react(situation, reply, persona)` with the **training** persona set -> records
   `{conversation record, "rating", "source": "simulated"}` (JSONL, spec record shape).
2. F fits `stacker.pkl` (Ridge, few features: text, delay, style one-hot, emotion one-hot, style x emotion)
   on those records; choose alpha on a held-out simulator seed. Never on the evaluation persona set or team ratings.
3. Guard against circularity: Mahmoud's ratings come from his MiniLM scorer trained on real CSAT, so a big F would
   just copy it. Keep the stacker small and keep the real-data parts frozen; RL6 checks F on the team's real ratings.
4. Report F with and without the stacker on the team set; keep the stacker only if it is not worse there.

Extra real data seen (not used yet): Mahmoud's branch documents the Kaggle `ddosad` support CSAT set (85,907 contacts,
28,742 with a remark, customer-given 1-5) - closer to support chats than Amazon reviews. Not downloadable here
(Kaggle login); also shares data with the simulator's scorer (circularity risk above).

## Not yet measured
- Team real ratings: MAE, Spearman vs "predict average" and "delay-only" baselines → `python -m benchmarks.agent_f.evaluate_rated <file.jsonl>`.
- Domain gap: product reviews ≠ support chats; the team set is the real check.

## Rebuild
```
python -m benchmarks.agent_f.benchmark   # choose on validation
python -m benchmarks.agent_f.train       # train, save models/agent_f/satisfaction.pkl, test once
```

## Dual reward (correctness + satisfaction) — `callverse/quality/reward.py`
`evaluate_response(record) -> {"satisfaction", "correctness": PASS|FAIL|UNKNOWN, "reward": 1|-1|None, "train", "evidence"}`.
Record = spec conversation record + `"decision"` (Coordinator decision, `docs/decision_format.md`); the checked reply
is the last assistant message. Correctness reuses existing plain-code checks: `kb.policies.get_policy` (rule must be
in THIS company's file: tenant isolation), `kb.policies.check_condition` (rule condition vs decision facts),
`slm.check.check_reply` (numbers only from facts, no unapproved refund / forbidden promise, must_say). UNKNOWN when
decision, reply or facts are missing. Reward: PASS and satisfaction >= 4 -> +1, PASS and < 4 -> -1, FAIL -> -1,
UNKNOWN -> None (excluded from training). A friendly but wrong reply never gets +1.
Satisfaction stays the provisional text + Olist-delay proxy: it is **not** reply-aware until `stacker.pkl` is
promoted (see `docs/agent_f_style_reward.md`). Tests: `tests/test_agent_f_reward.py`.

## Style RL end to end (feature/agent-f-rlhf-e2e) — SIMULATED feedback
Flow: message -> decision (made by code from the live tool reads of the scripted orders 4505-4515 / bookings
7001-7012) -> style policy -> writer (`learning/style_writer.write_with_slm`: the real Qwen/Ollama SLM writer with the
style as an extra wording instruction, template `write()` when Ollama is missing or the SLM reply fails its check)
-> `quality/reward.evaluate_response` (connector-verified correctness + response-aware satisfaction) -> reward ->
policy update. Entry point: `callverse/learning/inference.py` (`respond`, `select_style`, `learn`).
Demo: `python scripts/run_rl_demo.py 30`. Reproduce everything (≈35 min CPU):
```
python -m benchmarks.agent_f.rl_eval --generate-only      # data/simulated/agent_f/{train,val,eval}.jsonl
python -m benchmarks.agent_f.compare_satisfaction         # models/agent_f/stacker_selected.pkl, results/satisfaction_models.json
python -m benchmarks.agent_f.rl_eval                      # results/rl_eval.json, models/agent_f/style_policy_*.json
python -m benchmarks.agent_f.policy_eval                  # results/policy_eval.json (selection on VAL)
python -m benchmarks.agent_f.persona_scale_eval           # results/persona_scale_eval.json
```

### Data (all `source: simulated`, `callverse/learning/simulator.py`)
Personas TRAIN seed 101 (12) / VAL 202 (6) / EVAL 303 (6), disjoint; 69 situations x 3 styles x personas =
train 2,484 / val 1,242 / eval 1,242 rows. 25 % of replies carry one of 9 corruptions (invented amount, unapproved
refund, false delivery promise, fabricated completed action, wrong amount, voucher over-claim, contradiction, stale
fact, false approval; a corruption is always a real error for that decision), 15 % one of 2 degradations
(incomplete, generic: correct but weaker). First messages = AI-generated Intake reason examples. No real human
rating anywhere in this section. Simulator audit (eval, mean rating): clean 3.38 · incomplete 3.14 · generic 2.37 ·
wrong replies 1.86-2.51 -> the simulated rating does respond to reply quality.

### Satisfaction model (fit TRAIN, selected on VAL, EVAL read once) — `results/satisfaction_models.json`
| model (44 features: user text score, Olist delay, style, emotion, style x emotion, reply length / apology / next-step / outcome) | VAL MAE | VAL Spearman | VAL pairwise style pref. acc | calib. err | ms/row |
|---|---|---|---|---|---|
| fixed text + delay (production default) | 0.956 | 0.01 | 0.44 | 0.77 | - |
| mean of train | 0.771 | 0 | - | 0.03 | - |
| Ridge (alpha 0.1 / 1 / 10) | 0.691 / 0.691 / 0.690 | 0.52 | 0.68 | 0.10 | <0.01 |
| Ridge + style x reply cross | 0.698 | 0.51 | 0.66 | 0.13 | <0.01 |
| **HistGradientBoosting (300 it, lr 0.05, depth 4)** | **0.656** | **0.57** | 0.69 | 0.11 | 0.005 |
| ExtraTrees (300, leaf 5) | 0.675 | 0.56 | **0.70** | 0.15 | 0.07 |
| RandomForest (300, leaf 5) | 0.660 | 0.56 | 0.68 | 0.12 | 0.05 |

Selected HistGBM on EVAL (once): MAE 0.688, Spearman 0.60, pairwise 0.69, calibration 0.08; ShopNova 0.678 / 0.60,
Atlas 0.704 / 0.60; anger 0.681 / 0.64, neutral 0.702 / 0.52; by reply quality: clean 0.58, degraded 0.55,
wrong 1.06 (the wrong replies are the hard part: whether the simulated customer "notices" is random).
Fixed on EVAL: 0.999 / 0.01; mean-of-train 0.856. Saved as `models/agent_f/stacker_selected.pkl` (used by the RL loop
and the demo); **not** promoted to the production `stacker.pkl`: trained on the simulator's own labels.
MiniLM / fine-tuned transformers not run: `sentence-transformers` is not installed here and a 1.5k-row synthetic
set does not justify it. Amazon-review MAE (0.644, real stars) and simulated-support MAE are different benchmarks.

### Correctness (EVAL, 1,242 replies, 291 wrong) — `results/rl_eval.json`
False-PASS **0 / 291** (Wilson 95 % CI 0-1.3 %), FAIL precision 1.00, recall 1.00, UNKNOWN 0 %, false-FAIL 0 / 951
clean. Before the adversarial round: 6 / 320 (1.9 %), then 8 / 291 — every case was inspected: 12 were label bugs
(a "corruption" that was true for that decision, fixed in the simulator) and 2 were a real gap (a delay value allowed
by the next step passed off as the order's own delay) fixed by the stated-fact check. Fresh adversarial cases live in
`tests/test_rl_pipeline.py` (`test_new_adversarial_cases_never_pass`, `test_stated_fact_values_must_match_the_decision`).
Reward agreement with the oracle (true correctness + simulated rating): fixed 0.685, selected 0.744.
Latency `evaluate_response` (connector re-reads + verifier + HistGBM): mean 6.0 ms, p95 7.9 ms.

### Style policy vs fixed styles — `results/policy_eval.json` (greedy, 3 evaluation seeds, mean rating)
| policy | VAL (6 personas) | EVAL (6 personas) ± sd |
|---|---|---|
| always short | 3.22 | 3.02 ± 0.04 |
| always apology_first | 3.26 | 3.52 ± 0.02 |
| always apology_next_step | 3.45 | **3.59 ± 0.03** |
| random | 3.30 | 3.36 ± 0.05 |
| rule: upset -> apology_first, else short | 3.46 | 3.51 ± 0.04 |
| rule by mood learned on TRAIN (upset -> apology_next_step, calm -> short) | **3.55** | 3.46 ± 0.05 |
| supervised best style per observable group (TRAIN) | **3.55** | 3.46 ± 0.05 |
| Agent F counterfactual argmax (write 3 styles, keep the best predicted) | - | 3.54 (CI 3.46-3.61) |
| LinUCB (alpha 2.0 chosen on VAL; 3 train seeds) | 3.54 ± 0.00 | 3.47 ± 0.00 |
| Gaussian Thompson on Agent F score (3 train seeds) | 3.54 ± 0.01 | 3.47 ± 0.00 |
| Beta Thompson on the ±1 reward (5 seeds, rl_eval) | - | 3.47 ± 0.06 |
| epsilon-greedy on the ±1 reward (5 seeds) | - | 3.37 ± 0.22 (unstable: the ±1 signal is almost always -1) |
| rule read off the EVAL audit (upset -> apology_first, calm -> apology_next_step) | 3.36 | 3.65 (excluded: leakage) |

Reading. (1) Every learned or train-derived policy wins on VAL (3.54-3.55 vs 3.45 for the best fixed style) and
loses on EVAL (3.46-3.47 vs 3.59): the policies learn the TRAIN personas' taste, and the ranking of styles flips
between persona sets (train audit: calm customers prefer short; eval audit: calm prefer apology + next step).
The style preference in this simulator is driven by the hidden persona archetype, which no observable context
carries; see `results/persona_scale_eval.json` for the check with 40-persona sets. (2) The ±1 reward is too sparse
(most predicted scores are < 4 -> almost all -1): the continuous Agent F score (Gaussian Thompson, LinUCB) learns
stably; the ±1 variants do not. (3) Honest selection on VAL picks the mood rule learned on TRAIN (EVAL 3.46);
the most robust choice across both sets is the fixed `apology_next_step` (never worst, best on EVAL), kept as
`inference.DEFAULT_STYLE`. On the 6-persona EVAL no learned policy beats the best fixed style; the 40-persona check
below shows this is a persona-mix artefact and that the learned mood rule transfers (small gain). Real customers
may differ: this needs the real rated conversations. Hallucination rate of the deployed fixed style on EVAL: 0 %
(414 clean replies, 0 FAIL); end-to-end success (PASS and rating >= 4) 0.56.

### Persona-set size check — `results/persona_scale_eval.json` (40 personas per set, seeds 404 / 505)
| policy | VAL40 ± sd | EVAL40 ± sd |
|---|---|---|
| always short | 3.20 ± 0.01 | 3.18 ± 0.01 |
| always apology_first | 3.28 ± 0.01 | 3.27 ± 0.00 |
| always apology_next_step | 3.50 ± 0.01 | 3.55 ± 0.01 |
| rule: upset -> apology_first, else short | 3.61 ± 0.01 | 3.49 ± 0.01 |
| **rule by mood learned on TRAIN** | **3.62 ± 0.01** | **3.56 ± 0.01** |
| Gaussian Thompson trained on the 12 TRAIN personas (3 train seeds) | 3.61 ± 0.00 | 3.56 ± 0.01 |

Archetype mix: EVAL6 had 3 "warm" personas out of 6 (train: 1 of 12), which is why the 6-persona EVAL favoured the
apology styles. With 40-persona sets the train-learned policies beat the best fixed style on VAL40 (+0.12, sd 0.01)
and tie or edge it on EVAL40 (+0.01, within noise). Conclusion: the loop learns a transferable mood -> style rule;
the gain over the best fixed style is small and persona-mix dependent. Deployed default (`inference.select_style`):
the train-learned mood rule, selected on VAL; `apology_next_step` stays the fallback without an emotion.

### Experiment log
| experiment | split | result | decision |
|---|---|---|---|
| text model: TF-IDF ridge vs logreg | Amazon val 5k | logreg MAE 0.638 vs 0.659 | logreg; test once 0.644 / rho 0.80 |
| response-aware model family | sim train/val | HistGBM 0.656 best val MAE | HistGBM; eval once 0.688 |
| verifier adversarial rounds 1-3 | sim eval | 1.9 % -> 2.7 % (new labels) -> 0 % false-PASS | stated-fact check added |
| bandit algorithms x reward source, 5 seeds | sim train -> eval | best 3.49 (Gaussian Thompson) < fixed 3.59 | fixed style kept |
| LinUCB alpha {0.1, 0.5, 1, 2} | sim val | 3.40 / 3.40 / 3.55 / 3.55 | alpha 2.0 |
| policy selection | sim val -> eval | mood rule 3.55 val -> 3.46 eval | persona-set flip documented |
| persona-set size 6 -> 40 | sim val40 / eval40 | mood rule 3.62 / 3.56 vs fixed 3.50 / 3.55 | mood rule deployed, fixed fallback |
