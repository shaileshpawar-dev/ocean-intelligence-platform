import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// The SPA is built into backend/app/static/app and mounted by FastAPI, so the
// runtime container stays pure Python -- Node is only needed at build time.
export default defineConfig({
  plugins: [react()],
  base: "/app/",
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: {
    outDir: path.resolve(__dirname, "../backend/app/static/app"),
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        // Split the two heaviest libraries so the shell paints before the
        // map and chart code arrives.
        manualChunks: {
          map: ["leaflet", "react-leaflet"],
          charts: ["recharts"],
        },
      },
    },
  },
  server: {
    port: 5173,
    // Dev server proxies the API so there is no CORS config in development.
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
