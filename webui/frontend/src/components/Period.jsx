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
