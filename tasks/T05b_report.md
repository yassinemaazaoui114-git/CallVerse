# T05b report — SLM fixes: client-facing decisions, exact sentences, calm opener by code, temperature 0, qwen2.5:3b

## 1. In plain words
The reply writer is now more reliable because the parts that must not go wrong are no longer left to the AI model.
The Coordinator can give exact sentences (`must_say`) that the reply must copy word for word, and a check verifies
them. An upset client always gets a fixed calm first sentence, added by code. If the model forgets the order number,
code adds it. The model now runs at temperature 0 with a fixed seed, so the same decision always gives the same
reply. The larger `qwen2.5:3b` model fits on this PC and is fast enough, so it is now used. On the 6 new held-out
decisions, all replies passed the check on the first try and contained every required sentence.

## 2. Done
- **Decision format** (`docs/decision_format.md`): `next_step` is written **to the client**. New optional field
  `must_say` (list of exact sentences). A new section lists the parts written by code.
- **`must_say`**: the prompt asks the model to copy each item exactly. `check_reply` refuses a reply missing any item
  (case-insensitive, spaces ignored), and `must_say` text counts as approved (its numbers and words are allowed).
  Templates append any `must_say` item not already present.
- **Written by code** (`callverse/slm/writer.py`, `finish()`):
  - calm opener when `style.shouting` or `sentiment == "negative"`: a fixed sentence by formality from
    `config.yaml` (`slm.calm_openers`); a greeting or apology the model wrote is removed so it is not doubled;
    the prompt tells the model not to write one;
  - "About your order N:" inserted if the model forgot the order number;
  - exact repeated sentences removed.
  Templates use the same opener.
- **Temperature 0 + seed 42** for the `slm` role. `callverse/llm.py`: optional per-model settings (`temperature`, `seed`,
  `top_p`, `max_tokens`) from `config.yaml` are sent only when set, so other roles are unchanged (tested).
- **Forbidden list moved to `config.yaml`** (`slm.forbidden`, the same (pattern, keyword) behaviour). The 9 T05 entries
  are kept, plus 5 new ones seen on the dev and v1 sets: "contact … directly", "as quickly as possible",
  "minimum threshold / did not meet the", "committed to resolving", "technical issue". ("soon" was already there.)
- **Model**: `qwen2.5:3b` (pulled with `ollama pull qwen2.5:3b`), chosen by the T05b rule (see Evidence).
  `qwen2.5:1.5b` stays installed as the fallback (edit one line in `config.yaml`).
- **Dev set**: `must_say` added to 6 of my 8 dev decisions (my own sentences). Their next steps were already written to
  the client.
- **`scripts/run_slm.py`**: new set `test2` (v2 held-out, final run only); v1 (`test`) marked as spent / dev use;
  `--model` override for comparison runs (in memory only); the summary now counts `must_say` presence.
- **Tests** (`tests/test_slm.py`, +14 → 45): `must_say` checked word for word, `must_say` numbers allowed, templates for all
  7 outcomes include `must_say`, the calm opener by code (writer + templates), the prompt lists `must_say`, the forbidden
  list comes from config (T05 + T05b entries), and `llm.py` sends temperature/seed only when configured.
  No test reads `slm_test_decisions_v2.json`.

## 3. Evidence
- **Held-out discipline**: I printed only v2's ids and key names, to see that `must_say` is a list. I never printed
  its values, and nothing was written or tuned from it. It was run **once**, at the end, after every change.
  Output: `run_slm.py --all test2`, trace `traces/run_20261021_000512_696812.jsonl`.
- **Held-out v2 (6 decisions, qwen2.5:3b)**:
  - passed **without** template: **6/6** (all on the first try);
  - final replies passing: **6/6**;
  - `must_say` present: **6/6**;
  - forbidden phrases: **0**; numbers not in facts: **0**;
  - average **3.37 s** per reply (first, cold call 5.05 s).
- **v2-02 (Layer 3)**: "Please accept our apologies for the trouble. Order 4515, Your refund request of 378.00 TND is
  above our 300 TND limit, so our finance team must approve it first. We will reply in this conversation once our finance
  team has decided." → it contains the exact 300 TND `must_say` sentence (the check passed) and does **not** tell the
  client to contact finance.
- **v2-01** (angry client): "I'm really sorry for the trouble. Order 4512, Your refund of 59.90 TND is approved. Your refund
  of 59.90 TND is approved and goes back to your original payment method." → starts with the calm opener.
- **Same decision twice → identical reply**: the dev set was run twice per model and all 8 replies were identical, for
  1.5b and for 3b. The held-out set was run once only, by design.
- **Model choice** (rule: 3b if free VRAM ≥ 2.5 GB and a reply takes ≤ 10 s):
  - free VRAM with no model loaded: **3.32 GB** (RTX 3050 Ti Laptop, 4 GB total);
  - 3b loaded: **2.01 GB**, all on the GPU (`ollama ps`); 1.15 GB left free;
  - slowest warm 3b reply on dev: 3.82 s; cold first call: 5.9–8 s. Both are ≤ 10 s, so **3b**.
- **1.5b vs 3b on the dev set only** (8 decisions, temperature 0) and the spent v1 set (6):

  | | 1.5b | 3b |
  |---|---|---|
  | dev: passed without template | 8/8 | 8/8 |
  | dev: `must_say` present | 6/6 | 6/6 |
  | dev: order number by the model itself (no code insert) | 4/8 | 7/8 |
  | dev: average time | 2.85 s | 3.11–3.33 s |
  | v1: passed without template | 6/6 | 6/6 |
  | v1: average time | 3.52 s | 3.74 s |
  | meaning errors seen on dev | none | d03: "has not arrived by the promised date of 2026-10-11" (it is on time) |

  Earlier, before the code fixes and still at temperature 0, 1.5b passed 4/8 on dev without the template; most failures
  were a missing order number.
- **Tests**: **143 passed / 146**. The 3 failures are `test_intake` ×2 and `test_pipeline` ×1, all
  `ModuleNotFoundError: sentence_transformers`: intake's local models are not installed on this PC, and the same tests
  fail on `main` (98/101). T05b's 45 SLM tests all pass.

## 4. Problems
- **Wording is still imperfect** (the check passes, a person would notice):
  - v2-01 says "Your refund of 59.90 TND is approved" twice (the second time inside a longer sentence, so it is not an
    exact repeat and not removed);
  - "Order 4512, Your …" has an odd comma and capital;
  - v2-04 starts "order 4512, please confirm…" with a lowercase letter and no "Dear customer" for a formal client.
- **3b made one meaning error on dev** (d03, a wrong "not arrived by the promised date") that 1.5b did not make. I
  followed the task rule (3b), but 3b is not better at meaning on every case.
- **Some passes are code-assisted**: the opener and the order reference are added by code, as T05b intends. Without the
  order-number insert, 1.5b would have failed more replies; 3b inserted the number itself in 7/8 dev cases.
- **The retry rarely helps at temperature 0**: the same prompt plus a short problem list often gives the same reply. The
  template stays the safety net.
- **v1 decisions still have next steps written to the agent** ("do not promise it", "Ask the client…"), and both models
  copy them. That is expected: the format now says `next_step` is written to the client, and v1 predates that rule.
- **VRAM**: with 3b loaded, 1.15 GB is left. Another GPU program running at the same time could push Ollama to CPU
  (slower). The fallback is one line in `config.yaml`.

## 5. Questions for the Brain
1. Keep 3b (task rule, better at the order number, one meaning error on dev) or prefer 1.5b (faster, no meaning error on
   dev, Apache 2.0)? I applied the rule: 3b.
2. Should the integration task make the Coordinator fill `must_say` for every amount it approves (e.g. "Your refund of
   X TND is approved.")? It is the strongest guard against misstated facts.
3. Should code also fix capitalisation after the order reference ("Order 4512, Your" → "Order 4512: your")? It is cosmetic,
   but visible in a demo.

## 6. Next step
Integration (T07): the Coordinator produces decisions in this format, with a client-facing `next_step` and `must_say` for
key facts. The pipeline then ends with `write_reply(decision, history)`. Optional SLM polish, checked on a fresh held-out
set: capitalisation clean-up and near-duplicate detection.

Git: continued on `feature/slm`, committed and pushed. Not merged into `main`.
