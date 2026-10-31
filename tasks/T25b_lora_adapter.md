# T25b — Score the LoRA adapter on bge-small (Intake only; rule search stays on the plain model)

## Why
T25 showed that full fine-tuning helps ShopNova Intake but makes the model forget general meaning (rule search 30 → 22)
and slightly hurts Atlas. T25b tests the fix approved by Yassine on 2026-10-31 (all ⭐): a **LoRA adapter** on the frozen
bge-small (Colab notebook `benchmarks/m3/kaggle/t25b_lora_bge_small.ipynb`), trained on cleaner, balanced data
(ABCD train with 'other' capped at 500 + Bitext Retail + Bitext Travel, 300 per reason + 120 Brain-written Atlas
messages; **our 140 Intake index examples NOT used**). The adapter is **on for Intake and off for rule search**, so
search keeps today's model. Adapter zip on the PC (git-ignored): `models/bge-small-callverse-lora.zip` (1.9 MB; LoRA r 16,
alpha 32, dropout 0.1, query/key/value; 5,429 rows; checked by the Brain: weights trained, training info correct).

## Hard limits
- **Validation sets only** for scoring and tuning (ShopNova = ABCD dev 328, Atlas val 40, rule-search val 30 + 5). The
  locked tests (`tests/data/atlas_intake_test.json`, `tests/data/rag_test.json`, ABCD `test`) are opened **once**, only
  if the adapter wins on val (step 4). Never tune on them.
- Change only what the switch needs (step 5). No change to prompts, agents, tools, rules, Coordinator, apps.
- `models/` stays git-ignored. Never read or stage `.env`. Tests: 0 API calls, no model downloads in tests. Stop if free
  RAM < 300 MB.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (main must be at **cac2490** or later). Branch
   `feature/t25b-lora`. Commit first: this task file, `tasks/NEXT.md` (IN PROGRESS) and the three Brain files already on
   the PC, untracked and unchanged: `benchmarks/m3/kaggle/t25b_lora_bge_small.ipynb`,
   `benchmarks/m3/data/bitext_mapping.json`, `benchmarks/m3/data/atlas_extra_train.json`.

1. **Unzip** into `models/bge-small-callverse-lora/`. **Loading rule (approved):** load the base
   `BAAI/bge-small-en-v1.5` **with the pinned revision** from config (`intake.embedding_revision`), then add the adapter
   from the folder (the adapter files do not record the revision, so code must set it; do not let it download another
   revision). Check: adapter ON gives different vectors from the base; adapter OFF / the plain base gives exactly
   today's vectors (allclose). Print `callverse_training.json`.

2. **Score on val** with the T25 code (`benchmarks/m3/t25_score.py`: add a `bge-small-lora` key; same grid, tie rule,
   measures, PC speed and peak RAM, one model per process):
   - **Intake** with the adapter ON: re-tune top-k and both thresholds on the T23 grid; macro-F1 per company + average,
     ShopNova money mix-ups, needs-LLM rate, chosen settings.
   - **Rule search** with the adapter OFF (the system setting) — must equal today's (30/30). Also report search with the
     adapter ON, for the record only.
   - **PC speed + memory in the planned setup:** two model objects in one process (base for search, base + adapter for
     Intake): Intake p50 / p95, search p50 / p95, peak RAM.
   - Table: today's bge-small (re-use T25's row if settings are identical, say so) vs bge-small-lora.

3. **Fixed rule (same as T25, do not change it):** the adapter **wins** if ALL of:
   - Intake average macro-F1 on val ≥ **0.667**;
   - Atlas macro-F1 not lower than today's (**0.884**, same re-tuning);
   - rule search top-2 **30/30** on val (adapter off);
   - Intake p95 ≤ **100 ms**, search p95 ≤ 200 ms, peak RAM ≤ **1.5 GB** (two model objects).
   If it loses: **stop after step 3** (no locked test, no switch), report.

4. **Locked test, once (only if it wins):** T23 locked-test code for the adapter with the val-chosen settings; today's
   bge-small locked numbers re-used from T23 if the settings are identical (say so). If the adapter's locked average
   macro-F1 is more than **0.03 below** its val average: stop before step 5 and report.

5. **Switch (only if it won steps 3–4):**
   - **Two model objects (approved):** rule search uses the plain base (pinned revision, as today); Intake uses base +
     adapter. No adapter on/off switching at run time (the apps run several chats at once).
   - `config.yaml`: new key for the adapter path (e.g. `intake.embedding_adapter: "models/bge-small-callverse-lora"`, path
     from the repo root), new top-k / thresholds from val, comments (T25b, val-tuned, locked-test checked).
   - **Fallback:** if the adapter folder is missing (fresh clone), Intake uses the plain base with today's settings
     (top-k 5, 0.69 / 0.54; e.g. a `fallback` block in config) and logs one warning. Both paths tested.
   - Vector caches: the Intake example cache fingerprint must include the adapter (rebuild once); the search cache stays.
   - README: how to get the adapter (Colab notebook output → `models/`), and that the fallback is used otherwise.

6. **Tests:** all pass. Tests pinning the old settings updated (list each one). New tests: adapter path loads with the
   pinned base revision, fallback path uses its own settings, search model is the plain base (skip/mock when the adapter
   is absent; say which).

7. **Live check (only if switched; Ollama running, PC restarted):** ShopNova **d05** and Atlas **a03** on fresh databases:
   same outcomes (refund 59.90 / 1,500.00). Report Intake seconds per message before / after, Groq tokens, 0 Gemini, and
   whether replies came from the SLM (not the template). Reseed both databases and delete `callverse.db` after.

8. **Docs:** `docs/benchmarks/M3.md` section "T25b LoRA adapter" (table, rule, decision; adapter vs full fine-tune);
   `DATA_LICENCES.md`: **Bitext Retail + Bitext Travel (CDLA-Sharing 1.0, synthetic), used to train the adapter**, plus ABCD
   train (MIT) for fine-tuning; README (CLAUDE.md rule 8).

## Checks (with numbers)
- Step 1 load checks (ON ≠ base, OFF = base); step 2 table; step 3 verdict per condition (pass / fail); step 4 numbers if
  run; tests x/y; live table if run; `git status` clean of `models/`, `.env`, raw data.
- One sentence: does the system switch, and is it safe for the demo?

## Time box and stop rule
**1 h.** Stop and report if: the adapter does not load with the pinned base, a test fails, the adapter loses on val
(normal end), the locked test is clearly worse, the PC breaks a speed / RAM limit, a locked test would be needed twice,
free RAM < 300 MB, or Groq's daily limit answers. **If Yassine has to leave:** stop at a safe point, write
`tasks/T25b_progress.md`, commit "T25b WIP: …" and push the branch.

## Git (approved by Yassine, 2026-10-31)
Commit and push `feature/t25b-lora`. **No merge into `main`** (Yassine merges after the Brain's review). Write
`tasks/T25b_report.md` (In plain words · Done · Evidence · Problems · Questions for the Brain · Next step) and set
`tasks/NEXT.md` to WAITING FOR REVIEW. Last step: update the README with what changed (CLAUDE.md rule 8).
