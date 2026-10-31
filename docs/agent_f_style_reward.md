# RL3 — Agent F style-aware reward: implementation and handoff

This patch is based on the GitHub branch `claude/agent-f-satisfaction-rr8f85` at commit `79bc5ee` (2026-10-31). Apply only to an isolated feature branch; **do not merge to main** before review.

## What this does and does not do

- Preserves `predict_satisfaction(record) -> {"score": float 1..5}`, CPU-only. Base prediction still uses the original trusted real-review classifier plus the Olist delivery-delay prior.
- Introduces **style × emotion interaction features** so that a trained Ridge candidate can predict different scores for `short`, `apology_first` and `apology_next_step` under different emotional contexts.
- Adds a train/validation pipeline that accepts **only explicitly tagged simulated training-persona reactions** (RL4), requires 2,000+ rated replies and 8+ personas by default, and separates training from validation **by persona**. It never imports an evaluation-persona dataset or the ~100 human-rated holdout.
- Trains and saves `models/agent_f/stacker_candidate.pkl`, not the live `stacker.pkl`. Saves a JSON report with provenance, MAE/Spearman, leakage checks and style sensitivity. **No automatic deployment**.
- Adds a **one-shot real-team evaluation** comparing the candidate against the fixed Agent F and the existing mean/delay baselines. This requires the team-rated real JSONL and human confirmation, and never trains on it.
- Adds offline unit tests for interactions, no-leakage split, simulated-only validation and style-sensitive prediction. The unit-test scores use *toy synthetic data*, not a model evaluation claim.

This is an **RLHF-style simulated-feedback reward proxy** for a contextual bandit. It is NOT a PPO policy, a human-preference-trained foundation model, or proof that the style reward generalizes to humans.

## Apply

Overlay these paths onto the existing Agent F branch, then run:

```bash
python -m pytest tests/test_satisfaction.py tests/test_agent_f_style_training.py -q
```

To build the original trusted base model if it does not already exist:

```bash
python -m benchmarks.agent_f.train
```

**RL4 data required** (obtain from Mahmoud): at least 2,000 JSONL rows from `react()`, all `source="simulated"`, `persona_id` distinct and **TRAINING** personas only. Each row must include `rating` in 1–5, `style`, `situation` (with `emotion` and optional `days_late`), and `messages` with user and assistant turns. A `scenario_id` (same situation under 2+ reply styles) is strongly recommended for counterfactual interpretation. Never generate ratings by simply calling Agent F; that would train the reward to copy itself.

```bash
python -m benchmarks.agent_f.train_style data/rl4_train_persona_ratings.jsonl
```

If the dataset does not exist, this step is **blocked**, and no style-aware reward can honestly be trained. The generated model is a candidate at `models/agent_f/stacker_candidate.pkl`. It is not auto-loaded by production code.

When the independent ~100 genuinely human-rated support conversations arrive **and the candidate configuration is frozen**, run the locked final check ONCE:

```bash
python -m benchmarks.agent_f.evaluate_style_candidate data/real_human_ratings.jsonl \
 --candidate models/agent_f/stacker_candidate.pkl --confirm-real \
 --out benchmarks/agent_f/results/real_support_final.json
```

Do **not** use these 100 ratings for tuning alpha, optimizing features, choosing a model or repeating experiments. Source/license/provenance should be verified before use. No fake scores, fabricated tests, or automatic promotion.

## Before promotion, require all of the following

1. Locked real support MAE no worse than original fixed Agent F, with measured p95 <200ms.
2. Clear style-sensitive rewards on held-out, independently rated situations; manual audit to guard simulator self-confirming feedback.
3. Same immutable Coordinator outcome, amounts, approved actions and `must_say` across styles. Style selection **must never** authorize business actions.
4. RL5 Yassine bandit baseline evaluation (always `short`, always `apology_first`, random). Use the same held-out evaluation personas and seeds for paired comparisons.
5. Real team reviews the results and confirms the valid interface contract. Only then explicitly promote the candidate to `models/agent_f/stacker.pkl` on the intended machine, and document an artifact checksum and rollback plan.

## Known constraints, not work completed by this patch

- Real team ratings (~100) were not available in checked GitHub/Notion. They must be sourced; **do not invent them**.
- Mahmoud's existing simulator (`feature/client-simulator-with-real-data`) does not expose the new RL4 `react()` train-persona vs evaluation-persona output in GitHub as of the recheck. Do not confuse the old MiniLM `score_conversation()` with style-counterfactual ratings.
- Yassine's RL5 writer/contextual bandit and Console Learning page were not found on `main`; they are team-owned, not Agent F changes.
- `RL_interface_spec.md` itself was not present in GitHub or searchable files. This patch follows the documented record contract; require confirmation against the canonical spec before integration.
- Base `models/agent_f/satisfaction.pkl` is git-ignored and must be built or obtained from a trusted source.
- The data and learned reward can be biased by persona and simulator models. A randomized human A/B test would be necessary for causal claims; matching ratings on a tiny holdout does not establish real-world improvement.
