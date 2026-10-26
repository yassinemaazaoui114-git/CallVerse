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
- Grid result (VAL, `results/f3_ridge_grid.json`): B_v3 reproduces V3 exactly (VAL 0.3954, alpha 3).
  One-factor gains: roles +0.0047 (only factor >= 0.001); noword +0.0004; tailfull -0.0002; charwb25 0;
  tail512 -0.0019; word13 -0.0006; char13 -0.0006; nochar -0.0046; mindf5 -0.0003; nosublin -0.0003; lang -0.0008.
  Greedy rule → selected "roles" (VAL 0.3907). CAVEAT: v4 already scored a very similar roles variant on TEST
  (tie, diff -0.0012 CI [-0.008, +0.006]); my TEST score of the v5 roles config will therefore not be a blind
  confirmation in spirit even though the selection procedure is VAL-only. Written down before scoring.

## 15:50 — F9 M7 v5 checks (`m7/quality_v5.py`, tests `tests/test_m7_v5.py`, 14 pass)
- 7 new deterministic checks (refund promise unbacked by approved+executed refund, EN via callverse.slm.check and
  FR regex; delivery-time promise without data date; reply numbers not in the decision; instruction/tool-format
  leak; EN client→FR reply; follow-up promise without subscription/escalation; executed refund > balance).
- On the 240 scripted conversations: 0 new flags (templates are consistent with the decision) → 0 false positives;
  recall only from unit tests (no planted defect of these kinds exists in the corpus).

## 15:55 — F8 labelling package (`labelling/`), dry run SCRIPTED (pseudo-random fill-in ratings, NOT labels)
- Test found a rounding bug in allocate() (total 101 for n=100) → fixed (exact total).
- Finding: in the scripted corpus every FR conversation is P1 (English templates → reply_language_mismatch).
- Mutation test on the 240 real-format conversations (inject one defect per new kind): first run found a BUG —
  reply_delivery_promise_unsupported recall 99/240 because the data-date exemption looked at the whole reply
  (templates always say "the promised delivery date was …"). Fixed: exemption only within the promise's sentence;
  regression test added. After the fix all 7 kinds 100% detected, no cross-firing. Caveat: the mutation set was
  then used to fix the check, so it is a development set, not an independent recall estimate.

## 16:00 — neural plan, pre-registered BEFORE the F2 loss results
- N2 = n2_scratch_full_mse: documented V3 initialisation (pretrained e5-small, vocab trimmed on TRAIN+VAL text,
  6 layers, fresh head), full TRAIN, MSE, 3 epochs, LR 4e-5 (V3 value) with 6% warm-up + linear decay.
  Why: removes the seed-selection bias of the warm start and isolates "full TRAIN + schedule" vs V3.
- N3 (conditional) = warm start + Huber (delta 0.5) 2 epochs, ONLY if the F2 same-feature comparison shows Huber
  or ordinal lowering VAL MAE by >= 0.003 vs MSE on BOTH TF-IDF and frozen-e5 features, or lowering
  dissatisfied-class MAE by >= 0.05 without raising overall VAL MAE by > 0.002. Otherwise N3 = wmse (sample
  weighting toward extreme classes) is NOT run either (VAL MAE would be the selection metric and weighting trades
  MAE for extremes) and the slot goes to a 2nd seed of the best of N1/N2.
- 384 tokens: NOT run. Evidence: Ridge tail512 is worse than tail256 on VAL (0.3973 vs 0.3954), full text ≈ tail256
  (0.3956): no sign that more context helps; cost x1.6.
- CLS pooling: not run (no evidence it matters; V3 mean pooling; would need a scratch run).
- Ridge saved: $FV5/ckpt/ridge_v5_roles (SHA256 0119f1b0…debb68), reload reproduces grid VAL preds (≤1e-4).
- VAL paired bootstrap vs B_v3 (`results/f3_ridge_val_paired_ci.json`): even on VAL the selected roles gain is
  -0.0047 [-0.0105, +0.0009] — CI includes 0 on the selection set itself; only "nochar" is credibly worse
  (+0.0046 [0.0009, 0.0085]). Expectation written now: TEST gain of roles is likely ~0 (as in v4).
