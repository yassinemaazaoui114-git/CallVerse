# P10 — Register the fine-tuned agent model in Ollama + smoke test (go / no-go)  ·  Dali's lane

## Why
The fine-tuned M2 candidate (Qwen3-4B-Instruct-2507 + LoRA on ABCD) exists only as a file:
`C:\Users\DALI\Desktop\D4\finetuned\callverse-m2-abcd-Q4_K_M.gguf` (2.5 GB). It is not in `ollama list`.
Its Kaggle test (`D4/finetuned/results.md`) is better on ABCD chats but worse on the real Agent B case: after the
fine-tune it called **no tool** and answered "Hello, how can I help you?" (`s1_agentb_after.json`). That test used HF
weights in Kaggle, not the GGUF. This task builds the Ollama model correctly and checks, on the real file, whether the
problem is real. Nothing in CallVerse uses the model yet. Background: `docs/m2_finetune_review.md`.

## Hard limits
- No change to `callverse/`, `config.yaml`, prompts or tests. Only an Ollama model and a small script outside `callverse/`.
- No Groq or Gemini call (zero quota).
- Do not edit or delete anything in `D4/` except writing the generated `Modelfile` there (keep a copy of the
  original as `Modelfile.orig`).
- Never run `tests/data/*` (held-out). Never read or stage `.env`.

## What to do
1. **Build the Modelfile.** In `D4/finetuned/`: copy `Modelfile` to `Modelfile.orig`, then run
   `python make_modelfile.py` (it copies TEMPLATE and PARAMETER lines from `qwen3:4b-instruct-2507-q4_K_M`, which is
   already pulled). Then add these lines by hand:
   - `PARAMETER num_ctx 8192` (one agent turn is ~6,000 tokens, see T13; without it the prompt is cut silently).
   - Keep the base PARAMETER lines as they are; CallVerse sends temperature / seed per request.
2. **Create the model.** `ollama create callverse-m2-abcd -f Modelfile`. Prove it: `ollama list`,
   `ollama show callverse-m2-abcd` (capabilities must list `tools`; parameters must show `num_ctx 8192`).
3. **Smoke script** `scripts/smoke_local_agent.py` (new, small, commented): calls Ollama's OpenAI endpoint
   (`http://localhost:11434/v1`) directly with **CallVerse's real Agent B system prompt and real Agent B tool schemas**
   (import them from `callverse.agents.agent_b` and `callverse.tools.registry.schemas_for("B")`), temperature 0,
   seed 42, and fake tool results copied from the S1 test (`D4/s1_agent_b_test.py`: order 4512, paid 59.9, refunded 0,
   days_late 6 / 3, not delivered). Loop up to 8 steps like `base_agent.py`. Argument `--model`. Same for Agent A with
   one status question ("Where is my order 4512?") and its real tool list.
   Print per try: tools called (in order), arguments, final answer, seconds.
4. **Run it** for `callverse-m2-abcd` and for the base `qwen3:4b-instruct-2507-q4_K_M` (same settings), 3 tries each,
   cases: B-late6, B-late3, A-status. Note `ollama ps` (size, % GPU) once per model.
5. **Go / no-go rule (fixed in advance).** **GO** for P11 only if `callverse-m2-abcd`, on B-late6, calls `get_order` and
   `search_policy` in **3/3** tries and makes **0 invalid calls** in all tries. Otherwise **NO-GO**: report, stop, and
   list which of the likely causes in `docs/m2_finetune_review.md` §3 the outputs point to (diagnosis only, no fix).

## Checks (with numbers)
- `ollama show callverse-m2-abcd`: tools capability yes/no, num_ctx value.
- Table: model × case → tools called x/3, `propose_refund` called x/3 (late6), wrong `propose_refund` x/3 (late3),
  invalid calls, avg seconds, `ollama ps` size / % GPU.
- Compare with `results.md` (Kaggle): does the GGUF behave like the Kaggle "after" (no tools) or not?
- Offline tests still x/x (no code change in `callverse/`, so the same as before: 300/300 on `main`).
- One line: GO or NO-GO, and why.

## Time box and stop rule
60 minutes. Stop and report if `ollama create` fails, the template has no tool support, or the model spills to CPU
so much that one step takes > 60 s.

## Git (needs approval)
Branch `feature/m2-finetuned` from the latest `main`. Commit `scripts/smoke_local_agent.py`, this task file and
`tasks/P10_report.md`. The GGUF and Modelfile stay in `D4/` (never commit model files). No merge into `main`.
Set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
