# T13c report — Stricter practice checker, qwen3.5 settings tests, "claims a proposal" safety net (+ 3 small fixes)

## 1. In plain words
The practice test is now honest: the 5 messages where a correct agent must refund or set up a notification
fail if nothing is written. With that stricter test, the local model qwen3.5:4b scores **20–21 out of 24**
(not 24/24 as before). Its 3 or 4 misses are always the same mistake: it *says* "I can propose a refund" but
never presses the button. Changing two model settings helped by at most one message. The new safety net (ask
the agent once more when it claims a proposal without making one) **did not help in the part we could
measure**, and it fired mostly on false alarms like "no refund proposal is needed". The last run (run 4) was
cut off after 20 of 24 messages because the PC ran out of memory, so it is **not scored**.

## 2. Done
- Git: `git fetch`; `feature/t13c-checker` from `origin/feature/t13b-context` (`fd2d041`). First commit `e0db18f` =
  this task file + `tasks/NEXT.md` (the Brain's version, with Status set to IN PROGRESS). Ollama answered (0.40.12).
- **Fix 1:** `ollama rm cv-qwen3.5-4b-ctx16384` → gone. `cv-qwen3.5-4b` still `num_ctx 8192` (presence_penalty 1.5).
- **Fix 2:** `config.yaml` comment above `agents_local`: "~6,000 tokens per turn" replaced by the T13b fact (largest
  single prompt ~2,300 tokens; ~6,000 was the total of all calls of one turn). Comment only; settings unchanged.
- **Fix 3:** `callverse/llm.py` `models_for()`: with `CALLVERSE_AGENTS_SET=local`, `CALLVERSE_FORCE_AGENTS_MODEL` accepts
  any Ollama name not listed in `models.agents_local`, with the settings of the first local entry. An API model of
  the default list is still refused there (the local set can never call an API). Default set: unchanged (a forced
  name must be listed). 2 new tests in `tests/test_agents_set.py` (unlisted name accepted in local / refused in default).
- **Stricter checker (L2)**, `tests/dev/live_dev_messages.json` only, 5 lines changed:
  d05 `refund_rows: 1, refund_amount: 59.9` (+ `refund_order_if_any: 4512`, `reply_not_contains` kept);
  d17 `refund_rows: 1, refund_amount: 378.0` (`if_refund_reply_contains: finance` kept);
  d18 `subscriptions: 1` (`subscription_event_if_any`, `refund_rows: 0`, `if_subscription_reply_contains` kept);
  d20 `refund_rows: 1, refund_amount: 59.9, refund_order_if_any: 4512`; d24 `refund_rows: 1, refund_amount: 59.9`.
  All keys already existed in `scripts/run_live_check.py`: no checker code change. No other message changed.
  These expectations match what a correct agent does: **gpt-oss-120b passed them in T10 (24/24 with 4 refunds +
  1 subscription: d05, d17, d20, d24 refunds; d18 subscription).**
- **Safety net (L3)**, `callverse/pipeline.py`: `claims_proposal()` (short phrase list in code:
  `propose/proposed/proposes/proposing/proposal`, `sent for checking`, `submitted … for review`). In
  `run_agent_with_coordinator`, after the T10 retry: claim **and** no `propose_refund`/`propose_subscription` call
  **and** no proposal → the same agent runs **once** more with a short note. Traced as `proposal_claim_retry`.
  The net writes nothing; the Coordinator checks every proposal as before. 5 offline tests (fake LLM) in the new
  file `tests/test_proposal_claim_retry.py`: claim + no tool → 1 retry; at most 1 retry even if the 2nd answer claims
  again; claim + tool call → no retry; no claim → no retry; the phrase list.
- **5 s pause (R3)**, `scripts/run_live_check.py`: `pause_seconds()` = 5 with the default (Groq) agents set, 0 with
  `CALLVERSE_AGENTS_SET=local`; the pause is between messages and not counted in a message's seconds.
  1 offline test in `tests/test_live.py`. No Groq run.
- **How the settings were set (run only, `config.yaml` unchanged):**
  - Run 1: `CALLVERSE_FORCE_AGENTS_MODEL=cv-qwen3.5-4b` (today: presence_penalty 1.5 from qwen's Modelfile defaults;
    temperature 0, seed 42, reasoning_effort none from `config.yaml`).
  - Run 2: temporary Ollama copy **`cv-qwen3.5-4b-pp0`** (Modelfile `FROM qwen3.5:4b`, `PARAMETER num_ctx 8192`,
    `PARAMETER presence_penalty 0`), forced by name thanks to fix 3, so it gets temperature 0, seed 42,
    reasoning_effort none from the first local entry. presence_penalty is not sent in the request, so the copy's 0 applies.
  - Run 3: same copy + **temperature 0.3**. The request always sends the config's temperature (it overrides a Modelfile
    value), so a one-off runner script in my scratch folder (`run_check_temp.py`, not committed) set
    `agents_local[0].temperature = 0.3` **in memory** and then called `run_live_check.main()`.
  - Run 4: same as run 3, with the safety net.
- Order of work: runs 1–3 ran **before** the safety net was added to the code (so "without the net" is exact, no
  on/off switch needed); the net was committed (`6a81983`) and then run 4 started.
- No change to agent prompts, the Coordinator, policies, the SLM, Intake or `tests/data/*`. `.env` not read.

## 3. Evidence
- **Offline tests: 315/315 passed** (307 + 2 force + 1 pause + 5 safety net).
- `cv-qwen3.5-4b`: `num_ctx 8192`; `cv-qwen3.5-4b-ctx16384`: gone (`ollama list`).
- **API calls: 0.** All `llm_call` lines of the 4 traces are `ollama` (0 groq, 0 google): run 1 102, run 2 106,
  run 3 104, run 4 (partial) 114.

| Run | presence_penalty | temperature | Safety net | x/24 (strict) | Refunds / subscriptions made (of 4 / 1) | Crashes | Leaks | Wrong writes | Avg / max s per msg | Safety-net retries (how many helped) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1.5 (today) | 0 | no | **20/24** | 1 / 0 | 0 | 0 | 0 | 25.1 / 47.5 | – |
| 2 | 0 | 0 | no | **20/24** | 1 / 0 | 0 | 0 | 0 | 26.3 / 39.3 | – |
| 3 | 0 | 0.3 | no | **21/24** | 2 / 0 | 0 | 0 | 0 | 25.3 / 38.6 | – |
| 4 | 0 | 0.3 | yes | **not scored** (stopped after 20/24: the PC ran out of memory) | (info: 2 / 0 in the 20 done) | (info: 0) | – | – | – | (info: 6 retries, 0 helped) |

**Which action messages made the right write**

| Run | d05 refund 59.9 | d17 refund 378.0 | d18 subscription | d20 refund 59.9 | d24 refund 59.9 |
|---|---|---|---|---|---|
| 1 | no | no | no | **yes** | no |
| 2 | **yes** | no | no | no | no |
| 3 | **yes** | **yes** | no | no | no |
| 4 (info, partial) | **yes** (first try) | **yes** (first try) | no | no (retry did not help) | not reached |

**FAILs** (all 4 + 4 + 3 are on the action messages; the other 19 messages passed in every run). Cause: **model** in all.
- Run 1: d05 `refund rows 0 != 1; refund amounts [] != [59.9]` (says "I can propose one under rule R-REF-03 …
  Please confirm …", no tool call); d17 `refund rows 0 != 1; refund amounts [] != [378.0]` (same, "I can propose a
  full refund"); d18 `subscriptions 0 != 1` (asks "Would you like to be notified when it arrives?" instead of
  calling `propose_subscription`); d24 `refund rows 0 != 1; refund amounts [] != [59.9]` ("The proposal has been
  sent for checking", no tool call).
- Run 2: d17, d20, d24 `refund rows 0 != 1 …` ("I can propose …", "I will now send the refund proposal", "I propose
  a refund …", no tool call); d18 `subscriptions 0 != 1` (asks for confirmation).
- Run 3: d20, d24 `refund rows 0 != 1 …` ("I am sending a refund proposal", "I propose a refund of 59.9", no tool
  call); d18 `subscriptions 0 != 1` (asks for confirmation).
- d18 failed in all runs the same way. Its text has no claim words, so the safety net cannot catch it.
- **T13's "never proposes" (re-check on Ollama 0.40.12, run 1 = today's settings):** no longer true. It proposed
  once (d20) out of the 5 action messages. In runs 2–3 it proposed 1 and 2 times.

**Run 4 (information only, not scored)**: trace `traces/run_20261028_150050_334441.jsonl`, d01–d20 finished
(d21–d24 not reached), 0 crashes, 0 T10 retries, 114 `llm_call` (all ollama).
- 6 `proposal_claim_retry`, all Agent B: **d08, d09, d13, d15, d16** are **false alarms**. The first answer
  *denies* a proposal, e.g. d08 "No refund proposal under R-DEL-01 or R-DEL-02", d09 "no new proposal is needed
  since the refund is complete", d16 "No further refund proposal is needed". After the retry: no proposal,
  decision `info` (correct, as before). **d20** is a real claim ("I can propose a full refund under rule
  R-REF-03"). After the retry: still no proposal, decision `info`.
- **Ended with a correct proposal: d05** (refund 4512, 59.9, R-REF-03 → approve) and **d17** (refund 4515, 378.0,
  R-REF-03 → approve). Both on the **first** try, without a retry. **Retries that helped: 0 of 6.**

- Traces: run 1 `traces/run_20261028_112928_739365.jsonl`, run 2 `traces/run_20261028_143623_961150.jsonl`,
  run 3 `traces/run_20261028_144802_368651.jsonl`, run 4 `traces/run_20261028_150050_334441.jsonl`.
  Results (git-ignored): `out/t13c/run1.json` … `run3.json`, console output `out/t13c/run*.txt`.

**Recommendation (one sentence):** I would **not** change `models.agents_local` yet. The three settings differ by
one message (20–21/24, one run each), and temperature 0.3 makes runs non-repeatable. If one must be picked, the
task's rule picks **presence_penalty 0 + temperature 0.3** (run 3). The safety net is **not worth keeping in this
form**: 5 of its 6 retries were false alarms on "no proposal" sentences, the one real claim was not fixed, and
each retry costs a full extra agent run.

## 4. Problems
1. **Run 2 was interrupted once and restarted.** The first try started at 11:40 (right after run 1) and stopped
   during start-up, before any message, when the previous Claude Code session ended. Its output is kept as
   `out/t13c/run2_interrupted.txt`. Run 2 was redone from the start at 14:36 with exactly the same settings, then run 3.
   Run 1 (11:29–11:40) was kept and not redone.
2. **Run 4 is not scored.** Claude Code stopped it at about 15:01 after 20 of 24 messages because the PC was
   critically low on memory. It was not redone (Yassine's decision). The killed run left an untracked
   `callverse/data/shopnova.db-journal` (SQLite's undo file; the database is re-seeded for every message). Not committed.
3. **The safety net's phrase list is too wide.** "propose / proposal" also matches *negative* sentences ("No refund
   proposal …", "no new proposal is needed"). In the 20 messages of run 4, 5 of 6 retries were false alarms. They did
   no harm (nothing written, same correct `info`), but each one is a full extra agent run.
4. One run per setting: a difference of one message (20 vs 21) is within what a re-run could change, especially at
   temperature 0.3.
5. The temporary Ollama copy `cv-qwen3.5-4b-pp0` is **still installed** (kept for a possible later run; nothing in
   the repo uses it). Remove it with `ollama rm cv-qwen3.5-4b-pp0` when not needed.
6. Time: about 1 h 30 min of work within the 2.5 h time box (not counting the gap between the two sessions).

## 5. Questions for the Brain
1. Safety net: (a) remove it, (b) keep it but only count a claim when no negation is near ("no", "not", "needed")
   or only for the clear forms ("I can propose", "sent for checking", "submitted"), or (c) keep it as is? It never
   writes anything, so it is safe, but in its current form it costs time and did not help.
2. `models.agents_local` settings: keep today's (presence_penalty 1.5, temperature 0), or switch to presence_penalty 0
   (with temperature 0 for repeatability, or 0.3 as the rule picked)? A repeat of runs 2–3 would make this firmer.
3. d18 (subscription): the model always asks "Would you like to be notified?" instead of proposing. Is that a model
   limit to accept for the local test model, or worth a later look?
4. Redo run 4 later (about 12 minutes, with enough free memory), if the safety net is kept?

## 6. Next step
Brain review. Then decide on the safety net (question 1), and only after that, if needed, one complete run 4 of the
kept version. The 315 offline tests and the strict practice set are ready for the next model comparison.
