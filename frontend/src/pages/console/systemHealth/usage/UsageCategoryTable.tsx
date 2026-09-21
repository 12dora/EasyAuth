import { AppTable, type ColumnsType } from "../../../../components/antd/AppTable";
import { Badge } from "../../../../components/Badge";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { Locale } from "../../../../i18n/messages";
import type { Translator } from "../../../../lib/status";
import { USAGE_SERIES_COLOR } from "./usageChartTheme";
import { formatUsageCount, formatUsagePercent, sharePercent } from "./usageMeterModel";
import { usageCategoryLabel, type UsageCategoryTotal } from "./usageTypes";

export interface UsageCategoryTableProps {
  categories: readonly UsageCategoryTotal[];
  isLoading: boolean;
}

/** 调用次数降序; 次数相同时按分类键排, 保证两次渲染的顺序一致。 */
export function sortUsageCategories(categories: readonly UsageCategoryTotal[]): UsageCategoryTotal[] {
  return [...categories].sort((left, right) =>
    right.count === left.count ? left.category.localeCompare(right.category) : right.count - left.count,
  );
}

function rowKey(row: UsageCategoryTotal): string {
  return `${row.source}:${row.category}`;
}

export function UsageCategoryTable({ categories, isLoading }: UsageCategoryTableProps) {
  const { t, locale } = useI18n();
  const rows = sortUsageCategories(categories);
  const total = rows.reduce((sum, row) => sum + row.count, 0);

  return (
    <PanelSurface padding="lg" className="space-y-3">
      <h3 className="text-sm font-semibold leading-tight text-ink">{t("usage.category.title")}</h3>
      <AppTable<UsageCategoryTotal>
        ariaLabel={t("usage.category.tableLabel")}
        columns={categoryColumns(t, locale, total)}
        dataSource={rows}
        emptyDescription={t("usage.category.emptyDescription")}
        emptyTitle={t("usage.category.emptyTitle")}
        loading={isLoading}
        minWidth={880}
        pagination={false}
        rowKey={rowKey}
      />
    </PanelSurface>
  );
}

function categoryColumns(t: Translator, locale: Locale, total: number): ColumnsType<UsageCategoryTotal> {
  return [
    {
      dataIndex: "category",
      key: "label",
      title: t("usage.category.label"),
      width: 240,
      render: (_value, row) => (
        <div className="min-w-0">
          <p className="truncate text-body leading-5 text-ink">{usageCategoryLabel(row, locale === "en")}</p>
          <p className="truncate font-mono text-micro leading-4 text-ink-faint">{row.category}</p>
        </div>
      ),
    },
    {
      dataIndex: "source",
      key: "source",
      title: t("usage.category.source"),
      width: 120,
      render: (_value, row) => (
        <Badge tone={row.source === "authentik" ? "bond" : "neutral"}>
          {t(row.source === "authentik" ? "usage.category.source.authentik" : "usage.category.source.easyauth")}
        </Badge>
      ),
    },
    {
      dataIndex: "billed",
      key: "billed",
      title: t("usage.category.billed"),
      width: 100,
      render: (_value, row) => (
        <Badge tone={row.billed ? "amber" : "faint"}>
          {t(row.billed ? "usage.category.billedYes" : "usage.category.billedNo")}
        </Badge>
      ),
    },
    {
      dataIndex: "priority",
      key: "priority",
      title: t("usage.category.priority"),
      width: 100,
      render: (_value, row) =>
        row.priority === null ? (
          <span className="text-body text-ink-faint">{t("common.none")}</span>
        ) : (
          <Badge tone={row.priority === "p0" ? "bond" : row.priority === "p1" ? "neutral" : "faint"}>
            {row.priority.toUpperCase()}
          </Badge>
        ),
    },
    {
      align: "right",
      dataIndex: "count",
      key: "count",
      title: t("usage.category.count"),
      width: 120,
      render: (_value, row) => (
        <span className="font-mono text-body text-ink">{formatUsageCount(row.count, locale)}</span>
      ),
    },
    {
      align: "right",
      dataIndex: "blocked",
      key: "blocked",
      title: t("usage.category.blocked"),
      width: 110,
      render: (_value, row) => (
        <span className={`font-mono text-body ${row.blocked > 0 ? "text-signal" : "text-ink-faint"}`}>
          {formatUsageCount(row.blocked, locale)}
        </span>
      ),
    },
    {
      dataIndex: "count",
      key: "share",
      title: t("usage.category.share"),
      width: 160,
      render: (_value, row) => <ShareBar percent={sharePercent(row.count, total)} />,
    },
  ];
}

/** 占比条: 单一色相的量级编码, 数值就写在旁边, 不靠颜色深浅去读。 */
function ShareBar({ percent }: { percent: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="h-1.5 min-w-12 flex-1 overflow-hidden rounded-full bg-ink/10">
        <span
          className="block h-full rounded-r-full transition-[width] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none"
          style={{ width: `${percent}%`, background: USAGE_SERIES_COLOR.api_billed }}
        />
      </span>
      <span className="w-10 shrink-0 text-right font-mono text-caption text-ink-soft">
        {formatUsagePercent(percent)}
      </span>
    </div>
  );
}
