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
| `outcome` | str | `approve` · `send_back` · `ask_user` · `ask_proof` · `layer3` · `escalate` · `info` (see below) |
| `action` | str | what the case is about, e.g. `refund`, `subscribe`, `status` |
| `order_id` | int or null | the order the reply is about; the reply mentions it |
| `rule_id` | str or null | policy rule behind the decision, for the trace only: **never written in the reply** |
| `facts` | dict | the **only** facts the reply may contain (amounts, dates, days, statuses, ...) |
| `next_step` | str | one sentence **written to the client** (never to the agent): what happens next / what the client must do. Written by the Coordinator. The reply ends with it almost word for word, so "Ask the client for a photo" is wrong; "Please send us a photo of the damaged item" is right |
| `must_say` | list of str, optional | exact sentences or phrases the reply must contain **word for word** (checked case-insensitively). For facts that must not be misstated (e.g. "Refunds above 300 TND need approval from our finance team."). Written by the Coordinator |
| `style` | dict | from Intake: `formality` (formal · casual · neutral), `length` (short · medium · long), `shouting` (bool), `emotion` (e.g. anger, joy, neutral), `sentiment` (negative · neutral · positive) |

Known `facts` keys (others are allowed; the writer passes them as they are):
`amount_tnd`, `days_late`, `order_status`, `promised_date` (YYYY-MM-DD), `carrier`, `event` (notification event),
`needed` (what proof is needed), `threshold_tnd` (Layer 3 limit).

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

## Rule check (callverse/slm/check.py)
After the SLM writes, a rule check (plain code) verifies the reply:
- every number in the reply appears in `facts`, `order_id` or `next_step`;
- no forbidden promise ("we will keep you updated", "we are monitoring", "guarantee", "within X hours/days", ...)
  unless the same idea is in `facts` / `next_step`; no refund promise unless `outcome` is `approve` for a refund;
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
