// Order detail (ShopNova customer): the lines, the delivery progress, the dates, the payment and the refunds of
// ONE owned order. The API answers 404 for an order that is missing or belongs to someone else (same answer).
// Nothing here guesses: the progress list only marks what the database says (status, dates), "days late"
// comes from the read tool (computed against the shop's simulation date), and an unknown status is text.
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../api.js";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad, words } from "../hooks.js";
import { paidText, statusClass } from "./MyOrders.jsx";

// The delivery steps in the order the shop uses (seed.STATUS_MOVES); a status outside this list (refunded,
// cancelled, or a new one) is shown as its own line, not placed on the path.
const PATH = ["processing", "shipped", "out_for_delivery", "delivered"];

export function progressOf(order) {
  const status = String(order.status || "");
  const at = PATH.indexOf(status);
  const onPath = at >= 0 || status === "stuck_at_depot";
  const reached = status === "stuck_at_depot" ? PATH.indexOf("shipped") : at;
  const steps = PATH.map((code, i) => ({
    code, label: words(code),
    state: !onPath ? "none" : i < reached ? "done" : i === reached && code !== status ? "done" : i === reached ? "now" : "todo",
    note: code === "processing" ? `ordered ${order.order_date}`
      : code === "delivered" ? (order.delivered_date ? `delivered ${order.delivered_date}` : order.promised_date ? `promised ${order.promised_date}` : "")
      : "",
  }));
  if (status === "stuck_at_depot") steps.splice(2, 0, { code: status, label: words(status), state: "now", note: "" });
  return { steps, onPath };
}

export default function OrderDetail() {
  const { orderId } = useParams();
  const location = useLocation();
  const backTo = (location.state && location.state.from) || "/shop/orders";
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.order(orderId, signal), [orderId]);

  if (error) {
    return (
      <div className="stack">
        <div><Link to={backTo} className="btn btn-sm"><Icon name="back" size={14} />My orders</Link></div>
        {error.code === "not_found"
          ? <div className="panel"><Empty icon="search" title={`Order ${orderId} is not one of your orders`} text="Check the number, or go back to your orders." /></div>
          : <ApiErrorView error={error} onRetry={reload} />}
      </div>
    );
  }
  if (loading || !data) return <Loading text={`Loading order ${orderId}…`} />;

  const o = data.order;
  const tr = data.tracking;
  const rf = data.refunds;
  const { steps, onPath } = progressOf(o);

  return (
    <>
      <div style={{ marginBottom: "var(--cv-s3)" }}>
        <Link to={backTo} className="btn btn-sm"><Icon name="back" size={14} />My orders</Link>
      </div>

      <section className="panel ticket-identity" aria-label="Order">
        <div className="title-row">
          <h1>Order {o.id}</h1>
          <span className={`badge ${statusClass(o.status)}`}>{words(o.status)}</span>
          {!onPath && <span className="muted xs">status code <code>{String(o.status)}</code></span>}
        </div>
        <dl className="meta">
          <div><dt>Ordered</dt><dd className="tabular">{o.order_date}</dd></div>
          <div><dt>Promised</dt><dd className="tabular">{o.promised_date || "—"}</dd></div>
          <div><dt>Delivered</dt><dd className="tabular">{o.delivered_date || "not delivered yet"}</dd></div>
          <div><dt>Carrier</dt><dd>{o.carrier ? `${o.carrier} · ${o.tracking_number || "—"}` : "—"}</dd></div>
        </dl>
        <p className="muted xs"><Icon name="calendar" size={12} /> Dates are the shop's simulation dates (today in the shop: <span className="tabular">{data.sim_today}</span>).</p>
        <div className="row">
          <Link to={`/shop/orders/${o.id}/ask`} className="btn btn-primary"><Icon name="chat" size={16} />Ask about this order</Link>
        </div>
      </section>

      <div className="detail-grid">
        <section className="panel stack" aria-label="Delivery">
          <h2>Delivery</h2>
          {onPath ? (
            <ol className="progress">
              {steps.map((s) => (
                <li key={s.code} className={s.state} aria-current={s.state === "now" ? "step" : undefined}>
                  <span className="mark" aria-hidden="true"><Icon name={s.state === "done" ? "check" : s.state === "now" ? "truck" : "dot"} size={14} /></span>
                  <div><div className="t">{s.label}{s.state === "now" ? " (now)" : ""}</div>{s.note && <div className="d tabular">{s.note}</div>}</div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="small">This order's status is <strong>{words(o.status)}</strong>; it is not on the delivery path.</p>
          )}
          {tr ? (
            <dl className="kv">
              <dt>Days late</dt><dd className="tabular">{tr.days_late}{tr.delivered ? " (at delivery)" : ` (as of ${tr.checked_on})`}</dd>
              {tr.delivered && <><dt>Days since delivery</dt><dd className="tabular">{tr.days_since_delivery}</dd></>}
            </dl>
          ) : (
            <p className="muted small">Tracking details are not available for this order.</p>
          )}
        </section>

        <section className="panel stack" aria-label="Items and payment">
          <h2>Items</h2>
          <table className="lines">
            <thead><tr><th scope="col">Item</th><th scope="col" className="num">Qty</th><th scope="col" className="num">Price</th></tr></thead>
            <tbody>
              {o.items.map((i, n) => (
                <tr key={n}><td className="wrap-any">{i.name}</td><td className="num">{i.qty}</td><td className="num">{tnd(i.price)}</td></tr>
              ))}
            </tbody>
            <tfoot><tr><td colSpan={2}>Total</td><td className="num">{tnd(o.total)}</td></tr></tfoot>
          </table>
          <h3>Payment</h3>
          <p className="small"><Icon name="card" size={14} /> {paidText(o)}</p>
          <h3>Refunds</h3>
          {rf && rf.refunds.length > 0 ? (
            <>
              <ul className="stack" style={{ margin: 0, paddingLeft: "var(--cv-s4)", gap: "var(--cv-s1)" }}>
                {rf.refunds.map((r) => (
                  <li key={r.id} className="small">
                    <strong className="tabular">{tnd(r.amount)}</strong> · {words(r.status)}{r.created_at ? ` · ${r.created_at}` : ""}{r.rule_id ? ` · rule ${r.rule_id}` : ""}
                  </li>
                ))}
              </ul>
              <p className="small muted">Refunded so far: <span className="tabular">{tnd(rf.refunded_total)}</span></p>
            </>
          ) : (
            <p className="small muted">No refund on this order.</p>
          )}
        </section>
      </div>
    </>
  );
}
