import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// pnpm 的真实路径形如 .pnpm/rc-table@x/node_modules/rc-table/es/...,
// 因此只按最后一个 node_modules/ 之后的包名判定, 不做整串包含匹配。
// antd 独占的传递依赖也一起归到 antd 块: 它们不被仓库其他依赖使用,
// 留在 vendor 只会白白吃掉 vendor 的同步 chunk 预算。
const ANTD_PACKAGE_PATTERN =
  /^(antd|@ant-design\/[^/]+|rc-[^/]+|@rc-component\/[^/]+|@babel\/runtime|@emotion\/[^/]+|@ctrl\/tinycolor|classnames|dayjs|throttle-debounce|scroll-into-view-if-needed|compute-scroll-into-view|copy-to-clipboard|toggle-selection|resize-observer-polyfill|json2mq|string-convert|stylis)(\/|$)/;

function isAntdModule(id: string): boolean {
  const marker = "/node_modules/";
  const index = id.lastIndexOf(marker);
  if (index === -1) {
    return false;
  }
  return ANTD_PACKAGE_PATTERN.test(id.slice(index + marker.length));
}

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
            // antd 及其 rc-* 运行时体积远大于其余依赖, 单独成块,
            // 否则 vendor 会一次性突破同步 chunk 预算。
            return isAntdModule(id) ? "antd" : "vendor";
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
