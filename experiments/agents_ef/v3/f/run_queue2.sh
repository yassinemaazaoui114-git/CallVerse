#!/usr/bin/env bash
# Agent F v3, second queue. It replaces the tail of run_queue.sh after the truncation finding (2026-10-25 ~16:40Z:
# every TEST dialogue is longer than 128 tokens; TF-IDF on the last 128 tokens loses ~0.02 MAE on JDDC).
# 1) wait for the running mminilmv2l6 job (PID given as $1) and prune it,
# 2) e5-small L6 at 256 tokens (context-length test on the smallest candidate),
# 3) e5-small 12 layers at 128 tokens (reference: what layer truncation costs).
# Usage: setsid nohup bash v3/f/run_queue2.sh <pid of running job or 0> > v3/f/logs/queue2.log 2>&1 &
set -u
cd "$(dirname "$0")/../.."
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1
export HF_HOME=${HF_HOME:-/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/models/hf}
P=${PY:-/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python}
W=${FV3:-/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3}
OUT=v3/f/results/uss
SEEDS=${SEEDS:-"0 1 2"}
job() {
  tag=$1; shift
  if [ -f $OUT/$tag.json ]; then echo "skip $tag (done)"; return; fi
  echo "=== $(date -u +%FT%TZ) start $tag"
  nice -n 10 $P v3/f/bench_uss.py --data $W/data_uss --save-dir $W/ckpt --out $OUT --seeds $SEEDS "$@" \
     > v3/f/logs/$tag.log 2>&1
  echo "=== $(date -u +%FT%TZ) end $tag (exit $?)"
  $P v3/f/prune_ckpt.py --result $OUT/$tag.json --ckpt $W/ckpt
}
WAIT_PID=${1:-0}
while [ "$WAIT_PID" != "0" ] && kill -0 "$WAIT_PID" 2>/dev/null; do sleep 30; done
$P v3/f/prune_ckpt.py --result $OUT/mminilmv2l6_trim_ft_frac0.5_len128.json --ckpt $W/ckpt
job e5small_trim_ft_L6_frac0.5_len256  --model e5small_trim_ft --layers 6 --max-len 256 --epochs 3 --train-frac 0.5
job e5small_trim_ft_frac0.5_len128     --model e5small_trim_ft --max-len 128 --epochs 3 --train-frac 0.5
echo "=== $(date -u +%FT%TZ) queue2 done"
