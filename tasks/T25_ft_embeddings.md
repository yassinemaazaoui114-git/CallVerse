# T25 — Score the fine-tuned embedding models (bge-small-ft, bge-base-ft) on the PC

## Why
T23b fine-tuned two M3 models on Colab with the Brain's notebook
(`benchmarks/m3/kaggle/t23b_finetune_bge_base.ipynb`: ABCD **train** + our reason examples, BatchAllTripletLoss,
2 epochs). Zips on the PC (git-ignored): `models/bge-small-callverse-ft.zip` (109 MB) and
`models/bge-base-callverse-ft.zip` (374 MB). T25 scores them against today's system (bge-small, top-k 5, ShopNova 0.69,
Atlas 0.54, BGE query prompt in rule search) with the T23 code and the fixed rule below, and switches only if
bge-small-ft wins. All details approved by Yassine on 2026-10-31 (all ⭐).

## Hard limits
- **Validation sets only** for scoring and tuning (ShopNova = ABCD dev 328, Atlas val 40, rule-search val 30 + 5).
  The locked tests (`tests/data/atlas_intake_test.json`, `tests/data/rag_test.json`, ABCD `test`) are opened **once**,
  only for bge-small-ft and only if it wins on val (step 4). Never tune on them.
- The fine-tuned models saw ABCD train only. Do not use ABCD dev / test or any val / test file for training.
- Change only what the switch needs (step 5): `config.yaml`, model loading, docs, tests. No change to prompts, agents,
  tools, rules, Coordinator, apps.
- `models/` stays git-ignored: never commit model files. Never read or stage `.env`. Tests: 0 API calls.
  Stop if free RAM < 300 MB.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (main must be at **de24fa3** or later). Branch
   `feature/t25-ft-embeddings`. Commit this task file and `tasks/NEXT.md` (IN PROGRESS) first.

1. **Unzip** both zips into `models/bge-small-callverse-ft/` and `models/bge-base-callverse-ft/`. Check each loads with
   `SentenceTransformer(path, device="cpu")`, print its `callverse_training.json` (base, train_rows, labels, seed) and the
   embedding size. Say if a zip is broken (stop for that model).

2. **Score on val (T23 code, CPU torch as installed on the PC).** For each of: today's bge-small (reference),
   bge-small-ft, bge-base-ft:
   - **Intake:** re-tune top-k and both thresholds on val with **the same grid as T23** (top-k and threshold lists from
     `benchmarks/m3/common.py` / `benchmark.py`). Report macro-F1 per company and the average, ShopNova money mix-ups
     (critical errors), needs-LLM rate, the chosen top-k / thresholds.
   - **Rule search:** dense with the BGE query prompt (as today) **and** without it (the fine-tune trained without the
     prompt): top-1, top-2, MRR, no-rule handling as in T23. Keep the better of the two per model and say which.
   - **PC speed + memory, measured like `benchmarks/m3/pc_check.py`:** Intake p50 / p95 per message, search p50 / p95,
     peak RAM. Load the local folder path the same way the system would.
   - One table with all three rows. bge-base-ft is **for the record only** (bge-base was already too slow on the PC
     in T24; say its numbers anyway).

3. **Fixed rule (decided before the run, do not change it):** **bge-small-ft wins** if ALL of:
   - Intake average macro-F1 on val ≥ **0.647 + 0.02 = 0.667**;
   - Atlas macro-F1 not lower than today's (bge-small, same re-tuning);
   - rule search top-2 stays **30/30** on val;
   - Intake p95 ≤ **100 ms** and peak RAM ≤ **1.5 GB** on the PC (search p95 ≤ 200 ms).
   Rule search may keep today's model even if Intake switches: decide per job (Intake: the rule above; search: switch
   only if bge-small-ft is ≥ today's top-2 AND MRR). If bge-small-ft loses: **stop after step 3**, no locked test, no
   switch, report.

4. **Locked test, once (only if bge-small-ft wins):** run the T23 locked-test code for bge-small-ft with the val-chosen
   settings, and the same for today's bge-small for comparison (T23 already ran bge-small on the locked tests: reuse
   those numbers if the settings are identical, say so). Report; the choice is **not** changed by the locked result —
   if bge-small-ft is clearly worse on the locked test (> 0.03 lower average macro-F1), stop before step 5 and report.

5. **Switch (only if it won steps 3–4):**
   - `config.yaml`: `intake.embedding_model: "models/bge-small-callverse-ft"` (path relative to the repo root,
     resolved in code), `embedding_revision` not used for a local path, new top-k / thresholds from val; comments say
     where the values come from (T25, val-tuned, locked-test checked).
   - **Fallback:** if the folder is missing (a fresh clone), load `BAAI/bge-small-en-v1.5` with the pinned revision
     and today's settings, and log one warning. Write this so the fallback also uses the right top-k / thresholds
     (e.g. a `fallback` block in config). Test both paths.
   - Rule search: as decided per job in step 3.
   - Vector caches rebuild (fingerprint includes the model); build them once.
   - README (how to get the model: unzip from Colab output into `models/`, otherwise the fallback is used).

6. **Tests:** all pass. Tests pinning the old model / top-k / thresholds updated (list each one). New tests: local
   path loads, fallback path loads with its own settings (no download in tests: mock or skip if the model is absent,
   say which).

7. **Live check (only if switched; Ollama running, PC restarted):** ShopNova **d05** and Atlas **a03** on fresh
   databases: same outcomes (refund 59.90 / 1,500.00). Report Intake seconds per message before / after, Groq tokens,
   0 Gemini, and whether replies came from the SLM (not the template). Reseed both databases and delete
   `callverse.db` after.

8. **Docs:** `docs/benchmarks/M3.md` gets a "T25 fine-tuned models" section (table, rule, decision);
   `DATA_LICENCES.md`: ABCD (MIT) used for fine-tuning; README (CLAUDE.md rule 8).

## Checks (with numbers)
- Step 1 load check per model; step 2 table (3 rows: macro-F1 per company + average, critical, needs-LLM, settings,
  search top-1 / top-2 / MRR with and without prompt, PC p50 / p95, RAM); step 3 verdict per condition (pass / fail);
  step 4 numbers if run; tests x/y; live table if run; `git status` clean of `models/`, `.env`, raw data.
- One sentence: does the system switch, and is it safe for the demo?

## Time box and stop rule
**1.5 h.** Stop and report if: a zip does not load, a test fails, bge-small-ft loses on val (normal end), the locked
test is clearly worse, the PC breaks a speed / RAM limit, a locked test would be needed twice, free RAM < 300 MB, or
Groq's daily limit answers. **If Yassine has to leave:** stop at a safe point, write `tasks/T25_progress.md`, commit
"T25 WIP: …" and push the branch.

## Git (approved by Yassine, 2026-10-31)
Commit and push `feature/t25-ft-embeddings`. **No merge into `main`** (Yassine merges after the Brain's review). Write
`tasks/T25_report.md` (In plain words · Done · Evidence · Problems · Questions for the Brain · Next step) and set
`tasks/NEXT.md` to WAITING FOR REVIEW. Last step: update the README with what changed (CLAUDE.md rule 8).
