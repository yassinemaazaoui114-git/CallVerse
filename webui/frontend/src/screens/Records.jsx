// Records (Atlas Travel admin, permission view_dashboard): Atlas's tables, read only, with a search box and
// 50 rows per page, and the admin log, exactly as the Streamlit Records page shows them.
import { useState } from "react";
import { api } from "../api.js";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { useGuardedLoad } from "../hooks.js";

const TABLES = [["hotels", "Hotel bookings"], ["flights", "Flight bookings"], ["users", "Users"],
                ["refunds", "Refunds"], ["compensations", "Compensation"], ["log", "Admin log"]];

export default function Records() {
  const [table, setTable] = useState("hotels");
  const [search, setSearch] = useState("");
  const [typed, setTyped] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.records(table, search, page, signal), [table, search, page]);

  const columns = data && data.items.length ? Object.keys(data.items[0]) : [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Records</h1>
          <p className="sub">Atlas Travel's tables, view only · the admin log shows the last 50 decisions</p>
        </div>
      </div>
      <div className="records-tabs" role="tablist" aria-label="Tables">
        {TABLES.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={table === key} className={`btn btn-sm ${table === key ? "btn-primary" : ""}`}
            onClick={() => { setTable(key); setPage(1); setSearch(""); setTyped(""); }}>{label}</button>
        ))}
      </div>
      {table !== "log" && (
        <form className="records-tools" onSubmit={(e) => { e.preventDefault(); setPage(1); setSearch(typed.trim()); }}>
          <div className="field">
            <label htmlFor="rec-search">Search</label>
            <input id="rec-search" className="input" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="id, name, status…" />
          </div>
          <button type="submit" className="btn"><Icon name="search" size={14} />Search</button>
          {data && (
            <span className="row small muted" role="status">
              {data.total} rows · {data.page_size} per page · page {data.page} of {data.pages}
              <button type="button" className="btn btn-sm" disabled={data.page <= 1} onClick={() => setPage(data.page - 1)} aria-label="Previous page">‹</button>
              <button type="button" className="btn btn-sm" disabled={data.page >= data.pages} onClick={() => setPage(data.page + 1)} aria-label="Next page">›</button>
            </span>
          )}
        </form>
      )}
      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading…" />}
      {data && data.items.length === 0 && <div className="panel"><Empty icon="file" title="No rows" /></div>}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="tickets records">
            <caption className="visually-hidden">{TABLES.find(([k]) => k === table)[1]}</caption>
            <thead><tr>{columns.map((c) => <th key={c} scope="col">{c.replace(/_/g, " ")}</th>)}</tr></thead>
            <tbody>
              {data.items.map((row, i) => (
                <tr key={row.id ?? i}>{columns.map((c) => <td key={c}>{row[c] === null || row[c] === undefined ? "—" : typeof row[c] === "object" ? JSON.stringify(row[c]) : String(row[c])}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
