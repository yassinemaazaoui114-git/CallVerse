# Review: switching the agents (M2) to the fine-tuned local model

Written 2026-10-27 for the team (Yassine, Dali, Semah) and the Brain. Basis: `main` at `d125959` (300/300 offline
tests pass on Dali's laptop), branch `origin/feature/t13-test-model` (not merged), and the fine-tune output in
`C:\Users\DALI\Desktop\D4\finetuned\` (`results.md`, `s1_agentb_before/after.json`, `tool_eval_*.jsonl`).

## 1. In plain words
We trained a small local model (Qwen3-4B + LoRA on the ABCD support chats) so the agents could run on the laptop
instead of Groq. On ABCD's own test chats it got much better at choosing tools. But on the one real CallVerse test
(Agent B's real prompt, order 4512, 6 days late) it got worse: it now answers "Hello, how can I help you?" and calls
no tool at all. So we must not switch the agents to it yet. The tasks below first check this on the real Ollama file,
then measure it on the 24 practice messages, and only switch if it passes rules fixed in advance. Groq stays as backup.

## 2. What the code looks like today (relevant parts)
| Part | File | Note for the switch |
|---|---|---|
| One LLM layer, role `agents` | `callverse/llm.py`, `config.yaml` `models.agents` | Chain gpt-oss-120b → gpt-oss-20b → gemini-3.5-flash. Moves to the next model **only on provider errors** (429, 404, 5xx, network, Groq `tool_use_failed`), never because an answer is bad. |
| Local switch | `origin/feature/t13-test-model`: `CALLVERSE_AGENTS_SET=local` → `models.agents_local` | Ready-made way to run a local agent model without touching the default chain. **Not on `main` yet.** |
| Agent loop | `callverse/agents/base_agent.py` | OpenAI tool calls; max 5 steps (B: 8). |
| Agent A | `agent_a.py`, tools `get_user, get_order, get_tracking, get_company_profile, search_policy, propose_subscription` | |
| Agent B | `agent_b.py`, tools `get_order, get_refunds, search_policy, propose_refund, ask_agent` | |
| Agents C, D | **no code** | See section 5. |
| Other users of role `agents` | `callverse/intake/llm_fallback.py`, `ask_agent` sub-call | They switch together with the agents. |
| Coordinator | `callverse/coordinator/coordinator.py` | Rules only. `rule_not_searched` is only a **trace warning** (line ~258), it does not send back. |
| SLM | `callverse/slm/writer.py`, `qwen2.5:3b` on Ollama, warm-up at start | Shares the GPU with a local agent model. |

Note on the name: in `callverse-m2-abcd`, "abcd" is the **ABCD dataset** (ASAPP), not "agents A to D".

## 3. Fine-tune results (from `D4/finetuned/results.md`)
Base `unsloth/Qwen3-4B-Instruct-2507`, LoRA r=16, 1 epoch, lr 2e-4, 2,737 train chats, best dev loss 0.966.

| ABCD test split | before | after |
|---|---:|---:|
| call / no-call decision right | 0.644 | **0.789** |
| right tool (gold-call turns) | 0.283 | **0.692** |
| right tool + right args | 0.267 | **0.658** |
| wrong call on text-only turns | 0.233 | **0.117** |
| invalid / broken calls | 0.011 | **0** |
| propose_refund right tool + args | 0 | **0.733** |
| search_policy right tool + args | 0.167 | **0.567** |

| S1 Agent B cases (real prompt, 5 tries) | before | after |
|---|---:|---:|
| late6 (6 days late): right proposal x/5 | 0 | 0 |
| late3 (3 days late): strict pass x/5 | **5** | **0** |
| tools called (all tries) | 4 read tools every try | **none** |

Raw answers after the fine-tune (`s1_agentb_after.json`): "Hello, how can I help you?", "Can I have your name, please?",
"how much did you pay for the order?". Before, the base model read all 4 facts, cited R-REF-03 and the right
amount 59.9 TND, but wrote the proposal as text instead of calling `propose_refund` (same gap T13 saw with qwen3.5:4b).

**Reading:** better in-distribution (ABCD), worse out-of-distribution (CallVerse). Likely causes, to be **checked**, not
assumed:
1. ABCD chats open with a greeting and an identity check (name, account id). The model learned "first turn = ask".
2. Training used a neutral "online store" system prompt; at run time each agent has its own long prompt.
3. `get_refunds`, `ask_agent` and (for B) `propose_subscription` have **0 training examples**; Agent B's tool list
   differs from the training list.
4. `rule_id` was optional in training, required at run time.
5. The S1 eval ran in Kaggle with HF 4-bit weights + sampling (temp 0.7). The **GGUF in Ollama was never tested.**

## 4. Problems found that matter for any agent model
- **Model not registered in Ollama.** `ollama list` shows `qwen3:4b-instruct-2507-q4_K_M` (base, needed by
  `make_modelfile.py`) but no `callverse-m2-abcd`. `D4/finetuned/Modelfile` has only the `FROM` line: without the
  template copied by `make_modelfile.py`, Ollama would not parse tool calls.
- **Context cut.** The base Modelfile has no `num_ctx`. One agent turn is ~6,000 tokens (T13); Ollama's default
  context is smaller and cuts the prompt silently. Needs `PARAMETER num_ctx 8192`.
- **4 GB GPU (Dali's RTX 3050 Ti).** GGUF 2.5 GB + KV cache at 8k (~1.2 GB) + SLM qwen2.5:3b (1.9 GB) do not fit
  together: Ollama swaps models, ~12 s per swap (D4 summary, S1). One ticket has several agent ↔ SLM switches.
  Default timeout is 60 s (`llm.DEFAULT_TIMEOUT_S`); only the SLM has a warm-up.
- **Groq fallback does not cover bad answers.** If the local model answers "Hello, how can I help?" the chain does
  not move to Groq (no provider error). Only the T10 safety net in `pipeline.run_agent_with_coordinator` retries once
  (same model) when the agent used no tool.
- **"Says it proposes, but does not call the tool."** Base Qwen3-4B and qwen3.5:4b (T13) both do it. The Coordinator
  ignores text-only claims (safe), but the refund path is never exercised.
- **Agent B sometimes skips `search_policy`.** The Coordinator only logs `rule_not_searched`; it does not send back.
- **S1 wording mismatch.** `coordinator.user_words` says "Your order N is now cancelled." for R-REF-03, while
  `_finish` sets the order status to `refunded` (coordinator.py lines ~78 and ~328). The client is told "cancelled",
  the database says "refunded".

## 5. Decisions for the team (not invented here)
1. **Agents C and D.** There is no code, prompt, tool list or rule for them. The D4 summary mentions Atlas Travel
   (hotel cancellations) as a later add-on, and CLAUDE.md says C, D, E, F are **out of scope for the prototype**.
   Before any task: what is C's job and company (ShopNova or Atlas)? What is D? Their tools and allow-lists? Is this
   a change to the locked scope? Until decided, "switch A to D" = switch **A and B**.
2. **Locked decision M2.** CLAUDE.md locks M2 = gpt-oss-120b on Groq. Making a local model the default changes a
   locked decision: needs Yassine's OK (task P12 is written so it stops there).
3. **Retrain or not.** If P10 confirms the regression on the GGUF, the next step is a v3 dataset (CallVerse system
   prompts, CallVerse tool lists including `get_refunds` / `ask_agent`, chats where the order id is already given,
   required `rule_id`), done in the D4 folder, not in this repo. Who owns it and is there time before the validation?
4. **T13 branch.** Tasks P11 to P14 build on `feature/t13-test-model` (the local switch). Merge it into `main` first,
   or let P11 branch from it?
5. **Behaviour fallback to Groq.** Should a local agent that makes no tool call (after the T10 retry) be re-run once on
   the Groq chain? (P12 proposes it; it is a pipeline change.)

## 6. Recommendations for the next fine-tune (v3), human data only
Rule kept: no AI-generated training text. Every change below is a rule-based transformation of ABCD's human chats,
or chats written by hand by the team.
1. **Train in the run-time format.** Use each agent's real system prompt (`agent_a.SYSTEM_PROMPT`,
   `agent_b.SYSTEM_PROMPT`) and its real tool list (`registry.schemas_for("A")` / `("B")`) instead of the neutral prompt
   and one shared list. Make `rule_id` required as at run time. This is the most likely cause of the S1 regression.
2. **Cut the ABCD opening.** Drop the greeting and identity check (name, account id, "how can I help") and start each chat
   at the client's request, with the order id already given the way CallVerse gives it (`pipeline.ticket_note`).
   The model must learn "order id given = call tools now", not "first ask the name".
3. **Fill the tools that have 0 examples, by rule.** `get_refunds`: insert it next to `get_order` in refund chats, result
   computed from the ABCD scenario (refunded_total 0). `ask_agent`: in Agent B chats, replace `get_tracking` with
   `ask_agent("A", ...)` returning the same status. No human source for `propose_subscription` in ABCD: leave it out or
   use the team's hand-written chats.
4. **Keep "no refund" chats.** ABCD chats where the agent refuses or only explains a policy teach "no proposal" (the
   late3 case). Keep them in balance with refund chats; keep the cut of FAQ-only chats.
5. **A small hand-written CallVerse set.** 50 to 100 short chats written by the team from the dev scenarios (never from
   `tests/data/*`), in the exact run-time format. Use them as extra training data or, at least, as the dev set.
6. **Choose the checkpoint on CallVerse, not on ABCD loss.** Run the S1 cases (late6, late3) and an Agent A status case
   at every eval step with temperature 0, and keep the best checkpoint on those. Consider a lower learning rate (1e-4) or
   fewer steps if CallVerse scores fall while ABCD loss improves.
7. **Test the GGUF, not only the Kaggle weights.** After export, run P10's smoke script on the Ollama model.
Do P10 first: if the GGUF already behaves well in Ollama, v3 may not be needed.

## 7. Task files written (none approved yet, NEXT files not changed)
| Task | What | Depends on |
|---|---|---|
| `tasks/P10_register_finetuned_m2.md` | Build the Ollama model (template + num_ctx), smoke test on the real Agent B / A prompts, go / no-go | — |
| `tasks/P11_finetuned_m2_bakeoff.md` | Add it to `models.agents_local`, run the 24 practice messages vs base Qwen3-4B, fixed choice rule | P10 = go, decision 4 |
| `tasks/P12_promote_m2_with_groq_fallback.md` | Make it the default agents model, Groq chain behind it, behaviour fallback | P11 pass, decisions 2 and 5 |
| `tasks/P13_agent_safety_checks.md` | Code checks: text-only proposal claim, missing `search_policy`, "cancelled" vs "refunded" | none (useful for every model; core files: Yassine's OK) |
| `tasks/P14_gpu_swap_4gb.md` | Measure and cut the agent ↔ SLM swap on 4 GB | P10 |
