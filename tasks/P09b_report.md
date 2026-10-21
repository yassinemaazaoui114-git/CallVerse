# P09b report — Demo screen: S3 + notifications, Host check, live check

## 1. In plain words
The demo page can now play the whole delivery-notification story (S3): the client asks to be told when order 4510
arrives, CallVerse approves it, you move the simulated clock with the +24 h / +30 h buttons, and "Send notifications"
shows ShopNova's message "your order 4510 has been delivered" in the chat. Typed messages now keep their changes until
you press Reset demo. The demo also refuses requests addressed to any host other than this computer. Finally, the live
check with the real models was done on this PC: S1, S2, S4, S3 and a typed message all worked as expected. Three
screenshots are in `docs/screenshots/`.

## 2. Done
- **Merged `origin/main` into `feature/demo-screen`** (T09: story S3 + notifier). No conflicts.
- **S3 button**: resets data **and clock**, runs "Hi, can you let me know when my order 4510 arrives?" through the
  pipeline, shows the reply, and returns `next: ["+24 h", "+30 h", "Send notifications"]`. The page then shows a
  "Next in this story" row with those buttons.
- **Clock buttons** (top bar and the Next row) **add** time to the simulation clock: +24 h, then +30 h = 54 h after the
  start. Each press shows the new time and the timeline events in the chat.
- **Send notifications** calls `callverse.notifier.notifier.run_notifier()`. Each message is shown in the chat as
  "ShopNova (notification, order N)", and in a **Notifications** stage (sent text + source, notifier run count).
  "No notification to send" when there is none.
- **Typed messages keep the data** (they never re-seed; only Reset demo does). There's a line under the chat:
  "Data changes stay until you press Reset demo." Story buttons still start from fresh data and clear the chat.
- **Host check**: every demo route refuses a `Host` other than `127.0.0.1:<port>` / `localhost:<port>` → 403
  (port = `server.port` if set, default 8000). `scripts/run_platform_server.py` reads the same port.
- **Stage fix**: Intake's own read-tool calls now appear on the Intake card instead of the Agent card.
- **Tests** (`tests/test_demo.py`, +4 → 19): S3 story → clock → notifier (0 / 1 / 0); typed messages keep the data;
  wrong Host → 403 (and wrong port); notifier missing → "not available yet". To pass the Host check, 2 lines of the P09
  tests changed: the test client uses `http://127.0.0.1:8000`, and the same-origin header matches it; the fixture pins
  the port to 8000. "S3 not available" now tests an unknown story (S9), since S3 exists.
- **Contract**: P09b line in §8 (Host check, S3 `next`, notifier answer, typed messages don't re-seed).
- **Screenshots**: `docs/screenshots/p09b_s1_refund.png` (full page), `p09b_s4_layer3.png`, `p09b_s3_notification.png`.

## 3. Evidence
- **Tests: 284 passed / 284** (`python -m pytest -q`). The intake libraries are installed now, so the 3 earlier
  failures are gone. The other existing tests are unchanged; only `test_demo.py` (mine, P09) changed as described above.
- **S3 on the page (test and live)**: 1 subscription (4510, delivered, waiting). Notifications: **0** after +24 h (4510
  out_for_delivery), **1** after +30 h more (delivered), **0** when pressed again; the subscription is then `sent`.
- **Wrong Host → 403** (test), wrong port → 403, `localhost:8000` → 200. **Demo off → 404** (unchanged test).
- **Live check** (real models: Groq `openai/gpt-oss-120b` for the agents, Ollama `qwen2.5:3b` for the SLM, intake local
  models; server on `127.0.0.1:8001`, see Problems). Seconds = pipeline time for the run:

  | Run | Seconds | Result |
  |---|---|---|
  | S1 | 29.3 (24.3 in the screenshot run) | reply "I'm sorry for the trouble. Your refund of 59.90 TND is approved. Your order 4512 is now cancelled."; Coordinator: 9 checks, all PASS; decision APPROVE |
  | S2 | 86.2 | decisions **SEND_BACK** (refund_limit R-REF-05 FAIL on the injected 70.00) then **APPROVE**; same final reply as S1 |
  | S4 | 39.3 (29.7) | Layer 3 step: "finance approved for 378.0 TND", check `layer3 R-ESC-01` PASS; reply "... Your refund of 378.00 TND is approved after a check by our finance team." |
  | S3 | 14.6 (15.8) | decision approve / subscribe; reply "... You will get a message here when your order is delivered."; then 0 / 1 / 0 notifications, message "Hello, your order 4510 has been delivered." (2.8 s) |
  | typed: "Hello, my order 4513 should arrive soon, where is it now?" | 4.8 | route A, info, reply from the SLM |

  No response contained `gsk_` or `AIza` (the live script checks every response). After the runs: Reset demo, then a
  re-seed. Local DB MD5 `e18ff80b…` (seed state).
- **Screenshots**: headless Edge with a fresh, empty profile in the scratchpad (no autofill, no saved data). They show only
  the demo page: no terminal, no `.env`, no key.

## 4. Problems
- **Port 8000 was already in use** by another `scripts/run_platform_server.py` (started 03:07, not by me; probably
  Dali's, running older code). I didn't stop it. I ran the live check on **8001** by setting `server.port: 8001` and
  `demo_enabled: true` in the working copy only. Both are back to the committed values (`git diff config.yaml` is empty;
  `test_default_config_has_the_demo_off` passes).
  **Side effect**: before I noticed, my live script's first two calls reached that other server. Its `/demo/reset`
  re-seeded the shared database, which is harmless, and its S1 answered HTTP 500; it runs older code, so I can't see why.
  Both servers use the same `callverse/data/shopnova.db`.
- **S2 took 86 s**: Groq rate-limit waits (`llm wait` notes, visible on the Agent card) plus two full agent runs. S4
  also shows waits. That's acceptable for a demo, but worth knowing before presenting live.
- **The agents don't follow exactly the same steps every run**: in the screenshot S1 run, Agent B skipped
  `search_policy`. The Coordinator still approved and showed a NOTE "rule R-REF-03 was not searched by the agent" (T07's
  warning). Groq's model is not at temperature 0.
- **Typed 4513 reply**: the SLM wrote "It seems there was a delay" for an order that is on time. That's an SLM wording
  issue (core), not a demo bug.
- Test change for the Host check (2 lines in my P09 test file), explained above.

## 5. Questions for the Brain
1. Should `/demo/reset` also be offered as a script (`scripts/reset_demo.py`) for presenting without the browser?
2. For the live presentation: should S2's injected error be shown as a separate visible step in the chat, or is the Agent
   card enough?
3. Should two servers sharing one DB be prevented (e.g. a lock file), or is "one server at a time" a rule for the team?

## 6. Next step
Merge `feature/demo-screen` into `main` after review (owners' OK). For the presentation: start one server, set
`demo_enabled: true` locally, press Reset demo, then S1 → S2 → S4 → S3 (+24 h → Send → +30 h → Send).

Git: merged `origin/main` into `feature/demo-screen` (own branch), committed and pushed. Not merged into `main`.
