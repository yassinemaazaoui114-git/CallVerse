// T27: Agent D's proposals waiting for the OWNER. ShopNova admin: Promotions (rule R-PRM-01, a discount for a
// product with too much stock). Atlas admin: Hotel deals (rule AT-DEAL-01, a discount for a hotel's empty nights).
// Same layout and safety as Refund approvals:
// - tabs Waiting / Decided, one card per proposal (cards, not a wide table: each one needs a reason box and two
//   buttons, and must stay readable on a small screen);
// - Approve / Refuse (a reason is required to refuse) opens a confirmation that repeats the exact choice;
// - one decision at a time: every button is disabled while it runs, and the request carries an id, so a second
//   click or a retry is not a second decision (the API answers the recorded result);
// - the decision itself is the core's (callverse.channels.approvals.decide_promotion / decide_atlas_deal); this
//   screen shows what the API returns. The price is never changed by itself: an approval is recorded.
import { Fragment, useEffect, useRef, useState } from "react";
import { ApiError, COMPANIES } from "../api.js";
import { useAuth } from "../auth.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad, words } from "../hooks.js";

function newClientId() {
  return (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `o-${Date.now()}-${Math.random()}`;
}

function statusClass(status) {
  if (status === "approved") return "badge-ok";
  if (status === "refused") return "badge-danger";
  if (status === "pending") return "badge-warn";
  return "badge-neutral";
}
const STATUS_ICON = { approved: "check", refused: "x", pending: "clock" };
const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`);
const num = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 }));
// T28: the backend says 9999 days of cover when nothing was sold (stock_tools.NO_SALES_COVER): say it in words.
const NO_SALES_COVER = 9999;
const cover = (f) => {
  if (!f || f.days_of_cover == null) return "—";
  if (f.days_of_cover >= NO_SALES_COVER || f.units_sold_30d === 0) return "No sales in the last 30 days";
  return `${num(f.days_of_cover)} days`;
};

// What differs between the two pages: words and which facts a card shows.
const KINDS = {
  shopnova: {
    word: "promotion", Word: "Promotion", title: "Promotions", rule: "R-PRM-01",
    sub: "Agent D proposes a discount for a product with too much stock · nothing starts until you approve it, and the price is never changed by itself",
    empty: "No promotion is waiting", emptyText: "Use “Check stock now” on the Dashboard to let Agent D look at the stock.",
    head: (p) => `${num(p.discount_pct)}% on ${p.product_name}`,
    facts: (p) => [
      ["Product", `${p.product_name} (product ${p.product_id})${p.price != null ? ` · price ${tnd(p.price)}` : ""}`],
      ["Stock now", num(p.stock)],
      ["Sold in the last 30 days", num(p.facts && p.facts.units_sold_30d)],
      ["Days of cover", cover(p.facts)],
      ["Discount", pct(p.discount_pct)],
    ],
    confirmLine: (p) => `${num(p.discount_pct)}% on ${p.product_name}`,
  },
  atlas: {
    word: "deal", Word: "Deal", title: "Hotel deals", rule: "AT-DEAL-01",
    sub: "Agent D proposes a discount for a hotel's empty nights · nothing starts until you approve it, and the price is never changed by itself",
    empty: "No hotel deal is waiting", emptyText: "Use “Check rooms now” on the Dashboard to let Agent D look at the coming nights.",
    head: (d) => `${num(d.discount_pct)}% at ${d.hotel_name}`,
    facts: (d) => [
      ["Hotel", `${d.hotel_name} (hotel ${d.hotel_id})`],
      ["Nights", `${(d.nights || []).length} night${(d.nights || []).length === 1 ? "" : "s"}${d.first_night ? ` · ${d.first_night}${d.last_night && d.last_night !== d.first_night ? ` to ${d.last_night}` : ""}` : ""}`],
      ["Lowest occupancy", `${pct(d.facts && d.facts.min_occupancy_pct)}${d.facts && d.facts.capacity ? ` of ${num(d.facts.capacity)} rooms` : ""}`],
      ["Discount", pct(d.discount_pct)],
    ],
    confirmLine: (d) => `${num(d.discount_pct)}% at ${d.hotel_name} (${(d.nights || []).length} nights)`,
  },
};

export default function OwnerProposals({ company = "shopnova" }) {
  const api = COMPANIES[company].owner;
  const k = KINDS[company];
  const { expired } = useAuth();
  const [tab, setTab] = useState("pending");
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.list(tab, signal), [tab, company]);
  const [reasons, setReasons] = useState({});      // row id -> reason typed
  const [confirm, setConfirm] = useState(null);     // {row, approve, reason, clientId}
  const [inflight, setInflight] = useState(null);   // row id being decided
  const inflightRef = useRef(null);                 // the same, readable at once (a double click)
  const [notice, setNotice] = useState(null);       // {kind: ok | error, text}
  const dialogRef = useRef(null);

  useEffect(() => { if (confirm && dialogRef.current) dialogRef.current.focus(); }, [confirm]);
  useEffect(() => {
    if (!confirm) return undefined;
    const onKey = (e) => { if (e.key === "Escape" && !inflightRef.current) setConfirm(null); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [confirm]);

  function ask(row, approve) {
    const reason = (reasons[row.id] || "").trim();
    if (!approve && !reason) {
      setNotice({ kind: "error", text: `${k.Word} ${row.id}: a reason is required to refuse.` });
      return;
    }
    setNotice(null);
    setConfirm({ row, approve, reason, clientId: newClientId() });
  }

  async function submit() {
    if (!confirm || inflightRef.current) return;
    const { row, approve, reason, clientId } = confirm;
    inflightRef.current = row.id;
    setInflight(row.id);
    try {
      const out = await api.decide(row.id, { approve, reason, client_id: clientId });
      const item = out.item || {};
      setNotice({ kind: "ok", text: `${k.Word} ${row.id}: ${words(item.status)} by ${item.decided_by || "you"} on ${item.decided_at || "—"}${out.recorded ? " (recorded earlier)" : ""}.` });
      setReasons((r) => ({ ...r, [row.id]: "" }));
      reload();
    } catch (err) {
      if (err instanceof ApiError && err.code === "not_logged_in") { expired(); return; }
      const text = err instanceof ApiError && err.code === "unavailable"
        ? `${k.Word} ${row.id}: the answer was lost. Refresh the list before deciding again (a retry is not a second decision).`
        : `${k.Word} ${row.id}: nothing was done. ${err.message}`;
      setNotice({ kind: "error", text });
      reload();
    } finally {
      inflightRef.current = null;
      setInflight(null);
      setConfirm(null);
    }
  }

  const rows = data ? data.items : [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{k.title}</h1>
          <p className="sub">{k.sub}</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}><Icon name="refresh" size={14} />Refresh</button>
      </div>

      <div className="row" role="tablist" aria-label={k.title} style={{ marginBottom: "var(--cv-s3)" }}>
        {["pending", "decided"].map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={`btn btn-sm ${tab === t ? "btn-primary" : ""}`} onClick={() => { setTab(t); setNotice(null); }}>
            {t === "pending" ? "Waiting" : "Decided"}{data && tab === t ? ` (${data.count})` : ""}
          </button>
        ))}
      </div>

      {notice && (
        <div className={`alert ${notice.kind === "ok" ? "" : "alert-danger"}`} role={notice.kind === "ok" ? "status" : "alert"} style={{ marginBottom: "var(--cv-s3)" }}>
          <Icon name={notice.kind === "ok" ? "check" : "alert"} />
          <div className="stack" style={{ gap: "var(--cv-s1)" }}><strong>{notice.text}</strong></div>
          <div className="actions row">
            <button type="button" className="btn btn-ghost btn-sm" aria-label="Dismiss" onClick={() => setNotice(null)}><Icon name="x" size={14} /></button>
          </div>
        </div>
      )}

      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text={`Loading the ${k.word}s…`} />}
      {data && rows.length === 0 && (
        <div className="panel">
          {tab === "pending" ? <Empty icon="tag" title={k.empty} text={k.emptyText} /> : <Empty icon="tag" title="No decision yet" />}
        </div>
      )}

      <div className="orders">
        {rows.map((p) => {
          const isPending = p.status === "pending";
          const mine = inflight === p.id;
          return (
            <article className="panel order-card" key={p.id} aria-labelledby={`own-${p.id}`}>
              <div className="head">
                <span id={`own-${p.id}`} style={{ fontFamily: "var(--cv-font-heading)", fontWeight: 600, fontSize: "var(--cv-text-lg)" }}>
                  {k.Word} {p.id} · {k.head(p)}
                </span>
                <span className={`badge ${statusClass(p.status)}`}><Icon name={STATUS_ICON[p.status] || "dot"} size={12} />{words(p.status)}</span>
              </div>
              <dl className="kv">
                {k.facts(p).map(([label, value]) => <Fragment key={label}><dt>{label}</dt><dd className="tabular">{value}</dd></Fragment>)}
                <dt>Agent D's note</dt><dd>{p.note || <span className="muted">no note</span>}</dd>
                <dt>Proposal</dt><dd>{p.proposal_id || "—"} · rule {k.rule}</dd>
                <dt>Proposed on</dt><dd className="tabular">{p.created_at || "—"}<span className="muted xs"> (simulation clock)</span></dd>
                {!isPending && <>
                  <dt>Decided by</dt><dd>{p.decided_by || "—"}</dd>
                  <dt>Decided on</dt><dd className="tabular">{p.decided_at || "—"}<span className="muted xs"> (simulation clock)</span></dd>
                  <dt>Reason</dt><dd>{p.reason || <span className="muted">none given</span>}</dd>
                </>}
              </dl>
              {isPending && (
                <form className="stack" onSubmit={(e) => e.preventDefault()}>
                  <div className="field">
                    <label htmlFor={`own-reason-${p.id}`}>Reason (required to refuse)</label>
                    <input id={`own-reason-${p.id}`} className="input" value={reasons[p.id] || ""} maxLength={1000}
                      onChange={(e) => setReasons((r) => ({ ...r, [p.id]: e.target.value }))} disabled={!!inflight} />
                  </div>
                  <div className="row">
                    <button type="button" className="btn btn-primary" onClick={() => ask(p, true)} disabled={!!inflight}>{mine ? "Deciding…" : "Approve"}</button>
                    <button type="button" className="btn" onClick={() => ask(p, false)} disabled={!!inflight}>Refuse</button>
                  </div>
                </form>
              )}
            </article>
          );
        })}
      </div>

      {confirm && (
        <div className="confirm-backdrop" role="presentation">
          <div className="panel confirm" role="dialog" aria-modal="true" aria-labelledby="own-confirm-title" ref={dialogRef} tabIndex={-1}>
            <h2 id="own-confirm-title">{confirm.approve ? "Approve" : "Refuse"} {k.word} {confirm.row.id}?</h2>
            <dl className="kv">
              <dt>{k.Word}</dt><dd>{k.confirmLine(confirm.row)}</dd>
              <dt>Choice</dt><dd><strong>{confirm.approve ? `Approve: the ${k.word} is recorded as approved` : `Refuse: the ${k.word} does not start`}</strong></dd>
              <dt>Reason</dt><dd>{confirm.reason || <span className="muted">none (allowed when approving)</span>}</dd>
            </dl>
            <p className="small muted">No price is changed by this decision; it is recorded with your name in the admin log.</p>
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
