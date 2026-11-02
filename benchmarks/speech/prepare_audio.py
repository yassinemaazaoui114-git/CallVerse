
from pathlib import Path
import wave
import numpy as np
from scipy.signal import resample_poly
from math import gcd

BASE = Path(__file__).resolve().parent
INPUT = BASE / "audio"
OUTPUT = BASE / "audio_16k"
OUTPUT.mkdir(exist_ok=True)

for i in range(1, 11):
    source = INPUT / f"audio-{i}.wav"

    with wave.open(str(source), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise ValueError(f"{source.name}: expected 16-bit PCM")

    audio = np.frombuffer(frames, dtype=np.int16).copy()
    audio = audio.reshape(-1, channels).astype(np.float32)

    # Convert stereo to mono by averaging channels.
    mono = audio.mean(axis=1)

    # Resample without changing playback duration.
    if sample_rate != 16000:
        divisor = gcd(sample_rate, 16000)
        mono = resample_poly(
            mono,
            16000 // divisor,
            sample_rate // divisor,
        )

    # Convert back to 16-bit PCM.
    mono = np.clip(np.rint(mono), -32768, 32767)
    mono = mono.astype(np.int16)

    destination = OUTPUT / f"audio-{i}.wav"

    with wave.open(str(destination), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(mono.tobytes())

    print(f"{source.name} -> {destination.name} | 16000 Hz | mono")

print("\nAll 10 recordings standardized successfully.")
