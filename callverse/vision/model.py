"""The photo model: Qwen3-VL-2B-Instruct + the CallVerse QLoRA adapter (published on Hugging Face).

Why this model? Benchmarked on 25 held-out real photos (Kaggle T4, 2026-11-01, evaluation/ in the adapter repo):
  fine-tuned adapter  accuracy 0.84 [0.68-0.96], macro-F1 0.79, damage recall 1.00, valid JSON 100 %
  base + same prompt  accuracy 0.64 [0.44-0.80], macro-F1 0.61, damage recall 1.00, valid JSON 100 %
  paired difference +0.20 [+0.08, +0.36] -> the adapter is used; the base model is the fallback.

Fallback chain (config.yaml vision.backends): "qlora" (base + adapter) -> "base" (base model alone, same prompt).
If both fail the caller gets VisionError and the channel treats the photo as "could not be checked" (a human looks).
The model is loaded once, on first use (about 4.5 GB download the first time, cached by Hugging Face).
GPU: 4-bit NF4 when bitsandbytes is installed (as in training), else 16-bit. CPU: float32 (slow: ~15-30 s / photo).

Facts never come from here: the answer is VISUAL EVIDENCE, unverified, for the router and the humans.
"""
import io
import threading
import time

from PIL import Image, UnidentifiedImageError

from callverse import trace
from callverse.config import load_config
from callverse.vision import schema

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
FORMATS = ("JPEG", "PNG", "WEBP")


class VisionError(Exception):
    """A photo that cannot be read, or a model that cannot run. code = short machine-readable reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def cfg() -> dict:
    return load_config()["vision"]


# T34: the photo packages (requirements-vision.txt) are optional. Without them the photo check is "not available".
VISION_PACKAGES = ("torch", "transformers", "peft", "accelerate", "torchvision")


def missing_packages() -> list[str]:
    """The photo packages that are not installed (empty list = the photo check can load)."""
    import importlib.util
    return [name for name in VISION_PACKAGES if importlib.util.find_spec(name) is None]


def available() -> bool:
    """True only when vision is enabled in config.yaml AND its packages import (or a test fake is set). Never loads
    the model."""
    return bool(cfg().get("enabled", True)) and (_override is not None or not missing_packages())


def load_image(data: bytes) -> Image.Image:
    """Check the upload and return an RGB image, at most cfg max_side pixels on its longest side."""
    if not data:
        raise VisionError("empty_image", "The image is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise VisionError("image_too_large", "The image exceeds the 5 MB limit.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in FORMATS:
                raise VisionError("unsupported_image", "Only JPEG, PNG and WebP images are supported.")
            if im.width * im.height > MAX_IMAGE_PIXELS:
                raise VisionError("image_too_large", "The image dimensions are too large.")
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise VisionError("invalid_image", "The uploaded file is not a valid image.") from e
    side = cfg().get("max_side", 1024)
    im.thumbnail((side, side))
    return im


class QwenVL:
    """One loaded model (base, or base + adapter). generate(image) -> raw text."""

    def __init__(self, with_adapter: bool):
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

        c = cfg()
        self.name = "qlora" if with_adapter else "base"
        self.processor = AutoProcessor.from_pretrained(c["base_model"], revision=c["base_revision"])
        self.processor.image_processor.size = {"longest_edge": c["max_pixels"], "shortest_edge": c["min_pixels"]}
        kwargs = {"revision": c["base_revision"]}
        if torch.cuda.is_available():
            self.dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            kwargs["device_map"] = {"": 0}
            kwargs["dtype"] = self.dtype
            try:
                from transformers import BitsAndBytesConfig
                import bitsandbytes  # noqa: F401  (only to know it is installed)
                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=self.dtype, llm_int8_skip_modules=["visual", "lm_head"])
                self.quant = "nf4"
            except ImportError:
                self.quant = "none"
        else:
            self.dtype, self.quant = torch.float32, "none"
            kwargs["dtype"] = torch.float32
        model = Qwen3VLForConditionalGeneration.from_pretrained(c["base_model"], **kwargs)
        if with_adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, c.get("adapter_path") or c["adapter_repo"],
                                              revision=None if c.get("adapter_path") else c["adapter_revision"])
        self.model = model.eval()
        self.adapter = (c.get("adapter_path") or f"{c['adapter_repo']}@{c['adapter_revision'][:7]}") if with_adapter else None

    def generate(self, image: Image.Image) -> str:
        import torch
        msgs = [{"role": "user", "content": [{"type": "image", "image": image},
                                             {"type": "text", "text": schema.PROMPT}]}]
        text = self.processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(text=[text], images=[image], return_tensors="pt").to(self.model.device)
        with torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=cfg()["max_new_tokens"], do_sample=False,
                                      temperature=None, top_p=None, top_k=None)
        return self.processor.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True)


_lock = threading.Lock()          # one inference at a time (one GPU / CPU, memory-safe)
_loaded: dict = {}                # backend name -> QwenVL
_failed: dict = {}                # backend name -> load error (not retried in this process)
_override = None                  # tests: a fake backend


def set_backend_for_tests(fake) -> None:
    """fake(image) -> (raw_text, backend_name). None = back to the real models."""
    global _override
    _override = fake


def _backend(name: str):
    if name in _loaded:
        return _loaded[name]
    if name in _failed:
        raise VisionError("model_unavailable", _failed[name])
    try:
        _loaded[name] = QwenVL(with_adapter=(name == "qlora"))
        trace.log("vision_model_loaded", "vision", {"backend": name, "adapter": _loaded[name].adapter,
                                                     "quant": _loaded[name].quant})
        return _loaded[name]
    except Exception as e:   # missing adapter, no network, missing library, out of memory...
        _failed[name] = f"{type(e).__name__}: {str(e)[:200]}"
        trace.log("vision_model_failed", "vision", {"backend": name, "error": _failed[name]})
        raise VisionError("model_unavailable", _failed[name]) from e


def analyze(data: bytes) -> dict:
    """Check one photo. Returns {"assessment", "backend", "adapter", "valid_output", "latency_s"}.

    Invalid model text -> assessment "unclear" (valid_output False): never guessed from broken output.
    Raises VisionError for a bad file, or when no backend can run.
    """
    image = load_image(data)
    errors = []
    with _lock:
        t0 = time.perf_counter()
        if _override is not None:
            raw, name, adapter = *_override(image), None
        else:
            raw = name = adapter = None
            for candidate in cfg()["backends"]:
                try:
                    model = _backend(candidate)
                    raw, name, adapter = model.generate(image), candidate, model.adapter
                    break
                except VisionError as e:
                    errors.append(f"{candidate}: {e.message}")
                except Exception as e:   # the model loaded but failed on this photo
                    errors.append(f"{candidate}: {type(e).__name__}: {str(e)[:200]}")
            if raw is None:
                trace.log("vision_unavailable", "vision", {"errors": errors})
                raise VisionError("model_unavailable", "; ".join(errors) or "no vision backend configured")
        latency = round(time.perf_counter() - t0, 3)
    assessment, why = schema.parse_output(raw)
    if assessment is None:
        assessment = schema.unclear("The photo check gave an invalid answer; a colleague needs to look at it.")
    out = {"assessment": assessment, "backend": name, "adapter": adapter, "valid_output": why == "ok",
           "parse": why, "fallback_used": bool(errors) or name == "base", "errors": errors, "latency_s": latency}
    trace.log("vision_assessment", "vision", {**out, "raw": raw[:500]})
    return out
