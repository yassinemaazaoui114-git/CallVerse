"""Notifier (story S3): sends ONE message per subscription when the order reaches the subscribed event.

How it works, step by step:
  1. reports.get_pending_notifications() lists the "waiting" subscriptions whose event has happened
     (e.g. the clock moved and order 4510 became "delivered");
  2. for each one, a "notify" decision is built by code: the fact (event, when) and the exact sentence
     the message must contain ("Your order 4510 has been delivered.");
  3. the SLM writes the message from that decision (same writer, same rule check, template if needed);
  4. "sending" = trace step notification_sent + the message in the returned list (no real SMS / e-mail
     in the prototype);
  5. writes.mark_subscription_sent() sets the subscription to "sent", so a second run sends nothing:
     the same subscription is never sent twice.

Why no agent here? Nothing needs to be decided: the subscription was already approved by the
Coordinator, and the event comes from the platform data. A fixed loop is cheaper and predictable.
"""

from callverse import trace
from callverse.data.reports import get_pending_notifications
from callverse.data.writes import mark_subscription_sent
from callverse.slm.writer import write_reply

# What the message must say, per event (the sentence is copied word for word by the SLM).
EVENT_SENTENCES = {
    "delivered": "Your order {id} has been delivered.",
    "out_for_delivery": "Your order {id} is out for delivery.",
    "shipped": "Your order {id} has been shipped.",
}

NEUTRAL_STYLE = {"formality": "neutral", "length": "short", "shouting": False, "emotion": "neutral",
                 "sentiment": "neutral"}


def notify_decision(pending: dict) -> dict:
    """The decision the SLM writes the notification from (facts from the platform only)."""
    order_id = pending["order_id"]
    return {"outcome": "notify", "action": "notify", "order_id": order_id, "rule_id": "R-NOT-01",
            "facts": {"event": pending["event"], "event_at": pending["event_at"]},
            "must_say": [EVENT_SENTENCES[pending["event"]].format(id=order_id)], "next_step": "",
            "style": NEUTRAL_STYLE}


def run_notifier(slm_chat_fn=None) -> list[dict]:
    """Send every pending notification once. Returns [{subscription_id, order_id, event, text, reply_source}]."""
    sent = []
    for pending in get_pending_notifications():
        decision = notify_decision(pending)
        written = write_reply(decision, chat_fn=slm_chat_fn)
        source = "template" if written["used_template"] else ("slm" if written["attempts"] == 1 else "slm_retry")
        message = {"subscription_id": pending["subscription_id"], "order_id": pending["order_id"],
                   "event": pending["event"], "text": written["reply"], "reply_source": source}
        trace.log("notification_sent", "notifier", {**message, "user_id": pending["user"]["id"]})
        mark_subscription_sent(pending["subscription_id"])
        sent.append(message)
    trace.log("notifier_run", "notifier", {"sent": len(sent)})
    return sent
