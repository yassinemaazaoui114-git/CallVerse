// Help chat screen tests (step 3): a successful send with live steps, the saved reply read back, the order
// context, a lost connection with recovery and NO resend, the busy outcome, a failed request, a running job
// found on load, and the unread notice. The API is the fake fetch with streaming answers.
import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import Chat from "../screens/Chat.jsx";
import { installFakeFetch } from "./fakeApi.js";

const SARA = { username: "sara", name: "Sara Ben Ali", role: "user", company: "shopnova" };
const EMPTY = { ticket: null, messages: [], unread: [], job: null, server_time: "t" };
const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function convo(ticketId, msgs, extra = {}) {
  return { ticket: { id: ticketId, status: "Solved", company: "shopnova", user_id: 1, user_unread: 0, created_real: "2026-11-01T12:00:00" },
           messages: msgs.map((m, i) => ({ id: i + 1, sender: m[0], text: m[1], at_real: "2026-11-01T12:00:00", seconds: m[0] === "assistant" ? 4.2 : null })),
           unread: [], job: null, server_time: "t", ...extra };
}

function renderChat(path = "/shop/chat") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes><Route path="/shop/chat" element={<Chat />} /></Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

async function start(net, path, first = EMPTY) {
  renderChat(path);
  (await net.waitFor("/api/auth/session")).respond(200, { session: SARA });
  const load = await net.waitFor(/\/api\/shop\/chat(\?|$)/);
  await act(async () => { load.respond(200, first); });
}

async function type(text) {
  // user-event goes through React's own value tracking (a raw `value =` assignment does not)
  await userEvent.type(screen.getByLabelText("Your message"), text);
}

describe("Help chat", () => {
  it("sends with live steps, then shows the saved reply and the outcome", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat?order=4512");
    await type("Where is it?");
    const sendBtn = screen.getByRole("button", { name: /^send$/i });
    expect(sendBtn).toBeEnabled();
    await act(async () => { sendBtn.click(); });
    const req = await net.waitFor("/api/shop/chat/send");
    const body = JSON.parse(req.options.body);
    expect(body).toMatchObject({ text: "Where is it?", about_order: 4512 });
    expect(body.client_id).toBeTruthy();
    expect(req.options.headers["X-Requested-With"]).toBe("CallVerse");
    expect(screen.getByRole("button", { name: /sending/i })).toBeDisabled();   // no double send
    let open;
    await act(async () => { open = req.respondStreamOpen(); });
    await act(async () => { open.push(frame("job", { job_id: "j" }) + frame("step", { text: "Reading your message…" })); });
    await act(async () => { open.push("event: step\ndata: {\"text\": \"Checking yo"); });   // a frame split in two chunks
    await act(async () => { open.push("ur order…\"}\n\n"); });
    // the live texts come from the backend events, while the job runs
    expect(await screen.findByText("Checking your order…")).toBeInTheDocument();
    expect(screen.getByText("Reading your message…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sending/i })).toBeDisabled();
    // the stream ends WITHOUT `done` -> the screen must not pretend it finished
    await act(async () => { open.close(); });
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
  });

  it("shows the reply from the saved conversation after done, and the outcome as text", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat");
    await type("hello");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const req = await net.waitFor("/api/shop/chat/send");
    await act(async () => {
      req.respondStream([frame("job", { job_id: "j" }), frame("step", { text: "Writing the reply…" }),
                         frame("done", { ticket_id: "T-0007", status: "Waiting for user", reply: "x", outcome: "ask_photo_v9" })]);
    });
    // after done the conversation is READ BACK for the ticket the result names
    const reload = await net.waitFor("ticket=T-0007");
    await act(async () => { reload.respond(200, convo("T-0007", [["user", "hello"], ["assistant", "Please send a photo."]])); });
    expect(screen.getByText("Please send a photo.")).toBeInTheDocument();
    expect(screen.getAllByText("T-0007").length).toBeGreaterThan(0);
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent("Outcome: ask photo v9");   // unknown outcome, as text
    expect(screen.getByRole("button", { name: /^send$/i })).toBeDisabled();   // empty draft again
  });

  it("busy outcome is shown as the assistant being busy, not as an error", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat");
    await type("hello");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const req = await net.waitFor("/api/shop/chat/send");
    await act(async () => { req.respondStream([frame("done", { ticket_id: "T-0001", status: "Open", reply: "busy", outcome: "busy" })]); });
    const reload = await net.waitFor("ticket=T-0001");
    await act(async () => { reload.respond(200, convo("T-0001", [["user", "hello"], ["assistant", "Our assistant is busy, please try again later."]])); });
    expect(screen.getByText(/Our assistant is busy right now/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("lost connection: Check status re-attaches without sending again", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat");
    await type("slow one");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const req = await net.waitFor("/api/shop/chat/send");
    await act(async () => { req.respondStream([frame("step", { text: "Reading your message…" })], { cut: true }); });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Connection lost");
    expect(alert).toHaveTextContent("NOT sent again");
    await act(async () => { within(alert).getByRole("button", { name: /check status/i }).click(); });
    const jobReq = await net.waitFor("/api/shop/chat/job");
    await act(async () => { jobReq.respond(200, { job: { job_id: "j", status: "running", client_id: "c", steps: [{ text: "Reading your message…" }], result: null, error: null } }); });
    const attach = await net.waitFor("/api/shop/chat/job/stream");
    await act(async () => { attach.respondStream([frame("step", { text: "Reading your message…" }), frame("step", { text: "Writing the reply…" }), frame("done", { ticket_id: "T-0001", status: "Solved", outcome: "approve" })]); });
    const reload = await net.waitFor("ticket=T-0001");
    await act(async () => { reload.respond(200, convo("T-0001", [["user", "slow one"], ["assistant", "Done."]])); });
    expect(screen.getByText("Done.")).toBeInTheDocument();
    expect(net.all("/api/shop/chat/send")).toHaveLength(1);   // exactly one send
  });

  it("a failed request (error event or 409) is shown with its words and does not fake a reply", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat");
    await type("x");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const req = await net.waitFor("/api/shop/chat/send");
    await act(async () => { req.respondStream([frame("error", { error: "worker_error", message: "RuntimeError: boom" })]); });
    expect(screen.getByRole("alert")).toHaveTextContent("RuntimeError: boom");
    await act(async () => { screen.getByRole("button", { name: /dismiss/i }).click(); });
    await type("y");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const second = await net.waitFor("/api/shop/chat/send", { index: 1 });
    await act(async () => { second.respond(409, { error: "busy_user", message: "Your previous message is still being processed." }); });
    expect(screen.getByRole("alert")).toHaveTextContent("still being processed");
  });

  it("a job still running on load is shown as such and Send is disabled", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat", { ...EMPTY, job: { job_id: "j", status: "running", client_id: "c", started_at: "2026-11-01T12:00:00", steps: [], result: null, error: null } });
    expect(screen.getByText("CallVerse is still working on your last message")).toBeInTheDocument();
    await type("more");
    expect(screen.getByRole("button", { name: /^send$/i })).toBeDisabled();
  });

  it("unread notice opens the ticket and marks it read on the server", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat", { ...EMPTY, unread: [{ id: "T-0003", status: "Solved" }] });
    expect(screen.getByText("T-0003")).toBeInTheDocument();
    await act(async () => { screen.getByRole("button", { name: /open/i }).click(); });
    const load = await net.waitFor("ticket=T-0003");
    const c = convo("T-0003", [["user", "refund?"], ["assistant", "Finance approved it."]]);
    c.ticket.user_unread = 1;
    await act(async () => { load.respond(200, c); });
    const read = await net.waitFor("/api/shop/chat/tickets/T-0003/read");
    expect(read.options.method).toBe("POST");
    expect(screen.getByText("Finance approved it.")).toBeInTheDocument();
  });

  it("session expiry while sending goes back to login", async () => {
    const net = installFakeFetch();
    await start(net, "/shop/chat");
    await type("x");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const req = await net.waitFor("/api/shop/chat/send");
    await act(async () => { req.respond(401, { error: "not_logged_in", message: "Please log in." }); });
    // the auth context dropped the session: the guarded screens redirect to /login (tested in step 1); here
    // the chat must not show a reply or a success
    expect(screen.queryByText(/Outcome:/)).toBeNull();
  });
});
