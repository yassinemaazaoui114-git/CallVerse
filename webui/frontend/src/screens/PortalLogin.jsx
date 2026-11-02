// One sign-in page per portal: ShopNova (/shop/login), Atlas Travel (/atlas/login), CallVerse Console
// (/console/login). Same form, same accounts, same session; each page has its own name, colours and words, and
// names no other company. The server decides who may sign in on which page: a wrong password and an account of
// another portal get the same answer, shown as the same sentence.
//
// - ?next= is kept only when it is a path of THIS portal; after sign-in it is followed only into the account's
//   own area (a customer is never sent to the store team's pages), else the account's home.
// - Already signed in through this portal: straight to the return path or home.
// - Signed in with an account of another portal: the page says so and offers Log out (one browser, one session).
import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api.js";
import { useAuth } from "../auth.jsx";
import Icon from "../components/Icon.jsx";
import { Loading } from "../components/States.jsx";
import { homeFor } from "../hooks.js";
import { PORTALS, nextForSession, nextInPortal, portalOfSession } from "../portals.js";

const GENERIC = "Wrong username or password, or this account does not sign in on this page.";

export function usePortalTheme(cfg) {
  useEffect(() => {
    document.documentElement.dataset.theme = cfg.theme;
    document.title = `Sign in · ${cfg.title}`;
    return () => { delete document.documentElement.dataset.theme; };
  }, [cfg.theme, cfg.title]);
}

export default function PortalLogin({ portal }) {
  const cfg = PORTALS[portal];
  const { session, status, notice, login, logout, setNotice, refresh } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = nextInPortal(params.get("next"), portal);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [leaving, setLeaving] = useState(false);
  const errorRef = useRef(null);
  usePortalTheme(cfg);

  useEffect(() => { if (error && errorRef.current) errorRef.current.focus(); }, [error]);

  if (status === "loading") return <Loading text="Checking your session…" />;
  if (session && portalOfSession(session) === portal) {
    return <Navigate to={nextForSession(next, session) || homeFor(session)} replace />;
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const who = await login(username.trim(), password, portal);
      navigate(nextForSession(next, who) || homeFor(who), { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "bad_login") setError(GENERIC);
      else if (err instanceof ApiError && err.code === "unavailable") setError("The CallVerse API is not reachable. Start it, then try again.");
      else setError((err && err.message) || "Sign-in failed.");
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  async function onLeave() {
    setLeaving(true);
    try { await logout(); } catch (e) { setError("Log out failed: you are still signed in. Try again."); } finally { setLeaving(false); }
  }

  return (
    <div className={`portal-wrap portal-${portal}`}>
      <div className="portal">
        <aside className="portal-brand" aria-label={cfg.title}>
          <div className="portal-mark" aria-hidden="true"><Icon name={cfg.icon} size={24} /></div>
          <div className="logo portal-logo">{cfg.logo[0]}<span>{cfg.logo[1]}</span></div>
          <p className="portal-lead">{cfg.lead}</p>
          <ul className="portal-points">
            {cfg.points.map((p) => <li key={p}><Icon name="check" size={14} />{p}</li>)}
          </ul>
        </aside>

        <main className="portal-form" id="main">
          <div className="stack" style={{ gap: "var(--cv-s1)" }}>
            <h1>{cfg.heading}</h1>
            <p className="muted small">{cfg.who}</p>
          </div>

          {status === "unavailable" && (
            <div className="alert alert-danger" role="alert">
              <Icon name="alert" />
              <div className="stack" style={{ gap: "var(--cv-s1)" }}>
                <strong>The CallVerse API is not reachable</strong>
                <span className="small">Start it with <code>python -m webui.api.run</code>, then retry.</span>
              </div>
              <div className="actions"><button type="button" className="btn btn-sm" onClick={refresh}>Retry</button></div>
            </div>
          )}

          {notice && !error && (
            <div className="alert" role="status">
              <Icon name="info" />
              <span className="small">{notice}</span>
              <div className="actions"><button type="button" className="btn btn-ghost btn-sm" aria-label="Dismiss" onClick={() => setNotice(null)}><Icon name="x" size={14} /></button></div>
            </div>
          )}

          {session ? (
            <div className="alert alert-warn" role="status">
              <Icon name="lock" />
              <div className="stack" style={{ gap: "var(--cv-s2)" }}>
                <strong>You are signed in as {session.name || session.username}.</strong>
                <span className="small">That account does not use this page. Log out first to sign in with a {cfg.title} account.</span>
                {error && <span className="small" role="alert">{error}</span>}
                <div><button type="button" className="btn btn-sm" onClick={onLeave} disabled={leaving}><Icon name="logout" size={14} />{leaving ? "Logging out…" : "Log out"}</button></div>
              </div>
            </div>
          ) : (
            <form onSubmit={onSubmit} noValidate className="stack" style={{ gap: "var(--cv-s4)" }} aria-busy={busy}>
              <div className="field">
                <label htmlFor={`${portal}-username`}>Username</label>
                <input id={`${portal}-username`} className="input" autoComplete="username" autoCapitalize="none" spellCheck={false}
                  value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus disabled={busy}
                  aria-describedby={error ? "login-error" : undefined} aria-invalid={error ? true : undefined} />
              </div>
              <div className="field">
                <label htmlFor={`${portal}-password`}>Password</label>
                <div className="pw-wrap">
                  <input id={`${portal}-password`} className="input" type={show ? "text" : "password"} autoComplete="current-password"
                    value={password} onChange={(e) => setPassword(e.target.value)} required disabled={busy}
                    aria-describedby={error ? "login-error" : undefined} aria-invalid={error ? true : undefined} />
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShow((s) => !s)}
                    aria-pressed={show} aria-label={show ? "Hide password" : "Show password"}>
                    <Icon name="eye" size={16} />{show ? "Hide" : "Show"}
                  </button>
                </div>
              </div>
              {error && (
                <div id="login-error" className="alert alert-danger" role="alert" tabIndex={-1} ref={errorRef}>
                  <Icon name="alert" /><span className="small">{error}</span>
                </div>
              )}
              <button type="submit" className="btn btn-primary portal-submit" disabled={busy || !username || !password}>
                {busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="lock" size={16} />}
                {busy ? "Signing in…" : "Sign in"}
              </button>
            </form>
          )}
        </main>
      </div>
    </div>
  );
}
