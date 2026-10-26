# Agent E — new confirmatory evaluation (V4, TEST4) and the integration adapter

All numbers are **SIMULATED** (frozen V3 tape simulator).

Sources:
- `v4/e/results/eval_test4/*.csv`: 59 policies × 650 days, every file complete (651 lines).
- `v4/e/results/test4_analysis.json`, produced by `python -m v4.e.analyze_v4 test4`.
- Figures: `v4/e/figures/e5_test4_*.png`.

## In plain words
- We built a brand-new set of 650 simulated days that nobody had looked at, wrote down the rules of the contest
  **before** running it, and then ran it once.
- Classical MPC is still a very strong controller.
- One new learned design (learned allocation + a "keep at least 3 sessions on urgent" rule + a classical rule for
  how many sessions are open) **beats MPC on the overall score**: +6.9 per day, statistically significant. But it
  serves the urgent queue 2.7 points worse and HIGH-priority tickets 0.12 points worse, so it breaks the
  safety margins we set in advance.
- The learned design that **passes every pre-declared safety test** protects the urgent queue better than MPC
  (+1.8 points). But it is 4.6 points worse on the overall score, and it loses 0.6 % more customers.
- So: no learned policy is both safer and better than MPC. We recommend the safe one, and we report the faster one
  as an option that needs a human decision.

## 1. Test hygiene

| Item | Value |
|---|---|
| New TEST4 manifest | `v4/e/configs/test4_manifest.json`; seeds 1300000 + 1000·family + i; 13 families × 50 = **650 days** |
| TEST4 SHA256 | `cedc50afa1090457b8a1d6bf9748d06e2b25b1d8261169b2e292864e037545bd` (created 2026-10-25 23:26:11 UTC) |
| DEV manifest (exploration only) | `v4/e/configs/dev_manifest.json`; seeds 700000+; 104 days; SHA256 `d54493d254ce10b3526d8ffbb4527b382c8d9040a88a671a627ec16d190d639c` |
| Pre-registration | `v4/e/configs/preregistration.json` and `.md` |
| **Candidates frozen** | **2026-10-26T01:03:21Z**, before any TEST4 row existed. `evaluate_v4` refuses TEST4 for any policy that is not listed |
| Checkpoints | SHA256 of every best.pt recorded in the pre-registration |
| V3 TEST (seeds 900000+) | **not used** for any choice in V4 |
| Seed blocks | Disjoint: TRAIN 0–199,999; V3 VAL 500,000+; DEV 700,000+; V3 TEST 900,000+; TEST4 1,300,000+ |
| Exploratory vs confirmatory | Everything on VAL and DEV is exploratory. Only the pre-registered analysis below is confirmatory. Per-family tables and the single-seed numbers are exploratory |

**Pre-registered rules**
- Primary metric: the equal-weight return, i.e. the unchanged V3 reward.
- Reference: Fluid MPC k=0.5, the best rule on V3 VAL. It was not re-tuned.
- Constraints (paired 95 % CI lower bound vs MPC):
  - queue-C SLA > −2.0 pp;
  - HIGH SLA > −0.2 pp;
  - 0 HIGH tickets on fallback, 0 invalid proposals, budget respected on every day.
- Statistics: paired two-level bootstrap (V3 `boot_diff`), 4000 resamples, Holm correction over the 7 primary return
  comparisons.

## 2. Confirmatory results (TEST4, 650 days)

| Group | Seeds | Return [95 % CI] | Δ return vs MPC [95 % CI] | Holm p | Queue-C SLA % (Δ pp, CI low) | HIGH SLA % (Δ pp, CI low) | Lost % (Δ pp) | Cost/day (Δ) | Safe? |
|---|---|---|---|---|---|---|---|---|---|
| NEW floor@3 + guarded (Forecast capacity, V3 DDQN allocation) | 10 | **−217.2** [−226.7, −208.0] | **+6.89 [+2.99, +10.48]** | **0.006** | 88.4 (−2.74, −3.79) ✗ | 99.74 (−0.12, −0.254) ✗ | 4.70 (+0.08) | 1638 (−34) | **no** (C and HIGH) |
| V3 guarded hybrid (Forecast + DDQN) | 10 | −220.6 | +3.50 [−0.19, +6.97] | 0.24 | 81.7 (−9.41) ✗ | 99.65 (−0.22) ✗ | 4.96 (+0.34) | 1598 (−74) | no |
| NEW floor@3 + pure V3 DDQN | 10 | −222.4 | +1.62 [−2.42, +5.49] | 0.84 | 87.5 (−3.67) ✗ | 99.81 (−0.05, −0.181) ✓ | 4.42 (−0.20) | 1745 (+73) | no (C) |
| NEW floor@3 + MPC envelope (MPC capacity, DDQN allocation) | 5 | −223.9 | +0.18 [−5.69, +5.56] | 0.93 | 91.4 (+0.23, −1.53) ✓ | 99.74 (−0.12, −0.334) ✗ | 4.49 (−0.13) | 1699 (+27) | no (HIGH) |
| **MPC k = 0.5 (reference)** | — | −224.1 [−233.9, −214.3] | 0 | — | 91.1 | 99.86 | 4.62 | 1672 | — |
| floor@3 + MPC (fairness check, not RL) | — | −224.5 | −0.45 [−0.93, −0.02] | (secondary) | 93.0 (+1.91) ✓ | 99.90 (+0.03) ✓ | 4.55 | 1700 (+28) | yes |
| Erlang-C 0.4 | — | −226.9 | −2.80 [−4.69, −0.89] | (secondary) | 85.0 (−6.09) ✗ | 99.82 | 5.39 | 1652 | no |
| Forecast z = 0.25 | — | −227.0 | −2.97 [−4.99, −0.87] | (secondary) | 82.1 (−9.06) ✗ | 99.73 | 5.67 | 1597 | no |
| V3 pure RL: Dueling DDQN | 10 | −227.4 | −3.29 [−6.76, +0.41] | 0.25 | 80.4 (−10.74) ✗ | 99.71 (−0.16) ✗ | 4.68 | 1722 (+50) | no |
| **NEW floor@3 + guarded with Lagrangian DDQN** | 5 | −228.6 [−239.3, −218.2] | −4.57 [−8.74, −0.29] | 0.19 | **92.9 (+1.79, +1.16) ✓** | **99.82 (−0.05, −0.106) ✓** | 5.22 (**+0.60** [+0.48, +0.70]) | 1639 (−33) | **yes** |
| NEW Lagrangian DDQN (pure, constrained objective) | 5 | −234.3 | −10.28 [−15.33, −5.40] | 0.002 | 90.1 (−1.04, −1.75) ✓ | 99.80 (−0.07, −0.156) ✓ | 5.02 (+0.40) | 1740 (+68) | yes |

**Safety rows**
- Every policy had 0 HIGH tickets on fallback, 0 invalid proposals reaching execution, and no budget overrun on any
  of the 650 days.
- Fallback stayed ≤ 25 % of the day for every policy (fallback share 4–16 %).

**Secondary comparisons (pre-registered, not Holm-corrected)**

| Comparison | Δ return | Δ queue-C SLA |
|---|---|---|
| floor@3 + guarded vs V3 guarded (effect of the floor) | +3.39 [−1.01, +7.51] | +6.66 pp |
| floor@3 + pure DDQN vs V3 pure DDQN | +4.91 [+0.38, +9.09] | +7.07 pp |
| floor@3 + guarded vs floor@3 + MPC | +7.35 [+3.40, +11.01] | −4.66 pp |

Figures: `e5_test4_leaderboard.png`, `e5_test4_return_vs_queueC.png`, `e5_test4_per_family.png`.

## 3. Decision (by the pre-registered rule)

- **Does any new RL beat MPC?**
  - On return, yes: floor@3 + guarded is +6.89 [+2.99, +10.48], Holm p = 0.006.
  - Under the pre-declared safety constraints, **no**: that design misses the queue-C margin (CI low −3.79 pp vs
    −2.0) and the HIGH margin (−0.254 vs −0.2). So by the pre-registered rule, **no learned policy beats MPC**.
- **Recommended final Agent E (pre-registered rule: the safe NEW RL group with the highest return)**
  - **floor@3 + guarded with the Lagrangian Dueling DDQN.**
  - It is safe on every pre-declared constraint, and queue C is better than MPC (+1.8 pp).
  - It is **worse than MPC on return** (−4.6; the raw CI excludes 0; Holm p = 0.19). It loses **0.6 pp more
    customers**, and it is 2 % cheaper.
  - In plain terms, it is a safety-first controller, not a better one.
- **Option that needs a human decision**
  - floor@3 + guarded with the V3 DDQN: the best overall score, 2 % cheaper than MPC.
  - It accepts −2.7 pp queue-C SLA and −0.12 pp HIGH SLA.
  - Its gain comes almost entirely from the **severe_overload** family (exploratory per-family, Δ vs MPC):
    - severe_overload +75.2;
    - the other 12 families between −2.5 and +3.7;
    - in-distribution families +1.2 [−2.6, +4.7] (tie);
    - held-out families +16.0 [+9.9, +22.1].
- **The floor is a general fix, not an RL trick.** floor@3 also raises MPC's queue-C SLA (+1.9 pp) at a tiny
  return cost (−0.45).
- **V3 findings replicate on fresh days:**
  - V3 pure DDQN −3.3 vs MPC (V3 TEST: −3.7);
  - V3 guarded +3.5 (V3 TEST: +4.1);
  - the queue-C deficit is ~−9 to −11 pp in both tests.

## 4. Recommended tiny RL model (deployment artifact)

| Field | Value |
|---|---|
| Spec (adapter / evaluator) | `floor@3|guarded:dueling_double_dqn_h64x64_150k_lag0d2t0.9_s1` (`v4/e/configs/recommended.json`) |
| Checkpoint | `experiments/agents_ef/v4/e/runs/dueling_double_dqn_h64x64_150k_lag0d2t0.9_s1/best.pt` (git-ignored like V3 checkpoints) |
| SHA256 | `ed5810c186ed90c915f524e829da17e3b5384cceed8803711894eae5dff5d025` |
| Network | Dueling Double DQN, 43 → 64 → 64 → (V + 17 advantages); **8,146 params, 34.9 KB** |
| Training | 150k steps, equal-weight reward − λ·(queue-C failures)/F_ref, dual ascent to queue-C SLA target 0.90 (λ_final 5.33); 624 s on 1 CPU thread |
| Seed choice | Seed 1 = best DEV return in its group (−213.8, DEV queue-C 92.2 %). Chosen on DEV only. Its single-seed TEST4 return is −222.8 (exploratory, not used for the choice) |
| Structure | Forecast(z=0.25) owns activate/deactivate. The network chooses moves, keep and the capped fallback. Queue C is always ≥ 3 sessions |
| Decision latency (TEST4 evaluator) | p50 0.34 ms, p95 0.52 ms (MPC: 2.2 / 2.8 ms) |
| Adapter latency (whole propose(), incl. snapshot parsing) | p50 ~1.6 ms, p95 ~2.6 ms (demo day) |

**Performance-first alternative**
- Spec: `floor@3|guarded:dueling_double_dqn_equal_h64x64_150k_s1` (V3 checkpoint).
- SHA256 `4586ec1ba13354348c6d55e1244e27a971f09d03dc8f0104753c1c61d8cb0272`, also 8,146 params.
- Seed = best DEV return.

## 5. E6 — standalone adapter (`v4/e/adapter.py`)

- **Load:** `AgentEAdapter.load()` reads `configs/recommended.json`. It also accepts `spec=...` or a run id with
  `floor=` / `shield_target=`.
- **Propose:** `.propose(snapshot) -> dict`, a PROPOSAL only. The adapter never acts and never mutates the snapshot.
- **Snapshot builder:** `snapshot_from_env(env: EnvV3) -> snapshot`.
- **Snapshot schema:** the V2 schema of `integration/agent_e_policy.py`, unchanged:
  - top-level fields: `t_step`, `fallback_on`, `fallback_steps_used`, `budget_spent`, `capacity`;
  - one optional new field, `budget_total` (default 16 × 96 × 1.15 = 1766.4);
  - `queues`: 4 entries in the order A_status, B_refund, C_urgent, D_availability, each with `alloc`,
    `arrivals_last_step`, `ewma_arrivals`, and `waiting` = a list of `{priority_label, priority_score, waited_min}`.
  - Worker D's interface request is satisfied as specified.
- **Same code path as the env:**
  - `SnapshotViewV3` fills exactly the attributes that `EnvV3._obs`, `EnvV3.action_mask` and `EnvV3._load` read,
    then calls those unbound methods.
  - The policy itself is `policies.make_policy(spec)`, the same object the evaluator scored.
- **Output fields:** `action_id`, `action` (type/from/to/text), `policy`, `q_values` (17, masked = null),
  `rl_preference`, `decided_by`, `mask`, `safety_veto` and `veto_reason` (when the urgent floor changed the decision),
  `fallback_reason` (when the checkpoint is missing or broken, a backup floor@3 + MPC rule answers), `urgent_floor_c`,
  `fallback_scope`, and `audit` = {adapter_version, run_id, model_sha256, n_params, obs_sha256, latency_ms}.
- **Tests** (`v4/e/tests/test_adapter.py`, **14 pass**; with the V3 env tests: 39 pass; the repo's `tests/`:
  63 pass). They cover:
  - obs equivalence adapter vs env on 70+ real env states (atol 1e-5), and mask and `_load` equivalence;
  - no snapshot mutation;
  - unshielded adapter = env greedy policy;
  - urgent floor never violated by Agent E's action, and vetoes reported with a reason;
  - shield logic below the floor;
  - HIGH never on fallback, even with fallback forced on;
  - deterministic reload (same hash, same Q-values);
  - latency bound (< 20 ms);
  - missing checkpoint → backup rule;
  - malformed snapshot rejected;
  - full-day adapter-driven run identical to the evaluator for 3 specs;
  - the recommended config loads and its hash matches the pre-registration.
- **Demo:** `python -m v4.e.demo_adapter` (offline, one severe_overload day). It prints proposals, vetoes, the day's
  KPIs and an audit summary. Example output: 7 floor vetoes, 0 HIGH on fallback, 0 invalid, budget OK, but queue-C
  SLA only 78 % on that overload day. This is the reminder that a floor constrains **allocation**, not future SLA.

## 6. Commands (run from `experiments/agents_ef`)

```bash
PY=/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python
$PY -m pytest -q v4/e/tests v3/e/tests                     # 39 tests
$PY -m v4.e.evaluate_v4 --split dev --policy-file v4/e/configs/evalsets/dev_floor2.txt   # DEV (exploratory)
bash v4/e/run_test4.sh                                     # TEST4: only pre-registered policies (resumable)
$PY -m v4.e.analyze_v4 test4                               # confirmatory analysis + figures
$PY -m v4.e.demo_adapter                                   # adapter demo with the recommended model
```

## NOT VERIFIED / limits
- All results are simulated. There is no real ShopNova traffic, and the simulator's ASSUMPTIONS hold (see V3
  `02_SIMULATOR_VALIDATION.md`).
- The recommended group has 5 training seeds; the V3-weight groups have 10. The MPC-envelope group was cut to
  5 seeds to save CPU.
- The DEV-chosen choices are exploratory: floor k = 3, the candidate set and the deployment seed. DEV contains the
  held-out families, so they are no longer "unseen by selection" (they are still unseen by training).
- The Lagrangian training is non-stationary (λ oscillates between 0.2 and 10). The constraint holds on TEST4 for this
  checkpoint, but it is not a formal guarantee.
- The adapter is not wired into `callverse/`. That needs an approved task (CLAUDE.md). It is tested only against the
  simulator's snapshots, not against the prototype's live queue.
- The single-seed TEST4 number of the deployed checkpoint (−222.8) is exploratory.
