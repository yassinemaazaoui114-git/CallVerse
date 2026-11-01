// My orders (ShopNova customer): the logged-in customer's own orders, newest first, as cards. The API decides
// whose orders these are (from the accounts file); this screen only shows what it gets. Statuses are the
// database's words (an unknown one is shown as it is); dates are the shop's simulation dates.
import { Link } from "react-router-dom";
import { api } from "../api.js";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad, words } from "../hooks.js";

// Colour of the status badge. Codes come from the database (seed.ORDER_STATUSES today); unknown = neutral.
export function statusClass(status) {
  const s = String(status || "");
  if (s === "delivered") return "badge-ok";
  if (s === "stuck_at_depot") return "badge-warn";
  if (s === "cancelled" || s === "refunded") return "badge-danger";
  return "badge-neutral";
}

export function paidText(order) {
  if (order.payment === "cash_on_delivery" && !order.paid) return "cash on delivery (nothing paid yet)";
  return `paid ${tnd(order.paid)}${order.payment ? ` by ${words(order.payment)}` : ""}`;
}

export default function MyOrders() {
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.orders(signal), []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>My orders</h1>
          <p className="sub">Your orders at ShopNova, newest first</p>
        </div>
        {data && <span className="muted small">Shop date: <span className="tabular">{data.sim_today}</span> (simulation)</span>}
      </div>

      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading your orders…" />}

      {data && data.count === 0 && (
        <div className="panel"><Empty icon="bag" title="You have no orders yet" text="Orders you place at ShopNova will appear here." /></div>
      )}

      {data && data.count > 0 && (
        <>
          <p className="visually-hidden" role="status">{data.count} order{data.count === 1 ? "" : "s"}</p>
          <div className="orders">
            {data.orders.map((o) => (
              <article className="panel order-card" key={o.id} aria-labelledby={`order-${o.id}`}>
                <div className="head">
                  <Link to={`/shop/orders/${o.id}`} id={`order-${o.id}`}>Order {o.id}<Icon name="chevron" size={16} /></Link>
                  <span className={`badge ${statusClass(o.status)}`}>{words(o.status)}</span>
                </div>
                <div className="small muted tabular">
                  Ordered {o.order_date}
                  {o.delivered_date ? ` · delivered ${o.delivered_date}` : o.promised_date ? ` · promised ${o.promised_date}` : ""}
                </div>
                <div className="items">
                  {o.items_count} item{o.items_count === 1 ? "" : "s"}: {o.items_preview.join(", ")}{o.items_preview.length < o.items_count ? ", …" : ""}
                </div>
                <div className="foot">
                  <span className="amount tabular">{tnd(o.total)}</span>
                  <span className="small muted">{paidText(o)}{o.refunds_count ? ` · ${o.refunds_count} refund${o.refunds_count === 1 ? "" : "s"}` : ""}</span>
                </div>
                <div className="row">
                  <Link to={`/shop/orders/${o.id}`} className="btn btn-sm">Details</Link>
                  <Link to={`/shop/orders/${o.id}/ask`} className="btn btn-primary btn-sm"><Icon name="chat" size={14} />Ask about this order</Link>
                </div>
              </article>
            ))}
          </div>
        </>
      )}
    </>
  );
}
