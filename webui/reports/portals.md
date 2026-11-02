# UI replacement — separate sign-in pages (for Yassine)

Branch `feat/ui-react` · after `fb11649` · folder `webui/` · 2026-11-02 · Dali's lane. `callverse/` unchanged,
Streamlit apps unchanged, same accounts file, same password check, same session store. No merge, no push.
**Not an acceptance.**

## 1. In plain words

ShopNova, Atlas Travel and the CallVerse Console now each have their own sign-in page with their own name,
colours and words: `/shop/login`, `/atlas/login`, `/console/login`. `/login` only asks where you want to go.
The server, not the page, decides who may sign in where: ShopNova's page accepts only ShopNova customers and its
admin, Atlas's page only Atlas travellers and its admin, the Console's page only the supervisor. A wrong password
and a right password on the wrong page get the same message, so nobody learns which accounts exist elsewhere.
Links, logout and an expired session go back to the right page; after signing in you return to where you were,
but only inside your own part of the product.

## 2. What changed

| Part | Change |
|---|---|
| API `POST /api/auth/login` | takes `portal` (`shop` / `atlas` / `console`). Order: unknown or missing portal → 400 `bad_portal`; password (bcrypt, same check as before, also run for unknown usernames); then the account's role and company **from the accounts file** must match the portal. Any failure after the portal check → 401 `bad_login`, one sentence. A refused attempt changes nothing; a successful one deletes the browser's previous session token and creates a new one. A `company` or `role` in the body is ignored (not even read). |
| API `GET /api/auth/session` | adds `portal` (from the file) so the browser knows where to send a logout or an expired session. |
| `webui/api/auth.py` | `PORTALS`, `portal_of`, `may_use_portal`. |
| `src/portals.js` | the three portals (name, colours, words), which area a path belongs to, the return-path rules. |
| `screens/PortalLogin.jsx` | one component, three brands: a brand panel (mark, name, one-line purpose, three points) next to the form; on a phone the panel becomes a header. Labels, `autocomplete`, paste allowed, 44 px controls, error focused with `role=alert`, password cleared after a refusal. |
| `screens/PortalChooser.jsx` | `/login`: three links, no form. |
| `App.jsx` | the route tree as `AppRoutes` (testable); a protected path without a session → its portal's page with `?next=`; `/console` → `/tickets`. The old shared `Login.jsx` is removed. |
| `Shell.jsx` | logout → the account's own sign-in page. |

Return path (`?next=`): kept only if it is a same-origin app path (no `//host`, scheme, backslash or control
character) of THIS portal; after sign-in followed only into the account's own area (a ShopNova customer coming
from `/admin/manage` lands on My orders, not on the admin page); otherwise the account's home.

**Shared session (by design, documented):** one browser holds one session, whichever page it came through.
Signed in as Sara and opening `/atlas/login`, the page says "You are signed in as Sara Ben Ali. That account does
not use this page. Log out first…" with a Log out button, and shows no form. Signing in through another page
replaces the previous session. There are no separate user databases.

## 3. Evidence

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` | **110 passed** (92 + 18 `test_portals.py`) |
| `npm --prefix webui/frontend test` | **66 passed** (56 + 10 `Portals.test.jsx`), 12 files |
| `npm --prefix webui/frontend run build` | OK |
| API: each of the 13 demo accounts signs in on its own portal only; on the two others 401, no cookie, no session | passed (13 parametrised tests) |
| API: wrong portal, wrong password, unknown user → identical status and body; message names no company | passed |
| API: `company` / `role` in the body ignored (Sara + `company: atlas` on the Atlas page → 401; on ShopNova → a ShopNova customer, 403 on Atlas and admin routes) | passed |
| API: missing / unknown / wrong-case portal → 400 before the password | passed |
| API: refused attempt keeps the session; a new sign-in replaces it and the old token is dead | passed |
| API: company isolation after sign-in (hedi, atlas_admin, supervisor against the other areas) | passed |
| Screens: return-path rules (12 bad inputs dropped, in-portal kept, customer never sent to admin pages); deep link `/admin/manage` → `/shop/login?next=…` → back after sign-in; customer from that link → My orders; `//evil.com` dropped; wrong portal → generic focused error; signed in elsewhere → notice + Log out → form; already signed in here → home; chooser has no form; logout → own page; expiry → own page with `next`, then back | passed |
| Existing workflows (orders, chat, approvals, dashboards, Manage, logout failure) | unchanged tests pass |
| Browser, desktop: chooser; ShopNova, Atlas, Console pages; Console page refuses the ShopNova admin with the generic error (focused, password cleared); supervisor signs in → `/tickets`; `/shop/login` while signed in as supervisor shows the notice, Log out → form + "You are logged out."; `/admin/manage` signed out → `/shop/login?next=%2Fadmin%2Fmanage` → admin → `/admin/manage`; Log out → `/shop/login` | ✔ |
| Browser, phone 375 × 812: the three pages and the chooser, `scrollWidth` 375 = `clientWidth`, submit button 44 px | ✔ |

Screenshots `webui/reports/screenshots/portals/`: `01` chooser, `02` ShopNova, `03` Atlas, `04` Console with the
wrong-portal error, `05` ShopNova page while signed in as the supervisor, `06`–`08` the three pages on a phone,
`09` chooser on a phone. Some shots were taken during the card's 180 ms entrance and look slightly paler.

## 4. Limits and questions

- The portal is a sign-in rule. Every data route still checks role, permission and company itself, as before.
- Signed in through one portal, a person who types another area's URL sees that area's "Not available for your
  account" box (the API answers 403); no data is shown. A redirect to their own home could be added if wanted.
- The Streamlit apps keep their own sign-in; nothing changed there.
- Real accounts (`config/accounts.yaml`) were not used; the demo fixture and test accounts only.
