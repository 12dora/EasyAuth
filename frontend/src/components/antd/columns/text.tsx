import { type ReactNode } from "react";

import { useI18n } from "../../../i18n/I18nProvider";
import { cn } from "../../../lib/cn";
import { readField, textFilter, type ColumnType, type ServerSortState } from "../AppTable";

/**
 * 表格里等宽文本(app_key / user_id / 版本号等标识符)的唯一样式出处。
 * 门户权限选择表格(按架构约定直接渲染原生 table)也从这里取, 避免两处字面量漂移。
 */
export const MONO_TEXT_CLASS = "font-mono text-body leading-5 text-ink-soft";

/**
 * 不省略(`ellipsis: false`)的等宽文本用这一份 class, 由 `textColumn` 自动选用。
 *
 * 这类列的内容是多值拼接的标识符(`审批退款 (orders.refund.approve):ALL、…`), 串里
 * 没有空格也没有连字符, 浏览器找不到断行点; 而 AppTable 固定 `tableLayout: "fixed"`,
 * 列宽由 `<colgroup>` 写死, 于是整串会溢出到相邻单元格上。`break-all` 允许在任意
 * 字符处断开 —— 这类列本来就是「撑高行、不截断」的语义, 换行正是想要的结果。
 */
export const MONO_WRAP_TEXT_CLASS = cn(MONO_TEXT_CLASS, "whitespace-normal break-all");

export interface ServerColumnOptions {
  /**
   * 允许多选(仅对 antd 内建 `filters` 下拉有意义)。
   * 默认 false: `filtersToParams` 默认只取第一个选中值, 多选会被静默丢弃,
   * 因此下拉也应该只让选一个。后端确实支持多值(配 `ServerFilterParam.multiple`)时传 true。
   */
  multiple?: boolean;
}

/**
 * 把任意列改造成「服务端筛选」列。
 *
 * 必须做两件事, 少一件都会出错:
 * 1. 去掉列预设自带的客户端 `onFilter` —— antd 在受控筛选(`filteredValue`)下**依然**
 *    会执行 `onFilter`, 于是后端已经筛过的当前页会被再筛一遍; 审计的 app_key 藏在
 *    metadata 里、列上读不到, 客户端再筛会把整页筛空;
 * 2. 用 `filteredValue` 受控 —— 筛选值的真相在 URL / 查询状态里, 不能留给 antd 内部
 *    状态, 否则刷新或深链后表头筛选图标会与实际请求参数对不上(`null` 表示未筛选)。
 *
 * ```tsx
 * serverColumn(textColumn<Row>({ key: "app_key", title: t("common.app"), filter: true }), filters.app_key)
 * ```
 */
export function serverColumn<T>(
  column: ColumnType<T>,
  filteredValue?: readonly string[] | null,
  options: ServerColumnOptions = {},
): ColumnType<T> {
  const { multiple = false } = options;
  return {
    ...column,
    onFilter: undefined,
    filteredValue: filteredValue !== undefined && filteredValue !== null && filteredValue.length > 0 ? [...filteredValue] : null,
    // filterMultiple 只影响 antd 内建下拉; 自定义 filterDropdown(文本/时间范围)不受它管。
    ...(column.filters ? { filterMultiple: multiple } : {}),
  };
}

/**
 * 把任意列改造成「服务端排序」列。和 `serverColumn` 之于筛选是同一件事:
 *
 * 1. `sorter: true` —— 服务端模式的开关, **不带比较函数**。列预设自带的比较函数
 *    (`dateTimeColumn` 默认按时间戳、`textColumn({ sorter: true })` 按 localeCompare)
 *    只对「当前页那几行」生效, 在服务端分页表上是错的: 表头写着按时间倒序,
 *    实际只是把第 2 页内部重排了一遍。传进来的列若还带着比较函数, 这里会覆盖掉。
 * 2. `sortOrder` 受控 —— 排序的真相在 `useServerTable().query` 里(它就是请求参数的
 *    来源), 交给 antd 内部状态会让表头指示器和实际 `ordering` 参数对不上;
 *    别的列在排序时本列必须显式回到 `null`, 否则会同时亮起两个指示器。
 *
 * ```tsx
 * serverSortColumn(dateTimeColumn<Row>({ key: "created_at", title: t("...") }), sort)
 * ```
 */
export function serverSortColumn<T>(column: ColumnType<T>, sort: ServerSortState): ColumnType<T> {
  return {
    ...column,
    sorter: true,
    sortOrder: sort.sortField !== undefined && String(column.key) === sort.sortField ? (sort.sortOrder ?? null) : null,
  };
}

export interface DateTimeColumnConfig<T> {
  key: string;
  title: ReactNode;
  /** 默认读 `record[key]`; 返回 ISO 字符串。 */
  getValue?: (record: T) => string | null | undefined;
  width?: number;
  /** 关闭排序(默认开启, 按时间戳升降序)。 */
  sorter?: boolean;
}

/** 时间列: 走 I18nProvider 的 formatDateTime(跟随界面语言) + 时间戳排序。 */
export function dateTimeColumn<T>({
  getValue,
  key,
  sorter = true,
  title,
  width = 170,
}: DateTimeColumnConfig<T>): ColumnType<T> {
  const read = (record: T) => {
    const raw = getValue ? getValue(record) : readField(record, key);
    return raw === null || raw === undefined ? undefined : String(raw);
  };

  return {
    key,
    dataIndex: key,
    title,
    width,
    render: (_value: unknown, record: T) => <DateTimeCell value={read(record)} />,
    ...(sorter ? { sorter: (a: T, b: T) => timestamp(read(a)) - timestamp(read(b)) } : {}),
  };
}

function DateTimeCell({ value }: { value: string | undefined }) {
  const { formatDateTime } = useI18n();
  return <span className="whitespace-nowrap tabular">{formatDateTime(value)}</span>;
}

function timestamp(value: string | undefined): number {
  if (!value) {
    return 0;
  }
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

export interface TextColumnConfig<T> {
  key: string;
  title: ReactNode;
  /** 默认读 `record[key]`。 */
  getValue?: (record: T) => string | null | undefined;
  /** 开启文本子串筛选。 */
  filter?: boolean;
  /** 开启本地化字符串排序。 */
  sorter?: boolean;
  /**
   * 超宽省略(默认开启), 关闭后长文本会撑高行。
   * 关掉且 `mono` 为真时改用 `MONO_WRAP_TEXT_CLASS`, 否则无空格的标识符串会溢出列宽。
   */
  ellipsis?: boolean;
  /** 等宽字体展示(应用 key、ID 之类)。 */
  mono?: boolean;
  width?: number;
}

/** 普通文本列; 空值统一展示 "-"。 */
export function textColumn<T>({
  ellipsis = true,
  filter = false,
  getValue,
  key,
  mono = false,
  sorter = false,
  title,
  width,
}: TextColumnConfig<T>): ColumnType<T> {
  const read = (record: T) => {
    const raw = getValue ? getValue(record) : readField(record, key);
    return raw === null || raw === undefined ? "" : String(raw);
  };

  return {
    key,
    dataIndex: key,
    title,
    width,
    ellipsis,
    render: (_value: unknown, record: T) => {
      const value = read(record);
      if (value === "") {
        return "-";
      }
      if (!mono) {
        return value;
      }
      return <code className={ellipsis ? MONO_TEXT_CLASS : MONO_WRAP_TEXT_CLASS}>{value}</code>;
    },
    ...(filter ? textFilter<T>(key, { getValue: (record) => read(record) }) : {}),
    ...(sorter ? { sorter: (a: T, b: T) => read(a).localeCompare(read(b)) } : {}),
  };
}
