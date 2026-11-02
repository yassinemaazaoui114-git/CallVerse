// useGuardedLoad: load data for a screen with the step-1 safety rules in one place.
// - every call is numbered; only the latest call may change the state (an older answer is dropped);
// - the previous request is aborted when a new one starts, and on unmount;
// - a 401 is reported to the auth context (session expired) instead of being shown as an error.
//
//   const { data, error, loading, reload } = useGuardedLoad((signal) => api.order(id, signal), [id]);
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api.js";
import { useAuth } from "./auth.jsx";

// `keep: true` leaves the previous answer on screen (dimmed by the caller) while the next one loads: the
// dashboards use it so a period change never blanks the numbers; a late answer of the old period is still dropped.
export function useGuardedLoad(fetcher, deps, { keep = false } = {}) {
  const { expired } = useAuth();
  const [data, setData] = useState(null);
  const [dataDeps, setDataDeps] = useState(null);   // the deps the shown `data` was loaded for (JSON)
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const requestNo = useRef(0);
  const controller = useRef(null);
  const depsKey = JSON.stringify(deps);

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
      setDataDeps(depsKey);
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
    if (!keep) setData(null);
    load();
    return () => { if (controller.current) controller.current.abort(); };
  }, [load, keep]);

  // isCurrent: the shown data belongs to the CURRENT deps (false while another period / id loads or failed).
  return { data, error, loading, reload: load, isCurrent: data !== null && dataDeps === depsKey };
}

// Where an account lands after login: the supervisor in the Console, a ShopNova customer in My orders, every
// other account (ShopNova admin, Atlas accounts) on the "workspace not available yet" page.
export function homeFor(session) {
  if (!session) return "/login";
  if (session.role === "supervisor") return "/tickets";
  if (session.role === "user" && session.company === "shopnova") return "/shop/orders";
  if (session.role === "admin" && session.company === "shopnova") return "/admin/approvals";
  if (session.role === "user" && session.company === "atlas") return "/atlas/bookings";
  if (session.role === "admin" && session.company === "atlas") return "/atlas/admin/approvals";
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
