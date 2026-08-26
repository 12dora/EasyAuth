import { render, waitFor, type RenderOptions, type RenderResult } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import type { ReactElement, ReactNode } from "react";

import { I18nProvider } from "../../i18n/I18nProvider";
import { AppConfigProvider } from "./AppConfigProvider";

/**
 * 表格测试的公共脚手架。**只给测试文件用**, 不要从页面代码引入
 * (它依赖 @testing-library, 属于 devDependencies)。
 *
 * 渲染 AppTable 的用例必须包 AppConfigProvider(主题/locale 都在那), 否则
 * antd 的分页、筛选文案会退回默认英文, 且拿不到设计令牌主题; 而 AppConfigProvider
 * 自己要读 I18nProvider 的 locale, 因此两层必须成对出现 —— 这里包好一次。
 */
export function AppTableTestProvider({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <AppConfigProvider>{children}</AppConfigProvider>
    </I18nProvider>
  );
}

/** `render(ui)` 的替代品: 自动套上 I18nProvider + AppConfigProvider。 */
export function renderWithAntd(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">): RenderResult {
  return render(ui, { ...options, wrapper: AppTableTestProvider });
}

/**
 * antd Table 在 jsdom 里每次筛选/排序都要重建整棵表格, 比自研原语慢得多,
 * 默认 5s 常常不够。在测试文件顶层写:
 * `vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS })`。
 *
 * 取 30s: 工作区/矩阵/凭据这几个大页面本来就要 30s, 而模板页在整套用例并发跑时
 * 会逼近 20s 上限而偶发超时 —— 全站统一到最大的那一档, 页面里不再各写各的数字。
 */
export const ANTD_TEST_TIMEOUT_MS = 30_000;

/**
 * 打开某一列的表头筛选下拉, 返回下拉面板节点(可用 `within(dropdown)` 继续查询)。
 *
 * 页面测试里各写一份的版本合并在这里:
 * - 可选 `scope`: 一个页面有多张表时把查找限定在某张表的容器内;
 * - 列名按「优先前缀匹配、其次包含匹配」定位表头(固定列会让同一个标题出现两次);
 * - 等到下拉真正可见(`.ant-dropdown:not(.ant-dropdown-hidden)`)再返回, antd 的
 *   下拉是延迟挂载 + 动画收起的, 直接查 `.ant-table-filter-dropdown` 会拿到上一个。
 *
 * ```ts
 * const dropdown = await openHeaderFilter(user, "状态");
 * const dropdown = await openHeaderFilter(user, panel, "角色");
 * ```
 */
export function openHeaderFilter(user: UserEvent, columnTitle: string): Promise<HTMLElement>;
export function openHeaderFilter(user: UserEvent, scope: HTMLElement, columnTitle: string): Promise<HTMLElement>;
export async function openHeaderFilter(
  user: UserEvent,
  scopeOrTitle: HTMLElement | string,
  maybeColumnTitle?: string,
): Promise<HTMLElement> {
  const scope: ParentNode = typeof scopeOrTitle === "string" ? document : scopeOrTitle;
  const columnTitle = typeof scopeOrTitle === "string" ? scopeOrTitle : (maybeColumnTitle ?? "");
  const header = findColumnHeader(scope, columnTitle);
  const trigger = header.querySelector(".ant-table-filter-trigger");
  if (!(trigger instanceof HTMLElement)) {
    throw new Error(`列「${columnTitle}」的表头上没有筛选图标, 该列没有开启筛选?`);
  }
  await user.click(trigger);
  return openFilterDropdown();
}

/** 表头筛选图标已经点开时, 等下拉面板可见并返回它。 */
export function openFilterDropdown(): Promise<HTMLElement> {
  return waitFor(() => {
    const dropdown = document.querySelector(".ant-dropdown:not(.ant-dropdown-hidden) .ant-table-filter-dropdown");
    if (!(dropdown instanceof HTMLElement)) {
      throw new Error("表头筛选下拉没有出现");
    }
    return dropdown;
  });
}

/**
 * 点一次某列表头的排序区(不是整个 `th`: 带筛选的列上点 `th` 可能命中筛选图标)。
 *
 * 服务端排序的用例都是「点一下断言 `ordering=field`, 再点一下断言 `-field`」,
 * 每个页面各写一遍 querySelector 太碎, 合并在这里。
 *
 * ```ts
 * await sortByColumn(user, "状态");
 * await sortByColumn(user, panel, "申请时间");
 * ```
 */
export function sortByColumn(user: UserEvent, columnTitle: string): Promise<void>;
export function sortByColumn(user: UserEvent, scope: HTMLElement, columnTitle: string): Promise<void>;
export async function sortByColumn(
  user: UserEvent,
  scopeOrTitle: HTMLElement | string,
  maybeColumnTitle?: string,
): Promise<void> {
  const scope: ParentNode = typeof scopeOrTitle === "string" ? document : scopeOrTitle;
  const columnTitle = typeof scopeOrTitle === "string" ? scopeOrTitle : (maybeColumnTitle ?? "");
  const header = findColumnHeader(scope, columnTitle);
  const sorters = header.querySelector(".ant-table-column-sorters");
  if (!(sorters instanceof HTMLElement)) {
    throw new Error(`列「${columnTitle}」的表头上没有排序区, 该列没有开启排序?`);
  }
  await user.click(sorters);
}

/**
 * 某列表头当前亮着的排序指示器; 未排序返回 null。
 * 读的是 antd 的高亮箭头(`.ant-table-column-sorter-up/down.active`),
 * 因此服务端排序下它同时验证了「受控 sortOrder 真的回填到了表头」。
 */
export function columnSortOrder(columnTitle: string): "ascend" | "descend" | null;
export function columnSortOrder(scope: HTMLElement, columnTitle: string): "ascend" | "descend" | null;
export function columnSortOrder(
  scopeOrTitle: HTMLElement | string,
  maybeColumnTitle?: string,
): "ascend" | "descend" | null {
  const scope: ParentNode = typeof scopeOrTitle === "string" ? document : scopeOrTitle;
  const columnTitle = typeof scopeOrTitle === "string" ? scopeOrTitle : (maybeColumnTitle ?? "");
  const header = findColumnHeader(scope, columnTitle);
  if (header.querySelector(".ant-table-column-sorter-up.active")) {
    return "ascend";
  }
  if (header.querySelector(".ant-table-column-sorter-down.active")) {
    return "descend";
  }
  return null;
}

function findColumnHeader(scope: ParentNode, columnTitle: string): HTMLElement {
  const headers = [...scope.querySelectorAll("th.ant-table-cell")].filter(
    (cell): cell is HTMLElement => cell instanceof HTMLElement,
  );
  const text = (cell: HTMLElement) => (cell.textContent ?? "").trim();
  const header =
    headers.find((cell) => text(cell).startsWith(columnTitle)) ??
    headers.find((cell) => text(cell).includes(columnTitle));
  if (!header) {
    throw new Error(`没找到标题以「${columnTitle}」开头的表头, 现有表头: ${headers.map(text).join(" | ")}`);
  }
  return header;
}
