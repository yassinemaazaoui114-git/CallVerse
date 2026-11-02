// T27: the "Check now" panel of the two admin dashboards. One click runs Agent D's scan ONCE on the server
// (the same function as the Streamlit button) and shows what it found; the button is disabled while it runs,
// so a double click starts one scan. The counts come from the API as they are.
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, COMPANIES } from "../api.js";
import { useAuth } from "../auth.jsx";
import Icon from "./Icon.jsx";
import { ApiErrorView } from "./States.jsx";
import { Stat } from "./Chart.jsx";

const WORDS = {
  shopnova: {
    title: "Agent D: stock check", button: "Check stock now", link: "Open Promotions",
    text: "Compares each product's stock with what sold in the last 30 days. Too much stock gets a promotion proposal; nothing starts until you approve it.",
    stats: [["short", "Products short"], ["over", "Overstocked"], ["proposed", "Promotions proposed"]],
  },
  atlas: {
    title: "Agent D: room check", button: "Check rooms now", link: "Open Hotel deals",
    text: "Compares the rooms booked on the coming nights with each hotel's rooms. Nights at 30% or less get a deal proposal; nothing starts until you approve it.",
    stats: [["overbooked", "Hotels at risk of overbooking"], ["low", "Hotels with empty nights"], ["proposed", "Deals proposed"]],
  },
};

export default function CheckNow({ company = "shopnova" }) {
  const co = COMPANIES[company];
  const w = WORDS[company];
  const { expired } = useAuth();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function run() {
    if (running) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await co.owner.scan());
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_logged_in") { expired(); return; }
      setError(e);
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="panel stack" aria-label={w.title}>
      <div className="panel-head">
        <h2>{w.title}</h2>
        <button type="button" className="btn btn-primary btn-sm" onClick={run} disabled={running} aria-busy={running}>
          {running ? <span className="spinner" aria-hidden="true" /> : <Icon name="refresh" size={14} />}
          {running ? "Checking…" : w.button}
        </button>
      </div>
      <p className="small muted">{w.text}</p>
      {error && <ApiErrorView error={error} onRetry={run} />}
      {result && (
        <div className="stack" role="status" aria-live="polite">
          <div className="stats">
            {w.stats.map(([k, label]) => <Stat key={k} label={label} value={result.counts[k]} />)}
          </div>
          <div><Link to={co.ownerPath} className="btn btn-sm"><Icon name="tag" size={14} />{w.link}</Link></div>
        </div>
      )}
    </section>
  );
}
