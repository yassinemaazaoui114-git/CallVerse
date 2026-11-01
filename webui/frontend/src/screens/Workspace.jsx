// The page for an account whose screens are not built yet in this delivery (ShopNova admin, Atlas customers and
// admin). It says so plainly and offers to log out; the Streamlit apps keep serving these accounts meanwhile.
import { useAuth } from "../auth.jsx";
import Icon from "../components/Icon.jsx";

const WHERE = {
  "admin:shopnova": "the ShopNova back office (approvals, catalogue, orders)",
  "user:atlas": "the Atlas Travel customer pages (bookings, refunds)",
  "admin:atlas": "the Atlas Travel back office",
};

export default function Workspace() {
  const { session } = useAuth();
  const key = session ? `${session.role}:${session.company || ""}` : "";
  const where = WHERE[key] || `the pages for a ${session ? session.role : ""} account`;
  return (
    <section className="panel stack" aria-label="Workspace not available" style={{ maxWidth: 640 }}>
      <h1>Your workspace is not in this delivery step yet</h1>
      <div className="alert" role="status">
        <Icon name="info" />
        <div className="stack" style={{ gap: "var(--cv-s1)" }}>
          <strong>Logged in as {session ? session.name || session.username : "—"} ({session ? session.role : "—"}{session && session.company ? `, ${session.company}` : ""})</strong>
          <span className="small">This new UI is being built in steps. So far it has the CallVerse Console (supervisor) and the ShopNova customer pages. {where[0].toUpperCase() + where.slice(1)} come in a later step; until then they stay in the existing Streamlit apps.</span>
        </div>
      </div>
      <p className="small muted">Use the Log out button in the top bar to switch account.</p>
    </section>
  );
}
