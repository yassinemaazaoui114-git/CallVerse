# T13d — RAG check: does the policy search find the right rule, the way the agents really use it?

## Why
The agents find company rules with `search_policy` (agentic RAG: bge-small-en-v1.5 embeddings of the 8 rules,
cosine similarity, numpy file). The agents receive only the **2 best rules**, each text cut at **300 characters**.
T06 measured the **top 3** (10/10) on 10 questions, so test and real use do not match. We also never tested typos,
look-alike rules or cancellations. This task only **measures**; no fixes.
All details were agreed with Yassine on 2026-10-28 (items 1–10, all the Brain's ⭐ options).

## Hard limits
- `tests/data/policy_search_questions_v2.json` (20 questions) is **held-out**, written by the Brain and approved by
  Yassine: run it, never change it, never tune anything on it.
- **No fix to the RAG** (no change to `callverse/kb/*`, policies, prompts, agents). The only code change is item 3.
- **No new agent run and no API call** (the search runs on the CPU with the local embedding model).
- Never read or stage `.env`.

## What to do
1. **Git.** `git fetch`; create `feature/t13d-rag-check` from `origin/main` (6a88a4e). Commit this task file,
   `tests/data/policy_search_questions_v2.json` and `tasks/NEXT.md` first.
2. **Cancellation questions:** p19 and p20 have `expected: []` (we have no cancellation rule). Do not score them;
   report the 2 rules that come back and their scores.
3. **Small change to `scripts/eval_policy_search.py`:** also count and print **top-2** (an expected rule among the
   2 best = what the agents see), next to top-1 and top-3; skip questions with an empty `expected` from the scores
   and print them as "not scored". One offline test.
4. **Run the new set once:** `python -m scripts.eval_policy_search tests/data/policy_search_questions_v2.json`.
   For each question: the 3 rules returned with their scores, the **gap between the 1st and 2nd score**, and
   OK / top-2 / top-3 / MISS. Paste the output as printed.
5. **Re-run the old T06 set once, report only:** `tests/data/policy_search_questions.json` → its top-1 / top-2 / top-3.
6. **How the agents really search (existing traces only, no new runs):** from the traces of T12
   (`traces/run_20261024_101903_139840.jsonl`) and T13c (`traces/run_20261028_*.jsonl`), list every `policy_search`
   step: the agent's query text, the 2 rules it got, and whether the rule the agent then cited / the Coordinator used
   was among them. Count: queries, right rule in the 2, right rule missing.
7. **Cut rules:** list every rule whose text is longer than 300 characters and the part the agents never see.

## Checks (with numbers)
- Offline tests x/y (all pass).
- New set (18 scored): **top-1 x/18 · top-2 x/18 · top-3 x/18**; list of every question not in the top-2, with the
  rule that took its place.
- Old set (10): top-1 / top-2 / top-3.
- Agents' real queries: n queries, right rule in the 2 returned x/n.
- Cut rules: ids, lengths, the lost text.
- 3 sentences: is the RAG good enough for the agents today, its weakest case, and what to fix first (suggestion only).

## Time box and stop rule
1 h. Stop and report if the embedding model cannot load, or a test fails.

## Git (approved by Yassine, 2026-10-28)
Commit and push `feature/t13d-rag-check` (task file, question set, eval-script change + test, report, NEXT.md).
**No merge into `main`.** Write `tasks/T13d_report.md` (In plain words · Done · Evidence · Problems · Questions for
the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
