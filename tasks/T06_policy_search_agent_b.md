# T06 — Merge the pipeline, Policy search (RAG), Agent B

## Why
Agent B handles refunds, returns and damaged items. It must find the **right company rule by meaning** (RAG over
the Policy KB) and send a **proposal** that cites the rule — never pay or promise money itself. The Coordinator (T07)
will check and execute proposals.

## Hard limits
- Step 0 merges the reviewed `feature/pipeline` into `main` (approved). Everything else on a new branch
  `feature/agent-b`. No other merge.
- Agent B only **proposes**. No database writes, no Coordinator in this task.
- `tests/data/policy_search_questions.json` is held out (written by the Brain): never use it to build or tune; run it once.
- Reuse the M3 model already used by Intake (`BAAI/bge-small-en-v1.5`); no new model. New library: none.
- Do not change the platform files (`callverse/data/*`, `callverse/kb/policies*`), except reading them.

## What to do
0. `git checkout main` → `git pull --ff-only` → `git merge --no-ff origin/feature/pipeline -m "Merge feature/pipeline (T04) into main"`
   → all tests pass → `git push origin main`. Then `git checkout -b feature/agent-b`.
1. **Policy search** — `callverse/kb/search.py`: embed each policy's `title + text` with M3 (reuse Intake's loader),
   cache vectors (git-ignored), cosine similarity, `search_policy(query, k=3) -> [{id, title, text, score}]`.
   Add the tool + JSON schema to the registry; allow it for **A** and **B**. Traced (`policy_search`).
2. **Agent B** — `callverse/agents/agent_b.py` (same base loop). Allow-list `B = [get_order, get_refunds,
   search_policy, propose_refund, ask_agent]`. Prompt: Payment & Refund; always find and cite the rule with
   `search_policy`; get delivery facts from A with `ask_agent("A", question)`; check `get_refunds`; never promise money;
   tell the user the request goes for checking; **plain text, no Markdown**.
   - `propose_refund(order_id, amount, rule_id, facts_used, user_confirmed, user_quote)` — proposal-only tool:
     validates the fields, gives an id `P-0001` (counter), traces `proposal`, returns `"submitted to Coordinator"`.
     Proposals are kept in memory and in the trace for now (the platform's `proposals` table comes with Dali's P06).
   - `ask_agent(agent, question)` runs Agent A and returns its answer + the facts it used.
3. **Pipeline** — route B now runs Agent B (A's `[HANDOVER: B]` also goes to B). Result includes `proposal` if any.
4. **Handover / reason texts** (Brain decision): no more "refund team" for every case. Per-reason short sentence in
   `config.yaml` (refund → refund check, return → returns check, damaged → damage check).
5. **Plain text** (Brain decision): Agent A's prompt also asks for plain text, no Markdown (the SLM and voice channel
   need clean text).
6. **Company profile** — allow `get_company_profile` for **A** (general questions: carriers, delivery promise, cities).
7. **Single source for 300 TND** — Intake's large-amount bonus reads the threshold from rule R-ESC-01 (`amount > 300`)
   instead of `config.yaml`.
8. **Windows console fix** — same one-line UTF-8 fix as `run_pipeline.py` in `scripts/run_demo.py`.
9. Tests (no API calls): search ranking with stubbed vectors; propose_refund validation (missing rule id, amount ≤ 0,
   wrong types → refused); allow-lists (B cannot call `get_tracking`, A cannot call `propose_refund`); pipeline route B
   with a fake LLM; R-ESC-01 threshold read; no Markdown rule present in prompts.

## Checks (with numbers)
- Policy search on the 10 held-out questions: right rule in the **top 3 ≥ 9/10**, top 1 (report x/10).
- `"Order 4512 is a week late. I want my money back."` → B proposes **59.90**, rule **R-REF-03**, facts days_late 6,
  user_confirmed true (paste the proposal).
- `"Please refund order 4506."` → B finds it already refunded (get_refunds) and makes **no** refund proposal; cites R-REF-05.
- `"I want a refund for order 4510."` (not late) → **no** refund proposal; cites R-DEL-01/R-DEL-02.
- Answers contain **0** Markdown `**`.
- All tests pass (report x/y).

## Time box and stop rule
2 hours. Stop and report if the merge in step 0 has a conflict or a test fails.

## Git (approved by Yassine, 2026-10-20)
Step 0: merge `feature/pipeline` into `main`, push `main`. Then branch `feature/agent-b`, commit, push it. No other merge.
Write `tasks/T06_report.md` and set `tasks/NEXT.md` to WAITING FOR REVIEW.
