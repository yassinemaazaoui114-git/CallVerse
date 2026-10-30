# T21 progress note (work stopped early, at Yassine's request)

Not the final report: `tasks/T21_report.md` is still to write. `tasks/NEXT.md` stays **IN PROGRESS**. Nothing is merged.

## Test result
`pytest tests --ignore=tests/data`: **872 passed, 2 failed, 874 total** (207 s, 0 API calls). **Not green.**

Both failures are in the new file `tests/test_routing_by_company.py`, and the 640 older tests have no failure:
1. `test_a_shopnova_order_number_means_nothing_at_atlas`: "Where is order 4512?" finds no Atlas reason, so Intake calls
   the LLM fallback, and this test's fake LLM forbids any call. The fallback runs before the identity check.
2. `test_a_handover_from_a_to_b_stays_at_atlas`: `out["handover"]` is None, B was expected.
   Probable cause, **not verified**: the fake Agent A uses no tool, so the T10 safety net runs it again and the second
   scripted reply is used up. This looks like a problem in the test script, but it could be a real handover bug.

Neither was fixed, because the work stopped here. Look at both before anything else.

## Done (step numbers of tasks/T21_routing_by_company.md)
- **0** Git: branch from main with the T20 merge; task file, NEXT.md and the Brain's two files committed unchanged (d72d9dd).
- **1** `callverse/companies.py` + `config.yaml companies:`; `console.companies` has atlas; `ticket["company"]`, missing = shopnova.
- **2** Bookings 7011, 7012 in the Atlas seed, pinned in tests.
- **3** Intake for Atlas: extract, 8 reasons, LLM fallback, facts, priority. Threshold **0.68** by leave-one-out on the
  examples only: 58/80 exact, 10 wrong, 12 to the LLM. ShopNova's is unchanged: 0.66, 47/60, 4, 9.
- **4** Atlas routes, including `escalate` (no agent call).
- **5** Atlas prompts, tools, allow-lists; proposal tools take no amount.
- **6** One rule index per company, own cache file.
- **7** `callverse/coordinator/atlas_coordinator.py`: amounts by code, hotel cancellation, AT-ESC-01 changed to 1,500 TND +
  every compensation, stub.
- **8** `callverse/data/atlas/writes.py`; approvals columns `company`, `booking_type`, `action`; `approvals.decide` handles Atlas.
- **9** Atlas sentences, reply writer gets the company, off-topic answer per company.
- **10** `web_chat.send`: identity, pending guard per company and booking; Console shows Atlas tickets.
- **Offline check:** Intake alone on the 12 practice messages (no API): reason, booking type and route all as expected.
- **ShopNova prompts:** the agent A / B, fallback and writer prompts, tool schemas and a sample writer message have the
  same SHA-256 as on main (fingerprints taken before any code changed; pinned in tests).

## Left
- **11** Tests written (232 in the new file), **2 failing** (above).
- **12** Live proof: **not started**, no live run and no Groq tokens used. ShopNova d05, d17, d20; Atlas 12 messages; a02 approve;
  then reseed both DBs and delete `callverse.db`. Before it: PC restarted, free RAM >= 300 MB, Ollama up.
- **13** README: not updated (it still says nothing uses atlas.db).
- `tasks/T21_report.md`, then NEXT.md to WAITING FOR REVIEW, and the last line for Dali.

## Half-done or fragile
- `.vscode/` was already untracked before this task and is not in this commit.
- **Console Dashboard:** `_refunds` still reads ShopNova's data only, so Atlas refunds are missing from its money totals. Left as
  is because the task says "no other change" in the Console.
- **Cancel write error:** an exception inside `cancel_hotel_booking` is not caught there. Nothing is half-written (test), but
  the proposal is already recorded "approve", and the pipeline escalates.
- **A wrong compensation proposal:** if B proposes one and gives up after a send-back, the client gets "escalate", not the
  status only. Only a correct no-proposal gives the status.
- **Several proposals in one turn:** only the last one counts (same as ShopNova).

## Choices to confirm in the report (made without asking)
- `companies.atlas.stub_max_approve_tnd: 2000`: ShopNova's 500 is below the 1,500 limit, so the stub could never approve.
- A refund rule pays a booking once (Coordinator + writes): otherwise AT-HOT-04's 20 % could be paid twice.
- Atlas proposal ids are `AP-0001`, not `P-0001`.
- The ShopNova Refund approvals page now filters on `company="shopnova"`, else Atlas cases would show there.
- Allow-lists stay in `tools/registry.py` (CLAUDE.md), not in config. Config has no "reads" entry either.
- Atlas has no `admin_actions` table: the admin's name and reason stay in the proposal's `decision_reason`.
- `search_policy` for Atlas is a separate function, so a model can never pass a company.

## Existing tests changed (`tests/test_atlas_data.py` only)
- `test_counts` (10 to 12), `test_scripted_bookings_are_labelled` (4 to 6), `test_summary` (2004 to 2006).
- `test_scripted_hotel_bookings`: 7011 and 7012 added.
- `test_finance_above_300` replaced by `test_finance_limit_is_1500_and_every_compensation` (asked by step 7).
- `test_atlas_is_read_by_no_agent` replaced by `test_no_agent_can_write_atlas_data`: **not a rename**, the old test forbade
  what T21 builds. Tell the Brain.
