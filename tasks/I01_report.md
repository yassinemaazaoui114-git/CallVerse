# I01 report — Integration: platform + Intake + voice channel

## 1. In plain words
The customer website now runs the whole CallVerse chain instead of only Agent A. A typed or spoken message
is first checked for the customer's identity. It is then understood by Intake (why the client writes, how
they feel, how urgent it is), sent by the Router to the right agent, and answered. The reply is shown and
spoken, and the conversation continues over several turns. The parts that teammates have not built yet
(Agent B, the Coordinator, the reply writer, the final router) are clearly marked "not built" in every
answer. Nothing pretends to be finished: a refund request is only passed on, and no action is ever executed.

## 2. Done
Base: `main` c2984b1 (platform P01–P04 + Intake T03), plus `platform` P05 (local server + dashboard, still
unreviewed), plus the voice V01 patch. Conflicts were only in `config.yaml` and `requirements.txt`
(both sides appended a section, both kept).

**New `callverse/integration/`:**
- `workflow.py`: Intake → Router → agent → Coordinator → response writer, with `steps` (real / interim / mock / not built / skipped).
- `components.py`: finds the team's router, Agent B, Coordinator and SLM at call time, by the interfaces of T04, Brief #2 and T05.
- `interim_router.py`: exactly the approved T04 rules, used only until `callverse/queues/router.py` exists.

**Changed:**
- `callverse/web/pipeline.py`: identity gate (now in both modes, because Intake reads order facts), then the workflow.
- `callverse/web/app.py`: `steps` / `ticket` / `route` in replies, component status in `/api/health`.
- `static/app.js` + `style.css`: the "How CallVerse handled this" panel; reply labels (agent, handover, security check, MOCK).
- `scripts/run_web.py`: preloads Intake in the background.
- `scripts/download_voice_models.py`: also fetches the Intake models; downloads are now atomic with retries.
- `requirements-voice.txt`: no duplicate of P05's web dependencies.
- Docs: `docs/integration.md` (new), `docs/voice_channel.md`, `README.md`.

**Tests:**
- New `tests/test_integration_workflow.py` (17, with the REAL Intake models).
- `tests/test_web_pipeline.py` and `tests/test_web_api.py` updated (fake Intake for speed; new handover, routing and steps checks).
- `tests/test_web_browser.py` updated to the integrated multi-turn flow.

**Not changed:** agents, `llm.py`, tools, registry, Intake, platform code, policies, teammates' tests,
`tasks/NEXT.md`, `tasks/NEXT_PLATFORM.md` (its P05 status comes from the `platform` branch as is).

## 3. Evidence

| Check | Result |
|---|---|
| Merged tree before integration code (main + P05 + V01) | **168/168** |
| Final suite | **187 passed**, 1 opt-in module skipped. 2 runs: main 88 + P05 15 + voice/integration 84 |
| Browser E2E, real Chromium + fake microphone, real Whisper, Intake and Piper | **2/2**, 3 runs in a row |
| `demo_platform.py` and `demo_platform_http.py` RESULT lines | **8/8 identical** to the `platform` branch |
| `run_intake` "…a week late. I want my money back!" | late_delivery 0.845, **HIGH 0.832** (same as T04a) |
| T04 check: "Order 4512 is a week late. I want my money back." | main reason refund_request, route **B**, handover recorded (test) |
| A proposal with no Coordinator | not executed: 0 refund rows written (test) |
| Team router / Coordinator / SLM plugged in as fake modules | used automatically, statuses "real" (tests) |
| Admin dashboard (P05) | 127.0.0.1:8000 returns 200 for `/` and `/summary` |
| Customer app with the same data | `/summary` and `/admin/reset` return 404 |
| Docker | 3-turn conversation OK (see below); 868 MB RAM; admin routes 404 |
| Secret scan | 0 |

Docker conversation (2 CPUs, user 1000, no key):
1. Voice question "Hello, where is my order 4512?" → the email is asked.
2. Email → Intake REAL / Router INTERIM / Agent A MOCK, spoken.
3. "I want my money back for order 4512" → Router → B → handover recorded, spoken.

## 4. Problems
- **Not committed or pushed:** CLAUDE.md rule 1 needs Yassine's approval of the Git section in `tasks/I01_integration_platform_voice.md`.
- **P05 is unreviewed** but included (Dali's NEXT_PLATFORM: WAITING FOR REVIEW).
- **Docker image size:** Docker Hub rate-limited the base image (429), so the integrated image was verified as a layer on the V01 image (same `python:3.12-slim` base, same steps). Its 7.22 GB includes the old layers; a clean build was not measured.
- **REAL with a live Groq key was not run** (no key here); it is covered by fake-LLM tests.
- **French:** Intake is English-only, so French reasons and emotions are weak.
- **Concurrent model loading:** Intake models may load twice if the first message arrives during the background preload (memory spike only).
- **Cut downloads:** a model download cut off in the build exposed a bug (a partial file would later be treated as complete); fixed.

## 5. Questions for the Brain
1. Approve the Git section (commit + push `integration/platform-voice` + PR, no merge)?
2. Review P05 first, or accept it in this integration PR?
3. When T04 lands, delete `interim_router.py`: should T04 also adopt the identity gate, or keep it in the channel?
4. Agent B / Coordinator: is `proposal` in the agent result (Brief #2 format) the agreed hand-off to `review()`?

## 6. Next step
Approve and push, deploy the image to a Hugging Face Space with `GROQ_API_KEY`, run the REAL demo live.
Then T04 (router), Agent B + Coordinator, and T05 (SLM) plug in through `components.py` with no channel change.
