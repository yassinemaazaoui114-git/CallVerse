# T28 progress (WIP protocol)

Branch: `feat/t28-step09` (from main 4aa0bf8).

| Step | State | Notes |
|---|---|---|
| 0 branch, task file, NEXT IN PROGRESS | done | |
| 1 Desktop shortcuts | done | `scripts/make_shortcuts.ps1`, `Reset.bat`; `start_demo.ps1` starts Ollama when it is down. Tested: Ollama stopped → shortcut → ready in 12 s → windows closed. |
| 2 design note | done | `docs/step09_design.md` |
| 3 memory | done | `callverse/channels/conversation.py` (earlier id, pending question), `store.pending_questions` |
| 4 bare yes/no | done | `web_chat._send` step 0; Coordinators read `case["yes_answer"]` (`negation.yes_confirmation`) |
| 5 several requests | done | `conversation.split_requests` (2+ ids), extras appended in `finish()` |
| 6 T14f follow-ups | done | "no refund please" (negation step 3); TWCS-style draft tests; rest = limits in report |
| 7 T27 fixes | 7a done; 7b in the live run | `OwnerProposals.jsx` "No sales in the last 30 days" + vitest |
| 8 tests + regression | pytest 1803/1803 (+7 later); 72-set running (`out/t28_run72.sh`, DB backup in `out/t28_dbbackup/`) | vitest: `Chat.test.jsx` one flaky test (file not touched) |
| 9 live check | todo | `scripts/run_t28_live.py` (S1-S4, U1-U4) |
| 10 docs + report | README done; runbook + report todo | |

If the session stops during the 72-set: restore `out/t28_dbbackup/*.db` into `callverse/data/`.
