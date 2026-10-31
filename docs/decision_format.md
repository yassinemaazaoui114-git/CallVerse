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
| `order_id` | int or null | the order the reply is about; the reply mentions it |
| `rule_id` | str or null | policy rule behind the decision, for the trace only: **never written in the reply** |
| `facts` | dict | the **only** facts the reply may contain (amounts, dates, days, statuses, ...) |
| `next_step` | str | one sentence **written to the client** (never to the agent): what happens next / what the client must do. Written by the Coordinator. The reply ends with it almost word for word, so "Ask the client for a photo" is wrong; "Please send us a photo of the damaged item" is right |
| `must_say` | list of str, optional | exact sentences or phrases the reply must contain **word for word** (checked case-insensitively). For facts that must not be misstated (e.g. "Refunds above 300 TND need approval from our finance team."). Written by the Coordinator |
| `style` | dict | from Intake: `formality` (formal · casual · neutral), `length` (short · medium · long), `shouting` (bool), `emotion` (e.g. anger, joy, neutral), `sentiment` (negative · neutral · positive) |

Known `facts` keys (others are allowed; the writer passes them as they are):
`amount_tnd`, `days_late`, `order_status`, `promised_date` (YYYY-MM-DD), `carrier`, `event` (notification event),
`needed` (what proof is needed), `threshold_tnd` (Layer 3 limit), `days_since_delivery` (T14a).

## Outcomes, as the client sees them
| Outcome | The reply says | The reply must not |
|---|---|---|
| `approve` | the request is approved (e.g. refund of X TND, notification set up) + next step | add amounts, dates or delays not in facts |
| `send_back` | the request is still being checked + next step | say it is approved or refused |
| `ask_user` | a question to the client (in `next_step`) | decide anything |
| `ask_proof` | what proof is needed (`facts.needed`) + next step | promise a refund or replacement |
| `layer3` | the refund needs approval from the finance team + next step | promise the refund |
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

## Rule check (callverse/slm/check.py)
After the SLM writes, a rule check (plain code) verifies the reply:
- every number in the reply appears in `facts`, `order_id` or `next_step`;
- no forbidden promise ("we will keep you updated", "we are monitoring", "guarantee", "within X hours/days", ...)
  unless the same idea is in `facts` / `next_step`; no refund promise unless `outcome` is `approve` for a refund or a
  cancellation;
- no rule id (R-XXX-00), no placeholder such as `[Name]`;
- the order number is mentioned; the reply is not empty and has at most 120 words.
- every `must_say` item is present word for word (case-insensitive, spaces ignored);
- the forbidden list lives in `config.yaml` (`slm.forbidden`), so it can grow without code changes.
If the check fails: one retry with the problems listed; if it fails again, a fixed template is used
(`callverse/slm/templates.py`, it includes the `must_say` items). The final reply always passes the check.

## Parts written by code, not by the model (T05b)
- **Calm opener**: if `style.shouting` or `style.sentiment == "negative"`, the reply starts with a fixed sentence
  from `config.yaml` (`slm.calm_openers`, by formality), e.g. "I'm really sorry for the trouble."; a greeting or
  apology the model wrote is removed so the apology is not doubled.
- **Order reference**: if the model forgot the order number, "About your order N:" is inserted.
- **Repeated sentences** are removed.
The model runs at temperature 0 with a fixed seed: the same decision gives the same reply.
