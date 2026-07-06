import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, RefreshCcw } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useParams } from "react-router-dom";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TableActionCell, TableRowActionButton } from "../../components/ui/TableActions";
import { TablePagination } from "../../components/ui/TablePagination";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";

import { ApprovalDecisionDialog } from "../../components/ApprovalDecisionDialog";
import type { ApprovalDecisionMode } from "../../components/ApprovalDecisionDialog";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { UserMultiSelect } from "../../components/UserSelect";
import { ApiError, apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject, ListPayload } from "../../lib/api";
import type { OperationRow } from "../../lib/domain";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/messages";
import { accessRequestStatusLabel, badgeToneForAccessRequestStatus, formatDateTime, grantStatusLabel, grantTypeLabel, healthStatusLabel } from "../../lib/status";
import type { Translator } from "../../lib/status";

const ENDPOINTS: Record<string, { titleKey: MessageKey; endpoint: string }> = {
  "access-requests": { titleKey: "nav.console.accessRequests", endpoint: "/console/api/v1/operations/access-requests" },
  "access-grants": { titleKey: "nav.console.accessGrants", endpoint: "/console/api/v1/operations/access-grants" },
  "dependency-health": { titleKey: "nav.console.dependencyHealth", endpoint: "/console/api/v1/operations/dependency-health" },
  audit: { titleKey: "console.operations.title.audit", endpoint: "/console/api/v1/audit-logs" },
};

const DEFAULT_PAGE_SIZE = 20;

type AccessRequestActionType = ApprovalDecisionMode | "reassign";

interface AccessRequestAction {
  type: AccessRequestActionType;
  row: OperationRow;
}

type AccessRequestNoticeKey =
  | "approvals.approved"
  | "approvals.rejected"
  | "approvals.conflict"
  | "console.accessRequests.reassigned"
  | "";

export function OperationsPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { section = "access-requests" } = useParams();
  const config = ENDPOINTS[section] ?? ENDPOINTS["access-requests"];
  // 依赖健康返回非分页的 list_payload; 其余分区走后端分页, 需按分区区分表格模式。
  const isPaginated = section !== "dependency-health";
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE });
  const [pendingAction, setPendingAction] = useState<AccessRequestAction | null>(null);
  const [noticeKey, setNoticeKey] = useState<AccessRequestNoticeKey>("");

  // 切换分区时回到第一页, 避免带着上个分区的页码请求。
  useEffect(() => {
    setPagination((current) => (current.pageIndex === 0 ? current : { ...current, pageIndex: 0 }));
  }, [section]);

  const query = useQuery({
    queryKey: isPaginated
      ? ["console", "operations", section, pagination.pageIndex, pagination.pageSize]
      : ["console", "operations", section],
    queryFn: () =>
      apiRequest<ListPayload<OperationRow>>(
        isPaginated ? `${config.endpoint}?page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}` : config.endpoint,
      ),
  });
  const healthCheckMutation = useMutation({
    mutationFn: () =>
      apiRequest<ListPayload<OperationRow>>(
        "/console/api/v1/operations/dependency-health/checks",
        { method: "POST" },
      ),
    onSuccess: (payload) => {
      queryClient.setQueryData(["console", "operations", "dependency-health"], payload);
    },
  });

  const invalidateAccessRequests = () =>
    queryClient.invalidateQueries({ queryKey: ["console", "operations", "access-requests"] });
  // 409 = 申请状态已变化(如已被处理): 关弹窗、提示冲突并刷新, 其余错误留在弹窗内展示。
  const handleAccessRequestActionError = (error: Error) => {
    if (error instanceof ApiError && error.status === 409) {
      setPendingAction(null);
      setNoticeKey("approvals.conflict");
      void invalidateAccessRequests();
    }
  };
  const decisionMutation = useMutation({
    mutationFn: ({ type, row, comment }: { type: ApprovalDecisionMode; row: OperationRow; comment: string }) =>
      apiRequest(`/console/api/v1/operations/access-requests/${row.id}/${type}`, {
        method: "POST",
        body: type === "reject" || comment ? { comment } : {},
      }),
    onSuccess: (_, variables) => {
      setPendingAction(null);
      setNoticeKey(variables.type === "approve" ? "approvals.approved" : "approvals.rejected");
      void invalidateAccessRequests();
    },
    onError: handleAccessRequestActionError,
  });
  const reassignMutation = useMutation({
    mutationFn: ({ row, approverUserIds }: { row: OperationRow; approverUserIds: string[] }) =>
      apiRequest(`/console/api/v1/operations/access-requests/${row.id}/reassign`, {
        method: "POST",
        body: { approver_user_ids: approverUserIds } satisfies JsonObject,
      }),
    onSuccess: () => {
      setPendingAction(null);
      setNoticeKey("console.accessRequests.reassigned");
      void invalidateAccessRequests();
    },
    onError: handleAccessRequestActionError,
  });
  const openAccessRequestAction = (type: AccessRequestActionType, row: OperationRow) => {
    decisionMutation.reset();
    reassignMutation.reset();
    setNoticeKey("");
    setPendingAction({ type, row });
  };

  const rows = itemsFromPayload<OperationRow>(query.data);
  const columns = operationColumns(
    section,
    t,
    section === "access-requests"
      ? { disabled: decisionMutation.isPending || reassignMutation.isPending, onAction: openAccessRequestAction }
      : undefined,
  );
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    ...(isPaginated
      ? {
          manualPagination: true as const,
          pageCount: query.data?.pagination?.total_pages ?? 1,
          state: { pagination },
          onPaginationChange: setPagination,
        }
      : {
          getPaginationRowModel: getPaginationRowModel(),
        }),
  });

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.operations")}
        title={t(config.titleKey)}
        description={t("console.operations.description")}
        actions={
          <>
            {section === "dependency-health" ? (
              <Button
                variant="primary"
                icon={<Activity size={16} />}
                loading={healthCheckMutation.isPending}
                onClick={() => healthCheckMutation.mutate()}
              >
                {t("ops.dependencyHealth.runCheck")}
              </Button>
            ) : null}
            <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
              {t("common.refresh")}
            </Button>
          </>
        }
      />
      {healthCheckMutation.error ? (
        <StatusBanner
          tone="signal"
          title={t("ops.dependencyHealth.runCheckFailed")}
          message={(healthCheckMutation.error as Error).message}
        />
      ) : null}
      {section === "access-requests" && noticeKey ? (
        <div role="status">
          <StatusBanner tone={noticeKey === "approvals.conflict" ? "amber" : "evergreen"} title={t(noticeKey)} />
        </div>
      ) : null}
      {query.error && rows.length > 0 ? (
        <StatusBanner tone="signal" title={t("console.operations.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      {query.error && rows.length === 0 ? (
        <PageState
          tone="signal"
          title={t("console.operations.loadFailed")}
          description={(query.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <TableFrame>
          <TableRoot>
            <TableHead>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHeaderCell key={header.id}>
                      {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHeaderCell>
                  ))}
                </TableRow>
              ))}
            </TableHead>
            <TableBody>
              {query.isLoading ? (
                <TableSkeletonRows columns={table.getAllLeafColumns().length} />
              ) : table.getRowModel().rows.length > 0 ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) =>
                      cell.column.id === "actions" ? (
                        <Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Fragment>
                      ) : (
                        <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                      ),
                    )}
                  </TableRow>
                ))
              ) : (
                <TableEmptyRow colSpan={table.getAllLeafColumns().length}>
                  <EmptyState title={t("console.operations.empty")} description={t("console.operations.emptyDescription")} />
                </TableEmptyRow>
              )}
            </TableBody>
          </TableRoot>
          <TablePagination table={table} />
        </TableFrame>
      )}
      {pendingAction && pendingAction.type !== "reassign" ? (
        <ApprovalDecisionDialog
          mode={pendingAction.type}
          description={t("console.accessRequests.target", {
            user: stringValue(pendingAction.row.user_id),
            app: stringValue(pendingAction.row.app_key),
          })}
          note={t("console.accessRequests.auditNote")}
          errorMessage={dialogErrorMessage(decisionMutation.error)}
          isSubmitting={decisionMutation.isPending}
          onClose={() => setPendingAction(null)}
          onSubmit={(comment) => decisionMutation.mutate({ type: pendingAction.type as ApprovalDecisionMode, row: pendingAction.row, comment })}
        />
      ) : null}
      {pendingAction?.type === "reassign" ? (
        <ReassignApproversDialog
          description={t("console.accessRequests.target", {
            user: stringValue(pendingAction.row.user_id),
            app: stringValue(pendingAction.row.app_key),
          })}
          errorMessage={dialogErrorMessage(reassignMutation.error)}
          isSubmitting={reassignMutation.isPending}
          onClose={() => setPendingAction(null)}
          onSubmit={(approverUserIds) => reassignMutation.mutate({ row: pendingAction.row, approverUserIds })}
        />
      ) : null}
    </>
  );
}

/** 409 冲突走顶部提示并刷新列表, 不在弹窗内重复展示。 */
function dialogErrorMessage(error: Error | null): string {
  if (!error || (error instanceof ApiError && error.status === 409)) {
    return "";
  }
  return error.message;
}

function ReassignApproversDialog({
  description,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  description: string;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (approverUserIds: string[]) => void;
}) {
  const { t } = useI18n();
  const [approverUserIds, setApproverUserIds] = useState<string[]>([]);
  const [fieldError, setFieldError] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (approverUserIds.length === 0) {
      setFieldError(t("console.accessRequests.approversRequired"));
      return;
    }
    onSubmit(approverUserIds);
  };

  return (
    <Dialog
      title={t("console.accessRequests.reassignTitle")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="reassign-approvers-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("console.accessRequests.reassignConfirm")}
          </Button>
        </>
      }
    >
      <form id="reassign-approvers-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">{description}</p>
        <Field label={t("console.accessRequests.approversField")} error={fieldError}>
          <UserMultiSelect
            value={approverUserIds}
            onChange={(next) => {
              setApproverUserIds(next);
              if (fieldError && next.length > 0) {
                setFieldError("");
              }
            }}
          />
        </Field>
        <p className="text-xs leading-5 text-ink-faint">{t("console.accessRequests.reassignNote")}</p>
        {errorMessage ? <StatusBanner tone="signal" title={t("console.accessRequests.reassignFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

interface AccessRequestColumnActions {
  disabled: boolean;
  onAction: (type: AccessRequestActionType, row: OperationRow) => void;
}

function operationColumns(section: string, t: Translator, accessRequestActions?: AccessRequestColumnActions): ColumnDef<OperationRow>[] {
  if (section === "dependency-health") {
    return [
      { header: t("console.operations.column.component"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.component)}</code> },
      { header: t("common.status"), cell: ({ row }) => <Badge tone={healthTone(stringValue(row.original.status))}>{healthStatusLabel(t, stringValue(row.original.status))}</Badge> },
      { header: t("console.operations.column.summary"), cell: ({ row }) => stringValue(row.original.summary) },
      { header: t("console.operations.column.error"), cell: ({ row }) => stringValue(row.original.error_summary) },
      { header: t("console.operations.column.checkedAt"), cell: ({ row }) => formatDateTime(stringValue(row.original.last_checked_at)) },
    ];
  }
  if (section === "audit") {
    // 审计行字段对齐后端 audit_api._audit_item; 审计行无 id, 故不展示 ID 列。
    return [
      { header: t("console.operations.column.event"), cell: ({ row }) => stringValue(row.original.event_type) },
      { header: t("console.operations.column.actor"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{auditPair(row.original.actor_type, row.original.actor_id)}</code> },
      { header: t("console.operations.column.target"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{auditPair(row.original.target_type, row.original.target_id)}</code> },
      { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{auditAppKey(row.original)}</code> },
      { header: t("console.operations.column.time"), cell: ({ row }) => formatDateTime(stringValue(row.original.created_at)) },
    ];
  }
  if (section === "access-grants") {
    return [
      { header: t("common.user"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
      { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
      { header: t("common.status"), cell: ({ row }) => <Badge tone={row.original.status === "active" ? "evergreen" : "neutral"}>{grantStatusLabel(t, stringValue(row.original.status))}</Badge> },
      { header: t("common.type"), cell: ({ row }) => grantTypeLabel(t, stringValue(row.original.grant_type)) },
      { header: t("console.operations.column.expiresAt"), cell: ({ row }) => formatDateTime(stringValue(row.original.grant_expires_at)) },
    ];
  }
  const accessRequestColumns: ColumnDef<OperationRow>[] = [
    { header: "ID", cell: ({ row }) => row.original.id ?? "-" },
    { header: t("common.user"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
    { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
    { header: t("common.status"), cell: ({ row }) => <Badge tone={badgeToneForAccessRequestStatus(stringValue(row.original.status))}>{accessRequestStatusLabel(t, stringValue(row.original.status))}</Badge> },
    { header: t("common.type"), cell: ({ row }) => stringValue(row.original.request_type) },
    { header: t("console.operations.column.submittedAt"), cell: ({ row }) => formatDateTime(stringValue(row.original.submitted_at)) },
  ];
  if (accessRequestActions) {
    accessRequestColumns.push({
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) =>
        // 仅待处理(submitted)的申请可操作; 其余状态只读展示。
        row.original.status === "submitted" ? (
          <TableActionCell>
            <TableRowActionButton
              type="button"
              disabled={accessRequestActions.disabled}
              onClick={() => accessRequestActions.onAction("approve", row.original)}
            >
              {t("approvals.approve")}
            </TableRowActionButton>
            <TableRowActionButton
              type="button"
              variant="ghost-danger"
              disabled={accessRequestActions.disabled}
              onClick={() => accessRequestActions.onAction("reject", row.original)}
            >
              {t("approvals.reject")}
            </TableRowActionButton>
            <TableRowActionButton
              type="button"
              disabled={accessRequestActions.disabled}
              onClick={() => accessRequestActions.onAction("reassign", row.original)}
            >
              {t("console.accessRequests.reassign")}
            </TableRowActionButton>
          </TableActionCell>
        ) : (
          <TableActionCell>
            <span className="text-caption text-ink-faint">{t("common.none")}</span>
          </TableActionCell>
        ),
    });
  }
  return accessRequestColumns;
}

function stringValue(value: unknown): string {
  return typeof value === "string" && value !== "" ? value : "-";
}

function auditPair(type: string | undefined, id: string | undefined): string {
  const parts = [type, id].filter((part): part is string => typeof part === "string" && part !== "");
  return parts.length > 0 ? parts.join(":") : "-";
}

function auditAppKey(row: OperationRow): string {
  // 非超管审计以 metadata.app_key 做作用域, app_key 不在顶层字段而在 metadata 中。
  const appKey = row.metadata && typeof row.metadata === "object" ? row.metadata.app_key : undefined;
  return typeof appKey === "string" && appKey !== "" ? appKey : "-";
}

function healthTone(status: string): "evergreen" | "amber" | "neutral" | "signal" {
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
