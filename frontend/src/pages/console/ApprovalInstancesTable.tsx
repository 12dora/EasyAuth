import { Check } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { AppTable, type AppTableProps, type ColumnType, type ColumnsType } from "../../components/antd/AppTable";
import { dateTimeColumn, statusColumn, textColumn, type StatusColumnOption } from "../../components/antd/columns";
import { useI18n } from "../../i18n/I18nProvider";
import type { ApprovalInstanceRow } from "../../lib/domain";
import { APPROVAL_STATUS_LABEL_KEYS } from "../../lib/status";
import type { BadgeTone, Translator } from "../../lib/status";

export interface RedeliverActions {
  isDisabled: (row: ApprovalInstanceRow) => boolean;
  onRedeliver: (row: ApprovalInstanceRow) => void;
}

export function ApprovalInstancesTable({
  rows,
  isLoading,
  tableProps,
  actions,
}: {
  rows: ApprovalInstanceRow[];
  isLoading: boolean;
  tableProps: Pick<AppTableProps<ApprovalInstanceRow>, "pagination" | "onChange">;
  actions: RedeliverActions;
}) {
  const { t } = useI18n();

  return (
    <AppTable<ApprovalInstanceRow>
      {...tableProps}
      columns={instanceColumns(t, actions)}
      dataSource={rows}
      emptyTitle={t("console.operations.empty")}
      emptyDescription={t("console.operations.emptyDescription")}
      loading={isLoading}
      minWidth={1240}
      rowKey="instance_id"
    />
  );
}

function instanceColumns(t: Translator, actions: RedeliverActions): ColumnsType<ApprovalInstanceRow> {
  return [
    serverFiltered(
      textColumn<ApprovalInstanceRow>({
        key: "app_key",
        title: t("approvalInstances.column.app"),
        mono: true,
        filter: true,
        width: 150,
      }),
    ),
    textColumn<ApprovalInstanceRow>({
      key: "template_key",
      title: t("approvalInstances.column.template"),
      mono: true,
      width: 150,
    }),
    textColumn<ApprovalInstanceRow>({ key: "biz_key", title: t("approvalInstances.column.bizKey"), mono: true }),
    textColumn<ApprovalInstanceRow>({
      key: "originator_user_id",
      title: t("approvalInstances.column.originator"),
      mono: true,
      width: 160,
    }),
    // 失败原因没有独立的列, 沿用旧表格挂在状态徽章上的 title 提示。
    withTitle(
      serverFiltered(
        statusColumn<ApprovalInstanceRow>({
          key: "status",
          title: t("common.status"),
          options: approvalStatusOptions(t),
          width: 130,
        }),
      ),
      (row) => row.last_error || undefined,
    ),
    textColumn<ApprovalInstanceRow>({
      key: "dingtalk_process_instance_id",
      title: t("approvalInstances.column.dingtalkInstance"),
      mono: true,
      width: 180,
    }),
    {
      key: "delivery",
      title: t("approvalInstances.column.delivery"),
      width: 190,
      render: (_value: unknown, row: ApprovalInstanceRow) => <DeliveryCell t={t} row={row} actions={actions} />,
    },
    dateTimeColumn<ApprovalInstanceRow>({
      key: "created_at",
      title: t("approvalInstances.column.createdAt"),
      // 后端固定按 -created_at 排序, 没有 ordering 参数可用。
      sorter: false,
    }),
  ];
}

/**
 * 服务端筛选列: 后端已按 status / app_key 过滤当前页, 必须去掉列预设自带的
 * 客户端 `onFilter`, 否则 antd 会拿当前页再筛一次。
 */
function serverFiltered<T>(column: ColumnType<T>): ColumnType<T> {
  return { ...column, onFilter: undefined };
}

/** 给列预设的单元格补一个原生 title 提示, 渲染仍走预设。 */
function withTitle<T>(column: ColumnType<T>, getTitle: (record: T) => string | undefined): ColumnType<T> {
  const render = column.render;
  if (!render) {
    return column;
  }
  return {
    ...column,
    render: (value: unknown, record: T, index: number) => (
      <span title={getTitle(record)}>{render(value, record, index) as ReactNode}</span>
    ),
  };
}

function DeliveryCell({ t, row, actions }: { t: Translator; row: ApprovalInstanceRow; actions: RedeliverActions }) {
  switch (row.delivery_state) {
    case "delivered":
      return (
        <Badge tone="evergreen">
          <Check size={12} aria-hidden="true" />
          {t("approvalInstances.delivery.delivered")}
        </Badge>
      );
    case "failed":
      return (
        <span className="inline-flex items-center gap-1.5">
          <span title={row.delivery_last_error || undefined}>
            <Badge tone="signal">{t("approvalInstances.delivery.failed")}</Badge>
          </span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={actions.isDisabled(row)}
            onClick={() => actions.onRedeliver(row)}
          >
            {t("approvalInstances.redeliver")}
          </Button>
        </span>
      );
    case "skipped":
      return <Badge tone="faint">{t("approvalInstances.delivery.skipped")}</Badge>;
    case "pending":
      return <Badge tone="amber">{t("approvalInstances.delivery.pending")}</Badge>;
    default:
      return <span className="text-caption text-ink-faint">{t("common.none")}</span>;
  }
}

const APPROVAL_STATUS_TONES: Record<string, BadgeTone> = {
  approved: "evergreen",
  rejected: "signal",
  failed: "signal",
  canceled: "faint",
  // created / submitted 等推进中的状态用中性色。
};

function approvalStatusOptions(t: Translator): StatusColumnOption[] {
  return Object.entries(APPROVAL_STATUS_LABEL_KEYS).map(([status, key]) => ({
    value: status,
    label: t(key),
    tone: APPROVAL_STATUS_TONES[status] ?? "neutral",
  }));
}
