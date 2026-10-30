"""CallVerse Console, the start file (T19): Streamlit's st.navigation with the 4 pages.

Start: .\\start_console.ps1 or Console.bat (they run `streamlit run app.py`). Port 8502, 127.0.0.1 only.
The built-in page list is hidden; each page draws the sidebar menu itself (console_ui.setup) and checks the
supervisor login itself. The Console loads no model: it only reads callverse.db and the company's data.
"""

import console_ui as ui
import streamlit as st

st.session_state[ui.NAV_FLAG] = True   # tells the pages to draw the sidebar menu
st.navigation(ui.all_pages(), position="hidden").run()
