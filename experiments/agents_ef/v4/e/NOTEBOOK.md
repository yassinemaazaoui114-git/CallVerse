# Agent E v4 — lab notebook (Worker E, overnight session 2026-10-25/26)

Rules I follow: V3 is frozen (read-only). V3 TEST (seeds 900000+) was already inspected → never used for tuning or as
the new final test; reading its rows for *descriptive* diagnosis is labelled "V3-TEST (descriptive)". Selection and
refinement use V3 VAL (diagnosis) and the NEW DEV manifest. The NEW TEST4 manifest is evaluated once, after
pre-registration. Every number below comes from a file under v4/e/results/ (or the cited v3 file).

## 0. Setup (23:05)
- DEV manifest: `configs/dev_manifest.json`, seeds 700000 + 1000*family_index + i, 13 families x 8 days = 104 days,
  SHA256 d54493d254ce10b3526d8ffbb4527b382c8d9040a88a671a627ec16d190d639c.
  Note: DEV contains the 5 held-out families. They stay UNSEEN IN TRAINING (training only draws TRAIN families), but
  they are visible to DEV selection. Declared here, before any DEV result.
- Sanity: EnvV4 (bookkeeping wrapper) reproduces V3 exactly: MPC k=0.5 on the first 4 VAL days -126.055 in v4 vs
  -126.055 in v3/e/results/eval_val/rule__mpc__0.5.csv.

## Pre-declared DEV design target (written BEFORE any DEV result)
- A new candidate is "safe enough" on DEV if: queue-C SLA >= MPC(k=0.5) queue-C SLA - 1.0 pp, HIGH SLA >= MPC HIGH
  SLA - 0.2 pp, 0 HIGH tickets on fallback, 0 invalid proposals reaching execution, budget always respected.
- Among safe candidates, rank by DEV equal-weight return (the unchanged v3 reward).
- The confirmatory margin on TEST4 is wider (declared in the pre-registration), because DEV is small.

## Exp 1 — DEV re-evaluation of baselines and frozen V3 checkpoints (23:07–23:15)
- Question: on new days never used for any selection, how do V3 policies compare to MPC, and which tiny RL base is best?
- Command: `python -m v4.e.evaluate_v4 --split dev --workers 2 --policies rule:mpc:0.5 rule:forecast:0.25 rule:erlang:0.4 rule:fixed rule:priority rl:<36 V3 runs> guarded:<15 V3 runs>`
- Result (results/eval_dev/*.csv, `python -m v4.e.analyze_v4 dev`): MPC -214.3 (queue-C SLA 91.2 %),
  Erlang -216.1 (C 85.9), Forecast -216.4 (C 82.7), DDQN 10 seeds -217.5 (C 80.8, Δret vs MPC -3.2 [-8.9,+4.4],
  ΔC -10.4 pp [-13.9,-7.4]). The V3 TEST pattern replicates on DEV: tie on return, large queue-C deficit.
- E3 base choice (matched seeds 0-4, DEV, independent of checkpoint selection):
  Dueling DQN -225.4 -220.2 -234.6 -222.2 -211.6 → mean -222.8, seed SD 7.5;
  Dueling DDQN -216.5 -217.7 -217.8 -222.8 -214.9 → mean -217.9, seed SD 2.7.
  The V3 VAL advantage of Dueling DQN (-184.0 vs -186.7) is the MAXIMUM over 10 noisy VAL evaluations of each run
  (the same days used to pick best.pt), so it is optimistically biased; on fresh DEV days it reverses and its seed
  spread is ~3x larger. Decision: base = Dueling Double DQN 64x64 (8,146 params, 35 KB). Smaller 32x32 was clearly
  worse in V3 (-25 on V3 TEST) so it is not re-tried. This decision is based on DEV, NOT on V3 TEST.
- Also seen: RL's MEAN queue-C allocation is only ~0.25 session below MPC (3.06 vs 3.31) yet C SLA is 10 pp
  lower → the problem is WHEN sessions are on C, not how many on average (followed up in Exp 2).
- Started Arm B (Lagrangian, no shield) at 23:13 because it does not depend on the shield sweep: dual ascent on
  λ with target C SLA 0.90 per training day (set below MPC's VAL 0.923 because ε-exploration lowers training-time
  SLA; declared before any result), dual_lr 2, λ∈[0,10]. best.pt = best VAL return among VAL-feasible evaluations
  (VAL queue-C SLA ≥ 91.3 = MPC VAL 92.28 − 1).

## TEST4 manifest created (23:26:11 UTC) — NOT evaluated until pre-registration
- `configs/test4_manifest.json`: seeds 1300000 + 1000*family_index + i, 13 families x 50 days = 650 days.
  SHA256 cedc50afa1090457b8a1d6bf9748d06e2b25b1d8261169b2e292864e037545bd.
  evaluate_v4 refuses `--split test4` until configs/preregistration.json exists and lists the policy.

## Exp 2 (running) — VAL trajectories for diagnosis; Exp 3 (running) — runtime shield / hierarchy sweep on DEV
- Exp 3 question: does a classical urgent-capacity shield (Erlang-C floor for queue C, target t ∈ {0.05,0.1,0.2,0.35})
  around the FROZEN V3 DDQN recover queue-C SLA, and at what return cost? Same shield also applied to MPC,
  Forecast and Erlang so the comparison is fair (the shield is not an RL-only advantage). Also: hierarchical
  MPC-envelope + RL allocation (mpcguard), and shield + V3 guarded hybrid.
- Arm B first two seeds finished (≈612 s each). Observation: λ hits the cap 10 in the first ~30k steps (ε≈1
  exploration makes queue C fail, so dual ascent pushes λ up while the policy is still random), then decays to
  ~1–5. Noted as a possible flaw of the schedule; arm B is completed as declared, a warm-up variant may follow.

## Exp 2 — Diagnosis from VAL trajectories (results/diagnosis.json, figures/e1_*.png) (23:28)
Hypotheses: H1 RL under-serves queue C because of reward scale/credit assignment; H2 RL decisions are noisy
(dithering); H3 training/selection noise is as large as the effects; H4 RL relies on time-of-day; H5 RL's win is
only overload behaviour. Data: 48 V3 VAL days, MPC/Forecast/Erlang + 5 seeds DDQN, 5 seeds Dueling DQN, 3 guarded.
- Queue-C failures per day (VAL): MPC 14.3, Erlang 23.8, Forecast 28.7, DDQN 28.9, Dueling DQN 31.2, guarded 29.1.
  But queue-B failures: MPC 21.1 vs DDQN 14.7 → MPC protects C and sacrifices B; RL does the opposite.
  Reward accounting: 14.6 extra C failures × (1/1.947) = −7.5 return/day for RL; MPC's extra C capacity is only
  ~0.25 session on average (3.31 vs 3.06 on DEV) = 0.25 × 96 / 16 = −1.5 return/day. So under the SAME equal-weight
  reward, protecting C is clearly worth it → H1 is NOT "the reward does not value C"; it is a LEARNING / credit-
  assignment failure (the gain from protecting C is delayed, sparse and needs well-timed moves).
- H2 confirmed: DDQN spends 31.7 % of decisions on 'activate' and 28.9 % on 'deactivate' (MPC 11.5/10.5 %,
  Forecast 16/16.6 %) and toggles fallback on/off 5 %/5 % (MPC 0.8/0.2 %). Activate goes to the most-loaded queue
  and deactivate removes from the least-loaded one, so the net learned to use activate+deactivate pairs as an
  indirect "move" (and pays one extra session-step each time: RL runs 17.5–18 sessions vs MPC 17.2). With one action
  per 5 minutes, dithering steps are steps NOT used to move sessions into C (DDQN 6.4 % of decisions move into C,
  MPC 14.3 %).
- H3 confirmed: V3 VAL curves change by 12–15 return units between consecutive evaluations (last 5 evals, mean
  |Δ|), larger than the RL-vs-MPC gaps (2–5). best.pt = max of 10 noisy evaluations: optimistic by 4–6 units
  (best − final). Checkpoint choice is largely noise.
- H5 confirmed (DEV per family, return Δ vs MPC / queue-C Δ pp): DDQN wins only on severe_overload (+62.7 / −32.2)
  and combined_shock (+17.0 / −13.6) and loses on every other family (−1 to −23). By load: rho>1.05 +25.8 / −22.9 pp,
  0.85–1.05 −9.7 / −11.0 pp, rho<0.85 −13.1 / −2.9 pp. The overload "win" is bought with queue C.
- Time-of-day profile: RL keeps more sessions all day and ramps up at the end of the day (end-of-day backlog counts
  as lost); queue-C allocation is flat and ~0.1–0.3 below MPC during hours 1–3, where C backlog is highest.

## Exp 3 (partial) — runtime shield around the frozen V3 DDQN
- shield@0.05: DEV −268.5 (C 98.7 %), shield@0.1: −258.9 (C 98.2 %), vs unshielded −217.5 (C 80.8), MPC −214.3 (91.2).
  HIGH SLA also DROPS (−0.33 pp vs MPC): sessions pulled from A/B/D leave HIGH tickets waiting there.
  Conclusion so far: a tight runtime shield over-protects C (floor 5–6) and destroys return; a network trained
  without the shield fights it. Looser targets (0.2, 0.35, then 0.5/0.7) and static floors (3, 4) are being tested.

## Exp 2b — time-of-day ablation (results/diag_tfrac.json) and Q-value gaps (results/diag_qgap.json) (23:37)
- H4 (relies on clock): replacing the time input obs[28] by 0.5 / shifting ±0.25 h-fraction changes 7–32 % of the
  greedy decisions of DDQN/Dueling-DQN seeds. Return impact is usually small (−0.5 to −4 on VAL) but seed-dependent
  and sometimes large: DDQN s2 t+0.25 −14.3; Dueling DQN s2 t−0.25 −35.6. → partly confirmed: some seeds memorised
  TRAIN demand timing, one reason for fragile generalisation. Not fixed by removing the input: the clock is
  legitimately needed (tickets still waiting at day end count as lost). Recorded as an option, not an arm.
- Q-gaps on 24 VAL days: in 34–65 % of decisions (DDQN s1: 7 %) the best and second-best valid actions differ
  by less than one session-step of reward (0.0625) → the net is close to indifferent most of the time
  (explains dithering + seed spread). When ≥3 queue-C tickets wait (6–10 % of steps; with 6-min service and 5-min
  SLA most will miss), the best move INTO C is valued 0.26–0.67 BELOW the chosen action (median) — the learned value
  of protecting C is wrong in exactly the states where it matters. MPC computes this explicitly with its fluid model.
- Conclusion E1: the RL gap is mainly (1) wrong/indifferent values for well-timed queue-C protection (delayed,
  sparse signal: ~12 % of tickets), (2) dithering activate/deactivate pairs (capacity decisions wasted), (3) noisy
  checkpoint selection; RL's only real advantage is overload allocation. Targeted fixes: Lagrangian penalty on
  C failures (makes the C signal louder, with a pre-declared target), hierarchical capacity owner (removes
  dithering, inherits MPC's envelope), and a classical floor/shield as a hard backstop.

## Exp 3 (complete part) — runtime shield / hierarchy on frozen V3 DDQN (DEV, 104 days) (23:46)
| policy | seeds | DEV return | Δ vs MPC [95% CI] | queue-C SLA | Δ C pp [CI] | HIGH Δ pp |
|---|---|---|---|---|---|---|
| shield@0.05 | 5 | −268.5 | −54.2 [−76.6,−36.9] | 98.7 | +7.5 | −0.34 |
| shield@0.1 | 5 | −256.0 | −41.7 [−60.9,−27.6] | 98.2 | +6.9 | −0.27 |
| shield@0.2 | 5 | −245.6 | −31.3 [−50.2,−17.8] | 97.3 | +6.1 | −0.24 |
| shield@0.35 | 5 | −236.2 | −21.9 [−35.4,−11.1] | 96.2 | +5.0 | −0.16 |
| shield@0.2 + V3 guarded | 3* | −235.5 | −21.2 | 97.0 | +5.7 | −0.33 |
| mpcguard (MPC owns act/deact, V3 DDQN allocates) | 5 | −216.9 | −2.6 [−12.0,+4.4] | 87.1 | −4.2 [−7.4,−1.2] | −0.14 |
(*partial at that time.) Conclusion: an Erlang-C dynamic floor is far too blunt — it over-protects C (floor 4–6,
C SLA 96–99 %) and starves the other queues (lost % up, even HIGH SLA down). A network trained WITHOUT the shield
also keeps proposing what the shield forbids. Runtime shields are rejected as a main approach; only a mild static
floor (floor@3, being tested) remains a candidate backstop. mpcguard removes dithering (cost = MPC's) but RL
allocation still under-serves C (−4.2 pp).

## Exp 4 — Arm B: Lagrangian (dual ascent, target 0.90, no warm-up), 5 seeds, DEV (23:46)
- DEV: return −224.7 (seeds −230.5 −220.1 −219.1 −228.3 −225.5), Δ vs MPC −10.4 [−15.8,−4.4];
  queue-C SLA 90.3 %, Δ −1.0 pp [−2.3,+0.5]; HIGH −0.05 pp; cost 1731/day (MPC 1657), C sessions 3.58 (MPC 3.31).
- Conclusion: the constrained objective WORKS for the constraint (C deficit −10.4 pp → −1.0 pp, i.e. the credit-
  assignment diagnosis was right: a louder C signal makes the net protect C) but it is EXPENSIVE: the net protects C
  by adding sessions (cost +74/day vs MPC) rather than by timing moves. Return −10 vs MPC (and −7 vs plain DDQN).
- Train curves: λ saturates at 10 early (exploration), then oscillates 0.2–8 → nonstationary objective. Arm D
  (warm-up) tests whether that matters.

## Exp 5 (designed 23:44) — confidence-gated hybrid "gate@d:mpc|rl" (no training)
- Question: diagnosis says RL is nearly indifferent in ~40 % of decisions but has a real edge in some states
  (overload). If MPC is the default and RL overrides only when its own Q-value says its action is ≥ d better than
  MPC's action, do we keep MPC's queue-C protection and add RL's overload gains? d ∈ {0.05,0.15,0.3,0.6}, 5 seeds.
  Caveat (declared): Q-values estimate the value of RL's OWN greedy continuation, not of the mixed policy, so the
  gate is a heuristic use of the Q-function, not an exact advantage test.

## Exp 6 — static stronger mask floor@3 (queue C ≥ 3 sessions) and gate (DEV) (23:55)
| policy (frozen V3 DDQN seeds 0-4) | DEV return | Δ vs MPC [CI] | C SLA | Δ C pp [CI] | HIGH Δ | lost % | cost |
|---|---|---|---|---|---|---|---|
| plain (10 seeds) | −217.5 | −3.2 [−8.9,+4.4] | 80.8 | −10.4 [−13.9,−7.4] | −0.06 | 4.38 | 1714 |
| floor@3 | −212.5 | +1.8 [−5.4,+8.3] | 88.1 | −3.2 [−5.2,−1.3] | +0.03 | 4.02 | 1735 |
| shield@0.5 (Erlang floor) | −231.6 | −17.3 [−29.6,−7.6] | 95.3 | +4.1 | −0.12 | 5.16 | 1711 |
| gate@0.05:mpc | −216.9 | −2.6 [−8.6,+3.6] | 81.0 | −10.3 | −0.04 | 4.30 | 1702 |
| gate@0.15:mpc | −213.5 | +0.9 [−4.8,+6.2] | 81.4 | −9.9 [−13.7,−5.7] | −0.04 | 4.17 | 1685 |
| hier:mpc (V3 net NOT trained for it) | −216 to −390 per seed | — | — | — | — | — | — |
- floor@3 is the first variant that improves BOTH return (+5.0 vs plain, same seeds) and queue C (+7.3 pp) with no
  retraining; still −3.2 pp C vs MPC (misses the −1 pp DEV target). Static floors are blunt but predictable:
  the RL keeps its allocation freedom above the floor.
- Gate: even when MPC is the default, the few RL overrides at d ≤ 0.15 already cost ~10 pp of queue C → the RL's
  "confident" overrides are exactly the ones that take sessions from C. Gate rejected.
- hier:mpc with the V3 net is unstable (seed 2 −390, seed 4 −339): a net never trained without activate/deactivate
  behaves badly when they are removed. Expected; arm C trains in that setting.
- Next: floor@4; floor@3 on arm B (Lagrangian) agents, on V3 guarded, on mpcguard; floor@3 for DDQN seeds 5-9;
  arm E = training inside floor@3 (queued after arm C/C0/D).

## Exp 7 — more floor@3 combinations (DEV) (00:08)
| policy | seeds | DEV return | Δ vs MPC [CI] | C SLA | Δ C pp [CI] | HIGH Δ | lost % | cost |
|---|---|---|---|---|---|---|---|---|
| floor@3 + V3 guarded (Forecast owns capacity, V3 DDQN allocates) | 5 | **−208.4** | +5.9 [−3.7,+13.9] | 89.0 | −2.3 [−4.2,−0.5] | −0.01 | 4.39 | **1625** |
| floor@3 + mpcguard (MPC owns capacity) | 5 | −213.5 | +0.8 [−7.7,+7.3] | 91.5 | +0.3 [−1.5,+2.1] | −0.05 | 4.19 | 1688 |
| floor@3 + pure V3 DDQN | 10 | −212.4 | +1.9 [−3.9,+9.3] | 87.8 | −3.5 [−5.5,−1.7] | +0.02 | 4.08 | 1742 |
| floor@3 + MPC (fairness check) | — | −213.7 | +0.6 [−0.7,+1.7] | 93.5 | +2.2 | +0.06 | 4.21 | 1688 |
| floor@3 + Forecast | — | −214.5 | −0.2 | 88.4 | −2.9 | −0.01 | 5.14 | 1627 |
| floor@3 + Erlang | — | −215.7 | −1.3 | 88.3 | −2.9 | +0.05 | 4.92 | 1668 |
| floor@4 + pure V3 DDQN | 5 | −222.3 | −8.0 | 95.3 | +4.1 | +0.01 | 4.51 | 1752 |
| floor@3 + arm B (Lagrangian) | 5 | −223.7 | −9.4 | 93.2 | +1.9 | −0.00 | 4.62 | 1748 |
| gate@0.6:mpc + V3 DDQN | 5 | −208.6 | +5.7 [−0.1,+10.6] | 85.0 | −6.2 | −0.01 | 4.00 | 1667 |
- floor@3 helps the rules too (MPC +0.6, Forecast +1.9) → the floor is a general fix, not an RL trick; the TEST4
  set must contain floor@3+MPC as a comparator.
- floor@4 over-protects. floor@3 + Lagrangian protects C but keeps arm B's cost penalty.

## Exp 8 — Arm C: hierarchical (MPC owner) + Lagrangian with warm-up — FAILED, stopped (00:09)
- DEV: seed 0 −242.5, seed 1 −232.0 (MPC −214.3). VAL during training: λ still oscillates 1.6–8.8 after warm-up.
- Decision: stopped seeds 2–3 at ~55 % (SIGINT; run.json status stays "running" = incomplete, never evaluated),
  dropped seed 4 and arm D (Lagrangian warm-up alone) via configs/skip_runs.txt. Reason: two clearly bad seeds and
  arm B already shows the Lagrangian costs ~10 return; CPU is better spent on the floor-based arms.
- Kept: arm C0 (hierarchical MPC owner, NO Lagrangian), seeds 0–1, to attribute arm C's failure.
- Added arm F: hierarchical training with the Forecast owner INSIDE floor@3 (= the structure of the best DEV
  candidate floor@3 + guarded, but with the RL trained for it). Arm E (pure RL trained inside floor@3) as planned.

## Exp 9 — Arm C0: hierarchical training with the MPC owner, no Lagrangian — FAILED (00:27)
- DEV: seed 0 −262.3, seed 1 −271.5 (MPC −214.3). Seed 0: C SLA 69.5 %, lost 6.8 %, 68 moves/day (MPC 58),
  7.4 fallback switches/day (MPC 0.8). VAL during training still improving at 150k (−470 → −210) and never
  VAL-feasible → learning inside the MPC-owned loop is much slower; 150k steps are not enough.
- Attribution: arm C's failure comes from the hierarchical TRAINING setup (C0 is even worse without the C penalty),
  not from the Lagrangian. The Lagrangian in arm C did raise C SLA (93.5 % for seed 0) as in arm B.
- Contrast: the V3 net trained WITHOUT the owner works well INSIDE the guarded structure (Exp 7). Reason (plausible,
  not proven): a free-capacity agent explores every action and learns general state values; in the owner loop the
  agent only sees the rule's capacity trajectories (less diverse data) and its moves interact with the rule's
  activation logic.
- floor@3 + V3 guarded, seeds 5–9 (DEV): −203.3 −204.7 −209.8 −209.4 −206.4 → consistent with seeds 0–4.

## Exp 10 — Arm E: pure RL trained inside floor@3 (first 2 seeds, DEV) (00:35)
- DEV: seed 0 −218.4, seed 1 −211.9 (mean −215.2) vs the frozen V3 nets wrapped by floor@3 on the same seeds
  −210.9 / −207.5. Retraining inside the floor did NOT help so far.
- Selection-rule side effect (declared rule, kept): no VAL evaluation reached the feasibility threshold
  (VAL C ≥ 91.3; arm E VAL C 82–89), so best.pt = highest VAL C-SLA checkpoint, not the best VAL return
  (seed 1 best VAL return −179.6 at 60k was not kept). Recorded as a limitation; not changed after the fact.
- Decision rule for TEST4 inclusion of retrained arms, written BEFORE arm E seeds 2–4 / arm F results: a retrained
  arm enters TEST4 only if its DEV mean return (all its seeds) is ≥ the DEV mean of the same structure with the
  frozen V3 weights (E vs floor@3|rl V3 seeds 0–4 = −212.5; F vs floor@3|guarded V3 seeds 0–4 = −208.4) AND its
  DEV queue-C SLA is not lower.

## Exp 11 — Arms E and F complete; Lagrangian nets inside the guarded structure (DEV) (01:03)
| policy | seeds | DEV return | Δ vs MPC [CI] | C SLA | Δ C pp [CI] | HIGH Δ | cost |
|---|---|---|---|---|---|---|---|
| floor@3 + V3 guarded | 10 | **−207.6** | **+6.7 [+0.1,+14.2]** | 88.7 | −2.5 [−4.3,−1.0] | −0.02 | 1625 |
| arm E: RL trained inside floor@3 | 5 | −225.2 | −10.9 [−23.9,−0.7] | 88.3 | −2.9 | −0.25 | 1660 |
| arm F: Forecast-owned hierarchy trained inside floor@3 | 3 | −218.1 | −3.8 [−14.2,+4.8] | 84.6 | −6.6 | −0.08 | 1615 |
| floor@3 + guarded with arm-B Lagrangian nets | 5 | −219.6 | −5.3 [−10.7,+0.4] | **93.1** | **+1.8 [+0.9,+2.7]** | −0.04 | 1625 |
| guarded with arm-B Lagrangian nets (no floor) | 5 | −222.0 | −7.7 | 88.6 | −2.7 | −0.11 | 1582 |
- E (−225.2 < −212.5) and F (−218.1 < −208.4, C lower) FAIL the pre-declared inclusion rule → not in TEST4.
  Retraining inside the constraint structure did not beat reusing the V3 nets (3 independent arms now agree:
  C0, E, F). Plausible reason: constrained exploration = less diverse data, and checkpoint selection by the
  feasibility rule.
- The Lagrangian nets in the guarded+floor structure are SAFE on DEV (C +1.8 pp) but cost ~5 return vs MPC:
  added to TEST4 as the "safety-first" candidate (explicitly a trade-off, decided before TEST4).
- NOTE (honest, before TEST4): with the pre-declared 2.0 pp queue-C margin, the best-return candidate
  (floor@3 + V3 guarded) would FAIL on DEV (CI lower bound −4.3 pp). The margin was set on business grounds,
  not to make any candidate pass.

## FREEZE (next step): configs/prereg_candidates.json → python -m v4.e.preregister
Training runs used: 16 complete (B 5, C 2, C0 2, E 5, F 3 — F has 3) + 2 stopped (C s2, s3) = 18 of 25 budget.
- 01:03:21Z pre-registration frozen (configs/preregistration.json/.md, 59 policies in 11 groups, checkpoint SHA256s).
- 01:04 TEST4 evaluation started: `bash v4/e/run_test4.sh` (2 workers, log logs/test4_eval.log).
