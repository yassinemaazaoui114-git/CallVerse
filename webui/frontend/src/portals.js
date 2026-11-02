// The three sign-in portals and the rules that tie a page to a portal. The SERVER decides who may sign in where
// (POST /api/auth/login checks the portal against the accounts file); this file only decides where the browser
// goes: which sign-in page a protected link, a logout or an expired session leads to, and which return path
// (?next=) may be followed after a sign-in.
//
//   area    = whose pages a path belongs to: shop-customer (/shop/…), shop-admin (/admin/…),
//             atlas-customer (/atlas/…), atlas-admin (/atlas/admin/…), console (/tickets, /agents, /dashboard)
//   portal  = the sign-in page of an area: shop, atlas, console

export const PORTALS = {
  shop: {
    key: "shop", login: "/shop/login", theme: "shopnova", title: "ShopNova", logo: ["Shop", "Nova"], icon: "bag",
    heading: "Sign in to ShopNova",
    lead: "Follow your orders, ask for help and see your refunds in one place.",
    points: ["Your orders and deliveries", "Help chat that knows your order", "Store team: approvals, dashboard, catalogue"],
    who: "ShopNova customers and the ShopNova store team sign in here.",
  },
  atlas: {
    key: "atlas", login: "/atlas/login", theme: "atlas", title: "Atlas Travel", logo: ["Atlas ", "Travel"], icon: "plane",
    heading: "Sign in to Atlas Travel",
    lead: "Your flights, hotel stays and travel help, together.",
    points: ["Flights and hotel stays", "Help chat about a booking", "Travel team: approvals, records, dashboard"],
    who: "Atlas Travel travellers and the Atlas Travel team sign in here.",
  },
  console: {
    key: "console", login: "/console/login", theme: "console", title: "CallVerse Console", logo: ["CallVerse ", "Console"], icon: "radio",
    heading: "Supervisor sign-in",
    lead: "The live view of the CallVerse center: every ticket, agent step and decision.",
    points: ["Live tickets for every company", "How the agents worked, step by step", "Center dashboard and model usage"],
    who: "For CallVerse supervisors only.",
  },
};

const LOGIN_PATHS = new Set(["/login", "/shop/login", "/atlas/login", "/console/login"]);

// The area a pathname belongs to, or null (sign-in pages, the chooser, unknown paths).
export function areaOfPath(pathname) {
  if (typeof pathname !== "string" || LOGIN_PATHS.has(pathname)) return null;
  const is = (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`);
  if (is("/atlas/admin")) return "atlas-admin";
  if (is("/atlas")) return "atlas-customer";
  if (is("/admin")) return "shop-admin";
  if (is("/shop")) return "shop-customer";
  if (is("/tickets") || is("/agents") || is("/dashboard")) return "console";
  return null;
}

export function portalOfArea(area) {
  if (!area) return null;
  if (area.startsWith("shop")) return "shop";
  if (area.startsWith("atlas")) return "atlas";
  return area === "console" ? "console" : null;
}

export const portalOfPath = (pathname) => portalOfArea(areaOfPath(pathname));

// The area of the signed-in account (from the session the API returned; the API took it from the file).
export function areaOfSession(session) {
  if (!session) return null;
  if (session.role === "supervisor") return "console";
  const side = session.role === "admin" ? "admin" : session.role === "user" ? "customer" : null;
  if (!side) return null;
  if (session.company === "atlas") return `atlas-${side}`;
  if (session.company === "shopnova") return `shop-${side}`;
  return null;
}

export function portalOfSession(session) {
  if (!session) return null;
  return session.portal || portalOfArea(areaOfSession(session));
}

export function loginPathFor(portal) {
  return PORTALS[portal] ? PORTALS[portal].login : "/login";
}

// A return path the browser may follow: an app path on THIS origin (not "//host", no scheme, no backslash, no
// control character), that belongs to an area. Anything else is dropped (null).
export function cleanNext(raw) {
  if (typeof raw !== "string" || !raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\")) return null;
  if (/[\u0000-\u001f\u007f]/.test(raw)) return null;
  const base = "http://callverse.invalid";
  let url;
  try { url = new URL(raw, base); } catch (e) { return null; }
  if (url.origin !== base || !areaOfPath(url.pathname)) return null;
  return url.pathname + url.search + url.hash;
}

// The return path kept on a portal's sign-in page: only one inside that portal.
export function nextInPortal(raw, portal) {
  const path = cleanNext(raw);
  return path && portalOfPath(new URL(path, "http://callverse.invalid").pathname) === portal ? path : null;
}

// After sign-in: follow the return path only into the signed-in account's OWN area (a ShopNova customer is never
// sent to /admin/…, even though both sign in on /shop/login); otherwise the account's home.
export function nextForSession(raw, session) {
  const path = cleanNext(raw);
  return path && areaOfPath(new URL(path, "http://callverse.invalid").pathname) === areaOfSession(session) ? path : null;
}

// Where a protected page sends a visitor who is not signed in: its portal's sign-in page with the path as ?next=.
export function loginRedirect(pathname, search = "") {
  const portal = portalOfPath(pathname);
  if (!portal) return "/login";
  const next = cleanNext(pathname + search);
  return next ? `${PORTALS[portal].login}?next=${encodeURIComponent(next)}` : PORTALS[portal].login;
}
