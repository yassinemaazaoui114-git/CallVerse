# F1 — Review and accept Semah's agent F (nothing else from his branch)

## Why
Agreed 31 Oct and again 1 Nov: from Semah's branch `feature/agent-f-rlhf-e2e` we accept **only agent F** (the model that predicts how satisfied a user will be with a reply)
and its correctness check. The rest of his branch stays as **reference** for RL1 (style bandit) and RL5. Offline task: **no Groq, no live runs, no merge into main.**

## Hard limits
- Never read `.env`; no secrets; **never commit `models/` or `data/raw/`** (rule 13); no force push / rebase / reset / branch deletion; do NOT change Semah's branch.
- Work on a new branch `review/agent-f` created from `main`. Take files from his branch with `git checkout feature/agent-f-rlhf-e2e -- <path>` only for the paths you list in step 2.
- Do not change the pipeline, Coordinator, Intake or any pinned file. F is a separate module that nothing calls yet.
- Locked test sets: never tune on them. If F's data has a held-out part, evaluate on it once.

## What to do
0. `git fetch --all`, check `git status` is clean (the T14d branch `feat/t14d-request-match` is paused: you will return to it at the end). Branch `review/agent-f` from `main`.
1. **Inventory (read only):** `git diff --stat main...origin/feature/agent-f-rlhf-e2e` and a table in the report: path · what it is (F model code / tests / data script / UI / voice / other) · size · take or leave.
   Take only: F's model + inference code, its tests, the data-prep scripts F needs. Leave: UI, voice, Docker, web channel, anything touching the pipeline.
2. **Bring in only the F files** you listed. Say how F is called (input, output, range — e.g. text pair → score 1–5), and compare with the RL interface file if the repo has one (`docs/` or `claude/`); if not, just write the signature.
3. **Run his tests** with the `.venv` python. Report passed/failed. Do not rewrite his tests; if one fails, say why (missing package, path, data).
4. **Licences:** every dataset or pretrained model F uses (e.g. Amazon Reviews Multi, others) → add to `DATA_LICENCES.md`: name · source URL · licence · what we use it for · stored where (git-ignored). If a licence is unclear or non-commercial-only, flag it (this is a university project, but say it).
5. **Correctness check:** run F on **50–100 human reviews** that were not used to train it (the 28 Oct plan: "check its predictions on 50–100 reviews"). Report: MAE, % within ±1 star, and a baseline (always predict the training mean). If F's own eval script exists, use it; do not tune. No texts of reviews in the report.
6. **Size/speed:** model size on disk, RAM, ms per prediction on CPU (this PC: RTX 4050 6 GB, 7.7 GB RAM; F must fit next to Ollama).
7. Commit on `review/agent-f` (no `models/`, no `data/raw/`), push. **No merge.** Write `tasks/F1_report.md`. Then `git checkout feat/t14d-request-match`.

## Checks the Brain will look at
- Inventory table with take/leave; only F + tests + needed scripts brought in.
- Tests result; licence rows; the 50–100 review check vs the baseline.
- Does F fit the RL contract (input/output) so RL1 can use it as the reward?

## Time box
1.5 h. Stop and report if: his tests need paid APIs, a model file is missing, or a licence blocks use.
Report format: In plain words · Numbers · Problems · Questions for the Brain · Next step.
