# Agent F v3 — run and resume

Run every command from `experiments/agents_ef/`.

**Resuming.** Every benchmark step skips itself when its result JSON already exists, so re-running a command resumes the work. To redo a step on purpose, delete its JSON first.

## 0. Environment

### Linux sandbox (where these results were produced)

```bash
export PY=/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python
export HF_HOME=/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/models/hf
export FV3=/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3   # data + checkpoints, OUTSIDE git
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
```

### Windows + RTX 4050 (PowerShell)

Use the research venv: `requirements-research.txt` plus torch with CUDA. Then:

```powershell
$env:FV3 = "C:\callverse_work\f_v3"; $env:TOKENIZERS_PARALLELISM = "false"
```

## 1. Data (USS, public)

### Download the raw files

Download the 5 raw files into `$FV3/raw/uss_gh/`:

```bash
B=https://raw.githubusercontent.com/sunnweiwei/user-satisfaction-simulation/master/dataset
mkdir -p $FV3/raw/uss_gh && for f in SGD MWOZ ReDial CCPE JDDC; do curl -sSL -o $FV3/raw/uss_gh/$f.txt $B/$f.txt; done
```

Check the files against the SHA256 values in `v3/f/results/uss_stats.json` (`files.<name>.sha256`).

### Build the splits

This builds the dialogue-level splits (70/15/15 by dialogue, seed 13) and rewrites `uss_stats.json`:

```bash
$PY v3/f/uss_data.py --raw $FV3/raw/uss_gh --out $FV3/data_uss --stats v3/f/results/uss_stats.json
```

The split SHA256 values must match the `split_sha256` entry of `uss_stats.json`.

## 2. Baselines (CPU, minutes)

```bash
for m in mean group_mean hgb_features tfidf_ridge tfidf_logreg; do
  $PY v3/f/bench_uss.py --data $FV3/data_uss --model $m --out v3/f/results/uss; done
$PY v3/f/bench_uss.py --data $FV3/data_uss --model tfidf_ridge --train-frac 0.5 --out v3/f/results/uss
$PY v3/f/bench_uss.py --data $FV3/data_uss --model group_mean  --train-frac 0.5 --out v3/f/results/uss
$PY v3/f/bench_uss.py --data $FV3/data_uss --model tfidf_ridge --train-langs en --out v3/f/results/uss
for t in 128 256; do   # truncation diagnostic: TF-IDF on about the last t tokens only
  $PY v3/f/bench_uss.py --data $FV3/data_uss --model tfidf_ridge --tail-tokens $t --out v3/f/results/uss; done
$PY v3/f/noise_floor.py --data $FV3/data_uss --out v3/f/results/noise_floor.json
```

## 3. Fine-tuned models

### Linux CPU

Runs one job at a time in the background and keeps only the best seed's checkpoint:

```bash
setsid nohup bash v3/f/run_queue.sh > v3/f/logs/queue.log 2>&1 &
tail -f v3/f/logs/queue.log
# afterwards (or instead of its last job): L6 at 256 tokens and the 12-layer reference
setsid nohup bash v3/f/run_queue2.sh 0 > v3/f/logs/queue2.log 2>&1 &
```

Note: `run_queue.sh` still lists `e5small_trim_ft_frac0.5_len128` as its last job. In the sandbox run that job was taken over by `run_queue2.sh`; the result is the same file, so whichever queue runs second skips it.

The CPU settings are 128 tokens, 3 epochs, 50% of TRAIN (stratified) and seeds 0 1 2. They were chosen only for the CPU budget.

### Windows RTX 4050

There, use the full protocol: 256 tokens, full TRAIN, 5 epochs. Example:

```powershell
python v3/f/bench_uss.py --data $env:FV3\data_uss --model e5small_trim_ft --layers 6 --max-len 256 --epochs 5 `
  --seeds 0 1 2 --save-dir $env:FV3\ckpt --out v3/f/results/uss_gpu --device cuda --fp16
python v3/f/prune_ckpt.py --result v3/f/results/uss_gpu/e5small_trim_ft_L6_len256.json --ckpt $env:FV3\ckpt
```

- To run the other models, repeat with `--model e5small_trim_ft` (no `--layers`), `mminilmv2l6_trim_ft`, `mminilm_trim_ft`, and `tinybert_ft --train-langs en`.
- `peak_vram_mb` is then recorded in each run. It is NOT VERIFIED here because this sandbox has no GPU.
- GPU results go to a separate folder (`results/uss_gpu`). Do not mix them with the CPU table: the settings differ.

## 4. Quantization, latency, error analysis, figures, leaderboard

`<BEST>` = the selected tag in `checkpoints_manifest.json` (`e5small_trim_ft_L6_frac0.5_len256`, seed 1).

```bash
$PY v3/f/quantize_f.py --ckpt $FV3/ckpt/<BEST>_s<seed> --data $FV3/data_uss --out v3/f/results/quant_<BEST>.json --save-int8
$PY v3/f/amazon_rescore.py --ckpt <v2 checkpoint e5small_trim_ft_s0> --data <data_amazon/subset_enfr> \
    --out v3/f/results/amazon_rescore_e5small_trim_ft.json
$PY v3/f/latency_bench.py --ckpt-root $FV3/ckpt --data $FV3/data_uss --tags <all fine-tuned tags> --int8 <BEST> \
    --out v3/f/results/latency_cpu.json
$PY v3/f/error_analysis.py --data $FV3/data_uss --models <BEST> tfidf_ridge group_mean --out v3/f/results/error_analysis.json
$PY v3/f/amazon_leaderboard.py
$PY v3/f/make_leaderboard.py
$PY v3/f/make_figures.py --best <BEST> --quant v3/f/results/quant_<BEST>.json v3/f/results/amazon_rescore_e5small_trim_ft.json
$PY v3/f/make_manifest.py
```

## 5. Inference demo

```bash
$PY v3/f/infer_example.py            # uses checkpoints_manifest.json -> selected checkpoint
$PY v3/f/infer_example.py --int8
```

## Where things are

| What | Where |
|---|---|
| Code, configs, metrics, figures, docs | `experiments/agents_ef/v3/f/` (in git) |
| Raw data, splits, checkpoints | `$FV3` (OUTSIDE git, not durable in the sandbox) |
| Logs | `v3/f/logs/` |
