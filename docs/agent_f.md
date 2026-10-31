# Agent F — Satisfaction Predictor (Semah)

`callverse.satisfaction.predict_satisfaction(record) -> int 1..5`. CPU only.
Record: `{"text": ...}` or `{"messages": [{"role": "customer", "text": ...}, ...]}` (customer turns scored).
**Provisional interface**: `RL_interface_spec.md` was not available; adapt when it lands.

## Data
Real reviews with real 1-5 stars: `SetFit/amazon_reviews_multi_en` (balanced; downloaded to `data/raw/`).
Train = 60k fixed-seed sample of train split; model chosen on validation (5k); test (5k) read once.
The repo's Olist sample has real scores but no text, so it cannot train a text model.
No simulated ratings used.

## Benchmark (validation, `benchmarks/agent_f/results/benchmark.json`)
| model | MAE | acc | within±1 | p95 ms |
|---|---|---|---|---|
| baseline constant mean | 1.20 | 0.20 | 0.60 | - |
| TF-IDF + ridge | 0.659 | 0.436 | 0.911 | 2.8 |
| **TF-IDF + logreg (chosen)** | **0.638** | **0.512** | 0.883 | 3.2 |
| MiniLM + logreg | not run (sentence-transformers not installed in build env) | | | |

Fine-tuning not justified: TF-IDF is ~60x under the 200 ms budget.

## Held-out test (`results/test_eval.json`)
n=5000: MAE 0.628, accuracy 0.517, within±1 0.888, latency mean 1.9 ms / p95 2.8 ms.

## Run
```
python -m benchmarks.agent_f.benchmark      # choose model (validation)
python -m benchmarks.agent_f.train          # train + save models/agent_f/satisfaction.pkl + test eval
python -m benchmarks.agent_f.evaluate_rated rated.jsonl   # final eval: team's real rated conversations
```
Final evaluation on the ~100 team-rated conversations and RL comparison: pending (data / RL not available yet).
Domain caveat: product reviews ≠ support conversations; the rated set is the real check.
