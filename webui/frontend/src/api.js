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
    const error = new ApiError(code, message, response.status);
    error.body = body;   // e.g. the admin route's `evidence` on an uncertain decision
    throw error;
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
  // dashboards (step 6): the period is the core's own (the API refuses another one)
  consoleDashboard: (days, signal) => request(`/api/console/dashboard${query({ days })}`, { signal }),
  consoleAgents: (days, signal) => request(`/api/console/agents${query({ days })}`, { signal }),
  consoleGroq: (signal) => request("/api/console/groq", { signal }),
  shopDashboard: (days, signal) => request(`/api/admin/dashboard${query({ days })}`, { signal }),
  atlasDashboard: (days, signal) => request(`/api/atlas/admin/dashboard${query({ days })}`, { signal }),
  // Atlas customer (step 5)
  bookings: (signal) => request("/api/atlas/bookings", { signal }),
  booking: (kind, id, signal) => request(`/api/atlas/bookings/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, { signal }),
  // Atlas admin records (step 5)
  records: (table, search, page, signal) => request(`/api/atlas/admin/records/${encodeURIComponent(table)}${query({ search, page })}`, { signal }),
};

// The chat and the admin queue exist once per company, under their own prefix. A scope binds the calls to one
// prefix; the screens take the scope from the company they serve (COMPANIES below), so ShopNova's and Atlas's
// requests can never cross.
export function chatScope(prefix) {
  return {
    chat: (ticket, signal) => request(`${prefix}/chat${query({ ticket })}`, { signal }),
    chatJob: (signal) => request(`${prefix}/chat/job`, { signal }),
    markRead: (ticketId) => request(`${prefix}/chat/tickets/${encodeURIComponent(ticketId)}/read`, { method: "POST" }),
    // The two streaming calls return the raw fetch Response (read with sse.js); a non-2xx answer throws ApiError.
    chatSend: (body, signal) => streamRequest(`${prefix}/chat/send`, { method: "POST", body: JSON.stringify(body), signal }),
    chatJobStream: (signal) => streamRequest(`${prefix}/chat/job/stream`, { signal }),
  };
}

export function adminScope(prefix) {
  return {
    approvals: (status, signal) => request(`${prefix}${query({ status })}`, { signal }),
    approval: (id, signal) => request(`${prefix}/${encodeURIComponent(id)}`, { signal }),
    decide: (id, body) => request(`${prefix}/${encodeURIComponent(id)}/decide`, { method: "POST", body: JSON.stringify(body) }),
  };
}

// T27: Agent D's owner screens (Promotions at ShopNova, Hotel deals at Atlas) and the "Check now" scan.
export function ownerScope(prefix, scanPath) {
  return {
    list: (status, signal) => request(`${prefix}${query({ status })}`, { signal }),
    decide: (id, body) => request(`${prefix}/${encodeURIComponent(id)}/decision`, { method: "POST", body: JSON.stringify(body) }),
    scan: () => request(scanPath, { method: "POST" }),
  };
}

// What differs between the two companies' screens: words, routes and API prefixes. Everything else is shared.
export const COMPANIES = {
  shopnova: {
    key: "shopnova", name: "ShopNova", chat: chatScope("/api/shop"), admin: adminScope("/api/admin/approvals"),
    contextParam: "order", contextWord: "order", contextField: "about_order",
    home: "/shop/orders", chatPath: "/shop/chat", adminPath: "/admin/approvals",
    listLabel: "My orders", caseWord: "order",
    owner: ownerScope("/api/admin/promotions", "/api/admin/stock-check"), ownerPath: "/admin/promotions",
  },
  atlas: {
    key: "atlas", name: "Atlas Travel", chat: chatScope("/api/atlas"), admin: adminScope("/api/atlas/admin/approvals"),
    contextParam: "booking", contextWord: "booking", contextField: "about_booking",
    home: "/atlas/bookings", chatPath: "/atlas/chat", adminPath: "/atlas/admin/approvals",
    listLabel: "My bookings", caseWord: "booking",
    owner: ownerScope("/api/atlas/admin/deals", "/api/atlas/admin/room-check"), ownerPath: "/atlas/admin/deals",
  },
};

// Backwards-compatible names (ShopNova) used by the step 3 / 4 screens and tests.
Object.assign(api, COMPANIES.shopnova.chat, COMPANIES.shopnova.admin);

async function streamRequest(path, options = {}) {
  const headers = { Accept: "text/event-stream" };
  if (options.method && options.method !== "GET") {
    headers["X-Requested-With"] = "CallVerse";
    headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  } catch (e) {
    if (e && e.name === "AbortError") throw e;
    throw new ApiError("unavailable", "The CallVerse API cannot be reached.", 0);
  }
  if (!response.ok) {
    let body = null;
    try { body = await response.json(); } catch (e) { body = null; }
    if (body === null && response.status >= 500) throw new ApiError("unavailable", "The CallVerse API cannot be reached.", response.status);
    throw new ApiError((body && body.error) || `http_${response.status}`, (body && body.message) || `The API answered ${response.status}.`, response.status);
  }
  return response;
}
