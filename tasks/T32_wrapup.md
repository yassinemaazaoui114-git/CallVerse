# T32 — Wrap-up after the held-out check: honest bench line, C12 note, Agent C finding

## Why
T31 ran the held-out C/D set once: **6/10 official** (C 3/7, D 3/3). Yassine approved the Brain's answers on 2 Nov (17:32):
- Q1 (C12): the official score stays 6/10 (the case was fixed BEFORE the run). Add a note: a 3-day hold is legal under
  R-HLD-01, so C12's tightened expectation was too strict (Brain's mistake); on a lenient reading the score is 7/10.
- Q2 (fix Agent C): **no fix now.** The held-out set is spent, so a fix could not be measured. Write it up as a finding.
- Q3 (bench): yes, the "Wrong proposals" line must also count `must_not_call` breaks (today it shows 0, which misleads).
- Style policy: stays **OFF** in `config.yaml`. Not part of this task.

## Hard limits
- Branch `feat/t32-wrapup` (the Brain created it from main b4ad04d; continue on it). Claude Code never merges into main.
  No secrets; never read `.env`. No force push.
- **Rule 2:** do NOT run the agents on `tests/data/agents_heldout_cd.json` again, and do not edit it. Re-score the
  saved T31 output file (`out/t31_heldout_cd.json`) only if the script can do it without calling any model.
- No change to agents, prompts, rules or models. No new libraries.

## What to do
0. Write `tasks/T32_progress.md`, set NEXT.md IN PROGRESS, update progress after every step (WIP protocol).
1. `scripts/eval_agents.py`: the summary line counts both kinds of wrong proposals, shown apart, e.g.
   `Wrong proposals: N (acted when it should not: a, called a forbidden tool: b)`. A forbidden tool = any tool in the
   case's `must_not_call`. Unit test with 2-3 fake runs (no model). If the saved T31 runs can be re-summarised offline,
   print the corrected line for T31 (expect b = 3: C09, C14, C12) and put it in the report.
2. `tasks/T31_report.md`: add a short "Note (T32)" under the score: the C12 note above (official 6/10, lenient 7/10)
   and the corrected wrong-proposal count.
3. `docs/findings_agent_c.md` (new, short, simple words, for the teacher): what the held-out check showed. Agent C
   proposes when the facts say "no" (C09 order not late, C14 stock 0), and leaves the order id empty on a hand-over (C11,
   dev C06). The Coordinator's rules caught every case, so 0 wrong writes. This is why actions are proposals checked by
   rules (the locked "agents never act directly" decision). Dev 9/11 vs held-out 6/10: the dev set had no "facts say
   no" cases. Possible fixes for later, NOT done: a code pre-check like T29, more dev cases of that kind, a model
   change; each needs a NEW held-out set to measure it. Link it from `docs/architecture.md` (one line) and README.
4. Full suite green (>= 1877 + new). Report `tasks/T32_report.md` (CLAUDE.md format), NEXT.md WAITING FOR REVIEW, push.

## Checks
Suite green. Held-out file unchanged and not run. No change in `callverse/`. No `models/`,
`data/raw/` or secrets in the diff.

## Time box
45 minutes. Commit a WIP after each step. The report lists the merge line for Yassine (the Brain reviews first).
