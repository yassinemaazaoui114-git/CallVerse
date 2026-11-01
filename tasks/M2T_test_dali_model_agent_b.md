# M2T — Test Dali's fine-tuned model (callverse-m2-v3) as Agent B, local only

## Why
Agent B runs on Groq (gpt-oss-120b → 20b): fast but limited by the free quota. Dali fine-tuned `callverse-m2-v3` (Qwen3-4B, GGUF Q4_K_M,
2.4 GB): 24/26 on his own cases vs 16/26 for the base model. Yassine wants a quick standalone test **tonight**: does it make the same
decisions as Groq on OUR real test messages, with **0 wrong writes**? Local only, **0 Groq calls**. Research: no switch, no merge.

## Win rule (fixed before the run — do not change)
m2-v3 is a **candidate to replace Groq for Agent B** only if, on the 24 messages below: 0 crashes, 0 leaks, **0 wrong writes**, and the
`expect` checks pass on **≥ (Groq's count − 2)**. Otherwise it is not used for Agent B. Time per message is reported, not part of the rule.

## Hard limits
- Never read `.env`; no secrets; **never commit `models/` or `data/raw/`** (the GGUF stays git-ignored); no force push / rebase / reset; **no merge**.
- **0 Groq / API calls**: Agent B forced to the local model for the whole run (`CALLVERSE_AGENT_B_SET=local` + `CALLVERSE_FORCE_AGENT_B_MODEL`,
  or the T13 mechanism). If anything would call Groq, stop.
- Do not change prompts, tools, rules, the Coordinator or the writer. Only add the model to the local model list in `config.yaml` (on the test branch).
- Do not open `tests/data/t14d_heldout_messages.json`.
- Stop if free RAM < 300 MB or the GPU runs out of memory (report it; this PC: RTX 4050 6 GB, 7.7 GB RAM).

## What to do
0. You start on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (Brain). Commit both there ("NEXT: M2T (Brain)"), push.
   Then `git checkout main`, `git pull`, branch `test/m2-v3-agent-b`.
1. **Load the model:** Yassine put Dali's two files in `models/m2/` (`callverse-m2-v3-Q4_K_M.gguf`, `Modelfile_v3`). Read `Modelfile_v3`
   (report its FROM line, TEMPLATE / SYSTEM if any, parameters). Fix only the FROM path if needed, then `ollama create callverse-m2-v3 -f models/m2/Modelfile_v3`.
   If the Modelfile has its own SYSTEM prompt, say so (our agent prompt is sent as messages; report whether they clash). `ollama list` must show it.
   If the files are not there, stop and say so.
2. **Smoke test:** one Agent B call on one practice message; it must call a tool (not just chat). If it never calls a tool, stop and report.
3. **Run** with `scripts/run_t14c.py` (same runner, fresh DBs per message, clock 2026-10-09) on:
   `tests/dev/t14c_practice_messages.json` (12) and `tests/data/t14c_heldout_messages.json` (12, dev material now). Agent A, Intake and the SLM unchanged.
   Write `out/m2t_practice.json`, `out/m2t_dev.json`.
4. **Compare** with the Groq runs already on disk: `out/t14c_practice_run1.json` and `out/t14c_heldout.json` (same code = main after T14c;
   note any message where main's code changed since, e.g. none expected). Table per message: id · expected · Groq got · m2 got · same? · m2 seconds.
   Totals: expect passes (Groq vs m2), wrong writes, crashes, leaks, avg / p95 seconds, tool-call failures, any Groq call (must be 0).
5. Commit only `config.yaml` (model entry) + any small compare script + `tasks/M2T_report.md` on `test/m2-v3-agent-b`, push. **No merge.**
   Copy the report to `out/M2T_report.md`. Then `git checkout feat/t14d-request-match` and put `tasks/NEXT.md` back to T14d IN PROGRESS
   (items 5–6 Monday), "Last done" = M2T. Commit, push.

## Time box
1.5 h (24 local runs at ~30 s + model load). WIP stop allowed. Start Ollama first.
Report format: In plain words · Numbers (the WIN RULE line: true/false) · Problems · Questions for the Brain · Next step.
