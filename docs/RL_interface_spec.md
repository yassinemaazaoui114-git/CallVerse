# CallVerse RL — interface spec (v1.1, 2026-11-01, Brain; split approved by Yassine)

## What the RL does (one sentence)
A **style policy** (contextual bandit) chooses HOW the reply writer (SLM) says an already-approved decision; the
**reward** is agent F's predicted user satisfaction (or the user's real ★ rating). It never changes a decision, an
amount or a rule.

## Who builds what
| Piece | Owner | Branch |
|---|---|---|
| RL1 · Style-aware writer (styles + templates + situation features) | Yassine (core) | feature/rl1-styles |
| RL3 · Agent F · satisfaction predictor (Notion 33) | **Semah** | own branch |
| RL4 · Training simulator: scenarios + simulated user reactions and ratings (Notion 15, 17) | **Mahmoud** | own branch |
| RL5 · Style policy + `style_log` + Console "Learning" page | Yassine (core) | feature/rl5-policy |
| RL6 · Evaluation vs baselines | Semah + Yassine | – |
Merges into main only after the Brain's review. If a piece is not ready by the agreed date, Yassine builds a minimal version.

## Shared objects (the contract)
### Situation (built by RL1, read by everyone)
```json
{"company": "shopnova", "reason": "refund_request", "outcome": "approve", "action": "refund",
 "rule_id": "R-REF-03", "emotion": "anger", "sentiment": "negative", "priority": "high", "days_late": 6}
```
### Styles (fixed by RL1b)
`short` (greeting + decision) · `warm` (greeting + one SLM empathy sentence + decision) · `warm_next_step` (`warm` + one
closing line by outcome, by code).

### Conversation record (what F reads)
```json
{"ticket_id": "T-0001", "company": "shopnova",
 "messages": [{"role": "user", "text": "..."}, {"role": "assistant", "text": "..."}],
 "situation": {"...": "as above"}, "style": "warm"}
```

## Semah — agent F (RL3)
- **Function:** `predict_satisfaction(record: dict) -> {"score": float 1..5}` in `callverse/quality/satisfaction.py`.
- **Limits:** CPU only, ≤ 200 ms per record, no API at run time, no write to any database.
- **Data (real first, CLAUDE.md rule 10):** look for real conversation + satisfaction data first; real anchors such as
  Olist review scores vs delivery delay; simulated ratings (Mahmoud) only to fill volume, flagged as simulated.
- **Check:** against the team's real ratings (Notion 31, ~100 conversations, kept apart, never trained on):
  MAE and Spearman correlation. A baseline must be beaten (e.g. "predict the average" and a delay-only rule).
- **Deliver:** code + tests, a model card (data, licence, metrics), a report in `tasks/`.

## Mahmoud — training simulator (RL4)
- **Scenario generator:** `make_situations(n, seed) -> list[situation + first_message + facts]`. First messages are **real
  tweets (TWCS)** where possible; facts from our scripted orders / bookings; decisions made by code (no agents, no Groq).
- **User reaction:** `react(situation, reply, persona) -> {"rating": 1..5, "comment": str}`. Personas (patience, tone
  preference, mood) generated with M1 (Gemini Flash), **not hand-written preferences** (otherwise the RL just finds
  what we wrote). Two persona sets with different seeds: one for training, one kept for evaluation.
- **Volume:** ≥ 2,000 rated replies for training; seed fixed; cost and quota written in the report.
- **Deliver:** code + tests, a realism check vs real data (rating distribution vs Olist scores), a report in `tasks/`.

## Yassine — RL1 and RL5 (core)
- RL1: the writer takes `style`; one template per style; must_say and the rule check unchanged.
- RL5: `callverse/learning/style_policy.py` (Thompson sampling per situation group), table `style_log`
  (situation, style, reply, reward, source = predicted / real), `scripts/train_style_policy.py` (offline loop:
  simulator → SLM → F → update), Console "Learning" page (reward curve, best style per group, baselines).

## Proof (RL6)
Baselines: always `short`, always `warm`, random. Evaluated on the **evaluation persona set**, plus F checked on
real team ratings. Report: average reward, gain vs baselines, best style per situation group.

## v1.1 note (2026-11-01, after the F1 review of Semah's agent F)
- Semah's accepted F (`callverse/quality/satisfaction.py`, `reward.py`) reads only the **user's words** (and `situation.days_late`);
  `style` and the assistant reply are **ignored** unless an optional stacker (`models/agent_f/stacker.pkl`) exists. Today the stacker does not exist.
- Consequence: with F as it is, the reward is **the same for all three styles**, so the bandit (RL5) cannot learn from it. Before RL1/RL5 we need
  reward data that **changes with the style**: (a) a stacker trained on simulated ratings (Mahmoud's simulator, flagged as simulated) and/or
  (b) a small real preference study (the team rates the same reply in the 3 styles). The team's ~100 real ratings stay the final exam (never trained on).
  Decision with Yassine: open (see handoff).
- `reward.evaluate_response(record)` = correctness (PASS / FAIL / UNKNOWN) + satisfaction → reward +1 / −1 / None. Reply-correctness uses the Coordinator `decision`
  (`docs/decision_format.md`).
