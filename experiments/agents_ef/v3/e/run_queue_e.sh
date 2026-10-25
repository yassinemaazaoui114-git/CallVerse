#!/bin/sh
# Agent E v3 training queue (Gate C). Resumable: train_v3 skips runs whose run.json says status=done.
# Usage (from experiments/agents_ef):  PY=<python> PAR=2 sh v3/e/run_queue_e.sh
PY=${PY:-python}
PAR=${PAR:-2}
cd "$(dirname "$0")/../.." || exit 1
mkdir -p v3/e/logs
{
  # C1: matched 150k budget, 5 seeds, all principal algorithms (+ tabular reference)
  for s in 0 1 2 3 4; do for a in dueling_double_dqn ppo dqn double_dqn dueling_dqn; do echo "$a $s 150000 equal 64,64"; done; done
  for s in 0 1 2 3 4; do echo "tabular_q $s 150000 equal 64,64"; done
  # C2: 10 seeds for the principal candidates
  for s in 5 6 7 8 9; do for a in dueling_double_dqn ppo dqn; do echo "$a $s 150000 equal 64,64"; done; done
  # C3: reward-weight sensitivity (3 seeds)
  for w in sla_heavy abandon_heavy cost_heavy; do for s in 0 1 2; do echo "dueling_double_dqn $s 150000 $w 64,64"; done; done
  # C4: model-size ablation (3 seeds)
  for h in 32,32 128,128; do for s in 0 1 2; do echo "dueling_double_dqn $s 150000 equal $h"; done; done
  # C5: larger training budget (3 seeds)
  for a in dueling_double_dqn ppo; do for s in 0 1 2; do echo "$a $s 400000 equal 64,64"; done; done
} | xargs -P "$PAR" -L 1 sh -c 'nice -n 10 '"$PY"' -m v3.e.train_v3 --algo $0 --seed $1 --steps $2 --weights $3 --hidden $4 \
      --eval-every $(( $2 / 10 )) > v3/e/logs/train_$0_$3_h$4_$(( $2 / 1000 ))k_s$1.log 2>&1;
      echo "$(date +%H:%M) $0 s$1 $2 $3 $4 exit=$?" >> v3/e/logs/queue_e.log'
echo "ALLDONE $(date +%H:%M)" >> v3/e/logs/queue_e.log
