// The app shell: skip link, top bar (brand, compact navigation, who is logged in, log out) and the content
// area. One shell for every area; `area` picks the brand, the menu and the theme (data-theme on <html>):
//   console  = the CallVerse Console (dark control room, supervisor)
//   shopnova = the ShopNova customer site (light, coral accent)
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import Icon from "./Icon.jsx";

export const AREAS = {
  console: {
    theme: "console", home: "/tickets", brand: ["CallVerse ", "Console"],
    nav: [{ to: "/tickets", label: "Live tickets", icon: "radio" }, { to: "/agents", label: "Agents", icon: "brain" }, { to: "/dashboard", label: "Dashboard", icon: "chart" }],
  },
  shopnova: {
    theme: "shopnova", home: "/shop/orders", brand: ["Shop", "Nova"],
    nav: [{ to: "/shop/orders", label: "My orders", icon: "bag" }, { to: "/shop/chat", label: "Help chat", icon: "chat" }],
  },
  "shopnova-admin": {
    theme: "shopnova", home: "/admin/approvals", brand: ["Shop", "Nova admin"],
    nav: [{ to: "/admin/approvals", label: "Refund approvals", icon: "bank" }, { to: "/admin/dashboard", label: "Dashboard", icon: "chart" }, { to: "/admin/manage", label: "Manage", icon: "pen" }],
  },
  atlas: {
    theme: "atlas", home: "/atlas/bookings", brand: ["Atlas ", "Travel"],
    nav: [{ to: "/atlas/bookings", label: "My bookings", icon: "plane" }, { to: "/atlas/chat", label: "Help chat", icon: "chat" }],
  },
  "atlas-admin": {
    theme: "atlas", home: "/atlas/admin/approvals", brand: ["Atlas ", "Travel admin"],
    nav: [{ to: "/atlas/admin/approvals", label: "Approvals", icon: "bank" }, { to: "/atlas/admin/dashboard", label: "Dashboard", icon: "chart" }, { to: "/atlas/admin/records", label: "Records", icon: "file" }],
  },
  none: { theme: "console", home: "/workspace", brand: ["Call", "Verse"], nav: [] },
};

export default function Shell({ area = "console" }) {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [logoutError, setLogoutError] = useState(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const cfg = AREAS[area] || AREAS.console;   // a fixed object per area, so the effect below runs once per area

  // The theme lives on <html> so the page background and the scrollbars follow it too.
  useEffect(() => {
    document.documentElement.dataset.theme = cfg.theme;
    document.title = cfg.brand.join("");
    return () => { delete document.documentElement.dataset.theme; };
  }, [cfg.theme, cfg.brand]);

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
          <NavLink to={cfg.home} className="logo">{cfg.brand[0]}<span>{cfg.brand[1]}</span></NavLink>
          {cfg.nav.length > 0 && (
            <nav className="nav" aria-label={cfg.brand.join("")}>
              {cfg.nav.map((n) => (
                <NavLink key={n.to} to={n.to} aria-label={n.label}><Icon name={n.icon} size={16} /><span className="label">{n.label}</span></NavLink>
              ))}
            </nav>
          )}
          <div className="who">
            {session && (
              <span className="name">
                <strong>{session.name || session.username}</strong> · {session.role}
              </span>
            )}
            <button type="button" className="btn btn-ghost btn-sm" onClick={onLogout} disabled={loggingOut} aria-label={loggingOut ? "Logging out" : "Log out"}>
              <Icon name="logout" size={14} /><span className="label">{loggingOut ? "Logging out…" : "Log out"}</span>
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
        {/* keyed by the path: the page content rises in once per navigation; a refresh of the data on the same
            page changes nothing here, so the entrance never replays */}
        <div className="page-enter" key={location.pathname}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
