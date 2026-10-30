"""Atlas Travel app, the start file (T22): Streamlit's st.navigation with all pages.

Start: .\\start_atlas.ps1 (it runs `streamlit run app.py`). Port 8503, 127.0.0.1 only.
The built-in page list is hidden; each page draws the sidebar menu itself (atlas_ui.setup), with only the pages this
account may see. Every page still checks the login, the role and the company itself.
"""

import atlas_ui as ui
import streamlit as st

st.session_state[ui.NAV_FLAG] = True   # tells the pages to draw the sidebar menu
st.navigation(ui.all_pages(), position="hidden").run()
