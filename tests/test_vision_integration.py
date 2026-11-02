"""Vision integration: photo check (schema, fallback, errors), late fusion, and the whole channel with a photo.

No GPU and no model download here: the photo model is replaced by a fake that returns the JSON text the real model
would write (callverse.vision.model.set_backend_for_tests). The REAL adapter is checked separately on real photos
by scripts/vision_check.py (results in docs/vision_integration.md). Agents get a fake LLM, the SLM is offline.
Customer messages are written for these tests (not from any held-out set).
"""
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from callverse.channels import web_chat
from callverse.kb import search
from callverse.tickets import store
from callverse.tools.registry import run_tool
from callverse.vision import fusion, schema
from callverse.vision import model as vm


def photo_bytes(fmt="JPEG", size=(64, 48)):
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 80, 40)).save(buf, format=fmt)
    return buf.getvalue()


def answer(issue, obj="smartphone", conf="high", desc="A phone with a cracked screen."):
    vis = True if issue in schema.DAMAGE_TYPES else (False if issue == "no_visible_issue" else None)
    return json.dumps({"visible_damage": vis, "object": obj, "issue_type": issue, "description": desc,
                       "confidence_level": conf, "requires_review": vis is not False})


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    store.use_db(tmp_path / "callverse_test.db")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    vm._loaded.clear(), vm._failed.clear()
    yield
    vm.set_backend_for_tests(None)
    vm._loaded.clear(), vm._failed.clear()
    store.use_db(store.DEFAULT_DB_PATH)


def fake_vision(text, backend="qlora"):
    seen = []

    def fake(image):
        seen.append(image.size)
        return text, backend
    vm.set_backend_for_tests(fake)
    return seen


def tool_call(name, arguments):
    tc = SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tc])


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def no_llm(role_key, messages, tools=None):
    raise AssertionError("no LLM call expected")


# Order 4509 (user 1): delivered, paid 39.80 TND, nothing refunded (scripted seed).
DMG_REFUND = {"order_id": 4509, "amount": 39.80, "rule_id": "R-DMG-01",
              "facts_used": {"days_late": 0, "delivered": True, "paid": 39.80, "refunded_total": 0.0},
              "user_confirmed": True, "user_quote": "I want a refund."}


def damaged_refund_llm(messages_seen):
    """Agent B: reads the order, searches the rules, proposes a refund under R-DMG-01."""
    steps = iter([tool_call("get_order", {"order_id": 4509}), tool_call("get_refunds", {"order_id": 4509}),
                  tool_call("search_policy", {"query": "damaged item refund"}),
                  tool_call("propose_refund", DMG_REFUND)])

    def fake(role_key, messages, tools=None):
        messages_seen.append(messages[-1]["content"] if messages[-1]["role"] == "user" else "")
        return next(steps, None) or text_reply("Your request is sent for checking.")
    return fake


@pytest.fixture
def dmg_rule(monkeypatch):
    monkeypatch.setattr(search, "search_policy",
                        lambda query, k=3: [{"id": "R-DMG-01", "title": "", "text": "", "score": 1.0}])


# ---------- schema ----------
def test_prompt_is_the_one_the_adapter_was_trained_with():
    assert schema.PROMPT.startswith("You check photos sent to a customer-service centre")
    assert "issue_type values: cracked_screen, screen_display_defect" in schema.PROMPT


@pytest.mark.parametrize("raw,why", [("nothing", "no_json"), ('{"damaged": true}', "wrong_keys"),
                                     (answer("refund_request"), "bad_issue_type")])
def test_invalid_model_output_is_rejected(raw, why):
    assert schema.parse_output(raw) == (None, why)


def test_contradictory_output_is_normalised():
    raw = json.dumps({"visible_damage": False, "object": "suitcase", "issue_type": "damaged_luggage",
                      "description": "A dented suitcase.", "confidence_level": "high", "requires_review": False})
    a, why = schema.parse_output(raw)
    assert why == "ok" and a["visible_damage"] is True and a["requires_review"] is True


# ---------- photo model: files, fallback, errors ----------
@pytest.mark.parametrize("data,code", [(b"", "empty_image"), (b"not an image", "invalid_image"),
                                       (photo_bytes("GIF"), "unsupported_image"),
                                       (b"x" * (vm.MAX_IMAGE_BYTES + 1), "image_too_large")],
                         ids=["empty", "not_image", "gif", "too_large"])   # T34: short ids (Windows env-var limit)
def test_bad_files_are_refused_before_any_model(data, code):
    fake_vision(answer("cracked_screen"))
    with pytest.raises(vm.VisionError) as e:
        vm.analyze(data)
    assert e.value.code == code


def test_formats_and_downsizing():
    seen = fake_vision(answer("cracked_screen"))
    for fmt in ("JPEG", "PNG", "WEBP"):
        assert vm.analyze(photo_bytes(fmt))["valid_output"]
    vm.analyze(photo_bytes(size=(3000, 1500)))
    assert max(seen[-1]) <= 1024


def test_invalid_output_becomes_unclear_never_a_guess():
    fake_vision("The phone looks broken to me!")
    out = vm.analyze(photo_bytes())
    assert out["valid_output"] is False and out["assessment"]["issue_type"] == "unclear"
    assert out["assessment"]["visible_damage"] is None and out["assessment"]["requires_review"]


class FakeModel:
    def __init__(self, with_adapter):
        if with_adapter and FakeModel.adapter_missing:
            raise FileNotFoundError("adapter_model.safetensors not found")
        self.name, self.adapter, self.quant = ("qlora" if with_adapter else "base"), None, "none"

    def generate(self, image):
        return answer("cracked_screen")


def test_missing_adapter_falls_back_to_the_base_model(monkeypatch):
    monkeypatch.setattr(vm, "QwenVL", FakeModel)
    FakeModel.adapter_missing = True
    out = vm.analyze(photo_bytes())
    assert out["backend"] == "base" and out["fallback_used"] and "qlora" in out["errors"][0]
    FakeModel.adapter_missing = False
    vm._failed.clear()
    assert vm.analyze(photo_bytes())["backend"] == "qlora"


def test_no_backend_at_all_raises_model_unavailable(monkeypatch):
    def broken(with_adapter):
        raise OSError("no network")
    monkeypatch.setattr(vm, "QwenVL", broken)
    with pytest.raises(vm.VisionError) as e:
        vm.analyze(photo_bytes())
    assert e.value.code == "model_unavailable"


# ---------- late fusion rules ----------
def ticket(company="shopnova", reason="other", text="look"):
    t = fusion.image_only_ticket("T-X", company)
    return {**t, "text": text, "main_reason": reason, "reasons": [{"reason": reason, "score": 0.8, "sentence": text}]}


def block(issue, conf="high"):
    a, _ = schema.parse_output(answer(issue, conf=conf))
    return fusion.photo_block({"assessment": a, "backend": "qlora", "valid_output": True})


def test_text_reason_always_wins_over_the_photo():
    out = fusion.fuse(ticket(reason="order_status", text="Where is my order?"), block("cracked_screen"))
    assert out["main_reason"] == "order_status" and out["fusion"]["reason_source"] == "text"
    assert out["photo"]["verified"] is False and out["fusion"]["proof_received"] is True


def test_unclear_text_plus_damage_photo_at_shopnova_is_a_damage_report():
    out = fusion.fuse(ticket(reason="other", text="Look at this."), block("damaged_packaging"))
    assert out["main_reason"] == "damaged_item" and out["fusion"]["reason_source"] == "text+photo"


def test_atlas_never_gets_an_intent_from_a_photo():
    out = fusion.fuse(ticket("atlas", "other", ""), block("damaged_luggage"))
    assert out["main_reason"] == "other" and out["fusion"]["proof_received"] is True


def test_image_only_ticket_does_not_guess_feelings():
    t = fusion.image_only_ticket("T-X", "shopnova")
    assert t["emotion"]["source"] == t["sentiment"]["source"] == fusion.NOT_MEASURED
    assert t["emotion"]["score"] is None and t["emotion_intensity"] == 0.0


def test_conflicts_are_flagged_for_review():
    out = fusion.fuse(ticket(reason="damaged_item", text="It arrived broken."), block("no_visible_issue"))
    assert out["fusion"]["conflict"] == "text_says_damage_photo_shows_none" and out["fusion"]["requires_review"]
    assert out["fusion"]["proof_received"] is False
    unclear = fusion.fuse(ticket(), block("unclear", conf="low"))
    assert unclear["fusion"]["conflict"] == "photo_unclear" and unclear["main_reason"] == "other"
    unchecked = fusion.fuse(ticket(), fusion.photo_block(None, "model_unavailable"))
    assert unchecked["fusion"]["conflict"] == "photo_not_checked" and "could not be checked" in fusion.note(unchecked)


# ---------- the whole channel (Intake -> fusion -> router -> agent -> Coordinator -> reply) ----------
def test_damaged_phone_photo_is_the_proof_and_the_coordinator_approves(dmg_rule):
    fake_vision(answer("cracked_screen"))
    seen = []
    out = web_chat.send(1, "shopnova", "My phone from order 4509 arrived with a cracked screen, I want a refund.",
                        chat_fn=damaged_refund_llm(seen), image=photo_bytes())
    assert out["outcome"] == "approve", out
    assert any("Photo proof for R-DMG-01 = yes" in m for m in seen)           # the agent saw the unverified note
    assert run_tool("B", "get_refunds", {"order_id": 4509})["refunded_total"] == 39.80
    kinds = [s["step"] for s in store.steps(out["ticket_id"])]
    assert "photo_check" in kinds
    msgs = store.messages(out["ticket_id"])
    assert msgs[0]["text"].endswith("[Photo attached]")                       # the photo bytes are never stored


def test_photo_message_keeps_live_steps_and_saves_the_pipeline_steps(dmg_rule):
    """T35b: the photo_check step used to stop the step listener before the pipeline ran, so a photo message showed
    no live steps and saved only photo_check. Now the pipeline's steps are live AND saved, after photo_check."""
    from callverse import trace
    fake_vision(answer("cracked_screen"))
    said = []
    out = web_chat.send(1, "shopnova", "My phone from order 4509 arrived with a cracked screen, I want a refund.",
                        chat_fn=damaged_refund_llm([]), image=photo_bytes(), on_step=said.append)
    assert out["outcome"] == "approve", out
    assert len(said) >= 2, said                                 # live texts while the pipeline ran
    assert said[0] == web_chat.PHOTO_STEP_TEXT == "Checking your photo…"   # first, before the photo model runs
    kinds = [s["step"] for s in store.steps(out["ticket_id"])]
    assert "photo_check" in kinds and "route" in kinds and "coordinator" in kinds, kinds
    assert kinds.index("photo_check") < kinds.index("route")   # time order kept
    assert not trace._listeners                                 # listening stopped when the message ended


def test_no_photo_no_photo_step_text(dmg_rule):
    said = []
    web_chat.send(1, "shopnova", "My phone from order 4509 arrived with a cracked screen, I want a refund.",
                  chat_fn=damaged_refund_llm([]), on_step=said.append)
    assert said and web_chat.PHOTO_STEP_TEXT not in said


def test_same_request_without_photo_still_asks_for_one(dmg_rule):
    out = web_chat.send(1, "shopnova", "My phone from order 4509 arrived with a cracked screen, I want a refund.",
                        chat_fn=damaged_refund_llm([]))
    assert out["outcome"] == "ask_proof" and "photo" in out["reply"].lower()
    assert run_tool("B", "get_refunds", {"order_id": 4509})["refunded_total"] == 0.0


def test_intact_photo_is_not_proof_a_colleague_checks(dmg_rule):
    fake_vision(answer("no_visible_issue", desc="An intact phone."))
    out = web_chat.send(1, "shopnova", "My phone from order 4509 arrived with a cracked screen, I want a refund.",
                        chat_fn=damaged_refund_llm([]), image=photo_bytes())
    assert out["outcome"] == "escalate" and out["status"] == "Escalated"
    assert run_tool("B", "get_refunds", {"order_id": 4509})["refunded_total"] == 0.0   # nothing paid


def test_model_down_photo_is_not_proof(dmg_rule, monkeypatch):
    monkeypatch.setattr(vm, "QwenVL", lambda with_adapter: (_ for _ in ()).throw(OSError("offline")))
    out = web_chat.send(1, "shopnova", "My phone from order 4509 arrived with a cracked screen, I want a refund.",
                        chat_fn=damaged_refund_llm([]), image=photo_bytes())
    assert out["outcome"] == "escalate"
    assert run_tool("B", "get_refunds", {"order_id": 4509})["refunded_total"] == 0.0


def test_photo_only_damage_asks_for_the_order_number():
    fake_vision(answer("cracked_screen"))

    def agent(role_key, messages, tools=None):
        assert "(The customer sent a photo without any text.)" in messages[-1]["content"]
        return text_reply("Please send your order number.")
    out = web_chat.send(1, "shopnova", "", chat_fn=agent, image=photo_bytes())
    assert store.get_ticket(out["ticket_id"])["main_reason"] == "damaged_item"
    assert out["outcome"] == "info" and "order number" in out["reply"].lower()


def test_photo_only_with_a_bad_file_asks_for_another_photo():
    out = web_chat.send(1, "shopnova", "", chat_fn=no_llm, image=b"%PDF-1.4 not a photo")
    assert out["outcome"] == "photo_invalid" and "JPEG, PNG or WebP" in out["reply"]


def test_bad_file_with_text_continues_with_the_text_only():
    def agent(role_key, messages, tools=None):
        assert "Photo check" not in messages[-1]["content"]
        return text_reply("Order 4512 is on its way.")
    out = web_chat.send(1, "shopnova", "Where is my order 4512?", chat_fn=agent, image=b"garbage")
    assert store.get_ticket(out["ticket_id"])["main_reason"] in ("order_status", "late_delivery")


def test_misleading_photo_does_not_change_the_route():
    fake_vision(answer("cracked_screen"))
    first_prompt = []

    def agent(role_key, messages, tools=None):
        first_prompt.append(messages[0]["content"])
        return text_reply("Order 4512 is on its way.")
    out = web_chat.send(1, "shopnova", "Where is my order 4512?", chat_fn=agent, image=photo_bytes())
    t = store.get_ticket(out["ticket_id"])
    assert t["main_reason"] in ("order_status", "late_delivery") and t["lead_agent"] == "A"
    assert first_prompt[0].startswith("You are Agent A")


def test_text_only_flow_is_unchanged():
    def agent(role_key, messages, tools=None):
        assert "Photo" not in messages[-1]["content"]
        return text_reply("Order 4512 is on its way.")
    out = web_chat.send(1, "shopnova", "Where is my order 4512?", chat_fn=agent)
    assert [s["step"] for s in store.steps(out["ticket_id"])].count("photo_check") == 0


def test_atlas_luggage_photo_goes_with_the_compensation_request():
    fake_vision(answer("damaged_luggage", obj="suitcase", desc="A suitcase with a broken shell."))
    seen = []

    def agent(role_key, messages, tools=None):
        seen.append((messages[0]["content"][:40], messages[-1]["content"]))
        return text_reply("Your request is passed on for a compensation check.")
    out = web_chat.send(1, "atlas", "My suitcase was destroyed on my flight, I want compensation for booking 7001.",
                        chat_fn=agent, image=photo_bytes())
    t = store.get_ticket(out["ticket_id"])
    assert t["main_reason"] == "compensation_request" and t["lead_agent"] == "B"
    assert any("issue = damaged_luggage" in m and "unverified" in m for _, m in seen)


def test_atlas_photo_only_stays_other():
    fake_vision(answer("dirty_or_messy_room", obj="hotel_room", desc="A messy room."))

    def agent(role_key, messages, tools=None):
        return text_reply("What would you like us to do about it?")
    out = web_chat.send(1, "atlas", "", chat_fn=agent, image=photo_bytes())
    assert store.get_ticket(out["ticket_id"])["main_reason"] == "other"


# ---------- Molka's website endpoint ----------
def test_web_image_endpoint_returns_the_structured_evidence():
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient
    from callverse.web import app as web_app
    fake_vision(answer("cracked_screen"))
    client = TestClient(web_app.app)
    sid = client.post("/api/session").json()["session_id"]
    r = client.post("/api/turn/image", data={"session_id": sid},
                    files={"image": ("p.jpg", photo_bytes(), "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["damaged"] is True and body["assessment"]["issue_type"] == "cracked_screen"
    assert body["requires_review"] is True and body["model"] == "qlora"
    bad = client.post("/api/turn/image", data={"session_id": sid}, files={"image": ("p.gif", photo_bytes("GIF"))})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unsupported_image"
    vm.set_backend_for_tests(None)
    import callverse.vision.model as m2
    m2._failed.update(qlora="missing", base="missing")
    down = client.post("/api/turn/image", data={"session_id": sid}, files={"image": ("p.jpg", photo_bytes())})
    assert down.status_code == 503 and down.json()["error"]["code"] == "model_unavailable"
