# T34 — Bring the team's finished branches into one integration branch (agent F extras, new login, simulator, vision)

## Why
Several finished parts live only on side branches (Brain check, 2 Nov 18:20 UTC). Yassine asked to integrate them, fastest
way first ("lessgo", 2 Nov 18:19). One branch, one step per source branch, the full suite after each step, one regression
at the end. Voice is NOT in this task: there is no live voice channel to merge (Molka's speech benchmarks come in with
step 4; a live voice channel is Semah's lane, `tasks/NEXT_VOICE.md`).

| Step | Source branch | State vs main (test merge) | Expected work |
|---|---|---|---|
| 1 | `feature/agent-f-rlhf-e2e` (contains `-style-reward` and `claude/agent-f-satisfaction-rr8f85`) | 154 behind, 5 add/add conflicts | ~30-45 min |
| 2 | `new-login` (Dali) | 123 behind, 3 conflicts in `webui/` | ~45 min |
| 3 | `feature/client-simulator-with-real-data` (Mahmoud) | no common history | ~1 h |
| 4 | `claude/magical-albattani-ktcgao` (vision: Semah's QLoRA adapter + Molka's channel) | 135 behind, 2 conflicts | ~1.5-2 h |

## Hard limits
- Branch `feat/t34-integrate` (the Brain created it from main d1c5909; continue on it). Claude Code never merges into
  main. Merging into MAIN later needs Yassine + each branch owner's OK (CLAUDE.md rule 1): list the owners in the report.
- `git merge --no-ff origin/<branch>` (no rebase, no force push, never rewrite or delete the teammates' branches).
- **main's version wins** for everything main already has and that was reviewed: T30 `callverse/learning/*`
  (style policy), `callverse/quality/reward.py` / `satisfaction.py` (agent F from `review/agent-f`), the Coordinator
  rules, Agent A/B/C/D prompts (locked), `config.yaml` model choices. Bring in only what main does NOT have
  (new files, benchmarks, docs, tests that pass against main's code). If a branch's file and main's file both exist
  and differ in behaviour, keep main's and list the difference in the report as a question.
- Every new feature is **OFF by default or only active on its own input** (a photo, the simulator script, the new
  login pages). With no photo and no simulator, the 72-message regression must be unchanged.
- No secrets; never read `.env`. Nothing under `models/` or `data/raw/` in git. New Python packages only in a separate
  requirements file (e.g. `requirements-vision.txt`), never in the core `requirements.txt` unless already there.
- `tests/data/*` (locked sets) stay closed.
- Close other apps before model runs (7.7 GB RAM, 6 GB VRAM).

## What to do
0. Write `tasks/T34_progress.md`, set NEXT.md IN PROGRESS, update progress after every step (WIP protocol: commit +
   push after each step).
1. **Agent F extras.** Merge `feature/agent-f-rlhf-e2e`. Resolve with main's version for `callverse/learning/*`,
   `callverse/quality/*`, `tests/test_satisfaction.py`; `requirements.txt` = main's + only the pins the new benchmark
   files need (say which). Its `callverse/learning/inference.py`, `simulator.py`, `style_writer.py`: keep only if they
   import cleanly against main and are not used by the pipeline; otherwise leave them out and say so. Suite green.
2. **New login (Dali).** Merge `new-login`. Resolve the 3 `webui/` conflicts so both main's T27 screens and Dali's
   separate sign-in pages work. Build the frontend once (`npm run build` as in the webui README) and check the 3 sign-in
   pages load. Suite green.
3. **Client simulator (Mahmoud).** No common history, so do NOT merge the branch: copy its `client_simulator/` folder
   with `git checkout origin/feature/client-simulator-with-real-data -- client_simulator` (plus its docs if any) in one
   commit that names the source commit. Make it talk to the current system through one adapter function that calls
   `callverse.channels.web_chat.send` (or the documented entry point). Run 3 simulated clients end to end (local
   `gemma3:1b`, as in its config). Its tests run in the suite (or are skipped with a reason if they need Ollama).
4. **Vision.** First the memory check: on the PC, install `requirements-vision.txt` (+ `bitsandbytes`), load the
   model once with `python -m scripts.vision_check` and confirm it runs on the GPU in 4-bit (`quant=nf4`). If it can
   only run on CPU float32, STOP step 4 and report (it would not fit in 7.7 GB). If it fits: merge
   `claude/magical-albattani-ktcgao`; resolve `README.md` and `callverse/pipeline.py` (keep every T28/T30 change, add
   the vision lines: `fusion.note`, `proof_received` from the channel, the "photo already sent -> colleague" path);
   `vision.enabled` true only when the vision packages import, else a clear "photo check not available" reply.
   Suite green (1879 + the vision tests). One real photo per company through the Help chat.
5. **Regression (once, at the end):** full suite; the 72-message set as in T28-T31 (bar >= 70/72, 0 wrong writes,
   0 leaks; no photo, so vision is not used); 3 simulator conversations; 2 photo messages (one damaged, one not).
6. Docs: README (what came in, from which branch, how to install the optional parts), `docs/DEMO_RUNBOOK.md`
   (photo step, simulator command). Report `tasks/T34_report.md` (CLAUDE.md format): per step merged / partly / not,
   conflicts and how they were solved, tests, regression, memory numbers (RAM / VRAM peak with everything loaded),
   the list of owners who must OK the merge into main, questions for the Brain. NEXT.md WAITING FOR REVIEW, push.

## Priority if time runs short
1, 2, 4, 3 (vision before the simulator: it is part of the live demo). Stop at the time box and report.

## Time box
4 hours. Commit + push a WIP after each step.
