// Accessible bar charts without a library: plain SVG bars with the value written next to each bar, and a
// "Show as table" toggle that renders the same rows as a real <table>. Every chart has an accessible name and
// the table is the text alternative; colours come from the theme tokens. Values are the API's: a null or
// missing value is drawn as "—" and no bar, never as 0.
import { useId, useState } from "react";

function fmt(v, unit) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  const text = Number.isInteger(n) ? n.toLocaleString("en-US") : n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return unit ? `${text} ${unit}` : text;
}

// rows: [{label, value, group?}] — horizontal bars, one per row (good for statuses, companies, agents).
export function BarChart({ title, rows, unit = "", color = "var(--cv-primary)", labelHeader = "label", valueHeader = "value", max }) {
  const id = useId();
  const [asTable, setAsTable] = useState(false);
  const values = rows.map((r) => (r.value === null || r.value === undefined ? 0 : Number(r.value)));
  const top = max ?? Math.max(1, ...values);
  const rowH = 26;
  return (
    <figure className="chart" aria-labelledby={`${id}-t`}>
      <figcaption className="chart-head">
        <span id={`${id}-t`}>{title}</span>
        <button type="button" className="btn btn-ghost btn-sm" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </figcaption>
      {rows.length === 0 && <p className="muted small">No data for this period.</p>}
      {rows.length > 0 && asTable && (
        <table className="tickets chart-table">
          <thead><tr><th scope="col">{labelHeader}</th><th scope="col" className="num">{valueHeader}</th></tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}><td>{String(r.label)}</td><td className="num tabular">{fmt(r.value, unit)}</td></tr>)}</tbody>
        </table>
      )}
      {rows.length > 0 && !asTable && (
        <svg className="bars" viewBox={`0 0 440 ${rows.length * rowH}`} role="img" aria-label={`${title}: ${rows.map((r) => `${r.label} ${fmt(r.value, unit)}`).join(", ")}`}>
          {rows.map((r, i) => {
            const v = values[i];
            const w = r.value === null || r.value === undefined ? 0 : Math.max(2, (v / top) * 200);
            return (
              <g key={i} transform={`translate(0, ${i * rowH})`}>
                <text x="0" y={rowH / 2 + 4} className="bar-label">{String(r.label).slice(0, 22)}</text>
                <rect x="130" y="5" width={w} height={rowH - 10} rx="4" fill={color} />
                <text x={130 + w + 6} y={rowH / 2 + 4} className="bar-value">{fmt(r.value, unit)}</text>
              </g>
            );
          })}
        </svg>
      )}
    </figure>
  );
}

// points: [{label, value}] — vertical bars in time order (days). Same text alternative.
export function ColumnChart({ title, points, unit = "", color = "var(--cv-primary)", labelHeader = "day", valueHeader = "value" }) {
  const id = useId();
  const [asTable, setAsTable] = useState(false);
  const values = points.map((p) => (p.value === null || p.value === undefined ? 0 : Number(p.value)));
  const top = Math.max(1, ...values);
  const W = 400, H = 140, pad = 20;
  const slot = points.length ? (W - pad * 2) / points.length : 0;
  return (
    <figure className="chart" aria-labelledby={`${id}-t`}>
      <figcaption className="chart-head">
        <span id={`${id}-t`}>{title}</span>
        <button type="button" className="btn btn-ghost btn-sm" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </figcaption>
      {points.length === 0 && <p className="muted small">No data for this period.</p>}
      {points.length > 0 && asTable && (
        <table className="tickets chart-table">
          <thead><tr><th scope="col">{labelHeader}</th><th scope="col" className="num">{valueHeader}</th></tr></thead>
          <tbody>{points.map((p, i) => <tr key={i}><td>{String(p.label)}</td><td className="num tabular">{fmt(p.value, unit)}</td></tr>)}</tbody>
        </table>
      )}
      {points.length > 0 && !asTable && (
        <svg className="columns" viewBox={`0 0 ${W} ${H + 30}`} role="img" aria-label={`${title}: ${points.map((p) => `${p.label} ${fmt(p.value, unit)}`).join(", ")}`}>
          {points.map((p, i) => {
            const v = values[i];
            const h = p.value === null || p.value === undefined ? 0 : Math.max(1, (v / top) * H);
            const x = pad + i * slot;
            const every = Math.max(1, Math.ceil(points.length / 8));
            return (
              <g key={i}>
                <rect x={x + slot * 0.15} y={H - h} width={Math.max(2, slot * 0.7)} height={h} rx="2" fill={color}>
                  <title>{`${p.label}: ${fmt(p.value, unit)}`}</title>
                </rect>
                {i % every === 0 && <text x={x + slot / 2} y={H + 16} className="bar-label" textAnchor="middle">{String(p.label).slice(-5)}</text>}
              </g>
            );
          })}
          <text x={W - pad} y="12" className="bar-value" textAnchor="end">max {fmt(top, unit)}</text>
        </svg>
      )}
    </figure>
  );
}

// A KPI tile: a label, a value (null → "—") and an optional note. Never turns a missing value into 0.
export function Stat({ label, value, unit = "", note }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value tabular">{fmt(value, unit)}</div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  );
}

export { fmt };
