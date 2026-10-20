# P04 — Platform hardening + merge check with the intake branch

## Why
The ShopNova platform covers the prototype minimum (P01-P03). Before Yassine's core tasks (Agent B, Coordinator,
notifier) start using it, we close the small gaps found in the P03 review and prove that `platform` and
`feature/intake` (T03) work together, so the final merge into `main` has no surprises.

## Hard limits
- `docs/platform_contract.md` wins. Update it for every behaviour you change.
- Scripted orders 4505-4515 and all demo RESULT lines stay identical. 4512 stays 6 days late.
- Generated data stays byte-identical (same MD5 as P03, `56d970b1…b189`), unless a step below says otherwise.
- No agent, Coordinator, intake or LLM code changes. No secrets in files.
- **Never merge into `main`, and never push a merge branch.** The merge check is local only.

## What to do
1. **NaN / infinity guard.** `create_refund(4512, float("nan"), ...)` crashes today with
   `sqlite3.IntegrityError: NOT NULL constraint failed: refunds.amount`, because NaN passes `amount <= 0`.
   Python's `json.loads` accepts `NaN`, so an LLM tool argument can carry it. In `create_refund` and `layer3_decide`,
   refuse any amount that is not a finite number > 0 (`math.isfinite`; also refuse `bool`). Return `{"error": ...}`
   and trace it, never raise. Add tests for `nan`, `inf`, `True`, `"59.90"`.
2. **One source for the demo date.** `seed.py` repeats `SIM_TODAY` = 2026-10-09 next to `sim_today` in `config.yaml`.
   Make `seed.py` use `sim_today()` from `callverse/config.py`. The MD5 must stay the same.
3. **`shipped → stuck_at_depot`** (P03 question 1). **Only if Yassine has approved it** (see "Decisions" below): add the
   move to `STATUS_MOVES`, plus a test and a contract line. If he hasn't answered, skip this step and say so in the report.
4. **Company profile read tool.** `get_company_profile()` in `shopnova_tools.py` + JSON schema. Returns the profile
   dict. **Do not add it to any allow-list** (agents get it in a core task if Yassine wants). Contract §3.
5. **Merge check (local only).** Create a temporary local branch from `platform`, merge `origin/feature/intake` into it,
   and resolve the one known conflict in `config.yaml` by keeping both new sections (`intake:` and `layer3:`).
   Then:
   - run the full test suite (platform tests + intake tests);
   - run `python scripts/demo_platform.py` and `python scripts/data_summary.py`;
   - check that intake still works with the new data: run intake on the 4512 and 4515 messages if its tests or scripts
     allow it without an API key (4515 paid 378 > 300 should trigger intake's `amount_bonus`).
   Report every conflict and failure. **Delete the temporary branch afterwards; don't push it.**

## Decisions (filled in by Dali before running)
- `shipped → stuck_at_depot` allowed? **[ ] yes  [x] no / not yet** — waiting for Yassine. **Skip step 3.**

## Checks (with numbers)
- `create_refund(4512, nan|inf|True|"59.90", ...)` → `{"error": ...}`, traced, no row, no exception.
  `layer3_decide(4515, nan)` → `{"error": ...}`.
- `seed.py` has no hard-coded 2026-10-09 any more; rebuild MD5 = `56d970b1…b189`.
- `get_company_profile()` returns all fields of `company_profile.json`; it is in no allow-list (test).
- Merge check: number of conflicts, how they were resolved, and test results x/y on the merged tree.
- All tests on `platform` pass (report x/y, the 54 old ones included). Real `shopnova.db` unchanged by the tests.

## Time box and stop rule
1 hour. Stop and ask if the merge check shows that intake depends on a field or status the platform changed.

## Git
Work on branch `platform`, commit and push it (the temporary merge branch is never pushed). Do not merge into `main`.
Write `tasks/P04_report.md` (6-section format) and set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
