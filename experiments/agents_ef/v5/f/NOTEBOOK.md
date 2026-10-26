# Worker F v5 — lab notebook (append-only, UTC)

Rules: VAL-only selection; TEST scored once after the freeze file (`results/FREEZE_candidates.json`);
paired bootstrap over TEST dialogues + Holm; every experiment registered in `v5/registry/experiments.jsonl`.

## 2026-10-26 15:30 — start
- Machine rebooted shortly before (uptime 4 min). Worker E started 2 RL processes at ~15:40.
- Read: v3/f/F_RESULTS.md, bench_uss.py, uss_data.py, DATASETS.md; v4 F deliverables (domain shift, model
  improvements), v4/f/tfidf_predictor.py, f2_experiments.py.
- Key prior facts: V3 e5 runs had best epoch = last epoch (3/3) for all 3 seeds with a CONSTANT LR → under-trained,
  budget-limited (50% TRAIN). Seed spread on VAL 0.390–0.405 (std ≈ 0.006) → single-seed VAL differences < ~0.01
  are not meaningful.

## 15:38 — F4 N1 launched first (long pole)
- n1_warm_full_mse: warm start from V3 selected checkpoint (s1), full TRAIN, MSE, 2 epochs, LR 2e-5 linear
  warm-up 6% + linear decay, grad clip 1.0. Hypothesis: V3 was data/budget limited. Caveat written now: s1 was
  the best of 3 seeds on VAL, so its VAL score is optimistically selected (~0.008 below the seed mean) — the VAL
  comparison with V3 inherits this bias; TEST (once, after freeze) is the arbiter.
- ~5 s/step with 2 threads alone, ~6 s/step with E running → ~30 min/epoch.

## 15:40 — F1 data audit (`data_audit.py`)
- 0 exact and 0 normalised (NFKC, lower, digits→0, punctuation/space removed, role tags removed) duplicate
  texts within or across splits. Nearest-TRAIN char-TF-IDF cosine: VAL/TEST 99th pct 0.68 / 0.67, 0 pairs ≥ 0.8.
- PII regex spot-check (terminal only, nothing written): SGD phone numbers are synthetic (SGD fake DB);
  MWOZ numbers are Cambridge venue/taxi numbers from the MultiWOZ DB (public businesses / generated taxi numbers);
  JDDC digits are de-identified placeholders ([数字x], [ORDERID_…]) and 8-digit pseudonymised ids; JDDC URLs are
  jd.com product/help pages; 1 card-like 14-digit JDDC string (inside a pseudonymised context, looks like an
  order/tracking number). No e-mail addresses. No real customer PII found in the spot-check.
- Alibaba/Taobao: Song et al. EMNLP 2019 (D19-1019) "Clothes" (10k) and "Makeup" (3,540) Taobao CS dialogues,
  "service satisfaction ratings in 1-5 stars from customer feedbacks" (GENUINE customer ratings, ZH),
  released at github.com/songkaisong/ssa with NO LICENSE file (GitHub page shows none). NOT downloaded:
  no licence = all rights reserved by default + Taobao platform data. Candidate for a licence request only.

## 15:42 — F3 Ridge VAL grid launched (1 thread; briefly 3 threads in total with N1)
