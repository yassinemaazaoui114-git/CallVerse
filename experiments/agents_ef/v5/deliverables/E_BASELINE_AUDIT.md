# E1 — Baseline audit on identical DEV days (Agent E v5)

**Question.** On the same 104 DEV days, with the same evaluator, how do the original Dueling DQN, Dueling Double
DQN, Fluid MPC (k = 0.5), the V3 guarded hybrid, floor@3 + MPC and floor@3 + V3 guarded compare?

## What was reused and how it was verified

- Manifest: `v4/e/configs/dev_manifest.json`, SHA256 `d54493d254ce10b3526d8ffbb4527b382c8d9040a88a671a627ec16d190d639c`
  (13 families × 8 days, seeds 700000 + 1000·k + i; the hash is re-checked on every load).
- 54 policy files used (rows per training seed). **All 54 have exactly the manifest's 104 (day_id, seed) pairs in
  manifest order** (`v5/e/results/e1_baselines.json`, field `audit`). 11 come from V4 (`v4/e/results/eval_dev/`),
  43 were evaluated by the v5 evaluator (needed anyway for E2 provenance; nothing that existed was trusted blindly).
- Same evaluator: the v5 evaluator reproduces the V4 rows with **0 mismatching cells** on 3 policies × 104 days
  (`v5/e/results/consistency_check/`), and the v5 trainer reproduces V3 training exactly (NOTEBOOK §0). So V4 and
  V5 DEV rows are interchangeable.
- Checkpoints: frozen V3 `best.pt` files (selected on V3 VAL by V3; not re-selected here).
- Command: `python -m v5.e.analyze_v5 e1` (statistics: paired two-level bootstrap, 2000 resamples; v3 `boot_diff`).

## Results (DEV, 104 days; Δ = policy − MPC, paired 95 % CI)

| Policy | seeds | DEV return [95 % CI] | seed SD | Δ return vs MPC | queue-C SLA % | Δ C (pp) | HIGH SLA % | Δ HIGH (pp) | lost % | cost / day | CVaR10 | Δ CVaR10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Dueling DQN (V3, pure RL) | 5 | −222.80 [−247.7, −201.7] | 8.35 | −8.48 [−20.86, +1.21] | 79.74 | −11.50 [−13.71, −9.23] | 99.58 | −0.24 [−0.71, −0.01] | 4.44 | 1727 | −482.0 | +6.98 [−105.1, +63.5] |
| Dueling DDQN (V3, pure RL) | 10 | −217.52 [−238.1, −199.5] | 4.44 | −3.20 [−8.97, +3.70] | 80.81 | −10.42 [−13.63, −7.31] | 99.76 | −0.06 [−0.13, +0.00] | 4.38 | 1714 | −431.0 | +57.99 [+20.9, +80.1] |
| **Fluid MPC k = 0.5** (reference) | — | −214.32 [−237.0, −194.9] | — | — | 91.23 | — | 99.82 | — | 4.36 | 1657 | −489.0 | — |
| V3 guarded hybrid (Forecast owns capacity, DDQN allocates) | 10 | −210.37 [−229.8, −193.4] | 3.95 | +3.94 [−2.02, +10.73] | 81.91 | −9.32 [−12.02, −7.24] | 99.71 | −0.11 [−0.19, −0.04] | 4.71 | 1580 | −422.3 | +66.66 [+27.2, +90.3] |
| floor@3 + MPC | — | −213.74 [−236.1, −194.1] | — | +0.58 [−0.74, +1.71] | 93.46 | +2.22 [+1.81, +2.67] | 99.88 | +0.06 [+0.02, +0.11] | 4.21 | 1688 | −487.7 | +1.27 [−5.3, +2.8] |
| floor@3 + V3 guarded (DDQN) | 10 | **−207.58** [−228.0, −190.5] | 5.67 | **+6.74 [+0.30, +13.59]** | 88.71 | −2.52 [−4.23, −0.96] | 99.80 | −0.02 [−0.09, +0.05] | 4.45 | 1625 | −422.0 | +66.95 [+22.1, +93.7] |
| floor@3 + pure Dueling DDQN | 10 | −212.42 [−232.9, −194.7] | 4.71 | +1.90 [−4.28, +8.84] | 87.78 | −3.46 [−5.44, −1.65] | 99.85 | +0.02 [−0.05, +0.09] | 4.08 | 1742 | −422.6 | +66.41 [+28.6, +87.9] |
| floor@3 + pure Dueling DQN | 5 | −217.08 [−240.8, −196.0] | 7.46 | −2.77 [−13.65, +6.71] | 87.35 | −3.88 [−6.11, −1.82] | 99.67 | −0.16 [−0.54, +0.07] | 4.15 | 1750 | −475.4 | +13.61 [−86.0, +68.8] |
| Forecast z = 0.25 | — | −216.40 | — | −2.08 [−7.05, +3.25] | 82.72 | −8.52 | 99.70 | −0.12 | 5.36 | 1580 | −440.0 | +49.0 |
| Erlang-C 0.4 | — | −216.13 | — | −1.82 [−6.20, +3.11] | 85.88 | −5.35 | 99.79 | −0.03 | 5.07 | 1636 | −446.4 | +42.6 |

CVaR10 = mean daily return of the worst 10 % of DEV days (11 days; seed-averaged), higher is better.

## Findings

1. **No pure RL beats MPC on DEV.** Dueling DQN −8.5 (CI includes 0, seed SD 8.4), Dueling DDQN −3.2; both lose
   ~10–11 pp of queue-C SLA. The original Dueling DQN is the WEAKEST and least stable base (seed SD 8.35 vs 4.44);
   it also loses HIGH SLA (−0.24 pp, CI excludes 0).
2. **The V3 VAL figures are not comparable.** V3 reported Dueling DQN −184.0 and MPC −178.3 on V3 VAL. Those are
   the maximum of 10 noisy VAL evaluations of each run on the same 48 days used to pick `best.pt` (selection-biased,
   different days). Per-run best VAL returns of the 5 Dueling DQN seeds are −185.2 −187.7 −183.4 −183.1 −180.5 and
   of 10 DDQN seeds −185.5 … −187.9 (run.json files). On fresh DEV days the ranking reverses (DDQN > Dueling DQN).
   All V5 comparisons therefore use the same DEV days and evaluator, never VAL numbers.
3. **The static floor (queue C ≥ 3) is a general fix**, not an RL trick: it adds +2.2 pp C to MPC at no return
   cost and moves pure RL from −10 to −3.5 pp C. Only `floor@3 + V3 guarded` has a positive return CI vs MPC
   (+6.7 [+0.3, +13.6]) — but it still loses 2.5 pp of queue C (CI −4.2 to −1.0), i.e. it would fail a −2.0 pp
   non-inferiority margin on DEV (as it failed on TEST4).
4. **New observation — the lower tail.** Every RL-containing controller has a much better CVaR10 than MPC
   (+58 to +67, CIs exclude 0), except the unstable Dueling DQN. The worst DEV days are severe-overload / combined-
   shock days, where MPC's fluid model over-commits and RL's learned allocation does much better. RL's weakness is
   the middle of the distribution (normal days: queue-C protection, dithering); its strength is the bad days.
   This motivates reporting the lower tail in every comparison (E5/E9) rather than the mean only.
