// Regression test of logout: when the server does not confirm the logout, the user stays logged in, sees the
// failure and can retry. (Clearing React state alone would leave the HttpOnly cookie and the server session.)
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider, useAuth } from "../auth.jsx";
import Shell from "../components/Shell.jsx";
import { SUPERVISOR, installFakeFetch } from "./fakeApi.js";

function Page() {
  const { session } = useAuth();
  return <p>page for {session ? session.username : "nobody"}</p>;
}

function renderShell() {
  return render(
    <MemoryRouter initialEntries={["/tickets"]}>
      <AuthProvider>
        <Routes>
          <Route element={<Shell />}><Route path="/tickets" element={<Page />} /></Route>
          <Route path="/console/login" element={<p>login page</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("Logout", () => {
  it("reports a failed logout and keeps the session until the server confirms", async () => {
    const net = installFakeFetch();
    renderShell();
    await act(async () => { (await net.waitFor("/api/auth/session")).respond(200, { session: SUPERVISOR }); });
    expect(screen.getByText("page for supervisor")).toBeInTheDocument();

    await act(async () => { screen.getByRole("button", { name: /log out/i }).click(); });
    const req = await net.waitFor("/api/auth/logout");
    expect(req.options.method).toBe("POST");
    expect(req.options.headers["X-Requested-With"]).toBe("CallVerse");
    await act(async () => { req.respond(500, { error: "boom", message: "Server error." }); });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Log out failed");
    expect(alert).toHaveTextContent("You are still logged in");
    expect(screen.getByText("page for supervisor")).toBeInTheDocument();   // not sent to /login, session kept
    expect(screen.queryByText("login page")).toBeNull();

    // Retry: this time the server confirms.
    await act(async () => { screen.getByRole("button", { name: /retry/i }).click(); });
    const again = await net.waitFor("/api/auth/logout", { index: 1 });
    await act(async () => { again.respond(200, { ok: true }); });
    expect(screen.getByText("login page")).toBeInTheDocument();
  });

  it("treats a 401 on logout as already logged out", async () => {
    const net = installFakeFetch();
    renderShell();
    await act(async () => { (await net.waitFor("/api/auth/session")).respond(200, { session: SUPERVISOR }); });
    await act(async () => { screen.getByRole("button", { name: /log out/i }).click(); });
    const req = await net.waitFor("/api/auth/logout");
    await act(async () => { req.respond(401, { error: "not_logged_in", message: "Please log in." }); });
    expect(screen.getByText("login page")).toBeInTheDocument();
  });
});
