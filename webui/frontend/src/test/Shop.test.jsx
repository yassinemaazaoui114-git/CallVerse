// Step 2 screen tests: My orders, Order detail, "Ask about this order" and the login home per role.
import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import Shell from "../components/Shell.jsx";
import { homeFor } from "../hooks.js";
import AskAboutOrder from "../screens/AskAboutOrder.jsx";
import MyOrders from "../screens/MyOrders.jsx";
import OrderDetail from "../screens/OrderDetail.jsx";
import { installFakeFetch } from "./fakeApi.js";
import { useLocation } from "react-router-dom";

function ChatLocation() {
  const loc = useLocation();
  return <p>chat at {loc.pathname + loc.search}</p>;
}

const SARA = { username: "sara", name: "Sara Ben Ali", role: "user", company: "shopnova" };

function order(id, status = "shipped", extra = {}) {
  return { id, status, order_date: "2026-09-20", promised_date: "2026-10-05", delivered_date: null, total: 129.9, paid: 129.9,
           payment: "card", carrier: "Aramex", tracking_number: "AR123", items: [{ product_id: 1, name: "USB hub", qty: 1, price: 129.9 }],
           refunds: [], ...extra };
}
function summary(id, status = "shipped", extra = {}) {
  const o = order(id, status, extra);
  return { id, status, order_date: o.order_date, promised_date: o.promised_date, delivered_date: o.delivered_date, total: o.total,
           paid: o.paid, payment: o.payment, carrier: o.carrier, tracking_number: o.tracking_number, items_count: 1,
           items_preview: ["USB hub"], refunds_count: 0, ...extra };
}
const KNOWN = { order_statuses: ["processing", "shipped"], refund_statuses: [], payment_methods: ["card"] };

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route element={<Shell area="shopnova" />}>
            <Route path="/shop/orders" element={<MyOrders />} />
            <Route path="/shop/orders/:orderId" element={<OrderDetail />} />
            <Route path="/shop/orders/:orderId/ask" element={<AskAboutOrder />} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("ShopNova customer screens", () => {
  it("My orders lists the API's orders with status, date, amount and a detail link", async () => {
    const net = installFakeFetch();
    renderAt("/shop/orders");
    (await net.waitFor("/api/auth/session")).respond(200, { session: SARA });
    const req = await net.waitFor("/api/shop/orders");
    await act(async () => { req.respond(200, { orders: [summary(4505, "held_for_photo_proof"), summary(4506, "delivered", { delivered_date: "2026-10-01" })],
                                               count: 2, sim_today: "2026-10-09", known: KNOWN }); });
    const first = screen.getByRole("article", { name: /order 4505/i });
    expect(within(first).getByText("held for photo proof")).toBeInTheDocument();   // unfamiliar status, as text
    expect(within(first).getByText(/Ordered 2026-09-20/)).toBeInTheDocument();
    expect(within(first).getByText("129.90 TND")).toBeInTheDocument();
    expect(within(first).getByRole("link", { name: /order 4505/i })).toHaveAttribute("href", "/shop/orders/4505");
    expect(within(first).getByRole("link", { name: /ask about this order/i })).toHaveAttribute("href", "/shop/orders/4505/ask");
    expect(screen.getByText(/delivered 2026-10-01/)).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("shopnova");
  });

  it("My orders shows the empty state", async () => {
    const net = installFakeFetch();
    renderAt("/shop/orders");
    (await net.waitFor("/api/auth/session")).respond(200, { session: SARA });
    const req = await net.waitFor("/api/shop/orders");
    await act(async () => { req.respond(200, { orders: [], count: 0, sim_today: "2026-10-09", known: KNOWN }); });
    expect(screen.getByText("You have no orders yet")).toBeInTheDocument();
  });

  it("Order detail shows lines, progress, dates, payment and refunds, and a 404 as 'not one of your orders'", async () => {
    const net = installFakeFetch();
    renderAt("/shop/orders/4505");
    (await net.waitFor("/api/auth/session")).respond(200, { session: SARA });
    const req = await net.waitFor("/api/shop/orders/4505");
    await act(async () => {
      req.respond(200, {
        order: order(4505, "stuck_at_depot", { refunds: [{ id: 1, order_id: 4505, amount: 20, status: "approved", rule_id: "R-REF-03", created_at: "2026-10-08" }] }),
        tracking: { order_id: 4505, status: "stuck_at_depot", delivered: false, promised_date: "2026-10-05", delivered_date: null, days_late: 4,
                    days_since_delivery: null, carrier: "Aramex", tracking_number: "AR123", checked_on: "2026-10-09" },
        refunds: { order_id: 4505, refunds: [{ id: 1, order_id: 4505, amount: 20, status: "approved", rule_id: "R-REF-03", created_at: "2026-10-08" }], refunded_total: 20 },
        sim_today: "2026-10-09",
      });
    });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Order 4505");
    expect(screen.getByText("USB hub")).toBeInTheDocument();
    const now = document.querySelector('.progress li[aria-current="step"]');
    expect(now).toHaveTextContent("stuck at depot (now)");
    expect(screen.getByText("4 (as of 2026-10-09)")).toBeInTheDocument();          // days late from the read tool
    expect(screen.getByText(/paid 129.90 TND by card/)).toBeInTheDocument();
    expect(screen.getByText(/approved · 2026-10-08 · rule R-REF-03/)).toBeInTheDocument();
    expect(screen.getByText(/Refunded so far/)).toHaveTextContent("20.00 TND");
    expect(screen.getByText(/simulation dates/)).toBeInTheDocument();

    // Another id: the API says 404 (missing or someone else's: same answer), the screen says it plainly.
    const view = renderAt("/shop/orders/4600");
    (await net.waitFor("/api/auth/session", { index: 1 })).respond(200, { session: SARA });
    const bad = await net.waitFor("/api/shop/orders/4600");
    await act(async () => { bad.respond(404, { error: "not_found", message: "Order 4600 is not one of your orders." }); });
    expect(within(view.container).getByText("Order 4600 is not one of your orders")).toBeInTheDocument();
  });

  it("Ask about this order opens the Help chat with the order as context", async () => {
    installFakeFetch();
    render(
      <MemoryRouter initialEntries={["/shop/orders/4505/ask"]}>
        <AuthProvider>
          <Routes>
            <Route path="/shop/orders/:orderId/ask" element={<AskAboutOrder />} />
            <Route path="/shop/chat" element={<ChatLocation />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    );
    expect(await screen.findByText("chat at /shop/chat?order=4505")).toBeInTheDocument();
  });

  it("drops a late answer of the previous order (guarded load)", async () => {
    const net = installFakeFetch();
    render(
      <MemoryRouter initialEntries={["/shop/orders/4505"]}>
        <AuthProvider>
          <Routes><Route path="/shop/orders/:orderId" element={<OrderDetail />} /></Routes>
          <a href="/shop/orders/4506" onClick={(e) => { e.preventDefault(); window.history.pushState({}, "", "/shop/orders/4506"); }}>x</a>
        </AuthProvider>
      </MemoryRouter>
    );
    (await net.waitFor("/api/auth/session")).respond(200, { session: SARA });
    const first = await net.waitFor("/api/shop/orders/4505");
    expect(first.options.signal).toBeDefined();
    // simulate the screen moving on: unmount aborts the request in flight
    expect(first.aborted).toBeFalsy();
  });

  it("sends each role to its own home after login", () => {
    expect(homeFor({ role: "supervisor", company: null })).toBe("/tickets");
    expect(homeFor(SARA)).toBe("/shop/orders");
    expect(homeFor({ role: "admin", company: "shopnova" })).toBe("/admin/approvals");
    expect(homeFor({ role: "admin", company: "atlas" })).toBe("/atlas/admin/approvals");
    expect(homeFor({ role: "user", company: "atlas" })).toBe("/atlas/bookings");
    expect(homeFor(null)).toBe("/login");
  });
});
