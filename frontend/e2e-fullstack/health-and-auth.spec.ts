import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

test("真实 Django 服务暴露健康检查和本地登录页", async ({ page, request }) => {
  const health = await request.get("/health/");
  expect(health.ok()).toBe(true);

  await page.goto("/auth/local/");
  await expect(page).toHaveURL(/\/auth\/local\//);
  await expect(page.getByRole("button", { name: /登录|sign in/i })).toBeVisible();
});

test("真实门户 React shell 加载入口、同步 chunk 与目标懒加载路由 chunk", async ({ browser }) => {
  const sessionCookie = createPortalSession();
  const expectedAssets = expectedPortalAssets();
  const seenAssets = new Map<string, number>();
  const bareAssetFailures: string[] = [];
  const context = await browser.newContext();
  await context.addCookies([
    {
      name: sessionCookie.name,
      value: sessionCookie.value,
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  page.on("response", (response) => {
    const responseUrl = new URL(response.url());
    if (responseUrl.pathname.startsWith("/assets/") && response.status() >= 400) {
      bareAssetFailures.push(`${response.status()} ${responseUrl.pathname}`);
    }
    const asset = expectedAssets.find((file) => response.url().endsWith(`/static/easyauth/frontend/${file}`));
    if (asset) {
      seenAssets.set(asset, response.status());
    }
  });

  await page.goto("/portal/request");

  await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal/request");
  await expect(page.getByRole("navigation").getByText("申请权限")).toBeVisible();
  await expect
    .poll(() => expectedAssets.every((asset) => seenAssets.get(asset) === 200), {
      message: `缺少成功加载的前端产物: ${expectedAssets.join(", ")}`,
      timeout: 10_000,
    })
    .toBe(true);
  for (const asset of expectedAssets) {
    expect(seenAssets.get(asset), asset).toBe(200);
  }
  expect(bareAssetFailures).toEqual([]);

  await context.close();
});

test("全栈 Playwright 用例不得伪造 EasyAuth console 或 portal API", () => {
  const specFiles = listSpecFiles(path.resolve(process.cwd(), "e2e-fullstack"));
  const offenders = specFiles.filter((file) => {
    const source = readFileSync(file, "utf8");
    return /page\.route\s*\(|context\.route\s*\(|browserContext\.route\s*\(/.test(source);
  });

  expect(offenders.map((file) => path.relative(process.cwd(), file))).toEqual([]);
});

function createPortalSession(): { name: string; value: string } {
  const repoRoot = path.resolve(process.cwd(), "..");
  const output = execFileSync(
    ".venv/bin/python",
    [
      "-c",
      `
import json
import os
from pathlib import Path

from easyauth.config.local_env import load_local_env

load_local_env(Path.cwd() / ".env.local")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "easyauth.config.settings.base")

import django
django.setup()

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror

user_id = "playwright-portal-user"
UserMirror.objects.update_or_create(
    authentik_user_id=user_id,
    defaults={
        "name": "Playwright Portal User",
        "email": "playwright-portal@example.test",
        "status": USER_STATUS_ACTIVE,
    },
)
session = SessionStore()
session[AUTHENTIK_SESSION_KEY] = user_id
session.save()
print(json.dumps({"name": settings.SESSION_COOKIE_NAME, "value": session.session_key}))
`,
    ],
    {
      cwd: repoRoot,
      encoding: "utf8",
      env: { ...process.env, DATABASE_URL: "", EASYAUTH_SQLITE_PATH: fullstackSqlitePath() },
    },
  );
  const parsed = JSON.parse(output);
  if (typeof parsed.name !== "string" || typeof parsed.value !== "string") {
    throw new Error("无法创建 Playwright 门户 session。");
  }
  return parsed;
}

function fullstackSqlitePath(): string {
  return process.env.EASYAUTH_PLAYWRIGHT_SQLITE_PATH ?? `/tmp/easyauth-playwright-${process.env.PLAYWRIGHT_FULLSTACK_PORT ?? "8001"}.sqlite3`;
}

function expectedPortalAssets(): string[] {
  const repoRoot = path.resolve(process.cwd(), "..");
  const manifest = JSON.parse(
    readFileSync(path.join(repoRoot, "src/easyauth/static/easyauth/frontend/.vite/manifest.json"), "utf8"),
  );
  const main = manifest["src/main.tsx"];
  const portal = manifest["src/pages/portal/PortalPage.tsx"];
  const importFiles = (main.imports ?? []).map((key: string) => manifest[key]?.file).filter((file: unknown) => typeof file === "string");
  const files = [main.file, ...importFiles, portal.file];
  if (!files.every((file) => typeof file === "string" && file.endsWith(".js"))) {
    throw new Error("Vite manifest 缺少门户 shell 必需的 JavaScript 产物。");
  }
  return files;
}

function listSpecFiles(root: string): string[] {
  return readdirSync(root).flatMap((entry) => {
    const file = path.join(root, entry);
    if (statSync(file).isDirectory()) {
      return listSpecFiles(file);
    }
    return file.endsWith(".spec.ts") ? [file] : [];
  });
}
