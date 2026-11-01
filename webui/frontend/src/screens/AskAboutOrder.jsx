// "Ask about this order" (ShopNova customer): prepares the chat context for step 3 (the order number the chat
// will attach to the first message, as the Streamlit Help chat does with "About order N") and says honestly
// that the chat itself is not built yet. Nothing is sent and the pipeline is never called from here.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { useGuardedLoad, words } from "../hooks.js";
import { statusClass } from "./MyOrders.jsx";

export default function AskAboutOrder() {
  const { orderId } = useParams();
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.order(orderId, signal), [orderId]);
  const [draft, setDraft] = useState("");

  if (error) {
    return (
      <div className="stack">
        <div><Link to="/shop/orders" className="btn btn-sm"><Icon name="back" size={14} />My orders</Link></div>
        {error.code === "not_found"
          ? <div className="panel"><Empty icon="search" title={`Order ${orderId} is not one of your orders`} text="You can only ask about your own orders." /></div>
          : <ApiErrorView error={error} onRetry={reload} />}
      </div>
    );
  }
  if (loading || !data) return <Loading text={`Preparing the chat for order ${orderId}…`} />;

  const o = data.order;
  return (
    <>
      <div style={{ marginBottom: "var(--cv-s3)" }}>
        <Link to={`/shop/orders/${o.id}`} className="btn btn-sm"><Icon name="back" size={14} />Order {o.id}</Link>
      </div>
      <div className="page-head">
        <div>
          <h1>Ask about order {o.id}</h1>
          <p className="sub">Help chat with CallVerse · the conversation will be about this order</p>
        </div>
      </div>

      <section className="panel stack" aria-label="Order context" data-chat-order={o.id}>
        <div className="row">
          <Icon name="package" size={18} />
          <strong>About order {o.id}</strong>
          <span className={`badge ${statusClass(o.status)}`}>{words(o.status)}</span>
          <span className="muted small tabular">ordered {o.order_date}{o.delivered_date ? ` · delivered ${o.delivered_date}` : ""}</span>
        </div>
        <p className="small muted">{o.items.map((i) => i.name).join(", ")}</p>

        <div className="ask-box">
          <div className="alert" role="status">
            <Icon name="info" />
            <div className="stack" style={{ gap: "var(--cv-s1)" }}>
              <strong>Chat is coming in the next step</strong>
              <span className="small">The order number is ready; sending a message to CallVerse is built in step 3. Nothing you type here is sent.</span>
            </div>
          </div>
          <div className="field">
            <label htmlFor="draft">Your message (draft only, not sent)</label>
            <textarea id="draft" className="input" value={draft} onChange={(e) => setDraft(e.target.value)}
              placeholder={`e.g. Where is my order ${o.id}?`} />
          </div>
          <div className="row">
            <button type="button" className="btn btn-primary" disabled aria-disabled="true" title="Available in step 3">
              <Icon name="chat" size={16} />Send (not available yet)
            </button>
            <span className="muted xs">Context kept: order {o.id} · nothing is sent in this step</span>
          </div>
        </div>
      </section>
    </>
  );
}
