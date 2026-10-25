# Agent E — why the V3 RL policy is not reliably better than MPC (failure analysis, V4)

All numbers are **SIMULATED** (frozen V3 tape simulator). Sources: `v4/e/results/diagnosis.json`,
`diag_tfrac.json`, `diag_qgap.json`, `eval_dev/*.csv`, `eval_val/*.trace.jsonl`; figures in `v4/e/figures/e1_*.png`.
Code: `v4/e/diagnose_v4.py`, `v4/e/evaluate_v4.py`. Lab notebook: `v4/e/NOTEBOOK.md` (Exp 1–3).

**Which data was used.**
- Diagnosis rollouts: the V3 **VAL** days (48 days, 8 training families) and the **new DEV** set
  (`v4/e/configs/dev_manifest.json`, 104 days, 13 families, seeds 700000+, SHA256 `d54493d2…`).
- The V3 TEST rows were **not** used for any choice. One table in §7 reads them *descriptively only* and is labelled.
- Policies diagnosed: Fluid MPC k=0.5 (reference), Forecast z=0.25, Erlang-C 0.4, frozen V3 checkpoints
  (Dueling DDQN 10 seeds, Dueling DQN 5, DQN 10, Double DQN 5, guarded hybrid 10).

## In plain words
The learned policy is not worse because the network is too small or because the reward ignores urgent customers.
Under the very same reward, protecting the urgent queue C is clearly worth it, and MPC does it. The network did not
learn it: its value estimates say that moving a session into C is a *bad* idea exactly when urgent tickets pile up.
It also wastes many decisions switching sessions on and off, and its training curve jumps around so much that
picking the "best" checkpoint is mostly luck. Its one real strength — handling extreme overload — is paid for with
urgent customers.

## 1. The result replicates on fresh DEV days (not used for any choice before)

| Policy (DEV, 104 days) | Seeds | Return | Queue-C SLA % | HIGH SLA % | Lost % | Cost/day | Sessions on C (mean) | Active sessions (mean) |
|---|---|---|---|---|---|---|---|---|
| Fluid MPC k=0.5 | — | **−214.3** | **91.2** | **99.82** | 4.36 | 1657 | 3.31 | 17.3 |
| Erlang-C 0.4 | — | −216.1 | 85.9 | 99.79 | 5.07 | 1636 | 3.08 | 17.0 |
| Forecast z=0.25 | — | −216.4 | 82.7 | 99.70 | 5.36 | 1580 | 2.90 | 16.5 |
| Dueling DDQN (V3) | 10 | −217.5 | 80.8 | 99.76 | 4.38 | 1714 | 3.06 | 17.9 |
| DQN (V3) | 10 | −220.8 | 80.9 | 99.75 | 4.49 | 1701 | 3.04 | 17.7 |
| Dueling DQN (V3) | 5 | −222.8 | 79.7 | 99.58 | 4.44 | 1727 | 2.93 | 18.0 |
| Double DQN (V3) | 5 | −232.7 | 79.1 | 99.66 | 5.16 | 1676 | 2.95 | 17.5 |
| Guarded hybrid Forecast + DDQN (V3) | 10 | −210.4 | 81.9 | 99.71 | 4.71 | 1580 | 2.93 | 16.5 |

- Dueling DDQN − MPC on DEV: return −3.2 [−8.9, +4.4] (tie), queue-C SLA **−10.4 pp [−13.9, −7.4]**.
  This is the same picture as the V3 TEST.

## 2. Reward scale and credit assignment: the reward *does* value queue C, the network did not learn it

Queue C has ~12 % of the tickets, a 5-minute SLA (HIGH tickets: 3 minutes) and a 6-minute service time.

| Failed tickets per day (VAL, 48 days) | Queue A | Queue B | **Queue C** | Queue D |
|---|---|---|---|---|
| Fluid MPC k=0.5 | 26.1 | 21.1 | **14.3** | 26.7 |
| Erlang-C 0.4 | 26.9 | 14.0 | 23.8 | 19.9 |
| Forecast z=0.25 | 29.0 | 13.5 | 28.7 | 20.3 |
| Dueling DDQN (5 seeds) | 27.6 | 14.7 | **28.9** | 21.3 |
| Dueling DQN (5 seeds) | 25.3 | 13.1 | 31.2 | 21.1 |

Marginal reward arithmetic (equal-weight reward, one failure = 1/1.947 = 0.51, one session-step = 1/16 = 0.0625):
- RL has 14.6 more queue-C failures per day than MPC: about **−7.5 return/day**.
- MPC's extra queue-C capacity is only ~0.25 session on average: 0.25 × 96 / 16 = **−1.5 return/day**.
- MPC pays for it partly in queue B (+6.4 failures ≈ −3.3/day). Net, the MPC trade is better.

So the reward is not blind to queue C. The failure is a **learning / credit-assignment** failure: the benefit of a
well-timed move into C arrives later, is sparse (a few tickets) and is noisy.

**The Q-values confirm it** (`diag_qgap.json`, 24 VAL days, 3 seeds each of DDQN and Dueling DQN):
- In 34–65 % of decisions (one seed: 7 %) the best and second-best valid actions differ by less than one
  session-step of reward. The network is close to **indifferent** most of the time.
- When 3 or more queue-C tickets are waiting (6–10 % of steps; most of them will miss their SLA), the best move
  **into** C is valued **0.26–0.67 below** the action the network picks (median). The values are wrong exactly where
  urgent customers are at stake.

## 3. Action distribution: dithering with activate/deactivate (figure `e1_action_distribution.png`)

| Share of decisions (VAL) | keep | move into C | move out of C | other moves | activate | deactivate | fallback on | fallback off |
|---|---|---|---|---|---|---|---|---|
| Fluid MPC | 16.3 | 14.3 | 12.6 | 33.8 | 11.5 | 10.5 | 0.8 | 0.2 |
| Forecast | 31.9 | 8.0 | 5.4 | 21.4 | 16.0 | 16.6 | 0.3 | 0.3 |
| Dueling DDQN | 9.1 | 6.4 | 2.5 | 11.5 | **31.7** | **28.9** | 5.0 | 4.9 |
| Dueling DQN | 9.3 | 3.6 | 4.0 | 19.8 | 28.7 | 25.6 | 4.6 | 4.5 |

- 60 % of RL decisions are activate or deactivate. Activate goes to the most-loaded queue and deactivate removes a
  session from the least-loaded one, so the net learned to use pairs of them as an indirect "move". Each pair costs
  an extra session-step, and RL runs more sessions (17.9 vs 17.3 for MPC on DEV, cost 1714 vs 1657).
- With one decision every 5 minutes, those steps are not used for direct moves into C (6.4 % vs 14.3 % for MPC).
- RL toggles fallback on/off about 10 % of the time (MPC 1 %).

## 4. Queue-C allocation and backlog over the day (figure `e1_time_of_day_profiles.png`)
- Sessions on C are almost flat over the day for every policy. RL is 0.1–0.3 session below MPC during hours 1–3,
  when the C backlog is highest (RL ~0.8 waiting vs MPC ~0.5).
- RL keeps more sessions active all day and ramps up near the end of the day (tickets still waiting at the end count
  as lost). Forecast and the guarded hybrid run the fewest sessions.

## 5. Overload behaviour and generalisation (figure `e1_dev_family_diff.png`, DEV)

| Dueling DDQN − MPC (DEV) | Return Δ / day | Queue-C SLA Δ (pp) |
|---|---|---|
| severe_overload (held-out family) | **+62.7** | **−32.2** |
| combined_shock (held-out) | +17.0 | −13.6 |
| other 11 families | −1.3 to −22.8 | −3.1 to −24.6 |
| offered load rho > 1.05 | +25.8 | −22.9 |
| rho 0.85–1.05 | −9.7 | −11.0 |
| rho < 0.85 | −13.1 | −2.9 |

- RL's only clear win is extreme overload, and it is bought with urgent customers.
- In normal and light load, RL is worse than MPC on return as well.

## 6. Time-of-day dependence (`diag_tfrac.json`, VAL)
- Replacing the clock input (obs[28]) by a constant or shifting it by ±25 % of the day changes **7–32 % of the
  greedy decisions**.
- The usual return change is small (−0.5 to −4), but some seeds break: DDQN seed 2 with t+0.25 loses 14.3;
  Dueling DQN seed 2 with t−0.25 loses 35.6.
- So some seeds memorised the timing of the training demand shapes. That is one reason for fragile behaviour on new
  shapes. The clock cannot simply be removed, because the end of the day really matters (waiting = lost).

## 7. Training stability and checkpoint selection (figure `e1_training_stability.png`, V3 run logs)

| V3 run group (VAL curve, 10 evaluations each) | Seeds | Best VAL (mean) | Final VAL (mean) | Best − final | Mean change between consecutive evals (last 5) |
|---|---|---|---|---|---|
| Dueling DDQN | 10 | −186.7 | −192.2 | 5.6 | 14.8 |
| Dueling DQN | 5 | −184.0 | −189.9 | 5.9 | 12.7 |
| DQN | 10 | −185.5 | −189.5 | 4.0 | 15.4 |
| Double DQN | 5 | −185.5 | −188.3 | 2.7 | 12.7 |

- The VAL return jumps by 12–15 between consecutive evaluations, more than the RL-vs-MPC differences (2–5).
- best.pt = the maximum of 10 noisy evaluations on the same 48 days: an optimistic estimate (about 4–6 too high).
- This is why "Dueling DQN has the best VAL mean" (−184.0) did **not** hold on fresh DEV days: there Dueling DQN
  is −222.8 (seed SD 7.5) vs Dueling DDQN −217.9 (seed SD 2.7) on matched seeds 0–4 (§ E3 in the improvements file).

Descriptive only (V3 TEST rows, read-only, no choice made from them): MPC queue-C SLA 91.0 %; V3 guarded seed 0
78.8 %; V3 DDQN seed 0 79.8 %. Same direction as DEV.

## 8. Fallback use
- Fallback is used ~9–10 % of the day by RL (DEV fallback share 0.094) vs 15 % by MPC and 4 % by Forecast/Erlang.
- No policy ever put a HIGH ticket on fallback (simulator rule) and no policy exceeded the 25 % cap.
- Fallback is not where RL loses.

## 9. Summary of causes (ranked by evidence)
1. **Wrong values for urgent protection** (credit assignment): queue C failures 2× MPC; Q-values penalise moving
   into C when C is in trouble. The reward is not the main problem (§2 arithmetic).
2. **Dithering**: 60 % of decisions are activate/deactivate; extra cost and fewer useful moves.
3. **Noisy training and checkpoint selection**: eval-to-eval swings (~15) larger than the effects (~3).
4. **Clock memorisation** in some seeds: fragile under new demand timing.
5. Its genuine strength (overload allocation) trades away queue C.

**What this implies.**
- A mask can enforce allocation limits (for example "C never below k sessions") but **cannot guarantee future SLA**:
  arrivals are random, a HIGH queue-C ticket's SLA (3 min) is shorter than one service (6 min), and a
  session moved now only helps tickets that arrive later.
- Targeted fixes tested in `AGENT_E_RL_IMPROVEMENTS.md`:
  - make the queue-C signal explicit with a constrained (Lagrangian) objective;
  - remove dithering by letting a classical controller own the capacity level (hierarchy);
  - test classical floors/shields as backstops.

## NOT VERIFIED / limits
- Everything is simulated. The causes are shown for this simulator and these reward weights only.
- Q-gap and time-ablation analyses use 3 seeds per algorithm and VAL days, which were also used to pick best.pt.
- The marginal-value arithmetic uses average effects; it is not a causal decomposition per ticket.
