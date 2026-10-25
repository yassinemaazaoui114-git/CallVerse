# Agent F — tiny satisfaction model: what was saved, what was tried, what to use (F2)

**Worker F, v4, 2026-10-26.**
- Code: `v4/f/tfidf_predictor.py`, `v4/f/f2_experiments.py`, `v4/f/f2_compare.py`, `v4/f/latency_tfidf.py`.
- Results: `v4/f/results/`. Notebook: `v4/f/NOTEBOOK.md` (N1, N3).
- Data: USS TRAIN 4,740 / VAL 1,016 / TEST 1,016 dialogues (EN + ZH), split by dialogue as in V3.

## In plain words

- The best V3 satisfaction model was a very small text model (TF-IDF + Ridge, 0.19 M numbers). V3 only kept its scores, not the model itself.
- It is now re-built with the same recipe and saved. It gives **exactly** the same 1,016 test predictions as in V3, and it loads with a checksum.
- I then tried five targeted changes about the ShopNova mismatch: customer words only, separate customer/agent features, one model per language, and the ShopNova shape.
- None of them is a real improvement on the test set. One looked better on validation, but the gain disappeared on test.
- The most useful finding is negative. When USS dialogues are cut to the ShopNova shape (one client message + one reply), no model beats "always predict the average". So the fix is data, not a cleverer model.

## 1. The recommended scorer is now a real, loadable file

| Item | Value | Source |
|---|---|---|
| Model | TF-IDF word 1–2 + char_wb 3–5 grams on the last ~256 tokens + Ridge (alpha 3, chosen on VAL) | `tfidf_predictor.py`, recipe copied from `v3/f/bench_uss.py` |
| Path (outside git, not durable) | `/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3/ckpt/tfidf_ridge_tail256/` (`model.joblib`, `meta.json`) | |
| SHA256 of `model.joblib` | `1c2018532cf6b50631eca9e150e66b94f2ac8c1cdfead1d620e44b7088a75261` (checked before unpickling) | `meta.json` |
| Size / parameters | 3.08 MB / 193,429 | |
| Reproduction | VAL MAE 0.39542 (V3 0.39542), TEST MAE 0.39187 (V3 0.39187), **1,016 / 1,016 TEST predictions identical at 4 decimals** | `results/tfidf_ridge_tail256_reproduction.json` |
| USS TEST | MAE 0.392 (EN 0.301, ZH 0.489), Spearman 0.596 [bootstrap 95% CI 0.550, 0.638] | same + `results/card_tfidf_ridge_tail256.json` |
| Baselines (TEST) | pooled TRAIN mean 0.510; per-corpus mean 0.423 (V3); noise limit EN 0.234, ZH 0.247 (V3) | `v3/f/F_RESULTS.md` |
| Cost (CPU, 2 threads, shared machine, load average ≈ 4–5) | load 2.9 s incl. imports; batch-1 p50 / p95 2.6 / 4.4 ms on ShopNova texts, 4.1 / 6.0 ms on USS; peak RSS 236 MB | `results/latency_tfidf.json` |
| Interface | `TfidfSatisfactionPredictor.load(dir).predict(texts) -> [{score, label}]`, the same as V3's `SatisfactionPredictor` | |
| Languages validated | EN, ZH only. Any non-Chinese text uses the EN cut. **French is not validated** | `meta.json` `lang_rule` |
| Re-create | `python -m v4.f.tfidf_predictor --data $FV3/data_uss --out $FV3/ckpt/tfidf_ridge_tail256 --v3-result v3/f/results/uss/tfidf_ridge_tail256tok.json` (26 s) | |

## 2. Targeted experiments (domain mismatch, not parameters)

- **Selection rule, fixed before running:** lowest VAL MAE; within 0.002, fewer parameters.
- TEST was scored **once**, for the VAL winner only. Figure: `figures/f2_variants_val.png`.

| Variant | Question it answers | Params | VAL MAE | VAL EN | VAL ZH | VAL Spearman EN |
|---|---|---|---|---|---|---|
| baseline (V3 tail-256) | — | 193k | 0.3954 | 0.3070 | 0.4900 | 0.317 |
| two_turn (first customer turn + last agent turn) | Is there signal in the ShopNova shape? | 33k | 0.4130 | 0.3174 | 0.5152 | 0.196 |
| customer_only | Do the customer's words carry the signal? | 121k | 0.3928 | 0.2996 | 0.4924 | 0.367 |
| **roles** (full + customer-only + last customer turn blocks) | Does turn / role separation help? | 325k | **0.3880** | 0.2957 | 0.4866 | 0.386 |
| lang_split (one Ridge per language) | Language-aware model? | 194k | 0.3962 | 0.3066 | 0.4919 | 0.314 |
| roles_lang_split | Both | 326k | 0.3882 | 0.2948 | 0.4881 | 0.381 |

### TEST, once, for the VAL winner (`roles`)

Sources: `results/f2_test_roles.json`, `results/f2_compare.json`.

| | baseline | roles | paired diff (bootstrap 95% CI, 2,000 resamples) |
|---|---|---|---|
| TEST MAE all | 0.3919 | 0.3906 | −0.0012 [−0.0080, +0.0063] |
| TEST MAE EN | 0.3012 | 0.3011 | −0.0002 [−0.0077, +0.0077] |
| TEST MAE ZH | 0.4888 | 0.4864 | −0.0024 [−0.0136, +0.0094] |
| Spearman all | 0.596 | 0.597 | — |
| ShopNova prediction SD | 0.050 | 0.084 | (spread, not accuracy) |
| Probe groups with a wrong-sign response (of 7) | 1 (status calm→angry +0.03) | 3 (status calm→angry +0.17; complaint closing turn > no closing turn in both closing groups, +0.03 / +0.04) | |

**Conclusions**
1. **No significant improvement.** The VAL gain of roles (−0.0075) did not transfer to TEST (−0.0012, CI includes 0). The hypothesis "role separation helps" failed on TEST. The roles model is saved for traceability only: `$FV3/ckpt/tfidf_roles_tail256/`, SHA256 `318bbbf2…`. The first save pickled a `__main__` class; it was re-saved as plain parts without re-fitting (`meta.json` → `note`).
2. **ShopNova shape = no signal.** two_turn is at the per-corpus floor (VAL 0.413 vs 0.414). On ZH it is worse than the floor. This is the key evidence for the domain-shift analysis.
3. **Customer words matter most.** customer_only beats the baseline on VAL with 37% fewer features. It was not tested on TEST: it was not the VAL winner.
4. **Language-aware models give no gain.** The pooled model already separates EN and ZH.
5. **Quantization was not done**, because it is not useful: the model is 3 MB and runs in about 3 ms. The neural e5 int8 copy from V3 is unchanged.

## 3. Recommendation

| Use | Model | Why |
|---|---|---|
| **Default Agent F scorer** (M7 v4, `AgentF.load({"scorer": "tfidf:<dir>"})`) | **TF-IDF+Ridge tail-256** (§1) | Best measured on USS (tied with e5 at 0.391–0.392). 90× fewer parameters than e5-L6. 2.6 ms vs 58 ms. Deterministic, re-creatable in 26 s. |
| Multilingual neural option | V3 e5-small trim L6/256, seed 1 (`model.pt` SHA256 `466c0cc8…`, 17.4M params) | Kept for the future. French product-review evidence exists for this family only (Amazon FR). It is not validated on French dialogues. |
| Not recommended | roles variant; TinyBERT-EN (English only) | Above. |

**Limits that apply to every option:**
- The labels are USS annotator judgements of other dialogues.
- On ShopNova every scorer is `indicative_out_of_domain` at best. French gets no score.
- None may feed E's reward (gate closed).

## 4. NOT VERIFIED

- Accuracy on CallVerse / ShopNova conversations: no labels.
- French and Arabic: no labelled dialogues.
- Full-protocol neural retraining (GPU): not in scope here.
