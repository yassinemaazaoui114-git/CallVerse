// The shared screen states: loading, empty, error (API unavailable, permission denied, not found...).
import { Link } from "react-router-dom";
import Icon from "./Icon.jsx";

export function Loading({ text = "Loading…" }) {
  return (
    <div className="state-block" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{text}</span>
    </div>
  );
}

export function Empty({ icon = "inbox", title, text, children }) {
  return (
    <div className="state-block">
      <Icon name={icon} size={28} />
      <strong style={{ color: "var(--cv-text)" }}>{title}</strong>
      {text && <span>{text}</span>}
      {children}
    </div>
  );
}

// One alert for every API error code. `onRetry` adds a Retry button (used by the screens).
export function ApiErrorView({ error, onRetry }) {
  const code = error && error.code;
  let icon = "alert", title = "Something went wrong", text = error && error.message, kind = "alert-danger";
  if (code === "unavailable") {
    title = "The CallVerse API is not reachable";
    text = "Start it with `python -m webui.api.run` (see webui/README.md), then retry.";
  } else if (code === "forbidden") {
    icon = "lock"; title = "Supervisor only";
    text = "This page is for the CallVerse supervisor. Your account does not have that role.";
    kind = "alert-warn";
  } else if (code === "not_logged_in") {
    icon = "lock"; title = "Please log in"; kind = "alert-warn";
  } else if (code === "not_found") {
    icon = "search"; title = "Not found"; kind = "alert-warn";
  }
  return (
    <div className={`alert ${kind}`} role="alert">
      <Icon name={icon} />
      <div className="stack" style={{ gap: "var(--cv-s1)" }}>
        <strong>{title}</strong>
        {text && <span className="small">{text}</span>}
      </div>
      {onRetry && (
        <div className="actions">
          <button type="button" className="btn btn-sm" onClick={onRetry}><Icon name="refresh" size={14} />Retry</button>
        </div>
      )}
    </div>
  );
}

export function BackToTickets() {
  return <Link to="/tickets" className="btn btn-sm"><Icon name="back" size={14} />Live tickets</Link>;
}
