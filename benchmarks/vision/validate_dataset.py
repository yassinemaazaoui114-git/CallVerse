
import csv
from pathlib import Path

# Folder containing this script
BASE_DIR = Path(__file__).resolve().parent

LABELS_FILE = BASE_DIR / "labels.csv"
IMAGES_DIR = BASE_DIR / "images"

with LABELS_FILE.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

damaged = 0
intact = 0
errors = []

for row in rows:
    filename = row["filename"].strip()
    label = row["damaged"].strip().lower()
    image_path = IMAGES_DIR / filename

    if not image_path.is_file():
        errors.append(f"Missing image: {filename}")

    if label == "true":
        damaged += 1
    elif label == "false":
        intact += 1
    else:
        errors.append(f"Invalid label: {filename} -> {label}")

print(f"Total images: {len(rows)}")
print(f"Damaged images: {damaged}")
print(f"Intact images: {intact}")

if len(rows) != 30:
    errors.append("Expected exactly 30 images")

if damaged != 15 or intact != 15:
    errors.append("Expected 15 damaged and 15 intact images")

if errors:
    print("\nVALIDATION FAILED:")
    for error in errors:
        print(f" - {error}")
else:
    print("\nDATASET VALIDATION PASSED!")
