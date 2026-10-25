# Checkpoint backup status

Updated 2026-10-25 by Worker D. Checkpoints are git-ignored on purpose, and nothing was pushed, so **Git alone preserves no weights**. Durable copies live in a private claude.ai artifact, readable only by the account owner:

**CallVerse Model Vault**: https://claude.ai/artifact/CJ3RnnzJpDK317jC9YvdbY

**How the files are stored**
- The asset store accepts text, not binary, so each archive is stored as base64 text, split into parts under 15 MB.
- Restore steps are on the vault page:
  1. `cat parts | base64 -d > x.tar.gz`
  2. `sha256sum` (it must match the table below)
  3. `tar -xzf`

## Preserved (durable, verified)

| Archive | Contents | Archive SHA256 | Verification |
|---|---|---|---|
| `agentE_v3_best_checkpoints` (2.6 MB) | All 69 Agent E v3 runs: `best.pt` + `run.json`; `CHECKPOINT_MANIFEST_E.json`; `val_choice.json`; VAL/TEST manifests | `07d4718ff598a0a5183e03858bca172f851e21ab5c308d80436510a7dcca4acb` | **Full round trip**: downloaded from the vault, decoded, extracted; 69/69 `best.pt` match the manifest hashes |
| `agentF_v3_e5L6_256_selected` (70 MB, 8 parts) | Selected Agent F model: `model.pt` fp32 (SHA256 `466c0cc8…`) + `meta.json`; base tokenizer and config at revision `614241f6`; `SHA256SUMS`; F checkpoint manifest | `ed664a746a6be52f3ce37243816bcf7d98571c418f9480077c1b2560fc613483` | Server SHA256 of all 8 parts = local parts; local concatenation decodes to the archive hash |
| `m7_corpus_v3_traces` (0.28 MB) | M7 dev and held-out corpora: 240 traces plus `ground_truth.json`. Not bit-reproducible (ticket ids are random UUIDs) | `52e0b9d2958b6657421f4f9299b8bc6d2886fee109824e41defb0466d0176db4` | Server SHA256 = local |

## Not backed up (at risk; regenerable)

| Item | Why not | How to regenerate |
|---|---|---|
| Agent E `last.pt` (69) | Not needed: the evaluated policies are `best.pt` | Re-train (`v3/e/run_queue_e.sh`) |
| Agent F int8 copy `model_int8.pt` (SHA256 `78908a2b…`) | Deterministic from fp32 | `v3/f/quantize_f.py` |
| Other F checkpoints (TinyBERT EN, e5 L6/128, e5 L12/128, mMiniLMv2-L6) | Not selected; 341 MB | `v3/f/run_queue*.sh`, about 15–50 min CPU per seed |
| USS splits (12 MB) | Public dataset | `RUN_AND_RESUME_F.md`: download and SHA256 check against `uss_stats.json`, then `uss_data.py` |
| HF base models | Public (Hugging Face) | Pinned revisions in `meta.json` |

## Pending

New post-V3 artifacts (Worker E's final RL policy, Worker F's TF-IDF predictor) will be added to the vault when they exist; their rows are below.
