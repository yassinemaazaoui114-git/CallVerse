// Ticket detail: the ticket's identity, the conversation (left) and how CallVerse worked on the selected
// message (right): the Coordinator's decision first, then the step timeline, then tools, policy evidence and
// the raw steps in disclosures. Everything is plain text from the API: an unknown status, outcome or step
// is shown as it is. Two clocks: computer time (when it really happened) and simulation time (the demo date).
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, ApiError } from "../api.js";
import { useAuth } from "../auth.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, BackToTickets, Empty, Loading } from "../components/States.jsx";
import { priorityClass } from "./LiveTickets.jsx";

// Which SVG icon (and colour) a step kind gets. A kind that is not here gets the neutral dot.
const STEP_ICONS = {
  intake_ticket: ["inbox"], route: ["route"], handover: ["route"], handover_ignored: ["undo"],
  tool_call: ["tool"], tool_refused: ["ban", "bad"], ask_agent: ["user"],
  proposal: ["file"], proposal_refused: ["ban", "bad"],
  coordinator_check: ["check"], coordinator_decision: ["scale", "primary"],
  internal_outcome_to_escalate: ["scale", "warn"], send_back_to_agent: ["undo", "warn"], rule_not_searched: ["alert", "warn"],
  layer3_decision: ["bank"], approval: ["bank", "warn"], approval_pending: ["bank", "warn"],
  quota: ["clock", "warn"], identity: ["lock", "bad"], error: ["alert", "bad"], pipeline_error: ["alert", "bad"],
  db_write: ["bank"], db_write_refused: ["ban", "bad"],
  slm_call: ["pen"], slm_check: ["check"], slm_template: ["file"], final_reply: ["pen", "ok"],
  llm_call: ["brain"], llm_fallback: ["alert", "warn"], llm_daily_limit: ["ban", "bad"], llm_wait: ["clock"], llm_skip: ["clock"],
};
// Checks: pass / fail colour the check icon (the API keeps the result in the raw data).
function stepIcon(step) {
  const [name, tone] = STEP_ICONS[step.kind] || ["dot"];
  let cls = tone || "";
  if (step.kind === "coordinator_check") {
    const r = step.raw && step.raw.data && step.raw.data.result;
    cls = r === "pass" ? "ok" : r === "fail" ? "bad" : "warn";
    return [r === "fail" ? "x" : "check", cls];
  }
  if (step.kind === "slm_check") {
    const ok = step.raw && step.raw.data && step.raw.data.passed;
    return [ok ? "check" : "x", ok ? "ok" : "bad"];
  }
  return [name, cls];
}

// The API's titles/details use **bold** (same words as the Streamlit page). Render only that mark, as text.
function Words({ text }) {
  if (!text) return null;
  const parts = String(text).split("**");
  return parts.map((p, i) => (i % 2 === 1 ? <strong key={i}>{p}</strong> : <span key={i}>{p}</span>));
}

function secondsText(v) { return v == null ? "—" : `${Number(v).toFixed(1)} s`; }
function num(v) { return Number(v || 0).toLocaleString(); }

export default function TicketDetail() {
  const { ticketId } = useParams();
  const location = useLocation();
  const { expired } = useAuth();
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [turnIndex, setTurnIndex] = useState(0);
  const backTo = (location.state && location.state.from) || "/tickets";

  const load = useCallback(async () => {
    setError(null);
    try {
      const body = await api.ticket(ticketId);
      setDetail(body);
      setTurnIndex((i) => Math.min(i, Math.max(0, body.turns.length - 1)));
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_logged_in") { expired(); return; }
      setError(e);
    }
  }, [ticketId, expired]);

  useEffect(() => { setDetail(null); setTurnIndex(0); load(); }, [load]);

  const turn = useMemo(() => (detail && detail.turns[turnIndex]) || null, [detail, turnIndex]);

  if (error) {
    return (
      <div className="stack">
        <div><BackToTickets /></div>
        {error.code === "not_found"
          ? <div className="panel"><Empty icon="search" title={`Ticket ${ticketId} does not exist`} text="It may have been removed, or the id is wrong." /></div>
          : <ApiErrorView error={error} onRetry={load} />}
      </div>
    );
  }
  if (!detail) return <Loading text={`Loading ticket ${ticketId}…`} />;

  const t = detail.ticket;
  return (
    <>
      <div style={{ marginBottom: "var(--cv-s3)" }}>
        <Link to={backTo} className="btn btn-sm"><Icon name="back" size={14} />Live tickets</Link>
      </div>

      <section className="panel ticket-identity" aria-label="Ticket identity">
        <div className="title-row">
          <h1>{t.id}</h1>
          <span className="badge badge-neutral">{String(t.status ?? "—")}</span>
          <span className="badge">{String(t.company ?? "—")}</span>
          <span className={`badge ${priorityClass(t.priority)}`}>priority {String(t.priority ?? "—")}</span>
          <span className="badge badge-neutral">lead agent {String(t.lead_agent ?? "—")}</span>
        </div>
        <dl className="meta">
          <div><dt>User</dt><dd>{detail.user}</dd></div>
          <div><dt>Reason</dt><dd>{String(t.main_reason ?? "—")}</dd></div>
          <div>
            <dt><span className="clock-note"><Icon name="clock" size={12} />Created (computer time)</span></dt>
            <dd className="tabular">{t.created_real || "—"}{t.created_real ? ` · ${detail.age} ago` : ""}</dd>
          </div>
          <div>
            <dt><span className="clock-note"><Icon name="clock" size={12} />Updated (computer time)</span></dt>
            <dd className="tabular">{t.updated_real || "—"}</dd>
          </div>
          <div>
            <dt><span className="clock-note sim"><Icon name="calendar" size={12} />Simulation time</span></dt>
            <dd className="tabular">{t.created_at || "—"}<span className="muted xs"> · the demo clock, not the real date</span></dd>
          </div>
        </dl>
        {detail.approvals.length > 0 && (
          <div className="stack" style={{ gap: "var(--cv-s1)" }}>
            {detail.approvals.map((a) => (
              <div key={a.id} className="row small">
                <Icon name="bank" size={14} />
                <span>Finance approval {a.id}: <strong>{String(a.status)}</strong> · {Number(a.amount).toFixed(2)} TND on {a.booking_type ? `${a.booking_type} booking` : "order"} {a.order_id}
                  {a.decided_by ? ` · decided by ${a.decided_by}` : ""}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="detail-grid">
        <section className="panel" aria-label="Conversation">
          <div className="panel-head">
            <h2>Conversation</h2>
            <span className="muted small">{detail.turns.length} message{detail.turns.length === 1 ? "" : "s"} · select one to see its steps</span>
          </div>
          {detail.turns.length === 0 && <Empty title="No messages on this ticket" />}
          <div className="conversation">
            {detail.turns.map((tr, i) => (
              <button type="button" key={i} className="turn-btn" aria-pressed={i === turnIndex} onClick={() => setTurnIndex(i)}>
                <span className="who"><span className="n">Message {i + 1}</span><span>{(tr.message && tr.message.at_real) || "—"}</span></span>
                {tr.message
                  ? <span className="bubble user">{tr.message.text}</span>
                  : <span className="bubble user muted">(no user message)</span>}
                {tr.replies.map((r) => (
                  <span key={r.id} className={`bubble ${r.sender === "assistant" ? "assistant" : "user"}`}>
                    {r.text}
                    <span className="stamp">{r.sender}{r.at_real ? ` · ${r.at_real}` : ""}{r.sender === "assistant" ? ` · reply took ${secondsText(r.seconds)}` : ""}</span>
                  </span>
                ))}
              </button>
            ))}
          </div>
        </section>

        <section className="panel stack" aria-label="How CallVerse worked on the selected message" aria-live="polite">
          <div className="panel-head">
            <h2>How CallVerse worked on message {turn ? turnIndex + 1 : "—"}</h2>
            {turn && (
              <span className="muted small tabular">
                tokens {num(turn.tokens_total)}
                {Object.keys(turn.tokens).length ? ` (${Object.entries(turn.tokens).map(([m, n]) => `${m} ${num(n)}`).join(" · ")})` : " (no model call)"}
                {" · reply "}{turn.seconds.length ? turn.seconds.map(secondsText).join(", ") : "—"}
              </span>
            )}
          </div>

          {!turn && <Empty title="Select a message" />}

          {turn && (
            <div className="decision" aria-label="Coordinator decision">
              <span className="muted xs" style={{ textTransform: "uppercase", letterSpacing: "0.04em" }}>Coordinator decision</span>
              {turn.decision ? (
                <>
                  <span className="outcome">{String(turn.decision.outcome ?? "—")}</span>
                  <span className="small">{turn.decision.reason ? String(turn.decision.reason) : "No explanation recorded."}</span>
                  {turn.decision.proposal_id && <span className="muted xs">proposal {String(turn.decision.proposal_id)}</span>}
                </>
              ) : <span className="muted small">No Coordinator decision recorded for this message.</span>}
            </div>
          )}

          {turn && (
            <div>
              <h3 style={{ marginBottom: "var(--cv-s2)" }}>Steps</h3>
              {turn.steps.length === 0 && <p className="muted small">No steps saved for this message.</p>}
              <ol className="timeline">
                {turn.steps.map((s) => {
                  const [icon, tone] = stepIcon(s);
                  return (
                    <li key={s.id} className={s.kind === "coordinator_decision" ? "highlight" : ""}>
                      <span className={`ico ${tone}`}><Icon name={icon} size={16} /></span>
                      <div>
                        <div>
                          {s.actor_label && <span className="who">{s.actor_label} </span>}
                          <span className="t"><Words text={s.title} /></span>
                          {s.at_real && <span className="when"> · {s.at_real}</span>}
                        </div>
                        {s.detail && <div className="d"><Words text={s.detail} /></div>}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          )}

          {turn && (
            <details className="disclosure">
              <summary><Icon name="chevron" size={14} className="chev" />Tools called ({turn.tool_calls.length})</summary>
              <div className="disclosure-body stack">
                {turn.tool_calls.length === 0 && <p className="muted small">No tool call on this message.</p>}
                {turn.tool_calls.map((s) => (
                  <dl className="kv" key={s.id}>
                    <dt>Tool</dt><dd><code>{String(s.raw.data.tool)}</code>{s.kind === "tool_refused" ? <span className="badge badge-danger" style={{ marginLeft: 8 }}>refused</span> : null}</dd>
                    <dt>By</dt><dd>{String(s.raw.data.agent ?? s.agent ?? "—")}</dd>
                    <dt>Arguments</dt><dd><code>{JSON.stringify(s.raw.data.args ?? {})}</code></dd>
                    <dt>Result</dt><dd><pre className="raw">{JSON.stringify(s.raw.data.result ?? s.raw.data, null, 2)}</pre></dd>
                  </dl>
                ))}
              </div>
            </details>
          )}

          {turn && (
            <details className="disclosure">
              <summary><Icon name="chevron" size={14} className="chev" />Policy evidence ({turn.policy_searches.length})</summary>
              <div className="disclosure-body stack">
                {turn.policy_searches.length === 0 && <p className="muted small">No policy search on this message.</p>}
                {turn.policy_searches.map((s) => {
                  const results = (s.raw.data.result && s.raw.data.result.results) || [];
                  return (
                    <dl className="kv" key={s.id}>
                      <dt>Query</dt><dd>“{String((s.raw.data.args || {}).query ?? "")}”</dd>
                      <dt>Rules</dt><dd>{results.length ? results.map((r, i) => <span key={i} className="badge" style={{ marginRight: 4 }}>{String(r.id ?? JSON.stringify(r))}</span>) : <span className="muted">none</span>}</dd>
                      <dt>Raw</dt><dd><pre className="raw">{JSON.stringify(s.raw.data.result, null, 2)}</pre></dd>
                    </dl>
                  );
                })}
              </div>
            </details>
          )}

          {turn && (
            <details className="disclosure">
              <summary><Icon name="chevron" size={14} className="chev" />Raw step data ({turn.steps.length})</summary>
              <div className="disclosure-body">
                <pre className="raw">{JSON.stringify(turn.steps.map((s) => s.raw), null, 2)}</pre>
              </div>
            </details>
          )}
        </section>
      </div>
    </>
  );
}
