# T14b — Reply-writer fixes, hidden fields, off-topic opener, Intake fallback (ShopNova)

## Why
T14a made "no + the reason" work. What is left from the T14 list on the **ShopNova** side are small problems seen in live
runs: the writer prompt forces "order N" in the first sentence (stray sentence); status decisions pass raw facts
(promised_date, days_late = 0, carrier) and the small model comments on them, sometimes wrongly; since T10 the writer
does not see the user's text, so it lost the language hint; the prompt example "order 1234" was copied once; `layer3_pending`
has no guide; agents see fields they do not need (source, source_id, city, payment); the off-topic reply starts oddly;
and the Intake LLM fallback can still say `cancel_order` without the word "cancel". All details approved by Yassine
2026-11-01 ("approved", options ⭐). Atlas declines, the smarter negative-sentence check (incl. the T14a h08 case) and the
R-DMG-01 > 300 TND proof flag are **T14c**, not here.

## Hard limits
- **ShopNova only.** Atlas prompts, tools and behaviour unchanged (all Atlas tests still pass).
- **Decisions, rules and amounts do not change.** Only words, what the writer / agents see, and the Intake fallback.
  The Coordinator still reads the full order row from the database (cash on delivery etc.). Agents still never write.
- **Real data first (CLAUDE.md rule 10):** the 12 practice messages in `tests/dev/t14b_practice_messages.json` are real
  TWCS tweets chosen by the Brain. Do not edit their text. The T14a sets are **not** reused and no new held-out run happens
  in this task (the new held-out is run once at the end of T14c).
- Never read `.env`. Tests: 0 API calls. Stop if free RAM < 300 MB. Ollama running before the live run.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (main must contain T14a). Branch `feature/t14b-writer-fixes`.
   Commit first: this task file, `tasks/NEXT.md` (IN PROGRESS), `tests/dev/t14b_practice_messages.json`.
1. **"Before" run** (code unchanged). `CALLVERSE_AGENTS_SET=local`, B on Groq (quota guard first). Extend the T14a runner
   (`scripts/run_decline_check.py`, or a tiny wrapper) to read the new keys: `expect` (outcome, rule_id, refund_rows,
   order_status, refund_amount — as now), `review` (no expect), and **`reply_must_not_contain`** (whole-word,
   case-insensitive check on the final reply). Run the 12 messages once, each on a fresh database. Save
   `out/t14b_before.json`. This is the baseline for the comparison; it fixes nothing.
2. **Writer prompt** (`callverse/slm/writer.py`, ShopNova prompt only):
   a. Remove the rule "Mention the order number in the FIRST sentence" and the forced opener in `ensure_order_reference`.
      The order number appears where the code-written text (`must_say` / `next_step`) has it. **Keep the check** that no
      *wrong* order number is in the reply (and the template fallback unchanged). If a reply ends without any order number
      and the decision has none in its words, say so in the report; do not add a sentence for it.
   b. Replace the example "order 1234" with a placeholder (e.g. "order <ORDER_NUMBER>") in the ShopNova prompt examples.
   c. Add a short dedicated guide for `layer3_pending` (the case is passed to finance / a person; say it is passed on and the
      user will be told; **no time promise, no amount, no rule id unless in `must_say`**).
3. **Facts whitelist.** For each ShopNova decision type, pass the writer only the facts that decision needs. First **list the
   facts passed today per decision type** in the report; then apply: `promised_date`, `days_late`, `carrier` and other
   order details are passed only when they are inside `must_say` / `next_step` (or `days_late` only when > 0 and the
   decision is about lateness). Amounts (`amount_tnd`) stay. List the final whitelist in the report for the Brain's OK.
4. **Language code.** Check whether Intake already returns a language. If yes, pass it to the ShopNova writer prompt
   ("write the reply in <language>") — a prompt line only when it is not English. If Intake has none: add a small pure-
   Python detector (stop-words for en / fr / es / it / de / ar-script; no new package) in `callverse/intake/`, default
   "en" when unsure, and say so in the report. The checker for numbers is unchanged. Offline test: a fake `chat_fn`
   asserts the language line is in the prompt for "fr" and absent for "en".
5. **Hide fields from agents.** In the ShopNova tool results (`callverse/tools/shopnova_tools.py` / `registry.py`) remove
   `source`, `source_id`, `city` and `payment` from what Agent A and B see (also inside `ask_agent` answers). The database,
   Coordinator and `writes.py` still read them. Offline tests: tool outputs lack these keys; cash-on-delivery cancel and
   refund tests still pass; Atlas tools unchanged.
6. **Off-topic opener.** Run p11 and p12 on the current code (they are in the "before" run). Read the two replies and
   the T17 report note (F4, "odd off-topic opener"). Fix the opener by the smallest change (code, not a bigger prompt):
   an off-topic reply should say sorry-free, calm, one scope sentence (the existing `off_topic_decision` text) and nothing
   odd before it. If the "before" replies show no problem, say so plainly and change nothing.
7. **Intake LLM fallback** (`callverse/intake/llm_fallback.py`): if the fallback returns `cancel_order`, accept it only when a
   sentence of the user's message contains "cancel"/"cancle" and the sentence does not match the not-an-order list
   (same two regexes as `reasons.py`; import them, do not copy); otherwise use the next-best reason / `other`. Offline test.
8. **Offline tests (0 API)** for steps 2–7 (every item). All tests pass (1122 before + new). Then re-measure **Intake on
   val** (T24 `pc_check`, original val): macro-F1 ≥ 0.391 and critical ≤ 29; report the numbers.
9. **"After" run.** Same 12 messages, once, same setup. Fix only through code (CLAUDE.md fix rule), at most **one** re-run.
   Save `out/t14b_after.json`. Report a table per message: outcome, rule, writes, seconds, Groq tokens, before reply,
   after reply (full text), hard-check result. Reseed both databases and delete `callverse.db` after.
10. **Non-English candidates (read-only helper, small).** Write `scripts/find_twcs_non_english.py` in the style of
    `scripts/build_twcs_candidates.py` (chunked, English filter reversed, shop brands only, simple stop-word guess of
    es / fr / it / de, @handles and links removed). Output `data/raw/twcs/lang_candidates.json` (git-ignored, ≤ 15 per
    language, tweet_id + brand + text). Run it; **do not use the tweets in any test** (the Brain picks later). If the
    zip has too few, report the counts.
11. **Docs.** `docs/decision_format.md` (facts whitelist), `DATA_LICENCES.md` (T14b practice set = TWCS, CC BY-NC-SA 4.0),
    README (CLAUDE.md rule 8).

## Pass bar and checks
- **Hard (all 12):** 0 crashes, 0 leaks, 0 wrong writes, 0 `reply_must_not_contain` hits.
- **Expected (8 messages with `expect`: p01–p04, p06, p07, p09, p10):** ≥ 7/8.
- **Brain reads all 12 "after" replies** (and compares with "before"): no stray order sentence, no comment on raw facts, no
  hidden field, calm off-topic. The 4 `review` messages (p05, p08, p11, p12) have no pass/fail; the Brain judges.
- Numbers to report: tests x/y; Intake val before/after; practice before vs after table; seconds avg / max; Groq tokens;
  `git status` clean of `models/`, `data/raw/`, `.env`.
- One sentence: is it safe for the demo?

## Time box and stop rule
**3 h.** Stop and report if: a test fails and cannot be fixed inside the task, Intake val macro-F1 < 0.391 or critical > 29,
the "after" run would be needed a third time, free RAM < 300 MB, or Groq's daily limit answers (abort unscored; the
"before" and "after" runs together use about 130k of ~200k tokens/day, so run the second one only if the quota allows).
**If Yassine has to leave:** stop at a safe point, write `tasks/T14b_progress.md`, commit "T14b WIP: …" and push.

## Git
Commit and push `feature/t14b-writer-fixes`. **No merge into `main`** (Yassine merges after the Brain's review). Write
`tasks/T14b_report.md` (In plain words · Done · Evidence · Problems · Questions for the Brain · Next step) and set
`tasks/NEXT.md` to WAITING FOR REVIEW. Last step: README (CLAUDE.md rule 8).
