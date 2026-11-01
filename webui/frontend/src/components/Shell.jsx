// The app shell: skip link, top bar (logo, compact navigation, who is logged in, log out) and the content area.
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import Icon from "./Icon.jsx";

export default function Shell() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const [logoutError, setLogoutError] = useState(null);
  const [loggingOut, setLoggingOut] = useState(false);

  // Logout: the user stays logged in (and on this page) until the server confirmed the session is gone.
  async function onLogout() {
    setLoggingOut(true);
    setLogoutError(null);
    try {
      await logout();
      navigate("/login", { replace: true });
    } catch (e) {
      setLogoutError(e);
    } finally {
      setLoggingOut(false);
    }
  }

  return (
    <div className="shell">
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/tickets" className="logo">CallVerse <span>Console</span></NavLink>
          <nav className="nav" aria-label="Console">
            <NavLink to="/tickets" aria-label="Live tickets"><Icon name="radio" size={16} /><span className="label">Live tickets</span></NavLink>
          </nav>
          <div className="who">
            {session && (
              <span className="name">
                <strong>{session.name || session.username}</strong> · {session.role}
              </span>
            )}
            <button type="button" className="btn btn-ghost btn-sm" onClick={onLogout} disabled={loggingOut}>
              <Icon name="logout" size={14} />{loggingOut ? "Logging out…" : "Log out"}
            </button>
          </div>
        </div>
        {logoutError && (
          <div className="topbar-inner" style={{ paddingTop: 0 }}>
            <div className="alert alert-danger" role="alert" style={{ width: "100%" }}>
              <Icon name="alert" />
              <div className="stack" style={{ gap: "var(--cv-s1)" }}>
                <strong>Log out failed</strong>
                <span className="small">
                  {logoutError.code === "unavailable" ? "The CallVerse API cannot be reached." : logoutError.message}
                  {" "}You are still logged in.
                </span>
              </div>
              <div className="actions row">
                <button type="button" className="btn btn-sm" onClick={onLogout} disabled={loggingOut}><Icon name="refresh" size={14} />Retry</button>
                <button type="button" className="btn btn-ghost btn-sm" aria-label="Dismiss" onClick={() => setLogoutError(null)}><Icon name="x" size={14} /></button>
              </div>
            </div>
          </div>
        )}
      </header>
      <main id="main" className="content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
