#!/bin/bash
# Worker F v5: run the neural training queue (v5/f/queue.txt, one argument line per run) one job at a time.
# Re-reads the queue after every job, so lines can be appended while it runs. Done runs are skipped by
# train_neural.py itself (results/neural/<name>.json status completed); interrupted runs resume from state.pt.
cd "$(dirname "$0")/../.." || exit 1
source v5/f/env.sh
i=0
while true; do
  line=$(sed -n "$((i+1))p" v5/f/queue.txt)
  [ -z "$line" ] && { echo "queue empty $(date -u)"; break; }
  name=$(echo "$line" | sed -E 's/.*--name ([^ ]+).*/\1/')
  echo "=== $(date -u) start $name"
  nice -n 10 $PY -m v5.f.train_neural $line >> v5/f/logs/$name.log 2>&1
  echo "=== $(date -u) end $name rc=$?"
  i=$((i+1))
done
