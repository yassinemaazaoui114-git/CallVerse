# CallVerse integration — platform + Intake + router + voice (branch `integration/platform-voice`)

One workflow for every channel. Each stage runs the team's **real** module when it exists, and every reply
says, stage by stage, what ran (`steps` in the API, the panel "How CallVerse handled this" in the website).

## 1. Flow and status (2026-10-20, on `main` 22aa220)

```
Customer: text, or voice (browser microphone)
   ▼
Speech-to-text  ............ REAL     Groq Whisper (key) → faster-whisper in the server     (Semah, V01)
   ▼
Identity gate  ............. REAL     email of the order, checked with the read tools        (Semah, V01)
   ▼
Intake  .................... REAL     reasons (M3), emotion + sentiment (M4), priority       (Yassine, T03, main)
   ▼
Router  .................... REAL     rules in config.yaml queues.routes                     (Yassine, T04, main)
   ▼
Agent A Status & Tracking .. REAL     with GROQ_API_KEY; MOCK (labelled demo text) without  (main)
Agent B Payment & Refund ... NOT BUILT  the handover is recorded (T04 behaviour), nothing decided
   ▼
Coordinator  ............... NOT BUILT  no agent proposes actions today; any proposal is WITHHELD (fail closed)
   ▼
Response writer (SLM) ...... NOT BUILT  the reply text is used as is                         (T05, Dali)
   ▼
Text-to-speech  ............ REAL     Piper voice on the server                              (Semah, V01)
   ▼
Customer: text + audio (+ replay), same conversation over many turns
```

Platform underneath (Dali, P01–P04 on `main`; P05 from `platform`):
- ShopNova database: 131 orders, flags, safety nets.
- Policies + `check_condition`, the Layer 3 stub, Coordinator-only write functions.
- P05: the local server and admin dashboard.

## 2. How the team's modules plug in (no change needed here)

`callverse/integration/components.py` looks each component up **at call time**, by the interface its task file defines:

| Component | Module | Interface | Until it exists |
|---|---|---|---|
| Agent B | `callverse/agents/agent_b.py` | `class AgentB(BaseAgent)` | handover recorded: "Your request is passed to our refund team." |
| Coordinator | `callverse/coordinator/coordinator.py` | `review(proposal) -> decision` | proposals are never executed (customer told a colleague will review) |
| SLM (T05) | `callverse/slm/writer.py` | `write_reply(decision, history=None) -> {reply, ...}` | reply text used as is |

The T04 router is merged and imported directly (`callverse/integration/workflow.py`). A module that exists but
fails to import is **not** hidden: the error is raised (tested).

## 3. REAL and MOCK
- **REAL** (`GROQ_API_KEY` set): Intake (with its M2 fallback for unclear messages), the T04 router and Agent A all run.
- **MOCK** (no key): Intake and the router still run for real on the real data; only the LLM agent is replaced
  by a demo text that says so. The identity gate applies in both modes, because Intake reads the order facts.
- A MOCK reply never contains order facts, and REAL never falls back to MOCK: an LLM outage gives
  "temporarily unavailable".

## 4. Two apps, two audiences
| App | Start | Listens on | Who |
|---|---|---|---|
| Customer website (`callverse/web`) | `python -m scripts.run_web` | 127.0.0.1:8080 (Docker/cloud: 0.0.0.0:7860) | customers, public |
| Platform server + admin dashboard (`callverse/server`, P05) | `python scripts/run_platform_server.py` | **127.0.0.1:8000 only** | the team |

The customer website has no admin, write or dashboard route (tested: `/admin/reset`, `/summary`, `/orders/…` → 404).
Only the customer website goes into the Docker image's start command.

## 5. Not integrated, on purpose
- **RAG / `search_policy`:** out of scope. The policy files and `check_condition` are in place, for the Coordinator.
- **Queue manager (T04 `queue.py`):** one conversation is answered at once, so there is no queue in the channel.
- **T04 `callverse/pipeline.py`:** the website uses its own workflow (it adds the identity gate, conversation
  history and per-stage status) with the same Intake, router and Agent A; the two can be merged into one later.
- **Agents C–F, Simulator, notifier:** not built.
