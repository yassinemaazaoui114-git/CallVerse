# Statistical methodology (shared by Agents E and F, V5)

## Agent E (simulated capacity control)

**Common random numbers**
- Every evaluated policy faces identical pre-generated "tapes" for each day: arrivals, ticket attributes, patience, failures (`v3/e/env_v3.py`; tested).
- Days are therefore **paired**: differences between policies on the same day remove most day-to-day noise.

**Two sources of variance**
1. The training seed of a learned policy (3–10 seeds per configuration).
2. The evaluation day.

Confidence intervals come from a **two-level bootstrap**: resample seeds, then resample days with the same day indices for both policies (`v3/e/analyze_v3.py: boot_diff`). Rule-based policies have no seed level.

**Reported for every comparison**
- Mean paired difference with 95% CI.
- d_z (mean / SD of per-day differences).
- Win rate (share of days the policy beats the reference).
- Holm-corrected p over the pre-registered primary family.

**Selection vs confirmation**
- Development and selection use DEV days only (v4 DEV, seeds 700,000+).
- The confirmatory test uses a new manifest whose hash is recorded.
- Its pre-registration (primary metric, safety margins, comparison set, seeds, correction) is frozen **before** any row of that test exists. The evaluator refuses unregistered policies.

**Safety acceptance (stated before testing)**
- Urgent queue C SLA: non-inferiority vs MPC with a declared margin.
- HIGH-priority SLA: a declared margin.
- Zero hard-constraint violations.

A return gain that fails these is reported as **not a win**. Business-approved thresholds do not exist; margins are research choices and are labelled as such.

**Robustness**
- Per-family results.
- Held-out families and unseen parameter shifts.
- Lower tail: CVaR-10% of daily return, i.e. the mean of the worst 10% of days.

**Selection-biased numbers**
- "Best VAL return of a run" (for example V3's −184.0) is the maximum over about 10 noisy evaluations and is optimistic.
- It is never compared with test numbers or with numbers on other day sets.

## Agent F (satisfaction prediction)

**Data**
- USS: annotator mean ratings.
- Splits grouped by dialogue: 4,740 / 1,016 / 1,016.
- Label types (annotator, customer-submitted, product stars, synthetic) are never pooled.

**Metrics**
- MAE (primary), RMSE, Spearman.
- QWK on rounded labels; per-class MAE.
- Calibration (binned predicted vs observed).
- Subsets: dissatisfied (label ≤ 2.5), highly satisfied (≥ 4).
- Per language: EN, ZH. There are no labelled French support dialogues.

**Comparisons**
- Paired bootstrap over test dialogues (2,000 resamples) for MAE and Spearman differences.
- Holm correction across the candidate family.
- A difference such as 0.007 MAE is called a difference only if its CI excludes 0.

**Selection vs confirmation**
- Hyper-parameters, checkpoints, ensembles and calibration are chosen on VAL.
- TEST is scored once after a written freeze.
- USS TEST was used repeatedly in earlier rounds (V3, v4). This is a stated limitation of any further comparison on it.

**Target domain**
- No target-domain metric is reported until genuine target-domain labels exist (customer-submitted ratings or adjudicated human labels, kept separate).
- Scripted-corpus results are wiring checks only.

## Reproducibility

Every experiment is registered in `v5/registry/experiments.jsonl` with:
- id, worker, configuration, seed;
- dataset name and hash;
- code SHA, hardware;
- start and end time, duration;
- parameter count, checkpoint path and SHA256;
- status: completed / failed / deferred / stopped, with the reason.

Remaining nondeterminism (threaded BLAS on shared CPUs, PyTorch kernels) is documented per worker.
