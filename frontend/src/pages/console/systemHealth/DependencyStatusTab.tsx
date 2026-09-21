import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, RefreshCcw } from "lucide-react";
import { useMemo } from "react";

import { AppTable, type ColumnsType } from "../../../components/antd/AppTable";
import {
  dateTimeColumn,
  statusColumn,
  textColumn,
  type StatusColumnOption,
} from "../../../components/antd/columns";
import { Button } from "../../../components/Button";
import { StatusBanner } from "../../../components/StatusBanner";
import { PageState } from "../../../components/ui/PageState";
import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonValue, ListPayload } from "../../../lib/api";
import { bindParse } from "../../../lib/domain/parse";
import { healthStatusLabel, type BadgeTone, type Translator } from "../../../lib/status";

const DEPENDENCIES_URL = "/console/api/v1/operations/system-health/dependencies";
const DEPENDENCY_CHECKS_URL = `${DEPENDENCIES_URL}/checks`;

/** 「立即检测」要把结果写回同一份缓存, 因此查询键只有这一个出处。 */
export const DEPENDENCIES_QUERY_KEY = ["console", "system-health", "dependencies"] as const;

/** 后端 operations_payloads.health_item 的行; 字段缺失即契约违约。 */
export interface DependencyHealthRow {
  component: string;
  status: string;
  summary: string;
  error_summary: string;
  last_checked_at: string | null;
}

/**
 * 「依赖状态」页签: 外部依赖的最近一次探测结果。
 *
 * 后端一次性返回全部依赖(非分页), 因此筛选、排序、分页都在客户端完成,
 * 与「用量监控」页签各自取数, 互不影响。
 */
export function DependencyStatusTab() {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: DEPENDENCIES_QUERY_KEY,
    queryFn: async (): Promise<DependencyHealthRow[]> =>
      dependencyHealthRows(await apiRequest<ListPayload<JsonValue>>(DEPENDENCIES_URL)),
  });
  const checkMutation = useDependencyCheckMutation();
  const rows = query.data ?? [];

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 className="text-base font-semibold text-ink">{t("systemHealth.dependencies.heading")}</h2>
          <p className="text-body leading-5 text-ink-soft">{t("systemHealth.dependencies.description")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="primary"
            icon={<Activity size={16} />}
            loading={checkMutation.isPending}
            onClick={() => checkMutation.mutate()}
          >
            {t("systemHealth.dependencies.runCheck")}
          </Button>
          <Button
            type="button"
            icon={<RefreshCcw size={16} />}
            loading={query.isFetching}
            onClick={() => void query.refetch()}
          >
            {t("common.refresh")}
          </Button>
        </div>
      </div>
      {/* 已有数据时故障降级为横幅, 一行都没有时才把整块换成失败态。 */}
      {query.error && rows.length > 0 ? (
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("systemHealth.dependencies.loadFailed")}
          message={query.error.message}
        />
      ) : null}
      {query.error && rows.length === 0 ? (
        <PageState
          tone="signal"
          title={t("systemHealth.dependencies.loadFailed")}
          description={query.error.message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <DependencyStatusTable rows={rows} isLoading={query.isLoading} />
      )}
    </section>
  );
}

function DependencyStatusTable({ isLoading, rows }: { isLoading: boolean; rows: DependencyHealthRow[] }) {
  const { t } = useI18n();
  // 列定义每次渲染重建会让 antd 整表重挂(表头筛选下拉随之关闭), 因此按真正的输入缓存。
  const columns = useMemo(() => dependencyColumns(t), [t]);

  return (
    <AppTable<DependencyHealthRow>
      ariaLabel={t("systemHealth.dependencies.heading")}
      columns={columns}
      dataSource={rows}
      emptyTitle={t("systemHealth.dependencies.empty")}
      emptyDescription={t("systemHealth.dependencies.emptyDescription")}
      loading={isLoading}
      rowKey={(row) => row.component}
    />
  );
}

function useDependencyCheckMutation() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (): Promise<DependencyHealthRow[]> =>
      dependencyHealthRows(await apiRequest<ListPayload<JsonValue>>(DEPENDENCY_CHECKS_URL, { method: "POST" })),
    // 检测结果直接写回查询缓存, 省掉一次列表往返; 形状必须与 queryFn 一致, 否则表格读不出行。
    onSuccess: (rows) => {
      queryClient.setQueryData(DEPENDENCIES_QUERY_KEY, rows);
    },
    onError: (error: Error) => {
      toast.error(t("systemHealth.dependencies.runCheckFailed"), error.message);
    },
  });
}

function dependencyColumns(t: Translator): ColumnsType<DependencyHealthRow> {
  return [
    textColumn<DependencyHealthRow>({
      key: "component",
      title: t("systemHealth.dependencies.column.component"),
      mono: true,
      filter: true,
      sorter: true,
      width: 240,
    }),
    statusColumn<DependencyHealthRow>({
      key: "status",
      title: t("common.status"),
      options: healthStatusOptions(t),
      sorter: true,
      width: 130,
    }),
    textColumn<DependencyHealthRow>({
      key: "summary",
      title: t("systemHealth.dependencies.column.summary"),
      sorter: true,
    }),
    textColumn<DependencyHealthRow>({
      key: "error_summary",
      title: t("systemHealth.dependencies.column.error"),
      sorter: true,
    }),
    dateTimeColumn<DependencyHealthRow>({
      key: "last_checked_at",
      title: t("systemHealth.dependencies.column.checkedAt"),
    }),
  ];
}

/** 与后端 health_models 的取值一一对应; 顺序即状态筛选下拉与客户端排序的顺序。 */
const HEALTH_STATUSES = ["healthy", "warning", "unhealthy", "unknown"] as const;

function healthStatusOptions(t: Translator): StatusColumnOption[] {
  return HEALTH_STATUSES.map((status) => ({
    value: status,
    label: healthStatusLabel(t, status),
    tone: healthTone(status),
  }));
}

function healthTone(status: string): BadgeTone {
  if (status === "healthy") {
    return "evergreen";
  }
  if (status === "warning") {
    return "amber";
  }
  if (status === "unknown") {
    return "neutral";
  }
  return "signal";
}

class DependencyHealthContractError extends Error {
  constructor(field: string) {
    super(`Dependency health contract violation: ${field}`);
    this.name = "DependencyHealthContractError";
  }
}

const { requireRecord, requireString, requireNullableString } = bindParse({
  fail: (path) => new DependencyHealthContractError(path),
});

/**
 * 载荷 -> 行。解析放在取数阶段: 字段缺失直接变成查询/变更错误, 走页面已有的失败态,
 * 不在渲染期炸表格, 也不静默兜底。
 */
function dependencyHealthRows(payload: ListPayload<JsonValue>): DependencyHealthRow[] {
  return itemsFromPayload<JsonValue>(payload).map(parseDependencyHealthRow);
}

function parseDependencyHealthRow(raw: JsonValue): DependencyHealthRow {
  const source = requireRecord(raw, "dependency");
  return {
    component: requireString(source.component, "dependency.component"),
    status: requireString(source.status, "dependency.status"),
    summary: requireString(source.summary, "dependency.summary"),
    error_summary: requireString(source.error_summary, "dependency.error_summary"),
    last_checked_at: requireNullableString(source.last_checked_at, "dependency.last_checked_at"),
  };
}
