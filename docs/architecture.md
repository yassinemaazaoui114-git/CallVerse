# CallVerse prototype — architecture (one page)

## 1. Flow

```
Client Simulator ──► Intake ──► Queues ──► Agent A / Agent B ──► Coordinator ──► SLM ──► reply
   (M1, API)        (M3, M4)    (rules)         (M2, API)            (rules)        (M5, local)
```

| Step | What it does | Why it is here | Status |
|---|---|---|---|
| Client Simulator | Plays a ShopNova client and writes messages | Test the system without real clients | later |
| Intake | Understands the message (reasons, emotion, priority from the facts) | Cheap local models, so the big LLM is not used for sorting; a fixed pipeline, not an agent | **runs** (T03) |
| Queues | Sends the request to Agent A or B; serves high before medium before low | Simple rules are predictable and easy to check | **runs** (T04; B = recorded handover) |
| Agent A | Status & Tracking: "where is my order?" | One narrow job per agent, with its own tools | **runs** |
| Agent B | Payment & Refund: proposes refunds | Money decisions are kept apart from tracking | Brief #2 |
| Coordinator | Checks each proposal and executes it | Rules, no LLM: the final decision is never a guess | Brief #2 |
| SLM | Writes the final reply in a friendly tone | A small local model is enough to rephrase checked facts | later |

## 2. Model map (switchable in `config.yaml` only)

| Id | Role | Starting model | Where it runs |
|---|---|---|---|
| M1 | Client Simulator | Gemini Flash (a **different family** than M2, so the test client is not the same model as the agents) | API |
| M2 | Shared LLM of all agents | `openai/gpt-oss-120b` on Groq, backup `openai/gpt-oss-20b` | API (OpenAI-compatible) |
| M3 | Embeddings (policy search, intake) | `BAAI/bge-small-en-v1.5` | local, CPU |
| M4 | Emotion / sentiment classifiers | ready-made models, chosen later | local, CPU |
| M5 | Reply writer (SLM) | small 1–4B model via Ollama, chosen later | local (max 6 GB VRAM) |

All API models go through **one shared layer**, `callverse/llm.py`. If a model fails on the provider's side,
the next model in the list in `config.yaml` is tried.

## 3. The four safety rules

1. **Agents only propose.** Agents may use *read* tools (look up an order, a user, a policy).
   An *action* tool (e.g. refund) only creates a **proposal**; it changes no data.
2. **Only the Coordinator executes.** It re-reads the real data (it never trusts the agent's facts),
   checks the policy rule and the user's confirmation, then approves, sends back, asks, or escalates.
   Only an approved proposal writes to the database.
3. **Allow-list per agent, enforced in code.** `callverse/tools/registry.py` holds each agent's list.
   The model only sees its allowed tools, and any other call is refused and logged.
4. **Every step is traced.** `callverse/trace.py` writes one JSON line per step in `traces/`:
   who acted, the input, the output, tool calls and the time. Any answer can be replayed and explained.

Also: **facts come from tools, never from model memory**, and the demo uses a fixed date
(`sim_today: 2026-10-09`) so runs are reproducible.
