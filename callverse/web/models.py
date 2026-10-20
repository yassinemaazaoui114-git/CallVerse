"""Where the downloaded speech models live (Whisper for speech-to-text, Piper voices for text-to-speech).

Default: <repo>/models (git-ignored). The Docker image sets CALLVERSE_MODELS_DIR so the models are
downloaded once at build time (scripts/download_voice_models.py) and never at request time.
"""

import os
from pathlib import Path

from callverse.config import PROJECT_ROOT


def models_dir() -> Path:
    return Path(os.getenv("CALLVERSE_MODELS_DIR", PROJECT_ROOT / "models"))


def whisper_dir() -> Path:
    return models_dir() / "whisper"


def piper_dir() -> Path:
    return models_dir() / "piper"
