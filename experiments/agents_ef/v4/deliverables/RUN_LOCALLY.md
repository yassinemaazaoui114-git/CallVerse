# Run locally (Agents E and F, post-V3)

Everything runs on **CPU**; no GPU is needed. Commands are run from `experiments/agents_ef/` on the branch `research/agents-e-f-tiny-models`.

## 1. Environment

**Windows (PowerShell):**
```powershell
py -3.11 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-research.txt      # torch CPU wheel is enough
$env:TOKENIZERS_PARALLELISM = "false"
```

**Linux / macOS:**
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-research.txt
```

The prototype's own requirements (repository root `requirements.txt`) are needed for the Intake fixture and the M7 corpus builder.

## 2. Restore the models (they are not in Git)

1. Open the private **CallVerse Model Vault**: https://claude.ai/artifact/CJ3RnnzJpDK317jC9YvdbY. Download the `.b64.txt` parts.
2. Decode and check:
```bash
cat agentE_v3_best_checkpoints.b64.txt | base64 -d > agentE.tar.gz && sha256sum agentE.tar.gz
tar -xzf agentE.tar.gz                                  # -> v3/e/runs/*/best.pt (+ manifests)
cat agentF_v4_tfidf_ridge_tail256.b64.txt | base64 -d > tfidf.tar.gz && sha256sum tfidf.tar.gz
mkdir -p $FV3/ckpt && tar -xzf tfidf.tar.gz -C $FV3/ckpt     # -> tfidf_ridge_tail256/model.joblib
```
   On PowerShell, decode with `[IO.File]::WriteAllBytes("x.tar.gz", [Convert]::FromBase64String((Get-Content x.b64.txt -Raw)))`.
3. Compare each archive hash with `v4/deliverables/CHECKPOINT_BACKUP_STATUS.md`.

**Security:** `model.joblib` is a pickle, and loading a pickle runs code. Load it only after the hash matches.

The TF-IDF scorer can also be rebuilt deterministically with `python -m v4.f.tfidf_predictor` (26 s; it needs the USS splits, see `v3/f/RUN_AND_RESUME_F.md`).

## 3. Tests

```bash
python -m pytest v3/e/tests v3/m7/tests v4/e/tests v4/f/tests v4/d/tests -q
cd ../.. && python -m pytest tests -q          # the prototype's own suite (unchanged by this work)
```

## 4. Demos

```bash
python -m v4.d.demo_end_to_end              # tickets -> Agent E -> safety check; conversations -> Agent F; F->E gate
python -m v4.e.demo_adapter                 # Agent E adapter alone (Worker E)
python -m v4.f.demo_agent_f                 # Agent F alone (Worker F)
```

## 5. Re-running experiments

- Agent E v4 training and evaluation: `v4/deliverables/AGENT_E_RL_IMPROVEMENTS.md` and `AGENT_E_NEW_EVALUATION.md`. They list the queue scripts and the pre-registered TEST4 manifest.
- V3: `v3/deliverables/RUN_AND_RESUME.md`. Frozen; do not re-tune on its TEST.
