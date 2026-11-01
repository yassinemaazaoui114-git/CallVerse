// Refund approvals (ShopNova admin, step 4): the Layer 3 queue. Pending approvals with the order and
// proposal facts, Approve / Refuse with a reason and a confirmation that repeats the exact approval, amount,
// choice and reason; then the decided ones. The decision itself is made by the core
// (callverse.channels.approvals.decide: pending check, reason rule, the Coordinator's re-check on fresh data,
// one transaction, the new reply to the customer). This screen only shows what the API returns:
// - a decision in flight disables every other submission on that approval; a second click is not a second run
//   (the request id is kept, so asking again returns the recorded result);
// - a lost response or an error raised mid-decision is NOT retried: the screen reads the API's recorded state
//   (what was actually written: nothing / the company transaction / the approval record / the customer reply,
//   and whether a decision is still running) and says exactly that; "Confirm again" with the same request id
//   is offered only when nothing was written and nothing is running;
// - a refused re-check leaves the approval pending and shows the Coordinator's words;
// - an outcome the UI has never seen is shown as text.
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api.js";
import { useAuth } from "../auth.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad, words } from "../hooks.js";

function newClientId() {
  return (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `d-${Date.now()}-${Math.random()}`;
}

function statusClass(status) {
  if (status === "approved") return "badge-ok";
  if (status === "refused") return "badge-danger";
  if (status === "pending") return "badge-warn";
  return "badge-neutral";
}

export default function AdminApprovals() {
  const { expired } = useAuth();
  const [tab, setTab] = useState("pending");
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.approvals(tab, signal), [tab]);
  const [reasons, setReasons] = useState({});          // approval id -> reason typed
  const [confirm, setConfirm] = useState(null);         // {approval, approve, reason, clientId} waiting for "Confirm"
  const [inflight, setInflight] = useState(null);       // approval id being decided
  const inflightRef = useRef(null);                     // the same, readable synchronously (a double click)
  const [notice, setNotice] = useState(null);           // {kind: ok | refused | error | uncertain, approvalId, text, detail}
  const confirmRef = useRef(null);

  useEffect(() => { if (confirm && confirmRef.current) confirmRef.current.focus(); }, [confirm]);

  function ask(approval, approve) {
    const reason = (reasons[approval.id] || "").trim();
    if (!approve && !reason) {
      setNotice({ kind: "error", approvalId: approval.id, text: "A reason is required to refuse." });
      return;
    }
    setNotice(null);
    setConfirm({ approval, approve, reason, clientId: newClientId() });
  }

  async function submit() {
    if (!confirm || inflight || inflightRef.current) return;
    const { approval, approve, reason, clientId } = confirm;
    inflightRef.current = approval.id;
    setInflight(approval.id);
    try {
      const out = await api.decide(approval.id, { approve, reason, client_id: clientId });
      setConfirm(null);
      setNotice({ kind: "ok", approvalId: approval.id,
        text: `Approval ${approval.id}: ${words(out.approval && out.approval.status)}${out.recorded ? " (recorded earlier)" : ""}.`,
        detail: `Outcome ${words(out.outcome)} · ticket ${out.ticket ? `${out.ticket.id} is now ${words(out.ticket.status)}` : "—"}`
          + (out.refund ? ` · refund ${tnd(out.refund.amount)} written` : " · nothing paid") + " · the customer got a new reply." });
      setReasons((r) => ({ ...r, [approval.id]: "" }));
      reload();
    } catch (err) {
      if (err instanceof ApiError && err.code === "not_logged_in") { expired(); return; }
      if (err instanceof ApiError && err.code === "recheck_refused") {
        setConfirm(null);
        setNotice({ kind: "refused", approvalId: approval.id, text: `Approval ${approval.id}: the Coordinator's re-check refused it, nothing was written. It stays pending.`, detail: err.message });
      } else if (err instanceof ApiError && err.code === "decision_uncertain") {
        // the core raised after it started: the API re-read what was written; show THAT, never "nothing was done"
        setConfirm(null);
        showEvidence(approval, (err.body && err.body.evidence) || null, null, { approve, reason, clientId }, err.message);
      } else if (err instanceof ApiError && (err.code === "already_decided" || err.code === "decision_in_progress" || err.code === "client_id_reused")) {
        setConfirm(null);
        setNotice({ kind: "error", approvalId: approval.id, text: `Approval ${approval.id}: ${err.message}` });
        reload();
      } else if (err instanceof ApiError && err.code !== "unavailable") {
        // an explicit refusal by the core or the API (its contract: nothing written)
        setConfirm(null);
        setNotice({ kind: "error", approvalId: approval.id, text: `Approval ${approval.id}: the server refused it. ${err.message}` });
      } else {
        // the answer was lost (network drop, proxy error): do NOT send again; read the recorded state
        await recover(approval, { approve, reason, clientId });
      }
    } finally {
      inflightRef.current = null;
      setInflight(null);
    }
  }

  // What the recorded state says, in words the admin can act on. `evidence` is the API's re-read (stage:
  // nothing_written / company_written_approval_pending / approval_closed_reply_missing / complete),
  // `inFlight` the decision running in the API right now, `request` the submission whose answer is unknown.
  function showEvidence(approval, evidence, inFlight, request, prefix) {
    const stage = evidence && evidence.stage;
    const head = prefix ? `${prefix} ` : "";
    const check = { approval, request };
    if (inFlight) {
      setNotice({ kind: "uncertain", approvalId: approval.id,
        text: `Approval ${approval.id}: the decision may still be processing; its result is not confirmed.`,
        detail: `${head}A decision (${inFlight.approve ? "approve" : "refuse"}, started ${inFlight.started_at}) is running in the API. Do not decide again; check its status in a moment.`,
        check });
      return;
    }
    if (!evidence || stage === "unknown") {
      setNotice({ kind: "uncertain", approvalId: approval.id,
        text: `Approval ${approval.id}: the result is not confirmed and the recorded state could not be read.`,
        detail: `${head}Reload the queue before deciding again; nothing was sent twice.`, check });
      return;
    }
    if (stage === "complete") {
      const a = evidence.approval || {};
      setNotice({ kind: "ok", approvalId: approval.id,
        text: `Approval ${approval.id}: the server recorded it as ${words(a.status)} by ${a.decided_by || "—"} at ${a.decided_at || "—"}.`,
        detail: head ? `${head}${evidence.stage_words}` : evidence.stage_words });
      reload();
      return;
    }
    if (stage === "nothing_written") {
      setNotice({ kind: "uncertain", approvalId: approval.id,
        text: `Approval ${approval.id}: the result is not confirmed. No write was found (proposal undecided, no refund row, no decision running in the API).`,
        detail: `${head}If the request never reached the server, "Confirm again" sends it with the SAME request id; the server will not run it twice if it did arrive.`,
        check, retry: request ? { approval, ...request } : null });
      return;
    }
    // partial completion: money or the decision moved, the record or the customer notification is not confirmed
    setNotice({ kind: "uncertain", approvalId: approval.id,
      text: stage === "approval_closed_notification_unconfirmed"
        ? `Approval ${approval.id}: decided and recorded, but the customer's reply for it is not confirmed — do NOT decide again.`
        : `Approval ${approval.id}: partially completed — do NOT decide again.`,
      detail: `${head}${evidence.stage_words}${evidence.refund ? ` Refund row: ${tnd(evidence.refund.amount)}.` : ""}${evidence.proposal_decision ? ` Proposal decision: ${words(evidence.proposal_decision)}.` : ""} Ticket ${words(evidence.ticket_status)}. Finishing the record or the customer reply needs a core step (reported to Yassine).`,
      check });
    reload();
  }

  async function recover(approval, request) {
    try {
      const state = await api.approval(approval.id);
      showEvidence(approval, state.evidence || null, state.in_flight || null, request, null);
    } catch (e) {
      showEvidence(approval, null, null, request, null);
    }
  }

  const rows = data ? data.approvals : [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Refund approvals</h1>
          <p className="sub">The Layer 3 queue: refunds above the limit wait for your decision · the client never sees your reason</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}><Icon name="refresh" size={14} />Refresh</button>
      </div>

      <div className="row" role="tablist" aria-label="Approvals" style={{ marginBottom: "var(--cv-s3)" }}>
        {["pending", "decided"].map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={`btn btn-sm ${tab === t ? "btn-primary" : ""}`} onClick={() => { setTab(t); setNotice(null); }}>
            {t === "pending" ? "Waiting" : "Decided"}{data && tab === t ? ` (${data.count})` : ""}
          </button>
        ))}
      </div>

      {notice && (
        <div className={`alert ${notice.kind === "ok" ? "" : notice.kind === "refused" || notice.kind === "uncertain" ? "alert-warn" : "alert-danger"}`} role={notice.kind === "ok" ? "status" : "alert"} style={{ marginBottom: "var(--cv-s3)" }}>
          <Icon name={notice.kind === "ok" ? "check" : notice.kind === "uncertain" ? "clock" : "alert"} />
          <div className="stack" style={{ gap: "var(--cv-s1)" }}>
            <strong>{notice.text}</strong>
            {notice.detail && <span className="small">{notice.detail}</span>}
          </div>
          <div className="actions row">
            {notice.check && <button type="button" className="btn btn-sm" onClick={() => recover(notice.check.approval, notice.check.request)}><Icon name="refresh" size={14} />Check status</button>}
            {notice.retry && <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setConfirm(notice.retry); setNotice(null); }}>Confirm again</button>}
            <button type="button" className="btn btn-ghost btn-sm" aria-label="Dismiss" onClick={() => setNotice(null)}><Icon name="x" size={14} /></button>
          </div>
        </div>
      )}

      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading the queue…" />}
      {data && rows.length === 0 && (
        <div className="panel"><Empty icon="bank" title={tab === "pending" ? "No refund is waiting for approval" : "No decision yet"} /></div>
      )}

      <div className="orders">
        {rows.map((a) => {
          const f = a.facts || {};
          const p = a.proposal || {};
          const isPending = a.status === "pending";
          const mine = inflight === a.id;
          return (
            <article className="panel order-card" key={a.id} aria-labelledby={`appr-${a.id}`}>
              <div className="head">
                <span id={`appr-${a.id}`} style={{ fontFamily: "var(--cv-font-heading)", fontWeight: 600, fontSize: "var(--cv-text-lg)" }}>
                  Approval {a.id} · <span className="tabular">{tnd(a.amount)}</span>
                </span>
                <span className={`badge ${statusClass(a.status)}`}>{words(a.status)}</span>
              </div>
              <dl className="kv">
                <dt>Order</dt><dd>{a.order_id} · {f.user_name || "unknown client"}</dd>
                <dt>Ticket</dt><dd className="mono">{a.ticket_id}</dd>
                <dt>Proposal</dt><dd>{a.proposal_id || "—"}{p.action ? ` · ${words(p.action)} by agent ${p.agent}` : ""}</dd>
                <dt>Rule</dt><dd>{f.rule_id || "—"}{f.rule_title ? `: ${f.rule_title}` : ""}</dd>
                <dt>Order status</dt><dd>{words(f.order_status)}</dd>
                <dt>Paid</dt><dd className="tabular">{tnd(f.paid)}</dd>
                <dt>Already refunded</dt><dd className="tabular">{tnd(f.refunded_total)}</dd>
                <dt>Days late</dt><dd className="tabular">{f.days_late ?? "—"}</dd>
                {"proof_received" in (p.facts_used || {}) && <><dt>Proof</dt><dd>{String(p.facts_used.proof_received)}</dd></>}
                {a.booking_type && <><dt>Booking</dt><dd>{a.booking_type}</dd></>}
                {a.action && a.action !== "refund" && <><dt>Action</dt><dd>{words(a.action)}</dd></>}
                {!isPending && <>
                  <dt>Decided by</dt><dd>{a.decided_by || "—"}</dd>
                  <dt>Decided at</dt><dd className="tabular">{a.decided_at || "—"}<span className="muted xs"> (simulation clock)</span></dd>
                  <dt>Reason</dt><dd>{a.reason || <span className="muted">none given</span>}</dd>
                  {p.decision && <><dt>Proposal decision</dt><dd>{words(p.decision)}</dd></>}
                </>}
              </dl>
              <details className="disclosure">
                <summary><Icon name="chevron" size={14} className="chev" />The agent's facts (facts_used)</summary>
                <div className="disclosure-body"><pre className="raw">{JSON.stringify(p.facts_used ?? f.facts_used ?? {}, null, 2)}</pre></div>
              </details>
              {isPending && (
                <form className="stack" onSubmit={(e) => e.preventDefault()}>
                  <div className="field">
                    <label htmlFor={`reason-${a.id}`}>Reason (required to refuse; never shown to the client)</label>
                    <input id={`reason-${a.id}`} className="input" value={reasons[a.id] || ""} maxLength={1000}
                      onChange={(e) => setReasons((r) => ({ ...r, [a.id]: e.target.value }))} disabled={!!inflight} />
                  </div>
                  <div className="row">
                    <button type="button" className="btn btn-primary" onClick={() => ask(a, true)} disabled={!!inflight}>{mine ? "Deciding…" : "Approve"}</button>
                    <button type="button" className="btn" onClick={() => ask(a, false)} disabled={!!inflight}>Refuse</button>
                  </div>
                </form>
              )}
            </article>
          );
        })}
      </div>

      {confirm && (
        <div className="confirm-backdrop" role="presentation">
          <div className="panel confirm" role="dialog" aria-modal="true" aria-labelledby="confirm-title" ref={confirmRef} tabIndex={-1}
            onKeyDown={(e) => { if (e.key === "Escape" && !inflight) setConfirm(null); }}>
            <h2 id="confirm-title">{confirm.approve ? "Approve" : "Refuse"} approval {confirm.approval.id}?</h2>
            <dl className="kv">
              <dt>Approval</dt><dd>{confirm.approval.id} · order {confirm.approval.order_id} · ticket {confirm.approval.ticket_id}</dd>
              <dt>Amount</dt><dd className="tabular">{tnd(confirm.approval.amount)}</dd>
              <dt>Choice</dt><dd><strong>{confirm.approve ? "Approve: the refund is written and the client is told" : "Refuse: nothing is paid and the client is told"}</strong></dd>
              <dt>Reason</dt><dd>{confirm.reason || <span className="muted">none (allowed when approving)</span>}</dd>
            </dl>
            <p className="small muted">The Coordinator re-checks the order on fresh data before anything is written. Your reason is stored, never shown to the client.</p>
            <div className="row">
              <button type="button" className="btn btn-primary" onClick={submit} disabled={!!inflight}>
                {inflight ? <span className="spinner" aria-hidden="true" /> : <Icon name="check" size={16} />}{inflight ? "Deciding…" : `Confirm ${confirm.approve ? "approval" : "refusal"}`}
              </button>
              <button type="button" className="btn" onClick={() => setConfirm(null)} disabled={!!inflight}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
