# 04 — Agent E results (V3, locked TEST)

All numbers are **SIMULATED** (v3 tape-based simulator, `02_SIMULATOR_VALIDATION.md`). They come from:
- `v3/e/results/test_analysis.json`, `test_leaderboard.csv`;
- `v3/e/results/eval_test/*.csv`: 136 policies × 650 days, every file complete.

**TEST setup**
- 650 days = 13 families × 50. 5 families were never seen in training.
- Manifest hash `673373a7…`.
- Candidates frozen at **2026-10-25T20:48:08** (`v3/e/results/CANDIDATE_FREEZE.txt`). No TEST row was read before that time.

**Reference** = the best rule by VAL return: **Fluid MPC, k = 0.5**. VAL scores: −178.3, against −185.3 for Erlang-C and −187.4 for Forecast.

## 1. Leaderboard (TEST, equal weights; return = −[SLA failures/F_ref + lost/L_ref + cost/C_ref] per day, higher is better)

| Policy | Seeds | Return [95% CI] | Δ vs MPC [95% CI] | SLA % | HIGH SLA % | Queue-C SLA % | Lost % | p95 wait (min) | Cost / day | Params | Decision p50 / p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Guarded hybrid: Forecast + Dueling DDQN | 10 | −224.6 [−234.0, −215.7] | +4.1 [−0.9, +8.2], Holm p = 1.0 | 92.06 | 99.63 | 81.5 | 5.06 | 7.4 | 1601 | 8,146 | 0.29 / 0.61 |
| Dueling DDQN, 400k steps (ablation) | 3 | −228.5 | +0.1 [−8.3, +7.5] | 92.20 | 99.63 | 80.5 | 4.67 | — | 1708 | 8,146 | 0.22 |
| **Fluid MPC, k = 0.5 (reference)** | — | **−228.7 [−238.2, −218.9]** | 0 | 92.32 | **99.81** | **91.0** | 4.79 | 8.2 | 1671 | 0 | 2.25 / 5.17 |
| Dueling DDQN 128×128 (ablation) | 3 | −229.8 | −1.1 [−7.6, +3.5] | 92.36 | 99.64 | 84.5 | 4.64 | — | 1737 | 24,466 | 0.22 |
| Forecast, z = 0.25 | — | −230.3 | −1.6 [−3.5, +0.4] | 92.26 | 99.68 | 81.9 | 5.72 | 8.1 | 1600 | 0 | 0.06 / 0.14 |
| Erlang-C, target 0.4 | — | −230.3 | −1.6 [−3.5, +0.1] | **92.65** | 99.79 | 84.9 | 5.47 | 7.9 | 1651 | 0 | 0.07 / 0.17 |
| Dueling DDQN (pure RL) | 10 | −232.3 [−242.4, −223.5] | −3.7 [−8.8, +0.8] | 92.10 | 99.67 | 80.2 | 4.84 | 7.1 | 1721 | 8,146 | 0.22 / 0.36 |
| Guarded hybrid: Forecast + PPO | 10 | −233.2 | −4.5 [−8.3, −1.4] | 92.09 | 99.67 | 78.9 | 5.85 | — | 1600 | 15,122 | — |
| DQN | 10 | −237.4 | −8.7 [−17.4, −2.6] | 91.74 | 99.64 | 80.5 | 5.00 | — | 1710 | 8,081 | — |
| Dueling DQN | 5 | −244.1 | −15.5 [−29.3, −3.1] | 91.58 | 99.01 | 79.2 | 5.15 | — | 1733 | 8,146 | — |
| Double DQN | 5 | −250.9 | −22.3 [−56.0, −1.0] | 90.96 | 99.60 | 78.6 | 5.73 | — | 1689 | 8,081 | — |
| PPO | 10 | −259.3 | −30.6 [−37.1, −24.0] | 91.54 | 99.75 | 73.4 | 6.42 | — | 1764 | 15,122 | 0.49 |
| Threshold rule | — | −288.2 | −59.5 | 88.54 | 99.59 | 68.7 | 8.03 | — | 1536 | 0 | — |
| Tabular Q | 5 | −293.2 | −64.6 | 87.70 | 99.23 | 71.4 | 7.02 | — | 1761 | 1,224 | 0.02 |
| Priority rule | — | −342.0 | −113.4 | 86.03 | 99.54 | 92.3 | 11.17 | — | 1536 | 0 | — |
| Fixed (planned 16 sessions) | — | −359.4 | −130.8 | 85.75 | 99.64 | 80.7 | 12.06 | — | 1536 | 0 | 0.00 |
| Random valid | — | −589.2 | −360.5 | 69.78 | 88.34 | 82.0 | 23.69 | — | 1509 | 0 | — |

**Safety holds for every policy:**
- 0 HIGH tickets on fallback;
- 0 invalid proposals that reached execution;
- budget respected;
- fallback ≤ 25% of the day.

**Other notes**
- E+F rows are in §4.
- Figures: `v3/e/figures/e_leaderboard.png`, `e_pareto.png`, `e_per_family.png`, `e_learning_curves.png`, `e_latency_quality.png`.

## 2. Answer: does RL beat the best classical baseline?

**No, not on the pre-declared objective.**
- **Pure RL:** the best (Dueling DDQN, 10 seeds) is −3.7 vs MPC, CI [−8.8, +0.8]: a tie, leaning worse. DQN, Dueling DQN, Double DQN and PPO are significantly worse than MPC.
- **Guarded hybrid** (the Forecast rule owns activation and deactivation; DDQN owns allocation and fallback): the best RL-containing policy, at +4.1, CI [−0.9, +8.2], Holm p = 1.0. That is a **statistical tie with MPC**.
- **Forecast and Erlang-C** are also within 1.6 of MPC.

So the top group (MPC, Forecast, Erlang-C, guarded DDQN) is **not separable** on return at 650 days × 10 seeds.

**Where they differ: weight-free trade-offs**

| Guarded DDQN − MPC | Δ [95% CI] | Reading |
|---|---|---|
| Cost / day | −70 [−75, −65] (−4.2%) | cheaper |
| Lost customers | +0.27 pp [+0.07, +0.46] | worse |
| HIGH-priority SLA | −0.19 pp [−0.32, −0.11] | slightly worse |
| **Queue-C SLA (5-min urgent queue)** | **−9.5 pp [−11.6, −7.8]** | **clearly worse**: the equal-weight objective counts every ticket the same, and queue C is a small share, so RL sacrifices it |
| Return, in-distribution families | −2.2 [−6.5, +1.3] | tie |
| Return, held-out families | +14.2 [+6.6, +21.3] | better, but **driven by one family**: severe_overload, −410.6 vs −481.3 for MPC. All three policies spend the full budget there (1,766/day), and MPC and the hybrid both use the 25% fallback cap; the hybrid's **allocation** loses fewer customers: 9.2% vs 13.4% for MPC and 11.3% for Forecast. On the other 4 held-out families it is within ±7.3 |

**Matched comparisons against the Forecast sweep** (interpolated, no extrapolation)
- At the same cost, guarded DDQN loses 0.66 pp fewer customers and has 0.20 pp more SLA failures.
- At the same SLA, it is 101 session-steps/day cheaper.
- It sits **on or just beyond the Forecast frontier**, not beyond the MPC and Erlang points.
- Pareto non-dominated set: Forecast, Erlang-C and MPC sweep points; DDQN 400k; DDQN 128×128; the guarded csat-shaped hybrid. The plain guarded DDQN is **not** in it.

## 3. Ablations (Dueling DDQN, TEST, equal-weight return)

| Factor | Variant | Seeds | Return | Δ vs MPC |
|---|---|---|---|---|
| Size | 32×32 (3.1k params) | 3 | −253.7 | −25.0 [−41.3, −9.7] |
| Size | 64×64 (8.1k params, main) | 10 | −232.3 | −3.7 |
| Size | 128×128 (24.5k params) | 3 | −229.8 | −1.1 |
| Budget | 150k steps (main) | 10 | −232.3 | — |
| Budget | 400k steps | 3 | −228.5 | +0.1 |
| Budget | PPO 150k → 400k | 10 / 3 | −259.3 → −251.4 | still −22.8 |

**Reading the ablations**
- 64 → 128 units and 150k → 400k steps each move RL only to a **tie** with MPC. Neither beats it.
- 32×32 is too small.

**Reward-weight retraining** (sla_heavy, abandon_heavy, cost_heavy; 3 seeds each): under its **own** preset, each retrained policy is **worse** than the equal-weight DDQN scored under that same preset.

| Preset | Own-trained | Equal-trained | MPC | Rank of own-trained |
|---|---|---|---|---|
| sla_heavy | −315.1 | −305.1 | −299.7 | 14th |
| abandon_heavy | −289.7 | −284.3 | −281.9 | 10th |
| cost_heavy | −344.8 | −339.9 | −333.1 | 15th |

Retraining with new weights did not produce the intended trade-off within 150k steps. A weight change is better served by re-tuning a rule, which costs seconds.

## 4. E × F: synthetic satisfaction term in E's reward

- Run: `--w-csat 1`, the SIM-CSAT shortfall term, 3 seeds. All safety limits are unchanged.
- The **real F model is not used**: the M7 gate blocks it (`10_AGENT_F_M7_SCOPE.md`).

| Comparison (same seeds 0–2, paired days) | Δ return [95% CI] |
|---|---|
| Pure RL: csat-shaped − equal | +2.3 [−1.7, +6.7], d_z 0.08 |
| Guarded: csat-shaped − equal | +2.0 [−2.2, +6.8], d_z 0.07 |

**No measurable effect.**
- Against MPC, the guarded csat run shows +5.9 [+2.4, +9.2] (Holm p = 0.02).
- That significance is **not** evidence for the term. Seeds 0–2 of the plain guarded DDQN average about −224.8, close to its 10-seed mean of −224.6. The csat run's CI against MPC is narrow because its 3 seeds happen to agree (seed SD 2.2 vs 6.4 for the 10-seed group), and its mean is only +2.0 higher.
- The matched-seed paired comparison above is the valid test of the term, and it is not significant.
- Only 3 seeds: not evidence that a satisfaction term helps.

## 5. Cost of the learned policies (CPU, shared 4 cores)

| Algo | Params | Checkpoint | Train time / run | Peak RSS (train) | VAL return (mean over seeds) |
|---|---|---|---|---|---|
| DQN family 64×64 | 8.1k | 35 KB | 560–630 s (150k steps) | 345 MB | −184.0 to −186.7 |
| PPO 64×64 | 15.1k | 65 KB | 556 s | 313 MB | −202.8 |
| Tabular Q | 1.2k | — | 348 s | 225 MB | −242.0 |
| DDQN 400k | 8.1k | 35 KB | 1,420 s | 349 MB | −183.9 |

- **Sample efficiency:** DQN-family VAL curves plateau after about 60k steps (`e_learning_curves.png`). PPO is slower and noisier.
- **Seed spread:** the SD of per-seed TEST return is 6.4–6.8 for DDQN. Double DQN has one bad seed (the CI is wide).
