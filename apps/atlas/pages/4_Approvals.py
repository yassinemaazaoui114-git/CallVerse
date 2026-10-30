"""Approvals (T22): the Atlas admin's queue (permission approve_refunds). A refund above 1,500 TND and every compensation
(rule AT-ESC-01) wait here. Only Atlas's cases: store.approvals(company=...), and approvals.decide refuses any other.

Waiting first (ticket, booking, client, action, amount, rule, the agent's facts, the code's confirmation decision), then
the decided ones. Approve (reason optional) / Refuse (reason required). The decision itself is made by
callverse/channels/approvals.py: it re-checks the data, writes through atlas writes.py (the decision, the money, any
booking change and the admin log line in ONE transaction) and writes the new reply. The reason is never shown to the client.
"""

import atlas_ui as ui
import streamlit as st

from callverse.auth import accounts
from callverse.channels import approvals
from callverse.data.atlas import atlas_app_reads
from callverse.tickets import store

ui.admin_setup("Approvals", "approve_refunds")   # without the permission: only "please log in"


def decide(approval_id: int, approve: bool) -> None:
    admin = accounts.check_permission(st.session_state, "approve_refunds", ui.COMPANY)   # again, just before deciding
    if admin is None:
        out = {"error": accounts.LOGIN_MESSAGE}
    else:
        out = approvals.decide(approval_id, admin["username"], approve, st.session_state.get(f"reason_{approval_id}"),
                               company=ui.COMPANY)
    st.session_state["approval_result"] = (approval_id, out)


if "approval_result" in st.session_state:
    approval_id, out = st.session_state.pop("approval_result")
    if "error" in out:
        st.error(f"Approval {approval_id}: nothing was done. {out['error']}")
    else:
        st.success(f"Approval {approval_id}: {out['approval']['status']}. Ticket {out['ticket']['id']} is now "
                   f"{out['ticket']['status']}; the client got a new reply.")

pending = store.approvals("pending", company=ui.COMPANY)
st.subheader(f"Waiting ({len(pending)})")
if not pending:
    st.caption("No case is waiting for approval.")
for a in pending:
    f = atlas_app_reads.approval_facts(a)
    with st.container(border=True):
        st.markdown(f"#### {a['action'].capitalize()} of {ui.tnd(a['amount'])} · {a['booking_type']} booking "
                    f"{a['order_id']} · {f['user_name'] or 'unknown client'}")
        st.caption(f"Ticket {a['ticket_id']} · proposal {a['proposal_id']} · rule {f['rule_id']}: {f['rule_title']}")
        st.markdown(f"Confirmed by code: **{f['confirmation']}**")
        with st.expander("The agent's facts (facts_used)"):
            st.json(f["facts_used"])
        st.text_input("Reason (required to refuse; never shown to the client)", key=f"reason_{a['id']}")
        b1, b2 = st.columns(2)
        b1.button("Approve", key=f"approve_{a['id']}", type="primary", on_click=decide, args=(a["id"], True),
                  use_container_width=True)
        b2.button("Refuse", key=f"refuse_{a['id']}", on_click=decide, args=(a["id"], False), use_container_width=True)

decided = [a for a in store.approvals(company=ui.COMPANY) if a["status"] != "pending"]
st.subheader(f"Decided ({len(decided)})")
if decided:
    st.dataframe([{"id": a["id"], "ticket": a["ticket_id"], "booking": f"{a['booking_type']} {a['order_id']}",
                   "action": a["action"], "amount": a["amount"], "status": a["status"], "decided_by": a["decided_by"],
                   "decided_at": a["decided_at"], "reason": a["reason"]} for a in decided],
                 hide_index=True, use_container_width=True)
else:
    st.caption("No decision yet.")
