
import base64
import csv
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
LABELS_FILE = BASE_DIR / "labels.csv"
IMAGES_DIR = BASE_DIR / "images"
RESULTS_FILE = BASE_DIR / "results_qwen3vl_nothink_600tokens.csv"

MODEL = "qwen3-vl:2b"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

PROMPT = (
    "Analyze the product image for visible damage. "
    "Return only a JSON object with exactly one field: "
    '"damaged", whose value must be true or false. '
    "Do not include explanations."
)


def ollama_memory_mb():
    total = 0

    for process in psutil.process_iter(["name", "memory_info"]):
        try:
            name = (process.info["name"] or "").lower()
            if "ollama" in name or "llama-server" in name:
                total += process.info["memory_info"].rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return round(total / (1024 * 1024), 1)


def prepare_image(image_path):
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        image.thumbnail((512, 512))

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)

    return base64.b64encode(buffer.getvalue()).decode("ascii")


def predict(image_path):
    image_base64 = prepare_image(image_path)

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": PROMPT,
                "images": [image_base64],
            }
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 600,
        },
        "keep_alive": "30m",
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    memory_before = ollama_memory_mb()
    start = time.perf_counter()

    with urllib.request.urlopen(request, timeout=240) as response:
        result = json.load(response)

    latency = time.perf_counter() - start
    memory_after = ollama_memory_mb()

    answer = result.get("message", {}).get("content", "").strip()

    try:
        parsed = json.loads(answer)
        valid_json = (
            isinstance(parsed, dict)
            and set(parsed.keys()) == {"damaged"}
            and isinstance(parsed["damaged"], bool)
        )
        prediction = parsed["damaged"] if valid_json else None
    except (json.JSONDecodeError, TypeError):
        valid_json = False
        prediction = None

    return {
        "prediction": prediction,
        "valid_json": valid_json,
        "latency_seconds": round(latency, 2),
        "ram_before_mb": memory_before,
        "ram_after_mb": memory_after,
        "generated_tokens": result.get("eval_count"),
        "done_reason": result.get("done_reason"),
        "raw_response": answer,
        "error": "",
    }


with LABELS_FILE.open("r", encoding="utf-8-sig", newline="") as file:
    labels = list(csv.DictReader(file))

print(f"Model: {MODEL}")
print(f"Images: {len(labels)}")

# Warm-up request is excluded from benchmark results.
print("\nWarming up model...")

try:
    predict(IMAGES_DIR / labels[0]["filename"])
    print("Warm-up completed.")
except Exception as error:
    print(f"Warm-up failed: {error}")
    raise SystemExit(1)

fieldnames = [
    "filename",
    "ground_truth",
    "prediction",
    "correct",
    "valid_json",
    "latency_seconds",
    "ram_before_mb",
    "ram_after_mb",
    "generated_tokens",
    "done_reason",
    "raw_response",
    "error",
]

results = []

with RESULTS_FILE.open("w", encoding="utf-8", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=fieldnames)
    writer.writeheader()

    for index, label in enumerate(labels, start=1):
        filename = label["filename"]
        ground_truth = label["damaged"].strip().lower() == "true"

        print(f"\n[{index}/30] Processing {filename}...")

        try:
            result = predict(IMAGES_DIR / filename)
        except Exception as error:
            result = {
                "prediction": None,
                "valid_json": False,
                "latency_seconds": None,
                "ram_before_mb": None,
                "ram_after_mb": None,
                "generated_tokens": None,
                "done_reason": None,
                "raw_response": "",
                "error": str(error),
            }

        correct = (
            result["valid_json"]
            and result["prediction"] == ground_truth
        )

        row = {
            "filename": filename,
            "ground_truth": ground_truth,
            "correct": correct,
            **result,
        }

        writer.writerow(row)
        file.flush()
        results.append(row)

        print(
            f"Expected: {ground_truth} | "
            f"Predicted: {result['prediction']} | "
            f"Correct: {correct} | "
            f"Latency: {result['latency_seconds']} s"
        )

correct_count = sum(row["correct"] for row in results)
valid_count = sum(row["valid_json"] for row in results)

latencies = [
    row["latency_seconds"]
    for row in results
    if row["latency_seconds"] is not None
]

print("\n========== BENCHMARK RESULTS ==========")
print(f"Model: {MODEL}")
print(f"Total images: {len(results)}")
print(f"Correct predictions: {correct_count}/{len(results)}")
print(f"Accuracy: {correct_count / len(results) * 100:.2f}%")
print(f"Valid JSON responses: {valid_count}/{len(results)}")

if latencies:
    print(f"Average latency: {sum(latencies) / len(latencies):.2f} s")

print(f"Results saved to: {RESULTS_FILE}")
