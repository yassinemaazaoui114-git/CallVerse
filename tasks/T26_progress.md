# T26 progress (WIP protocol)

Branch: `feat/t26-demo-ready` (from main b5addd3). Started 2026-11-02.

| Step | State | Notes |
|---|---|---|
| 0 branch + task file | done | |
| 1 merge callverse-UI | done | clean merge; webui pytest 82/82 after 2 test-helper lines (T14f money-back words need the client message in the case); npm test 51/51; build OK |
| 2 merge m2-finetuned (C/D) | done | 7 conflicts, both sides kept; ask_c tools take booking_type; full suite 1554/1554 |
| 3 models + switches | done | agent_c = callverse-m2-v3 -> Groq 120b -> 20b -> Gemini; low-confidence routing OFF (step 4); layer2_agent_c ON (no fail traced to it so far) |
| 4 regression check | done (2026-11-02 session 2) | 72-set: 70/72 as run, s02 re-run with switch OFF = PASS -> 71/72; h10 is held-out, NOT re-run (rule 9: open once). 0 wrong writes, 0 leaks, 0 Groq tokens. Bench fixed (**kwargs), 26 cases = 22/26 (A 8/8, B 5/7, C 5/7, D 4/4), 2 wrong proposals: B02 bench artifact (override on get_tracking, B now reads tracking via ask_agent), B06 model error (refund on unpaid COD 4514, Coordinator escalated, nothing written). Earlier notes: | 4 of 6 sets done: decline_practice 12/12, decline_heldout 11/12 (h10), t14b_practice 12/12, t14c_practice 11/12 (s02) = 46/48, 0 wrong writes seen. Both fails = P20 low-confidence routing to C -> switched OFF (null). Left: t14c_heldout, t14d_heldout, eval_agents 26 cases, and rerun h10 + s02 with the switch off. Script: out/t26_* names, same runners as T14f |
| 5 merge rl1-styles | done | README conflict only, both kept; reply_style null (default unchanged); suite 1765/1765 |
| 6 one-click start + reset | done, run live once (exit 0, 7 s) | scripts/start_demo.ps1, Demo.bat, scripts/reset_demo.ps1, shortcut |
| 7 live demo flows | done | F1-F5 + F7 pass, F6 safe escalation (no later flight in real data); 0 wrong writes | |
| 8 docs | done | docs/DEMO_RUNBOOK.md (old runbook kept as appendix), README | |
| 9 report | done | tasks/T26_report.md (copy in out/), suite 1767/1767 | |

## Notes for the next session
- Step 7 driver (not in git): drive the REAL API with a temporary accounts file (password demo-only), real DBs,
  real models: start the API with only CALLVERSE_WEBUI_ACCOUNTS pointing at a temp copy made by
  `webui.api.dev_fixture.write_accounts(folder)`, plus CALLVERSE_AGENTS_SET=local and CALLVERSE_LAYER3_MODE=queue.
- Do not run step 7 while a regression runner is busy: the runners reseed the company databases.

## Brain notes (2026-11-02 10:30) — read before resuming
The last session ended at about 08:58 (PC low on memory / session stopped). Steps 7, 8 and 9 were not started. Files in `out/t26_*` written after the last commit are not committed.
What the Brain read in `out/`:
- `t26_decline_heldout` 11/12 (h10, with low-confidence routing ON), `t26_t14c_heldout` 12/12, `t26_t14d_heldout` 12/12 (routing OFF), 0 wrong writes, 0 Groq tokens. With the first four sets (46/48) the regression bar (>= 70/72, 0 wrong writes) is met; h10 and s02 were not re-run with the switch OFF.
- `t26_eval_agents_v3` = **invalid run**: every A/B/C case crashed with `TypeError: with_overrides.<locals>.run_tool() got an unexpected keyword argument 'booking_type'` (the P20 bench wrapper in `scripts/eval_agents.py` predates T14f's `booking_type`). Agent D passed 4/4 (rules). Fix the wrapper to accept `**kwargs` (bench only, small), add a test, then re-run the 26 cases once (P20 had 24/26; bar >= 22/26, 0 wrong proposals).
To finish, in this order (keep it short, Yassine has little usage left):
1. Commit what is on disk; fix the bench wrapper; re-run h10 + s02 (switch OFF) and the 26 cases. Close other apps first (7.7 GB RAM); do not run step 7 while a regression runner is busy.
2. Step 7: live flows F1–F4 first (Sara 4512, Youssef 4515 + admin approve, Nizar 7004 + atlas_admin approve, Amira 4511), then F5 (C at ShopNova), F6 (C at Atlas, Hedi 7005 rebooking), F7 (D: stock check, hotel deals). Real models, queue mode, `Demo.bat` run once for real.
3. Step 8 `docs/DEMO_RUNBOOK.md` (known limits: bare "Yes" re-asks except C's own question; the new UI has no Promotions / Hotel deals pages yet = T27; D has no seats; C/D cases are drafts, no held-out set), README.
4. Step 9 report `out/T26_report.md` (merged / not merged, test counts, both regression tables, F1–F7 table, P20's new rules with their text, conflict decisions, list for T27).
If short on time: do 1 (bench fix only), 2 (F1–F4), 3, 4, and say which flows were not run.
