# T05b — SLM: client-facing decisions, exact key sentences, calm opener, temperature 0, try qwen2.5:3b  ·  Dali's lane

## Why
T05 met its targets, but the model made meaning mistakes the rule check can't see (s06: "378 did not meet the 300
threshold", "contact finance directly"), skipped the calm opener for an angry client, and copied agent-facing text.
The fix: the **facts that must not be misstated are written by code**, and the model only writes around them.

## Hard limits
- Branch `feature/slm` (continue). Do not merge. Do not change the Coordinator, agents, intake or platform files.
- `tests/data/slm_test_decisions_v2.json` (written by the Brain) is the **new held-out set**: never use it to write or tune
  prompts, checks or forbidden phrases; run it once at the end. The v1 set is spent (dev use only from now on).
- Local model only. No secrets in files.

## What to do
1. **Decision format** (`docs/decision_format.md`): `next_step` is **written to the client** (never to the agent);
   new optional field **`must_say`**: a list of exact sentences or phrases the reply must contain word for word.
   (The Coordinator will fill both in the integration task.)
2. **Writer**: the prompt tells the model to include every `must_say` item **exactly**; the rule check verifies each one is
   present (case-insensitive), else retry → template. Templates include the `must_say` items too.
3. **Calm opener by code**: if `style.shouting` or `sentiment == negative`, the writer starts the reply with a fixed short
   opener chosen from a small list (e.g. "I'm sorry for the trouble."), instead of relying on the model.
4. **Temperature 0** for the `slm` role (`config.yaml`).
5. **More forbidden phrases** found on the dev/v1 sets: e.g. "contact … directly", "as quickly as possible", "soon",
   "minimum threshold". Keep the list in `config.yaml`.
6. **Try `qwen2.5:3b`** (≈2 GB): if free VRAM ≥ 2.5 GB and a reply takes ≤ 10 s, use 3b; else keep 1.5b. Compare both on
   the **dev set** only and report.

## Checks (with numbers)
- Held-out v2 (run once at the end): replies passing **without** template **≥ 5/6**; final replies **6/6**;
  `must_say` present **6/6**; forbidden phrases **0**; numbers not in facts **0**.
- v2-02 (Layer 3): the reply contains the exact 300 TND sentence and does **not** tell the client to contact finance.
- v2-01: starts with a calm opener (angry client).
- Same decision run twice → **identical** reply (temperature 0).
- Model used (1.5b or 3b), VRAM, average seconds per reply. All tests pass (report x/y).

## Time box and stop rule
90 minutes. Stop and report if the model can't follow `must_say` on the dev set.

## Git (approved)
Commit and push `feature/slm`. No merge. Write `tasks/T05b_report.md`, set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.

## Notes from review (Dali, 2026-10-20)
- **Temperature needs a small `llm.py` change**: `chat()` sends no sampling options today. Allowed: optional per-model
  settings in `config.yaml` (e.g. `{provider: ollama, model: "qwen2.5:1.5b", temperature: 0, seed: 42}`) passed into the
  request. Nothing else in `llm.py` changes; other roles behave exactly as before. Set `seed` too, so "same decision twice
  → identical reply" holds on Ollama.
- **Moving the forbidden list to `config.yaml`**: keep the current (pattern, keyword) behaviour and its tests; the T05
  entries stay.
- **Held-out v2**: no test and no prompt-tuning script reads `tests/data/slm_test_decisions_v2.json`; only the final
  `run_slm.py --all test2` run (or similar) does, once.
