/**
 * 日期范围的纯数据契约: 编解码、宽度、控件 props。
 * 不含 DatePicker / dayjs, 表格与 URL 筛选可以同步引用, 不会把选择器打进同步包。
 */

/**
 * 起止时间; 空字符串表示这一端不限。
 * 写入 URL / 后端的是浏览器本地时区的日界, 带偏移的 ISO 8601
 * (`YYYY-MM-DDTHH:mm:ssZ`, 如 `2026-09-13T00:00:00+08:00`)。
 */
export interface DateRangeValue {
  from: string;
  to: string;
}

/** 工具栏与表头筛选共用的 RangePicker 宽度。 */
export const DATE_RANGE_CONTROL_WIDTH_PX = 260;

/** 起止两端编码进同一个筛选值时的分隔符。 */
const DATE_RANGE_SEPARATOR = "~";

/** `{ from, to }` -> antd 的筛选值(空区间为 `[]`, 即「未筛选」)。 */
export function encodeDateRange({ from, to }: DateRangeValue): string[] {
  return from === "" && to === "" ? [] : [`${from}${DATE_RANGE_SEPARATOR}${to}`];
}

/** antd 的筛选值 -> `{ from, to }`; 无值时两端都是空字符串。 */
export function decodeDateRange(values: readonly unknown[] | null | undefined): DateRangeValue {
  const [from = "", to = ""] = String(values?.[0] ?? "").split(DATE_RANGE_SEPARATOR);
  return { from, to };
}

export interface DateRangeControlProps {
  value: DateRangeValue;
  onChange: (value: DateRangeValue) => void;
  /** 套在选择器外层的无障碍名。 */
  ariaLabel?: string;
  fromPlaceholder?: string;
  toPlaceholder?: string;
  allowClear?: boolean;
  size?: "small" | "middle" | "large";
  getPopupContainer?: (node: HTMLElement) => HTMLElement;
}

export interface DateRangeFilterOptions {
  /** 覆盖两个输入框的占位; 默认走 i18n `table.dateRange.from` / `to`。 */
  fromLabel?: string;
  toLabel?: string;
}
