"""Ticket detail (T19 item 7): one ticket, the conversation, then HOW CallVerse worked on each user message.

For each user message, a step-by-step timeline from the saved steps: Intake → route / hand-over → each tool call
and policy search (rules returned) → proposal → each Coordinator check ✅/❌ + the decision and why → Layer 3 →
reply writer (first try / retry / template) → what was written. Identity-check and quota steps are shown too.
Per message: tokens (model calls, by model) and seconds. The raw step data is in a closed "details" expander.
"""

import console_ui as ui
import streamlit as st

from callverse.console import reads

ui.setup("Ticket detail")   # without the supervisor login: only "please log in"

ids = reads.ticket_ids()
if not ids:
    st.info(reads.NO_TICKETS)
    st.stop()
chosen = st.session_state.get(ui.TICKET_KEY)
ticket_id = st.selectbox("Ticket", ids, index=ids.index(chosen) if chosen in ids else 0, key="detail_ticket")
ui.open_ticket(ticket_id)
detail = reads.ticket_detail(ticket_id)
t = detail["ticket"]

badges = "".join(f"<span class='cv-badge'>{v}</span>" for v in
                 (t["status"], t["company"], f"priority {t['priority'] or '—'}", f"lead agent {t['lead_agent'] or '—'}"))
st.markdown(f"### {t['id']} · {detail['user']} &nbsp; {badges}", unsafe_allow_html=True)
st.caption(f"Reason {t['main_reason'] or '—'} · created {t.get('created_real') or '—'} "
           f"({reads.age(t.get('created_real'))} ago) · updated {t.get('updated_real') or '—'} · "
           f"simulation time {t['created_at']}")
for a in detail["approvals"]:
    st.markdown(f"🏦 Finance approval {a['id']}: **{a['status']}** · {a['amount']:.2f} TND on order {a['order_id']}"
                + (f" · decided by {a['decided_by']}" if a["decided_by"] else ""))

st.subheader("Conversation")
for turn in detail["turns"]:
    for m in ([turn["message"]] if turn["message"] else []) + turn["replies"]:
        with st.chat_message("user" if m["sender"] == "user" else "assistant"):
            st.markdown(m["text"])
            took = f" · reply took {ui.seconds_text(m.get('seconds'))}" if m["sender"] == "assistant" else ""
            st.caption(f"{m.get('at_real') or '—'}{took}")

st.subheader("How CallVerse worked on each message")
for number, turn in enumerate(detail["turns"], start=1):
    with st.container(border=True):
        text = turn["message"]["text"] if turn["message"] else "(no user message)"
        st.markdown(f"**Message {number}:** “{text}”")
        by_model = " · ".join(f"{model} {n:,}" for model, n in turn["tokens"].items()) or "no model call"
        seconds = ", ".join(ui.seconds_text(s) for s in turn["seconds"]) or "—"
        st.caption(f"Tokens: **{turn['tokens_total']:,}** ({by_model}) · reply seconds: {seconds}")
        if not turn["steps"]:
            st.caption("No steps saved for this message.")
        lines = []
        for step in turn["steps"]:
            icon, title, said = reads.describe_step(step)
            who = reads.AGENTS.get(step["actor"]) if step.get("actor") else step.get("agent")
            # Plain markdown (no HTML): a client's words inside a step can never change the page.
            lines.append(f"{icon} " + (f"`{who}` " if who else "") + title + (f" — {said}" if said else ""))
        st.markdown("  \n".join(lines))
        with st.expander("details (raw step data)", expanded=False):
            st.json([{k: s[k] for k in ("id", "step", "agent", "at", "at_real", "data") if k in s}
                     for s in turn["steps"]], expanded=False)
