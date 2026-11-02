# T29 progress (WIP protocol)

Branch: `feat/t29-polish` (from main 9feca1b).

- [x] Step 0: branch, task file + NEXT committed.
- [x] Step 1: money-back words (`request_words.py`, `negation.py` ACTION), `tests/test_t29_money_words.py` (30 tests).
- [x] Step 2: F6: `propose_rebooking` refused by code with no later flight; `AgentC.run` marks `no_later_flight`; `pipeline.run_c` -> `atlas_special.no_later_flight_decision` (escalate, fixed sentence). `tests/test_t29_no_later_flight.py` (3 tests).
- [ ] Step 3: eval bench fix + refund on unpaid order refused by code.
- [ ] Step 5: regression (full suite + 72-message set).
- [ ] Step 6: docs, report.
- [ ] Step 4 (optional): "client" -> "user" in P20 rule texts.
