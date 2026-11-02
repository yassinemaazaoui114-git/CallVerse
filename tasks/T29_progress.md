# T29 progress (WIP protocol)

Branch: `feat/t29-polish` (from main 9feca1b).

- [x] Step 0: branch, task file + NEXT committed.
- [x] Step 1: money-back words (`request_words.py`, `negation.py` ACTION), `tests/test_t29_money_words.py` (30 tests).
- [x] Step 2: F6: `propose_rebooking` refused by code with no later flight; `AgentC.run` marks `no_later_flight`; `pipeline.run_c` -> `atlas_special.no_later_flight_decision` (escalate, fixed sentence). `tests/test_t29_no_later_flight.py` (3 tests).
- [x] Step 3: `eval_agents.override_facts`, `proposal_tools.nothing_paid`, 4 tests. Bench 22/26, 1 wrong proposal (B02, model), `out/t29_eval_agents.*`.
- [x] Step 5: full suite 1848/1848; 72-set 72/72, 0 wrong writes, DBs restored.
- [x] Step 6: runbook, README, report `tasks/T29_report.md`.
- [-] Step 4 skipped (see report).
