
import csv
import statistics
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

MODELS = {
    "Qwen3-VL 2B": "results_qwen3vl_nothink_600tokens.csv",
    "Moondream 1.8B": "results_moondream_improved.csv",
    "Granite Vision 2B": "results_granite.csv",
}


def parse_bool(value):
    value = str(value).strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def evaluate(model_name, filename):
    path = BASE_DIR / filename

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    tp = tn = fp = fn = invalid = 0
    latencies = []

    for row in rows:
        actual = parse_bool(row["ground_truth"])
        predicted = parse_bool(row["prediction"])

        if actual is None:
            raise ValueError(f"Invalid ground truth in {filename}")

        if predicted is None or parse_bool(row["valid_json"]) is not True:
            invalid += 1
        elif actual and predicted:
            tp += 1
        elif not actual and not predicted:
            tn += 1
        elif not actual and predicted:
            fp += 1
        elif actual and not predicted:
            fn += 1

        latency = row.get("latency_seconds", "")
        if latency:
            latencies.append(float(latency))

    total = len(rows)
    correct = tp + tn

    accuracy = correct / total if total else 0
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    specificity = tn / (tn + fp) if tn + fp else 0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0
    )

    return {
        "model": model_name,
        "images": total,
        "accuracy": round(accuracy * 100, 2),
        "precision": round(precision * 100, 2),
        "recall": round(recall * 100, 2),
        "specificity": round(specificity * 100, 2),
        "f1": round(f1 * 100, 2),
        "valid_json": total - invalid,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "invalid": invalid,
        "avg_latency_s": round(statistics.mean(latencies), 2)
        if latencies else None,
        "median_latency_s": round(statistics.median(latencies), 2)
        if latencies else None,
    }


results = []

for model, filename in MODELS.items():
    results.append(evaluate(model, filename))

print("\n========== VISION MODEL COMPARISON ==========")

for result in results:
    print(f"\nModel: {result['model']}")
    print(f"Accuracy: {result['accuracy']}%")
    print(f"Precision: {result['precision']}%")
    print(f"Recall: {result['recall']}%")
    print(f"Specificity: {result['specificity']}%")
    print(f"F1-score: {result['f1']}%")
    print(f"Valid JSON: {result['valid_json']}/{result['images']}")
    print(
        f"Confusion matrix: TP={result['tp']}, "
        f"TN={result['tn']}, FP={result['fp']}, "
        f"FN={result['fn']}, Invalid={result['invalid']}"
    )
    print(f"Average latency: {result['avg_latency_s']} s")
    print(f"Median latency: {result['median_latency_s']} s")

output_file = BASE_DIR / "vision_model_comparison.csv"

with output_file.open("w", encoding="utf-8", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print(f"\nComparison saved to: {output_file}")
