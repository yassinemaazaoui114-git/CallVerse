
"""Local product-damage detection using Ollama vision models."""

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
import threading

from PIL import Image, UnidentifiedImageError


OLLAMA_URL = os.getenv(
    "CALLVERSE_OLLAMA_URL",
    "http://127.0.0.1:11434/api/chat",
)

DEFAULT_MODEL = os.getenv(
    "CALLVERSE_VISION_MODEL",
    "qwen3-vl:2b",
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
VISION_SLOTS = threading.BoundedSemaphore(1)

PROMPT = (
    "Look carefully at this product image. "
    "Is there clearly visible physical damage such as cracks, "
    "breakage, tears, or missing parts? "
    "Normal product features are NOT damage. "
    "If no clear damage is visible, answer false. "
    'Return only JSON: {"damaged": true} or {"damaged": false}.'
)


class VisionError(Exception):
    """A validation or inference failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def prepare_image(data: bytes) -> str:
    """Validate an uploaded image and return base64-encoded JPEG."""

    if not data:
        raise VisionError("empty_image", "The image is empty.")

    if len(data) > MAX_IMAGE_BYTES:
        raise VisionError(
            "image_too_large",
            "The image exceeds the 5 MB limit.",
        )

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP"):
                raise VisionError(
                    "unsupported_image",
                    "Only JPEG, PNG and WebP images are supported.",
                )

            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise VisionError(
                    "image_too_large",
                    "The image dimensions are too large.",
                )

            image = image.convert("RGB")
            image.thumbnail((512, 512))

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)

    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise VisionError(
            "invalid_image",
            "The uploaded file is not a valid image.",
        ) from exc

    return base64.b64encode(buffer.getvalue()).decode("ascii")


def analyze_image(
    data: bytes,
    model: str | None = None,
) -> dict:
    """Analyze a product image and return a structured result.

    This is an advisory classification, not a verified damage claim.
    """

    selected_model = model or DEFAULT_MODEL
    encoded_image = prepare_image(data)

    payload = {
        "model": selected_model,
        "messages": [
            {
                "role": "user",
                "content": PROMPT,
                "images": [encoded_image],
            }
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 600,
        },
        "keep_alive": "30m",
    }

    # Match the JSON enforcement used in the Moondream benchmark.
    if selected_model.startswith("moondream"):
        payload["format"] = "json"

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()

    try:
        with VISION_SLOTS:
            with urllib.request.urlopen(request, timeout=240) as response:
                result = json.load(response)

    except urllib.error.HTTPError as exc:
        raise VisionError(
            "ollama_http_error",
            f"Ollama returned HTTP {exc.code}.",
        ) from exc

    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VisionError(
            "ollama_unavailable",
            "The local vision model is unavailable.",
        ) from exc

    latency = round(time.perf_counter() - start, 3)

    try:
        raw = result["message"]["content"]
        parsed = json.loads(raw)

        if (
            not isinstance(parsed, dict)
            or set(parsed.keys()) != {"damaged"}
            or type(parsed["damaged"]) is not bool
        ):
            raise ValueError("Unexpected JSON schema")

    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VisionError(
            "invalid_model_output",
            "The vision model did not return a valid damage classification.",
        ) from exc

    return {
        "status": "success",
        "damaged": parsed["damaged"],
        "model": selected_model,
        "latency_seconds": latency,
        "requires_review": True,
    }
