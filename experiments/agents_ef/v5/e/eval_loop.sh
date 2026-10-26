#!/bin/bash
# Keeps DEV / DEVSHIFT evaluations of finished ablation runs up to date (resumable; evaluate_v5 skips done files).
# Usage: bash v5/e/eval_loop.sh <stop_file>   (exits when <stop_file> exists and nothing is missing)
cd "$(dirname "$0")/../.."
PY=${PY:-/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python}
export OMP_NUM_THREADS=1
nice -n 12 $PY -W ignore -m v5.e.evaluate_v5 --split devshift --policy-file v5/e/configs/devshift_base_policies.txt
while true; do
  M1=$($PY -W ignore -m v5.e.ablation queue dev); M2=$($PY -W ignore -m v5.e.ablation queue devshift)
  [ -n "$M1" ] && nice -n 12 $PY -W ignore -m v5.e.evaluate_v5 --split dev --policies $M1
  [ -n "$M2" ] && nice -n 12 $PY -W ignore -m v5.e.evaluate_v5 --split devshift --policies $M2
  if [ -z "$M1$M2" ]; then [ -f "$1" ] && break; sleep 60; fi
done
echo "eval loop finished $(date -u +%H:%M)"
