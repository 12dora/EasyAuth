import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import ts from "typescript";
import { describe, expect, test } from "vitest";

import baseline from "./codeQuality.baseline.json";

const sourceRoot = join(process.cwd(), "src");

const FILE_LINE_CAP = 500;
const FUNCTION_SPAN_CAP = 120;
const HOOK_STATE_EFFECT_CAP = 8;
const IMPORT_CAP = 25;

describe("前端体积棘轮", () => {
  const measured = measureProdTree();

  test("文件行数不超过硬帽, baseline 只许还不许借", () => {
    assertRatchet({
      measured: pickOverCap(measured.files, FILE_LINE_CAP),
      baseline: intMap(baseline.files),
      cap: FILE_LINE_CAP,
      kind: "file",
    });
  });

  test("函数/组件/hook 跨度不超过硬帽, baseline 只许还不许借", () => {
    assertRatchet({
      measured: pickOverCap(measured.functions, FUNCTION_SPAN_CAP),
      baseline: intMap(baseline.functions),
      cap: FUNCTION_SPAN_CAP,
      kind: "function",
    });
  });

  test("hook 的 useState+useEffect 不超过硬帽, baseline 只许还不许借", () => {
    assertRatchet({
      measured: pickOverCap(measured.hooksStateEffect, HOOK_STATE_EFFECT_CAP),
      baseline: intMap(baseline.hooksStateEffect),
      cap: HOOK_STATE_EFFECT_CAP,
      kind: "hooksStateEffect",
    });
  });

  test("顶层 import 不超过硬帽, baseline 只许还不许借", () => {
    assertRatchet({
      measured: pickOverCap(measured.imports, IMPORT_CAP),
      baseline: intMap(baseline.imports),
      cap: IMPORT_CAP,
      kind: "imports",
    });
  });

  test("棘轮规则: 新增超帽失败、已还清必须删行、实测不得高于记录值", () => {
    expect(() =>
      assertRatchet({
        measured: { "a.ts": 501 },
        baseline: {},
        cap: 500,
        kind: "file",
      }),
    ).toThrow(/新增超帽 file/);

    expect(() =>
      assertRatchet({
        measured: {},
        baseline: { "a.ts": 501 },
        cap: 500,
        kind: "file",
      }),
    ).toThrow(/baseline 含已还清或已消失条目/);

    expect(() =>
      assertRatchet({
        measured: { "a.ts": 400 },
        baseline: { "a.ts": 501 },
        cap: 500,
        kind: "file",
      }),
    ).toThrow(/baseline 含已还清或已消失条目/);

    expect(() =>
      assertRatchet({
        measured: { "a.ts": 520 },
        baseline: { "a.ts": 510 },
        cap: 500,
        kind: "file",
      }),
    ).toThrow(/实测超过 baseline 记录值/);

    expect(() =>
      assertRatchet({
        measured: { "a.ts": 505 },
        baseline: { "a.ts": 510 },
        cap: 500,
        kind: "file",
      }),
    ).not.toThrow();
  });

  test("countStateEffect 只计 hook 体顶层 useState/useEffect, 不进入嵌套函数", () => {
    const sourceFile = ts.createSourceFile(
      "useExample.ts",
      `
function useExample() {
  const [a, setA] = useState(0);
  useEffect(() => {
    const [inner, setInner] = useState(1);
    useEffect(() => undefined, []);
  }, []);
  function localHelper() {
    const [b, setB] = useState(2);
    useEffect(() => undefined, []);
  }
  const nested = () => {
    useState(3);
  };
  return { a, localHelper, nested };
}
`,
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TS,
    );
    const hook = collectFunctions(sourceFile).find((fn) => fn.name === "useExample");
    expect(hook).toBeDefined();
    expect(countStateEffect(hook!.node)).toBe(2);
  });
});

interface MeasuredTree {
  files: Record<string, number>;
  functions: Record<string, number>;
  hooksStateEffect: Record<string, number>;
  imports: Record<string, number>;
}

function measureProdTree(): MeasuredTree {
  const files: Record<string, number> = {};
  const functions: Record<string, number> = {};
  const hooksStateEffect: Record<string, number> = {};
  const imports: Record<string, number> = {};

  for (const file of prodSourceFiles(sourceRoot)) {
    const relativePath = relative(sourceRoot, file).split(sep).join("/");
    const content = readFileSync(file, "utf8");
    files[relativePath] = lineCount(content);

    const sourceFile = ts.createSourceFile(
      relativePath,
      content,
      ts.ScriptTarget.Latest,
      true,
      file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );
    imports[relativePath] = sourceFile.statements.filter((statement) => ts.isImportDeclaration(statement)).length;

    for (const fn of collectFunctions(sourceFile)) {
      const key = `${relativePath}:${fn.name}`;
      functions[key] = fn.span;
      if (/^use[A-Z]/.test(fn.name)) {
        hooksStateEffect[key] = countStateEffect(fn.node);
      }
    }
  }

  return { files, functions, hooksStateEffect, imports };
}

function prodSourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      return prodSourceFiles(path);
    }
    if (!/\.tsx?$/.test(path)) {
      return [];
    }
    const relativePath = relative(sourceRoot, path).split(sep).join("/");
    if (/\.test\.tsx?$/.test(relativePath) || relativePath.startsWith("i18n/messages/")) {
      return [];
    }
    return [path];
  });
}

function lineCount(content: string): number {
  if (content.length === 0) {
    return 0;
  }
  const lines = content.split(/\r?\n/);
  return content.endsWith("\n") ? lines.length - 1 : lines.length;
}

interface MeasuredFunction {
  name: string;
  span: number;
  node: ts.FunctionLikeDeclaration;
}

function collectFunctions(sourceFile: ts.SourceFile): MeasuredFunction[] {
  const out: MeasuredFunction[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isFunctionDeclaration(node) && node.name) {
      out.push({ name: node.name.text, span: nodeSpan(node, sourceFile), node });
    } else if (ts.isMethodDeclaration(node) && ts.isIdentifier(node.name)) {
      out.push({ name: node.name.text, span: nodeSpan(node, sourceFile), node });
    } else if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      const fn = unwrapFunction(node.initializer);
      if (fn) {
        out.push({ name: node.name.text, span: nodeSpan(fn, sourceFile), node: fn });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return out;
}

function unwrapFunction(node: ts.Expression): ts.ArrowFunction | ts.FunctionExpression | undefined {
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
    return node;
  }
  if (ts.isCallExpression(node) && node.arguments.length > 0) {
    const first = node.arguments[0];
    if (first && (ts.isArrowFunction(first) || ts.isFunctionExpression(first))) {
      return first;
    }
  }
  return undefined;
}

function nodeSpan(node: ts.Node, sourceFile: ts.SourceFile): number {
  let startPos = node.getStart(sourceFile, false);
  const decorators = ts.canHaveDecorators(node) ? ts.getDecorators(node) : undefined;
  if (decorators && decorators.length > 0) {
    startPos = decorators[0].getStart(sourceFile, false);
  }
  const start = sourceFile.getLineAndCharacterOfPosition(startPos).line + 1;
  const end = sourceFile.getLineAndCharacterOfPosition(node.end).line + 1;
  return end - start + 1;
}

function countStateEffect(fn: ts.FunctionLikeDeclaration): number {
  let count = 0;
  const visit = (node: ts.Node): void => {
    if (ts.isFunctionLike(node)) {
      return;
    }
    if (ts.isCallExpression(node)) {
      const name = callName(node.expression);
      if (name === "useState" || name === "useEffect") {
        count += 1;
      }
    }
    ts.forEachChild(node, visit);
  };
  if (fn.body) {
    visit(fn.body);
  }
  return count;
}

function callName(expression: ts.Expression): string {
  if (ts.isIdentifier(expression)) {
    return expression.text;
  }
  if (ts.isPropertyAccessExpression(expression) && ts.isIdentifier(expression.name)) {
    return expression.name.text;
  }
  return "";
}

function pickOverCap(measured: Record<string, number>, cap: number): Record<string, number> {
  const over: Record<string, number> = {};
  for (const [key, value] of Object.entries(measured)) {
    if (value > cap) {
      over[key] = value;
    }
  }
  return over;
}

function intMap(raw: Record<string, number>): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value !== "number" || !Number.isInteger(value)) {
      throw new Error(`baseline 值必须是整数: ${key}`);
    }
    result[key] = value;
  }
  return result;
}

function assertRatchet({
  measured,
  baseline: recorded,
  cap,
  kind,
}: {
  measured: Record<string, number>;
  baseline: Record<string, number>;
  cap: number;
  kind: string;
}): void {
  const added = Object.keys(measured)
    .filter((key) => !(key in recorded))
    .sort();
  const stale = Object.keys(recorded)
    .filter((key) => !(key in measured) || measured[key] <= cap)
    .sort();
  const grown = Object.keys(measured)
    .filter((key) => key in recorded && measured[key] > recorded[key])
    .map((key) => `${key}: ${measured[key]} > ${recorded[key]}`)
    .sort();
  expect(added, `新增超帽 ${kind}, 禁止扩表: ${added.join(", ")}`).toEqual([]);
  expect(stale, `${kind} baseline 含已还清或已消失条目, 请删行: ${stale.join(", ")}`).toEqual([]);
  expect(grown, `${kind} 实测超过 baseline 记录值: ${grown.join(", ")}`).toEqual([]);
}
