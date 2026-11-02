// A small Server-Sent Events reader for a `fetch` response (a native EventSource cannot POST).
//
// SSE frames are separated by a blank line; a frame has `event:` and one or more `data:` lines; lines that
// start with ":" are comments (the API sends ": ping" to keep an idle connection alive). The network delivers
// the stream in arbitrary chunks, so the bytes are decoded with a streaming TextDecoder and kept in a buffer
// until a complete frame is there; a frame may arrive split over several chunks, or several frames in one
// chunk. Line ends may be LF, CRLF or CR, and a CRLF may itself be split between two chunks (the CR at the end
// of one chunk, the LF at the start of the next): a trailing CR is held back until the next chunk says what
// follows it. `data` is parsed as JSON when it is JSON, else kept as text. Every event is delivered on its own
// (progress `step` events and the final `done` / `error` are never merged).
//
//   await readSSE(response, (event) => { ... }, { signal });   // event = {event, data}
// Rejects when the connection drops mid-stream (the caller shows "disconnected"; it never resends). An abort
// through `signal` cancels the reader (the caller stops listening; the server's job is NOT cancelled by that)
// and rejects with an AbortError. The reader's lock on the body is always released at the end.

export function parseFrame(frame) {
  let event = null;
  const data = [];
  for (const line of frame.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (event === null && data.length === 0) return null;
  const text = data.join("\n");
  let parsed = text;
  try { parsed = JSON.parse(text); } catch (e) { /* plain text data */ }
  return { event: event || "message", data: parsed };
}

// Turn CRLF and lone CR into LF. A CR at the very end is kept as is (its LF may be in the next chunk).
function normalize(text) {
  const keep = text.endsWith("\r") ? "\r" : "";
  const body = keep ? text.slice(0, -1) : text;
  return body.replace(/\r\n/g, "\n").replace(/\r/g, "\n") + keep;
}

export async function readSSE(response, onEvent, { signal } = {}) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const abortError = () => Object.assign(new Error("aborted"), { name: "AbortError" });
  const onAbort = () => { reader.cancel().catch(() => {}); };
  if (signal) {
    if (signal.aborted) { reader.releaseLock(); throw abortError(); }
    signal.addEventListener("abort", onAbort, { once: true });
  }
  const flush = () => {
    let at;
    while ((at = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, at);
      buffer = buffer.slice(at + 2);
      const ev = parseFrame(frame);
      if (ev) onEvent(ev);
    }
  };
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (signal && signal.aborted) throw abortError();
      buffer = normalize(buffer + decoder.decode(value, { stream: true }));
      flush();
    }
    if (signal && signal.aborted) throw abortError();
    buffer = normalize(buffer + decoder.decode()).replace(/\r$/, "\n");
    flush();
    const last = parseFrame(buffer);   // a final frame without its trailing blank line
    if (last) onEvent(last);
  } finally {
    if (signal) signal.removeEventListener("abort", onAbort);
    try { reader.releaseLock(); } catch (e) { /* already released by cancel */ }
  }
}
