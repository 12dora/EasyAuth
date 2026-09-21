import { useState } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";

import { useI18n } from "../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../i18n/messages";
import { UsageChartTooltip } from "./UsageChartTooltip";
import {
  USAGE_SERIES_LABEL_KEYS,
  USAGE_STACK_SERIES,
  formatAxisCount,
  prefersReducedMotion,
  type UsageChartRow,
  type UsageStackSeriesKey,
} from "./usageChartModel";
import { USAGE_CHART_MARKS, USAGE_SERIES_COLOR, USAGE_SINGLE_SERIES_COLOR } from "./usageChartTheme";

const ANIMATION_MS = 600;
const MAIN_CHART_HEIGHT = 260;
const SMALL_CHART_HEIGHT = 132;

const AXIS_TICK = { fill: USAGE_CHART_MARKS.axisTextColor, fontSize: USAGE_CHART_MARKS.tickFontSize };

/** 数据端 4px 圆角, 基线一侧保持方角。 */
const DATA_END_RADIUS: [number, number, number, number] = [4, 4, 0, 0];

export interface UsageTrendChartImplProps {
  rows: UsageChartRow[];
  /** 重新取数时整块降不透明度, 保持上一帧, 不塌成骨架屏。 */
  dimmed: boolean;
}

/**
 * 趋势图本体(recharts, 独立异步 chunk)。
 *
 * 主图只画 API 的三段堆叠 —— 部分到整体用堆叠柱; Webhook / Stream / 被拒绝三条
 * 量级完全不同的序列各占一张共用 X 轴的小图, 而不是挤在同一张图上配第二条 Y 轴
 * (双 Y 轴会凭空造出一种并不存在的相关性)。
 */
export default function UsageTrendChartImpl({ rows, dimmed }: UsageTrendChartImplProps) {
  const { t, locale } = useI18n();
  const [hidden, setHidden] = useState<UsageStackSeriesKey[]>([]);
  const animate = !prefersReducedMotion();

  return (
    <div className={`space-y-4 transition-opacity duration-300 ${dimmed ? "opacity-60" : "opacity-100"}`}>
      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-caption font-semibold leading-4 text-ink">{t("usage.trend.apiTitle")}</h4>
          <StackLegend
            hidden={hidden}
            onToggle={(key) =>
              setHidden((previous) =>
                previous.includes(key) ? previous.filter((item) => item !== key) : [...previous, key],
              )
            }
          />
        </div>
        <ResponsiveContainer width="100%" height={MAIN_CHART_HEIGHT}>
          <ComposedChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={USAGE_CHART_MARKS.gridColor} vertical={false} />
            <XAxis
              axisLine={{ stroke: USAGE_CHART_MARKS.gridColor }}
              dataKey="label"
              interval="preserveStartEnd"
              minTickGap={18}
              tick={AXIS_TICK}
              tickLine={false}
            />
            <YAxis
              allowDecimals={false}
              axisLine={false}
              tick={AXIS_TICK}
              tickFormatter={(value: number) => formatAxisCount(value, locale)}
              tickLine={false}
              width={52}
            />
            <Tooltip content={renderUsageTooltip} cursor={{ fill: "rgb(15 23 42 / 0.05)" }} />
            {USAGE_STACK_SERIES.filter((key) => !hidden.includes(key)).map((key, index, visible) => (
              <Bar
                animationDuration={ANIMATION_MS}
                dataKey={key}
                fill={USAGE_SERIES_COLOR[key]}
                isAnimationActive={animate}
                key={key}
                maxBarSize={USAGE_CHART_MARKS.barMaxWidth}
                radius={index === visible.length - 1 ? DATA_END_RADIUS : undefined}
                stackId="api"
                stroke={USAGE_CHART_MARKS.surface}
                strokeWidth={USAGE_CHART_MARKS.stackGap}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <SmallMultiple color={USAGE_SINGLE_SERIES_COLOR} dataKey="webhook" kind="area" rows={rows} />
        <SmallMultiple color={USAGE_SINGLE_SERIES_COLOR} dataKey="stream" kind="area" rows={rows} />
        <SmallMultiple color={USAGE_SERIES_COLOR.blocked} dataKey="blocked" kind="bar" rows={rows} />
      </div>
    </div>
  );
}

const SMALL_TITLE_KEYS: Record<string, MessageKey> = {
  webhook: "usage.trend.webhookTitle",
  stream: "usage.trend.streamTitle",
  blocked: "usage.trend.blockedTitle",
};

/** 与主图共用 X 轴刻度与悬浮卡的单序列小图。 */
function SmallMultiple({
  color,
  dataKey,
  kind,
  rows,
}: {
  color: string;
  dataKey: "webhook" | "stream" | "blocked";
  kind: "area" | "bar";
  rows: UsageChartRow[];
}) {
  const { t, locale } = useI18n();
  const animate = !prefersReducedMotion();

  return (
    <div>
      <h4 className="mb-2 text-caption font-semibold leading-4 text-ink">{t(SMALL_TITLE_KEYS[dataKey])}</h4>
      <ResponsiveContainer width="100%" height={SMALL_CHART_HEIGHT}>
        <ComposedChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={USAGE_CHART_MARKS.gridColor} vertical={false} />
          <XAxis
            axisLine={{ stroke: USAGE_CHART_MARKS.gridColor }}
            dataKey="label"
            interval="preserveStartEnd"
            minTickGap={24}
            tick={AXIS_TICK}
            tickLine={false}
          />
          <YAxis
            allowDecimals={false}
            axisLine={false}
            tick={AXIS_TICK}
            tickCount={3}
            tickFormatter={(value: number) => formatAxisCount(value, locale)}
            tickLine={false}
            width={40}
          />
          <Tooltip
            content={renderUsageTooltip}
            cursor={
              kind === "bar"
                ? { fill: "rgb(15 23 42 / 0.05)" }
                : { stroke: "rgb(15 23 42 / 0.25)", strokeWidth: 1 }
            }
          />
          {kind === "area" ? (
            <Area
              activeDot={{ r: USAGE_CHART_MARKS.dotRadius, stroke: USAGE_CHART_MARKS.surface, strokeWidth: 2 }}
              animationDuration={ANIMATION_MS}
              dataKey={dataKey}
              dot={false}
              fill={color}
              fillOpacity={0.1}
              isAnimationActive={animate}
              stroke={color}
              strokeWidth={USAGE_CHART_MARKS.lineWidth}
              type="monotone"
            />
          ) : (
            <Bar
              animationDuration={ANIMATION_MS}
              dataKey={dataKey}
              fill={color}
              isAnimationActive={animate}
              maxBarSize={USAGE_CHART_MARKS.barMaxWidth}
              radius={DATA_END_RADIUS}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** 图例即开关: 点一下把该段从堆叠里摘掉, 其余段的颜色不变(颜色跟着序列走, 不跟着位次)。 */
function StackLegend({
  hidden,
  onToggle,
}: {
  hidden: UsageStackSeriesKey[];
  onToggle: (key: UsageStackSeriesKey) => void;
}) {
  const { t } = useI18n();

  return (
    <div className="flex flex-wrap items-center gap-3" role="group" aria-label={t("usage.trend.legendHint")}>
      {USAGE_STACK_SERIES.map((key) => {
        const isHidden = hidden.includes(key);
        return (
          <button
            aria-pressed={!isHidden}
            className={`inline-flex items-center gap-1.5 text-caption leading-4 transition-colors ${
              isHidden ? "text-ink-faint" : "text-ink-soft hover:text-ink"
            }`}
            key={key}
            onClick={() => onToggle(key)}
            type="button"
          >
            <span
              aria-hidden="true"
              className="size-2 shrink-0 rounded-[2px]"
              style={{
                background: isHidden ? "transparent" : USAGE_SERIES_COLOR[key],
                boxShadow: isHidden ? `inset 0 0 0 1px ${USAGE_SERIES_COLOR[key]}` : undefined,
              }}
            />
            {t(USAGE_SERIES_LABEL_KEYS[key])}
          </button>
        );
      })}
    </div>
  );
}

function renderUsageTooltip(props: TooltipProps<number, string>) {
  const row = props.payload?.[0]?.payload as UsageChartRow | undefined;
  return <UsageChartTooltip active={props.active} payload={row ? [{ payload: row }] : []} />;
}
