# P04 report — Platform hardening + merge check with the intake branch

## 1. In plain words
The refund and finance functions now refuse broken amounts, such as "not a number", infinity, true/false or text,
instead of crashing. The demo date is now written in one place only (`config.yaml`), and the data is still exactly the
same. A read tool now returns the company profile, but no agent has access to it yet. Finally, I tried merging the
platform with Yassine's intake work on a temporary copy: there was one small, expected conflict, everything fits, and
the only 2 test failures come from AI libraries that are not installed on this PC. Nothing was merged into `main`.

## 2. Done
- **Amount guard**: `is_valid_amount()` in `callverse/data/writes.py` accepts only a finite int/float > 0 (refuses
  `bool`, text, `None`, NaN, ±inf). It is used by `create_refund` (refusal → `db_write_refused`) and by `layer3_decide`
  in `callverse/data/layer3.py` (refusal → `layer3_decision` with an error). Neither raises.
- **One demo date**: `seed.py` now calls `sim_today()` from `callverse/config.py`. The `SIM_TODAY` constant and the
  hard-coded 2026-10-09 are gone.
- **Step 3 skipped**: `shipped → stuck_at_depot` was not added, because the "Decisions" section says no / not yet
  (waiting for Yassine).
- **`get_company_profile()`** read tool + JSON schema in `shopnova_tools.py`. It returns the profile dict, or `{"error"}`
  if the file is missing or broken. It is on no allow-list (tested). `scripts/data_summary.py` now uses it.
- **Tests (+14)**: `test_writes.py` (6 bad amounts + NaN coming from `json.loads`), `test_layer3.py` (4 bad amounts),
  `test_tools.py` (profile fields, not on any allow-list, no hard-coded date in `seed.py`).
- **Contract** `docs/platform_contract.md`: §2 (demo date from config), §3 (`get_company_profile`), §4 + §7 (amount rules).
- **Merge check**: done locally on the temporary branch `tmp/merge-check-p04`. The merge was left uncommitted and then
  aborted, the branch was deleted, and it was never pushed.

## 3. Evidence
- Tests on `platform`: **68 passed / 68** (the 54 old tests included, 7.3 s).
- `create_refund(4512, nan | inf | -inf | True | "59.90" | None, ...)` → `{"error": ...}`, no new row, last trace
  `db_write_refused`, no exception. `json.loads('{"amount": NaN}')` → also refused.
  `layer3_decide(4515, nan | inf | True | "378.00")` → `{"error": ...}`, traced.
- `seed.py` contains no `2026, 10, 9` and no `SIM_TODAY` (tested). Rebuild MD5 = **`56d970b1…b189`**, the same as P03.
- Demo RESULT lines and `data_summary.py` output: **identical** to P03 (diffed), on `platform` and on the merged tree.
- Real `shopnova.db` unchanged by the test suite: MD5 and mtime are the same before and after.
- **Merge check** (`platform` 2b865db + `origin/feature/intake` fe06b55):
  - **1 conflict**, in `config.yaml`: both branches added a section at the end. I kept both, `layer3:` then `intake:`;
    YAML loads with keys `intake, layer3, models, providers, sim_today`. README.md, .gitignore and requirements.txt
    auto-merged without conflict.
  - Tests on the merged tree: **86 passed / 88**. Platform tests 68/68; intake tests 18/20.
  - The 2 failures (`test_priority_pair_calm_late_refund_beats_angry_on_time`, `test_ticket_has_all_fields`) both stop
    on `ModuleNotFoundError: No module named 'sentence_transformers'`: the intake models (torch, transformers,
    sentence-transformers) are **not installed in this Python**. They are not caused by the merge.
  - Without models, I ran intake's model-free parts on the merged tree (`get_facts` + `priority.compute`, reason
    `refund_request`):
    - 4512 → facts `{days_late 6, delivered False, paid 59.9}` (exactly what the 2 failing tests assert), priority 0.724 **high**
    - 4515 → facts `{days_late 8, delivered False, paid 378.0}`, severity **1.0** = 0.5 + 0.3 (late) + **0.2 amount_bonus**
      (378 > 300), priority 0.88 high
    - `extract()` finds order ids 4512 and 4515 in the demo messages.
  - Demo (exit 0) and summary (exit 0) on the merged tree: same output as P03.

## 4. Problems
- **I could not run full intake** (the 2 tests above and `scripts/run_intake.py`): the local models are not installed
  on this PC. Installing torch + transformers + sentence-transformers and downloading the models is large and changes
  the machine's Python, so I didn't do it without asking. On a PC with `requirements.txt` from the intake branch
  installed, all 88 tests should pass. The facts they check are confirmed above.
- **The 300 TND threshold now exists twice**: in R-ESC-01's condition (platform) and in intake's
  `amount_bonus.paid_over: 300` (`config.yaml`). They mean different things (finance approval vs. priority bonus) but
  could drift apart. Not changed here (intake code is out of scope).
- Intake depends only on `get_order` / `get_tracking` fields `days_late`, `delivered`, `paid`, which are unchanged. It
  does not read order status codes, so the `stuck at depot` → `stuck_at_depot` rename in P01 does not affect it.

## 5. Questions for the Brain
1. Should I install the intake models (in a separate virtual env, so the main Python is untouched) and re-run the
   merge check to get 88/88?
2. Should intake's `amount_bonus.paid_over` be read from R-ESC-01 (one place), or stay a separate intake setting?
3. `shipped → stuck_at_depot`: still waiting for Yassine.
4. Should `get_company_profile` go on agent A's or B's allow-list in a core task?

## 6. Next step
When Yassine and Dali agree, merge `platform` and `feature/intake` into `main`, using the `config.yaml` resolution
above (keep both sections). After that, Yassine's core tasks (Agent B, Coordinator, notifier) can build on the merged
`main`.

Git: P04 committed on `platform` and pushed to `origin/platform`. The temporary merge branch was deleted and never pushed. Not merged into `main`.
