"""Step 3 tests: the ShopNova customer chat (worker thread + SSE) with a FAKE channel. No model, no Groq.

The fake `send` behaves like callverse.channels.web_chat.send from the outside: it calls on_step with live
texts, writes the user message and the reply with the tickets store (the real channel does that too), and
returns the channel's result dict. Tests set it with chat.use_send_fn(); conftest puts the real one back.
"""

import json
import threading
import time

import pytest
from conftest import CSRF, login, portal_for

from callverse.tickets import store

from webui.api import chat

STEPS = ["Reading your message…", "Checking your order…", "Writing the reply…"]


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """[(event, data)] of an SSE body; comment lines (": ping") are skipped."""
    out = []
    for frame in text.replace("\r\n", "\n").split("\n\n"):
        event, data = None, []
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if event:
            out.append((event, json.loads("\n".join(data))))
    return out


def make_fake(outcome="approve", reply="Your refund is approved.", delay=0.0, gate: threading.Event | None = None,
              raise_exc: Exception | None = None, calls: list | None = None):
    """A fake channel. gate: the fake waits on it after the first step (to hold a job 'running')."""
    def fake_send(user_id, company, text, ticket_id=None, on_step=None, about_order=None, **kwargs):
        if calls is not None:
            calls.append({"user_id": user_id, "company": company, "text": text, "ticket_id": ticket_id,
                          "about_order": about_order})
        if raise_exc:
            raise raise_exc
        t = store.ticket_for_message(company, user_id, ticket_id)
        store.add_message(t["id"], "user", text)
        on_step(STEPS[0])
        if gate is not None:
            gate.wait(10)
        time.sleep(delay)
        for said in STEPS[1:]:
            on_step(said)
        store.add_message(t["id"], "assistant", reply, seconds=1.2)
        status = {"approve": "Solved", "busy": "Open", "ask_proof": "Waiting for user"}.get(outcome, "Open")
        store.update_ticket(t["id"], status=status)
        return {"ticket_id": t["id"], "status": status, "reply": reply, "outcome": outcome,
                "reply_source": "channel", "steps": 3, "seconds": 1.2}
    return fake_send


@pytest.fixture(autouse=True)
def fake_channel(shop_db):
    """Every chat test runs on the seeded temp shopnova.db with the fake channel; the real one is put back."""
    yield
    chat.use_send_fn(None)


def send(client, text, **body):
    return client.post("/api/shop/chat/send", json={"text": text, **body}, headers=CSRF)


# ---------- success, persistence, context ----------

def test_send_streams_steps_then_done_and_saves_the_conversation(client):
    calls = []
    chat.use_send_fn(make_fake(calls=calls))
    login(client, "sara")
    r = send(client, "Where is my order 4512?", client_id="c1")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert [e for e, _ in events] == ["job", "step", "step", "step", "done"]
    assert [d["text"] for e, d in events if e == "step"] == STEPS
    done = events[-1][1]
    assert done["outcome"] == "approve" and done["ticket_id"] == "T-0001" and done["reply"] == "Your refund is approved."
    assert calls == [{"user_id": 1, "company": "shopnova", "text": "Where is my order 4512?", "ticket_id": None,
                      "about_order": None}]
    # persisted by the channel (fake, like the real one): the conversation is read back, not kept in memory
    body = client.get("/api/shop/chat").json()
    assert body["ticket"]["id"] == "T-0001" and body["ticket"]["status"] == "Solved"
    assert [(m["sender"], m["text"]) for m in body["messages"]] == [
        ("user", "Where is my order 4512?"), ("assistant", "Your refund is approved.")]
    assert body["job"]["status"] == "done" and body["job"]["client_id"] == "c1"


def test_order_context_and_ticket_continue_are_passed_to_the_channel(client):
    calls = []
    chat.use_send_fn(make_fake(calls=calls))
    login(client, "sara")
    own = client.get("/api/shop/orders").json()["orders"][0]["id"]
    r = send(client, "Is it late?", about_order=own, client_id="c1")
    assert r.status_code == 200
    assert calls[-1]["about_order"] == own and calls[-1]["ticket_id"] is None
    r2 = send(client, "Thanks", ticket_id="T-0001", client_id="c2")
    assert r2.status_code == 200
    assert calls[-1]["ticket_id"] == "T-0001"


# ---------- who may chat, and about what ----------

def test_other_users_ticket_or_order_is_refused_before_the_channel(client):
    calls = []
    chat.use_send_fn(make_fake(calls=calls))
    login(client, "sara")
    assert send(client, "hi", client_id="a").status_code == 200   # T-0001 is sara's
    saras_order = client.get("/api/shop/orders").json()["orders"][0]["id"]
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "youssef")
    r = send(client, "continue", ticket_id="T-0001", client_id="b")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = send(client, "about hers", about_order=saras_order, client_id="c")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert client.get("/api/shop/chat", params={"ticket": "T-0001"}).status_code == 404
    assert client.post("/api/shop/chat/tickets/T-0001/read", headers=CSRF).status_code == 404
    assert len(calls) == 1   # the channel ran once, for sara only


def test_atlas_ticket_with_the_same_user_id_is_refused(client):
    chat.use_send_fn(make_fake())
    t = store.create_ticket("atlas", 1)   # an Atlas ticket of user id 1 (hedi); sara is user id 1 at ShopNova
    login(client, "sara")
    assert client.get("/api/shop/chat", params={"ticket": t["id"]}).status_code == 404
    assert send(client, "x", ticket_id=t["id"], client_id="z").status_code == 404
    # and sara's "current ticket" is not the Atlas one
    assert client.get("/api/shop/chat").json()["ticket"] is None


def test_roles_and_csrf(client):
    chat.use_send_fn(make_fake())
    paths = ("/api/shop/chat", "/api/shop/chat/job")
    for p in paths:
        assert client.get(p).status_code == 401
    assert client.post("/api/shop/chat/send", json={"text": "x"}, headers=CSRF).status_code == 401
    for username in ("hedi", "admin", "supervisor"):
        login(client, username)
        for p in paths:
            assert client.get(p).status_code == 403, (username, p)
        assert send(client, "x").status_code == 403
        client.post("/api/auth/logout", headers=CSRF)
    login(client, "sara")
    assert client.post("/api/shop/chat/send", json={"text": "x"}).status_code == 403   # no CSRF header
    assert send(client, "   ").status_code == 400
    assert send(client, "x" * (chat.MAX_TEXT + 1)).status_code == 400


# ---------- duplicates, disconnects, recovery, busy, failures ----------

def live_login(base: str, username: str):
    """An httpx client logged in on the live server (cookie jar kept)."""
    import httpx
    c = httpx.Client(base_url=base, timeout=20)
    r = c.post("/api/auth/login", json={"username": username, "password": "test-only", "portal": portal_for(username)}, headers=CSRF)
    assert r.status_code == 200
    return c


def read_until(response, needle: str) -> None:
    """Consume the live SSE stream until a line contains `needle` (then stop reading: a disconnect)."""
    for line in response.iter_lines():
        if needle in line:
            return
    raise AssertionError(f"stream ended without {needle!r}")


def test_same_client_id_is_not_run_twice_and_another_send_is_refused_while_running(live_server):
    calls, gate = [], threading.Event()
    chat.use_send_fn(make_fake(calls=calls, gate=gate))
    c = live_login(live_server, "sara")
    with c.stream("POST", "/api/shop/chat/send", json={"text": "hello", "client_id": "dup"}, headers=CSRF) as r:
        assert r.status_code == 200
        lines = r.iter_lines()   # ONE iterator over the stream (httpx allows a single pass)
        for line in lines:
            if "Reading your message" in line:
                break
        # the job is running: a second message is refused; the same client id is the same job (no second run)
        assert c.post("/api/shop/chat/send", json={"text": "again", "client_id": "other"}, headers=CSRF).status_code == 409
        job = c.get("/api/shop/chat/job").json()["job"]
        assert job["status"] == "running" and job["steps"][0]["text"] == STEPS[0]
        gate.set()
        assert any("event: done" in line for line in lines)
    again = c.post("/api/shop/chat/send", json={"text": "hello", "client_id": "dup"}, headers=CSRF)
    assert again.status_code == 200 and parse_sse(again.text)[-1][0] == "done"
    assert len(calls) == 1   # the channel ran ONCE for the two identical sends


def test_disconnect_then_recover_without_a_second_run(live_server):
    """The browser drops the stream while the channel works; the job finishes anyway; the saved conversation
    and the job result are read back; nothing is sent again."""
    calls, gate = [], threading.Event()
    chat.use_send_fn(make_fake(calls=calls, gate=gate))
    c = live_login(live_server, "sara")
    with c.stream("POST", "/api/shop/chat/send", json={"text": "hello", "client_id": "d1"}, headers=CSRF) as r:
        read_until(r, "Reading your message")
    # disconnected: the worker is still running, shown accurately
    job = c.get("/api/shop/chat/job").json()["job"]
    assert job["status"] == "running"
    convo = c.get("/api/shop/chat").json()
    assert convo["job"]["status"] == "running" and [m["sender"] for m in convo["messages"]] == ["user"]
    # re-attach to the live stream: the steps so far are replayed, then the end
    gate.set()
    r2 = c.get("/api/shop/chat/job/stream")
    events = parse_sse(r2.text)
    assert [e for e, _ in events] == ["job", "step", "step", "step", "done"]
    assert c.get("/api/shop/chat/job").json()["job"]["status"] == "done"
    assert [m["sender"] for m in c.get("/api/shop/chat").json()["messages"]] == ["user", "assistant"]
    assert len(calls) == 1


def test_busy_outcome_is_a_normal_result_not_a_transport_error(client):
    chat.use_send_fn(make_fake(outcome="busy", reply="Our assistant is busy, please try again later."))
    login(client, "sara")
    events = parse_sse(send(client, "hi", client_id="b").text)
    assert events[-1][0] == "done" and events[-1][1]["outcome"] == "busy"
    assert events[-1][1]["reply"].startswith("Our assistant is busy")


def test_worker_exception_is_an_error_event_and_the_job_is_failed(client):
    chat.use_send_fn(make_fake(raise_exc=RuntimeError("boom in the channel")))
    login(client, "sara")
    events = parse_sse(send(client, "hi", client_id="e").text)
    assert events[-1][0] == "error" and events[-1][1]["error"] == "worker_error"
    assert "RuntimeError" in events[-1][1]["message"]
    job = client.get("/api/shop/chat/job").json()["job"]
    assert job["status"] == "failed" and job["error"]["error"] == "worker_error"
    # after a failure a new send is allowed
    chat.use_send_fn(make_fake())
    assert send(client, "again", client_id="f").status_code == 200


def test_unknown_outcome_passes_through(client):
    chat.use_send_fn(make_fake(outcome="ask_proof_photo_v2", reply="Please send a photo."))
    login(client, "sara")
    events = parse_sse(send(client, "hi", client_id="u").text)
    assert events[-1][1]["outcome"] == "ask_proof_photo_v2"


def test_session_expiry_during_recovery(client):
    chat.use_send_fn(make_fake())
    login(client, "sara")
    assert send(client, "hi", client_id="s").status_code == 200
    client.post("/api/auth/logout", headers=CSRF)
    assert client.get("/api/shop/chat/job").status_code == 401
    assert client.get("/api/shop/chat").status_code == 401


def test_unread_notice_and_mark_read_owned_only(client):
    chat.use_send_fn(make_fake())
    login(client, "sara")
    assert send(client, "hi", client_id="r").status_code == 200
    store.set_unread("T-0001", True)   # e.g. finance decided later
    body = client.get("/api/shop/chat")
    assert body.json()["unread"][0]["id"] == "T-0001"
    assert client.post("/api/shop/chat/tickets/T-0001/read", headers=CSRF).status_code == 200
    assert client.get("/api/shop/chat").json()["unread"] == []
    assert client.post("/api/shop/chat/tickets/T-0001/read").status_code == 403   # CSRF header required


def test_console_answers_while_a_chat_is_running(live_server):
    """The worker thread holds the channel; the API event loop is free: the supervisor's reads still answer."""
    gate = threading.Event()
    chat.use_send_fn(make_fake(gate=gate))
    sara = live_login(live_server, "sara")
    with sara.stream("POST", "/api/shop/chat/send", json={"text": "hello", "client_id": "k"}, headers=CSRF) as r:
        read_until(r, "Reading your message")
        supervisor = live_login(live_server, "supervisor")
        t0 = time.perf_counter()
        resp = supervisor.get("/api/console/tickets")
        assert resp.status_code == 200 and resp.json()["count"] >= 1
        assert time.perf_counter() - t0 < 2.0
        gate.set()


def test_chat_imports_the_channel_lazily():
    """With no fake set, the channel is imported only when send_fn() is first called (never at API import)."""
    chat.use_send_fn(None)
    assert chat._send_fn is None


# ---------- correction pass: client_id index, payload binding, bounds ----------

def test_replay_of_a_after_b_returns_a_without_a_third_run(client):
    calls = []
    chat.use_send_fn(make_fake(calls=calls))
    login(client, "sara")
    a = send(client, "message A", client_id="id-A")
    b = send(client, "message B", client_id="id-B", ticket_id="T-0001")
    assert a.status_code == 200 and b.status_code == 200
    assert len(calls) == 2
    again = send(client, "message A", client_id="id-A")   # A is no longer the current job: still found
    assert again.status_code == 200
    events = parse_sse(again.text)
    assert events[-1][0] == "done" and events[-1][1]["ticket_id"] == "T-0001"
    assert [d["text"] for e, d in events if e == "step"] == STEPS   # A's own recorded events, replayed
    assert len(calls) == 2                                          # the channel ran exactly twice
    assert client.get("/api/shop/chat/job").json()["job"]["client_id"] == "id-B"   # the pointer stays on B


def test_same_client_id_with_other_content_is_rejected(client):
    calls = []
    chat.use_send_fn(make_fake(calls=calls))
    login(client, "sara")
    assert send(client, "first text", client_id="same").status_code == 200
    own = client.get("/api/shop/orders").json()["orders"][0]["id"]
    for other in ({"text": "other text"}, {"text": "first text", "ticket_id": "T-0001"},
                  {"text": "first text", "about_order": own}):
        r = client.post("/api/shop/chat/send", json={"client_id": "same", **other}, headers=CSRF)
        assert r.status_code == 409 and r.json()["error"] == "client_id_reused", other
    assert len(calls) == 1
    # the exact same payload is still the same job
    assert parse_sse(send(client, "first text", client_id="same").text)[-1][0] == "done"
    assert len(calls) == 1


def test_registry_expires_and_bounds_records():
    """Finished jobs leave the client index after KEEP_SECONDS; above MAX_JOBS the oldest finished go first;
    a running job is never dropped and the current pointer is independent of the index."""
    reg = chat.Registry()
    reg.MAX_JOBS = 3
    runs = []

    def run(job):
        runs.append(job.client_id)
        job.finish({"ok": True})
    for i in range(5):
        job, created = reg.start(1, "shopnova", f"m{i}", None, None, f"c{i}", run)
        assert created
        for _ in range(100):   # the worker thread finishes at once; wait for it
            if job.status != "running":
                break
            time.sleep(0.01)
        time.sleep(0.002)   # distinct finish times, in order c0 < c1 < ... (the real "oldest first")
    kept = {k[2] for k in reg._by_client}
    assert kept == {"c2", "c3", "c4"}   # the two oldest finished jobs were dropped
    assert reg.current("shopnova", 1).client_id == "c4"
    # expiry: push a job past the window
    reg._by_client[("shopnova", 1, "c4")].finished -= chat.KEEP_SECONDS + 1
    assert reg.current("shopnova", 1) is None and ("shopnova", 1, "c4") not in reg._by_client
    # a running job is kept whatever the bound
    held = []
    def hold(job): held.append(job)   # never finishes
    reg.start(1, "shopnova", "running", None, None, "run", hold)
    for i in range(10, 14):
        try:
            reg.start(1, "shopnova", f"m{i}", None, None, f"c{i}", run)
        except ValueError as e:
            assert str(e) == "busy_user"
    assert ("shopnova", 1, "run") in reg._by_client
    assert len(runs) == 5
