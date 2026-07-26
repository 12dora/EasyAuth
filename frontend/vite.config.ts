import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/easyauth/frontend/" : "/",
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
      input: "/src/main.tsx",
      output: {
        manualChunks(id) {
          if (id.includes("/node_modules/")) {
            return "vendor";
          }
          if (id.includes("/src/i18n/")) {
            return "i18n";
          }
        }
      }
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["e2e/**", "e2e-fullstack/**", "node_modules/**", "dist/**"]
  }
}));
