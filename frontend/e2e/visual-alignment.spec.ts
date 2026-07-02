import { expect, test, type Locator, type Page } from "@playwright/test";

const TARGETS = [
  { path: "/console", marker: "应用列表" },
  { path: "/console/operations/access-requests", marker: "申请运营" },
  { path: "/portal", marker: "我的权限" },
  { path: "/portal/request", marker: "申请权限" },
];

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "mobile390", width: 390, height: 844 },
];

for (const viewport of VIEWPORTS) {
  for (const target of TARGETS) {
    test(`视觉对齐主路径 ${target.path} ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await setConsoleAdmin(page);
      await mockVisualData(page);

      await page.goto(target.path);

      await expect(page.getByText(target.marker).first()).toBeVisible();
      await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", target.path);
      await expectVisibleControlsAreClickable(page.getByRole("main"));
      if (target.path === "/console") {
        await expectCreateAppDialogIsCovered(page);
      }
      await expectVisibleTextFits(page);
    });
  }
}

async function expectCreateAppDialogIsCovered(page: Page) {
  await page.getByRole("button", { name: "新建应用" }).click();
  const dialog = page.getByRole("dialog", { name: "新建应用" });
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("app_key")).toBeVisible();
  await expect(page.getByLabel("名称")).toBeVisible();
  await expect(page.getByLabel("描述")).toBeVisible();
  await expect(page.getByRole("button", { name: "创建" })).toBeVisible();
  await expectVisibleControlsAreClickable(dialog);
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

async function mockVisualData(page: Page) {
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
  await page.route("**/console/api/v1/operations/access-requests", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [
          {
            id: 2001,
            user_id: "employee-001",
            app_key: "demo",
            status: "submitted",
            request_type: "access",
            submitted_at: "2026-07-01T00:00:00Z",
          },
        ],
      },
    });
  });
  await page.route("**/portal/api/v1/me/grants", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [
          {
            app_key: "demo",
            app_name: "Demo App",
            grant_type: "permanent",
            grant_expires_at: null,
            groups: [{ key: "reader", kind: "role", name: "只读角色" }],
            grants: [{ permission: "invoice.read", scope: "customer_id", source_type: "authorization_group", source_key: "reader" }],
            grant_version: "grant-visual-v1",
            catalog_version: "catalog-visual-v1",
            snapshot_version: "snapshot-visual-v1",
          },
        ],
      },
    });
  });
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
            grants: [{ permission: "invoice.read", scope: "customer_id", is_active: true }],
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
        ],
        catalog_version: "catalog-visual-v1",
        snapshot_version: "snapshot-visual-v1",
      },
    });
  });
}

async function expectVisibleControlsAreClickable(scope: Page | Locator) {
  const controls = scope.locator("button:visible, a:visible, select:visible, input:visible, textarea:visible");
  const count = Math.min(await controls.count(), 12);
  for (let index = 0; index < count; index += 1) {
    await expectNotCovered(controls.nth(index));
  }
}

async function expectNotCovered(locator: Locator) {
  await locator.scrollIntoViewIfNeeded();
  await expect(locator).toBeVisible();
  await expect
    .poll(async () =>
      locator.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        const topElement = document.elementFromPoint(centerX, centerY);
        return topElement !== null && element.contains(topElement);
      }),
    )
    .toBe(true);
}

async function expectVisibleTextFits(page: Page) {
  const offenders = await page.locator("main :is(h1,h2,h3,p,span,strong,button,a,label,th,td):visible").evaluateAll((elements) =>
    elements
      .map((element) => {
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        const horizontalOverflow = element.scrollWidth > Math.ceil(rect.width) + 1 && style.overflowX === "visible";
        if (!horizontalOverflow) {
          return null;
        }
        return {
          tag: element.tagName.toLowerCase(),
          text: (element.textContent ?? "").trim().slice(0, 80),
          rect: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
          scroll: `${element.scrollWidth}x${element.scrollHeight}`,
          overflow: style.overflowX,
        };
      })
      .filter(Boolean),
  );

  expect(offenders).toEqual([]);
}
