# T23 report — Benchmark M3 (embeddings): Intake reasons + rule search

## 1. In plain words
We tested whether today's embedding model (bge-small) is the right one for its two jobs: recognising why a client
writes (Intake) and finding the right company rule for an agent (rule search). Four models and three simple baselines
were compared on validation sets, with a choosing rule written before the results; then the two winners ran once on
locked test sets. The winner for **both** jobs is **bge-base-en-v1.5** (same family, 3× bigger): Intake macro-F1 0.69 vs
0.57 for today's setting, and 30/30 right rules in the agent's top 2 on validation, 29/30 on the locked test. Keyword
search (BM25), hybrid search and a reranker did **not** help on such small rule sets. Nothing in the running system was
changed: switching is a separate step after Yassine's OK.

## 2. Done
- **Step 0 skipped** as instructed (branch and its first commit already existed). `tasks/NEXT.md` → IN PROGRESS, then
  WAITING FOR REVIEW.
- **Step 1** `benchmarks/m3/build_data.py` → `benchmarks/m3/data/shopnova_intake_val.json` (ABCD `dev`, mapping applied
  exactly); `--locked-test` builds the test file into git-ignored `out/t23/` only. ABCD credited in `DATA_LICENCES.md`.
- **Step 2** candidates with pinned revisions in `benchmarks/m3/common.py`; `benchmarks/m3/embed_run.py` runs one model
  per process (vectors, latency, peak RAM, params, disk). EmbeddingGemma **skipped** (gated: 401, needs a Hugging Face
  login). Baselines: TF-IDF nearest examples, BM25 (written out, no new library), majority reason.
- **Steps 3–5** `benchmarks/m3/benchmark.py`: the Intake matcher copied from `reasons.py` on saved vectors, grid
  top-k × threshold on val, rule-search methods (dense ± documented prompt, BM25, hybrid RRF k=60, hybrid + bge-reranker-base
  on the top 10), the fixed choosing rule → `results/intake_val.json`, `rag_val.json`, `choice.json`,
  `results/models/*.json`.
- **Step 6** `docs/benchmarks/M3.md`: one combined document with every candidate and baseline, the rule, winners, why the
  others lost, pinned versions, data sizes, a presentation paragraph.
- **Step 7** `benchmarks/m3/locked_test.py`: winners only, once (it refuses a second run) → `results/locked_test.json`.
  Val results and the choice were **committed before** the locked test ran (commit 27a9c41).
- **Step 8** `tests/test_m3_benchmark.py` (5 tests, offline): the matcher gives the same reasons as `reasons.match_reasons`
  on the system's settings (fake embedder, 4 thresholds × 5 messages); toy metrics; RRF; BM25; data builder on a fake ABCD.
- **Step 9** README: Benchmarks section, folder, docs link, ABCD note, T23 in the task history.

## 3. Evidence
- **Machine (not Yassine's PC):** cloud machine, 4 CPUs, 15 GB RAM, Python 3.13.17, torch 2.15.0 **GPU build (cu132)
  running on CPU** (the CPU index was blocked by the network policy when installing), 4 threads. Python + torch take
  ~823 MB before any model; latencies and RAM will differ on the PC.
- **Val sizes:** ShopNova 328 (order_status 37, late_delivery 26, refund_request 67, return_item 38, damaged_item 10,
  other 150 of 826, seed 2026; 0 chats dropped); Atlas 40 (5 × 8); rule search 30 (12 S + 18 A) + 5 no-rule.
  Locked: ShopNova test 341, Atlas 40, rule search 30 + 5.
- **Intake (val, macro-F1 S / A / avg):** bge-base k1 0.70/0.51 **0.431 / 0.950 / 0.691** (p95 54.8 ms, peak 1393 MB);
  Qwen3-0.6B 0.657 (p95 146.8 ms, 2352 MB → not eligible); bge-small tuned (k5) 0.647; MiniLM 0.643;
  **today (bge-small k3 0.66/0.68) 0.571**; TF-IDF 0.552; majority 0.066. Critical errors on ShopNova val: bge-base 25,
  today 58.
- **Intake locked test (bge-base):** macro-F1 0.385 / 0.975 / **0.680** (val 0.691); accuracy 0.331 / 0.975; critical
  38 / 0; needs-LLM 33.4% / 0%.
- **Rule search (val, top-2 / MRR):** dense bge-base + prompt **30/30 / 0.967** (p95 44.7 ms), tied with Qwen3 + prompt
  (p95 161.6 ms; tie → simpler, smaller); bge-small + prompt 30/30 / 0.950; MiniLM 30/30 / 0.950; **today (bge-small, no
  prompt) 29/30 / 0.944**; hybrid 25–27/30; hybrid + reranker 29/30 (p95 614–769 ms → not eligible); BM25 20/30.
- **Rule search locked test (dense bge-base + prompt):** top-1 29/30, **top-2 29/30**, MRR 0.978; no-rule separable 4/5.
- **Tests:** 1048 / 1048 passed (1043 before + 5 new), `python -m pytest -q --ignore=tests/data`, 107 s.
- **Time and downloads:** started 22:25, results and report by ~22:40 UTC (container clock); each model run 7–72 s.
  Downloads ~3.0 GB of model files (bge-small 135 MB, MiniLM 92, bge-base 439, Qwen3 1208, reranker 1134) + ABCD 37 MB.
- **0 API calls.** `git status`: no raw ABCD (`data/raw/` ignored), no `.env`, no model files, no ShopNova test file
  (`out/` ignored). `config.yaml`, `callverse/`, `apps/`, `scripts/` unchanged (`git diff` empty).

## 4. Problems
- **Push failed:** `git push` → 403 "Claude doesn't have GitHub access to yassinemaazaoui114-git/CallVerse". The commits
  are on the local branch in the cloud session only; see "Next step".
- **ShopNova scores are low for every model** (macro-F1 ~0.4): ABCD labels are chat-level, many first messages are vague
  ("I have a question about my account"), and ABCD is a clothing shop, not electronics. The ranking is still fair (same
  noise for all), but the absolute numbers are not what the live system would get on ShopNova's own messages.
- **"Under the threshold = a miss"** (0 API calls) pushes the tuned thresholds down (Atlas 0.51 → 0% needs-LLM). In the
  live system those messages go to the LLM fallback, which may be right; today's 0.68 is penalised by this rule.
- **Small sets:** Atlas 40 and rule search 30 questions, AI-generated; one error = 2.5–3.3 points. Several rule-search
  methods tie at 30/30 on val.
- **Speeds/RAM from a cloud CPU with the GPU torch build**, not from the demo PC. bge-base's peak 1393 MB is close to the
  1.5 GB limit here; with the CPU torch build it should be lower.
- Hybrid + reranker rows are identical for every dense model on ShopNova (8 rules ≤ 10 → all reranked).
- EmbeddingGemma not measured (gated). The reranker was slow (~0.5 s for 10 pairs) on this CPU.

## 5. Questions for the Brain
1. Switch M3 to **bge-base-en-v1.5** (top-k 1, thresholds ShopNova 0.70 / Atlas 0.51) and add the BGE query
   instruction to the rule-search query? That is a separate task (config + one line in `kb/search.py`), with a check of
   the live demo and of the leave-one-out numbers on the examples.
2. Or a smaller step for rule search only: keep bge-small and just add its documented query prompt (val 30/30, MRR 0.950)?
3. Should the thresholds keep the current "leave-one-out on the examples" method (which assumes the LLM fallback) rather
   than the benchmark's tuned values (which assume no fallback)?
4. Is EmbeddingGemma worth one more run with Yassine's Hugging Face login (licence accepted)?

## 6. Next step
- Fix GitHub access (reconnect GitHub at https://claude.ai/connect-github, or install the Claude GitHub App on the
  repository), then push `feature/t23-m3-benchmark` (no merge).
- Brain reviews `docs/benchmarks/M3.md`; if approved, a small task "T24: switch M3 to bge-base" on Yassine's PC
  (re-measure latency there with the CPU torch build).
