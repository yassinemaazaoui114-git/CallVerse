"""ShopNova app, the start file (T18): Streamlit's st.navigation with all pages.

Start: .\\start_shopnova.ps1 (it runs `streamlit run app.py`). Port 8501, 127.0.0.1 only.
The built-in page list is hidden; each page draws the sidebar menu itself (shopnova_ui.setup), with the admin
pages only for an account that has their permission. Every page still checks the login / permission itself.
"""

import shopnova_ui as ui
import streamlit as st

st.session_state[ui.NAV_FLAG] = True   # tells the pages to draw the sidebar menu
st.navigation(ui.all_pages(), position="hidden").run()
