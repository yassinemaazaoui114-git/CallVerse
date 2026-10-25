# 00 — Executive summary: CallVerse Agents E & F, benchmark V3

**Bottom line**
- **Agent E:** RL does **not** beat the best classical rule. The best rule, Fluid MPC, and the best RL-containing policy, a Forecast + Dueling DDQN hybrid, are a statistical tie on the locked TEST. Select **Fluid MPC**, or Forecast as an equally good simpler option.
- **Agent F:** on the primary satisfaction benchmark, a **TF-IDF + Ridge** model (0.19M params) matches or beats every fine-tuned tiny transformer. No model is valid as a reward for E yet: the only reachable labels are annotator judgements and product stars, not ShopNova customer ratings.
- All M7 responsibilities of Agent F are now built and tested:
  - satisfaction score;
  - closed-conversation review;
  - outdated-rule audit;
  - owner report;
  - gated feedback to E.

## Agent E (capacity proposals; simulated, CPU)

**Simulator fix**
- v1/v2 shared one random generator, so a policy changed its own future arrivals. Earlier "paired" comparisons were therefore not paired.
- v3 pre-generates each day's world on a tape: identical for every policy, and tested (25 invariant tests).

**Protocol**
- Objective: balanced and normalised (SLA failures, lost customers, cost), locked on VAL before any RL.
- Rules were tuned on VAL.
- 66 RL runs: 6 algorithms; 5–10 seeds; size, budget and weight ablations. Plus 3 E+F runs.
- Candidates frozen at 20:48:08. Locked TEST: 650 days, 13 families, 5 never seen in training.
- Statistics: two-level paired bootstrap and Holm correction.

**Results** (Δ return vs MPC [95% CI])

| Policy | Δ return vs MPC |
|---|---|
| Guarded DDQN (Forecast + Dueling DDQN, 10 seeds) | **+4.1 [−0.9, +8.2]**, a tie |
| Pure Dueling DDQN (10 seeds) | −3.7 [−8.8, +0.8], a tie |
| Forecast | −1.6 [−3.5, +0.4] |
| Erlang-C | −1.6 [−3.5, +0.1] |
| DQN | −8.7 |
| PPO | −30.6 |
| Tabular Q | −64.6 |

**Trade-offs of the hybrid vs MPC**
- Better: 4% cheaper, and much better under severe overload (9.2% vs 13.4% customers lost).
- Worse: queue-C SLA (−9.5 pp), lost customers (+0.27 pp), HIGH SLA (−0.19 pp).

**Ablations**
- 128×128 networks and 400k training steps only reach a tie.
- Reward-weight retraining did not produce the intended trade-offs.
- A synthetic satisfaction term had no measurable effect (+2.0 [−2.2, +6.8]).

**Safety held for every policy:** 0 HIGH tickets on fallback, 0 invalid executions, budget always respected.

## Agent F (satisfaction predictor + M7 quality & knowledge)

**Data**
- USS: 6,772 dialogues; English task dialogues plus JDDC real Chinese e-commerce service; human annotator ratings. Primary.
- Amazon EN/FR product stars: auxiliary.
- Rejected: synthetic CSAT (Saif7800).
- Blocked: DCH-2 (needs an agreement, not accepted) and local CallVerse data (no access).

**USS TEST MAE**

| Model | Params | Overall | EN | ZH |
|---|---|---|---|---|
| TF-IDF+Ridge (last 256 tokens) | 0.19M | **0.392** (Spearman 0.596) | — | **0.489** |
| e5-small trimmed, 6 layers, 256 tokens | 17.4M | 0.399 ± 0.006 | **0.296** (best) | — |

- Floors: per-corpus mean 0.423; noise limit 0.234 (EN) and 0.247 (ZH).
- Cost of the e5 model on CPU: 58 ms (41 ms in int8), 39.5 MB in int8.

**M7: review, audit and report on closed conversations**
- Test corpus: 120 held-out conversations through the **real prototype pipeline**, with scripted agents.
- 16/16 planted defects that occurred were caught; 0 false flags on 91 clean conversations.

**Prototype findings**
- French clients receive English template replies.
- No rule covers delivered-late orders after the 14-day return window.
- All 8 rules are AI-written and unreviewed.

**Feedback to E is gated**
- With the selected model, the gate passes the statistics: Spearman CI [0.545, 0.635].
- It fails on label type and domain, and scores are flat on ShopNova text (SD 0.04).
- **Verdict: KPI only, not a reward.**

## What is not verified

- RTX 4050 / GPU numbers.
- Local datasets on the user's PC.
- QCRI GPU state.
- DCH-2.
- Full-protocol F fine-tuning.
- SLM-on behaviour of the prototype replies.
- Simulator sensitivity to its invented parameters.
- TEST at 300 days per scenario (650 days were used).

## Where to read

| Topic | File |
|---|---|
| Audit | `01` |
| Simulator validation | `02` |
| Protocol | `03` |
| Agent E results | `04` |
| Agent F results | `05` |
| Statistics | `06` |
| Error analysis | `07` |
| Model selection | `08` |
| Limitations | `09` |
| M7 scope | `10` |
| How to run | `RUN_AND_RESUME.md` |
| Status | `BENCHMARK_STATUS.json` |
| Slides | `SLIDE_OUTLINE.md` |
| Checkpoint hashes | `CHECKPOINT_MANIFEST_E.json`, `v3/f/checkpoints_manifest.json` |
