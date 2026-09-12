import { Check } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "../../components/Badge";
import {
  AppTable,
  type AppTableProps,
  type ColumnType,
  type ColumnsType,
  type ServerSortState,
} from "../../components/antd/AppTable";
import { textFilter } from "../../components/antd/AppTable";
import {
  MONO_TEXT_CLASS,
  RowActionButton,
  dateTimeColumn,
  serverColumn,
  serverSortColumn,
  statusColumn,
  textColumn,
  personColumn,
  type StatusColumnOption,
} from "../../components/antd/columns";
import { useI18n } from "../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../lib/appDisplayName";
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
  filters,
  sort,
  actions,
}: {
  rows: ApprovalInstanceRow[];
  isLoading: boolean;
  tableProps: Pick<AppTableProps<ApprovalInstanceRow>, "pagination" | "onChange">;
  /** 列 key -> 已选筛选值, 来自 useServerTable 的查询状态。 */
  filters: Record<string, string[]>;
  /** 当前排序, 来自同一份查询状态(应用/模板/状态/创建时间四列在后端排)。 */
  sort: ServerSortState;
  actions: RedeliverActions;
}) {
  const { t } = useI18n();

  return (
    <AppTable<ApprovalInstanceRow>
      {...tableProps}
      columns={instanceColumns(t, filters, sort, actions)}
      dataSource={rows}
      emptyTitle={t("console.operations.empty")}
      emptyDescription={t("console.operations.emptyDescription")}
      loading={isLoading}
      minWidth={1320}
      rowKey="instance_id"
    />
  );
}

/**
 * 排序在后端(`ordering=app_key|template|status|created_at`), 对应四列过
 * `serverSortColumn`; 业务键 / 发起人 / 钉钉实例 / 投递状态后端排不了, 不给 sorter。
 */
function instanceColumns(
  t: Translator,
  filters: Record<string, string[]>,
  sort: ServerSortState,
  actions: RedeliverActions,
): ColumnsType<ApprovalInstanceRow> {
  return [
    // 应用按展示名(别名 + 技术名)呈现, app_key 退到第二行: 筛选与排序仍按 app_key 走后端。
    serverSortColumn(
      serverColumn(
        {
          key: "app_key",
          title: t("approvalInstances.column.app"),
          width: 190,
          render: (_value: unknown, row: ApprovalInstanceRow) => (
            <div className="flex min-w-0 flex-col gap-1">
              <strong className="truncate">{formatAppDisplayName({ name: row.app_name, alias: row.app_alias })}</strong>
              <code className={`${MONO_TEXT_CLASS} truncate`}>{row.app_key}</code>
            </div>
          ),
          ...textFilter<ApprovalInstanceRow>("app_key", { getValue: (row) => row.app_key }),
        },
        filters.app_key,
      ),
      sort,
    ),
    serverSortColumn(
      textColumn<ApprovalInstanceRow>({
        key: "template_key",
        title: t("approvalInstances.column.template"),
        mono: true,
        width: 150,
      }),
      sort,
    ),
    textColumn<ApprovalInstanceRow>({ key: "biz_key", title: t("approvalInstances.column.bizKey"), mono: true }),
    personColumn<ApprovalInstanceRow>({
      key: "originator_user_id",
      title: t("approvalInstances.column.originator"),
      t,
      getName: (row) => row.originator_name,
      getUserId: (row) => row.originator_user_id,
      getDepartment: (row) => row.originator_department,
      width: 190,
    }),
    // 失败原因没有独立的列, 沿用旧表格挂在状态徽章上的 title 提示。
    withTitle(
      serverSortColumn(
        serverColumn(
          statusColumn<ApprovalInstanceRow>({
            key: "status",
            title: t("common.status"),
            options: approvalStatusOptions(t),
            width: 130,
          }),
          filters.status,
        ),
        sort,
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
    serverSortColumn(
      dateTimeColumn<ApprovalInstanceRow>({
        key: "created_at",
        title: t("approvalInstances.column.createdAt"),
        // 预设自带的时间戳比较函数只会重排当前页, 由 serverSortColumn 换成服务端排序。
        sorter: false,
      }),
      sort,
    ),
  ];
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
          <RowActionButton
            type="button"
            disabled={actions.isDisabled(row)}
            onClick={() => actions.onRedeliver(row)}
          >
            {t("approvalInstances.redeliver")}
          </RowActionButton>
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
