import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";
import { Fragment, useState } from "react";

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
import { ApiError, apiRequest, itemsFromPayload } from "../../../lib/api";
import type { ListPayload } from "../../../lib/api";
import { cn } from "../../../lib/cn";
import type { PortalApprovalItem } from "../../../lib/domain";
import {
  accessRequestStatusLabel,
  badgeToneForAccessRequestStatus,
  formatDateTime,
  grantTypeLabel,
} from "../../../lib/status";
import type { Translator } from "../../../lib/status";

type ApprovalTab = "pending" | "processed";

type ApprovalNoticeKey = "approvals.approved" | "approvals.rejected" | "approvals.conflict" | "";

interface PendingDecision {
  mode: ApprovalDecisionMode;
  approval: PortalApprovalItem;
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
    queryFn: () =>
      apiRequest<ListPayload<PortalApprovalItem>>(
        `/portal/api/v1/me/approvals?status=${tab}&page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}`,
      ),
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
      // 409 = 已被其他审批人处理: 关弹窗、提示冲突并刷新列表, 其余错误留在弹窗内展示。
      if (error instanceof ApiError && error.status === 409) {
        setPendingDecision(null);
        setNoticeKey("approvals.conflict");
        void queryClient.invalidateQueries({ queryKey: ["portal", "approvals"] });
      }
    },
  });

  const approvals = itemsFromPayload<PortalApprovalItem>(query.data);
  const openDecision = (mode: ApprovalDecisionMode, approval: PortalApprovalItem) => {
    decisionMutation.reset();
    setNoticeKey("");
    setPendingDecision({ mode, approval });
  };
  const switchTab = (nextTab: ApprovalTab) => {
    setTab(nextTab);
    setPagination((current) => (current.pageIndex === 0 ? current : { ...current, pageIndex: 0 }));
  };

  const columns = approvalColumns(t, tab, decisionMutation.isPending, openDecision);
  const table = useReactTable({
    data: approvals,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: query.data?.pagination?.total_pages ?? 1,
    state: { pagination },
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
          <StatusBanner tone={noticeKey === "approvals.conflict" ? "amber" : "evergreen"} title={t(noticeKey)} />
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
            <TablePagination table={table} />
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
          errorMessage={dialogErrorMessage}
          isSubmitting={decisionMutation.isPending}
          onClose={() => setPendingDecision(null)}
          onSubmit={(comment) => decisionMutation.mutate({ ...pendingDecision, comment })}
        />
      ) : null}
    </>
  );
}

function approvalColumns(
  t: Translator,
  tab: ApprovalTab,
  actionsDisabled: boolean,
  onDecision: (mode: ApprovalDecisionMode, approval: PortalApprovalItem) => void,
): ColumnDef<PortalApprovalItem>[] {
  const columns: ColumnDef<PortalApprovalItem>[] = [];
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
    { header: t("portal.approvals.column.content"), cell: ({ row }) => approvalContentSummary(t, row.original) },
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

function applicantLabel(approval: PortalApprovalItem): string {
  return approval.applicant?.name || approval.applicant?.email || approval.applicant?.user_id || "-";
}

/** 申请内容摘要: 授权组名列表 + 直接权限条数, 均为空时显示 "-"。 */
function approvalContentSummary(t: Translator, approval: PortalApprovalItem): string {
  const parts: string[] = [];
  const groups = approval.authorization_groups ?? [];
  if (groups.length > 0) {
    parts.push(groups.map((group) => group.name || group.key || "-").join("、"));
  }
  const directGrants = approval.direct_grants ?? [];
  if (directGrants.length > 0) {
    parts.push(t("portal.approvals.summary.directGrants", { count: directGrants.length }));
  }
  return parts.length > 0 ? parts.join("、") : "-";
}
