
import csv
import re
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent
INPUT = BASE / "results" / "stt_results.csv"
OUTPUT = BASE / "results" / "number_accuracy.csv"



def extract_order(text):
    # Supports:
    # "order 4512"
    # "order number 4512"
    # "order number is 10528"
    # "order 1, 0, 5, 2, 8"

    match = re.search(
        r"\border(?:\s+number)?(?:\s+is)?\s+((?:\d[\s,\-]*){4,6})",
        text.lower(),
    )

    if not match:
        return None

    digits = re.sub(r"\D", "", match.group(1))
    return digits if 4 <= len(digits) <= 6 else None



def extract_amount(text):
    text = text.lower()

    euros = re.search(r"\b(\d+)\s+euros?\b", text)
    cents = re.search(r"\b(\d+)\s+cents?\b", text)

    if not euros:
        return None

    euro_value = int(euros.group(1))
    cent_value = int(cents.group(1)) if cents else 0

    if cent_value >= 100:
        return None

    return Decimal(euro_value) + Decimal(cent_value) / 100


with open(INPUT, encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

for row in rows:
    prediction = row["prediction"]

    if row["category"] == "order":
        extracted = extract_order(prediction)
        expected = row["expected_number"].strip()
        correct = extracted == expected
    else:
        extracted = extract_amount(prediction)
        expected = Decimal(row["expected_number"])
        correct = extracted == expected

    row["extracted_number"] = str(extracted)
    row["number_correct"] = int(correct)

with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

print("\nEXACT NUMBER ACCURACY")
print("-" * 45)

for model in ["tiny", "base", "small"]:
    subset = [r for r in rows if r["model"] == model]
    correct = sum(int(r["number_correct"]) for r in subset)

    print(f"{model:6s}: {correct}/{len(subset)} = {correct / len(subset):.0%}")

    for row in subset:
        if not int(row["number_correct"]):
            print(
                f"  FAILED: {row['filename']} "
                f"expected={row['expected_number']} "
                f"extracted={row['extracted_number']}"
            )

print(f"\nDetailed results saved to: {OUTPUT}")
