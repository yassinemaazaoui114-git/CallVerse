# Decision format (Coordinator → SLM reply writer)

The Coordinator decides **what** is said; the SLM (M5, `callverse/slm/writer.py`) only decides **how** it is said,
in the client's style. The SLM's only input is this decision dict, plus a few recent messages for tone.
It has no tools and never reads the database, so every fact it may write must be in the decision.

```json
{
  "outcome": "approve",
  "action": "refund",
  "order_id": 4512,
  "rule_id": "R-REF-03",
  "facts": {"amount_tnd": 59.90, "days_late": 6, "order_status": "stuck_at_depot"},
  "next_step": "The money goes back to the card you paid with.",
  "must_say": ["Your refund of 59.90 TND is approved."],
  "style": {"formality": "casual", "length": "short", "shouting": true,
            "emotion": "anger", "sentiment": "negative"}
}
```

| Field | Type | Meaning |
|---|---|---|
| `outcome` | str | `approve` · `send_back` · `ask_user` · `ask_proof` · `layer3` · `escalate` · `info` · `decline` (see below) |
| `action` | str | what the case is about, e.g. `refund`, `subscribe`, `status`, `cancel`, `return` |
| `order_id` | int or null | the order the reply is about. The reply must never give another number; ShopNova no longer forces the reply to name it (T14b): it appears where the Coordinator's sentences (`must_say`, `next_step`) have it. Atlas still has to mention its booking number |
| `rule_id` | str or null | policy rule behind the decision, for the trace only: **never written in the reply** |
| `facts` | dict | the **only** facts the reply may contain (amounts, dates, days, statuses, ...). The decision carries all of them for the checker and the trace; the ShopNova writer is shown only the whitelist below (T14b) |
| `next_step` | str | one sentence **written to the client** (never to the agent): what happens next / what the client must do. Written by the Coordinator. The reply ends with it almost word for word, so "Ask the client for a photo" is wrong; "Please send us a photo of the damaged item" is right |
| `must_say` | list of str, optional | exact sentences or phrases the reply must contain **word for word** (checked case-insensitively). For facts that must not be misstated (e.g. "Refunds above 300 TND need approval from our finance team."). Written by the Coordinator |
| `style` | dict | from Intake: `formality` (formal · casual · neutral), `length` (short · medium · long), `shouting` (bool), `emotion` (e.g. anger, joy, neutral), `sentiment` (negative · neutral · positive), `language` (T14b: `en` · `fr` · `es` · `it` · `de` · `ar`; missing = `en`) |

Known `facts` keys (others are allowed; the writer passes them as they are):
`amount_tnd`, `days_late`, `order_status`, `promised_date` (YYYY-MM-DD), `carrier`, `event` (notification event),
`needed` (what proof is needed), `threshold_tnd` (Layer 3 limit), `days_since_delivery` (T14a).

## What the ShopNova writer is shown (T14b: facts whitelist)
A small model comments on raw order details ("0 days late", the carrier, a promised date, the status code). So the writer's
prompt (`writer.writer_facts`) contains only these facts; Atlas decisions are passed unchanged.

| Fact | Shown to the writer when |
|---|---|
| `amount_tnd`, `event`, `layer3_decision`, `threshold_tnd`, `needed` | always (amounts and the like) |
| `days_late` | only when > 0 **and** the decision is about lateness: a status answer (`action` = `status`) or rule R-REF-03 / R-DEL-02 |
| `order_status`, `promised_date`, `carrier`, `days_since_delivery`, any other fact | only when its value is inside `must_say` / `next_step` (the sentence says it already) |

What each decision type carries today (before the whitelist) and what the writer now sees:

| Decision | Facts in the decision | Shown to the writer |
|---|---|---|
| `info` / status (`info_decision`) | `order_status`, `days_late`, `promised_date`, `carrier` | `days_late` if > 0; the rest only if in the sentence |
| `info` / redirect (off topic) | none | none (and no calm opener: the scope sentence stands alone) |
| `decline` R-REF-03 (not late) | `order_status`, `days_late` (0), `promised_date` | `promised_date` (it is in `must_say`) |
| `decline` R-REF-05 | `order_status`, `amount_tnd` | `amount_tnd` |
| `decline` R-RET-01 / R-CAN-01 | `order_status`, `days_since_delivery` | `days_since_delivery` (in `must_say`) |
| `ask_user` (cancel) / `ask_proof` | `order_status` | nothing (the sentence says it) |
| `approve` refund / cancel (`slm_facts`) | `order_status`, `days_late`, `amount_tnd`, `days_since_delivery` (cancel), `layer3_decision`, `threshold_tnd` | `amount_tnd`, `layer3_decision`, `threshold_tnd`; `days_late` for R-REF-03 when > 0 |
| `approve` subscribe | `order_status`, `days_late`, `event` | `event` (`days_late` for R-DEL-02 when > 0) |
| `layer3_pending` / `layer3_refused` / `escalate` | `order_status`, `days_late`, `amount_tnd`, `layer3_decision`, `threshold_tnd` | `amount_tnd`, `layer3_decision`, `threshold_tnd` |

The agents also no longer see `source`, `source_id`, `city` and `payment` in their read-tool results
(`registry.hide_fields`); the Coordinator and the platform still read the full rows.

## Outcomes, as the client sees them
| Outcome | The reply says | The reply must not |
|---|---|---|
| `approve` | the request is approved (e.g. refund of X TND, notification set up) + next step | add amounts, dates or delays not in facts |
| `send_back` | the request is still being checked + next step | say it is approved or refused |
| `ask_user` | a question to the client (in `next_step`) | decide anything |
| `ask_proof` | what proof is needed (`facts.needed`) + next step | promise a refund or replacement |
| `layer3` | the refund needs approval from the finance team + next step | promise the refund |
| `layer3_pending` (T14b guide) | the request was passed to the finance team and the client will be told here | give a time, an amount or a rule that is not in `must_say`, or promise payment |
| `escalate` | a colleague takes over + next step | promise a result |
| `info` | the facts (status, delay, ...) + next step | promise follow-up actions |
| `decline` | no, with the rule's reason (`must_say`, copied word for word) + next step, if any | offer anything else, or promise a refund or a later check |

## The `decline` outcome (T14a, ShopNova)
The Coordinator says no **by code**, from fresh data and the rules; no LLM decides or words the reason. Each sentence is one
`must_say` item (the reply writer removes a sentence that is only a part of a longer item). `rule_id` is the rule behind the
no, shown in the ticket's timeline and never in the reply. The ticket becomes Solved.

| Main reason | Condition (fresh data) | `rule_id` | Reason |
|---|---|---|---|
| `return_item` | delivered more than 14 days ago | R-RET-01 | too late to return |
| `refund_request` | `refunded_total` >= `paid`, and `paid` > 0 | R-REF-05 | already fully refunded |
| `refund_request` | delivered more than 14 days ago | R-RET-01 | money back on a delivered order only comes from a return |
| `refund_request` | not delivered, not late, not refunded or cancelled | R-REF-03 | not late |
| `cancel_order` | status is not `processing` | R-CAN-01 | already left; also for a cancel proposal, not a send-back |

R-CAN-01's `next_step`: shipped, out for delivery or stuck at the depot: "Once it is delivered, you can return it within 14
days."; delivered at most 14 days ago: "You can still return it within 14 days of delivery."; otherwise empty.
A `cancel_order` case on a `processing` order without a proposal is not a decline: `ask_user` ("Please confirm that you want
to cancel order N."). Any other case without a proposal keeps today's `info` reply.

## The `decline` outcome at Atlas (T14c)
Same idea (`atlas_coordinator.decline_rule`, fresh data + Intake's main reason, first match wins). It runs for a case
without a proposal AND inside `review()` right after the facts are read, when the proposal is about the client's request
(a compensation for `compensation_request`; a refund or a hotel cancellation for `refund_request` / `cancellation`); a
cancellation of a still-confirmed hotel booking is never declined (it is a real cancellation, T21).

| Main reason | Condition (fresh data) | `rule_id` |
|---|---|---|
| `compensation_request` (flight) | the flight left and arrived < 3 h late, or on time | AT-FLT-03 |
| `compensation_request` (flight) | recorded cause weather / air system / security | AT-FLT-06 |
| `compensation_request` (flight) | cancelled with `notice_days` >= 14 | AT-FLT-02 |
| `refund_request` (flight) | the flight left < 5 h late (not cancelled) | AT-FLT-04 |
| `refund_request` (flight) | already fully refunded | AT-REF-01 |
| `refund_request`, or `cancellation` of a booking no longer confirmed (hotel) | non-refundable (cancelled or confirmed) | AT-HOT-03 |
| same | refundable, cancelled < 2 days before arrival | AT-HOT-02 |
| same | no-show | AT-HOT-05 |
| same | already fully refunded | AT-REF-01 |
| same | no deposit | AT-HOT-01 |

Facts in the decision: `booking_status`, `flight_status` (+ `refunded_tnd` for AT-REF-01); the numbers are inside
`must_say`. Writer guide `decline_atlas`: the next step may say what is still possible ("You can still choose a full refund
or a new flight."). The template gives the reason first, then the next step.

## Off-topic (T14c)
The redirect (`action` = `redirect`, both companies) is a fixed text: greeting + the Coordinator's two sentences, no SLM call.

## Rule check (callverse/slm/check.py)
After the SLM writes, a rule check (plain code) verifies the reply:
- every number in the reply appears in `facts`, `order_id` or `next_step`;
- no forbidden promise ("we will keep you updated", "we are monitoring", "guarantee", "within X hours/days", ...)
  unless the same idea is in `facts` / `next_step`; no refund promise unless `outcome` is `approve` for a refund or a
  cancellation;
- no rule id (R-XXX-00), no placeholder such as `[Name]`;
- ShopNova (T14b): no WRONG order number ("order 4511" in a reply about 4510); Atlas: its booking number is mentioned;
  the reply is not empty and has at most 120 words.
- every `must_say` item is present word for word (case-insensitive, spaces ignored);
- the forbidden list lives in `config.yaml` (`slm.forbidden`), so it can grow without code changes.
If the check fails: one retry with the problems listed; if it fails again, a fixed template is used
(`callverse/slm/templates.py`, it includes the `must_say` items). The final reply always passes the check.

## Parts written by code, not by the model (T05b)
- **Calm opener**: if `style.shouting` or `style.sentiment == "negative"`, the reply starts with a fixed sentence
  from `config.yaml` (`slm.calm_openers`, by formality), e.g. "I'm really sorry for the trouble."; a greeting or
  apology the model wrote is removed so the apology is not doubled.
- **Order reference** (Atlas only since T14b): if the model forgot the booking number, "About your booking N:" is inserted.
  ShopNova adds no such sentence.
- **Language** (T14b, ShopNova): `style.language` comes from Intake (`callverse/intake/language.py`, stop-words). When it is not
  `en` the prompt says "write the reply in <language>"; the `must_say` sentences stay as given (English). The off-topic
  reply (`action` = `redirect`) gets no calm opener.
- **Repeated sentences** are removed.
The model runs at temperature 0 with a fixed seed: the same decision gives the same reply.
