# T26 progress (WIP protocol)

Branch: `feat/t26-demo-ready` (from main b5addd3). Started 2026-11-02.

| Step | State | Notes |
|---|---|---|
| 0 branch + task file | done | |
| 1 merge callverse-UI | done | clean merge; webui pytest 82/82 after 2 test-helper lines (T14f money-back words need the client message in the case); npm test 51/51; build OK |
| 2 merge m2-finetuned (C/D) | done | 7 conflicts, both sides kept; ask_c tools take booking_type; full suite 1554/1554 |
| 3 models + switches | done | agent_c = callverse-m2-v3 -> Groq 120b -> 20b -> Gemini; low-confidence routing OFF (step 4); layer2_agent_c ON (no fail traced to it so far) |
| 4 regression check | PARTIAL (run killed: PC low on memory) | 4 of 6 sets done: decline_practice 12/12, decline_heldout 11/12 (h10), t14b_practice 12/12, t14c_practice 11/12 (s02) = 46/48, 0 wrong writes seen. Both fails = P20 low-confidence routing to C -> switched OFF (null). Left: t14c_heldout, t14d_heldout, eval_agents 26 cases, and rerun h10 + s02 with the switch off. Script: out/t26_* names, same runners as T14f |
| 5 merge rl1-styles | done | README conflict only, both kept; reply_style null (default unchanged); suite 1765/1765 |
| 6 one-click start + reset | done (not yet run live) | scripts/start_demo.ps1, Demo.bat, scripts/reset_demo.ps1, shortcut |
| 7 live demo flows | todo | |
| 8 docs | todo | |
| 9 report | todo | |

## Notes for the next session
- Step 7 driver (not in git): drive the REAL API with a temporary accounts file (password demo-only), real DBs,
  real models: start the API with only CALLVERSE_WEBUI_ACCOUNTS pointing at a temp copy made by
  `webui.api.dev_fixture.write_accounts(folder)`, plus CALLVERSE_AGENTS_SET=local and CALLVERSE_LAYER3_MODE=queue.
- Do not run step 7 while a regression runner is busy: the runners reseed the company databases.
