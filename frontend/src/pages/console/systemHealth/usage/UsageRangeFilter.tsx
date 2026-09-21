import { useState } from "react";

import { DateRangeControl, type DateRangeValue } from "../../../../components/antd/AppTable";
import { Button } from "../../../../components/Button";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../i18n/messages";
import {
  DEFAULT_USAGE_RANGE_KEY,
  USAGE_QUICK_RANGE_KEYS,
  USAGE_RANGE_MAX_DAYS,
  calendarDayCount,
  isCalendarDay,
  type UsageQuickRangeKey,
  type UsageRange,
  type UsageRangeKey,
} from "./usageRange";

const QUICK_RANGE_LABEL_KEYS: Record<UsageQuickRangeKey, MessageKey> = {
  today: "usage.range.today",
  yesterday: "usage.range.yesterday",
  week: "usage.range.week",
  month: "usage.range.month",
  last_month: "usage.range.last_month",
};

export interface UsageRangeFilterProps {
  range: UsageRange;
  onChange: (key: UsageRangeKey, from?: string, to?: string) => void;
}

/**
 * 图表上方唯一的一排筛选: 快捷区间按钮 + 自定义区间。
 *
 * 筛选只在这里出现一次, 下方所有图表与表格都按同一个区间取数,
 * 不给单张图表再挂自己的时间选择。
 *
 * 正在选的自定义区间(只填了一端, 或者跨度超过后端上限)只留在本地 state:
 * URL 只承载"两端都合法且可查"的区间, 因此选到一半不会被 resolveUsageRange
 * 回落成"今天", 选择过程也不会被自己写回的 URL 打断。
 */
export function UsageRangeFilter({ range, onChange }: UsageRangeFilterProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<DateRangeValue | null>(null);
  const [tooLong, setTooLong] = useState(false);

  const selectQuickRange = (key: UsageQuickRangeKey) => {
    setDraft(null);
    setTooLong(false);
    onChange(key);
  };

  const selectCustomRange = (value: DateRangeValue) => {
    const from = calendarDay(value.from);
    const to = calendarDay(value.to);
    // 两端都清空 = 回到默认区间。
    if (from === "" && to === "") {
      setDraft(null);
      setTooLong(false);
      onChange(DEFAULT_USAGE_RANGE_KEY);
      return;
    }
    // 只给了一端: 还没构成一次合法请求, 留在本地等另一端。
    if (!isCalendarDay(from) || !isCalendarDay(to)) {
      setDraft({ from, to });
      setTooLong(false);
      return;
    }
    const start = from <= to ? from : to;
    const end = from <= to ? to : from;
    if (calendarDayCount(start, end) > USAGE_RANGE_MAX_DAYS) {
      setDraft({ from, to });
      setTooLong(true);
      return;
    }
    setDraft(null);
    setTooLong(false);
    onChange("custom", start, end);
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("usage.range.label")}>
        {USAGE_QUICK_RANGE_KEYS.map((key) => (
          <Button
            aria-pressed={range.key === key && draft === null}
            key={key}
            onClick={() => selectQuickRange(key)}
            size="sm"
            variant={range.key === key && draft === null ? "primary" : "outline"}
          >
            {t(QUICK_RANGE_LABEL_KEYS[key])}
          </Button>
        ))}
        <DateRangeControl
          ariaLabel={t("usage.range.custom")}
          size="small"
          value={draft ?? { from: range.from, to: range.to }}
          onChange={selectCustomRange}
        />
        <span className="ml-auto font-mono text-caption leading-4 text-ink-faint">
          {t("usage.range.summary", { from: range.from, to: range.to })}
        </span>
      </div>
      {tooLong ? (
        <p className="text-caption leading-4 text-signal" role="alert">
          {t("usage.range.tooLong", { max: USAGE_RANGE_MAX_DAYS })}
        </p>
      ) : null}
    </div>
  );
}

/** DateRangeControl 回传的是带偏移的日界 ISO, URL 与后端只要日历日。 */
function calendarDay(bound: string): string {
  return bound.slice(0, 10);
}
