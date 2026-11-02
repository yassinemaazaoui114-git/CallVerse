// Atlas admin dashboard (permission view_dashboard): the business view for the last 7 / 30 days or all, of the
// SIMULATION clock, from callverse.data.atlas.atlas_app_reads.dashboard through the API. Bookings are counted by
// booked date, flights by departure date (the core's rule); the upcoming lists look 14 days ahead.
import { api } from "../api.js";
import { BarChart, Stat, fmt } from "../components/Chart.jsx";
import PeriodPicker, { StalePeriodNote, labelOf, usePeriod } from "../components/Period.jsx";
import CheckNow from "../components/CheckNow.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad, words } from "../hooks.js";

export default function AtlasAdminDashboard() {
  const [days, setDays] = usePeriod("all");
  const { data, error, loading, reload, isCurrent } = useGuardedLoad((signal) => api.atlasDashboard(days, signal), [days], { keep: true });
  const d = data && data.dashboard;
  const options = Object.entries((data && data.periods) || { All: null }).map(([label, v]) => ({ label, value: v === null ? "all" : String(v) }));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Admin dashboard</h1>
          <p className="sub">Atlas Travel's business view · simulation clock · bookings by booked date, flights by departure date</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}><Icon name="refresh" size={14} />Refresh</button>
      </div>
      <div style={{ marginBottom: "var(--cv-s3)" }}><CheckNow company="atlas" /></div>
      <PeriodPicker options={options} value={days} onChange={setDays} clock={d ? `${d.start ? `from ${d.start}` : "all dates"} to ${d.today} (simulation clock)` : null} />
      {data && !isCurrent && <StalePeriodNote loading={loading} error={error} shownLabel={labelOf(options, data.days === null ? "all" : String(data.days))} selectedLabel={labelOf(options, days)} onRetry={reload} />}
      {error && !data && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading the dashboard…" />}
      {d && (
        <div className={`stack ${isCurrent ? "" : "is-stale"}`} aria-busy={loading}>
          <div className="stats">
            <Stat label="Hotel cancellation rate" value={d.hotel_cancellation_rate} unit="%" note={`${fmt(d.hotel_bookings)} hotel bookings`} />
            <Stat label="Flight delay rate" value={d.flight_delay_rate} unit="%" note={`${fmt(d.flights)} flights flown`} />
            <Stat label="Flight cancellation rate" value={d.flight_cancellation_rate} unit="%" />
            <Stat label="Refunds paid" value={d.refunds_paid ? `${fmt(d.refunds_paid.count)} · ${tnd(d.refunds_paid.tnd)}` : null} />
            <Stat label="Compensation paid" value={d.compensation_paid ? `${fmt(d.compensation_paid.count)} · ${tnd(d.compensation_paid.tnd)}` : null} />
          </div>
          <div className="charts">
            <div className="panel"><BarChart title={`Hotel bookings by status (${fmt(d.hotel_bookings)})`} rows={(d.hotel_by_status || []).map((s) => ({ label: words(s.status), value: s.bookings }))} labelHeader="status" valueHeader="bookings" /></div>
            <div className="panel"><BarChart title={`Flight bookings by status (${fmt(d.flight_bookings)})`} rows={(d.flight_by_status || []).map((s) => ({ label: words(s.status), value: s.bookings }))} labelHeader="status" valueHeader="bookings" color="var(--cv-accent)" /></div>
          </div>
          <div className="charts">
            <section className="panel stack" aria-label="Upcoming arrivals">
              <h2>Upcoming arrivals, until {d.upcoming_until} ({fmt((d.upcoming_arrivals || []).length)})</h2>
              {(d.upcoming_arrivals || []).length === 0 ? <p className="small muted">No arrival in the next {fmt(data.upcoming_days)} days.</p> : (
                <div className="table-wrap"><table className="tickets records"><thead><tr><th scope="col">booking</th><th scope="col">client</th><th scope="col">hotel</th><th scope="col">arrival</th><th scope="col" className="num">nights</th></tr></thead>
                  <tbody>{d.upcoming_arrivals.map((a) => <tr key={a.id}><td>{a.id}</td><td>{a.client}</td><td>{a.hotel}</td><td className="tabular">{a.arrival_date}</td><td className="num tabular">{fmt(a.nights)}</td></tr>)}</tbody></table></div>
              )}
            </section>
            <section className="panel stack" aria-label="Upcoming departures">
              <h2>Upcoming departures, until {d.upcoming_until} ({fmt((d.upcoming_departures || []).length)})</h2>
              {(d.upcoming_departures || []).length === 0 ? <p className="small muted">No departure in the next {fmt(data.upcoming_days)} days.</p> : (
                <div className="table-wrap"><table className="tickets records"><thead><tr><th scope="col">booking</th><th scope="col">client</th><th scope="col">from</th><th scope="col">to</th><th scope="col">departure</th></tr></thead>
                  <tbody>{d.upcoming_departures.map((f) => <tr key={f.id}><td>{f.id}</td><td>{f.client}</td><td>{f.origin}</td><td>{f.destination}</td><td className="tabular">{f.scheduled_departure}</td></tr>)}</tbody></table></div>
              )}
            </section>
          </div>
        </div>
      )}
    </>
  );
}
