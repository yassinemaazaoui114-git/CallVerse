# T05 — SLM: the reply writer (M5)  ·  Dali's lane

## Why
Deciding and wording are separate. The Coordinator fixes **what** is said (the decision); the SLM only decides
**how**, in the user's style (teacher: "adaptive answers" — same decision, wording adapted to the person).
A small local model is fast, free, private and fine-tunable later. A rule check after it guarantees the reply says
only what was approved.

## Hard limits
- Model: **`qwen2.5:3b` via Ollama**, local only. If the PC has < 4 GB free VRAM or a reply takes > 10 s, use
  `qwen2.5:1.5b` and report it. (Licence note for the report: 3B = Qwen licence, 1.5B = Apache 2.0.)
- The SLM gets **no tools** and never reads the database. Its only input is the decision dict + style + recent messages.
- It must not add any fact, number, date, amount or promise that is not in the decision.
- Reuse the shared LLM layer: add provider `ollama` (`base_url: http://localhost:11434/v1`) and role `slm` in
  `config.yaml`. Minimal change allowed in `callverse/llm.py`: a provider with `key_env: null` needs no key.
- **Never tune on test data:** `tests/data/slm_test_decisions.json` (6 decisions, written by the Brain) is held out.
  Write your own **dev set** (6–10 decisions) in `callverse/slm/dev_decisions.json` to iterate on the prompt.
- Do not change agents, tools, intake, platform files. No secrets in files.

## What to do
1. **Decision format** — document it in `docs/decision_format.md` (the Coordinator will produce it later):
   `outcome` (approve | send_back | ask_user | ask_proof | layer3 | escalate | info), `action`, `order_id`, `rule_id`,
   `facts` (dict of the only facts allowed in the reply), `next_step` (one sentence), `style` (from Intake).
2. **Writer** — `callverse/slm/writer.py`: `write_reply(decision, history=None) -> {reply, check, attempts, used_template}`.
   Prompt: write in the user's style (formal/casual, short/medium, calm opener if shouting or negative), state only the
   facts and next step, mention the order number, max ~80 words, no internal rule ids in the text.
3. **Rule check** — `callverse/slm/check.py`: every number in the reply (amounts, dates, order ids, days) must appear in
   `facts`/`order_id`; no forbidden promises (e.g. "we will keep you updated", "we are monitoring", "guarantee",
   "within X hours/days" unless in facts); not empty; ≤ 120 words. Return `{passed, problems[]}`.
4. **Retry + template fallback** — if the check fails: one retry with the problems listed; if it fails again, use a fixed
   template per outcome (`callverse/slm/templates.py`). The final reply must always pass the check.
5. **Script** — `scripts/run_slm.py --id s01` (from the test file) or `--file my_decision.json`: prints the reply, the
   check result and the time.
6. **Tests** (no Ollama needed): check rules (good and bad replies), template per outcome passes the check, writer flow
   with a fake LLM (fail → retry → template).
7. Trace every SLM call and check (`slm_call`, `slm_check`, `slm_template`).

## Checks (with numbers)
- Held-out set (6 decisions, run once at the end): replies passing the check **without** template ≥ **5/6**;
  final replies passing the check **6/6**.
- s01 vs s02 (same decision, formal vs casual-angry): the two replies are clearly different in tone (paste both).
- s06 (Layer 3): the reply does **not** promise the refund.
- Forbidden phrases in final replies: **0**. Numbers not in facts: **0**.
- Average time per reply on your PC (report GPU/VRAM and model tag).
- All tests pass (report x/y).

## Time box and stop rule
2 hours. If Ollama is not installed, install it (ollama.com), `ollama pull qwen2.5:3b`, and report the steps.
If the model can't run, stop and report.

## Git (approved by Dali, 2026-10-20)
From the latest `main`, create branch `feature/slm`. Commit and push it. **Do not merge into `main`.**
Write `tasks/T05_report.md` (6-section format) and set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
