# Annotation protocol — a small human-labelled set of genuine CallVerse closed conversations (PROPOSAL)

**Purpose:** validate Agent F's satisfaction score on the **right domain**: CallVerse / ShopNova closed
conversations, in French, Arabic and English. Today the score is validated only on USS (other dialogues, other
labels), and French is not validated at all.

**Status:** proposal only. Nothing has been collected. It needs Yassine's and the supervisor's approval, and the
university's data-protection rules.

**Evaluation code (ready, tested on a SYNTHETIC fixture only):**
- `v4/f/annotation/eval_labels.py`
- `v4/f/contracts/validate_reviews.py`
- tests in `v4/f/tests/test_contract_annotation.py`

## 1. What the labels can and cannot do (read first)

| Label kind | Who gives it | Validates the KPI use (owner report) | Opens E's reward (gate) |
|---|---|---|---|
| **Customer rating** (`customer_submitted`) | the person who had the conversation, right after it | yes | possible, if n ≥ 300 and the other checks pass |
| **Annotator rating** (`annotator`) | 2–3 trained people reading the closed conversation | yes | **no**: the gate requires genuine customer ratings (`v3/m7/feedback_e.py`, kept in v4). Changing that is a Brain decision. |

- So collect **both** when possible.
- The customer rating is the target.
- The annotator ratings measure how readable satisfaction is from the text. They also give a noise limit.

## 2. Where genuine conversations come from

- The prototype has **no real clients**. "Genuine" therefore means **real people** (volunteer testers) using the CallVerse demo channel (`callverse/server/demo.html`, chat or voice) on the ShopNova mock shop.
- Testers get a **scenario card** (an order number and a situation, e.g. "your order is 8 days late"). They write in their own words and their own language.
- Testers are not real ShopNova customers: their stakes are role-played. Report this as a limit.
- **Not genuine** (never used as labels):
  - simulator conversations (M1, Gemini);
  - the scripted M7 corpus;
  - anything with `is_test_or_synthetic = true`.
- **Target mix:** at least 40% French, about 20% Arabic, the rest English; all four intents (status, late / refund, damaged item, notification); calm and frustrated scenario cards.

## 3. Consent and ethics

- **Consent comes before the conversation**, with an information sheet. It explains:
  - the conversation is processed by AI agents;
  - it is stored as a trace;
  - it is read by 2–3 annotators;
  - it is used to evaluate a satisfaction model.
- **Separate tick-boxes** match the contract's `consent.scope`: `quality_reporting`, `model_validation`, `model_training`.
- Testers may withdraw until the set is frozen. Their records are then deleted (trace + labels).
- No minors. No real personal data: testers use the fake ShopNova identities from the scenario card.
- **The post-chat rating** (1–5, "How satisfied are you with how your request was handled?", optional comment) is stored as a `customer_submitted` record. The question asks about the **support interaction**, not the product.

## 4. PII redaction (before any annotator sees anything)

1. **Automatic pass**, regexes for:
   - e-mails and phone numbers (Intake already extracts them: `callverse/intake/extract.py`);
   - card-like numbers;
   - names that are not on the scenario card.
2. **Human check by one person who is not an annotator.** Their name goes in `pii_redaction.checked_by`.
3. **Status values:** `redacted` / `none_found` (contract field `pii_redaction.status`). A comment with `not_done` is never stored (contract rule R4).

## 5. Annotators, guidelines, procedure

- **Annotators:** 3 people. They are not the developers of Agents A/B/F, and they have no access to Agent F's scores (blind).
- **One guideline page.** The question: "If you were this client, how satisfied would you be with how the request was handled?" The scale:
  - 1 = very dissatisfied: wrong, unhelpful or ignored request;
  - 2 = dissatisfied;
  - 3 = neutral / partly handled;
  - 4 = satisfied;
  - 5 = very satisfied: correct, complete and polite.
- **Rate the interaction, not the policy outcome.** A correct refusal can still be a 3–4.
- **What annotators see:**
  - the client messages and the replies the client actually received, in the original language;
  - **not** the internal trace (proposals, Coordinator checks), because the client never saw them.
- **Pilot:** 30 conversations rated by all 3. Then a calibration meeting, and the guideline is updated once. The pilot is **not** part of the evaluation.
- **Main set:** every conversation rated by all 3 annotators. The conversations are short (about 80 tokens today), so 1–2 minutes each.
  - 430 conversations × 3 ratings × 1.5 min ≈ 32 hours in total, about 11 hours per annotator.
- **Disagreement:** no forced consensus. The gold label is the **mean** of the 3, as in USS. Items with a spread of 3 or more points are listed for the guideline review, not re-labelled.

## 6. Agreement metric and splits

- **Agreement:** Krippendorff's α, **ordinal** (main) and interval (comparison with USS).
  - Also reported: mean pairwise |diff|, share of exact agreement, and the human leave-one-out MAE (the noise limit).
  - All are computed by `eval_labels.py`.
- **Reference points from USS:** EN α 0.20–0.28, ZH α 0.52.
- **Stop rule:** if the pilot α (ordinal) is below 0.4, the guideline is revised before the main set starts.
- **Splits are fixed BEFORE any prediction is looked at.**
  - Write `split.json` by conversation, stratified by language and intent.
  - DEV (about 130): used for the mean baseline and for the `ReviewCalibrator`.
  - TEST (300 or more): scored once.

## 7. Sample size

The gate needs TEST n ≥ 300 and a Spearman 95% CI lower bound ≥ 0.30. The table uses the Fisher-z approximation for
Spearman, se = √(1.06 / (n − 3)). It is computed in this session.

| n (TEST) | expected CI low if the true ρ = 0.35 | ρ = 0.45 | ρ = 0.55 | ρ = 0.60 |
|---|---|---|---|---|
| 100 | 0.16 | 0.27 | 0.39 | 0.45 |
| 150 | 0.20 | 0.31 | 0.42 | 0.48 |
| 200 | 0.22 | 0.33 | 0.44 | 0.50 |
| 300 | 0.24 | 0.35 | 0.46 | 0.52 |
| 500 | 0.27 | 0.38 | 0.48 | 0.54 |

**Smallest n for CI low ≥ 0.30:**
- ρ = 0.40: n ≥ 316
- ρ = 0.45: n ≥ 136
- ρ = 0.50: n ≥ 74
- ρ = 0.60: n ≥ 31

**Reading:**
- On USS TEST the recommended TF-IDF model has Spearman 0.596 overall and **0.383 on EN** (`v3/f/F_RESULTS.md` EN table; recomputed 0.596 in `results/f1_diagnosis.json`).
- If CallVerse looks like USS-EN, even 300 is not enough.
- **Per language:** at least 150 TEST conversations per language. Otherwise French stays "not validated".
- **Plan:** 30 pilot + about 130 DEV + 300 TEST ≈ **460 conversations**.

## 8. Storage

- **Traces:** under the existing `traces/` folder (git-ignored), on the project's machine only. Never in git.
- **Labels:** contract records (`v4/f/contracts/reviews.schema.json`), one JSONL file per batch. Validated with `validate_reviews.py` before use. Stored next to the traces, not in git.
- **Access:** the 3 annotators (redacted text only), the redaction checker, and Yassine.
- **Retention:** until the project's final grade plus the period set by the university; then delete.
- **Released artefacts:** only metrics and the validation card (`card.json`). No text.

## 9. How to run the evaluation when the labels exist

```bash
cd experiments/agents_ef
python -m v4.f.contracts.validate_reviews <labels.jsonl>                  # contract check
python -m v4.f.eval_m7_v4 ...  (or AgentF.process on the traces)  -> agent_f_results.jsonl with the predictions
python -m v4.f.annotation.eval_labels --labels <labels.jsonl> --predictions <agent_f_results.jsonl> \
    --split <split.json> --out <folder>                                   # agreement, metrics, card, gate
```

- The pipeline has been run only on `annotation/fixture_SYNTHETIC/`: fake labels, **no number from it may be reported**.
- On that fixture it correctly:
  - drops synthetic records unless `--allow-synthetic` is given;
  - labels the card `synthetic_fixture`;
  - counts the withheld French conversations as not scored;
  - refuses a dev/test overlap.
