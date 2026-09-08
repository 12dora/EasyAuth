import { dateRangeFilter, textFilter, type ColumnType, type ColumnsType } from "../../../components/antd/AppTable";
import {
  MONO_TEXT_CLASS,
  RowActionButton,
  actionsColumn,
  dateTimeColumn,
  serverColumn,
  statusColumn,
  textColumn,
  userColumn,
  type StatusColumnOption,
} from "../../../components/antd/columns";
import { GrantExpiryCell } from "../../../components/grants/GrantExpiryCell";
import { GrantPermissionsCell } from "../../../components/grants/GrantPermissionsCell";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import type { AccessGrantRow } from "../../../lib/domain/accessGrantRow";
import { formatGrantGroupNames } from "../../../lib/grantMembership";
import type { Translator } from "../../../lib/status";
import {
  accessRequestStatusLabel,
  badgeToneForAccessRequestStatus,
  grantStatusLabel,
  healthStatusLabel,
} from "../../../lib/status";
import { requestTypeLabel } from "../../portal/components/portalApprovalFacts";
import { ACCESS_GRANT_STATUSES, ACCESS_REQUEST_STATUSES } from "./operationQuery";
import {
  auditAppKey,
  auditPair,
  healthTone,
  operationAppDisplayName,
  operationApproverNames,
  type AccessRequestActionType,
  type OperationRow,
} from "./operationRow";

export interface AccessRequestColumnActions {
  disabled: boolean;
  onAction: (type: AccessRequestActionType, row: OperationRow) => void;
}

export interface AccessGrantColumnActions {
  disabled: boolean;
  onEmergencyRevoke: (row: AccessGrantRow) => void;
}

/** 列 key -> 当前选中的筛选值(来自 URL), 交给 antd 做受控表头筛选。 */
export type OperationFilterValues = Record<string, string[]>;

/** 授权明细以外的分区(申请 / 审计 / 依赖健康)共用松散的运营行类型。 */
export function operationColumns(
  section: string,
  t: Translator,
  filters: OperationFilterValues,
  accessRequestActions?: AccessRequestColumnActions,
): ColumnsType<OperationRow> {
  if (section === "dependency-health") {
    return dependencyHealthColumns(t);
  }
  if (section === "audit") {
    return auditColumns(t, filters);
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

/**
 * 应用列: 展示名(`别名 (技术名)`)在上、app_key 在下。
 *
 * 与 userColumn 同构 —— 管理员按名字找应用, 但排查问题时又要能一眼读到 key,
 * 因此两行都给, 而不是只留一个裸 key。筛选仍按 app_key 走服务端。
 */
function appColumn<T>({
  getAppKey,
  getDisplayName,
  title,
  width = 200,
}: {
  getAppKey: (record: T) => string;
  getDisplayName: (record: T) => string;
  title: string;
  width?: number;
}): ColumnType<T> {
  return {
    key: "app_key",
    title,
    width,
    render: (_value: unknown, record: T) => (
      <div className="flex min-w-0 flex-col gap-1">
        <strong className="truncate">{getDisplayName(record)}</strong>
        <code className={`${MONO_TEXT_CLASS} truncate`}>{getAppKey(record)}</code>
      </div>
    ),
    ...textFilter<T>("app_key", { getValue: getAppKey }),
  };
}

/**
 * 授权明细列。
 *
 * 行由 `parseAccessGrantRow` 按后端共享序列化器解析, 因此这里的字段都是必填的:
 * 用户与应用按姓名/别名展示, 权限组、权限详情、过期时间三列与门户「我的权限」同源。
 * 版本号与「当前版本」不再单独占列 —— 列表默认只给当前版本, 历史版本由表格上方的
 * 开关控制。
 */
export function accessGrantColumns(
  t: Translator,
  filters: OperationFilterValues,
  actions: AccessGrantColumnActions | undefined,
): ColumnsType<AccessGrantRow> {
  const columns: ColumnsType<AccessGrantRow> = [
    serverColumn(
      userColumn<AccessGrantRow>({
        key: "user_id",
        title: t("common.user"),
        getName: (row) => row.user_name,
        getUserId: (row) => row.user_id,
        filter: true,
        width: 200,
      }),
      filters.user_id,
    ),
    serverColumn(
      appColumn<AccessGrantRow>({
        title: t("common.app"),
        getDisplayName: (row) => formatAppDisplayName({ name: row.app_name, alias: row.app_alias }),
        getAppKey: (row) => row.app_key,
      }),
      filters.app_key,
    ),
    serverColumn(
      statusColumn<AccessGrantRow>({
        key: "status",
        title: t("common.status"),
        options: grantStatusOptions(t),
        width: 130,
      }),
      filters.status,
    ),
    textColumn<AccessGrantRow>({
      key: "groups",
      title: t("console.operations.column.groups"),
      getValue: (row) => formatGrantGroupNames(row.groups),
      ellipsis: false,
      width: 200,
    }),
    {
      key: "permission_details",
      title: t("console.operations.column.permissionDetails"),
      width: 140,
      render: (_value: unknown, row: AccessGrantRow) => <GrantPermissionsCell row={row} />,
    },
    {
      key: "grant_expires_at",
      title: t("console.operations.column.expiresAt"),
      width: 210,
      render: (_value: unknown, row: AccessGrantRow) => (
        <GrantExpiryCell grantType={row.grant_type} expiresAt={row.grant_expires_at} />
      ),
    },
  ];
  if (actions) {
    columns.push(
      actionsColumn<AccessGrantRow>({ width: 140, render: (row) => renderAccessGrantActions(t, actions, row) }),
    );
  }
  return columns;
}

function renderAccessGrantActions(t: Translator, actions: AccessGrantColumnActions, row: AccessGrantRow) {
  if (row.status !== "active" || !row.is_current) {
    return <span className="text-caption text-ink-faint">{t("common.none")}</span>;
  }
  return (
    <RowActionButton
      type="button"
      variant="ghost-danger"
      disabled={actions.disabled}
      onClick={() => actions.onEmergencyRevoke(row)}
    >
      {t("console.operations.emergencyRevoke")}
    </RowActionButton>
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
      userColumn<OperationRow>({
        key: "user_id",
        title: t("common.user"),
        getName: (row) => row.user_name,
        getUserId: (row) => row.user_id,
        filter: true,
        width: 200,
      }),
      filters.user_id,
    ),
    serverColumn(
      appColumn<OperationRow>({
        title: t("common.app"),
        getDisplayName: operationAppDisplayName,
        getAppKey: (row) => row.app_key ?? "",
      }),
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
    textColumn<OperationRow>({
      key: "request_type",
      title: t("common.type"),
      getValue: (row) => (row.request_type ? requestTypeLabel(t, row.request_type) : ""),
      width: 120,
    }),
    {
      key: "approvers",
      title: t("console.operations.column.approvers"),
      width: 190,
      render: (_value: unknown, row: OperationRow) => <ApproversCell t={t} row={row} />,
    },
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

/** 审批人一律按姓名展示; 已有决定的申请在第二行补上决定人。 */
function ApproversCell({ t, row }: { t: Translator; row: OperationRow }) {
  const decidedBy = row.decided_by_name ?? "";
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="truncate">{operationApproverNames(row)}</span>
      {decidedBy ? (
        <span className="truncate text-caption text-ink-faint">
          {t("console.operations.decidedBy", { name: decidedBy })}
        </span>
      ) : null}
    </div>
  );
}

// 待处理申请走审批动作; 授权失败申请走显式重试, 其余状态只读。
function renderAccessRequestActions(t: Translator, actions: AccessRequestColumnActions, row: OperationRow) {
  if (row.status === "submitted") {
    return (
      <>
        <RowActionButton type="button" disabled={actions.disabled} onClick={() => actions.onAction("approve", row)}>
          {t("approvals.approve")}
        </RowActionButton>
        <RowActionButton
          type="button"
          variant="ghost-danger"
          disabled={actions.disabled}
          onClick={() => actions.onAction("reject", row)}
        >
          {t("approvals.reject")}
        </RowActionButton>
        <RowActionButton type="button" disabled={actions.disabled} onClick={() => actions.onAction("reassign", row)}>
          {t("console.accessRequests.reassign")}
        </RowActionButton>
      </>
    );
  }
  if (row.status === "grant_failed") {
    return (
      <RowActionButton
        type="button"
        disabled={actions.disabled}
        onClick={() => actions.onAction("retry-grant", row)}
      >
        {t("console.operations.retryGrant")}
      </RowActionButton>
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
