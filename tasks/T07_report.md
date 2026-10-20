# T07 report — Platform + Agent B into main, the Coordinator (S1, S2, S4), rate-limit fix

## 1. In plain words
The platform work (P05–P07) and Agent B (T06) are now joined in `main`. The new **Coordinator** is a
rule-based gate with no AI. It takes each agent proposal and re-reads the real data itself. Then it
checks the cited rule, the refund limit, the client's confirmation and the finance limit. Only then does
it let the platform write the refund. The three demo scenarios run end to end:
- S1: the 59.90 refund is approved;
- S2: a wrong amount (70.00) is sent back, Agent B corrects it, and it is approved;
- S4: the 378 TND refund goes to finance first and is approved.

Agent B now uses about half as many tokens per turn (11,681 → 5,911). Groq's rate limit now causes a short
wait instead of a crash, and Gemini Flash is a third backup model.

## 2. Done
- **Step 0 — merges.** `CLAUDE.md` committed on `main` (`516c33e`, "git rules and lanes (approved)").
  Then `origin/platform` was merged (`a001c4d`). It had 2 conflicts, both on the allowed list, resolved by
  keeping both sides:
  - `requirements.txt`: intake libraries + FastAPI/uvicorn/httpx;
  - `tasks/NEXT_PLATFORM.md`: the platform side (P07), plus `main`'s "Queue: T05" row.

  Then `origin/feature/agent-b` was merged (`a9e98ce`, no conflict). `CLAUDE.md` kept the new git rules
  and the three lanes. `pip install -r requirements.txt` was needed: fastapi was missing locally. Tests
  passed and `main` was pushed. New branch `feature/coordinator`.
- **Coordinator** — new `callverse/coordinator/coordinator.py`, `review(proposal, case) -> decision`:
  - First `record_proposal`, which gives the id. The Coordinator never trusts `facts_used`: it keeps them
    in the trace for comparison only.
  - Facts it re-reads itself: `paid` (`get_order`), `refunded_total` (`get_refunds`), and `days_late`,
    `delivered`, `days_since_delivery` (`get_tracking`).
  - Checks, each traced as `coordinator_check` (rule, facts, result):
    - action known;
    - order exists;
    - the rule exists and may justify the action. Allowed rules per action are in
      `config.yaml → coordinator.allowed_rules` (refund: R-REF-03 / R-RET-01 / R-DMG-01; subscribe:
      R-NOT-01 / R-DEL-02);
    - `check_condition` holds;
    - **R-REF-05 always** for refunds, **R-NOT-01 always** for subscriptions;
    - `user_confirmed`;
    - R-ESC-01 → `layer3_decide`.
  - Outcomes:
    - `approve`: `record_decision`, then `create_refund`, plus `set_order_status(…, "refunded")` for
      R-REF-03; or `create_subscription`;
    - `send_back`: max 2 per case (`coordinator.max_send_backs`); the 3rd becomes `escalate`;
    - `ask_user`;
    - `ask_proof` (R-DMG-01 without proof);
    - `layer3_refused`, recorded as the platform decision `layer3`;
    - `escalate`;
    - `refused`: the proposal was already decided, nothing is written.
  - Decision dict: `outcome, action, order_id, rule_id, facts (verified only), next_step, reason,
    proposal_id`. Traced as `coordinator_decision`.
- **Pipeline** — `run_agent_with_coordinator()`. Each proposal goes to `review`. On `send_back`, the same
  agent runs once more with the reason added to the message. The result now has `proposals` and
  `decision`. It works for any agent that returns a `proposal`, including Agent A subscriptions with
  action `subscribe`.
- **`propose_refund`** no longer keeps its own P-0001 counter or memory store. Ids now come from the
  platform's `proposals` table, through the Coordinator. Agent B's `proposal` is in the platform shape
  `{agent, action: "refund", params: {order_id, amount}, rule_id, facts_used, user_confirmed, user_quote}`.
- **Scenarios** — new `scripts/run_scenario.py S1|S2|S4 [--inject-error]`. It prints a readable step list
  (route, tools, LLM model + tokens, every check, Layer 3, writes, decision), the proposals as recorded by
  the platform, the order status and refunds, and the trace path.
  - `--inject-error` changes the **first** proposal that reaches the Coordinator to 70.00. It is traced
    as `inject_error` and printed.
- **Fewer tokens per turn**:
  - `search_policy` tool → top 2, text cut to 300 characters, no `k` parameter in the schema;
  - `ask_agent` returns compact delivery facts from A's `get_tracking`, not A's whole transcript;
  - shorter A and B prompts;
  - shorter schemas for my 3 tools;
  - `reasoning_effort: low` for both gpt-oss models (as `options` in `config.yaml`, passed by `llm.py`).

  Measuring tool: new `scripts/token_report.py`, which reads the traces. I did not change the platform's
  `shopnova_tools.py` schemas.
- **Rate limit** — `llm.py`:
  - on 429, it reads `retry-after`; at most 20 s (`llm.max_retry_wait_s`) → it waits and retries the same
    model once (traced `llm_wait`); otherwise it moves to the next model;
  - 3rd model: **Gemini `gemini-3.5-flash`**;
  - `CALLVERSE_FORCE_<ROLE>_MODEL` (e.g. `CALLVERSE_FORCE_AGENTS_MODEL=gemini-3.5-flash`) keeps only that model.
- **Gemini fix**: Gemini returns an `extra_content` field (its "thought signature") on each tool call
  and needs it back. `base_agent.py` keeps it, and `llm.messages_for()` removes it for providers without
  `tool_call_extras: true`, so Groq never sees it.
- Tests: new `tests/test_coordinator.py` (14) and 4 new tests in `tests/test_llm.py`. `tests/test_agent_b.py`
  and `tests/conftest.py` were adapted to the new proposal flow. README status updated.

## 3. Evidence
- Tests: before the merges **126/126** (feature/agent-b); after the merges on `main` **160/160**; now
  **178/178** (`python -m pytest -q`, no API call).
- **S1** (`traces/run_20261020_233353_415125.jsonl`):
  - refund row id 8: **59.90**, rule **R-REF-03**, status **approved**, proposal P-0001;
  - order 4512 `stuck_at_depot → refunded`;
  - decision **approve**; 9/9 checks PASS.
- **S2** (`traces/run_20261020_235829_636292.jsonl`): `INJECTED ERROR: 59.9 -> 70.0` →
  "SEND_BACK P-0001: R-REF-05: amount 70.0 TND is more than paid 59.9 - already refunded 0 = 59.9 TND". The
  reason goes back to B, B proposes 59.90 → **APPROVE P-0002**. The platform recorded
  `P-0001 70.0 -> send_back, P-0002 59.9 -> approve`: **1 send_back, 2 proposals**. One refund row (59.90).
- **S4** (`traces/run_20261020_234835_707397.jsonl`): 4515, 8 days late. Layer 3 (finance) **approved**,
  refund **378.00** (R-REF-03), order → refunded, decision approve.
- **Agent B tokens per turn** (`scripts/token_report.py`):
  - **before: 11,681** average (4 T06 turns, 10,467–13,018, 7–8 LLM calls);
  - **after: 5,911** average (8 turns, 3,962–8,356; target < 8,000 met).

  The one turn above 8,000 (8,356) is S2's first turn, which had 8 calls.
- **S1 three times in a row, no pause**:
  - first try: 2/3. The 3rd run ended without a proposal: B wrote "I will send a refund proposal" but
    never called the tool. The LLM worked fine (4 short waits, no failure). I made the prompt explicit
    ("you MUST call propose_refund before your final answer");
  - second try: **3/3 approve**, all three answered by **openai/gpt-oss-120b** with no wait or fallback
    (`run_20261020_234538_833893`, `…234558_824781`, `…234618_353844`);
  - earlier runs showed the wait working: `llm_wait` of 1–9 s and one fallback 120b → 20b
    (`run_20261020_234225_634155`).
- **Forced Gemini S1** (`CALLVERSE_FORCE_AGENTS_MODEL=gemini-3.5-flash`,
  `traces/run_20261020_235630_488142.jsonl`): outcome **approve**. Tool calling works, including
  **parallel** calls (get_order + get_refunds in one step): 5 LLM calls, 8,328 tokens.
  - `gemini-3.8-flash` (the simulator's id) failed first: `APITimeoutError` after the 60 s timeout.
    Direct timing of one Agent B call: 3.8-flash 47.5 s (76.2 s with reasoning_effort low),
    flash-latest 53.4 s, **3.5-flash 4.4 s**. So the agents use 3.5-flash.
- Time used: about 2 h of the 3 h box.

## 4. Problems
- **Agent B skips steps sometimes.** In one run (`…234558_824781`) B called only get_order, get_refunds
  and propose_refund. It worked out days_late = 6 itself from the dates and did not cite or search a
  rule. The Coordinator re-read the real data, so the decision was still correct. But the prompt rule
  "facts from tools, always search" is not always followed. With `reasoning_effort: low` the model is
  less careful (the "said it but did not call" slip above).
- **gpt-oss on Groq makes no parallel tool calls**, even with `parallel_tool_calls=true` (tested once).
  So the "do the 3 reads together" step only helps on Gemini.
- **B's answers are written before the decision.** They say "sent for checking", even when the
  Coordinator then approves. Some still say "the Coordinator" (internal name), and S4's answer did not
  mention finance approval. The SLM (T05) should write the final reply from the decision dict.
- `gemini-3.8-flash` (the simulator model in `config.yaml`) is very slow right now (47–76 s per call).
  This matters for the Client Simulator later.
- `tests/test_coordinator.py::test_600_is_refused_by_layer3` raises order 4515's `paid` to 650 **in the
  temp test DB**. The seed data has no order that is late > 5 days, undelivered and paid > 500.
- An `extra_content` field from Gemini would reach Groq only if `tool_call_extras` were set wrongly in
  config; with today's config Groq never sees it.
- `.vscode/` is untracked and not mine; it is not committed.

## 5. Questions for the Brain
1. Agent A has no `propose_subscription` tool yet. The Coordinator and pipeline support action
   `subscribe`, but I did not add a tool to A's allow-list (the task did not list it). Should that be the
   S3 task?
2. Keep `reasoning_effort: low`? It halves tokens but made one tool-call slip. `medium` is safer and
   costs more tokens.
3. Should the Coordinator also refuse proposals whose rule was never returned by `search_policy` in that
   turn ("cite only what you looked up")? Today it only checks that the rule fits and its condition holds.
4. Should `config.yaml`'s simulator model also move from `gemini-3.8-flash` to `gemini-3.5-flash` because
   of the speed?

## 6. Next step
Review T07, merge `feature/coordinator`, then S3 (delivery notification: A proposes `subscribe`, the
Coordinator approves, the clock advances, the notifier sends) and the SLM writing replies from the decision dict.
