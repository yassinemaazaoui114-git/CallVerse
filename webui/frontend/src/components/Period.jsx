// The period picker of the dashboards. Each read defines its own periods (the Console: all / 7 / 30 days of
// COMPUTER time; ShopNova: 7 / 30 / 90 days of the SIMULATION clock; Atlas: 7 / 30 / all, simulation clock), so
// the options come from the API answer, never from this file. The choice lives in the URL (?days=), so Back and
// reload keep it; the screen's guarded load reloads on every change and drops an older answer.
import { useSearchParams } from "react-router-dom";

export function usePeriod(fallback = "") {
  const [params, setParams] = useSearchParams();
  const days = params.get("days") ?? fallback;
  const setDays = (value) => {
    const next = new URLSearchParams(params);
    if (value === "" || value === null) next.delete("days"); else next.set("days", String(value));
    setParams(next, { replace: true });
  };
  return [days, setDays];
}

// Shown above numbers that belong to ANOTHER period than the selected one: while the new period loads, or when
// its load failed. The numbers stay visible (nothing blanks) but are never presented as the current period's.
export function StalePeriodNote({ loading, error, shownLabel, selectedLabel, onRetry }) {
  if (loading) return <p className="alert" role="status"><span className="spinner" aria-hidden="true" /><span className="small">Loading {selectedLabel}… the numbers below are still those of {shownLabel}.</span></p>;
  if (error) return (
    <div className="alert alert-danger" role="alert">
      <div className="stack" style={{ gap: "var(--cv-s1)" }}>
        <strong>{selectedLabel} could not be loaded</strong>
        <span className="small">{error.message} The numbers below are those of {shownLabel}, not of the selected period.</span>
      </div>
      {onRetry && <div className="actions"><button type="button" className="btn btn-sm" onClick={onRetry}>Retry</button></div>}
    </div>
  );
  return null;
}

export function labelOf(options, value) {
  const found = options.find((o) => String(o.value) === String(value));
  return found ? found.label : String(value);
}

// options: [{value, label}] — value is what the API takes ("all", "7", "30", "90").
export default function PeriodPicker({ options, value, onChange, clock }) {
  return (
    <div className="period" role="group" aria-label="Period">
      {options.map((o) => (
        <button key={o.value} type="button" className={`btn btn-sm ${String(value) === String(o.value) ? "btn-primary" : ""}`}
          aria-pressed={String(value) === String(o.value)} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
      {clock && <span className="muted xs" style={{ marginLeft: "var(--cv-s2)" }}>{clock}</span>}
    </div>
  );
}
