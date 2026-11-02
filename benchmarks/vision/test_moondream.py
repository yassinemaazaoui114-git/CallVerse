
import base64
import json
import urllib.request
from pathlib import Path

# Image located next to this script, inside images/
image_path = Path(__file__).parent / "images" / "test-damaged.jpg"

if not image_path.exists():
    raise FileNotFoundError(f"Image not found: {image_path}")

with open(image_path, "rb") as image_file:
    image_base64 = base64.b64encode(image_file.read()).decode("utf-8")

payload = {
    "model": "moondream:1.8b-v2-q4_0",
    "prompt": (
        "Look at this image. Is the packaging visibly damaged? "
        "Answer DAMAGED or INTACT, followed by one short reason."
    ),
    "images": [image_base64],
    "stream": False,
    "options": {
        "num_predict": 80,
        "temperature": 0
    }
}

request = urllib.request.Request(
    "http://127.0.0.1:11434/api/generate",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST"
)

print("Analyzing image with Moondream...")

try:
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)

    print("\nMODEL RESPONSE:")
    print(result.get("response", ""))
    print("\nFULL OLLAMA RESPONSE:")
    print(json.dumps(result, indent=2))

    print("\nINFERENCE TIME:")
    print(round(result.get("eval_duration", 0) / 1e9, 2), "seconds")

except Exception as error:
    print("Error:", error)
