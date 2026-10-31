# Agent F (RL3) — satisfaction predictor · model card

**Contract** (RL_interface_spec v1): `callverse.quality.satisfaction.predict_satisfaction(record) -> {"score": float 1..5}`.
CPU only, no API, no database write. Measured: ~2 ms mean, p95 3.4 ms per record (limit 200 ms).

## How it scores
1. **Text** (user turns only): TF-IDF (word 1-2 + char 2-5 grams) + logistic regression → expected stars.
2. **Delay prior**: `situation.days_late` → mean real Olist score for that delay (table below).
3. **Blend**: 0.5 text + 0.5 delay if `days_late` known, else text. **Provisional weights** — no real rated
   conversations exist for fitting (the team set is test-only).
4. **Optional stacker** (`models/agent_f/stacker.pkl`, Ridge on text, delay, style, emotion): fit on Mahmoud's
   SIMULATED ratings (flagged) when they exist. Without it the reward does **not** depend on `style`.

## Data
| Use | Source | Real? | Licence |
|---|---|---|---|
| Text model | `SetFit/amazon_reviews_multi_en` (60k train sample, 5k val, 5k test; balanced 1-5) | real stars | Amazon Reviews Multi licence: non-commercial research |
| Delay prior | ShopNova Olist sample (`callverse/data/real/`), review score vs delivered − promised | real | CC BY-NC-SA 4.0 |
| Final check | team ratings (Notion 31, ~100) | real | test only, never trained on |

Olist delay table (`python -m benchmarks.agent_f.olist_delay`): on time 4.22 (n=1801) · 1-2 d 3.07 (27) ·
3-5 d 2.50 (32) · 6-10 d 1.57 (35) · >10 d 1.40 (48).
Earlier simulated-only F experiments (`research/agents-e-f-tiny-models`) are not used: synthetic labels.

## Results — Amazon reviews (real stars)
Validation (model choice): TF-IDF+logreg MAE 0.638, Spearman 0.75 · TF-IDF+ridge MAE 0.696 (float) · predict-mean MAE 1.20.
Held-out test, n=5000 (read once), expected-stars output: **MAE 0.644, Spearman 0.80**, rounded accuracy 0.48, within ±1 0.92.
MiniLM not benchmarked (sentence-transformers not installed in build env). Fine-tuning not justified at 2 ms / budget 200 ms.

## Not yet measured
- Team real ratings: MAE, Spearman vs "predict average" and "delay-only" baselines → `python -m benchmarks.agent_f.evaluate_rated <file.jsonl>`.
- Domain gap: product reviews ≠ support chats; the team set is the real check.

## Rebuild
```
python -m benchmarks.agent_f.benchmark   # choose on validation
python -m benchmarks.agent_f.train       # train, save models/agent_f/satisfaction.pkl, test once
```
