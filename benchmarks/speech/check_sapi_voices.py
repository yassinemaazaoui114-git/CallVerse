
import pyttsx3

engine = pyttsx3.init(driverName="sapi5")

voices = engine.getProperty("voices")

print(f"Available SAPI5 voices: {len(voices)}")

for index, voice in enumerate(voices):
    print(f"\nVoice {index + 1}")
    print(f"Name: {voice.name}")
    print(f"ID: {voice.id}")
    print(f"Languages: {getattr(voice, 'languages', [])}")

engine.stop()
