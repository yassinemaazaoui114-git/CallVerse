# P02 — ShopNova platform: P01 fixes, Layer 3 stub, platform demo (no LLM)

## Why
P01 gave the platform its data, policies and write functions. Three things are still missing on the platform side:
- two small P01 fixes found in review (a policy condition that misses past refunds, one tool shape);
- the Layer 3 company contact stub (R-ESC-01), which the Coordinator will call for refunds above 300 TND;
- a script that plays S1, S2 and S3 with platform functions only. It proves the platform works on its own and
  is the backup for the professor's demo if the Groq API is down.

## Hard limits
- `docs/platform_contract.md` wins. Update it for every shape you change.
- Do not change agents, `llm.py`, `registry.py` allow-lists, intake, Coordinator or notifier.
  The demo script imitates them in a few plain lines; it does not build them.
- Write functions stay outside `tools/` and outside every allow-list.
- The demo date stays fixed (`sim_today`). Tests use the temporary DB only.
- No secrets in files.

## What to do
1. **R-REF-05 fix** (`callverse/kb/policies_shopnova.json`): the condition `amount <= paid` lets 4506 be refunded
   twice (paid 189, already refunded 189). Change it to `amount <= paid - refunded_total`, where `refunded_total`
   = sum of that order's refunds with status `approved` or `completed`. Keep the text meaning; mention past refunds.
   Yassine reviews the wording with the other rules.
2. **`get_refunds` shape** (`callverse/tools/shopnova_tools.py`): return a dict like the other tools:
   `{"order_id": 4512, "refunds": [...], "refunded_total": 0.0}`. Unknown order stays `{"error": ...}`.
   Update its JSON description, tests and the contract §3.
3. **Layer 3 stub** — `callverse/data/layer3.py`, `layer3_decide(order_id, amount, reason) -> dict`:
   - amount <= 300 TND (R-ESC-01 condition false): `{"decision": "not_required", ...}`
   - 300 < amount <= `layer3.stub_max_approve_tnd` (500, from `config.yaml`): `"approved"`, by `"finance"`
   - above 500: `"refused"`
   - unknown order or amount <= 0: `{"error": ...}`
   Returns `{order_id, amount, decision, by, rule_id: "R-ESC-01", reason}`. Read the 300 from R-ESC-01's condition
   (one place only, as P01 did for notification events). Trace with `trace.log("layer3_decision", "layer3", ...)`.
   No DB write. Not in any allow-list.
4. **Platform demo** — `scripts/demo_platform.py`: re-seed, start a trace run, then print each step in plain words
   (function called, result, rule used):
   - **S1**: read 4512 (`get_order`, `get_tracking`, `get_refunds`), check R-REF-03 and R-REF-05 conditions,
     `layer3_decide` → `not_required`, `create_refund(4512, 59.90, "R-REF-03", "demo-s1")`.
   - **S2**: proposal 70.00 for 4512 → R-REF-05 fails → print "sent back"; corrected 59.90 → passes.
     (Run S2 on a fresh seed, or before S1's refund, so the numbers stay right.)
   - **S3**: `create_subscription(4512, "delivered")`, `set_order_status(4512, "out_for_delivery")`, then
     `"delivered"`; print the `events` rows that match the waiting subscription (do not mark them `sent`:
     that is the notifier's job).
   - **Extra**: 4506 second refund → R-REF-05 fails (already refunded); a 350 TND case through `layer3_decide`
     → `approved`, 600 → `refused` (call the stub directly, no DB change).
   End by printing the path of the trace file. Re-seed at the end so the real DB is clean again.
   For the condition checks, write one small helper in the script (or `callverse/kb/policies.py` if it stays
   under ~30 lines) that evaluates the conditions with plain Python comparisons. **No `eval()`.**

## Checks (with numbers)
- 4506: `amount=1` fails R-REF-05 (`refunded_total` 189 = paid 189). 4512: 59.90 passes, 70.00 fails.
- `get_refunds(4506)` → `refunded_total` 189.0, 1 row; `get_refunds(4512)` → `refunded_total` 0.0, `[]`.
- `layer3_decide`: 59.90 → `not_required`; 350 → `approved`; 500 → `approved`; 500.01 → `refused`; 0 → error.
- `python scripts/demo_platform.py` runs with **no API key** and exits 0; S1, S2, S3 and the extra cases each print a
  clear result line.
- Real `callverse/data/shopnova.db` unchanged after the test suite (same check as P01).
- All tests pass (report x/y, the 29 old ones included).

## Time box and stop rule
1.5 hours. Stop and ask if a change would touch agents, the registry allow-lists or the Coordinator.

## Git
Work on branch `platform`, commit. Push only if GitHub access works now; do not merge into `main`.
Write `tasks/P02_report.md` (same 6-section format as CLAUDE.md) and set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
