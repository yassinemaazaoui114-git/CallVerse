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

- 16:20 an interim report was sent to Worker D by mistake (harness prompt); work continues with the full plan.

## E7a — runtime hysteresis hyst@2 on frozen nets (DEV, 16:35) — NEGATIVE
- Dueling DQN 5 seeds: −258.0 vs −222.8 unshielded, Δ −35.2 [−70.1, −7.6]; flips/day 37.0 → 0; act+deact/day 51.4 → 44.8.
- Dueling DDQN 10 seeds: −255.9, Δ −38.4 [−69.4, −14.5] (seeds −215 … −366); ΔC −3.1 pp.
- MPC: Δ −0.19 [−0.99, +0.54] (MPC flips only 5.9/day).
- Conclusion: the nets USE activate→deactivate pairs as an indirect "move" (activation goes to the most-loaded queue,
  deactivation removes from the least-loaded); forbidding the reversal at runtime breaks the learned behaviour.
  Dithering is a symptom of the 17-action design, not removable after training. Runtime hysteresis rejected.

## E2 — shield analysis (DEV, `python -m v5.e.shield_analysis` → results/e2_shield.json) (16:35)
- floor@3 around pure RL: shield active (removes ≥1 action) on 69–74 % of steps, but changes the executed action on
  only 15.1 % (DDQN) / 20.3 % (Dueling DQN) of steps; replacement by a non-RL default 0 % (the RL always re-chooses
  inside the shielded mask) → 84.9 % / 79.7 % of decisions are the RL's unconstrained own choice. Agreement with
  MPC 24 % (same as without the shield) → NOT MPC in disguise. Effect DDQN: Δret +5.1 [+0.6, +9.3], ΔC +7.0 pp.
- floor@3 around V3 guarded: action changed on 26.0 % of steps; RL own 29.5 %, RL re-choice 8.7 %, owner rule
  (Forecast) 61.8 % → in the guarded hybrid the RL decides only ~38 % of steps; this is a property of the guarded
  structure (owner decides capacity AND replaces every RL activate/deactivate), not of the floor.
- Erlang shield@0.2: changes 27–48 % of actions and costs −18 to −29 return for every controller (incl. MPC) →
  an over-protective ESTIMATED-risk shield; rejected (confirms V4).
- Hard constraints: 0 invalid proposals executed, 0 HIGH on fallback, 0 budget overruns for every controller.

## Stage 1 result and promotion decision (16:45) — `python -m v5.e.ablation` (DEV, 104 days, seeds 0–2, paired)
| arm | wrapper | arm return (seed SD) | control (seed SD) | Δ return [CI] | Δ C pp [CI] | Δ CVaR10 [CI] |
|---|---|---|---|---|---|---|
| PER | pure | −216.56 (1.6) | −226.74 (7.3) | +10.18 [+2.34, +23.85] | +3.47 [+1.46, +5.29] | +65.7 [−8.0, +192.4] |
| PER | floor@3 | −211.52 (0.7) | −221.06 (4.6) | +9.54 [+2.65, +20.34] | +2.10 [−0.26, +4.30] | +71.4 [+7.5, +177.5] |
| N3 | pure | −229.08 (4.3) | −226.74 | −2.34 [−13.52, +10.68] | −1.60 [−3.29, +0.37] | +16.4 |
| N3 | floor@3 | −224.65 (5.6) | −221.06 | −3.60 [−14.01, +6.95] | −0.48 | +2.1 |
| DR | pure | −216.65 (1.0) | −226.74 | +10.08 [+2.05, +23.30] | −1.72 [−3.83, +0.24] | +73.1 [−2.8, +200.8] |
| DR | floor@3 | −210.06 (0.9) | −221.06 | +10.99 [+4.03, +21.44] | −1.31 | +72.8 [+9.5, +179.3] |
| FLIP | pure | −220.74 (4.6) | −226.74 | +6.00 [−3.49, +20.54] | +0.43 | +47.6 |
| FLIP | floor@3 | −213.74 (4.9) | −221.06 | +7.32 [−0.76, +18.75] | −0.03 | +46.3 |
- Pre-declared rule (Δreturn ≥ +2.0 pure, or ΔC ≥ +2 with Δret ≥ −2): **PER, DR, FLIP promoted** (+seeds 3, 4);
  **N3 dropped** (Δ −2.3, ΔC −1.6) → n = 5 is NOT run (its pre-declared condition failed).
- Caution written now: control seed 2 (−234.6) is the worst V3 Dueling DQN seed, so seeds 0–2 favour every arm;
  the large Δs are partly "the arms are more stable than the control". Seed SDs of PER (1.6) and DR (1.0) vs control
  7.3 are themselves a finding (stability), to be confirmed with seeds 3–4.
- Stage 2 queue started 16:46 (6 runs).

## Stage 2 result → validation decision (17:05) — 5 seeds vs control seeds 0–4 (`results/ablation.json`)
| arm | DEV Δ return [CI] | DEV Δ C pp [CI] | seed SD arm / ctl | DEVSHIFT Δ return | DEVSHIFT Δ C pp | Δ CVaR10 DEV |
|---|---|---|---|---|---|---|
| PER | +6.98 [−1.06, +19.89] | +2.92 [+0.94, +5.14] | 1.9 / 8.3 | +7.19 [−0.47, +22.57] | +2.96 [+0.77, +5.11] | +50.4 [−4.5, +158.5] |
| DR | +5.62 [−2.41, +19.10] | −1.44 [−3.86, +1.42] | 1.9 / 8.3 | +4.22 [−3.97, +20.09] | −1.73 [−4.50, +0.70] | +55.1 [−3.7, +171.4] |
| FLIP | +5.34 [−4.73, +19.26] | +2.19 [−1.97, +6.26] | 5.8 / 8.3 | +6.32 [−2.50, +21.85] | +2.49 [−1.62, +6.52] | +42.2 [−22.0, +159.2] |
- Pre-declared rule (Δret > 0 AND ΔC ≥ −1.0, or ΔC ≥ +2 with Δret ≥ −2; DR also on DEVSHIFT):
  **PER validated, FLIP validated, DR NOT validated** (queue C −1.44 pp on DEV and −1.73 pp on DEVSHIFT, i.e. its own
  validation distribution; DR's return gain does not come with better queue-C protection).
- Honest caveat: no Δreturn CI excludes 0 at 5 seeds (control seed SD 8.3); the clearest, CI-backed effects are PER's
  queue-C gain (+2.9 pp, CI > 0 on DEV and DEVSHIFT) and the 4× smaller seed spread of PER and DR.
- **Stage 3 (17:06):** PER + FLIP on Dueling DQN (seeds 0–4) and on Dueling Double DQN (seeds 0–4) = 10 runs.
  Budget after queueing: 28 of 45 runs used (12 + 6 + 10; plus a 15k-step reproduction check).
- E6 decision (rule pre-declared at 15:45): 17 runs left (≥ 8) and the planned TEST5 freeze is ≈ 19:30 UTC
  (≥ 2.5 h away) → QR-DQN IS run: 3 seeds of the better Stage-3 base with a QR head + PER + FLIP, queued after
  Stage 3 (base chosen by Stage-3 DEV return, written here before QR results).
