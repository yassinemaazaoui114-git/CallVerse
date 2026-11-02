# CallVerse — Multimodality Integration Guide

## 1. Overview

This module adds speech and vision capabilities to the CallVerse customer-support application.

It provides two main functionalities:

- **Speech (STT/TTS):** Converts customer speech into text and generates spoken responses.
- **Vision:** Analyzes uploaded product images to identify potentially visible physical damage.

Both capabilities have been implemented and tested locally.

## 2. Scope and Responsibilities

The multimodality module is responsible for processing audio and images. It does not implement customer-support decision-making logic.

**Speech workflow:**

Customer audio → Speech-to-Text → Customer-support pipeline → Text-to-Speech → Audio response

**Vision workflow:**

Customer image → Vision model → Structured damage assessment → Customer-support agent integration

The Vision API returns a classification indicating whether visible product damage was detected.

This classification is supplementary, unverified evidence. It must not independently authorize refunds, replacements or other customer-support decisions.

## 3. Implementation Status

| Component | Status |
|---|---|
| Speech-to-Text | Implemented and locally tested |
| Text-to-Speech | Implemented and locally tested |
| Vision classification | Implemented and locally tested |
| Vision API endpoint | Tested successfully |
| Browser image upload | Tested successfully |
| Agent integration | To be completed by the agent development team |

## 4. Technical Environment

Development and evaluation environment:

- Windows 11
- Python 3.12 virtual environment
- Local Ollama inference for Vision
- CPU-based execution without a dedicated NVIDIA GPU

The implementation is a functional prototype, not a production-ready service.
## 5. Speech Models

### Speech-to-Text (STT)

**Technology:** Faster-Whisper, running locally on CPU with INT8 quantization.

Three models were evaluated using 10 English audio samples containing order identifiers and monetary amounts.

| Model | Number accuracy | Number-masked WER | Average latency |
|---|---|---|---|
| Whisper Tiny | 100% | 2.00% | 0.44 s |
| Whisper Base | 100% | 0.00% | 0.72 s |
| Whisper Small | 100% | 0.00% | 2.11 s |

**Recommended model: Whisper Base**, providing a favorable balance between transcription accuracy, latency and memory usage in the tested environment.

### Text-to-Speech (TTS)

Two local speech synthesis solutions were evaluated:

- **Piper:** Offline neural speech synthesis with English and French voices.
- **Windows SAPI5:** Native Windows speech synthesis.

| Engine | English latency | French latency |
|---|---|---|
| Piper | 0.315 s | 0.296 s |
| SAPI5 | 0.104 s | 0.083 s |

**Recommended engine: Piper** for portability across environments, subject to the availability of the required voice models.

SAPI5 was faster in the local benchmarks but depends on Windows and installed system voices.

## 6. Vision Models

**Technology:** Ollama, running locally.

Three vision-language models were evaluated on 30 product images: 15 labeled damaged and 15 labeled intact.

| Model | Classification accuracy | Valid JSON outputs | Average warm latency |
|---|---|---|---|
| Qwen3-VL 2B | 80.0% | 28/30 | 9.61 s |
| Moondream 1.8B | 83.3% | 30/30 | 1.02 s |
| Granite Vision 2B | 66.7% | 30/30 | 68.71 s |

**Selected primary model: `qwen3-vl:2b`**

Qwen3-VL was prioritized for its higher recall of visibly damaged products in the evaluation, despite Moondream achieving better overall accuracy and latency.

**Alternative model:** `moondream:1.8b-v2-q4_0`, suitable when low latency is a higher priority.

### Important limitations

- Results are based on a small, exploratory dataset.
- The models were not evaluated under identical prompting and output-format constraints.
- Some product conditions are visually ambiguous.
- Model classifications can contain false positives and false negatives.
- A human or downstream business process must validate consequential decisions.

These results support prototype model selection, not production performance guarantees.
## 7. API Integration

The multimodality capabilities are exposed through the existing CallVerse FastAPI application.

### 7.1 Create a session

**Endpoint:** `POST /api/session`

A session must be created before submitting audio or images.

Example response:

```json
{
  "session_id": "<generated-session-id>",
  "mode": "mock"
}
```

The `session_id` must be reused for subsequent requests belonging to the same conversation. The mode depends on the application configuration.

### 7.2 Speech-to-Text and voice interaction

**Endpoint:** `POST /api/turn/audio`

**Request format:** `multipart/form-data`

| Parameter | Required | Description |
|---|---|---|
| `session_id` | Yes | Existing CallVerse session identifier |
| `audio` | Yes | Customer audio recording |
| `lang` | No | `auto` (default), `en` or `fr` |

The endpoint validates the audio, transcribes it using STT, and forwards the recognized text to the existing customer-support pipeline.

The response includes a `transcript` object containing:

- `text`: recognized customer speech
- `language`: detected language
- `provider`: STT provider used
- `seconds`: transcription processing duration
- `audio_seconds`: recording duration

The response also contains the existing CallVerse pipeline reply.

**Audio playback endpoint:** `GET /api/audio/{clip_id}`

This retrieves a generated WAV audio clip when one is available. Clips are temporary and can expire.

### 7.3 Product image analysis

**Endpoint:** `POST /api/turn/image`

**Request format:** `multipart/form-data`

| Parameter | Required | Description |
|---|---|---|
| `session_id` | Yes | Existing CallVerse session identifier |
| `image` | Yes | Product image in JPEG, PNG or WebP format |

**Maximum image size:** 5 MB.

Example response for a product with visible damage:

```json
{
  "status": "success",
  "damaged": true,
  "model": "qwen3-vl:2b",
  "latency_seconds": 4.731,
  "requires_review": true
}
```

The latency value is illustrative and varies between requests.

The API stores the latest assessment in the session as `vision_assessment`, containing `damaged`, `model` and `requires_review`.

The original uploaded image is not stored by this endpoint.

### 7.4 Integration responsibilities

The multimodality module provides transcription, speech synthesis and image classification.

The agent development team is responsible for connecting these outputs to its business workflows, including order verification, customer-support policies and refund decisions.

**Important:** The Vision assessment is not automatically injected into Agent A's conversation history. Agent integration must be implemented explicitly by the responsible team.

Vision output is not proof of damage or refund eligibility. Consequential decisions require additional validation.
## 8. Installation and Startup

### 8.1 Python environment

From the CallVerse repository root, create and activate a Python virtual environment (Windows PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-voice.txt
```

This installs the web application, Speech and Vision dependencies.

### 8.2 Install Ollama and the Vision model

Install Ollama from https://ollama.com/download.

Then download the selected Vision model:

```powershell
ollama pull qwen3-vl:2b
```

Ensure Ollama is running locally at `http://127.0.0.1:11434`.

The alternative benchmarked Vision model can be installed with:

```powershell
ollama pull moondream:1.8b-v2-q4_0
```

Qwen3-VL 2B is the provisional primary model based on the damage-detection benchmark. Moondream is an alternative when inference speed is the priority.

### 8.3 Start the web application

From the repository root, with the virtual environment activated:

```powershell
$env:PORT = "8081"
python -m scripts.run_web
```

Open `http://127.0.0.1:8081/` in your browser.

Port 8081 is used for the tested local setup; it can be changed if required.

### 8.4 Integration notes

- Speech requires the appropriate STT and TTS models and voice assets to be available locally.
- The Vision model runs through Ollama.
- The Vision API returns a structured assessment but does not automatically trigger an agent workflow.
- Model inference performance depends on the available hardware, especially when running on CPU.
- The benchmark media files are excluded from Git. Benchmark results and scripts are included, but reproducing the exact evaluation requires access to the original test media.