import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/query": {
        target: "http://localhost:8000",
        changeOrigin: true,
        bypass(req) {
          // GET /query is a React Router page — only proxy POST (pipeline API)
          if (req.method === "GET") return "/index.html";
          return null;
        },
      },
      "/schema": {
        target: "http://localhost:8000",
        changeOrigin: true,
        bypass(req) {
          // Browser page navigations send text/html Accept — serve SPA
          // fetch() calls from JS send *//* — proxy to backend for JSON
          if (req.headers.accept?.includes("text/html")) return "/index.html";
          return null;
        },
      },
      "/audit": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/setup": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/suggest": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
