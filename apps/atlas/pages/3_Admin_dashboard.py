"""Admin dashboard (T22): Atlas's business view for atlas_admin (permission view_dashboard). Read only.

Numbers from callverse/data/atlas/atlas_app_reads.py, for the last 7 / 30 days or all (default all) of the simulation
clock. Charts with Altair (comes with Streamlit, no new library).
"""

import altair as alt
import atlas_ui as ui
import streamlit as st

from callverse.data.atlas import atlas_app_reads as reads

ui.admin_setup("Admin dashboard", "view_dashboard")   # without the permission: only "please log in"

SKY, ORANGE = "#0EA5E9", "#F97316"
labels = list(reads.PERIODS)
period = st.radio("Period", labels, index=labels.index(reads.DEFAULT_PERIOD), horizontal=True, key="dash_period")
d = reads.dashboard(reads.PERIODS[period])
st.caption(f"{'From ' + d['start'] if d['start'] else 'All dates'} to {d['today']} (simulation clock) · bookings counted "
           "by booked date, flights by departure date")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Hotel cancellation rate", f"{d['hotel_cancellation_rate']} %")
c2.metric("Flight delay rate", f"{d['flight_delay_rate']} %")
c3.metric("Flight cancellation rate", f"{d['flight_cancellation_rate']} %")
c4.metric("Refunds paid", f"{d['refunds_paid']['count']} · {ui.tnd(d['refunds_paid']['tnd'])}")
c5.metric("Compensation paid", f"{d['compensation_paid']['count']} · {ui.tnd(d['compensation_paid']['tnd'])}")


def status_chart(rows: list[dict], color: str) -> None:
    st.altair_chart(alt.Chart(alt.Data(values=rows)).mark_bar(color=color).encode(
        x=alt.X("bookings:Q", title="bookings"), y=alt.Y("status:N", sort="-x", title=None),
        tooltip=["status:N", "bookings:Q"]), use_container_width=True)


left, right = st.columns(2)
with left:
    st.subheader(f"Hotel bookings by status ({d['hotel_bookings']})")
    status_chart(d["hotel_by_status"], SKY)
with right:
    st.subheader(f"Flight bookings by status ({d['flight_bookings']})")
    status_chart(d["flight_by_status"], ORANGE)

left, right = st.columns(2)
with left:
    st.subheader(f"Upcoming arrivals, until {d['upcoming_until']} ({len(d['upcoming_arrivals'])})")
    st.dataframe(d["upcoming_arrivals"], hide_index=True, use_container_width=True)
with right:
    st.subheader(f"Upcoming departures, until {d['upcoming_until']} ({len(d['upcoming_departures'])})")
    st.dataframe(d["upcoming_departures"], hide_index=True, use_container_width=True)
