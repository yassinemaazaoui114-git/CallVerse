# Step 8 (T27) — design pass: Promotions, Hotel deals, Check now, urgent flag, C/D outcomes

Made with the `ui-ux-pro-max` plugin (ux guidelines searched: "data table admin approval", "badge status color
only", "loading button disabled", "empty state"). Rules kept from it: never show meaning by colour alone (every
badge has an icon AND a word); wide tables sit in a scroll wrapper (`.table-wrap`), never break the page; a busy
button is disabled, says what it is doing and shows the spinner; an empty list says what is missing and what to do.
Everything reuses Dali's tokens (`styles/tokens.css`, `themes.css`), the `Shell`, `States` and `Icon` components, and
the classes of `AdminApprovals.jsx` (`panel order-card`, `kv`, `badge-*`, `confirm` dialog). No new npm dependency.

**Promotions (ShopNova admin, `/admin/promotions`).** Agent D proposes a discount for a product that has too much
stock (rule R-PRM-01). Same layout as Refund approvals: tabs "Waiting / Decided", one card per promotion (cards, not
a wide table, because each pending row needs a reason box and two buttons — the plugin's "tables overflow on small
screens" rule). Card: "10% on <product>", status badge; facts: product id, stock, sold in 30 days, days of cover,
Agent D's note, proposal + rule. Approve / Refuse (reason required to refuse) → confirmation dialog → one request
with a request id (a double click decides once). Decided: who, when, reason. Empty: "No promotion is waiting. Use
Check now on the dashboard to let Agent D look at the stock."

**Hotel deals (Atlas admin, `/atlas/admin/deals`).** Same page for Agent D's hotel deals (rule AT-DEAL-01): hotel,
number of nights (first–last date), lowest occupancy % of N rooms, discount %, note, status.

**Check now (both admin dashboards).** One panel at the top of the dashboard: a sentence saying what Agent D
checks, a "Check stock now" / "Check rooms now" button (disabled + spinner + "Checking…" while it runs), then the
result as three numbers in the `stats` style (short / overstocked / promotions proposed; overbooked / with empty
nights / deals proposed) and a link "Open Promotions" / "Open Hotel deals". Error: the shared alert with Retry.

**Urgent flag.** A red badge with the bolt icon and the word "Urgent" (never colour alone). Live tickets: in the
ticket column; Ticket detail: next to the status; Approvals: in the card head, urgent cards first.

**C/D outcomes (Ticket detail).** A "What was done" panel above the timeline: one line per outcome with an icon and
plain words — replacement (new order id), hold (units, until), passed to a colleague (reason), rebooking (new
flight), special assistance (kind), "waiting for the user's yes", Agent D's stock / overbooking warning.

```
┌ Promotions ─────────────────────────────── [Refresh] ┐   ┌ Admin dashboard ─────────────────────────────┐
│ [Waiting (2)] [Decided]                               │   │ ┌ Agent D: stock check ────────────────────┐ │
│ ┌ Promotion 3 · 10% on Garden chair   [● pending] ─┐ │   │ │ Compares stock with the last 30 days.     │ │
│ │ Stock 120 · sold 30 d 4 · cover 900 days          │ │   │ │ [⟳ Check stock now]                       │ │
│ │ Note: Garden chair: 120 units in stock and …      │ │   │ │  2 short · 5 overstocked · 3 proposed      │ │
│ │ Reason [______________]  [Approve] [Refuse]       │ │   │ │  → Open Promotions                         │ │
│ └───────────────────────────────────────────────────┘ │   │ └──────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────┘   └──────────────────────────────────────────────┘
Live tickets row:  T-0012  [⚡ Urgent]  Waiting for finance …     Ticket detail: "What was done" ⟶ [↻ Replacement] new order 4601
```
