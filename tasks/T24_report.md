# T24 report — M3 settings on the demo PC

## 1. In plain words
The Brain's benchmark preferred the bigger model (bge-base), so I first switched to it and measured it on Yassine's PC.
It is the most accurate, but it is too slow there (the 95th-percentile Intake time was 124-134 ms; the limit is 100 ms).
By the same rule fixed in advance, the system keeps the small model (bge-small) but uses the better settings found in
T23 (look at the 5 closest examples, thresholds 0.69 / 0.54) and the special BGE question prefix for rule search. On the
PC the numbers equal T23's validation numbers, the speed is well inside the limits, and the two live checks give the
same results as before. Nothing is merged into main.

## 2. Done
- Step 0: T23 merged locally into main (merge 4ea501b, **not pushed**), tests 1048/1048; branch `feature/t24-m3-switch`.
- `config.yaml`: bge-small + pinned revision `5c38ec7c…` (new key `intake.embedding_revision`, passed to
  SentenceTransformer in `reasons.get_model`), `top_k` 5, ShopNova 0.69, Atlas 0.54, comments say where values come from.
- `callverse/kb/search.py`: `QUERY_PROMPT` + `embed_query` (query side only; rules embedded as before), both companies.
- `benchmarks/m3/pc_check.py`: measures the system's own code on the PC, val sets only (Windows RAM).
- `.gitignore`: `models/`. Docs: `docs/benchmarks/M3.md` section 8 (bge-base not chosen, why), README.
- Tests changed (4): `test_routing_by_company.py` ×3 (`shopnova threshold 0.66→0.69`; Atlas leave-one-out 0.68/(58,10,12)→0.54/(62,17,1);
  ShopNova leave-one-out 0.66/(47,4,9)→0.69/(40,5,15)); `test_m3_benchmark.py` ×1 (matcher test now uses config's top_k 5, threshold 0.69).

## 3. Evidence
Step 2, PC (torch 2.14.1 CPU, 12 threads), val only, `benchmarks/m3/results/pc_check*.json`:

| | bge-base | **bge-small (chosen)** | Limit |
|---|---|---|---|
| Intake avg macro-F1 | 0.6905 | **0.6473** (= T23) | |
| ShopNova critical / needs-LLM | 25 / 36.0 % | 26 / 40.6 % | |
| Atlas critical / needs-LLM | 1 / 0 % | 1 / 2.5 % | |
| Search top-1 / top-2 / MRR | 28 / 30 / 0.967 | 27 / 30 / 0.95 | |
| Intake p50 / p95 | 76 / 134 ms (rerun 70 / 124) | 40 / **60 ms** | 100 ms |
| Search p50 / p95 | 84 / 92 ms | 41 / **47 ms** | 200 ms |
| Peak RAM | 921 MB | **662 MB** | 1.5 GB |

Step 3 (leave-one-out on the examples, report only): ShopNova 0.69 → 40 exact, 5 wrong, **15 to the LLM** of 60 (its own best
would be 0.65: 45/6/9). Atlas 0.54 → 62 exact, 17 wrong, **1 to the LLM** of 80 (its best would be 0.67: 60/8/12).
Thresholds stay the benchmark's. Note the examples-based and val-based choices disagree: the leave-one-out favours higher thresholds on Atlas.

Step 4: tests **1048/1048**.

Step 5 live check (fresh databases, free RAM 1.8 GB):

| | d05 (ShopNova) | a03 (Atlas) |
|---|---|---|
| Outcome | approve, route B, refund 4512 **59.90** | approve, Solved, refund 7005 **1,500.00** |
| Total seconds | 20.4 | 29.6 |
| Groq tokens | 7,325 (incl. 3 quota pings) | 5,648 |
| Gemini | 87 tokens = the quota ping only, no simulator call | 0 |
Intake per message, warm, same process, median of 5: before (top_k 3, 0.66 / 0.68) ShopNova 0.066 s, Atlas 0.063 s → after
(top_k 5, 0.69 / 0.54) 0.065 s / 0.063 s: no change. (Cold first message ≈ 9-20 s = the models loading, as in T21/T22.)
Both replies came from the template (the local SLM was not reachable), as in earlier runs. Both DBs reseeded; no `callverse.db` left.
`git status`: only `.vscode/` untracked; no models, `.env`, raw data staged.

## 4. Problems
- The total Groq tokens (about 13,000) are a bit under the "about 15,000" in the task.
- The Atlas threshold 0.54 gives 17 wrong of 80 on the examples' leave-one-out (it rarely sends to the LLM). It was tuned on the 40 val messages; worth watching in the Atlas live tests.
- bge-base data: `pc_check_bge-base.json` is the first of two runs (134 ms); the rerun (124 ms) is in the docs only.

## 5. Questions for the Brain
1. Atlas 0.54 vs the leave-one-out (best 0.67): keep the benchmark's, as ordered?
2. Re-run the benchmark selection with a PC-measured speed in the rule (so the chosen model is fixed on the machine that runs the demo)?

## 6. Next step
Brain review, then Yassine pushes main (T23 merge + this branch). Option: Kaggle fine-tune of bge-base is moot for speed; a fine-tuned bge-small would fit the limit.

**Is the switch safe for the demo?** Yes: bge-small with the tuned settings is fast on the PC (p95 60 ms, 662 MB), reproduces T23's val numbers and both live checks pass.
