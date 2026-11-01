// The one place that talks to the API. Every call goes to the same origin (/api/..., proxied by Vite in dev),
// sends the HttpOnly cookie, and adds the X-Requested-With header on POST (the API refuses a POST without it).
//
// Errors are thrown as ApiError with a `code`:
//   "unavailable"     the API could not be reached (network / server down)
//   "not_logged_in"   401 from the API (not logged in, or the session expired)
//   "forbidden"       403: logged in, but not the supervisor
//   "not_found"       404
//   any other `error` code the API sends ({error, message}), or "http_<status>" for a non-JSON answer.
// A cancelled request (AbortSignal) rejects with the browser's AbortError, which the screens ignore.

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message || code);
    this.code = code;
    this.status = status;
  }
}

async function request(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.method && options.method !== "GET") {
    headers["X-Requested-With"] = "CallVerse";
    headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  } catch (e) {
    if (e && e.name === "AbortError") throw e;   // cancelled by the screen: not an API problem
    throw new ApiError("unavailable", "The CallVerse API cannot be reached.", 0);
  }
  let body = null;
  try {
    body = await response.json();
  } catch (e) {
    body = null;
  }
  if (!response.ok) {
    // A 5xx without our JSON shape comes from the dev proxy or a crashed server: the API is not reachable.
    if (body === null && response.status >= 500) {
      throw new ApiError("unavailable", "The CallVerse API cannot be reached.", response.status);
    }
    const code = (body && body.error) || `http_${response.status}`;
    const message = (body && body.message) || `The API answered ${response.status}.`;
    throw new ApiError(code, message, response.status);
  }
  return body;
}

const query = (params) => {
  const q = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => { if (v) q.set(k, v); });
  const s = q.toString();
  return s ? `?${s}` : "";
};

export const api = {
  login: (username, password) =>
    request("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => request("/api/auth/logout", { method: "POST" }),
  session: () => request("/api/auth/session"),
  company: (company) => request(`/api/company${query({ company })}`),
  tickets: (filters, signal) => request(`/api/console/tickets${query(filters)}`, { signal }),
  ticketFilters: (signal) => request("/api/console/tickets/filters", { signal }),
  ticket: (id, signal) => request(`/api/console/tickets/${encodeURIComponent(id)}`, { signal }),
  orders: (signal) => request("/api/shop/orders", { signal }),
  order: (id, signal) => request(`/api/shop/orders/${encodeURIComponent(id)}`, { signal }),
};
