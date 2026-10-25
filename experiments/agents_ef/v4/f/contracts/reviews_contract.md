# Reviews data contract — PROPOSAL v0.1 (not adopted)

**Status:** proposal by Worker F (Agent F / M7), 2026-10-26. It is isolated in `v4/f/contracts/`. It changes nothing
in the prototype or the platform. Adopting it is a decision for the Brain, Yassine and the platform owner (Dali).
It would sit next to `docs/platform_contract.md`.

## 1. Why this contract is needed

- Agent F must "learn from real reviews". The ShopNova platform has **no reviews table** (`callverse/data/seed.py`:
  users, products, orders, refunds, subscriptions, events). So there is nothing to learn from yet.
- Satisfaction numbers now come from three very different places:
  1. a client gives a rating (**measured**);
  2. a trained person labels a conversation (**measured**, but by a third party);
  3. Agent F's model predicts a score (**not measured**).
- If these three are stored in one `rating` field, a prediction can later be read as if it were a measured
  rating. Then a model could be "validated" on its own outputs, or Agent E could be rewarded on a guess.
  This contract keeps them apart **by construction**.

## 2. One record = one satisfaction fact about one closed conversation

Machine-readable schema: `reviews.schema.json`. Validator (no extra library): `validate_reviews.py`.
Tests: `v4/f/tests/test_contract_annotation.py`.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | "0.1" | yes | version of this contract |
| `record_id` | string | yes | unique id of the record |
| `conversation_id` | string | yes | id of the closed conversation (trace run id; `run#n` inside a batch file) |
| `ticket_id` | string / null | no | Intake ticket id (`T-…`) |
| `order_id` | integer / null | no | ShopNova order id |
| `rating_source` | `customer_submitted` \| `annotator` \| `ai_predicted` | yes | who produced the number |
| `rating` | integer 1–5 / null | measured only | **measured** rating; must be null for `ai_predicted` |
| `predicted_score` | number 1–5 / null | predicted only | **AI-predicted** score; must be null for measured records |
| `prediction` | object / null | predicted only | `model_id`, `model_sha256`, `label_type_trained_on`, `validity` (the M7 v4 values) |
| `annotator_id` | string / null | annotator only | pseudonymous annotator id |
| `feedback_text` | string ≤ 2,000 / null | no | client comment; stored **only after PII redaction** |
| `submitted_at` | ISO 8601 date-time | yes | when the rating was given (or the prediction made) |
| `conversation_closed_at` | date-time / null | no | from the trace (`pipeline_done` time) |
| `channel` | `chat` \| `email` \| `phone` \| `voice` \| `annotation_tool` \| `agent_f` | yes | where the record came from |
| `language` | `fr` \| `ar` \| `en` \| `other` \| `unknown` | yes | language of the client's messages |
| `consent` | {given, scope[], recorded_at, consent_text_version} | yes | scope ⊆ quality_reporting, model_validation, model_training |
| `pii_redaction` | {status: redacted \| none_found \| not_done, method, checked_by} | yes | state of the free text |
| `data_quality` | {is_duplicate, is_test_or_synthetic, rating_delay_hours, conversation_found_in_traces, flags[]} | yes | for filtering |

## 3. Rules that keep measured and predicted apart

| Rule | Text |
|---|---|
| R1 | `rating` exists only for `customer_submitted` and `annotator`; those records carry no `predicted_score` / `prediction`. |
| R2 | `ai_predicted` records have `rating = null`, and need `prediction{}`. `predicted_score` may be null only when M7 withheld it (e.g. language not validated). |
| R3 | `annotator` records need `annotator_id` (needed for the agreement metric). |
| R4 | `feedback_text` is stored only when `pii_redaction.status` is `redacted` or `none_found`. |
| R5 | A client rating without `consent.given = true` is not stored at all. |
| R6 (use) | Only measured, consented (`model_validation` in scope), non-duplicate, non-synthetic records may be used as labels (`usable_for_validation`). |
| R7 (use) | Agent E's reward may use a predicted score only if the M7 gate passes (`v3/m7/feedback_e.py`, kept in v4). A measured rating is never replaced by a prediction in reports: both are shown, with their source. |

## 4. How M7 would use it

- **Validation card.** `v4/f/annotation/eval_labels.py` reads measured records. It writes a card with
  `label_type = genuine_customer_rating` (from `customer_submitted`) or `human_annotation` (from `annotator`),
  `domain = support_conversation` and `corpus = callverse`. The F→E gate then decides. Annotator labels can
  validate the KPI use. They do **not** open E's reward, because the gate requires genuine customer ratings.
  Changing that would be a Brain decision.
- **Learning from the few reviews.** `v3/m7/satisfaction.ReviewCalibrator` (isotonic, cross-validated, at least
  50 reviews) maps model scores to measured ratings. `review_bias` compares reviewed with all conversations,
  because the people who review are not typical.

## 5. Questions for the owners

1. Where should the table live: the platform DB (`callverse/data/db.py`) or a separate store?
2. Who asks the client for a rating, and when? This choice changes `rating_delay_hours` and the review bias.
3. Consent text and retention period: these need the university's / data-protection officer's rules.
