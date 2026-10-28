# T13f report — SLM switched to qwen2.5:1.5b, copied labels rejected, practice re-run, both models loaded

## 1. In plain words
The reply writer now uses the smaller qwen2.5:1.5b. The bigger qwen2.5:3b stays only as a backup. The reply check now
also rejects instruction labels a model copies into a reply ("Length: …", "The next step is: …"). It wrongly
rejected 0 of the 24 practice replies. On the 24 practice messages the system scored 19/24 (T13c run 1: 20/24) with
0 leaks and 0 wrong writes, and it was much faster: 14.5 s per message instead of 25.1 s. The speed comes from a
side effect: the small SLM now fits on the GPU next to the agent model, so Ollama keeps **both loaded**, even with
its normal settings. The one message lost (d20) is an agent problem, not a reply problem: with both models loaded,
the agent's answers come out slightly different, and on d20 it described a refund instead of proposing one.

## 2. Done
- **Step 0:** `origin/feature/t13e-small-slm` merged into local `main` with `--no-ff`: **`f7e3414`**, no conflict.
  Tests on `main`: **318/318**. `main` **not pushed**.
- **Step 1:** branch `feature/t13f-slm-switch` from that `main`. First commit `193a0da` (task file, NEXT.md).
- **Step 2, `config.yaml` → `models.slm`:** first `qwen2.5:1.5b` (temperature 0, seed 42), then `qwen2.5:3b` (same
  settings) as the backup, used only if 1.5b is missing or unreachable (the normal `llm.py` fallback chain).
  The comment now gives the T13e result, ~1 GB less, Apache 2.0.
- **Step 3, `config.yaml` → `slm.forbidden`:** 3 new entries, keyword `instruction-label` (never in a decision):
  - `\b(?:tone|length|style|formality|emotion|outcome|decision|facts)\s*:` (labels with a colon)
  - `\bnext step is\s*:|\b(?:next_step|must_say|order_number)\b` (the copied "next step" line, the prompt's JSON keys)
  - `\bat most \d+ words\b|\b\d+ (?:or|to) \d+ sentences\b` (the copied length instruction)
  
  No code change. **7 new offline tests** in `tests/test_slm.py`: 6 copied-label replies fail; normal replies and
  the templates of all 7 outcomes still pass.
  Commit `T13f: SLM -> qwen2.5:1.5b …`.
- **Step 4:** practice re-run, once (24 messages, `CALLVERSE_AGENTS_SET=local`,
  `CALLVERSE_FORCE_AGENTS_MODEL=cv-qwen3.5-4b`, as in T13c run 1). Before it, Yassine closed Brave and Notion
  (free RAM 1.6 → 2.9 GB).
- **Step 5:** I stopped the Ollama tray app and ran `ollama serve` myself with **`OLLAMA_MAX_LOADED_MODELS=2`,
  `OLLAMA_KEEP_ALIVE=30m`**, both confirmed in the server log. I ran d05, d20, d24 from the temporary file
  `out/t13f/refund_messages.json` (copied unchanged) with a sampler (`ollama ps` + `nvidia-smi` every ~1 s).
  - **Extra control run (not asked, 3 messages, local, ~2 min):** the same 3 messages with
    `OLLAMA_MAX_LOADED_MODELS=1` (agent alone, as in T13b setup A, keep-alive default 5m). It shows whether loading
    both models changes the agent.
  - **Restored:** stopped my server and started the tray app again (`ollama app.exe`). Its log shows the normal
    values `OLLAMA_MAX_LOADED_MODELS:0` (= automatic) and `OLLAMA_KEEP_ALIVE:5m0s`. The API answers (0.40.12),
    no model is loaded. No Ollama environment variable is set for the user or the machine (checked before and after).

## 3. Evidence

### Tests
- `main` after the merge: **318/318** passed.
- Branch after the config change and new tests: **325/325** passed (318 + 7).

### Label check on old replies (offline)
The 70 stored T13e practice replies (5 models × 14) were re-checked with the new entries:
- **2 more caught**: gemma3:1b s06 (`order_number`) and llama3.2:1b d03 ("The next step is:").
- **0 changed** among the 28 qwen2.5 and 14 qwen3 replies.

In the practice re-run below the new labels rejected **0** replies.

### Practice re-run (24 dev messages) vs T13c run 1
| | T13c run 1 (SLM qwen2.5:3b) | **T13f (SLM qwen2.5:1.5b)** |
|---|---|---|
| Score (strict checker) | 20/24 | **19/24** |
| Failed | d05, d17, d18, d24 | d05, d17, d18, **d20**, d24 |
| Crashes / leaks / wrong writes | 0 / 0 / 0 | **0 / 0 / 0** |
| Reply source slm / slm_retry / template | 20 / 4 / 0 | **21 / 1 / 2** |
| s per message avg / max | 25.1 / 47.5 | **14.5 / 29.0** |
| SLM call avg / max | 6.53 / 8.04 s | **2.43 / 2.61 s** |
| Both models loaded during the run | no (3b + agent did not fit) | **yes** (server log: "fits alongside existing models", `loaded runners count=2`, then no reload) |

- **All 5 failures are agent failures, none is an SLM failure.**
  - d05, d17, d20, d24: the agent wrote "I can propose one under rule R-REF-03 … sent for checking" as text instead
    of calling `propose_refund`, so the Coordinator answered `info`.
  - d18: the known small-model limit (T13c).
- **d20 is the only change.** Agent A's answer for order 4510 differs with the same prompt (1,261 tokens):
  - one model at a time: "…promised for delivery on October 10, 2026, so it is not late yet…"
  - both loaded: "…will be delivered on 2026-10-10. It is not late yet…"
  
  After that, agent B's turn differs and B does not propose. See step 5: this repeats.
- **Template fallbacks (2):** d06 "weather in Tunis" and d23 "?". Twice each, qwen2.5:1.5b left out the must_say
  sentence "I can help with your ShopNova orders: delivery, refunds, returns and damaged items." The template
  includes it, and both replies passed.
- **Retry (1):** d02 "My package never came": the first reply contained **1234**, the number from the system
  prompt's own example ("written as \"order 1234\""). Caught by the number check; the retry passed.
- Trace `traces/run_20261028_195656_044678.jsonl`. Results `out/live_check_live_dev_messages.json`, console
  `out/t13f/practice_run.txt` (git-ignored). The previous results file was backed up to
  `out/t13f/previous_live_check_backup.json`.

### Both models loaded (step 5) and the agent-alone control run
| Ollama setting | Both models listed (samples) | % GPU / % CPU | GPU memory peak | Evictions | Model loads | d05 / d20 / d24 (strict) | s per message avg / max |
|---|---|---|---|---|---|---|---|
| **MAX_LOADED_MODELS=2, KEEP_ALIVE=30m** | **yes: 66 of 94** (the other 28 come before the agent's first load: 20 nothing loaded during start-up, 8 only the SLM after its warm-up; once both were loaded they stayed) | agent 3.3 GB 100% GPU · SLM 1.2 GB 100% GPU | **5,092 MiB** of 6,141 | **0** | 2 | FAIL / **FAIL** / FAIL | **24.2 / 29.1** |
| MAX_LOADED_MODELS=1 (control, agent alone) | no (swaps) | each 100% GPU | — | 0 | 7 | FAIL / **PASS** (refund 4512 59.9) / FAIL | 32.9 / 44.3 |
| T13b setup A (SLM qwen2.5:3b, agent alone) | no | each 100% GPU | 3,963–4,304 MiB | 0 | — | (old, looser checker) | ~36.7 / 48.8 |

- The server log of the 2-loaded run says "llama-server model fits alongside existing models"
  `predicted="3.1 GiB" … available="3.9 GiB"` (T13b with the 3b SLM: needed 2.8 GiB, 2.9 available → evicting).
  RAM was tight at that moment (`system_free="896.0 MiB"`).
- SLM call: 2.39 s with both loaded vs 5.87 s alone (reloading costs ~3.5 s per reply).
- **Loading both changes the agent's output at temperature 0, and it does so every time.** The two "both loaded"
  runs (practice d20 and step-5 d20) give the same agent A answer as each other. The two "one at a time" runs
  (T13c run 1 and the control run) give the same answer as each other. The two answers differ. Most likely
  Ollama runs the agent with a different GPU setup when the GPU is shared (my reading; not proven).
- d05 and d24 fail in every setup. In T13b they counted as PASS only because the checker was looser then
  (T13c made them expect a refund).
- Traces: `traces/run_20261028_200443_413556.jsonl` (2 loaded), `traces/run_20261028_200716_987518.jsonl` (control).
  Raw files (git-ignored): `out/t13f/` (`run_*.txt`, `live_check_*loaded.json`, `samples_*.txt`, `server_*.log`).

### Calls
- 0 API calls. `llm_call` lines, all `ollama`, **0 groq, 0 google**:
  - practice run: 106 (qwen2.5:1.5b 28, cv-qwen3.5-4b 78)
  - 2-loaded run: 22
  - control run: 23
- `tests/data/*` not run. `.env` not read.
- Time: 19:50 → about 20:15 (~25 min of 1 h, plus the wait for memory).

### One sentence each
- **Keep qwen2.5:1.5b?** Yes. Every SLM reply in the re-run passed the check, with 0 leaks, and it saves ~1 GB and
  ~4 s per reply. One weak spot to watch: it left out the long "I can help with…" must_say sentence twice (the
  template covered it).
- **Keep the new labels in the check?** Yes. 0 wrong rejections on 24 live practice replies and 70 stored ones, and
  it catches the copied labels the old check missed.
- **Run both models loaded by default?** This is now what Ollama does on its own: with the 1.5b SLM, both fit and
  the normal setting loads them together. It is faster (14.5 vs 25.1 s per message), but it changes the agent's
  answers, and d20 lost its refund proposal in 2 of 2 runs. The Brain should choose one setup and measure the agent
  in that setup.

## 4. Problems
- **The task's "normal setting (one model at a time)" is no longer what happens.** Ollama's normal value is
  `OLLAMA_MAX_LOADED_MODELS=0` (automatic, limited by GPU memory). With the 3b SLM only one model fitted. With 1.5b,
  both fit, so the normal setting now loads both. I restored the normal tray app with no variables. If "one at a
  time" is wanted, a **user environment variable `OLLAMA_MAX_LOADED_MODELS=1`** is needed. I did not set it: it is a
  lasting change to this PC.
- **The SLM switch therefore changed the agent's behaviour** (d20), through GPU sharing and not through anything the
  SLM writes. The agent's results from T13/T13b/T13c (one model at a time) may not repeat in the new default setup.
- **qwen2.5:1.5b copies the prompt's example number** (d02: "1234"). It was caught and retried, but the system
  prompt's `"order 1234"` example invites it. The prompt was not changed (not allowed).
- The new labels are reported by the check as "forbidden promise: 'length:'" (the existing message text). The
  wording is a little odd, but it is enough for the retry.
- RAM: 1.6 GB free at first (I asked Yassine to close Brave and Notion). At the 2-loaded agent load, the server saw
  896 MiB free. Nothing crashed, but this PC has little spare RAM with both models plus Intake's CPU models.
- The control run with the agent alone was not in the task. I added it because the 0/3 result needed a baseline
  on the same code. It took 3 messages and ~2 min, all local.

## 5. Questions for the Brain
1. **Both loaded (now the default) or one at a time** (needs `OLLAMA_MAX_LOADED_MODELS=1` as a user variable)?
   Both is ~40% faster; one at a time keeps the agent's T13c behaviour (d20 proposes).
2. Should the next agent task re-measure the 24 practice messages **in the chosen setup**, with 2–3 repeats, to see
   whether the d20 change is stable?
3. Should a later prompt task replace the "order 1234" example in the SLM system prompt? 1.5b copied it once.

## 6. Next step
Decide the Ollama setup (question 1). Then a short agent task: the agent writes "I can propose … sent for checking"
instead of calling `propose_refund` (d05, d17, d20, d24). This is now the main cause of failures, much more than
the SLM.
