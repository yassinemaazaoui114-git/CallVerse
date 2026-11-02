
import csv
import re
from collections import defaultdict
from pathlib import Path

from jiwer import wer

BASE = Path(__file__).resolve().parent
INPUT = BASE / "results" / "number_accuracy.csv"
OUTPUT = BASE / "results" / "wer_comparison.csv"

# Exact number phrases in our 10 reference transcripts.
REFERENCE_NUMBERS = {
    "audio-1.wav": "four five one two",
    "audio-2.wav": "eight seven three nine six",
    "audio-3.wav": "one zero five two eight",
    "audio-4.wav": "six four zero one seven",
    "audio-5.wav": "nine two three five zero",
    "audio-6.wav": "forty-nine euros and ninety-nine cents",
    "audio-7.wav": "one hundred and twenty euros",
    "audio-8.wav": "seventy-five euros and fifty cents",
    "audio-9.wav": "two hundred and thirty-four euros",
    "audio-10.wav": "nineteen euros and ninety cents",
}


def normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def mask_reference(row):
    text = row["reference"]
    phrase = REFERENCE_NUMBERS[row["filename"]]

    if text.lower().count(phrase.lower()) != 1:
        raise ValueError(
            f"Reference phrase not found exactly once: "
            f"{row['filename']}"
        )

    return re.sub(
        re.escape(phrase),
        "NUM",
        text,
        count=1,
        flags=re.IGNORECASE,
    )


def mask_prediction(row):
    text = row["prediction"]

    if row["category"] == "order":
        pattern = (
            r"(\border(?:\s+number)?(?:\s+is)?\s+)"
            r"(\d(?:[\s,\-]*\d){3,5})"
        )
    else:
        pattern = (
            r"\b\d+(?:[.,]\d+)?\s+euros?"
            r"(?:\s*,?\s*and\s+\d+\s+cents?)?"
        )

    if row["category"] == "order":
        result, count = re.subn(
            pattern,
            lambda m: m.group(1) + "NUM",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        result, count = re.subn(
            pattern,
            "NUM",
            text,
            count=1,
            flags=re.IGNORECASE,
        )

    if count != 1:
        raise ValueError(
            f"Could not mask prediction: "
            f"{row['model']} {row['filename']}"
        )

    return result


with open(INPUT, encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

summary = defaultdict(list)

for row in rows:
    # Never hide a wrong numerical value as correct.
    if int(row["number_correct"]) != 1:
        raise ValueError(
            "Incorrect number detected. Review the prediction "
            "before calculating number-masked WER."
        )

    reference = normalize(mask_reference(row))
    prediction = normalize(mask_prediction(row))

    score = wer(reference, prediction)

    row["normalized_wer"] = round(score, 4)
    summary[row["model"]].append(score)

    print(
        f"{row['model']:5s} {row['filename']:12s} "
        f"WER={score:.3f}"
    )

    if score > 0:
        print(f"  REF:  {reference}")
        print(f"  PRED: {prediction}")

with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

print("\nAVERAGE NUMBER-MASKED WER")
print("-" * 40)

for model in ["tiny", "base", "small"]:
    scores = summary[model]
    print(f"{model:5s}: {sum(scores) / len(scores):.2%}")

print(f"\nResults saved to: {OUTPUT}")
