# UI replacement — step 2 report (for Yassine)

Branch `feat/ui-react` (on top of step 1 `dafe1ae` + corrections `4f7c51e`) · folder `webui/` · 2026-11-01 · Dali's lane.
`callverse/` unchanged, Streamlit apps unchanged, no merge into `main`.

## 1. In plain words

A ShopNova customer can now log in to the new UI and see **My orders** (their own orders only, newest first),
open an **Order detail** page (items, delivery progress, dates, payment, refunds) and press **Ask about this
order**, which prepares the chat for the next step and says plainly that sending a message is not built yet.
The server decides whose orders are shown from the accounts file; the browser cannot ask for another person's
order (it gets the same "not one of your orders" answer as for an order that does not exist), and Atlas
accounts, admins and the supervisor are refused on these pages. After login each account lands on its own
home: supervisor → Console, ShopNova customer → My orders, every other account → a page that explains its
screens are not in this delivery yet. The ShopNova pages use the warm light theme (paper background, navy text
and buttons, coral accent) with the same components, spacing and focus behaviour as the Console.

## 2. Done

- **API** (`webui/api/shop_reads.py`, routes in `app.py`): `GET /api/shop/orders` and `GET /api/shop/orders/{id}`,
  behind a `shopnova_customer` dependency = `accounts.check_role(session, "user", "shopnova")` (the same check
  as the Streamlit page; an Atlas account with the same numeric user id is refused by the company check; admins
  and the supervisor by the role check). The user id then comes from the accounts file. Functions wrapped:
  `callverse.data.shop_reads.user_orders` (the exact function of `apps/shopnova/pages/2_My_orders.py`) for the
  list and for the ownership check; then, for an owned order only, `shopnova_tools.get_tracking` (days late
  against `sim_today`) and `shopnova_tools.get_refunds` (refunded total). No SQL, no rule, no coordinator
  import (`status_words` is not used: the API returns the database's status codes and the screen shows them
  as words by replacing underscores, keeping the raw code in the markup). Missing and unowned order: the same
  404 `not_found` with the same wording.
- **Frontend**: `hooks.js` (`useGuardedLoad`: request number + abort on new request / unmount + 401 → session
  expired; `homeFor`; `tnd`; `words`), `styles/themes.css` (ShopNova colour tokens under
  `:root[data-theme="shopnova"]`, screen styles), `Shell` made generic (area → brand, menu, theme on `<html>`,
  page title), screens `MyOrders`, `OrderDetail`, `AskAboutOrder`, `Workspace`; routes `/shop/orders`,
  `/shop/orders/:id`, `/shop/orders/:id/ask`, `/workspace`; login redirect by role; "forbidden" box now shows
  the API's own words (customer-only vs supervisor-only). Delivery progress marks only what the database says
  (status + dates) along the shop's own status path; a status outside the path (refunded, cancelled, unknown)
  is shown as text with its raw code, never placed on the path. No promised-arrival or eligibility guess.
- **Tests**: `webui/api/tests/test_shop.py` (8) and `webui/frontend/src/test/Shop.test.jsx` (6).
- Screenshots `20_` to `25_` in `webui/reports/screenshots/`; `webui/README.md` updated.
- `ui-ux-pro-max` consulted for the order list/tracking (kept: feedback states, consistent help placement,
  live-status wording; nothing else fitted).

## 3. Numbers / evidence

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` (step 1 + step 2) | **23 passed** (15 + 8) |
| `npm --prefix webui/frontend test` (vitest, step 1 + step 2) | **13 passed** (7 + 6) |
| `npm --prefix webui/frontend run build` | OK, JS 208.5 kB (66.1 kB gzip), CSS 17.4 kB |
| sara (user 1) sees only her orders; ids equal `shop_reads.user_orders(1)` and are disjoint from user 2's | passed |
| youssef (user 2) opens sara's order by URL | 404 `not_found`, same wording as a missing id |
| hedi (Atlas, user id 1 like sara) on both routes | 403 `customer_only` |
| admin, supervisor, atlas_admin on both routes; no login | 403 `customer_only`; 401 |
| owned detail == `user_orders` row, `get_tracking`, `get_refunds`; `checked_on` = 2026-10-09 | passed |
| empty list (account pointed at a user id without orders) | 200, `[]` |
| unfamiliar status `held_for_photo_proof` | passed through by the API; shown as "held for photo proof" by the screen |
| reads write nothing: temp shopnova.db SHA-256 unchanged after 3 requests, Atlas file never created | passed |
| "Ask about this order" keeps `data-chat-order=4505`, Send disabled, only two GETs happened (session, order) | passed |
| Browser, desktop ~1000 px: login as sara → My orders (2 orders, status badges, amounts, "Shop date 2026-10-09 (simulation)") ✔, Order 4512 detail (progress with "stuck at depot (now)", days late 6 as of 2026-10-09, items, payment, no refund) ✔, Ask page ✔, `/shop/orders/4505` (not hers) → "not one of your orders" ✔, sara on `/tickets` → "Not available for your account: supervisor only" ✔, admin login → `/workspace` explanation ✔ | ✔ |
| Browser, phone 375×812: My orders and Order detail stacked, `scrollWidth` 375 = `clientWidth` | ✔ |
| Real data touched | none (temp fixture in the scratchpad; `callverse/data/*.db` and `config/accounts.yaml` absent on this PC) |

## 4. Problems

- **A missing shopnova.db would have been seeded by a read** (`callverse.data.db.connect()` creates and seeds
  a missing file). **Closed in the correction commit**: both order routes now check that the configured
  `shopnova.db` exists (after the role check, before any read function runs) and answer 503
  `setup_required` with the seed instruction; the screens show "ShopNova's data is not set up on this PC"
  with Retry. Tests: both routes with a missing file → 503 and the file is still absent; a non-customer still
  gets 403 (no hint about files); the Console routes answer 200 / 404 without the shop file and never create
  it. API tests: **25 passed**.
- **Order detail reads the whole list** to check ownership (`user_orders(user_id)` then filter by id): one
  extra read per detail, fine for a demo (a customer has a handful of orders). A `user_order(user_id,
  order_id)` function in `shop_reads.py` would be cleaner; listed below for Yassine.
- **Status words**: the Streamlit page uses `coordinator.status_words`; importing the coordinator from the API
  would pull writes/Layer 3 modules into a read-only process, so the screen does the simple underscore → space
  itself. Codes stay visible in the markup (`<code>` for off-path statuses).
- **Unread-reply notice** ("New reply on T-00NN" on the Streamlit My orders page) is not in this step: it
  belongs with the chat (step 3).
- Not verified in the browser: an unfamiliar status (covered by API + screen tests), a customer with zero
  orders (API test + screen test), the API-down and session-expired boxes on these screens (same components
  and hook paths as step 1, which were checked there).

## 5. Questions for the Brain

1. Should Yassine add `shop_reads.user_order(user_id, order_id)` (one owned order or None) so the API does
   not list all orders to check one? Until then the list-then-filter stays.
2. (closed) The API now refuses the shop routes with 503 `setup_required` while `shopnova.db` is missing.
3. Step 3 chat: the Streamlit page passes the order as `about_order` to `web_chat.send` and keeps the ticket id
   in the browser session. For the React chat I plan: `POST /api/shop/chat` (one at a time, worker thread) +
   SSE for `on_step` texts, ticket id in the URL. OK, or do you prefer WebSocket?

## 6. Next step

Step 3 of the brief: the chat with live steps (SSE), tested with the scripted users and a fake `chat_fn`
first, plus the "busy / quota reached" message and the unread-reply notice. After your review of this step.
