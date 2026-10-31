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
7001-7012) -> `learning/style_policy.StylePolicy` (Thompson sampling per company|mood|outcome family|lateness)
-> `learning/style_writer.write(decision, style)` -> `quality/reward.evaluate_response` (connector-verified
correctness + satisfaction) -> reward -> policy update. Demo: `python scripts/run_rl_demo.py 30`.
Benchmark: `python -m benchmarks.agent_f.rl_eval` -> `benchmarks/agent_f/results/rl_eval.json`.

Data (all `source: simulated`, `callverse/learning/simulator.py`; personas TRAIN seed 101 / VAL 202 / EVAL 303,
disjoint): 69 situations x 3 styles x personas = train 2,484 rows (12 personas), val 1,242 (6), eval 1,242 (6);
25% of replies carry one of 4 corruptions (invented amount, unapproved refund, false delivery promise,
fabricated completed action). First messages = the AI-generated Intake reason examples. No real human rating
was used anywhere in this section.

| Satisfaction (EVAL personas, simulated ratings) | MAE | Spearman |
|---|---|---|
| fixed text + delay (production default) | 1.010 | -0.01 |
| predict the mean rating | 0.841 | 0 |
| **style candidate** (Ridge on 44 features, alpha 0.1, `models/agent_f/stacker_candidate.pkl`) | **0.699** | **0.59** |

Per company (eval): ShopNova candidate MAE 0.703 / rho 0.59; Atlas 0.693 / 0.57. Median style reward spread 0.87.
The candidate is NOT promoted to `stacker.pkl`: it was fitted on the simulator's own assumptions; real
human-rated validation is still pending.

Correctness (eval, 320 corrupted of 1,242): FAIL precision 1.00, recall 0.98, false-PASS rate 1.9 %, UNKNOWN 0 %.
Reward agreement with the oracle (true correctness + simulated rating): fixed 0.669, candidate 0.735.
Latency `evaluate_response` (connector reads + verifier + satisfaction): mean 3.5 ms, p95 4.4 ms.

| Style policy (greedy, EVAL personas) | avg simulated rating | share >= 4 |
|---|---|---|
| always short | 3.03 | 0.24 |
| random | 3.36 | 0.41 |
| rule-based (upset -> apology_first) | 3.54 | 0.49 |
| always apology_first | 3.54 | 0.50 |
| **always apology_next_step** | **3.61** | **0.56** |
| bandit, reward = Agent F (3,000 episodes, train personas) | 3.46 | 0.47 |
| bandit, reward = simulated rating | 3.47 | 0.47 |

Reading: the bandit beats always-short and random but not the best fixed style. In this simulator the style
effect is mostly global (apology + next step wins) and the persona archetype is not observable in the context,
so the group arms have little to separate; 3,000 noisy +1/-1 episodes are not enough to match the best arm.
These are simulator numbers: they show the loop learns, not that real customers are happier.
