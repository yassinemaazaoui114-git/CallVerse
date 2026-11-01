// Manage (ShopNova admin): the tables and forms of the Streamlit Manage page in the new UI. One tab per kind
// of data, each behind its own permission on the server (products: edit_catalogue, orders: edit_orders,
// clients: edit_users, refunds and the admin log: view only). Every write is one of the core's own functions
// (callverse.data.writes), run by the API with the admin's username from the account:
// - products: add, edit, remove from the shop (deactivate) and put back — never deleted;
// - orders: only the status moves the core allows (shown per row), cancel only while not shipped and unpaid,
//   "refunded" never by hand (that is Refund approvals);
// - clients: add and edit — never deleted.
// Forms check the fields before sending (the same limits the core applies, fetched from the API); the core's
// refusal comes back as the sentence it wrote, placed under the field it names. Each submission carries a
// request id: a lost answer is retried with the SAME id, so nothing is ever written twice. A destructive
// change (remove from the shop, cancel an order) is confirmed in a dialog that names the exact record.
import { useRef, useState } from "react";
import { ApiError, manage } from "../api.js";
import Dialog from "../components/Dialog.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { tnd, useGuardedLoad, words } from "../hooks.js";

const TABS = [["products", "Products"], ["orders", "Orders"], ["users", "Clients"], ["refunds", "Refunds"], ["log", "Admin log"]];

function newClientId() {
  return (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `w-${Date.now()}-${Math.random()}`;
}

// ---------- field checks (the core's limits, fetched from /options; checked again by the core) ----------

function checkProduct(f, limits, categories) {
  const errors = {};
  const name = (f.name || "").trim();
  if (!name) errors.name = "Name is required.";
  else if (name.length > limits.max_name) errors.name = `At most ${limits.max_name} characters.`;
  if (!categories.includes(f.category)) errors.category = "Choose one of the shop's categories.";
  const price = Number(f.price);
  if (f.price === "" || Number.isNaN(price) || price <= 0 || price > limits.max_price) errors.price = `A number above 0 and at most ${limits.max_price.toLocaleString("en-US")} TND.`;
  else if (Math.round(price * 100) !== price * 100) errors.price = "At most 2 decimals.";
  const stock = Number(f.stock);
  if (f.stock === "" || !Number.isInteger(stock) || stock < 0 || stock > limits.max_stock) errors.stock = `A whole number from 0 to ${limits.max_stock.toLocaleString("en-US")}.`;
  return errors;
}

function checkUser(f, limits, cities) {
  const errors = {};
  const name = (f.name || "").trim();
  if (!name) errors.name = "Name is required.";
  else if (name.length > limits.max_name) errors.name = `At most ${limits.max_name} characters.`;
  if (!(f.email || "").includes("@")) errors.email = "An email address with an @.";
  const digits = (f.phone || "").replace(/[\s-]/g, "").replace(/^\+?216(?=\d{8}$)/, "");
  if (!/^\d{8}$/.test(digits)) errors.phone = "8 digits (e.g. 20 123 456).";
  if (f.city !== "" && f.city !== null && !cities.includes(f.city)) errors.city = "Choose a city ShopNova serves.";
  return errors;
}

// Only the fields the admin really changed (so the core logs the real change and refuses "nothing to change").
function changed(current, next) {
  const out = {};
  for (const [k, v] of Object.entries(next)) {
    const before = current[k] === null || current[k] === undefined ? "" : String(current[k]);
    if (String(v) !== before) out[k] = v;
  }
  return out;
}

// ---------- one form field ----------

function Field({ id, label, required, error, hint, children }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}{required && <span className="req" aria-hidden="true">*</span>}</label>
      {children}
      {error && <span className="field-error" id={`${id}-error`} role="alert"><Icon name="alert" size={12} />{error}</span>}
      {!error && hint && <span className="hint" id={`${id}-hint`}>{hint}</span>}
    </div>
  );
}

const describedBy = (id, error, hint) => (error ? `${id}-error` : hint ? `${id}-hint` : undefined);

// ---------- the write helper: one request id per attempt, the answer or the error in one place ----------

function useWrite(onDone) {
  const [state, setState] = useState({ busy: false, error: null, field: null, uncertain: null });
  const inflight = useRef(false);

  async function run(label, call, { retryOf } = {}) {
    if (inflight.current) return null;
    inflight.current = true;
    const clientId = retryOf || newClientId();
    setState({ busy: true, error: null, field: null, uncertain: null });
    try {
      const out = await call(clientId);
      setState({ busy: false, error: null, field: null, uncertain: null });
      onDone(out, label);
      return out;
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_logged_in") { setState({ busy: false, error: e, field: null, uncertain: null }); return null; }
      if (e instanceof ApiError && e.code !== "unavailable") {
        // the core or the API refused: by their contract nothing was written
        setState({ busy: false, error: e, field: (e.body && e.body.field) || null, uncertain: null });
        return null;
      }
      // the answer was lost: the write may or may not have happened; the same request id is kept for the retry
      setState({ busy: false, error: null, field: null, uncertain: { label, call, clientId, message: e.message } });
      return null;
    } finally {
      inflight.current = false;
    }
  }
  return { ...state, run, clear: () => setState({ busy: false, error: null, field: null, uncertain: null }) };
}

function WriteNotice({ write }) {
  if (write.uncertain) {
    return (
      <div className="alert alert-warn" role="alert">
        <Icon name="clock" />
        <div className="stack" style={{ gap: "var(--cv-s1)" }}>
          <strong>{write.uncertain.label}: not confirmed</strong>
          <span className="small">{write.uncertain.message} The change may or may not have been saved. "Try again" sends the same request id: the server will not apply it twice.</span>
        </div>
        <div className="actions row">
          <button type="button" className="btn btn-sm" onClick={() => write.run(write.uncertain.label, write.uncertain.call, { retryOf: write.uncertain.clientId })}><Icon name="refresh" size={14} />Try again</button>
          <button type="button" className="btn btn-ghost btn-sm" aria-label="Dismiss" onClick={write.clear}><Icon name="x" size={14} /></button>
        </div>
      </div>
    );
  }
  if (write.error && !write.field) return <ApiErrorView error={write.error} note={write.error.code === "refused" || write.error.code === "invalid" ? "Nothing was saved." : null} />;
  return null;
}

// ---------- the table (search + 50 rows per page) ----------

function Table({ table, data, columns, render, actions, caption }) {
  if (data.items.length === 0) return <div className="panel"><Empty icon="file" title="No rows" text="Nothing matches, or the table is empty." /></div>;
  return (
    <div className="table-wrap">
      <table className="tickets records">
        <caption className="visually-hidden">{caption}</caption>
        <thead><tr>{columns.map((c) => <th key={c.key} scope="col" className={c.num ? "num" : ""}>{c.label}</th>)}{actions && <th scope="col">Actions</th>}</tr></thead>
        <tbody>
          {data.items.map((row) => (
            <tr key={row.id}>
              {columns.map((c) => <td key={c.key} className={c.num ? "num tabular" : ""}>{render(row, c.key)}</td>)}
              {actions && <td>{actions(row)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function cell(row, key) {
  const v = row[key];
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// ---------- products ----------

function ProductForm({ initial, options, onSubmit, onCancel, write, submitLabel }) {
  const [f, setF] = useState(initial);
  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState({});
  const limits = options.limits;
  const idp = initial.id ? `p${initial.id}` : "pnew";
  const serverField = write.field && write.error ? { [write.field]: write.error.message } : {};
  const shown = { ...errors, ...serverField };

  function validate(next) { const e = checkProduct(next, limits, options.categories); setErrors(e); return e; }
  function set(k, v) { const next = { ...f, [k]: v }; setF(next); if (touched[k]) validate(next); }
  function blur(k) { setTouched((t) => ({ ...t, [k]: true })); validate(f); }
  function submit(e) {
    e.preventDefault();
    setTouched({ name: true, category: true, price: true, stock: true });
    const errs = validate(f);
    if (Object.keys(errs).length) { document.getElementById(`${idp}-${Object.keys(errs)[0]}`)?.focus(); return; }
    onSubmit({ name: f.name.trim(), category: f.category, price: Math.round(Number(f.price) * 100) / 100, stock: Number(f.stock) });
  }
  return (
    <form className="stack" onSubmit={submit} noValidate aria-busy={write.busy}>
      <div className="form-grid">
        <Field id={`${idp}-name`} label="Name" required error={shown.name} hint={`At most ${limits.max_name} characters`}>
          <input id={`${idp}-name`} className="input" value={f.name} maxLength={limits.max_name} onChange={(e) => set("name", e.target.value)} onBlur={() => blur("name")} aria-invalid={!!shown.name} aria-describedby={describedBy(`${idp}-name`, shown.name, "hint")} disabled={write.busy} />
        </Field>
        <Field id={`${idp}-category`} label="Category" required error={shown.category}>
          <select id={`${idp}-category`} className="select" value={f.category} onChange={(e) => set("category", e.target.value)} onBlur={() => blur("category")} aria-invalid={!!shown.category} disabled={write.busy}>
            <option value="">Choose…</option>
            {options.categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
        <Field id={`${idp}-price`} label="Price (TND)" required error={shown.price} hint="Above 0, at most 2 decimals">
          <input id={`${idp}-price`} className="input tabular" type="number" inputMode="decimal" step="0.01" min="0.01" max={limits.max_price} value={f.price} onChange={(e) => set("price", e.target.value)} onBlur={() => blur("price")} aria-invalid={!!shown.price} disabled={write.busy} />
        </Field>
        <Field id={`${idp}-stock`} label="Stock" required error={shown.stock} hint="A whole number">
          <input id={`${idp}-stock`} className="input tabular" type="number" inputMode="numeric" step="1" min="0" max={limits.max_stock} value={f.stock} onChange={(e) => set("stock", e.target.value)} onBlur={() => blur("stock")} aria-invalid={!!shown.stock} disabled={write.busy} />
        </Field>
      </div>
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={write.busy}>{write.busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="check" size={16} />}{write.busy ? "Saving…" : submitLabel}</button>
        <button type="button" className="btn" onClick={onCancel} disabled={write.busy}>Cancel</button>
        {initial.id && <span className="muted small">Old orders keep the price they were sold at.</span>}
      </div>
    </form>
  );
}

function Products({ options, notify }) {
  const [search, setSearch] = useState(""); const [typed, setTyped] = useState(""); const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useGuardedLoad((signal) => manage.table("products", search, page, signal), [search, page], { keep: true });
  const [mode, setMode] = useState(null);         // null | {add: true} | {edit: product}
  const [confirm, setConfirm] = useState(null);   // {product, active: false|true, opener}
  const write = useWrite((out, label) => { notify(out && out.row && label.endsWith("added") ? `${label}: id ${out.row.id}, ${out.row.name}` : label); setMode(null); setConfirm(null); reload(); });

  const columns = [{ key: "id", label: "Id", num: true }, { key: "name", label: "Name" }, { key: "category", label: "Category" },
                   { key: "price", label: "Price", num: true }, { key: "stock", label: "Stock", num: true }, { key: "active", label: "In the shop" }];
  const render = (row, key) => {
    if (key === "price") return tnd(row.price);
    if (key === "active") return <span className={`badge ${row.active ? "badge-ok" : "badge-neutral"}`}>{row.active ? "on sale" : "removed"}</span>;
    return cell(row, key);
  };
  const actions = (row) => (
    <span className="row" style={{ flexWrap: "nowrap" }}>
      <button type="button" className="btn btn-sm" onClick={() => { write.clear(); setMode({ edit: row }); }} disabled={write.busy}><Icon name="pen" size={12} />Edit</button>
      <button type="button" className={`btn btn-sm ${row.active ? "btn-danger" : ""}`} disabled={write.busy}
        onClick={(e) => setConfirm({ product: row, active: !row.active, opener: e.currentTarget })}>
        {row.active ? "Remove from shop" : "Put back"}
      </button>
    </span>
  );

  return (
    <div className="stack">
      <SearchBar id="products" typed={typed} setTyped={setTyped} onSearch={(s) => { setSearch(s); setPage(1); }} data={data} setPage={setPage}>
        {!mode && <button type="button" className="btn btn-primary btn-sm" onClick={() => { write.clear(); setMode({ add: true }); }}><Icon name="package" size={14} />Add a product</button>}
      </SearchBar>
      <WriteNotice write={write} />
      {mode && (
        <section className="panel" aria-labelledby="product-form-title">
          <div className="panel-head"><h2 id="product-form-title">{mode.add ? "Add a product" : `Edit product ${mode.edit.id} · ${mode.edit.name}`}</h2></div>
          <ProductForm key={mode.add ? "new" : mode.edit.id} options={options} write={write} submitLabel={mode.add ? "Add product" : "Save changes"}
            initial={mode.add ? { name: "", category: "", price: "", stock: "" } : { id: mode.edit.id, name: mode.edit.name, category: mode.edit.category, price: String(mode.edit.price), stock: String(mode.edit.stock) }}
            onCancel={() => { setMode(null); write.clear(); }}
            onSubmit={(fields) => {
              if (mode.add) write.run("Product added", (client_id) => manage.createProduct({ ...fields, client_id }));
              else {
                const diff = changed(mode.edit, fields);
                if (Object.keys(diff).length === 0) { notify("Nothing to change."); setMode(null); return; }
                write.run(`Product ${mode.edit.id} saved`, (client_id) => manage.updateProduct(mode.edit.id, { ...diff, client_id }));
              }
            }} />
        </section>
      )}
      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading products…" />}
      {data && <div className={loading ? "is-stale" : ""} aria-busy={loading}><Table table="products" data={data} columns={columns} render={render} actions={actions} caption="Products" /></div>}
      {confirm && (
        <Dialog title={confirm.active ? `Put product ${confirm.product.id} back in the shop?` : `Remove product ${confirm.product.id} from the shop?`} onClose={() => setConfirm(null)} busy={write.busy} opener={confirm.opener} labelledBy="confirm-product">
          <dl className="kv">
            <dt>Product</dt><dd>{confirm.product.id} · {confirm.product.name}</dd>
            <dt>Category</dt><dd>{confirm.product.category}</dd>
            <dt>Price</dt><dd className="tabular">{tnd(confirm.product.price)}</dd>
            <dt>Effect</dt><dd><strong>{confirm.active ? "It is on sale again." : "It leaves the shop; the row stays and old orders still show it. It can be put back later."}</strong></dd>
          </dl>
          <div className="row">
            <button type="button" className={`btn ${confirm.active ? "btn-primary" : "btn-danger"}`} disabled={write.busy}
              onClick={() => write.run(confirm.active ? `Product ${confirm.product.id} is on sale again` : `Product ${confirm.product.id} removed from the shop`, (client_id) => manage.setProductActive(confirm.product.id, confirm.active, client_id))}>
              {write.busy ? "Saving…" : confirm.active ? "Put back" : "Remove from shop"}
            </button>
            <button type="button" className="btn" onClick={() => setConfirm(null)} disabled={write.busy}>Cancel</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

// ---------- orders ----------

function Orders({ notify }) {
  const [search, setSearch] = useState(""); const [typed, setTyped] = useState(""); const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useGuardedLoad((signal) => manage.table("orders", search, page, signal), [search, page], { keep: true });
  const [choice, setChoice] = useState({});       // order id -> chosen status
  const [confirm, setConfirm] = useState(null);   // {order, status, opener}
  const write = useWrite((out, label) => { notify(label); setConfirm(null); reload(); });

  const columns = [{ key: "id", label: "Order", num: true }, { key: "user_name", label: "Client" }, { key: "status", label: "Status" },
                   { key: "total", label: "Total", num: true }, { key: "paid", label: "Paid", num: true }, { key: "payment", label: "Payment" },
                   { key: "order_date", label: "Ordered" }, { key: "promised_date", label: "Promised" }, { key: "delivered_date", label: "Delivered" }];
  const render = (row, key) => {
    if (key === "total" || key === "paid") return tnd(row[key]);
    if (key === "status") return <span className="badge badge-neutral">{words(row.status)}</span>;
    if (key === "user_name") return `${row.user_name || "—"} (${row.user_id})`;
    return cell(row, key);
  };
  function apply(row, opener) {
    const status = choice[row.id];
    if (!status) return;
    if (status === "cancelled") { setConfirm({ order: row, status, opener }); return; }
    write.run(`Order ${row.id} is now ${words(status)}`, (client_id) => manage.setOrderStatus(row.id, status, client_id));
  }
  const actions = (row) => {
    if (!row.moves || row.moves.length === 0) return <span className="muted xs">{row.cancel_blocked || "No move allowed from here"}</span>;
    return (
      <span className="row" style={{ flexWrap: "nowrap" }}>
        <label className="visually-hidden" htmlFor={`move-${row.id}`}>New status for order {row.id}</label>
        <select id={`move-${row.id}`} className="select" style={{ minHeight: 32, width: "auto" }} value={choice[row.id] || ""} onChange={(e) => setChoice((c) => ({ ...c, [row.id]: e.target.value }))} disabled={write.busy}>
          <option value="">Change status…</option>
          {row.moves.map((m) => <option key={m} value={m}>{words(m)}</option>)}
        </select>
        <button type="button" className="btn btn-sm" disabled={!choice[row.id] || write.busy} onClick={(e) => apply(row, e.currentTarget)}>Apply</button>
        {row.cancel_blocked && <span className="muted xs">{row.cancel_blocked}</span>}
      </span>
    );
  };
  return (
    <div className="stack">
      <p className="muted small">Only the moves the carrier would make; cancel only before shipping and when nothing is paid; refunds go through Refund approvals.</p>
      <SearchBar id="orders" typed={typed} setTyped={setTyped} onSearch={(s) => { setSearch(s); setPage(1); }} data={data} setPage={setPage} />
      <WriteNotice write={write} />
      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading orders…" />}
      {data && <div className={loading ? "is-stale" : ""} aria-busy={loading}><Table table="orders" data={data} columns={columns} render={render} actions={actions} caption="Orders" /></div>}
      {confirm && (
        <Dialog title={`Cancel order ${confirm.order.id}?`} onClose={() => setConfirm(null)} busy={write.busy} opener={confirm.opener} labelledBy="confirm-order">
          <dl className="kv">
            <dt>Order</dt><dd>{confirm.order.id} · {confirm.order.user_name} ({confirm.order.user_id})</dd>
            <dt>Status</dt><dd>{words(confirm.order.status)} · paid {tnd(confirm.order.paid)}</dd>
            <dt>Effect</dt><dd><strong>The order is cancelled and its items go back to stock. This cannot be undone.</strong></dd>
          </dl>
          <div className="row">
            <button type="button" className="btn btn-danger" disabled={write.busy} onClick={() => write.run(`Order ${confirm.order.id} cancelled`, (client_id) => manage.setOrderStatus(confirm.order.id, "cancelled", client_id))}>{write.busy ? "Saving…" : "Cancel the order"}</button>
            <button type="button" className="btn" onClick={() => setConfirm(null)} disabled={write.busy}>Keep it</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

// ---------- clients ----------

function UserForm({ initial, options, onSubmit, onCancel, write, submitLabel }) {
  const [f, setF] = useState(initial);
  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState({});
  const limits = options.limits;
  const idp = initial.id ? `u${initial.id}` : "unew";
  const serverField = write.field && write.error ? { [write.field]: write.error.message } : {};
  const shown = { ...errors, ...serverField };
  function validate(next) { const e = checkUser(next, limits, options.cities); setErrors(e); return e; }
  function set(k, v) { const next = { ...f, [k]: v }; setF(next); if (touched[k]) validate(next); }
  function blur(k) { setTouched((t) => ({ ...t, [k]: true })); validate(f); }
  function submit(e) {
    e.preventDefault();
    setTouched({ name: true, email: true, phone: true, city: true });
    const errs = validate(f);
    if (Object.keys(errs).length) { document.getElementById(`${idp}-${Object.keys(errs)[0]}`)?.focus(); return; }
    onSubmit({ name: f.name.trim(), email: f.email.trim(), phone: f.phone.trim(), city: f.city });
  }
  return (
    <form className="stack" onSubmit={submit} noValidate aria-busy={write.busy}>
      <div className="form-grid">
        <Field id={`${idp}-name`} label="Name" required error={shown.name}>
          <input id={`${idp}-name`} className="input" value={f.name} maxLength={limits.max_name} autoComplete="off" onChange={(e) => set("name", e.target.value)} onBlur={() => blur("name")} aria-invalid={!!shown.name} disabled={write.busy} />
        </Field>
        <Field id={`${idp}-email`} label="Email" required error={shown.email}>
          <input id={`${idp}-email`} className="input" type="email" value={f.email} autoComplete="off" onChange={(e) => set("email", e.target.value)} onBlur={() => blur("email")} aria-invalid={!!shown.email} disabled={write.busy} />
        </Field>
        <Field id={`${idp}-phone`} label="Phone" required error={shown.phone} hint="8 digits, e.g. 20 123 456">
          <input id={`${idp}-phone`} className="input" type="tel" value={f.phone} autoComplete="off" onChange={(e) => set("phone", e.target.value)} onBlur={() => blur("phone")} aria-invalid={!!shown.phone} disabled={write.busy} />
        </Field>
        <Field id={`${idp}-city`} label="City" required={!initial.id} error={shown.city}>
          <select id={`${idp}-city`} className="select" value={f.city ?? ""} onChange={(e) => set("city", e.target.value)} onBlur={() => blur("city")} aria-invalid={!!shown.city} disabled={write.busy}>
            <option value="">{initial.id ? "(none)" : "Choose…"}</option>
            {options.cities.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
      </div>
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={write.busy}>{write.busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="check" size={16} />}{write.busy ? "Saving…" : submitLabel}</button>
        <button type="button" className="btn" onClick={onCancel} disabled={write.busy}>Cancel</button>
        <span className="muted small">No login is created: a client only exists as data.</span>
      </div>
    </form>
  );
}

function Users({ options, notify }) {
  const [search, setSearch] = useState(""); const [typed, setTyped] = useState(""); const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useGuardedLoad((signal) => manage.table("users", search, page, signal), [search, page], { keep: true });
  const [mode, setMode] = useState(null);
  const write = useWrite((out, label) => { notify(out && out.row && label.endsWith("added") ? `${label}: id ${out.row.id}, ${out.row.name}` : label); setMode(null); reload(); });
  const columns = [{ key: "id", label: "Id", num: true }, { key: "name", label: "Name" }, { key: "email", label: "Email" }, { key: "phone", label: "Phone" }, { key: "city", label: "City" }];
  const actions = (row) => <button type="button" className="btn btn-sm" onClick={() => { write.clear(); setMode({ edit: row }); }} disabled={write.busy}><Icon name="pen" size={12} />Edit</button>;
  return (
    <div className="stack">
      <SearchBar id="users" typed={typed} setTyped={setTyped} onSearch={(s) => { setSearch(s); setPage(1); }} data={data} setPage={setPage}>
        {!mode && <button type="button" className="btn btn-primary btn-sm" onClick={() => { write.clear(); setMode({ add: true }); }}><Icon name="user" size={14} />Add a client</button>}
      </SearchBar>
      <WriteNotice write={write} />
      {mode && (
        <section className="panel" aria-labelledby="user-form-title">
          <div className="panel-head"><h2 id="user-form-title">{mode.add ? "Add a client" : `Edit client ${mode.edit.id} · ${mode.edit.name}`}</h2></div>
          <UserForm key={mode.add ? "new" : mode.edit.id} options={options} write={write} submitLabel={mode.add ? "Add client" : "Save changes"}
            initial={mode.add ? { name: "", email: "", phone: "", city: "" } : { id: mode.edit.id, name: mode.edit.name || "", email: mode.edit.email || "", phone: mode.edit.phone || "", city: mode.edit.city || "" }}
            onCancel={() => { setMode(null); write.clear(); }}
            onSubmit={(fields) => {
              if (mode.add) write.run("Client added", (client_id) => manage.createUser({ ...fields, client_id }));
              else {
                const diff = changed(mode.edit, fields);
                if (Object.keys(diff).length === 0) { notify("Nothing to change."); setMode(null); return; }
                write.run(`Client ${mode.edit.id} saved`, (client_id) => manage.updateUser(mode.edit.id, { ...diff, client_id }));
              }
            }} />
        </section>
      )}
      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading clients…" />}
      {data && <div className={loading ? "is-stale" : ""} aria-busy={loading}><Table table="users" data={data} columns={columns} render={cell} actions={actions} caption="Clients" /></div>}
    </div>
  );
}

// ---------- read-only tables ----------

function ReadOnly({ table, caption, note }) {
  const [search, setSearch] = useState(""); const [typed, setTyped] = useState(""); const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useGuardedLoad((signal) => manage.table(table, search, page, signal), [table, search, page], { keep: true });
  const columns = data && data.items.length ? Object.keys(data.items[0]).map((k) => ({ key: k, label: k.replace(/_/g, " ") })) : [];
  return (
    <div className="stack">
      <p className="muted small">{note}</p>
      {table !== "log" && <SearchBar id={table} typed={typed} setTyped={setTyped} onSearch={(s) => { setSearch(s); setPage(1); }} data={data} setPage={setPage} />}
      {error && <ApiErrorView error={error} onRetry={reload} />}
      {!error && loading && !data && <Loading text="Loading…" />}
      {data && <div className={loading ? "is-stale" : ""} aria-busy={loading}><Table table={table} data={data} columns={columns} render={cell} caption={caption} /></div>}
    </div>
  );
}

function SearchBar({ id, typed, setTyped, onSearch, data, setPage, children }) {
  return (
    <form className="records-tools" onSubmit={(e) => { e.preventDefault(); onSearch(typed.trim()); }}>
      <div className="field">
        <label htmlFor={`${id}-search`}>Search</label>
        <input id={`${id}-search`} className="input" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="id, name, status…" />
      </div>
      <button type="submit" className="btn"><Icon name="search" size={14} />Search</button>
      {data && (
        <span className="row small muted" role="status">
          {data.total} rows · {data.page_size} per page · page {data.page} of {data.pages}
          <button type="button" className="btn btn-sm" disabled={data.page <= 1} onClick={() => setPage(data.page - 1)} aria-label="Previous page">‹</button>
          <button type="button" className="btn btn-sm" disabled={data.page >= data.pages} onClick={() => setPage(data.page + 1)} aria-label="Next page">›</button>
        </span>
      )}
      {children && <span style={{ marginLeft: "auto" }}>{children}</span>}
    </form>
  );
}

// ---------- the screen ----------

export default function Manage() {
  const [tab, setTab] = useState("products");
  const [notice, setNotice] = useState(null);
  const options = useGuardedLoad((signal) => manage.options(signal), []);

  function notify(text) { setNotice(text); }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Manage</h1>
          <p className="sub">ShopNova's products, orders and clients · every change is checked by the shop's own rules and logged with your name · nothing is deleted</p>
        </div>
      </div>
      <div className="records-tabs" role="tablist" aria-label="Tables">
        {TABS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={`btn btn-sm ${tab === key ? "btn-primary" : ""}`} onClick={() => { setTab(key); setNotice(null); }}>{label}</button>
        ))}
      </div>
      {notice && (
        <div className="alert" role="status" style={{ marginBottom: "var(--cv-s3)" }}>
          <Icon name="check" />
          <strong>{notice}</strong>
          <div className="actions"><button type="button" className="btn btn-ghost btn-sm" aria-label="Dismiss" onClick={() => setNotice(null)}><Icon name="x" size={14} /></button></div>
        </div>
      )}
      {options.error && <ApiErrorView error={options.error} onRetry={options.reload} />}
      {!options.error && !options.data && <Loading text="Loading…" />}
      {options.data && tab === "products" && <Products options={options.data} notify={notify} />}
      {options.data && tab === "orders" && <Orders notify={notify} />}
      {options.data && tab === "users" && <Users options={options.data} notify={notify} />}
      {options.data && tab === "refunds" && <ReadOnly table="refunds" caption="Refunds" note="View only: refunds are written by the Coordinator or through Refund approvals." />}
      {options.data && tab === "log" && <ReadOnly table="log" caption="Admin log" note="The last 50 admin actions: who, when, before and after." />}
    </>
  );
}
