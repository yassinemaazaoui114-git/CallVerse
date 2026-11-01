
import csv
import gc
import re
import time
from pathlib import Path

from faster_whisper import WhisperModel
from jiwer import wer

BASE = Path(__file__).resolve().parent
AUDIO_DIR = BASE / "audio_16k"
RESULTS_DIR = BASE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

MODELS = ["tiny", "base", "small"]


def normalize_text(text):
    """Normalize case and punctuation for WER comparison."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


with open(BASE / "references.csv", encoding="utf-8-sig", newline="") as f:
    references = list(csv.DictReader(f))

results = []

for model_name in MODELS:
    print(f"\n{'=' * 50}")
    print(f"Testing Whisper {model_name} (CPU, INT8)")
    print(f"{'=' * 50}")

    load_start = time.perf_counter()

    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        download_root=str(BASE.parent.parent / "models" / "whisper"),
    )

    load_seconds = time.perf_counter() - load_start
    print(f"Model loading time: {load_seconds:.2f}s")

    for row in references:
        audio_path = AUDIO_DIR / row["filename"]

        start = time.perf_counter()

        segments, info = model.transcribe(
            str(audio_path),
            language="en",
            beam_size=5,
        )

        # Transcription is lazy: materialize segments before
        # stopping the timer.
        prediction = " ".join(
            segment.text.strip() for segment in segments
        )

        latency = time.perf_counter() - start

        reference = row["reference"]

        score = wer(
            normalize_text(reference),
            normalize_text(prediction),
        )

        result = {
            "model": model_name,
            "filename": row["filename"],
            "category": row["category"],
            "reference": reference,
            "prediction": prediction,
            "expected_number": row["expected_number"],
            "wer": round(score, 4),
            "latency_seconds": round(latency, 3),
        }

        results.append(result)

        print(
            f"{row['filename']}: "
            f"WER={score:.3f} | "
            f"Time={latency:.2f}s"
        )
        print(f"  Predicted: {prediction}")

    # Release the model before loading the next one.
    del model
    gc.collect()

output_path = RESULTS_DIR / "stt_results.csv"

with open(output_path, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print(f"\nResults saved to: {output_path}")
