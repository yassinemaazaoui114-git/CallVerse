
import csv
import time
import wave
from pathlib import Path

import pyttsx3

from callverse.web.tts import speech_text


# --------------------------------------------------
# 1. Paths
# --------------------------------------------------

BASE = Path(__file__).resolve().parent
RESULTS_DIR = BASE / "results"
AUDIO_DIR = BASE / "tts_audio_sapi"

RESULTS_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)


# --------------------------------------------------
# 2. Load the same test sentences used for Piper
# --------------------------------------------------

with open(
    RESULTS_DIR / "tts_results.csv",
    encoding="utf-8",
    newline=""
) as file:
    samples = list(csv.DictReader(file))


# --------------------------------------------------
# 3. Identify available Windows SAPI5 voices
# --------------------------------------------------

VOICE_NAMES = {
    "en": "Zira",
    "fr": "Hortense",
}

discovery_engine = pyttsx3.init(driverName="sapi5")
voices = discovery_engine.getProperty("voices")

voice_ids = {}

for language, name in VOICE_NAMES.items():
    match = next(
        (
            voice
            for voice in voices
            if name.lower() in voice.name.lower()
        ),
        None
    )

    if match is None:
        raise RuntimeError(
            f"Missing SAPI5 voice: {name}"
        )

    voice_ids[language] = match.id

discovery_engine.stop()
del discovery_engine


# --------------------------------------------------
# 4. Benchmark SAPI5 synthesis
# --------------------------------------------------

results = []

print("Starting SAPI5 benchmark...\n", flush=True)

for sample in samples:

    language = sample["language"]
    sample_id = sample["sample_id"]
    text = sample["text"]

    # Apply the same number preprocessing as Piper.
    spoken = speech_text(text)

    output_path = AUDIO_DIR / f"{sample_id}.wav"

    # Initialize a fresh engine for each sentence.
    engine = pyttsx3.init(driverName="sapi5")

    engine.setProperty("rate", 170)
    engine.setProperty("voice", voice_ids[language])

    print(
        f"Generating {sample_id}...",
        flush=True
    )

    start = time.perf_counter()

    engine.save_to_file(
        spoken,
        str(output_path)
    )

    engine.runAndWait()

    latency = time.perf_counter() - start

    engine.stop()
    del engine

    if not output_path.exists():
        raise RuntimeError(
            f"Audio not generated: {output_path}"
        )

    with wave.open(str(output_path), "rb") as wav:
        duration = (
            wav.getnframes() / wav.getframerate()
        )

    results.append({
        "sample_id": sample_id,
        "language": language,
        "voice": VOICE_NAMES[language],
        "text": text,
        "spoken_text": spoken,
        "audio_duration_seconds": round(duration, 2),
        "synthesis_latency_seconds": round(latency, 3),
    })

    print(
        f"{sample_id}: "
        f"latency={latency:.3f}s | "
        f"audio={duration:.2f}s",
        flush=True
    )


# --------------------------------------------------
# 5. Save benchmark results
# --------------------------------------------------

output_csv = RESULTS_DIR / "sapi_results.csv"

with open(
    output_csv,
    "w",
    encoding="utf-8",
    newline=""
) as file:

    writer = csv.DictWriter(
        file,
        fieldnames=results[0].keys()
    )

    writer.writeheader()
    writer.writerows(results)


# --------------------------------------------------
# 6. Summary
# --------------------------------------------------

print("\nSAPI5 benchmark completed!")

for language in ["en", "fr"]:

    subset = [
        row for row in results
        if row["language"] == language
    ]

    avg_latency = sum(
        row["synthesis_latency_seconds"]
        for row in subset
    ) / len(subset)

    print(
        f"{language.upper()} average latency: "
        f"{avg_latency:.3f}s"
    )

print(f"\nResults saved to: {output_csv}")
print(f"Audio saved to: {AUDIO_DIR}")
