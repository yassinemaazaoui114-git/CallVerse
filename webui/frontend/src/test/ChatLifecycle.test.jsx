// Correction-pass tests of the Help chat: request identity (a new message is a new id, a pending one keeps
// its id and payload), stream lifecycle (unmount / navigation / New chat drop late events), one recovery at a
// time, and the stream being released on detach.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import Chat from "../screens/Chat.jsx";
import { installFakeFetch } from "./fakeApi.js";

const SARA = { username: "sara", name: "Sara Ben Ali", role: "user", company: "shopnova" };
const EMPTY = { ticket: null, messages: [], unread: [], job: null, server_time: "t" };
const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function renderChat(path = "/shop/chat") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Link to="/elsewhere">leave</Link>
        <Routes>
          <Route path="/shop/chat" element={<Chat />} />
          <Route path="/elsewhere" element={<p>elsewhere</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

async function start(net, path = "/shop/chat", first = EMPTY) {
  const view = renderChat(path);
  (await net.waitFor("/api/auth/session")).respond(200, { session: SARA });
  const load = await net.waitFor(/\/api\/shop\/chat(\?|$)/);
  await act(async () => { load.respond(200, first); });
  return view;
}

async function sendText(text) {
  await userEvent.type(screen.getByLabelText("Your message"), text);
  await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
}

describe("Help chat: request identity and stream lifecycle", () => {
  it("new text after a failure gets a new request id and is not replaced by the old result", async () => {
    const net = installFakeFetch();
    await start(net);
    await sendText("first");
    const a = await net.waitFor("/api/shop/chat/send");
    const idA = JSON.parse(a.options.body).client_id;
    await act(async () => { a.respondStream([frame("error", { error: "worker_error", message: "boom" })]); });
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    await act(async () => { screen.getByRole("button", { name: /dismiss/i }).click(); });
    await sendText("second");
    const b = await net.waitFor("/api/shop/chat/send", { index: 1 });
    const bodyB = JSON.parse(b.options.body);
    expect(bodyB.text).toBe("second");
    expect(bodyB.client_id).not.toBe(idA);
    await act(async () => { b.respondStream([frame("done", { ticket_id: "T-0002", status: "Solved", outcome: "approve" })]); });
    const reload = await net.waitFor("ticket=T-0002");
    await act(async () => { reload.respond(200, { ...EMPTY, ticket: { id: "T-0002", status: "Solved" }, messages: [{ id: 1, sender: "user", text: "second" }, { id: 2, sender: "assistant", text: "B's reply" }] }); });
    expect(screen.getByText("B's reply")).toBeInTheDocument();
  });

  it("while a submission is uncertain, typing is not a retry: Send is paused, resend keeps the same id and payload", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat?order=4512");
    await sendText("lost one");
    const a = await net.waitFor("/api/shop/chat/send");
    const bodyA = JSON.parse(a.options.body);
    await act(async () => { a.respondStream([frame("step", { text: "Reading your message…" })], { cut: true }); });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Connection lost");
    expect(alert).toHaveTextContent("lost one");
    await userEvent.type(screen.getByLabelText("Your message"), "a different text");
    expect(screen.getByRole("button", { name: /^send$/i })).toBeDisabled();
    expect(net.all("/api/shop/chat/send")).toHaveLength(1);
    await act(async () => { within(alert).getByRole("button", { name: /resend the same message/i }).click(); });
    const again = await net.waitFor("/api/shop/chat/send", { index: 1 });
    expect(JSON.parse(again.options.body)).toEqual(bodyA);   // same id, same text, same order
  });

  it("navigating away during sending drops the late done event (no state change, no redirect)", async () => {
    const net = installFakeFetch();
    await start(net);
    await sendText("hello");
    const a = await net.waitFor("/api/shop/chat/send");
    let open;
    await act(async () => { open = a.respondStreamOpen(); });
    await act(async () => { open.push(frame("step", { text: "Reading your message…" })); });
    expect(screen.getByText("Reading your message…")).toBeInTheDocument();
    await act(async () => { screen.getByText("leave").click(); });   // unmounts the chat (navigation / logout)
    expect(screen.getByText("elsewhere")).toBeInTheDocument();
    expect(a.options.signal.aborted).toBe(true);                      // detached: the reader was cancelled
    await act(async () => { try { open.push(frame("done", { ticket_id: "T-0009", status: "Solved", outcome: "approve" })); open.close(); } catch (e) { /* cancelled stream */ } });
    await new Promise((r) => setTimeout(r, 20));
    expect(net.all("ticket=T-0009")).toHaveLength(0);                 // no reload for another conversation
    expect(screen.getByText("elsewhere")).toBeInTheDocument();        // no redirect
  });

  it("navigating away during recovery detaches, and a late done of the old stream is ignored", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat?ticket=T-0001", { ...EMPTY, ticket: { id: "T-0001", status: "Open" }, job: { job_id: "j", status: "running", client_id: "c", started_at: "t", steps: [], result: null, error: null } });
    await act(async () => { screen.getByRole("button", { name: /follow progress/i }).click(); });
    const jobReq = await net.waitFor("/api/shop/chat/job");
    await act(async () => { jobReq.respond(200, { job: { job_id: "j", status: "running", client_id: "c", steps: [], result: null, error: null } }); });
    const attach = await net.waitFor("/api/shop/chat/job/stream");
    let open;
    await act(async () => { open = attach.respondStreamOpen(); });
    expect(screen.getByRole("button", { name: /new chat/i })).toBeDisabled();   // no conversation switch mid-stream
    await act(async () => { screen.getByText("leave").click(); });                 // but leaving is always possible
    expect(attach.options.signal.aborted).toBe(true);
    await act(async () => { try { open.push(frame("done", { ticket_id: "T-0001", status: "Solved", outcome: "approve" })); open.close(); } catch (e) { /* cancelled */ } });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByText("elsewhere")).toBeInTheDocument();
    expect(net.all("ticket=T-0001")).toHaveLength(1);   // only the first load; no reload triggered by the late event
  });

  it("repeated Check status makes one job request and one stream", async () => {
    const net = installFakeFetch();
    await start(net);
    await sendText("x");
    const a = await net.waitFor("/api/shop/chat/send");
    await act(async () => { a.respondStream([], { cut: true }); });
    const alert = await screen.findByRole("alert");
    const check = within(alert).getByRole("button", { name: /check status/i });
    await act(async () => { check.click(); check.click(); check.click(); });
    await new Promise((r) => setTimeout(r, 20));
    expect(net.all("/api/shop/chat/job")).toHaveLength(1);
    const jobReq = net.all("/api/shop/chat/job")[0];
    await act(async () => { jobReq.respond(200, { job: { job_id: "j", status: "running", client_id: "c", steps: [], result: null, error: null } }); });
    await new Promise((r) => setTimeout(r, 20));
    await act(async () => { check.click(); });
    await new Promise((r) => setTimeout(r, 20));
    expect(net.all("/api/shop/chat/job/stream")).toHaveLength(1);
    expect(net.all(/\/api\/shop\/chat\/job(\?|$)/)).toHaveLength(1);
  });
});
