"""Records (T22): Atlas's tables for atlas_admin (permission view_dashboard). READ ONLY: no editing in T22.

One tab per table, each with a search box and 50 rows per page, and the admin log (the last 50 decisions).
"""

import atlas_ui as ui
import streamlit as st

from callverse.data.atlas import atlas_app_reads as reads

ui.admin_setup("Records", "view_dashboard")   # without the permission: only "please log in"


def table(kind: str, read) -> None:
    """Search box + one page of 50 rows of a table. read(search, page) -> {items, total, page, pages}."""
    col1, col2 = st.columns([3, 1])
    search = col1.text_input("Search", key=f"{kind}_search")
    found = read(search, st.session_state.get(f"{kind}_page", 1))
    st.session_state[f"{kind}_page"] = found["page"]   # kept inside 1..pages (set before the widget is drawn)
    col2.number_input(f"Page (of {found['pages']})", min_value=1, max_value=found["pages"], step=1, key=f"{kind}_page")
    st.caption(f"{found['total']} rows · {reads.PAGE_SIZE} per page")
    st.dataframe(found["items"], hide_index=True, use_container_width=True)


hotels, flights, users, refunds, compensation, log = st.tabs(
    ["Hotel bookings", "Flight bookings", "Users", "Refunds", "Compensation", "Admin log"])
with hotels:
    table("hotels", reads.hotel_bookings_page)
with flights:
    table("flights", reads.flight_bookings_page)
with users:
    table("users", reads.users_page)
with refunds:
    table("refunds", reads.refunds_page)
with compensation:
    table("compensations", reads.compensations_page)
with log:
    st.caption("The last 50 admin decisions (who, when, before / after).")
    st.dataframe(reads.admin_log(50), hide_index=True, use_container_width=True)
