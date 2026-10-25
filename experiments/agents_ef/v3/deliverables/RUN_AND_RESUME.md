# Run and resume — V3 benchmark (Agents E and F)

Run every command from `experiments/agents_ef/`.
Each step is **resumable**:
- training skips runs whose `run.json` says `status: done`;
- the evaluator skips policies whose result CSV is complete;
- Agent F skips steps whose result JSON already exists.

Nothing is overwritten. To redo a step on purpose, move its output away first. Do not delete it.

## 0. Environment (Linux sandbox where the results were produced)

```bash
export PY=/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python
export HF_HOME=/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/models/hf
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
```

On another machine, install `requirements-research.txt` plus torch and set `PY=python`.
Agent E needs CPU only. Agent F fine-tuning is faster on a GPU, but every reported number was measured on CPU.

## 1. Agent E (Worker E, CPU)

```bash
# Gate A: simulator validity tests (must pass before anything else)
$PY -m pytest v3/e/tests -q

# Locked manifests are already in v3/e/configs/ (hash-checked by the evaluator).

# VAL: rule baselines and tuning (writes v3/e/results/val_choice.json)
$PY -m v3.e.evaluate_v3 --split val --workers 2 --policies rule:fixed rule:threshold rule:priority rule:random_valid \
    rule:forecast:0.25 rule:erlang:0.4 rule:mpc:0.5          # the full sweep is listed in 03_BENCHMARK_PROTOCOL.md
$PY -m v3.e.analyze_v3 val

# Gate C: RL training queue (70 runs, about 7-9 h on 4 shared cores)
PY=$PY PAR=2 sh v3/e/run_queue_e.sh          # log: v3/e/logs/queue_e.log, ends with ALLDONE
PY=$PY sh v3/e/run_queue_e2.sh               # E+F experiment (synthetic SIM-CSAT term), starts after ALLDONE

# Locked TEST (only after the candidate set is frozen)
$PY -m v3.e.evaluate_v3 --split test --workers 2 --policies <rule:... rl:<run_id> guarded:<run_id> ...>
$PY -m v3.e.analyze_v3 test                  # -> results/test_analysis.json, test_leaderboard.csv, figures/

# One-day inference example
$PY -m v3.e.infer_example --run dueling_double_dqn_equal_h64x64_150k_s0 --mode guarded
```

## 2. Agent F (Worker F)

See `v3/f/RUN_AND_RESUME_F.md`. It covers the USS download and SHA256 check, splits, baselines, the fine-tune queue (`v3/f/run_queue.sh`), quantization, latency, error analysis, figures and the manifest. Raw data and checkpoints stay outside git, in `$FV3`.

## 2b. Agent F as M7: quality review, rule audit, owner report, E feedback

See `10_AGENT_F_M7_SCOPE.md` §6. Short form:

```bash
$PY -m pytest v3/m7/tests -q
$PY -m v3.m7.report --traces <folder of prototype traces> --out <out> --scorer f:<F checkpoint folder> \
    --card-result v3/f/results/uss/<model>.json --card-data $FV3/data_uss/test.jsonl
```

## 3. Combined status (built from files only)

```bash
$PY -m v3.status_v3          # -> v3/deliverables/BENCHMARK_STATUS.json
```

## 4. Single resume command (both workers)

```bash
cd experiments/agents_ef && PY=$PY PAR=2 sh v3/e/run_queue_e.sh; PY=$PY sh v3/e/run_queue_e2.sh; sh v3/f/run_queue.sh; $PY -m v3.status_v3
```
