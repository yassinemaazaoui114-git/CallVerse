# T24 — Switch M3 to bge-base-en-v1.5 (Intake + rule search), measured on the PC

## Why
T23 (cloud session, reviewed by the Brain) chose **`BAAI/bge-base-en-v1.5`** for both M3 jobs by the rule fixed in
advance: Intake macro-F1 (ShopNova / Atlas average) 0.571 → **0.691** on val, **0.680** on the locked test; ShopNova
money mix-ups 58 → 25; rule search top-2 **30/30** on val (29/30 locked) with the BGE query prompt. Its speed and memory
were measured on a cloud CPU with the GPU build of torch, so T24 switches the system **and re-measures on Yassine's PC**.
All decisions approved by Yassine on 2026-10-31 (all ⭐): switch both jobs; thresholds from the benchmark (ShopNova
0.70, Atlas 0.51, top-k 1); EmbeddingGemma skipped; merge T23 first.

## Hard limits
- Change only what the switch needs: `config.yaml` (model, top-k, the two thresholds) and the query prompt in
  `callverse/kb/search.py` (query side only; rule texts are embedded as today). No change to prompts, agents, tools,
  rules, Coordinator, apps.
- **Never run the locked test sets again** (`tests/data/atlas_intake_test.json`, `tests/data/rag_test.json`, ABCD
  `test`): T23 used them once. Re-measuring = **validation sets only**.
- Never read or stage `.env`; tests 0 API calls; stop if free RAM < 300 MB.

## What to do
0. **Git.** The PC is on the local `feature/t23-m3-benchmark` (behind GitHub) and the Brain's new `tasks/NEXT.md` is an
   uncommitted change: copy it aside, `git checkout -- tasks/NEXT.md`, then `git fetch`, `git checkout main`, `git pull`, and put
   the copy back after branching (below). main must be at **ea52210** or later. Then
   `git merge --no-ff origin/feature/t23-m3-benchmark` (approved by Yassine after the Brain's review; on a conflict:
   `git merge --abort`, stop and report). Run all tests (all pass). Do not push main. Branch `feature/t24-m3-switch`
   from this main. Commit this task file, `tasks/NEXT.md` (IN PROGRESS) and the Brain's Kaggle notebook
   `benchmarks/m3/kaggle/t23b_finetune_bge_base.ipynb` (untracked, unchanged) first.

1. **Switch** in `config.yaml`: `intake.embedding_model: "BAAI/bge-base-en-v1.5"` (pin the T23 revision `a5beb1e3…` if
   the loader supports it; say how), `top_k: 1`, ShopNova `reason_threshold: 0.70`, Atlas `reason_threshold: 0.51`.
   Comments say where the values come from (T23, val-tuned, locked-test confirmed). Rule search: prefix the **query**
   with the BGE instruction "Represent this sentence for searching relevant passages: " (one constant, both
   companies). The vector caches rebuild by themselves (fingerprint includes the model); make sure the new caches are
   built once.

2. **Re-measure on the PC (val only, CPU torch build as installed):** run the T23 benchmark code for the new system
   setting on the Intake val sets (ShopNova 328 + Atlas 40) and the rule-search val set. Report macro-F1, critical
   errors, needs-LLM rate, top-1 / top-2 / MRR — they should equal T23's val numbers (say any difference and why) — and
   **PC latency p50 / p95 per message and peak RAM**. Limits (T23 rule): Intake p95 ≤ 100 ms, peak RAM ≤ 1.5 GB;
   search p95 ≤ 200 ms. If the PC breaks a limit: **stop and report** (plan B = keep bge-small and only add its query
   prompt; not to be done without the Brain's OK).

3. **Leave-one-out on the examples** with the new model (`scripts/choose_threshold`, report only; the thresholds stay
   the benchmark's values). Say how many messages would go to the LLM fallback with 0.70 / 0.51.

4. **Tests:** all pass. Tests that pin bge-small / 0.66 / 0.68 / top-k 3 are updated to the new values (list each one).

5. **Short live check** (PC restarted, app settings): ShopNova practice **d05** and Atlas practice **a03**
   (`tests/dev/…`), each on a fresh database: same outcome as before (refund 59.90 / refund 1,500.00). Report the Intake
   seconds per message before / after, Groq tokens (about 15,000), 0 Gemini. Reseed both databases and delete
   `callverse.db` after.

6. **Docs:** `docs/benchmarks/M3.md` gets a "Switched in T24" section with the PC numbers; README (rule 8) updated;
   `DATA_LICENCES.md` unchanged unless needed.

## Checks (with numbers)
- Step 0 merge id + tests; step 2 table (val numbers vs T23, PC p50 / p95, RAM); step 3 numbers; tests x/y; live check
  table; `git status` clean of models / `.env` / raw data.
- One sentence: is the switch safe for the demo (speed on the PC included)?

## Time box and stop rule
**1.5 h.** Stop and report if: the T23 merge conflicts, a test fails, the PC breaks a speed / RAM limit, a locked test
set would be needed, free RAM < 300 MB, or Groq's daily limit answers. If Yassine has to leave: stop at a safe point,
write `tasks/T24_progress.md`, commit "T24 WIP: …" and push the branch.

## Git (approved by Yassine, 2026-10-31)
Commit and push `feature/t24-m3-switch`. **No merge into `main`** (the step-0 merge of T23 stays local; Yassine pushes
main after the Brain's review). Write `tasks/T24_report.md` (In plain words · Done · Evidence · Problems · Questions for
the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
