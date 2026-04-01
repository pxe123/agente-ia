import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Servimos o index no "/" via Flask, mas os assets ficam em "/landing/...".
  base: "/landing/",
  build: {
    outDir: "../panel/static/landing",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:5000", changeOrigin: true },
    },
  },
});

