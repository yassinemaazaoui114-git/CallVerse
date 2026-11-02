// Live tickets: every ticket of every company, newest first, with 4 filters (kept in the URL, so coming back
// from a ticket keeps them) and a refresh every 10 s that never blanks the table or moves the focus.
//
// Requests: every load gets a number and an AbortController. Only the answer of the LATEST request may change
// the screen (an older answer that arrives late is dropped), the previous request is aborted when a new one
// starts, and the screen aborts its request when it unmounts. The table always says which filters its rows
// belong to: after a failed filter change the old rows stay visible but are labelled as the previous filters'
// results, next to an error with Retry.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api.js";
import { useAuth } from "../auth.jsx";
import Icon from "../components/Icon.jsx";
import { UrgentBadge } from "../components/Outcomes.jsx";
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

// "company=atlas, status=Open" or "no filters": the words for a set of filters.
export function describeFilters(filters) {
  const parts = Object.entries(filters || {}).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`);
  return parts.length ? parts.join(", ") : "no filters";
}

export default function LiveTickets() {
  const { expired } = useAuth();
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(FILTERS.map(([k]) => [k, params.get(k) || ""]));
  const filtersKey = JSON.stringify(filters);

  const [data, setData] = useState(null);           // the last GOOD answer (never blanked by a failure)
  const [loadedFilters, setLoadedFilters] = useState(null); // the filters that answer belongs to
  const [values, setValues] = useState(null);       // the filter values
  const [error, setError] = useState(null);         // the load for the CURRENT filters failed
  const [refreshError, setRefreshError] = useState(null); // a background refresh failed (data still current)
  const [lastOk, setLastOk] = useState(null);       // when the table was last updated successfully
  const [loading, setLoading] = useState(false);
  const requestNo = useRef(0);          // the number of the latest request: older answers are dropped
  const controller = useRef(null);      // the AbortController of the request in flight
  const dataRef = useRef(null);         // the last good answer + its filters, readable inside load()
  const timer = useRef(null);

  const load = useCallback(async (reason) => {
    if (controller.current) controller.current.abort();
    const mine = ++requestNo.current;
    const ctrl = new AbortController();
    controller.current = ctrl;
    setLoading(true);
    try {
      const [body, fv] = await Promise.all([api.tickets(filters, ctrl.signal), api.ticketFilters(ctrl.signal)]);
      if (mine !== requestNo.current) return;   // an older request: its answer must not touch the screen
      dataRef.current = { data: body, key: filtersKey };
      setData(body);
      setLoadedFilters(filters);
      setValues(fv);
      setError(null);
      setRefreshError(null);
      setLastOk(new Date());
    } catch (e) {
      if (mine !== requestNo.current || (e && e.name === "AbortError")) return;   // superseded or unmounted
      if (e instanceof ApiError && e.code === "not_logged_in") { expired(); return; }
      const current = dataRef.current && dataRef.current.key === filtersKey;
      if (reason === "refresh" && current) setRefreshError(e);   // the rows shown are still the right ones
      else setError(e);                                           // no rows yet, or rows of OTHER filters
    } finally {
      if (mine === requestNo.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey, expired]);

  // First load, reload when the filters change, and abort the request in flight when the screen unmounts.
  useEffect(() => {
    load("filters");
    return () => { if (controller.current) controller.current.abort(); };
  }, [load]);

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
  const rowsAreCurrent = data && JSON.stringify(loadedFilters) === filtersKey;
  const statusText = data ? `${data.count} ticket${data.count === 1 ? "" : "s"} shown` : "";

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
        {rowsAreCurrent && <span className={`dot ${refreshError ? "stale" : ""}`} aria-hidden="true" />}
        <span role="status" aria-live="polite" aria-atomic="true">
          {rowsAreCurrent ? `${statusText}${lastOk ? ` · last update ${timeOnly(lastOk.toISOString())}` : ""} · refreshes every 10 s` : ""}
        </span>
        {loading && data && <span className="spinner" style={{ width: 14, height: 14 }} aria-hidden="true" />}
      </div>

      {refreshError && rowsAreCurrent && (
        <div style={{ marginBottom: "var(--cv-s3)" }}>
          <ApiErrorView error={refreshError} onRetry={() => load("refresh")}
            note={`Refresh failed. The table still shows the data from ${timeOnly(lastOk && lastOk.toISOString())}.`} />
        </div>
      )}

      {error && data && !rowsAreCurrent && (
        <div style={{ marginBottom: "var(--cv-s3)" }}>
          <ApiErrorView error={error} onRetry={() => load("filters")}
            note={`Could not load tickets for the selected filters (${describeFilters(filters)}). `
              + `The rows below are the results of the previous filters (${describeFilters(loadedFilters)}).`} />
        </div>
      )}

      {error && !data && <ApiErrorView error={error} onRetry={() => load("filters")} />}
      {!error && !data && <Loading text="Loading tickets…" />}
      {!error && data && !rowsAreCurrent && <Loading text={`Loading tickets for ${describeFilters(filters)}…`} />}

      {data && !data.has_tickets && (
        <div className="panel"><Empty title="No tickets yet" text={data.no_tickets_message} /></div>
      )}
      {data && data.has_tickets && rows.length === 0 && (
        <div className="panel">
          <Empty icon="search" title={rowsAreCurrent ? "No ticket matches these filters" : `No ticket matched the previous filters (${describeFilters(loadedFilters)})`}>
            <button type="button" className="btn btn-sm" onClick={clearFilters}>Clear filters</button>
          </Empty>
        </div>
      )}
      {data && rows.length > 0 && (
        <div className={`table-wrap ${loading ? "loading" : ""}`}>
          <table className="tickets" aria-describedby={rowsAreCurrent ? undefined : "previous-filters-note"}>
            <caption className={rowsAreCurrent ? "visually-hidden" : "small muted"} id="previous-filters-note" style={{ padding: "var(--cv-s2) var(--cv-s3)", textAlign: "left" }}>
              {rowsAreCurrent ? "Live tickets, newest first" : `Results of the previous filters (${describeFilters(loadedFilters)}), not of the selected ones`}
            </caption>
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
                          {t.urgent && <> <UrgentBadge /></>}
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
