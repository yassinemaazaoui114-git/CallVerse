# T12 report — Run the unseen live-typing test once (roadmap step 06)

## 1. In plain words
We ran the whole system once on 20 free-typed messages it had never seen. All 20 passed: nothing crashed,
no private data leaked, and no wrong change was written to the company data. On average a message took
16.4 seconds, the slowest 51.3 seconds. The main model hit its per-minute limit 5 times; each time the
backup model answered, so the run finished normally.

## 2. Done
- Git: `main` at `d125959`, new branch `feature/t12-heldout`. Committed the T11 files and this task file (`ff010f9`).
- Offline tests (no API).
- Quota window check from `traces/*.jsonl` (one-off PowerShell command, no new script).
- Ollama check: `ollama list`, `GET /api/tags`, plus one local `qwen2.5:3b` prompt (local only, no cloud quota).
- The held-out run, **once**, file unchanged.
- `python -m scripts.quota_check` after the run.
- Filled the held-out numbers into `tasks/T10_report.md` and `tasks/T10b_report.md` (section 3, "done in T12").
- No code, config, policy, rule or `tests/data/*` change. No fix after the run. `.env` not read or staged.

## 3. Evidence
- **Offline tests: 300/300 passed** (79 s).
- **Tokens in the 24 h before the run** (`llm_call` in traces written after 2026-10-23 10:17; only Yassine's
  quota check at 10:11 matched): gpt-oss-120b **96** (1 call) · gpt-oss-20b 90 (1) · gemini-3.5-flash 55 (1).
  Far below the 60,000 stop line.
- **Ollama:** up, `qwen2.5:3b` listed in `ollama list` and `/api/tags`; test prompt answered "OK." (21.3 s, cold start).
- **The run** (2026-10-24 10:19–~10:25): `python -m scripts.run_live_check --file tests/data/live_typing_test_messages.json`,
  exit 0. Not aborted. No warm-up `Warning:` line from the script (trace `slm_warmup`: ok, 2.9 s). The only
  "Warning:" printed was the Hugging Face Hub notice about a missing `HF_TOKEN` (from model loading, not the script).

Per-message table and SUMMARY, exactly as printed:
```
L01   route A  info           writes -  PASS    (7.3 s)
      reply [slm_retry]: Your order 4510 is on its way.
L02   route A  info           writes -  PASS    (3.2 s)
      reply [slm]: I'm sorry for the trouble. Please tell us your order number so we can check it.
L03   route A  info           writes -  PASS    (4.1 s)
      reply [slm]: Hello, we could not find order 9999. Please check the order number and send it again.
L04   route B  approve        writes ['refund 4512 59.9']  PASS    (29.3 s)
      reply [slm]: I'm sorry for the trouble. Your refund of 59.90 TND is approved. Order 4512. Your order 4512 is now cancelled.
L05   route B  approve        writes ['refund 4515 378.0']  PASS    (25.4 s)
      reply [slm]: I'm sorry for the trouble. Your refund of 378.00 TND is approved after a check by our finance team. Your order 4515 is now cancelled.
L06   route A  info           writes -  PASS    (7.0 s)
      reply [slm]: Hello, I can help with your ShopNova orders: delivery, refunds, returns and damaged items. If your question is about an order, please send us the order number.
L07   route B  approve        writes ['refund 4512 59.9']  PASS    (51.3 s)
      reply [slm]: Hello, your refund of 59.90 TND is approved. Your order 4512 is now cancelled.
L08   route B  info           writes -  PASS    (18.6 s)
      reply [slm]: I'm sorry for the trouble. Your order 4508 is delivered. No delay occurred as per the promised date with carrier Rapid-Poste.
L09   route B  info           writes -  PASS    (17.6 s)
      reply [slm]: Your order 4506 is refunded.
L10   route B  info           writes -  PASS    (10.0 s)
      reply [slm]: I'm sorry for the trouble. Your order 4510 is on its way. No follow-up needed as per the promised date.
L11   route B  ask_proof      writes -  PASS    (5.7 s)
      reply [slm]: I'm sorry for the trouble. Order 4513. Please send us a photo of the damage.
L12   route B  ask_proof      writes -  PASS    (5.1 s)
      reply [slm]: I'm sorry for the trouble. Order 4507. Please send us a photo of the damage.
L13   route B  approve        writes ['refund 4512 59.9']  PASS    (31.0 s)
      reply [slm]: I'm sorry for the trouble. Your refund of 59.90 TND is approved. Your order 4512 is now cancelled.
L14   route B  info           writes -  PASS    (16.0 s)
      reply [slm]: Hello, your order 4514 is being prepared. The promised date has not been met.
L15   route B  info           writes -  PASS    (19.6 s)
      reply [slm]: I'm sorry for the trouble. Your order 4511 is being prepared. The promised date has not been met, as it is still in the processing stage with no delay.
L16   route A  approve        writes ['subscribe 4513 out_for_delivery']  PASS    (12.8 s)
      reply [slm]: Hello, order 4513. You will get a message here when your order is out for delivery.
L17   route A  info           writes -  PASS    (16.0 s)
      reply [slm]: Dear customer, your order 4512 is delayed at the delivery depot. It is now 6 days late.
L18   route A  info           writes -  PASS    (7.2 s)
      reply [slm]: Hello, your order 4512 is delayed at the delivery depot. It is now 6 days late.
L19   route A  info           writes -  PASS    (6.8 s)
      reply [slm]: Hello, I can help with your ShopNova orders: delivery, refunds, returns and damaged items. If your question is about an order, please send us the order number.
L20   route B  approve        writes ['refund 4512 59.9']  PASS    (33.9 s)
      reply [slm]: I'm sorry for the trouble. Your refund of 59.90 TND is approved. Your order 4512 is now cancelled.

SUMMARY: 20/20 passed · crashes 0 · leaks 0 · wrong writes 0 · avg 16.4 s · max 51.3 s
Results: out\live_check_live_typing_test_messages.json   Trace: C:\Users\mam83\dev\callverse-proto\traces\run_20261024_101903_139840.jsonl
```

- **Checks vs pass rule:** crashes **0** · leaks **0** · wrong writes **0** · fully passing **20/20** · avg **16.4 s** ·
  max **51.3 s** (L07). **Pass = 0 · 0 · 0 · ≥ 18/20 → met.**
- **FAILs:** none.
- **Models that answered** (count of `llm_call` in `traces/run_20261024_101903_139840.jsonl`) and **tokens used**:

  | Model | Role | Calls | Tokens |
  |---|---|---|---|
  | groq / openai/gpt-oss-120b | agents (main) | 81 | 75,337 |
  | groq / openai/gpt-oss-20b | agents (backup) | 6 | 5,486 |
  | google / gemini-3.5-flash | quota ping only | 1 | 76 |
  | ollama / qwen2.5:3b | SLM | 22 | 12,320 |

- **Backup model used: yes, gpt-oss-20b, 5 times.** Each followed an `llm_fallback` on gpt-oss-120b with
  `RateLimitError 429 ... tokens per minute (TPM): Limit 8000` (per-minute limit, not the daily limit), at
  10:20:09, 10:20:18, 10:20:54, 10:23:19, 10:24:01. The 6th gpt-oss-20b call and the Gemini call are the
  script's pre-run quota ping (10:19:24–26). Gemini never answered a message.
- Other trace counts: 1 `agent_retry` (Agent B, missing order-id check), 3 `intake_llm_fallback`, 1 SLM retry (L01 `[slm_retry]`).
- **`quota_check` after the run:** gpt-oss-120b OK · gpt-oss-20b OK · gemini-3.5-flash OK.

## 4. Problems
- **I saw part of the held-out data.** While reading the trace for the fallback reasons, I printed
  `intake_llm_fallback` and `agent_retry` lines. They contain the text of 3 held-out messages and one draft agent
  answer. I did not open the test file and changed nothing, but the Brain should know this. Please treat those
  3 messages as seen by the Builder (they must not be used for later fixes).
- **The per-minute limit of gpt-oss-120b (8,000 TPM) was hit 5 times.** The backup model saved the run, so
  about 6% of the agent calls were answered by the smaller model. The score is for "120b with 20b backup", not 120b alone.
- **Some replies sound odd, though the checker passed them** (observed only, not fixed): L08 "No delay occurred
  as per the promised date...", L15 "The promised date has not been met, as it is ... with no delay" (says late
  and not late together), L04 "Order 4512." as a stray sentence. These come from the SLM wording. Per the rules,
  any fix must be checked on new data (roadmap step 08), not on this file.
- Slowest messages are refunds on route B (L07 51.3 s, L20 33.9 s, L13 31.0 s), partly the TPM wait plus fallback.

## 5. Questions for the Brain
1. The 3 held-out messages I saw in the trace: is this acceptable, or should the step-08 check exclude anything similar?
2. Should the checker also catch contradicting replies like L15 (late and not late in one reply)? That would be a
   checker change for step 08, tested on new data.
3. To avoid the 120b per-minute limit in the real demo: is a short pause between messages wanted, or is the 20b backup fine?

## 6. Next step
Brain review of these numbers. Then roadmap step 08: fix the reply wording issues on new data (not on this file).
