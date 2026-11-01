// vitest setup: jest-dom matchers, and a fake `fetch` the tests control call by call (see fakeApi.js).
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
