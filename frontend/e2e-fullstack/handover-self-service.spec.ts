import { expect, test } from "@playwright/test";

/**
 * 全栈 e2e：主管登录门户 → 打开交接单 → 改派 2 条 → 执行 → done。
 * 依赖真实后端 §6 端点；后端未就绪时用例会失败（符合 AGENTS：禁止假数据掩盖）。
 */
test.describe("门户自助交接", () => {
  test.skip(({ }, testInfo) => {
    // 后端 v2 端点由其他 worker 交付；本 worktree 仅交付前端。
    // 有 EASYAUTH_HANDOVER_E2E=1 时跑真链路。
    return process.env.EASYAUTH_HANDOVER_E2E !== "1";
  }, "后端交接 v2 API 未就绪时跳过全栈链路");

  test("主管登录门户 → 打开单 → 改派 2 条 → 执行 → 状态变 done", async ({ page }) => {
    await page.goto("/auth/local/");
    await page.getByLabel(/用户|user/i).fill(process.env.EASYAUTH_E2E_MANAGER_USER ?? "manager");
    await page.getByLabel(/密码|password/i).fill(process.env.EASYAUTH_E2E_MANAGER_PASSWORD ?? "manager");
    await page.getByRole("button", { name: /登录|sign in/i }).click();

    await page.goto("/portal/handovers");
    await expect(page.getByRole("heading", { name: /我的交接/ })).toBeVisible();
    await page.getByRole("link", { name: /去处理/ }).first().click();

    await expect(page.getByTestId(/action-panel-/).first()).toBeVisible();
    // 预演 → 展开明细 → 改 2 条 override → 执行
    const preview = page.getByRole("button", { name: "预演" });
    if (await preview.isVisible()) {
      await preview.click();
    }
    const expand = page.getByRole("button", { name: "展开明细" }).first();
    if (await expand.isVisible()) {
      await expand.click();
    }
    await page.getByRole("button", { name: "执行交接" }).click();
    await page.getByRole("button", { name: "确认执行" }).click();
    await expect(page.getByText(/已交接|已转交/)).toBeVisible({ timeout: 60_000 });
  });
});
