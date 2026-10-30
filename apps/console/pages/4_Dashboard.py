"""Dashboard (T19 item 9): the center's KPIs for the tickets created in the period (default All), computer time.

Numbers from callverse/console/reads.dashboard (read-only). Charts with Altair (comes with Streamlit).
"""

import altair as alt
import console_ui as ui
import streamlit as st

from callverse.console import reads

ui.setup("Dashboard")   # without the supervisor login: only "please log in"

if not reads.ticket_ids():
    st.info(reads.NO_TICKETS)
    st.stop()
days = ui.period_picker("dash_period")
d = reads.dashboard(days)
if not d["tickets"]:
    st.info("No tickets in this period.")
    st.stop()

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Tickets", d["tickets"])
c2.metric("Solved by the AI alone", f"{d['solved_ai_pct']}%", help=f"{d['solved_ai']} ticket(s): Solved, never "
          "escalated, no finance approval")
c3.metric("Escalated (Layer 2)", f"{d['escalated_pct']}%", help=f"{d['escalated']} ticket(s) passed to a human")
c4.metric("Sent to finance (Layer 3)", f"{d['finance_pct']}%", help=f"{d['finance']} ticket(s) with an approval")
c5.metric("Average reply time", ui.seconds_text(d["avg_reply_s"]),
          help=f"{d['replies_timed']} timed replies ({d['replies_untimed']} older replies without a time)")
c6.metric(f"Late replies (> {d['late_s']:.0f} s)", f"{d['late']} · {d['late_pct']}%")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Finance: approved / refused", f"{d['finance_approved']} / {d['finance_refused']}",
          help=f"{d['finance_pending']} still waiting")
c2.metric("Refunds paid", f"{d['refunds_tnd']:,.2f} TND",
          help=f"{d['refunds_paid']} refund(s) of these tickets; {d['finance_tnd']:,.2f} TND after a finance approval")
c3.metric("Satisfaction (reviews)", "—" if d["review_avg"] is None else f"{d['review_avg']} / 5",
          help=f"Average of {d['reviews']:,} ShopNova review scores")
c4.metric("Tokens per ticket (avg / max)", f"{d['tokens_avg']:,} / {d['tokens_max']:,}")
c5.metric("System tokens (apart)", f"{d['system_tokens']:,}", help="Quota-check pings: tokens spent for no ticket")
st.caption("Satisfaction = ShopNova's real Olist review scores (not per ticket yet: agent F will measure it later).")

g = d["groq_today"]
st.progress(min(1.0, g["total"] / g["limit"]) if g["limit"] else 0.0,
            text=f"Groq tokens used today: {g['total']:,} of {g['limit']:,} "
                 f"({g['tickets']:,} tickets + {g['system']:,} system)")

left, right = st.columns([2, 1])
with left:
    st.subheader("Tickets per day")
    st.altair_chart(alt.Chart(alt.Data(values=d["per_day"])).mark_bar().encode(
        x=alt.X("day:N", title=None), y=alt.Y("tickets:Q", title="tickets"),
        color=alt.Color("company:N", scale=alt.Scale(scheme="tealblues")),
        tooltip=["day:N", "company:N", "tickets:Q"]), use_container_width=True)
with right:
    st.subheader("Per company")
    st.altair_chart(alt.Chart(alt.Data(values=d["per_company"])).mark_bar(color=ui.TEAL).encode(
        x=alt.X("tickets:Q", title="tickets"), y=alt.Y("company:N", title=None),
        tooltip=["company:N", "tickets:Q"]), use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Tokens per ticket")
    st.altair_chart(alt.Chart(alt.Data(values=d["tokens_per_ticket"])).mark_bar(color=ui.TEAL).encode(
        x=alt.X("ticket:N", title=None, sort=None), y=alt.Y("tokens:Q", title="tokens"),
        tooltip=["ticket:N", "tokens:Q"]), use_container_width=True)
with right:
    st.subheader("Tickets by status")
    st.altair_chart(alt.Chart(alt.Data(values=d["by_status"])).mark_bar(color=ui.AMBER).encode(
        x=alt.X("tickets:Q", title="tickets"), y=alt.Y("status:N", sort="-x", title=None),
        tooltip=["status:N", "tickets:Q"]), use_container_width=True)
