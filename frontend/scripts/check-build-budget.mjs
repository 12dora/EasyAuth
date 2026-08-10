import { gzipSync } from "node:zlib";
import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_MANIFEST = "../../src/easyauth/static/easyauth/frontend/.vite/manifest.json";
const DEFAULT_ASSETS_DIR = "../../src/easyauth/static/easyauth/frontend";

const DEFAULT_BUDGETS = {
  initialEntryRawBytes: 80 * 1024,
  initialEntryGzipBytes: 30 * 1024,
  synchronousChunkRawBytes: 360 * 1024,
  synchronousChunkGzipBytes: 110 * 1024,
  asyncChunkRawBytes: 140 * 1024,
  asyncChunkGzipBytes: 40 * 1024,
  // 数据交接 v2 门户/共享组件落地后总量上调；见 docs/operations/frontend-build-budget.md
  totalJavaScriptRawBytes: 960 * 1024,
};

const REQUIRED_DYNAMIC_ROUTE_KEYS = [
  "src/pages/console/ApprovalInstancesPage.tsx",
  "src/pages/console/ApprovalTemplatesPage.tsx",
  "src/pages/console/ConsoleAppList.tsx",
  "src/pages/console/ConsoleAppWorkspace.tsx",
  "src/pages/console/ConsoleSettingsPage.tsx",
  "src/pages/console/ConsoleTeamDetail.tsx",
  "src/pages/console/ConsoleTeamList.tsx",
  "src/pages/console/OperationsPage.tsx",
  "src/pages/console/lifecycle/ConsolePeopleList.tsx",
  "src/pages/console/lifecycle/HandoverTaskDetail.tsx",
  "src/pages/console/lifecycle/HandoverTaskList.tsx",
  "src/pages/console/lifecycle/OnboardingPage.tsx",
  "src/pages/console/onboarding/AppOnboardingWizard.tsx",
  "src/pages/portal/PortalPage.tsx",
  "src/pages/portal/PortalHandoverList.tsx",
  "src/pages/portal/PortalHandoverDetail.tsx",
];

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const args = parseArgs(process.argv.slice(2));
const manifestPath = path.resolve(scriptDir, args.manifest ?? DEFAULT_MANIFEST);
const assetsDir = path.resolve(scriptDir, args.assetsDir ?? DEFAULT_ASSETS_DIR);
const budgets = {
  ...DEFAULT_BUDGETS,
  ...(args.budgetFile ? JSON.parse(readFileSync(path.resolve(process.cwd(), args.budgetFile), "utf8")) : {}),
};

if (!existsSync(manifestPath)) {
  fail([`未找到 Vite manifest: ${manifestPath}`]);
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const entries = Object.values(manifest);
const mainEntry = entries.find((entry) => entry.isEntry);

if (!mainEntry) {
  fail(["Vite manifest 没有标记 isEntry 的入口。"]);
}

const javascriptAssets = collectJavaScriptAssets(entries);
const failures = [];
const mainStats = assetStats(mainEntry.file);
const asyncRouteChunks = [...new Set(entries.filter((entry) => entry.isDynamicEntry).map((entry) => entry.file))];
const synchronousChunks = [...new Set((mainEntry.imports ?? []).map((key) => manifest[key]?.file).filter(Boolean))];
const totalRawBytes = javascriptAssets.reduce((sum, file) => sum + statSync(path.join(assetsDir, file)).size, 0);

checkBudget(failures, "入口 main 原始体积", mainStats.rawBytes, budgets.initialEntryRawBytes);
checkBudget(failures, "入口 main gzip 体积", mainStats.gzipBytes, budgets.initialEntryGzipBytes);
checkBudget(failures, "JavaScript 总原始体积", totalRawBytes, budgets.totalJavaScriptRawBytes);

for (const file of synchronousChunks) {
  const stats = assetStats(file);
  checkBudget(failures, `同步 chunk 原始体积 ${file}`, stats.rawBytes, budgets.synchronousChunkRawBytes);
  checkBudget(failures, `同步 chunk gzip 体积 ${file}`, stats.gzipBytes, budgets.synchronousChunkGzipBytes);
}

for (const file of asyncRouteChunks) {
  const stats = assetStats(file);
  checkBudget(failures, `异步 chunk 原始体积 ${file}`, stats.rawBytes, budgets.asyncChunkRawBytes);
  checkBudget(failures, `异步 chunk gzip 体积 ${file}`, stats.gzipBytes, budgets.asyncChunkGzipBytes);
}

const entryDynamicImports = new Set(mainEntry.dynamicImports ?? []);
for (const routeKey of REQUIRED_DYNAMIC_ROUTE_KEYS) {
  const routeEntry = manifest[routeKey];
  if (!routeEntry) {
    failures.push(`缺少预期的路由 manifest key: ${routeKey}`);
    continue;
  }
  if (routeEntry.isDynamicEntry !== true) {
    failures.push(`路由不是异步入口: ${routeKey}`);
  }
  if (!entryDynamicImports.has(routeKey)) {
    failures.push(`入口未动态导入路由: ${routeKey}`);
  }
  if (!routeEntry.file?.endsWith(".js")) {
    failures.push(`路由缺少 JavaScript chunk: ${routeKey}`);
  }
}

if (failures.length > 0) {
  fail(failures);
}

console.log(
  [
    "前端构建预算通过",
    `入口: ${mainEntry.file} ${formatBytes(mainStats.rawBytes)} / gzip ${formatBytes(mainStats.gzipBytes)}`,
    `同步 chunk: ${synchronousChunks.length}`,
    `异步路由 chunk: ${asyncRouteChunks.length}`,
    `JavaScript 总量: ${formatBytes(totalRawBytes)}`,
  ].join("\n"),
);

function parseArgs(values) {
  const parsed = {};
  for (let index = 0; index < values.length; index += 1) {
    const name = values[index];
    const value = values[index + 1];
    if (!name.startsWith("--") || !value) {
      fail([`无法解析参数: ${name}`]);
    }
    if (name === "--manifest") {
      parsed.manifest = value;
    } else if (name === "--assets-dir") {
      parsed.assetsDir = value;
    } else if (name === "--budget-file") {
      parsed.budgetFile = value;
    } else {
      fail([`未知参数: ${name}`]);
    }
    index += 1;
  }
  return parsed;
}

function collectJavaScriptAssets(entries) {
  const files = new Set();
  for (const entry of entries) {
    if (entry.file?.endsWith(".js")) {
      files.add(entry.file);
    }
    for (const cssOrAsset of entry.imports ?? []) {
      const importedFile = manifest[cssOrAsset]?.file;
      if (importedFile?.endsWith(".js")) {
        files.add(importedFile);
      }
    }
  }
  return [...files];
}

function assetStats(file) {
  const fullPath = path.join(assetsDir, file);
  if (!existsSync(fullPath)) {
    fail([`manifest 引用的产物不存在: ${file}`]);
  }
  const source = readFileSync(fullPath);
  return {
    rawBytes: source.length,
    gzipBytes: gzipSync(source).length,
  };
}

function checkBudget(failures, label, actualBytes, limitBytes) {
  if (actualBytes > limitBytes) {
    failures.push(`${label} ${formatBytes(actualBytes)} 超过预算 ${formatBytes(limitBytes)}`);
  }
}

function formatBytes(bytes) {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

function fail(messages) {
  console.error(["前端构建预算失败", ...messages].join("\n"));
  process.exit(1);
}
