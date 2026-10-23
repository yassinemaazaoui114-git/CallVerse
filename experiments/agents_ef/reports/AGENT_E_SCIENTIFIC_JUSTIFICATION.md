# Agent E: scientific justification of the hybrid Forecast + Dueling Double DQN architecture

**Scope**
- Every definition below is taken from the code on branch `research/agents-e-f-tiny-models`; file and line references are given.
- Every number is a measured result saved under `experiments/agents_ef/results/`.
- All Agent E results are **SIMULATED**: our own call-centre simulator, calibrated with public Olist data where the data allow it.
- No CallVerse contact-centre logs were available.

---

## 1. Problem formulation

Agent E is a **finite-horizon, discrete-time MDP** controller of service capacity.

| Element | Definition |
|---|---|
| Episode | one 8-hour working day = 96 decision steps of Δ = 5 min (`EnvConfig.step_min = 5`, `steps_per_day = 96`) |
| Queues | q ∈ {A status, B refund, C urgent, D availability} (`env/callcenter_env.py: QUEUES`) |
| Controlled variables | sessions per queue n_q (integers), fallback mode on/off |
| Exogenous randomness | Poisson arrivals; per-ticket Intake fields; service slow-downs; capacity failures; demand spikes and drifts (`make_scenario`) |
| Objective | maximise E[Σ_t γ^t r_t] with γ = 0.97, effective horizon 1/(1−γ) ≈ 33 steps ≈ 2.75 h |

**Arrivals.** Per step, arrivals_q ~ Poisson(λ_q(t)) with

λ_q(t) = base_q · p(t) · load_day · drift_q(t) · spike_q(t),

- base = (5.0, 2.6, 1.8, 5.6) per 5 min;
- p(t) is the daily demand shape: an assumed two-peak curve, or a real one (Olist);
- load_day ~ U(0.9, 1.05), or U(1.25, 1.4) on "high" days, optionally × lognormal(σ = 0.43; Olist day-to-day CV).

**Service.** One session serves one ticket in service_q = (4, 8, 6, 3) minutes, × 0.45 on fallback for eligible tickets.

**Abandonment.** A waiting customer leaves with hazard 1/patience_i after a 2-minute grace, with

patience_i = patience_q · (1 − 0.3 · emotion_i), where patience_q = (25, 35, 12, 40) min.

---

## 2. State space: exact definition, 43 dimensions

Code: `CallCenterEnv._obs` (31 values) + `IntakeAwareEnv._obs` (12 values). All values are clipped to [−10, 10], float32.

### 2.1 Per queue q (6 × 4 = 24): indices 6q … 6q+5

| idx | Feature | Formula |
|---|---|---|
| 6q+0 | recent arrivals | arrivals_q(t−1) / 10 |
| 6q+1 | backlog | waiting_q / 50 |
| 6q+2 | mean waiting age | mean(now − arrival) / SLA_q |
| 6q+3 | tail waiting age | p90(now − arrival) / SLA_q |
| 6q+4 | sessions | n_q / 24 |
| 6q+5 | utilisation | EWMA_q · service_q / (5 · max(n_q, 1)) |

EWMA_q ← 0.8 · EWMA_q + 0.2 · arrivals_q. This is Agent E's forecast of demand; it uses no future information (tested).

### 2.2 Global (7): indices 24–30

| idx | Feature |
|---|---|
| 24 | active sessions / 24 |
| 25 | available capacity / 24 (drops during a failure) |
| 26 | fallback on (0/1) |
| 27 | budget left / budget |
| 28 | sin(2π t/96) |
| 29 | cos(2π t/96) |
| 30 | Σ_q EWMA_q / 10 |

### 2.3 Intake-derived (3 × 4 = 12): indices 31 + 3q …

| idx | Feature |
|---|---|
| 31+3q | HIGH-priority tickets waiting / 20 |
| 32+3q | mean Intake priority score of the waiting tickets |
| 33+3q | oldest HIGH-priority wait / SLA_high,q, where SLA_high,q = 0.3 · SLA_q |

**Why aggregates only.** The observation contains **no text and no per-customer identity**. Agent E never reinterprets messages; it reads queue-level statistics of Intake's structured output. This satisfies the architecture rule "facts come from tools, agents never act directly". The same 43 values are rebuilt from a JSON queue snapshot by `integration/agent_e_policy.py`. A test checks that the two are identical over 60 steps.

---

## 3. Action space: all 17 discrete actions

Code: `MOVES = [(i, j) for i in range(4) for j in range(4) if i != j]`; `A_KEEP = 0, A_FB_ON = 13, A_FB_OFF = 14, A_ACT = 15, A_DEACT = 16`.

| id | Action | id | Action | id | Action |
|---|---|---|---|---|---|
| 0 | keep | 6 | move B → D | 12 | move D → C |
| 1 | move A → B | 7 | move C → A | 13 | fallback ON |
| 2 | move A → C | 8 | move C → B | 14 | fallback OFF |
| 3 | move A → D | 9 | move C → D | 15 | activate 1 session (goes to the queue with the highest load per session) |
| 4 | move B → A | 10 | move D → A | 16 | deactivate 1 session (from the least-loaded queue, respecting floors) |
| 5 | move B → C | 11 | move D → B | | |

**Why "one change per 5 minutes".** It keeps the action space small: 17 actions instead of a combinatorial allocation vector. Staffing changes are gradual, as in a real centre, and every action is a human-readable proposal for the Coordinator.

---

## 4. Reward function

Code: `IntakeAwareEnv.step`, preset `intake`.

Tickets carry Intake's priority tier k ∈ {low, medium, high}. Per step t:

r_t = w_s · N_t^served / Z − w_a · Σ_{i ∈ abandoned_t} α_{k(i)} / Z − w_l · Σ_{i ∈ served_t, wait_i > SLA_i} β_{k(i)} / Z − w_c · (Σ_q n_q · c) / (16 · c) + w_x · ((mean_{i ∈ served_t} CSAT_i − 3) / 2) · min(N_t^served / Σ_q λ_q(t), 1)

**Parameters**

| Symbol | Value | Meaning |
|---|---|---|
| Z | Σ_q base_q = 15 | typical arrivals per step |
| c | 1 | cost of one session for one step |
| 16 | — | planned sessions (`init_active`) |
| w_s, w_a, w_l, w_c, w_x | 1, 1, 1, 0.5, 1 | reward weights |
| α (abandonment penalty) | low 1, medium 2, high 4 | `abandon_tier_w` |
| β (lateness penalty) | low 0.25, medium 0.5, high 1 | `late_tier_w` |
| SLA_i | max(SLA_q · f_k, 3 min) | SLA_q = (15, 20, 5, 30); f = (1.5, 1.0, 0.3) |

**SIM-CSAT per served ticket**

CSAT_i = clip(5 − 2 · max(0, wait_i − SLA_i/2) / SLA_i − 0.6 · 1[fallback_i] − |ε|, 1, 5), with ε ~ N(0, 0.3²).

An abandoned ticket counts as CSAT 1 in the KPIs.

**Measured check.** In the worked example (§10) the reward parts are served 1.5333 (= 23/15), abandon 0.2667, late 0.1333, cost 1.0625 (= 17/16) and csat 0.5397. The total is 1.1418, which the script re-computes from the formula.

**Why this reward and not Intake's 0.6/0.25/0.15**
- Intake's weights answer "how urgent is this ticket?". They produce the tier label.
- The reward answers "what does it cost the business to fail a ticket of that tier?". That is a separate decision, made with separate numbers (α, β).
- Re-using 0.6/0.25/0.15 would double-count urgency and make the learned staffing depend on a ranking heuristic that was never meant as a cost.

---

## 5. Intake → Agent E: semantic priorities (TESTED)

1. **Same formula.** priority = 0.6 · severity + 0.25 · time_pressure + 0.15 · emotion.
   - Labels: high ≥ 0.6, medium ≥ 0.35.
   - `env/intake_adapter.priority_vec` re-implements it, vectorised, reading `config.yaml` and the R-ESC-01 threshold (300) from the policy file.
   - Test: equal to `callverse.intake.priority.compute` on 300 random cases.
2. **Semantic over emotional.** The maximum effect of emotion is 0.15, smaller than the severity weight 0.6.
   - Test: a calm client 6 days late (score 0.69, high) outranks a furious client on time (score 0.27, low).
3. **Queue discipline** = the prototype's `callverse/queues/queue.py`: heap by (label rank, arrival).
   - Measured consequence: HIGH-ticket SLA is 99.8–99.9% under **every** policy, including "fixed" (`results/agent_e_v2/summary.json`).
   - So the *ordering* of tickets protects urgent customers. Agent E's leverage is **capacity**: cost, medium/low waiting, abandonment.
4. **What E uses:** only aggregates of Intake's output (§2.3). It never re-scores a message.

---

## 6. Safety constraints and action masking

There are two independent layers.

### 6.1 Action mask

Computed in `action_mask()` before every decision; every agent picks argmax over **valid** actions only.

| Action | Valid if |
|---|---|
| keep | always |
| move i → j | n_i > floor_i, with floor_C = 2 (urgent minimum) and 0 otherwise |
| fallback ON | fallback off **and** fallback_steps < 0.25 · 96 = 24 |
| fallback OFF | fallback on |
| activate | active < available capacity **and** spent + (active + 1) · c · steps_left ≤ budget, with budget = 16 · 96 · 1.15 = 1766.4 |
| deactivate | active > 6 (`min_active`) |

### 6.2 Environment safety layer (in `step`)

- Any invalid action becomes "keep" and is counted as a violation.
- A capacity failure removes sessions from the lowest-priority queues first.
- Fallback never serves a HIGH ticket.
- Fallback is forced OFF when the daily allowance is used up.

### 6.3 Measured

- **0 violations** in all 24 v2 runs × 56 TEST days.
- 0 HIGH tickets on fallback.
- Budget respected on 100% of days.

**Why the cap is necessary**
- An RL agent rewarded by Agent F's predicted satisfaction (F cannot see fallback quality) learned to keep fallback ON **94% of the day, with 62% of tickets** on it.
- Its ground-truth SIM-CSAT fell to **4.30**, the lowest of any policy.
- With the runtime cap the same network scores 102.10 instead of 98.09 (`results/agent_e_v2_freward*`).
- Hard rules must sit outside the learned policy.

---

## 7. Why Double DQN and the dueling architecture

### 7.1 Network

Code: `rl/agents.py: QNet(dueling=True)`.

h = tanh(W₂ · tanh(W₁ x + b₁) + b₂), with 43 → 64 → 64;
V(s) = v^T h + b_v; A(s, ·) = U h + b_A ∈ ℝ¹⁷;
**Q(s, a) = V(s) + A(s, a) − (1/17) Σ_a' A(s, a')**.

Parameters: (43·64 + 64) + (64·64 + 64) + (64 + 1) + (64·17 + 17) = 2816 + 4160 + 65 + 1105 = **8,146**.

Footprint: checkpoint 32 KB; decision latency 0.032 ms on CPU (`results/local_measure/measure_v2_cpu.json`).

### 7.2 Training

`DQN(double=True, dueling=True)`:
- Adam, lr 5·10⁻⁴; Huber loss; gradient norm clipped at 10.
- Replay buffer 100k; minibatch 128; one update every 4 environment steps after 5k warm-up steps.
- Target network copied every 2,000 steps.
- ε-greedy over **valid** actions, decaying linearly from 1 to 0.05 over 60k steps.
- 150k steps (1,562 simulated days, about 6.5 min on one CPU thread), or 400k steps (about 15.5 min).
- Checkpoint = best greedy return on the 30 VAL days, evaluated every 15k / 25k steps. TEST is never used for selection.

**Double DQN target** (masked; `_update`):

y = r + γ (1 − done) · Q_target(s', a*), with a* = argmax over valid a' of Q_online(s', a').

### 7.3 Why Double

- The plain DQN target max_a Q_target(s', a) is a biased-upward estimate whenever the Q-estimates are noisy (Thrun & Schwartz 1993; van Hasselt 2010).
- Here 13–17 actions are valid at once, with almost equal values. In the worked example, the 16 valid Q-values span only 32.64–33.30.
- The max over many near-ties picks noise. Decoupling selection (online net) from evaluation (target net) removes most of that bias (van Hasselt, Guez & Silver 2016).

### 7.4 Why dueling

- In this task **most actions barely change the next 5 minutes**: one session out of about 17. The value of the state dominates; the advantages are small.
- Measured in the example: V(s) = 32.91, with advantages within ±0.35, about 1% of V.
- The dueling head learns V(s) from **every** transition, whatever action was taken, and A only for the differences (Wang et al. 2016).
- That is exactly the regime where it helps.

### 7.5 Empirical selection

Selection was made on VAL. Differences between the DQN variants are small and partly within seed noise.

| Algorithm (v2, 3 seeds) | VAL return | TEST return (in-distribution) | Params |
|---|---|---|---|
| Dueling DDQN | 106.11 ± 0.29 | 105.52 ± 0.98 | 8,146 |
| PPO (masked, GAE) | 106.19 ± 0.21 | 105.40 ± 0.46 | 15,122 |
| Double DQN | 104.90 ± 0.31 | 104.23 ± 0.49 | 8,081 |
| DQN | 104.75 ± 0.82 | 104.93 ± 0.66 | 8,081 |
| Dueling DDQN, 400k steps | 107.16 ± 0.74 | **106.28 ± 0.91** | 8,146 |

In round 1 (v1 env), Dueling DDQN 106.83 ± 0.51 > DQN 106.68 > Double 106.10 > PPO 104.56.

**Honest statement: PPO is statistically tied with Dueling DDQN in-distribution.** We keep the value-based agent for three properties PPO lacks:
1. **Off-policy learning.** It can be trained from logged decisions of the current rule, which is the realistic path to real data.
2. **Explainability.** A Q-value per action can be shown to the Coordinator (§10).
3. **Size.** About half the parameters.

**Decisive measured reason for the hybrid: what each agent actually learned.** Action mix on 14 TEST days (`results/agent_e_v2_diagnose/action_mix.json`):

| Policy | keep | move (1–12) | fallback (13–14) | capacity (15–16) |
|---|---|---|---|---|
| PPO, pure | 0.0% | 0.8% | 0.0% | **99.2%** |
| PPO, guarded | 22.6% | 21.2% | 0.7% | 55.4% (rule) |
| Dueling DDQN 400k, pure | 4.5% | **46.1%** | 2.7% | 46.8% |
| Dueling DDQN 400k, guarded | 13.8% | 28.2% | 3.0% | 55.1% (rule) |

- **PPO** learned almost only to set the capacity level, by toggling activate/deactivate. Under the guard those decisions go to the rule, so **guarded PPO is the rule**. Paired Δ return vs Forecast is −0.03 to +1.60, all CIs include 0, and the win rate is 1–19%: it adds nothing.
- **Dueling DDQN** learned *allocation* (46% session moves). That is the part the hybrid keeps, and the source of its significant +0.39 SLA in-distribution.
- So the value-based agent is the right partner for a Forecast-controlled capacity level.

---

## 8. Benchmark results with statistical uncertainty

**Design**
- 56 TEST days: 7 scenarios × 8 seeds, including the unseen "compound" scenario.
- Identical seeds for every policy, so differences are **paired** per day.
- 3 training seeds per learned policy.
- **95% CIs** from a two-level bootstrap: resample training seeds, then days; 4,000 draws (`bench/paired_stats_e.py` → `results/agent_e_v2_stats/*/paired_stats.json`).
- **Reference policy:** Forecast rule with z = 0, the value chosen on in-distribution VAL among {−0.5, …, 1.0}.
- **Δ = policy − Forecast; win = share of (seed, day) pairs with higher return.**

| Condition | Policy | Δ return [95% CI] | Δ SLA pts [95% CI] | Δ cost | win |
|---|---|---|---|---|---|
| in-distribution | Dueling DDQN 400k | +0.22 [−1.08, +1.50] | **+1.13 [+0.23, +2.28]** | +4 | 0.52 |
| | Guarded hybrid (400k) | −0.51 [−1.40, +0.34] | **+0.39 [+0.11, +0.71]** | −7 | 0.39 |
| | Erlang-C (VAL-tuned) | −0.54 [−1.53, +0.37] | **+1.78 [+1.50, +2.05]** | +119 | 0.50 |
| real flat shape (Olist) | Dueling DDQN 400k | **−4.06 [−5.21, −2.86]** | −0.31 [−1.15, +0.72] | +41 | 0.10 |
| | Guarded hybrid | **−0.99 [−1.88, −0.16]** | −0.05 [−0.32, +0.19] | −1 | 0.35 |
| evening (never in training) | Dueling DDQN 400k | **−6.15 [−7.56, −4.75]** | **−2.07 [−3.32, −0.32]** | +23 | 0.07 |
| | Guarded hybrid | **−1.13 [−2.10, −0.22]** | −0.07 [−0.37, +0.23] | −6 | 0.35 |
| | Guarded hybrid (DR ckpt) | −0.49 [−1.28, +0.32] | +0.10 [−0.25, +0.42] | +1 | 0.42 |
| volatile days | Dueling DDQN 400k | +1.14 [−0.50, +3.43] | **+1.28 [+0.28, +2.48]** | +25 | 0.55 |
| | Guarded hybrid (DR ckpt) | +1.84 [−0.12, +4.61] | **+0.81 [+0.30, +1.43]** | +8 | 0.49 |
| evening + volatile | Dueling DDQN 400k | **−6.33 [−8.41, −4.15]** | **−1.73 [−3.13, −0.20]** | +16 | 0.06 |
| | Guarded hybrid | −0.86 [−2.66, +1.49] | +0.17 [−0.37, +0.80] | −5 | 0.35 |

**Equal-cost view** (`bench/generalize_e.py`)
- Return mixes service and cost, so we also compare against the Forecast cost–service curve (z swept from −0.5 to 1.0) **at the same cost**.
- Pure Dueling DDQN 400k, SLA points: +1.08 in-distribution, +1.15 volatile, −0.60 flat, −2.38 evening.
- Guarded hybrid, SLA points: +0.52, +0.43, −0.03, +0.14, +0.27. It is never below the curve.
- No extrapolation is allowed: runs outside the curve's cost range are excluded.

**Reading**
1. **Familiar or volatile demand.** Pure RL does not lose to the tuned rule on return (CI includes 0) and serves significantly more tickets within SLA.
2. **Unfamiliar demand shapes.** Pure RL loses significantly: −4 to −6 return, with a win rate of only 6–10%.
3. **Guarded hybrid.** Its return is within about 1 point of the rule everywhere. Its SLA is never significantly worse, and significantly better in-distribution (and, with the domain-randomised checkpoints, on volatile days).
4. **Erlang-C** buys about 1.5–2 SLA points for about 100–130 more session-steps per day: a different point on the cost–service trade-off, not a better policy.

---

## 9. Why pure RL failed to generalise, and why the hybrid is robust

Measured with `bench/diagnose_e.py` → `results/agent_e_v2_diagnose/diagnose.json` (Dueling DDQN 400k, 3 seeds, TEST days).

**(a) Clock ablation.** obs[28], obs[29] (sin/cos of time) are the only time-of-day inputs. Replacing them by their daily mean (0):

| Condition | RL return | RL without clock | Δ |
|---|---|---|---|
| in-distribution (two-peak) | 106.28 | 100.97 | **−5.31** |
| volatile (same shape) | 101.39 | 96.21 | **−5.18** |
| real flat | 105.27 | 102.69 | −2.59 |
| evening (reversed shape) | 101.17 | 101.62 | **+0.45** |
| evening + volatile | 96.26 | 97.23 | **+0.96** |

- The network relies heavily on the clock: it learned *when* the peaks happen.
- When the shape changes, that knowledge becomes wrong, and removing it no longer hurts; it even helps.

**(b) Staffing vs offered load by hour.** Ratio of active sessions to the forecast-needed sessions, evening shape:

| Hour | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| RL | 2.00 | 1.68 | 1.78 | 1.19 | 1.09 | 1.21 | 1.07 | **0.95** |
| Forecast rule | 1.88 | 1.34 | 1.28 | 1.24 | 1.20 | 1.14 | 1.12 | 1.13 |

- RL over-staffs the (now quiet) morning and under-staffs the (now busy) end of day.
- Correlation of active sessions with offered load: **RL 0.70 vs rule 0.90** (evening); 0.47 vs 0.79 (flat); 0.74 vs 0.86 (in-distribution).

**(c) Not an out-of-range-state problem.**
- Only 1.0–5.5% of states lie beyond the 99th percentile of in-distribution Mahalanobis distance.
- The individual inputs look familiar. What changed is the **joint relation** between the clock and the load. A function approximator trained on one relation extrapolates it.

**Mechanism.** The Q-network minimises TD error on the training distribution. In that distribution "time of day" is a cheap, low-noise predictor of the coming load, cheaper than the noisy EWMA. So the network learns a time-indexed schedule, a shortcut, and does not generalise across shapes. Domain randomisation over shapes reduces the shortcut (evening gap −1.18 instead of −2.38) but costs in-distribution return (103.13).

**Why the hybrid is robust**
- The Forecast rule recomputes the needed sessions every step from the current EWMA and backlog. It uses square-root safety staffing, need_q = offered_q + z · √offered_q · priority_w_q / mean(priority_w), and contains **no clock**.
- In the hybrid, the rule alone decides *how many* sessions are active (actions 15/16). The RL policy decides only allocation (1–12) and capped fallback (13/14): decisions whose value depends on the **relative** queue state, which transfers across shapes.
- **Measured:** the hybrid's equal-cost SLA gap stays in [−0.03, +0.52] across all 5 conditions.

---

## 10. One complete decision and one learning step

Real checkpoint `dueling_double_dqn_intake_h64x64_s0_400k`, TEST day 30200 ("spike"), step 30 (minute 150). Produced by `python -m bench.explain_decision` → `results/agent_e_v2_explain/decision_example.json`.

**1. State.**
- Sessions: A 5, B 4, C 5, D 3.
- Waiting: A 0, B 2, **C 7**, D 4. No HIGH ticket waiting.
- A demand spike is hitting the urgent queue C.
- The 43 named inputs are in the JSON.

**2. Mask.** 16 of 17 actions are valid. "Fallback ON" (13) is invalid, because fallback is already ON.

**3. Forward pass.**
- V(s) = 32.907.
- Q(keep) = 32.942; **Q(move A → C) = 33.303 (max)**; Q(activate) = 33.162; Q(move D → C) = 33.105; …; lowest valid Q(move C → A) = 32.636.
- The network prefers to take a session from the idle queue A and give it to the spiking queue C.

**4. Hybrid guard.**
- The Forecast rule's own action is "fallback OFF". That is not a capacity change (15/16), so the RL action stands.
- **Executed action: move A → C.**

**5. Environment step.** r = 1.1418 = 1·1.5333 − 1·0.2667 − 1·0.1333 − 0.5·1.0625 + 1·0.5397. In words: 23 served, some lateness and abandonment, 17 sessions paid, mean SIM-CSAT of the served tickets.

**6. Learning (one Double-DQN update on this transition).**
- The online net chooses a* = argmax over valid a' of Q(s', a') = move A → C.
- The target net evaluates it: Q_target(s', a*) = 32.814.
- y = 1.1418 + 0.97 · 32.814 = **32.971**. Q(s, a) = 33.303, so the TD error is **−0.332**: the network was slightly optimistic.
- Huber loss ½ δ² = 0.0552; gradient norm 9.32 (clipped at 10).
- After one Adam step, Q(s, a) = 32.772.
- A single-sample first Adam step overshoots (each weight moves by about lr). In training the same update is averaged over minibatches of 128 transitions and thousands of steps, so Q converges to E[r + γ Q(s', a*)].

---

## 11. Limitations

1. **Simulated environment.**
   - From real data (Olist): flat demand shape, lateness distribution, order values, day-to-day volatility.
   - Assumptions: queue reason mix, emotion distribution, patience–emotion link, tier SLA factors, service times, base rates.
   - No CallVerse contact logs (arrivals, handle times, abandonment) were available.
2. **Statistics.**
   - 3 training seeds per configuration: the seed level of the bootstrap is coarse.
   - 56 TEST days per condition. Many comparisons are reported with no multiple-testing correction; treat CIs that barely exclude 0 with caution.
3. **The guarded hybrid is not trained as a hybrid.** The RL policy was trained to also control capacity. Training it under the guard (or residual RL over the rule) might add more value. NOT VERIFIED.
4. **SIM-CSAT is a formula.** Agent F's real-data reward model (Olist lateness → rating) is weak (Spearman 0.23) and gave no gain.
5. **Hardware.** All Agent E numbers are CPU. GPU is unnecessary at 8k parameters. RTX 4050 measurements are NOT VERIFIED (no access to the PC).
