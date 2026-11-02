// Step 5 screen tests: My bookings, Booking detail (wrong type = not yours), the Atlas chat (its own API prefix
// and booking context) and the Atlas approval queue (a compensation is not a refund).
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import Shell from "../components/Shell.jsx";
import AdminApprovals from "../screens/AdminApprovals.jsx";
import BookingDetail from "../screens/BookingDetail.jsx";
import Chat from "../screens/Chat.jsx";
import MyBookings from "../screens/MyBookings.jsx";
import { installFakeFetch } from "./fakeApi.js";

const HEDI = { username: "hedi", name: "Hedi Karoui", role: "user", company: "atlas" };
const ATLAS_ADMIN = { username: "atlas_admin", name: "Atlas Admin", role: "admin", company: "atlas" };
const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function renderAt(path, session, element) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes><Route element={<Shell area={session.role === "admin" ? "atlas-admin" : "atlas"} />}>{element}</Route></Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("Atlas Travel screens", () => {
  it("My bookings shows flights and hotel stays with their money lines and the ask link", async () => {
    const net = installFakeFetch();
    renderAt("/atlas/bookings", HEDI, <Route path="/atlas/bookings" element={<MyBookings />} />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: HEDI });
    const req = await net.waitFor("/api/atlas/bookings");
    await act(async () => {
      req.respond(200, { count: 2, sim_today: "2026-10-09",
        flights: [{ id: 7005, route: "Tunis (TUN) → Paris (CDG)", airline: "Air Test", flight_number: "AT 100", departure: "2026-10-12T08:00",
                    situation: "delayed 200 minutes (the airline)", paid: 700, refunds: [], compensations: [{ id: 1, amount: 250, status: "approved", created_at: "2026-10-09" }] }],
        hotels: [{ id: 7001, hotel: "Hotel Test", arrival: "2026-10-20", nights: 3, room_booked: "double", room_given: "double",
                   deposit: "no deposit (pay at the hotel)", total: 360, paid: 0, status: "cancelled", refunds: [], compensations: [] }] });
    });
    expect(document.documentElement.dataset.theme).toBe("atlas");
    const flight = screen.getByRole("article", { name: /booking 7005/i });
    expect(flight).toHaveTextContent("delayed 200 minutes (the airline)");
    expect(flight).toHaveTextContent("Compensation of 250.00 TND · approved");
    expect(within(flight).getByRole("link", { name: /ask about this booking/i })).toHaveAttribute("href", "/atlas/chat?booking=7005");
    const hotel = screen.getByRole("article", { name: /booking 7001/i });
    expect(hotel).toHaveTextContent("cancelled");
    expect(hotel).toHaveTextContent("no deposit (pay at the hotel)");
  });

  it("Booking detail shows the facts and a wrong type as 'not one of your bookings'", async () => {
    const net = installFakeFetch();
    renderAt("/atlas/bookings/flight/7005", HEDI, <Route path="/atlas/bookings/:kind/:bookingId" element={<BookingDetail />} />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: HEDI });
    const req = await net.waitFor("/api/atlas/bookings/flight/7005");
    await act(async () => {
      req.respond(200, { kind: "flight", sim_today: "2026-10-09",
        booking: { id: 7005, route: "Tunis (TUN) → Paris (CDG)", airline: "Air Test", flight_number: "AT 100", situation: "cancelled (weather)", paid: 700 },
        facts: { carrier_name: "Air Test", flight_status: "cancelled", cancellation_reason: "weather", paid_tnd: 700, refunded_total: 0, status: "booked", new_field_v9: "shown raw" },
        // the exact shape of reads.get_refunds / get_compensations: refunded_total and compensated_total
        refunds: { booking_type: "flight", booking_id: 7005, refunds: [], refunded_total: 0 },
        compensations: { booking_type: "flight", booking_id: 7005, compensations: [{ id: 3, booking_type: "flight", booking_id: 7005, amount: 250, status: "approved", rule_id: "AT-FLT-03", proposal_id: "AP-0002", created_at: "2026-10-09" }], compensated_total: 250 } });
    });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Booking 7005");
    expect(screen.getByText(/compensation so far/)).toHaveTextContent("compensation so far: 250.00 TND");   // nonzero, from compensated_total
    expect(screen.getByRole("region", { name: /money/i })).toHaveTextContent("Compensation of 250.00 TND · approved");
    expect(screen.getByText("weather")).toBeInTheDocument();
    expect(screen.getByText(/new_field_v9/)).toBeInTheDocument();   // an unknown fact stays visible (raw)
    render(
      <MemoryRouter initialEntries={["/atlas/bookings/hotel/7005"]}><AuthProvider>
        <Routes><Route path="/atlas/bookings/:kind/:bookingId" element={<BookingDetail />} /></Routes>
      </AuthProvider></MemoryRouter>
    );
    (await net.waitFor("/api/auth/session", { index: 1 })).respond(200, { session: HEDI });
    const bad = await net.waitFor("/api/atlas/bookings/hotel/7005");
    await act(async () => { bad.respond(404, { error: "not_found", message: "Hotel booking 7005 is not one of your bookings." }); });
    expect(screen.getByText("hotel booking 7005 is not one of your bookings")).toBeInTheDocument();
  });

  it("the Atlas chat uses its own API prefix and sends the booking context", async () => {
    const net = installFakeFetch();
    renderAt("/atlas/chat?booking=7005", HEDI, <Route path="/atlas/chat" element={<Chat company="atlas" />} />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: HEDI });
    const load = await net.waitFor(/\/api\/atlas\/chat(\?|$)/);
    await act(async () => { load.respond(200, { company: "atlas", ticket: null, messages: [], unread: [], job: null, server_time: "t" }); });
    expect(screen.getByText("About booking 7005")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Your message"), "Is it late?");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const req = await net.waitFor("/api/atlas/chat/send");
    const body = JSON.parse(req.options.body);
    expect(body).toMatchObject({ text: "Is it late?", about_booking: 7005 });
    expect(body.about_order).toBeUndefined();
    expect(net.all("/api/shop/")).toHaveLength(0);   // never ShopNova's routes
    await act(async () => { req.respondStream([frame("done", { ticket_id: "T-0003", status: "Solved", outcome: "info" })]); });
    const reload = await net.waitFor("/api/atlas/chat?ticket=T-0003");   // the conversation of the ticket the result names
    expect(reload).toBeTruthy();
  });

  it("the Atlas queue names the action and the booking, and reports a compensation", async () => {
    const net = installFakeFetch();
    renderAt("/atlas/admin/approvals", ATLAS_ADMIN, <Route path="/atlas/admin/approvals" element={<AdminApprovals company="atlas" />} />);
    (await net.waitFor("/api/auth/session")).respond(200, { session: ATLAS_ADMIN });
    const load = await net.waitFor("/api/atlas/admin/approvals?status=pending");
    const row = { id: 1, ticket_id: "T-0001", order_id: 7004, amount: 839.5, proposal_id: "AP-0001", status: "pending", company: "atlas",
                  booking_type: "flight", action: "compensation", decided_by: null, decided_at: null, reason: null,
                  facts: { user_name: "Nizar Haddad", booking_status: "flown", rule_id: "AT-FLT-03", rule_title: "Long delay", facts_used: { read: true }, confirmation: "yes (compensation request + quote found)" },
                  proposal: { id: "AP-0001", agent: "B", action: "compensation", params: { booking_type: "flight", booking_id: 7004, amount: 839.5 }, rule_id: "AT-FLT-03", facts_used: { read: true }, decision: null, confirmed_by_code: 1 } };
    await act(async () => { load.respond(200, { company: "atlas", status: "pending", approvals: [row], count: 1, server_time: "t" }); });
    const card = screen.getByRole("article", { name: /approval 1/i });
    expect(card).toHaveTextContent("Approval 1 · compensation of 839.50 TND");
    expect(card).toHaveTextContent("flight booking 7004 · Nizar Haddad");
    expect(card).toHaveTextContent("yes (compensation request + quote found)");
    expect(card).not.toHaveTextContent("Days late");
    await act(async () => { within(card).getByRole("button", { name: /^approve$/i }).click(); });
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Approve: the compensation is written and the client is told");
    await act(async () => { within(dialog).getByRole("button", { name: /confirm approval/i }).click(); });
    const req = await net.waitFor("/api/atlas/admin/approvals/1/decide");
    expect(net.all("/api/admin/approvals")).toHaveLength(0);   // never ShopNova's queue
    await act(async () => { req.respond(200, { approval: { ...row, status: "approved" }, outcome: "approve", ticket: { id: "T-0001", status: "Solved" }, refund: null, compensation: { amount: 839.5 }, reply_source: "slm" }); });
    expect(screen.getByRole("status")).toHaveTextContent("compensation 839.50 TND written");
  });
});
