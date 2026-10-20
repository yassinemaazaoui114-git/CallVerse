"""Download the speech models of config.yaml once, so the website never downloads at request time.

Usage:  python -m scripts.download_voice_models
- Piper voices (voice.tts.voices) from the official rhasspy/piper-voices repository on Hugging Face.
- The faster-whisper model (voice.stt.faster_whisper.model).
Files go to CALLVERSE_MODELS_DIR (default: <repo>/models, git-ignored). Already downloaded files are skipped.
"""

import sys
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


def main() -> None:
    cfg = load_config()["voice"]
    piper_dir().mkdir(parents=True, exist_ok=True)
    for voice in cfg["tts"]["voices"].values():
        for ext in ("onnx", "onnx.json"):
            target = piper_dir() / f"{voice}.{ext}"
            if target.exists():
                continue
            print(f"downloading {target.name}")
            urllib.request.urlretrieve(piper_url(voice, ext), target)

    from faster_whisper import WhisperModel
    model = cfg["stt"]["faster_whisper"]["model"]
    print(f"faster-whisper model '{model}'")
    WhisperModel(model, device="cpu", compute_type=cfg["stt"]["faster_whisper"]["compute_type"],
                 download_root=str(whisper_dir()))
    print(f"models ready in {piper_dir().parent}")


if __name__ == "__main__":
    main()
