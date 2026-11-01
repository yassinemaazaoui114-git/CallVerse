// Console Dashboard (supervisor): the center's KPIs for the tickets created in the period, from
// callverse.console.reads.dashboard through the API. Times are COMPUTER time (the simulation clock does not
// move). Every number is the core's; a missing value shows "—". Groq today is the core's count out of the
// configured daily quota; nothing is computed here.
import { api } from "../api.js";
import { BarChart, ColumnChart, Stat, fmt } from "../components/Chart.jsx";
import PeriodPicker, { usePeriod } from "../components/Period.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad } from "../hooks.js";

export function consoleOptions(periods) {
  return Object.entries(periods || { All: null }).map(([label, v]) => ({ label, value: v === null ? "all" : String(v) }));
}

export default function ConsoleDashboard() {
  const [days, setDays] = usePeriod("all");
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.consoleDashboard(days, signal), [days], { keep: true });
  const d = data && data.dashboard;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="sub">The center's numbers for the tickets created in the period · computer time, not the simulation clock</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}><Icon name="refresh" size={14} />Refresh</button>
      </div>
      <PeriodPicker options={consoleOptions(data && data.periods)} value={days} onChange={setDays} clock={data ? `${data.clock} · read ${data.read_at}` : null} />

      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading the dashboard…" />}
      {data && !data.has_tickets && <div className="panel"><Empty icon="inbox" title="No tickets yet" text={data.no_tickets_message} /></div>}
      {d && d.tickets === 0 && <div className="panel"><Empty icon="search" title="No tickets in this period" /></div>}

      {d && d.tickets > 0 && (
        <div className={`stack ${loading ? "is-stale" : ""}`} aria-busy={loading}>
          <div className="stats">
            <Stat label="Tickets" value={d.tickets} />
            <Stat label="Solved by the AI alone" value={d.solved_ai_pct} unit="%" note={`${fmt(d.solved_ai)} ticket(s): Solved, never escalated, no finance approval`} />
            <Stat label="Escalated (Layer 2)" value={d.escalated_pct} unit="%" note={`${fmt(d.escalated)} ticket(s) passed to a human`} />
            <Stat label="Sent to finance (Layer 3)" value={d.finance_pct} unit="%" note={`${fmt(d.finance)} ticket(s) with an approval`} />
            <Stat label="Average reply time" value={d.avg_reply_s} unit="s" note={`${fmt(d.replies_timed)} timed replies (${fmt(d.replies_untimed)} older replies without a time)`} />
            <Stat label={`Late replies (> ${fmt(d.late_s)} s)`} value={d.late_pct} unit="%" note={`${fmt(d.late)} late`} />
            <Stat label="Finance: approved / refused" value={`${fmt(d.finance_approved)} / ${fmt(d.finance_refused)}`} note={`${fmt(d.finance_pending)} still waiting`} />
            <Stat label="Refunds paid" value={d.refunds_tnd === null || d.refunds_tnd === undefined ? null : tnd(d.refunds_tnd)} note={`${fmt(d.refunds_paid)} refund(s); ${d.finance_tnd === null || d.finance_tnd === undefined ? "—" : tnd(d.finance_tnd)} after a finance approval`} />
            <Stat label="Compensation paid" value={d.compensations_tnd === null || d.compensations_tnd === undefined ? null : tnd(d.compensations_tnd)} note={`${fmt(d.compensations_paid)} compensation(s)`} />
            <Stat label="Satisfaction (reviews)" value={d.review_avg === null || d.review_avg === undefined ? null : `${d.review_avg} / 5`} note={d.reviews ? `average of ${fmt(d.reviews)} ShopNova review scores (not per ticket yet)` : "no review score available"} />
            <Stat label="Tokens per ticket (avg / max)" value={`${fmt(d.tokens_avg)} / ${fmt(d.tokens_max)}`} note={`${fmt(d.tokens_total)} in total`} />
            <Stat label="System tokens (apart)" value={d.system_tokens} note="quota-check pings: tokens spent for no ticket" />
          </div>

          <section className="panel stack" aria-label="Groq today">
            <h2>Groq tokens used today</h2>
            {d.groq_today ? (
              <>
                <p className="small">
                  <strong className="tabular">{fmt(d.groq_today.total)}</strong> of <span className="tabular">{fmt(d.groq_today.limit)}</span> ({fmt(d.groq_today.tickets)} in tickets + {fmt(d.groq_today.system)} system) · computer date, as the center counted them
                </p>
                <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={d.groq_today.limit || 0} aria-valuenow={d.groq_today.total || 0} aria-label="Groq tokens used today">
                  <div className="meter-fill" style={{ width: `${d.groq_today.limit ? Math.min(100, (100 * (d.groq_today.total || 0)) / d.groq_today.limit) : 0}%` }} />
                </div>
              </>
            ) : <p className="muted small">Not available.</p>}
          </section>

          <section className="panel stack" aria-label="Money per company">
            <h2>Money per company</h2>
            <div className="table-wrap">
              <table className="tickets records">
                <thead><tr><th scope="col">company</th><th scope="col" className="num">refunds</th><th scope="col" className="num">refunds TND</th><th scope="col" className="num">compensations</th><th scope="col" className="num">compensation TND</th><th scope="col" className="num">after finance TND</th></tr></thead>
                <tbody>
                  {(d.money_per_company || []).map((c) => (
                    <tr key={c.company}><td>{c.company}</td><td className="num tabular">{fmt(c.refunds_paid)}</td><td className="num tabular">{fmt(c.refunds_tnd)}</td><td className="num tabular">{fmt(c.compensations_paid)}</td><td className="num tabular">{fmt(c.compensations_tnd)}</td><td className="num tabular">{fmt(c.finance_tnd)}</td></tr>
                  ))}
                  {(d.money_per_company || []).length === 0 && <tr><td colSpan={6} className="muted">No money moved on these tickets.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <div className="charts">
            <div className="panel"><ColumnChart title="Tickets per day (all companies)" points={perDay(d.per_day)} valueHeader="tickets" /></div>
            <div className="panel"><BarChart title="Per company" rows={(d.per_company || []).map((c) => ({ label: c.company, value: c.tickets }))} labelHeader="company" valueHeader="tickets" /></div>
            <div className="panel"><BarChart title="Tokens per ticket" rows={(d.tokens_per_ticket || []).map((t) => ({ label: t.ticket, value: t.tokens }))} labelHeader="ticket" valueHeader="tokens" /></div>
            <div className="panel"><BarChart title="Tickets by status" rows={(d.by_status || []).map((s) => ({ label: s.status, value: s.tickets }))} labelHeader="status" valueHeader="tickets" color="var(--cv-warn)" /></div>
          </div>
        </div>
      )}
    </>
  );
}

// per_day rows are (day, company, tickets); the column chart shows the day totals (the table keeps the split).
function perDay(rows) {
  const totals = new Map();
  for (const r of rows || []) totals.set(r.day, (totals.get(r.day) || 0) + (r.tickets || 0));
  return [...totals.entries()].map(([label, value]) => ({ label, value }));
}
