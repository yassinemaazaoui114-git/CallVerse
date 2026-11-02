"""T34: real photos through the Help chat door (callverse.channels.web_chat.send with image=...), real models.

Usage (from the repo root; Ollama running; requirements-vision.txt installed, GPU for 4-bit):
    set CALLVERSE_AGENTS_SET=local
    python -m scripts.t34_photo_check

The 3 photos are real photos of the vision dataset (benchmarks/vision_qlora/manifest.jsonl), downloaded from their
pinned source revisions into out/t34_photos/ (sha256 checked against the manifest). The client messages are WRITTEN
for this check (one per photo). Fresh ShopNova + Atlas data per message; tickets in their own file
(out/t34_photo_tickets.db, deleted at the end). Output: out/t34_photo_check.json.
"""
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from callverse import trace  # noqa: E402
from callverse.channels import web_chat  # noqa: E402
from callverse.data import clock  # noqa: E402
from callverse.data.atlas.seed import seed as seed_atlas  # noqa: E402
from callverse.data.seed import seed as seed_shopnova  # noqa: E402
from callverse.intake import intake  # noqa: E402
from callverse.slm.writer import warm_up  # noqa: E402
from callverse.tickets import store  # noqa: E402
from callverse.tools.registry import run_tool  # noqa: E402

OUT = ROOT / "out"
PHOTOS = OUT / "t34_photos"
TICKETS_DB = OUT / "t34_photo_tickets.db"

MESSAGES = [
    {"id": "P1", "photo": "cv001.jpg", "sha256": "3055a67143ad4f8391caf9d1aef54ad95619a1b5758d599b8b372f99a032edb1",
     "what": "ShopNova, damaged (cracked phone screen)", "company": "shopnova", "user_id": 1, "order_id": 4509,
     "text": "My order 4509 arrived damaged, see the photo. I want a refund."},
    {"id": "P2", "photo": "cv025.jpg", "sha256": "4b7af5e0ad3f8fb897d23b31ff051d67a43e8c1e7954a2dec9135a84c6aeb3a4",
     "what": "ShopNova, NOT damaged (intact phone)", "company": "shopnova", "user_id": 1, "order_id": 4509,
     "text": "My order 4509 arrived damaged, see the photo. I want a refund."},
    {"id": "P3", "photo": "cv057.jpg", "sha256": "6f2f0ee470791b277028baafdd9e7d882017f44500aac4872a6fe2c91efa88b6",
     "what": "Atlas, damaged suitcase", "company": "atlas", "user_id": 5, "order_id": 7004,
     "text": "My suitcase arrived broken after my flight, booking 7004. See the photo."},
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    TICKETS_DB.unlink(missing_ok=True)
    store.use_db(TICKETS_DB)
    trace_path = trace.start_run()
    intake.load_models()
    warm_up()
    rows = []
    try:
        for m in MESSAGES:
            data = (PHOTOS / m["photo"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == m["sha256"], f"{m['photo']}: not the manifest's photo"
            seed_shopnova()
            seed_atlas()
            clock.reset()
            refunded_before = (run_tool("B", "get_refunds", {"order_id": m["order_id"]})["refunded_total"]
                               if m["company"] == "shopnova" else None)
            start = time.perf_counter()
            try:
                out, error = web_chat.send(m["user_id"], m["company"], m["text"], image=data), None
            except Exception as e:  # noqa: BLE001
                out, error = {}, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            seconds = round(time.perf_counter() - start, 1)
            ticket = store.get_ticket(out["ticket_id"]) if out.get("ticket_id") else {}
            photo_steps = [r["data"] for r in map(json.loads, Path(trace_path).read_text(encoding="utf-8").splitlines())
                           if r.get("step") == "vision_assessment"][-1:]   # what the photo check saw (last one)
            refunded_after = (run_tool("B", "get_refunds", {"order_id": m["order_id"]})["refunded_total"]
                              if m["company"] == "shopnova" else None)
            rows.append({**{k: m[k] for k in ("id", "what", "company", "order_id", "text", "photo")},
                         "outcome": out.get("outcome"), "status": out.get("status"), "reply": out.get("reply"),
                         "reply_source": out.get("reply_source"), "main_reason": ticket.get("main_reason"),
                         "photo_step": photo_steps, "refunded_before": refunded_before,
                         "refunded_after": refunded_after, "seconds": seconds, "error": error})
            print(f"{m['id']} {m['what']}: outcome={out.get('outcome')} reason={ticket.get('main_reason')} "
                  f"photo={[(p['assessment']['issue_type'], p['backend']) for p in photo_steps]} {seconds} s\n"
                  f"   reply: {out.get('reply')}", flush=True)
    finally:
        store.use_db(store.DEFAULT_DB_PATH)
        TICKETS_DB.unlink(missing_ok=True)
    (OUT / "t34_photo_check.json").write_text(json.dumps({"trace": str(trace_path), "rows": rows}, indent=1,
                                                         ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Saved out/t34_photo_check.json   Trace: {trace_path}")


if __name__ == "__main__":
    main()
