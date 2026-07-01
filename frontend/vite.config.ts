import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/console/api": "http://127.0.0.1:8000",
      "/portal/api": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000"
    }
  },
  build: {
    manifest: true,
    outDir: "../src/easyauth/static/easyauth/frontend",
    emptyOutDir: true,
    rollupOptions: {
      input: "/src/main.tsx"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"]
  }
});
