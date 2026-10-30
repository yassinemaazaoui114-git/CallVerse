# T21 report — Routing by company, part A: Atlas Travel through the same center

## 1. In plain words
A message for Atlas Travel now goes through the same center as ShopNova: it is read, routed, handled by agents A or B,
checked by the Coordinator, written to the database and answered. Atlas has its own reasons, tools and rules, and the
agents never give an amount: the code computes it from the rules. In the live test, 10 of the 12 Atlas practice messages
gave the expected result, and the 2 misses wrote nothing wrong: one client was asked to confirm, the other was passed to
a colleague. ShopNova behaved as before on its 3 test messages. Nothing is merged; the two misses need the Brain's
decision.

## 2. Done
All 13 steps of `tasks/T21_routing_by_company.md`:
- **0–2** Branch; companies registry (`callverse/companies.py`, `config.yaml companies:`); `ticket["company"]` (missing =
  shopnova); bookings 7011, 7012.
- **3–4** Atlas Intake (booking ids, 8 reasons, fallback, facts, priority) and routes, including `escalate` (no agent).
- **5–6** Atlas prompts, tools and allow-lists (proposal tools take no amount); one rule index per company.
- **7–8** `callverse/coordinator/atlas_coordinator.py` (amounts by code, hotel cancellation, AT-ESC-01 = 1,500 TND +
  every compensation); `callverse/data/atlas/writes.py`; approvals columns `company`, `booking_type`, `action`;
  `approvals.decide` handles Atlas.
- **9–10** Atlas reply sentences, writer gets the company, off-topic answer per company; `web_chat.send` for Atlas
  (identity, pending guard); Console shows Atlas tickets.
- **11** `tests/test_routing_by_company.py` (232 tests).
- **12** Live proof (below). **13** README.

The two test failures left by the interrupted session were faults in the test scripts, not in the code (traced, then
fixed in commit b4b1362):
- `test_a_shopnova_order_number_means_nothing_at_atlas`: the Intake fallback runs before the identity check, as at
  ShopNova. The test now allows that one call only, and still refuses any agent call.
- `test_a_handover_from_a_to_b_stays_at_atlas`: the fake Agent A used no tool, so the T10 safety net ran it again and its
  second run used up the step meant for B. The net is the same on `main`. The fake A now reads first.

## 3. Evidence
**Tests:** 874/874, no API call (`pytest tests --ignore=tests/data`, 108 s, run after the final cleanup). 232 in the new
file; 642 in the others, which is the 640 older tests plus 2 cases added to `tests/test_atlas_data.py` for 7011 / 7012
(the +2 is inferred from the task's change, not traced test by test).

**Atlas threshold:** **0.68**, by leave-one-out on the examples only: 58/80 exact, 10 wrong, 12 to the LLM. ShopNova's is
unchanged: 0.66, 47/60, 4, 9.

**ShopNova prompts:** agent A / B, fallback and writer prompts, tool schemas and a sample writer message have the same
SHA-256 as on main (pinned in tests).

**ShopNova live (via `web_chat.send`, database reset before each message):** all 3 are the outcomes the task expects.
d05 and d20 match T16's rows. d17 was approved by the finance stub in T16; here it is pending because the run is in queue
mode, as the task says. I compared with T16's report only, not with T19's.

| Id | Outcome | Writes | Seconds | Note |
|---|---|---|---|---|
| d05 | approve | refund 4512, 59.90, R-REF-03 | 10.0 | |
| d17 | layer3_pending | none; approval 378.00 pending | 23.5 | |
| d20 | approve | refund 4512, 59.90, R-REF-03 | 42.8 | Last B call hit Groq's per-minute limit: moved to the backup model `gpt-oss-20b` |

**Atlas live: 10/12**, in order, on one fresh `atlas.db`, queue mode:

| Id | User | Outcome | Writes | Reply | Result |
|---|---|---|---|---|---|
| a01 | 5 | info | none | Your flight booking 7010 is scheduled. | pass |
| a02 | 5 | layer3_pending | none; approval 839.50 | …compensation of 839.50 TND for booking 7004 needs approval from our finance team… | pass |
| a03 | 1 | approve | refund 7005, 1,500.00, AT-FLT-01 | …refund of 1500.00 TND for booking 7005 is approved. | pass |
| a04 | 4 | **ask_user** | none | Please confirm that you want a refund of 690.00 TND for booking 7008. | **miss** |
| a05 | 4 | info | none | Your flight booking 7008 is cancelled. | pass |
| a06 | 3 | info | none | Your flight booking 7007 was delayed. | pass |
| a07 | 2 | info | none | Your flight booking 7006 was delayed. | pass |
| a08 | 3 | **escalate** | none | About your booking 7003: your request has been passed on to a colleague… | **miss** |
| a09 | 1 | approve | 7011 cancelled + refund 220.00, AT-HOT-02 | Your hotel booking 7011 is cancelled. Your refund of 220.00 TND… | pass |
| a10 | 2 | approve | 7012 cancelled, no refund (AT-HOT-03) | …cancelled. This booking is non-refundable, so nothing is paid back. | pass |
| a11 | 5 | escalate | none | Your request has been passed on to a colleague who will help you with it. | pass |
| a12 | 1 | not_your_order | none | This booking is not on your account. | pass |

**a02 approved:** `approvals.decide(approve)` wrote compensation 7004, 839.50, status `approved`, AT-FLT-03, proposal
AP-0001. New message: "Your compensation of 839.50 TND for booking 7004 is approved after a check by our finance team."

**Misses explained:**
- **a04:** Agent B called `propose_refund` correctly but set `user_confirmed: false`, although the client wrote "please
  refund me" and B quoted those words. The Coordinator did its job and asked. This is a model slip with a safe result:
  no money moved, but the client has one extra step.
- **a08:** B called `propose_compensation` with AT-HOT-04, a refund rule, without searching the rules. The Coordinator
  sent it back, but its hint named two flight rules for a hotel booking (AT-FLT-02, AT-FLT-03), not the action that
  fits. B proposed nothing on the second run, so the case escalated. Part model slip, part a misleading hint in our code.
- **Knock-on on a05:** because a04 paid nothing, a05 ran on a booking with no refund, not the case it was written for. It
  still gave the expected result (no compensation, weather).

**Tokens and time:** Groq **64,172** in total (the task expected about 50,000): 22,966 for ShopNova, 41,012 for Atlas,
194 for 2 quota checks. Gemini **0**. Local, both runs together: 9,136 SLM, 4,760 Agent A. Atlas average **5.6 s**, max
12.6 s (a04); no model fallback on Atlas.

**Run note, the proof was not one clean run:** the first run did the 3 ShopNova messages, then stopped after a01 on a bug
in my throwaway scoring script (wrong column name), not in CallVerse. I fixed the script and ran the 12 Atlas messages
again on a fresh `atlas.db`, so a01 ran twice; the table is the second run. The pause was raised from 5 to 20 s, to stay
under Groq's per-minute limit. a01 runs on the local Agent A, so repeating it cost no Groq tokens.
Traces: `traces/t21_live_proof.jsonl`, `traces/t21_live_proof_atlas.jsonl`. Results: `out/t21_live_proof_shopnova.json`,
`out/t21_live_proof_atlas.json` (all git-ignored).

**Git:** both databases reseeded, `callverse.db` deleted. `.db` files, traces and `out/` are git-ignored; `.env` not read
or staged. `.vscode/` was already untracked and stays out of the commits.

## 4. Problems
- **B's confirmation flag is unreliable:** false on 2 of 6 live proposals (a04, a08). It decides whether money moves
  without another question, and it comes from the model.
- **Misleading send-back hint** (a08): `atlas_coordinator.py:340` lists rules for the wrong action.
- **A wrong compensation proposal:** if B proposes one and gives up after a send-back, the client gets "escalate", not the
  status. This is what happened on a08.
- **Groq per-minute limit:** d17 and d20 waited 8 times, and d20 moved to the backup model. Its outcome was right, but a
  busy demo can be slow (42.8 s on d20).
- **Console Dashboard:** `_refunds` reads ShopNova's data only, so Atlas refunds are missing from its money totals. Left
  as is because the task says "no other change" in the Console.
- **Cancel write error:** an exception inside `cancel_hotel_booking` is not caught there. Nothing is half-written (test),
  but the proposal is already recorded "approve", and the pipeline escalates.
- **Several proposals in one turn:** only the last one counts (same as ShopNova).
- **An unused LLM call:** a message with a booking number that is not the user's and no clear reason still pays for the
  Intake fallback, because the identity check comes after Intake (same as ShopNova).
- **Handover without a tool:** if Agent A hands over without using a tool, the T10 net runs it again and the first
  handover is dropped. Same on `main`, so left alone. It can only matter when a money request is routed to A.

## 5. Questions for the Brain
1. **a04 (user_confirmed):** should the flag stay with the model, or should code decide it? My recommendation: leave the
   prompts, and treat a request routed as refund / compensation / cancellation that the agent quotes as confirmed, in code.
   That would touch how the safety check works, so it needs your decision. I changed nothing after the scored run.
2. **a08 (send-back hint):** my recommendation is a code fix: when the rule fits another action, the send-back names that
   action ("AT-HOT-04 justifies a refund: use propose_refund"). Small, Atlas only. It needs its own live check.
3. **Choices made without asking, please confirm:**
   - `companies.atlas.stub_max_approve_tnd: 2000`: ShopNova's 500 is below the 1,500 limit, so the stub could never approve.
   - A refund rule pays a booking once (Coordinator + writes): otherwise AT-HOT-04's 20 % could be paid twice.
   - Atlas proposal ids are `AP-0001`, not `P-0001`.
   - The ShopNova Refund approvals page now filters on `company="shopnova"`, else Atlas cases would show there.
   - Allow-lists stay in `tools/registry.py` (CLAUDE.md), not in config. Config has no "reads" entry either.
   - Atlas has no `admin_actions` table: the admin's name and reason stay in the proposal's `decision_reason`.
   - `search_policy` for Atlas is a separate function, so a model can never pass a company.
4. **Existing tests changed (`tests/test_atlas_data.py` only), more than renames:**
   - `test_counts` (10 to 12), `test_scripted_bookings_are_labelled` (4 to 6), `test_summary` (2004 to 2006).
   - `test_scripted_hotel_bookings`: 7011 and 7012 added.
   - `test_finance_above_300` replaced by `test_finance_limit_is_1500_and_every_compensation` (asked by step 7).
   - `test_atlas_is_read_by_no_agent` replaced by `test_no_agent_can_write_atlas_data`: **not a rename**, the old test
     forbade what T21 builds.

## 6. Next step
Decide questions 1 and 2, apply them as a short follow-up with a live re-check of a04 and a08, then review and merge
`feature/t21-routing-by-company`. After that, T22 (the Atlas app).

**For Yassine, to tell Dali:** companies registry (`callverse/companies.py`), approvals columns `company` / `booking_type` /
`action`, Atlas bookings 7011–7012, AT-ESC-01 now 1,500 TND + every compensation.

---

# Follow-up after the Brain's review (approved by Yassine, 2026-10-30)

## In plain words
The two misses are fixed and both messages now get the right result live: a04 pays 690.00 and a08 pays 72.00. At Atlas, code now decides whether the client asked, not the model. When an agent cites a rule under the wrong tool, the Coordinator now names the right tool. The Console's money totals now include Atlas, per company. The new confirmation rule has one real risk (a sentence saying "do not cancel"), described below.

## Done
1. **Confirmation by code, Atlas only:** `client_confirmed` in `callverse/coordinator/atlas_coordinator.py`. Confirmed = Intake's main reason is refund_request, compensation_request or cancellation, AND the agent's `user_quote` is in the client's message (case-insensitive, outer spaces trimmed). The pipeline gives the Coordinator the ticket's own text, so a quote of the Intake note does not count. An empty or non-text quote confirms nothing.
2. **Send-back hint:** `wrong_rule_reason` gives e.g. "AT-HOT-04 justifies a refund: use propose_refund". A rule of two actions names both (AT-HOT-02). A rule of no action keeps the old text.
3. **Console:** `reads.dashboard` gives refunds and compensation per company (`money_per_company`), and the top totals add them up. A row counts only for its own company. The Dashboard has a "Compensation paid" number and a "Money per company" table. `atlas.db` is opened read-only.
4. **Approved, nothing to build:** question 3's choices and the 6 changed tests. Atlas `admin_actions` comes in T22.

## Evidence
**Tests: 912/912** (`pytest tests --ignore=tests/data`, 99.5 s, 0 API calls, after the final cleanup), 38 more than before. Code commit: **5abce5a**.

**Live re-check** (each on a fresh `atlas.db`, queue mode, Agent B on Groq; trace `traces/t21_recheck.jsonl`):

| Id | Outcome | Writes | Reply | Groq tokens | Seconds |
|---|---|---|---|---|---|
| a04 | approve | refund 7008, 690.00, AT-FLT-01 | I'm sorry for the trouble. Your refund of 690.00 TND for booking 7008 is approved. | 6,665 | 7.1 |
| a08 | approve | refund 7003, 72.00, AT-HOT-04 (1 send-back) | I'm sorry for the trouble. Your refund of 72.00 TND for booking 7003 is approved. | 7,937 | 7.2 |

Groq total **14,699** (14,602 + 97 for one quota check), `gpt-oss-120b` only, Gemini 0, no limit hit. Both databases reseeded, `callverse.db` deleted.

**What this live run proves, and what it does not:**
- **a08** proves both fixes together: the model first chose compensation, the hint moved it to `propose_refund`, and the model still said `user_confirmed: false`, so only the code confirmed it.
- **a04** did not test the new rule live: this time the model said `true` by itself. The case "agent says false, code confirms" on a04's own message is covered by the offline test `test_the_client_was_not_asked_again_on_a_clear_request`.
- Only a04 and a08 were re-run. Replaying the rule on the 6 real proposals of the first live run gives "confirmed" for all 6, so no earlier pass should turn into a question, but the other 10 messages were not run live again.

## Decisions I made
- **Read literally: the agent's `user_confirmed` no longer counts at all.** The agent's `true` is not enough either: if the two conditions fail, the client is asked. This is the safer reading.
- **Behaviour change from that reading:** a handover from A to B with a reason like booking_status now asks the client instead of paying. `test_a_handover_from_a_to_b_stays_at_atlas` was changed for this, and `test_an_unconfirmed_request_asks_the_client` was rewritten.
- **Test helpers changed:** the fake agents now quote the client's real words, as the real agent does, and hand-made cases carry a main reason and a message.

## Problems
- **Risk, a negative sentence can confirm:** "Please do not cancel my booking 7011." gets main reason `cancellation` (checked offline, no agent run), and "Do not refund booking 7008, I don't want my money back." gets it too. If the agent wrongly proposed and quoted that sentence, the code would confirm it, and the agent's own `false` no longer blocks it. The agent would have to go wrong first, and no such case was seen, but a hotel cancellation cannot be undone by the client.
- **A plain "yes" cannot confirm:** "Yes, go ahead for booking 7008." gets `booking_status`, so the client is asked again; "yes" alone has no reason and no booking. A client must repeat the request. Fewer questions are asked now, so this should be rare.
- **Two places still show the agent's flag:** the `proposals` table (a08's approved refund has `user_confirmed` = 0) and the Console's proposal line ("client confirmed: False"), next to a passing check. Not changed: outside this follow-up.

## Questions for the Brain
1. Should a negative sentence block the confirmation at Atlas? My recommendation: yes, with a small code check for "do not", "don't", "never" in the quoted sentence, at least for cancellations. It would have its own tests and live check.
2. Should the Atlas proposal row and the Console line show the code's decision? My recommendation: yes, in T22 with `admin_actions`.

## Next step
Decide question 1 before merging, then review and merge `feature/t21-routing-by-company`.
