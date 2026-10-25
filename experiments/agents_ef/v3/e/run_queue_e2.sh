#!/bin/sh
# Agent E v3 follow-up queue (E+F interaction): waits for queue 1, then trains Dueling DDQN with the SYNTHETIC
# SIM-CSAT shortfall as an extra reward term (fallback cap + HIGH protection unchanged), 3 seeds.
PY=${PY:-python}
cd "$(dirname "$0")/../.." || exit 1
until grep -q ALLDONE v3/e/logs/queue_e.log 2>/dev/null; do sleep 60; done
for s in 0 1 2; do echo $s; done | xargs -P 2 -I{} sh -c "nice -n 10 $PY -m v3.e.train_v3 --algo dueling_double_dqn --seed {} --steps 150000 --eval-every 15000 --w-csat 1 > v3/e/logs/train_csat1_s{}.log 2>&1; echo \"\$(date +%H:%M) csat1 s{} exit=\$?\" >> v3/e/logs/queue_e2.log"
echo "ALLDONE $(date +%H:%M)" >> v3/e/logs/queue_e2.log
