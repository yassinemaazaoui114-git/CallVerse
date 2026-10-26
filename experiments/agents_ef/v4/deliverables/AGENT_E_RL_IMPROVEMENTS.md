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

(Arms C0, E and F are added below when finished.)

## NOT VERIFIED / limits
- DEV has 104 days; the CIs are wide.
- DEV is also used to choose the floor (k=3), so DEV differences are optimistic.
- Only TEST4 is confirmatory.
