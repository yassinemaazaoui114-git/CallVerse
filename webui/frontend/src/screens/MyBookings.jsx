// My bookings (Atlas Travel customer, step 5): the customer's flights and hotel stays, each with its refunds and
// compensation, from atlas_app_reads.my_bookings through the API. The API decides whose bookings these are.
// Situations ("delayed 200 minutes (the airline)") and statuses are the read layer's words, shown as they come.
import { Link } from "react-router-dom";
import { api } from "../api.js";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad, words } from "../hooks.js";

export function situationClass(text) {
  const s = String(text || "").toLowerCase();
  if (s.startsWith("cancelled") || s === "no-show") return "badge-danger";
  if (s.startsWith("delayed")) return "badge-warn";
  if (s === "on time" || s === "stayed" || s === "confirmed") return "badge-ok";
  return "badge-neutral";
}

function MoneyLines({ booking }) {
  const rows = [...(booking.refunds || []).map((r) => ({ ...r, what: "Refund" })),
                ...(booking.compensations || []).map((c) => ({ ...c, what: "Compensation" }))];
  if (rows.length === 0) return null;
  return (
    <ul className="stack" style={{ margin: 0, paddingLeft: "var(--cv-s4)", gap: "var(--cv-s1)" }}>
      {rows.map((r) => (
        <li key={`${r.what}-${r.id}`} className="small">{r.what} of <strong className="tabular">{tnd(r.amount)}</strong> · {words(r.status)}{r.created_at ? ` · ${r.created_at}` : ""}</li>
      ))}
    </ul>
  );
}

export default function MyBookings() {
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.bookings(signal), []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>My bookings</h1>
          <p className="sub">Your flights and hotel stays at Atlas Travel</p>
        </div>
        {data && <span className="muted small">Today at Atlas: <span className="tabular">{data.sim_today}</span> (simulation)</span>}
      </div>

      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading your bookings…" />}
      {data && data.count === 0 && <div className="panel"><Empty icon="plane" title="You have no bookings yet" /></div>}

      {data && data.flights.length > 0 && (
        <section aria-labelledby="flights-h" style={{ marginBottom: "var(--cv-s4)" }}>
          <h2 id="flights-h" className="row" style={{ marginBottom: "var(--cv-s2)" }}><Icon name="plane" size={18} />Flights</h2>
          <div className="orders">
            {data.flights.map((f) => (
              <article className="panel order-card" key={f.id} aria-labelledby={`fl-${f.id}`}>
                <div className="head">
                  <Link to={`/atlas/bookings/flight/${f.id}`} id={`fl-${f.id}`}>Booking {f.id}<Icon name="chevron" size={16} /></Link>
                  <span className={`badge ${situationClass(f.situation)}`}>{f.situation}</span>
                </div>
                <div className="small">{f.route}</div>
                <div className="small muted tabular">{f.airline} · flight {f.flight_number} · departure {f.departure}</div>
                <div className="foot"><span className="amount tabular">{tnd(f.paid)}</span><span className="small muted">paid</span></div>
                <MoneyLines booking={f} />
                <div className="row">
                  <Link to={`/atlas/bookings/flight/${f.id}`} className="btn btn-sm">Details</Link>
                  <Link to={`/atlas/chat?booking=${f.id}`} className="btn btn-primary btn-sm"><Icon name="chat" size={14} />Ask about this booking</Link>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {data && data.hotels.length > 0 && (
        <section aria-labelledby="hotels-h">
          <h2 id="hotels-h" className="row" style={{ marginBottom: "var(--cv-s2)" }}><Icon name="hotel" size={18} />Hotel stays</h2>
          <div className="orders">
            {data.hotels.map((h) => (
              <article className="panel order-card" key={h.id} aria-labelledby={`ho-${h.id}`}>
                <div className="head">
                  <Link to={`/atlas/bookings/hotel/${h.id}`} id={`ho-${h.id}`}>Booking {h.id}<Icon name="chevron" size={16} /></Link>
                  <span className={`badge ${situationClass(h.status)}`}>{h.status}</span>
                </div>
                <div className="small">{h.hotel}</div>
                <div className="small muted tabular">Arrival {h.arrival} · {h.nights} night{h.nights === 1 ? "" : "s"} · room booked {h.room_booked}, room given {h.room_given} · {h.deposit}</div>
                <div className="foot"><span className="amount tabular">{tnd(h.total)}</span><span className="small muted">paid {tnd(h.paid)}</span></div>
                <MoneyLines booking={h} />
                <div className="row">
                  <Link to={`/atlas/bookings/hotel/${h.id}`} className="btn btn-sm">Details</Link>
                  <Link to={`/atlas/chat?booking=${h.id}`} className="btn btn-primary btn-sm"><Icon name="chat" size={14} />Ask about this booking</Link>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
