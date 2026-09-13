import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// pnpm 的真实路径形如 .pnpm/rc-table@x/node_modules/rc-table/es/...,
// 因此只按最后一个 node_modules/ 之后的包名判定, 不做整串包含匹配。
// antd 独占的传递依赖也一起归到 antd 块: 它们不被仓库其他依赖使用,
// 留在 vendor 只会白白吃掉 vendor 的同步 chunk 预算。
const ANTD_PACKAGE_PATTERN =
  /^(antd|@ant-design\/[^/]+|rc-[^/]+|@rc-component\/[^/]+|@babel\/runtime|@emotion\/[^/]+|@ctrl\/tinycolor|classnames|dayjs|throttle-debounce|scroll-into-view-if-needed|compute-scroll-into-view|copy-to-clipboard|toggle-selection|resize-observer-polyfill|json2mq|string-convert|stylis)(\/|$)/;

const ANTD_PICKER_PACKAGE_PATTERN = /^(rc-picker|dayjs)(\/|$)/;
const ANTD_PICKER_COMPONENT_PATTERN = /^antd\/(es|lib)\/(date-picker|calendar|time-picker)(\/|$)/;

function packagePathAfterNodeModules(id: string): string | null {
  const marker = "/node_modules/";
  const index = id.lastIndexOf(marker);
  if (index === -1) {
    return null;
  }
  return id.slice(index + marker.length);
}

function isAntdPickerModule(id: string): boolean {
  const rest = packagePathAfterNodeModules(id);
  if (rest === null) {
    return false;
  }
  // ConfigProvider 同步引入 antd locale, 后者再引入 date-picker / calendar /
  // time-picker / rc-picker 的文案文件。这些文案必须留在同步 antd chunk,
  // 否则整个 antd-picker 会被一并同步拉进来。dayjs 的 locale 只被选择器实现引用,
  // 跟选择器走。
  if (!rest.startsWith("dayjs/") && /\/locale(\/|$)/.test(rest)) {
    return false;
  }
  return ANTD_PICKER_PACKAGE_PATTERN.test(rest) || ANTD_PICKER_COMPONENT_PATTERN.test(rest);
}

function isAntdModule(id: string): boolean {
  const rest = packagePathAfterNodeModules(id);
  if (rest === null) {
    return false;
  }
  return ANTD_PACKAGE_PATTERN.test(rest);
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
            // DatePicker / Calendar / TimePicker / rc-picker / dayjs 只给日期范围控件用,
            // 单独成 antd-picker, 由 React.lazy 的 DateRangeControl 异步拉取;
            // 必须先于 antd 判定, 否则会回到同步 antd chunk。
            if (isAntdPickerModule(id)) {
              return "antd-picker";
            }
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
