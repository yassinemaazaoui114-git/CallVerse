"""My bookings (T22): the logged-in user's OWN bookings only, with their refunds and compensation."""

import atlas_ui as ui
import streamlit as st

from callverse.data.atlas import atlas_app_reads

user = ui.user_setup("My bookings")   # without an Atlas user login the page shows only "please log in"


def ask_about(booking_id: int) -> None:
    st.session_state["chat_booking"] = booking_id   # Help chat shows "About booking N"


def ask_button(column, booking_id: int) -> None:
    if column.button("Ask about this booking", key=f"ask_{booking_id}", on_click=ask_about, args=(booking_id,)):
        st.switch_page(ui.HELP_PAGE)


def money_lines(booking: dict) -> None:
    """Under each booking: its refunds and compensation (amount, status, date)."""
    for r in booking["refunds"]:
        st.markdown(f"↩️ Refund of **{ui.tnd(r['amount'])}** · {r['status']} · {r['created_at']}")
    for c in booking["compensations"]:
        st.markdown(f"💶 Compensation of **{ui.tnd(c['amount'])}** · {c['status']} · {c['created_at']}")


ui.unread_notice(user, switch=True)   # "💬 New reply on T-00NN" (e.g. finance decided)
bookings = atlas_app_reads.my_bookings(user["user_id"])   # the user id comes from the accounts file, not the browser
if not bookings["flights"] and not bookings["hotels"]:
    st.info("You have no bookings yet.")

if bookings["flights"]:
    st.subheader("✈️ Flights")
for f in bookings["flights"]:
    with st.container(border=True):
        top, right = st.columns([3, 1])
        top.markdown(f"#### Booking {f['id']} · {f['route']}")
        top.caption(f"{f['airline']} · flight {f['flight_number']} · departure {f['departure']}")
        ask_button(right, f["id"])
        st.markdown(f"<span class='at-badge'>{f['situation']}</span> &nbsp; Paid {ui.tnd(f['paid'])}",
                    unsafe_allow_html=True)
        money_lines(f)

if bookings["hotels"]:
    st.subheader("🏨 Hotel stays")
for h in bookings["hotels"]:
    with st.container(border=True):
        top, right = st.columns([3, 1])
        top.markdown(f"#### Booking {h['id']} · {h['hotel']}")
        top.caption(f"Arrival {h['arrival']} · {h['nights']} nights · room booked {h['room_booked']}, "
                    f"room given {h['room_given']} · {h['deposit']}")
        ask_button(right, h["id"])
        st.markdown(f"<span class='at-badge'>{h['status']}</span> &nbsp; **Total {ui.tnd(h['total'])}** · "
                    f"paid {ui.tnd(h['paid'])}", unsafe_allow_html=True)
        money_lines(h)

ui.help_button()
