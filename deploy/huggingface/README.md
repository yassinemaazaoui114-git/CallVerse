---
title: CallVerse Voice
emoji: 🎧
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: ShopNova customer care by text or voice (CallVerse prototype)
---

# CallVerse — customer channel (text + voice)

University data-science prototype: a digital twin of an AI customer relation center for the
fictional shop ShopNova. Write or speak to customer care; every reply is shown and spoken.

- **REAL mode** (when the `GROQ_API_KEY` secret is set): Agent A (Status & Tracking) answers from the
  ShopNova demo data, after an identity check (the email of the order).
- **MOCK mode** (no key): clearly labelled demo replies to try the voice features. No agent, no data.

All ShopNova data is fictional and AI-generated. Voice messages are transcribed and not stored.
Source and documentation: see `docs/voice_channel.md` in the CallVerse repository.

(This file is the README of the Hugging Face Space. Copy it to the root of the Space repository.)
