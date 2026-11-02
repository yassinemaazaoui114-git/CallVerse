"""T34: Mahmoud's Client Simulator (client_simulator/) talks to the CallVerse center.

Usage (from the repo root; Ollama running with gemma3:1b and the center's local models):
    set CALLVERSE_AGENTS_SET=local
    python -m scripts.run_client_simulator              # the 3 default role cards
    python -m scripts.run_client_simulator --cards SN-01 AT-02 --turns 2

How it works:
  - The simulator (client_simulator/simulator, gemma3:1b) plays the CLIENT: it writes the client's messages from a
    role card (who the client is, what they want, their mood).
  - center_reply() below is the ONE adapter: it sends the client's message through the same door as the apps,
    callverse.channels.web_chat.send, and returns the center's reply. The simulator never touches the center's data.
  - After the chat, the simulator's CPU scorer (MiniLM, ONNX) gives the conversation a 1-5 satisfaction score.

The role cards were written for Mahmoud's platform, so some name orders / bookings that do not exist in our data.
CASES maps each card used here to a real scripted order or booking and its owner (user_id), so the center can find it.

Data: every conversation starts from fresh ShopNova and Atlas data (the same seed as the checks, scripts.run_t14c),
and the tickets go to their own file (out/t34_sim_tickets.db, deleted at the end), so callverse.db is not touched.
Output: out/t34_simulator.json (transcripts, scores, timings) and out/t34_simulator.md (readable).
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "client_simulator"))   # the simulator package is client_simulator/simulator

from callverse import trace  # noqa: E402
from callverse.channels import web_chat  # noqa: E402
from callverse.data import clock  # noqa: E402
from callverse.data.atlas.seed import seed as seed_atlas  # noqa: E402
from callverse.data.seed import seed as seed_shopnova  # noqa: E402
from callverse.intake import intake  # noqa: E402
from callverse.slm.writer import warm_up  # noqa: E402
from callverse.tickets import store  # noqa: E402

import simulator  # noqa: E402  (client_simulator/simulator)

CARDS = ROOT / "client_simulator" / "simulator" / "role_cards"
OUT = ROOT / "out"
TICKETS_DB = OUT / "t34_sim_tickets.db"

# card id -> the real case it is about. user_id = the owner in the seed data (callverse/data/seed.py, atlas/seed.py).
CASES = {
    "SN-01": {"user_id": 1, "facts": {"order_id": 4512}},     # late laptop -> order 4512 (stuck at depot)
    "SN-03": {"user_id": 5, "facts": {"order_id": 4514}},     # not shipped yet -> order 4514 (processing)
    "AT-02": {"user_id": 5, "facts": {"booking_id": 7004, "route": "New York-Chicago"}},   # delayed flight -> 7004
}
DEFAULT_CARDS = ["SN-01", "SN-03", "AT-02"]


def center_reply(user_id: int, company: str, text: str, ticket_id: str | None) -> dict:
    """THE adapter: one client message into the center, through the same door as the apps. Returns its answer."""
    return web_chat.send(user_id, company, text, ticket_id)


def load_card(card_id: str) -> dict:
    company = "shopnova" if card_id.startswith("SN") else "atlas"
    card = simulator.load_role_card(CARDS / company / f"{card_id}.yaml")
    case = CASES[card_id]
    card["facts"] = {k: v for k, v in (card.get("facts") or {}).items() if k != "booking_ref"} | case["facts"]
    return card


def run_conversation(card_id: str, turns: int, seed: int) -> dict:
    """Fresh data, then up to `turns` client messages (the client stops early when the ticket is solved)."""
    seed_shopnova()
    seed_atlas()
    clock.reset()
    card = load_card(card_id)
    user_id = CASES[card_id]["user_id"]
    transcript, steps, ticket_id = [], [], None
    for turn in range(turns):
        start = time.perf_counter()
        said = simulator.simulate_turn(card, transcript, seed=seed + turn)
        sim_seconds = round(time.perf_counter() - start, 1)
        if not said:
            break
        transcript.append({"role": "customer", "text": said})
        start = time.perf_counter()
        try:
            out = center_reply(user_id, card["company"], said, ticket_id)
            error = None
        except Exception as e:  # noqa: BLE001 — a crash is recorded, never a stop of the whole run
            out, error = {}, f"{type(e).__name__}: {e}"
        center_seconds = round(time.perf_counter() - start, 1)
        ticket_id = out.get("ticket_id") or ticket_id
        reply = out.get("reply") or ""
        transcript.append({"role": "agent", "text": reply})
        steps.append({"turn": turn + 1, "client": said, "reply": reply, "outcome": out.get("outcome"),
                      "status": out.get("status"), "reply_source": out.get("reply_source"), "error": error,
                      "sim_seconds": sim_seconds, "center_seconds": center_seconds})
        print(f"  {card_id} turn {turn + 1}: outcome={out.get('outcome')} status={out.get('status')} "
              f"sim {sim_seconds} s, center {center_seconds} s{'  ERROR ' + error if error else ''}", flush=True)
        if error or out.get("status") in ("Solved", "Escalated", "Waiting for finance"):
            break
    start = time.perf_counter()
    score = simulator.score_conversation(card, transcript) if transcript else {}
    return {"card": card_id, "company": card["company"], "user_id": user_id, "facts": card["facts"],
            "steps": steps, "score": score, "score_seconds": round(time.perf_counter() - start, 1)}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", nargs="+", default=DEFAULT_CARDS, choices=sorted(CASES))
    ap.add_argument("--turns", type=int, default=3, help="max client messages per conversation")
    ap.add_argument("--seed", type=int, default=34)
    a = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    TICKETS_DB.unlink(missing_ok=True)
    store.use_db(TICKETS_DB)
    trace_path = trace.start_run()
    intake.load_models()
    warm = warm_up()
    if not warm["ok"]:
        print(f"Warning: {warm['warning']} ({warm['error']})")
    runs = []
    try:
        for card_id in a.cards:
            print(f"{card_id}:", flush=True)
            runs.append(run_conversation(card_id, a.turns, a.seed))
            print(f"  score {runs[-1]['score'].get('score')} ({runs[-1]['score'].get('expected_score')}) "
                  f"comment: {runs[-1]['score'].get('comment')}", flush=True)
    finally:
        store.use_db(store.DEFAULT_DB_PATH)
        TICKETS_DB.unlink(missing_ok=True)

    lines = ["# T34 — Client Simulator conversations with the center", "",
             f"Writer: {simulator.config()['model']} (Ollama) · scorer: CPU MiniLM (ONNX) · trace `{trace_path}`", ""]
    for r in runs:
        lines += [f"## {r['card']} ({r['company']}, user {r['user_id']}, {r['facts']})", ""]
        for s in r["steps"]:
            lines += [f"- **Client:** {s['client']}", f"- **Center** ({s['outcome']}, {s['status']}, "
                      f"{s['center_seconds']} s): {s['reply']}" + (f" — ERROR {s['error']}" if s["error"] else "")]
        lines += ["", f"Score: **{r['score'].get('score')}** / 5 (expected {r['score'].get('expected_score')}) — "
                  f"{r['score'].get('comment')}", ""]
    (OUT / "t34_simulator.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "t34_simulator.json").write_text(json.dumps({"trace": str(trace_path), "runs": runs}, indent=1,
                                                       ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Saved out/t34_simulator.md and .json   Trace: {trace_path}")


if __name__ == "__main__":
    main()
