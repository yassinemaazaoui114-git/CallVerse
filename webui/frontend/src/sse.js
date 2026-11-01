// A small Server-Sent Events reader for a `fetch` response (a native EventSource cannot POST).
//
// SSE frames are separated by a blank line; a frame has `event:` and one or more `data:` lines; lines that
// start with ":" are comments (the API sends ": ping" to keep an idle connection alive). The network delivers
// the stream in arbitrary chunks, so the bytes are decoded with a streaming TextDecoder and kept in a buffer
// until a complete frame (ending in "\n\n") is there; a frame may arrive split over several chunks or several
// frames in one chunk. CRLF is accepted. `data` is parsed as JSON when it is JSON, else kept as text.
//
//   await readSSE(response, (event) => { ... });   // event = {event, data}
// Rejects when the connection drops mid-stream (the caller shows "disconnected"; it never resends).

export function parseFrame(frame) {
  let event = null;
  const data = [];
  for (const raw of frame.split("\n")) {
    const line = raw.replace(/\r$/, "");
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

export async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = () => {
    let at;
    while ((at = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, at);
      buffer = buffer.slice(at + 2);
      const ev = parseFrame(frame);
      if (ev) onEvent(ev);
    }
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    flush();
  }
  buffer += decoder.decode();
  flush();
  const last = parseFrame(buffer);   // a final frame without its trailing blank line
  if (last) onEvent(last);
}
