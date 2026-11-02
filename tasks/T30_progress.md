# T30 progress (RL5 style policy)

Branch `feat/t30-rl5` (from main 8db7e8d).

| Step | State |
|---|---|
| 0 branch + task file + held-out C/D file (unchanged) | done |
| 2 `callverse/learning/style_policy.py` (Thompson, groups, save/load) | done, tests |
| 3 `style_log` table (store.py) | done, tests |
| 4 `callverse/learning/rewards.py` (agent F, ratings, synthetic) | done, tests |
| 7 pipeline switch (OFF by default, `learning.style_policy`) | done, tests |
| 5 `scripts/train_style_policy.py`, `scripts/import_ratings.py` | done, tests |
| 6 baselines (synthetic) | done (`out/rl5_baselines.md`) |
| 8 regression | full suite 1876/1876; 72-message run STOPPED by the system (low memory) at 36/72 (all pass); left: t14c_practice, t14c_heldout, t14d_heldout + switch-ON spot check |
| 1 held-out C/D read-only check | done (D07 problem, C12 weak) |
| 10 docs + report | README, runbook done; report drafted |
| 9 Console page (optional) | skipped (time) |

Tests: `tests/test_t30_style_policy.py` 28/28.
