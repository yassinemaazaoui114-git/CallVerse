// The login screen: username + password (show/hide), the API's error words under the form, a notice when the
// session expired. After a login the user goes back to the page they wanted (state.from) or to Live tickets.
import { useEffect, useRef, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { ApiError } from "../api.js";
import Icon from "../components/Icon.jsx";
import { Loading } from "../components/States.jsx";

export default function Login() {
  const { session, status, notice, login, setNotice, refresh } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const errorRef = useRef(null);

  useEffect(() => { if (error && errorRef.current) errorRef.current.focus(); }, [error]);

  if (status === "loading") return <Loading text="Checking your session…" />;
  if (session) return <Navigate to={(location.state && location.state.from) || "/tickets"} replace />;

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      navigate((location.state && location.state.from) || "/tickets", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "bad_login") setError("Wrong username or password.");
      else if (err instanceof ApiError && err.code === "unavailable") setError("The CallVerse API is not reachable. Start it, then try again.");
      else if (err instanceof ApiError && err.code === "no_accounts") setError(err.message);
      else setError((err && err.message) || "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="panel login-card">
        <div>
          <div className="logo">CallVerse <span>Console</span></div>
          <p className="muted small">The center's control room · read only · supervisor login</p>
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
        <form onSubmit={onSubmit} noValidate>
          <div className="field">
            <label htmlFor="username">Username</label>
            <input id="username" className="input" autoComplete="username" value={username}
              onChange={(e) => setUsername(e.target.value)} required autoFocus
              aria-describedby={error ? "login-error" : undefined} aria-invalid={error ? true : undefined} />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <div className="pw-wrap">
              <input id="password" className="input" type={show ? "text" : "password"} autoComplete="current-password"
                value={password} onChange={(e) => setPassword(e.target.value)} required
                aria-describedby={error ? "login-error" : undefined} aria-invalid={error ? true : undefined} />
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShow((s) => !s)}
                aria-pressed={show} aria-label={show ? "Hide password" : "Show password"}>
                <Icon name={show ? "eyeOff" : "eye"} size={16} />{show ? "Hide" : "Show"}
              </button>
            </div>
          </div>
          {error && (
            <div id="login-error" className="alert alert-danger" role="alert" tabIndex={-1} ref={errorRef}>
              <Icon name="alert" /><span className="small">{error}</span>
            </div>
          )}
          <button type="submit" className="btn btn-primary" disabled={busy || !username || !password}>
            {busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="lock" size={16} />}
            {busy ? "Logging in…" : "Log in"}
          </button>
        </form>
      </div>
    </div>
  );
}
