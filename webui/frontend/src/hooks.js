// useGuardedLoad: load data for a screen with the step-1 safety rules in one place.
// - every call is numbered; only the latest call may change the state (an older answer is dropped);
// - the previous request is aborted when a new one starts, and on unmount;
// - a 401 is reported to the auth context (session expired) instead of being shown as an error.
//
//   const { data, error, loading, reload } = useGuardedLoad((signal) => api.order(id, signal), [id]);
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api.js";
import { useAuth } from "./auth.jsx";

export function useGuardedLoad(fetcher, deps) {
  const { expired } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const requestNo = useRef(0);
  const controller = useRef(null);

  const load = useCallback(async () => {
    if (controller.current) controller.current.abort();
    const mine = ++requestNo.current;
    const ctrl = new AbortController();
    controller.current = ctrl;
    setLoading(true);
    setError(null);
    try {
      const body = await fetcher(ctrl.signal);
      if (mine !== requestNo.current) return;
      setData(body);
    } catch (e) {
      if (mine !== requestNo.current || (e && e.name === "AbortError")) return;
      if (e instanceof ApiError && e.code === "not_logged_in") { expired(); return; }
      setError(e);
    } finally {
      if (mine === requestNo.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, expired]);

  useEffect(() => {
    setData(null);
    load();
    return () => { if (controller.current) controller.current.abort(); };
  }, [load]);

  return { data, error, loading, reload: load };
}

// Where an account lands after login: the supervisor in the Console, a ShopNova customer in My orders, every
// other account (ShopNova admin, Atlas accounts) on the "workspace not available yet" page.
export function homeFor(session) {
  if (!session) return "/login";
  if (session.role === "supervisor") return "/tickets";
  if (session.role === "user" && session.company === "shopnova") return "/shop/orders";
  return "/workspace";
}

// Money and dates as the ShopNova app shows them.
export function tnd(amount) {
  const n = Number(amount || 0);
  return `${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} TND`;
}

// A status code from the database as words for the screen (the raw code is kept next to it in the markup).
export function words(code) {
  return String(code ?? "—").replace(/_/g, " ");
}
