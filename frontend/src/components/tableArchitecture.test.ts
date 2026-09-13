import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

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

  test("人员标识不得用 textColumn / safeJoin / .join 展示, 应使用 personColumn / peopleColumn", () => {
    const files = sourceFiles(sourceRoot).filter(
      (file) => /\.tsx?$/.test(file) && !/\.test\.tsx?$/.test(file) && !file.endsWith("tableArchitecture.test.ts"),
    );
    const violations = files.flatMap((file) => {
      const relativePath = relative(sourceRoot, file).split(sep).join("/");
      if (ALLOWED_PERSON_ID_DISPLAY[relativePath]) {
        return [];
      }
      return personIdDisplayViolations(file).map(
        (reason) => `${relativePath}: ${reason} —— 改用 personColumn / peopleColumn`,
      );
    });

    expect(violations).toEqual([]);

    const ownersPanel = readFileSync(join(sourceRoot, "pages/console/workspace/overview/AppBasicInfoPanel.tsx"), "utf8");
    expect(ownersPanel).not.toMatch(/safeJoin\(\s*app\?\.owners/);
    expect(ownersPanel).toMatch(/formatOwnerList\(app\?\.owners/);
  });
});

/**
 * 本批次仍把人员 ID 当字符串拼接的页面。台账只能变短, 不得新增;
 * 对应接口改为 PersonRef[] 后必须删掉对应条目。
 */
const ALLOWED_PERSON_ID_DISPLAY: Record<string, string> = {
  "pages/console/workspace/tabs/RulesTab.tsx": "审批规则 approver_userids 本批次仍为 string[]",
  "pages/console/onboarding/BasicsStep.tsx": "接入向导 AppSummaryLike.owners 仍为 string[]",
  "pages/console/workspace/overview/AppBasicInfoPanel.tsx": "developers 本批次仍为 string[]",
};

/** 人员 ID 数组字段: 把它们 join 成单元格就是 UUID 回归。单数 user_id 常作姓名回退, 不在此列。 */
const PERSON_ARRAY_FIELD = /^(?:owners|developers|[A-Za-z0-9_]*user_ids|[A-Za-z0-9_]*userids)$/;
/** textColumn 的 key 若是人员标识(含单数 user_id), 同样禁止。 */
const PERSON_COLUMN_KEY = /^(?:owners|developers|[A-Za-z0-9_]*user_ids?|[A-Za-z0-9_]*userids)$/;

function personIdDisplayViolations(file: string): string[] {
  const content = stripComments(readFileSync(file, "utf8"));
  const hits: string[] = [];

  for (const match of content.matchAll(/\bsafeJoin\s*\(([^)]*)\)/g)) {
    if (personArrayFieldInExpression(match[1] ?? "")) {
      hits.push(`safeJoin(${(match[1] ?? "").trim()})`);
    }
  }

  for (const match of content.matchAll(
    /\.((?:owners|developers|[A-Za-z0-9_]*user_ids|[A-Za-z0-9_]*userids))\b(?:\s*\?\?[\s\S]{0,40})?\)?\s*\.join\s*\(/g,
  )) {
    hits.push(`.${match[1]}.join(`);
  }

  for (const block of extractNamedCalls(content, "textColumn")) {
    if (textColumnReadsPersonField(block)) {
      hits.push("textColumn 读取人员标识字段");
    }
  }

  return hits;
}

function personArrayFieldInExpression(expression: string): boolean {
  return [...expression.matchAll(/\.([A-Za-z0-9_]+)\b/g)].some((match) => PERSON_ARRAY_FIELD.test(match[1] ?? ""));
}

function textColumnReadsPersonField(block: string): boolean {
  const key = block.match(/\bkey\s*:\s*["']([^"']+)["']/);
  if (key && PERSON_COLUMN_KEY.test(key[1] ?? "")) {
    return true;
  }
  if (!personArrayFieldInExpression(block)) {
    return false;
  }
  // 联调结果「解析到 N 人」读的是 user_ids.length, 不是把 ID 列表渲染进单元格。
  return !/\.user_ids\s*\.\s*length\b/.test(block);
}

function extractNamedCalls(source: string, name: string): string[] {
  const calls: string[] = [];
  const pattern = new RegExp(`\\b${name}\\s*(?:<[^>]*>)?\\s*\\(`, "g");
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(source))) {
    const start = match.index + match[0].length - 1;
    const end = matchingParen(source, start);
    if (end !== -1) {
      calls.push(source.slice(start, end + 1));
    }
  }
  return calls;
}

function matchingParen(source: string, openIndex: number): number {
  let depth = 0;
  for (let index = openIndex; index < source.length; index += 1) {
    const char = source[index];
    if (char === "(") {
      depth += 1;
    } else if (char === ")") {
      depth -= 1;
      if (depth === 0) {
        return index;
      }
    }
  }
  return -1;
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

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
