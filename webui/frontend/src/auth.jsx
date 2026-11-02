// Who is logged in, for the whole app (React context). The truth is the API's session cookie: on start the app
// asks GET /api/auth/session; a 401 anywhere later (session expired) sends the user back to the sign-in page of
// the portal they were in, with a "session expired" note. The role is never decided here: the API checks it on
// every request. ONE session per browser, whichever of the three sign-in pages it came through.
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

  const login = useCallback(async (username, password, portal) => {
    const body = await api.login(username, password, portal);
    setSession(body.session);
    setNotice(null);
    return body.session;
  }, []);

  // Logout is only done when the SERVER confirms it: clearing React state would leave the HttpOnly cookie and
  // the server session alive. A failure is thrown to the caller (the shell shows it with Retry). A 401 means
  // the server session is already gone, which is the wanted end state.
  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (e) {
      if (!(e instanceof ApiError && e.code === "not_logged_in")) throw e;
    }
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
