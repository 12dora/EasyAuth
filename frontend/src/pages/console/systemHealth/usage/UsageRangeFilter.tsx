import { DateRangeControl } from "../../../../components/antd/AppTable";
import { Button } from "../../../../components/Button";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../i18n/messages";
import {
  DEFAULT_USAGE_RANGE_KEY,
  USAGE_QUICK_RANGE_KEYS,
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
 */
export function UsageRangeFilter({ range, onChange }: UsageRangeFilterProps) {
  const { t } = useI18n();

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("usage.range.label")}>
      {USAGE_QUICK_RANGE_KEYS.map((key) => (
        <Button
          aria-pressed={range.key === key}
          key={key}
          onClick={() => onChange(key)}
          size="sm"
          variant={range.key === key ? "primary" : "outline"}
        >
          {t(QUICK_RANGE_LABEL_KEYS[key])}
        </Button>
      ))}
      <DateRangeControl
        ariaLabel={t("usage.range.custom")}
        size="small"
        value={{ from: range.from, to: range.to }}
        onChange={(value) => {
          // 两端都清空 = 回到默认区间; 只给一端也不是合法请求, 交给 resolveUsageRange 兜住。
          if (value.from === "" && value.to === "") {
            onChange(DEFAULT_USAGE_RANGE_KEY);
            return;
          }
          onChange("custom", calendarDay(value.from), calendarDay(value.to));
        }}
      />
      <span className="ml-auto font-mono text-caption leading-4 text-ink-faint">
        {t("usage.range.summary", { from: range.from, to: range.to })}
      </span>
    </div>
  );
}

/** DateRangeControl 回传的是带偏移的日界 ISO, URL 与后端只要日历日。 */
function calendarDay(bound: string): string {
  return bound.slice(0, 10);
}
