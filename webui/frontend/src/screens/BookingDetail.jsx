// Booking detail (Atlas Travel customer): one owned flight or hotel booking with the facts the rules use (the
// agents' read, hidden fields already removed), its refunds and compensation. The API answers 404 for a wrong
// type, someone else's or a missing booking (same answer). Nothing is computed here: every value is the core's.
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../api.js";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad, words } from "../hooks.js";
import { situationClass } from "./MyBookings.jsx";

// Which facts to show, per kind: [key, label, kind of value]. Anything the read returns but is not listed here
// stays available under "All facts" (raw), so a new field never gets lost.
const FLIGHT_FACTS = [
  ["carrier_name", "Airline"], ["flight_number", "Flight"], ["origin_city", "From"], ["destination_city", "To"],
  ["scheduled_departure", "Scheduled departure"], ["scheduled_arrival", "Scheduled arrival"],
  ["flight_status", "Flight status"], ["departure_delay_min", "Departure delay (min)"], ["arrival_delay_min", "Arrival delay (min)"],
  ["main_delay_cause", "Delay cause"], ["cancellation_reason", "Cancellation cause"], ["distance_km", "Distance (km)"],
  ["status", "Booking status"], ["booked_date", "Booked"], ["price_tnd", "Price", "money"], ["paid_tnd", "Paid", "money"],
  ["refunded_total", "Refunded so far", "money"], ["hours_before_departure", "Hours before departure (simulation)"],
];
const HOTEL_FACTS = [
  ["hotel_name", "Hotel"], ["arrival_date", "Arrival"], ["nights", "Nights"], ["room_reserved", "Room booked"],
  ["room_assigned", "Room given"], ["room_changed", "Room changed"], ["deposit_type", "Deposit"], ["status", "Booking status"],
  ["booked_date", "Booked"], ["cancelled_date", "Cancelled on"], ["days_before_arrival", "Days before arrival (at cancellation)"],
  ["total_tnd", "Total", "money"], ["paid_tnd", "Paid", "money"], ["refunded_total", "Refunded so far", "money"],
  ["hours_before_arrival", "Hours before arrival (simulation)"],
];

function show(value, kind) {
  if (value === null || value === undefined || value === "") return "—";
  if (kind === "money") return tnd(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

export default function BookingDetail() {
  const { kind, bookingId } = useParams();
  const location = useLocation();
  const backTo = (location.state && location.state.from) || "/atlas/bookings";
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.booking(kind, bookingId, signal), [kind, bookingId]);

  if (error) {
    return (
      <div className="stack">
        <div><Link to={backTo} className="btn btn-sm"><Icon name="back" size={14} />My bookings</Link></div>
        {error.code === "not_found"
          ? <div className="panel"><Empty icon="search" title={`${words(kind)} booking ${bookingId} is not one of your bookings`} text="Check the number and the type, or go back to your bookings." /></div>
          : <ApiErrorView error={error} onRetry={reload} />}
      </div>
    );
  }
  if (loading || !data) return <Loading text={`Loading booking ${bookingId}…`} />;

  const b = data.booking;
  const f = data.facts || {};
  const facts = data.kind === "flight" ? FLIGHT_FACTS : HOTEL_FACTS;
  const money = [...(data.refunds.refunds || []).map((r) => ({ ...r, what: "Refund" })),
                 ...(data.compensations.compensations || []).map((c) => ({ ...c, what: "Compensation" }))];

  return (
    <>
      <div style={{ marginBottom: "var(--cv-s3)" }}>
        <Link to={backTo} className="btn btn-sm"><Icon name="back" size={14} />My bookings</Link>
      </div>
      <section className="panel ticket-identity" aria-label="Booking">
        <div className="title-row">
          <Icon name={data.kind === "flight" ? "plane" : "hotel"} size={22} />
          <h1>Booking {b.id}</h1>
          <span className={`badge ${situationClass(data.kind === "flight" ? b.situation : b.status)}`}>{data.kind === "flight" ? b.situation : b.status}</span>
          <span className="badge badge-neutral">{data.kind}</span>
        </div>
        <p className="small">{data.kind === "flight" ? `${b.route} · ${b.airline} · flight ${b.flight_number}` : `${b.hotel} · arrival ${b.arrival} · ${b.nights} nights`}</p>
        <p className="muted xs"><Icon name="calendar" size={12} /> Dates are the simulation dates (today at Atlas: <span className="tabular">{data.sim_today}</span>).</p>
        <div className="row">
          <Link to={`/atlas/chat?booking=${b.id}`} className="btn btn-primary"><Icon name="chat" size={16} />Ask about this booking</Link>
        </div>
      </section>

      <div className="detail-grid">
        <section className="panel stack" aria-label="Facts">
          <h2>What Atlas knows about it</h2>
          {data.facts ? (
            <dl className="kv">
              {facts.filter(([k]) => k in f).map(([k, label, kindOf]) => (
                <div key={k} style={{ display: "contents" }}><dt>{label}</dt><dd className={kindOf === "money" ? "tabular" : ""}>{show(f[k], kindOf)}</dd></div>
              ))}
            </dl>
          ) : <p className="muted small">The facts of this booking are not available.</p>}
          <details className="disclosure">
            <summary><Icon name="chevron" size={14} className="chev" />All facts (raw)</summary>
            <div className="disclosure-body"><pre className="raw">{JSON.stringify(f, null, 2)}</pre></div>
          </details>
        </section>

        <section className="panel stack" aria-label="Money">
          <h2>Refunds and compensation</h2>
          {money.length === 0 ? <p className="small muted">Nothing paid back on this booking.</p> : (
            <ul className="stack" style={{ margin: 0, paddingLeft: "var(--cv-s4)", gap: "var(--cv-s1)" }}>
              {money.map((r) => (
                <li key={`${r.what}-${r.id}`} className="small">{r.what} of <strong className="tabular">{tnd(r.amount)}</strong> · {words(r.status)}{r.created_at ? ` · ${r.created_at}` : ""}{r.rule_id ? ` · rule ${r.rule_id}` : ""}</li>
              ))}
            </ul>
          )}
          <p className="small muted">Refunded so far: <span className="tabular">{tnd(data.refunds.refunded_total)}</span> · compensation so far: <span className="tabular">{tnd(data.compensations.compensated_total)}</span></p>
        </section>
      </div>
    </>
  );
}
