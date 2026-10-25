# 06 — Statistical analysis

Code: `v3/e/analyze_v3.py`, `analyze_v3_report.py`. Output: `v3/e/results/test_analysis.json`.

## Agent E

**Design**
- Every policy is evaluated on the **same 650 TEST tapes**: identical arrivals, ticket attributes, patience and failure draws (tested: `test_exogenous_world_is_identical_for_every_policy`).
- So the unit of pairing is the **day**. Learned policies add a second source of variance: the **training seed**, with 3–10 seeds per group.

**Intervals**
- 95% CIs come from a **two-level bootstrap**.
  - Level 1: resample the policy's seeds.
  - Level 2: resample the days, using the **same day indices** for both policies of a comparison.
- 1,000 resamples for differences and for leaderboard means.
- A CI therefore includes uncertainty from both training and evaluation.

**Effect size and win rate**
- d_z = mean per-day paired difference / SD of the per-day differences, with seeds averaged.
- Win rate = share of days where the policy beats the reference.

**Multiple testing**
- Holm correction over the 20 primary comparisons: every learned group (pure RL, guarded, ablations, E+F) vs the reference, on return.
- The bootstrap p-value has a floor of 1/1000. With 20 tests, **0.020 is the smallest attainable p_Holm**, so every "p_Holm 0.020" in the tables means p ≤ 0.001 before correction.

**Reference.** Chosen on VAL before TEST: the best tuned rule, Fluid MPC k = 0.5 (`results/val_choice.json`).

**Sample size**
- Target: 300 days per scenario. Actual: 50 days per family, 650 in total (CPU budget).
- At this size, the half-width of the CI on a return difference is about 4–5 points for 10-seed groups (DDQN vs MPC: [−8.8, +0.8]). A true effect below about 4 points (≈ 2% of the return) cannot be resolved.

### Primary results (equal weights)

| Comparison vs Fluid MPC | Δ return [95% CI] | d_z | Win rate | p_Holm |
|---|---|---|---|---|
| Guarded Dueling DDQN (10 seeds) | +4.1 [−0.9, +8.2] | +0.14 | 0.40 | 1.0 |
| Dueling DDQN (10) | −3.7 [−8.8, +0.8] | −0.12 | 0.29 | 1.0 |
| Forecast (rule) | −1.6 [−3.5, +0.4] | −0.06 | — | (not a primary test) |
| Erlang-C (rule) | −1.6 [−3.5, +0.1] | −0.07 | — | (not a primary test) |
| DQN (10) | −8.7 [−17.4, −2.6] | −0.22 | — | 0.072 |
| PPO (10) | −30.6 [−37.1, −24.0] | −0.84 | — | 0.020 |
| Tabular Q (5) | −64.6 [−77.0, −51.9] | −1.37 | — | 0.020 |

**Conclusion.**
- No learned policy is significantly better than the best classical rule.
- PPO, Tabular Q, DQN (by CI), Dueling DQN and Double DQN are worse.
- The guarded hybrid and pure DDQN are **ties**.

**Secondary (weight-free) results** are in `04_AGENT_E_RESULTS.md` §2: cost, lost customers, HIGH SLA, queue-C SLA, held-out families, Pareto sets and matched cost / SLA. They are reported with CIs, without a multiplicity correction, as descriptive evidence.

**Sensitivity**
- Returns were recomputed exactly from the KPIs under the 4 weight presets (`weight_sensitivity`).
- Under every preset, the plain guarded hybrid ranks 2nd (behind its csat-shaped variant) and MPC 4th–5th.
- The differences between them stay inside the tie band above.

### Validity checks behind the statistics

| Check | Result |
|---|---|
| Tapes are identical for every policy | tested |
| Manifest | hash-checked by the evaluator before every run |
| Candidates frozen before TEST was read | 20:48:08 (`CANDIDATE_FREEZE.txt`) |
| What VAL selected | rules' parameters, reward normalisation, and each RL run's checkpoint (best greedy VAL return). Nothing was chosen on TEST |
| v1/v2 "paired" intervals | invalid (shared-RNG coupling, `02` §1); superseded |

## Agent F

Selection was on VAL only; TEST was scored once per run; 3 seeds for fine-tuned models (`05_AGENT_F_RESULTS.md`).

**How large the differences are**
- **USS EN:** MAE 0.296–0.312 for every model, against a noise limit of 0.234. VAL differences below about 0.01 are within seed noise. The 12-layer e5 model ranked first on VAL but did worse on TEST, which is the evidence for that.
- **M7 validation card for the selected model:** Spearman 0.592 with a bootstrap 95% CI of [0.545, 0.635] (2,000 resamples over the 1,016 TEST dialogues, `v3/m7/report.py`).

**M7 defect detection** (planted, scripted corpus): reported as counts (16/16; 0/91 false flags). There is no inferential claim: the defects are visible in the traces by construction.
