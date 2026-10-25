# 03 — Benchmark protocol V3

Agent E and Agent F are separate benchmarks, run concurrently as two independent workstreams:
- **Worker E:** `v3/e/`, CPU.
- **Worker F:** `v3/f/`, CPU; there is no GPU in this sandbox.

Each worker has its own code, logs, manifests, checkpoints and resume commands.

---

## Agent E

### Environment
- `v3/e/env_v3.py`: tape-based, validated in `02_SIMULATOR_VALIDATION.md`.
- Same action space (17 actions), mask and safety layer for every policy.
- Observation: 43 aggregate values. They include Intake priority aggregates, and no text.

### Reward
- Reference-normalised, equal weights (locked before RL training; §3 of 02).
- Sensitivity presets: sla_heavy, abandon_heavy, cost_heavy.

### Candidates

| Type | Policies |
|---|---|
| Rule | Fixed (planned 16 sessions); Threshold; Priority; **Random valid action** (masked); Forecast (EWMA + square-root staffing, z ∈ {−0.5 … 1}); **Erlang-C** staffing (target ∈ {0.95 … 0.05}); **Fluid MPC** (6-step lookahead over all valid actions with the same objective, safety margin k ∈ {0 … 3}) |
| RL, 150k steps, matched budget | DQN, Double DQN, Dueling DQN, Dueling Double DQN, PPO (masked, GAE); Tabular Q (reference) |
| Hybrid | Forecast (z chosen on VAL) owns activate/deactivate; the RL policy owns allocation and capped fallback ("guarded:") |

**Rule tuning.** Rule parameters are chosen on VAL only (`v3/e/results/val_choice.json`): Forecast z = 0.25, Erlang target = 0.4, MPC k = 0.5.

### Training (`v3/e/train_v3.py`, queue `v3/e/run_queue_e.sh`: 66 runs; E+F queue `run_queue_e2.sh`: 3 runs)
- TRAIN days: random seeds 0–199,999, a random TRAIN family per day.
- Shared hyper-parameters: γ = 0.97; DQN family Adam 5e-4, replay buffer 100k, batch 128, target network every 2k steps, ε from 1 to 0.05 over 60k steps; PPO lr 3e-4, rollout 2048, clip 0.2.
- Checkpoint = best greedy VAL return (48 VAL days), evaluated every 10% of the budget.
- Seeds:
  - 10 (0–9): Dueling DDQN, PPO, DQN;
  - 5: Double DQN, Dueling DQN, Tabular Q.
- Ablations, 3 seeds each:
  - reward weights (sla_heavy, abandon_heavy, cost_heavy);
  - model size (32×32, 128×128);
  - training budget (400k steps, Dueling DDQN and PPO), labelled separately from the 150k results.

### Locked TEST evaluation
- 650 fresh days (13 families × 50) at seeds 900,000+.
  - Hash: `v3/e/configs/test_manifest.sha256`.
  - 8 families are in-distribution; 5 are held out (evening_peak, refund_surge, combined_shock, severe_overload, random_shape).
- Every policy is evaluated on the identical tapes (`v3/e/evaluate_v3.py`).
- **Target vs actual sample size:** the target was 300 days per scenario; we used 50 per family (650 in total) because of the CPU budget (4 cores shared with Worker F). Seed and day uncertainty are both reported, so this lowers precision, not validity.
- **Freeze rule:** TEST rows of the rules were generated while the RL training was still running, but they are **not inspected** until the candidate set is frozen. The freeze is recorded in `BENCHMARK_STATUS.json`. No hyper-parameter, checkpoint or candidate is chosen on TEST.

### Statistics (`v3/e/analyze_v3.py`, `analyze_v3_report.py`)
- **Reference** = the best rule by VAL return.
- **Paired differences per day.** Each learned policy is represented by 3–10 training seeds.
- **95% CIs** from a two-level bootstrap: resample seeds, then days, with the same days for both policies.
- **Effect size** d_z = mean per-day difference / SD of per-day differences. Also reported: the win rate.
- **Holm correction** across the primary comparisons of every learned policy vs the reference on return.
- **Weight-free evidence:** Pareto fronts (cost vs SLA failure vs lost), SLA at matched cost, and cost at matched SLA against the Forecast and Erlang-C sweeps (no extrapolation).
- **Weight sensitivity:** returns recomputed exactly from the KPIs under every preset.

### KPIs
- Return; overall SLA; HIGH / MEDIUM / LOW SLA; queue-C SLA.
- Abandonment; unresolved at day end; lost.
- Mean and p95 waiting time; cost (session-steps); budget compliance.
- Fallback share; HIGH tickets on fallback (must be 0); invalid proposals; safety interventions.
- SIM-CSAT: **synthetic**, a KPI only.
- Parameters; checkpoint size; decision latency p50/p95; peak RAM; training time; learning curves.

---

## Agent F

Protocol: `v3/f/PROTOCOL.md` (Worker F). In short:
- **Label types stay separate:**
  - genuine customer ratings (none reachable for support conversations);
  - human dialogue-quality / satisfaction annotations (USS);
  - product-review stars (Amazon EN/FR);
  - synthetic (rejected).
- Splits are grouped by dialogue.
- VAL-only selection; ≥ 3 seeds.
- Ordinal metrics: MAE, RMSE, QWK, Spearman, exact / within-1 accuracy, macro-F1 (3 classes), confusion matrices.
