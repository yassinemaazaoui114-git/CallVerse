# T14b report — Reply-writer fixes, hidden fields, off-topic opener, Intake fallback (ShopNova)

Branch `feature/t14b-writer-fixes` (from `main` 73e4a0b, which contains T14a). **Not merged.** Time used: well inside the 3 h box.

## 1. In plain words
The ShopNova reply writer now only words what the Coordinator already decided, and it has fewer ways to say something odd:
it is no longer forced to open with "order N", it is shown only the facts it needs (no "0 days late", no carrier, no promised
date unless a fixed sentence already says it), and it is told the client's language when it is not English. The agents no
longer see the database labels and the city / payment fields. The off-topic reply no longer starts with a pointless apology.
The Intake backup model can only say "cancel this order" when the client's own words contain "cancel". Decisions, rules
and amounts did not change. On the 12 real practice tweets all hard checks pass (12/12, 0 crashes, 0 leaks, 0 wrong writes);
two of the 12 are not yet what they should be (see Problems: p07 and the English-only fixed sentences for other languages).

## 2. Done
| Step | What | Files |
|---|---|---|
| 0 | Branch from `main`; first commit = task file, NEXT.md, practice messages | — |
| 1 | "Before" run (code unchanged). Runner extended: `reply_must_not_contain` (whole word, case-insensitive), `review`, `--out`, off-topic messages without an order, partial results saved after each message, **layer3 queue mode like the app** | `scripts/run_decline_check.py` |
| 2a | Rule "order number in the FIRST sentence" removed from the ShopNova prompt; forced "Your first sentence must contain…" line and `ensure_order_reference` removed for ShopNova (Atlas keeps both); upset-client text says "Start directly with the content" for ShopNova. Check: a reply may omit the order number, but a **wrong** one ("order 4511" in a reply about 4510) now fails | `callverse/slm/writer.py`, `callverse/slm/check.py` |
| 2b | Prompt example uses `order <ORDER_NUMBER>` (and the example reply no longer names the order) | `writer.py` |
| 2c | Own guide for `layer3_pending` (passed to finance, client told here; no time, no amount/rule beyond `must_say`, no "approved"/"will be paid"). Before, it fell back to the "info" guide | `writer.py` |
| 3 | Facts whitelist `writer_facts` (table below and in `docs/decision_format.md`) | `writer.py`, `docs/decision_format.md` |
| 4 | **Intake had no language** → new pure-Python detector (stop-words en/fr/es/it/de, Arabic by script; default `en`), `ticket["language"]` → `reply_style` → prompt line "The client writes in French: write the reply in French…" (only ShopNova, only if not `en`; the "Write in English" rule is replaced then) | `callverse/intake/language.py`, `intake.py`, `pipeline.py`, `writer.py` |
| 5 | Agents / Intake no longer see `source`, `source_id`, `city`, `payment` (also inside lists, e.g. refund rows). Done in the registry, so the Coordinator, `writes.py` and the apps still read full rows | `callverse/tools/registry.py` |
| 6 | Off-topic: the "before" replies were *"I'm sorry for the trouble. I can help with your ShopNova orders…"* — the calm opener (negative sentiment) in front of the scope sentence. Fix by code: no opener for the ShopNova redirect decision; and a proper template for it (the generic template said "here is the latest information" and put the next step *before* the sentence) | `callverse/slm/templates.py`, `writer.py` |
| 7 | Intake LLM fallback: `cancel_order` accepted only if a sentence has the cancel word and no subscription/account word (imports `CANCEL_WORD_RE`, `NOT_AN_ORDER_RE` from `reasons.py`); else the next reason of its list, else `other`. Atlas untouched | `callverse/intake/llm_fallback.py` |
| 8 | 54 new offline tests; 3 old tests updated on purpose (see Evidence) | `tests/test_t14b.py`, `tests/test_slm.py`, `tests/test_routing_by_company.py` |
| 10 | `scripts/find_twcs_non_english.py` run; output `data/raw/twcs/lang_candidates.json` (git-ignored, ≤ 15 per language, **not used in any test**) | `scripts/find_twcs_non_english.py` |
| 11 | Docs: `docs/decision_format.md`, `DATA_LICENCES.md`, README | — |

### Facts passed to the writer per decision type
**Before T14b** the writer was shown the whole `facts` dict of the decision. **Now (whitelist for the Brain's OK):**

| Decision | Facts in the decision (before) | Shown to the writer (now) |
|---|---|---|
| `info` / status | `order_status`, `days_late`, `promised_date`, `carrier` | `days_late` only if > 0; others only if their value is inside `must_say`/`next_step` |
| `info` / redirect (off topic) | none | none |
| `decline` R-REF-03 | `order_status`, `days_late` (0), `promised_date` | `promised_date` (it is in the sentence); `days_late` 0 hidden |
| `decline` R-REF-05 | `order_status`, `amount_tnd` | `amount_tnd` |
| `decline` R-RET-01 / R-CAN-01 | `order_status`, `days_since_delivery` | `days_since_delivery` (in the sentence) |
| `ask_user` cancel / `ask_proof` | `order_status` | none |
| `approve` refund / cancel | `order_status`, `days_late`, `amount_tnd`, `days_since_delivery`, `layer3_decision`, `threshold_tnd` | `amount_tnd`, `layer3_decision`, `threshold_tnd`; `days_late` for R-REF-03 if > 0 |
| `approve` subscribe | `order_status`, `days_late`, `event` | `event` (+ `days_late` for R-DEL-02 if > 0) |
| `layer3_pending` / `layer3_refused` / `escalate` | `order_status`, `days_late`, `amount_tnd`, `layer3_decision`, `threshold_tnd` | `amount_tnd`, `layer3_decision`, `threshold_tnd` |

Rule in code: always shown = `amount_tnd`, `event`, `layer3_decision`, `threshold_tnd`, `needed`; `days_late` = only if > 0 **and**
the decision is about lateness (`action` = status, or rule R-REF-03 / R-DEL-02); any other fact = only if its value is in
`must_say`/`next_step`. The **checker still uses the whole decision** (numbers allowed, carriers allowed), and the template
fallback is unchanged. Atlas facts are passed unchanged.

## 3. Evidence
**Tests:** 1122 → **1176 passed, 0 failed** (+54 in `tests/test_t14b.py`; 0 API calls). Updated on purpose:
`test_routing_by_company` — the two ShopNova **writer** fingerprints were renewed (the prompt and the messages changed by design);
`test_slm` — the case "reply without order number fails" became "wrong order number fails" (ShopNova). Proof that **Atlas is
unchanged**: `test_the_atlas_writer_is_byte_identical_to_the_code_before_t14b` checks the Atlas prompt and its messages (calm and
upset) against hashes computed with the writer of `main`; the Atlas tools, fallback and checker rules have their own tests.

**Intake on val (T24 `pc_check`, original val), ShopNova:** before (main) macro-F1 **0.4108**, critical **26** → after **0.4117**,
critical **26** (bar: ≥ 0.391 and ≤ 29 → OK). `reasons.py` was not touched; the 0.0009 difference is run noise. Atlas 0.8838 / 1, same.
`benchmarks/m3/results/pc_check.json` restored to main's version.

**Practice set (12 real TWCS tweets), summary**

| | Before (`out/t14b_before.json`) | After (`out/t14b_after.json`) |
|---|---|---|
| Hard checks (0 crashes, 0 leaks, 0 wrong writes, 0 forbidden words) | 12/12 | **12/12** |
| `expect` messages (p01–p04, p06, p07, p09, p10) | 7/8 (p07 failed only because the runner was in *stub* mode; see Problems) | **8/8** |
| Seconds avg / max | 11.2 / 19.0 | **9.4 / 18.5** |
| Groq tokens | 29,391 | 29,744 |
| Reply source | all `slm` | 10 `slm`, 2 `template` (p11, p12) |

**Per message** (outcome · rule · writes · seconds · Groq tokens; hard check = PASS for all 12 in "after"). Replies are the full text.

| id | Outcome · rule · writes | s | tokens | Before reply | After reply |
|---|---|---|---|---|---|
| p01 | info · – · none | 18.5 | 0 | I'm sorry for the trouble. Your order 4510 is on its way. | *same* |
| p02 | info · – · none | 9.4 | 0 | I'm sorry for the trouble. Your order 4513 is on its way. | *same* |
| p03 | info · – · none | 10.1 | 0 | I'm sorry for the trouble. Your order 4505 is delivered. | *same* |
| p04 | info · – · none | 10.3 | 0 | I'm sorry for the trouble. Your order 4511 is being prepared. | *same* |
| p05 | approve · R-REF-03 · refund 59.90 | 6.5 | 8,290 | I'm really sorry for the trouble. Your refund of 59.90 TND is approved. Your order 4512 is now refunded. | *same* |
| p06 | info · – · none | 10.0 | 0 | I'm sorry for the trouble. Your order 4512 is delayed at the delivery depot. **The carrier is Rapid-Poste, and it is 6 days late.** | I'm sorry for the trouble. Your order 4512 is delayed at the delivery depot. |
| p07 | info · – · none (see Problems) | 5.6 | 7,405 | *(queue-mode baseline)* I'm sorry for the trouble. Your refund of 378.00 TND for order 4515 needs approval from our finance team. We will reply here as soon as it has been reviewed. | I'm sorry for the trouble. Your order 4515 is delayed at the delivery depot. |
| p08 | decline · R-RET-01 · none | 6.0 | 6,143 | I'm sorry for the trouble. Returns are possible within 14 days of delivery. Order 4509 was delivered 15 days ago, so it can no longer be returned. | *same* |
| p09 | decline · R-RET-01 · none | 5.4 | 4,834 | I'm really sorry for the trouble. **There.** Returns are possible within 14 days of delivery. Order 4508 was delivered 16 days ago, so it can no longer be returned. **Thank you for understanding.** | I'm really sorry for the trouble. Returns are possible within 14 days of delivery. Order 4508 was delivered 16 days ago, so it can no longer be returned. |
| p10 | decline · R-REF-05 · none | 4.2 | 3,072 | I'm sorry for the trouble. Order 4506 has already been fully refunded (189.00 TND), so no further refund is possible. | *same* |
| p11 | info (off topic) · – · none | 15.0 | 0 | **I'm sorry for the trouble.** I can help with your ShopNova orders: delivery, refunds, returns and damaged items. If your question is about an order, please send us the order number. | Hello, I can help with your ShopNova orders: delivery, refunds, returns and damaged items. If your question is about an order, please send us the order number. |
| p12 | info (off topic) · – · none | 11.5 | 0 | *as p11 (before)* | *as p11 (after)* |

(The T14b task asked for the "after" run once, with at most one re-run. I used it: the first "after" run (`out/t14b_after_run1.json`)
had the two off-topic replies on a clumsy template — "Hello, here is the latest information. If your question…" — which I fixed in
`templates.py`; the table above is the second run.)

**Extra evidence for `layer3_pending` (p07 only, current code, 2 diagnostic runs, `out/t14b_p07_diag_1.json`, `_2.json`):** both gave
`layer3_pending`, refund rows 0, reply *"I'm sorry for the trouble. Your refund of 378.00 TND for order 4515 needs approval from
our finance team. We will reply here as soon as it has been reviewed."* (the new guide's output, 7.1–8.4 s).

**Non-English candidates** (`data/raw/twcs/lang_candidates.json`, 15 per language written): found for shop brands — **es 2,870, fr 4,150,
it 659, de 1,875** (all from AmazonHelp-type accounts, real tweets; the language is a stop-word guess: a few Portuguese tweets
appear under "it"). Not used in any test.

**Order number in the replies:** in all 10 order replies of the "after" run the number is present (it is inside the fixed
sentences). A reply can end without any number when the decision has none in its words: an approved refund whose status did not
move (`next_step` empty and `must_say` = "Your refund of X TND is approved."), `ask_proof` ("Please send us a photo…"), `escalate`.
By the task's rule nothing is added for these.

**Git:** `git status` has no `models/`, `data/raw/`, `.env`. Both databases reseeded, `callverse/data/callverse.db` deleted
(it was git-ignored). Not mine and left untouched: `.vscode/`, `tasks/RL2b_followup.md`.

## 4. Problems
1. **p07 in the official "after" run did not reach the finance queue.** Agent B (Groq) wrote "I am sending a refund proposal for
   checking" but never called `propose_refund` (the known "claims a proposal without the tool" slip; T13c's safety net
   `pipeline.proposal_claim_retry` exists but is **off** by default). It happened in both full "after" runs, never in the 4 other
   runs of p07 (the stub-mode baseline, the queue-mode baseline and my 2 p07-only diagnostics). The hidden fields are not the cause as far as I can see (B got
   `get_order`, `get_refunds`, `ask_agent` and `search_policy` results as usual), but I cannot prove it with 6 samples. The hard
   checks and `expect` pass (nothing written, status unchanged), and the reply is true ("your order is delayed at the depot"), but it
   does not mention the refund the client asked about. Not fixed here: it is the agent layer, not T14b's scope.
2. **The baseline p07 in the first "before" run failed** because `run_decline_check` used the stub Layer 3 (auto-approve) while the
   app uses the queue. I made the runner `setdefault` queue mode like the app, and re-ran **only p07** on the unchanged code
   (git stash) for the baseline: `out/t14b_before_p07_queue.json`. The other 11 "before" results are from the stub-mode run (the mode
   does not matter for them). The very first "before" attempt crashed on p11 (`get_order(None)`) and lost its results — the runner
   was fixed (and now saves after each message).
3. **Off-topic goes through the template.** The 1.5B model writes "returns, **and** damaged items" (extra comma), so the word-for-word
   check fails twice and the template (now clean) is used. The reply is right, but it costs two SLM calls (~11–15 s). Option: no SLM call
   for this decision (the text is fixed anyway).
4. **Language is only a prompt line.** The fixed `must_say` / `next_step` sentences are English, so a French client would get a
   French wrapper around English key sentences. The detector is tested offline; **no live non-English message was run** (not in the practice set).
5. **"I'm sorry for the trouble." on a plain status answer** (p01–p04) is the existing calm opener for negative sentiment, unchanged.
6. Groq daily budget: about 165k of ~200k tokens used today by the lost first run + baselines + runs; no limit was hit.

## 5. Questions for the Brain
1. **Order-number check:** I replaced "the order number must be in the reply" by "no wrong order number" for ShopNova (otherwise a reply
   without the number would fail twice and fall to the template, which defeats step 2a). OK? (Atlas keeps the old check.)
2. **Hidden fields:** the ask_agent answer has a key `"source": "get_tracking"` (a provenance label written by `ask.py`, *not* the
   database field). I kept it: it tells B the facts came from a tool. Do you want it renamed or removed too? The labels `ai_generated`
   and `scripted` are still visible to the agents; hide them as well?
3. **p07:** switch on `pipeline.proposal_claim_retry` (T13c net, one more agent run, writes nothing)? Or accept it as agent variance?
4. **Off-topic:** skip the SLM for this fixed text (saves ~11 s, same reply as the template)?
5. **Languages:** translate the fixed key sentences for fr / es / it / de, or keep them English with a translated wrapper?
   The candidates are ready (`lang_candidates.json`) when you want to pick test messages.
6. `docs/decision_format.md` lists the whitelist; please confirm it (step 3 asks for your OK).

## 6. Next step
Brain reads the 12 "after" replies and the whitelist, answers the questions, then **T14c** (Atlas declines, smarter negative-sentence
check incl. the T14a h08 case, R-DMG-01 > 300 TND proof flag) with the one new held-out run at its end.

**Is it safe for the demo?** Yes for ShopNova: every hard check passes, nothing is written wrongly and no internal word or hidden field
appears in any reply; the one weak spot is p07, where the agent sometimes skips the refund proposal (the reply stays true, only less helpful).
