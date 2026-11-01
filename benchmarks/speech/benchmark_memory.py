
import csv
import gc
import os
import time
from pathlib import Path

import psutil
from faster_whisper import WhisperModel

BASE = Path(__file__).resolve().parent
AUDIO = BASE / "audio_16k" / "audio-1.wav"
OUTPUT = BASE / "results" / "memory_results.csv"

process = psutil.Process(os.getpid())
results = []

def ram_mb():
    return process.memory_info().rss / (1024 ** 2)

for name in ["tiny", "base", "small"]:
    gc.collect()
    before = ram_mb()

    start = time.perf_counter()
    model = WhisperModel(
        name,
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        download_root=str(BASE.parent.parent / "models" / "whisper"),
    )
    load_time = time.perf_counter() - start
    after_load = ram_mb()

    segments, _ = model.transcribe(
        str(AUDIO),
        language="en",
        beam_size=5,
    )
    list(segments)
    after_inference = ram_mb()

    results.append({
        "model": name,
        "baseline_ram_mb": round(before, 1),
        "ram_after_load_mb": round(after_load, 1),
        "ram_after_inference_mb": round(after_inference, 1),
        "load_time_seconds": round(load_time, 2),
    })

    print(
        f"{name}: baseline={before:.1f} MB | "
        f"loaded={after_load:.1f} MB | "
        f"after inference={after_inference:.1f} MB"
    )

    del model
    gc.collect()

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print(f"\nSaved to: {OUTPUT}")
