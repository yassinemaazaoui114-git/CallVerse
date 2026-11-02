// T35 tests: a photo in the Help chat. Choose a photo -> small preview -> the send body carries `image_b64`;
// a photo that is too large or of another type -> a plain error and nothing is sent; remove -> not sent;
// a photo with no text can be sent; Atlas uses the same screen and route shape. The API is the fake fetch.
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import Chat from "../screens/Chat.jsx";
import { installFakeFetch } from "./fakeApi.js";

const SARA = { username: "sara", name: "Sara Ben Ali", role: "user", company: "shopnova" };
const HEDI = { username: "hedi", name: "Hedi", role: "user", company: "atlas" };
const EMPTY = { ticket: null, messages: [], unread: [], job: null, server_time: "t" };
const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

// A small fake JPEG: the screen checks only the browser's type and size (the API checks the bytes).
const jpeg = (size = 64, name = "cracked.jpg", type = "image/jpeg") => {
  const file = new File([new Uint8Array(Math.min(size, 64))], name, { type });
  if (size > 64) Object.defineProperty(file, "size", { value: size });   // no need to build a real 6 MB blob
  return file;
};

async function start(net, company = "shopnova") {
  const path = company === "atlas" ? "/atlas/chat" : "/shop/chat";
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes><Route path={path} element={<Chat company={company} />} /></Routes>
      </AuthProvider>
    </MemoryRouter>
  );
  (await net.waitFor("/api/auth/session")).respond(200, { session: company === "atlas" ? HEDI : SARA });
  const load = await net.waitFor(company === "atlas" ? /\/api\/atlas\/chat(\?|$)/ : /\/api\/shop\/chat(\?|$)/);
  await act(async () => { load.respond(200, EMPTY); });
}

async function choose(file) {
  // applyAccept: false so a wrong type reaches the screen's own check (a user can pick "All files")
  await userEvent.setup({ applyAccept: false }).upload(screen.getByLabelText("Add a photo"), file);
}

describe("Help chat photo (T35)", () => {
  it("choose a photo -> preview -> the send body has image_b64 with the text; the photo is cleared after", async () => {
    const net = installFakeFetch();
    await start(net);
    await choose(jpeg());
    const preview = await screen.findByAltText("Photo to send: cracked.jpg");
    expect(preview.getAttribute("src")).toMatch(/^data:image\/jpeg;base64,/);
    await userEvent.type(screen.getByLabelText("Your message"), "My order 4509 arrived damaged, see the photo.");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const req = await net.waitFor("/api/shop/chat/send");
    const body = JSON.parse(req.options.body);
    expect(body.text).toBe("My order 4509 arrived damaged, see the photo.");
    expect(body.image_b64).toMatch(/^data:image\/jpeg;base64,/);
    expect(screen.getByRole("button", { name: /^photo$|change photo/i })).toBeDisabled();   // no change while sending
    await act(async () => { req.respondStream([frame("done", { ticket_id: "T-0009", status: "Open", outcome: "escalate" })]); });
    await waitFor(() => expect(screen.queryByAltText(/Photo to send/)).not.toBeInTheDocument());
  });

  it("a photo with no text can be sent", async () => {
    const net = installFakeFetch();
    await start(net);
    const sendBtn = screen.getByRole("button", { name: /^send$/i });
    expect(sendBtn).toBeDisabled();
    await choose(jpeg(64, "photo.png", "image/png"));
    await screen.findByAltText("Photo to send: photo.png");
    expect(sendBtn).toBeEnabled();
    await act(async () => { sendBtn.click(); });
    const body = JSON.parse((await net.waitFor("/api/shop/chat/send")).options.body);
    expect(body.text).toBe("");
    expect(body.image_b64).toMatch(/^data:image\/png;base64,/);
  });

  it("too large or wrong type: plain error, no preview, nothing sent", async () => {
    const net = installFakeFetch();
    await start(net);
    await choose(jpeg(6 * 1024 * 1024, "big.jpg"));
    expect(await screen.findByRole("alert")).toHaveTextContent("too large");
    expect(screen.queryByAltText(/Photo to send/)).not.toBeInTheDocument();
    await choose(jpeg(64, "anim.gif", "image/gif"));
    expect(await screen.findByRole("alert")).toHaveTextContent("JPEG, PNG or WebP");
    expect(screen.getByRole("button", { name: /^send$/i })).toBeDisabled();   // no text and no photo
    await userEvent.type(screen.getByLabelText("Your message"), "hello");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const body = JSON.parse((await net.waitFor("/api/shop/chat/send")).options.body);
    expect(body).not.toHaveProperty("image_b64");
  });

  it("remove x: the photo is not sent", async () => {
    const net = installFakeFetch();
    await start(net);
    await choose(jpeg());
    await screen.findByAltText("Photo to send: cracked.jpg");
    await act(async () => { screen.getByRole("button", { name: "Remove the photo" }).click(); });
    expect(screen.queryByAltText(/Photo to send/)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Your message"), "no photo after all");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const body = JSON.parse((await net.waitFor("/api/shop/chat/send")).options.body);
    expect(body).toMatchObject({ text: "no photo after all" });
    expect(body).not.toHaveProperty("image_b64");
  });

  it("Atlas: the same photo field goes to the Atlas chat route", async () => {
    const net = installFakeFetch();
    await start(net, "atlas");
    await choose(jpeg(64, "room.webp", "image/webp"));
    await screen.findByAltText("Photo to send: room.webp");
    await userEvent.type(screen.getByLabelText("Your message"), "The room was dirty.");
    await act(async () => { screen.getByRole("button", { name: /^send$/i }).click(); });
    const body = JSON.parse((await net.waitFor("/api/atlas/chat/send")).options.body);
    expect(body.image_b64).toMatch(/^data:image\/webp;base64,/);
  });
});
