# Agent E v5 — lab notebook (Worker E, session 2026-10-26, from 15:30 UTC)

Rules: v3/ and v4/ are frozen evidence (imported / subclassed, never edited). V3 TEST (900000+) and TEST4 (1300000+)
were already inspected → never used for selection. Selection uses V3 VAL (checkpoint choice inside a run, as in V3)
and the V4 DEV manifest (104 days, sha d54493d2…) for model choice; DEVSHIFT (new, below) for robustness choice.
TEST5 (new) is evaluated once, after a frozen pre-registration. Every number here comes from a file in v5/e/results
or an existing v3/v4 file (cited). Hardware: 4 CPU cores shared with Worker F, no GPU; ≤ 2 training processes.

## 0. Setup (15:30–15:45)
- Code: `agents5.py` (SumTree, PER, n-step, QR-DQN; subclasses rl.agents.DQN), `common5.py` (EnvV5 = EnvV4 +
  per-day shift / domain randomisation; manifests; loader for v5+v4+v3 runs), `train_v5.py`, `configs/dr_ranges.json`.
- Tests: `python -m pytest v5/e/tests -q` → 19 passed (sum tree, PER distribution / IS weights / eps / clip /
  reproducibility / unfilled slots, n-step targets incl. truncation at day end and no cross-day windows, γ^n
  bootstrap with Double target, QR shapes; EnvV5 == EnvV3 without shift, shifts reproducible and policy-independent).
- **Reproduction check:** `train_v5 --algo dueling_dqn --seed 0 --steps 15000` (all options off) gives VAL return
  −824.4428 at 15k steps = V3 run `dueling_dqn_equal_h64x64_150k_s0/val_log.csv` (−824.4428). The v5 trainer with
  options off IS the V3 trainer, so the 5 frozen V3 Dueling DQN checkpoints (seeds 0–4) are a valid matched
  control (same code, same seeds, same TRAIN-day stream, same 150k budget, same VAL selection). This saves 5 runs.
- PER cost: +1.35 s per 1000 updates (≈ +50 s per 150k run, ~10 %).

## Pre-declared plan and stopping rules (written 15:45 UTC, BEFORE any v5 training result)
Base for the ablation = **Dueling DQN 64×64** (user spec). Matched budget: 150k env steps, same hyper-parameters,
best.pt by V3 VAL return (identical to V3). Control = V3 Dueling DQN seeds 0–4 (reproduced exactly).
Each arm uses seeds 0,1,2 first: same torch init and the same TRAIN-day stream as control seeds 0,1,2 (paired seeds).

**Stage 1 (individual components, 3 seeds each = 12 runs):**
- A-PER: proportional PER α 0.6, β 0.4→1 (linear over 150k), eps 1e-3, |TD| clip 5.
- A-N3: 3-step returns (n = 5 only if n = 3 passes the promotion rule below).
- A-DR: domain randomisation (configs/dr_ranges.json train_ranges).
- A-FLIP (E7, motivated by V4 diagnosis H2 = 60 % activate/deactivate dithering): training-only penalty
  0.0625 (= one session-step of reward) on an activate within 2 steps after a deactivate or the reverse.
**DEV metrics per arm:** evaluated as pure greedy RL (`rl:`) and inside the static floor (`floor@3|rl:`), 104 DEV days,
paired two-level bootstrap vs control on the SAME seeds (v3 boot_diff).
**Promotion rule (Stage 1 → Stage 2, +seeds 3,4):** arm promoted iff, as pure RL on DEV vs control seeds 0–2,
  Δreturn ≥ +2.0, OR (Δ queue-C SLA ≥ +2.0 pp AND Δreturn ≥ −2.0). Otherwise dropped (no more seeds).
  For A-DR the DEVSHIFT return may replace DEV return in this rule (its stated purpose is robustness), and its
  lower tail (CVaR10 % of daily return) is reported.
**Individually validated (after Stage 2, 5 seeds vs control 0–4):** Δreturn (point) > 0 AND Δ C-SLA ≥ −1.0 pp,
  OR Δ C-SLA ≥ +2.0 pp AND Δreturn ≥ −2.0 (for DR: same on DEVSHIFT).
**Stage 3 (combination):** union of validated components on Dueling DQN (5 seeds) AND on Dueling Double DQN (5 seeds;
  control = V3 Dueling DDQN seeds 0–4, also reproduced by the same code path). If only one component is validated,
  it is transferred alone to Dueling DDQN (5 seeds). If none is validated: the best Stage-1 arm by Δreturn is run on
  Dueling DDQN with 3 seeds, labelled exploratory, and the result is reported as negative.
**E6 (QR-DQN):** run (3 seeds, on the best Stage-3 configuration with a QR head) only if ≥ 8 training runs of the
  45-run budget AND ≥ 2.5 h before the planned TEST5 freeze remain after Stage 3 is queued. Otherwise skipped (reason
  written here). If run: risk-NEUTRAL greedy (argmax of the mean); it is not called risk-aware.
**No other tuning:** no learning-rate / network / α / β sweeps (no uncontrolled sweeps).

## 1. Manifests (15:44 UTC) — written before any v5 result
- `configs/devshift_manifest.json` (DR validation distribution): 8 TRAIN families × 6 days, seeds 760000+1000k+i,
  each day with a shift drawn from the DR TRAINING ranges. SHA256 1ecf04613d4a2a06b78a114d074c52bb59f7911062871e3b368c2b46312ae965.
- `configs/test5_manifest.json` (NEW confirmatory test, NOT evaluated until pre-registration): 13 V3 families +
  3 UNSEEN-SHIFT families (shift_slow_service: all service ×1.20–1.35; shift_impatient: patience ×0.45–0.65;
  shift_urgent_wave: queue-C ×2.8–3.5 for 90–150 min; all outside the DR training ranges) × 50 days = 800 days,
  seeds 1700000+1000k+i. SHA256 deb698ca2594ae9ab02370d40e8ec8cbcce778f07b40a8a820b73a2fd5765c88.
  evaluate_v5 refuses `--split test5` for any policy not in configs/preregistration5.json.

## 2. Evaluator consistency (15:50)
- v5 evaluator (policies5 re-implementation of floor / guarded / rl / rule + provenance) vs the v4 CSVs on DEV:
  `floor@3|rl:DDQN s0`, `floor@3|guarded:DDQN s0`, `rule:mpc:0.5` → 0 mismatching cells (all KPI columns, 104 days).
  Copies kept in results/consistency_check/. v5 "intervened" = v4 "shield_vetoes" for the RL inner (1322 = 1322).
  New: for the guarded inner v4 counted 0 vetoes (it only counted for `rl:`); v5 counts 3063 interventions
  (30.7 % of steps) → E2 below.

## E7 runtime anti-dithering — pre-declared (15:58, before evaluation)
- Question: V4 diagnosis H2 = RL spends ~60 % of decisions on activate/deactivate, often reversing. Does a runtime
  hysteresis (no activate within 2 steps after a deactivate, and the reverse; `hyst@2|…`) reduce reversals and
  change DEV return / queue-C SLA of the frozen V3 nets, with no retraining? Single setting k = 2 (no sweep).
  It complements the training-time flip cost arm (A-FLIP).
