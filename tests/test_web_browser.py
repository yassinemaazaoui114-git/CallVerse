"""End-to-end test in a real browser (Chromium via Playwright), with a FAKE MICROPHONE fed by a Piper clip
of "Hello, where is my order 4512?" and the REAL speech models (in-server Whisper + Piper).

It runs only when asked, because it needs a browser and the models:
    RUN_BROWSER_TESTS=1 python -m pytest tests/test_web_browser.py
Optional: CHROMIUM_PATH=/path/to/chrome, BROWSER_SCREENSHOTS=<folder> to save screenshots.
"""

import os
import re
import socket
import threading
import time

import pytest

if os.getenv("RUN_BROWSER_TESTS") != "1":
    pytest.skip("browser test: set RUN_BROWSER_TESTS=1", allow_module_level=True)
playwright = pytest.importorskip("playwright.sync_api")
pytest.importorskip("fastapi")

import uvicorn  # noqa: E402

from callverse.web import pipeline  # noqa: E402
from callverse.web.models import piper_dir  # noqa: E402

if not (piper_dir() / "en_GB-cori-medium.onnx").exists():
    pytest.skip("speech models not installed", allow_module_level=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(pipeline, "resolve_mode", lambda: "mock")   # no API key here: MOCK, clearly labelled
    monkeypatch.delenv("GROQ_API_KEY", raising=False)                # speech-to-text = in-server Whisper
    from callverse.web.app import app
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def mic_clip(tmp_path):
    """The customer's question as a WAV file for Chromium's fake microphone (the number said digit by digit)."""
    from tests.test_web_speech import steady_clip
    path = tmp_path / "question.wav"
    path.write_bytes(steady_clip("Hello, where is my order 4512?"))
    return path


def launch(p, clip):
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={clip}", "--autoplay-policy=no-user-gesture-required"]
    path = os.getenv("CHROMIUM_PATH")
    return p.chromium.launch(executable_path=path or None, args=args)


def shot(page, name):
    folder = os.getenv("BROWSER_SCREENSHOTS")
    if folder:
        page.screenshot(path=os.path.join(folder, f"{name}.png"), full_page=True)


def test_text_and_voice_in_the_browser(server, mic_clip):
    with playwright.sync_playwright() as p:
        browser = launch(p, mic_clip)
        context = browser.new_context(permissions=["microphone"], viewport={"width": 1280, "height": 860})
        page = context.new_page()
        problems = []
        page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: problems.append(str(e)))
        page.goto(server)
        playwright.expect(page.locator("#mode-badge")).to_have_text("Demo (MOCK)")

        # 1. Text message: CallVerse asks for the email of the order first (identity gate)
        page.fill("#input", "Hello, where is my order 4512?")
        page.keyboard.press("Enter")
        bot = page.locator(".msg.bot").last
        playwright.expect(bot.locator(".text")).to_contain_text("email address used for order 4512", timeout=30_000)
        playwright.expect(bot.locator(".player")).to_be_visible()

        # 2. Same conversation: the email unlocks the waiting question -> Intake -> Router -> Agent A (MOCK)
        page.fill("#input", "sara@example.com")
        page.keyboard.press("Enter")
        bot = page.locator(".msg.bot").last
        playwright.expect(bot.locator(".text")).to_contain_text("Demo mode", timeout=60_000)
        playwright.expect(bot.locator(".tag.mock")).to_have_text("MOCK")
        bot.locator(".steps summary").click()
        steps = bot.locator(".steps li")
        playwright.expect(steps.nth(0)).to_contain_text("Intake")
        playwright.expect(steps.nth(0).locator(".status")).to_have_text("real")
        playwright.expect(steps.nth(1)).to_contain_text("Agent A")
        playwright.expect(bot.locator(".steps")).to_contain_text("Coordinator")
        playwright.expect(bot.locator(".steps")).to_contain_text("not built")

        # 3. Voice message in the same conversation: record from the fake microphone, stop, send
        page.click("#mic")
        playwright.expect(page.locator("#recorder")).to_be_visible()
        playwright.expect(page.locator("#composer")).to_be_hidden()
        page.wait_for_timeout(3500)
        shot(page, "recording")
        page.click("#rec-stop")
        user = page.locator(".msg.user").last
        playwright.expect(user.locator(".tag")).to_have_text("Voice")
        playwright.expect(user.locator(".meta")).to_contain_text("transcribed", timeout=60_000)
        transcript = user.locator(".text").inner_text()
        assert "4512" in re.sub(r"\D", "", transcript), transcript
        assert "order" in transcript.lower()
        bot = page.locator(".msg.bot").last
        playwright.expect(bot.locator(".text")).to_contain_text("Demo mode", timeout=60_000)   # order already verified
        bot.locator(".steps summary").click()
        playwright.expect(bot.locator(".steps li").first).to_contain_text("Speech-to-text")
        playwright.expect(bot.locator(".steps")).to_contain_text("Text-to-speech")

        # 3. The answer's audio plays and can be replayed
        play = bot.locator(".player .play")
        playwright.expect(play).to_have_attribute("aria-label", re.compile("Pause|Play"), timeout=10_000)
        page.wait_for_timeout(1500)
        bot.locator(".player .secondary").click()            # replay from the start
        playwright.expect(play).to_have_attribute("aria-label", "Pause", timeout=10_000)
        shot(page, "desktop")

        # 4. Cancel a recording: nothing is sent
        count = page.locator(".msg").count()
        page.click("#mic")
        playwright.expect(page.locator("#recorder")).to_be_visible()
        page.wait_for_timeout(800)
        page.click("#rec-cancel")
        playwright.expect(page.locator("#composer")).to_be_visible()
        page.wait_for_timeout(500)
        assert page.locator(".msg").count() == count

        assert not problems, problems                          # no JS errors, no CSP violations
        browser.close()


def test_mobile_layout(server, mic_clip):
    with playwright.sync_playwright() as p:
        browser = launch(p, mic_clip)
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = context.new_page()
        page.goto(server)
        playwright.expect(page.locator("#mode-badge")).to_have_text("Demo (MOCK)")
        page.locator(".chip").first.click()
        playwright.expect(page.locator(".msg.bot .player")).to_be_visible(timeout=60_000)
        no_side_scroll = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert no_side_scroll
        for selector in ("#mic", "#send", "#input", "#lang", "#new-chat"):
            box = page.locator(selector).bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, selector
        shot(page, "mobile")
        browser.close()
