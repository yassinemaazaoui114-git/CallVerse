#!/bin/bash
# Resumable training queue: N workers pull lines from a queue file (one train_v5 argument line each) using a lock.
# Usage: bash v5/e/run_queue.sh <queue_file> <worker_id>     (run from experiments/agents_ef; nohup for overnight)
# Done runs are skipped by train_v5 itself (run.json status=done), so re-running the queue is safe.
cd "$(dirname "$0")/../.."
Q=$1; W=$2
PY=${PY:-/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python}
CLAIM=v5/e/logs/$(basename $Q).claimed
touch $CLAIM
while true; do
  LINE=$(flock $CLAIM.lock bash -c "grep -vxF -f $CLAIM $Q | grep -v '^#' | grep -v '^\s*$' | head -1 | tee -a $CLAIM")
  [ -z "$LINE" ] && break
  echo "[$(date -u +%H:%M:%S)] worker $W start: $LINE"
  OMP_NUM_THREADS=1 nice -n 10 $PY -W ignore -m v5.e.train_v5 $LINE 2>&1 | tail -2
  echo "[$(date -u +%H:%M:%S)] worker $W end: $LINE"
done
echo "[$(date -u +%H:%M:%S)] worker $W: queue empty"
