# Model selection and limitations (post-V3)

Written by Worker D as the independent reviewer. It is checked against:
- `v4/e/results/test4_analysis.json`;
- `v4/f/results/tfidf_ridge_tail256_reproduction.json`;
- the frozen pre-registration (`v4/e/configs/preregistration.json`, frozen **2026-10-26T01:03:21Z**; the first TEST4 row was written at 01:05:40).

All Agent E numbers are **simulated**: 650 new days, 13 families, seeds 1,300,000+, manifest SHA256 `cedc50af…`.

## Agent E

### TEST4: every group vs Fluid MPC (k = 0.5)

Paired two-level bootstrap. Pre-declared margins: queue-C SLA > −2.0 pp, HIGH SLA > −0.2 pp, 0 safety violations.

| Policy | Learned part | Δ return [95% CI] | Δ queue-C SLA | Δ HIGH SLA | Δ lost customers | Δ cost/day | Passes margins |
|---|---|---|---|---|---|---|---|
| floor@3 + guarded (V3 DDQN allocates) | yes | **+6.89 [+2.99, +10.48]** | −2.74 [−3.79, −1.72] | −0.12 [−0.25, −0.04] | +0.08 | −34 | **no** |
| floor@3 + guarded, Lagrangian DDQN (**Worker E's pre-registered pick**) | yes | −4.57 [−8.74, −0.29] | **+1.79 [+1.16, +2.43]** | −0.05 | **+0.60 [+0.48, +0.70]** | −33 | yes |
| floor@3 + MPC (classical, fairness check) | no | −0.45 [−0.93, −0.02] | **+1.91 [+1.75, +2.07]** | +0.03 | −0.07 | +28 | yes |
| floor@3 + MPC envelope, DDQN allocates | yes | +0.18 [−5.69, +5.56] | +0.23 | −0.12 (CI low −0.33) | −0.13 | +27 | no (HIGH) |
| floor@3 + pure DDQN | yes | +1.62 [−2.42, +5.49] | −3.67 | −0.05 | −0.20 | +73 | no |
| Lagrangian DDQN alone | yes | −10.28 [−15.33, −5.40] | −1.04 | −0.06 | +0.40 | +68 | yes |
| V3 pure DDQN (old) | yes | −3.29 [−6.76, +0.41] | −10.74 | −0.16 | +0.06 | +50 | no |
| V3 guarded hybrid (old) | yes | +3.50 [−0.19, +6.97] | −9.41 | −0.22 | +0.34 | −74 | no |
| Forecast z = 0.25 | no | −2.97 [−4.99, −0.87] | −9.06 | −0.13 | +1.05 | −75 | no |
| Erlang-C 0.4 | no | −2.80 [−4.69, −0.89] | −6.09 | −0.04 | +0.77 | −21 | no |

**Reviewer's reading** (critical, and stronger than Worker E's report on one point):

1. **The real improvement is the urgent floor, not the learning.**
   - A static floor (queue C ≥ 3 sessions) moves V3 pure DDQN from −10.7 pp to −3.7 pp on queue C, and its return from −3.3 to +1.6 against MPC (paired gain vs the old policy +4.9 [+0.4, +9.1]).
   - It also helps MPC itself: +1.9 pp on queue C for −0.45 return.
2. **No RL policy is both better than MPC and inside the safety margins.**
   - The only significant return gain (+6.9) breaks the queue-C and HIGH margins.
   - It comes almost entirely from one held-out family, severe_overload (Worker E: +75 on that family; −2.5 to +3.7 on the other 12; in-distribution +1.2 [−2.6, +4.7], a tie).
3. **The "safe" RL pick is dominated by a classical controller.**
   - floor@3 + MPC beats the Lagrangian hybrid on return (−0.45 vs −4.57), queue C (+1.91 vs +1.79), lost customers (−0.07 vs +0.60) and HIGH SLA (+0.03 vs −0.05).
   - The Lagrangian hybrid protects queue C by giving up other customers: +0.60 pp lost.
   - The pre-registered rule chose among RL-containing groups only, so it could not see this. The domination is stated here.

### Decision (recommended)

| Use | Policy | Why |
|---|---|---|
| **Deployable controller (urgent-safe, best measured)** | **floor@3 + Fluid MPC** | Passes every margin. Within 0.5 of MPC's return. Best queue-C SLA. No learned part |
| **RL research deliverable (the trained policy)** | **floor@3 + guarded Lagrangian Dueling DDQN** — `dueling_double_dqn_h64x64_150k_lag0d2t0.9_s1`, 8,146 params, 34.9 KB, 0.34 ms/decision, SHA256 `ed5810c1…` (`v4/e/configs/recommended.json`; vault archive `agentE_v4_checkpoints`) | A genuine trained RL policy that passes the pre-declared urgent margins. It is reloadable and integration-tested (adapter default). Its costs are reported, not hidden: −4.6 return and +0.6 pp lost vs MPC |
| Performance-first alternative (team decision) | floor@3 + guarded, V3 DDQN s1 | +6.9 return, but queue C −2.7 pp and HIGH −0.12 pp. Not recommended while urgent safety has priority |

**Why keep RL at all?** It is the project's research question, and the evidence locates where learning helps: queue allocation under overload, where it lost 9.2% vs 13.4% customers in V3 and wins +75 on severe_overload in TEST4. It also shows where learning fails: well-timed urgent protection. With MPC and the floor as backstop, the RL component can be demonstrated without risking urgent customers.

### Limitations (Agent E)
- **Simulated world.** Several parameters are invented (`v3/deliverables/02_SIMULATOR_VALIDATION.md` §5).
- **Small and fragile training evidence.**
  - Only 5 training seeds per new group.
  - The Lagrangian multiplier is non-stationary (λ 0.2–10), so the constraint is soft, not a guarantee.
  - The checkpoint of retrained arms was chosen by best VAL queue-C SLA.
- **What the guarantees cover.** Masks and floors constrain **allocation**. They cannot guarantee future SLA: queue C was 78% on one overload demo day.
- **Integration gaps.**
  - The 4-category model is a research abstraction; the prototype has one queue and two routes.
  - The ticket bridge's arrival EWMA starts cold (0). In the offline demo this made the Forecast capacity rule deactivate sessions while the backlog grew; a deployment must warm-start it from history.
- **V3 TEST** was used for no v4 choice. TEST4 was run once after the freeze.

## Agent F (M7)

**Satisfaction scorer: TF-IDF + Ridge on the last 256 tokens**
- 193,429 params, 3.1 MB, about 2.6 ms per conversation.
- `model.joblib` SHA256 `1c201853…`, in the vault.
- Re-fit reproduces V3 exactly: USS TEST MAE 0.392, Spearman 0.596 [0.550, 0.638], all 1,016 predictions identical.
- The e5-L6/256 transformer (17.4M params) is no better on USS and is kept only as the multilingual option.

**Validity on CallVerse/ShopNova**
- Out of domain, and the scores are almost flat (SD 0.04–0.07).
- The cause is diagnosed: 2-turn template conversations, and USS labels concentrated near 3. USS cut to the ShopNova shape is at the mean-predictor floor.
- **Real-world accuracy is BLOCKED by missing labels.** French and other unvalidated languages get **no score**.

**F → E reward: NOT ALLOWED**
- The gate fails on label type (annotator, not customer) and on domain.
- The D-side contract re-checks it, and the integration tests confirm 30/30 refused.
- Correction to V3: DCH-2 labels come from student annotators, so even with the agreement signed it would not open the gate.

**Quality and knowledge checks**
- 14 deterministic flags, each with positive / negative / boundary tests. Every evidence ref is re-verified against the trace.
- False vs unsupported claims are separated.
- Rule freshness is **NOT CHECKABLE**: the rules carry no dated authoritative sources.
- On the scripted corpora: planted-defect recall 21/21 (dev) and 16/16 (held-out); 0 false flags on 90 and 91 clean conversations. This is a wiring check, not real-world precision.

## What blocks final team integration
1. **No genuine satisfaction labels.** The reviews contract (`v4/f/contracts/`) and the annotation protocol (`v4/f/ANNOTATION_PROTOCOL.md`) need a team decision.
2. **E categories vs prototype routes.** The mapping must be adopted, or the prototype must expose per-category capacity.
3. **Wiring into `callverse/`** needs an approved task (CLAUDE.md).
4. **Multi-turn prototype conversations** would give Agent F the customer's reaction, which is the main lever for satisfaction prediction.
5. **French reply templates; dated policy sources.**
