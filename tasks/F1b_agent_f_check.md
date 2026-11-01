# F1b — Check Semah's agent F with his real model file (finish F1 steps 5–6)

## Why
F1 brought agent F onto `review/agent-f` (14/14 tests, 1297 suite) but could not check it: the model file was missing.
Semah sent `satisfaction.pkl` (18.6 MB). Answers approved by Yassine (1 Nov, all ⭐): **no training on this PC**; licence accepted
(flagged non-commercial); check on a **seeded random 100 from the Amazon test split** now (the team's ~100 ratings stay the final exam later).
Offline task: no Groq, no merge into main.

## Hard limits
- Never read `.env`; no secrets; **never commit `models/` or `data/raw/`**; no force push / rebase / reset; do not change Semah's branch.
- **Do not train or re-fit anything** (not the model, not a stacker). Do not tune on the 100 reviews. Run the check **once**.
- Only download the Amazon **test** split, into `data/raw/` (git-ignored). Report its size.

## What to do
0. You start on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (written by the Brain). Commit both there
   ("NEXT: F1b (Brain)"), push. Then `git checkout review/agent-f`, `git pull`. (This file stays readable with
   `git show feat/t14d-request-match:tasks/F1b_agent_f_check.md`.)
1. The file is at `models/satisfaction.pkl` → move it to `models/agent_f/satisfaction.pkl` (create the folder). Print its size and SHA-256.
   Check it loads with `predict_satisfaction` on one made-up record. If it fails to load (version mismatch etc.), **stop and report** the error.
2. Download the Amazon test split with the project's own script (`benchmarks/agent_f/common.py`); English only, as F was trained.
3. Draw **100 reviews with seed 2026** (balanced or not: say which; use the same rule as his eval if it has one). Save their ids only to
   `benchmarks/agent_f/results/check100_ids.json` (no texts).
4. Score them once. Report: MAE, % within ±1 star, Spearman, and two baselines: predict the training mean (from his results JSON) and a
   delay-only rule is not possible here (no delay in Amazon) → say so. Compare with his n=5000 numbers (MAE 0.605, within ±1 92 %).
   Save `benchmarks/agent_f/results/check100.json` (numbers only).
5. Size/speed on this PC: file size, RAM after loading (process RSS), ms per prediction (mean + p95 over the 100). Limit from the RL spec: ≤ 200 ms.
6. Run F's 14 tests + full suite again. Commit (results JSON + any small script; no model, no data), push `review/agent-f`. **No merge.**
7. Write `tasks/F1b_report.md` **and** copy it to `out/F1b_report.md` (so the Brain can read it after you switch branch).
   Then `git checkout feat/t14d-request-match` and set `tasks/NEXT.md` on that branch back to: Status IN PROGRESS, task T14d (as before), "Last done" = F1b.

## Checks the Brain will look at
- File loads; check run once; MAE / ±1 / Spearman vs mean baseline and vs his n=5000; ms ≤ 200; no model or data committed.

## Time box
45 min. Stop and report on any error.
Report format: In plain words · Numbers · Problems · Questions for the Brain · Next step.
