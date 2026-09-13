import { Button as AntdButton, DatePicker } from "antd";
import type { FilterDropdownProps } from "antd/es/table/interface";
import dayjs, { type Dayjs } from "dayjs";

import { useI18n } from "../../i18n/I18nProvider";
import type { Translator } from "../../lib/status";
import {
  DATE_RANGE_CONTROL_WIDTH_PX,
  decodeDateRange,
  encodeDateRange,
  type DateRangeControlProps,
  type DateRangeValue,
} from "./dateRange";

export type { DateRangeControlProps, DateRangeValue };
export { DATE_RANGE_CONTROL_WIDTH_PX, decodeDateRange, encodeDateRange };

/**
 * 全站唯一的日期范围控件: antd RangePicker, 预设近7天 / 近30天 / 本月。
 * 授权明细工具栏与表头 `dateRangeFilter` 都走这里, 不要再各写一份。
 *
 * 展示按日。写回 URL / 后端时在浏览器本地时区取当日 00:00:00 / 23:59:59,
 * 并以带偏移的 ISO 8601 序列化(`format("YYYY-MM-DDTHH:mm:ssZ")`)。
 * 回读取字符串里的日历日, 不把带 Z / 偏移的瞬间换算成浏览器当天,
 * 避免再确认时日期被挪一天。
 *
 * 本模块由 AppTable / 运营页 `React.lazy` 加载, 不要同步 import, 否则 DatePicker
 * 会回到同步 antd chunk。
 */
export function DateRangeControl({
  allowClear = true,
  ariaLabel,
  fromPlaceholder,
  getPopupContainer,
  onChange,
  size = "middle",
  toPlaceholder,
  value,
}: DateRangeControlProps) {
  const { t } = useI18n();
  const picker = (
    <DatePicker.RangePicker
      allowClear={allowClear}
      allowEmpty={[true, true]}
      format="YYYY-MM-DD"
      getPopupContainer={getPopupContainer}
      onChange={(dates) => onChange(fromPickerValue(dates))}
      placeholder={[fromPlaceholder ?? t("table.dateRange.from"), toPlaceholder ?? t("table.dateRange.to")]}
      presets={dateRangePresets(t)}
      size={size}
      style={{ width: DATE_RANGE_CONTROL_WIDTH_PX }}
      value={toPickerValue(value)}
    />
  );
  if (ariaLabel === undefined) {
    return picker;
  }
  return (
    <div aria-label={ariaLabel} role="group">
      {picker}
    </div>
  );
}

export function DateRangeFilterDropdown({
  clearFilters,
  confirm,
  fromLabel,
  selectedKeys,
  setSelectedKeys,
  toLabel,
}: FilterDropdownProps & { fromLabel?: string; toLabel?: string }) {
  const { t } = useI18n();

  return (
    // 下拉内部的键盘事件不能冒泡到表头, 否则空格/回车会触发排序。
    <div className="flex flex-col gap-2 p-2" onKeyDown={(event) => event.stopPropagation()}>
      <DateRangeControl
        fromPlaceholder={fromLabel}
        onChange={(range) => setSelectedKeys(encodeDateRange(range))}
        toPlaceholder={toLabel}
        value={decodeDateRange(selectedKeys)}
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

function dateRangePresets(t: Translator): { label: string; value: [Dayjs, Dayjs] }[] {
  const today = dayjs();
  return [
    { label: t("table.dateRange.preset.last7Days"), value: [today.subtract(6, "day"), today] },
    { label: t("table.dateRange.preset.last30Days"), value: [today.subtract(29, "day"), today] },
    { label: t("table.dateRange.preset.thisMonth"), value: [today.startOf("month"), today.endOf("month")] },
  ];
}

function toPickerValue(range: DateRangeValue): [Dayjs | null, Dayjs | null] | null {
  const from = parseDateRangeBound(range.from);
  const to = parseDateRangeBound(range.to);
  if (from === null && to === null) {
    return null;
  }
  return [from, to];
}

function fromPickerValue(dates: [Dayjs | null, Dayjs | null] | null): DateRangeValue {
  const [from, to] = dates ?? [null, null];
  return {
    from: from ? formatDateRangeBound(from, "from") : "",
    to: to ? formatDateRangeBound(to, "to") : "",
  };
}

/** ISO 日界字符串开头的日历日。 */
const DATE_BOUND_DATE = /^(\d{4}-\d{2}-\d{2})/;

/**
 * 从 URL / 筛选值解析日历日: 取 ISO 字符串的日期部分, 忽略时区换算。
 * `2026-09-13T23:59:59Z` 与 `2026-09-13T00:00:00+08:00` 都显示 9 月 13 日。
 */
export function parseDateRangeBound(raw: string): Dayjs | null {
  if (raw === "") {
    return null;
  }
  const datePart = DATE_BOUND_DATE.exec(raw)?.[1];
  const parsed = datePart === undefined ? dayjs(raw) : dayjs(`${datePart}T00:00:00`);
  return parsed.isValid() ? parsed : null;
}

/** 把日历日格式化为本地时区的日起/日止瞬时, 带偏移。 */
export function formatDateRangeBound(day: Dayjs, bound: "from" | "to"): string {
  const boundary = bound === "from" ? day.startOf("day") : day.endOf("day");
  return boundary.format("YYYY-MM-DDTHH:mm:ssZ");
}
