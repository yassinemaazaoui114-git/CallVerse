# T06 report — Merge the pipeline, Policy search (RAG), Agent B

## 1. In plain words
The reviewed pipeline (T04) is now merged into `main`. ShopNova's rules can now be found by meaning: a
question like "can I get my money back, it's 8 days late" finds the refund rule even though it uses
different words. Agent B (Payment & Refund) now answers refund, return and damage requests. It asks Agent A
for the delivery facts, checks past refunds, finds the rule and, when the rule allows it, sends a
**proposal** for checking. It never pays anything and never promises money. On the main demo (order 4512,
6 days late) it proposes 59.90 TND under rule R-REF-03. It correctly refuses 4506 (already refunded) and
4510 (not late).

## 2. Done
- **Step 0**: `main` ← `feature/pipeline` (`--no-ff`, no conflict), 101/101 tests, pushed (`22aa220`).
  New branch `feature/agent-b`.
- **Policy search** — new `callverse/kb/search.py`. Each rule is embedded as `title. text` with M3,
  reusing Intake's loader (`intake.reasons.embed`, so the model is loaded once). Vectors are cached in
  `callverse/kb/policy_vectors.npz` (git-ignored, rebuilt if the policy file or the model changes).
  Scores are cosine similarities. `search_policy(query, k=3) -> [{id, title, text, score}]`; `rank()` is
  the pure-maths part (tested with stubbed vectors). Traced as `policy_search`. Tool `search_policy` +
  schema in the registry, allowed for A and B.
- **Proposal tool** — new `callverse/tools/proposal_tools.py`: `propose_refund(order_id, amount, rule_id,
  facts_used, user_confirmed, user_quote)`. It checks the fields only:
  - integer order id;
  - amount a finite number > 0 (not bool, not text);
  - rule id present and existing;
  - non-empty `facts_used` dict;
  - `user_confirmed` a bool;
  - non-empty quote.

  It gives ids `P-0001`, `P-0002`… and keeps proposals in memory. It traces `proposal` (or
  `proposal_refused`) and returns `"submitted to Coordinator"`. No database write.
- **ask_agent** — new `callverse/agents/ask.py`: `ask_agent(agent, question)` runs Agent A and returns
  `{agent, answer, facts}`. `facts` = A's tool calls and their results. Only `"A"` can be asked, and A has
  no `ask_agent`, so the agents cannot ask each other in a loop. Traced `ask_agent`. The registry passes
  the caller's LLM function to this tool (so tests use a fake LLM). The model cannot set it.
- **Agent B** — new `callverse/agents/agent_b.py`, same base loop. Its allow-list is `get_order,
  get_refunds, search_policy, propose_refund, ask_agent` (no `get_tracking`). Its prompt gives the steps
  (order → ask A → refunds → search rule → decide) and says:
  - always cite the rule id;
  - make no proposal when already refunded, not late / 1–5 days late, damaged without a photo, or a return;
  - never promise money;
  - plain text only.

  `run()` adds `proposal` (the last accepted one, or None).
- **Agent B step limit**: `BaseAgent` now has a `max_steps` class field (default 5 = `MAX_STEPS`, Agent A
  unchanged); Agent B uses 8. Why: its job is 5 tool steps + the answer = 6 model calls. With 5 it always
  stopped at the limit.
- **Pipeline** — route B runs Agent B; A's `[HANDOVER: B]` also runs Agent B on the same message. The
  result has `handover_text` and `proposal`; `HANDOVER_ANSWER` is removed.
- **Handover texts** per reason in `config.yaml` (`queues.handover_texts`): refund check / returns check /
  damage check. The pipeline traces this sentence and returns it as `handover_text`. The client's answer is
  Agent B's answer. A's handovers (money requests) use the refund text.
- **Plain text**: A's and B's prompts say "plain text only, no Markdown". A's prompt no longer says
  "refund team" ("passed on for checking"). Both prompts now say "answer in the language of the client's
  message (English → English)". Reason: B once answered an English message in French (see Problems).
- **Company profile**: `get_company_profile` added to A's allow-list and mentioned in A's prompt.
- **Single source for 300 TND**: `intake/priority.py` reads the threshold from R-ESC-01
  (`layer3_threshold()`); `amount_bonus.paid_over` removed from `config.yaml` (only `add: 0.2` stays).
- **Windows UTF-8 fix** in `scripts/run_demo.py`.
- New `scripts/eval_policy_search.py` (held-out evaluation, top 1 / top 3); `run_pipeline.py` prints
  handover text and proposal; README status updated; `.gitignore` + `policy_vectors.npz`.
- Tests: new `tests/test_agent_b.py` (25 tests). Updated:
  - `tests/test_pipeline.py`: 2 tests expected the old fixed text.
  - `tests/test_tools.py`: 2 platform tests said "get_refunds / get_company_profile on no allow-list
    yet". They now check "only B" / "only A".
  - `tests/conftest.py`: resets proposals before each test.

## 3. Evidence
- Tests: **126/126 passed** (`python -m pytest -q`; 101 before + 25 new, 4 rewritten; 0 API calls).
- **Held-out policy search** (`tests/data/policy_search_questions.json`, run **once**, after a dry run on
  2 questions of my own): **top 3 = 10/10** (≥ 9 required), **top 1 = 7/10**. The 3 top-1 misses:
  - q01 "8 days late… money back" → R-DEL-02 first, R-REF-03 second;
  - q05 "refund of 450 TND" → R-REF-05 first, R-ESC-01 second;
  - q08 "by when should my order arrive" → R-DEL-02 first, R-DEL-01 second.

  Trace `traces/run_20261020_221402_674200.jsonl`. Nothing tuned on it.
- **4512** `"Order 4512 is a week late. I want my money back."` → refund_request, HIGH 0.831, route B.
  Tools used, in order: B:get_order, A:get_tracking (inside B:ask_agent), B:get_refunds,
  B:search_policy, B:propose_refund. Proposal:
  `{'proposal_id': 'P-0001', 'type': 'refund', 'order_id': 4512, 'amount': 59.9, 'rule_id': 'R-REF-03',
  'facts_used': {'days_late': 6, 'delivered': False, 'paid': 59.9, 'refunded_total': 0},
  'user_confirmed': True, 'user_quote': 'I want my money back.', 'status': 'submitted'}`
  Answer: "Your refund request has been forwarded for approval under rule R‑REF‑03. The proposed amount
  is 59.9 TND. You'll be notified once the Coordinator reviews the proposal."
  Trace `traces/run_20261020_222358_444726.jsonl`.
- **4506** `"Please refund order 4506."` → **no proposal**; "the order has already been fully refunded.
  According to rule R‑REF‑05, no further refund can be issued." Get_refunds was called.
  Trace `traces/run_20261020_221947_117900.jsonl`.
- **4510** `"I want a refund for order 4510."` → **no proposal**; "not yet delivered and it is not late
  (promised 2026‑10‑10, today 2026‑10‑09). According to our policy (R‑DEL‑01) refunds are not offered…".
  Trace `traces/run_20261020_221806_037474.jsonl`.
- Markdown `**` in the answers of these runs: **0**. Agent A demo (`run_demo`, carriers + 4512): plain
  text, used get_company_profile, get_order, get_tracking; trace `traces/run_20261020_222640_922104.jsonl`.
- Cost of one Agent B turn: ~10.5–12.7k tokens, ~6 s of LLM time (6–8 model calls including Agent A's).

## 4. Problems
- **Groq rate limit**: the free tier allows 8,000 tokens per minute per model. One Agent B turn uses about
  10–13k tokens, so it already falls back from 120b to 20b mid-turn (1–2 fallbacks per run in the traces).
  Two runs back-to-back exhausted both models: `AllModelsFailed` (429) on the first 4510 try. Rerun after
  a 65 s pause: OK. The demos and the batch (`--batch`) need pauses, or a paid tier.
- **Language**: the first 4506 run answered an English message **in French** (model guess, the shop is in
  Tunisia). I added "English message → English answer" to both prompts. The rerun was in English. This
  is a prompt rule, so it can still slip.
- **Rule ids in the text use a non-breaking hyphen** (`R‑REF‑03`, U+2011) written by the model. The
  proposal's `rule_id` field is a normal `R-REF-03`, so the Coordinator is fine. A text search for
  "R-REF-03" in the answer would fail.
- B's answer says "the Coordinator" to the client (internal name). The SLM rewrite (T05) should hide it.
- Policy search top 1 is 7/10: close rules (R-DEL-01/02, R-REF-03/05, R-ESC-01) score near each other.
  Top 3 is 10/10, which is why B gets 3 rules.
- Proposals are in memory only, so they are lost when the process ends (until Dali's P06 `proposals` table).

## 5. Questions for the Brain
1. Rate limit: keep pauses in the demos, cut B's tokens (e.g. shorter tool results from A), or use a paid
   Groq tier for the demo day?
2. `max_steps` per agent (A 5, B 8): OK, or should every agent use one shared limit?
3. Should the pipeline (or the SLM) normalise the model's special hyphens and remove internal names like
   "Coordinator" from client answers?
4. `handover_text` is returned and traced but not added to the client's answer (B's answer already says
   "sent for checking"). Should the channel show/say it before B's answer?

## 6. Next step
Review T06, then T07 Coordinator: `review(proposal)` checks the rule's condition with `check_condition`
on `facts_used` + re-read facts, R-REF-05 limit and R-ESC-01 → Layer 3, then `create_refund` on approve.
