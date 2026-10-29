"""My orders (T17): the logged-in user's OWN orders only (status, dates, lines incl. Delivery, refunds)."""

import shopnova_ui as ui
import streamlit as st

from callverse.auth import accounts
from callverse.coordinator.coordinator import status_words
from callverse.data import shop_reads

ui.setup("My orders")
st.title("My orders")
user = accounts.require_role("user")   # without a user login the page shows only "please log in"


def ask_about(order_id: int) -> None:
    st.session_state["chat_order"] = order_id   # Help chat shows "About order N" (F1)


orders = shop_reads.user_orders(user["user_id"])   # the user id comes from the accounts file, not the browser
if not orders:
    st.info("You have no orders yet. Have a look at the shop!")
for o in orders:
    with st.container(border=True):
        top, right = st.columns([3, 1])
        top.markdown(f"#### Order {o['id']} &nbsp; <span class='sn-badge'>{status_words(o['status'])}</span>",
                     unsafe_allow_html=True)
        dates = [f"Ordered {o['order_date']}", f"promised {o['promised_date'] or '—'}"]
        dates.append(f"delivered {o['delivered_date']}" if o["delivered_date"] else "not delivered yet")
        top.caption(" · ".join(dates) + (f" · {o['carrier']} {o['tracking_number']}" if o["carrier"] else ""))
        if right.button("Ask about this order", key=f"ask_{o['id']}", on_click=ask_about, args=(o["id"],)):
            st.switch_page(ui.HELP_PAGE)
        lines = [{"Item": i["name"], "Qty": i["qty"], "Price": ui.tnd(i["price"])} for i in o["items"]]
        st.dataframe(lines, hide_index=True, use_container_width=True)
        paid = ui.tnd(o["paid"]) if o["paid"] else "cash on delivery (nothing paid yet)"
        st.markdown(f"**Total {ui.tnd(o['total'])}** · paid: {paid}")
        for r in o["refunds"]:
            st.markdown(f"↩️ Refund of **{ui.tnd(r['amount'])}** · {r['status']} · {r['created_at']}")

ui.help_button()
