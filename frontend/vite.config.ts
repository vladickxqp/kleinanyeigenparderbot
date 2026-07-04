import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development the admin panel proxies /api and /metrics to the FastAPI
// backend so there are no CORS issues locally.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/metrics": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
