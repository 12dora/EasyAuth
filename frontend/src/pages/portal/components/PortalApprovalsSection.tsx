import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { ApprovalDecisionDialog } from "../../../components/ApprovalDecisionDialog";
import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { StatusBanner } from "../../../components/StatusBanner";
import { TableActionCell, TableRowActionButton } from "../../../components/ui/TableActions";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../../components/ui/TablePrimitives";
import { TablePagination } from "../../../components/ui/TablePagination";
import { EmptyState } from "../../../components/ui/EmptyState";
import { PageState } from "../../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../../components/ui/tableStyles";
import { useI18n } from "../../../i18n/I18nProvider";
import { ApiError, apiRequest } from "../../../lib/api";
import type { Pagination } from "../../../lib/api";
import { cn } from "../../../lib/cn";
import type { PortalApprovalApplicant } from "../../../lib/domain";
import {
  accessRequestStatusLabel,
  badgeToneForAccessRequestStatus,
  formatDateTime,
  grantTypeLabel,
} from "../../../lib/status";
import type { Translator } from "../../../lib/status";

type ApprovalTab = "pending" | "processed";

type ApprovalNoticeKey =
  | "approvals.approved"
  | "approvals.rejected"
  | "approvals.conflict"
  | "approvals.grantFailedCommitted"
  | "";

interface ApprovalGrantFact {
  permission: string;
  permission_name: string;
  scope: string;
}

interface ApprovalAuthorizationGroup {
  key: string;
  kind: string;
  name: string;
  grants: ApprovalGrantFact[];
}

interface PortalApprovalRow {
  id: number;
  app_key: string;
  app_name: string;
  request_type: string;
  status: string;
  status_label: string;
  grant_type: string;
  grant_expires_at: string | null;
  reason: string;
  submitted_at: string;
  authorization_groups: ApprovalAuthorizationGroup[];
  direct_grants: ApprovalGrantFact[];
  decided_at: string | null;
  decision_comment: string | null;
  applicant: Required<PortalApprovalApplicant>;
  approver_user_ids: string[];
  decided_by: string | null;
}

interface ApprovalListPayload {
  data: PortalApprovalRow[];
  pagination: Pagination;
}

interface PendingDecision {
  mode: ApprovalDecisionMode;
  approval: PortalApprovalRow;
}

const DEFAULT_PAGE_SIZE = 20;

export function PortalApprovalsSection() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<ApprovalTab>("pending");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE });
  const [pendingDecision, setPendingDecision] = useState<PendingDecision | null>(null);
  const [noticeKey, setNoticeKey] = useState<ApprovalNoticeKey>("");

  const query = useQuery({
    queryKey: ["portal", "approvals", tab, pagination.pageIndex, pagination.pageSize],
    queryFn: async () =>
      parseApprovalListPayload(
        await apiRequest<unknown>(
          `/portal/api/v1/me/approvals?status=${tab}&page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}`,
        ),
        t("portal.approvals.invalidPayload"),
      ),
  });
  const detailQuery = useQuery({
    queryKey: ["portal", "approvals", "detail", pendingDecision?.approval.id],
    queryFn: async () =>
      parseApprovalDetailPayload(
        await apiRequest<unknown>(`/portal/api/v1/me/approvals/${pendingDecision?.approval.id ?? 0}`),
        t("portal.approvals.invalidPayload"),
      ),
    enabled: pendingDecision !== null,
  });
  const decisionMutation = useMutation({
    mutationFn: ({ mode, approval, comment }: PendingDecision & { comment: string }) =>
      apiRequest(`/portal/api/v1/me/approvals/${approval.id}/${mode}`, {
        method: "POST",
        body: mode === "reject" || comment ? { comment } : {},
      }),
    onSuccess: (_, variables) => {
      setPendingDecision(null);
      setNoticeKey(variables.mode === "approve" ? "approvals.approved" : "approvals.rejected");
      void queryClient.invalidateQueries({ queryKey: ["portal", "approvals"] });
    },
    onError: (error) => {
      // 决定已提交但授权失败是复合结果: 不得保留旧待办或允许重复提交。
      if (decisionWasCommitted(error)) {
        setPendingDecision(null);
        setNoticeKey("approvals.grantFailedCommitted");
        void queryClient.invalidateQueries({ queryKey: ["portal", "approvals"] });
      } else if (error instanceof ApiError && error.status === 409) {
        setPendingDecision(null);
        setNoticeKey("approvals.conflict");
        void queryClient.invalidateQueries({ queryKey: ["portal", "approvals"] });
      }
    },
  });

  const approvals = query.data?.data ?? [];
  const openDecision = (mode: ApprovalDecisionMode, approval: PortalApprovalRow) => {
    decisionMutation.reset();
    setNoticeKey("");
    setPendingDecision({ mode, approval });
  };
  const switchTab = (nextTab: ApprovalTab) => {
    setTab(nextTab);
    setPagination((current) => (current.pageIndex === 0 ? current : { ...current, pageIndex: 0 }));
  };

  const totalPages = query.data?.pagination.total_pages ?? 0;
  const clampedPageIndex = totalPages === 0 ? 0 : Math.min(pagination.pageIndex, totalPages - 1);
  useEffect(() => {
    if (pagination.pageIndex !== clampedPageIndex) {
      setPagination((current) => ({ ...current, pageIndex: clampedPageIndex }));
    }
  }, [clampedPageIndex, pagination.pageIndex]);

  const columns = approvalColumns(t, tab, decisionMutation.isPending, openDecision);
  const table = useReactTable({
    data: approvals,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: totalPages,
    state: { pagination: { ...pagination, pageIndex: clampedPageIndex } },
    onPaginationChange: setPagination,
  });

  const dialogErrorMessage =
    decisionMutation.error && !(decisionMutation.error instanceof ApiError && decisionMutation.error.status === 409)
      ? (decisionMutation.error as Error).message
      : "";

  return (
    <>
      <div className="mb-4 flex gap-1 border-b border-ink/12" role="tablist" aria-label={t("portal.approvals.tablist")}>
        {(["pending", "processed"] as const).map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            id={`portal-approvals-tab-${item}`}
            aria-selected={item === tab}
            aria-controls="portal-approvals-tabpanel"
            className={cn(
              "relative -mb-px h-10 shrink-0 border-b-2 px-3 text-sm font-semibold transition-colors",
              item === tab ? "border-accent text-ink" : "border-transparent text-ink-soft hover:text-ink",
            )}
            onClick={() => switchTab(item)}
          >
            {item === "pending" ? t("portal.approvals.tab.pending") : t("portal.approvals.tab.processed")}
          </button>
        ))}
      </div>
      {noticeKey ? (
        <div className="mb-4" role="status">
          <StatusBanner
            tone={
              noticeKey === "approvals.conflict"
                ? "amber"
                : noticeKey === "approvals.grantFailedCommitted"
                  ? "signal"
                  : "evergreen"
            }
            title={t(noticeKey)}
            message={
              noticeKey === "approvals.grantFailedCommitted"
                ? t("approvals.grantFailedCommittedDescription")
                : undefined
            }
          />
        </div>
      ) : null}
      {query.error && approvals.length > 0 ? (
        <StatusBanner tone="signal" title={t("portal.approvals.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      <div id="portal-approvals-tabpanel" role="tabpanel" aria-labelledby={`portal-approvals-tab-${tab}`}>
        {query.error && approvals.length === 0 ? (
          <PageState
            tone="signal"
            title={t("portal.approvals.loadFailed")}
            description={(query.error as Error).message}
            action={
              <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
                {t("common.retry")}
              </Button>
            }
          />
        ) : (
          <TableFrame>
            <TableRoot aria-label={t("nav.portal.myApprovals")}>
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
                    <EmptyState
                      title={tab === "pending" ? t("portal.approvals.empty.pending") : t("portal.approvals.empty.processed")}
                      description={
                        tab === "pending"
                          ? t("portal.approvals.empty.pendingDescription")
                          : t("portal.approvals.empty.processedDescription")
                      }
                    />
                  </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
            <TablePagination
              table={table}
              totalItems={query.data?.pagination.total_items ?? approvals.length}
            />
          </TableFrame>
        )}
      </div>
      {pendingDecision ? (
        <ApprovalDecisionDialog
          mode={pendingDecision.mode}
          description={t(
            pendingDecision.mode === "approve" ? "portal.approvals.approveDescription" : "portal.approvals.rejectDescription",
            {
              applicant: applicantLabel(pendingDecision.approval),
              app: pendingDecision.approval.app_name ?? pendingDecision.approval.app_key ?? "-",
            },
          )}
          details={decisionDetails(
            t,
            detailQuery.data?.approval,
            detailQuery.isLoading,
            detailQuery.error,
          )}
          errorMessage={dialogErrorMessage}
          isSubmitting={decisionMutation.isPending}
          canSubmit={Boolean(detailQuery.data?.approval && approvalFactsAreComplete(detailQuery.data.approval))}
          onClose={() => setPendingDecision(null)}
          onSubmit={(comment) => {
            if (detailQuery.data?.approval && approvalFactsAreComplete(detailQuery.data.approval)) {
              decisionMutation.mutate({
                mode: pendingDecision.mode,
                approval: detailQuery.data.approval,
                comment,
              });
            }
          }}
        />
      ) : null}
    </>
  );
}

function approvalColumns(
  t: Translator,
  tab: ApprovalTab,
  actionsDisabled: boolean,
  onDecision: (mode: ApprovalDecisionMode, approval: PortalApprovalRow) => void,
): ColumnDef<PortalApprovalRow>[] {
  const columns: ColumnDef<PortalApprovalRow>[] = [];
  if (tab === "processed") {
    columns.push({
      header: t("common.status"),
      cell: ({ row }) => (
        <Badge tone={badgeToneForAccessRequestStatus(row.original.status)}>
          {row.original.status_label ?? accessRequestStatusLabel(t, row.original.status)}
        </Badge>
      ),
    });
  }
  columns.push(
    {
      header: t("portal.approvals.column.applicant"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{applicantLabel(row.original)}</strong>
          {row.original.applicant?.department ? (
            <span className="text-xs leading-4 text-ink-faint">{row.original.applicant.department}</span>
          ) : null}
        </div>
      ),
    },
    {
      header: t("common.app"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{row.original.app_name ?? row.original.app_key ?? "-"}</strong>
          <code className={MONO_TEXT_CLASS}>{row.original.app_key ?? "-"}</code>
        </div>
      ),
    },
    { header: t("portal.approvals.column.content"), cell: ({ row }) => approvalContentDetails(t, row.original) },
    {
      header: t("portal.column.term"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <span>{grantTypeLabel(t, row.original.grant_type)}</span>
          {row.original.grant_expires_at ? (
            <span className="text-xs leading-4 text-ink-faint">{formatDateTime(row.original.grant_expires_at)}</span>
          ) : null}
        </div>
      ),
    },
    { header: t("portal.column.submittedAt"), cell: ({ row }) => formatDateTime(row.original.submitted_at) },
    { header: t("portal.column.reason"), cell: ({ row }) => row.original.reason ?? "-" },
  );
  if (tab === "pending") {
    columns.push({
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" disabled={actionsDisabled} onClick={() => onDecision("approve", row.original)}>
            {t("approvals.approve")}
          </TableRowActionButton>
          <TableRowActionButton
            type="button"
            variant="ghost-danger"
            disabled={actionsDisabled}
            onClick={() => onDecision("reject", row.original)}
          >
            {t("approvals.reject")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    });
  } else {
    columns.push(
      { header: t("portal.approvals.column.decidedAt"), cell: ({ row }) => formatDateTime(row.original.decided_at) },
      { header: t("portal.approvals.column.myComment"), cell: ({ row }) => row.original.decision_comment || "-" },
    );
  }
  return columns;
}

function applicantLabel(approval: PortalApprovalRow): string {
  return approval.applicant?.name || approval.applicant?.email || approval.applicant?.user_id || "-";
}

function approvalContentDetails(t: Translator, approval: PortalApprovalRow): ReactNode {
  const hasTargets = approval.authorization_groups.length > 0 || approval.direct_grants.length > 0;
  return (
    <div className="grid min-w-64 gap-2 text-xs leading-5">
      <strong className="text-ink">{requestTypeLabel(t, approval.request_type)}</strong>
      {approval.authorization_groups.map((group) => (
        <div key={`${group.kind}:${group.key}`}>
          <span className="font-semibold text-ink-soft">
            {t("portal.column.groups")}: {group.name || group.key} [{group.kind}]
          </span>
          {group.grants.length > 0 ? (
            <ul className="mt-0.5 grid gap-0.5 pl-3 text-ink-faint">
              {group.grants.map((grant) => (
                <li key={`${grant.permission}:${grant.scope}`}>{grantLabel(grant)}</li>
              ))}
            </ul>
          ) : (
            <StatusBanner tone="signal" title={t("portal.approvals.groupWithoutGrants")} />
          )}
        </div>
      ))}
      {approval.direct_grants.length > 0 ? (
        <div>
          <span className="font-semibold text-ink-soft">{t("portal.column.directGrants")}</span>
          <ul className="mt-0.5 grid gap-0.5 pl-3 text-ink-faint">
            {approval.direct_grants.map((grant) => (
              <li key={`${grant.permission}:${grant.scope}`}>{grantLabel(grant)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {!hasTargets && approval.request_type === "revoke" ? (
        <span className="text-ink-soft">{t("portal.approvals.fullRevoke")}</span>
      ) : null}
    </div>
  );
}

function decisionDetails(
  t: Translator,
  approval: PortalApprovalRow | undefined,
  isLoading: boolean,
  error: Error | null,
): ReactNode {
  if (isLoading) {
    return <StatusBanner title={t("common.loading")} />;
  }
  if (error || !approval) {
    return (
      <StatusBanner
        tone="signal"
        title={t("portal.approvals.detailLoadFailed")}
        message={error?.message}
      />
    );
  }
  const factsComplete = approvalFactsAreComplete(approval);
  return (
    <section className="grid gap-3 rounded-[3px] border border-ink/12 bg-paper-deep/20 p-3">
      <strong className="text-sm text-ink">{t("portal.approvals.facts")}</strong>
      {approvalContentDetails(t, approval)}
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs leading-5">
        <dt className="text-ink-faint">{t("portal.column.term")}</dt>
        <dd>{grantTypeLabel(t, approval.grant_type)}</dd>
        {approval.grant_expires_at ? (
          <>
            <dt className="text-ink-faint">{t("portal.column.expiresAt")}</dt>
            <dd>{formatDateTime(approval.grant_expires_at)}</dd>
          </>
        ) : null}
        <dt className="text-ink-faint">{t("portal.column.reason")}</dt>
        <dd>{approval.reason || "-"}</dd>
      </dl>
      {!factsComplete ? (
        <StatusBanner tone="signal" title={t("portal.approvals.groupWithoutGrants")} />
      ) : null}
    </section>
  );
}

function approvalFactsAreComplete(approval: PortalApprovalRow): boolean {
  if (approval.authorization_groups.some((group) => group.grants.length === 0)) {
    return false;
  }
  if (approval.grant_type === "timed" && !approval.grant_expires_at) {
    return false;
  }
  const targetCount =
    approval.direct_grants.length +
    approval.authorization_groups.reduce((count, group) => count + group.grants.length, 0);
  return approval.request_type === "revoke" || targetCount > 0;
}

function requestTypeLabel(t: Translator, requestType: string): string {
  switch (requestType) {
    case "grant":
      return t("portal.approvals.requestType.grant");
    case "change":
      return t("portal.approvals.requestType.change");
    case "revoke":
      return t("portal.approvals.requestType.revoke");
    case "renew":
      return t("portal.approvals.requestType.renew");
    default:
      return requestType;
  }
}

function grantLabel(grant: ApprovalGrantFact): string {
  const name = grant.permission_name || grant.permission;
  return `${name} (${grant.permission}) · ${grant.scope}`;
}

function decisionWasCommitted(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    isRecord(error.details) &&
    error.details.decision_committed === true
  );
}

function parseApprovalListPayload(payload: unknown, errorMessage: string): ApprovalListPayload {
  if (!isRecord(payload) || !Array.isArray(payload.data) || !isPagination(payload.pagination)) {
    throw new Error(errorMessage);
  }
  const expectedTotalPages = Math.ceil(payload.pagination.total_items / payload.pagination.page_size);
  if (
    payload.pagination.total_pages !== expectedTotalPages ||
    payload.data.length > payload.pagination.page_size ||
    !payload.data.every(isPortalApprovalRow)
  ) {
    throw new Error(errorMessage);
  }
  return { data: payload.data, pagination: payload.pagination };
}

function parseApprovalDetailPayload(
  payload: unknown,
  errorMessage: string,
): { approval: PortalApprovalRow } {
  if (!isRecord(payload) || !isPortalApprovalRow(payload.approval)) {
    throw new Error(errorMessage);
  }
  return { approval: payload.approval };
}

function isPortalApprovalRow(value: unknown): value is PortalApprovalRow {
  if (!isRecord(value)) {
    return false;
  }
  const requiredStrings = [
    value.app_key,
    value.app_name,
    value.request_type,
    value.status,
    value.status_label,
    value.grant_type,
    value.reason,
    value.submitted_at,
  ];
  return (
    Number.isInteger(value.id) &&
    typeof value.id === "number" &&
    value.id > 0 &&
    requiredStrings.every((item) => typeof item === "string") &&
    isNullableString(value.grant_expires_at) &&
    Array.isArray(value.authorization_groups) &&
    value.authorization_groups.every(isApprovalAuthorizationGroup) &&
    Array.isArray(value.direct_grants) &&
    value.direct_grants.every(isApprovalGrantFact) &&
    isNullableString(value.decided_at) &&
    isNullableString(value.decision_comment) &&
    isApprovalApplicant(value.applicant) &&
    Array.isArray(value.approver_user_ids) &&
    value.approver_user_ids.every((item) => typeof item === "string") &&
    isNullableString(value.decided_by)
  );
}

function isApprovalAuthorizationGroup(value: unknown): value is ApprovalAuthorizationGroup {
  return (
    isRecord(value) &&
    typeof value.key === "string" &&
    typeof value.kind === "string" &&
    typeof value.name === "string" &&
    Array.isArray(value.grants) &&
    value.grants.every(isApprovalGrantFact)
  );
}

function isApprovalGrantFact(value: unknown): value is ApprovalGrantFact {
  return (
    isRecord(value) &&
    typeof value.permission === "string" &&
    typeof value.permission_name === "string" &&
    typeof value.scope === "string"
  );
}

function isApprovalApplicant(value: unknown): value is Required<PortalApprovalApplicant> {
  return (
    isRecord(value) &&
    typeof value.user_id === "string" &&
    typeof value.name === "string" &&
    typeof value.email === "string" &&
    typeof value.department === "string"
  );
}

function isPagination(value: unknown): value is Pagination {
  return (
    isRecord(value) &&
    isIntegerAtLeast(value.page, 1) &&
    isIntegerAtLeast(value.page_size, 1) &&
    isIntegerAtLeast(value.total_items, 0) &&
    isIntegerAtLeast(value.total_pages, 0)
  );
}

function isIntegerAtLeast(value: unknown, minimum: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
