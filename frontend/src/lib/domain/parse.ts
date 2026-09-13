/** JSON 载荷共用的解析原语。缺字段或类型不对立即失败, 不做静默兜底。 */

import { PersonContractError, readPersonRef, type PersonRef } from "./person";

export interface ParseOptions {
  /** 覆盖默认 Error, 例如抛出领域 ContractError。只接收 path。 */
  fail?: (path: string) => Error;
  /** 整句覆盖, 不再拼接「必须是…」。 */
  message?: string;
  /** 「是」或「为」, 默认「是」。 */
  copula?: "是" | "为";
  /** 覆盖默认期望类型名, 如「有限数字」。 */
  expected?: string;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function requireRecord(value: unknown, path: string, options?: ParseOptions): Record<string, unknown> {
  if (!isRecord(value)) {
    throwAt(path, "对象", options);
  }
  return value;
}

export function requireArray(value: unknown, path: string, options?: ParseOptions): unknown[] {
  if (!Array.isArray(value)) {
    throwAt(path, "数组", options);
  }
  return value;
}

export function requireString(value: unknown, path: string, options?: ParseOptions): string {
  if (typeof value !== "string") {
    throwAt(path, "字符串", options);
  }
  return value;
}

/** 缺省或 null 当空串; 给了但不是字符串仍算契约违约。 */
export function optionalString(value: unknown, path: string, options?: ParseOptions): string {
  if (value === undefined || value === null) {
    return "";
  }
  return requireString(value, path, options);
}

/** 字段存在才校验; undefined 原样返回。 */
export function optionalPresentString(value: unknown, path: string, options?: ParseOptions): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  return requireString(value, path, options);
}

export function requireNullableString(value: unknown, path: string, options?: ParseOptions): string | null {
  if (value === null) {
    return null;
  }
  if (typeof value !== "string") {
    throwAt(path, options?.expected ?? "字符串或 null", options);
  }
  return value;
}

export function requireNumber(value: unknown, path: string, options?: ParseOptions): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throwAt(path, options?.expected ?? "数字", options);
  }
  return value;
}

export function requireInteger(value: unknown, path: string, options?: ParseOptions & { minimum?: number }): number {
  const minimum = options?.minimum;
  if (!Number.isInteger(value) || (minimum !== undefined && (value as number) < minimum)) {
    const expected =
      options?.expected ?? (minimum !== undefined ? `大于等于 ${minimum} 的整数` : "整数");
    throwAt(path, expected, options);
  }
  return value as number;
}

export function requireNullableInteger(
  value: unknown,
  path: string,
  options?: ParseOptions & { minimum?: number },
): number | null {
  if (value === null) {
    return null;
  }
  return requireInteger(value, path, options);
}

export function requireBoolean(value: unknown, path: string, options?: ParseOptions): boolean {
  if (typeof value !== "boolean") {
    throwAt(path, "布尔值", options);
  }
  return value;
}

export function requireEnum<T extends string>(
  value: unknown,
  path: string,
  allowed: readonly T[],
  options?: ParseOptions,
): T {
  if (!allowed.includes(value as T)) {
    throwAt(path, options?.expected ?? ` ${allowed.join(" 或 ")}`, options);
  }
  return value as T;
}

export function requireNonEmptyString(value: unknown, path: string, options?: ParseOptions): string {
  if (typeof value !== "string" || value === "") {
    throwAt(path, "非空字符串", options);
  }
  return value;
}

export function requireObjectArray(value: unknown, path: string, options?: ParseOptions): Record<string, unknown>[] {
  return requireArray(value, path, options).map((item, index) => requireRecord(item, `${path}[${index}]`, options));
}

/** PersonRef: 五字段必填; 失败时用 options.fail 换成领域错误。 */
export function parsePersonRef(raw: unknown, path = "person", options?: ParseOptions): PersonRef {
  try {
    return readPersonRef(raw, path);
  } catch (error) {
    if (error instanceof PersonContractError && options?.fail) {
      throw options.fail(error.field);
    }
    throw error;
  }
}

/** null 表示系统 / 未解析到 UserMirror。`undefinedThrows` 时缺字段立即失败。 */
export function parseNullablePersonRef(
  raw: unknown,
  path: string,
  options?: ParseOptions & { undefinedThrows?: boolean },
): PersonRef | null {
  if (raw === undefined && options?.undefinedThrows) {
    throwAt(path, "对象或 null", options);
  }
  if (raw === null) {
    return null;
  }
  return parsePersonRef(raw, path, options);
}

export function bindParse(bound: ParseOptions): {
  requireRecord: (value: unknown, path: string, extra?: ParseOptions) => Record<string, unknown>;
  requireArray: (value: unknown, path: string, extra?: ParseOptions) => unknown[];
  requireString: (value: unknown, path: string, extra?: ParseOptions) => string;
  optionalString: (value: unknown, path: string, extra?: ParseOptions) => string;
  optionalPresentString: (value: unknown, path: string, extra?: ParseOptions) => string | undefined;
  requireNullableString: (value: unknown, path: string, extra?: ParseOptions) => string | null;
  requireNumber: (value: unknown, path: string, extra?: ParseOptions) => number;
  requireInteger: (value: unknown, path: string, extra?: ParseOptions & { minimum?: number }) => number;
  requireNullableInteger: (value: unknown, path: string, extra?: ParseOptions & { minimum?: number }) => number | null;
  requireBoolean: (value: unknown, path: string, extra?: ParseOptions) => boolean;
  requireEnum: <T extends string>(value: unknown, path: string, allowed: readonly T[], extra?: ParseOptions) => T;
  requireNonEmptyString: (value: unknown, path: string, extra?: ParseOptions) => string;
  requireObjectArray: (value: unknown, path: string, extra?: ParseOptions) => Record<string, unknown>[];
  parsePersonRef: (raw: unknown, path?: string, extra?: ParseOptions) => PersonRef;
  parseNullablePersonRef: (
    raw: unknown,
    path: string,
    extra?: ParseOptions & { undefinedThrows?: boolean },
  ) => PersonRef | null;
} {
  const merge = (extra?: ParseOptions): ParseOptions => ({ ...bound, ...extra });
  return {
    requireRecord: (value, path, extra) => requireRecord(value, path, merge(extra)),
    requireArray: (value, path, extra) => requireArray(value, path, merge(extra)),
    requireString: (value, path, extra) => requireString(value, path, merge(extra)),
    optionalString: (value, path, extra) => optionalString(value, path, merge(extra)),
    optionalPresentString: (value, path, extra) => optionalPresentString(value, path, merge(extra)),
    requireNullableString: (value, path, extra) => requireNullableString(value, path, merge(extra)),
    requireNumber: (value, path, extra) => requireNumber(value, path, merge(extra)),
    requireInteger: (value, path, extra) => requireInteger(value, path, merge(extra)),
    requireNullableInteger: (value, path, extra) => requireNullableInteger(value, path, merge(extra)),
    requireBoolean: (value, path, extra) => requireBoolean(value, path, merge(extra)),
    requireEnum: (value, path, allowed, extra) => requireEnum(value, path, allowed, merge(extra)),
    requireNonEmptyString: (value, path, extra) => requireNonEmptyString(value, path, merge(extra)),
    requireObjectArray: (value, path, extra) => requireObjectArray(value, path, merge(extra)),
    parsePersonRef: (raw, path = "person", extra) => parsePersonRef(raw, path, merge(extra)),
    parseNullablePersonRef: (raw, path, extra) => parseNullablePersonRef(raw, path, merge(extra)),
  };
}

function throwAt(path: string, expected: string, options?: ParseOptions): never {
  if (options?.fail) {
    throw options.fail(path);
  }
  if (options?.message) {
    throw new Error(options.message);
  }
  const copula = options?.copula ?? "是";
  throw new Error(`${path} 必须${copula}${options?.expected ?? expected}`);
}
