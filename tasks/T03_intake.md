# T03 — Intake: semantic understanding + sentiment + priority

## Why
Users describe the same problem in very different words. Intake must understand each message **by meaning**
(teacher's requirement: semantic + sentiment), find the order, and give a **priority based on the real
situation** — not on how angry the user sounds. Its output (a labelled ticket) is what the Queues will route.
Intake is a fixed pipeline, **not an agent**.

## Hard limits
- **Never tune on test data.** `tests/data/intake_test_messages.json` is held out: use it only in the final
  evaluation. Build and choose thresholds using `callverse/intake/data/reason_examples.json` only
  (e.g. leave-one-out on the examples). Both files are already written by the Brain — do not edit them.
- Models: M3 = `BAAI/bge-small-en-v1.5`; M4 = `j-hartmann/emotion-english-distilroberta-base` (emotion) and
  `cardiffnlp/twitter-roberta-base-sentiment-latest` (sentiment). All local, CPU. M2 (`llm.chat("agents")`)
  only for unclear messages.
- New libraries allowed: `sentence-transformers`, `transformers`, `torch` (CPU build), `numpy`.
- Intake reads facts only through the existing read tools (`get_order`, `get_tracking`); it never writes data.
- Do not change agents, tools or the LLM layer.

## What to do
1. `callverse/intake/reasons.py` — embed the examples once (cache vectors to a git-ignored file);
   `match_reasons(text)`: split into sentences, score each sentence against each reason (mean of the top-3
   cosine similarities), keep reasons above a threshold → list of `{reason, score, sentence}` (several reasons
   = several sub-cases). Choose the threshold by leave-one-out on the **examples**; record its value in the report.
   If no reason passes, set `needs_llm = True`.
2. `callverse/intake/llm_fallback.py` — for `needs_llm` only: ask M2 for JSON `{"reasons": [...], "order_id": ...}`
   restricted to the 6 reasons; validate the JSON; if invalid → reason `other`.
3. `callverse/intake/sentiment.py` — emotion (label + score) and sentiment (label + score) with the M4 models.
4. `callverse/intake/extract.py` — order number (`#?` + 4–6 digits), email, phone, with regular expressions.
5. `callverse/intake/priority.py` — all weights in `config.yaml` (section `intake.priority`), so they can change later
   without changing the objective:
   - severity (0–1): base by reason (order_status 0.2, late_delivery 0.5, refund_request 0.5, return_item 0.3,
     damaged_item 0.6, other 0.2) + 0.3 if days_late > 5 + 0.2 if amount paid > 300; max 1.
   - time_pressure (0–1): min(days_late / 7, 1); 0 if no order or not late.
   - emotion_intensity (0–1): negative-sentiment score.
   - priority = 0.6·severity + 0.25·time_pressure + 0.15·emotion_intensity; label high ≥ 0.6, medium ≥ 0.35, else low.
6. `callverse/intake/style.py` — style profile: formality (formal / neutral / casual), length (short / medium / long),
   exclamation and capitals (shouting) flags. Simple rules, explained in comments.
7. `callverse/intake/intake.py` — `process(text) -> ticket` combining all of the above; every step traced. Ticket:
   `ticket_id, text, order_id, email, phone, reasons[], main_reason, emotion, sentiment, facts{days_late, delivered,
   paid}, severity, time_pressure, emotion_intensity, priority_score, priority_label, style, needs_llm`.
8. `scripts/run_intake.py "<message>"` prints the ticket readably. `scripts/eval_intake.py` runs the held-out test set
   and prints the results table (per message: expected vs found reasons, order id, priority).
9. Tests (no API calls; models may run locally): extraction, priority formula on fixed numbers, style rules,
   and the priority pair (calm 4512 refund > angry 4510).
10. Housekeeping: `.gitattributes` (text files `eol=lf`, `*.bat` / `*.ps1` `eol=crlf`); add the vector cache to `.gitignore`.

## Checks (with numbers)
- Reason accuracy on the 20 held-out messages: **≥ 17/20** exact match of the reason set (report each miss).
- Multi-reason messages (t18, t19, t20): **3/3** contain both expected reasons.
- Order number found in **6/6** test messages that contain one.
- Priority pair p01: calm 4512 refund **> ** angry 4510 (report both scores and labels).
- Speed on CPU after loading: average Intake time per message **< 1 s** (report average, and model load time).
- `needs_llm` count on the test set (report the number; M2 calls are allowed only for those).
- Old tests still pass + new tests pass (report x/y).

## Time box and stop rule
2 hours. If accuracy is below 17/20, do **not** change the test set or tune on it: report the misses and stop.
If a model will not download or install, stop and report the error.

## Git (approved by Yassine, 2026-10-20)
- From the latest `main`, create branch `feature/intake`.
- Commit on that branch: T02 report + NEXT.md update, `.gitattributes`, and all T03 work. Push `feature/intake`.
- **Do not merge into `main`.** Merge happens after the Brain's review and Yassine's OK.
