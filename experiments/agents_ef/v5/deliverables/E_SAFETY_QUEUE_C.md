# E2 — Safety shield and queue C (Agent E v5)

**Questions.** (1) How often does a shield actually change what the controller does (intervention), and how often
is the controller's action replaced by a non-RL default (replacement)? (2) Does the same shield help non-RL
baselines (is it an RL-specific trick)? (3) With vs without the shield, what happens to return, queue-C SLA, HIGH SLA,
lost tickets and the lower tail? (4) Does a shielded RL controller stay RL, or does it become MPC in disguise?
Hard constraints and estimated risk are reported separately.

Data: DEV, 104 days, frozen V3 checkpoints, v5 evaluator with decision provenance and MPC agreement
(`python -m v5.e.evaluate_v5 --split dev --agree-mpc …`, `python -m v5.e.shield_analysis` → `v5/e/results/e2_shield.json`).
The 17-action semantics are unchanged: shields only shrink the valid-action mask.

## Definitions (per decision step; 96 steps per day)

- **Removal rate**: the shield removed at least one otherwise-valid action (shield "active").
- **Intervention rate**: the EXECUTED action differs from what the same controller would execute without the shield in
  the same state (counterfactual call; all inner controllers are deterministic and stateless).
- **Replacement rate**: a non-RL default action (move into C / keep) replaced the controller's action. This only
  happens for rules that propose a removed action; an RL agent always re-chooses its best action inside the mask.
- **RL own**: executed action = the RL's greedy choice over the FULL valid mask. **RL re-choice**: the RL chose inside
  the shielded mask because its first choice was removed. **Owner**: decided by the guarded hybrid's classical
  owner rule (Forecast z = 0.25 decides activate/deactivate and replaces every RL activate/deactivate).
- **MPC agreement**: executed action = Fluid MPC's action in the same state (MPC itself = 100 %).

## Results (DEV; shield effect = shielded − unshielded, same seeds and days, paired 95 % CI)

| Controller + shield | seeds | removal % | intervention % | replacement % | RL own % | RL re-choice % | owner % | MPC agree % (no shield) | return (no shield → shield) | Δ return | queue-C SLA % | Δ HIGH pp | Δ lost pp | Δ CVaR10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pure Dueling DQN + floor@3 | 5 | 74.4 | 20.3 | 0.0 | 79.7 | 20.3 | 0 | 24.4 (23.7) | −222.8 → −217.1 | +5.72 [−5.51, +18.19] | 79.7 → 87.4 | +0.087 [−0.263, +0.481] | −0.29 [−0.78, +0.20] | +6.6 [−87.5, +113.8] |
| pure Dueling DDQN + floor@3 | 10 | 68.7 | 15.1 | 0.0 | 84.9 | 15.1 | 0 | 24.1 (24.9) | −217.5 → −212.4 | **+5.10 [+0.56, +9.33]** | 80.8 → 87.8 | +0.083 [+0.033, +0.144] | −0.30 [−0.58, −0.03] | +8.4 [−23.3, +38.1] |
| pure Dueling DDQN + shield@0.2 (Erlang) | 5 | 54.3 | 27.2 | 0.0 | 72.8 | 27.2 | 0 | 18.3 (25.5) | −217.9 → −245.6 | −27.70 [−47.85, −14.70] | 80.6 → 97.3 | −0.177 [−0.504, +0.025] | +1.33 [+0.62, +2.27] | −138.7 [−272.5, −57.7] |
| V3 guarded (DDQN) + floor@3 | 10 | 73.4 | 26.0 | 0.0 | 29.5 | 8.7 | 61.8 | 21.1 (23.3) | −210.4 → −207.6 | +2.80 [−2.51, +7.21] | 81.9 → 88.7 | +0.091 [+0.029, +0.155] | −0.26 [−0.42, −0.07] | +0.3 [−41.1, +36.0] |
| V3 guarded (DDQN) + shield@0.2 | 5 | 60.4 | 38.3 | 1.2 | 23.9 | 24.8 | 50.2 | 17.9 (23.6) | −210.9 → −240.3 | −29.33 [−45.70, −17.82] | 81.7 → 97.0 | −0.198 [−0.566, +0.019] | +1.47 [+0.98, +2.20] | −135.1 [−239.4, −59.2] |
| MPC k = 0.5 + floor@3 | — | 61.1 | 15.0 | 0.0 | — | — | — | 85.0 (100) | −214.3 → −213.7 | +0.58 [−0.79, +1.70] | 91.2 → 93.5 | +0.057 [+0.018, +0.103] | −0.14 [−0.21, −0.07] | +1.3 [−5.4, +2.8] |
| MPC k = 0.5 + shield@0.2 | — | 72.1 | 40.1 | 0.0 | — | — | — | 59.9 (100) | −214.3 → −232.1 | −17.77 [−22.95, −13.09] | 91.2 → 96.5 | +0.056 [+0.011, +0.106] | +0.84 [+0.63, +1.08] | −55.2 [−70.2, −43.0] |
| Forecast z = 0.25 + floor@3 | — | 78.8 | 24.2 | 0.0 | — | — | — | 17.4 (19.8) | −216.4 → −214.5 | +1.90 [+0.24, +3.33] | 82.7 → 88.4 | +0.113 [+0.014, +0.212] | −0.22 [−0.32, −0.11] | +5.0 [−1.3, +13.8] |
| Forecast z = 0.25 + shield@0.2 | — | 69.6 | 47.7 | 18.1 | — | — | — | 14.8 (19.8) | −216.4 → −240.7 | −24.30 [−30.21, −18.93] | 82.7 → 96.6 | +0.049 [−0.047, +0.133] | +1.22 [+0.98, +1.50] | −94.1 [−113.7, −66.0] |

(Rules re-choose inside the mask too; their interventions are "rule re-choices", replacement is only counted when the
rule's own proposal was invalid under the shielded mask.)

## Findings

1. **The static floor (queue C ≥ 3) intervenes rarely relative to how often it is active.** It removes an action on
   69–79 % of steps (because moving out of C at C = 3 is almost always a valid option it forbids), but the executed
   action changes on only 15 % (DDQN), 20 % (Dueling DQN), 15 % (MPC) of steps. It never substitutes a non-RL
   default for an RL agent (replacement 0 %).
2. **A floor-shielded pure RL stays RL — not MPC in disguise.** 84.9 % (DDQN) / 79.7 % (Dueling DQN) of decisions are
   the network's own unconstrained choice; the rest are its own re-choice inside the mask. Agreement with MPC is
   24 % with and without the floor (MPC + floor agrees with plain MPC 85 %). The shield moves queue C, not the
   controller's identity.
3. **The V3 guarded hybrid is mostly a rule.** In `floor@3 + guarded` the RL decides only 38 % of steps (29.5 % own +
   8.7 % re-choice); the Forecast owner decides 61.8 % (capacity changes + replacing every RL activate/deactivate,
   which the unconstrained RL proposes on ~50 % of steps). This is a property of the guarded structure (also 60 %+
   without the floor), and must be stated whenever the guarded hybrid is called "RL". It is still not MPC (21 %
   agreement).
   V4 reported 0 shield vetoes for guarded controllers because it only counted vetoes for pure `rl:` inners; the real
   intervention rate of floor@3 + guarded is 26.0 % over 10 seeds (30.7 % for seed 0).
4. **The floor helps every controller, RL and non-RL**: queue C +2.2 (MPC) / +5.7 (Forecast) / +6.8–7.6 pp (RL),
   HIGH SLA slightly up, lost slightly down, return up (+0.6 MPC, +1.9 Forecast, +2.8 to +5.7 RL). It is a general
   operational rule, not an RL advantage — so every RL vs MPC comparison must also include floor@3 + MPC.
5. **The Erlang-C shield (shield@0.2) is an estimated-risk tool and over-protects**: it changes 27–48 % of actions,
   lifts queue C to 96–97 % but costs −18 (MPC) to −29 (guarded) return, raises lost tickets by 0.8–1.5 pp and
   destroys the lower tail (CVaR10 −55 to −139). Rejected again (V4 reached the same conclusion with fewer checks).

## Hard constraints vs estimated risk (kept separate)

| Kind | What | How it is enforced | DEV result |
|---|---|---|---|
| HARD (exact) | budget never exceeded; capacity; ≥ 6 active sessions; queue C ≥ 2 (V3 mask) | simulator mask (invalid proposals become keep and are counted) | 0 invalid proposals executed, 0 budget-overrun days (all controllers above) |
| HARD (exact) | fallback ≤ 25 % of the day; never for HIGH tickets | mask + service rule | 0 HIGH tickets on fallback |
| HARD design rule | queue C ≥ 3 sessions (floor@3) | stronger mask (UrgentShield static=3) | holds by construction (the controller can never choose an action leaving C < 3; only exogenous failures could, and they remove C last) |
| ESTIMATED risk | P(queue-C wait > SLA) ≤ target (shield@t) | Erlang-C M/M/k estimate on forecast + backlog | not a guarantee; over-protects on DEV |
| OUTCOMES (statistical) | queue-C SLA %, HIGH SLA %, lost % | measured, never guaranteed by any mask | reported with CIs; the TEST5 safety rule uses margins on these (E_TEST5_RESULTS.md) |

A mask constrains ALLOCATION only. With 6-minute service and a 5-minute queue-C SLA (3 minutes for HIGH), no
allocation rule can guarantee future SLA; that is why queue-C / HIGH outcomes are tested with margins, not claimed.

## TEST5 safety outcome
See E_TEST5_RESULTS.md (pre-registered acceptance rule: queue-C non-inferiority −2.0 pp, HIGH −0.2 pp, 0 hard violations).
