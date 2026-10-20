"""Download the models of config.yaml once, so the website never downloads at request time.

Usage:  python -m scripts.download_voice_models
- Piper voices (web_channel.tts.voices) from the official rhasspy/piper-voices repository on Hugging Face.
- The faster-whisper model (web_channel.stt.faster_whisper.model).
- The Intake models (M3 embeddings, M4 emotion + sentiment), into the Hugging Face cache (HF_HOME),
  plus Intake's example-vector cache.
Speech files go to CALLVERSE_MODELS_DIR (default: <repo>/models, git-ignored). Existing files are skipped.
"""

import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse.config import load_config  # noqa: E402
from callverse.web.models import piper_dir, whisper_dir  # noqa: E402

PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def piper_url(voice: str, ext: str) -> str:
    """'en_GB-cori-medium' -> .../en/en_GB/cori/medium/en_GB-cori-medium.onnx"""
    locale, name, quality = voice.split("-")
    return f"{PIPER_BASE}/{locale.split('_')[0]}/{locale}/{name}/{quality}/{voice}.{ext}"


def download(url: str, target: Path, attempts: int = 4) -> None:
    """Download to <target>.part, then rename: a cut-off download never looks like a finished file."""
    part = target.with_name(target.name + ".part")
    for attempt in range(1, attempts + 1):
        try:
            urllib.request.urlretrieve(url, part)
            part.replace(target)
            return
        except OSError as e:          # network errors, incomplete downloads (ContentTooShortError)
            part.unlink(missing_ok=True)
            if attempt == attempts:
                raise
            print(f"  retry {attempt}/{attempts - 1} after: {e}")
            time.sleep(2 * attempt)


def main() -> None:
    cfg = load_config()["web_channel"]
    piper_dir().mkdir(parents=True, exist_ok=True)
    for voice in cfg["tts"]["voices"].values():
        for ext in ("onnx", "onnx.json"):
            target = piper_dir() / f"{voice}.{ext}"
            if target.exists():
                continue
            print(f"downloading {target.name}")
            download(piper_url(voice, ext), target)

    from faster_whisper import WhisperModel
    model = cfg["stt"]["faster_whisper"]["model"]
    print(f"faster-whisper model '{model}'")
    WhisperModel(model, device="cpu", compute_type=cfg["stt"]["faster_whisper"]["compute_type"],
                 download_root=str(whisper_dir()))
    print("Intake models (M3 + M4)")
    from callverse.intake import intake
    intake.load_models()
    print(f"models ready in {piper_dir().parent}")


if __name__ == "__main__":
    main()
