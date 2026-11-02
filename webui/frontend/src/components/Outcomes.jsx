// T27: the urgent badge and the plain-words list of what Agents C and D did on a ticket.
// Meaning is never shown by colour alone (ui-ux-pro-max rule): every badge has an icon AND a word.
import Icon from "./Icon.jsx";

// The ticket was marked urgent by the pipeline (Agent C passed a money request to Agent B: "urgent refund").
export function UrgentBadge() {
  return (
    <span className="badge badge-danger" title="Marked urgent by Agent C: top of the list">
      <Icon name="bolt" size={12} />Urgent
    </span>
  );
}

const C_ACTIONS = ["replace", "hold", "assistance", "rebook"];
const unitsOf = (n) => (Number(n) === 1 ? "1 unit" : `${n ?? "?"} units`);

// The last proposal step of this action in the turn (its params hold e.g. the colleague's reason).
function proposalOf(steps, action) {
  const found = [...steps].reverse().find((s) => s.raw && s.raw.data && s.raw.data.trace_step === "proposal" && s.raw.data.action === action);
  const d = (found && found.raw.data) || {};
  return { ...d, ...(d.params || {}) };
}

// One line per thing done, from the steps of one turn (the Coordinator's decisions and Agent D's warnings).
// Returns [{key, icon, tone, title, text}]. An outcome not listed here gives no line (the timeline shows it).
export function outcomesOf(steps) {
  const out = [];
  (steps || []).forEach((s) => {
    const d = (s.raw && s.raw.data) || {};
    if (d.trace_step === "stock_warning") {
      out.push({ key: s.id, icon: "alert", tone: "warn", title: "Agent D's stock warning",
        text: String(d.note || "").replace(/^\[|\]$/g, "") });
      return;
    }
    if (d.trace_step === "handover" && d.urgent === true) {
      out.push({ key: s.id, icon: "bolt", tone: "bad", title: "Passed to Agent B as urgent", text: d.text || "The money request goes to the top of the list." });
      return;
    }
    if (d.trace_step !== "coordinator_decision") return;
    const f = d.facts || {};
    const said = Array.isArray(d.must_say) && d.must_say.length ? d.must_say[0] : "";
    const what = d.action;
    if (d.outcome === "ask_user" && C_ACTIONS.includes(what)) {
      out.push({ key: s.id, icon: "chat", tone: "warn", title: "Waiting for the user's yes", text: said || `Agent C asked the user to confirm (${what}).` });
    } else if (d.outcome === "approve" && what === "replace") {
      out.push({ key: s.id, icon: "package", tone: "ok", title: "Replacement created",
        text: `New order ${f.new_order_id ?? "—"}${f.product_name ? ` · ${unitsOf(f.qty)} of ${f.product_name}` : ""} · free for the user.` });
    } else if (d.outcome === "approve" && what === "hold") {
      out.push({ key: s.id, icon: "clock", tone: "ok", title: "Hold made",
        text: `${unitsOf(f.qty)}${f.product_name ? ` of ${f.product_name}` : ""} kept until ${f.held_until ?? "—"}.` });
    } else if (d.outcome === "approve" && what === "rebook") {
      out.push({ key: s.id, icon: "plane", tone: "ok", title: "Rebooked on a new flight", text: said || `New departure ${f.new_departure ?? "—"}.` });
    } else if (d.outcome === "approve" && what === "assistance" && f.kind) {
      out.push({ key: s.id, icon: "hand", tone: "ok", title: "Special assistance requested", text: said || `${f.kind} requested.` });
    } else if (d.outcome === "approve" && what === "assistance") {
      const p = proposalOf(steps, "assistance");
      out.push({ key: s.id, icon: "user", tone: "ok", title: "Passed to a colleague",
        text: `Special help team${p.reason ? ` · reason: ${p.reason}` : ""}.` });
    } else if (d.outcome === "escalate") {
      out.push({ key: s.id, icon: "user", tone: "warn", title: "Passed to a colleague", text: d.reason ? `Reason: ${d.reason}` : "A human colleague takes over." });
    }
  });
  return out;
}

// The "What was done" panel of the ticket view. Nothing to show = nothing rendered.
export function OutcomeList({ items }) {
  if (!items || items.length === 0) return null;
  return (
    <section className="outcomes" aria-label="What was done">
      <h3 style={{ marginBottom: "var(--cv-s2)" }}>What was done</h3>
      <ul className="timeline">
        {items.map((o) => (
          <li key={o.key}>
            <span className={`ico ${o.tone}`}><Icon name={o.icon} size={16} /></span>
            <div>
              <div className="t"><strong>{o.title}</strong></div>
              {o.text && <div className="d">{o.text}</div>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
