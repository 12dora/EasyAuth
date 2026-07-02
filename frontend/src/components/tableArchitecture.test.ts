import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, test } from "vitest";

const sourceRoot = join(process.cwd(), "src");

describe("表格架构", () => {
  test("不再保留旧 DataTable 包装组件和旧表格包装类名", () => {
    const files = sourceFiles(sourceRoot).filter((file) => !file.endsWith("tableArchitecture.test.ts"));
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
    expect(content).toMatch(/aria-label="权限选择"/);
  });

  test("门户权限选择仅看已选是组件内本地展示状态", () => {
    const file = join(sourceRoot, "pages/portal/components/PermissionSelector.tsx");
    const content = readFileSync(file, "utf8");

    expect(content).toMatch(/showSelectedOnly/);
    expect(content).toMatch(/filterRowsToSelected/);
    expect(content).toMatch(/role="switch"/);
    expect(content).toMatch(/aria-label="仅看已选"/);
  });

  test("门户权限选择工具栏状态只保留已选数量", () => {
    const file = join(sourceRoot, "pages/portal/components/PermissionSelector.tsx");
    const content = readFileSync(file, "utf8");

    expect(content).toMatch(/selectedCount/);
    expect(content).not.toMatch(/configuredScopeCount/);
    expect(content).not.toMatch(/已设置权限范围/);
  });

  test("门户权限选择退出动画状态不会在每次渲染返回新数组", () => {
    const file = join(sourceRoot, "pages/portal/components/PermissionSelector.tsx");
    const content = readFileSync(file, "utf8");

    expect(content).toMatch(/return useMemo\(\s*\(\) => exitingGroupKeys\.filter/);
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
  const tablePrimitivePatterns =
    relativePath === "components/ui/TablePrimitives.tsx" ? [/rounded-lg/, /slate-/, /shadow-slate/, /bg-white/] : [];

  return [...forbiddenPatterns, ...tablePrimitivePatterns]
    .filter((pattern) => pattern.test(content))
    .map((pattern) => `${relativePath}: ${pattern.source}`);
}
