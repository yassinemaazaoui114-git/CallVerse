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

describe("sse: CRLF and detach", () => {
  const TEXT = "event: step\r\ndata: {\"text\": \"one\"}\r\n\r\nevent: step\r\ndata: {\"text\": \"two\"}\r\n\r\nevent: done\r\ndata: {\"ok\": 1}\r\n\r\n";
  const EXPECTED = [{ event: "step", data: { text: "one" } }, { event: "step", data: { text: "two" } }, { event: "done", data: { ok: 1 } }];

  it("parses CRLF frames split at every possible chunk boundary (CR and LF in different chunks too)", async () => {
    for (let cut = 1; cut < TEXT.length; cut++) {
      const got = [];
      await readSSE(streamOf([TEXT.slice(0, cut), TEXT.slice(cut)]), (e) => got.push(e));
      expect(got, `cut at ${cut}`).toEqual(EXPECTED);
    }
  });

  it("also handles three chunks and lone CR line ends", async () => {
    const got = [];
    await readSSE(streamOf(["event: step\r", "\ndata: {\"a\":1}\r", "\n\r\nevent: done\rdata: {\"b\":2}\r\r"]), (e) => got.push(e));
    expect(got).toEqual([{ event: "step", data: { a: 1 } }, { event: "done", data: { b: 2 } }]);
  });

  it("an abort cancels the reader, releases the body and rejects with AbortError", async () => {
    const enc = new TextEncoder();
    let controller;
    const body = new ReadableStream({ start(c) { controller = c; c.enqueue(enc.encode("event: step\ndata: {\"x\":1}\n\n")); } });
    const response = { body };
    const ctrl = new AbortController();
    const got = [];
    const run = readSSE(response, (e) => got.push(e), { signal: ctrl.signal });
    await new Promise((r) => setTimeout(r, 10));
    ctrl.abort();
    await expect(run).rejects.toMatchObject({ name: "AbortError" });
    expect(got).toEqual([{ event: "step", data: { x: 1 } }]);
    expect(body.locked).toBe(false);
    expect(() => controller.enqueue(enc.encode("x"))).toThrow();   // the stream was cancelled
  });
});
