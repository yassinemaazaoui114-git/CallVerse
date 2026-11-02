// Regression tests of the Live tickets screen: answers that arrive out of order, and a filter change that fails
// after a successful load. The API is a fake fetch (fakeApi.js); no server runs.
import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import LiveTickets from "../screens/LiveTickets.jsx";
import { FILTER_VALUES, LIST, SUPERVISOR, installFakeFetch, ticketsBody } from "./fakeApi.js";

function renderScreen(path = "/tickets") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes><Route path="/tickets" element={<LiveTickets />} /></Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

async function firstLoad(net) {
  (await net.waitFor("/api/auth/session")).respond(200, { session: SUPERVISOR });
  const list = await net.waitFor(LIST);
  const filters = await net.waitFor("/api/console/tickets/filters");
  await act(async () => { filters.respond(200, FILTER_VALUES); list.respond(200, ticketsBody(["T-0002", "T-0001"])); });
  return screen.findByLabelText("Open ticket T-0002");
}

function rowIds() {
  const table = screen.getByRole("table");
  return within(table).getAllByRole("link").map((a) => a.textContent.trim());
}

describe("Live tickets", () => {
  it("drops an older answer that arrives after a newer filter change", async () => {
    const net = installFakeFetch();
    renderScreen();
    await firstLoad(net);
    expect(rowIds()).toEqual(["T-0002", "T-0001"]);

    // The user picks company=atlas (request B), then changes to company=shopnova (request C) before B answers.
    const company = screen.getByLabelText("Company");
    await act(async () => { company.value = "atlas"; company.dispatchEvent(new Event("change", { bubbles: true })); });
    const b = await net.waitFor("company=atlas");
    await act(async () => { company.value = "shopnova"; company.dispatchEvent(new Event("change", { bubbles: true })); });
    const c = await net.waitFor("company=shopnova");
    const cFilters = net.pending("/filters")[0];
    expect(b.aborted).toBe(true);   // the screen cancelled the superseded request

    // Even if B's answer had arrived (a fetch that ignores the signal), it would be dropped: simulate that by
    // answering B's values call too, then C.
    await act(async () => { b.respond(200, ticketsBody(["T-0009"])); });
    expect(rowIds()).toEqual(["T-0002", "T-0001"]);   // nothing from B shown
    await act(async () => { cFilters.respond(200, FILTER_VALUES); c.respond(200, ticketsBody(["T-0005"])); });
    expect(rowIds()).toEqual(["T-0005"]);
    expect(screen.getByRole("status")).toHaveTextContent("1 ticket shown");
  });

  it("marks retained rows as the previous filters' results when a filter change fails", async () => {
    const net = installFakeFetch();
    renderScreen();
    await firstLoad(net);

    const status = screen.getByLabelText("Status");
    await act(async () => { status.value = "Open"; status.dispatchEvent(new Event("change", { bubbles: true })); });
    const req = await net.waitFor("status=Open");
    const vals = net.pending("/filters")[0];
    await act(async () => { vals.respond(200, FILTER_VALUES); req.respond(500, { error: "boom", message: "Server error." }); });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Could not load tickets for the selected filters (status=Open)");
    expect(alert).toHaveTextContent("results of the previous filters (no filters)");
    expect(within(alert).getByRole("button", { name: /retry/i })).toBeInTheDocument();
    // the old rows stay visible, but the table says whose they are, and the "N tickets shown" line is gone
    expect(rowIds()).toEqual(["T-0002", "T-0001"]);
    expect(screen.getByRole("table")).toHaveAccessibleDescription(/previous filters \(no filters\), not of the selected ones/);
    expect(screen.getByRole("status")).toHaveTextContent("");

    // Retry succeeds: the rows are current again.
    await act(async () => { within(alert).getByRole("button", { name: /retry/i }).click(); });
    const again = await net.waitFor("status=Open", { index: 1 });
    const vals2 = net.pending("/filters")[0];
    await act(async () => { vals2.respond(200, FILTER_VALUES); again.respond(200, ticketsBody(["T-0003"])); });
    expect(rowIds()).toEqual(["T-0003"]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("1 ticket shown");
  });

  it("keeps a failed background refresh as a refresh error (rows still current)", async () => {
    const net = installFakeFetch();
    renderScreen();
    await firstLoad(net);
    await act(async () => { screen.getByRole("button", { name: /refresh now/i }).click(); });
    const req = await net.waitFor(LIST, { index: 1 });
    const vals = net.pending("/filters")[0];
    await act(async () => { vals.respond(200, FILTER_VALUES); req.fail(); });
    expect(screen.getByRole("alert")).toHaveTextContent(/Refresh failed\. The table still shows the data from/);
    expect(rowIds()).toEqual(["T-0002", "T-0001"]);
    expect(screen.getByRole("status")).toHaveTextContent("2 tickets shown");
  });

  it("aborts the request in flight when the screen unmounts", async () => {
    const net = installFakeFetch();
    const view = renderScreen();
    (await net.waitFor("/api/auth/session")).respond(200, { session: SUPERVISOR });
    const list = await net.waitFor(LIST);
    view.unmount();
    expect(list.aborted).toBe(true);
  });
});
