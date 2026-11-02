// Manage screen (ShopNova admin): the product form checks its fields before sending and shows the core's
// refusal under the field it names; a product is added with a request id and the list reloads; removing a
// product from the shop is confirmed in a dialog naming the exact product (Tab stays inside, Escape closes,
// the focus returns); an order's status move offers only the moves the API listed, cancelling asks first; a
// lost answer is not sent again blindly ("Try again" keeps the same request id); the denied state.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth.jsx";
import Manage from "../screens/Manage.jsx";
import { installFakeFetch } from "./fakeApi.js";

const ADMIN = { username: "admin", name: "ShopNova Admin", role: "admin", company: "shopnova" };
const OPTIONS = { categories: ["audio", "electronics"], cities: ["Tunis", "Sfax"], statuses: ["processing", "shipped", "cancelled"],
                  limits: { max_name: 100, max_price: 100000, max_stock: 100000 } };
const product = (id, extra = {}) => ({ id, name: `Product ${id}`, category: "audio", price: 19.9, stock: 5, active: 1, source: "app", ...extra });
const page = (items) => ({ items, total: items.length, page: 1, pages: 1, page_size: 50 });

async function start(net, products = [product(1), product(2, { active: 0 })]) {
  render(<MemoryRouter initialEntries={["/admin/manage"]}><AuthProvider><Routes><Route path="/admin/manage" element={<Manage />} /></Routes></AuthProvider></MemoryRouter>);
  (await net.waitFor("/api/auth/session")).respond(200, { session: ADMIN });
  await act(async () => { (await net.waitFor("/api/admin/manage/options")).respond(200, OPTIONS); });
  const list = await net.waitFor(/\/api\/admin\/manage\/products(\?|$)/);
  await act(async () => { list.respond(200, page(products)); });
  return list;
}

const body = (call) => JSON.parse(call.options.body);
const notice = () => document.querySelector('.alert[role="status"]');   // the pager is a status too
// the n-th GET of a list (a POST to /products matches the same path)
async function waitGet(net, part, index) {
  for (let i = 0; i < 100; i++) {
    const gets = net.all(part).filter((c) => !c.options.method);
    if (gets.length > index) return gets[index];
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error(`no GET ${part} #${index}`);
}

describe("Manage", () => {
  it("the product form checks its fields, sends once with a request id and reloads the list", async () => {
    const net = installFakeFetch();
    await start(net);
    await act(async () => { screen.getByRole("button", { name: /add a product/i }).click(); });
    await act(async () => { screen.getByRole("button", { name: /^add product$/i }).click(); });   // empty: nothing sent
    expect(screen.getByText("Name is required.")).toBeInTheDocument();
    expect(screen.getByLabelText(/^name/i)).toHaveFocus();
    expect(net.all("/api/admin/manage/products").filter((c) => c.options.method === "POST")).toHaveLength(0);
    await userEvent.type(screen.getByLabelText(/^name/i), "Desk lamp");
    await userEvent.selectOptions(screen.getByLabelText(/^category/i), "electronics");
    await userEvent.type(screen.getByLabelText(/^price/i), "45.5");
    await userEvent.type(screen.getByLabelText(/^stock/i), "12");
    await act(async () => { screen.getByRole("button", { name: /^add product$/i }).click(); });
    const post = (await net.waitFor("/api/admin/manage/products", { index: 1 }));
    expect(post.options.method).toBe("POST");
    const sent = body(post);
    expect(sent).toMatchObject({ name: "Desk lamp", category: "electronics", price: 45.5, stock: 12 });
    expect(sent.client_id).toBeTruthy();
    expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
    // the core refuses with the field it names: the sentence goes under that field, nothing else changes
    await act(async () => { post.respond(400, { error: "invalid", message: "price must be a number above 0 and at most 100,000 TND", field: "price" }); });
    expect(screen.getByText(/price must be a number above 0/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^price/i)).toHaveAttribute("aria-invalid", "true");
    // corrected and sent again: a NEW request id (the first was refused, never written)
    await userEvent.clear(screen.getByLabelText(/^price/i));
    await userEvent.type(screen.getByLabelText(/^price/i), "45");
    await act(async () => { screen.getByRole("button", { name: /^add product$/i }).click(); });
    const second = await net.waitFor("/api/admin/manage/products", { index: 2 });
    expect(body(second).client_id).not.toBe(sent.client_id);
    await act(async () => { second.respond(200, { ok: true, row: product(9, { name: "Desk lamp", price: 45 }) }); });
    expect(notice()).toHaveTextContent("Product added: id 9, Desk lamp");
    const reload = await waitGet(net, /\/api\/admin\/manage\/products(\?|$)/, 1);
    await act(async () => { reload.respond(200, page([product(1), product(9, { name: "Desk lamp" })])); });
    expect(screen.getByRole("table", { name: /products/i })).toHaveTextContent("Desk lamp");
    expect(screen.queryByRole("heading", { name: /add a product/i })).toBeNull();   // the form closed
  });

  it("removing a product asks in a dialog naming the exact product; Escape cancels and returns the focus", async () => {
    const net = installFakeFetch();
    await start(net);
    const row = screen.getByRole("row", { name: /product 1/i });
    const opener = within(row).getByRole("button", { name: /remove from shop/i });
    opener.focus();
    await act(async () => { opener.click(); });
    const dialog = screen.getByRole("dialog", { name: /remove product 1 from the shop/i });
    expect(dialog).toHaveFocus();
    expect(dialog).toHaveTextContent("1 · Product 1");
    expect(dialog).toHaveTextContent("19.90 TND");
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();                                   // wraps: still inside
    expect(dialog.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
    expect(net.all("/deactivate")).toHaveLength(0);
    // confirmed: one POST with a request id, the row reloads
    await act(async () => { opener.click(); });
    await act(async () => { within(screen.getByRole("dialog")).getByRole("button", { name: /remove from shop/i }).click(); });
    const post = await net.waitFor("/api/admin/manage/products/1/deactivate");
    expect(body(post).client_id).toBeTruthy();
    await act(async () => { post.respond(200, { ok: true, row: product(1, { active: 0 }) }); });
    expect(notice()).toHaveTextContent("Product 1 removed from the shop");
    expect(screen.queryByRole("dialog")).toBeNull();
    const reload = await waitGet(net, /\/api\/admin\/manage\/products(\?|$)/, 1);
    await act(async () => { reload.respond(200, page([product(1, { active: 0 }), product(2, { active: 0 })])); });
    expect(within(screen.getByRole("row", { name: /product 1/i })).getByRole("button", { name: /put back/i })).toBeInTheDocument();
  });

  it("a lost answer is not sent again blindly: 'Try again' keeps the same request id", async () => {
    const net = installFakeFetch();
    await start(net);
    const opener = within(screen.getByRole("row", { name: /product 1/i })).getByRole("button", { name: /remove from shop/i });
    await act(async () => { opener.click(); });
    await act(async () => { within(screen.getByRole("dialog")).getByRole("button", { name: /remove from shop/i }).click(); });
    const post = await net.waitFor("/api/admin/manage/products/1/deactivate");
    await act(async () => { post.fail(); });                 // the network dropped: written or not, unknown
    expect(screen.getByRole("alert")).toHaveTextContent("not confirmed");
    expect(screen.getByRole("alert")).toHaveTextContent("may or may not have been saved");
    await act(async () => { screen.getByRole("button", { name: /try again/i }).click(); });
    const again = await net.waitFor("/api/admin/manage/products/1/deactivate", { index: 1 });
    expect(body(again).client_id).toBe(body(post).client_id);
    await act(async () => { again.respond(200, { ok: true, recorded: true, row: product(1, { active: 0 }) }); });
    expect(notice()).toHaveTextContent("Product 1 removed from the shop");
  });

  it("orders: only the API's moves are offered, cancelling asks first and names the order", async () => {
    const net = installFakeFetch();
    await start(net);
    await act(async () => { screen.getByRole("tab", { name: /orders/i }).click(); });
    const list = await net.waitFor(/\/api\/admin\/manage\/orders(\?|$)/);
    await act(async () => { list.respond(200, page([
      { id: 4514, user_id: 5, user_name: "Leila Mansour", status: "processing", total: 89, paid: 0, payment: "cash_on_delivery", order_date: "2026-10-08", promised_date: "2026-10-14", delivered_date: null, source: "app", moves: ["shipped", "cancelled"], cancel_blocked: null },
      { id: 4511, user_id: 3, user_name: "Amira", status: "processing", total: 54.4, paid: 54.4, payment: "card", order_date: "2026-10-07", promised_date: "2026-10-13", delivered_date: null, source: "app", moves: ["shipped"], cancel_blocked: "This order is paid: it must be refunded first." },
      { id: 4505, user_id: 2, user_name: "Youssef", status: "delivered", total: 34.5, paid: 34.5, payment: "card", order_date: "2026-09-10", promised_date: "2026-09-15", delivered_date: "2026-09-14", source: "app", moves: [], cancel_blocked: null },
    ])); });
    const select = screen.getByLabelText(/new status for order 4514/i);
    expect([...select.options].map((o) => o.value)).toEqual(["", "shipped", "cancelled"]);
    expect([...screen.getByLabelText(/new status for order 4511/i).options].map((o) => o.value)).toEqual(["", "shipped"]);
    expect(screen.getByText("This order is paid: it must be refunded first.")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /4505/ })).toHaveTextContent("No move allowed from here");
    await userEvent.selectOptions(select, "cancelled");
    await act(async () => { within(screen.getByRole("row", { name: /4514/ })).getByRole("button", { name: /apply/i }).click(); });
    const dialog = screen.getByRole("dialog", { name: /cancel order 4514/i });
    expect(dialog).toHaveTextContent("Leila Mansour (5)");
    expect(dialog).toHaveTextContent("paid 0.00 TND");
    expect(net.all("/status")).toHaveLength(0);
    await act(async () => { within(dialog).getByRole("button", { name: /cancel the order/i }).click(); });
    const post = await net.waitFor("/api/admin/manage/orders/4514/status");
    expect(body(post)).toMatchObject({ status: "cancelled" });
    await act(async () => { post.respond(409, { error: "refused", message: "only an order that is not shipped yet (processing) can be cancelled; order 4514 is shipped" }); });
    expect(screen.getByRole("alert")).toHaveTextContent("order 4514 is shipped");
    expect(screen.getByRole("alert")).toHaveTextContent("Nothing was saved.");
  });

  it("denied: the API's words, no form", async () => {
    const net = installFakeFetch();
    render(<MemoryRouter initialEntries={["/admin/manage"]}><AuthProvider><Routes><Route path="/admin/manage" element={<Manage />} /></Routes></AuthProvider></MemoryRouter>);
    (await net.waitFor("/api/auth/session")).respond(200, { session: { ...ADMIN, username: "atlas_admin", company: "atlas" } });
    await act(async () => { (await net.waitFor("/api/admin/manage/options")).respond(403, { error: "admin_only", message: "This page is for the ShopNova admin (permission view_dashboard) only." }); });
    expect(screen.getByRole("alert")).toHaveTextContent("ShopNova admin");
    expect(screen.queryByRole("button", { name: /add a product/i })).toBeNull();
  });
});
