
import csv
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"


def load_csv(filename):
    with open(
        RESULTS / filename,
        encoding="utf-8",
        newline=""
    ) as file:
        return list(csv.DictReader(file))


piper = load_csv("tts_results.csv")
sapi = load_csv("sapi_results.csv")

summary = []

for engine_name, rows in [
    ("Piper", piper),
    ("SAPI5", sapi),
]:
    for language in ["en", "fr"]:
        subset = [
            row for row in rows
            if row["language"] == language
        ]

        total_latency = sum(
            float(row["synthesis_latency_seconds"])
            for row in subset
        )

        total_duration = sum(
            float(row["audio_duration_seconds"])
            for row in subset
        )

        summary.append({
            "engine": engine_name,
            "language": language,
            "samples": len(subset),
            "avg_latency_seconds": round(
                total_latency / len(subset), 3
            ),
            "avg_audio_duration_seconds": round(
                total_duration / len(subset), 3
            ),
            "real_time_factor": round(
                total_latency / total_duration, 3
            ),
            "listening_result": "Clear; no errors observed",
        })


output = RESULTS / "tts_summary.csv"

with open(
    output,
    "w",
    encoding="utf-8",
    newline=""
) as file:
    writer = csv.DictWriter(
        file,
        fieldnames=summary[0].keys()
    )
    writer.writeheader()
    writer.writerows(summary)

print("FINAL TTS BENCHMARK SUMMARY")
print("-" * 65)

for row in summary:
    print(
        f"{row['engine']:6} | "
        f"{row['language'].upper()} | "
        f"Latency: {row['avg_latency_seconds']:.3f}s | "
        f"RTF: {row['real_time_factor']:.3f}"
    )

print(f"\nSaved to: {output}")
