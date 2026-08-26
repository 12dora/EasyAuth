import { Button } from "../../../components/Button";
import { dateRangeFilter, enumFilter, type ColumnsType } from "../../../components/antd/AppTable";
import {
  actionsColumn,
  dateTimeColumn,
  serverColumn,
  statusColumn,
  textColumn,
  type StatusColumnOption,
} from "../../../components/antd/columns";
import type { Translator } from "../../../lib/status";
import {
  accessRequestStatusLabel,
  badgeToneForAccessRequestStatus,
  grantStatusLabel,
  healthStatusLabel,
} from "../../../lib/status";
import { ACCESS_GRANT_STATUSES, ACCESS_REQUEST_STATUSES } from "./operationQuery";
import {
  auditAppKey,
  auditPair,
  booleanValue,
  healthTone,
  numberValue,
  operationAuthorizationGroupSummary,
  operationDirectGrantSummary,
  type AccessRequestActionType,
  type OperationRow,
} from "./operationRow";

export interface AccessRequestColumnActions {
  disabled: boolean;
  onAction: (type: AccessRequestActionType, row: OperationRow) => void;
}

export interface AccessGrantColumnActions {
  disabled: boolean;
  onEmergencyRevoke: (row: OperationRow) => void;
}

/** 列 key -> 当前选中的筛选值(来自 URL), 交给 antd 做受控表头筛选。 */
export type OperationFilterValues = Record<string, string[]>;

export function operationColumns(
  section: string,
  t: Translator,
  filters: OperationFilterValues,
  accessRequestActions?: AccessRequestColumnActions,
  accessGrantActions?: AccessGrantColumnActions,
): ColumnsType<OperationRow> {
  if (section === "dependency-health") {
    return dependencyHealthColumns(t);
  }
  if (section === "audit") {
    return auditColumns(t, filters);
  }
  if (section === "access-grants") {
    return accessGrantColumns(t, filters, accessGrantActions);
  }
  return accessRequestColumns(t, filters, accessRequestActions);
}

function dependencyHealthColumns(t: Translator): ColumnsType<OperationRow> {
  // 依赖健康是一次性返回的数组, 筛选与排序都在客户端完成。
  return [
    textColumn<OperationRow>({
      key: "component",
      title: t("console.operations.column.component"),
      mono: true,
      filter: true,
      sorter: true,
      width: 240,
    }),
    statusColumn<OperationRow>({
      key: "status",
      title: t("common.status"),
      options: healthStatusOptions(t),
      width: 130,
    }),
    textColumn<OperationRow>({ key: "summary", title: t("console.operations.column.summary") }),
    textColumn<OperationRow>({ key: "error_summary", title: t("console.operations.column.error") }),
    dateTimeColumn<OperationRow>({ key: "last_checked_at", title: t("console.operations.column.checkedAt") }),
  ];
}

function auditColumns(t: Translator, filters: OperationFilterValues): ColumnsType<OperationRow> {
  // 审计行字段对齐后端 audit_api._audit_item; 审计行无 id, 故不展示 ID 列。
  return [
    textColumn<OperationRow>({ key: "event_type", title: t("console.operations.column.event"), width: 220 }),
    serverColumn(
      textColumn<OperationRow>({
        key: "actor",
        title: t("console.operations.column.actor"),
        getValue: (row) => auditPair(row.actor_type, row.actor_id),
        mono: true,
        filter: true,
        width: 200,
      }),
      filters.actor,
    ),
    textColumn<OperationRow>({
      key: "target",
      title: t("console.operations.column.target"),
      getValue: (row) => auditPair(row.target_type, row.target_id),
      mono: true,
    }),
    serverColumn(
      textColumn<OperationRow>({
        key: "app",
        title: t("common.app"),
        getValue: auditAppKey,
        mono: true,
        filter: true,
        width: 160,
      }),
      filters.app,
    ),
    serverColumn(
      {
        ...dateTimeColumn<OperationRow>({
          key: "created_at",
          title: t("console.operations.column.time"),
          sorter: false,
          width: 190,
        }),
        ...dateRangeFilter<OperationRow>(),
      },
      filters.created_at,
    ),
  ];
}

function accessGrantColumns(
  t: Translator,
  filters: OperationFilterValues,
  actions: AccessGrantColumnActions | undefined,
): ColumnsType<OperationRow> {
  const columns: ColumnsType<OperationRow> = [
    serverColumn(
      textColumn<OperationRow>({ key: "user_id", title: t("common.user"), mono: true, filter: true, width: 170 }),
      filters.user_id,
    ),
    serverColumn(
      textColumn<OperationRow>({ key: "app_key", title: t("common.app"), mono: true, filter: true, width: 150 }),
      filters.app_key,
    ),
    serverColumn(
      statusColumn<OperationRow>({
        key: "status",
        title: t("common.status"),
        options: grantStatusOptions(t),
        width: 130,
      }),
      filters.status,
    ),
    textColumn<OperationRow>({
      key: "authorization_groups",
      title: t("console.operations.column.authorizationGroups"),
      getValue: (row) => operationAuthorizationGroupSummary(t, row.authorization_groups),
    }),
    textColumn<OperationRow>({
      key: "direct_grants",
      title: t("console.operations.column.directGrants"),
      getValue: (row) => operationDirectGrantSummary(t, row.direct_grants),
    }),
    serverColumn(
      textColumn<OperationRow>({
        key: "version",
        title: t("console.operations.column.version"),
        getValue: (row) => `v${numberValue(row.version)}`,
        mono: true,
        filter: true,
        width: 130,
      }),
      filters.version,
    ),
    serverColumn(
      {
        ...textColumn<OperationRow>({
          key: "is_current",
          title: t("console.operations.column.isCurrent"),
          getValue: (row) => booleanValue(row.is_current),
          mono: true,
          width: 140,
        }),
        ...enumFilter<OperationRow>("is_current", [
          { label: t("console.operations.filter.currentOnly"), value: "true" },
          { label: t("console.operations.filter.historyOnly"), value: "false" },
        ]),
      },
      filters.is_current,
    ),
  ];
  if (actions) {
    columns.push(
      actionsColumn<OperationRow>({ render: (row) => renderAccessGrantActions(t, actions, row) }),
    );
  }
  return columns;
}

function renderAccessGrantActions(t: Translator, actions: AccessGrantColumnActions, row: OperationRow) {
  if (row.status !== "active" || row.is_current !== true) {
    return <span className="text-caption text-ink-faint">{t("common.none")}</span>;
  }
  return (
    <Button
      type="button"
      size="sm"
      variant="ghost-danger"
      disabled={actions.disabled}
      onClick={() => actions.onEmergencyRevoke(row)}
    >
      {t("console.operations.emergencyRevoke")}
    </Button>
  );
}

function accessRequestColumns(
  t: Translator,
  filters: OperationFilterValues,
  actions: AccessRequestColumnActions | undefined,
): ColumnsType<OperationRow> {
  const columns: ColumnsType<OperationRow> = [
    textColumn<OperationRow>({ key: "id", title: "ID", width: 90 }),
    serverColumn(
      textColumn<OperationRow>({ key: "user_id", title: t("common.user"), mono: true, filter: true, width: 170 }),
      filters.user_id,
    ),
    serverColumn(
      textColumn<OperationRow>({ key: "app_key", title: t("common.app"), mono: true, filter: true, width: 150 }),
      filters.app_key,
    ),
    serverColumn(
      statusColumn<OperationRow>({
        key: "status",
        title: t("common.status"),
        options: accessRequestStatusOptions(t),
        width: 130,
      }),
      filters.status,
    ),
    textColumn<OperationRow>({ key: "request_type", title: t("common.type"), width: 120 }),
    textColumn<OperationRow>({ key: "failure_reason", title: t("console.operations.column.failureReason") }),
    serverColumn(
      {
        ...dateTimeColumn<OperationRow>({
          key: "submitted_at",
          title: t("console.operations.column.submittedAt"),
          sorter: false,
          width: 190,
        }),
        ...dateRangeFilter<OperationRow>(),
      },
      filters.submitted_at,
    ),
  ];
  if (actions) {
    columns.push(
      actionsColumn<OperationRow>({ render: (row) => renderAccessRequestActions(t, actions, row) }),
    );
  }
  return columns;
}

// 待处理申请走审批动作; 授权失败申请走显式重试, 其余状态只读。
function renderAccessRequestActions(t: Translator, actions: AccessRequestColumnActions, row: OperationRow) {
  if (row.status === "submitted") {
    return (
      <>
        <Button type="button" size="sm" variant="ghost" disabled={actions.disabled} onClick={() => actions.onAction("approve", row)}>
          {t("approvals.approve")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost-danger"
          disabled={actions.disabled}
          onClick={() => actions.onAction("reject", row)}
        >
          {t("approvals.reject")}
        </Button>
        <Button type="button" size="sm" variant="ghost" disabled={actions.disabled} onClick={() => actions.onAction("reassign", row)}>
          {t("console.accessRequests.reassign")}
        </Button>
      </>
    );
  }
  if (row.status === "grant_failed") {
    return (
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={actions.disabled}
        onClick={() => actions.onAction("retry-grant", row)}
      >
        {t("console.operations.retryGrant")}
      </Button>
    );
  }
  return <span className="text-caption text-ink-faint">{t("common.none")}</span>;
}

function accessRequestStatusOptions(t: Translator): StatusColumnOption[] {
  return ACCESS_REQUEST_STATUSES.map((status) => ({
    value: status,
    label: accessRequestStatusLabel(t, status),
    tone: badgeToneForAccessRequestStatus(status),
  }));
}

function grantStatusOptions(t: Translator): StatusColumnOption[] {
  return ACCESS_GRANT_STATUSES.map((status) => ({
    value: status,
    label: grantStatusLabel(t, status),
    tone: status === "active" ? "evergreen" : "neutral",
  }));
}

const HEALTH_STATUSES = ["healthy", "warning", "unhealthy", "unknown"] as const;

function healthStatusOptions(t: Translator): StatusColumnOption[] {
  return HEALTH_STATUSES.map((status) => ({
    value: status,
    label: healthStatusLabel(t, status),
    tone: healthTone(status),
  }));
}
