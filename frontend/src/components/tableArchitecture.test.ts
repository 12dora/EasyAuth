import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, test } from "vitest";

const sourceRoot = join(process.cwd(), "src");

describe("表格架构", () => {
  test("不再保留旧 DataTable 包装组件和旧表格包装类名", () => {
    // components/antd/**、AppTable 的样式表与测试文件排除在外: 这里的禁用词是旧自研
    // 表格的类名, 而 antd 自己的类名(ant-table-wrapper / ant-table-scroll-horizontal)
    // 会被 table-wrap / table-scroll 误伤 —— 那是 antd 的 DOM 约定, 不是本仓库要清理的
    // 历史包袱。写 antd 类名的地方只有三处: components/antd/**、*.test.tsx,
    // 以及 AppTable 那两条只能用真实 CSS 表达的约定(单行分页 / 隐藏 caption)。
    const files = sourceFiles(sourceRoot).filter(
      (file) =>
        !file.endsWith("tableArchitecture.test.ts") &&
        !/\.test\.tsx?$/.test(file) &&
        !file.endsWith(join("styles", "features", "app-table.css")) &&
        !file.includes(join("components", "antd")),
    );
    const violations = files.flatMap((file) => forbiddenMatches(file));

    expect(violations).toEqual([]);
  });

  test("门户权限选择表格直接使用 TanStack Table 渲染原生表格", () => {
    const file = join(sourceRoot, "pages/portal/components/PermissionSelector.tsx");
    const content = readFileSync(file, "utf8");

    expect(content).not.toMatch(/components\/ui\/TablePrimitives/);
    expect(content).not.toMatch(/components\/ui\/TablePagination/);
    expect(content).not.toMatch(/\bDataTable\b/);
    expect(content).not.toMatch(/\bTableFrame\b/);
    expect(content).not.toMatch(/\bTableRoot\b/);
    expect(content).not.toMatch(/\bTableEmptyRow\b/);
    expect(content).toMatch(/useReactTable/);
    expect(content).toMatch(/getCoreRowModel/);
    expect(content).toMatch(/getPaginationRowModel/);
    expect(content).toMatch(/getRowId/);
    expect(content).toMatch(/flexRender/);
    expect(content).toMatch(/<table\b/);
    expect(content).toMatch(/aria-label=\{t\("selector.ariaLabel"\)\}/);
  });

  test("门户权限选择仅看已选是组件内本地展示状态", () => {
    const file = join(sourceRoot, "pages/portal/components/PermissionSelector.tsx");
    const content = readFileSync(file, "utf8");

    expect(content).toMatch(/showSelectedOnly/);
    expect(content).toMatch(/filterRowsToSelected/);
    expect(content).toMatch(/role="switch"/);
    expect(content).toMatch(/aria-label=\{t\("selector.toolbar.showSelectedOnly"\)\}/);
  });

  test("门户权限选择工具栏状态只保留已选数量", () => {
    const file = join(sourceRoot, "pages/portal/components/PermissionSelector.tsx");
    const content = readFileSync(file, "utf8");

    expect(content).toMatch(/selectedCount/);
    expect(content).not.toMatch(/configuredScopeCount/);
    expect(content).not.toMatch(/已设置权限范围/);
  });

  test("门户权限选择进出场动画状态在渲染期推进且不会每次渲染返回新数组", () => {
    const file = join(sourceRoot, "pages/portal/components/useGroupTransitionKeys.ts");
    const content = readFileSync(file, "utf8");

    // 收起时 exiting 集合必须与 isExpanded 同一次渲染就位(渲染期 setState),
    // 放到 useEffect 里会让子行先卸载再挂回来, 收起动画就会闪一下。
    expect(content).not.toMatch(/useEffect\(\(\) => \{[^}]*previousExpandedGroupKeys\.current/);
    expect(content).toMatch(/if \(!stringListsAreEqual\(previousExpandedGroupKeys, expandedGroupKeys\)\)/);
    expect(content).toMatch(/stringListsAreEqual\(current, next\) \? current : next/);
  });
});

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    const stats = statSync(path);
    if (stats.isDirectory()) {
      return sourceFiles(path);
    }
    return /\.(tsx?|css)$/.test(path) ? [path] : [];
  });
}

function forbiddenMatches(file: string): string[] {
  const relativePath = relative(sourceRoot, file);
  const content = readFileSync(file, "utf8");
  const forbiddenPatterns = [
    /components\/DataTable/,
    /\bDataTable\b/,
    /\bCredentialTable\b/,
    /\bGrantTable\b/,
    /\bRequestTable\b/,
    /tanstack-table/,
    /table-scroll/,
    /permission-table/,
    /matrix-table/,
    /data-table/,
    /table-wrap/,
    /empty-row/,
  ];
  return forbiddenPatterns
    .filter((pattern) => pattern.test(content))
    .map((pattern) => `${relativePath}: ${pattern.source}`);
}
