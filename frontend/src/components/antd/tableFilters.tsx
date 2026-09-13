import { Button as AntdButton, Input } from "antd";
import type { FilterDropdownProps } from "antd/es/table/interface";
import { lazy, Suspense, type Key, type ReactNode } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import type { ColumnType } from "./AppTable";
import {
  DATE_RANGE_CONTROL_WIDTH_PX,
  decodeDateRange,
  encodeDateRange,
  type DateRangeControlProps,
  type DateRangeFilterOptions,
  type DateRangeValue,
} from "./dateRange";

export type { DateRangeControlProps, DateRangeFilterOptions, DateRangeValue };
export { DATE_RANGE_CONTROL_WIDTH_PX, decodeDateRange, encodeDateRange };

/** textFilter 的返回值; 直接展开到列定义上。 */
export type TextFilterColumn<T> = Required<Pick<ColumnType<T>, "filterDropdown" | "onFilter">>;

/** enumFilter 的返回值; 直接展开到列定义上。 */
export type EnumFilterColumn<T> = Required<Pick<ColumnType<T>, "filters" | "onFilter">>;

export interface TextFilterOptions<T> {
  /** 默认读 `record[columnKey]`; 嵌套字段或需要拼接多字段时自定义。 */
  getValue?: (record: T) => string | null | undefined;
  /** 覆盖输入框占位符; 默认走 i18n。 */
  placeholder?: string;
}

/**
 * 文本子串筛选(antd 没有内建)。大小写不敏感, 空关键字视为不筛选。
 * 用法: `{ title: "名称", dataIndex: "name", key: "name", ...textFilter<Row>("name") }`
 */
export function textFilter<T>(columnKey: string, options: TextFilterOptions<T> = {}): TextFilterColumn<T> {
  const { getValue, placeholder } = options;
  return {
    filterDropdown: (props: FilterDropdownProps) => <TextFilterDropdown {...props} placeholder={placeholder} />,
    onFilter: (value, record) => {
      const keyword = String(value).trim().toLowerCase();
      if (keyword === "") {
        return true;
      }
      const raw = getValue ? getValue(record) : readField(record, columnKey);
      return String(raw ?? "").toLowerCase().includes(keyword);
    },
  };
}

export interface EnumFilterOption {
  label: ReactNode;
  value: string;
}

export interface EnumFilterOptions<T> {
  /** 默认读 `record[columnKey]`; 返回数组时按「包含」匹配。 */
  getValue?: (record: T) => string | string[] | null | undefined;
}

/**
 * 枚举筛选: 生成 antd 内建的 `filters` 复选下拉 + 精确匹配 `onFilter`。
 * 用法: `{ ...enumFilter<Row>("status", [{ label: t("..."), value: "active" }]) }`
 */
export function enumFilter<T>(
  columnKey: string,
  options: readonly EnumFilterOption[],
  config: EnumFilterOptions<T> = {},
): EnumFilterColumn<T> {
  const { getValue } = config;
  return {
    filters: options.map((option) => ({ text: option.label, value: option.value })),
    onFilter: (value, record) => {
      const raw = getValue ? getValue(record) : readField(record, columnKey);
      if (Array.isArray(raw)) {
        return raw.map(String).includes(String(value));
      }
      return raw !== null && raw !== undefined && String(raw) === String(value);
    },
  };
}

export function readField<T>(record: T, columnKey: string): unknown {
  return (record as Record<string, unknown>)[columnKey];
}

function TextFilterDropdown({
  clearFilters,
  confirm,
  placeholder,
  selectedKeys,
  setSelectedKeys,
}: FilterDropdownProps & { placeholder?: string }) {
  const { t } = useI18n();
  const value = selectedKeys.length === 0 ? "" : String(selectedKeys[0]);

  return (
    // 下拉内部的键盘事件不能冒泡到表头, 否则空格/回车会触发排序。
    <div className="flex w-56 flex-col gap-2 p-2" onKeyDown={(event) => event.stopPropagation()}>
      <Input
        aria-label={t("table.filter.inputLabel")}
        autoFocus
        onChange={(event) => setSelectedKeys(toSelectedKeys(event.target.value))}
        onPressEnter={() => confirm()}
        placeholder={placeholder ?? t("table.filter.placeholder")}
        size="small"
        value={value}
      />
      <div className="flex items-center justify-end gap-2">
        <AntdButton
          onClick={() => {
            setSelectedKeys([]);
            clearFilters?.({ confirm: true, closeDropdown: true });
          }}
          size="small"
          type="text"
        >
          {t("table.filter.reset")}
        </AntdButton>
        <AntdButton onClick={() => confirm()} size="small" type="primary">
          {t("table.filter.confirm")}
        </AntdButton>
      </div>
    </div>
  );
}

function toSelectedKeys(value: string): Key[] {
  return value === "" ? [] : [value];
}

const LazyDateRangeControl = lazy(() =>
  import("./DateRangeControl").then((module) => ({ default: module.DateRangeControl })),
);
const LazyDateRangeFilterDropdown = lazy(() =>
  import("./DateRangeControl").then((module) => ({ default: module.DateRangeFilterDropdown })),
);

/**
 * 日期范围控件的懒加载入口。真正的 RangePicker 在 `DateRangeControl.tsx`,
 * 只在授权明细工具栏和表头 `dateRangeFilter` 打开时才拉取 antd-picker chunk。
 */
export function DateRangeControl(props: DateRangeControlProps) {
  return (
    <Suspense fallback={<DateRangeControlFallback />}>
      <LazyDateRangeControl {...props} />
    </Suspense>
  );
}

/** dateRangeFilter 的返回值; 直接展开到列定义上(多出来的方法 antd 会忽略)。 */
export interface DateRangeFilterColumn<T> extends Required<Pick<ColumnType<T>, "filterDropdown">> {
  /** 筛选值 -> `{ from, to }`。 */
  decode: (values: readonly unknown[] | null | undefined) => DateRangeValue;
  /** `{ from, to }` -> 筛选值; 回填受控 `filteredValue` 时用。 */
  encode: (range: DateRangeValue) => string[];
  /** 起止 -> 后端参数 `<paramKey>_from` / `<paramKey>_to`; 空的一端不进参数。 */
  toParams: (from: string, to: string) => Record<string, string>;
}

/**
 * 时间范围筛选。antd 只内建「文本 / 枚举」两种筛选, 时间范围要自定义下拉;
 * 输入区走全站共用的 `DateRangeControl`(RangePicker + 预设)。
 *
 * `paramKey` 决定后端参数名(默认 "created" -> created_from / created_to)。
 * 起止两端编码进同一个筛选值, 因此一列只占 antd 的一个筛选槽。
 *
 * ```tsx
 * const submittedRange = dateRangeFilter<Row>("submitted");
 * const column = serverColumn(
 *   { ...dateTimeColumn<Row>({ key: "submitted_at", title: t("...") }), ...submittedRange },
 *   submittedRange.encode({ from, to }),
 * );
 * // 请求参数: submittedRange.toParams(from, to) -> { submitted_from, submitted_to }
 * ```
 */
export function dateRangeFilter<T>(
  paramKey = "created",
  options: DateRangeFilterOptions = {},
): DateRangeFilterColumn<T> {
  const { fromLabel, toLabel } = options;
  return {
    filterDropdown: (props: FilterDropdownProps) => (
      <DateRangeFilterDropdown {...props} fromLabel={fromLabel} toLabel={toLabel} />
    ),
    decode: decodeDateRange,
    encode: encodeDateRange,
    toParams: (from, to) => {
      const params: Record<string, string> = {};
      if (from !== "") {
        params[`${paramKey}_from`] = from;
      }
      if (to !== "") {
        params[`${paramKey}_to`] = to;
      }
      return params;
    },
  };
}

function DateRangeFilterDropdown(props: FilterDropdownProps & { fromLabel?: string; toLabel?: string }) {
  return (
    <Suspense fallback={<DateRangeControlFallback />}>
      <LazyDateRangeFilterDropdown {...props} />
    </Suspense>
  );
}

function DateRangeControlFallback() {
  return (
    <span
      aria-busy="true"
      aria-hidden="true"
      className="inline-block h-9 rounded-md bg-paper-soft"
      style={{ width: DATE_RANGE_CONTROL_WIDTH_PX }}
    />
  );
}
