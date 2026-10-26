# CallVerse satisfaction labelling — rubric, guidelines, adjudication (v5)

**Status:** proposal, ready to use. Nothing has been labelled. Builds on `v4/f/ANNOTATION_PROTOCOL.md`
(consent, PII redaction, storage, sample-size table): those sections still apply and are not repeated here.
What v5 adds: an anchored rubric, explicit decision rules, an adjudication step, a sampling plan with
oversampling and weights, a sheet template and an import/evaluation script.

## 1. The question you answer

> "If you were this client, how satisfied would you be with **how your request was handled** in this
> conversation?"

- Rate the **support interaction**, not the product, the shop, or the policy itself.
- Read only what the client saw: the client's messages and the replies the client received.
  You never see the internal trace, Agent F's score, the M7 flags or why the conversation was sampled.
- Read the whole conversation once before you rate it. Take about 1–2 minutes.

## 2. The 1–5 rubric (anchored)

| Score | Name | The client's request… | Typical signs |
|---|---|---|---|
| **1** | Very dissatisfied | was ignored, answered wrongly, or made worse | wrong facts about the order; a promise that is then contradicted; reply in a language the client cannot read; client insulted or blamed |
| **2** | Dissatisfied | was not solved, and the reply gives no useful next step | generic reply that does not address the question; asks for information the client already gave; repeated unhelpful replies |
| **3** | Neutral / partly handled | was partly handled, or correctly refused with a reason, but with friction | correct but vague; correct refusal with little explanation; client must come back; slow or cold tone |
| **4** | Satisfied | was handled correctly, with a clear answer or a clear next step | accurate status; refund/notification done or clearly explained; polite |
| **5** | Very satisfied | was handled correctly, completely and with care | everything in 4, plus anticipates the next question, empathy matching the client's tone, nothing left open |

## 3. Decision rules (apply in this order)

1. **Correctness first.** A polite reply with a wrong fact or an unkept promise is at most **2**.
2. **A correct refusal is not a failure.** If the policy does not allow what the client asked and the reply says so
   clearly and gives the reason or the next step, rate **3–4**, not 1–2.
3. **Language.** A reply in a language the client did not use is at most **2** (the client may not understand it).
4. **Tone adjusts by at most one point.** Tone alone never moves a score by two points.
5. **Unsure between two scores?** Pick the lower one only if a concrete problem from the table applies;
   otherwise the higher one. Write the reason in `comment` and set `confidence_low_med_high = low`.
6. **Cannot judge** (empty reply, text unreadable, conversation cut): leave `rating_1to5` empty and fill
   `cannot_judge_reason`. Never guess.
7. **Do not** use outside knowledge of ShopNova, do not look up the order, do not discuss items with other
   annotators before the adjudication step.

## 4. Procedure

1. **Pilot (30 conversations, all 3 annotators):** rate, then one calibration meeting on the disagreements;
   the rubric is updated once. Pilot labels are never used for evaluation (`split = pilot`).
   **Stop rule:** pilot Krippendorff α (ordinal) < 0.40 → revise the rubric before the main set.
2. **Main set:** every conversation rated by all 3 annotators, independently, in their own shuffled order
   (one sheet per annotator, `sheet_<ANN>.csv`).
3. **Import and check:** `python -m v5.f.labelling.import_eval ...` validates the sheets, converts them to
   annotator records of the reviews contract (`v4/f/contracts/`), computes agreement and writes the
   **adjudication queue**.

## 5. Adjudication (disagreement resolution)

- **Which items:** ratings spread ≥ 2 points, **or** the ratings straddle the dissatisfied line
  (one annotator ≤ 2 and another ≥ 3). These are the cases where the mean is least trustworthy and where the
  dissatisfied class — the one Agent F misses most — is decided.
- **Who:** one adjudicator who is not one of the 3 annotators and not a developer of Agents A/B/F; blind to
  Agent F's score and to the M7 flags.
- **How:** the adjudicator reads the conversation and the three ratings with their comments, applies the
  decision rules of §3, and writes one final integer 1–5 plus a one-line reason in `adjudication_queue.csv`.
  Annotators' original ratings are **kept unchanged**.
- **Storage:** adjudicated labels go to `adjudicated.jsonl` with `label_source = adjudicated_human`. They are a
  third label kind, separate from annotator records and **never mixed with customer-submitted ratings**
  (the v4 contract keeps `customer_submitted` and `annotator` apart; adjudicated labels live in their own file).
- **Reported gold labels:** (a) mean of the annotators (comparable with USS; it is what the v4 card and the
  F→E gate read) and (b) adjudicated label where one exists, else the mean. Both are reported.
- Items with a spread ≥ 3 are also listed for the next rubric revision.

## 6. What these labels can and cannot do

- They validate Agent F on the right **domain** (CallVerse conversations, French and English) as an
  **annotator** judgement. They do **not** open E's reward: the gate needs genuine customer ratings
  (`v4/f/m7/feedback_v4.py`); changing that is a Brain decision.
- Never accepted as labels: LLM or model ratings, Agent F's own scores, M7 flags, scripted or simulated
  conversations, the priority stratum used for sampling.
