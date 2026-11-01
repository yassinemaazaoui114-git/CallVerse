
import csv
import time
from pathlib import Path

from callverse.web.tts import synthesize

BASE = Path(__file__).resolve().parent
OUTPUT_DIR = BASE / "tts_audio"
RESULTS_DIR = BASE / "results"

OUTPUT_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

SAMPLES = [
    ("en", "en-1", "Your order 4512 has been shipped."),
    ("en", "en-2", "Your refund of 49 euros and 99 cents has been approved."),
    ("en", "en-3", "Order 87396 will arrive tomorrow."),
    ("en", "en-4", "The total amount is 120 euros."),
    ("en", "en-5", "We have cancelled order 10528."),

    ("fr", "fr-1", "Votre commande 4512 a été expédiée."),
    ("fr", "fr-2", "Votre remboursement de 49 euros et 99 centimes a été approuvé."),
    ("fr", "fr-3", "La commande 87396 arrivera demain."),
    ("fr", "fr-4", "Le montant total est de 120 euros."),
    ("fr", "fr-5", "Nous avons annulé la commande 10528."),
]

# Warm up both voices so measured calls exclude initial loading.
print("Warming up TTS voices...")
synthesize("Hello.", language="en")
synthesize("Bonjour.", language="fr")

results = []

for language, sample_id, text in SAMPLES:
    result = synthesize(text, language=language)

    output_path = OUTPUT_DIR / f"{sample_id}.wav"
    output_path.write_bytes(result["wav"])

    results.append({
        "sample_id": sample_id,
        "language": language,
        "voice": result["voice"],
        "text": text,
        "spoken_text": result["spoken_text"],
        "audio_duration_seconds": result["seconds"],
        "synthesis_latency_seconds": result["synthesis_seconds"],
    })

    print(
        f"{sample_id}: "
        f"latency={result['synthesis_seconds']:.3f}s | "
        f"audio={result['seconds']:.2f}s"
    )

output_csv = RESULTS_DIR / "tts_results.csv"

with open(output_csv, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print(f"\nSaved results to: {output_csv}")
print(f"Saved audio to: {OUTPUT_DIR}")
