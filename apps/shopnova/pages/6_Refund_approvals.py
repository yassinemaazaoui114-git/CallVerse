"""Refund approvals (T18): the REAL Layer 3 queue (permission approve_refunds). Refunds above 300 TND (R-ESC-01)
wait here for the ShopNova admin when the app runs with layer3 mode "queue".

Pending first (ticket, order, client, amount, rule, the agent's facts, the order's status / paid / already
refunded, days late), then the decided ones. Approve (reason optional) / Refuse (reason required). No amount limit.
The decision itself is made by callverse/channels/approvals.py (it re-checks the data, writes the refund through
writes.py and writes the new reply to the client). The admin's reason is never shown to the client.
"""

import shopnova_ui as ui
import streamlit as st

from callverse.auth import accounts
from callverse.channels import approvals
from callverse.data import admin_reads
from callverse.tickets import store

ui.admin_setup("Refund approvals", "approve_refunds")   # without the permission: only "please log in"


def decide(approval_id: int, approve: bool) -> None:
    admin = accounts.check_permission(st.session_state, "approve_refunds")   # checked again just before deciding
    if admin is None:
        out = {"error": accounts.LOGIN_MESSAGE}
    else:
        out = approvals.decide(approval_id, admin["username"], approve, st.session_state.get(f"reason_{approval_id}"))
    st.session_state["approval_result"] = (approval_id, out)


if "approval_result" in st.session_state:
    approval_id, out = st.session_state.pop("approval_result")
    if "error" in out:
        st.error(f"Approval {approval_id}: nothing was done. {out['error']}")
    else:
        st.success(f"Approval {approval_id}: {out['approval']['status']}. Ticket {out['ticket']['id']} is now "
                   f"{out['ticket']['status']}; the client got a new reply.")

pending = store.approvals("pending")
st.subheader(f"Waiting ({len(pending)})")
if not pending:
    st.caption("No refund is waiting for approval.")
for a in pending:
    f = admin_reads.approval_facts(a["order_id"], a["proposal_id"])
    with st.container(border=True):
        st.markdown(f"#### {ui.tnd(a['amount'])} · order {a['order_id']} · {f['user_name'] or 'unknown client'}")
        st.caption(f"Ticket {a['ticket_id']} · proposal {a['proposal_id']} · rule {f['rule_id']}: {f['rule_title']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Order status", f["order_status"] or "—")
        c2.metric("Paid", ui.tnd(f["paid"] or 0))
        c3.metric("Already refunded", ui.tnd(f["refunded_total"] or 0))
        c4.metric("Days late", f["days_late"] if f["days_late"] is not None else "—")
        with st.expander("The agent's facts (facts_used)"):
            st.json(f["facts_used"])
        st.text_input("Reason (required to refuse; never shown to the client)", key=f"reason_{a['id']}")
        b1, b2 = st.columns(2)
        b1.button("Approve", key=f"approve_{a['id']}", type="primary", on_click=decide, args=(a["id"], True),
                  use_container_width=True)
        b2.button("Refuse", key=f"refuse_{a['id']}", on_click=decide, args=(a["id"], False), use_container_width=True)

decided = [a for a in store.approvals() if a["status"] != "pending"]
st.subheader(f"Decided ({len(decided)})")
if decided:
    st.dataframe([{k: a[k] for k in ("id", "ticket_id", "order_id", "amount", "status", "decided_by", "decided_at",
                                     "reason")} for a in decided], hide_index=True, use_container_width=True)
else:
    st.caption("No decision yet.")
