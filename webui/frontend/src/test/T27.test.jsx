// T27 screen tests: the Promotions and Hotel deals pages (list, empty state, approve with confirmation, refuse needs
// a reason, a double click sends ONE decision), the Check-now button (disabled while running, counts, error), the
// urgent badge (Live tickets, approvals sorted urgent first), the C/D outcomes in Ticket detail, and a C question
// shown as a normal assistant message in the chat.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import CheckNow from "../components/CheckNow.jsx";
import AdminApprovals from "../screens/AdminApprovals.jsx";
import Chat from "../screens/Chat.jsx";
import LiveTickets from "../screens/LiveTickets.jsx";
import OwnerProposals from "../screens/OwnerProposals.jsx";
import TicketDetail from "../screens/TicketDetail.jsx";
import { LIST, SUPERVISOR, installFakeFetch, ticketsBody } from "./fakeApi.js";

const SHOP_ADMIN = { username: "admin", name: "ShopNova Admin", role: "admin", company: "shopnova" };
const ATLAS_ADMIN = { username: "atlas_admin", name: "Atlas Admin", role: "admin", company: "atlas" };

function promo(id, extra = {}) {
  return { id, product_id: 2, product_name: "Phone Case", stock: 120, price: 19.9, discount_pct: 10, status: "pending",
    note: "Phone Case: 120 units in stock and 4 sold in the last 30 days, so a 10% promotion is proposed.",
    proposal_id: `P-000${id}`, created_at: "2026-10-09", decided_by: null, decided_at: null, reason: null,
    facts: { stock: 120, units_sold_30d: 4, days_of_cover: 900 }, ...extra };
}
function deal(id, extra = {}) {
  return { id, hotel_id: 1, hotel_name: "Atlas City Hotel Lisbon", nights: ["2026-11-06", "2026-11-07"], first_night: "2026-11-06",
    last_night: "2026-11-07", discount_pct: 10, status: "pending", note: "2 coming nights at 30% or less.", proposal_id: `AP-000${id}`,
    created_at: "2026-10-09", decided_by: null, decided_at: null, reason: null, facts: { capacity: 25, min_occupancy_pct: 24 }, ...extra };
}
const listBody = (items, status = "pending") => ({ company: "x", status, items, count: items.length, server_time: "t" });

function renderAt(path, routePath, element) {
  render(<MemoryRouter initialEntries={[path]}><AuthProvider><Routes><Route path={routePath} element={element} /></Routes></AuthProvider></MemoryRouter>);
}

describe("Promotions page (ShopNova admin)", () => {
  it("T28: says 'No sales in the last 30 days' instead of 9,999 days", async () => {
    const net = installFakeFetch();
    renderAt("/admin/promotions", "/admin/promotions", <OwnerProposals company="shopnova" />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SHOP_ADMIN });
    const list = await net.waitFor(/\/api\/admin\/promotions\?status=pending$/);
    await act(async () => { list.respond(200, listBody([promo(1, { facts: { stock: 120, units_sold_30d: 0, days_of_cover: 9999 } })])); });
    const card = screen.getByRole("article", { name: /Promotion 1 · 10% on Phone Case/ });
    expect(within(card).getByText("Days of cover").nextSibling).toHaveTextContent("No sales in the last 30 days");
    expect(within(card).queryByText(/9,999/)).toBeNull();
  });

  it("shows Agent D's facts, approves after the confirmation, and a double click sends one decision", async () => {
    const net = installFakeFetch();
    renderAt("/admin/promotions", "/admin/promotions", <OwnerProposals company="shopnova" />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SHOP_ADMIN });
    const list = await net.waitFor(/\/api\/admin\/promotions\?status=pending$/);
    await act(async () => { list.respond(200, listBody([promo(1)])); });
    const card = screen.getByRole("article", { name: /Promotion 1 · 10% on Phone Case/ });
    expect(within(card).getByText("Days of cover").nextSibling).toHaveTextContent("900 days");
    expect(within(card).getByText("Sold in the last 30 days").nextSibling).toHaveTextContent("4");
    expect(within(card).getByText(/so a 10% promotion is proposed/)).toBeInTheDocument();

    await userEvent.click(within(card).getByRole("button", { name: "Approve" }));
    const confirm = screen.getByRole("button", { name: /Confirm approval/ });
    await userEvent.click(confirm);
    await userEvent.click(confirm);   // the second click while the first runs
    expect(net.all("/decision")).toHaveLength(1);
    const call = net.all("/api/admin/promotions/1/decision")[0];
    const body = JSON.parse(call.options.body);
    expect(body.approve).toBe(true);
    expect(body.client_id).toBeTruthy();
    expect(call.options.headers["X-Requested-With"]).toBe("CallVerse");
    await act(async () => { call.respond(200, { item: promo(1, { status: "approved", decided_by: "admin", decided_at: "2026-10-09" }) }); });
    expect(screen.getByRole("status")).toHaveTextContent("Promotion 1: approved by admin on 2026-10-09.");
  });

  it("refuse without a reason sends nothing; empty list says what to do", async () => {
    const net = installFakeFetch();
    renderAt("/admin/promotions", "/admin/promotions", <OwnerProposals company="shopnova" />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SHOP_ADMIN });
    const list = await net.waitFor(/\/api\/admin\/promotions\?status=pending$/);
    await act(async () => { list.respond(200, listBody([promo(2)])); });
    await userEvent.click(screen.getByRole("button", { name: "Refuse" }));
    expect(screen.getByRole("alert")).toHaveTextContent("a reason is required to refuse");
    expect(net.all("/decision")).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    const again = net.all(/\/api\/admin\/promotions\?status=pending$/)[1];
    await act(async () => { again.respond(200, listBody([])); });
    expect(screen.getByText("No promotion is waiting")).toBeInTheDocument();
    expect(screen.getByText(/Check stock now/)).toBeInTheDocument();
  });

  it("a customer account sees 'Not available for your account'", async () => {
    const net = installFakeFetch();
    renderAt("/admin/promotions", "/admin/promotions", <OwnerProposals company="shopnova" />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: { username: "sara", role: "user", company: "shopnova" } });
    const list = await net.waitFor("/api/admin/promotions");
    await act(async () => { list.respond(403, { error: "admin_only", message: "This page is for the ShopNova admin (permission approve_refunds) only." }); });
    expect(screen.getByText("Not available for your account")).toBeInTheDocument();
  });
});

describe("Hotel deals page (Atlas admin)", () => {
  it("shows nights and occupancy, refuses with a reason", async () => {
    const net = installFakeFetch();
    renderAt("/atlas/admin/deals", "/atlas/admin/deals", <OwnerProposals company="atlas" />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: ATLAS_ADMIN });
    const list = await net.waitFor(/\/api\/atlas\/admin\/deals\?status=pending$/);
    await act(async () => { list.respond(200, listBody([deal(1)])); });
    const card = screen.getByRole("article", { name: /Deal 1 · 10% at Atlas City Hotel Lisbon/ });
    expect(within(card).getByText("Nights").nextSibling).toHaveTextContent("2 nights · 2026-11-06 to 2026-11-07");
    expect(within(card).getByText("Lowest occupancy").nextSibling).toHaveTextContent("24% of 25 rooms");
    await userEvent.type(within(card).getByLabelText(/Reason/), "Full price this week");
    await userEvent.click(within(card).getByRole("button", { name: "Refuse" }));
    await userEvent.click(screen.getByRole("button", { name: /Confirm refusal/ }));
    const call = net.all("/api/atlas/admin/deals/1/decision")[0];
    expect(JSON.parse(call.options.body)).toMatchObject({ approve: false, reason: "Full price this week" });
    await act(async () => { call.respond(409, { error: "already_decided", message: "Deal 1 is already approved." }); });
    expect(screen.getByRole("alert")).toHaveTextContent("Deal 1: nothing was done. Deal 1 is already approved.");
  });
});

describe("Check now", () => {
  it("is disabled while the scan runs, then shows the counts and the link", async () => {
    const net = installFakeFetch();
    renderAt("/admin/dashboard", "/admin/dashboard", <CheckNow company="shopnova" />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SHOP_ADMIN });
    const button = screen.getByRole("button", { name: "Check stock now" });
    await userEvent.click(button);
    expect(screen.getByRole("button", { name: /Checking/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Checking/ }));
    expect(net.all("/api/admin/stock-check")).toHaveLength(1);
    await act(async () => { net.all("/api/admin/stock-check")[0].respond(200, { counts: { short: 42, over: 504, proposed: 3 } }); });
    expect(screen.getByText("Products short").closest(".stat")).toHaveTextContent("42");
    expect(screen.getByText("Promotions proposed").closest(".stat")).toHaveTextContent("3");
    expect(screen.getByRole("link", { name: /Open Promotions/ })).toHaveAttribute("href", "/admin/promotions");
    expect(screen.getByRole("button", { name: "Check stock now" })).toBeEnabled();
  });

  it("Atlas: shows the error and offers Retry", async () => {
    const net = installFakeFetch();
    renderAt("/atlas/admin/dashboard", "/atlas/admin/dashboard", <CheckNow company="atlas" />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: ATLAS_ADMIN });
    await userEvent.click(screen.getByRole("button", { name: "Check rooms now" }));
    await act(async () => { net.all("/api/atlas/admin/room-check")[0].respond(500, { error: "scan_failed", message: "The check could not run (RuntimeError: locked)" }); });
    expect(screen.getByRole("alert")).toHaveTextContent("The check could not run");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("Urgent flag", () => {
  it("Live tickets shows the Urgent badge (icon + word) only on urgent rows", async () => {
    const net = installFakeFetch();
    renderAt("/tickets", "/tickets", <LiveTickets />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SUPERVISOR });
    const filters = await net.waitFor("/api/console/tickets/filters");
    await act(async () => { filters.respond(200, { company: [], status: [], priority: [], agent: [] }); });
    const list = await net.waitFor(LIST);
    const body = ticketsBody(["T-0002", "T-0001"]);
    body.tickets[0].urgent = true;
    body.tickets[1].urgent = false;
    await act(async () => { list.respond(200, body); });
    const rows = screen.getAllByRole("row");
    expect(within(rows[1]).getByText("Urgent")).toBeInTheDocument();
    expect(within(rows[2]).queryByText("Urgent")).toBeNull();
  });

  it("Approvals put urgent cases first with the badge", async () => {
    const net = installFakeFetch();
    renderAt("/admin/approvals", "/admin/approvals", <AdminApprovals />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SHOP_ADMIN });
    const list = await net.waitFor(/\/api\/admin\/approvals\?status=pending$/);
    const a = (id, urgent) => ({ id, ticket_id: `T-000${id}`, order_id: 4515, amount: 378, proposal_id: "P-1", status: "pending", urgent, facts: {}, proposal: null });
    await act(async () => { list.respond(200, { approvals: [a(1, 0), a(2, 1)], count: 2 }); });
    const cards = screen.getAllByRole("article");
    expect(cards[0]).toHaveTextContent("Approval 2");
    expect(within(cards[0]).getByText("Urgent")).toBeInTheDocument();
    expect(within(cards[1]).queryByText("Urgent")).toBeNull();
  });
});

describe("Ticket detail: C/D outcomes", () => {
  it("lists replacement, hold, colleague, waiting for yes and D's stock warning in plain words", async () => {
    const net = installFakeFetch();
    renderAt("/tickets/T-0009", "/tickets/:ticketId", <TicketDetail />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: SUPERVISOR });
    const req = await net.waitFor("/api/console/tickets/T-0009");
    const step = (id, data) => ({ id, kind: data.trace_step, step: "x", agent: null, actor: null, actor_label: null, at: "t", at_real: "t", title: data.trace_step, detail: "", raw: { data } });
    const steps = [
      step(1, { trace_step: "stock_warning", note: "[Agent D: low stock (rule R-STK-01): Phone Case (product 2) has only 3 left. Do not promise a new unit.]" }),
      step(2, { trace_step: "coordinator_decision", outcome: "ask_user", action: "replace", must_say: ["Please confirm that you want a free replacement Phone Case for order 4512."] }),
      step(3, { trace_step: "coordinator_decision", outcome: "approve", action: "replace", facts: { new_order_id: 4601, product_name: "Phone Case", qty: 1 } }),
      step(4, { trace_step: "coordinator_decision", outcome: "approve", action: "hold", facts: { product_name: "USB hub", qty: 2, held_until: "2026-10-12" } }),
      step(5, { trace_step: "proposal", action: "assistance", params: { reason: "the client disputes the decision" } }),
      step(6, { trace_step: "coordinator_decision", outcome: "approve", action: "assistance", facts: {} }),
      step(7, { trace_step: "coordinator_decision", outcome: "approve", action: "assistance", facts: { kind: "wheelchair" }, must_say: ["A wheelchair is requested for your flight booking 7003."] }),
      step(8, { trace_step: "coordinator_decision", outcome: "approve", action: "rebook", facts: { new_departure: "2026-10-11 09:00" }, must_say: ["Your booking 7004 is moved to flight Delta 120 leaving on 2026-10-11 09:00."] }),
    ];
    await act(async () => {
      req.respond(200, { ticket: { id: "T-0009", company: "shopnova", status: "Waiting for user", priority: "high", lead_agent: "C" }, user: "Sara (1)", age: "1 min",
        approvals: [], urgent: true, server_time: "t",
        turns: [{ message: { id: 1, sender: "user", text: "help", at_real: "t" }, replies: [], steps, decision: null, tool_calls: [], policy_searches: [], tokens: {}, tokens_total: 0, seconds: [] }] });
    });
    const panel = screen.getByRole("region", { name: "What was done" });
    expect(panel).toHaveTextContent("Agent D's stock warning");
    expect(panel).toHaveTextContent("Phone Case (product 2) has only 3 left");
    expect(panel).toHaveTextContent("Waiting for the user's yes");
    expect(panel).toHaveTextContent("Replacement created");
    expect(panel).toHaveTextContent("New order 4601");
    expect(panel).toHaveTextContent("2 units of USB hub kept until 2026-10-12");
    expect(panel).toHaveTextContent("reason: the client disputes the decision");
    expect(panel).toHaveTextContent("A wheelchair is requested");
    expect(panel).toHaveTextContent("moved to flight Delta 120");
    expect(screen.getByRole("region", { name: "Ticket identity" })).toHaveTextContent("Urgent");
  });
});

describe("Chat: Agent C's question", () => {
  it("is a normal assistant message while the ticket waits for the user's yes", async () => {
    const net = installFakeFetch();
    render(<MemoryRouter initialEntries={["/shop/chat"]}><AuthProvider><Routes><Route path="/shop/chat" element={<Chat />} /></Routes></AuthProvider></MemoryRouter>);
    (await net.waitFor("/api/auth/session")).respond(200, { session: { username: "sara", name: "Sara", role: "user", company: "shopnova" } });
    const load = await net.waitFor(/\/api\/shop\/chat(\?|$)/);
    await act(async () => {
      load.respond(200, { ticket: { id: "T-0009", status: "Waiting for user", company: "shopnova", user_id: 1, user_unread: 0 },
        messages: [{ id: 1, sender: "user", text: "I need it by Friday", at_real: "t" },
                   { id: 2, sender: "assistant", text: "Please confirm that you want a free replacement Phone Case for order 4512.", at_real: "t", seconds: 3 }],
        unread: [], job: null, server_time: "t" });
    });
    const msg = screen.getByText(/Please confirm that you want a free replacement/);
    expect(msg.closest(".msg")).toHaveClass("assistant");
    expect(screen.getByLabelText("Your message")).toBeEnabled();
  });
});
