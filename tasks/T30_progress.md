# T30 progress (RL5 style policy)

Branch `feat/t30-rl5` (from main 8db7e8d).

| Step | State |
|---|---|
| 0 branch + task file + held-out C/D file (unchanged) | done |
| 2 `callverse/learning/style_policy.py` (Thompson, groups, save/load) | done, tests |
| 3 `style_log` table (store.py) | done, tests |
| 4 `callverse/learning/rewards.py` (agent F, ratings, synthetic) | done, tests |
| 7 pipeline switch (OFF by default, `learning.style_policy`) | done, tests |
| 5 `scripts/train_style_policy.py`, `scripts/import_ratings.py` | todo |
| 6 baselines (synthetic) | todo |
| 8 regression | todo |
| 1 held-out C/D read-only check | todo |
| 10 docs + report | todo |
| 9 Console page (optional) | todo |

Tests: `tests/test_t30_style_policy.py` 21/21.
