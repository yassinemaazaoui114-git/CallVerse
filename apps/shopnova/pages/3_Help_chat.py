"""Help chat (T17): the user talks to CallVerse through the web chat channel, one ticket per chat.

The page shows the current ticket's messages (from callverse.db), the ticket number, the live steps while
CallVerse works ("Checking your order…"), and a "New chat" button (the next message starts a new ticket).
One input box only. After "Ask about this order" (My orders) a small label "About order N" is shown, and the
channel adds that order number to a message that names none (F1).
"""

import shopnova_ui as ui
import streamlit as st

from callverse.auth import accounts
from callverse.channels import web_chat
from callverse.tickets import store

ui.setup("Help chat")
st.title("Help chat")
user = accounts.require_role("user")

# The chat's ticket: kept in this browser session; after a reload, the user's latest ticket that is still open.
if "chat_ticket_id" not in st.session_state:
    current = store.current_ticket(ui.COMPANY, user["user_id"])
    st.session_state["chat_ticket_id"] = current["id"] if current else None
ticket = store.get_ticket(st.session_state["chat_ticket_id"]) if st.session_state["chat_ticket_id"] else None
if ticket and ticket["user_id"] != user["user_id"]:   # never show another user's ticket (e.g. after a re-login)
    ticket = st.session_state["chat_ticket_id"] = None

head, button = st.columns([4, 1])
if ticket:
    head.markdown(f"Ticket **{ticket['id']}** &nbsp; <span class='sn-badge'>{ticket['status']}</span>",
                  unsafe_allow_html=True)
else:
    head.markdown("New conversation: ask us about an order, a delivery, a refund or a return.")
if button.button("New chat", key="new_chat"):
    st.session_state["chat_ticket_id"] = None
    st.session_state.pop("chat_order", None)
    st.rerun()
about = st.session_state.get("chat_order")
if about:
    st.caption(f"📦 About order {about}")

if ticket:
    for m in store.messages(ticket["id"]):
        with st.chat_message("user" if m["sender"] == "user" else "assistant"):
            st.write(m["text"])


def answer(text: str) -> None:
    """Send one message through the channel, showing the live steps while waiting."""
    sender = accounts.check_role(st.session_state, "user")   # checked again just before CallVerse acts
    if sender is None:
        st.error(accounts.LOGIN_MESSAGE)
        return
    with st.chat_message("user"):
        st.write(text)
    with st.chat_message("assistant"):
        with st.status("Reading your message…", expanded=False) as status:
            out = web_chat.send(sender["user_id"], ui.COMPANY, text, ticket_id=st.session_state["chat_ticket_id"],
                                on_step=lambda said: status.update(label=said), about_order=about)
            status.update(label="Done", state="complete")
    st.session_state["chat_ticket_id"] = out["ticket_id"]
    st.rerun()   # show the conversation from the tickets store (the reply included)


typed = st.chat_input("Type your message…")
if typed and typed.strip():
    answer(typed.strip())
