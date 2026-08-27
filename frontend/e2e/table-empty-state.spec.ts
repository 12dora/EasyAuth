import { expect, test, type Page } from "@playwright/test";

/**
 * 空表的空态框必须和表头同宽同起点。
 *
 * 回归的是这个 bug: AppTable 恒设 `scroll.x`(默认取页面传的 minWidth), 于是没有一行
 * 数据的表格也被撑到 minWidth 宽、带上一条横向滚动条; 而 antd 的空态占位是包在
 * `.ant-table-expanded-row-fixed` 里、宽度写死成「容器宽度」并 sticky 在可视区的,
 * 结果表头(960px)比空态框(容器 860px)宽, 一滚表头整排移动、空态框纹丝不动,
 * 末尾的「操作」列还被 sticky 钉在右侧盖住相邻列。
 * 修法见 AppTable 的 `mergedScroll`: 空表把 `scroll.x` 降成 `true`(只要滚动容器,
 * 宽度交回 `table-layout: fixed`)。
 *
 * 断言写成「表头行 / 空态占位单元格 / 空态框」三者同宽同边界, 而不是截图比对,
 * 这样换字号或换空态文案都不会误报。
 */
const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "tablet900", width: 900, height: 800 },
];

interface EmptyTableMetrics {
  headLeft: number;
  headRight: number;
  cellLeft: number;
  cellRight: number;
  boxLeft: number;
  boxRight: number;
  scrollWidth: number;
  clientWidth: number;
}

for (const viewport of VIEWPORTS) {
  test(`空表的空态框与表头同宽 ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await setConsoleAdmin(page);
    await mockEmptyConsoleLists(page);

    await page.goto("/console/people");
    await expect(page.getByText("暂无人员")).toBeVisible();

    const metrics = await page.evaluate<EmptyTableMetrics>(() => {
      const wrapper = document.querySelector(".ant-table-wrapper") as HTMLElement;
      const scroller = wrapper.querySelector(".ant-table-content, .ant-table-body") as HTMLElement;
      const head = wrapper.querySelector("thead.ant-table-thead tr") as HTMLElement;
      const cell = wrapper.querySelector("tr.ant-table-placeholder td") as HTMLElement;
      // 开了横向滚动时 antd 会再包一层 `.ant-table-expanded-row-fixed`, 空态框在它里面。
      const box = (cell.querySelector(".ant-table-expanded-row-fixed") ?? cell).firstElementChild as HTMLElement;
      const round = (value: number) => Math.round(value);
      return {
        headLeft: round(head.getBoundingClientRect().left),
        headRight: round(head.getBoundingClientRect().right),
        cellLeft: round(cell.getBoundingClientRect().left),
        cellRight: round(cell.getBoundingClientRect().right),
        boxLeft: round(box.getBoundingClientRect().left),
        boxRight: round(box.getBoundingClientRect().right),
        scrollWidth: scroller.scrollWidth,
        clientWidth: scroller.clientWidth,
      };
    });

    // 表头行与空态占位单元格必须是同一条水平线上的同一段区间。
    expect(metrics.cellLeft).toBe(metrics.headLeft);
    expect(metrics.cellRight).toBe(metrics.headRight);
    // 空态框只比表头窄一个单元格内边距(左右对称), 不会出现整块偏移或跨出表头。
    const insetLeft = metrics.boxLeft - metrics.headLeft;
    const insetRight = metrics.headRight - metrics.boxRight;
    expect(insetLeft).toBe(insetRight);
    expect(insetLeft).toBeGreaterThanOrEqual(0);
    expect(insetLeft).toBeLessThanOrEqual(24);
    // 一行数据都没有的表格不该还能横向滚动: 各列声明的宽度加起来放得下就必须放下。
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);
  });
}

async function mockEmptyConsoleLists(page: Page) {
  await page.route("**/console/api/v1/**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { data: [], pagination: { page: 1, page_size: 10, total_items: 0, total_pages: 0 } },
    });
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
        .replace("<body", '<body data-current-user-role="EasyAuth Admins" data-current-user-id="admin-001" data-current-user-is-superuser="true" data-current-user-can-access-console="true"')
        .replace(
          '<div id="root"',
          '<div id="root" data-current-user-role="EasyAuth Admins" data-current-user-id="admin-001" data-current-user-is-superuser="true" data-current-user-can-access-console="true"',
        )
        .replace(
          '<div id="easyauth-root"',
          '<div id="easyauth-root" data-current-user-role="EasyAuth Admins" data-current-user-id="admin-001" data-current-user-is-superuser="true" data-current-user-can-access-console="true"',
        ),
      headers: { ...response.headers(), "content-type": "text/html" },
    });
  });
  await page.addInitScript(() => {
    document.documentElement.dataset.currentUserRole = "EasyAuth Admins";
    document.addEventListener("DOMContentLoaded", () => {
      document.body.dataset.currentUserRole = "EasyAuth Admins";
      document.body.dataset.currentUserId = "admin-001";
      document.body.dataset.currentUserIsSuperuser = "true";
      const root = document.getElementById("easyauth-root") ?? document.getElementById("root");
      if (root) {
        root.dataset.currentUserRole = "EasyAuth Admins";
        root.dataset.currentUserId = "admin-001";
        root.dataset.currentUserIsSuperuser = "true";
      }
    });
  });
}
