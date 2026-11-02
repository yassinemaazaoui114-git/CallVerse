# T31 progress (held-out C/D final run + replay fix)

Branch `feat/t31-heldout-cd` (from main 8976172).

| Step | State |
|---|---|
| 0 branch + progress file | done |
| 1 held-out file: D07 removed, C12 `must_not_call` + `propose_hold` (own commit); `about` file name fixed in `tests/dev/agents_cases.json` | done |
| 1b replay fix: `--source ratings` writes no style_log rows; test `test_training_on_ratings_never_writes_style_log_rows` (fails without fix: 212 != 12); PC DB restored from `out/t30_dbbackup/callverse.db`, re-import 483/483, retrain: `real` rows = 483, best per group identical to T30 section 7 (13/13, same n and means) | done |
| 2 full suite | done: 1877/1877 |
| 3 single final held-out run | done once (no memory stop): 6/10 (C 3/7, D 3/3), `out/t31_heldout_cd.json` |
| 4 report + README | done (`tasks/T31_report.md`) |
