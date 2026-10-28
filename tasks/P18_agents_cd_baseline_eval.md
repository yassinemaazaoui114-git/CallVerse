# P18 — Baseline: base Qwen3-4B-Instruct on the C/D dev set (no retrain, no prompt change)  ·  Dali's lane

## Why
We must know how the **untrained** base model does on C and D before anyone decides to retrain (P19). This task runs
the P17 dev set on `cv-qwen3-4b-instruct` through Ollama, 3 tries per case, and writes down every failure with its
type. Nothing is fixed here: a baseline only counts.

## Hard limits
- Only `tests/dev/agents_cd_cases.json`. **Never** `tests/data/agents_cd_heldout.json` or any other `tests/data/*`.
- No change to prompts, agents, allow-lists, Coordinator or the test cases (fix rule as T13: describe, do not fix).
- Local model only: force `cv-qwen3-4b-instruct`. **0 Groq / Google calls** (check: no groq/google `llm_call` lines in
  the traces). An optional Groq reference run is allowed **only** if Yassine writes OK in "Approved by" and
  `python -m scripts.quota_check` shows enough quota; it is never used to choose anything.
- Same settings for every run: temperature 0, seed 42, `num_ctx 8192`.

## What to do
1. `ollama ps` empty, then warm the model once (one tiny call). Note `ollama ps` (size, % GPU) and `nvidia-smi`.
2. Run: `python -m scripts.eval_agents_cd --file tests/dev/agents_cd_cases.json --agent all --tries 3 --model cv-qwen3-4b-instruct`.
3. Repeat the whole run once (repeatability: with temperature 0 and a seed, are the 3 tries and the 2 runs identical?).
4. **Classify each failed try** into exactly one type (write the rule in the report, apply it the same way to all):
   - `no_tool` — answered without any tool although `must_call` is not empty (the S1 / "Acme" slip);
   - `missing_tool` — some tools called, a `must_call` tool missing;
   - `wrong_tool` — a `must_not_call` tool called, or a refused tool (outside the allow-list);
   - `acted_wrongly` — proposal made on a `must_not_act` case (the most serious type);
   - `did_not_act` — no proposal on a `must_act` case;
   - `text_only_claim` — the answer says it proposed / sent for checking, but no proposal tool was called;
   - `bad_args` — right tool, wrong or invalid arguments (wrong order id, event, rule id, amount, broken JSON);
   - `answer_rule` — tools right, but the answer misses the rule id or makes a forbidden promise.
5. For 3 failures of the most common type, copy the model's raw output (tools + answer) into the report.

## Checks (with numbers)
- Table per agent: pass x/7 (per run), must_act pass x/n, must_not_act pass x/n, invalid calls, avg / max s per case,
  repeatable yes/no (tries identical x/7, runs identical yes/no).
- Table of failure types: type × agent → count (over all tries), with case ids.
- `acted_wrongly` count, alone, in the first line of the report.
- Model actually used per call (from the trace): 100 % `cv-qwen3-4b-instruct`, 0 Groq / Google.
- GPU: `ollama ps` size and % GPU; one line on swaps with the SLM if any (P14).
- **Decision line (rule fixed in advance):** the base model is **good enough without retraining** if, on both runs,
  each agent passes **≥ 6/7**, with **0 `acted_wrongly`** and **0 `no_tool`**. Otherwise write "retrain candidate"
  and list the failure types that block it. This line only feeds P19; it changes no config.

## Time box and stop rule
90 minutes. Stop on any Groq / Google call, repeated out-of-memory, or one model step > 60 s.

## Git (needs approval)
Continue `feature/agents-cd`. Commit this task file and `tasks/P18_report.md` (result JSON stays in `traces/`,
copy the tables into the report). No merge into `main`.
