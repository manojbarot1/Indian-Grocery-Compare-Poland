import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Hosts Vite will answer to.
 *
 * Vite rejects requests whose Host header it does not recognise, which is what
 * blocks a Cloudflare tunnel: the browser asks for desiprice.07062006.xyz but
 * Vite only expects localhost. A leading dot allows every subdomain of a
 * domain, so the tunnel keeps working if its hostname changes.
 *
 * Override with VITE_ALLOWED_HOSTS (comma-separated) rather than editing this
 * file, so the repo is not pinned to one person's domain.
 */
const allowedHosts = (process.env.VITE_ALLOWED_HOSTS ?? ".07062006.xyz")
  .split(",")
  .map((host) => host.trim())
  .filter(Boolean);

// Served through a tunnel, the HMR socket must be told to use wss on 443 —
// it cannot infer that from a dev server sitting behind TLS termination.
const tunnelHost = process.env.VITE_TUNNEL_HOST;

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts,
    hmr: tunnelHost
      ? { protocol: "wss", host: tunnelHost, clientPort: 443 }
      : undefined,
    // The API is same-origin in production; in dev we proxy so the browser
    // never needs CORS and the app can use plain relative /api URLs.
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8090",
        changeOrigin: true,
      },
    },
  },
});
