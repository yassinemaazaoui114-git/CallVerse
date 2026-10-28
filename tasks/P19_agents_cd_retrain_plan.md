# P19 — Retrain plan for C/D, only on the failures of P18, human data only (plan, no training)  ·  needs Yassine's OK

## Why
Only if P18's decision line says "retrain candidate". The first fine-tune (`callverse-m2-abcd`) improved ABCD scores
but broke the real CallVerse behaviour (greets "Acme", no tool calls; smoke test 2026-10-28). So this time the plan
is narrow: target **only the failure types P18 measured**, keep the base model's good behaviour, and use **no
AI-generated data**. This task writes the plan; the training itself is a later, separate task in the D4 folder.

## Team data rule (hard)
- **No AI-generated training text.** Allowed sources only: (a) human chats from ABCD (MIT licence), changed by
  **written, rule-based** transformations (code, not a model); (b) chats **written by hand** by team members, each
  with the author's name.
- **Agent traces from Groq (gpt-oss) or any other model do not count as training data**, even if correct and even if
  a person checked them. The same for Ollama traces, the simulator (Gemini) and SLM outputs.
- `generated` users/orders in `seed.py` (`ai_generated = 1`) may be used as **facts** in a hand-written chat (an order
  id, a date), never as chat text.
- Never use `tests/dev/agents_cd_cases.json` messages or `tests/data/*` as training text (a hand-written chat may not
  copy a test message or reuse a test case's order + intent pair). Write it in the plan as a check.

## Hard limits
- Write **one file**: `docs/agents_cd_retrain_plan.md`. No training, no data file, no change to `callverse/`,
  `config.yaml`, prompts or tests. No LLM call.
- Use P18's numbers only. Do not open the held-out file.

## What to do
1. **Failure table.** Copy P18's failure types × agent counts. Keep only types with ≥ 1 failure. For each, say if
   training is the right fix or if code already covers it (e.g. `text_only_claim` and "policy not searched" are
   P13's code checks; a code check comes first, training only for what is left).
2. **One data recipe per remaining type** (counts are targets, write them; say where each chat comes from):
   - `no_tool` / `missing_tool`: ABCD chats cut to start at the client's request with the order id already given
     (`pipeline.ticket_note` format), greeting and identity check removed by rule; first agent turn = the tool calls.
   - `acted_wrongly`: "no action" chats in balance with action chats: ABCD chats where the agent refuses or only
     explains a policy, plus hand-written boundary pairs like C06/C09 (same text, facts across the limit) on **other**
     orders and other wordings than the test set.
   - `did_not_act`: hand-written chats where the proposal tool is called before the final answer, in the exact
     run-time shape (`propose_refund` / `propose_subscription` with all required fields, `rule_id` required).
   - `bad_args`: rule-based fixes of ABCD slot values to CallVerse argument names and types (int order ids, event
     names from R-NOT-01).
   - `wrong_tool`: train with each agent's **real** allow-list only (`registry.schemas_for("C")` / `("D")`).
3. **Format** = run time (lessons of `docs/m2_finetune_review.md` §6): each agent's real `SYSTEM_PROMPT`, its real
   tool schemas, `sim_today`, plain-text answers. No neutral "online store" prompt, no shared tool list.
4. **Train / dev / held-out.** Training data = only the new chats above. Checkpoint choice and learning-rate choice
   on the **P17 dev split** (+ the P10 smoke cases), never on ABCD loss alone. The held-out split is read **once**, at
   the end, for the final number.
5. **Pass rule after retrain (fixed now):** the retrained model replaces the base model for C/D only if, on dev and
   then on held-out, it is **not worse than P18 on any agent**, has **0 `acted_wrongly`**, and still passes the P10
   smoke cases (B-late6, B-late3, A-status) with the base model's tool behaviour. Otherwise keep the base model.
6. **Plan the work:** who writes the hand-written chats (names), how many each, time estimate, where the data lives
   (`D4/`, not this repo), what the next task file (training run) must contain. Add a sheet template for hand-written
   chats: `author, date, agent, source (hand / ABCD id + rule), order facts used, chat`.
7. **No-retrain option.** Write the plan's alternative in 3 lines: keep the base model + P13 code checks + Groq
   fallback, and what that costs (quota, latency).

## Checks (with numbers)
- `docs/agents_cd_retrain_plan.md` exists with: failure table from P18, one recipe per kept type with target counts,
  data-source line per recipe (ABCD rule / hand-written), the pass rule, the data-rule checklist, the no-retrain option.
- Count: target chats total, of which ABCD-transformed n, hand-written n; 0 from any model's output.
- A check list a reviewer can tick: no Groq/Ollama/Gemini traces used · no test message copied · held-out not opened.

## Time box and stop rule
60 minutes. Stop if P18 says "good enough without retraining": then write only the no-retrain option and the reason.

## Git (needs approval)
Continue `feature/agents-cd`. Commit `docs/agents_cd_retrain_plan.md`, this task file and `tasks/P19_report.md`.
No merge into `main`. Training starts only with a new, approved task.
