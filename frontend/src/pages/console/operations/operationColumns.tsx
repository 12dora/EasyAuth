import {
  dateRangeFilter,
  type ColumnsType,
  type ServerSortState,
} from "../../../components/antd/AppTable";
import {
  RowActionButton,
  actionsColumn,
  appColumn,
  dateTimeColumn,
  personColumn,
  serverColumn,
  serverSortColumn,
  statusColumn,
  textColumn,
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
} from "../../../lib/status";
import { requestTypeLabel } from "../../portal/components/portalApprovalFacts";
import { ACCESS_GRANT_STATUSES, ACCESS_REQUEST_STATUSES, ALL_STATUSES_VALUE } from "./operationQuery";
import {
  auditAppKey,
  auditPair,
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
  onRevoke: (row: AccessGrantRow) => void;
}

/** 列 key -> 当前选中的筛选值(来自 URL), 交给 antd 做受控表头筛选。 */
export type OperationFilterValues = Record<string, string[]>;

/** 授权明细以外的分区(申请 / 审计)共用松散的运营行类型。 */
export function operationColumns(
  section: string,
  t: Translator,
  filters: OperationFilterValues,
  sort: ServerSortState,
  accessRequestActions?: AccessRequestColumnActions,
): ColumnsType<OperationRow> {
  if (section === "audit") {
    return auditColumns(t, filters, sort);
  }
  return accessRequestColumns(t, filters, sort, accessRequestActions);
}

function auditColumns(
  t: Translator,
  filters: OperationFilterValues,
  sort: ServerSortState,
): ColumnsType<OperationRow> {
  // 审计行字段对齐后端 audit_api._audit_item; 审计行无 id, 故不展示 ID 列。
  return [
    serverSortColumn(
      textColumn<OperationRow>({ key: "event_type", title: t("console.operations.column.event"), width: 220 }),
      sort,
    ),
    serverSortColumn(
      serverColumn(
        personColumn<OperationRow>({
          key: "actor",
          title: t("console.operations.column.actor"),
          t,
          getName: (row) =>
            row.actor_person ? row.actor_person.name : auditPair(row.actor_type, row.actor_id),
          getUserId: (row) => row.actor_person?.user_id ?? "",
          getDepartment: (row) => row.actor_person?.department,
          getAccountKind: (row) => row.actor_person?.account_kind,
          filter: true,
          width: 200,
        }),
        filters.actor,
      ),
      sort,
    ),
    serverSortColumn(
      textColumn<OperationRow>({
        key: "target",
        title: t("console.operations.column.target"),
        getValue: (row) => auditPair(row.target_type, row.target_id),
        mono: true,
      }),
      sort,
    ),
    serverSortColumn(
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
      sort,
    ),
    serverSortColumn(
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
      sort,
    ),
  ];
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
  sort: ServerSortState,
  actions: AccessGrantColumnActions | undefined,
): ColumnsType<AccessGrantRow> {
  const columns: ColumnsType<AccessGrantRow> = [
    serverSortColumn(
      serverColumn(
        personColumn<AccessGrantRow>({
          key: "user_id",
          title: t("common.user"),
          t,
          getName: (row) => row.user_name,
          getUserId: (row) => row.user_id,
          getDepartment: (row) => row.user_department,
          getAccountKind: (row) => row.user_account_kind,
          filter: true,
          width: 200,
        }),
        filters.user_id,
      ),
      sort,
    ),
    serverSortColumn(
      serverColumn(
        appColumn<AccessGrantRow>({
          key: "app_key",
          title: t("common.app"),
          getDisplayName: (row) => formatAppDisplayName({ name: row.app_name, alias: row.app_alias }),
          getAppKey: (row) => row.app_key,
          filter: true,
        }),
        filters.app_key,
      ),
      sort,
    ),
    serverSortColumn(
      serverColumn(
        statusColumn<AccessGrantRow>({
          key: "status",
          title: t("common.status"),
          options: grantStatusOptions(t),
          width: 130,
        }),
        filters.status,
      ),
      sort,
    ),
    serverSortColumn(
      textColumn<AccessGrantRow>({
        key: "groups",
        title: t("console.operations.column.groups"),
        getValue: (row) => formatGrantGroupNames(row.groups, t),
        ellipsis: false,
        width: 200,
      }),
      sort,
    ),
    serverSortColumn(
      {
        key: "permission_details",
        title: t("console.operations.column.permissionDetails"),
        width: 140,
        render: (_value: unknown, row: AccessGrantRow) => <GrantPermissionsCell row={row} />,
      },
      sort,
    ),
    serverSortColumn(
      {
        key: "grant_expires_at",
        title: t("console.operations.column.expiresAt"),
        width: 210,
        render: (_value: unknown, row: AccessGrantRow) => (
          <GrantExpiryCell grantType={row.grant_type} expiresAt={row.grant_expires_at} />
        ),
      },
      sort,
    ),
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
      onClick={() => actions.onRevoke(row)}
    >
      {t("console.operations.revoke")}
    </RowActionButton>
  );
}

function accessRequestColumns(
  t: Translator,
  filters: OperationFilterValues,
  sort: ServerSortState,
  actions: AccessRequestColumnActions | undefined,
): ColumnsType<OperationRow> {
  const columns: ColumnsType<OperationRow> = [
    serverSortColumn(textColumn<OperationRow>({ key: "id", title: "ID", width: 90 }), sort),
    serverSortColumn(
      serverColumn(
        personColumn<OperationRow>({
          key: "user_id",
          title: t("common.user"),
          t,
          getName: (row) => row.user_name,
          getUserId: (row) => row.user_id,
          getDepartment: (row) => row.user_department,
          getAccountKind: (row) => row.user_account_kind,
          filter: true,
          width: 200,
        }),
        filters.user_id,
      ),
      sort,
    ),
    serverSortColumn(
      serverColumn(
        appColumn<OperationRow>({
          key: "app_key",
          title: t("common.app"),
          getDisplayName: operationAppDisplayName,
          getAppKey: (row) => row.app_key ?? "",
          filter: true,
        }),
        filters.app_key,
      ),
      sort,
    ),
    serverSortColumn(
      serverColumn(
        statusColumn<OperationRow>({
          key: "status",
          title: t("common.status"),
          options: accessRequestStatusOptions(t),
          width: 130,
        }),
        filters.status,
      ),
      sort,
    ),
    serverSortColumn(
      textColumn<OperationRow>({
        key: "request_type",
        title: t("common.type"),
        getValue: (row) => (row.request_type ? requestTypeLabel(t, row.request_type) : ""),
        width: 120,
      }),
      sort,
    ),
    serverSortColumn(
      {
        key: "approvers",
        title: t("console.operations.column.approvers"),
        width: 190,
        render: (_value: unknown, row: OperationRow) => <ApproversCell t={t} row={row} />,
      },
      sort,
    ),
    serverSortColumn(
      textColumn<OperationRow>({ key: "failure_reason", title: t("console.operations.column.failureReason") }),
      sort,
    ),
    serverSortColumn(
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
      sort,
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

/**
 * 申请状态筛选项。
 *
 * 首项「全部」不是申请状态, 而是显式的筛选取值: 该页默认只列待审批申请,
 * 空筛选不等于全部, 所以要看历史必须能选到「全部」。没有一行的 status 会等于它,
 * 因此不会被状态徽章渲染到。
 */
function accessRequestStatusOptions(t: Translator): StatusColumnOption[] {
  return [
    { value: ALL_STATUSES_VALUE, label: t("console.operations.filter.allStatuses"), tone: "neutral" },
    ...ACCESS_REQUEST_STATUSES.map((status) => ({
      value: status,
      label: accessRequestStatusLabel(t, status),
      tone: badgeToneForAccessRequestStatus(status),
    })),
  ];
}

function grantStatusOptions(t: Translator): StatusColumnOption[] {
  return ACCESS_GRANT_STATUSES.map((status) => ({
    value: status,
    label: grantStatusLabel(t, status),
    tone: status === "active" ? "evergreen" : "neutral",
  }));
}
