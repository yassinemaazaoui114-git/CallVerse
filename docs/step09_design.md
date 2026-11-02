# Step 09 design — conversation memory, bare yes/no, one decision per message (T28)

Approved options (Yassine, 2 Nov 11:44): memory inside ONE conversation only; one decision per message; a bare
yes/no is resolved by code only when an open question exists.

## Where the conversation is kept today
- `callverse/tickets/store.py` (CallVerse's own DB, `callverse.db`): one chat = one **ticket** of one user and one
  company; `messages` holds every user / assistant text; `steps` holds the trace lines of each message.
- `callverse/channels/web_chat.py` `send()`: the one door. It finds the ticket (`ticket_for_message`: a ticket of
  another user or company is never reused), saves the user message, runs Intake **on this message only**, the
  identity check, then `pipeline.handle_ticket`. P20 already continues Agent C when the ticket's last decision was
  C's `ask_user` (`c_waiting_order`, read from `steps`).
- `callverse/pipeline.py`, `webui/api/chat.py`: no memory (one message in, one reply out; the API passes the ticket id).
So before T28 a "yes" to "Please confirm that you want a refund of 59.90 TND for order 4512." reached Agent B as a new
message without money-back words, and the Coordinator asked again (T14f problem 2).

## Memory shape (new module `callverse/channels/conversation.py`)
- **History** = the last 6 messages of the ticket (`store.messages`, nothing new stored). Used for ONE thing: when a
  message names no order / booking id and refers back ("and what about it?", "the order", "that one"), the newest id
  that the **user** typed in those messages is used. It goes through the same identity check (it must be this user's
  order). Assistant texts are never read. No amount, no decision, no reason comes from the history.
- **Pending question** = one row in the new table `pending_questions` (tickets DB): ticket, user, company, who asked
  (A, B or C), order / booking id + booking type, proposal id + action, Intake's main reason of the first message,
  and flags computed by code from the first message: `money_back` (the client's own money-back words, T14f),
  `negated`, `expenses`, `cancel_order`, `cancel_any`. Status: open → used / closed / cleared / expired.
  Created when a turn ends with `ask_user` on a recorded proposal (B's "Please confirm…" or C's offer).
  It ends at the **next user message** (whatever it says) or after **30 minutes** (computer time; the simulation clock
  does not move).

## Bare yes / no rule
A message is "bare" when, without punctuation, it is only one of a short list: yes, yeah, yep, ok, okay, sure,
please do, go ahead, confirm, i confirm, yes please … / no, nope, cancel, no thanks, never mind. (Intake knows no
French / Arabic yes words today, so none are added.)
- open question + **yes** (asked by A or B): the stored proposal is read back from the company DB (by its id: the
  amount and order come from the DB, not from text), copied as a NEW proposal with `user_confirmed` true, and goes
  through the **normal Coordinator** (`review`): all checks, Layer 3 queue, the write. No agent and no model decide.
  The case carries `yes_answer` = the stored flags; the Coordinator's confirmation step then uses them instead of the
  quote in the current text ("yes" has none): a refund needs `money_back` (and no `expenses` at Atlas); a ShopNova
  cancel needs `cancel_order`; an Atlas hotel cancel needs `cancel_any`; a compensation needs not `negated`. If a
  flag is missing the client is asked again (no write). Every other check is unchanged.
- open question + **yes** (asked by C): the P20 path as before (Agent C runs again with the yes).
- open question + **no**: the question is closed, short fixed reply, nothing written.
- no open question + yes/no: the normal flow (re-asked as today).
- double "yes": the first one marks the row `used` in one SQL update (`WHERE status = 'open'`); the second finds no
  open question → normal flow, and the platform's own guards (decided proposals, refund limit) stay.
- wrong user: the row stores user and company; a question of another user / company is never used.

## Several requests in one message: one decision per message
Rule (simplest that works): **two or more different order / booking ids** in one message = several requests (same
number regex as Intake; amounts and dates are skipped as before). The message is cut into sentences (and at
" and " / " also " just before a new id). Each id gets its part. A part is a **money part** when it has money-back
words or a cancel word. The **first money part** (else the first part) is handled by the normal pipeline, alone.
Each other part gets one sentence written by code: an information part → its status from the data ("Order 4511 is
shipped."); a money part → "Please send your request about order N as a new message: I can handle one decision per
message." An id that is not this user's → "Order N is not on your account." No second write in the same turn.
Not used: a second Intake reason above its threshold (two reasons often come from ONE request, e.g. late + refund).

## Tests (tests/test_t28_conversation.py)
Bare word list; history id (refers back / not / other user's id); pending: created on ask_user, yes → one write,
double yes → one write, no → closed, expired (31 min), cleared by an unrelated message, wrong user, money_back flag
false → asked again; split into parts (refund 4512 + where is 4511, two refunds, other user's id).
