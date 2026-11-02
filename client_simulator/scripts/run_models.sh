#!/bin/sh
# Runs Test 2 and Test 3 for each model given, logging wall time per step to logs/llm_runs.log
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
for m in "$@"; do
  for t in test2 test3; do
    s=$(date +%s); ../.venv/Scripts/python p3_tests.py $t "$m" --workers 4 > /dev/null 2>> ../logs/llm_errors.log
    echo "$m $t $(( $(date +%s) - s ))s $(date)" >> ../logs/llm_runs.log
  done
done
