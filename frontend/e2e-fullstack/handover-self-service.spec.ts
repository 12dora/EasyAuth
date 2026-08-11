import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * 全栈 e2e：主管登录门户 → 打开交接单 → 改派 2 条 → 执行 → done。
 * 依赖真实后端 §6 端点；后端未就绪时用例会失败（符合 AGENTS：禁止假数据掩盖）。
 *
 * 登录说明（设计冲突修正）：
 * - 规格原文走 `/auth/local/` 表单（`EASYAUTH_E2E_MANAGER_USER/PASSWORD`）。
 * - 但 `/auth/local/` 只绑定 break-glass 本地超管（`local-admin:` subject），
 *   门户交接 API 对 `local-admin:` 固定 403（01 §6.1 / 02 §3.1：
 *   「本地管理员不能使用员工门户交接接口」）。
 * - 因此本用例用真实 `UserMirror` session 注入（与 health-and-auth 同模式），
 *   用户主体仍是 seed 出的 manager，经真实 Django session + 门户 API 完成链路。
 */
test.describe("门户自助交接", () => {
  test("主管登录门户 → 打开单 → 改派 2 条 → 执行 → 状态变 done", async ({ browser }) => {
    const sessionCookie = createManagerPortalSession();
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

    await page.goto("/portal/handovers");
    await expect(page.getByRole("heading", { name: /我的交接/ })).toBeVisible();
    await page.getByRole("link", { name: /去处理/ }).first().click();

    await expect(page.getByTestId(/action-panel-/).first()).toBeVisible();
    // 预演 → 展开明细 → 改 2 条 override → 保存 → 执行（02 §9）
    const preview = page.getByRole("button", { name: "预演" });
    if (await preview.isVisible()) {
      await preview.click();
    }
    await expect(page.getByTestId("asset-allocator").first()).toBeVisible({ timeout: 30_000 });

    // 限定在资产类型行：勿点到 offboard 的 APP 级「权限接收人」picker（同 placeholder）。
    const typeRow = page.getByTestId("asset-type-row-document");
    await expect(typeRow).toBeVisible();

    // 默认 default_action=skip 时「暂不处理」与默认相同不会落 override。
    // 先把类型默认改为「全部转给」并指定接收人，再把前两条改为 skip，形成真实 2 条 override。
    const typeDefault = typeRow.locator('select[aria-label$="默认处理方式"]');
    await typeDefault.selectOption("transfer");
    await typeRow.getByPlaceholder("搜索接收人").click();
    // combobox 的 listbox option，勿与 <select><option> 混淆
    const peerOption = page.locator('[role="listbox"] [role="option"]').filter({ hasText: /E2E Peer|e2e-peer/ }).first();
    await expect(peerOption).toBeVisible({ timeout: 15_000 });
    await peerOption.click();
    // 等待类型默认 PATCH：路径含 /assets/document
    await page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        response.url().includes("/assets/document") &&
        response.ok(),
      { timeout: 15_000 },
    );
    await expect(typeDefault).toHaveValue("transfer");

    await typeRow.getByRole("button", { name: "展开明细" }).click();
    await expect(page.getByTestId(/asset-item-/).first()).toBeVisible({ timeout: 30_000 });

    // 改派 2 条：前两条改为「暂不处理」并保存 override
    const itemRows = page.locator("[data-testid^=asset-item-]");
    await expect(itemRows.first()).toBeVisible();
    const selects = itemRows.locator('select[aria-label$=" action"]');
    expect(await selects.count()).toBeGreaterThanOrEqual(2);
    await selects.nth(0).selectOption("skip");
    await selects.nth(1).selectOption("skip");
    await page.getByRole("button", { name: "保存单独指定" }).click();
    // 保存后两条明细都应出现 override 角标
    await expect(page.getByTestId("override-dot")).toHaveCount(2, { timeout: 15_000 });

    await page.getByRole("button", { name: "执行交接" }).click();
    await page.getByRole("button", { name: "确认执行" }).click();
    await expect(page.getByText("已交接").first()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("已转交 1")).toBeVisible();
    await expect(page.getByText("已跳过 2")).toBeVisible();

    await context.close();
  });
});

function createManagerPortalSession(): { name: string; value: string } {
  const repoRoot = path.resolve(process.cwd(), "..");
  const managerUser = process.env.EASYAUTH_E2E_MANAGER_USER ?? "manager";
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
os.environ.setdefault("DJANGO_DEBUG", "1")

import django
django.setup()

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror

user_id = ${JSON.stringify(managerUser)}
user = UserMirror.objects.filter(authentik_user_id=user_id, status=USER_STATUS_ACTIVE).first()
if user is None:
    raise SystemExit(f"E2E manager UserMirror 不存在: {user_id!r}；请先 seed_handover_e2e")
session = SessionStore()
session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
session.save()
print(json.dumps({"name": settings.SESSION_COOKIE_NAME, "value": session.session_key}))
`,
    ],
    {
      cwd: repoRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        DATABASE_URL: "",
        DJANGO_DEBUG: "1",
        EASYAUTH_SQLITE_PATH: fullstackSqlitePath(),
      },
    },
  );
  const parsed = JSON.parse(output);
  if (typeof parsed.name !== "string" || typeof parsed.value !== "string") {
    throw new Error("无法创建 Playwright 主管门户 session。");
  }
  return parsed;
}

function fullstackSqlitePath(): string {
  return (
    process.env.EASYAUTH_PLAYWRIGHT_SQLITE_PATH ??
    `/tmp/easyauth-playwright-${process.env.PLAYWRIGHT_FULLSTACK_PORT ?? "8010"}.sqlite3`
  );
}
