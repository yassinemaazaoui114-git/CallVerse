# T13f — Switch the SLM to qwen2.5:1.5b, reject copied instruction labels, re-test (practice set + both models loaded)

## Why
T13e: qwen2.5:1.5b matched today's qwen2.5:3b on all 14 practice replies (14/14 first try, 0 template, 0 invented
content), uses ~1 GB less GPU memory and has the **Apache 2.0** licence (qwen2.5:3b: non-commercial research
licence). The small 1B models copied instruction lines ("length: …") into replies; the check caught only labels
with numbers. With 1 GB freed, the agent model + SLM may now fit together on the 6 GB GPU (T13b missed by 0.1–0.5 GB).
All details were agreed with Yassine on 2026-10-28 (items 1–6, all the Brain's ⭐ options).

## Hard limits
- **0 API calls** (local Ollama only). Never run `tests/data/*` (held-out). Never read or stage `.env`.
- No change to prompts, agents, Coordinator, policies, Intake. The SLM prompt and writer code stay as they are.
- Before the runs: the PC must have enough free memory (Yassine closes browsers). If memory gets critically low,
  stop and report.

## What to do
0. **Merge T13e.** `git fetch`, `git checkout main`, `git pull`, `git merge --no-ff origin/feature/t13e-small-slm`
   (task + report files only). Conflict: `git merge --abort` and report. Run all tests offline: all pass.
   **Do not push `main`** (Yassine pushes it).
1. **Branch** `feature/t13f-slm-switch` from the new local `main`. Commit this task file and `tasks/NEXT.md` first.
2. **`config.yaml`, SLM:** first entry **qwen2.5:1.5b** (temperature 0, seed 42); keep **qwen2.5:3b** after it only
   as the backup (used only if 1.5b is missing/unreachable). Update the comment: T13e result, ~1 GB less, Apache 2.0.
3. **Check: reject copied instruction labels.** Add entries to `slm.forbidden` in `config.yaml` (no code change) for
   labels copied from the SLM instructions, e.g. `length:`, `style:`, `formality:`, `emotion:`, `next step is:`,
   `must_say`, `outcome:`. Use keywords that never appear in a decision's facts / next_step / must_say.
   Offline tests: a reply with such a label fails the check; normal replies still pass (run the existing SLM tests).
4. **Practice re-run (once):** the 24 messages of `tests/dev/live_dev_messages.json` with `CALLVERSE_AGENTS_SET=local`
   (agent `cv-qwen3.5-4b`) and the new SLM, strict checker. Compare with T13c run 1 (20/24, 0 leaks, 0 wrong writes):
   score, leaks, template fallbacks, reply source counts (`slm` / `slm_retry` / `template`), avg/max s per message.
5. **Both models loaded together:** with `OLLAMA_MAX_LOADED_MODELS=2` and a long keep-alive (say exactly what you
   set), run the 3 refund messages d05, d20, d24 (temporary file under `out/`). Record from `ollama ps` +
   `nvidia-smi` (every ~1 s): are both models listed at the same time (count of samples), % GPU / % CPU of each,
   GPU memory peak, evictions in the Ollama log, s per message. Compare with T13b setup A (agent alone: ~36 s/msg).
   Afterwards restore the normal Ollama setting (one model at a time) and say how.

## Checks (with numbers)
- Tests x/y (all pass) on `main` after the merge and on the branch.
- Practice re-run: x/24, leaks, wrong writes, template fallbacks, reply sources, avg/max s — next to T13c run 1.
- Both loaded: yes/no, how many samples with both, GPU peak, evictions, s per message (vs ~36 s alone).
- 0 `llm_call` lines with provider groq or google.
- One sentence each: keep qwen2.5:1.5b? keep the new labels in the check? run both models loaded by default?

## Time box and stop rule
1 h. Stop and report if: the merge conflicts, a test fails, memory gets critically low, or any API call happens.

## Git (approved by Yassine, 2026-10-28)
Step 0: merge `origin/feature/t13e-small-slm` into local `main` (do not push main). Then commit and push
`feature/t13f-slm-switch` (config, tests, task file, report, `tasks/NEXT.md`). **No merge of feature/t13f.**
Write `tasks/T13f_report.md` (In plain words · Done · Evidence · Problems · Questions for the Brain · Next step) and
set `tasks/NEXT.md` to WAITING FOR REVIEW.
