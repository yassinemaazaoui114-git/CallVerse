#!/usr/bin/env bash
# Agent F v3: run the fine-tuning jobs ONE AT A TIME (CPU shared with Agent E), resumable:
# bench_uss.py skips a job whose result JSON exists. After each job, keep only the best-by-VAL seed checkpoint.
# Usage: setsid nohup bash v3/f/run_queue.sh > v3/f/logs/queue.log 2>&1 &
set -u
cd "$(dirname "$0")/../.."                      # experiments/agents_ef
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1
export HF_HOME=${HF_HOME:-/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/models/hf}
P=${PY:-/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python}
W=${FV3:-/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3}
OUT=v3/f/results/uss
SEEDS=${SEEDS:-"0 1 2"}
job() {   # $1 = tag, rest = args
  tag=$1; shift
  if [ -f $OUT/$tag.json ]; then echo "skip $tag (done)"; return; fi
  echo "=== $(date -u +%FT%TZ) start $tag"
  nice -n 10 $P v3/f/bench_uss.py --data $W/data_uss --save-dir $W/ckpt --out $OUT --seeds $SEEDS "$@" \
     > v3/f/logs/$tag.log 2>&1
  echo "=== $(date -u +%FT%TZ) end $tag (exit $?)"
  $P v3/f/prune_ckpt.py --result $OUT/$tag.json --ckpt $W/ckpt
}
# CPU budget (measured 2026-10-25, 2 threads, CPU shared with Agent E): e5-small 12 layers at 256 tokens = 15 s per
# batch of 16 -> about 1 h per epoch. So: 128 tokens (end of the dialogue), 3 epochs, 50% of TRAIN (stratified).
C="--max-len 128 --epochs 3 --train-frac 0.5"
job tinybert_ft_en_frac0.5_len128         --model tinybert_ft --train-langs en $C
job e5small_trim_ft_L6_frac0.5_len128     --model e5small_trim_ft --layers 6 $C
job mminilmv2l6_trim_ft_frac0.5_len128    --model mminilmv2l6_trim_ft $C
job e5small_trim_ft_frac0.5_len128        --model e5small_trim_ft $C
echo "=== $(date -u +%FT%TZ) queue done"
