// Who is logged in, for the whole app (React context). The truth is the API's session cookie: on start the app
// asks GET /api/auth/session; a 401 anywhere later (session expired) sends the user back to the login page
// with a "session expired" note. The role is never decided here: the API checks it on every request.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);   // {username, name, role, company} or null
  const [status, setStatus] = useState("loading"); // loading | ready | unavailable
  const [notice, setNotice] = useState(null);      // a one-line message for the login page ("session expired")

  const refresh = useCallback(async () => {
    try {
      const body = await api.session();
      setSession(body.session);
      setStatus("ready");
    } catch (e) {
      if (e instanceof ApiError && e.code === "unavailable") setStatus("unavailable");
      else { setSession(null); setStatus("ready"); }
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = useCallback(async (username, password) => {
    const body = await api.login(username, password);
    setSession(body.session);
    setNotice(null);
    return body.session;
  }, []);

  const logout = useCallback(async () => {
    try { await api.logout(); } catch (e) { /* the cookie is gone either way once we drop the session */ }
    setSession(null);
    setNotice("You are logged out.");
  }, []);

  // Called by a screen that got 401 while it was working: the session expired (or was removed on the server).
  const expired = useCallback(() => {
    setSession(null);
    setNotice("Your session expired. Please log in again.");
  }, []);

  const value = useMemo(() => ({ session, status, notice, login, logout, expired, refresh, setNotice }),
    [session, status, notice, login, logout, expired, refresh]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
