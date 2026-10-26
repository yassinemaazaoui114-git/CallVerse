"""Ollama HTTP client with a resumable JSONL cache keyed by (model, prompt_version, item_id)."""
import json
import re
import threading
import time
from pathlib import Path

import requests

from common import CACHE

OLLAMA = "http://127.0.0.1:11434"  # not "localhost": on Windows it adds ~2 s per request (IPv6 first)
_LOCK = threading.Lock()
_MEM = {}

USERLM = "hf.co/bartowski/microsoft_UserLM-8b-GGUF:Q4_K_M"


def short(model):
    return {USERLM: "userlm-8b"}.get(model, model)


def chat(model, messages, temperature=0.7, num_predict=200, fmt=None, seed=42, timeout=300, num_ctx=4096):
    body = {"model": model, "messages": messages, "stream": False, "keep_alive": "10m",
            "options": {"temperature": temperature, "num_predict": num_predict, "seed": seed, "num_ctx": num_ctx}}
    if model.startswith("qwen3"):
        body["think"] = False
    if fmt:
        body["format"] = fmt
    t0 = time.time()
    r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    return {"text": j["message"]["content"], "wall_s": time.time() - t0,
            "eval_count": j.get("eval_count"), "eval_s": (j.get("eval_duration") or 0) / 1e9,
            "prompt_tokens": j.get("prompt_eval_count")}


def _cache_path(name):
    return CACHE / f"{name}.jsonl"


def _load(name):
    if name not in _MEM:
        d = {}
        p = _cache_path(name)
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    x = json.loads(line)
                    d[(x["model"], x["pv"], x["item"])] = x
        _MEM[name] = d
    return _MEM[name]


def cached_chat(cache_name, model, pv, item_id, messages, **kw):
    """Return the cached output if (model, pv, item_id) was already run; otherwise call and append."""
    d = _load(cache_name)
    key = (model, pv, str(item_id))
    if key in d:
        return d[key]
    try:
        out = chat(model, messages, **kw)
        out["error"] = None
    except Exception as e:  # keep going; record the failure so it is visible
        out = {"text": "", "wall_s": None, "eval_count": None, "eval_s": None, "error": repr(e)[:300]}
    rec = {"model": model, "pv": pv, "item": str(item_id), **out}
    if out["error"] is None:
        with _LOCK:
            d[key] = rec
            with _cache_path(cache_name).open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def ps():
    return requests.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", [])


def unload_all():
    for m in ps():
        requests.post(f"{OLLAMA}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)
    time.sleep(2)


_JSON = re.compile(r"\{.*?\}", re.S)


def parse_score(text):
    """Parse {"score": int 1-5, "comment": str}. Returns (score or None, comment, valid_json)."""
    t = text.strip()
    for cand in [t] + _JSON.findall(t):
        try:
            j = json.loads(cand)
        except Exception:
            continue
        if isinstance(j, dict) and "score" in j:
            try:
                s = int(round(float(j["score"])))
            except Exception:
                continue
            if 1 <= s <= 5:
                return s, str(j.get("comment", ""))[:300], cand == t
    m = re.search(r"\b([1-5])\b", t)
    return (int(m.group(1)) if m else None), "", False
