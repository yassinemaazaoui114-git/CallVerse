# T16 report — Agent B on its own Groq model list; Intake + A + SLM local

## 1. In plain words
Agent B, the refund agent, now has its own model setting. With the "local" switch on, the Intake helper, Agent A
and the reply writer run on this PC, while only Agent B uses the big Groq model. On the 24 practice messages this
scored **23/24** (19/24 when everything was local, T13f). All 4 refund cases that failed before now produce a real,
approved refund. There were no leaks and no wrong writes. Without any switch the system behaves exactly as before.

## 2. Done
- **Step 0 Git:** `main` = 0a0f461 (pushed by Yassine). Branch `feature/t16-agent-b-model`.
  Commits: 9659e42 (task file + NEXT.md IN PROGRESS) and the code commit.
- **`config.yaml`:**
  - New `models.agent_b`: Groq `openai/gpt-oss-120b` → `openai/gpt-oss-20b`, both `reasoning_effort: low`.
    **No Gemini.**
  - `agents_local` now carries the YAML anchor `&agents_local`, and `agent_b_local: *agents_local` reuses it.
    The local list is written once, so the two can't drift.
  - The comment says: T16, option A, temporary test setup, final setup decided after the M2 benchmark. It also
    explains the switches, including that `CALLVERSE_FORCE_AGENTS_MODEL` no longer affects B.
- **`callverse/agents/agent_b.py`:** `role_key = "agent_b"`, with a comment. Prompt and logic unchanged.
- **`callverse/agents/ask.py`:** the "ask Agent A" sub-call runs on `ASKER_ROLE_KEY = "agent_b"`. Only Agent B has
  `ask_agent` (allow-list). The role is set on that one `AgentA` instance; Agent A's class, code and prompt are
  unchanged, and its own turns keep `agents`.
- **`callverse/llm.py`: no change needed.** Its existing switch code builds the env names from the role, so
  `CALLVERSE_AGENT_B_SET=local` and `CALLVERSE_FORCE_AGENT_B_MODEL` work with no new code.
- **`scripts/run_live_check.py`:** `pause_seconds()` gives 5 s when any agent role (`agents` or `agent_b`) is on
  the default (API) set, and 0 s only when both are local.
- **Tests:**
  - New `tests/test_agent_b_model.py` (14 tests): B's turn asks `agent_b`; B → ask_agent → A asks `agent_b`
    (3 calls); `ask_agent` alone asks `agent_b`; A's own turn asks `agents`, and the `AgentA` class keeps
    `agents`; the switches (no switch / AGENTS local / both local / force B, and force AGENTS doesn't touch B);
    no Gemini in `agent_b` or `agent_b_local`; `agent_b_local == agents_local`; the pause rule in 4 cases.
  - Updated `tests/test_live.py::test_pause_between_messages_only_with_the_default_agents_set`. With only
    `CALLVERSE_AGENTS_SET=local` the pause is now 5 s, because B is still on Groq. Commented.
- **README:** a paragraph on the T16 switches next to the model chain.
- **Not touched:** prompts, agent logic, tools, Coordinator, rules, Intake, SLM.

## 3. Evidence
- **Tests: 346 / 346 pass** (332 + 14 new), 25.7 s.
- **Practice run** (`tests/dev/live_dev_messages.json`, 24 messages, strict checker, `CALLVERSE_AGENTS_SET=local`:
  A + Intake fallback on `cv-qwen3.5-4b`, B on Groq, SLM qwen2.5:1.5b). Trace
  `traces/run_20261029_103104_516641.jsonl`; results `out/t16/live_check_t16.json` and console `out/t16/run.log`
  (git-ignored). The T13f results file was backed up first to `out/t16/previous_t13f_live_check_backup.json`.

  | | T13f (all local) | **T16 (B on Groq)** |
  |---|---|---|
  | Score | 19/24 | **23/24** |
  | Failed | d05, d17, d18, d20, d24 | **d18** |
  | Crashes / leaks / wrong writes | 0 / 0 / 0 | **0 / 0 / 0** |
  | Reply source slm / slm_retry / template | 21 / 1 / 2 | **21 / 0 / 3** |
  | s per message avg / max | 14.5 / 29.0 | **10.0 / 36.1** (max = d17, Layer 3 case, 8 Groq calls) |

  - **B's proposals: 4, all approved** (0 sent back, 0 asked):
    - d05: refund 4512, 59.90, R-REF-03
    - d20: refund 4512, 59.90
    - d24: refund 4512, 59.90
    - d17: refund 4515, 378.00, through **Layer 3** (finance stub approved, R-ESC-01). Reply: "approved after a
      check by our finance team".
  - The other route-B messages ended correctly without a proposal: d08, d09, d13, d15, d16, d21 → info;
    d14 → ask_proof. d14 had one `agent_retry` (the existing "check the order id" retry, on Groq).
  - **d18 (only failure):** route A on the local model. The client asked to be notified, and Agent A gave the status
    but didn't call `propose_subscription` ("subscriptions 0 != 1"). This is the known small-model limit, as in
    T13c/T13f, and not part of T16.
  - Templates (3): d06 and d23 (off-topic / "?", same as T13f), and d19 (the "order number?" reply). All 3 passed.
- **`llm_call` lines by role:**

  | Role | Provider / model | Calls | Tokens |
  |---|---|---|---|
  | `agent_b` (B + its sub-call to A) | groq / gpt-oss-120b | 55 | 53,953 |
  | `agents` (A + Intake fallback) | ollama / cv-qwen3.5-4b | 25 | 29,430 (with phi4) |
  | `agents` | ollama / cv-phi4-mini | 1 (the quota check before the run) | |
  | `slm` | ollama / qwen2.5:1.5b | 28 | 15,711 |

  So A + the Intake fallback were **ollama only**, and B + its sub-call were **groq only**. **0 google.**
  0 fallbacks to gpt-oss-20b. 6 short `llm_wait` (2–8 s, Groq per-minute limit), all on `agent_b`.
- **Groq tokens:** **53,953** for the run. 11 messages used Groq (the route-B ones): average 2,248 per message
  over all 24, about 4,900 per Groq message, max 8,715 (d20). Per B turn (`scripts/token_report.py`): 12 turns,
  average 4,496 tokens.

## 4. Problems
- **RAM was not watched during the run (my mistake).** My RAM logger got a POSIX path that PowerShell could not
  write to, so it logged nothing, and the "low RAM" alert could not fire. Free RAM was 1.3 GB just before the start
  (browsers closed) and 2.4 GB right after. Nothing crashed, and the run finished normally (exit 0).
- **The quota check before the run tests only the `agents` list** (`scripts/quota_check.py`). With
  `CALLVERSE_AGENTS_SET=local` it therefore checks the two local models, not B's Groq models. If Groq's daily
  limit is already gone, the run would only stop at the first B message, through the existing T10b stop that
  aborts without scoring. That's safe, but late. `quota_check.py` was not in this task's file list.
- **Groq daily quota for the demo:** the traces from T10 show **200,000 tokens per day** for gpt-oss-120b. One
  practice run used ~54k, so about 3–4 full runs per day, or ~40 refund conversations (~4,900 tokens each). It's
  fine for a demo day if we don't run benchmarks the same day; gpt-oss-20b (its own quota) is the backup.
- The run shows the effect of the model on B, on 24 practice messages only (no held-out set), and from one run.

## 5. Questions for the Brain
1. Should `scripts/quota_check.py` also check the `agent_b` list (so a used-up Groq quota stops the run before
   message 1)? It's a small change; I'd do it in T14 or as a mini-task.
2. Should d18 (A not proposing a subscription on the local model) get its own fix, or wait for the M2 benchmark,
   as for the refunds?

## 6. Next step
Review and merge `feature/t16-agent-b-model`. Then T17 (ShopNova chat) can use `CALLVERSE_AGENTS_SET=local` and show
real refunds, with B on Groq.

**Answers to the task's two questions.** Does the refund path work now? Yes: all 4 refund cases (d05, d17, d20,
d24) got an approved refund, including the Layer 3 case 4515, with 0 wrong writes. Is the Groq daily quota a risk
for the demo? A moderate one: ~54k of 200k tokens per full run, so we must avoid long test runs on the demo day
(or keep gpt-oss-20b's own quota as the backup).
