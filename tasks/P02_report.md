# P02 report — P01 fixes, Layer 3 stub, platform demo (no LLM)

## 1. In plain words
The refund-limit rule now also counts refunds already given, so an order can no longer be refunded twice.
The refund lookup tool now answers in the same shape as the other tools and adds up what was already refunded.
A stand-in for ShopNova's finance team (Layer 3) now decides on large refunds: under 300 TND it is not needed,
up to 500 TND it approves, above 500 it refuses. A new demo script plays the three demo scenarios using only
the platform, with no AI model and no API key. It works as a backup if the Groq API is down on demo day.

## 2. Done
- **R-REF-05** (`callverse/kb/policies_shopnova.json`): condition `amount <= paid - refunded_total`; text now
  mentions refunds already given or approved. Wording still to be reviewed by Yassine.
- **`get_refunds`** (`callverse/tools/shopnova_tools.py`): returns `{"order_id", "refunds", "refunded_total"}`;
  `refunded_total` counts statuses `approved` + `completed` (not `refused`). JSON description updated.
- **Condition checker** (`callverse/kb/policies.py`): `check_condition(condition, facts)`. It splits the text
  with Python's parser (`ast`) and computes each piece by hand: names, comparisons (incl. `1 <= x <= 5`),
  `and/or/not`, `+ -`, lists. **No `eval()`**. Money results are rounded to 2 decimals. Missing facts and unsupported
  pieces raise `ValueError`. Also `layer3_threshold()`, which reads the 300 from R-ESC-01.
- **Layer 3 stub** `callverse/data/layer3.py`: `layer3_decide(order_id, amount, reason)` returns
  `{order_id, amount, decision, by, rule_id: "R-ESC-01", reason}`. It is traced as `layer3_decision`, writes nothing
  to the DB and is on no allow-list. 300 comes from R-ESC-01; 500 comes from `config.yaml`.
- **Platform demo** `scripts/demo_platform.py`: S1, S2, S3 and extras, each on a fresh seed. It prints every call,
  its result and the rule used, re-seeds at the end and prints the trace path. It runs as
  `python scripts/demo_platform.py` or `python -m scripts.demo_platform`.
- **Tests**: `test_tools.py` and `test_writes.py` updated for the new `get_refunds` shape; +1 test that a refused
  refund doesn't count; `test_policies.py` +4 tests (R-REF-05 cases, other conditions, no code execution,
  threshold); new `test_layer3.py` (6 parametrized amounts + errors + traced / no DB change).
- **Contract** `docs/platform_contract.md`: §3 `get_refunds` shape, §5 R-REF-05 + `check_condition` + list of facts,
  §7 `layer3_decide`.

## 3. Evidence
- Tests: **42 passed / 42** (`python -m pytest -q`, 6.7 s). The 29 old tests are included; 3 of them were updated for the new shape.
- R-REF-05: 4506 `amount=1` → FAIL (refunded_total 189 = paid 189); 4512 59.90 → PASS, 70.00 → FAIL;
  4514 (0 paid) `amount=1` → FAIL.
- `get_refunds(4506)` → `refunded_total` 189.0, 1 row; `get_refunds(4512)` → `{"order_id": 4512, "refunds": [], "refunded_total": 0.0}`.
- `layer3_decide`: 59.90 → `not_required`; 300 → `not_required`; 350 → `approved`; 500 → `approved`;
  500.01 → `refused`; 0, -5, unknown order → error.
- Demo: `python scripts/demo_platform.py` run with the key variables removed → **exit 0**. `callverse.llm` and
  `dotenv` are never imported. Result lines printed:
  - S1: refund of 59.90 TND APPROVED under R-REF-03 (layer3 `not_required`)
  - S2: 70.00 → SENT BACK (R-REF-05); 59.90 → PASSES
  - S3: subscription `delivered` `waiting`; 2 events (out_for_delivery, delivered); 1 matches → "1 notification ready to send"
  - Extra: 4506 second refund REFUSED by R-REF-05; 350 → APPROVED by finance; 600 → REFUSED by finance
- Real DB: `callverse/data/shopnova.db` mtime `16:56:17.54` and MD5 `4ada37f1…49b1` are the same before and after the
  test suite. The MD5 is also unchanged after the demo, because the final re-seed is byte-for-byte deterministic.

## 4. Problems
- **Process**: when I started, `tasks/NEXT_PLATFORM.md` still showed P01 *WAITING FOR REVIEW*, with no READY/approval
  line for P02. I did P02 because it was asked directly, and I set NEXT_PLATFORM to P02.
- `check_condition` is about 35 lines, a bit over the ~30 the task suggested. It is general on purpose, so the
  conditions stay written only in the policy file and are not copied into code. The Coordinator can reuse it.
- `check_condition` raises `ValueError` for a missing fact (for example, R-RET-01 needs `days_since_delivery`, which
  nothing computes yet). The caller must catch it, or the platform could add that fact to `get_tracking` later.
- The demo's Layer 3 extra uses order 4513 with 350 / 600 TND, more than it was paid (189). The stub only looks at
  the amount, as the task asks; the Coordinator would refuse such amounts earlier with R-REF-05.
- `by` is `None` when the decision is `not_required` (finance is not involved). The task did not say what to use.

## 5. Questions for the Brain
1. Is `by: None` for `not_required` OK, or should it be `"platform"`?
2. Should the platform compute `days_since_delivery` (for R-RET-01) in `get_tracking`? It would add one field to a
   tool shape, so I did not do it.
3. Should the Coordinator task reuse `check_condition` from `callverse/kb/policies.py`, or have its own?
4. Policy wording (now including the new R-REF-05 text): still waiting for Yassine's review.

## 6. Next step
Core task (Agent B + Coordinator): add `get_refunds` to B's allow-list; the Coordinator reads facts with the platform
tools, checks conditions with `check_condition`, calls `layer3_decide` above 300 TND, then `create_refund` /
`create_subscription`. Then the notifier: read the `events` rows that match `waiting` subscriptions (the same query as
the S3 demo) and mark them `sent`.

Git: committed on `platform` (`95d3c2b`) and pushed to `origin/platform` (GitHub access works now; P01 commits are on the remote too). Not merged into `main`.
