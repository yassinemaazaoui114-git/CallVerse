"""T10b: the demo screen can be switched on with CALLVERSE_DEMO_ENABLED=1, without editing config.yaml."""

from fastapi.testclient import TestClient

from callverse.config import load_config
from callverse.server.app import app

client = TestClient(app, base_url="http://127.0.0.1:8000")


def test_env_var_switches_the_demo_on_and_default_stays_off(monkeypatch):
    monkeypatch.setitem(load_config()["server"], "demo_enabled", False)   # the value kept in git
    monkeypatch.delenv("CALLVERSE_DEMO_ENABLED", raising=False)
    assert client.get("/demo").status_code == 404
    monkeypatch.setenv("CALLVERSE_DEMO_ENABLED", "0")
    assert client.get("/demo").status_code == 404                        # only "1" turns it on
    monkeypatch.setenv("CALLVERSE_DEMO_ENABLED", "1")
    assert client.get("/demo").status_code == 200
