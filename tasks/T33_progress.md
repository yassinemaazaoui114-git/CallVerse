# T33 progress (style policy demo check)

Branch `feat/t33-style-demo` (the Brain's, from main d020ccd).

| Step | State |
|---|---|
| 0 progress file, NEXT IN PROGRESS | done |
| 1 `scripts/style_demo_check.py` (5 messages, OFF vs ON, real-ratings policy, config patched in memory) | done; first run invalid (shared tickets file, F3), fixed and re-run; DBs restored (`cmp` identical) |
| 2 checks: 5/5 decisions unchanged, 0 wrong writes, 0 leaks, avg OFF 17.5 s / ON 18.9 s | done |
| 3 full suite 1879/1879, report, NEXT WAITING FOR REVIEW, push | done |
