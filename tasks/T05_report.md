# T05 report — SLM: the reply writer (M5)

## 1. In plain words
The last step of the pipeline now exists: a small AI model on this PC turns the Coordinator's decision into a
reply in the client's style (formal or casual, short or longer, calmer for an upset client). It never looks at
the database and gets no tools; it only sees the decision. After it writes, a plain-code check makes sure the reply
contains no new number, no forbidden promise and no internal code. If the reply fails twice, a fixed template is
sent instead, so every final reply passes the check. On the 6 held-out decisions, 5 replies passed without the template
and 6 of 6 final replies passed. Reading them, though, I see wording mistakes the check cannot catch (details below).

## 2. Done
- **Model**: `qwen2.5:1.5b` via Ollama (pulled with `ollama pull qwen2.5:1.5b`; Ollama 0.40.6 was already installed and
  running). The task rule picked 1.5b over 3b: the RTX 3050 Ti Laptop has 4 GB of VRAM, of which only ~3.3 GB is free
  (< 4 GB). Licence: Apache 2.0 (the 3B model has the Qwen licence).
- **Shared LLM layer**: `config.yaml` gets provider `ollama` (`http://localhost:11434/v1`, `key_env: null`) and role `slm`.
  `callverse/llm.py`: a provider with `key_env: null` needs no key (6 lines changed, nothing else).
- **`docs/decision_format.md`**: the decision dict (outcome, action, order_id, rule_id, facts, next_step, style), what each
  outcome may and may not say, and the rule check.
- **`callverse/slm/writer.py`**: `write_reply(decision, history=None) -> {reply, check, attempts, used_template, seconds}`.
  The prompt gives the rules, the outcome guidance, the allowed content (order number, facts, next step, not the rule id),
  the tone from Intake's style (exact opener, length, a calm sentence if upset), the exact words "order N" for the first
  sentence, the next step to end with, the client's last messages for tone only, and on a retry the check's problems.
  `clean()` only removes formatting (a "Reply:" label, quotes, a signature block).
- **`callverse/slm/check.py`**: `check_reply(reply, decision) -> {passed, problems}`. It checks:
  - every number in the reply appears in facts, order_id or next_step;
  - the order number is mentioned;
  - no forbidden promises: keep you updated, monitoring, guarantee, within X hours/days, contacting the carrier,
    notify you, soon / shortly / immediately, any updates, compensation — unless the idea is in the decision;
  - no refund promise unless the outcome is `approve` for a refund;
  - no rule id, placeholder, foreign currency, carrier name that isn't in the facts, or repeated sentence;
  - not empty and at most 120 words.
- **`callverse/slm/templates.py`**: one template per outcome, built only from facts, order_id and next_step.
- **Retry + template**: 1st try → check → 1 retry listing the problems → template. If Ollama is down, the template is
  used and nothing crashes.
- **Traces**: `slm_call`, `slm_check`, `slm_template` (plus the shared `llm_call` line).
- **Dev set**: `callverse/slm/dev_decisions.json`, 8 decisions written by me (orders 5042, 4513, 4510, 4507, 5017,
  4506, 4514; all 7 outcomes except send_back; formal / casual / shouting). All prompt and check work used this set only.
- **`scripts/run_slm.py`**: `--id s01` (held-out), `--file`, `--dev d02`, `--all dev|test` (with a summary).
- **`tests/test_slm.py`**: 31 tests with no Ollama: good and bad replies, Layer 3 refund promises, templates for all
  7 outcomes passing the check, writer flow with a fake LLM (pass, fail → retry, fail twice → template, model down →
  template, no tools sent), prompt content, clean-up.

## 3. Evidence
- **Held-out discipline**: before the final run I printed only the test file's ids and key names (to match the field
  names), never its values or wording. The held-out set was run **once**, after all changes. Output: `run_slm.py --all test`,
  trace `traces/run_20261020_234254_635795.jsonl`.
- **Held-out results (6 decisions)**:
  - passed the check without template: **5/6** (all 5 on the first try); s05 used the template;
  - final replies passing the check: **6/6**;
  - forbidden phrases in final replies (rule list): **0**; numbers not in facts: **0**;
  - average time **3.61 s** per reply (model warm; the first call after loading takes ~8 s).
- **s01 vs s02** (same decision, formal vs casual-angry):
  - s01: "Dear customer, Order 4512 has been approved, and the corresponding request for a refund is being processed.
    The refund is approved; the money goes back to the original payment method, as stated in the details. We apologize
    for any inconvenience caused by the delay and further appreciate your understanding. Please contact us if you have
    any additional questions."
  - s02: "Hi, Order 4512 is approved; the refund is approved; the money goes back to the original payment method."
  - They differ clearly in **register and length**: formal and 4 sentences vs casual and 1 sentence. But s02 has **no calm
    opening sentence** for the angry client, even though the prompt asks for one.
- **s06 (Layer 3)**: "Dear customer, We apologize for the inconvenience this has caused, but the refund for order 4515
  needs to be approved by the finance team first. The total refund amount is 378.0 TND, and the initial review did not
  meet the minimum threshold of 300 TND. Please contact the finance team directly for approval of the refund. We apologize
  for any inconvenience this has caused and are committed to resolving your issue as quickly as possible. Thank you."
  → it does **not** promise the refund (check passed). See Problems for its other errors.
- **Dev set** (last runs): 7/8 without template, 8/8 final, ~3.7 s average.
- **GPU / model**: NVIDIA GeForce RTX 3050 Ti Laptop GPU, 4096 MiB; `qwen2.5:1.5b` (1.5B, Q4_K_M) fully on the GPU,
  ~1.17 GB of VRAM (`ollama ps`).
- **Tests**: **129 passed / 132**. The 3 failures (`test_intake` ×2, `test_pipeline` ×1) are `ModuleNotFoundError:
  sentence_transformers`: the intake models are not installed on this PC. The same 3 fail on `main` without my
  changes (98/101), so T05 adds 31 tests and breaks none.

## 4. Problems
Honest reading of the held-out replies (found **after** the single run; nothing was changed afterwards):
- **s06 has errors the rules cannot see**: it invents a next step ("Please contact the finance team directly"; the
  decision says finance reviews it and ShopNova replies), it says the amount "did not meet the minimum threshold of
  300 TND" (it is **above** it), and it ends with "as quickly as possible", a vague promise. My forbidden list has
  "as soon as possible" but not this wording. No refund is promised.
- **s05 used the template** (both SLM tries failed). The template and s04 copy `next_step` word for word, and these
  decisions' next steps are written **to the agent**, not to the client: s05 ends with "Ask the client for a photo
  before any replacement or refund", and s04 says "The client will get a message…". See Question 1.
- **Upset clients**: the calm opener is often missing (s02), even though the prompt asks for it. The 1.5B model follows
  long instructions only partly.
- **The rule check has limits**: it catches numbers, names, codes and known promise phrases, but not meaning (a wrong
  comparison, an invented reason such as "refunded due to a technical issue" in a dev run, or a wrong next step).
  For those, a bigger model (3b on a GPU with more free VRAM), a second "meaning" check, or a fine-tuned SLM would help.
- **Not reproducible**: Ollama's default temperature makes replies change between runs (dev runs went 6/8 → 7/8 → 7/8).
  Setting `temperature: 0` needs a change in `llm.py` beyond the allowed minimum, so I did not do it.
- **Order-number rule**: the check requires the order number in the reply. The task asks for it in the prompt, and I made
  the check enforce it too.
- **Branch**: the working copy was on `main` when I started (someone had switched from `platform`). I created
  `feature/slm` from `main` (22aa220 = `origin/main`). Dali's uncommitted `tasks/NEXT_PLATFORM.md` change (P07 accepted,
  T05 READY) was in the working tree; it is committed here with my status update.

## 5. Questions for the Brain
1. **`next_step` audience**: should the Coordinator write `next_step` **to the client** ("Please send a photo of the
   damaged item")? The SLM and the templates repeat it, so text written to the agent ends up in the client's reply.
   I suggest adding that to `docs/decision_format.md` as a rule.
2. May I set `temperature: 0` (or a low value) for the `slm` role? It is a small change in `llm.py` (optional per-role
   settings in `config.yaml`), and it makes evaluations reproducible.
3. Should the forbidden list grow ("as quickly as possible", "committed to resolving", "contact … directly")? That should be
   checked on a **new** held-out set, because these were found on this one.
4. Is 1.5b acceptable for the demo, or should we test `qwen2.5:3b` (it would need ~2 GB of VRAM; free is ~3.3 GB, so it
   probably fits, but the task rule said < 4 GB free → 1.5b)?

## 6. Next step
T07 (Coordinator) produces decisions in this format, with `next_step` addressed to the client. Then the pipeline can
end with `write_reply(decision, history)`. For the SLM itself: low temperature, a few more forbidden phrases, then a
fresh held-out set (and later, optionally, fine-tuning on approved replies).

Git: branch `feature/slm` created from the latest `main`, committed and pushed. Not merged into `main`.
