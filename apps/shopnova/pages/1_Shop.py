"""Shop (T17): everyone can browse; buying needs a login (checked again just before the write)."""

import shopnova_ui as ui
import streamlit as st

from callverse.auth import accounts
from callverse.data import shop_reads
from callverse.data.writes import MAX_ORDER_QTY, create_order

user = ui.setup("Shop")
st.title("Shop")

PAYMENTS = {"card": "Card", "cash_on_delivery": "Cash on delivery"}


def choose(product_id: int) -> None:
    st.session_state["buy_id"] = product_id
    st.session_state.pop("bought", None)


def first_page() -> None:
    st.session_state["shop_page"] = 1   # a new search or category starts on page 1


def card(p: dict, section: str) -> None:
    """One product card: icon, name, category, price, stock, Buy. section = "featured" or "all" (widget keys)."""
    with st.container(border=True):
        st.markdown(f'<div class="sn-card-icon">{shop_reads.icon(p["category"])}</div>', unsafe_allow_html=True)
        st.markdown(f"**{p['name']}**")
        st.markdown(f'<span class="sn-muted">{shop_reads.category_name(p["category"])}</span>',
                    unsafe_allow_html=True)
        st.markdown(f'<span class="sn-price">{ui.tnd(p["price"])}</span>', unsafe_allow_html=True)
        st.caption(f"{p['stock']} in stock" if p["stock"] > 0 else "Out of stock")
        st.button("Buy", key=f"{section}_buy_{p['id']}", on_click=choose, args=(p["id"],), disabled=p["stock"] <= 0,
                  use_container_width=True)


def grid(products: list[dict], per_row: int, section: str) -> None:
    for start in range(0, len(products), per_row):
        for col, p in zip(st.columns(per_row), products[start:start + per_row]):
            with col:
                card(p, section)


def buy_panel() -> None:
    """The buy box for the chosen product. The login is checked here AND again before create_order."""
    product = shop_reads.product(st.session_state["buy_id"])
    if product is None:
        st.session_state.pop("buy_id", None)
        return
    with st.container(border=True):
        st.markdown(f"### Buy: {product['name']} · {ui.tnd(product['price'])}")
        if accounts.check_role(st.session_state, "user") is None:
            st.warning("Please log in to buy (left sidebar).")
            st.button("Close", key="buy_close", on_click=lambda: st.session_state.pop("buy_id", None))
            return
        qty = st.number_input("Quantity", min_value=1, max_value=MAX_ORDER_QTY, value=1, step=1, key="buy_qty")
        payment = st.radio("Payment", list(PAYMENTS), format_func=PAYMENTS.get, horizontal=True, key="buy_pay")
        st.caption("No real payment in this demo. Delivery fee: 0 TND. Cash on delivery: you pay when it arrives.")
        col1, col2 = st.columns(2)
        if col1.button("Confirm order", type="primary", key="buy_confirm"):
            buyer = accounts.check_role(st.session_state, "user")   # checked again just before the write
            if buyer is None:
                st.error("Please log in to buy.")
                return
            out = create_order(buyer["user_id"], product["id"], int(qty), payment)
            if "error" in out:
                st.error(f"Sorry, the order was not placed: {out['error']}.")
            else:
                st.session_state["bought"] = out["id"]
                st.session_state.pop("buy_id", None)
                st.rerun()
        col2.button("Cancel", key="buy_cancel", on_click=lambda: st.session_state.pop("buy_id", None))


if st.session_state.get("bought"):
    st.success(f"Thank you! Your order {st.session_state['bought']} is placed (status: being prepared). "
               "See it in My orders.")
if st.session_state.get("buy_id"):
    buy_panel()

st.subheader("✨ Featured")
grid(shop_reads.featured(), per_row=3, section="featured")

st.subheader("All products")
names = {c: f"{shop_reads.icon(c)} {shop_reads.category_name(c)}" for c in shop_reads.categories()}
col1, col2 = st.columns([2, 1])

search = col1.text_input("Search", placeholder="e.g. watch, audio, charger", key="shop_search", on_change=first_page)
category = col2.selectbox("Category", [None, *names], format_func=lambda c: "All categories" if c is None else names[c],
                          key="shop_category", on_change=first_page)
found = shop_reads.products(search=search, category=category, page=st.session_state.get("shop_page", 1))
if found["total"] == 0:
    st.info("No product matches your search.")
else:
    st.session_state["shop_page"] = found["page"]   # kept inside 1..pages (set before the widget is drawn)
    st.number_input(f"Page (of {found['pages']})", min_value=1, max_value=found["pages"], step=1, key="shop_page")
    st.caption(f"{found['total']} products · {shop_reads.PAGE_SIZE} per page")
    grid(found["items"], per_row=4, section="all")

ui.help_button()
