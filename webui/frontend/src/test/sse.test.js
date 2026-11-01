// The SSE reader: frames split across chunks, several frames in one chunk, CRLF, comments, a final frame
// without its blank line, and a dropped connection.
import { describe, expect, it } from "vitest";
import { parseFrame, readSSE } from "../sse.js";

function streamOf(chunks, { cut = false } = {}) {
  const enc = new TextEncoder();
  // the chunks arrive first, then the connection drops (a network does not lose what it already delivered)
  return { body: new ReadableStream({ start(c) { chunks.forEach((x) => c.enqueue(enc.encode(x))); setTimeout(() => { if (cut) c.error(new TypeError("net")); else c.close(); }, 0); } }) };
}

describe("sse", () => {
  it("parses a frame with event, multi-line data and a comment", () => {
    expect(parseFrame(': hi\nevent: step\ndata: {"a":\ndata: 1}')).toEqual({ event: "step", data: { a: 1 } });
    expect(parseFrame("data: plain")).toEqual({ event: "message", data: "plain" });
    expect(parseFrame(": only a comment")).toBeNull();
  });

  it("reassembles frames split across chunks and splits several frames in one chunk", async () => {
    const got = [];
    await readSSE(streamOf([
      ": connected\n\nevent: job\ndata: {\"job_id\": \"j1\"}\n\nevent: st",   // frame 2 cut mid-event-name
      "ep\ndata: {\"text\": \"Reading yo",                                  // data cut mid-string
      "ur message…\"}\n\n: ping\n\nevent: step\r\ndata: {\"text\": \"Checking\"}\r\n\r\nevent: done\ndata: {\"outcome\": \"approve\"}",
    ]), (e) => got.push(e));
    expect(got).toEqual([
      { event: "job", data: { job_id: "j1" } },
      { event: "step", data: { text: "Reading your message…" } },
      { event: "step", data: { text: "Checking" } },
      { event: "done", data: { outcome: "approve" } },
    ]);
  });

  it("keeps the events before a dropped connection and rejects", async () => {
    const got = [];
    await expect(readSSE(streamOf(["event: step\ndata: {\"text\": \"one\"}\n\n"], { cut: true }), (e) => got.push(e))).rejects.toThrow();
    expect(got).toEqual([{ event: "step", data: { text: "one" } }]);
  });
});
