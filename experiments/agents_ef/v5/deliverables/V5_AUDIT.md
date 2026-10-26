# V5 audit (start of the "V4 master prompt" round)

Audit date: 2026-10-26, 15:31–15:40 UTC. Worker D.

**Naming.** This round is stored in `experiments/agents_ef/v5/`, because `v4/` already holds the previous night's post-V3 work. Nothing in `v3/` or `v4/` is modified.

## 1. Code and repository state

| Item | Verified state |
|---|---|
| Local branch | `research/agents-e-f-tiny-models` at `75524e9` (contains V3 `3237eed` and all v4 commits). Working tree clean |
| **GitHub branch** | **`50acb04`: pre-V3.** The 28 commits holding all V3 and v4 code, results and reports exist **only in this cloud container**. Nothing was pushed (pushing needs the user's approval) |
| Prepared for preservation (local only, not uploaded) | `scratchpad/backup/callverse_research_v3_v4.bundle` (27.5 MB, `git bundle verify` OK, SHA256 `ea0fccf1…`). It restores all 28 commits with `git fetch <bundle>` |
| Latest implementation | Agent E: V3 simulator `v3/e/env_v3.py`, v4 policies/adapter `v4/e/`. Agent F: v4 `v4/f/` (AgentF, M7 v4), V3 benchmark `v3/f/`. No V2 code is used as a substitute |
| Simulator randomness | V3 tape-based common random numbers: `test_exogenous_world_is_identical_for_every_policy` passes |
| Smoke tests | 149/149 research tests (`v3/e`, `v3/m7`, `v4/e`, `v4/f`, `v4/d`) in 65 s. The prototype's `tests/` passed 300/300 at the end of v4 |

## 2. Artifacts

| Artifact | Status |
|---|---|
| 69 V3 Agent E `best.pt` | **Exist and verified** (69/69 SHA256 = manifest). Durable copy in the private vault (full restore tested) |
| 19 v4 Agent E `best.pt` (incl. recommended `…lag0d2t0.9_s1`, SHA256 `ed5810c1…`) | **Exist**; vault copy, server hash verified |
| Agent F e5-L6/256 selected (`model.pt` SHA256 `466c0cc8…`) | **Exists**; vault copy (8 parts, hashes verified) |
| Agent F TF-IDF+Ridge tail-256 (`model.joblib` SHA256 `1c201853…`) | **Exists**; vault copy |
| Other F checkpoints (TinyBERT, e5 L6/128, e5 L12, mMiniLMv2-L6, tfidf_roles) | **Exist locally only**; regenerable; not backed up |
| USS splits (12 MB) | **Exist locally**; public; regenerable (SHA256 in `v3/f/results/uss_stats.json`) |
| M7 corpora (240 scripted traces) | **Exist**; vault copy |
| Genuine CallVerse satisfaction ratings | **Missing**: none exist (v4 search: 0 real `pipeline_done` traces, no ratings table) |
| Code / results / reports | **Exist locally only** (see §1) |

Vault: https://claude.ai/artifact/CJ3RnnzJpDK317jC9YvdbY (private; created under the previous round's backup instruction). This round's prompt requires permission for external uploads, so nothing new has been uploaded.

## 3. Evaluation hygiene

| Split | State | Allowed use in V5 |
|---|---|---|
| V3 VAL (48 days, seeds 500,000+) | used for V3 checkpoint selection | development only. V3's "−184.0 / −178.3" are best-checkpoint VAL numbers, selection-biased, and not comparable with test numbers |
| V3 TEST (650 days, seeds 900,000+) | inspected | **none** |
| v4 DEV (104 days, seeds 700,000+, SHA256 `d54493d2…`) | development | development and selection |
| v4 TEST4 (650 days, seeds 1,300,000+) | inspected | **none** |
| **V5 final test** | to be created by Worker E (new seeds) and pre-registered before evaluation | confirmatory only |
| USS VAL / TEST | TEST scored many times in V3 and v4 | selection on VAL only. A new TEST comparison is scored once after a written freeze. The repeated past use of TEST is stated as a limitation |

**Leakage checks inherited from earlier rounds**
- Splits are grouped by dialogue.
- V3 and v4 manifests are disjoint by seed range (tested in `v3/e/tests`).
- Held-out scenario families appear only in test splits.

## 4. Resources (measured)

- 4 CPU cores, 15 GB RAM, **no GPU** (`nvidia-smi` absent).
- 5.2 GB free disk.
- The container restarts, but the scratchpad has persisted so far. Long jobs must be resumable.
- The user's PC is not accessible and is not used.

## 5. Workstreams

| Worker | Scope | Directory |
|---|---|---|
| E | Dueling DQN improvements: shield analysis, PER, n-step, domain randomisation, QR-DQN if justified; staged ablation; pre-registered new final test | `v5/e/` |
| F | Data audit, collapse diagnosis, Ridge rebuild, e5-small fine-tuning, optional encoder / ensemble, labelling package, M7 review | `v5/f/` |
| D | Audit, registry, integration and regression tests, packaging, local handoff, final reports | `v5/d/`, `v5/deliverables/` |

Experiment registry: `v5/registry/experiments.jsonl` (append-only; `registry.py`).
