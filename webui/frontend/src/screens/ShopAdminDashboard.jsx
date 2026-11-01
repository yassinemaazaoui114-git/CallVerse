// ShopNova admin dashboard (permission view_dashboard): the business view for the last 7 / 30 / 90 days of the
// SIMULATION clock, from callverse.data.admin_reads.dashboard through the API. Every number is the core's;
// a missing review average shows "—".
import { api } from "../api.js";
import { BarChart, ColumnChart, Stat, fmt } from "../components/Chart.jsx";
import PeriodPicker, { usePeriod } from "../components/Period.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad, words } from "../hooks.js";

export default function ShopAdminDashboard() {
  const [days, setDays] = usePeriod("30");
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.shopDashboard(days, signal), [days], { keep: true });
  const d = data && data.dashboard;
  const options = ((data && data.periods) || [7, 30, 90]).map((n) => ({ value: String(n), label: `Last ${n} days` }));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Admin dashboard</h1>
          <p className="sub">ShopNova's business view · simulation clock, orders counted by order date</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}><Icon name="refresh" size={14} />Refresh</button>
      </div>
      <PeriodPicker options={options} value={days} onChange={setDays} clock={d ? `from ${d.start} to ${d.today} (simulation clock)` : null} />
      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading the dashboard…" />}
      {d && (
        <div className={`stack ${loading ? "is-stale" : ""}`} aria-busy={loading}>
          <div className="stats">
            <Stat label="Sales" value={d.sales_tnd === null || d.sales_tnd === undefined ? null : tnd(d.sales_tnd)} />
            <Stat label="Orders" value={d.orders} />
            <Stat label="Late deliveries" value={d.late} />
            <Stat label="Stuck at depot" value={d.stuck} />
            <Stat label="Refunds paid" value={d.refunds_paid ? `${fmt(d.refunds_paid.count)} · ${tnd(d.refunds_paid.tnd)}` : null} />
            <Stat label="Review average" value={d.review_average === null || d.review_average === undefined ? null : `${d.review_average} / 5`} note={d.review_count ? `${fmt(d.review_count)} reviews in the period` : "no review in the period"} />
          </div>
          <div className="panel"><ColumnChart title="Sales per day (TND)" points={(d.sales_per_day || []).map((p) => ({ label: p.day, value: p.sales_tnd }))} unit="TND" color="var(--cv-accent)" valueHeader="sales TND" /></div>
          <div className="charts">
            <div className="panel"><BarChart title="Orders by status" rows={(d.orders_by_status || []).map((s) => ({ label: words(s.status), value: s.orders }))} labelHeader="status" valueHeader="orders" /></div>
            <div className="panel"><BarChart title="Review scores" rows={(d.review_scores || []).map((s) => ({ label: `${s.score} / 5`, value: s.count }))} labelHeader="score" valueHeader="reviews" color="var(--cv-accent)" /></div>
            <div className="panel"><BarChart title="Top 10 products (quantity sold)" rows={(d.top_products || []).map((p) => ({ label: p.name, value: p.qty }))} labelHeader="product" valueHeader="qty" /></div>
            <div className="panel"><BarChart title="Top categories (quantity sold)" rows={(d.top_categories || []).map((c) => ({ label: words(c.category), value: c.qty }))} labelHeader="category" valueHeader="qty" /></div>
          </div>
          <div className="charts">
            <section className="panel stack" aria-label="Low stock">
              <h2>Low stock (≤ {fmt(data.low_stock_limit)})</h2>
              {(d.low_stock || []).length === 0 ? <p className="small muted">No active product is low on stock.</p> : (
                <div className="table-wrap"><table className="tickets records"><thead><tr><th scope="col">id</th><th scope="col">name</th><th scope="col">category</th><th scope="col" className="num">stock</th></tr></thead>
                  <tbody>{d.low_stock.map((p) => <tr key={p.id}><td>{p.id}</td><td>{p.name}</td><td>{words(p.category)}</td><td className="num tabular">{fmt(p.stock)}</td></tr>)}</tbody></table></div>
              )}
            </section>
            <section className="panel stack" aria-label="Late deliveries">
              <h2>Late deliveries</h2>
              {(d.late_orders || []).length === 0 ? <p className="small muted">No late delivery in the period.</p> : (
                <div className="table-wrap"><table className="tickets records"><thead><tr><th scope="col">order</th><th scope="col">status</th><th scope="col">promised</th><th scope="col">delivered</th></tr></thead>
                  <tbody>{d.late_orders.map((o) => <tr key={o.id}><td>{o.id}</td><td>{words(o.status)}</td><td className="tabular">{o.promised_date || "—"}</td><td className="tabular">{o.delivered_date || "not yet"}</td></tr>)}</tbody></table></div>
              )}
            </section>
          </div>
        </div>
      )}
      {d && d.orders === 0 && <div className="panel"><Empty icon="search" title="No order in this period" /></div>}
    </>
  );
}
