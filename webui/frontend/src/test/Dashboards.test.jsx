// Step 6 screen tests: the Console dashboard (period race, unknown values, Groq numbers as given, table
// alternative), the Agents cards, the ShopNova and Atlas admin dashboards, and the denied state.
import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import AtlasAdminDashboard from "../screens/AtlasAdminDashboard.jsx";
import ConsoleAgents from "../screens/ConsoleAgents.jsx";
import ConsoleDashboard from "../screens/ConsoleDashboard.jsx";
import ShopAdminDashboard from "../screens/ShopAdminDashboard.jsx";
import { installFakeFetch } from "./fakeApi.js";

const SUP = { username: "supervisor", name: "CallVerse Supervisor", role: "supervisor", company: null };
const PERIODS = { All: null, "Last 7 days": 7, "Last 30 days": 30 };

function dash(tickets, extra = {}) {
  return { days: null, periods: PERIODS, has_tickets: true, no_tickets_message: "No tickets yet — chat in the ShopNova app to see them here.", clock: "computer time", read_at: "2026-11-01T12:00:00",
    dashboard: { tickets, solved_ai: 1, solved_ai_pct: 50, escalated: 0, escalated_pct: 0, finance: 1, finance_pct: 50, replies_timed: 2, replies_untimed: 0,
      avg_reply_s: 4.5, late_s: 30, late: 0, late_pct: 0, finance_approved: 1, finance_refused: 0, finance_pending: 0, refunds_paid: 1, refunds_tnd: 378,
      compensations_paid: 0, compensations_tnd: 0, finance_tnd: 378, reviews: 10, review_avg: 4.1, tokens_avg: 1200, tokens_max: 1200, tokens_total: 2400,
      tokens_per_ticket: [{ ticket: "T-0001", tokens: 1200 }, { ticket: "T-0002", tokens: 1200 }], system_tokens: 50,
      groq_today: { tickets: 4000, system: 50, total: 4050, limit: 200000 },
      per_day: [{ day: "2026-11-01", company: "shopnova", tickets: tickets }], per_company: [{ company: "shopnova", tickets }],
      by_status: [{ status: "Solved", tickets }], money_per_company: [{ company: "shopnova", refunds_paid: 1, refunds_tnd: 378, compensations_paid: 0, compensations_tnd: 0, finance_tnd: 378 }],
      ...extra } };
}

function renderAt(path, element, session = SUP) {
  render(<MemoryRouter initialEntries={[path]}><AuthProvider><Routes>{element}</Routes></AuthProvider></MemoryRouter>);
  return session;
}

describe("Dashboards", () => {
  it("Console dashboard: a period change drops the older answer, Groq numbers are shown as given", async () => {
    const net = installFakeFetch();
    renderAt("/dashboard", <Route path="/dashboard" element={<ConsoleDashboard />} />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SUP });
    const all = await net.waitFor(/\/api\/console\/dashboard\?days=all$/);
    await act(async () => { all.respond(200, dash(2)); });
    expect(screen.getByText("Tickets").closest(".stat")).toHaveTextContent("2");
    expect(screen.getByRole("meter", { name: /groq/i })).toHaveAttribute("aria-valuenow", "4050");
    expect(screen.getByText(/4,050/).closest("p")).toHaveTextContent("4,050 of 200,000 (4,000 in tickets + 50 system)");
    // the user clicks "Last 7 days" then "Last 30 days" before the 7-day answer arrives
    await act(async () => { screen.getByRole("button", { name: "Last 7 days" }).click(); });
    const seven = await net.waitFor("days=7");
    await act(async () => { screen.getByRole("button", { name: "Last 30 days" }).click(); });
    const thirty = await net.waitFor("days=30");
    expect(seven.aborted).toBe(true);
    await act(async () => { seven.done = false; seven.respond(200, { ...dash(7), days: 7 }); });   // a late 7-day answer
    expect(screen.getByText("Tickets").closest(".stat")).toHaveTextContent("2");                   // still the old rows, marked stale
    await act(async () => { thirty.respond(200, { ...dash(30), days: 30 }); });
    expect(screen.getByText("Tickets").closest(".stat")).toHaveTextContent("30");
    expect(screen.getByRole("button", { name: "Last 30 days" })).toHaveAttribute("aria-pressed", "true");
  });

  it("Console dashboard: a missing satisfaction is '—', not 0; the chart has a table alternative; empty states", async () => {
    const net = installFakeFetch();
    renderAt("/dashboard", <Route path="/dashboard" element={<ConsoleDashboard />} />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SUP });
    const all = await net.waitFor("/api/console/dashboard");
    await act(async () => { all.respond(200, dash(2, { review_avg: null, reviews: 0, avg_reply_s: null, replies_timed: 0 })); });
    expect(screen.getByText("Satisfaction (reviews)").closest(".stat")).toHaveTextContent("—");
    expect(screen.getByText("Satisfaction (reviews)").closest(".stat")).toHaveTextContent("no review score available");
    expect(screen.getByText("Average reply time").closest(".stat")).toHaveTextContent("—");
    const chart = screen.getByRole("figure", { name: "Per company" });
    expect(within(chart).getByRole("img")).toHaveAccessibleName("Per company: shopnova 2");
    await act(async () => { within(chart).getByRole("button", { name: /show as table/i }).click(); });
    expect(within(chart).getByRole("table")).toHaveTextContent("shopnova");
    expect(within(chart).getByRole("table")).toHaveTextContent("2");
    // no tickets at all
    render(<MemoryRouter initialEntries={["/dashboard"]}><AuthProvider><Routes><Route path="/dashboard" element={<ConsoleDashboard />} /></Routes></AuthProvider></MemoryRouter>);
    (await net.waitFor("/api/auth/session", { index: 1 })).respond(200, { session: SUP });
    const empty = await net.waitFor("/api/console/dashboard", { index: 1 });
    await act(async () => { empty.respond(200, { ...dash(0), has_tickets: false, dashboard: null }); });
    expect(screen.getByText("No tickets yet")).toBeInTheDocument();
  });

  it("Agents cards show the core's numbers and '—' for a missing average", async () => {
    const net = installFakeFetch();
    renderAt("/agents", <Route path="/agents" element={<ConsoleAgents />} />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SUP });
    const req = await net.waitFor("/api/console/agents");
    const card = (agent, name, extra = {}) => ({ agent, name, tickets: 1, messages: 1, proposals: 1, approved: 1, sent_back: 0, escalated: 0, to_finance: 0, errors: 0, avg_seconds: null, tokens: 1200, models: ["groq/openai/gpt-oss-120b"], ...extra });
    await act(async () => { req.respond(200, { days: null, periods: PERIODS, has_tickets: true, clock: "computer time", read_at: "t", agents: [card("intake", "Intake", { models: ["local: bge-small-en-v1.5"] }), card("A", "Agent A"), card("B", "Agent B", { avg_seconds: 2.4 }), card("coordinator", "Coordinator", { models: ["rules (no LLM)"] }), card("writer", "Reply writer")] }); });
    const b = screen.getByRole("article", { name: "Agent B" });
    expect(b).toHaveTextContent("2.4 s");
    expect(b).toHaveTextContent("groq/openai/gpt-oss-120b");
    expect(screen.getByRole("article", { name: "Intake" })).toHaveTextContent("Proposals—");
    expect(screen.getByRole("article", { name: "Agent A" })).toHaveTextContent("avg model seconds per message—");
  });

  it("ShopNova admin dashboard: periods from the API, simulation clock labelled, review average '—' when none", async () => {
    const net = installFakeFetch();
    renderAt("/admin/dashboard", <Route path="/admin/dashboard" element={<ShopAdminDashboard />} />, { role: "admin", company: "shopnova", username: "admin", name: "ShopNova Admin" });
    (await net.waitFor("/api/auth/session")).respond(200, { session: { role: "admin", company: "shopnova", username: "admin", name: "ShopNova Admin" } });
    const req = await net.waitFor("/api/admin/dashboard?days=30");
    await act(async () => {
      req.respond(200, { days: 30, periods: [7, 30, 90], default_days: 30, clock: "simulation clock", low_stock_limit: 5, read_at: "t",
        dashboard: { days: 30, start: "2026-09-10", today: "2026-10-09", orders: 12, sales_tnd: 1234.5, sales_per_day: [{ day: "2026-10-08", sales_tnd: 100 }, { day: "2026-10-09", sales_tnd: 0 }],
          orders_by_status: [{ status: "delivered", orders: 10 }], late: 1, late_orders: [{ id: 4512, status: "stuck_at_depot", promised_date: "2026-10-03", delivered_date: null }], stuck: 1,
          refunds_paid: { count: 1, tnd: 59.9 }, top_products: [{ product_id: 1, name: "USB hub", qty: 3 }], top_categories: [{ category: "audio", qty: 3 }],
          review_scores: [{ score: 5, count: 0 }], review_average: null, review_count: 0, low_stock: [] } });
    });
    expect(screen.getByText(/from 2026-09-10 to 2026-10-09 \(simulation clock\)/)).toBeInTheDocument();
    expect(screen.getByText("Review average").closest(".stat")).toHaveTextContent("—");
    expect(screen.getByText("Review average").closest(".stat")).toHaveTextContent("no review in the period");
    expect(screen.getByText("Sales").closest(".stat")).toHaveTextContent("1,234.50 TND");
    expect(screen.getByRole("button", { name: "Last 90 days" })).toBeInTheDocument();
    expect(screen.getByText("No active product is low on stock.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /late deliveries/i })).toHaveTextContent("4512");
  });

  it("Atlas admin dashboard: rates as given, and a denied account sees the API's words", async () => {
    const net = installFakeFetch();
    renderAt("/atlas/admin/dashboard", <Route path="/atlas/admin/dashboard" element={<AtlasAdminDashboard />} />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: { role: "admin", company: "atlas", username: "atlas_admin", name: "Atlas Admin" } });
    const req = await net.waitFor("/api/atlas/admin/dashboard?days=all");
    await act(async () => {
      req.respond(200, { days: null, periods: { "Last 7 days": 7, "Last 30 days": 30, All: null }, default: "All", clock: "simulation clock", upcoming_days: 14, read_at: "t",
        dashboard: { start: null, today: "2026-10-09", upcoming_until: "2026-10-23", hotel_by_status: [{ status: "confirmed", bookings: 5 }], flight_by_status: [],
          hotel_bookings: 5, flight_bookings: 0, hotel_cancellation_rate: 20, flights: 3, flight_delay_rate: 33.3, flight_cancellation_rate: 0,
          refunds_paid: { count: 0, tnd: 0 }, compensation_paid: { count: 1, tnd: 839.5 }, upcoming_arrivals: [], upcoming_departures: [{ id: 7010, client: "Nizar Haddad", origin: "Tunis", destination: "Paris", scheduled_departure: "2026-10-12 08:00" }] } });
    });
    expect(screen.getByText("Flight delay rate").closest(".stat")).toHaveTextContent("33.3 %");
    expect(screen.getByText("Compensation paid").closest(".stat")).toHaveTextContent("1 · 839.50 TND");
    expect(screen.getByText(/all dates to 2026-10-09 \(simulation clock\)/)).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: /flight bookings by status/i })).toHaveTextContent("No data for this period.");
    expect(screen.getByRole("region", { name: /upcoming departures/i })).toHaveTextContent("Nizar Haddad");
    // denied: the ShopNova admin on the Atlas dashboard
    render(<MemoryRouter initialEntries={["/atlas/admin/dashboard"]}><AuthProvider><Routes><Route path="/atlas/admin/dashboard" element={<AtlasAdminDashboard />} /></Routes></AuthProvider></MemoryRouter>);
    (await net.waitFor("/api/auth/session", { index: 1 })).respond(200, { session: { role: "admin", company: "shopnova", username: "admin" } });
    const denied = await net.waitFor("/api/atlas/admin/dashboard?days=all", { index: 1 });
    await act(async () => { denied.respond(403, { error: "admin_only", message: "This page is for the Atlas Travel admin (permission view_dashboard) only." }); });
    expect(screen.getByRole("alert")).toHaveTextContent("Atlas Travel admin (permission view_dashboard)");
  });
});
