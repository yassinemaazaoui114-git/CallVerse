"""Admin dashboard (T18): ShopNova's business view for the admin (permission view_dashboard). Read only.

Numbers from callverse/data/admin_reads.py, for the last 7 / 30 / 90 days of the simulation clock (default 30).
Charts with Altair (comes with Streamlit, no new library).
"""

import altair as alt
import shopnova_ui as ui
import streamlit as st

from callverse.data import admin_reads, shop_reads

ui.admin_setup("Admin dashboard", "view_dashboard")   # without the permission: only "please log in"

NAVY, CORAL = "#1F2A44", "#FF6B4A"
days = st.radio("Period", admin_reads.PERIODS, index=admin_reads.PERIODS.index(admin_reads.DEFAULT_PERIOD),
                format_func=lambda d: f"Last {d} days", horizontal=True, key="dash_days")
d = admin_reads.dashboard(days)
st.caption(f"From {d['start']} to {d['today']} (simulation clock) · orders counted by order date")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Sales", ui.tnd(d["sales_tnd"]))
c2.metric("Orders", d["orders"])
c3.metric("Late deliveries", d["late"])
c4.metric("Stuck at depot", d["stuck"])
c5.metric("Refunds paid", f"{d['refunds_paid']['count']} · {ui.tnd(d['refunds_paid']['tnd'])}")

st.subheader("Sales per day (TND)")
st.altair_chart(alt.Chart(alt.Data(values=d["sales_per_day"])).mark_bar(color=CORAL).encode(
    x=alt.X("day:T", title=None), y=alt.Y("sales_tnd:Q", title="TND"),
    tooltip=["day:T", "sales_tnd:Q"]), use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Orders by status")
    st.altair_chart(alt.Chart(alt.Data(values=d["orders_by_status"])).mark_bar(color=NAVY).encode(
        x=alt.X("orders:Q", title="orders"), y=alt.Y("status:N", sort="-x", title=None),
        tooltip=["status:N", "orders:Q"]), use_container_width=True)
with right:
    st.subheader("Review scores")
    avg = f"{d['review_average']:.2f} / 5" if d["review_average"] is not None else "no reviews"
    st.caption(f"Average {avg} · {d['review_count']} reviews")
    st.altair_chart(alt.Chart(alt.Data(values=d["review_scores"])).mark_bar(color=CORAL).encode(
        x=alt.X("score:O", title="score"), y=alt.Y("count:Q", title="reviews"),
        tooltip=["score:O", "count:Q"]), use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Top 10 products (quantity sold)")
    st.dataframe(d["top_products"], hide_index=True, use_container_width=True)
with right:
    st.subheader("Top categories (quantity sold)")
    st.dataframe([{"category": shop_reads.category_name(c["category"]), "qty": c["qty"]} for c in d["top_categories"]],
                 hide_index=True, use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader(f"Low stock (≤ {admin_reads.LOW_STOCK})")
    if d["low_stock"]:
        st.dataframe(d["low_stock"], hide_index=True, use_container_width=True)
    else:
        st.caption("No active product is low on stock.")
with right:
    st.subheader("Late deliveries")
    st.dataframe(d["late_orders"], hide_index=True, use_container_width=True)
