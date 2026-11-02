# T31 — Held-out C/D: fix two cases, then the single final run (+ T30 replay-row fix)

## Why
T30 checked the Brain's held-out C/D file by reading only and found two problems (T30 report, Q2 and Q3).
Yassine approved the Brain's answers on 2 Nov (16:15):
- Q1: emotion class stays "angry = anger or disgust only" (no change; T30 code is right).
- Q2: **drop D07**. It can never pass: `AgentD.scan` proposes only the top 3 overstocked products (stocks 120/80/80), and product 4 has 60.
- Q3: **C12: add `propose_hold` to `must_not_call`**. A 10-day hold breaks R-HLD-01 (max 3 days), so proposing it must fail the case.
- Q4: C08 ("wedding is on Friday") stays as it is (not scored).
- Q5 (T30 report): `train_style_policy --source ratings` writes its replay rounds to `style_log` as `real` (483 -> 783 rows).
  A second ratings training would read them back as ratings and count them twice. Brain's answer: ratings training must
  not write style_log rows (the real rows are already there).
This is the last required check that does not wait for the team's ratings.

## Hard limits
- Start only after T30 is merged into main. Branch `feat/t31-heldout-cd` from the latest main. Claude Code never merges into main (CLAUDE.md rule 11). No secrets; never read `.env`. No force push.
- **Rule 2:** the held-out file is edited ONLY as written in step 1 (the two approved changes). Nothing is tuned, re-prompted or retrained because of the result. The run happens **once**.
- Code changes ONLY in step 1b (the replay fix). If a held-out case fails because of a bug, report it; do not fix it here.

## What to do
0. Create the branch. Write `tasks/T31_progress.md` and update it after every step (WIP protocol).
1. Edit `tests/data/agents_heldout_cd.json`: remove case `D07`; in `C12` set `"must_not_call": ["propose_replacement", "propose_hold"]`. Change nothing else. Commit this alone ("T31: held-out C/D, Brain fixes D07 and C12, approved by Yassine"). Also fix the file name in the `about` text of `tests/dev/agents_cases.json` (`agents_heldout.json` → `agents_heldout_cd.json`) if it is there.
1b. **Replay fix (Q5):** in `scripts/train_style_policy.py`, `--source ratings` never writes `style_log` rows (same as
   `--no-log`; say so in the help text and docstring). Test: import a small synthetic ratings file, train twice with
   `--source ratings`, the count of `real` rows stays equal to the imported count. Then clean the PC's DB: restore
   `callverse/data/callverse.db` from `out/t30_dbbackup/callverse.db` (taken before the import), re-run
   `python -m scripts.import_ratings out/CallVerse_reply_rating_filled.xlsx` and
   `python -m scripts.train_style_policy --source ratings`. Report the `real` row count (expect 483) and that the
   best style per group is unchanged from T30 report section 7.
2. Full suite green (>= T30 count + new tests).
3. **The single final run** (close other apps first, 7.7 GB RAM):
   `python -m scripts.eval_agents --file tests/data/agents_heldout_cd.json --model callverse-m2-v3 --heldout --out out/t31_heldout_cd.json`
   Run it once. If the system kills it (memory), re-run it once and say so in the report.
4. Report `tasks/T31_report.md` (CLAUDE.md format): score per case and total (10 cases), failures with the reason (model vs rule vs data), timings, and a comparison with the dev-set score of the same agents (`tests/dev/agents_cases.json`, from earlier reports, no new run needed). README: one line.

## Checks (all reported)
Held-out file diff = exactly the two approved changes. One run only. Full suite green. No `models/`, `data/raw/` or secrets in the diff.

## Time box and WIP protocol
1.5 hours. Commit a WIP after each step. Push the branch. The report lists the merge line for Yassine (the Brain reviews first).
