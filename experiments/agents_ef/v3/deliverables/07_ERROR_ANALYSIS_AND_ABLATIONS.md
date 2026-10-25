# 07 — Error analysis and ablations

## Agent E

### Where the learned policies lose

**1. Queue C (5-minute urgent SLA)**
- SLA on queue C: about 80% for every RL policy, against 91.0% for MPC (guarded DDQN: −9.5 pp [−11.6, −7.8]).
- Cause: the objective counts every SLA failure the same, and queue C is a small share of tickets. RL learns that staffing queue C tightly is cheap in return terms.
- This is a **specification issue, not a learning failure**. If queue C matters more to the business, its weight must be in the reward (or in a hard constraint), and the rules must be re-tuned under the same weight.
- HIGH-priority tickets are protected by design: HIGH SLA ≥ 99.0% for every RL policy, and 0 HIGH tickets on fallback.

**2. In-distribution peak shapes**
- Pure DDQN is worse than MPC on morning_peak (−249.5 vs −227.5) and volatile days.
- Likely cause (not tested separately): MPC's 6-step fluid lookahead anticipates peaks that a reactive policy only sees once the queue has grown.

**3. Seed variance**
- The SD of per-seed TEST return is 6.4–6.8 for DDQN.
- Double DQN has one poor seed: seed 0 loses 8.9% of customers, against 4.6–5.1% for seeds 1–4. That gives the group a wide CI ([−56, −1] vs MPC).
- 3-seed ablations are therefore indicative only.

### Where the learned policies win

**Severe overload** (ρ = 1.3, beyond budget; a held-out family)
- MPC, Forecast and the guarded hybrid all spend the full budget there (1,766/day; checked for these three).
- The guarded hybrid loses 9.2% of customers, against 13.4% for MPC and 11.3% for Forecast.
- Its learned allocation across queues degrades more gracefully than the rule-based allocation when capacity cannot cover demand.

**Cost**
- The guarded hybrid uses about 4% fewer session-steps than MPC, for +0.27 pp lost customers.

### Ablations (details and numbers: `04_AGENT_E_RESULTS.md` §3)

| Question | Answer |
|---|---|
| Does size matter? | 32×32 is too small (−25 vs MPC). 64×64 and 128×128 are ties with MPC |
| Does more training help? | 400k steps moves DDQN from −3.7 to +0.1 vs MPC (still a tie), and PPO from −30.6 to −22.8 (still worse) |
| Which algorithm? | DQN-family value methods ≫ PPO ≫ Tabular Q at a matched 150k budget. Dueling + double is the best and most stable |
| Does guarding help? | Yes: Forecast owning activate / deactivate plus RL owning allocation gives +7.7 vs pure DDQN, mostly through 7% lower cost |
| Do retrained reward weights work? | No: each preset-trained policy is worse under its own preset than the equal-weight policy |
| Does a synthetic satisfaction term help? | No measurable effect (+2.0 to +2.3, CIs include 0, 3 seeds) |

## Agent F

Details: `v3/f/ERROR_ANALYSIS.md`.

**Regression to the mean**
- Dialogues rated 1–2 are over-predicted by about 1.2.
- Predictions are compressed toward 3, so QWK on EN is about 0 for every model.

**Polite but unsatisfied dialogues**
- MAE 0.60, against 0.29 for other polite dialogues.
- Polite wording hides the dissatisfaction from a text model.

**Context length**
- JDDC dialogues are long. 256 tokens beats 128, and TF-IDF on the last 128 tokens is worse than on the full text (0.511 vs 0.493 on ZH).

**Collapse**
- mMiniLMv2-L6 collapsed to a constant on ZH.

**Domain transfer to ShopNova**
- Scores are almost flat on single-turn ShopNova conversations: SD 0.07 (TinyBERT) and 0.04 (e5-L6/256), as measured by M7.
- Failed and ok conversations get the same score.

**Quantization**
- int8 shifts USS predictions by about +0.1. One offset fitted on VAL repairs most of it.
- On Amazon, int8 also lowers Spearman (0.829 → 0.809).

**M7 checks**
- On dev, two wiring faults were found and fixed before the code was frozen:
  - a missing rule id inside a refused proposal was not caught;
  - rules that are always checked were wrongly counted as "never used".
- On held-out data: 16/16 caught and 0 false flags.
