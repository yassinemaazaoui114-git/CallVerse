"""ShopNova app, home page (T17). Start: .\\start_shopnova.ps1 (or see README). Port 8501, 127.0.0.1 only."""

import shopnova_ui as ui
import streamlit as st

user = ui.setup("Home")

st.markdown('<div class="sn-hero"><h1>Welcome to ShopNova ✦</h1>'
            '<p>Phones, watches, audio, computers and more, delivered to the main cities of Tunisia.'
            ' Pay by card or cash on delivery.</p></div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1, st.container(border=True):
    st.markdown("### 🛍️ Shop")
    st.write("Browse the catalogue and buy.")
    st.page_link("pages/1_Shop.py", label="Go to the shop", icon="➡️")
with col2, st.container(border=True):
    st.markdown("### 📦 My orders")
    st.write("Follow your orders, dates and refunds.")
    st.page_link("pages/2_My_orders.py", label="See my orders", icon="➡️")
with col3, st.container(border=True):
    st.markdown("### 💬 Help chat")
    st.write("Questions about an order? Our assistant answers.")
    st.page_link(ui.HELP_PAGE, label="Open the chat", icon="➡️")

if user is None:
    st.info("Log in (left sidebar) to buy, see your orders and chat with us.")
ui.help_button()
