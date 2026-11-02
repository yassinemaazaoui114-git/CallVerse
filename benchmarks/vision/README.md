
# CallVerse — Vision Model Benchmark

## 1. Objective

Evaluate lightweight vision-language models for detecting visible physical damage in customer-submitted product images.

The objective is to identify a model suitable for local integration into CallVerse, considering classification accuracy, damage-detection sensitivity, inference latency, output reliability, and hardware constraints.

## 2. Hardware and Environment

- Operating system: Windows 11
- RAM: 16 GB
- GPU: Intel Iris Xe integrated graphics
- Inference: Ollama, CPU-based
- Python environment: Virtual environment (.venv)
- Execution: Local machine, without cloud inference

## 3. Dataset

The benchmark contains 30 product images:

- 15 damaged products
- 15 intact products
- Multiple product categories, including electronics, accessories, footwear, clothing, and packaging
- Image formats: JPG, PNG, and WebP

Ground-truth labels are stored in `labels.csv`.

Images are converted to RGB, resized to a maximum of 512 × 512 pixels while preserving aspect ratio, and encoded as JPEG before inference.

This is a small exploratory dataset, not a representative production evaluation dataset.

## 4. Models Evaluated

| Model | Ollama identifier |
|---|---|
| Qwen3-VL 2B | `qwen3-vl:2b` |
| Moondream 1.8B | `moondream:1.8b-v2-q4_0` |
| Granite Vision 2B | `granite3.2-vision:2b-q4_K_M` |

## 5. Inference Configuration

Common settings:

- Temperature: 0
- Maximum generated tokens: 600
- Non-streaming responses
- Model warm-up before benchmark
- Model keep-alive: 30 minutes
- Binary classification: `damaged = true/false`

Model-specific settings:

- Qwen3-VL: reasoning disabled (`think: false`), JSON validated after generation
- Moondream: Ollama JSON output enforcement (`format: "json"`)
- Granite Vision: Ollama JSON output enforcement (`format: "json"`)

Moondream and Granite use the revised prompt:

> Look carefully at this product image. Is there clearly visible physical damage such as cracks, breakage, tears, or missing parts? Normal product features are NOT damage. If no clear damage is visible, answer false. Return only JSON: {"damaged": true} or {"damaged": false}.

Qwen3-VL was evaluated using an earlier, shorter prompt.

Therefore, this benchmark compares tested model configurations rather than fully standardized model conditions.

## 6. Evaluation Metrics

- Accuracy: correct predictions divided by all images
- Precision: TP / (TP + FP)
- Recall: TP / (TP + FN)
- Specificity: TN / (TN + FP)
- F1-score: harmonic mean of precision and recall
- JSON validity: percentage of responses matching the expected schema
- Latency: elapsed request time per image, in seconds
- RAM: snapshots of Ollama-related process memory before and after inference

Invalid outputs are counted as failures in overall accuracy but are excluded from precision, recall, specificity, and F1 calculations.

RAM measurements are process snapshots, not peak model-only memory usage.

## 7. Benchmark Results

| Metric | Qwen3-VL | Moondream | Granite |
|---|---:|---:|---:|
| Accuracy | 80.00% | 83.33% | 66.67% |
| Precision | 82.35% | 91.67% | 100.00% |
| Recall | 93.33% | 73.33% | 33.33% |
| Specificity | 76.92% | 93.33% | 100.00% |
| F1-score | 87.50% | 81.48% | 50.00% |
| Valid JSON | 28/30 | 30/30 | 30/30 |
| Average latency | 9.61 s | 1.02 s | 68.71 s |

Moondream's improved configuration was repeated on the same dataset and reproduced all 30 predictions. Its second-run average latency was 0.46 seconds.

## 8. Model Analysis

### Qwen3-VL

Qwen3-VL achieved the highest damage-detection recall (93.33%), identifying 14 of 15 damaged products.

However, it produced two invalid responses and had higher inference latency than Moondream.

### Moondream

Moondream achieved the highest overall accuracy (83.33%) and the lowest latency.

Its improved prompt reduced false positives substantially, but the model missed four damaged products.

### Granite Vision

Granite produced valid JSON for all images and correctly identified every intact product.

However, it detected only 5 of 15 damaged products and had the highest inference latency.

## 9. Provisional Model Selection

Qwen3-VL is the preferred candidate when damage-detection recall is the primary requirement.

Moondream is a strong alternative when low latency and overall accuracy are prioritized.

Granite Vision is not recommended for the current local deployment configuration.

The final model selection should depend on operational requirements and further validation.

## 10. Limitations

- Small dataset of only 30 images
- No independent held-out evaluation dataset
- Limited product-category coverage
- Potentially ambiguous images
- Different prompts and output configurations across models
- No confidence calibration
- No concurrent-request or sustained-load testing
- RAM measurements do not represent peak memory usage
- Results do not establish production-level reliability

## 11. Reproduction

From the CallVerse project root, activate the Python virtual environment and ensure Ollama is running.

Run individual benchmarks:

```powershell
python .\benchmarks\vision\benchmark_vision.py
python .\benchmarks\vision\benchmark_moondream.py
python .\benchmarks\vision\benchmark_granite.py
```

Generate the consolidated comparison:

```powershell
python .\benchmarks\vision\compare_models.py
```

**Important:** Check the `RESULTS_FILE` variable in each script before running. Benchmark scripts overwrite their configured CSV output files.

