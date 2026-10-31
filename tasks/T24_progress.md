# T24 — progress (STOPPED at step 2: PC breaks the Intake speed limit)

## Done
- Step 0: T23 merged locally into main (merge 4ea501b, not pushed); tests 1048/1048. Branch `feature/t24-m3-switch`.
- Step 1 (applied, uncommitted before this WIP): config.yaml -> bge-base, revision pinned (`embedding_revision`,
  passed to SentenceTransformer in `reasons.get_model`), top_k 1, ShopNova 0.70, Atlas 0.51;
  `kb/search.py` adds QUERY_PROMPT + `embed_query` (query side only). Caches rebuilt once.
- Step 2: `benchmarks/m3/pc_check.py` (system code, val sets only, Windows RAM) -> `benchmarks/m3/results/pc_check.json`.

## Step 2 numbers (PC, torch 2.14.1+cpu, 12 threads, val only)
| | PC | T23 val | limit |
|---|---|---|---|
| Intake avg macro-F1 | 0.6905 | 0.691 | - |
| ShopNova: acc / macro-F1 / critical / needs-LLM | 0.369 / 0.431 / 25 / 36.0% | 25 critical | - |
| Atlas: acc / macro-F1 / critical / needs-LLM | 0.95 / 0.950 / 1 / 0% | - | - |
| Search top-1 / top-2 / MRR (30 q) | 28 / **30** / 0.967 | 30/30 | - |
| **Intake latency p50 / p95** | 76 / **134 ms** (rerun: 70 / **124 ms**) | 35 / 55 (cloud) | p95 <= 100 ms **BROKEN** |
| Search latency p50 / p95 | 84 / 92 ms | 35 / 45 | p95 <= 200 ms ok |
| Peak RAM | 921 MB | 1393 | <= 1.5 GB ok |

## Left
Steps 3-6 (leave-one-out, tests update, live check d05 / a03, docs M3.md, README, report). Waiting for the Brain / Yassine:
accept p95 ~125-135 ms (matcher only, the end-to-end Intake also runs the emotion + sentiment models) or plan B.
