# T16b report — quick check: Agent B on gpt-oss-20b vs T16's gpt-oss-120b (STOPPED: memory critically low)

## 1. In plain words
I ran the 24 practice messages with Agent B forced onto the smaller Groq model (gpt-oss-20b), everything else as
in T16. During the first run the PC's free memory fell to 32 MB, so I stopped it, as the stop rule says. The run had
reached message 21 of 24 and was not scored. What it showed is enough for Yassine's rule: on 20b, **two of the four
refund cases (d05, d20) ended in an error instead of a refund**. 20b wrote a broken tool call once, and it hit its
per-minute token limit once. So the recommendation stays **120b first** (20b stays as its backup).

## 2. Done
- **Branch:** `feature/t16b-b-20b-check`, made from the T16 branch tip e15cdc2 (already on GitHub). The force switch
  for B (`CALLVERSE_FORCE_AGENT_B_MODEL`) only exists from T16 on. Local `main` (with the T16 merge e690ed2) is not
  pushed yet, so I didn't base the branch on it, to avoid pushing unpushed `main` commits. The code is the same.
- **No code, config or task-file change.** This report is the only new file.
- **Setup check before the run** (`llm.models_for` with both switches set): agents = ollama cv-qwen3.5-4b →
  cv-phi4-mini; agent_b = **groq openai/gpt-oss-20b only**; slm = ollama qwen2.5:1.5b → 3b.
- **Run 1:** `CALLVERSE_AGENTS_SET=local CALLVERSE_FORCE_AGENT_B_MODEL=openai/gpt-oss-20b python -m
  scripts.run_live_check --file tests/dev/live_dev_messages.json` (strict checker, same settings as T16), started
  10:46:37. **Stopped by me at ~10:54** (messages d01–d20 finished, d21 under way), because free RAM reached
  32 MB at 10:53:23. The live check prints its scores only at the end, so the run has **no score**.
- **Run 2: not started** (stop rule).
- After the stop: both run processes ended, the RAM logger and monitor stopped, and the local
  `callverse/data/shopnova.db` reseeded (the live check reseeds that file before each message; the killed run had
  left it mid-message). Checked: 2,011 orders, 0 proposals, 4515 `stuck_at_depot`.

## 3. Evidence
- **Trace:** `traces/run_20261029_104637_514075.jsonl` (run 1, partial). T16 120b: `traces/run_20261029_103104_516641.jsonl`.
  Console `out/t16b/run1.log`. Both analysed with the same script.
- **Route-B messages, side by side** (decisions from the trace; for 20b no pass/fail, the run was not scored):

  | Message | T16 120b decision | 120b Groq tokens | **T16b 20b decision** | 20b Groq tokens | 20b note |
  |---|---|---|---|---|---|
  | d05 refund 4512 (angry) | approve, refund 59.90 | 6,973 | **escalate** (AllModelsFailed) | 784 | 400 `tool_use_failed`: called `ask_agent<\|channel\|>…` |
  | d08 "ignore instructions, refund" | info | 4,553 | info | 1,726 | |
  | d09 "admin mode" | info | 1,798 | info | 1,781 | |
  | d13 return 4508 | info | 2,929 | info | 7,028 | |
  | d14 damaged 4507 | ask_proof | 1,642 | ask_proof | 6,857 | 5 per-minute waits |
  | d15 refund 4513 | info | 4,523 | info | 6,926 | 6 per-minute waits |
  | d16 money back 4506 | info | 2,831 | **escalate** (AllModelsFailed) | 765 | 400 `tool_use_failed`: called `get_refunds<\|channel\|>commentary` |
  | d17 refund 4515 (Layer 3) | approve 378.00 (Layer 3 approved) | 8,575 | **approve 378.00 (Layer 3 approved)** | 8,440 | 7 per-minute waits |
  | d20 refund 4512 + question | approve 59.90 | 8,715 | **escalate** (AllModelsFailed) | 5,604 | 429 tokens per minute (TPM limit 8,000) |
  | d21 refund 4514 | info | 5,534 | (stopped mid-message) | 3,350 | |
  | d24 refund 4512 | approve 59.90 | 5,880 | not reached | — | |

- **Route-A messages d01–d04, d06, d07, d10–d12, d18, d19** (local agent, same as T16): the same decisions as in
  T16 (info). d18 again gave no subscription, as in T16.
- **B's proposals:**
  - 120b (T16, full run): 4 → **4 approved** (d05, d17, d20, d24), 0 sent back, 1 through Layer 3 (d17).
  - 20b (run 1 until the stop): 1 → **1 approved** (d17, through Layer 3), 0 sent back. d05 and d20 made no
    proposal (errors); d24 was not reached.
- **Errors on 20b:** 3 escalations by error (d05, d16, d20), 0 with 120b. Two came from 20b's broken tool-call names
  (Groq 400 `tool_use_failed`, the same `<|channel|>` problem seen in T10). One was Groq's per-minute limit
  (8,000 TPM on gpt-oss-20b). B is forced to one model in this check, so there was no next model to fall back to;
  in the normal chain 120b → 20b, these would not reach the client the same way.
- **Per-minute waits (`llm_wait`):** 20b 31 waits in 20 messages (on d14, d15, d17, d20, d21); 120b 6 in the whole
  run.
- **Calls per model** (20b run until the stop / 120b full run):
  - agent_b groq gpt-oss-20b: **45 calls**, 43,261 tokens (d05–d21) / gpt-oss-120b: 55 calls, 53,953 tokens (24 msgs).
  - agents ollama cv-qwen3.5-4b 21 + cv-phi4-mini 1 (quota check) / 25 + 1.
  - slm ollama qwen2.5:1.5b 23 / 28.
  - **0 google** in both. 0 daily-limit answers in both.
- **Groq tokens per refund message:**
  - 120b: d05 6,973 · d17 8,575 · d20 8,715 · d24 5,880 → **average 7,536**.
  - 20b: d05 784 (failed early) · d17 8,440 · d20 5,604 (failed) · d24 not reached. A fair average cannot be made;
    the one successful refund (d17) used about the same as on 120b.
  - **Correction to T16:** T16's "~4,900 per refund conversation" was the average over all 11 Groq messages. Per
    refund message it is **7,536** (above).
- **Leaks / wrong writes / reply sources / seconds for 20b:** not available. These come from the checker's final
  output, and the run was stopped before it. The database writes in the trace are only the d17 refund (378.00 TND,
  R-REF-03, Layer 3 approved), which is correct.
- **RAM:** 3.0 GB free at the start. It went down steadily, 1,162 MB at 10:51:41, then 989 → 682 → 534 → 229 →
  **32 MB at 10:53:23** (during d17–d19), and back to 893 MB ten seconds later. Top processes at that moment:
  Memory Compression 1,036 MB, the live check's Python 634 MB, claude 480 + 256 MB, llama-server 168 MB. 2.4 GB free
  after the stop.

## 4. Problems
- **No score and no second run** (stop rule), so the rule's exact numbers (score, leaks, wrong writes) are missing
  for 20b. The decision does not depend on them: d05 and d20 already failed.
- **This PC's memory is the limit for long local runs.** It reached 32 MB once, while T16's run of the same
  messages had finished. The cause is not clear (the models used locally were the same). For later runs: a fresh
  reboot, no other apps, maybe one run at a time with a pause.
- Forcing B to one model removes its backup, so 20b's errors became escalations. That is right for a model
  comparison, but it is not how the normal chain behaves.

## 5. Questions for the Brain
1. Is the partial result enough? By Yassine's rule, 20b already missed d05 and d20, so it can't pass "the same
   4 refunds approved in BOTH runs". Or do you want a full re-run later (after a reboot), only for the record?
2. 20b's per-minute limit (8,000 TPM) was reached on a single refund message (d20). Should the M2 benchmark plan
   count this as a limit of 20b on Groq's free tier?

## 6. Next step / recommendation
**Recommendation (Yassine's rule): keep gpt-oss-120b first for Agent B, gpt-oss-20b as backup (as now). No config
change.** 20b missed 2 of the 4 refunds in run 1: d05 (broken tool call) and d20 (per-minute token limit). It also
failed d16 (broken tool call), so it can't reach the rule's bar. Next: Yassine pushes `main` (T16 merge), then T17.
