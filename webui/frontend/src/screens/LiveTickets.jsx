// Live tickets: every ticket of every company, newest first, with 4 filters (kept in the URL, so coming back
// from a ticket keeps them) and a refresh every 10 s that never blanks the table or moves the focus.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api.js";
import { useAuth } from "../auth.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";

const REFRESH_MS = 10_000;
const FILTERS = [
  ["company", "Company"],
  ["status", "Status"],
  ["priority", "Priority"],
  ["agent", "Lead agent"],
];
// The table columns: [key in the API row, label]. The API row keys come from callverse.console.reads.
const COLUMNS = [
  ["id", "Ticket"], ["company", "Company"], ["user", "User"], ["reason", "Reason"],
  ["priority", "Priority"], ["status", "Status"], ["lead agent", "Lead agent"], ["age", "Age"],
];

function timeOnly(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function LiveTickets() {
  const { expired } = useAuth();
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(FILTERS.map(([k]) => [k, params.get(k) || ""]));

  const [data, setData] = useState(null);         // the last GOOD answer (never blanked by a failed refresh)
  const [values, setValues] = useState(null);     // the filter values
  const [error, setError] = useState(null);       // the error of the FIRST load (no data yet)
  const [refreshError, setRefreshError] = useState(null); // a failed refresh while data is shown
  const [lastOk, setLastOk] = useState(null);     // when the table was last updated successfully
  const [loading, setLoading] = useState(false);
  const timer = useRef(null);
  const filtersKey = JSON.stringify(filters);

  const load = useCallback(async (reason) => {
    setLoading(true);
    try {
      const [body, fv] = await Promise.all([api.tickets(filters), api.ticketFilters()]);
      setData(body);
      setValues(fv);
      setError(null);
      setRefreshError(null);
      setLastOk(new Date());
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_logged_in") { expired(); return; }
      if (reason === "refresh" && data) setRefreshError(e);
      else setError(e);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey, expired, data]);

  // First load and reload when the filters change.
  useEffect(() => { load("first"); }, [filtersKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Refresh every 10 s. Only the data changes; React keeps the focused element (the DOM is updated in place).
  useEffect(() => {
    timer.current = setInterval(() => {
      if (document.visibilityState === "visible") load("refresh");
    }, REFRESH_MS);
    return () => clearInterval(timer.current);
  }, [load]);

  function setFilter(key, value) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  }
  function clearFilters() { setParams(new URLSearchParams(), { replace: true }); }
  const anyFilter = Object.values(filters).some(Boolean);

  const rows = data ? data.tickets : [];
  const statusText = data
    ? `${data.count} ticket${data.count === 1 ? "" : "s"} shown`
    : "";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Live tickets</h1>
          <p className="sub">Every ticket of every company, newest first · read only</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={() => load("refresh")} disabled={loading}>
          <Icon name="refresh" size={14} />Refresh now
        </button>
      </div>

      <section className="panel" aria-label="Filters">
        <div className="filters">
          {FILTERS.map(([key, label]) => (
            <div className="field" key={key}>
              <label htmlFor={`f-${key}`}>{label}</label>
              <select id={`f-${key}`} className="select" value={filters[key]} onChange={(e) => setFilter(key, e.target.value)}>
                <option value="">All</option>
                {(values ? values[key] : []).map((v) => <option key={v} value={v}>{v}</option>)}
                {/* keep a filter value that is in the URL but not (any more) in the list, so it stays visible */}
                {filters[key] && values && !values[key].includes(filters[key]) && <option value={filters[key]}>{filters[key]}</option>}
              </select>
            </div>
          ))}
          <button type="button" className="btn" onClick={clearFilters} disabled={!anyFilter}>
            <Icon name="x" size={14} />Clear
          </button>
        </div>
      </section>

      <div className="refresh-line" style={{ margin: "var(--cv-s3) 0" }}>
        {data && <span className={`dot ${refreshError ? "stale" : ""}`} aria-hidden="true" />}
        <span role="status" aria-live="polite" aria-atomic="true">
          {data ? `${statusText}${lastOk ? ` · last update ${timeOnly(lastOk.toISOString())}` : ""} · refreshes every 10 s` : ""}
        </span>
        {loading && data && <span className="spinner" style={{ width: 14, height: 14 }} aria-hidden="true" />}
      </div>

      {refreshError && (
        <div style={{ marginBottom: "var(--cv-s3)" }}>
          <ApiErrorView error={{ ...refreshError, code: refreshError.code,
            message: `Refresh failed (${refreshError.message}). The table still shows the data from ${timeOnly(lastOk && lastOk.toISOString())}.` }}
            onRetry={() => load("refresh")} />
        </div>
      )}

      {error && !data && <ApiErrorView error={error} onRetry={() => load("first")} />}
      {!error && !data && <Loading text="Loading tickets…" />}

      {data && !data.has_tickets && (
        <div className="panel"><Empty title="No tickets yet" text={data.no_tickets_message} /></div>
      )}
      {data && data.has_tickets && rows.length === 0 && (
        <div className="panel">
          <Empty icon="search" title="No ticket matches these filters">
            <button type="button" className="btn btn-sm" onClick={clearFilters}>Clear filters</button>
          </Empty>
        </div>
      )}
      {data && rows.length > 0 && (
        <div className={`table-wrap ${loading ? "loading" : ""}`}>
          <table className="tickets">
            <caption className="visually-hidden">Live tickets, newest first</caption>
            <thead>
              <tr>{COLUMNS.map(([k, label]) => <th key={k} scope="col">{label}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  {COLUMNS.map(([k]) => {
                    if (k === "id") {
                      return (
                        <td className="id" key={k}>
                          <Link to={`/tickets/${encodeURIComponent(t.id)}`} state={{ from: `/tickets?${params.toString()}` }}
                            aria-label={`Open ticket ${t.id}`}>
                            {t.id}<Icon name="chevron" size={14} />
                          </Link>
                        </td>
                      );
                    }
                    if (k === "status") return <td key={k}><span className="badge badge-neutral">{String(t[k])}</span></td>;
                    if (k === "priority") return <td key={k}><span className={`badge ${priorityClass(t[k])}`}>{String(t[k])}</span></td>;
                    if (k === "age") return <td key={k} className="tabular muted">{String(t[k])}</td>;
                    return <td key={k} className="wrap-any">{String(t[k] ?? "—")}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// Priority words come from the pipeline (high / medium / low today). Unknown words get the neutral badge.
export function priorityClass(value) {
  const v = String(value || "").toLowerCase();
  if (v === "high" || v === "urgent") return "badge-danger";
  if (v === "medium") return "badge-warn";
  if (v === "low") return "badge-ok";
  return "badge-neutral";
}
