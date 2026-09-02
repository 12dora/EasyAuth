import { expect, test, type Locator, type Page } from "@playwright/test";

const TARGETS = [
  { path: "/console", marker: "应用列表" },
  { path: "/console/operations/access-requests", marker: "待审批" },
  { path: "/portal", marker: "我的权限" },
  { path: "/portal/request", marker: "申请权限" },
];

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "tablet900", width: 900, height: 800 },
  { name: "tablet768", width: 768, height: 800 },
  { name: "mobile390", width: 390, height: 844 },
  { name: "mobile320", width: 320, height: 740 },
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
      await expectSeedDataIsVisible(page, target.path);
      await expectVisibleControlsAreClickable(page.getByRole("main"));
      if (target.path === "/console") {
        await expectPageHeaderActionsAreUsable(page);
        await expectCreateAppDialogIsCovered(page);
      }
      if (target.path === "/console" || target.path === "/portal") {
        await expectTablesUseLocalHorizontalScroll(page);
      }
      await expectVisibleTextFits(page);
    });
  }
}

async function expectCreateAppDialogIsCovered(page: Page) {
  await page.getByRole("button", { name: "快速新建" }).click();
  const dialog = page.getByRole("dialog", { name: "新建应用" });
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("app_key")).toBeVisible();
  await expect(page.getByLabel("名称")).toBeVisible();
  await expect(page.getByLabel("描述")).toBeVisible();
  await expect(page.getByRole("button", { name: "创建" })).toBeVisible();
  await expectVisibleControlsAreClickable(dialog);
}

async function expectPageHeaderActionsAreUsable(page: Page) {
  await expect(page.getByRole("button", { name: "刷新" })).toBeVisible();
  await expect(page.getByRole("button", { name: "快速新建" })).toBeVisible();
  await expect(page.getByRole("button", { name: "接入向导" })).toBeVisible();
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
        .replace("<body", '<body data-current-user-role="admin" data-current-user-id="admin-001" data-current-user-is-superuser="true" data-current-user-can-access-console="true"')
        .replace(
          '<div id="root"',
          '<div id="root" data-current-user-role="admin" data-current-user-id="admin-001" data-current-user-is-superuser="true" data-current-user-can-access-console="true"',
        )
        .replace(
          '<div id="easyauth-root"',
          '<div id="easyauth-root" data-current-user-role="admin" data-current-user-id="admin-001" data-current-user-is-superuser="true" data-current-user-can-access-console="true"',
        ),
      headers: { ...response.headers(), "content-type": "text/html" },
    });
  });
  await page.addInitScript(() => {
    document.documentElement.dataset.currentUserRole = "admin";
    document.addEventListener("DOMContentLoaded", () => {
      document.body.dataset.currentUserRole = "admin";
      document.body.dataset.currentUserId = "admin-001";
      document.body.dataset.currentUserIsSuperuser = "true";
      const root = document.getElementById("easyauth-root") ?? document.getElementById("root");
      if (root) {
        root.dataset.currentUserRole = "admin";
        root.dataset.currentUserId = "admin-001";
        root.dataset.currentUserIsSuperuser = "true";
      }
    });
  });
}

async function mockVisualData(page: Page) {
  await page.route("**/console/api/v1/apps**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        data: [
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
        pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
      },
    });
  });
  await page.route("**/console/api/v1/operations/access-requests**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        data: [
          {
            id: 2001,
            user_id: "employee-001",
            app_key: "demo",
            status: "submitted",
            request_type: "access",
            submitted_at: "2026-07-01T00:00:00Z",
          },
        ],
        pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
      },
    });
  });
  await page.route((url) => url.pathname === "/portal/api/v1/me/grants", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        data: [
          {
            app_key: "demo",
            app_name: "Demo App",
            grant_type: "permanent",
            grant_expires_at: null,
            grant_id: 101,
            grant_revision: 1,
            groups: [{ key: "reader", kind: "role", name: "只读角色" }],
            grants: [{ permission: "invoice.read", scope: "customer_id", source_type: "authorization_group", source_key: "reader" }],
            grant_version: 1,
            catalog_version: 1,
            snapshot_version: "snapshot-visual-v1",
          },
        ],
        pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
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

async function expectSeedDataIsVisible(page: Page, path: string) {
  if (path === "/console" || path === "/portal") {
    await expect(page.getByText("Demo App").first()).toBeVisible();
  }
  if (path === "/portal") {
    await expect(page.getByText("invoice.read").first()).toBeVisible();
  }
  if (path === "/console/operations/access-requests") {
    await expect(page.getByText("employee-001").first()).toBeVisible();
  }
}

interface TableScrollOffender {
  columns: number;
  reason: string;
  scroller: string;
  tableWidth: number;
  visibleWidth: number;
}

/**
 * 表格超宽时必须由表格自己的滚动容器吸收, 页面本身永远不横向滚动。
 *
 * antd 的滚动容器是 `.ant-table-content`(不设 `scroll.y` 时)或 `.ant-table-body`
 * (设了 `scroll.y`, 表头单独一层时), AppTable 只有传 `minWidth` 才会写 `scroll.x`、
 * 也才会有这一层滚动; 不传 minWidth 的表格用 `tableLayout: "fixed"` 随容器收缩,
 * 本来就不会溢出。因此断言写成条件式: 溢出了就必须有 auto/scroll 的祖先容器,
 * 并且那个容器得是 antd 自己的那两个(而不是外层 paper-card 顺手把整页撑开)。
 */
async function expectTablesUseLocalHorizontalScroll(page: Page) {
  const tables = page.locator("main table");
  expect(await tables.count()).toBeGreaterThan(0);

  const offenders = await tables.evaluateAll<TableScrollOffender[], HTMLTableElement>((elements) => {
    const SCROLLABLE = new Set(["auto", "scroll"]);
    const describe = (element: Element) =>
      `${element.tagName.toLowerCase()}${element.className ? `.${String(element.className).trim().split(/\s+/).join(".")}` : ""}`;

    const nearestScroller = (table: HTMLElement): HTMLElement | null => {
      let node = table.parentElement;
      while (node) {
        if (SCROLLABLE.has(window.getComputedStyle(node).overflowX)) {
          return node;
        }
        if (node.tagName === "MAIN" || node === document.body) {
          return null;
        }
        node = node.parentElement;
      }
      return null;
    };

    return elements
      .map((table) => {
        const wrapper = table.closest(".ant-table-wrapper");
        const scroller = nearestScroller(table);
        const viewport = scroller ?? table.parentElement ?? document.documentElement;
        const tableWidth = Math.round(table.getBoundingClientRect().width);
        const visibleWidth = Math.round(viewport.clientWidth);
        const overflows = tableWidth > visibleWidth + 1;
        const offender = (reason: string): TableScrollOffender => ({
          columns: table.querySelectorAll("thead th").length,
          reason,
          scroller: scroller ? describe(scroller) : "<none>",
          tableWidth,
          visibleWidth,
        });

        if (overflows && !scroller) {
          return offender("表格超宽但没有局部横向滚动容器, 会把整页撑出横向滚动条");
        }
        if (overflows && wrapper && !scroller?.matches(".ant-table-content, .ant-table-body")) {
          return offender("横向滚动没有落在 antd 自己的 .ant-table-content / .ant-table-body 上");
        }
        if (scroller && Math.round(scroller.getBoundingClientRect().width) > Math.round(document.documentElement.clientWidth) + 1) {
          return offender("滚动容器本身比视口还宽, 局部滚动没起作用");
        }
        return null;
      })
      .filter((entry): entry is TableScrollOffender => entry !== null);
  });

  expect(offenders).toEqual([]);

  // 局部滚动的最终判据: 文档层面不存在横向滚动。
  const documentOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(documentOverflow).toBeLessThanOrEqual(1);
}

/**
 * 可见控件不能被别的元素盖住。
 *
 * antd 的 Select 是复合控件: 真正的点击面是 `.ant-select-selector`, 里面那个
 * `input.ant-select-selection-search-input` 只负责键盘输入, 视觉上被同级的
 * `.ant-select-selection-item`(当前选中项文案)压在下面 —— 那是 antd 的正常构造,
 * 不是被遮挡。所以这里跳过那个内部 input, 改判它外层的点击面。
 */
async function expectVisibleControlsAreClickable(scope: Page | Locator) {
  const controls = scope.locator(
    "button:visible, a:visible, select:visible, input:not(.ant-select-selection-search-input):visible, textarea:visible, .ant-select-selector:visible",
  );
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
