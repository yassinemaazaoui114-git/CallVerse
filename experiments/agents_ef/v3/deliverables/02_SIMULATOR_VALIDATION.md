# 02 — Simulator validation (Agent E, Gate A)

**Status: Gate A PASSED for the v3 simulator** (`v3/e/env_v3.py`).
- 25 / 25 invariant tests pass (`v3/e/tests/test_env_v3.py`).
- The v1/v2 simulators have one **critical** validity defect and several minor ones (below). v1/v2 results are kept as historical / development evidence only.

All Agent E numbers in V3 are **SIMULATED**.

---

## 1. Critical defect found in v1/v2: random-event coupling

**Measured** (same TEST seed 30200, "spike" day, three policies):

| Env | Daily arrivals: keep / Forecast / always-deactivate | First step where arrival traces differ |
|---|---|---|
| v1 (`callcenter_env.py`) | 1183 / 1149 / 1110 | step 6 |
| v2 (`intake_env.py`) | 1144 / 1085 / 1198 | step 6 |

**Cause**
- Arrivals (Poisson), arrival times, CSAT noise and abandonment draws all used **one** generator (`self.rng`).
- A policy that serves more tickets draws more CSAT noise and fewer abandonment uniforms. The generator state then shifts, and **the next arrivals change**.

**Consequences for earlier results**
- Each policy still faced arrivals from the *same distribution*, so mean comparisons are unbiased.
- But the days were **not** common across policies. The v2 "paired" bootstrap CIs (`bench/paired_stats_e.py`) assumed identical days, so they are **not valid as paired intervals**. They are kept only as history.

**Fix in v3: exogenous tapes**
- `EnvV3.build_tape(seed)` generates the **whole world of a day before any decision**, from independent `SeedSequence` streams:
  1. scenario specification;
  2. arrivals and arrival times;
  3. Intake ticket attributes (prototype priority formula);
  4. a patience time per ticket;
  5. fallback-failure draws and CSAT noise.
- Capacity failures and slow-downs are part of the specification.
- Policies only decide what happens to those tickets.
- **Test:** `test_exogenous_world_is_identical_for_every_policy` checks four very different policies on 5 families: identical arrival times, queues, priorities, patience draws, fallback draws and specification.

---

## 2. Other audit findings and their v3 treatment

| # | Item | v1/v2 behaviour | Severity | v3 |
|---|---|---|---|---|
| 1 | Abandonment randomness | per-step hazard draw from the shared RNG (policy-dependent consumption) | critical (part of §1) | per-ticket patience time T_i ~ Exp(mean patience_q·(1 − 0.3·emotion_i)) after a 2-min grace; same distribution, deterministic given the tape |
| 2 | Service timing | all tickets of a step served "at mid-step": a ticket arriving at minute 4.9 could get wait 0 before it arrived | minor bias | event-driven, work-conserving service at rate = sessions; a ticket starts only after it arrives; it leaves if patience expires first |
| 3 | Priority order | high → medium → low, then FIFO (v2) | correct | same; tested |
| 4 | End-of-day backlog | not in the reward: RL left 1.7–3.2 tickets/day vs 0.2–1.5 for rules (`results/agent_e*/test_rows.csv`): mild exploitation | moderate | still-waiting tickets at the end are **lost**: counted in KPIs and penalised as abandonment |
| 5 | SLA definitions | v1 "urgent SLA" = queue C; v2 "urgent SLA" = HIGH-priority tickets | reporting ambiguity | separate metrics: `sla_high_pct`, `sla_medium_pct`, `sla_low_pct`, `sla_queue_c_pct`; overall `sla_pct` = tickets served within their SLA / **all** arrivals (lost tickets count as failures) |
| 6 | Time encoding | sin/cos(2πt) over an 8-hour (non-cyclic) day makes the start and end of day identical | minor | linear t/96 plus "fallback allowance left" |
| 7 | Fallback quality | only a SIM-CSAT penalty; free in a reward without CSAT | reward-hacking risk | explicit ASSUMPTION: 20% of fallback answers do not resolve, counted as an SLA failure; fallback never for HIGH; ≤ 25% of the day |
| 8 | Reward | v2 mixed served count, tier-weighted lateness, cost and SIM-CSAT | not a clean 3-objective | §3 |
| 9 | Budget / capacity / mask | correct | — | unchanged and tested (random invalid proposals → keep, counted) |
| 10 | Observation leakage | none found | — | tested: worlds identical up to step 40 and different afterwards give identical observations up to step 40 |
| 11 | Determinism | v1/v2 deterministic per seed, but not common across policies | — | tested: the same policy and seed give identical KPIs and return |

---

## 3. Reward: locked before any RL training

**Objective chosen by the user:** balance SLA, abandonment and cost.

Every ticket has exactly one outcome: on time | SLA miss (served late, or fallback-unresolved) | lost (abandoned, or still waiting at day end).

r_t = −[ w_sla · (miss_t + lost_t) / F_ref + w_ab · lost_t / L_ref + w_cost · sessions_t / C_ref ]

**Reference constants** (`v3/e/results/reward_reference.json`)
- Measured with planned staffing (Fixed, 16 sessions) on 200 TRAIN days.
- F_ref = 1.947 SLA failures per step; L_ref = 1.656 lost per step; C_ref = 16 sessions.
- Under that reference, 1.9% of tickets are served late and 10.8% are lost.

**Properties**
- The day's return is **exactly a function of the reported KPIs**: −(SLA-failure count / F_ref + lost count / L_ref + cost / C_ref). It is tested.
- So weight sensitivity can be recomputed for any policy without re-simulation.
- **Equal weights mean** that a 10% relative improvement of SLA failures, of abandonment or of cost is worth the same.
- A lost customer is counted in both the SLA failure and abandonment terms. That matches the standard KPI definitions, and makes losing a customer costlier than serving them late.

**Normalisation choice, made on VAL with rule policies only, before any RL run and before TEST** (`v3/e/results/reward_normalisation_check_val.json`, 48 VAL days):

| Normalisation candidate | VAL optimum among 11 rule policies | Its outcome |
|---|---|---|
| raw percentage points (cost / 16 vs tickets / 17.5 per step) | fluid MPC, k = 0 | **25.9% customers lost**, cost −37%: pathological |
| reference, miss-only | Erlang-C (0.2) | 4.7% lost, cost +7.5% |
| **reference, standard KPIs (locked)** | Erlang-C (0.6) | 4.6% lost, cost +4.5% |

**Sensitivity presets:** sla_heavy (2, 1, 1), abandon_heavy (1, 2, 1), cost_heavy (1, 1, 2). Rankings under all presets are reported, together with weight-free Pareto fronts.

---

## 4. Workload and scenarios

- **Workload** is the offered-load ratio ρ = mean over the day of Σ_q λ_q·service_q / 5 min, divided by the 16 planned sessions. It is tested: the generated λ matches ρ·16 exactly.
- **TRAIN families:** normal (Olist-flat shape), morning_peak, two_peak, tracking_spike (queue A × 2.5–4), volatile (ρ × lognormal σ = 0.43), slowdown (× 1.3–1.7), failure (−4 to −8 sessions), high_priority_surge (+30–60% late orders → more HIGH tickets via Intake's formula). Each has ρ ∈ {0.6, 0.8, 0.9, 1.0, 1.1}.
- **Held out (TEST only):** evening_peak, refund_surge (queue B × 2–3), combined_shock (spike + slowdown + failure), severe_overload (ρ = 1.3, beyond budget), random_shape.
- **VAL:** 6 days × 8 TRAIN families = 48 days.
- **Locked TEST:** 50 days × 13 families = 650 days.
  - The manifest is hashed (`v3/e/configs/test_manifest.sha256 = 673373a7…`); the evaluator refuses a changed manifest.
  - Seeds start at 900,000, disjoint from TRAIN (0–199,999), VAL (500,000+) and all v1/v2 seeds.

---

## 5. Which assumptions are supported by data, and which are invented

| Quantity | Source |
|---|---|
| Intake priority formula and labels, R-ESC-01 threshold | **prototype code** (`callverse/intake/priority.py`, `config.yaml`, policies) |
| Queue discipline (priority, then FIFO) | **prototype code** (`callverse/queues/queue.py`) |
| Late-delivery share (8.1%), days-late distribution, order value > 300 (10.4%) | **real public data** (Olist) |
| Near-flat 10:00–18:00 demand shape; day-to-day volatility CV 0.43 | **real public data** (Olist orders; orders ≠ support contacts) |
| Queue mix, base rates, service times, patience, emotion distribution, patience–emotion link, tier SLA factors, fallback speed-up and failure rate, morning/evening/two-peak shapes | **INVENTED** (no CallVerse contact logs reachable). Parameterised; sensitivity on reward weights reported; other sensitivities = future work |

---

## 6. Tests (`python -m pytest v3/e/tests`, 25 passed)

- identical exogenous world across policies (5 families × 4 policies);
- every ticket has exactly one outcome; budget, urgent minimum, capacity, fallback cap and no HIGH fallback hold on all 13 families under random proposals;
- invalid-proposal accounting;
- reward decomposition equals ticket outcomes, and the return equals the KPI formula;
- no future information;
- deterministic KPIs;
- rule baselines run; checkpoint reload gives identical decisions;
- manifests are disjoint and held-out families appear only in TEST;
- ρ calibration.
