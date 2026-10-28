# P15 — Agents C and D: write the spec as a PROPOSAL (decision gate, no code)  ·  needs Yassine's OK

## Why
The team wants two more agents (C and D) running on the local base model, with Groq as backup. Today there is
**no code, prompt, tool list or rule** for them, and CLAUDE.md says "Out of scope for the prototype: agents C, D, E, F,
... fine-tuning". Yassine owns the agents and the locked decisions. So the first step is only a written proposal he
can accept, change or refuse. Nothing is built before his written OK. Background: `docs/m2_finetune_review.md` §5.1.

Why the base model and not the fine-tune: `callverse-m2-abcd` failed the smoke test on 2026-10-28 (it greets the
client as "Acme" and calls no tool). Tasks P16 to P19 therefore use the base `qwen3:4b-instruct-2507` in Ollama.

## Hard limits
- Write **one file only**: `docs/agents_cd_proposal.md`. No change to `callverse/`, `config.yaml`, prompts, tests,
  CLAUDE.md or any NEXT file.
- No LLM call (Groq, Gemini or Ollama). Reading code and data is enough.
- Do not choose for Yassine. Give options, recommend one, and say why in plain words.
- Never read `tests/data/*` (held-out).

## What to do
1. **Read** the agent pattern: `callverse/agents/base_agent.py`, `agent_a.py`, `agent_b.py`, `callverse/tools/registry.py`,
   `callverse/tools/proposal_tools.py`, `callverse/coordinator/coordinator.py` (`review`, `allowed_rules`),
   `callverse/queues/router.py` and `config.yaml` (`queues.routes`, `coordinator.allowed_rules`),
   `callverse/kb/policies_shopnova.json`, `callverse/data/seed.py` (scripted orders 4505 to 4515).
2. **Write the options** in `docs/agents_cd_proposal.md`. At least these two, plus any better one you find:
   - **Option 1 (recommended starting point): split the ShopNova work, reuse what exists.**
     - **Agent C — Returns & Damage.** Takes `return_item` and `damaged_item` from Agent B (B keeps late refunds).
       Read tools: `get_order`, `get_tracking`, `get_refunds`, `search_policy`. Action tool: `propose_refund` only,
       with rule `R-RET-01` (return within 14 days, delivered) or `R-DMG-01` (damage, only after a photo).
       Both rules are already in `coordinator.allowed_rules.refund`, so **no new Coordinator action**.
     - **Agent D — Notifications & Account.** Takes delivery-notification requests (story S3) and client-account
       questions from Agent A (A keeps "where is my order"). Read tools: `get_user`, `get_order`, `get_tracking`,
       `search_policy`. Action tool: `propose_subscription` only (rule `R-NOT-01`, already allowed).
     - Why it is good for the grade: each agent has a **smaller allow-list** (less room for a wrong tool), and the
       Coordinator gate is unchanged. Cost: routing must know which messages go to C and D (see step 3).
   - **Option 2: Atlas Travel (second company).** C = hotel-booking cancellations (`docs/platform.md` line ~60,
     `docs/platform_contract.md` line ~143). Needs new data, new read tools, a new action and new Coordinator rules:
     much bigger, and the demo stories S0 to S4 cannot be reused for tests.
3. **For the recommended option, write the full spec of each agent**, in the same shape as Agent A / B:
   - **Role** in 2 sentences; which `main_reason` values the router sends to it (`queues.routes` lines to change).
     Say how D gets subscription requests: Intake has no "subscription" reason today. Options: (a) Agent A hands over
     with a tag like `[HANDOVER: D]` (as A → B today), or (b) a new Intake reason (needs Intake examples: bigger).
     Recommend one.
   - **Allow-list** (exact tool names) and why each tool is on it and why the others are not.
   - **Draft system prompt** (short, same style as `agent_b.SYSTEM_PROMPT`: facts only from tools, cite the rule id,
     call the proposal tool before the final answer, never promise, plain text, client's language).
   - **Coordinator gate:** which proposals it can make, which rule ids, which existing checks apply. List any check
     that is missing (e.g. R-RET-01 "delivered and within 14 days" is checked by the Coordinator today? Read
     `review()` and say yes/no with the line).
   - **Model:** role key `agents_cd` in `config.yaml`: `cv-qwen3-4b-instruct` (Ollama, base model with
     `num_ctx 8192`, temperature 0, seed 42) → `openai/gpt-oss-120b` (Groq) → `openai/gpt-oss-20b` (Groq).
     Say clearly: this fallback moves to Groq **only on provider errors** (Ollama down, timeout), not on bad answers.
4. **Data check.** List which scripted orders each agent can be tested on, with the facts on `sim_today`
   2026-10-09. Note: no scripted order is delivered within 14 days of 2026-10-09 (4505: 09-14, 4507: 09-22,
   4508: 09-23, 4509: 09-24), so **no scripted order allows a return refund**. Check this yourself and write the
   options: use a generated order 5001-5120 that fits (find one), or ask Dali for one new scripted order (platform lane).
5. **Write the decision box** at the top of the doc, for Yassine to fill:
   ```
   Decision (Yassine): Option __   ·   D gets requests by: handover tag / new Intake reason
   Scope change in CLAUDE.md "Out of scope" line: agents C, D move into scope  yes / no
   Local base model for C and D with Groq fallback: yes / no
   Signed: ____  Date: ____
   ```

## Checks (with numbers)
- `docs/agents_cd_proposal.md` exists, has the decision box, ≥ 2 options, one recommendation with reasons.
- For each agent: allow-list (n tools), prompt length (characters; Agent B's is the reference), rule ids, router lines.
- Table of test orders per agent (order id, status, delivered date, days_late, paid, refunded) read from `seed.py`.
- Count of Coordinator checks that already cover C and D vs. missing ones (with line numbers).
- Offline tests unchanged (no code change): x/x.

## Time box and stop rule
60 minutes. Stop when the doc is written. **Decision gate:** P16 must not start until the decision box is signed by
Yassine. If he picks something other than Option 1, the Brain rewrites P16 to P18 first.

## Git (needs approval)
Branch `feature/agents-cd` from the latest `main`. Commit `docs/agents_cd_proposal.md`, this task file and
`tasks/P15_report.md`. No merge into `main`.
