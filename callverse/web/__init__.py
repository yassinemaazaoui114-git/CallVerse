"""Voice + text web channel for CallVerse customers.

A CHANNEL ADAPTER, not an agent: it turns a voice message into text (speech-to-text), passes the text to
the CallVerse pipeline (pipeline.py), and turns the approved reply into audio (text-to-speech).
It makes no business decision itself. See docs/voice_channel.md.
"""
