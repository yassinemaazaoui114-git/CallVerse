# UI replacement — design, motion and management pass (for Yassine)

Branch `feat/ui-react` · after the acceptance preparation `d777f36` · folder `webui/` · 2026-11-01 · Dali's lane.
`callverse/` unchanged, Streamlit apps unchanged, authentication unchanged, no merge into `main`, nothing
pushed, nothing deployed. Temporary databases and fake models only. **Not an acceptance: that is your review.**

Three commits: `5e1958f` design and motion · `e9c2153` the Manage page and its tests · this report, the README
and the screenshots.

## 1. What changed and why

### Design (every area, the three themes kept)

Guided by the `ui-ux-pro-max` skill's checks (contrast, 44 px targets, visible focus, motion with meaning,
errors next to the field, no decoration for its own sake) applied to the pages as they render in the browser.

| Where | Change | Why |
|---|---|---|
| Tokens | three motion durations (120 / 180 / 260 ms) and two curves (ease-out arriving, ease-in leaving); a soft panel shadow per light theme (none in the dark Console); a focus halo colour; `prefers-reduced-motion` sets every duration to 0 | one place for timing; the light themes needed a hint of depth to separate panels from the paper / pale-blue page without borders doing all the work |
| Headings, page head | slight negative tracking on headings; the page head gets a rule under it and more room below on desktop; subtitle capped at 72 characters | hierarchy: title, subtitle, then the controls |
| Buttons | colour and press transition, a 2 % press on `:active`, a `btn-danger` variant (soft red) for remove / cancel; tab rows and the period picker become one **segmented control** (the chosen tab lifted on the panel colour) with the same markup | the old active tab was a full primary pill, indistinguishable from the page's one primary action |
| Inputs | focus halo (not only the outline), `aria-invalid` red border, `.hint` and `.field-error` lines under the field, disabled state, a two-column form grid from 640 px | errors and help next to the field (skill rule "error clarity") |
| Tables | header tracking, a little more row padding, the header above rows when scrolling | readability of the records and Manage tables |
| Stats and charts | stat value 28 px on desktop with tighter line height; a rule under each chart's head | the number is the point of a tile |
| Cards, panels | panels get 24 px padding on desktop; order / approval cards change their border on hover | consistency with the stat tiles |
| Empty states | the icon sits in a soft disc | a recognisable empty state instead of a lone glyph |
| Skeleton rows | a `.skeleton` class (used by the Manage loading) that keeps the rows' height | no layout shift while a table loads |

### Motion (CSS only, no dependency)

| Element | Motion | Rule kept |
|---|---|---|
| page content | rises 6 px from 70 % opacity once per **navigation** (keyed by the path in `Shell.jsx`); a data refresh on the same page does not replay it | never on refresh; readable even on a frame where the animation did not run (a background tab pauses animations) |
| dialog | backdrop fades 120 ms, the panel rises 180 ms | the focus moves to the dialog on open as before, not during the motion |
| notices (`.alert`) | fade in 180 ms | no slide: nothing moves under the pointer |
| disclosure body | fades in when opened | the chevron rotation existed already |
| buttons, inputs, rows, cards | colour / border / halo 120 ms; press 2 % | no transform on focused controls except the press the user asked for |
| meter (Groq today) | the width transition existed; **not** added to the money tiles or the bars | financial values must not "count up" or grow in a misleading way |
| reduced motion | `@media (prefers-reduced-motion: reduce)`: every duration 0, the spinner static, the skeleton static | |

Not done on purpose: no entrance stagger on lists, no scroll-linked motion, no animated numbers, no GSAP (the
skill's presets would add a dependency for no user benefit here).

### Management (CRUD) — only where the core already has the function

Capability matrix (what the core offers, read the way the Streamlit pages call it):

| Entity | Read | Create | Update | Delete | Permission | In this UI |
|---|---|---|---|---|---|---|
| ShopNova product | `admin_reads.products_page`, `product_row`, `product_categories` | `writes.create_product` | `writes.update_product` (name, category, price, stock) | **no delete**: `writes.deactivate_product` / `reactivate_product` (soft) | `edit_catalogue` | **yes** (Manage → Products) |
| ShopNova order | `admin_reads.orders_page`, `order_row` | — (customers buy in the shop: `writes.create_order`, not an admin action) | `writes.admin_set_order_status` (the carrier's moves; `cancelled` only while `processing` and unpaid; `refunded` never by hand) | no | `edit_orders` | **yes** (Manage → Orders: a status select per row with the moves the core allows) |
| ShopNova client | `admin_reads.users_page`, `user_row`, `cities` | `writes.create_user` (no login created) | `writes.update_user` (name, email, phone, city) | no | `edit_users` | **yes** (Manage → Clients) |
| ShopNova refund | `admin_reads.refunds_page` | only through the Coordinator or `approvals.decide` | no | no | `view_dashboard` | read only (Manage → Refunds) |
| ShopNova admin log | `admin_reads.admin_log` | written by every write above | — | — | `view_dashboard` | read only (Manage → Admin log) |
| ShopNova proposal / decision | `admin_reads.proposal` | `writes.record_proposal` (agents) | `writes.record_decision`, `admin_decide_refund` (Coordinator / approvals) | no | — | not exposed (step 4's Refund approvals is the only way) |
| Atlas hotel / flight booking, user | `atlas_app_reads.*_page` (Records) | no core function | no core function | no | `view_dashboard` | read only (Records, step 5); **no management write exists in the core** |
| Atlas refund / compensation / cancel | `atlas_app_reads.refunds_page`, `compensations_page` | only through `atlas_coordinator` / `approvals.decide` (`atlas writes.create_refund`, `create_compensation`, `cancel_hotel_booking` take a proposal id) | `set_proposal_amount`, `set_proposal_confirmation` (Coordinator only) | no | — | not exposed (Approvals, step 5) |
| tickets, messages, steps, approvals (`callverse.db`) | `store.*`, `reads.*` | the channel and the Coordinator | `store.close_approval` (approvals.decide) | no | — | not exposed: the Console stays read only |
| accounts | `accounts.account` | `scripts/create_demo_accounts` (Yassine) | no | no | — | not exposed |

Implemented (commit `e9c2153`):

- **API** `webui/api/manage.py` + routes under `/api/admin/manage/`:
  `GET options` (categories, cities, statuses, the core's limits), `GET {products|orders|users|refunds|log}?search=&page=`
  (the table's own permission; orders carry `moves` and `cancel_blocked` from the core's constants),
  `POST products` (create), `POST products/{id}` (update the given fields), `POST products/{id}/deactivate|reactivate`,
  `POST orders/{id}/status`, `POST users` (create), `POST users/{id}` (update). Server side: role + permission +
  company from the account (`admin_of("shopnova", <permission>)`), CSRF header, 503 when the shop file is missing,
  the core's `{"error": reason}` mapped to 400 `invalid` with the **field** the sentence names (name, price,
  stock, category, email, phone, city), 404 `not_found`, or 409 `refused` (a forbidden move, a paid order,
  already active, nothing to change). A `client_id` per write: the identical request again returns the recorded
  answer (`recorded: true`, no second write); the same id with another payload is 409 `client_id_reused`; a
  refused write is not recorded, so the corrected request may reuse the id.
- **Screen** `/admin/manage` (menu entry "Manage"): tabs Products / Orders / Clients / Refunds / Admin log, search
  and 50 rows per page, "Add a product" / "Add a client" forms and per-row "Edit" (only the changed fields are
  sent), field checks before sending with the limits from `/options` (name, category, price with 2 decimals,
  stock whole number, email with @, phone 8 digits, city served), the core's sentence under the field it
  names, Saving… state with every control disabled, Cancel, the list reloaded after a confirmed write, the new
  record's id in the notice. **Remove from shop** and **Cancel the order** open a dialog that names the exact
  record (id, name / client, price / paid, the effect) with the keyboard rules of the approvals dialog (Tab
  inside, Escape unless busy, focus back to the opener). A lost answer (network drop) is shown as "not
  confirmed … may or may not have been saved" with **Try again** that resends the SAME request id.
- Audit: every write goes through the core's `_log_action` (the admin log tab shows it).

## 2. Unsupported operations (need Yassine / core work)

| Wanted | Why not done | What it would need |
|---|---|---|
| Atlas management (hotels, flights, users: edit a booking, a traveller) | no write function in `callverse/data/atlas/writes.py` for an admin; every Atlas write takes a Coordinator proposal id | admin write functions in the core with their checks and a log, like ShopNova's T18 set |
| Delete anything | the design doc forbids it (products are deactivated, orders cancelled) and no core function exists | none: by design |
| Edit an order's lines, dates, client | no core function | none unless the design changes |
| Reactivate / correct a refund or compensation, edit an approval | by design these are transactions, never edited | none |
| Restock from the Manage page | `update_product(stock=…)` covers it | done through Edit |
| Partial-decision recovery (`approvals.finish`) | still open from step 4 | core function |

## 3. Verification

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` | **92 passed** (82 + 10 `test_manage.py`) |
| `npm --prefix webui/frontend test` | **56 passed** (51 + 5 `Manage.test.jsx`), 11 files |
| `npm --prefix webui/frontend run build` | OK |
| Manage API: no login 401; sara / hedi / supervisor / atlas_admin 403 `admin_only` on every table, option list and write; POST without the CSRF header 403; unknown table 404 | passed |
| Manage API: bad name / category / price / decimals / stock → 400 `invalid` + field, nothing written, log empty; missing row 404; "nothing to change" 409 | passed |
| Orders: forbidden move 409, `refunded` by hand 409, unknown status 400, a delivered order cannot be cancelled, a processing unpaid order can (stock back, logged), a **paid** processing order shows `cancel_blocked` with the core's sentence and is refused | passed |
| Clients: create with phone normalised, duplicate email → 400 field email, bad phone / city → their field, update only the given field, missing 404, log rows | passed |
| Request id: same id + same payload → one product, `recorded: true`; another payload → 409; a refused write leaves the id free | passed |
| Without `shopnova.db`: 503 on read and write, no file created; a product write leaves `atlas.db` byte-identical | passed |
| Screen tests: empty form sends nothing and focuses the first error; the core's field error under the field; corrected submit uses a new id; remove dialog names "1 · Product 1 · 19.90 TND", Tab wraps, Escape returns the focus, one POST with an id, the list reloads; a lost answer → "not confirmed", Try again keeps the id; orders offer only the API's moves, cancel asks first, a 409 shows the core's words and "Nothing was saved."; denied state | passed |
| Existing chat and approval tests (steps 3–7) | unchanged, passing |
| Browser, desktop (demo fixture, fake chat): supervisor tickets, ticket detail, dashboard; admin approvals dialog (Escape); admin dashboard; Manage: add product with empty-form errors then success (id 1217 in a 1,215-row list), remove dialog Tab / Escape / focus back, order 4514 cancel through the dialog, client creation refused on sara's email with the sentence under the Email field | ✔ |
| Browser, phone 375 × 812: Manage products, `scrollWidth` 375 = `clientWidth`, table scrolls inside its panel, tabs wrap into the segmented control | ✔ |
| Keyboard: both dialogs (approvals and Manage) with Tab / Shift+Tab / Escape; forms submit with Enter; the first invalid field is focused | ✔ |
| Reduced motion | the media query zeroes the three duration tokens and stops the spinner and skeleton; checked in the stylesheet and in jsdom (durations are tokens, so no component sets its own); **not** toggled live in the browser pane (no emulation control there) |

Screenshots `webui/reports/screenshots/design-crud/`: `before_*` (the step-7 state) and `after_*` (this pass):
Console tickets, ticket detail, dashboard; ShopNova admin dialog, dashboard; Manage products, add-product form,
orders, products on the phone.

## 4. Remaining limitations

- The after-screenshots were taken through the hidden browser pane: a page captured while its 180 ms entrance
  was paused can look dimmed; the computed opacity was 1 in every case checked.
- The Manage lists show 50 rows per page ordered by id, so a product just added sits on the last page; the
  notice gives its id and name (search finds it).
- The dialog's backdrop fade starts at 0 opacity: in a background tab the overlay is invisible until the tab is
  shown (harmless: nothing can be clicked there).
- `.skeleton` exists but only the Manage tables use it; the other screens keep their spinner.
- The capability matrix is read from the code today; if the core gains Atlas admin writes, the Manage page can
  take an Atlas twin with the same API module.
- Real models, real data, Streamlit side by side: not run (same as the acceptance sheet).
