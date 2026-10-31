# T23 — Benchmark M3 (embeddings): Intake reasons + rule search (RAG methods)

## Why
The teacher asks "why this model and not another?" for every part. M3 (bge-small-en-v1.5) was chosen on 2026-10-14
without a benchmark. T23 measures it against alternatives for **both of its jobs** — Intake's reason matching (ShopNova
and Atlas) and the agents' rule search — with the HireSignal method: simple baselines, candidates, choose on a
**validation** set with a rule fixed in advance, then run the winner **once** on a **locked test** set, one combined
table. All details approved by Yassine on 2026-10-30 (15 items, all ⭐).

## Hard limits
- **No change to the running system:** `config.yaml`, Intake, rule search, agents, apps stay exactly as they are.
  Switching to a winner is a separate step after Yassine's OK. Benchmark code lives in `benchmarks/m3/`.
- **Locked test sets:** `tests/data/atlas_intake_test.json`, `tests/data/rag_test.json` and ABCD's `test` split are
  **never read, printed or used** until step 7, and then **only for the chosen model / method**, once. Nothing is tuned
  on them. Thresholds, top-k and method settings are tuned on validation only.
- **0 API calls** (no LLM fallback: a message under the threshold counts as "needs the LLM"). CPU only (Intake runs on
  CPU). Model versions pinned (Hugging Face revision hash) and listed.
- Never read or stage `.env`. Raw ABCD stays in git-ignored `data/raw/abcd/`. All existing tests pass.
- Stop if free RAM < 300 MB (the 0.6B model is the largest).

## Inputs
- `data/raw/abcd/abcd_v1.1.json` (copied by Yassine; ABCD, ASAPP, NAACL 2021, MIT licence).
- Brain's files (already placed, untracked — commit unchanged in step 0):
  `benchmarks/m3/data/abcd_mapping.json` (subflow → reason, rules for the first message, cap, seed),
  `benchmarks/m3/data/atlas_intake_val.json` (40), `benchmarks/m3/data/rag_val.json` (30 + 5 no-rule),
  `tests/data/atlas_intake_test.json` (40, LOCKED), `tests/data/rag_test.json` (30 + 5 no-rule, LOCKED).
- Index / examples (as the system uses them): `callverse/intake/data/reason_examples.json` (ShopNova, 60),
  `callverse/intake/data/reason_examples_atlas.json` (Atlas, 80), `callverse/kb/policies_shopnova.json` (8),
  `callverse/kb/policies_atlas.json` (14).

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (must be **ea52210** or later). Branch
   `feature/t23-m3-benchmark`. Commit this task file, `tasks/NEXT.md` (IN PROGRESS) and the Brain's 5 data files
   unchanged, first. Check `data/raw/abcd/abcd_v1.1.json` exists (else stop and ask Yassine).

1. **Data builder** `benchmarks/m3/build_data.py` → `benchmarks/m3/data/shopnova_intake_val.json` (from ABCD `dev`),
   following `abcd_mapping.json` exactly (first customer turn with ≥ 4 words; `other` sampled to 150, seed 2026).
   It builds the ShopNova **test** file into git-ignored `out/` only when called with `--locked-test` (step 7). Report
   per-reason counts of val. Credit ABCD in `DATA_LICENCES.md` (what was used, MIT).

2. **Candidates (item 2)** — sentence-embedding models, same code path as the system (`normalize_embeddings=True`,
   cosine): `BAAI/bge-small-en-v1.5` (today's), `sentence-transformers/all-MiniLM-L6-v2`, `BAAI/bge-base-en-v1.5`,
   `google/embeddinggemma-300m`, `Qwen/Qwen3-Embedding-0.6B`. Use each model's documented query / document prompts if
   it has them (say which). If one cannot load on this PC (licence gate, memory): skip it, say why, continue.
   **Baselines (item 3):** TF-IDF nearest examples (Intake), BM25 (rule search), majority reason.

3. **Intake benchmark (val only)** for each model × company: reproduce the system's matcher (`reasons.py`: sentence
   split, mean of top-k similarities to each reason's examples, best reason per sentence, threshold; main reason by the
   company's precedence order). Tune per model on val: **threshold** (grid 0.40–0.90, step 0.01) and **top-k** (1, 3, 5).
   Measures (item 8): accuracy, **macro-F1**, per-reason precision / recall, **critical errors** (a money reason —
   ShopNova refund_request / return_item / damaged_item; Atlas refund_request / compensation_request / cancellation —
   predicted as a non-money reason, or the other way round), **needs-LLM rate** (under threshold), latency per message
   (p50 / p95, CPU, after warm-up), peak RAM, parameters, disk size, licence. Today's setting (bge-small, top-k 3,
   0.66 / 0.68) is also reported as it is.

4. **Rule-search benchmark (val only)** per company's own rules: **dense** (each model; the system's "title. text"
   embedding), **BM25**, **hybrid** (dense + BM25 with reciprocal rank fusion, k = 60), **hybrid + reranker**
   (`BAAI/bge-reranker-base` on the hybrid top 10). Measures: **top-1, top-2** (agents get 2), **MRR**, latency p50 /
   p95; for the 5 no-rule questions: the top score and the gap to the lowest correct-hit score (report only).

5. **Choosing rule (item 9, fixed now):**
   - **Intake:** highest **macro-F1 on val (ShopNova and Atlas averaged)** among models with **p95 ≤ 100 ms** per
     message and **peak RAM ≤ 1.5 GB**; a tie (≤ 0.01) → the smaller model.
   - **Rule search:** highest **top-2 on val (both companies together)**, then MRR, among methods with **p95 ≤ 200 ms**.
   - If the winner is today's setting, say so plainly (that is a result too).

6. **One combined table** `docs/benchmarks/M3.md` (item 12): every candidate and baseline with every measure, the
   rule, the winner, why the others lost, pinned versions, data sources and sizes, and a short "what this means for the
   presentation" paragraph. Raw results in `benchmarks/m3/results/*.json` (committed; small).

7. **Locked test, once (item 9):** only the Intake winner (with its tuned threshold / top-k) on ShopNova's ABCD
   `test` split + `tests/data/atlas_intake_test.json`, and only the rule-search winner on `tests/data/rag_test.json`.
   Report the numbers next to val in the table. **No change after seeing them.**

8. **Tests:** small offline tests for the benchmark code (matcher reproduces `reasons.py` on the system's settings,
   metrics on a toy example, data builder follows the mapping on a fake ABCD file). All tests pass.

9. **README (rule 8):** benchmarks section (how to run, where the table is), task history.

## Checks (with numbers)
- Val sizes per reason (ShopNova from ABCD, Atlas 40) and rule-search counts.
- The full table; the winners; locked-test numbers; the time and downloads used.
- `git status`: no raw ABCD, no `.env`, no models in git.
- One sentence: should we switch M3 (and the search method), and what would change in the system?

## Time box and stop rule
**2.5 h.** Stop and report if: main is not at ea52210 or later, the ABCD file is missing, a locked set would be needed
before step 7, any change to the running system would be needed, free RAM < 300 MB, or a secret would end up in git.
If Yassine has to leave: stop at a safe point, write `tasks/T23_progress.md`, commit "T23 WIP: …" and push the branch.

## Git (approved by Yassine, 2026-10-30)
Commit and push `feature/t23-m3-benchmark`. **No merge into `main`.** Write `tasks/T23_report.md` (In plain words ·
Done · Evidence · Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
