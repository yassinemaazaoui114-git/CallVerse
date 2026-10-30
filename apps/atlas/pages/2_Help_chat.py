"""Help chat (T22): the same page as ShopNova's, with company="atlas": one ticket per chat, its number and status, the
live steps while CallVerse works, "New chat". After "Ask about this booking" a label "About booking N" is shown until
"New chat", and the channel adds that number to a message that names none. "💬 New reply on T-00NN" for a reply on
another ticket (e.g. finance's decision); showing a ticket marks its new reply as read.
"""

import atlas_ui as ui
import streamlit as st

from callverse.auth import accounts
from callverse.channels import web_chat
from callverse.tickets import store

user = ui.user_setup("Help chat")

# The chat's ticket: kept in this browser session; after a reload, the user's latest ticket that is still open.
if "chat_ticket_id" not in st.session_state:
    current = store.current_ticket(ui.COMPANY, user["user_id"])
    st.session_state["chat_ticket_id"] = current["id"] if current else None
ticket = store.get_ticket(st.session_state["chat_ticket_id"]) if st.session_state["chat_ticket_id"] else None
if ticket and (ticket["user_id"] != user["user_id"] or ticket["company"] != ui.COMPANY):
    ticket = st.session_state["chat_ticket_id"] = None   # never show another user's ticket (e.g. after a re-login)

head, button = st.columns([4, 1])
if ticket:
    head.markdown(f"Ticket **{ticket['id']}** &nbsp; <span class='at-badge'>{ticket['status']}</span>",
                  unsafe_allow_html=True)
else:
    head.markdown("New conversation: ask us about a booking, a delay, a cancellation, a refund or a compensation.")
if button.button("New chat", key="new_chat"):
    st.session_state["chat_ticket_id"] = None
    st.session_state.pop("chat_booking", None)
    st.rerun()
about = st.session_state.get("chat_booking")
if about:
    st.caption(f"📦 About booking {about}")

ui.unread_notice(user, shown_ticket=ticket["id"] if ticket else None)
if ticket:
    for m in store.messages(ticket["id"]):
        with st.chat_message("user" if m["sender"] == "user" else "assistant"):
            st.write(m["text"])
    if ticket["user_unread"]:
        store.set_unread(ticket["id"], False)   # the user has now seen the new reply


def answer(text: str) -> None:
    """Send one message through the channel, showing the live steps while waiting."""
    sender = accounts.check_role(st.session_state, "user", ui.COMPANY)   # checked again just before CallVerse acts
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
