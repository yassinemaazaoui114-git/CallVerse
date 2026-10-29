"""Manage (T18): the admin's tables and forms. One tab per kind of data, each with its own permission:
Products (edit_catalogue) · Orders (edit_orders) · Users (edit_users) · Refunds (view only, view_dashboard)
· Admin log (the last 50 admin_actions, view_dashboard).

Every table: a search box and 50 rows per page. Every write goes through writes.py (its input checks), after
require_permission(...) is checked AGAIN just before it; a refused write shows its reason to the admin.
Nothing is deleted: a product is deactivated (it leaves the shop), an order is cancelled.
"""

import shopnova_ui as ui
import streamlit as st

from callverse.auth import accounts
from callverse.data import admin_reads, writes
from callverse.data.seed import STATUS_MOVES

ui.admin_setup("Manage", "view_dashboard")   # without the permission: only "please log in"


def table(kind: str, read) -> None:
    """Search box + one page of 50 rows of a table. read(search, page) -> {items, total, page, pages}."""
    col1, col2 = st.columns([3, 1])
    search = col1.text_input("Search", key=f"{kind}_search")
    found = read(search, st.session_state.get(f"{kind}_page", 1))
    st.session_state[f"{kind}_page"] = found["page"]   # kept inside 1..pages (set before the widget is drawn)
    col2.number_input(f"Page (of {found['pages']})", min_value=1, max_value=found["pages"], step=1, key=f"{kind}_page")
    st.caption(f"{found['total']} rows · {admin_reads.PAGE_SIZE} per page")
    st.dataframe(found["items"], hide_index=True, use_container_width=True)


def show(result: dict, done: str) -> None:
    """Show the write's result: its error text if refused, else `done`."""
    if "error" in result:
        st.error(f"Not saved: {result['error']}")
    else:
        st.success(done)


def changed(current: dict, new: dict) -> dict:
    """Only the fields the admin really changed (an empty text box = the old empty value)."""
    return {k: v for k, v in new.items() if v != current[k] and not (v == "" and current[k] is None)}


def allowed(perm: str) -> bool:
    ok = accounts.check_permission(st.session_state, perm) is not None
    if not ok:
        st.warning("Your account may not use this tab.")
    return ok


def admin_name(perm: str) -> str:
    """Checked again just before a write: the admin's username, or the page stops ("please log in")."""
    return accounts.require_permission(perm)["username"]


products_tab, orders_tab, users_tab, refunds_tab, log_tab = st.tabs(
    ["Products", "Orders", "Users", "Refunds", "Admin log"])

with products_tab:
    if allowed("edit_catalogue"):
        table("products", admin_reads.products_page)
        categories = admin_reads.product_categories()
        left, right = st.columns(2)
        with left, st.form("product_add", clear_on_submit=True):
            st.markdown("**Add a product**")
            name = st.text_input("Name")
            category = st.selectbox("Category", categories)
            price = st.number_input("Price (TND)", min_value=0.0, max_value=float(writes.MAX_PRICE_TND), step=0.5,
                                    format="%.2f")
            stock = st.number_input("Stock", min_value=0, max_value=writes.MAX_STOCK, step=1)
            if st.form_submit_button("Add product"):
                out = writes.create_product(admin_name("edit_catalogue"), name, category, float(price), int(stock))
                show(out, f"Product {out.get('id')} added.")
        with right:
            st.markdown("**Edit a product**")
            pid = st.number_input("Product id", min_value=1, step=1, key="product_edit_id")
            current = admin_reads.product_row(int(pid))
            if current is None:
                st.caption("No product with this id.")
            else:
                with st.form("product_edit"):
                    name = st.text_input("Name", value=current["name"])
                    cat = st.selectbox("Category", categories, index=categories.index(current["category"])
                                       if current["category"] in categories else 0)
                    price = st.number_input("Price (TND)", min_value=0.0, max_value=float(writes.MAX_PRICE_TND),
                                            value=float(current["price"]), step=0.5, format="%.2f")
                    stock = st.number_input("Stock", min_value=0, max_value=writes.MAX_STOCK,
                                            value=int(current["stock"]), step=1)
                    if st.form_submit_button("Save changes"):
                        new = {"name": name, "category": cat, "price": round(float(price), 2), "stock": int(stock)}
                        out = writes.update_product(admin_name("edit_catalogue"), current["id"], **changed(current, new))
                        show(out, f"Product {current['id']} saved. Old orders keep their own price.")
                st.caption("On sale" if current["active"] else "Not on sale (deactivated)")
                if current["active"] and st.button("Remove from the shop (deactivate)", key="product_deactivate"):
                    show(writes.deactivate_product(admin_name("edit_catalogue"), current["id"]),
                         f"Product {current['id']} is not on sale any more.")
                if not current["active"] and st.button("Put back in the shop", key="product_reactivate"):
                    show(writes.reactivate_product(admin_name("edit_catalogue"), current["id"]),
                         f"Product {current['id']} is on sale again.")

with orders_tab:
    if allowed("edit_orders"):
        table("orders", admin_reads.orders_page)
        st.markdown("**Change an order's status** (only the allowed moves; cancel only before shipping; "
                    "refunds go through Refund approvals)")
        oid = st.number_input("Order id", min_value=1, value=4511, step=1, key="order_edit_id")
        order = admin_reads.order_row(int(oid))
        if order is None:
            st.caption("No order with this id.")
        else:
            moves = list(STATUS_MOVES.get(order["status"], ())) + (
                ["cancelled"] if order["status"] in writes.ADMIN_CANCEL_FROM else [])
            st.caption(f"Order {order['id']} · user {order['user_id']} · status **{order['status']}** · "
                       f"total {ui.tnd(order['total'])}")
            if not moves:
                st.caption("No status change is allowed from here.")
            else:
                with st.form("order_status"):
                    new = st.selectbox("New status", moves)
                    if st.form_submit_button("Change status"):
                        show(writes.admin_set_order_status(admin_name("edit_orders"), order["id"], new),
                             f"Order {order['id']} is now {new}.")

with users_tab:
    if allowed("edit_users"):
        table("users", admin_reads.users_page)
        cities = admin_reads.cities()
        left, right = st.columns(2)
        with left, st.form("user_add", clear_on_submit=True):
            st.markdown("**Add a client** (no login is created)")
            name = st.text_input("Name")
            email = st.text_input("Email")
            phone = st.text_input("Phone (8 digits)")
            city = st.selectbox("City", cities)
            if st.form_submit_button("Add client"):
                out = writes.create_user(admin_name("edit_users"), name, email, phone, city)
                show(out, f"Client {out.get('id')} added.")
        with right:
            st.markdown("**Edit a client**")
            uid = st.number_input("User id", min_value=1, step=1, key="user_edit_id")
            current = admin_reads.user_row(int(uid))
            if current is None:
                st.caption("No client with this id.")
            else:
                with st.form("user_edit"):
                    name = st.text_input("Name", value=current["name"])
                    email = st.text_input("Email", value=current["email"] or "")
                    phone = st.text_input("Phone", value=current["phone"] or "")
                    options = [None, *cities]   # None: users 1-5 have no city
                    city = st.selectbox("City", options, index=options.index(current["city"])
                                        if current["city"] in options else 0,
                                        format_func=lambda c: "(none)" if c is None else c)
                    if st.form_submit_button("Save changes"):
                        new = {"name": name, "email": email, "phone": phone, "city": city}
                        out = writes.update_user(admin_name("edit_users"), current["id"], **changed(current, new))
                        show(out, f"Client {current['id']} saved.")

with refunds_tab:
    if allowed("view_dashboard"):
        st.caption("View only: refunds are written by the Coordinator or through Refund approvals.")
        table("refunds", admin_reads.refunds_page)

with log_tab:
    if allowed("view_dashboard"):
        st.caption("The last 50 admin actions (who, when, before / after).")
        st.dataframe(admin_reads.admin_log(50), hide_index=True, use_container_width=True)
