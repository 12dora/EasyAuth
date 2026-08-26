import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, test } from "vitest";

/**
 * antd 表格迁移护栏。
 *
 * 产品决定: 所有数据表格统一走 Ant Design Table, 并且页面只允许消费
 * src/components/antd/* 的封装(AppTable / 列预设 / useServerTable),
 * 不允许直接 import antd 的 Table, 不允许再手写 <table>, 不允许继续用
 * 自研表格原语 —— 迁移完成后那些原语会被整体删除。
 *
 * ALLOWED_LEGACY_TABLE_FILES 是迁移台账: 每条都是「还没迁的页面」。
 * 迁一个删一条, 数组清空即迁移完成; 只能变短, 不允许新增。
 */
const PAGES_DIR = join(process.cwd(), "src", "pages");

const ALLOWED_LEGACY_TABLE_FILES: string[] = [
  // 迁移已完成: 只剩门户权限选择表格按设计保留 TanStack + 原生 table。
  // 它同时被 tableArchitecture.test.ts 断言「必须用 TanStack + 原生 table 渲染」,
  // 真要迁它时要一起改那条断言。
  "portal/components/PermissionSelector.tsx",
  "portal/components/PermissionSelectorTable.tsx",
];

const FORBIDDEN_PRIMITIVE_IMPORT =
  /from\s+["'][^"']*components\/ui\/(TableView|TablePrimitives|TablePagination|PaginationBar|TableState|TableActions)["']/;
const FORBIDDEN_ANTD_TABLE_IMPORT = /from\s+["']antd\/(es|lib)\/table/;
const FORBIDDEN_NATIVE_TABLE = /<table[\s>]/;
const FORBIDDEN_HEADLESS_TABLE = /\buseReactTable\b/;

describe("antd 表格迁移护栏", () => {
  test("页面不直接使用 antd Table、原生 table、TanStack Table 或自研表格原语", () => {
    const allowed = new Set(ALLOWED_LEGACY_TABLE_FILES);
    const violations = pageSourceFiles().flatMap((file) => {
      const relativePath = relative(PAGES_DIR, file).split(sep).join("/");
      if (allowed.has(relativePath)) {
        return [];
      }
      return forbiddenUsages(readFileSync(file, "utf8")).map((reason) => `${relativePath}: ${reason}`);
    });

    expect(violations).toEqual([]);
  });

  test("迁移台账只登记真实存在且真的还在用旧表格的文件", () => {
    const stale = ALLOWED_LEGACY_TABLE_FILES.filter((relativePath) => {
      const file = join(PAGES_DIR, relativePath);
      if (!existsFile(file)) {
        return true;
      }
      return forbiddenUsages(readFileSync(file, "utf8")).length === 0;
    });

    expect(stale).toEqual([]);
  });
});

function forbiddenUsages(content: string): string[] {
  const reasons: string[] = [];
  if (importsAntdTable(content) || FORBIDDEN_ANTD_TABLE_IMPORT.test(content)) {
    reasons.push("直接从 antd 引入 Table, 应改用 components/antd/AppTable");
  }
  if (FORBIDDEN_NATIVE_TABLE.test(content)) {
    reasons.push("手写原生 <table>, 应改用 components/antd/AppTable");
  }
  if (FORBIDDEN_HEADLESS_TABLE.test(content)) {
    reasons.push("使用 useReactTable, 应改用 components/antd/AppTable");
  }
  if (FORBIDDEN_PRIMITIVE_IMPORT.test(content)) {
    reasons.push("引入自研表格原语, 迁移后这些文件会被删除");
  }
  return reasons;
}

/** 只拦 `import { ..., Table, ... } from "antd"`, 其余 antd 组件不在本护栏范围内。 */
function importsAntdTable(content: string): boolean {
  const importPattern = /import\s+(?:type\s+)?\{([^}]*)\}\s+from\s+["']antd["']/g;
  for (const match of content.matchAll(importPattern)) {
    const names = match[1].split(",").map((name) => name.trim().split(/\s+as\s+/)[0].trim());
    if (names.includes("Table")) {
      return true;
    }
  }
  return false;
}

function pageSourceFiles(): string[] {
  return collect(PAGES_DIR).filter((file) => /\.tsx?$/.test(file) && !/\.test\.tsx?$/.test(file));
}

function collect(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    return statSync(path).isDirectory() ? collect(path) : [path];
  });
}

function existsFile(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}
