"""T34: the photo check runs only when vision is enabled AND its packages are installed (requirements-vision.txt).

No model and no GPU here: missing packages are faked by patching vision.model.missing_packages.
"""
import io

import pytest
from PIL import Image

from callverse.channels import web_chat
from callverse.tickets import store
from callverse.vision import model as vm


def photo_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 80, 40)).save(buf, format="JPEG")
    return buf.getvalue()


def no_llm(role_key, messages, tools=None):
    raise AssertionError("no model may run for a photo the channel cannot check")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    store.use_db(tmp_path / "callverse_test.db")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    monkeypatch.setattr(vm, "missing_packages", lambda: ["peft"])   # as on a PC without requirements-vision.txt
    vm.set_backend_for_tests(None)
    yield
    store.use_db(store.DEFAULT_DB_PATH)


def test_vision_is_not_available_without_its_packages():
    assert vm.available() is False


def test_photo_only_without_the_packages_gets_the_clear_reply_and_never_loads_the_model(monkeypatch):
    monkeypatch.setattr(vm, "QwenVL", lambda with_adapter: (_ for _ in ()).throw(AssertionError("model loaded")))
    out = web_chat.send(1, "shopnova", "", chat_fn=no_llm, image=photo_bytes())
    assert out["outcome"] == "photo_unavailable"
    assert out["reply"] == web_chat.PHOTO_UNAVAILABLE_REPLY
