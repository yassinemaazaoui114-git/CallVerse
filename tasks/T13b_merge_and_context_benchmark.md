# T13b — Merge our branches into main, then the context-length benchmark (qwen3.5:4b)

## Why
1. **Merge:** the team has started pushing branches. Our work (T11–T13) is only on `feature/t13-test-model`, so
   their branches start from an old `main`. Our branches are safe to merge (task files + the local switch, off by
   default; 307/307 tests). Approved by Yassine 2026-10-28. Teammates' branches are merged later, one at a time,
   after review — **not in this task**.
2. **Context benchmark:** Yassine wants to know the best context size for the local test model on his RTX 4050
   (6 GB). Too small = Ollama silently cuts the prompt; too big = part of the model moves to the CPU (slow).
   Today it is 8,192 (T13).
All details below were agreed with Yassine on 2026-10-28.

## Hard limits
- **0 API calls** (no Groq, no Google). Local Ollama only.
- **Ollama stays at version 0.40.12** (it auto-updated from 0.40.11 on 2026-10-28 09:55; accepted by Yassine at 10:11).
  Automatic updates are now off: do not update it. Write the version in the report. Note: T13 ran on 0.40.11.
- **No code change and no `config.yaml` change.** The report recommends a value; Yassine decides later.
- Only merge **`origin/feature/t13-test-model`** (it already contains `feature/t12-heldout`). No other branch.
- No force push, rebase, reset or branch deletion. Never read or stage `.env`. Never run `tests/data/*`.

## What to do
0. **Checks before anything:**
   - Ollama is running (`ollama list` answers) and `cv-qwen3.5-4b` is listed. If not: STOP and report.
   - `git fetch` works. If it hangs or asks for a login: STOP and report (do not merge on an old view of origin).
1. **Merge.** `git checkout main`, `git pull`. `git merge --no-ff origin/feature/t13-test-model`.
   Any conflict: STOP, `git merge --abort`, report. Run all tests offline (`python -m pytest -q`): all must pass
   (expected 307/307). Then push `main`.
2. **Branch.** Create `feature/t13b-context` from the new `main`. Commit this task file and `tasks/NEXT.md` first.
3. **Context copies.** One Ollama copy of qwen3.5:4b per value, same settings as `cv-qwen3.5-4b` except `num_ctx`:
   **4,096 · 6,144 · 8,192 · 16,384 · 32,768** (names e.g. `cv-qwen3.5-4b-ctx16384`).
4. **Messages.** The 3 refund messages **d05, d20, d24** from `tests/dev/live_dev_messages.json`, each run **once
   per value**. Put them in a temporary file under `out/` (git-ignored); do not add a new file to `tests/`.
   Run with `CALLVERSE_AGENTS_SET=local` and the copy forced (`CALLVERSE_FORCE_AGENTS_MODEL=<copy>`), via
   `python -m scripts.run_live_check --file out/<temp file>`.
5. **Two setups**, values from lowest to highest in each:
   - **Setup A — agent model alone** (as today: Ollama swaps the agent model and the SLM).
   - **Setup B — agent model + SLM (qwen2.5:3b) loaded together** (Yassine's L4 test), e.g. with
     `OLLAMA_MAX_LOADED_MODELS=2` and a keep-alive long enough for both. Say exactly what you set.
6. **Measure per value and setup:**
   - `ollama ps`: size and **% GPU / % CPU** of each loaded model (during the run);
   - `nvidia-smi`: GPU memory used (peak);
   - seconds per agent call (from the trace) and seconds per message;
   - **prompt tokens vs the context size** (largest `llm_call` prompt in the run);
   - whether the Ollama server log shows a **"truncating"** (prompt cut) warning
     (Windows: `%LOCALAPPDATA%\Ollama\server.log`);
   - PASS/FAIL of each message as printed.
7. **Stop rule (Yassine):** in each setup, **stop at the first value where any model has a CPU share**
   (anything below 100% GPU). The **recommended value** for that setup is the last value before it that ran
   100% on GPU **and** had no "truncating" warning. If 32,768 still runs 100% on GPU, say so (no higher value tested).
8. **Clean up:** delete the temporary context copies, except the recommended one(s).

## Checks (with numbers)
- Merge: conflicts (0 expected), tests x/y after the merge, `main` pushed (new commit id).
- One table per setup:
  | Context | % GPU / % CPU (agent, SLM) | GPU memory peak | s per agent call (avg / max) | s per message | Largest prompt tokens | "truncating" warning? | d05 / d20 / d24 |
- Recommended value for setup A and for setup B, in one sentence each.
- 0 `llm_call` lines with provider groq or google in this task's traces.

## Time box and stop rule
1.5 h. Stop and report if: a check in step 0 fails, the merge has a conflict, any test fails after the merge,
any API call happens, or Ollama crashes / runs out of memory twice.

## Git (approved by Yassine, 2026-10-28)
Step 1: merge `origin/feature/t13-test-model` into `main` and push `main`. Then commit and push
`feature/t13b-context` (task file, report, `tasks/NEXT.md`). **No merge of `feature/t13b-context`.**
Write `tasks/T13b_report.md` (In plain words · Done · Evidence · Problems · Questions for the Brain · Next step)
and set `tasks/NEXT.md` to WAITING FOR REVIEW.
