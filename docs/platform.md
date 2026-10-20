# CallVerse platform brief (ShopNova first, Atlas later)

Copy this file into the CallVerse repo as `docs/platform.md`. Add this line to the repo's `CLAUDE.md`:
`Platform work (mock company DB, policies, write tools, clock, Layer 3 stub): follow docs/platform.md.`

## What the platform is
The mock company side of CallVerse. It gives agents real data to read, real policies to follow and a safe place to act.
It already partly exists in the repo: a placeholder ShopNova SQLite DB, 3 read tools, a tool registry with per-agent allow-lists, agent A, traces, tests.
**Extend what exists. Do not rebuild or rename it.**

**Source of truth: `docs/platform_contract.md`** (tables, tool shapes, write functions, events, scripted cases).
If this brief and the contract disagree, follow the contract and tell the user about the difference.

## Fixed facts
- Currency: TND. Demo date: **2026-10-09**, fixed (`sim_today` in `config.yaml`, no moving clock).
- LLM layer: Groq `gpt-oss-120b`, backup `gpt-oss-20b`, OpenAI SDK function calling. No LangChain.
- API keys: names in `config.yaml`, values in `.env` (never committed, never printed). `GROQ_API_KEY`; others if needed: `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`.
- Tools = plain Python functions returning a dict or `{"error": ...}`, never raising to the agent, plus OpenAI-style JSON definitions, registered in the existing registry.
- Agent IDs: `A`, `B` (C, D later). Every call goes through the registry allow-list check.
- **Only the Coordinator writes.** On `approve` it writes: a `refunds` row with status `approved`, or a `subscriptions` row with status `waiting`. Agents never get write tools.
- Every tool call is traced (reuse the existing trace system, do not add a second log).
- Policy search: small numpy cosine index with `bge-small`. The platform provides the policy files and a loader; search lives with the RAG code.

## ShopNova scripted cases (already in DB, keep exactly)
| Order | Case |
|---|---|
| 4512 | Sara, 59.90 TND, promised 3 Oct, stuck at depot, 6 days late: main demo |
| 4506 | Already refunded (189 TND) |
| 4507 | Delivered 2 days late |
| 4510, 4513 | Shipped, on time |
| 4511 | Processing |
| 4514 | Cash on delivery, 0 paid |
| 4505, 4508, 4509 | Delivered |

## ShopNova policies
| ID | Rule |
|---|---|
| R-DEL-01 | Delivery promise |
| R-DEL-02 | 1-5 days late: apologise and offer a notification |
| R-REF-03 | More than 5 days late and not delivered: full refund |
| R-REF-05 | A refund never exceeds the amount paid |
| R-RET-01 | Returns accepted within 14 days |
| R-DMG-01 | Damaged item: photo proof required |
| R-ESC-01 | Refunds over 300 TND go to Layer 3 |
| R-NOT-01 | Notifications for shipped, out for delivery, delivered |

Policy rules (agents depend on these, do not change):
- Rule IDs exactly as listed above.
- Each rule has 4 fields: `id`, `title`, `text` (what agents read), `condition` (what the Coordinator checks in code, e.g. `days_late > 5 and not delivered`).
- Key numbers: refund after **more than 5 days** late and not delivered; returns within **14 days**; Layer 3 above **300 TND**; notification events **shipped, out_for_delivery, delivered**.
- Claude Code may write the full text, but Yassine reviews it before it is final.

## Layer 3 stub
Refund > 300 TND goes to finance. Stub approves up to 500 TND, refuses above 500.

## Demo scenarios
- S1: 4512 refund approved (R-REF-03, 59.90 TND).
- S2: wrong refund amount proposed, Coordinator sends back (R-REF-05), corrected, approved.
- S3: user subscribes to delivery notification, order status advanced (`scripts/advance_status.py`), notification fires (R-NOT-01).
- Atlas with agent C only if time allows.

## Rules for code changes
- Work on a branch, never directly on `main`. Existing tests must keep passing.
- Standard library first. No new dependency without a reason.
- Generated data has `ai_generated = 1`; scripted cases `scripted = 1` (the teacher asks to label AI-generated data).
- Data stays deterministic (fixed seed, fixed demo date).
