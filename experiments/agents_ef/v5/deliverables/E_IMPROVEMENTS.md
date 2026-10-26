# Agent E v5 — implemented improvements and their tests

All code is in `experiments/agents_ef/v5/e/`. Nothing in `v3/`, `v4/` or `callverse/` was changed: v5 subclasses
`rl.agents.DQN`, `v4.e.common.EnvV4` (itself a subclass of the frozen `EnvV3`) and re-uses the V3/V4 statistics.

| Component | File | What it does (simple words) | Why it is here (question it answers) |
|---|---|---|---|
| Prioritized Experience Replay (PER) | `agents5.py` (`SumTree`, `DQN5`) | The replay memory picks "surprising" past situations (large prediction error) more often. A sum tree makes picking proportional to priority fast. | V4 diagnosis: queue-C failures are rare and delayed, and the network under-values protecting C exactly in those rare states. Does replaying them more often fix it? |
| N-step returns | `agents5.py` (`DQN5.observe`, `_targets`) | The learning target adds up the next n rewards before trusting the network's own estimate. | The cost of not protecting queue C shows up several 5-minute steps later. Does propagating it faster reduce abandonment / queue-C misses? |
| Domain randomisation (DR) | `common5.py` (`EnvV5`, `draw_shift`), `configs/dr_ranges.json` | Each training day gets slightly different service times, patience, demand shape, urgent spikes, refund surges and capacity failures. | The simulator's service times / patience are invented (V3 report 02 §5). Does training on plausible variations make the policy more robust (lower tail, unseen shifts)? |
| Training flip cost (E7) | `train_v5.py --flip-cost` | During training only, a small penalty when the agent switches a session on right after switching one off (or the reverse). | V4 diagnosis H2: ~60 % of RL decisions were activate/deactivate dithering. |
| Runtime hysteresis (E7) | `policies5.py` `hyst@k` | At decision time, forbids reversing the capacity level within k steps. No training. | Same question, without retraining. |
| QR-DQN (small, optional E6) | `agents5.py` (`QRNet`, `QRDQN`) | Predicts 21 quantiles of the future return per action instead of one average; acts on the mean (risk-neutral). | Only run if E3–E5 justify it (see E_ABLATIONS.md). |
| Decision provenance | `policies5.py`, `evaluate_v5.py` | Each decision is labelled: RL's own choice, RL re-choice inside the shield, owner rule, shield default. Optional agreement with MPC. | E2: is a shielded controller still RL, or MPC in disguise? |
| Shifted / unseen test families | `common5.py`, `configs/dr_ranges.json` | TEST5 adds slow service ×1.20–1.35, impatient customers ×0.45–0.65, and a long urgent wave ×2.8–3.5 — all outside the DR training ranges. | E5/E9: robustness to conditions never trained on. |

## Implementation details that matter for correctness

- **PER (proportional, Schaul et al. 2016).** priority `p = (min(|TD|, 5) + 1e-3)^0.6`; new transitions get the
  current maximum priority; stratified sampling (one uniform draw per equal slice of total priority) with the agent's
  seeded `numpy.Generator`; importance weights `w = (p_min / p_i)^β` (= (N·P(i))^-β normalised by its maximum, so
  w ∈ (0,1]); β annealed linearly 0.4 → 1 over the 150k-step budget; loss = mean(w · Huber(TD)); priorities updated
  with the new |TD| after each update. Unfilled buffer slots can never be sampled (index clipped to the filled size;
  their priority is 0).
- **N-step.** A per-day window of (obs, action, reward); when it holds n steps, the stored transition is
  `(s_t, a_t, Σ_k γ^k r_{t+k}, s_{t+n}, done, mask_{t+n}, γ^n)`. The day ends at step 96: this is a TRUE terminal
  (tickets still waiting are counted as lost), so at day end the remaining partial windows are flushed with
  `done = 1` (no bootstrap) and their own γ^k. Windows never cross days. The target is
  `R^(n) + γ^n (1 − done) Q_target(s_{t+n}, a*)`, with `a*` from the online net when Double is on. Caveat: no
  off-policy correction for ε-greedy behaviour (standard in Rainbow-style n-step DQN; slight bias).
- **Exact V3 fallback.** With PER off and n = 1, `DQN5` calls the unchanged V3 `observe` / `_update`. Checked: the
  v5 trainer reproduces the V3 run `dueling_dqn_equal_h64x64_150k_s0` exactly at 15k steps (VAL −824.4428 both).
  Therefore the frozen V3 checkpoints are a valid matched control (same code, seeds, TRAIN-day stream, budget,
  checkpoint rule).
- **DR environment.** `EnvV5` changes the exogenous day spec BEFORE the ticket tape is built (common random numbers
  still hold: every policy sees the same world for the same (seed, shift)); service-time multipliers act inside the
  event-driven service like the existing `slowdown` family and are NOT visible in the observation; patience
  multipliers recompute the pre-drawn abandonment times. Without a shift EnvV5 equals EnvV3 bit for bit (tested).
- **Evaluator.** `evaluate_v5.py` re-implements the V4 policy grammar only to add provenance; on DEV it reproduces the
  v4 CSV rows with 0 mismatching cells (3 policies × 104 days; copies in `v5/e/results/consistency_check/`).

## Tests

`cd experiments/agents_ef && python -m pytest v5/e/tests -q`

| Test | Checks |
|---|---|
| test_sumtree_total_min_and_update_with_duplicates | sums / minimum after updates, duplicate indices, refuses p ≤ 0 |
| test_sumtree_find_boundaries | prefix-sum search at exact boundaries |
| test_per_sampling_distribution_matches_priorities | empirical sampling frequency = p_i / Σp (±1.5 pp, 24k draws) |
| test_per_is_weights_normalised_and_annealed | w = (p_min/p_i)^β, max ≤ 1, β schedule 0.4 → 0.7 → capped at 1 |
| test_priority_update_eps_clip_and_max | zero-TD gets ε, clip at 5 (here 2), new transitions get max priority |
| test_per_sampling_reproducible_with_seed | same seed → same indices; different seed → different |
| test_per_never_samples_unfilled_slots | indices always < filled size |
| test_nstep_targets_and_terminal_truncation | Σγ^k r, γ^n stored, terminal windows flushed at day end with done = 1 |
| test_nstep_window_does_not_cross_days | no reward mixing across days |
| test_nstep_one_equals_v3_dqn_transitions | n = 1 stores exactly what V3 stores |
| test_bootstrap_target_uses_gamma_n_and_done | Double target with γ^n; no bootstrap when done |
| test_per_update_runs_and_changes_priorities | PER + n-step learning step runs and updates priorities |
| test_qrdqn_shapes_and_update | quantile shapes, mean = Q, finite loss |
| test_make_agent5_names | factory |
| test_no_shift_identical_to_v3 | EnvV5 == EnvV3 (return and every KPI) on 3 families |
| test_shift_reproducible_and_policy_independent_world | same (seed, shift) → same tape and abandonment times |
| test_slow_service_hurts_and_patience_shift_applies | service ×1.3 lowers return; patience ×0.5 halves patience exactly |
| test_dr_draws_in_range_and_reproducible | every DR draw inside the declared ranges; reproducible |
| test_unseen_shifts_outside_training_ranges | TEST5 shift ranges lie outside the DR training ranges |

Result: see E_REPRODUCE.md for the final count (19 passed at 15:45 UTC).
