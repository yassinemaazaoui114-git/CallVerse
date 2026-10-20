# CallVerse customer channel (text + voice): one container, CPU only, no GPU needed.
#   docker build -t callverse-voice .
#   docker run -p 7860:7860 -e GROQ_API_KEY=... callverse-voice     (without the key: MOCK mode)
# Made for Hugging Face Spaces (Docker SDK, free CPU hardware), see docs/voice_channel.md.
# Only the customer website runs here; the platform/admin server is NOT part of this image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CALLVERSE_MODELS_DIR=/app/models \
    HF_HOME=/app/models/hf \
    HOST=0.0.0.0 \
    PORT=7860

# Hugging Face Spaces runs containers as user id 1000.
RUN useradd -m -u 1000 app
WORKDIR /app

COPY requirements.txt requirements-voice.txt ./
RUN pip install --no-cache-dir -r requirements-voice.txt

COPY . .
# Speech models are downloaded at BUILD time (about 210 MB), never while a customer is waiting.
RUN python -m scripts.download_voice_models && chown -R app:app /app
USER app

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ['PORT'])"
CMD ["python", "-m", "scripts.run_web"]
