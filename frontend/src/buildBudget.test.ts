import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, test } from "vitest";

const scriptPath = path.resolve(__dirname, "../scripts/check-build-budget.mjs");

describe("前端构建预算脚本", () => {
  test("校验 Vite manifest 中的入口、同步 chunk 与异步路由 chunk", () => {
    const fixture = createFixture();

    try {
      const output = execFileSync("node", [scriptPath, "--manifest", fixture.manifestPath, "--assets-dir", fixture.assetsDir], {
        encoding: "utf8",
      });

      expect(output).toContain("前端构建预算通过");
      expect(output).toContain("异步路由 chunk: 14");
    } finally {
      rmSync(fixture.root, { force: true, recursive: true });
    }
  });

  test("入口体积超过预算时失败", () => {
    const fixture = createFixture({ mainSource: "x".repeat(370 * 1024) });

    try {
      expect(() =>
        execFileSync("node", [scriptPath, "--manifest", fixture.manifestPath, "--assets-dir", fixture.assetsDir], {
          encoding: "utf8",
          stdio: "pipe",
        }),
      ).toThrow(/入口 main 原始体积/);
    } finally {
      rmSync(fixture.root, { force: true, recursive: true });
    }
  });

  test("缺少生命周期路由 chunk 时失败", () => {
    const fixture = createFixture({
      omitRouteKeys: ["src/pages/console/lifecycle/HandoverTaskList.tsx"],
    });

    try {
      expect(() =>
        execFileSync("node", [scriptPath, "--manifest", fixture.manifestPath, "--assets-dir", fixture.assetsDir], {
          encoding: "utf8",
          stdio: "pipe",
        }),
      ).toThrow(/缺少预期的路由 manifest key: src\/pages\/console\/lifecycle\/HandoverTaskList\.tsx/);
    } finally {
      rmSync(fixture.root, { force: true, recursive: true });
    }
  });

  test("路由被同步打进入口时失败", () => {
    const fixture = createFixture({
      nonDynamicRouteKeys: ["src/pages/console/ConsoleAppWorkspace.tsx"],
    });

    try {
      expect(() =>
        execFileSync("node", [scriptPath, "--manifest", fixture.manifestPath, "--assets-dir", fixture.assetsDir], {
          encoding: "utf8",
          stdio: "pipe",
        }),
      ).toThrow(/路由不是异步入口: src\/pages\/console\/ConsoleAppWorkspace\.tsx/);
    } finally {
      rmSync(fixture.root, { force: true, recursive: true });
    }
  });
});

function createFixture({
  mainSource = "console.log('main')",
  nonDynamicRouteKeys = [],
  omitRouteKeys = [],
}: {
  mainSource?: string;
  nonDynamicRouteKeys?: string[];
  omitRouteKeys?: string[];
} = {}) {
  const root = mkdtempSync(path.join(tmpdir(), "easyauth-budget-"));
  const assetsDir = path.join(root, "assets");
  const manifestPath = path.join(root, "manifest.json");
  mkdirSync(assetsDir);
  const files = [
    ["assets/main.js", mainSource],
    ["assets/vendor.js", "console.log('vendor')"],
    ...requiredRoutes().map((route) => [route.file, `console.log('${route.name}')`] as const),
  ] as const;

  for (const [file, source] of files) {
    writeFileSync(path.join(root, file), source);
  }

  const omitted = new Set(omitRouteKeys);
  const nonDynamic = new Set(nonDynamicRouteKeys);
  const routes = requiredRoutes().filter((route) => !omitted.has(route.key));
  const manifest = {
    "src/main.tsx": {
      file: "assets/main.js",
      imports: ["_vendor.js"],
      dynamicImports: routes.filter((route) => !nonDynamic.has(route.key)).map((route) => route.key),
      isEntry: true,
    },
    "_vendor.js": {
      file: "assets/vendor.js",
    },
    ...Object.fromEntries(
      routes.map((route) => [
        route.key,
        {
          file: route.file,
          isDynamicEntry: !nonDynamic.has(route.key),
        },
      ]),
    ),
  };

  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));

  return { assetsDir: root, manifestPath, root };
}

function requiredRoutes() {
  return [
    ["src/pages/console/ApprovalInstancesPage.tsx", "ApprovalInstancesPage"],
    ["src/pages/console/ApprovalTemplatesPage.tsx", "ApprovalTemplatesPage"],
    ["src/pages/console/ConsoleAppList.tsx", "ConsoleAppList"],
    ["src/pages/console/ConsoleAppWorkspace.tsx", "ConsoleAppWorkspace"],
    ["src/pages/console/ConsoleSettingsPage.tsx", "ConsoleSettingsPage"],
    ["src/pages/console/ConsoleTeamDetail.tsx", "ConsoleTeamDetail"],
    ["src/pages/console/ConsoleTeamList.tsx", "ConsoleTeamList"],
    ["src/pages/console/OperationsPage.tsx", "OperationsPage"],
    ["src/pages/console/lifecycle/ConsolePeopleList.tsx", "ConsolePeopleList"],
    ["src/pages/console/lifecycle/HandoverTaskDetail.tsx", "HandoverTaskDetail"],
    ["src/pages/console/lifecycle/HandoverTaskList.tsx", "HandoverTaskList"],
    ["src/pages/console/lifecycle/OnboardingPage.tsx", "OnboardingPage"],
    ["src/pages/console/onboarding/AppOnboardingWizard.tsx", "AppOnboardingWizard"],
    ["src/pages/portal/PortalPage.tsx", "PortalPage"],
  ].map(([key, name]) => ({
    file: `assets/${name}-abc.js`,
    key,
    name,
  }));
}
