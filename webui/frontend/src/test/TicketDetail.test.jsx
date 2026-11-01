// Regression test of the Ticket detail screen: the answer of a ticket the user already left must never replace
// the ticket now shown.
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, Link } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import TicketDetail from "../screens/TicketDetail.jsx";
import { SUPERVISOR, installFakeFetch } from "./fakeApi.js";

function detailBody(id) {
  return {
    ticket: { id, company: "shopnova", status: "Solved", priority: "high", lead_agent: "B", main_reason: "refund_request",
              created_at: "2026-10-09T09:00:00", created_real: "2026-11-01T12:00:00", updated_real: "2026-11-01T12:00:00" },
    user: "Sara Ben Ali (1)", age: "1 min", approvals: [], server_time: "2026-11-01T12:00:00",
    turns: [{ message: { id: 1, sender: "user", text: `hello from ${id}`, at_real: "2026-11-01T12:00:00" }, replies: [],
              steps: [], decision: null, tool_calls: [], policy_searches: [], tokens: {}, tokens_total: 0, seconds: [] }],
  };
}

describe("Ticket detail", () => {
  it("ignores the late answer of the previous ticket", async () => {
    const net = installFakeFetch();
    render(
      <MemoryRouter initialEntries={["/tickets/T-0001"]}>
        <AuthProvider>
          <Link to="/tickets/T-0002">go to T-0002</Link>
          <Routes><Route path="/tickets/:ticketId" element={<TicketDetail />} /></Routes>
        </AuthProvider>
      </MemoryRouter>
    );
    (await net.waitFor("/api/auth/session")).respond(200, { session: SUPERVISOR });
    const first = await net.waitFor("/api/console/tickets/T-0001");

    // The user moves to T-0002 before T-0001 answered.
    await act(async () => { screen.getByText("go to T-0002").click(); });
    const second = await net.waitFor("/api/console/tickets/T-0002");
    expect(first.aborted).toBe(true);

    // T-0002 answers, then the old T-0001 answer "arrives" (a fetch that ignored the abort): it must be dropped.
    await act(async () => { second.respond(200, detailBody("T-0002")); });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("T-0002");
    await act(async () => { first.done = false; first.respond(200, detailBody("T-0001")); });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("T-0002");
    expect(screen.getByText("hello from T-0002")).toBeInTheDocument();
    expect(screen.queryByText("hello from T-0001")).toBeNull();
  });
});
