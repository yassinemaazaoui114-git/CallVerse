# Brief #1 — Project skeleton, shared LLM layer, placeholder data, Agent A

**Goal:** a user asks "Where is my order 4512?" and Agent A answers using real data from tools,
through the shared LLM layer, with every step traced.

**Why (for the presentation):** proves the core pattern of the whole center — an agent (M2) that reasons,
calls only the tools it is allowed to use, and answers from data instead of memory.

## 1. Skeleton
Create the folder layout from CLAUDE.md, plus `requirements.txt`, `.env.example`
(`GROQ_API_KEY=`, `OPENROUTER_API_KEY=`, `GOOGLE_API_KEY=`), `.gitignore` (include `.env`, `traces/`, `*.db`),
and `config.yaml`:
```yaml
sim_today: "2026-10-09"
providers:
  groq:       {base_url: "https://api.groq.com/openai/v1", key_env: GROQ_API_KEY}
  openrouter: {base_url: "https://openrouter.ai/api/v1",   key_env: OPENROUTER_API_KEY}
  google:     {base_url: "https://generativelanguage.googleapis.com/v1beta/openai/", key_env: GOOGLE_API_KEY}
models:
  agents:    # M2, tried in order (backup chain)
    - {provider: groq,       model: "openai/gpt-oss-120b"}
    - {provider: openrouter, model: "openai/gpt-oss-120b:free"}
  simulator: # M1, different family (used in task 4)
    - {provider: google,     model: "gemini-2.5-flash"}
```
Check the exact model IDs on each provider's model list and fix them if they differ.

## 2. Shared LLM layer — `callverse/llm.py`
- `chat(role_key, messages, tools=None) -> response message` using the `openai` Python SDK with `base_url`.
- Tries the models of `role_key` in order; on rate limit (HTTP 429) or connection error, moves to the next one.
- Logs provider, model, token usage and time to the trace.

## 3. Trace — `callverse/trace.py`
- `log(step, actor, data)` appends one JSON line to `traces/<run_id>.jsonl`.

## 4. Placeholder ShopNova data — `callverse/data/`
SQLite file created by `seed.py`, tables following the teammate's structure:
- `users(id, name, email, phone)`
- `products(id, name, price, stock)`
- `orders(id, user_id, items, total, paid, status, order_date, promised_date, delivered_date, carrier, tracking_number)`
- `refunds(id, order_id, amount, status)`
Seed: 5 users, 10 orders. Must include **order 4512**: user Sara (sara@example.com), total and paid 59.90 TND,
ordered 2026-09-28, promised 2026-10-03, not delivered, status "stuck at depot", no refund.
Also one delivered order and one order already refunded. Mark the data as AI-generated in a comment.

## 5. Tools — `callverse/tools/`
- `shopnova_tools.py`: `get_user(email|phone|user_id)`, `get_order(order_id)`, `get_tracking(order_id)`
  (tracking returns status + days late, computed from `sim_today`).
- Each tool has a JSON schema for tool calling.
- `registry.py`: allow-lists. `AGENT_A = ["get_user", "get_order", "get_tracking"]`.
  `run_tool(agent, name, args)` refuses and logs any tool not on the agent's list.

## 6. Agents — `callverse/agents/`
- `base_agent.py`: the tool-calling loop — send system prompt + messages + allowed tool schemas to `llm.chat`;
  if the model asks for tools, run them through the registry and send results back; stop at a final answer
  or after 5 steps. Trace every step.
- `agent_a.py`: system prompt for **Agent A – Status & Tracking**: answer only from tool results; never invent
  dates or statuses; if the user asks for money back, do not promise anything — reply that the request will be
  handed to the refund team and return `handover: "B"` in the result.

## 7. Demo and tests
- `run_demo.py "Hi, where is my order 4512?"` prints Agent A's answer and the trace file path.
- `tests/`: tools return the right data for 4512; a tool outside the allow-list is refused;
  the agent loop stops after 5 steps (use a fake LLM for this test, no API call).

## Done when
- The demo answers that order 4512 is stuck at the depot and 6 days late, using `get_order` and `get_tracking`
  (visible in the trace).
- Switching `models.agents` order in `config.yaml` changes the provider with no code change.
- All tests pass. Then explain every file in simple words.
