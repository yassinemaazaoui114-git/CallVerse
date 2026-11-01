// The app shell: skip link, top bar (logo, compact navigation, who is logged in, log out) and the content area.
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import Icon from "./Icon.jsx";

export default function Shell() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
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
            <button type="button" className="btn btn-ghost btn-sm" onClick={onLogout}>
              <Icon name="logout" size={14} />Log out
            </button>
          </div>
        </div>
      </header>
      <main id="main" className="content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
