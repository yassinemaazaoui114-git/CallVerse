# T27 — Missing UI screens (Promotions, Hotel deals, Check now, urgent flag, new C/D outcomes)

## Why
T26 is merged (main cb2b59e/d467e14, 1767 tests). The demo runs, but the new React UI (`webui/`, Dali) has no page for what agents C and D produce:
the owner cannot approve a promotion or a hotel deal there (only in the old Streamlit apps), there is no "Check now" button, no urgent flag, and the new C outcomes
(replacement, hold, colleague, rebooking, wheelchair) are not shown. Yassine wants these in the UI for the demo and the final version.

## Hard limits
- Branch `feat/t27-ui-screens` from main (d467e14 or later). Claude Code never merges into main (CLAUDE.md rule 11). No secrets; never read or print `.env`. No force push.
- Use the **`ui-ux-pro-max`** plugin (installed in Claude Code) for the design of the new screens. First read Dali's existing tokens/styles (`webui/frontend/src/styles/`), `docs/ui_design.md`, `webui/README.md`
  and two existing screens (`AdminApprovals.jsx`, `ShopAdminDashboard.jsx`). New screens must look like part of the same app (same tokens, Shell, States, Icon components). No new npm dependency unless the plugin needs one; list it in the report.
- Backend: only thin read/decision endpoints in `webui/api/` that call the EXISTING functions (`agent_d.promotions`, `decide_promotion`, `atlas_writes.hotel_deals`, `admin_decide_deal`, `AgentD.scan` / `scan_atlas`, the same ones the Streamlit pages use).
  Do NOT change `callverse/` agent, coordinator or policy code. Reuse the idempotency/lock pattern of `webui/api/admin.py` for decisions (a double click must not decide twice).
- Roles: ShopNova admin sees Promotions; `atlas_admin` sees Hotel deals; customers never see them. Check the role on the API side too (tests).
- Wording on screen: simple English, "users" not "clients". Amounts in TND. No raw JSON on screen.
- No tuning on held-out files. Fix rule: a failing check is fixed in code, never with a prompt trick.

## What to do
0. Check main contains T26. Create the branch. Commit this file + NEXT.md. Write `tasks/T27_progress.md` and update it after every step (WIP protocol).
1. **Design pass (short).** Using the plugin, write `webui/reports/step-8.md` first: one paragraph per screen below + a rough layout sketch in text. Keep it to 1 page.
2. **Promotions page** (ShopNova admin, route `/admin/promotions`, menu entry in Shell): table of promotions, pending first; columns product, stock, days of cover, discount %, Agent D's note, status; Approve / Refuse (reason box) like the approvals page; after a decision show who/when. Empty state text.
   API: `GET /api/admin/promotions`, `POST /api/admin/promotions/{id}/decision`.
3. **Hotel deals page** (atlas_admin, route `/atlas/admin/deals`): same idea: hotel, nights, occupancy, discount %, note, status; Approve / Refuse.
   API: `GET /api/atlas/admin/deals`, `POST .../{id}/decision`.
4. **"Check now" buttons**: on `ShopAdminDashboard` (stock check) and `AtlasAdminDashboard` (overbooking + empty-room check). Click → API runs Agent D's scan once → shows counts (short, overstock, promotions proposed; overbooked, low, deals proposed) and a link to the page. Disabled while running; error state if it fails.
5. **Urgent flag.** Where the pipeline marks a case urgent (see `pipeline.layer2_agent_c`, `urgent` in the approvals/tickets data): show a clear badge on `LiveTickets`, `TicketDetail` and `AdminApprovals` rows, and sort urgent first in the approvals list. If the data is not exposed by the API yet, expose it (read-only).
6. **New C/D outcomes in the Console ticket view (`TicketDetail`) and in the chat.** Show, in plain words with an icon/badge: replacement offered/created (new order id), hold made (units, until), passed to a colleague (reason), rebooking (flight), special assistance (wheelchair etc.), "waiting for the user's yes", and D's stock warning if attached. In `Chat`, a C question that waits for the user's "Yes" must be visible as a normal assistant message (check it already is; fix if not).
7. **Tests.** `python -m pytest webui/api/tests -q` with new tests for each endpoint (auth, role, happy path, double decision, empty list); `npm --prefix webui/frontend test` with component tests for the two pages, the Check-now button and the urgent badge; `npm --prefix webui/frontend run build` OK. Full `python -m pytest -q` still green (1767 on main + new).
8. **Look at it for real.** Reset (`scripts/reset_demo.ps1`), start with `Demo.bat`, and use the browser tool (built-in browser or Claude in Chrome, whichever works) to: log in as the ShopNova admin → Check now → Promotions → approve one; log in as `atlas_admin` → Check now → Hotel deals → approve one; make an urgent case (T26 flow F5) and see the badge and the new outcome in TicketDetail. Save 4–6 screenshots under `webui/reports/screenshots/step-8/`. If no browser tool works, say so and test through the API + frontend tests only.
9. **Docs.** `docs/DEMO_RUNBOOK.md`: add the new screens to the demo order and remove the "UI has no Promotions / Hotel deals pages yet" known limit; `webui/README.md` + root README updated (CLAUDE.md rule 8).
10. Report `out/T27_report.md`: top line; screens done (with screenshot list); endpoints added; test counts (python / webui api / vitest / build); what did not work; the plugin's contribution (one line); anything left for later.

## Checks (all reported)
Full suite green on the branch. Both new pages work end to end in the browser as the right admin, and a customer account cannot open them (API returns 403). Double decision test passes. No change under `callverse/` except none expected (if needed, list each line in the report). No secrets, `models/`, `data/raw/` in the diff.

## Time box and WIP protocol
3 hours. Commit a WIP after each step and keep `tasks/T27_progress.md` current; if the session stops, the next one reads it. Priority if time runs short: 2, 3, 4, then 5, 6, 8, 9. Push the branch. Close other apps before the live check (the PC has 7.7 GB RAM).

## Git
Branch `feat/t27-ui-screens` from main; push the branch; the report lists the merge line for Yassine (the Brain reviews first).
