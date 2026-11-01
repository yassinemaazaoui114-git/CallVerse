// Help chat (ShopNova customer, step 3): the customer talks to CallVerse through the web chat channel.
//
// What the screen holds and where it comes from:
// - the conversation: the ticket and its messages, always READ BACK from the tickets store through
//   GET /api/shop/chat (never kept only in memory), so a reload, a reconnection or a reply written later by
//   the finance team shows what is really saved;
// - the order context (?order=N from "Ask about this order"): sent as about_order; the channel adds the order
//   number to a message that names none (F1, like the Streamlit page); "New chat" drops it;
// - one send at a time: POST /api/shop/chat/send returns an SSE stream (sse.js) with the channel's live step
//   texts, then `done` with the channel's saved result (or `error`). Send is disabled while a job runs, and
//   each send carries a fresh client_id so a double click or a retry is the SAME job on the server;
// - transport state (sending / disconnected / failed) is kept apart from the business outcome (approve, busy,
//   not_your_order, …), which only ever comes from the saved result and is shown as plain text;
// - after a disconnect NOTHING is sent again: the screen says the request may still be running, offers
//   "Check status" (GET /api/shop/chat/job, and re-attach to the live stream when it still runs) and shows the
//   saved conversation once the job is done;
// - the "New reply on T-00NN" notices (finance's decision on another ticket): opening one shows that ticket and
//   marks it read on the server (owned tickets only, checked there).
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api.js";
import { useAuth } from "../auth.jsx";
import Icon from "../components/Icon.jsx";
import { ApiErrorView, Empty, Loading } from "../components/States.jsx";
import { useGuardedLoad, words } from "../hooks.js";
import { readSSE } from "../sse.js";

const BUSY_OUTCOME = "busy";   // the channel's own "assistant is busy" result (quota): a normal outcome

function newClientId() {
  return (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `c-${Date.now()}-${Math.random()}`;
}

export default function Chat() {
  const { expired } = useAuth();
  const [params, setParams] = useSearchParams();
  const ticketParam = params.get("ticket") || "";
  const orderParam = params.get("order") || "";

  const { data: convo, error, loading, reload } = useGuardedLoad((signal) => api.chat(ticketParam || undefined, signal), [ticketParam]);

  const [draft, setDraft] = useState("");
  // transport: {status: idle | sending | attached | uncertain | failed, reason, steps, message}
  //   sending   = our POST stream is open          attached  = re-attached to the running job's stream
  //   uncertain = we do not know how the submission ended (reason: "disconnected" | "busy_user"): the server
  //               may still be running it -> only "Check status" / "Resend the same message" are offered
  //   failed    = the server said it failed (error event / refusal): the next message is a NEW submission
  const [tx, setTx] = useState({ status: "idle", reason: null, steps: [], message: null });
  // the submission whose outcome is uncertain: its request id and its payload stay together, so a recovery
  // or a resend is exactly that request, and a NEW message always gets a new id
  const [pending, setPending] = useState(null);   // {clientId, text, ticketId, aboutOrder} | null
  const [lastResult, setLastResult] = useState(null);   // the `done` data of the last send (business outcome)
  const [fresh, setFresh] = useState(false);             // "New chat" pressed: show an empty conversation
  const streamSeq = useRef(0);          // the number of the stream in progress: events of an older one are dropped
  const streamCtrl = useRef(null);      // its AbortController (detach = abort; the server's job goes on)
  const recovering = useRef(false);     // one Check status at a time
  const markedRef = useRef(new Set());
  const inputRef = useRef(null);

  const ticket = fresh ? null : (convo && convo.ticket) || null;
  const messages = fresh ? [] : (convo && convo.messages) || [];
  const unread = (convo && convo.unread) || [];
  const job = convo && convo.job;
  const busy = tx.status === "sending" || tx.status === "attached";
  const uncertain = tx.status === "uncertain";

  // Detach from any stream when the conversation changes (another ticket, New chat) or the screen unmounts
  // (navigation, logout, session expiry). Detaching never cancels the server's job: it only stops listening.
  const detach = useCallback(() => {
    streamSeq.current += 1;
    if (streamCtrl.current) { streamCtrl.current.abort(); streamCtrl.current = null; }
    recovering.current = false;
  }, []);
  useEffect(() => detach, [ticketParam, detach]);

  // A ticket shown with a new reply: tell the server the customer has seen it (once per ticket).
  useEffect(() => {
    if (ticket && ticket.user_unread && !markedRef.current.has(ticket.id)) {
      markedRef.current.add(ticket.id);
      api.markRead(ticket.id).then(() => reload()).catch(() => {});
    }
  }, [ticket, reload]);

  // Open a stream: returns {seq, ctrl}; `live(seq)` says whether that stream may still touch the screen.
  function openStream() {
    detach();
    const seq = streamSeq.current;
    const ctrl = new AbortController();
    streamCtrl.current = ctrl;
    return { seq, ctrl };
  }
  const live = (seq) => seq === streamSeq.current;

  // Stream consumer shared by "send" and "re-attach": feeds the live steps and ends on done / error.
  async function consume(response, seq, ctrl) {
    let ended = null;
    await readSSE(response, (ev) => {
      if (!live(seq)) return;
      if (ev.event === "step") setTx((t) => ({ ...t, steps: [...t.steps, ev.data] }));
      else if (ev.event === "done") ended = { kind: "done", data: ev.data };
      else if (ev.event === "error") ended = { kind: "error", data: ev.data };
    }, { signal: ctrl.signal });
    return ended;
  }

  // How a stream ended. Guarded by `seq`: a late end of an older stream changes nothing (no state, no URL).
  function finish(ended, seq) {
    if (!live(seq)) return;
    streamCtrl.current = null;
    if (!ended) {   // the stream closed without an end event: the connection was cut
      setTx((t) => ({ ...t, status: "uncertain", reason: "disconnected", message: null }));
      return;
    }
    if (ended.kind === "error") {
      setPending(null);   // the server reported the end of THIS submission: the next message is a new one
      setTx((t) => ({ ...t, status: "failed", reason: null, message: ended.data.message || "The request failed." }));
      return;
    }
    setPending(null);
    setLastResult(ended.data);
    setTx({ status: "idle", reason: null, steps: [], message: null });
    setFresh(false);
    const tid = ended.data && ended.data.ticket_id;
    if (tid && tid !== ticketParam) {
      const next = new URLSearchParams(params);
      next.set("ticket", tid);
      setParams(next, { replace: true });   // the hook reloads the conversation for this ticket
    } else {
      reload();
    }
  }

  // POST one submission (new or the pending one) and follow its stream.
  async function submit(sub) {
    const { seq, ctrl } = openStream();
    setTx({ status: "sending", reason: null, steps: [], message: null });
    setLastResult(null);
    try {
      const body = { text: sub.text, client_id: sub.clientId };
      if (sub.ticketId) body.ticket_id = sub.ticketId;
      if (sub.aboutOrder) body.about_order = sub.aboutOrder;
      const response = await api.chatSend(body, ctrl.signal);
      if (!live(seq)) return;
      setDraft("");
      const ended = await consume(response, seq, ctrl);
      finish(ended, seq);
    } catch (err) {
      if (!live(seq) || (err && err.name === "AbortError")) return;
      streamCtrl.current = null;
      if (err instanceof ApiError && err.code === "not_logged_in") { expired(); return; }
      if (err instanceof ApiError && err.code === "busy_user") {
        setTx((t) => ({ ...t, status: "uncertain", reason: "busy_user", message: err.message }));   // keep `pending`
      } else if (err instanceof ApiError) {
        setPending(null);   // refused outright (CSRF, not yours, bad text, id reused): not a submission in flight
        setTx((t) => ({ ...t, status: "failed", reason: null, message: err.message }));
      } else {
        setTx((t) => ({ ...t, status: "uncertain", reason: "disconnected", message: null }));
      }
    }
  }

  // A NEW message: always a new request id, bound to the text / ticket / order of this moment.
  async function send(e) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy || uncertain) return;
    const sub = { clientId: newClientId(), text, ticketId: ticket ? ticket.id : null, aboutOrder: orderParam ? Number(orderParam) : null };
    setPending(sub);
    await submit(sub);
  }

  // The pending submission again, same id and same payload: the server answers with the same job (or runs it
  // once if it never arrived). Never used for new text.
  async function resendPending() {
    if (!pending || busy) return;
    await submit(pending);
  }

  // After a disconnect (or when the page loads while a job is running): ask the server, never resend.
  // One at a time: a second click while a check runs does nothing.
  async function checkStatus() {
    if (recovering.current || busy) return;
    recovering.current = true;
    const { seq, ctrl } = openStream();
    recovering.current = true;   // openStream's detach cleared it
    try {
      const { job: current } = await api.chatJob(ctrl.signal);
      if (!live(seq)) return;
      if (!current) { setPending(null); setTx({ status: "idle", reason: null, steps: [], message: null }); reload(); return; }
      if (current.status === "running") {
        setTx({ status: "attached", reason: null, steps: [], message: null });
        const response = await api.chatJobStream(ctrl.signal);
        if (!live(seq)) return;
        const ended = await consume(response, seq, ctrl);   // the stream replays the steps from the start
        finish(ended, seq);
        return;
      }
      if (current.status === "failed") {
        setPending(null);
        setTx({ status: "failed", reason: null, steps: current.steps || [], message: current.error && current.error.message });
        reload();
        return;
      }
      finish({ kind: "done", data: current.result }, seq);
    } catch (err) {
      if (!live(seq) || (err && err.name === "AbortError")) return;
      if (err instanceof ApiError && err.code === "not_logged_in") { expired(); return; }
      setTx((t) => ({ ...t, status: "uncertain", reason: "disconnected" }));
    } finally {
      if (live(seq)) recovering.current = false;
    }
  }

  function resetTx() {
    setTx({ status: "idle", reason: null, steps: [], message: null });
  }

  function newChat() {
    detach();
    setFresh(true);
    setLastResult(null);
    setPending(null);
    resetTx();
    setParams(new URLSearchParams(), { replace: true });
    if (inputRef.current) inputRef.current.focus();
  }

  function openTicket(id) {
    detach();
    setFresh(false);
    setLastResult(null);
    const next = new URLSearchParams();
    next.set("ticket", id);
    setParams(next);
  }

  if (error) {
    return (
      <div className="stack">
        <div><Link to="/shop/orders" className="btn btn-sm"><Icon name="back" size={14} />My orders</Link></div>
        {error.code === "not_found"
          ? <div className="panel"><Empty icon="search" title={`Ticket ${ticketParam} is not one of your conversations`}><button type="button" className="btn btn-sm" onClick={newChat}>Start a new chat</button></Empty></div>
          : <ApiErrorView error={error} onRetry={reload} />}
      </div>
    );
  }
  if (loading && !convo) return <Loading text="Loading your conversation…" />;

  const runningOnServer = job && job.status === "running" && tx.status === "idle";
  const outcome = lastResult && lastResult.outcome;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Help chat</h1>
          <p className="sub">Ask us about an order, a delivery, a refund or a return · CallVerse answers here</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={newChat} disabled={busy}><Icon name="chat" size={14} />New chat</button>
      </div>

      <div className="chat">
        <section className="panel stack" aria-label="Conversation">
          <div className="chat-head">
            {ticket ? (
              <span className="row">Ticket <strong className="mono">{ticket.id}</strong> <span className="badge badge-neutral">{String(ticket.status)}</span></span>
            ) : (
              <span className="muted">New conversation</span>
            )}
            {orderParam && (
              <span className="context-chip"><Icon name="package" size={14} />About order {orderParam}
                <button type="button" className="btn btn-ghost btn-sm" aria-label="Remove the order context" onClick={() => { const n = new URLSearchParams(params); n.delete("order"); setParams(n, { replace: true }); }}><Icon name="x" size={12} /></button>
              </span>
            )}
          </div>

          {unread.filter((u) => !ticket || u.id !== ticket.id).length > 0 && (
            <div className="notice-list" role="status">
              {unread.filter((u) => !ticket || u.id !== ticket.id).map((u) => (
                <div className="alert" key={u.id}>
                  <Icon name="chat" />
                  <span className="small">New reply on <strong className="mono">{u.id}</strong></span>
                  <div className="actions"><button type="button" className="btn btn-sm" onClick={() => openTicket(u.id)}>Open</button></div>
                </div>
              ))}
            </div>
          )}

          <div className="messages" aria-live="polite" aria-relevant="additions">
            {messages.length === 0 && !busy && <p className="muted small">No messages yet. Type below to start.</p>}
            {messages.map((m) => (
              <div key={m.id} className={`msg ${m.sender === "user" ? "user" : m.sender === "assistant" ? "assistant" : "system"}`}>
                {m.text}
                <span className="stamp">{m.sender}{m.at_real ? ` · ${m.at_real}` : ""}{m.sender === "assistant" && m.seconds != null ? ` · ${Number(m.seconds).toFixed(1)} s` : ""}</span>
              </div>
            ))}
            {busy && (
              <div className="msg assistant" role="status" aria-label="CallVerse is working">
                <span className="row"><span className="spinner" aria-hidden="true" />CallVerse is working on your message…</span>
                <ol className="steps-live" style={{ marginTop: "var(--cv-s2)" }}>
                  {tx.steps.map((s, i) => <li key={i} className={i === tx.steps.length - 1 ? "now" : ""}><Icon name={i === tx.steps.length - 1 ? "dot" : "check"} size={14} />{String(s.text)}</li>)}
                  {tx.steps.length === 0 && <li className="now"><Icon name="dot" size={14} />Sending…</li>}
                </ol>
              </div>
            )}
          </div>

          {outcome && (
            <div className={`alert ${outcome === BUSY_OUTCOME ? "alert-warn" : ""}`} role="status">
              <Icon name={outcome === BUSY_OUTCOME ? "clock" : "info"} />
              <span className="small">
                {outcome === BUSY_OUTCOME
                  ? "Our assistant is busy right now (its daily quota or its model is not available). Your message is saved; please try again later."
                  : <>Outcome: <strong>{words(outcome)}</strong>{lastResult.status ? ` · ticket ${words(lastResult.status)}` : ""}</>}
              </span>
            </div>
          )}

          {runningOnServer && (
            <div className="alert alert-warn" role="status">
              <Icon name="clock" />
              <div className="stack" style={{ gap: "var(--cv-s1)" }}>
                <strong>CallVerse is still working on your last message</strong>
                <span className="small">Started {job.started_at}. The reply will appear here when it is saved; nothing needs to be sent again.</span>
              </div>
              <div className="actions"><button type="button" className="btn btn-sm" onClick={checkStatus}><Icon name="refresh" size={14} />Follow progress</button></div>
            </div>
          )}

          {uncertain && (
            <div className="alert alert-danger" role="alert">
              <Icon name="alert" />
              <div className="stack" style={{ gap: "var(--cv-s1)" }}>
                <strong>{tx.reason === "busy_user" ? "A previous message is still being processed" : "Connection lost"}</strong>
                <span className="small">
                  {tx.reason === "busy_user"
                    ? `${tx.message || ""} Check its status below; your new message is kept and NOT sent until you choose to.`
                    : "The link to CallVerse dropped while it was working. That does not cancel your request: it may still be running and its reply will be saved. Your message is NOT sent again unless you choose to resend it."}
                </span>
                {pending && <span className="muted xs">Waiting submission: “{pending.text.length > 60 ? `${pending.text.slice(0, 60)}…` : pending.text}”</span>}
              </div>
              <div className="actions row">
                <button type="button" className="btn btn-sm" onClick={checkStatus}><Icon name="refresh" size={14} />Check status</button>
                {pending && tx.reason === "disconnected" && <button type="button" className="btn btn-ghost btn-sm" onClick={resendPending}>Resend the same message</button>}
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setPending(null); resetTx(); reload(); }}>Discard it</button>
              </div>
            </div>
          )}

          {tx.status === "failed" && (
            <div className="alert alert-danger" role="alert">
              <Icon name="alert" />
              <div className="stack" style={{ gap: "var(--cv-s1)" }}>
                <strong>The request failed</strong>
                <span className="small">{tx.message || "CallVerse could not handle the message."}</span>
              </div>
              <div className="actions"><button type="button" className="btn btn-ghost btn-sm" aria-label="Dismiss" onClick={resetTx}><Icon name="x" size={14} /></button></div>
            </div>
          )}

          <form className="chat-form" onSubmit={send}>
            <div className="field">
              <label htmlFor="chat-text">Your message</label>
              <textarea id="chat-text" ref={inputRef} className="input" value={draft} onChange={(e) => setDraft(e.target.value)}
                placeholder={orderParam ? `About order ${orderParam}…` : "Type your message…"} disabled={busy} maxLength={2000}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!busy && !uncertain && draft.trim()) send(e); } }} />
              <span className="muted xs">Enter sends · Shift+Enter for a new line</span>
            </div>
            <div className="actions">
              <button type="submit" className="btn btn-primary" disabled={busy || uncertain || !draft.trim() || !!runningOnServer}>
                {busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="chat" size={16} />}{busy ? "Sending…" : "Send"}
              </button>
              {ticket && <span className="muted xs">Replies to ticket {ticket.id}</span>}
              {uncertain && <span className="muted xs">Send is paused until the previous submission is settled (Check status above).</span>}
            </div>
          </form>
        </section>

        <aside className="panel stack" aria-label="About this chat">
          <h2>How it works</h2>
          <p className="small muted">Each message goes to the CallVerse center. You see what it is doing (reading, checking your order, checking the rules, writing) and then its reply. One conversation = one ticket; a solved ticket can be continued for 3 days, then a new one starts.</p>
          {ticket && (
            <dl className="kv">
              <dt>Ticket</dt><dd className="mono">{ticket.id}</dd>
              <dt>Status</dt><dd>{String(ticket.status)}</dd>
              {ticket.main_reason && <><dt>Reason</dt><dd>{words(ticket.main_reason)}</dd></>}
              <dt>Opened</dt><dd className="tabular">{ticket.created_real || "—"}</dd>
            </dl>
          )}
          <p className="small muted">A refund above the limit goes to the ShopNova finance team; their decision arrives here as a new reply.</p>
          <Link to="/shop/orders" className="btn btn-sm"><Icon name="bag" size={14} />My orders</Link>
        </aside>
      </div>
    </>
  );
}
