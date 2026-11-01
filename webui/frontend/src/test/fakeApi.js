// A fake `fetch` for the screen tests. Every call is recorded with its URL and answered by a "deferred" the
// test resolves (or rejects) itself, in any order, so a test can make an old answer arrive after a new one.
//
//   const net = installFakeFetch();
//   render(...);
//   const first = await net.waitFor(LIST);   // the pending call whose URL matches (string part or RegExp)
//   first.respond(200, {...});   or   first.fail();   (network error)
import { vi } from "vitest";

// The Live tickets list call: /api/console/tickets or /api/console/tickets?... (not .../filters, not .../T-0001)
export const LIST = /\/api\/console\/tickets(\?|$)/;

export function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

export function installFakeFetch() {
  const calls = [];   // {url, options, respond, fail, done}
  const fetchMock = vi.fn((url, options = {}) => new Promise((resolve, reject) => {
    const call = {
      url: String(url), options, done: false,
      respond(status, body) { if (!call.done) { call.done = true; resolve(jsonResponse(status, body)); } },
      fail() { if (!call.done) { call.done = true; reject(new TypeError("Failed to fetch")); } },
    };
    // Honour cancellation like a browser would: an aborted request rejects with an AbortError.
    if (options.signal) {
      options.signal.addEventListener("abort", () => {
        if (!call.done) { call.done = true; call.aborted = true; reject(Object.assign(new Error("aborted"), { name: "AbortError" })); }
      });
    }
    calls.push(call);
  }));
  vi.stubGlobal("fetch", fetchMock);
  // `part` is a string the URL contains, or a RegExp the URL matches.
  const matches = (part) => (c) => (part instanceof RegExp ? part.test(c.url) : c.url.includes(part));
  return {
    calls,
    fetchMock,
    pending: (part) => calls.filter((c) => !c.done && matches(part)(c)),
    all: (part) => calls.filter(matches(part)),
    async waitFor(part, { index = 0 } = {}) {
      for (let i = 0; i < 100; i++) {
        const found = calls.filter(matches(part));
        if (found.length > index) return found[index];
        await new Promise((r) => setTimeout(r, 5));
      }
      throw new Error(`no fetch call containing "${part}" (index ${index}); calls: ${calls.map((c) => c.url).join(", ")}`);
    },
  };
}

// Answers the "who is logged in" call the AuthProvider makes on start.
export const SUPERVISOR = { username: "supervisor", name: "CallVerse Supervisor", role: "supervisor", company: null };

export function ticketsBody(ids, extra = {}) {
  return {
    tickets: ids.map((id) => ({ id, company: "shopnova", user: "Sara Ben Ali (1)", reason: "refund_request",
                                priority: "high", status: "Solved", "lead agent": "B", age: "1 min" })),
    count: ids.length, has_tickets: true, no_tickets_message: "No tickets yet", statuses: [],
    server_time: "2026-11-01T12:00:00", ...extra,
  };
}

export const FILTER_VALUES = { company: ["atlas", "shopnova"], status: ["Open", "Solved"], priority: ["high", "low"], agent: ["A", "B"] };
