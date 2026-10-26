#!/bin/bash
# Confirmatory TEST4 evaluation: every pre-registered policy, 650 days, 2 workers, resumable (finished CSVs skipped).
#   bash v4/e/run_test4.sh        (run from experiments/agents_ef, AFTER python -m v4.e.preregister)
PY=/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
$PY -c "import json; print('\n'.join(json.load(open('v4/e/configs/preregistration.json'))['policies_all']))" > v4/e/configs/evalsets/test4_policies.txt
nice -n 10 $PY -m v4.e.evaluate_v4 --split test4 --workers 2 --policy-file v4/e/configs/evalsets/test4_policies.txt
