
import base64
import json
import time
import urllib.request
from pathlib import Path

image_path = Path(__file__).parent / "images" / "test-damaged.jpg"

if not image_path.exists():
    raise FileNotFoundError(f"Image not found: {image_path}")

image_base64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

payload = {
    "model": "moondream:1.8b-v2-q4_0",
    "messages": [
        {
            "role": "user",
            "content": "Look carefully at the cardboard package in this image. Is it damaged or intact? Explain your answer in one short sentence.",
            "images": [image_base64]
        }
    ],
    "stream": False,
    "options": {
        "num_predict": 80,
        "temperature": 0
    }
}

request = urllib.request.Request(
    "http://127.0.0.1:11434/api/chat",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST"
)

print("Testing Moondream using Ollama Chat API...")

start = time.perf_counter()

try:
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)

    elapsed = time.perf_counter() - start

    print("\nMODEL RESPONSE:")
    print(repr(result.get("message", {}).get("content", "")))

    print("\nDIAGNOSTICS:")
    print("Done reason:", result.get("done_reason"))
    print("Generated tokens:", result.get("eval_count"))
    print("Total duration:", round(elapsed, 2), "seconds")

except Exception as error:
    print("Error:", error)
