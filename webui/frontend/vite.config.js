// Vite config: dev server on 127.0.0.1:5173, and every /api request is proxied to the FastAPI on 127.0.0.1:8610.
// Same origin for the browser (http://127.0.0.1:5173), so the HttpOnly session cookie just works and no CORS is
// needed. `npm run build` writes webui/frontend/dist (static files; serve them the same way behind /api in a
// later step).
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API = process.env.CALLVERSE_WEBUI_API || "http://127.0.0.1:8610";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: API, changeOrigin: false } },
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: API, changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false },
  // vitest: screen tests in src/test, in a jsdom browser, with a fake fetch (no server).
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.js"], globals: false },
});
