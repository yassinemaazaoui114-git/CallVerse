"""Live tickets (T19 item 6): every ticket of every company, newest first, refreshed by itself every 10 seconds.

Columns: id, company, user (name from the company's data), reason, priority, status, lead agent, age (computer
time; "—" for a ticket made before T19). Filters: company, status, priority, agent. Click a row: Ticket detail.
"""

import console_ui as ui
import streamlit as st

from callverse.console import reads

ui.setup("Live tickets")   # without the supervisor login: only "please log in"

ALL = "All"
values = reads.filter_values()
c1, c2, c3, c4 = st.columns(4)
company = c1.selectbox("Company", [ALL] + values["company"], key="f_company")
status = c2.selectbox("Status", [ALL] + values["status"], key="f_status")
priority = c3.selectbox("Priority", [ALL] + values["priority"], key="f_priority")
agent = c4.selectbox("Lead agent", [ALL] + values["agent"], key="f_agent")
pick = lambda value: None if value == ALL else value   # noqa: E731


@st.fragment(run_every=10)
def tickets_table() -> None:
    """The table alone reruns every 10 s (st.fragment), so new tickets appear without touching the page."""
    if not reads.ticket_ids():
        st.info(reads.NO_TICKETS)
        return
    rows = reads.live_tickets(pick(company), pick(status), pick(priority), pick(agent))
    st.caption(f"{len(rows)} ticket(s) · refreshed every 10 s · click a row to see how the agents worked on it")
    if not rows:
        st.info("No ticket matches these filters.")
        return
    # A new key after each click: the old selection is forgotten, so coming back here does not open it again.
    n = st.session_state.setdefault("live_table_n", 0)
    event = st.dataframe(rows, hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key=f"live_table_{n}")
    if event.selection.rows:
        ui.open_ticket(rows[event.selection.rows[0]]["id"])
        st.session_state["live_table_n"] = n + 1
        st.switch_page(ui.DETAIL_PAGE)


tickets_table()
