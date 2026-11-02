"""Photo check for the customer website (Molka's /api/turn/image endpoint).

First version (V01): a local Ollama model answered {"damaged": true/false}. Now the channel uses the shared photo
model of CallVerse (callverse/vision: Qwen3-VL-2B + the QLoRA adapter, base model as fallback), so the website and
the ShopNova / Atlas apps give the same answer for the same photo. The endpoint and its error codes stay the same;
the answer now carries the full visual evidence (object, issue_type, description, confidence) and keeps "damaged"
for the old clients. It is advisory, unverified evidence: it never authorises a refund or any decision.
"""

from callverse.vision import model as vision_model
from callverse.vision.model import MAX_IMAGE_BYTES, VisionError  # noqa: F401  (same names as before for app.py)


def analyze_image(data: bytes, model: str | None = None) -> dict:
    """Check one uploaded photo. Raises VisionError (bad file -> 400 codes, no model -> "model_unavailable").
    model: kept for compatibility with V01 callers; the backend comes from config.yaml vision.backends."""
    result = vision_model.analyze(data)
    a = result["assessment"]
    return {
        "status": "success",
        "damaged": a["visible_damage"] is True,          # V01 field
        "assessment": a,
        "model": result["backend"],
        "adapter": result["adapter"],
        "valid_output": result["valid_output"],
        "latency_seconds": result["latency_s"],
        "requires_review": True,                          # always: model output, never verified by a human yet
    }
