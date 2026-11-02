// The three sign-in pages, the chooser and the portal-aware redirects, through the real route tree (AppRoutes):
// return-path validation, unauthenticated deep links, the generic error for a wrong portal, a session of another
// portal, logout and session expiry back to the right sign-in page, and each page's own branding.
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "../App.jsx";
import { AuthProvider } from "../auth.jsx";
import { cleanNext, loginRedirect, nextForSession, nextInPortal } from "../portals.js";
import { installFakeFetch } from "./fakeApi.js";

const S = {
  sara: { username: "sara", name: "Sara Ben Ali", role: "user", company: "shopnova", portal: "shop" },
  admin: { username: "admin", name: "ShopNova Admin", role: "admin", company: "shopnova", portal: "shop" },
  hedi: { username: "hedi", name: "Hedi Karoui", role: "user", company: "atlas", portal: "atlas" },
  supervisor: { username: "supervisor", name: "CallVerse Supervisor", role: "supervisor", company: null, portal: "console" },
};

function Where() {
  const l = useLocation();
  return <span data-testid="where">{l.pathname + l.search}</span>;
}
const where = () => screen.getByTestId("where").textContent;

async function open(path, session = null) {
  const net = installFakeFetch();
  render(<MemoryRouter initialEntries={[path]}><AuthProvider><AppRoutes /><Where /></AuthProvider></MemoryRouter>);
  const s = await net.waitFor("/api/auth/session");
  await act(async () => { session ? s.respond(200, { session }) : s.respond(401, { error: "not_logged_in", message: "Please log in." }); });
  return net;
}

async function signIn(net, username) {
  await userEvent.type(screen.getByLabelText(/^username/i), username);
  await userEvent.type(screen.getByLabelText(/^password/i), "demo-only");
  await act(async () => { screen.getByRole("button", { name: /^sign in$/i }).click(); });
  return net.waitFor("/api/auth/login");
}

describe("portal helpers", () => {
  it("keeps only same-origin app paths, inside the portal, and only into the account's own area", () => {
    for (const bad of ["//evil.com/x", "https://evil.com", "javascript:alert(1)", "/\\evil.com", "/%0d%0a", "evil", "", null, "/login", "/shop/login", "/nowhere", "/\t/evil.com"]) {
      expect(cleanNext(bad)).toBeNull();
    }
    expect(cleanNext("/admin/manage?tab=1#x")).toBe("/admin/manage?tab=1#x");
    expect(nextInPortal("/atlas/bookings", "shop")).toBeNull();
    expect(nextInPortal("/admin/manage", "shop")).toBe("/admin/manage");
    expect(nextInPortal("/tickets/T-0001", "console")).toBe("/tickets/T-0001");
    expect(nextForSession("/admin/manage", S.sara)).toBeNull();          // a customer is never sent to the store team's pages
    expect(nextForSession("/admin/manage", S.admin)).toBe("/admin/manage");
    expect(nextForSession("/atlas/admin/records", S.hedi)).toBeNull();
    expect(loginRedirect("/admin/manage", "?x=1")).toBe("/shop/login?next=%2Fadmin%2Fmanage%3Fx%3D1");
    expect(loginRedirect("/atlas/bookings/flight/7004")).toBe("/atlas/login?next=%2Fatlas%2Fbookings%2Fflight%2F7004");
    expect(loginRedirect("/dashboard")).toBe("/console/login?next=%2Fdashboard");
    expect(loginRedirect("/somewhere")).toBe("/login");
  });
});

describe("Sign-in portals", () => {
  it("a deep link goes to its portal's sign-in page; signing in there returns to it", async () => {
    const net = await open("/admin/manage");
    expect(where()).toBe("/shop/login?next=%2Fadmin%2Fmanage");
    expect(screen.getByRole("heading", { name: "Sign in to ShopNova" })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("shopnova");
    expect(document.body.textContent).not.toMatch(/Atlas|Console/);       // no other company on this page
    const req = await signIn(net, "admin");
    expect(JSON.parse(req.options.body)).toEqual({ username: "admin", password: "demo-only", portal: "shop" });
    await act(async () => { req.respond(200, { session: S.admin }); });
    expect(where()).toBe("/admin/manage");
  });

  it("a customer signing in from a store-team link lands on her own home", async () => {
    const net = await open("/shop/login?next=%2Fadmin%2Fmanage");
    const req = await signIn(net, "sara");
    await act(async () => { req.respond(200, { session: S.sara }); });
    expect(where()).toBe("/shop/orders");
  });

  it("a foreign or off-site return path is dropped", async () => {
    const net = await open("/atlas/login?next=%2F%2Fevil.com%2Fsteal");
    expect(screen.getByRole("heading", { name: "Sign in to Atlas Travel" })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("atlas");
    const req = await signIn(net, "hedi");
    expect(JSON.parse(req.options.body).portal).toBe("atlas");
    await act(async () => { req.respond(200, { session: S.hedi }); });
    expect(where()).toBe("/atlas/bookings");
  });

  it("a wrong portal shows the same generic error as a wrong password, focused, nothing else", async () => {
    const net = await open("/console/login");
    expect(screen.getByRole("heading", { name: "Supervisor sign-in" })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("console");
    const req = await signIn(net, "admin");
    expect(JSON.parse(req.options.body).portal).toBe("console");
    await act(async () => { req.respond(401, { error: "bad_login", message: "Wrong username or password, or this account does not sign in on this page." }); });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Wrong username or password, or this account does not sign in on this page.");
    expect(alert).toHaveFocus();
    expect(screen.getByLabelText(/^password/i)).toHaveValue("");
    expect(where()).toBe("/console/login");
  });

  it("signed in through another portal: the page says so and offers Log out, no form", async () => {
    const net = await open("/atlas/login", S.sara);
    expect(screen.getByText(/You are signed in as Sara Ben Ali/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^password/i)).toBeNull();
    await act(async () => { screen.getByRole("button", { name: /log out/i }).click(); });
    await act(async () => { (await net.waitFor("/api/auth/logout")).respond(200, { ok: true }); });
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("You are logged out.");
    expect(where()).toBe("/atlas/login");
  });

  it("already signed in through this portal: straight to home", async () => {
    await open("/console/login", S.supervisor);
    expect(where()).toBe("/tickets");
  });

  it("/login is a chooser, not a form", async () => {
    await open("/login");
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(screen.getByRole("link", { name: /ShopNova/ })).toHaveAttribute("href", "/shop/login");
    expect(screen.getByRole("link", { name: /Atlas Travel/ })).toHaveAttribute("href", "/atlas/login");
    expect(screen.getByRole("link", { name: /CallVerse Console/ })).toHaveAttribute("href", "/console/login");
  });

  it("logout returns to the account's own sign-in page", async () => {
    const net = await open("/atlas/bookings", S.hedi);
    await act(async () => { screen.getByRole("button", { name: /log out/i }).click(); });
    await act(async () => { (await net.waitFor("/api/auth/logout")).respond(200, { ok: true }); });
    expect(where()).toBe("/atlas/login");
    expect(screen.getByRole("status")).toHaveTextContent("You are logged out.");
  });

  it("an expired session returns to the portal's sign-in page with the path kept", async () => {
    const net = await open("/atlas/bookings", S.hedi);
    await act(async () => { (await net.waitFor("/api/atlas/bookings")).respond(401, { error: "not_logged_in", message: "Please log in." }); });
    expect(where()).toBe("/atlas/login?next=%2Fatlas%2Fbookings");
    expect(screen.getByRole("status")).toHaveTextContent("Your session expired");
    const req = await signIn(net, "hedi");
    await act(async () => { req.respond(200, { session: S.hedi }); });
    expect(where()).toBe("/atlas/bookings");
  });
});
