# Agent E — targeted RL improvements (V4, exploratory phase on DEV)

All numbers are **SIMULATED** and come from `v4/e/results/eval_dev/*.csv`, analysed with
`python -m v4.e.analyze_v4 dev` (`v4/e/results/dev_analysis.json`).
- **DEV** = 104 new days (13 families × 8, seeds 700000+, SHA256 `d54493d2…`). It is used for refinement and
  selection, so every DEV number below is **exploratory**.
- The confirmatory result is in `AGENT_E_NEW_EVALUATION.md` (new TEST4).
- Full experiment log, including failures: `v4/e/NOTEBOOK.md`.

DEV reference: Fluid MPC k=0.5. Return −214.3, queue-C SLA 91.2 %, HIGH SLA 99.82 %, cost 1657 per day.

## In plain words
We tried five ways to make the learned controller protect urgent customers without losing its strengths.

What worked best:
- A simple rule, "the urgent queue always keeps at least 3 sessions".
- Splitting the job: a classical rule decides **how many** sessions are open, and the learned network decides
  **where** they go.

What did not work:
- A cleverer safety filter based on queueing formulas over-protected the urgent queue and hurt everyone else.
- A training penalty for urgent failures did fix the urgent queue, but it made the network expensive.
- Letting MPC decide capacity during training made training unstable.

All the winning changes are low-complexity, and the network stays the decision maker for allocation and fallback.

## E2 — feasibility comparison of the five options

| Option | What it is | Complexity | Guarantees | Risk | DEV evidence (frozen V3 DDQN unless noted) | Verdict |
|---|---|---|---|---|---|---|
| 1. Stronger mask (static floor) | Queue C never below k sessions (V3 mask: k=2) | Very low (1 line in the mask) | Allocation floor only | Over-staffing if k is too high | floor@3: return −212.4 (+1.9 vs MPC), C 87.8 % (−3.5 pp); floor@4: −222.3, C 95.3 % | **Implemented, adopted (k=3)** |
| 2. Minimum urgent capacity / overload rule (dynamic) | Erlang-C floor for C from forecast + backlog (UrgentShield) | Low | Allocation floor only | Floor jumps to 4–6 on spikes and starves other queues | target 0.05…0.5: return −268.5 … −231.6, C 98.7 … 95.3 %, HIGH SLA down to −0.34 pp | Implemented, **rejected** (too blunt) |
| 3. Veto shield from a classical controller | MPC default; RL only overrides when its Q-advantage ≥ d ("gate") | Low | None (heuristic use of Q) | RL's confident overrides are exactly the C-starving ones | gate d=0.15: −213.5, C 81.4 %; d=0.6: −208.6, C 85.0 % | Implemented, **rejected** (C not protected) |
| 4. Hierarchical: classical rule sets the capacity envelope, RL allocates | Forecast or MPC owns activate/deactivate | Low | Inherits the rule's capacity level; removes RL dithering | RL net must match the structure | V3 guarded + floor@3: **−208.4 (+5.9 [−3.7,+13.9])**, C 89.0 % (−2.3 pp), cost 1625; MPC envelope + floor@3: −213.5, C 91.5 % (+0.3 pp) | **Implemented, adopted** (+ retrained variant, arm F) |
| 5. Explicit constrained objective (Lagrangian) | Train with −λ·(C failures)/F_ref, λ by dual ascent to a pre-declared C SLA target (0.90) | Medium (training change) | Constraint in expectation, during training only | Non-stationary λ; expensive solutions | Arm B (5 seeds): −224.7 (−10.4 [−15.8,−4.4]), C 90.3 % (−1.0 [−2.3,+0.5]), cost 1731 | Implemented; **meets the C target but costs return** |

**Important limit.** Masks, floors and shields enforce **allocation** constraints only. They **cannot guarantee
future SLA**:
- arrivals are random;
- one queue-C service (6 min) is longer than the queue-C SLA (5 min), and a HIGH ticket's SLA is 3 min;
- a session moved now cannot serve a ticket that is already late.

A floor makes "C has at least 3 sessions" true at every step. It does not make "C SLA ≥ 91 %" true.

## E3 — base tiny RL candidate (chosen on DEV, not on V3 TEST)

| Algorithm (V3 checkpoints, 64×64) | Seeds | V3 VAL best (selection set) | DEV return (fresh days) | DEV seed SD | Params | Checkpoint |
|---|---|---|---|---|---|---|
| Dueling DQN | 5 | −184.0 | −222.8 | 7.5 | 8,146 | 35 KB |
| **Dueling Double DQN** | 5 (seeds 0–4) / 10 | −185.4 / −186.7 | **−217.9** / −217.5 | **2.7** / — | 8,146 | 35 KB |
| DQN | 10 | −185.5 | −220.8 | — | 8,081 | 35 KB |
| Double DQN | 5 | −185.5 | −232.7 | — | 8,081 | 35 KB |

- The Dueling DQN VAL advantage is the maximum of 10 noisy evaluations on the same days used to choose best.pt. It
  does not survive fresh days.
- **Choice: Dueling Double DQN 64×64.** 8,146 parameters, 35 KB, ~0.3 ms per decision.
- 32×32 was clearly worse in V3. 128×128 (24k params) was only a DEV tie (−214.9, C 84.8 %), with no safety gain,
  so we keep the smaller net.

## E4 — targeted experiments (each answers one diagnosis question)

| # | Question (from the diagnosis) | Experiment | Seeds | DEV return | Δ vs MPC [95% CI] | C SLA % | Δ C pp [95% CI] | HIGH Δ pp | Cost | Conclusion |
|---|---|---|---|---|---|---|---|---|---|---|
| — | baseline | V3 Dueling DDQN | 10 | −217.5 | −3.2 [−8.9,+4.4] | 80.8 | −10.4 [−13.9,−7.4] | −0.06 | 1714 | — |
| — | baseline | V3 guarded (Forecast capacity + DDQN) | 10 | −210.4 | — | 81.9 | — | — | 1580 | — |
| B | Does a louder C signal fix credit assignment? | Lagrangian, dual target 0.90 | 5 | −224.7 | −10.4 [−15.8,−4.4] | 90.3 | −1.0 [−2.3,+0.5] | −0.05 | 1731 | Yes for C, but expensive |
| C | Does a fixed capacity owner + C penalty help? | MPC owns capacity in training + Lagrangian with warm-up | 2 (stopped) | −237.2 | — | — | — | — | — | **Failed**: −242.5, −232.0 |
| 6 | Is a static floor enough? | floor@3 around V3 DDQN | 10 | −212.4 | +1.9 [−3.9,+9.3] | 87.8 | −3.5 [−5.5,−1.7] | +0.02 | 1742 | Better on both, no retraining |
| 7 | Floor + capacity owner? | floor@3 around V3 guarded | 5 | **−208.4** | +5.9 [−3.7,+13.9] | 89.0 | −2.3 [−4.2,−0.5] | −0.01 | **1625** | Best return, cheapest |
| 7 | Floor + MPC envelope? | floor@3 around mpcguard | 5 | −213.5 | +0.8 [−7.7,+7.3] | 91.5 | +0.3 [−1.5,+2.1] | −0.05 | 1688 | Meets C, return tie |
| 7 | Fairness: does the floor help rules too? | floor@3 around MPC / Forecast / Erlang | — | −213.7 / −214.5 / −215.7 | +0.6 / −0.2 / −1.3 | 93.5 / 88.4 / 88.3 | +2.2 / −2.9 / −2.9 | — | 1688 / 1627 / 1668 | Yes, a little |

| C0 | Is arm C's failure due to the hierarchy or to the penalty? | MPC owns capacity in training, no penalty | 2 | −266.9 | — | 69.5 (s0) | — | — | 1657 (s0) | **Failed**: −262.3, −271.5. The hierarchical training is the problem |
| E | Does a net trained inside floor@3 allocate better? | Pure RL trained with the floor in the loop | 5 | −225.2 | −10.9 [−23.9,−0.7] | 88.3 | −2.9 | −0.25 | 1660 | **No**: worse than the V3 net + floor@3 (−212.5) |
| F | Does a net trained for the guarded structure help? | Forecast owns capacity in training, floor@3 | 3 | −218.1 | −3.8 [−14.2,+4.8] | 84.6 | −6.6 | −0.08 | 1615 | **No**: worse than V3 guarded + floor@3 (−208.4) |
| 11 | Lagrangian nets inside the guarded structure? | floor@3 around guarded with the arm B nets | 5 | −219.6 | −5.3 [−10.7,+0.4] | **93.1** | **+1.8 [+0.9,+2.7]** | −0.04 | 1625 | Safe, costs ~5 return: the "safety-first" candidate |
| 7 | (10 seeds) | floor@3 around V3 guarded, all 10 seeds | 10 | **−207.6** | **+6.7 [+0.1,+14.2]** | 88.7 | −2.5 [−4.3,−1.0] | −0.02 | 1625 | Best DEV return; C deficit of 2.5 pp |

### What the experiments teach
1. **The diagnosis was right about queue C.** Making the queue-C failures explicit, with the Lagrangian (arm B), moves
   the C deficit from −10.4 pp to −1.0 pp. Simply refusing to go below 3 sessions on C (floor@3) moves it to −3.5 pp.
2. **The network's weakness is capacity dithering, not allocation.** When a rule owns activate/deactivate (guarded
   structure), the same V3 network becomes the best policy on DEV, and the cheapest.
3. **Retraining inside the constraint structure did not help** in 3 independent arms (C0, E, F) at a 150k-step
   budget. Plausible reasons, not proven:
   - the rule-driven or floor-limited trajectories give less diverse data;
   - the feasibility-first checkpoint rule kept checkpoints with high C SLA but lower return (arm E).
   So the final candidates reuse the V3 checkpoints (genuine trained RL policies, SHA256 recorded) inside the new
   structure.
4. **Dynamic shields and the gate are the wrong tools here.**
   - The dynamic shield is too blunt: it over-protects queue C and starves the other queues.
   - The gate lets RL override MPC only when the RL's own Q-values say it is better. Those overrides are exactly the
     moves that hurt queue C.

### Compute used (E4)
- **Runs:** 18 training runs of 25 budgeted:
  - completed: B 5, C 2, C0 2, E 5, F 3;
  - stopped early: 2 (arm C seeds 2 and 3, not evaluated).
- **Time per run:** ~530–700 s alone or in pairs (150k steps); MPC-owned runs ~1000 s.
- **DEV evaluation:** about 190 policy-runs of 104 days (`v4/e/results/eval_dev/`).

## What happened on the new TEST4 (confirmatory; details in AGENT_E_NEW_EVALUATION.md)

| Candidate (TEST4, 650 days) | Δ return vs MPC [95% CI] | Δ queue-C SLA (pp) | Δ HIGH SLA (pp) | Pre-registered safety |
|---|---|---|---|---|
| floor@3 + guarded (V3 DDQN) | **+6.89 [+2.99, +10.48]**, Holm p = 0.006 | −2.74 | −0.12 | fails (C, HIGH) |
| floor@3 + guarded (Lagrangian DDQN), **recommended** | −4.57 [−8.74, −0.29] | **+1.79** | −0.05 | **passes** |
| floor@3 + MPC envelope | +0.18 [−5.69, +5.56] | +0.23 | −0.12 | fails (HIGH) |
| floor@3 + pure DDQN | +1.62 [−2.42, +5.49] | −3.67 | −0.05 | fails (C) |
| Lagrangian DDQN (pure) | −10.28 [−15.33, −5.40] | −1.04 | −0.07 | passes |

The DEV ranking held on TEST4. The improvements are real, but they are a trade-off:
- the most rewarding design is not safe enough by our own pre-declared margins;
- the safe design costs return.

## NOT VERIFIED / limits
- DEV has 104 days; the CIs are wide.
- DEV is also used to choose the floor (k=3), so DEV differences are optimistic.
- Only TEST4 is confirmatory.
