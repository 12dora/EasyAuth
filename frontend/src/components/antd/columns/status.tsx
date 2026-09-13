import { type ReactNode } from "react";

import type { BadgeTone, Translator } from "../../../lib/status";
import { Badge } from "../../Badge";
import { enumFilter, readField, type ColumnType } from "../AppTable";
import { PERSON_SORT_LOCALE } from "./person";

export interface StatusColumnOption {
  value: string;
  /** 已本地化的展示文案。 */
  label: ReactNode;
  /** 复用 Badge 的色调; 缺省 neutral。 */
  tone?: BadgeTone;
}

export interface StatusColumnConfig<T> {
  /** 列 key, 同时作为默认取值字段。 */
  key: string;
  title: ReactNode;
  options: readonly StatusColumnOption[];
  /** 默认读 `record[key]`。 */
  getValue?: (record: T) => string | null | undefined;
  width?: number;
  /** 关闭内建的枚举筛选(默认开启)。 */
  filter?: boolean;
  /**
   * 开启按 options 声明顺序的客户端排序; 未知值排在最后。
   * 服务端分页表不要开, 改过 `serverSortColumn`(它会覆盖掉比较函数)。
   */
  sorter?: boolean;
  /**
   * 为 true 时单元格只渲染本地化文案, 不画 Badge、不加色调。
   * 筛选、排序、空值 "-" 不变。默认 false。
   */
  plain?: boolean;
}

/**
 * 状态列客户端比较: 按 `options` 声明顺序, 未出现在 options 里的值(含空值)排最后。
 * 同位时再按取值本身比较, 保证未知值之间顺序稳定。
 */
export function compareStatusByOptionIndex(
  left: string | undefined,
  right: string | undefined,
  options: readonly { value: string }[],
): number {
  const rank = (value: string | undefined): number => {
    if (value === undefined || value === "") {
      return options.length;
    }
    const index = options.findIndex((option) => option.value === value);
    return index === -1 ? options.length : index;
  };
  const leftRank = rank(left);
  const rightRank = rank(right);
  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }
  return String(left ?? "").localeCompare(String(right ?? ""), PERSON_SORT_LOCALE);
}

/**
 * 状态列: 默认 Badge 渲染 + 内建 enumFilter。
 * 未在 options 里出现的值按 neutral 原样展示, 空值展示 "-"。
 * `plain` 时只输出文案, 筛选 / 排序 / 空值规则不变。
 */
export function statusColumn<T>({
  filter = true,
  getValue,
  key,
  options,
  plain = false,
  sorter = false,
  title,
  width,
}: StatusColumnConfig<T>): ColumnType<T> {
  const read = (record: T) => {
    const raw = getValue ? getValue(record) : readField(record, key);
    return raw === null || raw === undefined || raw === "" ? undefined : String(raw);
  };

  return {
    key,
    dataIndex: key,
    title,
    width,
    render: (_value: unknown, record: T) => {
      const value = read(record);
      if (value === undefined) {
        return "-";
      }
      const option = options.find((item) => item.value === value);
      const label = option?.label ?? value;
      if (plain) {
        return <span>{label}</span>;
      }
      return <Badge tone={option?.tone ?? "neutral"}>{label}</Badge>;
    },
    ...(filter
      ? enumFilter<T>(
          key,
          options.map((option) => ({ label: option.label, value: option.value })),
          { getValue: (record) => read(record) ?? null },
        )
      : {}),
    ...(sorter
      ? { sorter: (a: T, b: T) => compareStatusByOptionIndex(read(a), read(b), options) }
      : {}),
  };
}

/**
 * 启用/停用状态列。工作区、应用列表、团队、模板表共用这一份徽章与筛选项。
 */
export function activeStatusColumn<T>({
  filter = true,
  getActive,
  key = "status",
  plain = false,
  sorter = true,
  t,
  width = 120,
}: {
  t: Translator;
  getActive: (record: T) => boolean | undefined;
  key?: string;
  width?: number;
  filter?: boolean;
  sorter?: boolean;
  plain?: boolean;
}): ColumnType<T> {
  return statusColumn<T>({
    filter,
    getValue: (record) => (getActive(record) ? "active" : "inactive"),
    key,
    options: [
      { value: "active", label: t("common.enabled"), tone: "evergreen" },
      { value: "inactive", label: t("common.disabled"), tone: "neutral" },
    ],
    plain,
    sorter,
    title: t("common.status"),
    width,
  });
}
