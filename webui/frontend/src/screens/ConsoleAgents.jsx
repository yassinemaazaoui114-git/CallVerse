// Console Agents (supervisor): one card per agent of the pipeline for the tickets created in the period, from
// callverse.console.reads.agents through the API. Same roles and lines as the Streamlit page; "—" for a missing
// value (e.g. no timed step); never 0 for unknown.
import { api } from "../api.js";
import { fmt } from "../components/Chart.jsx";
import PeriodPicker, { usePeriod } from "../components/Period.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { useGuardedLoad } from "../hooks.js";
import { consoleOptions } from "./ConsoleDashboard.jsx";

const ROLE = {
  intake: "Reads every message: reason, emotion, sentiment, priority, order id (local models).",
  A: "Orders, delivery, notifications. Read tools + subscription proposals.",
  B: "Refunds. Read tools + refund proposals; may ask Agent A.",
  coordinator: "Rules, no LLM: checks every proposal, decides, and only then writes.",
  writer: "Small local model: writes the reply from the decision; checked, template if it fails.",
};
const SECONDS = { intake: "avg seconds per message", A: "avg model seconds per message", B: "avg model seconds per message",
                  coordinator: "avg seconds", writer: "avg seconds per reply" };

export default function ConsoleAgents() {
  const [days, setDays] = usePeriod("all");
  const { data, error, loading, reload } = useGuardedLoad((signal) => api.consoleAgents(days, signal), [days], { keep: true });
  const cards = (data && data.agents) || [];
  const anyWork = cards.some((c) => c.tickets);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Agents</h1>
          <p className="sub">One card per agent of the pipeline, for the tickets created in the period · computer time</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}><Icon name="refresh" size={14} />Refresh</button>
      </div>
      <PeriodPicker options={consoleOptions(data && data.periods)} value={days} onChange={setDays} clock={data ? `${data.clock} · read ${data.read_at}` : null} />
      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading the agents…" />}
      {data && !data.has_tickets && <div className="panel"><Empty icon="inbox" title="No tickets yet" text={data.no_tickets_message} /></div>}
      {data && data.has_tickets && !anyWork && <div className="panel"><Empty icon="search" title="No tickets in this period" /></div>}
      {data && data.has_tickets && (
        <div className={`agents ${loading ? "is-stale" : ""}`} aria-busy={loading}>
          {cards.map((c) => {
            const rows = [["Messages", fmt(c.messages)], ["Proposals", c.agent === "intake" ? "—" : fmt(c.proposals)]];
            if (["A", "B", "coordinator"].includes(c.agent)) rows.push(["Approved", fmt(c.approved)], ["Sent back", fmt(c.sent_back)], ["Escalated", fmt(c.escalated)], ["To finance", fmt(c.to_finance)]);
            rows.push(["Errors", fmt(c.errors)], [SECONDS[c.agent] || "avg seconds", fmt(c.avg_seconds, "s")], ["Tokens", fmt(c.tokens)]);
            return (
              <article className="panel stack agent-card" key={c.agent} aria-labelledby={`ag-${c.agent}`}>
                <h2 id={`ag-${c.agent}`}>{c.name}</h2>
                <p className="small muted">{ROLE[c.agent] || ""}</p>
                <div className="stat"><div className="stat-label">Tickets handled</div><div className="stat-value tabular">{fmt(c.tickets)}</div></div>
                <dl className="kv">
                  {rows.map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd className="tabular">{v}</dd></div>)}
                </dl>
                <p className="small muted">Models: {(c.models || []).join(", ") || "—"}</p>
              </article>
            );
          })}
        </div>
      )}
      <p className="muted xs" style={{ marginTop: "var(--cv-s3)" }}>Proposals of the Coordinator = proposals it reviewed. Errors = refused tool calls or proposals, a model that failed (the next one of its list was used), refused writes, reply-writer errors.</p>
    </>
  );
}
