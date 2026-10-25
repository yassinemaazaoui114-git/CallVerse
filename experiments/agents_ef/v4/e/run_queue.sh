#!/bin/bash
# Resumable training queue for Agent E v4: one train_v4 command per line of the queue file, at most 2 at a time,
# nice 10, 1 thread each. Re-running the script skips finished runs (train_v4 checks run.json status=done).
#   bash v4/e/run_queue.sh v4/e/configs/queue_A.txt     (run from experiments/agents_ef)
PY=/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python
Q=$1
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
grep -v '^#' "$Q" | grep -v '^$' | xargs -P 2 -I{} bash -c "nice -n 10 $PY -m v4.e.train_v4 {} >> v4/e/logs/train_\$(echo '{}' | tr -c 'a-zA-Z0-9.' '_').log 2>&1; echo \"\$(date +%H:%M:%S) finished: {}\" >> v4/e/logs/queue.log"
echo "$(date +%H:%M:%S) queue $Q complete" >> v4/e/logs/queue.log
