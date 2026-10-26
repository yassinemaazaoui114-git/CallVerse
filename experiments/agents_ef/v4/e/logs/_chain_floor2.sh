while kill -0 22184 2>/dev/null; do sleep 10; done
OMP_NUM_THREADS=1 nice -n 10 /tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python -m v4.e.evaluate_v4 --split dev --policy-file v4/e/configs/evalsets/dev_floor2.txt
