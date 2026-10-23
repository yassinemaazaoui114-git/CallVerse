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
| — | DistilBERT fine-tuned (2 epochs) | "bigger model" reference (66M) | DISTILBERT_ROW | | | | | | | |

**Reading**
- Fine-tuning a tiny transformer end to end beats frozen embeddings and classical models by a wide margin (0.35 vs 0.55+ MAE).
- The bag-of-words MLP overfits the training phrasings. That is the expected failure on unseen wording.
- Meta features alone already give MAE ≈ 0.6, because waiting time and fallback drive the simulated label.

**Caveats**
- One seed per model; seed variance NOT VERIFIED.
- Fine-tuned weights were **not saved**, to keep model weights out of git. Re-run to reproduce.

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
   - TEST MAE 0.35, F1 0.85.
   - 5 ms per prediction on CPU, 58 MB.
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
- Agent F uses one seed per model.
- Fine-tuned F weights are not saved.

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
5. Agent F: 3 seeds per model; save the chosen TinyBERT checkpoint outside git.

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
