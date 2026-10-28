# T13e — Small SLM test: which small model should the reply writer use (base for the later LoRA/QLoRA)?

## Why
The reply writer (SLM, M5) is today qwen2.5:3b (2.2 GB). Yassine's plan (Confirmed 2026-10-24): a **smaller model
(0.5–2B) + a LoRA/QLoRA adapter** trained later on Dali's D3 data. This task only picks the **base model**:
no training. A smaller SLM also frees GPU memory on the 6 GB card.
All details were agreed with Yassine on 2026-10-28 (items 1–10, all the Brain's ⭐ options).

## Hard limits
- **Never run the held-out SLM set** `tests/data/slm_test_decisions_v2.json` (`--all test2`): it is kept for the
  final LoRA benchmark.
- **No change to `config.yaml`** (the report recommends; Yassine decides). No change to the SLM prompt, the rule
  check, templates or any other code. A small comparison script may live in `out/` (git-ignored) only.
- **0 API calls** (local Ollama only). Never read or stage `.env`.

## What to do
1. **Git.** `git fetch`; create `feature/t13e-small-slm` from `origin/main` (c2b222a). Commit this task file and
   `tasks/NEXT.md` first. Ollama must answer (`ollama list`); if not, stop and report.
2. **Models.** `ollama pull` qwen2.5:1.5b, qwen3:1.7b, gemma3:1b, llama3.2:1b (use the official tags; if a tag does
   not exist, the nearest official one of the same model and size, and say which). Baseline: today's qwen2.5:3b.
   For qwen3:1.7b, turn its thinking mode off (as for qwen3.5 in T13: `reasoning_effort: none` or the documented
   way) and prove it (no reasoning text in the replies).
3. **Test material** (practice only): the 8 decisions of `callverse/slm/dev_decisions.json` (`--all dev`) and the
   old v1 SLM set `tests/data/slm_test_decisions.json` (`--all test`, spent, practice use only since T05b).
4. **Runs:** for each of the 5 models, one at a time, with today's settings (temperature 0, seed 42) and today's
   rule check: `python scripts/run_slm.py --all dev --model <name>` and `--all test --model <name>`.
   Unload each model after its runs (`ollama stop <name>`).
5. **Memory safety:** close nothing yourself, but before each model check free memory; if the PC runs critically
   low on memory, stop and report (do not retry blindly).

## Checks (with numbers)
- One table (dev + v1 together, and per set):
  | Model | Size (GB, as loaded) | First-try pass % | Needed a retry % | Template fallback % | Invented numbers/facts (count) | s per reply (avg / max) | GPU memory | Licence | LoRA/QLoRA support (Unsloth / HF PEFT: yes/no + link) |
- **5 example replies per model** (the same 5 decisions for every model, chosen to cover approve, info, ask_proof,
  layer3/escalate, ask_user), printed as written, so Yassine can read them.
- **Choice rule (fixed in advance):** among the models **≤ 1.5 GB**, the one with the best first-try pass rate;
  tie → fewer template fallbacks, then faster. If no small model reaches **at least 80% of qwen2.5:3b's first-try
  pass rate**, there is no winner: say why.
- 0 `llm_call` lines with provider groq or google.
- 3 sentences: the pick and why, the runner-up and why not, the main risk.

## Time box and stop rule
1 h. Stop and report if Ollama is not running, a model cannot be pulled, memory gets critically low, or any API
call happens.

## Git (approved by Yassine, 2026-10-28)
Commit and push `feature/t13e-small-slm` (task file, report, `tasks/NEXT.md`). **No merge into `main`.**
Write `tasks/T13e_report.md` (In plain words · Done · Evidence · Problems · Questions for the Brain · Next step)
and set `tasks/NEXT.md` to WAITING FOR REVIEW.
