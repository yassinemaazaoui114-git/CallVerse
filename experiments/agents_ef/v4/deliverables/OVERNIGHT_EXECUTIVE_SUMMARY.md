# Overnight executive summary (post-V3)

Three workstreams ran in parallel:
- **E**: RL research;
- **F**: quality and knowledge;
- **D**: integration and delivery.

V3 is untouched and its TEST was used for no new choice. Everything is committed locally on `research/agents-e-f-tiny-models`; nothing was pushed or merged. All Agent E numbers are simulated.

## Bottom line

- **Agent E.** A trained tiny RL policy is kept as the research deliverable: floor@3 + guarded Lagrangian Dueling DDQN, 8,146 params. It passes the pre-declared urgent-customer margins on a new, pre-registered test.
  - **No RL policy beats MPC while staying inside those margins.**
  - The real improvement of the night is a simple **urgent floor (queue C ≥ 3)**. It repairs most of RL's queue-C failure (−10.7 → −3.7 pp vs MPC for pure DDQN).
  - With MPC, the same floor gives the best urgent-safe controller measured. That classical controller dominates the safe RL policy.
- **Agent F.** All five M7 responsibilities work offline and are tested.
  - The recommended scorer (TF-IDF + Ridge, 193k params) is saved and reproduces V3 exactly.
  - The flat ShopNova scores are explained: domain and structure mismatch, not a bug.
  - Accurate satisfaction prediction for CallVerse is **blocked** by missing genuine labels. The F → E reward gate stays **closed**.
- **Delivery.**
  - Every selected model is backed up and hash-verified in a private vault: https://claude.ai/artifact/CJ3RnnzJpDK317jC9YvdbY
  - End-to-end offline tests and a demo pass.
  - Tests: **149** research tests (31 of them integration) and **300** prototype tests pass.

## Evidence

| Claim | Evidence |
|---|---|
| Pre-registration frozen before TEST4 | `v4/e/configs/preregistration.json` written 01:03:21Z; first TEST4 row 01:05:40Z; the evaluator refuses unlisted policies |
| Fresh test set | `test4_manifest.json`: 650 days, 13 families, seeds 1,300,000+, SHA256 `cedc50af…` |
| V3 findings replicate on new days | V3 pure DDQN −3.29 [−6.76, +0.41] (V3: −3.7); V3 guarded +3.50 [−0.19, +6.97] (V3: +4.1); V3 guarded queue C −9.4 pp (V3: −9.5) |
| The floor helps | floor@3 + pure DDQN vs V3 pure DDQN: return +4.91 [+0.38, +9.09], queue C +7.07 pp [+4.31, +9.88] |
| Best return breaks safety | floor@3 + guarded (V3 DDQN): +6.89 [+2.99, +10.48] vs MPC, but queue C −2.74 pp and HIGH −0.12 pp (margins −2.0 / −0.2). Gain from severe_overload (+75.2); other families −2.5 to +3.7 |
| Safe RL pick | floor@3 + guarded Lagrangian DDQN: −4.57 [−8.74, −0.29], queue C +1.79 pp, lost +0.60 pp |
| Classical floor@3 + MPC | −0.45 [−0.93, −0.02], queue C +1.91 pp, lost −0.07 pp: dominates the safe RL pick |
| Why RL lost (diagnosis) | Q-values undervalue moves into C exactly when ≥ 3 C tickets wait (by 0.26–0.67); 60% of decisions are activate/deactivate dithering (MPC 22%); VAL noise of about 15 exceeds the effects; some seeds memorise the clock (7–32% of decisions change) |
| F scorer reproduced | VAL 0.39542 / TEST 0.39187, 1,016/1,016 predictions identical; SHA256 `1c201853…` |
| F flat scores explained | 0% truncation, inference matches V3 (≤ 5e-05); 2-turn template conversations vs USS's about 28 turns; USS cut to the ShopNova shape is at the mean floor (0.413 vs 0.414) |
| M7 checks | 14 flags with positive / negative / boundary tests. Wiring check: 16/16 planted defects caught on held-out; 0/91 false flags; 184/184 evidence refs valid. Two dev false-positive sources fixed |
| Integration | Real Intake → ticket bridge → RL adapter → independent validator (agrees with the simulator mask on 13 families) → update; closed-loop days pass. 30 held-out conversations → Agent F → contract: 30/30 refused for the reward |

## What did not improve

- **RL vs MPC.** Under the urgent margins RL still does not beat MPC.
- **Failed approaches:**
  - the dynamic Erlang shield (over-protects, −22 to −54 return);
  - the confidence gate (−10 pp on queue C);
  - hierarchical retraining (worse than MPC);
  - retraining inside the floor (worse than reusing the V3 nets);
  - the Lagrangian alone (−10.3 return).
- **Agent F modelling.**
  - A role-marker variant won on VAL but tied on TEST (−0.0012 [−0.0080, +0.0063]).
  - No variant fixes the domain gap without CallVerse labels.

## Recommended models

| Role | Model |
|---|---|
| Agent E, RL deliverable | `dueling_double_dqn_h64x64_150k_lag0d2t0.9_s1` inside floor@3 + guarded. SHA256 `ed5810c1…`, 34.9 KB, 0.34 ms |
| Agent E, deployable urgent-safe controller | floor@3 + Fluid MPC (no learned part) |
| Agent F scorer | TF-IDF + Ridge on the last 256 tokens. SHA256 `1c201853…`, 3.1 MB, about 2.6 ms. English is "indicative, out of domain"; French gets no score |

## Remaining before team integration

1. Genuine satisfaction labels: adopt the reviews contract, or run the annotation protocol.
2. Adopt the E category ↔ prototype route mapping, or expose per-category capacity.
3. An approved task to wire both adapters into `callverse/`.
4. Warm-start the arrival EWMA.
5. Multi-turn prototype conversations, French templates, dated policy sources.
6. Optional: raise the Agent E seed count for the RL deliverable, which has only 5 seeds.

## Files

All deliverables are in `experiments/agents_ef/v4/deliverables/`:
- `CHECKPOINT_BACKUP_STATUS.md`
- `AGENT_E_FAILURE_ANALYSIS.md`, `AGENT_E_RL_IMPROVEMENTS.md`, `AGENT_E_NEW_EVALUATION.md`
- `AGENT_F_DOMAIN_SHIFT_ANALYSIS.md`, `AGENT_F_MODEL_IMPROVEMENTS.md`, `AGENT_F_M7_VALIDATION.md`
- `E_F_INTEGRATION_TESTS.md`
- `FINAL_ARCHITECTURE.md`
- `MODEL_SELECTION_AND_LIMITATIONS.md`
- `RUN_LOCALLY.md`
- `OVERNIGHT_STATUS.json`
