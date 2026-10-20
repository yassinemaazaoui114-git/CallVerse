# T03 report — Intake: semantic understanding + sentiment + priority

## 1. In plain words
Every client message now goes through Intake first. Intake turns the message into a "ticket": why the
client writes (one or more reasons, found by meaning, not by keywords), the order number, how the client
feels, how they write, and a priority. The priority comes mostly from the real facts read in the database
(how late the order is, how much was paid), so a calm client with a very late order goes before an angry
client whose order is on time. On 20 test messages kept aside until the end, Intake found exactly the
right reasons for 18 of them.

## 2. Done
New files (all in `callverse/intake/` unless noted):
- `extract.py` — order number, email, phone by regular expressions (amounts, dates and phone numbers are not taken as order numbers).
- `reasons.py` — embeddings (M3, bge-small) of the Brain's examples, cached in `data/reason_vectors.npz` (git-ignored,
  rebuilt automatically if the examples or the model change); `match_reasons()`; `leave_one_out()` for the threshold.
- `llm_fallback.py` — M2 (`llm.chat("agents")`) only when no reason passes; JSON validated, restricted to the 6 reasons; invalid → `other`.
- `sentiment.py` — emotion (j-hartmann) + sentiment (cardiffnlp), local CPU; negative score = emotion_intensity.
- `priority.py` — the formula of the brief; all numbers in `config.yaml` → `intake.priority`.
- `style.py` — formality, length, exclamation, shouting (simple rules, explained in comments).
- `intake.py` — `process(text) -> ticket`, 7 steps, every step traced (`intake_*` steps + `tool_call` by actor `intake`).
- `scripts/run_intake.py`, `scripts/eval_intake.py`, `scripts/choose_threshold.py` (leave-one-out on the examples).
- `tests/test_intake.py` — 20 tests (extraction, priority formula on fixed numbers, style, LLM JSON validation with a
  fake LLM, priority pair with my own two messages, ticket fields). No API call.

Changed: `config.yaml` (new `intake` section: model names, top_k, threshold, priority weights) ·
`requirements.txt` (torch CPU, transformers, sentence-transformers, numpy) · `.gitignore` (vector cache) ·
new `.gitattributes` (LF, CRLF for .bat/.ps1) · `README.md` and `docs/architecture.md` (status lines only) ·
`callverse/intake/__init__.py` (docstring).
Not changed: agents, tools, registry, LLM layer, the examples file, the test file.

Decisions I made (please confirm, see Questions):
- **Best reason per sentence** instead of "every reason above the threshold" (see Evidence: 21/60 vs 47/60 on the examples).
- `main_reason` = the reason with the highest similarity score; **severity uses the most severe reason** found.
- `other` is dropped when a specific reason is also found.
- Intake calls `get_order` / `get_tracking` **directly** (it is not an agent, so it has no allow-list in the registry) and traces each call itself.
- `time_pressure` uses `days_late` from `get_tracking` as is, so a delivered-late order (e.g. 4507, 2 days) still gets a small time pressure.

## 3. Evidence

**Threshold, chosen by leave-one-out on the 60 examples only** (`python -m scripts.choose_threshold`):
| Rule | Best result on examples |
|---|---|
| Brief's literal rule: keep every reason ≥ threshold | best 21/60 exact (at 0.78: 10 wrong, 29 to LLM) — scores are all 0.6–0.85, so a sentence passes for several reasons |
| Best reason per sentence, if ≥ threshold (used) | **0.66 → 47/60 exact, 4 wrong, 9 to LLM** (argmax alone without threshold: 51/60) |

Pick rule: highest (exact − wrong), tie → fewest wrong. **reason_threshold = 0.66**, top_k = 3.

**Final evaluation on the held-out set — run once** (`python -m scripts.eval_intake`, trace `traces/run_20261020_170143_836338.jsonl`):
| Check | Target | Result |
|---|---|---|
| Reason accuracy (exact set) | ≥ 17/20 | **18/20** ✅ |
| Multi-reason t18, t19, t20 | 3/3 | **3/3** ✅ |
| Order number found | 6/6 | **7/7** ✅ (the file has 7 messages with an order id, not 6) |
| Priority pair p01 | calm 4512 > angry 4510 | ✅ **high 0.824** (sev 0.8, time 0.857, emo 0.862) vs **low 0.260** (sev 0.2, time 0, emo 0.934) |
| Speed after loading | avg < 1 s | **0.193 s** avg (max 1.073 s = a message with an M2 call); without M2: 0.05–0.15 s |
| Model load time | report | **7.6 s** (from local cache; first download took a few minutes) |
| needs_llm | report | **3** (t06, t16, t17) → 3 M2 calls |
| Tests | all pass | **34/34** (14 old + 20 new) |

Misses (reported, **not** tuned on):
- **t06** "Seriously?? Promised Friday, now it's Thursday the week after. Where is it?" — expected `late_delivery`.
  The late sentence scored 0.660 (just under the threshold) → M2 answered `late_delivery, order_status` (extra reason from "Where is it?").
- **t14** "Order 4507 arrived but the speaker has no sound at all, it's defective." — expected `damaged_item`, found
  `refund_request`: a tie, both at 0.726. The examples' refund sentences ("the order never came") are close to "arrived but…".

Example run: `python -m scripts.run_intake "Hi, my order 4512 is a week late. I want my money back!"` →
late_delivery (0.845) + refund_request (0.757), facts days_late 6 / paid 59.9, **HIGH 0.832**, 0.31 s.

## 4. Problems
- Scores of bge-small are compressed (most sentences score 0.6–0.85 against every reason), so reasons that are close in
  meaning (refund vs damaged, late vs status) can tie. More / more varied examples (written by the Brain, not from the
  test set) would help more than moving the threshold.
- Messages with two reasons in **one** sentence ("it's late so I want a refund") give only one reason, because each
  sentence keeps its best reason. The 3 multi-reason test messages had their reasons in separate sentences.
- The test set has been used once now; any further change to Intake should be measured on a **new** held-out set.
- Models are ~1 GB on disk the first time (HuggingFace cache, outside the repo). torch is large; requirements use the CPU-only index.
- The sentiment model prints a harmless "UNEXPECTED pooler weights" note when it loads.

## 5. Questions for the Brain
1. OK to keep **best reason per sentence** instead of the brief's "every reason above the threshold"? (21/60 vs 47/60 on examples.)
2. `main_reason` = highest score, severity = most severe reason: OK? Or should `main_reason` be the most severe one?
3. Should Intake get its own entry in the registry (allow-list `[get_order, get_tracking]`) instead of calling the read
   functions directly? It would need a small change in `tools/registry.py` (not allowed in T03).
4. `time_pressure` for a delivered order that was late: keep as now (uses days_late) or set to 0 once delivered?
5. Add 3–5 examples per reason that put two problems in one sentence, and for "damaged + arrived" phrasing?

## 6. Next step
Review and merge `feature/intake`, then the Brief #2 task (Queues router can now use `main_reason`, `reasons[]` and
`priority_label` from the ticket).

## Git
Branch `feature/intake` from `main` (fb187b5). One commit with the T02 report, NEXT.md updates, `.gitattributes` and all T03 work.
Pushed to `origin/feature/intake`. **Not merged into `main`.**
