import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, RefreshCcw } from "lucide-react";
import { Fragment, useCallback, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useParams, useSearchParams } from "react-router-dom";
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
import { Field, SelectInput, TextArea, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { useToast } from "../../components/ui/Toast";
import { UserMultiSelect } from "../../components/UserSelect";
import { ApiError, apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject, ListPayload } from "../../lib/api";
import type { OperationRow as DomainOperationRow } from "../../lib/domain";
import type { OperationAuthorizationGroup, OperationDirectGrant } from "../../lib/domain";
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

type OperationRow = DomainOperationRow & {
  version?: number;
  is_current?: boolean;
  failure_reason?: string;
};

type AccessRequestActionType = ApprovalDecisionMode | "reassign" | "retry-grant";

interface AccessRequestAction {
  type: AccessRequestActionType;
  row: OperationRow;
}

const ACCESS_REQUEST_STATUSES = ["submitted", "approved", "rejected", "grant_applied", "grant_failed"] as const;
const ACCESS_GRANT_STATUSES = ["active", "revoked", "expired"] as const;

export function OperationsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { section = "access-requests" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const config = ENDPOINTS[section] ?? ENDPOINTS["access-requests"];
  // 依赖健康返回非分页的 list_payload; 其余分区走后端分页, 需按分区区分表格模式。
  const isPaginated = section !== "dependency-health";
  const pagination = paginationFromSearchParams(searchParams);
  const [pendingAction, setPendingAction] = useState<AccessRequestAction | null>(null);
  const [pendingEmergencyRevoke, setPendingEmergencyRevoke] = useState<OperationRow | null>(null);
  const queryString = isPaginated ? operationQueryString(section, searchParams, pagination) : "";

  const updateSearchParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    next.set("page", "1");
    setSearchParams(next);
  };
  const updatePagination = (updater: PaginationState | ((current: PaginationState) => PaginationState)) => {
    const nextPagination = typeof updater === "function" ? updater(pagination) : updater;
    const next = new URLSearchParams(searchParams);
    next.set("page", String(nextPagination.pageIndex + 1));
    next.set("page_size", String(nextPagination.pageSize));
    setSearchParams(next);
  };

  const query = useQuery({
    queryKey: isPaginated
      ? ["console", "operations", section, queryString]
      : ["console", "operations", section],
    queryFn: () =>
      apiRequest<ListPayload<OperationRow>>(
        isPaginated ? `${config.endpoint}?${queryString}` : config.endpoint,
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
    onError: (error: Error) => {
      toast.error(t("ops.dependencyHealth.runCheckFailed"), error.message);
    },
  });

  const invalidateAccessRequests = () =>
    queryClient.invalidateQueries({ queryKey: ["console", "operations", "access-requests"] });
  // 409 = 申请状态已变化(如已被处理): 关弹窗、提示冲突并刷新, 其余错误留在弹窗内展示。
  const handleAccessRequestActionError = (error: Error) => {
    if (error instanceof ApiError && error.status === 409) {
      setPendingAction(null);
      toast.warning(t("approvals.conflict"));
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
      toast.success(t(variables.type === "approve" ? "approvals.approved" : "approvals.rejected"));
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
      toast.success(t("console.accessRequests.reassigned"));
      void invalidateAccessRequests();
    },
    onError: handleAccessRequestActionError,
  });
  const retryGrantMutation = useMutation({
    mutationFn: ({ row, reason }: { row: OperationRow; reason: string }) =>
      apiRequest(`/console/api/v1/operations/access-requests/${row.id}/retry-grant`, {
        method: "POST",
        body: { reason } satisfies JsonObject,
      }),
    onSuccess: () => {
      setPendingAction(null);
      toast.success(t("console.operations.retryGrantSuccess"));
      void invalidateAccessRequests();
    },
  });
  const emergencyRevokeMutation = useMutation({
    mutationFn: ({ row, reason }: { row: OperationRow; reason: string }) =>
      apiRequest("/console/api/v1/operations/emergency-revokes", {
        method: "POST",
        body: {
          user_id: requiredString(row.user_id),
          app_key: requiredString(row.app_key),
          reason,
        } satisfies JsonObject,
      }),
    onSuccess: () => {
      setPendingEmergencyRevoke(null);
      toast.success(t("console.operations.emergencyRevokeSuccess"));
      void queryClient.invalidateQueries({ queryKey: ["console", "operations", "access-grants"] });
    },
  });
  const openAccessRequestAction = (type: AccessRequestActionType, row: OperationRow) => {
    decisionMutation.reset();
    reassignMutation.reset();
    retryGrantMutation.reset();
    setPendingAction({ type, row });
  };
  const openEmergencyRevoke = (row: OperationRow) => {
    emergencyRevokeMutation.reset();
    setPendingEmergencyRevoke(row);
  };

  const rows = itemsFromPayload<OperationRow>(query.data);
  const columns = operationColumns(
    section,
    t,
    section === "access-requests"
      ? {
          disabled: decisionMutation.isPending || reassignMutation.isPending || retryGrantMutation.isPending,
          onAction: openAccessRequestAction,
        }
      : undefined,
    section === "access-grants"
      ? { disabled: emergencyRevokeMutation.isPending, onEmergencyRevoke: openEmergencyRevoke }
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
          onPaginationChange: updatePagination,
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
      {isPaginated ? (
        <OperationFilters
          section={section}
          searchParams={searchParams}
          onChange={updateSearchParam}
        />
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
          <TablePagination table={table} totalItems={query.data?.pagination?.total_items ?? rows.length} />
        </TableFrame>
      )}
      {pendingAction && (pendingAction.type === "approve" || pendingAction.type === "reject") ? (
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
      {pendingAction?.type === "retry-grant" ? (
        <ReasonActionDialog
          title={t("console.operations.retryGrant")}
          description={t("console.operations.retryGrantDescription", {
            user: stringValue(pendingAction.row.user_id),
            app: stringValue(pendingAction.row.app_key),
          })}
          confirmLabel={t("console.operations.retryGrant")}
          errorTitle={t("console.operations.retryGrantFailed")}
          errorMessage={dialogErrorMessage(retryGrantMutation.error)}
          isSubmitting={retryGrantMutation.isPending}
          onClose={() => setPendingAction(null)}
          onSubmit={(reason) => retryGrantMutation.mutate({ row: pendingAction.row, reason })}
        />
      ) : null}
      {pendingEmergencyRevoke ? (
        <ReasonActionDialog
          title={t("console.operations.emergencyRevoke")}
          description={t("console.operations.emergencyRevokeDescription", {
            user: stringValue(pendingEmergencyRevoke.user_id),
            app: stringValue(pendingEmergencyRevoke.app_key),
          })}
          confirmLabel={t("console.operations.emergencyRevoke")}
          errorTitle={t("console.operations.emergencyRevokeFailed")}
          errorMessage={dialogErrorMessage(emergencyRevokeMutation.error)}
          isSubmitting={emergencyRevokeMutation.isPending}
          onClose={() => setPendingEmergencyRevoke(null)}
          onSubmit={(reason) => emergencyRevokeMutation.mutate({ row: pendingEmergencyRevoke, reason })}
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

function OperationFilters({
  section,
  searchParams,
  onChange,
}: {
  section: string;
  searchParams: URLSearchParams;
  onChange: (key: string, value: string) => void;
}) {
  const { t } = useI18n();
  const userFilterKey = section === "audit" ? "actor_id" : "user_id";
  const statuses = section === "access-requests" ? ACCESS_REQUEST_STATUSES : section === "access-grants" ? ACCESS_GRANT_STATUSES : [];

  return (
    <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
      <TextInput
        aria-label="app_key"
        placeholder="app_key"
        autoComplete="off"
        value={searchParams.get("app_key") ?? ""}
        onChange={(event) => onChange("app_key", event.currentTarget.value)}
      />
      <TextInput
        aria-label={userFilterKey}
        placeholder={userFilterKey}
        autoComplete="off"
        value={searchParams.get(userFilterKey) ?? ""}
        onChange={(event) => onChange(userFilterKey, event.currentTarget.value)}
      />
      {statuses.length > 0 ? (
        <SelectInput
          aria-label="status"
          value={searchParams.get("status") ?? ""}
          onChange={(event) => onChange("status", event.currentTarget.value)}
        >
          <option value="">{t("approvalInstances.filter.allStatuses")}</option>
          {statuses.map((status) => (
            <option key={status} value={status}>
              {section === "access-requests" ? accessRequestStatusLabel(t, status) : grantStatusLabel(t, status)}
            </option>
          ))}
        </SelectInput>
      ) : null}
      <TextInput
        type="datetime-local"
        aria-label="created_from"
        value={searchParams.get("created_from") ?? ""}
        onChange={(event) => onChange("created_from", event.currentTarget.value)}
      />
      <TextInput
        type="datetime-local"
        aria-label="created_to"
        value={searchParams.get("created_to") ?? ""}
        onChange={(event) => onChange("created_to", event.currentTarget.value)}
      />
      {section === "access-grants" ? (
        <>
          <TextInput
            type="number"
            min={1}
            aria-label="version"
            placeholder="version"
            value={searchParams.get("version") ?? ""}
            onChange={(event) => onChange("version", event.currentTarget.value)}
          />
          <SelectInput
            aria-label="current"
            value={searchParams.get("current") ?? ""}
            onChange={(event) => onChange("current", event.currentTarget.value)}
          >
            <option value="">{t("console.operations.filter.allCurrentStates")}</option>
            <option value="true">{t("console.operations.filter.currentOnly")}</option>
            <option value="false">{t("console.operations.filter.historyOnly")}</option>
          </SelectInput>
        </>
      ) : null}
    </div>
  );
}

function ReasonActionDialog({
  title,
  description,
  confirmLabel,
  errorTitle,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  title: string;
  description: ReactNode;
  confirmLabel: string;
  errorTitle: string;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const [fieldError, setFieldError] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedReason = reason.trim();
    if (normalizedReason === "") {
      setFieldError(t("console.operations.reasonRequired"));
      return;
    }
    onSubmit(normalizedReason);
  };
  const close = useCallback(() => {
    if (!isSubmitting) {
      onClose();
    }
  }, [isSubmitting, onClose]);

  return (
    <Dialog
      title={title}
      onClose={close}
      footer={
        <>
          <Button type="button" onClick={close} disabled={isSubmitting}>
            {t("common.cancel")}
          </Button>
          <Button form="operation-reason-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <form id="operation-reason-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">{description}</p>
        <Field label={t("portal.column.reason")} error={fieldError}>
          <TextArea
            value={reason}
            maxLength={1000}
            disabled={isSubmitting}
            onChange={(event) => {
              setReason(event.currentTarget.value);
              if (fieldError && event.currentTarget.value.trim() !== "") {
                setFieldError("");
              }
            }}
          />
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title={errorTitle} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
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

interface AccessGrantColumnActions {
  disabled: boolean;
  onEmergencyRevoke: (row: OperationRow) => void;
}

function operationColumns(
  section: string,
  t: Translator,
  accessRequestActions?: AccessRequestColumnActions,
  accessGrantActions?: AccessGrantColumnActions,
): ColumnDef<OperationRow>[] {
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
    const accessGrantColumns: ColumnDef<OperationRow>[] = [
      { header: t("common.user"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
      { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
      { header: t("common.status"), cell: ({ row }) => <Badge tone={row.original.status === "active" ? "evergreen" : "neutral"}>{grantStatusLabel(t, stringValue(row.original.status))}</Badge> },
      {
        header: t("console.operations.column.authorizationGroups"),
        cell: ({ row }) => operationAuthorizationGroupSummary(t, row.original.authorization_groups),
      },
      {
        header: t("console.operations.column.directGrants"),
        cell: ({ row }) => operationDirectGrantSummary(t, row.original.direct_grants),
      },
      {
        header: t("console.operations.column.version"),
        cell: ({ row }) => <code className={MONO_TEXT_CLASS}>v{numberValue(row.original.version)}</code>,
      },
      {
        header: t("console.operations.column.isCurrent"),
        cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{booleanValue(row.original.is_current)}</code>,
      },
    ];
    if (accessGrantActions) {
      accessGrantColumns.push({
        id: "actions",
        header: t("common.actions"),
        cell: ({ row }) => (
          <TableActionCell>
            {row.original.status === "active" && row.original.is_current === true ? (
              <TableRowActionButton
                type="button"
                variant="ghost-danger"
                disabled={accessGrantActions.disabled}
                onClick={() => accessGrantActions.onEmergencyRevoke(row.original)}
              >
                {t("console.operations.emergencyRevoke")}
              </TableRowActionButton>
            ) : (
              <span className="text-caption text-ink-faint">{t("common.none")}</span>
            )}
          </TableActionCell>
        ),
      });
    }
    return accessGrantColumns;
  }
  const accessRequestColumns: ColumnDef<OperationRow>[] = [
    { header: "ID", cell: ({ row }) => row.original.id ?? "-" },
    { header: t("common.user"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
    { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
    { header: t("common.status"), cell: ({ row }) => <Badge tone={badgeToneForAccessRequestStatus(stringValue(row.original.status))}>{accessRequestStatusLabel(t, stringValue(row.original.status))}</Badge> },
    { header: t("common.type"), cell: ({ row }) => stringValue(row.original.request_type) },
    { header: t("console.operations.column.failureReason"), cell: ({ row }) => stringValue(row.original.failure_reason) },
    { header: t("console.operations.column.submittedAt"), cell: ({ row }) => formatDateTime(stringValue(row.original.submitted_at)) },
  ];
  if (accessRequestActions) {
    accessRequestColumns.push({
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) =>
        // 待处理申请走审批动作; 授权失败申请走显式重试, 其余状态只读。
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
        ) : row.original.status === "grant_failed" ? (
          <TableActionCell>
            <TableRowActionButton
              type="button"
              disabled={accessRequestActions.disabled}
              onClick={() => accessRequestActions.onAction("retry-grant", row.original)}
            >
              {t("console.operations.retryGrant")}
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

function requiredString(value: unknown): string {
  if (typeof value !== "string" || value === "") {
    throw new Error("Operation row is missing a required string field.");
  }
  return value;
}

function numberValue(value: unknown): string {
  return typeof value === "number" && Number.isInteger(value) ? String(value) : "-";
}

function booleanValue(value: unknown): string {
  return typeof value === "boolean" ? String(value) : "-";
}

function operationAuthorizationGroupSummary(
  t: Translator,
  value: OperationAuthorizationGroup[] | undefined,
): string {
  if (!Array.isArray(value)) {
    throw new Error(t("console.operations.contract.authorizationGroups"));
  }
  if (value.length === 0) {
    return t("common.none");
  }
  return value.map((group, index) => {
    const key = requiredContractString(t, group.key, `authorization_groups[${index}].key`);
    const name = requiredContractString(t, group.name, `authorization_groups[${index}].name`);
    return `${name || key} (${operationItemTerm(t, group.expires_at, `authorization_groups[${index}].expires_at`)})`;
  }).join("；");
}

function operationDirectGrantSummary(
  t: Translator,
  value: OperationDirectGrant[] | undefined,
): string {
  if (!Array.isArray(value)) {
    throw new Error(t("console.operations.contract.directGrants"));
  }
  if (value.length === 0) {
    return t("common.none");
  }
  return value.map((grant, index) => {
    const permission = requiredContractString(t, grant.permission, `direct_grants[${index}].permission`);
    const name = requiredContractString(t, grant.permission_name, `direct_grants[${index}].permission_name`);
    const scope = requiredContractString(t, grant.scope, `direct_grants[${index}].scope`);
    const term = operationItemTerm(t, grant.expires_at, `direct_grants[${index}].expires_at`);
    return `${name || permission} [${scope}] (${term})`;
  }).join("；");
}

function operationItemTerm(t: Translator, value: unknown, field: string): string {
  if (value === null) {
    return grantTypeLabel(t, "permanent");
  }
  return formatDateTime(requiredContractString(t, value, field));
}

function requiredContractString(t: Translator, value: unknown, field: string): string {
  if (typeof value !== "string" || value === "") {
    throw new Error(t("console.operations.contract.requiredString", { field }));
  }
  return value;
}

function paginationFromSearchParams(searchParams: URLSearchParams): PaginationState {
  return {
    pageIndex: positiveInteger(searchParams.get("page"), 1) - 1,
    pageSize: positiveInteger(searchParams.get("page_size"), DEFAULT_PAGE_SIZE),
  };
}

function positiveInteger(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function operationQueryString(
  section: string,
  searchParams: URLSearchParams,
  pagination: PaginationState,
): string {
  const query = new URLSearchParams({
    page: String(pagination.pageIndex + 1),
    page_size: String(pagination.pageSize),
  });
  const filterKeys =
    section === "access-requests"
      ? ["app_key", "user_id", "status", "created_from", "created_to"]
      : section === "access-grants"
        ? ["app_key", "user_id", "status", "created_from", "created_to", "version", "current"]
        : section === "audit"
          ? ["app_key", "actor_id", "created_from", "created_to"]
          : [];
  for (const key of filterKeys) {
    const value = searchParams.get(key);
    if (value) {
      query.set(key, value);
    }
  }
  return query.toString();
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
