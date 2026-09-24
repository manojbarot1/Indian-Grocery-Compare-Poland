import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // The API is same-origin in production; in dev we proxy so the browser
    // never needs CORS and the app can use plain relative /api URLs.
    proxy: {
      "/api": { target: process.env.VITE_API_TARGET ?? "http://localhost:8090", changeOrigin: true },
    },
  },
});
