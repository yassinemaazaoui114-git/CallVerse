# T14d report — a write must match the request + switch of Agents A and B to Dali's model

Branch `feat/t14d-request-match` (no merge). Task files: `tasks/T14d_request_action_match.md` (items 0–4, earlier, see
`tasks/T14d_progress.md`) and `tasks/T14d_finish_with_dali_model.md` (this session: Dali's model, switch, held-out).

**WIN RULE: true** (56/56, 0 wrong writes) → Agents A and B switched to `callverse-m2-v3`.
**T14d held-out: 10/12**, 0 crashes, 0 leaks, 0 wrong writes (runner), 0 forbidden words, 0 Groq calls → pass bar met,
but **t02 wrote a 690 TND refund the client did not ask for** (see Problems).

## 1. In plain words
T14d taught the center that a write must match what the customer asked: "cancel this payment" is not "cancel my order",
and a hotel-costs claim is not a ticket refund. With these fixes, we ran Dali's fine-tuned model on all 60 real
customer messages, on this PC only. It got every expected answer right (56 of 56) and made no wrong write, where our
old local model got 46. So Agents A and B now use Dali's model first; Agent B can still fall back to Groq, then Gemini,
if the local model fails. Then we ran the 12 new, never-seen T14d messages once: 10 of 12 passed, all on the local
model, with no API call. One of the 2 failures is serious: a refund was paid to a customer who only asked for help.

## 2. Done
- Items 0–4 (earlier, offline): `callverse/intake/request_words.py` (`cancels_order`, `asks_for_expenses`), Intake,
  LLM fallback, ShopNova Coordinator, `atlas_coordinator.ACTION_REASONS`, `negation.py` step 1c, `run_t14c.py`
  status wrong-write check, `tests/test_t14d.py` (52 tests). Details: `tasks/T14d_progress.md`.
- Step 0: `tasks/NEXT.md` + `tasks/T14d_finish_with_dali_model.md` committed ("NEXT: T14d finish (Brain)", b98391d), pushed.
- Step 1: from `test/m2-v3-agent-b` (commits 474a97a, ee65b5c, 1bf31dc): the `callverse-m2-v3` entry of `config.yaml`
  and `scripts/compare_m2t.py` (copied with `git checkout` / `git apply`; 194bc21). Suite 1335 passed.
- Step 2: setup D (A + B = `callverse-m2-v3`, forced local, 0 Groq calls) on the 5 sets, same runners as M2T3, fresh DBs,
  clock 2026-10-09 → `out/t14d_D_<set>.json` + `.log`. `scripts/compare_m2t.py --t14d` (new mode: the M2T3 code takes a
  list of setups; `--m2t3` output is byte-identical to `out/m2t3_compare.md`) → `out/t14d_compare.md` (2256cf0).
- Step 3 (switch, 8564d0e):
  - `config.yaml`: new list `models.agent_a` = callverse-m2-v3 → cv-qwen3.5-4b → cv-phi4-mini (all local);
    `models.agent_b` = callverse-m2-v3 → Groq gpt-oss-120b → gpt-oss-20b → Gemini 3.5 Flash.
  - `callverse/agents/agent_a.py`: `role_key = "agent_a"`. Why a new list: Agent A and the Intake LLM fallback shared
    the "agents" list; the M2T3 switch text says "Intake fallback unchanged", so A needed its own list (same pattern
    as T16's `agent_b`). The "ask Agent A" sub-call still uses B's list (`ask.py`, comment updated).
  - `callverse/console/reads.py`: an "agent_a" model call is Agent A's (old traces with "agents" still read the same).
  - `scripts/quota_check.py`: checks agents, agent_a, agent_b; when a role's first model is local and answers, it stops
    there (no Groq ping). The ShopNova chat already stopped at the first answer (`web_chat.agent_b_ready`).
  - Tests changed on purpose (they pin the model order): `tests/test_agent_b_model.py` (A's role, B's chain with Gemini,
    the old "B never has Gemini" test replaced by "agent_a is local only"), `tests/test_tickets_channel.py`
    (quota ping = callverse-m2-v3), `tests/test_agents_set.py` (+1 test: quota script does not ping Groq for A / B).
  - Docs: README (agents line, Ollama setup for callverse-m2-v3, models in the app, T14d entry), `docs/architecture.md`
    (M2 row), `docs/DEMO_RUNBOOK.md` (note at the top).
- Step 4: `python -m scripts.run_t14c --file tests/data/t14d_heldout_messages.json --out out/t14d_heldout.json`, once,
  with the app setup: `CALLVERSE_AGENTS_SET=local` only (as `start_*.ps1` / the apps do), no forcing, no `AGENT_B_SET`.
  Nothing fixed after it.

## 3. Evidence

| 60 real messages | M2T3 L (cv-qwen3.5-4b) | M2T3 D (m2-v3, old code) | **T14d D (m2-v3, T14d code)** |
|---|---|---|---|
| expect passes (of 56) | 46 | 53 | **56** |
| wrong writes (M2T3 definition) | 0 | 2 (t14c h03, h12) | **0** |
| crashes / leaks | 0 / 0 | 0 / 0 | 0 / 0 |
| avg / p95 s per message | 17.23 / 24.7 | 18.48 / 22.6 | 18.34 / 22.9 |
| tool errors / refused / step limit (A; B) | 0 | 0 | 0 |
| Groq / API calls | 0 | 0 | 0 |
| Agent A OWN turns | 7 | 7 | 7 (same messages, t14b p01–p04, p06, p11, p12, all pass) |

Per set (T14d D): decline_practice 12/12 · decline_heldout 12/12 · t14b_practice 12/12 · t14c_practice 12/12 · t14c_heldout 12/12.
**WIN RULE (0 crashes, 0 leaks, 0 wrong writes, passes 56 ≥ 46): true.**

What T14d changed against M2T3 D (only 3 messages differ, all in t14c_heldout):
- **h03** (hotel-costs claim, 7008): approve AT-FLT-01 690 TND refund (wrong write) → **decline AT-FLT-06**, 0 rows. PASS.
- **h12** ("please cancel this payment", 4514): order cancelled (wrong write) → **ask_user**, order stays processing. PASS.
- **h04** (7008, ticket refund): ask_user → **approve 690 TND** as expected. PASS.

T14d held-out (12 new real tweets, run once, `out/t14d_heldout.json`, trace `traces/run_20261101_233139_675095.jsonl`):
**10/12 PASS**, crashes 0, leaks 0, wrong writes 0 (runner, incl. order status), forbidden words 0, avg 18.7 s, max 23.0 s.
Models (from the trace): every agent call on **callverse-m2-v3** (agent_b role), every reply on qwen2.5:1.5b,
**0 Groq / Gemini calls, 0 fallbacks**. t06 escalated by code (no agent call). No Agent A own turn in this set.
- t02 FAIL: 7008 "cancelled flight ... no confirmation from BA to hotel. Help" → approve AT-FLT-01, **690 TND refund
  written** (expect 0 refund rows).
- t05 FAIL: 7008 "Cancelled ticket 2 months back and still no refund" → info ("Your flight booking 7008 is cancelled"),
  no refund (expect approve 690).

Note: T14c's held-out ran on Groq; this T14d held-out ran on the local model (Yassine's choice).
Tests: `pytest -q` → **1336 passed / 1336** (1335 before the switch, +1 new quota test).

## 4. Problems
- **t02 is a write the client did not ask for.** The runner does not count it (AT-FLT-01 holds on the data: the flight
  was cancelled), so the pass bar is met, but by M2T3's definition (any refund row the expect does not allow) it is a
  wrong write. Cause (trace): Intake gave `refund_request` **by meaning** (no money-back words in the text), and
  `ACTION_REASONS` trusts the reason, so the refund matched. T14d's word check covers expenses words, not a "help"
  message that the embedding calls a refund request. Not fixed (held-out rule).
- t05 is the reverse case: a clear money-back complaint answered with info. Likely the T14d negation path or the model;
  not looked into further (held-out rule).
- The win rule was measured on sets already seen while building T14d (dev + earlier held-outs); 56/56 there is not
  an unseen score. The unseen score is the T14d held-out: 10/12.
- `CLAUDE.md` still says "M2 Agent B = Groq; Agent A + Intake fallback = cv-qwen3.5-4b". I did not edit it (Brain's file).
- Fresh machines need `callverse-m2-v3` in Ollama (GGUF in git-ignored `models/m2/`, from Dali). If it is missing,
  A falls to cv-qwen3.5-4b and B to Groq.
- New list `agent_a` = a small structure change (a new config role, like T16). Flagged here for the Brain.

## 5. Questions for the Brain
1. t02: should a refund for a booking be confirmed only when the client's words ask for money back (like T14d's
   order-cancel check), instead of trusting the reason found by meaning? That would be a new task (T14e?).
2. Keep the switch even though the held-out shows one unasked refund (Groq made the same kind of write in M2T3)?
3. Update `CLAUDE.md`'s model line to the new setup?

## 6. Next step
Brain review → Yassine merges `feat/t14d-request-match`. Then RL1 merge → step 09 → agent C → agent D, with a small
T14e for the t02 case if the Brain agrees.
