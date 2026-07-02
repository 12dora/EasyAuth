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
  test(`05 console smoke exposes app creation entry on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await setConsoleAdmin(page);
    await mockConsoleAppList(page);

    await page.goto("/console");

    await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console");
    const createEntry = page.getByRole("link", { name: /新建应用|创建应用/ }).or(page.getByRole("button", { name: /新建应用|创建应用/ }));

    await expect(createEntry.first()).toBeVisible();
    await expectNoTextOverflow(createEntry.first());
    await expectButtonNotCovered(createEntry.first());
  });

  test(`05 console smoke can open the basic information editor on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await setConsoleAdmin(page);
    await mockConsoleApp(page);
    await mockConsoleConfigurationStatus(page);
    await mockConsoleMemberships(page);

    await page.goto("/console/apps/demo");

    await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console/apps/demo");
    const editEntry = page.getByRole("button", { name: /编辑基本信息|基本信息/ }).or(page.getByRole("link", { name: /编辑基本信息|基本信息/ }));

    await expect(editEntry.first()).toBeVisible();
    await expectNoTextOverflow(editEntry.first());
    await expectButtonNotCovered(editEntry.first());
  });

  test(`05 console smoke can enter the manifest tab on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await mockConsoleApp(page);
    await mockConsoleManifest(page);

    await page.goto("/console/apps/demo");

    await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console/apps/demo");
    const manifestTab = page.getByRole("button", { name: /manifest|Manifest|清单/ });

    await manifestTab.first().click();
    await expect(page.getByText(/manifest|Manifest|清单|版本|导入|导出/).first()).toBeVisible();
    await expectNoTextOverflow(manifestTab.first());
    await expectButtonNotCovered(manifestTab.first());
  });

  test(`05 console smoke shows grants in query test results on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await mockConsoleApp(page);
    await mockConsoleQueryTest(page);

    await page.goto("/console/apps/demo?tab=test");

    await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console/apps/demo");
    await page.getByLabel("用户 ID").fill("user-001");
    await page.getByLabel("Bearer token").fill("token-001");
    await page.getByRole("button", { name: "执行联调" }).click();

    await expect(page.getByRole("cell", { name: "invoice.read" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "customer_id" })).toBeVisible();
    await expect(page.getByText("snapshot-smoke-v1").first()).toBeVisible();
    await expectButtonNotCovered(page.getByRole("button", { name: "执行联调" }));
  });

  test(`05 portal smoke can start the new access request flow on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await mockPortalRequestCatalog(page);
    await mockPortalAccessRequestSubmit(page);

    await page.goto("/portal/request");

    await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal/request");
    const authorizationGroupSelect = page.getByLabel(/可申请权限组|授权组/);

    await page.getByLabel("应用").selectOption("demo");
    await authorizationGroupSelect.selectOption("reader");
    await page.getByLabel("申请原因").fill("05 smoke 申请授权组");
    await page.getByRole("button", { name: "提交申请" }).click();

    await expect(page.getByText(/申请已提交|提交成功/)).toBeVisible();
    await expectButtonNotCovered(page.getByRole("button", { name: "提交申请" }));
  });

  test(`portal request smoke renders the access request form on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await mockPortalRequestCatalog(page);

    await page.goto("/portal/request");

    await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal/request");
    await expect(page.getByLabel("应用")).toBeVisible();
    await expect(page.getByLabel("可申请权限组")).toBeVisible();
    await expect(page.getByLabel("授权期限")).toBeVisible();
    await expect(page.getByLabel("过期时间")).toBeDisabled();
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
    await expect(page.getByRole("button", { name: "保存授权组" })).toBeVisible();
    await expect(page.getByRole("button", { name: "新建授权组" })).toBeVisible();
    await expect(page.getByText("reader")).toBeVisible();
    await expect(page.getByRole("cell", { name: "invoice.read / customer_id" })).toBeVisible();

    await expectButtonNotCovered(page.getByRole("button", { name: "保存授权组" }));
  });
}

async function setConsoleAdmin(page: Page) {
  await page.route("**/*", async (route) => {
    const request = route.request();
    if (request.resourceType() !== "document") {
      await route.fallback();
      return;
    }
    const response = await route.fetch();
    const html = await response.text();
    await route.fulfill({
      response,
      body: html
        .replace("<body", '<body data-current-user-role="EasyAuth Admins" data-current-user-id="admin-001"')
        .replace(
          '<div id="root"',
          '<div id="root" data-current-user-role="EasyAuth Admins" data-current-user-id="admin-001"',
        )
        .replace(
          '<div id="easyauth-root"',
          '<div id="easyauth-root" data-current-user-role="EasyAuth Admins" data-current-user-id="admin-001"',
        ),
      headers: { ...response.headers(), "content-type": "text/html" },
    });
  });
  await page.addInitScript(() => {
    document.documentElement.dataset.currentUserRole = "EasyAuth Admins";
    document.addEventListener("DOMContentLoaded", () => {
      document.body.dataset.currentUserRole = "EasyAuth Admins";
      document.body.dataset.currentUserId = "admin-001";
      const root = document.getElementById("easyauth-root") ?? document.getElementById("root");
      if (root) {
        root.dataset.currentUserRole = "EasyAuth Admins";
        root.dataset.currentUserId = "admin-001";
      }
    });
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
          can_manage: true,
          role_count: 1,
          permission_count: 2,
          active_credential_count: 1,
        },
      },
    });
  });
}

async function mockConsoleMemberships(page: Page) {
  await page.route("**/console/api/v1/apps/demo/memberships", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [{ id: 1, user_id: "owner-001", role: "owner", is_active: true }],
      },
    });
  });
}

async function mockConsoleAppList(page: Page) {
  await page.route("**/console/api/v1/apps", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [
          {
            id: 1,
            app_key: "demo",
            name: "Demo App",
            description: "Demo console app",
            owners: ["owner-001"],
            is_active: true,
            configuration_status: "ready",
            updated_at: "2026-07-01T00:00:00Z",
            can_manage: true,
          },
        ],
      },
    });
  });
}

async function mockConsoleConfigurationStatus(page: Page) {
  await page.route("**/console/api/v1/apps/demo/configuration-status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        app_key: "demo",
        status: "ready",
        issues: [],
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

async function mockConsoleManifest(page: Page) {
  await page.route("**/console/api/v1/apps/demo/permission-template-versions", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [{ version: "catalog-smoke-v1", imported_at: "2026-07-01T00:00:00Z" }],
      },
    });
  });
  await page.route("**/console/api/v1/apps/demo/manifest", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { app_key: "demo", catalog_version: "catalog-smoke-v1" },
    });
  });
}

async function mockConsoleQueryTest(page: Page) {
  await page.route("**/console/api/v1/apps/demo/permission-query-tests", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        app_key: "demo",
        user_id: "user-001",
        allowed: true,
        groups: [{ key: "reader", kind: "role", name: "只读角色" }],
        grants: [
          {
            permission: "invoice.read",
            scope: "customer_id:1001",
            source_type: "authorization_group",
            source_key: "reader",
          },
        ],
        grant_version: "grant-smoke-v1",
        catalog_version: "catalog-smoke-v1",
        snapshot_version: "snapshot-smoke-v1",
        expires_at: null,
      },
    });
  });
}

async function mockConsoleMatrix(page: Page) {
  await page.route("**/console/api/v1/apps/demo/authorization-groups", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [
          {
            id: 10,
            key: "reader",
            kind: "role",
            name: "只读角色",
            requestable: true,
            is_active: true,
            grants: [{ permission: "invoice.read", scope: "customer_id", is_active: true }],
          },
        ],
      },
    });
  });
  await page.route("**/console/api/v1/apps/demo/permissions", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [
          { id: 20, key: "invoice.read", name: "发票读取", supported_scopes: ["customer_id"] },
          { id: 21, key: "invoice.export", name: "发票导出", supported_scopes: ["customer_id"] },
        ],
      },
    });
  });
  await page.route("**/console/api/v1/apps/demo/scopes", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [{ key: "customer_id", name: "客户", description: "", is_active: true, display_order: 1 }],
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
        authorization_groups: [
          {
            id: 10,
            app_key: "demo",
            key: "reader",
            kind: "role",
            name: "只读角色",
            requestable: true,
            is_active: true,
            grants: [{ permission: "invoice.read", scope: "customer_id:1001", is_active: true }],
          },
        ],
        permission_groups: [],
        ungrouped_permissions: [
          {
            id: 20,
            app_key: "demo",
            key: "invoice.read",
            name: "发票读取",
            scopes: [{ key: "customer_id", name: "客户" }],
          },
          {
            id: 21,
            app_key: "demo",
            key: "invoice.export",
            name: "发票导出",
            scopes: [{ key: "customer_id", name: "客户" }],
          },
        ],
        catalog_version: "catalog-smoke-v1",
        snapshot_version: "snapshot-smoke-v1",
      },
    });
  });
}

async function mockPortalAccessRequestSubmit(page: Page) {
  await page.route("**/portal/api/v1/me/access-requests", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        request: {
          id: 9001,
          status: "submitted",
        },
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

async function expectNoTextOverflow(locator: Locator) {
  await expect
    .poll(async () =>
      locator.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        const horizontalOverflow = element.scrollWidth > Math.ceil(rect.width) + 1 && style.overflowX === "visible";
        const verticalOverflow = element.scrollHeight > Math.ceil(rect.height) + 1 && style.overflowY === "visible";

        return !horizontalOverflow && !verticalOverflow;
      }),
    )
    .toBe(true);
}
