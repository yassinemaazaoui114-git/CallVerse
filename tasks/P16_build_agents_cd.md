# P16 — Build Agents C and D on the local base model (Groq fallback, Coordinator gate)  ·  core files, needs Yassine's OK

## Why
Only after P15's decision box is signed. This task builds the two agents exactly as the signed spec says, with the
same pattern as Agents A and B: one shared tool loop (`base_agent.py`), an allow-list enforced in code
(`tools/registry.py`), action tools that only create **proposals**, and the **Coordinator** (rules, no LLM) as the
only part that writes. The agents run on the base `qwen3:4b-instruct-2507` in Ollama, with the Groq chain as backup.
The fine-tuned `callverse-m2-abcd` is **not** used (failed the 2026-10-28 smoke test: "Acme" greeting, no tool calls).

This file is written for **Option 1** of P15 (C = Returns & Damage, D = Notifications & Account). If Yassine signed
another option, stop: the Brain rewrites this file first.

## Hard limits
- Start only if `docs/agents_cd_proposal.md` has the decision box signed by Yassine (quote it in the report).
- Agents A and B: **no change** to their prompts, allow-lists or model chain, except what the signed spec moves
  (the router lines and, if chosen, A's handover tag to D).
- Coordinator: **no new rule logic** unless the spec lists it as a missing check; any added check is traced and tested.
- Model choice in `config.yaml` only. No new library. No prompt tricks for one model (T13 fix rule).
- No Groq / Gemini call in this task (offline tests use a fake LLM). One local smoke run only (step 7).
- Never run `tests/data/*`. Never read or stage `.env`.

## What to do
1. **Local model.** If `cv-qwen3-4b-instruct` is not in `ollama list`, create it (as P11): Modelfile
   `FROM qwen3:4b-instruct-2507-q4_K_M` + `PARAMETER num_ctx 8192`, `ollama create cv-qwen3-4b-instruct -f Modelfile`.
   Prove it: `ollama show cv-qwen3-4b-instruct` lists `tools` and `num_ctx 8192`. Keep the Modelfile outside the repo.
2. **Config role `agents_cd`** in `config.yaml` `models`, with comments (what, why):
   ```yaml
   agents_cd:   # Agents C and D (P16): local base model first, Groq chain as backup (provider errors only)
     - {provider: ollama, model: "cv-qwen3-4b-instruct", temperature: 0, seed: 42}
     - {provider: groq,   model: "openai/gpt-oss-120b", options: {reasoning_effort: low}}
     - {provider: groq,   model: "openai/gpt-oss-20b",  options: {reasoning_effort: low}}
   ```
   No `reasoning_effort` on the Ollama line (Instruct-2507 has no thinking mode). The default `agents` chain stays
   exactly the same.
3. **Allow-lists** in `callverse/tools/registry.py`: `AGENT_C` and `AGENT_D` with the exact tools of the signed spec
   (Option 1: C = `get_order, get_tracking, get_refunds, search_policy, propose_refund`;
   D = `get_user, get_order, get_tracking, search_policy, propose_subscription`). Add `"C"` and `"D"` to `ALLOW_LISTS`.
   Comment why each list is what it is.
4. **Agents** `callverse/agents/agent_c.py` and `agent_d.py`, copied from the shape of `agent_b.py` / `agent_a.py`:
   module docstring (job, tools, steps), `SYSTEM_PROMPT` = the signed draft, `agent_id`, `name`,
   `role_key = "agents_cd"`, `max_steps` with a one-line reason, and `run()` that returns `proposal`
   (`refund_proposal` for C, `subscription_proposal` for D) exactly like A and B.
5. **Routing** (`config.yaml` `queues.routes` + `callverse/pipeline.py` `_run_agents`): send the reasons of the spec
   to C, and D's requests by the chosen way (handover tag `[HANDOVER: D]` from Agent A, or a new reason). Each agent
   goes through `run_agent_with_coordinator` (same send-back loop, same T10 retry). Trace each new route/handover.
6. **Coordinator gate.** Proposals from C and D go through `coordinator.review` unchanged. Add only the missing
   checks listed in the signed spec. Confirm in the report: C cannot write a refund with `R-REF-03` unless the spec
   allows it (it is in `allowed_rules.refund`: say whether the spec wants that, and how it is blocked if not).
7. **Tests (offline, fake LLM)**, new file `tests/test_agents_cd.py`:
   - allow-lists: C and D see only their tools; a call outside the list is refused and traced (`tool_refused`);
   - C on a damaged item without photo → no proposal, R-DMG-01 cited; D on "tell me when 4510 arrives" →
     `propose_subscription(event="delivered")` → Coordinator approves;
   - a proposal from C / D with a wrong rule → `send_back`; nothing is written before the Coordinator approves;
   - routing: `return_item` / `damaged_item` → C; S0 ("where is my order 4510?") still → A; S1 still → B;
   - config: `agents_cd` chain order; Ollama down (fake connection error) → next model is Groq 120b.
   All existing tests still pass (update only tests that check the moved routes, and explain each one).
8. **One local smoke run** (no Groq): with Ollama up, run one message per agent through
   `python -m scripts.run_pipeline` (or `run_scenario`), and check the trace shows `provider: ollama` for C/D.

## Checks (with numbers)
- `ollama show cv-qwen3-4b-instruct`: tools yes/no, num_ctx.
- Offline tests x/y, all pass; new tests n; changed existing tests (names + why).
- Allow-lists: C n tools, D n tools; prompts length in characters vs Agent B.
- Smoke: per agent, tools called, proposal yes/no, Coordinator outcome, seconds, model used (from trace).
- 0 Groq / Google `llm_call` lines in the smoke traces.

## Time box and stop rule
2.5 h. Stop and report if the base model makes no valid tool call in the smoke run (that is P18's job to measure,
do not fix prompts here), or if any write happens without a Coordinator approval.

## Git (needs approval)
Continue `feature/agents-cd`. Commit and push. **No merge into `main`** (Brain's review + Yassine's OK).
Write `tasks/P16_report.md`.
