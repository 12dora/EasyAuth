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
    expect(content).toMatch(/useReactTable/);
    expect(content).toMatch(/<table\b/);
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
