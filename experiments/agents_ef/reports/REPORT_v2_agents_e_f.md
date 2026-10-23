# CallVerse Agents E and F, v2: Intake-aware RL and tiny multilingual satisfaction models

- **Branch:** `research/agents-e-f-tiny-models` (main `d125959` merged in; no change to `main` or teammates' branches).
- **Folder:** `experiments/agents_ef/`.
- **Date:** 2026-10-23.
- **Compute:** cloud sandbox, 4 CPU cores, no GPU.
- **Earlier report:** `REPORT_agents_e_f.md`, kept as history.

**Labels**

| Label | Meaning |
|---|---|
| **TESTED** | covered by passing tests |
| **TRAINED / BENCHMARKED** | run here, scored on held-out TEST |
| **SIMULATED** | simulator result |
| **AUTHENTIC** | genuine human data with genuine labels |
| **RESEARCHED** | literature or metadata only |
| **NOT VERIFIED** | not run or not measured here |

---

## 0. In plain words

**Agent E: staffing**
- Agent E now sees Intake's priorities.
- A tiny RL agent (Dueling Double DQN, about 8k parameters) beats a tuned staffing rule on familiar demand.
- It loses when the shape of the day changes.
- A **guarded hybrid** is never worse than the rule at equal cost: the rule sets how many sessions run, and RL decides where they go and when to use the capped cheap mode.
- The gain over the rule is small. **Recommendation:** ship the rule (Forecast or Erlang-C), and run RL in shadow or guarded mode.

**Agent F: satisfaction**
- Agent F was tested on authentic customer texts with genuine 1–5 ratings, in English and French.
- The best model is **multilingual-e5-small with its vocabulary trimmed to the needed tokens: 27.8M parameters.** TEST error is 0.63 stars (EN 0.64, FR 0.62).
- TinyBERT, the winner on synthetic data, is clearly worse (0.74).
- Intake's sentiment model is not a satisfaction model. It fails in French (1.13).

**One shared network for E and F:** still not worth it.

**F as E's reward:** the RL agent learned to abuse the cheap fallback mode until a hard cap stopped it. Reward models must sit behind hard rules.

**Your own CallVerse files** stay on your PC. This session cannot reach the PC, so they remain NOT VERIFIED.

---

## 1. Access to your computer

- No computer-access tool is connected to this session: no Remote Control session, Desktop Commander, terminal bridge or MCP filesystem.
- The session runs in a cloud container. It cannot reach `C:\Users\semah\...`.
- I did not retry beyond one check.

**The one step that needs you** (either works):
- run `claude remote-control` in a terminal in the data folder (or use the Claude Desktop app on the PC), then start the session from the Claude app; **or**
- run the read-only inventory (`real_data/inventory_windows.ps1`, report section 14) and the local package (section 8), and share the JSON outputs. They contain no customer text.

---

## 2. GitHub audit

- **main:** `d125959` ("Merge feature/t10b"). It holds no Agent E or Agent F code.
  - CLAUDE.md still lists agents E and F as **out of prototype scope**, so all of this stays research.
- **This branch:** `origin/main` was merged into it (merge commit `27baa88`). It's my own branch: no rebase, no force push.
- **PR:** `yassinemaazaoui114-git/callverse#1` (I01 voice) is still open. I did not touch it.
- **Teammates' branches:** none modified.
- **Intake contract reused:**
  - `callverse/intake/priority.py`: priority = 0.6·severity + 0.25·time_pressure + 0.15·emotion; labels high ≥ 0.6, medium ≥ 0.35.
  - `callverse/queues/queue.py`: heap ordered by priority label, then arrival.
  - `config.yaml`: `intake.priority`.
  - R-ESC-01 threshold: 300.

---

## 3. Verified data inventory

| Data | Where | Verified | Labels | Use here |
|---|---|---|---|---|
| Your CallVerse collection (144,794 msgs; 8,000 EN/FR subset; 5,305 complaints; 220 human-gold; final_annotation) | your Windows PC | **NOT VERIFIED**: not reachable | unknown | none |
| Repository messages (~120) | `callverse/intake/data`, `tests/data`, `tests/dev` | yes | intents; **AI-generated** (each file says so) | not used as real data |
| Olist orders + reviews (public, CC BY-NC-SA 4.0) | Kaggle `olistbr/brazilian-ecommerce`, downloaded to the sandbox | yes: 99,441 orders, 99,224 reviews; SHA256 in report v1 §14.2 | **genuine 1–5 review_score**, Portuguese | E workload shape, lateness, order values; F (pt); F→E reward model |
| Amazon Multilingual Reviews (MTEB mirror, non-commercial research licence) | HF `mteb/amazon_reviews_multi`, EN/FR validation + test only (4 × 5,000 rows, 5.3 MB) | yes: counts, labels 0–4 = stars 1–5, balanced 1,000 per star by the curators | **genuine star ratings**, EN + FR | F: main EN/FR benchmark |

**Notes on the data**
- **Raw text** stays in the sandbox scratchpad, never in git. Only aggregates are committed.
- **Satisfaction labels:**
  - The genuine ratings here are *product/delivery* satisfaction, not support-conversation satisfaction.
  - No CallVerse support satisfaction label was reachable.
  - Intents were never turned into satisfaction labels.

**EN/FR subset** (`real_data/build_reviews_subset.py`)
- 1,000 per language: TRAIN 1,200 / VAL 400 / TEST 399.
- TRAIN and VAL come from the official validation split; TEST comes from the official test split.
- Stratified by star.
- Leakage: 0 shared texts across splits, 0 near-duplicates (char TF-IDF cosine ≥ 0.9); 1 removed from TEST.
- Reviewer and product ids are not in the mirror, so a group-aware split was not possible.

---

## 4. Agent E v2: Intake-aware design (IMPLEMENTED, TESTED)

**Files:** `env/intake_env.py`, `env/intake_adapter.py`, `env/factory.py`, `integration/agent_e_policy.py`.

**What Agent E sees: aggregates only, never text**
- v1's 31 queue features.
- Plus, per queue: waiting high-priority count, mean waiting priority score, and the oldest high-priority wait relative to its SLA.
- 43 inputs in total.
- E does not reinterpret messages: Intake already did.

**Priority**
- Every simulated ticket gets Intake's fields.
- Its priority uses **the prototype's own formula**, read from `config.yaml` and the policy file.
- Vectorised for speed; a test checks it equals `callverse.intake.priority.compute` on 300 random cases.

**Semantic priority over emotion**
- Queues serve high → medium → low, then FIFO, exactly as `queue.py`.
- Tested: a calm client with a 6-day-late order outranks a furious client whose order is on time.
- Emotion can move the score by at most 0.15.

**Reward: business costs, NOT the 60/25/15 weights**
- +1 per served ticket.
- Abandonment penalty by priority tier (low 1, medium 2, high 4).
- Lateness penalty by tier (0.25 / 0.5 / 1).
- Session cost (0.5).
- SIM-CSAT, or F's prediction.
- The 60/25/15 weights only decide the tier label.

**Fallback safety, as hard rules**
- Never used for HIGH-priority tickets.
- ON for at most **25% of the day**, enforced in the action mask and by a forced switch-off.
- Tested with a policy that always tries fallback: 0 high tickets on fallback, ≤ 24 of 96 steps.

**Ticket fields and simulation assumptions**

| Item | Source |
|---|---|
| Lateness given late, late share 8.1%, order value > 300: 10.4% | real (Olist) |
| Reason mix per queue | ASSUMPTION |
| Emotion distribution | ASSUMPTION |
| Patience × (1 − 0.3·emotion) | ASSUMPTION |
| Tier SLA factors (high 0.3×, low 1.5×, floor 3 min) | ASSUMPTION |
| Demand shape "flat" (Olist orders 10:00–18:00, peak/mean 1.045) | real |
| Day-to-day volatility σ = 0.43 (Olist daily orders CV) | real |
| Other shapes (two-peak, morning, evening) | assumed |

**Integration (research-ready, not wired into `callverse/`)**
- `AgentEPolicy.propose(snapshot)`: a JSON snapshot of queues and capacity becomes the **same** observation and mask as the simulator (tested over 60 steps).
- It returns a **capacity proposal** for the Coordinator. Agents never act.

---

## 5. Agent E v2 results (TRAINED, BENCHMARKED; SIMULATED)

**Setup**
- 150k steps per run, 3 seeds; checkpoint chosen on VAL; 56 TEST days.
- 24 v2 runs: DQN, Double DQN, Dueling DDQN, PPO; Dueling DDQN with domain randomisation (`_dr`), with 400k steps (`_400k`), and with the F reward with/without cap.

### 5.1 TEST, in-distribution (`results/agent_e_v2*/summary.json`)

| Policy | Params | Return | SLA % | Urgent (HIGH) SLA % | Abandon % | SIM-CSAT | Cost | Fallback share | Violations |
|---|---|---|---|---|---|---|---|---|---|
| Dueling DDQN 400k | 8,146 | **106.28 ± 0.91** | 96.24 | 99.85 | 2.20 | 4.600 | 1284 | 0.07 | 0 |
| Forecast z=0 (z chosen on VAL) | 0 | 106.06 | 95.11 | 99.93 | 2.91 | 4.597 | 1279 | 0.00 | 0 |
| Dueling DDQN | 8,146 | 105.52 ± 0.98 | 95.51 | 99.84 | 2.63 | 4.564 | 1273 | 0.10 | 0 |
| Erlang-C (target chosen on VAL) | 0 | 105.52 | 96.90 | 99.94 | 1.81 | 4.655 | 1398 | 0.01 | 0 |
| PPO | 15,122 | 105.40 ± 0.46 | 95.34 | 99.85 | 2.80 | 4.612 | 1305 | 0.00 | 0 |
| DQN | 8,081 | 104.93 ± 0.66 | 95.76 | 99.92 | 2.69 | 4.599 | 1321 | 0.03 | 0 |
| Double DQN | 8,081 | 104.23 ± 0.49 | 94.83 | 99.85 | 2.94 | 4.518 | 1209 | 0.14 | 0 |
| Dueling DDQN, domain-randomised | 8,146 | 103.13 ± 1.28 | 95.12 | 99.82 | 2.93 | 4.532 | 1269 | 0.12 | 0 |
| Forecast z=0.5 (default) | 0 | 104.03 | 97.55 | 99.94 | 1.54 | 4.675 | 1448 | 0.01 | 0 |

**Finding: urgent tickets are protected by the queue rule, not by E**
- HIGH-priority tickets reach about 99.8–99.9% SLA under **every** policy, even the fixed one.
- Prototype queues serve them first, so Intake's semantic priority is already preserved by rules.
- E's real leverage is cost, low/medium waiting and abandonment.

### 5.2 Generalisation across demand patterns (`results/agent_e_v2_general/generalization.json`)

Same 56 TEST days, under different demand. The gap is SLA points versus the Forecast cost-service curve **at the same cost**. Positive = RL better; no extrapolation outside the curve.

| Condition | Forecast (z=0) return | Dueling 400k return | Gap: Dueling 400k | Gap: Dueling DR | Gap: PPO | Gap: **Guarded hybrid (400k)** |
|---|---|---|---|---|---|---|
| in-distribution | 106.06 | 106.28 | +1.08 | +0.38 | −0.36 | +0.52 |
| real flat shape (Olist) | 109.33 | 105.27 | −0.60 | −0.79 | −0.53 | −0.03 |
| evening (never trained on) | 107.32 | 101.17 | −2.38 | −1.18 | −1.54 | +0.14 |
| volatile days (σ 0.43) | 100.25 | 101.39 | +1.15 | +0.45 | −0.42 | +0.43 |
| evening + volatile | 102.60 | 96.26 | −1.93 | −0.33 | −0.85 | +0.27 |

Guarded-hybrid returns per condition: 105.55 / 108.34 / 106.19 / 101.06 / 101.74 (`results/agent_e_v2_guarded/guarded.json`). 

Guarded hybrid with the domain-randomised checkpoints (`results/agent_e_v2_guarded_dr/guarded.json`):
- gaps +0.39 / −0.23 / +0.10 / +0.69 / +0.63;
- returns 105.73 / 107.99 / 106.82 / 102.09 / 103.21.
- It beats the rule's return on volatile days and on evening + volatile.

**Reading**
- **Strength:** RL policies beat the tuned rule at equal cost on the demand they were trained on, and on volatile days.
- **Weakness:** they lose up to 2.4 SLA points when the *shape* of the day changes. The rule re-forecasts every 5 minutes; the network extrapolates.
- **Domain randomisation** (training on several shapes) halves the loss but costs in-distribution performance.
- **The guarded hybrid** (rule owns the capacity level, RL owns allocation and capped fallback) is the only learned variant **never below the curve**, from −0.03 to +0.52 SLA points.
  - Its returns are within about 1 point of the rule.
  - So RL's added value over a good rule is **small**.

### 5.3 Fallback abuse and the cap (BENCHMARKED)

| Dueling DDQN trained with Agent F's reward | Fallback ON | Tickets on fallback | Cost | SIM-CSAT (ground truth) | Ground-truth return |
|---|---|---|---|---|---|
| no cap, evaluated **without** the cap | 94% of the day | 62% | 1089 | **4.30** (lowest) | 98.09 |
| no cap, evaluated with the 25% runtime cap | 25% | 17% | 1264 | 4.52 | 102.10 |
| trained and evaluated with the cap | 25% | 17% | 1320 | 4.55 | 102.45 |

- The v1 `sla_heavy` hacking (55–70% fallback) is now **blocked by construction**.
- The runtime cap protects even a policy that learned to abuse fallback.

---

## 6. Agent F v2 results (TRAINED, BENCHMARKED; AUTHENTIC EN/FR texts, genuine star ratings)

**Setup**
- 3 seeds for every fine-tuned model; epoch and seed chosen on VAL.
- CPU, 2 threads. Latencies were measured while other jobs shared the CPU, so they are upper bounds.
- Source: `results/f_v2_enfr/*.json` (table generator `real_data/summarize_f_v2.py`).

**Vocabulary trimming**
- The 250k-token embedding table is most of a multilingual encoder.
- Keeping only the 15,990 tokens seen in an **unlabelled** EN/FR/PT corpus (official validation texts + Olist TRAIN, never TEST) cuts e5-small from 117.7M to **27.8M parameters**.
- TEST out-of-vocabulary tokens: 0.9%.

| Rank (VAL) | Model | Params | TEST MAE all | EN | FR | 3-class F1 all | Spearman | Disk (fp32) | CPU ms/text | Peak RAM (train) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **e5-small, vocab-trimmed, fine-tuned** | 27.8M | **0.630 ± 0.007** | 0.638 ± 0.015 | 0.622 ± 0.002 | **0.672** | **0.829** | 113 MB | 36 | 4.3 GB |
| 2 | mMiniLM-L12 full, fine-tuned (Olist winner) | 117.7M | 0.642 ± 0.015 | 0.692 ± 0.015 | 0.592 ± 0.019 | 0.668 | 0.811 | 471 MB | 33 | 7.0 GB |
| 3 | mMiniLM-L12, vocab-trimmed, fine-tuned | 27.8M | 0.645 ± 0.013 | 0.691 ± 0.012 | 0.599 ± 0.015 | 0.664 | 0.810 | 113 MB | 33 | 4.1 GB |
| 4 | e5-small frozen + Ridge | 117.7M | 0.709 | 0.705 | 0.713 | 0.656 | 0.788 | - | 33 | 1.9 GB |
| 5 | mMiniLM-L12 frozen + Ridge | 117.7M | 0.757 | 0.817 | 0.697 | 0.624 | 0.747 | - | 33 | 1.9 GB |
| 6 | TinyBERT-4L fine-tuned (English vocab) | 14.4M | 0.743 ± 0.004 | 0.709 ± 0.018 | 0.778 ± 0.011 | 0.625 | 0.760 | 58 MB | 9 | 1.3 GB |
| 7 | mMiniLMv2-L6, vocab-trimmed, fine-tuned | 17.2M | 0.804 ± 0.009 | 0.861 ± 0.014 | 0.746 ± 0.010 | 0.579 | 0.723 | 71 MB | 13 | 2.4 GB |
| 8 | TF-IDF (word+char) + Ridge | 29k | 0.830 | 0.842 | 0.817 | 0.562 | 0.722 | <1 MB | 2 | 0.3 GB |
| 9 | Intake sentiment (M4) + Ridge | 124.6M | 0.932 | 0.719 | 1.146 | 0.496 | 0.596 | - | 69 | 1.4 GB |
| 10 | Intake sentiment (M4), no training | 124.6M | 0.935 | 0.736 | 1.134 | 0.498 | 0.595 | - | 66 | 1.4 GB |
| 11 | predict TRAIN mean | 1 | 1.205 | 1.202 | 1.208 | 0.110 | - | - | 0 | - |

Ranked by VAL MAE (selection); TEST is shown. VAL ranks 2 and 3 tie (0.614). Seeds: 3 for fine-tuned models, 1 for deterministic ones. RAM = peak process RSS during training on CPU.

**Reading**
- **Fine-tuning a trimmed multilingual encoder wins.** The trimmed e5-small model is best overall, and FR is no worse than EN.
- **TinyBERT** (English vocabulary, 14M) loses 0.11 MAE, mostly on French.
- **Frozen embeddings + Ridge** are 0.08–0.13 worse than fine-tuning.
- **Intake's sentiment model (M4) is not a satisfaction model.**
  - Untrained it is decent in English (0.74) but useless in French (1.13).
  - Fitting a regression on its 3 probabilities does not fix that.
  - Satisfaction ≠ sentiment: use a model trained on ratings.
- **Third language check** (Olist, Portuguese, genuine ratings, 1,000 reviews): - e5-small trimmed: **MAE 0.702 ± 0.005, F1 0.645** (3 seeds).
- Full mMiniLM in round 1: MAE 0.591, F1 0.600.
- So on Portuguese it is worse on MAE and better on F1. The trimmed vocabulary came mostly from EN/FR text (5.3% of Portuguese tokens out of vocabulary), and VAL error was still falling at epoch 6.
- Lesson: build the trimmed vocabulary from each deployment language's own unlabelled text.

**Candidates RESEARCHED, not run** (parameter counts from Hugging Face metadata)

| Model | Params | Note |
|---|---|---|
| granite-embedding-107m-multilingual | 107M | Apache-2.0; trimmable like e5 |
| flaubert_small_cased | 54M | French only |
| distilbert-base-multilingual-cased | 135M | — |
| xlm-roberta-base | 279M | — |
| gte-multilingual-base | 305M | — |

---

## 7. E + F together

**A / B / C architectures** (separate / shared backbone / hybrid)
- Benchmarked in v1 (§8 of the old report): 3 architectures × 3 seeds.
- Sharing saved 1.4k parameters (7%) and cost E about 5 urgent-SLA points. The hybrid showed negative transfer.
- With the **real** F (27.8M parameters, text input) and E (8k parameters, queue aggregates), the inputs share nothing. A shared backbone would save < 0.03% of memory, so I did not rerun it.
- **Recommended: A, independent models**, connected through **data**:
  - Intake's structured output feeds E's observation;
  - F's prediction feeds E's reward and reporting.

| Combined footprint (A) | Params | Disk | Note |
|---|---|---|---|
| E: Dueling DDQN | 8,146 | 32 KB | ~0.2 ms per decision (CPU) |
| F: e5-small trimmed | 27.8M | 113 MB fp32 (~56 MB fp16) | |
| Total | | | far below 6 GB VRAM / 32 GB RAM |

**F's prediction as E's reward** (`agent_f/f_reward.py`)
- **Model:** satisfaction vs relative lateness, fitted (isotonic) on **genuine** Olist ratings.
  - VAL MAE 0.905 vs 1.008 for a constant; Spearman 0.23: a weak but real signal.
- **Result:** at equal cost, F-reward training is **no better** than SIM-CSAT training (in-distribution gap +0.46 vs +0.56 SLA).
- **Risk:** without the cap it is exploited (§5.3).
- **Rule:** a learned reward goes behind hard rules. The fallback cap and the HIGH-ticket exclusion are mandatory.

---

## 8. RTX 4050 local package (IMPLEMENTED; GPU NOT VERIFIED)

**Script:** `local/run_local.ps1` (PowerShell 5.1 and 7; parse-checked with pwsh 7.4.6). It runs:
1. GPU / Python checks.
2. An isolated `.venv-agents-ef`. It installs the CUDA torch build **only if missing**.
3. The research tests.
4. `bench/measure_local.py`: real latency, peak RAM and **peak VRAM**.
   - Agent E: v1 and Intake-aware networks.
   - Agent F: 4 encoders, full and trimmed; inference at batch 1 / 64; training step at length 128, batch 16, fp32 + fp16.
5. `-TrainF`: EN/FR subset download (~5 MB) + GPU fine-tune of e5-small-trim, 3 seeds, fp16.
6. `-TrainE`: Intake-aware Dueling DDQN on CPU.

Data and checkpoints go to `%LOCALAPPDATA%\callverse_agents_ef`, outside git.

**CPU measurements from this sandbox** (`results/local_measure/measure_v2_cpu.json`): 4 threads, idle CPU, random weights. Sequences are padded to the worst case of 128 tokens.

| Model | Params | Inference batch 1 p50 | Batch 64 p50 | Train step (batch 16) p50 |
|---|---|---|---|---|
| E: intake Dueling DDQN | 8,146 | 0.032 ms | — | — |
| E: intake DQN / PPO | 8,081 / 15,122 | 0.021 / 0.020 ms | — | — |
| F: e5-small, trimmed (16k vocab) | 27.8M | 31 ms | 1.08 s | 1.57 s |
| F: e5-small, full | 117.7M | 30 ms | 1.05 s | 1.97 s |
| F: mMiniLM-L12, trimmed | 27.8M | 29 ms | 1.10 s | 1.51 s |
| F: mMiniLMv2-L6, trimmed | 17.1M | 15 ms | 0.50 s | 0.71 s |
| F: TinyBERT-4L | 14.4M | 10 ms | 0.34 s | 0.43 s |

- Process peak RAM: 4.3 GB (all models loaded one after another).
- Trimming does not speed up inference: the transformer layers are unchanged. It cuts memory, disk and optimizer state.

**GPU numbers:** none were measured. They are NOT VERIFIED until `run_local.ps1` runs on the laptop.

---

## 9. Tests

| Suite | Result |
|---|---|
| Research | **61 / 61 passed** (`experiments/agents_ef/tests`) |
| Prototype regression | **300 / 300 passed** (repository `tests/`, after merging main) |

**What the new tests check**
- Intake formula equality.
- Semantic priority > emotion.
- Priority-first service.
- Fallback cap and no HIGH ticket on fallback.
- Constraints and per-tier conservation under random actions.
- Determinism.
- Checkpoint round trip (43-input observation).
- Integration snapshot → identical observation and mask.
- F reward monotone.
- Trimmed-vocab F checkpoint reload (EN + FR).
- Leakage and split checks (from v1).

---

## 10. Checkpoints

All are outside git (`*.pt` git-ignored), in the session scratchpad. They are **temporary**: re-create them locally with `run_local.ps1`.

| Agent | Path | Selection |
|---|---|---|
| E | `results/runs/<run>/best.pt` (24 v2 runs + v1 runs) | VAL |
| F EN/FR | `.../scratchpad/checkpoints/f_v2_enfr/<model>_s<seed>/model.pt` + `meta.json` | best seed by VAL: e5small_trim_ft_s0 |
| F Olist | `.../checkpoints/f_v2_olist/` | — |

---

## 11. Recommendation

**Agent E**
- Production candidate: **Forecast or Erlang-C rule** for the capacity level.
- Plus the **guarded Dueling DDQN** (8k parameters) for allocation and capped fallback.
- Hard rules stay outside the learned policy: fallback cap, no fallback for HIGH, urgent minimum, budget.
- Run RL in **shadow mode** first. Promote it only if it beats the rule on real logs at equal cost.

**Agent F**
- **multilingual-e5-small, vocabulary-trimmed, fine-tuned on genuine ratings: 27.8M parameters.** One model for EN and FR.
- TF-IDF + Ridge is the fallback.
- Do **not** use the sentiment model as satisfaction.

**E + F:** independent models. F's output may enter E's reward only behind the hard rules.

---

## 12. Limitations and remaining work

1. **CallVerse data:** your files are NOT VERIFIED. The EN/FR evaluation uses product reviews, not support conversations. Run the inventory and the annotation protocol (`real_data/ANNOTATION_PROTOCOL.md`).
2. **Simulator assumptions:** reason mix, emotion, patience and tier SLAs are assumptions. Real contact logs (arrival, handle time, abandonment) do not exist in the reachable data.
3. **Hardware:** no GPU numbers. CPU latencies were measured under shared load.
4. **Seeds:** 3 per configuration. Some differences (e.g. DQN vs Double DQN) are within seed noise.
5. **Scope and approval:** E and F remain out of the prototype's scope (CLAUDE.md). Integration needs a task file and Brain + Yassine approval. Nothing in `callverse/` was changed.

---

## 13. Round 3 (2026-10-23, evening): validation work completed

**Access**
- Still no connection to the Windows PC: no Remote Control session or bridge was found when checked at the start of this round.
- Your CallVerse files and the RTX 4050 numbers therefore remain **NOT VERIFIED**.

**Agent E: scientific justification**
- New document: `reports/AGENT_E_SCIENTIFIC_JUSTIFICATION.md`.
- It covers the exact 43-dimensional state, the 17 actions, the reward formula, why Double/Dueling, the Intake link, masking and safety, and statistics.
- Three new measured analyses:
  - **Paired statistics** (`bench/paired_stats_e.py`, two-level bootstrap over seeds × days):
    - pure Dueling DDQN vs the VAL-tuned rule: return +0.22 [−1.08, +1.50] in-distribution, but −4.06 to −6.33 (significant) on shifted shapes;
    - the guarded hybrid stays within about 1 return point everywhere, with SLA never significantly worse (+0.39 [+0.11, +0.71] in-distribution).
  - **Failure mechanism** (`bench/diagnose_e.py`):
    - clock ablation costs −5.3 return on familiar shapes but gains +0.45/+0.96 on reversed shapes, so the network learned a time-indexed schedule;
    - its staffing tracks load less than the rule's (correlation 0.70 vs 0.90, evening);
    - only 1–5.5% of states are out of distribution.
  - **Why DDQN in the hybrid and not PPO:**
    - PPO's actions are 99.2% capacity toggles, so guarded PPO equals the rule (win rate 1–19%);
    - DDQN's actions are 46% allocation moves, which the hybrid keeps.
- **Worked decision** (`bench/explain_decision.py`): a real state, Q-values, the guard's decision, the reward decomposition, and one Double-DQN TD update with real numbers.

**Agent F: preserved and reproducible**
- Pipeline: `pipelines/agent_f_pipeline.py`. Data SHA256 checks → subsets → fine-tune → checkpoint outside git → manifest → reload check.
- Revision of multilingual-e5-small pinned to `614241f…`.
- Re-running it reproduced the validated checkpoint **bit-for-bit**: SHA256 `6bae1f48…`, TEST MAE 0.6309, reload MAE identical (`results/agent_f_pipeline/manifest_cpu_repro.json`).
- Bit-identity is expected only for the same CPU, thread count and libraries. On the RTX 4050 (`run_local.ps1 -TrainF`, fp16), expect MAE within the seed spread.
- The checkpoint itself (113 MB) is preserved outside git in the sandbox, in two copies: `checkpoints/f_v2_enfr/e5small_trim_ft_s0` and `f_pipeline_repro/checkpoints/`.
  - The sandbox is not durable storage, and there is no connected outside-git storage large enough.
  - The durable copy must be produced on your PC by the one-command pipeline.

**Tests**
- Research: 63/63, including new determinism and "work folder outside git" tests.
- Prototype: 300/300.
