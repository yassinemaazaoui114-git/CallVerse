"""Agents (T19 item 8): one card per agent of the pipeline, for the tickets created in the period (default All).

Intake, Agent A, Agent B, Coordinator, Reply writer: tickets and messages handled, proposals, the Coordinator's
outcomes (approved / sent back / escalated / to finance), errors, average seconds, tokens and the model(s) used.
Who did which step is explained at the top of callverse/console/reads.py.
"""

import console_ui as ui
import streamlit as st

from callverse.console import reads

ui.setup("Agents")   # without the supervisor login: only "please log in"

if not reads.ticket_ids():
    st.info(reads.NO_TICKETS)
    st.stop()
days = ui.period_picker("agents_period")

ROLE = {"intake": "Reads every message: reason, emotion, sentiment, priority, order id (local models).",
        "A": "Orders, delivery, notifications. Read tools + subscription proposals.",
        "B": "Refunds. Read tools + refund proposals; may ask Agent A.",
        "coordinator": "Rules, no LLM: checks every proposal, decides, and only then writes.",
        "writer": "Small local model: writes the reply from the decision; checked, template if it fails."}
SECONDS = {"intake": "avg seconds per message", "A": "avg model seconds per message",
           "B": "avg model seconds per message", "coordinator": "avg seconds", "writer": "avg seconds per reply"}

cards = reads.agents(days)
if not any(c["tickets"] for c in cards):
    st.info("No tickets in this period.")
for column, card in zip(st.columns(len(cards)), cards):
    with column, st.container(border=True):
        st.markdown(f"#### {card['name']}")
        st.caption(ROLE[card["agent"]])
        st.metric("Tickets handled", card["tickets"])
        rows = [("Messages", card["messages"]), ("Proposals", card["proposals"] if card["agent"] != "intake" else "—")]
        if card["agent"] in ("A", "B", "coordinator"):
            rows += [("Approved", card["approved"]), ("Sent back", card["sent_back"]),
                     ("Escalated", card["escalated"]), ("To finance", card["to_finance"])]
        rows += [("Errors", card["errors"]), (SECONDS[card["agent"]], ui.seconds_text(card["avg_seconds"])),
                 ("Tokens", f"{card['tokens']:,}")]
        st.markdown("".join(f"<div class='cv-card-line'><span>{k}</span><b>{v}</b></div>" for k, v in rows),
                    unsafe_allow_html=True)
        st.caption("Models: " + (", ".join(card["models"]) or "—"))
st.caption("Proposals of the Coordinator = proposals it reviewed. Errors = refused tool calls or proposals, a model "
           "that failed (the next one of its list was used), refused writes, reply-writer errors.")
