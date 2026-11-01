# RL1c — Clean the rating sheet (drop 3 rows, fix the "team," greeting bug, 2-reply rows)

## Why
The Brain read all 90 RL1b replies. Approved by Yassine 1 Nov 20:20 (all ⭐): keep qwen2.5:1.5b (the live writer) so ratings match reality;
drop h08 (empathy contradicts the decision), a07 (a decision inside the empathy sentence), p08 (decision from the pre-T14c run, outdated);
fix the bug that put the client's word "team," after the greeting (s02) so s02 stays; rows where `warm` = `warm_next_step` show only the
2 different replies. Local SLM only, **0 Groq**, no merge. Agent F is on main now: Yassine decided we rename its style names ourselves (step 1b); Semah is told.

## Hard limits
Same as RL1/RL1b (no `.env`, no secrets, no `models/` / `data/raw/` commits, no force push / rebase / reset, **no merge into main**,
default writer byte-identical, `check.py` and Coordinator unchanged, do not open `tests/data/t14d_heldout_messages.json`).

## What to do
0. You start on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (Brain). Commit both there ("NEXT: RL1c (Brain)"),
   push. Then `git checkout feature/rl1-styles`, `git pull`.
1. **Greeting bug:** in the styled path, a leftover word or vocative right after the greeting ("Dear customer, team, …", "Hello, guys, …")
   must be removed (the greeting is by code; the model's text must start with a real sentence). Add tests (≥ 4: "team,", "guys,", "sir,", a
   normal sentence untouched). Also: an empathy sentence that **copies the prompt's example** word for word is a problem → retry → template.
1b. **Agent F style names:** in `callverse/quality/satisfaction.py` change `STYLES` to `["short", "warm", "warm_next_step"]` and update the
   style used in `tests/test_satisfaction.py` (and any other old name in `callverse/quality/` or its tests). Nothing else in F. F's 14 tests must pass.
2. **Sheet:** remove h08, a07, p08 from the fixed list (27 rows). Rows where two styles give the same text: show only the distinct replies
   (A, B); the key lists every style for each letter (e.g. `"B": ["warm", "warm_next_step"]`). Add a column `n_replies`.
3. Rebuild the sheet (same files, seed 2026). Report: rows, rows with 2 replies, template ids per style, and print s02's three replies.
4. Tests (full suite) green. Commit, push `feature/rl1-styles`. **No merge.** Write `tasks/RL1c_report.md`, copy to `out/RL1c_report.md`.
   Then `git checkout feat/t14d-request-match`, put `tasks/NEXT.md` back to T14d IN PROGRESS (items 5–6 Monday), "Last done" = RL1c. Commit, push.

## Time box
45 min. Stop if Ollama is down.
Report format: In plain words · Numbers · Problems · Questions for the Brain · Next step.
