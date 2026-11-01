// Refund approvals screen (step 4): the queue with facts, the confirmation repeating approval / amount / choice /
// reason, one submission at a time, the result and the refresh, the refused re-check, already decided, a lost
// answer recovered from the recorded state (never resent), the denied-access and empty states.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import AdminApprovals from "../screens/AdminApprovals.jsx";
import { installFakeFetch } from "./fakeApi.js";

const ADMIN = { username: "admin", name: "ShopNova Admin", role: "admin", company: "shopnova" };

function approval(id, extra = {}) {
  return { id, ticket_id: "T-0001", order_id: 4515, amount: 378, proposal_id: "P-0001", status: "pending", company: "shopnova",
           decided_by: null, decided_at: null, reason: null, booking_type: null, action: "refund",
           facts: { order_status: "stuck_at_depot", paid: 378, refunded_total: 0, days_late: 8, user_name: "Youssef Trabelsi",
                    rule_id: "R-REF-03", rule_title: "Full refund of a late order", facts_used: { days_late: 8 }, proposal_decision: null },
           proposal: { id: "P-0001", agent: "B", action: "refund", params: { order_id: 4515, amount: 378 }, rule_id: "R-REF-03",
                       facts_used: { days_late: 8, proof_received: false }, user_confirmed: 1, decision: null }, ...extra };
}
const list = (rows, status = "pending") => ({ status, approvals: rows, count: rows.length, server_time: "t" });

async function start(net, first = list([approval(1)])) {
  render(<MemoryRouter initialEntries={["/admin/approvals"]}><AuthProvider><Routes><Route path="/admin/approvals" element={<AdminApprovals />} /></Routes></AuthProvider></MemoryRouter>);
  (await net.waitFor("/api/auth/session")).respond(200, { session: ADMIN });
  const load = await net.waitFor("status=pending");
  await act(async () => { load.respond(200, first); });
}

async function openConfirm(approve, reason) {
  if (reason) await userEvent.type(screen.getByLabelText(/^reason/i), reason);
  await act(async () => { screen.getByRole("button", { name: approve ? /^approve$/i : /^refuse$/i }).click(); });
  return screen.getByRole("dialog");
}

describe("Refund approvals", () => {
  it("shows the pending approval with its facts and proof field", async () => {
    const net = installFakeFetch();
    await start(net);
    const card = screen.getByRole("article", { name: /approval 1/i });
    expect(card).toHaveTextContent("378.00 TND");
    expect(card).toHaveTextContent("4515 · Youssef Trabelsi");
    expect(card).toHaveTextContent("R-REF-03: Full refund of a late order");
    expect(card).toHaveTextContent("Proof");
    expect(card).toHaveTextContent("false");
    expect(card).toHaveTextContent("stuck at depot");
  });

  it("confirms with the exact approval, amount, choice and reason, submits once, shows the result and refreshes", async () => {
    const net = installFakeFetch();
    await start(net);
    const dialog = await openConfirm(true, "looks fine");
    expect(dialog).toHaveTextContent("Approve approval 1?");
    expect(dialog).toHaveTextContent("378.00 TND");
    expect(dialog).toHaveTextContent("Approve: the refund is written");
    expect(dialog).toHaveTextContent("looks fine");
    const confirm = within(dialog).getByRole("button", { name: /confirm approval/i });
    await act(async () => { confirm.click(); confirm.click(); });   // a double click
    const req = await net.waitFor("/api/admin/approvals/1/decide");
    expect(net.all("/decide")).toHaveLength(1);
    const body = JSON.parse(req.options.body);
    expect(body).toMatchObject({ approve: true, reason: "looks fine" });
    expect(body.client_id).toBeTruthy();
    expect(req.options.headers["X-Requested-With"]).toBe("CallVerse");
    expect(within(dialog).getByRole("button", { name: /deciding/i })).toBeDisabled();
    await act(async () => { req.respond(200, { approval: { ...approval(1), status: "approved", decided_by: "admin" }, outcome: "approve_v2_unknown", ticket: { id: "T-0001", status: "Solved" }, refund: { amount: 378 }, reply_source: "slm" }); });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Approval 1: approved");
    expect(screen.getByRole("status")).toHaveTextContent("Outcome approve v2 unknown");   // unknown outcome as text
    const refresh = await net.waitFor("status=pending", { index: 1 });
    await act(async () => { refresh.respond(200, list([])); });
    expect(screen.getByText("No refund is waiting for approval")).toBeInTheDocument();
  });

  it("refuse needs a reason; a refused re-check leaves it pending with the Coordinator's words", async () => {
    const net = installFakeFetch();
    await start(net);
    await act(async () => { screen.getByRole("button", { name: /^refuse$/i }).click(); });
    expect(screen.getByRole("alert")).toHaveTextContent("A reason is required to refuse.");
    expect(screen.queryByRole("dialog")).toBeNull();
    const dialog = await openConfirm(true);
    await act(async () => { within(dialog).getByRole("button", { name: /confirm approval/i }).click(); });
    const req = await net.waitFor("/decide");
    await act(async () => { req.respond(409, { error: "recheck_refused", message: "rule R-REF-03 does not apply any more: delivered" }); });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("re-check refused it, nothing was written. It stays pending");
    expect(alert).toHaveTextContent("does not apply any more");
    expect(screen.getByRole("button", { name: /^approve$/i })).toBeEnabled();
  });

  it("already decided: shows the server's words and refreshes", async () => {
    const net = installFakeFetch();
    await start(net);
    const dialog = await openConfirm(false, "dup");
    await act(async () => { within(dialog).getByRole("button", { name: /confirm refusal/i }).click(); });
    const req = await net.waitFor("/decide");
    await act(async () => { req.respond(409, { error: "already_decided", message: "Approval 1 is already approved (by admin at 2026-10-09)." }); });
    expect(screen.getByRole("alert")).toHaveTextContent("already approved (by admin");
    expect(await net.waitFor("status=pending", { index: 1 })).toBeTruthy();
  });

  it("a lost answer is not resent: the recorded state is read and shown", async () => {
    const net = installFakeFetch();
    await start(net);
    const dialog = await openConfirm(true, "ok");
    await act(async () => { within(dialog).getByRole("button", { name: /confirm approval/i }).click(); });
    const req = await net.waitFor("/decide");
    await act(async () => { req.fail(); });
    const state = await net.waitFor(/\/api\/admin\/approvals\/1$/);
    await act(async () => { state.respond(200, { approval: { ...approval(1), status: "approved", decided_by: "admin", decided_at: "2026-10-09T09:00:00" } }); });
    expect(screen.getByRole("status")).toHaveTextContent("recorded it as approved by admin at 2026-10-09T09:00:00");
    expect(net.all("/decide")).toHaveLength(1);
    // still pending on the server: the admin may confirm again with the SAME request id
    const net2 = net;
    await act(async () => { screen.getByRole("button", { name: /dismiss/i }).click(); });
    const refresh = await net2.waitFor("status=pending", { index: 1 });
    await act(async () => { refresh.respond(200, list([approval(2)])); });
    const d2 = await openConfirm(true, "again");
    await act(async () => { within(d2).getByRole("button", { name: /confirm approval/i }).click(); });
    const r2 = await net2.waitFor("/api/admin/approvals/2/decide");
    const id2 = JSON.parse(r2.options.body).client_id;
    await act(async () => { r2.fail(); });
    const s2 = await net2.waitFor(/\/api\/admin\/approvals\/2$/);
    await act(async () => { s2.respond(200, { approval: approval(2) }); });
    expect(screen.getByRole("alert")).toHaveTextContent("still pending on the server. Nothing was written");
    await act(async () => { screen.getByRole("button", { name: /confirm again/i }).click(); });
    await act(async () => { within(screen.getByRole("dialog")).getByRole("button", { name: /confirm approval/i }).click(); });
    const r3 = await net2.waitFor("/api/admin/approvals/2/decide", { index: 1 });
    expect(JSON.parse(r3.options.body).client_id).toBe(id2);   // the same request id: the server dedupes
  });

  it("denied access and empty states", async () => {
    const net = installFakeFetch();
    render(<MemoryRouter initialEntries={["/admin/approvals"]}><AuthProvider><Routes><Route path="/admin/approvals" element={<AdminApprovals />} /></Routes></AuthProvider></MemoryRouter>);
    (await net.waitFor("/api/auth/session")).respond(200, { session: { ...ADMIN, company: "atlas" } });
    const load = await net.waitFor("status=pending");
    await act(async () => { load.respond(403, { error: "admin_only", message: "This page is for the ShopNova admin (permission approve_refunds) only." }); });
    expect(screen.getByRole("alert")).toHaveTextContent("Not available for your account");
    expect(screen.getByRole("alert")).toHaveTextContent("approve_refunds");
  });
});
