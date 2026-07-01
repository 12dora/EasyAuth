import { expect, test, type Locator, type Page } from "@playwright/test";

const VIEWPORTS = [
  { name: "desktop", size: { width: 1280, height: 800 } },
  { name: "mobile", size: { width: 390, height: 844 } },
];

test("控制台 React shell 可以加载", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("EasyAuth").first()).toBeVisible();
  await expect(page.getByRole("navigation").getByText("应用")).toBeVisible();
});

test("控制台和门户深链可以直接打开", async ({ page }) => {
  await page.goto("/console/operations/access-requests");

  await expect(page.getByRole("navigation").getByText("申请运营")).toBeVisible();
  await expect(page.getByTestId("route-transition")).toHaveAttribute(
    "data-route-pathname",
    "/console/operations/access-requests",
  );

  await page.goto("/portal/request");

  await expect(page.getByRole("navigation").getByText("申请权限")).toBeVisible();
  await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal/request");
});

for (const viewport of VIEWPORTS) {
  test(`portal request smoke renders the access request form on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await mockPortalRequestCatalog(page);

    await page.goto("/portal/request");

    await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal/request");
    await expect(page.getByLabel("应用")).toBeVisible();
    await expect(page.getByLabel("角色")).toBeVisible();
    await expect(page.getByLabel("授权期限")).toBeVisible();
    await expect(page.getByLabel("申请原因")).toBeVisible();

    await page.getByLabel("应用").selectOption("demo");

    await expect(page.getByRole("table", { name: "权限选择" })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "选择 invoice.read" })).toBeVisible();
    await expect(page.getByRole("button", { name: "提交申请" })).toBeVisible();
    await expectButtonNotCovered(page.getByRole("button", { name: "提交申请" }));
  });

  test(`console credentials smoke renders credential controls on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await mockConsoleApp(page);
    await mockConsoleCredentials(page);

    await page.goto("/console/apps/demo?tab=credentials");

    await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console/apps/demo");
    await expect(page.getByLabel("凭据名称")).toBeVisible();
    await expect(page.getByRole("button", { name: "静态 token" })).toBeVisible();
    await expect(page.getByRole("button", { name: "OAuth client" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Static Primary" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "OAuth Primary" })).toBeVisible();

    await expectButtonNotCovered(page.getByRole("button", { name: "静态 token" }));
    await expectButtonNotCovered(page.getByRole("button", { name: "OAuth client" }));
  });

  test(`console matrix smoke renders matrix controls on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await mockConsoleApp(page);
    await mockConsoleMatrix(page);

    await page.goto("/console/apps/demo?tab=matrix");

    await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console/apps/demo");
    await expect(page.getByRole("button", { name: "保存变更" })).toBeVisible();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "admin invoice.read" })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "auditor invoice.export" })).toBeVisible();
    await expect(page.getByText("matrix-smoke")).toBeVisible();

    await expectButtonNotCovered(page.getByRole("button", { name: "保存变更" }));
  });
}

async function mockConsoleApp(page: Page) {
  await page.route("**/console/api/v1/apps/demo", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        app: {
          id: 1,
          app_key: "demo",
          name: "Demo App",
          description: "Demo console app",
        },
      },
    });
  });
}

async function mockConsoleCredentials(page: Page) {
  await page.route("**/console/api/v1/apps/demo/credentials", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [
          { id: 101, kind: "static_token", name: "Static Primary", is_active: true },
          { id: 202, kind: "oauth_client", name: "OAuth Primary", client_id: "oauth-client-1", is_active: true },
        ],
      },
    });
  });
}

async function mockConsoleMatrix(page: Page) {
  await page.route("**/console/api/v1/apps/demo/role-permission-matrix", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        version: "matrix-smoke-v1",
        roles: [
          { id: 10, key: "admin", name: "管理员" },
          { id: 11, key: "auditor", name: "审计员" },
        ],
        permissions: [
          { id: 20, key: "invoice.read", name: "发票读取" },
          { id: 21, key: "invoice.export", name: "发票导出" },
        ],
        cells: [
          { role_id: 10, permission_id: 20, enabled: true },
          { role_id: 11, permission_id: 21, enabled: false },
        ],
      },
    });
  });
}

async function mockPortalRequestCatalog(page: Page) {
  await page.route("**/portal/api/v1/request-catalog", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        apps: [{ id: 1, app_key: "demo", name: "Demo App" }],
        roles: [{ id: 10, app_key: "demo", key: "reader", name: "只读角色", requestable: true, requires_approval: true }],
        permission_groups: [],
        ungrouped_permissions: [
          { id: 20, app_key: "demo", key: "invoice.read", name: "发票读取" },
          { id: 21, app_key: "demo", key: "invoice.export", name: "发票导出" },
        ],
      },
    });
  });
}

async function expectButtonNotCovered(button: Locator) {
  await button.scrollIntoViewIfNeeded();
  await expect(button).toBeVisible();

  await expect
    .poll(async () =>
      button.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        const topElement = document.elementFromPoint(centerX, centerY);

        return topElement !== null && element.contains(topElement);
      }),
    )
    .toBe(true);
}
