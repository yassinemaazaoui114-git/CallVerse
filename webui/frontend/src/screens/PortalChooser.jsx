// /login: a chooser, not a form. Three links, one per sign-in page. A visitor who is already signed in goes to
// their own home.
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import Icon from "../components/Icon.jsx";
import { Loading } from "../components/States.jsx";
import { homeFor } from "../hooks.js";
import { PORTALS } from "../portals.js";
import { usePortalTheme } from "./PortalLogin.jsx";

const CHOICES = [
  ["shop", "Customers and the store team of ShopNova"],
  ["atlas", "Travellers and the team of Atlas Travel"],
  ["console", "CallVerse supervisors"],
];

const CHOOSER = { theme: "console", title: "CallVerse" };

export default function PortalChooser() {
  const { session, status } = useAuth();
  usePortalTheme(CHOOSER);
  if (status === "loading") return <Loading text="Checking your session…" />;
  if (session) return <Navigate to={homeFor(session)} replace />;
  return (
    <div className="portal-wrap">
      <main className="chooser" id="main">
        <div className="stack" style={{ gap: "var(--cv-s1)" }}>
          <div className="logo">Call<span>Verse</span></div>
          <h1>Where do you want to sign in?</h1>
          <p className="muted small">Each service has its own sign-in page.</p>
        </div>
        <ul className="chooser-list">
          {CHOICES.map(([key, who]) => {
            const p = PORTALS[key];
            return (
              <li key={key}>
                <Link to={p.login} className={`chooser-card chooser-${key}`}>
                  <span className="portal-mark" aria-hidden="true"><Icon name={p.icon} size={20} /></span>
                  <span className="stack" style={{ gap: 2 }}>
                    <strong>{p.title}</strong>
                    <span className="muted small">{who}</span>
                  </span>
                  <Icon name="chevron" size={16} className="chooser-go" />
                </Link>
              </li>
            );
          })}
        </ul>
      </main>
    </div>
  );
}
