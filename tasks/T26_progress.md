# T26 progress (WIP protocol)

Branch: `feat/t26-demo-ready` (from main b5addd3). Started 2026-11-02.

| Step | State | Notes |
|---|---|---|
| 0 branch + task file | done | |
| 1 merge callverse-UI | done | clean merge; webui pytest 82/82 after 2 test-helper lines (T14f money-back words need the client message in the case); npm test 51/51; build OK |
| 2 merge m2-finetuned (C/D) | done | 7 conflicts, both sides kept; ask_c tools take booking_type; full suite 1554/1554 |
| 3 models + switches | done | agent_c = callverse-m2-v3 -> Groq 120b -> 20b -> Gemini; layer2 + low-confidence ON pending step 4 |
| 4 regression check | todo | |
| 5 merge rl1-styles | todo | |
| 6 one-click start + reset | done (not yet run live) | scripts/start_demo.ps1, Demo.bat, scripts/reset_demo.ps1, shortcut |
| 7 live demo flows | todo | |
| 8 docs | todo | |
| 9 report | todo | |
