"""Voice demo (task V01): a recorded question in, a spoken answer out.

Usage (from the repo root):
    python -m scripts.run_voice --audio samples/voice/clip1.wav            -> out/reply.wav
    python -m scripts.run_voice --audio clip.wav --out out/answer.wav

Steps: transcribe (Groq Whisper) -> respond() = the existing pipeline (Intake -> Router -> Agent A, or the handover
to B), see callverse/pipeline.py -> speak the answer (pyttsx3) into a .wav file. Every step is traced.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse import trace  # noqa: E402
from callverse.channels import voice  # noqa: E402
from callverse.data.seed import seed  # noqa: E402


def respond(text: str, chat_fn=None) -> dict:
    """The ONE place where the voice channel calls CallVerse: today the T04 pipeline (Intake -> Router -> Agent A).
    When the full chain (Coordinator, SLM) is in the pipeline, nothing changes here."""
    from callverse import pipeline
    return pipeline.handle(text, chat_fn=chat_fn)


def run(audio: Path, out: Path, chat_fn=None, stt_client=None, tts_engine=None) -> dict:
    heard = voice.transcribe(audio, client=stt_client)
    result = respond(heard["text"], chat_fn=chat_fn)
    spoken = voice.speak(result["answer"], out, engine=tts_engine)
    return {"heard": heard, "result": result, "spoken": spoken}


def main() -> None:
    parser = argparse.ArgumentParser(description="CallVerse voice demo: audio question -> spoken answer.")
    parser.add_argument("--audio", required=True, type=Path, help="recording of the question (.wav)")
    parser.add_argument("--out", default=Path("out/reply.wav"), type=Path, help="where to write the spoken answer")
    args = parser.parse_args()

    seed()                            # fresh placeholder ShopNova data, so every demo starts the same
    trace_path = trace.start_run()
    try:
        r = run(args.audio, args.out)
    except voice.VoiceError as e:
        sys.exit(f"Voice error: {e}")

    heard, t, route = r["heard"], r["result"]["ticket"], r["result"]["route"]
    print(f"Heard      : {heard['text']}")
    print(f"             language {heard['language']}, {heard['audio_seconds']} s of audio, STT {heard['seconds']} s")
    print(f"Ticket     : order {t['order_id']} | reasons {[x['reason'] for x in t['reasons']]} | "
          f"main_reason {t['main_reason']} | priority {t['priority_label'].upper()} {t['priority_score']}")
    print(f"             emotion {t['emotion']['label']} | sentiment {t['sentiment']['label']}")
    print(f"Route      : agent {route['agent']} ({route['layer']})")
    print(f"Answer     : {r['result']['answer']}")
    print(f"Handover   : {r['result']['handover'] or 'none'}")
    print(f"Spoken     : {r['spoken']['out_path']} ({voice.wav_seconds(r['spoken']['out_path'])} s of audio, "
          f"TTS {r['spoken']['seconds']} s)")
    print(f"Trace file : {trace_path}")


if __name__ == "__main__":
    main()
