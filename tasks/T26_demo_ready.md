# T26 — Demo-ready platform: Dali's UI + agents C and D + RL1 + one-click start + live demo flows

## Why
Yassine has very little time and usage left. He needs a platform he can open and demo, even if some accuracy is low or small things fail.
Four things are finished on other branches and must come together on ONE branch, then be proven with the real models:
Dali's web UI (`callverse-UI`), Dali's agents C and D (`m2-finetuned`, report `tasks/P20_report.md`), RL1 reply styles (`feature/rl1-styles`),
and a start script. Merge-only work goes on this task's branch (workflow rule); Yassine merges the branch into main afterwards.

## Hard limits
- Branch `feat/t26-demo-ready` from main (b5addd3 or later). Claude Code never merges into main (CLAUDE.md rule 11).
- No secrets in files. Never read or print `.env`. No force push; no rebase/reset of shared branches.
- Do **not** edit code under `webui/` in T26. The missing screens (Promotions, Hotel deals, urgent flag, new C/D outcomes) are task **T27**, built on the merged base with the `ui-ux-pro-max` plugin Yassine installed in Claude Code, so the design stays consistent. If the merged UI needs a change, list it in the report for T27. README/docs lines are fine.
- Main's T14 safety must survive every merge: money-back words, negation check, decline by code, proof flag, hidden fields, off-topic fixed text.
  When two sides conflict, keep BOTH behaviours. Never weaken a check to make a test pass.
- Fix rule: a failing demo flow is fixed in code (a check, a default, a structure), never by a prompt trick for one model.
  Fix only what blocks a demo flow. Anything bigger goes in the report as a limit.
- Do not tune on held-out files (`tests/data/*heldout*`). No new rules beyond the ones P20 brings.
- Live runs: local `callverse-m2-v3` first for A, B and C; Groq only as the backup chain; stop at a daily limit. No rotating keys.

## What to do
0. Check main contains T14f (b5addd3). Create the branch. Commit this file + NEXT.md. Write `tasks/T26_progress.md` and update it after every step (WIP protocol).
1. **Merge `origin/callverse-UI`** (clean merge expected; only `webui/` + 3 README lines). Run `python -m pytest webui/api/tests -q`, `npm --prefix webui/frontend install`, `npm --prefix webui/frontend test`, `npm --prefix webui/frontend run build`. Record the numbers (Dali: 82 / 51 / OK).
2. **Merge `origin/m2-finetuned`** (P20: agents C and D, 9 commits; the Brain tested the merge: 7 conflicts):
   `callverse/coordinator/coordinator.py`, `callverse/pipeline.py`, `config.yaml`, `callverse/kb/policies_shopnova.json`, `tests/test_policies.py`, `tests/test_routing_by_company.py`, `tests/test_server.py`.
   - Keep main's T14b–T14f code AND P20's C/D additions. `special.py` / `atlas_special.py` checks stay in `review()` next to the money-back-words check.
   - Policies: keep all of main's rules and P20's 5 ShopNova rules (R-RPL-01, R-HLD-01, R-AST-01, R-STK-01, R-PRM-01) and 2 Atlas rules (AT-CAP-01, AT-DEAL-01); ids unique; update the rule-count test.
   - Fingerprint tests (Agent A prompt, tool schemas): update to the merged values and list them in the report. Nothing else in old tests may be weakened.
   - Full suite green. If it is not green with a clear cause within 90 minutes: `git merge --abort` (or revert the merge commit), continue with steps 3–7 without C/D, and say so at the top of the report.
   - Update the scope line in CLAUDE.md: C and D are now in scope (P20).
3. **Models and switches.** A, B and C all use `callverse-m2-v3` first (C like B: local first, Groq backup); D = rules, model only for the owner's note. Keep P20's `pipeline.layer2_agent_c` and low-confidence routing (`queues.low_confidence_margin` 0.02) ON **only if** the check in step 4 still passes; otherwise turn them OFF and record why.
4. **Regression check, local, once.** (a) The 72-message set exactly as in T14f (`run_decline_check` + `run_t14c`; T14f: 72/72). Bar: >= 70/72, 0 wrong writes, 0 leaks. (b) `scripts/eval_agents.py` on P20's 26 cases with v3 (P20: 24/26). Bar: >= 22/26 and 0 wrong proposals. Report both tables.
5. **Merge `origin/feature/rl1-styles`** (expected conflict: README only). Default reply style must stay unchanged. If anything else conflicts or a test fails, skip it, `merge --abort`, and say so (RL waits for the team's ratings anyway).
6. **One-click start.** `scripts/start_demo.ps1` + `Demo.bat` (+ desktop shortcut in the same style as the existing ones): checks Ollama answers and that `callverse-m2-v3` and the SLM model exist; sets `CALLVERSE_LAYER3_MODE=queue`; no `CALLVERSE_WEBUI_*` overrides and no FAKE_CHAT; starts the API (127.0.0.1:8610) and the frontend dev server (5173) in two windows; opens the browser. Also `scripts/reset_demo.ps1`: asks the user to type YES, then reseeds both company databases and deletes the tickets DB (the reset commands in the README), so the demo can be repeated. If `config/accounts.yaml` is missing, print "run scripts/create_demo_accounts.py" (Yassine sets the passwords; never create or print passwords).
7. **Live demo flows with the real models** (reset first; queue mode; through the API or the browser, whichever works; max ~14 messages in total; record the exact message text, ticket id, outcome, seconds, trace file, model used):
   - F1 sara, order 4512, asks for her money back -> refund 59.90 approved by code, ticket Solved.
   - F2 youssef, order 4515, refund -> "waiting for finance"; then `admin` approves it in the new UI/API -> refund row written once, reply sent.
   - F3 nizar, flight 7004, compensation -> waits; `atlas_admin` approves 839.50.
   - F4 amira, order 4511, "where is my order" -> status answer.
   - F5 Agent C at ShopNova (adapt P20 case C01 or similar to the seeded data): urgent need -> C offers a replacement or hold -> the next message "yes" -> done. Reset between flows that use the same order.
   - F6 Agent C at Atlas: hedi, cancelled flight 7005, asks to be rebooked -> C asks -> "yes" -> rebooking row. Optionally sonia / tarek wheelchair request (consent).
   - F7 Agent D: run the stock check (promotion proposed, owner pending) and the Atlas hotel deal check. These approval pages exist only in the Streamlit apps (the new UI has no page for them yet): show them there and say so.
   A flow that fails is fixed once in code if the cause is small; otherwise record it and move on (stop at 2 design-level failures).
8. **Docs.** `docs/DEMO_RUNBOOK.md`: how to start and reset; the accounts and the exact messages in demo order (only the ones that worked); one line per flow on what to say; a **Known limits** list (at least: a bare "Yes" re-asks except C's own question; the new UI has no Promotions / Hotel deals pages yet (T27 adds them); D has no seats; C/D practice cases are Claude-written drafts and have no held-out set; if Ollama or Groq is slow). README updated (T26 + how to start the demo).
9. Report `out/T26_report.md`: top line = what is merged and what is not; test counts; step 4 tables; the flow table (F1–F7); the list of new rules from P20 with their text (Yassine reviews them); the conflict decisions; the list for T27 (Promotions / deals pages, urgent flag, new C/D outcomes, anything else the UI lacks); anything left.

## Checks (all reported)
Full suite green on the branch (before: 1429 on main + Dali's `webui` tests + P20's tests). Step 4 bars. F1–F4 pass with real models and 0 wrong writes. No secrets or `models/` or `data/raw/` in the diff. No file in `webui/` changed except README lines.

## Time box and WIP protocol
3 hours. Commit a WIP after each step and keep `tasks/T26_progress.md` current. If the session stops, the next one reads the progress file and continues. The demo-critical order if time runs short: 1, 6, 7 (F1–F4), 8, then 2–5. Do not push to main. Push the branch.

## Git
Branch `feat/t26-demo-ready` from main; push the branch; the report lists the merge line for Yassine. Update the README at the end (CLAUDE.md rule 8).
