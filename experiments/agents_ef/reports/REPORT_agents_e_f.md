> **Superseded for current conclusions by `REPORT_v2_agents_e_f.md` (2026-10-23): Intake-aware Agent E, EN/FR Agent F on genuine ratings.** This file is kept as the record of rounds 1-2.

# Agents E (M6) and F (M7): tiny-model research report

Branch: `research/agents-e-f-tiny-models` (from `main` @ `4cba464`). Folder: `experiments/agents_ef/`.
Date: 2026-10-23. Hardware used: cloud sandbox, 4 CPU cores, 15 GB RAM, **no GPU**.

**Labels used on every claim**
- RESEARCHED = from literature or reasoning, not run here.
- IMPLEMENTED = code written.
- TESTED = covered by passing pytest tests.
- TRAINED = model trained here.
- BENCHMARKED = measured here on held-out TEST data.
- NOT VERIFIED = not run or not measured here.

> **Read this first.**
> - All Agent E numbers come from **our own simulator**.
> - All Agent F numbers come from **simulated** satisfaction data (labels made by a formula plus noise, text made from templates).
> - None of this is real ShopNova or customer data, and nothing here proves real-world performance.
> - No GPU numbers were measured. The RTX 4050 script exists but has **not been run** (NOT VERIFIED).
> - CLAUDE.md lists agents E and F as **out of scope for the prototype**. This work is isolated research: nothing in `callverse/` changed, and nothing is merged into `main`. Integration needs Brain + Yassine approval.

> **Update 2026-10-23: first validation on real data (section 14).**
> - On genuine 1–5 review scores (public Olist data, Portuguese), TinyBERT **loses** its lead: MAE 0.78–0.85, worse than TF-IDF at 0.76. A multilingual MiniLM wins: **MAE 0.59**.
> - With the real demand shape, a tuned heuristic **matches** the RL agent on overall return. RL keeps an edge on urgent tickets, but only after retraining.
> - Your own CallVerse files are still **not verified**: they live on your PC.

---

## 1. In plain words

**Agent E (resource allocation)**
- We built a small simulated call centre: 4 queues, AI "sessions" that can be moved between queues, a budget, and a cheap "fallback" mode.
- We trained tiny learning agents to run it.
- The best one is a **dueling double DQN with 7,378 numbers (parameters)**. It decides in about 0.1 ms on a laptop CPU.
- At the **same cost** as a well-tuned hand-written rule, it reaches the response-time target slightly more often (+0.7 points overall, +5.7 points for urgent tickets).
- It never broke a safety rule in testing.

**Agent F (satisfaction prediction)**
- A **small fine-tuned TinyBERT (14M parameters)** predicted satisfaction (1–5) best: average error 0.35 stars on unseen phrasings.
- That holds on simulated data only.

**One shared model for E and F**
- We tested it for real (three designs × three seeds). It saved almost nothing and made Agent E slightly worse at urgent tickets.
- **Recommendation: keep E and F as two separate small models.**

---

## 2. GitHub safety audit (before any work)

**What was checked**
- Audit date: 2026-10-23, read-only.
- `main` = `4cba464` and did not change during the work.
- One PR is open: `yassinemaazaoui114-git/callverse#1` (I01 voice integration). It is not merged and has 9 conflicts with main.
- No Agent E or Agent F code existed on any branch.

**Branches compared with `origin/main`**

| Component / branch | Ahead / behind main | Implemented? | Tested? | Integrated into main? | Missing work |
|---|---|---|---|---|---|
| feature/intake, pipeline, agent-b, coordinator, reply, slm, sim-clock, s3-notify, live-check, demo-screen, platform | 0 ahead | yes | yes (main suite) | yes (fully merged) | none for this research |
| feature/t10b | 2 ahead, 0 behind | yes | not checked here | no | owner review/merge (not ours) |
| feature/voice | 1 ahead, 27 behind | yes (V01) | yes | no | review/merge by owners |
| feature/multimodal-voice-backup | 1 ahead, 41 behind | backup only | — | no | none (archive) |
| integration/platform-voice (PR #1) | 9 ahead, 27 behind, 9 conflicts | yes (I01) | yes | no | conflict resolution + approval |
| Agent E (M6) | — | **only on this research branch** | 41 research tests | no | approval, real data, integration task |
| Agent F (M7) | — | **only on this research branch** | yes | no | real labelled data, integration task |

**What this work did and did not touch**
- Nothing outside `experiments/agents_ef/` was modified.
- The only other change is one `.gitignore` line, which ignores the regenerable F dataset.
- No teammate branch, no `main`, no voice, Agent B, Coordinator or SLM code was touched.
- No merge, no force-push, no secrets.

---

## 3. Agent E: environment (IMPLEMENTED, TESTED)

**Code**
- `env/callcenter_env.py`: pure numpy, Gymnasium-style `reset()` / `step()`. No new library.
- 27 tests in `tests/test_env.py`, all passing.

**Model of the day**
- 4 queues: A status, B refund, C urgent, D availability.
- A day lasts 8 h, split into 96 steps of 5 minutes.
- Each queue has its own priority weight, SLA target, customer patience, service time and arrival rate.
- Arrivals are Poisson, with two daily peaks and a random intensity per day.

**Actions (17)**
- keep;
- move one session from queue i to queue j (12 actions);
- fallback on / off (only queues A and D may use fallback);
- activate / deactivate one session.

**Safety layer (hard rules the agent cannot break)**
- An action mask, plus a check inside `step()`. An invalid action becomes "keep" and is counted as a violation.
- Fixed limits:
  - at least 6 active sessions;
  - at least 2 sessions on the urgent queue;
  - at most 24 sessions;
  - a budget cap of 1.15 × the planned cost;
  - fallback is never used on urgent or refund tickets.

**Reward (balanced preset)**
- `served - 2·abandoned - 0.5·cost + 1·SIM-CSAT`.
- Each term is normalised.
- Other presets: `cost_heavy` and `sla_heavy`.

**SIM-CSAT**
- A **temporary formula, not Agent F**: `5 - 2·late_fraction - 0.6·fallback - |noise|`, clipped to 1–5.
- An abandoned ticket counts as 1.

**Scenarios**
- normal, high, spike, drift, slowdown, failure.
- **compound** (spike + failure + slowdown together) appears **only in TEST**, as an out-of-distribution check.

**Data splits** (`configs/splits.json`, checked by tests)
- TRAIN: random days, seeds 0–19999.
- VAL: 30 fixed days. Used for checkpoint choice, model size and heuristic tuning.
- TEST: 56 fixed days. Scored **once**, at the end.

**Limitations**
- Service times are exponential.
- There is no skill mix inside a queue.
- One action per 5 minutes.
- The rates are invented, not fitted to ShopNova data.

---

## 4. Agent E: candidates and why

| Candidate | Why it is in the comparison | Status |
|---|---|---|
| Fixed, Threshold, Priority | simple rules a call centre really uses; lower bound | IMPLEMENTED, BENCHMARKED |
| Forecast (EWMA + square-root staffing, Erlang rule of thumb) | the strongest classical method; the bar RL must beat | IMPLEMENTED, BENCHMARKED |
| Tabular Q (72 states) | the smallest possible RL; shows whether a function approximator is needed | TRAINED, BENCHMARKED |
| DQN | standard value-based RL for discrete actions | TRAINED, BENCHMARKED |
| Double DQN | fixes DQN's over-estimation (RESEARCHED: van Hasselt 2016) | TRAINED, BENCHMARKED |
| Dueling Double DQN | separates "how good is this state" from "which action"; helps when most actions do little (RESEARCHED: Wang 2016) | TRAINED, BENCHMARKED |
| PPO (masked, GAE) | the most common policy-gradient method; a stable on-policy reference | TRAINED, BENCHMARKED |

**Candidates not run (RESEARCHED only)**
- SAC / TD3: built for continuous actions; our actions are discrete.
- Rainbow / C51: more parts than a 7k-parameter policy needs.
- Offline RL (CQL): there is no logged real data yet.
- Model-based RL / MPC: a possible next step once real arrival data exists.

**Training setup**
- CPU only.
- 150,000 environment steps per run.
- 3 seeds per algorithm.
- Hidden size 64×64.
- The checkpoint is chosen on VAL return.

---

## 5. Agent E: results (BENCHMARKED on TEST, simulator only)

**Balanced reward, 56 TEST days, mean ± std over 3 training seeds** (`results/agent_e/summary.json`)

Units:
- Return: higher is better.
- SLA, urgent SLA and abandonment: % of tickets.
- Wait: minutes.
- CSAT: SIM-CSAT on a 1–5 scale.
- Cost: session-steps.

| Rank | Policy | TEST return | SLA | Urgent SLA | Abandon | Mean wait | p95 wait | SIM-CSAT | Cost | Violations | Compound (OOD) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Dueling Double DQN** | **106.83 ± 0.51** | 96.81 | 88.75 | 1.71 | 2.44 | 7.9 | 4.632 | 1293 | 0 | 99.95 |
| 2 | DQN | 106.68 ± 0.14 | 96.89 | 88.32 | 1.64 | 2.30 | 7.6 | 4.637 | 1313 | 0 | 98.8 |
| 3 | Double DQN | 106.10 ± 0.38 | 96.47 | 88.56 | 2.02 | 2.56 | 8.4 | 4.629 | 1290 | 0 | 97.9 |
| — | Forecast z=0 (z tuned on VAL) | 106.25 | 96.14 | 83.17 | 1.99 | — | — | 4.63 | 1289 | 0 | — |
| 4 | Forecast z=0.5 (default) | 104.93 | 98.03 | 92.63 | 1.09 | 1.84 | 6.6 | 4.687 | 1454 | 0 | 99.76 |
| 5 | PPO | 104.56 ± 0.62 | 96.35 | 85.42 | 1.87 | 2.34 | 7.9 | 4.646 | 1352 | 0 | 95.8 |
| 6 | Priority | 97.79 | 96.95 | 96.93 | 2.54 | 2.91 | 9.4 | 4.609 | 1536 | 0 | 89.7 |
| 7 | Threshold | 97.64 | 96.68 | 86.02 | 1.80 | 2.03 | 7.5 | 4.636 | 1536 | 0 | 91.3 |
| 8 | Fixed | 93.11 | 94.41 | 89.73 | 3.64 | 2.51 | 10.0 | 4.563 | 1536 | 0 | 78.9 |
| 9 | Tabular Q | 90.55 ± 0.19 | 93.25 | 85.31 | 4.31 | 3.03 | 11.5 | 4.390 | 1373 | 0 | 80.2 |

**Fair comparison at equal cost** (`bench/frontier.py`, `bench/frontier_gap.py`, `results/frontier/`)
- **Method:**
  - Return alone mixes service and cost, so the Forecast rule was swept over its safety factor z (from −0.5 to 1.5).
  - This traces the rule's cost-versus-service curve.
  - Each RL run is then compared with that curve **at the same cost**, using linear interpolation.
- **Results:**

| TEST, gap vs heuristic at equal cost | SLA | Urgent SLA | Abandon (− = better) | SIM-CSAT |
|---|---|---|---|---|
| Dueling Double DQN | **+0.74 ± 0.40** | **+5.70 ± 2.41** | −0.33 ± 0.17 | +0.01 |
| Double DQN | +0.47 ± 0.47 | +5.82 ± 1.21 | −0.06 ± 0.32 | +0.01 |
| DQN | +0.44 ± 0.16 | +3.57 ± 1.50 | −0.21 ± 0.14 | 0.00 |
| PPO | −0.70 ± 0.16 | −2.18 ± 0.65 | +0.32 ± 0.11 | −0.01 |

- The same signs appear on VAL. For example, dueling on VAL: SLA +0.93, urgent SLA +7.09.
- **Reading:**
  - The DQN family sits **above** the tuned heuristic's curve: better urgent service for the same money.
  - The gain is real but **modest**.
  - With z tuned on VAL, the heuristic's TEST return (106.25) is only 0.6 below the best RL agent.
  - PPO is below the curve.

**Model size** (dueling DDQN; size chosen on VAL, TEST shown; `results/agent_e_size/`)

| Hidden size | Parameters | TEST return | Urgent SLA |
|---|---|---|---|
| 32×32 | 2,674 | 105.99 ± 0.08 | 84.84 |
| **64×64** | **7,378** | **106.83 ± 0.51** | 88.75 |
| 128×128 | 22,930 | 105.61 ± 1.12 | 86.45 |

Bigger is not better here. 128×128 is less stable across seeds.

**Reward hacking found (BENCHMARKED, `results/agent_e_sla/`)**
- With the `sla_heavy` reward, RL agents sent **55–70% of simple tickets to fallback mode**. The heuristics sent 1–5%.
- This cuts cost to about 1130–1145 and keeps the SLA high, but SIM-CSAT falls to 4.37–4.41 (Forecast: 4.69).

| sla_heavy | Return | SLA | SIM-CSAT | Cost | Fallback share |
|---|---|---|---|---|---|
| DQN | 68.37 | 97.13 | 4.407 | 1129 | 0.55 |
| Dueling DDQN | 68.19 | 97.41 | 4.388 | 1141 | 0.63 |
| PPO | 65.62 | — | 4.369 | 1144 | 0.70 |
| Forecast | 66.01 | 98.03 | 4.687 | 1454 | 0.008 |

- **Lesson:** the reward weights are a business decision, not a tuning knob.
- A real deployment needs:
  - a cap on fallback share (a Coordinator rule);
  - satisfaction from Agent F, not the formula.

**Compute (CPU, this sandbox)**

| | Parameters | Checkpoint | Decision latency p50 | Training time | Training peak RAM |
|---|---|---|---|---|---|
| Dueling DDQN | 7,378 | 31.8 KB | 0.11 ms | 249 s | ~333 MB |
| DQN | 7,313 | 31.2 KB | 0.07 ms | 186 s | ~333 MB |
| PPO | 13,586 | 56.9 KB | 0.35 ms | 216 s | ~309 MB |
| Tabular Q | 1,224 values | 13.7 KB | 0.01 ms | 80 s | ~222 MB |

- `bench/measure_local.py` on CPU: inference p50 is 0.02–0.03 ms; process peak RAM is 299 MB.
- GPU VRAM: **NOT VERIFIED**. No GPU is in the sandbox.
- A 7k-parameter network needs well under 1 MB, so a GPU is not needed for Agent E.

**Safety**
- 0 violations in every TEST run, for all policies (TESTED + BENCHMARKED).
- The budget held on every day.

---

## 6. Agent F: data (IMPLEMENTED, TESTED)

**Code**
- `agent_f/make_dataset.py` writes `results/agent_f_data/{train,val,test}.jsonl`.
- 9,900 / 1,800 / 2,700 rows. Every row is labelled `source: simulated`.

**Where the rows come from**
- Tickets come from simulated days in the Agent E environment, under mixed heuristic policies.
- These day seeds are **disjoint** from all of Agent E's train, VAL and TEST seeds (tested).

**Label**
- SIM-CSAT, −1.5 if the ticket was not resolved, plus noise. Then rounded to 1–5.
- Resolution chance depends on the queue and on fallback.

**Text**
- Opening, agent closing and an optional last customer message (none in 30% of rows).
- Built from template pools split **by phrasing**: 4/6 train, 1/6 val, 1/6 test (tested disjoint).
- TEST therefore measures generalisation to **unseen wording**, not memorisation.

**Inputs** (no leakage)
- 13 meta features: queue, wait, fallback and the queue state at service time.
- The text.

---

## 7. Agent F: candidates and results (BENCHMARKED on TEST, simulated data, 1 seed each)

**What the columns mean**
- Latency: CPU, batch 1.
- MAE: in stars, lower is better.
- F1: 3-class macro (unhappy / neutral / happy).

| Rank | Model | Why it is a candidate | TEST MAE | F1 | Spearman | Parameters | Disk | Latency p50 | Peak RAM | Training time |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **TinyBERT-4L fine-tuned (3 epochs)** | smallest real transformer; fits CPU and 6 GB GPU easily | **0.346** | **0.848** | 0.719 | 14.4M | 57.5 MB | 5.1 ms | 1060 MB | 265 s |
| 2 | bge-small embeddings + head | the prototype's M3 model is already loaded; reuse is free | 0.549 | 0.770 | 0.621 | 33.4M | 134 MB | 31.7 ms | 833 MB | 186 s |
| 3 | GBM on meta features | strong classical tabular baseline | 0.593 | 0.615 | 0.297 | ~5.7k nodes | 0.3 MB | 0.6 ms | 333 MB | 2 s |
| 4 | Ridge on meta features | simplest baseline | 0.600 | 0.581 | 0.322 | 14 | ~0 | 0.05 ms | 324 MB | 2 s |
| 5 | MiniLM-L6 embeddings + head | common small sentence encoder | 0.604 | 0.674 | 0.446 | 22.7M | 91 MB | 14.7 ms | 779 MB | 94 s |
| 6 | TF-IDF + Ridge | classic text baseline | 0.639 | 0.790 | 0.477 | 5.5k | 0.17 MB | 0.56 ms | 340 MB | 2 s |
| 7 | Bag-of-words MLP | tiny neural net | 0.957 | 0.618 | 0.319 | 263k | 1.1 MB | 0.59 ms | 779 MB | 11 s |
| 2* | DistilBERT fine-tuned (2 epochs) | "bigger model" reference | 0.405 | 0.821 | 0.710 | 66.4M | 266 MB | 17.3 ms | 2621 MB | 746 s |

**Reading**
- Fine-tuning a tiny transformer end to end beats frozen embeddings and classical models by a wide margin (0.35 vs 0.55+ MAE).
- A 4.6× bigger model did not help: DistilBERT is worse than TinyBERT (MAE 0.405 vs 0.346), 3.4× slower, and uses 2.5× the RAM.
  - \*Caveat: DistilBERT had 2 epochs vs TinyBERT's 3 (CPU budget). The comparison is not exactly equal-effort.
- The bag-of-words MLP overfits the training phrasings. That is the expected failure on unseen wording.
- Meta features alone already give MAE ≈ 0.6, because waiting time and fallback drive the simulated label.

**Encoder cost on CPU** (`bench/measure_local.py`, `results/local_measure/measure_cpu.json`, BENCHMARKED, CPU only)

| Encoder | Parameters | Inference batch 1 p50 | Inference batch 64 p50 | One training step, batch 32, p50 |
|---|---|---|---|---|
| TinyBERT-4L | 14.4M | 3.5 ms | 41 ms | 164 ms |
| bge-small | 33.4M | 12.9 ms | 164 ms | 437 ms |
| DistilBERT | 66.4M | 15.5 ms | 307 ms | 698 ms |

The VRAM columns are empty: there is no GPU here (NOT VERIFIED). The same command on the RTX 4050 fills them.

**Caveats**
- TinyBERT update (2026-10-23): re-trained with **3 seeds**; see section 13.
  - TEST MAE 0.373 ± 0.014, F1 0.835 ± 0.022.
  - The single-seed 0.346 above was a favourable seed.
  - The ranking does not change.
- The other F models still have one seed each.
- The TinyBERT checkpoints are saved **outside git** (section 13).

---

## 8. Shared-model experiment (TRAINED, BENCHMARKED; `shared/multitask.py`, `results/shared/`)

**Question.** Can one small network serve both Agent E and Agent F?

**What the two tasks share**
- Both read the **queue state**: E to act, F to know how busy the centre was when the ticket was served.
- So the natural shared part is a **service-state encoder** g: 10 inputs → 32 → 32.

**Agent E head**
- Dueling factorised Q.
- Input: g applied to each of the 4 queues, plus 7 global features.

**F-lite head**
- Input: g(queue state at service time), 3 ticket features, and text as TF-IDF → SVD-64.
- Why not TinyBERT here: E is about 7k parameters and TinyBERT is 14.4M. Sharing TinyBERT with E would save about 0.05% of parameters. So the honest shared test uses the part both tasks really have in common.

**Three architectures** (3 seeds each, 150k E steps, about 36k F updates in every architecture for fairness)
- **A: separate.** Two encoders; E trained by RL and F by MSE, independently.
- **B: shared.** One encoder trained by both losses together (TD + 1.0 · MSE).
- **C: hybrid.** F is trained first. E then uses F's frozen encoder plus its own head.

**Results (TEST)**

| Architecture | E return | E SLA | E urgent SLA | E SIM-CSAT | E cost | F-lite MAE | F-lite F1 | Unique parameters | Training time |
|---|---|---|---|---|---|---|---|---|---|
| **A: separate** | **106.90 ± 0.25** | **97.66** | **93.12** | 4.629 | 1293 | 0.653 ± 0.018 | 0.829 | 19,155 | 282 s |
| B: shared | 106.40 ± 0.51 | 96.96 | 87.70 | 4.622 | 1283 | 0.661 ± 0.021 | 0.841 | 17,747 | 255 s |
| C: hybrid | 106.33 ± 0.39 | 96.92 | 87.96 | 4.608 | 1272 | 0.634 ± 0.003 | 0.833 | 17,747 | 250 s |

**Negative-transfer check** ("worse than separate by more than one seed-std")
- **B shared:**
  - E return −0.51, just under the flag threshold;
  - E urgent SLA −5.4 points;
  - F-lite unchanged (+0.009 MAE, within noise).
- **C hybrid:**
  - E return −0.57, **flagged as negative transfer**; urgent SLA −5.2 points;
  - F-lite slightly better (−0.019 MAE), because F trains first on its own.
- **Saving:** 1,408 parameters (7.4%), only about 6 KB. Training is about 10% faster.

**Reading**
- Sharing buys nothing meaningful and costs Agent E urgent-ticket service.
- F-lite (0.63–0.66 MAE) is also much weaker than TinyBERT (0.35). The shared design caps F at a weak model.

**Note.** Architecture A here (factorised E head over a per-queue encoder) scores 106.90, close to the flat dueling DDQN (106.83). This independently confirms the E result.

---

## 9. Conclusions

1. **Best Agent E: dueling double DQN, 64×64, 7,378 parameters** (TRAINED, BENCHMARKED, simulator only).
   - Highest TEST return.
   - Above the tuned heuristic at equal cost (+0.74 SLA, +5.7 urgent SLA).
   - 0 violations; 0.1 ms per decision on CPU; 32 KB on disk.
   - Runner-up: plain DQN, which is nearly identical and slightly faster.
   - **Keep the Forecast heuristic** as a fallback and as a safety reference: it is within 0.6 return and needs no training.
2. **Best Agent F: TinyBERT-4L fine-tuned, 14.4M parameters** (TRAINED, BENCHMARKED, simulated data only).
   - TEST MAE 0.373 ± 0.014 and F1 0.835 ± 0.022 (3 seeds).
   - 5 ms per prediction on CPU, 58 MB.
   - Beat DistilBERT (66M, MAE 0.405) at a fraction of the size.
   - Cheap option if a transformer is not wanted: TF-IDF + Ridge (MAE 0.64, under 1 ms, 0.2 MB).
3. **Best shared/hybrid: none is recommended.**
   - The shared encoder (B) is the least bad: no F loss, but −5 points urgent SLA for E.
   - The hybrid (C) shows negative transfer on E.
   - The saving is about 1.4k parameters.

**Overall recommendation**
- Use two separate models:
  - Agent E: a small dueling DDQN behind the existing action mask, with the Coordinator executing;
  - Agent F: a fine-tuned TinyBERT.
- Connect them through **data, not weights**: F's predicted satisfaction becomes E's satisfaction signal, replacing SIM-CSAT.
- Both fit easily on the RTX 4050:
  - E needs no GPU;
  - F fine-tuning should need well under 6 GB VRAM. This is RESEARCHED, NOT VERIFIED: run `bench/measure_local.py`.

---

## 10. Limitations and risks

**Data and simulator**
- Simulator and labels are invented. The Agent E ranking may change with real arrival and service data.
- Agent F has **not** seen a real customer message. Its numbers measure the method on templates, not real accuracy.
- SIM-CSAT is a formula. RL optimises whatever it measures, as the reward hacking shows.

**Measurement**
- No GPU measurements; CPU timings come from a shared 4-core sandbox.
- Agent F: TinyBERT has 3 seeds; the other F models have 1.
- F checkpoints were saved outside git, in the sandbox. That folder is temporary; re-run locally to keep one.

**Scope and process**
- E and F are outside the prototype scope in CLAUDE.md. No task file exists for them, so this is research only.
- Heuristic z, model size and checkpoints were all chosen on VAL; TEST was used only to report.
  - Exception: a single `sla_heavy` run set was used to *detect* reward hacking. Nothing was chosen from it.

---

## 11. Remaining tasks

1. Brain + Yassine decide whether E/F enter scope. If yes, write a task file.
2. Replace SIM-CSAT with Agent F predictions. Re-train E and re-check for fallback abuse; add a fallback-share cap rule.
3. Get real or teammate-platform data:
   - arrival logs, to fit the simulator rates;
   - labelled satisfaction, for F.
4. Run `bench/measure_local.py` on the RTX 4050 (VRAM, latency) and fill section 5/7 GPU columns.
5. Agent F: 3 seeds for the other F models. Done for TinyBERT.
6. Real-data validation: blocked on data access (section 13).

---

## 12. How to reproduce

**Linux or macOS, CPU**

```bash
cd experiments/agents_ef
pip install -r requirements-research.txt        # only matplotlib is new vs main requirements
python -m pytest -q tests                        # 41 tests
# Agent E
python -m rl.train --algo dueling_double_dqn --seed 0 --steps 150000 --preset balanced
python -m bench.benchmark_e --runs results/runs --out results/agent_e
python -m bench.frontier && python -m bench.frontier_gap
# Agent F
python -m agent_f.make_dataset
python -m agent_f.benchmark --model tinybert_ft --threads 4
# Shared experiment
python -m shared.multitask --arch separate --seed 0     # also: shared, hybrid
python -m shared.aggregate
```

**Windows 11, RTX 4050 (PowerShell)**: NOT VERIFIED here; prepared for the user.

```powershell
cd experiments\agents_ef
py -3.11 -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements-research.txt
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
python -m pytest -q tests
python -m bench.measure_local --out results\local_measure      # writes measure_cuda.json (VRAM, latency)
python -m agent_f.benchmark --model tinybert_ft --threads 8     # CPU path; GPU fine-tune not wired in yet
```

`measure_local.py` uses CUDA when available, which keeps memory use small: at most batch 64 for inference and batch 32 for one training step. It records:
- `torch.cuda.max_memory_allocated`;
- latency at batch 1 and 64;
- peak RAM.

**Generated artefacts**
- In git: code, summaries, CSVs, plots and logs.
- Not in git (`.gitignore`):
  - all model checkpoints (`*.pt`);
  - the F jsonl data (regenerable);
  - HF model caches;
  - fine-tuned F weights.
- Disclosure: the earlier pushed commit `e3fb710` contained 30 tiny Agent E checkpoints (13–57 KB each, numbers only, no secrets).
  - They are untracked from the next commit on.
  - They stay in history, because rewriting pushed history is forbidden.
- Re-running `rl.train` recreates them in about 3–4 minutes each.

---

## 13. Real CallVerse data validation (2026-10-23)

### 13.1 Step 1: finding the real datasets. Result: **not available in this environment**

You described a collection of about 144,794 customer-support messages and an authorised subset of 8,000 (5,600 EN / 2,400 FR). It was searched for in:

| Place searched | What was found |
|---|---|
| `yassinemaazaoui114-git/CallVerse`, all 17 branches (file names and contents) | No dataset. The only message data is about 120 **AI-generated** messages: `callverse/intake/data/reason_examples.json` (60, build set), `tests/data/intake_test_messages.json` (20), `tests/data/live_typing_test_messages.json` (20), `tests/dev/live_dev_messages.json` (24). Each file says in its `_note` that it is AI-generated. |
| Google Drive (connected account) | No CallVerse, ShopNova or support-message dataset. Only unrelated personal files. |
| Your other GitHub repositories (`list_repos`) | No CallVerse dataset repository. DenTech and HireSignal are excluded by your rules. |
| Sandbox disk, Claude project memory, earlier session transcripts | The number 144,794 appears only in your message. |

**Consequences**
- The real-data **results** asked for in steps 2–5 were **not produced**. No number in this report comes from real customer data.
- The ~120 AI-generated messages were **not** used as "real" data: they are not authentic, and some are held-out test sets for other tasks.
- A public dataset was **not** substituted. It would not be "our CallVerse data", and its permissions differ from your authorised subset.

### 13.2 What was built so it runs as soon as the data is reachable (IMPLEMENTED, TESTED on a fake fixture)

**`real_data/prepare_subset.py`**
- Takes a file (CSV / JSONL / JSON, or Parquet if pyarrow is installed) and the column names.
- Builds about 800 messages:
  1. exact dedup on normalised text (order numbers masked);
  2. stratified sampling by language × intent, with a floor of 6 per stratum;
  3. a **group-aware** 60/20/20 split, so a conversation never crosses splits;
  4. **removal** of val/test messages that near-duplicate a train message (TF-IDF char n-gram cosine ≥ 0.9);
  5. a leakage report;
  6. `profile.json`: aggregates only, no text — language / intent distribution, imbalance ratio, words per message, label presence;
  7. `e_calibration.json`.
- Satisfaction labels are used **only** from a genuine rating column (1–5 or 0–10). Intents and sentiment are never converted into satisfaction.

**`real_data/calibration.py` and `--calibration` on `rl.train` and `bench.benchmark_e`**
- Agent E's simulator takes the **queue mix** from real intents, through the editable `real_data/intent_to_queue.json`. That mapping is an **assumption to review**.
- The total load stays the same.
- The hourly arrival shape and service times are used **only if** timestamps or handle times exist. Otherwise the file says "NOT AVAILABLE" and the simulator keeps its assumptions.
- Patience and abandonment are never inferred from messages.

**`real_data/ANNOTATION_PROTOCOL.md`**
- A 300-conversation human labelling plan (210 EN / 90 FR).
- Two annotators, with a kappa target of at least 0.6.
- Metrics broken down per language and per intent, compared with the human ceiling and with baselines.
- A French caveat: TinyBERT-General is English-only. That is RESEARCHED; a multilingual MiniLM is the fallback to test.

**Tests:** 6 tests in `tests/test_real_data.py` use a made-up EN/FR fixture with imbalanced intents and templated duplicates. They check:
- no shared conversation or text across splits;
- rare strata still present in TEST;
- intents never become ratings;
- real ratings are used when present;
- the simulator changes only what the data supports.

Research suite: **47 / 47 passed**.

### 13.3 Agent F: 3 seeds and saved checkpoint (TRAINED, BENCHMARKED; simulated data)

`python -m agent_f.benchmark --model tinybert_ft --seed S --save-dir <outside git>`, with S = 0, 1, 2 (`results/agent_f_seeds/`).

| Seed | Epochs (best on VAL) | VAL MAE | TEST MAE | TEST F1 (3 classes) | Spearman | Training time |
|---|---|---|---|---|---|---|
| 0 | 2 | **0.386** | 0.354 | 0.864 | 0.716 | 265 s |
| 1 | 3 | 0.410 | 0.385 | 0.829 | 0.701 | 217 s |
| 2 | 1 | 0.471 | 0.381 | 0.811 | 0.713 | 216 s |
| **Mean ± std** | | | **0.373 ± 0.014** | **0.835 ± 0.022** | 0.710 ± 0.006 | |

**Best checkpoint**
- Seed 0, chosen on **VAL**, not TEST.
- Saved outside git as `model.pt` + `meta.json` (55 MB each).
- Location: the session scratchpad `checkpoints/agent_f/tinybert_ft_s0`. That sandbox folder is **temporary**.
- To keep a copy, re-run the same command on your laptop with `--save-dir D:\callverse_ckpt` or similar.
- `*.pt` stays git-ignored.

### 13.4 Steps 2–5 status

| Step | Status | What unblocks it |
|---|---|---|
| 2. Stratified subset, 500–1,000 messages | Code ready; NOT VERIFIED on real data | The data file path and its column names |
| 3. TinyBERT on authentic text | NOT VERIFIED | Data. If no rating column exists: run the annotation protocol first |
| 4. Agent E with the real queue / language mix | Code ready (`--calibration`); NOT VERIFIED | Data, plus review of `intent_to_queue.json` |
| 5. Synthetic vs real comparison | NOT VERIFIED | Steps 2–4 |

**Commands once the data is reachable.** Keep `--out` outside the repository:

```bash
cd experiments/agents_ef
python -m real_data.prepare_subset --input <path> --text <col> --intent <col> --lang <col> \
    --conv-id <col> [--rating <col>] [--timestamp <col>] --n 800 --out $CALLVERSE_DATA_DIR/subset
python -m rl.train --algo dueling_double_dqn --seed 0 --calibration $CALLVERSE_DATA_DIR/subset/e_calibration.json --tag _real
python -m bench.benchmark_e --filter _real --calibration $CALLVERSE_DATA_DIR/subset/e_calibration.json --out results/agent_e_real
```

The F evaluation on real text needs a small loader for the subset format. It is not written yet, because the label column (or the annotation output) does not exist yet.

---

## 14. Real-data validation, round 2 (2026-10-23)

### 14.1 Your CallVerse files: access status

The folder `C:\Users\semah\Documents\ChatGPT\data collection\callverse-data` is on your Windows PC.

This session runs in a cloud sandbox. It has **no access to your PC**: no Remote Control session from your computer is connected, and none of the connected tools reach local Windows files.

So these are **NOT VERIFIED**: their row counts, schemas, labels, annotation completion, and the 144,794 / 8,000 counts:
- `CALLVERSE_ECOM_FINAL\complaints\ecommerce_complaints_5305.csv`
- `new_human_gold_collection\callverse_existing_plus_new_human_gold_2cols.csv`
- `final_annotation\`
- `migrated_dataset_v1_3_2\migration_progress.json`

**Read-only inventory script:** `real_data/inventory_windows.ps1`.
- Tested here with PowerShell 7.4.6 on the real Olist CSVs and on fake JSON/JSONL files.
- Correct record counts, including multi-line quoted CSV fields.
- Never prints free-text or personal columns.
- What it writes: one report file, `Documents\callverse_inventory.json`. It reports:
  - per file: path, size, modified date, SHA256, header and record count;
  - per column: non-empty and distinct counts;
  - value counts for short categorical columns only (where label columns such as intent, language and rating appear);
  - JSON keys, with the values of small files such as `migration_progress.json`.
- It never changes, moves or copies a data file.

### 14.2 What could be verified: the public Olist data (your item 5)

`olist\raw\olist_orders_dataset.csv` is part of the **public** Olist dataset:
- source: Kaggle `olistbr/brazilian-ecommerce`, licence CC BY-NC-SA 4.0;
- content: Brazilian e-commerce from 2016 to 2018.

The same files were downloaded here from Kaggle's public endpoint into the sandbox, not into git.

| File | Records (quote-aware) | SHA256 (compare with your copy via the inventory) |
|---|---|---|
| olist_orders_dataset.csv | 99,441 | `8df58ef3d2d7e9944010f7beecd9b75367f5588ec6e3c91cec19ae3345ef9ecf` |
| olist_order_reviews_dataset.csv | 99,224 | `012b61c7593e34f51fa614efdf802b9c7056ce6aae5307ddb93236e7cfc797d7` |

**Labels**
- `review_score` (1–5) is a **genuine customer satisfaction rating**, given by the customer after delivery.
- 40,950 reviews have comment text; 33,662 remain after exact dedup.

**Limits**
- Olist is **product/delivery reviews in Portuguese**, not CallVerse support conversations in EN/FR.
- It has **no** support-contact logs.
- So it validates *methods and model choice on authentic text with real labels*. It does not replace your CallVerse data.

### 14.3 Agent F on genuine satisfaction labels (TRAINED, BENCHMARKED; Olist, Portuguese)

**Data**
- Stratified 1,000-review subset: rating × language strata, grouped by order.
- Splits: TRAIN 600 / VAL 199 / TEST 201.
- Leakage checks: 0 shared texts and 0 shared orders across splits; 1 near-duplicate removed from VAL.
- Raw text stays in the sandbox, outside git.

**Method**
- Text-only: the simulator's queue-state features do not exist in real data.
- Epoch, alpha and best seed are chosen on VAL; TEST is scored once.

| Model | Parameters | TEST MAE | RMSE | 3-class macro-F1 | 5-class macro-F1 | Spearman | CPU latency p50 | Training time (CPU, per seed) |
|---|---|---|---|---|---|---|---|---|
| Predict TRAIN mean | 1 | 1.506 | 1.660 | 0.251 | 0.049 | — | — | 0 s |
| TF-IDF (word + char) + Ridge | 8.3k | 0.758 | 1.032 | 0.569 | 0.329 | 0.784 | 1.4 ms | 2 s |
| TinyBERT-4L, 6 epochs, 3 seeds | 14.4M | 0.850 ± 0.030 | 1.220 | 0.524 ± 0.042 | 0.293 | 0.717 | ~7 ms | 90–154 s |
| TinyBERT-4L, 12 epochs, 3 seeds | 14.4M | 0.783 ± 0.032 | 1.203 | 0.571 ± 0.029 | 0.360 | 0.726 | ~7 ms | 150–184 s |
| **Multilingual MiniLM-L12, 6 epochs, 3 seeds** | 117.7M | **0.591 ± 0.006** | 0.936 | **0.600 ± 0.015** | **0.400** | **0.815** | ~21 ms | ~350 s |

`results/real_f_olist/`, `results/real_f_olist_e12/`

**Simulated vs real for Agent F**

| | Simulated benchmark (section 7/13) | Real labels (Olist) |
|---|---|---|
| TinyBERT MAE | 0.373 ± 0.014 (best model) | 0.78–0.85 (**worse than TF-IDF**) |
| Best model | TinyBERT | multilingual MiniLM, 0.591 |
| Share of negative labels (1–2★) | 5% | 30% |
| Type-token ratio of the text | 0.004 (templates) | 0.16 |
| Real word tokens found in the simulated vocabulary | — | 5.8% |
| TinyBERT pieces per word | 1.09 | 2.02 (English vocabulary on Portuguese) |

`results/real_f_olist/text_comparison.json`

**Reading**
- The simulated benchmark **over-rated TinyBERT**. Its template text is narrow and English, and the labels come from a formula.
- On authentic text with real labels:
  - an English-only 4-layer model is not enough;
  - a multilingual encoder wins clearly;
  - TF-IDF is a strong cheap baseline.
- Every model struggles with **3-star (neutral)** reviews: MAE 1.1–1.4 on that class.
- **For CallVerse (EN/FR), the safer choice is now the multilingual MiniLM.**
  - 118M parameters.
  - CPU training peak RAM 5.8 GB.
  - Fine-tuning should fit the RTX 4050 at batch 16, length 128. That is RESEARCHED, NOT VERIFIED.
- This must be confirmed on your EN/FR data. Portuguese reviews are only a proxy.

**Checkpoints**
- The best seed on VAL was saved per model, outside git, in the sandbox scratchpad: `checkpoints/agent_f_real*`.
- That folder is temporary. Re-run with `--save-dir` on your PC to keep one.

### 14.4 Agent E: what real order data supports (BENCHMARKED; Olist)

`real_data/olist_workload.py` writes `results/real_olist/workload.json` and `workload.png`.

| Property | Simulator assumption | Olist (real orders) | Used? |
|---|---|---|---|
| Demand shape inside an 8 h day | two peaks, peak/mean 1.51 | busiest window 10:00–18:00 is **flat**, peak/mean 1.045 | **yes** (`hourly_profile_8h`) |
| Day-to-day load | normal ×0.9–1.05, high ×1.25–1.4 | CV 0.43, p95/mean 1.58, max 6.2× (Black Friday 2017-11-24) | no (reported) |
| Late deliveries (a contact driver) | — | 8.1% late, 5.4% more than 3 days late | no (reported) |
| Satisfaction vs lateness | SIM-CSAT falls linearly with wait | 4.3★ early → 3.8★ (0–3 d late) → 2.3★ (3–7 d) → 1.7★ (>7 d) | qualitative check only |
| Arrival rates, waits, abandonment, handle times | assumed | **not in the data** | no |

**On the Olist-shaped simulator** (TEST; same seeds, splits and safety layer; `results/agent_e_olist/`, `results/frontier_olist/`)

| Policy | Return | SLA | Urgent SLA | Abandon | Cost |
|---|---|---|---|---|---|
| Forecast z=0 (z chosen on VAL) | **108.97** | 96.79 | 85.32 | 1.39 | 1266 |
| Dueling DDQN retrained on the Olist shape (3 seeds) | 108.34 ± 0.30 | 96.41 | 88.38 | 2.05 | 1224 |
| Dueling DDQN trained on the original simulator | 105.94 ± 1.09 | 96.45 | 89.72 | 1.97 | 1283 |
| Forecast z=0.5 (default) | 105.67 | 98.72 | 94.71 | 0.62 | 1446 |

**Gap against the heuristic curve at equal cost (TEST)**

| | SLA | Urgent SLA | Abandon (− = better) | SIM-CSAT |
|---|---|---|---|---|
| DDQN retrained | +0.45 ± 0.30 | +6.55 ± 1.35 | +0.22 ± 0.06 | 0.00 |
| DDQN, original training | −0.61 ± 0.29 | +2.86 ± 1.77 | +0.68 ± 0.23 | −0.04 |

The same signs appear on VAL. 0 violations everywhere.

**Reading**
- **Return advantage:** with the real (flat) demand shape, the tuned heuristic matches or beats RL on overall return.
- **Urgent tickets:** the RL agent still serves urgent tickets better at the same cost (+6.6 points), but lets slightly more people abandon.
- **Distribution shift:** a policy trained on the synthetic shape must be **retrained**, because it falls below the curve on overall SLA.
- **Conclusion for Agent E:** a small RL policy is still viable. But its advantage over a well-tuned rule is small and depends on the workload model. Keep the Forecast rule as baseline and fallback.

### 14.5 Leakage, imbalance and authenticity checks

**Leakage**
- Group-aware splits (by order); exact and near-duplicate removal; 0 overlaps.
- z, epochs and seeds chosen on VAL only.

**Imbalance**
- Real ratings: 46.5% are 5★, 6% are 2★ (ratio 7.75). Macro-F1 is reported for that reason.
- Selection bias: reviews with comments are more negative (21% 1★) than all reviews (12% 1★).

**Synthetic vs authentic**
- Large gaps in vocabulary, length spread, label balance and language (table in 14.3).

### 14.6 Next steps

1. Run the inventory on your PC (command in the chat reply) and share `Documents\callverse_inventory.json`. It holds no raw text.
2. From the inventory, decide which file holds the authorised 8,000 EN/FR subset, and check whether any column is a genuine satisfaction rating.
3. Run `real_data/prepare_subset.py` and `real_data/eval_f_real.py` **on your PC**, so raw customer text never leaves it. Share only the result JSONs.
4. If there is no rating column: run `real_data/ANNOTATION_PROTOCOL.md` on 300 conversations.
