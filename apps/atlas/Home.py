"""Atlas Travel app, home page (T22). Start: .\\start_atlas.ps1 (or see README). Port 8503, 127.0.0.1 only."""

import atlas_ui as ui
import streamlit as st

user = ui.setup("Home")

st.markdown('<div class="at-hero"><h1>Welcome to Atlas Travel ✈</h1>'
            '<p>Hotel stays in Portugal and flights in the US, for Tunisian travellers.</p></div>',
            unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1, st.container(border=True):
    st.markdown("### 🧳 My bookings")
    st.write("Your flights and hotel stays, with their refunds and compensation.")
    st.page_link("pages/1_My_bookings.py", label="See my bookings", icon="➡️")
with col2, st.container(border=True):
    st.markdown("### 💬 Help chat")
    st.write("A delay, a cancellation, a refund? Our assistant answers.")
    st.page_link(ui.HELP_PAGE, label="Open the chat", icon="➡️")

if user is None:
    st.info("Log in (left sidebar) to see your bookings and chat with us.")
ui.help_button()
