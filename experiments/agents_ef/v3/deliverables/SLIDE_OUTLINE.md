# Slide outline: Agents E and F, tiny-model benchmark V3 (for the professor)

The numbers on slides 6 and 9 come from `04_AGENT_E_RESULTS.md` and `05_AGENT_F_RESULTS.md`. Never quote them from memory.

## 1. Question
Which tiny models (or rules) should run Agent E (capacity) and Agent F (satisfaction) in CallVerse, and why?

## 2. Where E and F sit
- E watches the queues and **proposes** capacity changes.
- F predicts the satisfaction of a support conversation.
- Neither acts: the Coordinator (rules, no LLM) checks and executes.

## 3. Agent E: vertical architecture

```
 Intake tickets (priority, emotion, queue)
                │
                ▼
 Queue state (43 numbers: per-queue waits, backlog, sessions,
              time of day, fallback allowance, Intake aggregates)
                │
                ▼
 Action mask (budget, min sessions, urgent minimum, fallback cap, no HIGH fallback)
                │
                ▼
 Policy: tiny MLP (8.1k params DQN family, 15.1k PPO) or rule (Forecast / Erlang-C / MPC)
                │  proposal (1 of 17 actions)
                ▼
 Coordinator (rules): re-checks the constraints and executes or keeps
                │
                ▼
 Simulated day (tape-based, same world for every policy) → KPIs, trace
```

## 4. Why a new simulator (v3)
- Bug in v1/v2: one shared random generator, so the arrivals changed with the policy.
- Fix: a pre-generated "tape" for each day, which makes paired tests valid.
- Gate A: 25 / 25 invariant tests pass.

## 5. Agent E protocol
- Balanced objective, fixed before training: SLA failures, lost customers and cost, each normalised by the planned-staffing reference.
- Data splits:
  - TRAIN: 8 families;
  - VAL: 48 days;
  - locked TEST: 650 days, 13 families, 5 of them never seen in training.
- Rules tuned on VAL. RL: 5–10 seeds, matched budget.
- Statistics: paired two-level bootstrap, Holm correction, Pareto fronts.

## 6. Agent E results
- Leaderboard figure (`v3/e/figures/e_leaderboard.png`), Pareto figure, per-family figure.
- Verdict: does RL beat the best classical rule? Answer from `06_STATISTICAL_ANALYSIS.md`.

## 7. Agent F: vertical architecture

```
 Conversation text (customer + agent turns, up to the prediction time)
                │
                ▼
 Tokenizer (vocabulary trimmed to the corpus)
                │
                ▼
 Tiny encoder (< 30M params: TinyBERT / trimmed MiniLM / trimmed e5-small)
   or TF-IDF + linear model (baseline)
                │
                ▼
 Regression head → satisfaction score 1–5 (+ 3-class view)
                │
                ▼
 KPI only: dashboards and human review; it never rewards Agent E directly
```

## 8. Agent F data and labels
- USS: human annotations, primary benchmark.
- Amazon EN/FR: product stars, auxiliary.
- Synthetic CSAT: rejected.
- DCH-2: needs a user agreement, not accepted.
- Low annotator agreement (α 0.2–0.5) caps any model.

## 9. Agent F results
- Leaderboard: MAE, QWK, Spearman, size, latency.
- Verdict: transformer vs simple baseline.

## 10. E × F
- The F model is not a valid reward: its domain does not match, and the simulator has no text.
- Only a synthetic SIM-CSAT term was tested, with all safety limits kept.

## 11. Limitations and next steps
See `09_LIMITATIONS_AND_NEXT_STEPS.md`:
- invented simulator parameters;
- no real contact logs;
- no GPU numbers;
- DCH-2 pending an agreement.
