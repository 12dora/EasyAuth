import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RefreshCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TableRowActionButton } from "../../components/ui/TableActions";
import { TablePagination } from "../../components/ui/TablePagination";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { SelectInput, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { ListPayload } from "../../lib/api";
import type { ApprovalInstanceRow } from "../../lib/domain";
import type { MessageKey } from "../../i18n/messages";
import type { BadgeTone, Translator } from "../../lib/status";
import { APPROVAL_STATUS_LABEL_KEYS, approvalStatusLabel, formatDateTime } from "../../lib/status";

const INSTANCES_QUERY_PREFIX = ["console", "operations", "approval-instances"];
const DEFAULT_PAGE_SIZE = 20;

const APPROVAL_STATUSES = ["created", "submitted", "approved", "rejected", "canceled", "failed"] as const;

export function ApprovalInstancesPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [appKeyInput, setAppKeyInput] = useState("");
  const [appKeyFilter, setAppKeyFilter] = useState("");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE });
  const [redelivered, setRedelivered] = useState(false);

  // app_key 过滤输入去抖后生效, 避免每次按键都打后端。
  useEffect(() => {
    const timer = window.setTimeout(() => setAppKeyFilter(appKeyInput.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [appKeyInput]);

  // 过滤条件变化时回到第一页, 避免带着旧页码请求。
  useEffect(() => {
    setPagination((current) => (current.pageIndex === 0 ? current : { ...current, pageIndex: 0 }));
  }, [statusFilter, appKeyFilter]);

  const query = useQuery({
    queryKey: [...INSTANCES_QUERY_PREFIX, statusFilter, appKeyFilter, pagination.pageIndex, pagination.pageSize],
    queryFn: () =>
      apiRequest<ListPayload<ApprovalInstanceRow>>(
        `/console/api/v1/operations/approval-instances?status=${encodeURIComponent(statusFilter)}&app_key=${encodeURIComponent(appKeyFilter)}&page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}`,
      ),
  });
  const redeliverMutation = useMutation({
    mutationFn: (row: ApprovalInstanceRow) =>
      apiRequest(`/console/api/v1/operations/approval-instances/${row.instance_id}/redeliver`, {
        method: "POST",
        body: {},
      }),
    onSuccess: () => {
      setRedelivered(true);
      void queryClient.invalidateQueries({ queryKey: INSTANCES_QUERY_PREFIX });
    },
  });

  const rows = itemsFromPayload<ApprovalInstanceRow>(query.data);
  const columns = instanceColumns(t, {
    disabled: redeliverMutation.isPending,
    onRedeliver: (row) => {
      setRedelivered(false);
      redeliverMutation.reset();
      redeliverMutation.mutate(row);
    },
  });
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: query.data?.pagination?.total_pages ?? 1,
    state: { pagination },
    onPaginationChange: setPagination,
  });

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.operations")}
        title={t("nav.console.approvalInstances")}
        description={t("approvalInstances.description")}
        actions={
          <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
            {t("common.refresh")}
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SelectInput
          aria-label={t("approvalInstances.filter.status")}
          className="w-44"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.currentTarget.value)}
        >
          <option value="">{t("approvalInstances.filter.allStatuses")}</option>
          {APPROVAL_STATUSES.map((status) => (
            <option key={status} value={status}>
              {t(APPROVAL_STATUS_LABEL_KEYS[status])}
            </option>
          ))}
        </SelectInput>
        <TextInput
          aria-label={t("approvalInstances.filter.appKey")}
          className="w-64"
          placeholder={t("approvalInstances.filter.appKey")}
          autoComplete="off"
          value={appKeyInput}
          onChange={(event) => setAppKeyInput(event.currentTarget.value)}
        />
      </div>
      {redelivered ? (
        <div role="status">
          <StatusBanner tone="evergreen" title={t("approvalInstances.redelivered")} />
        </div>
      ) : null}
      {redeliverMutation.error ? (
        <StatusBanner tone="signal" title={t("approvalInstances.redeliverFailed")} message={(redeliverMutation.error as Error).message} />
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
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                    ))}
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
    </>
  );
}

interface RedeliverActions {
  disabled: boolean;
  onRedeliver: (row: ApprovalInstanceRow) => void;
}

function instanceColumns(t: Translator, actions: RedeliverActions): ColumnDef<ApprovalInstanceRow>[] {
  return [
    {
      header: t("approvalInstances.column.app"),
      cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code>,
    },
    {
      header: t("approvalInstances.column.template"),
      cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.template_key)}</code>,
    },
    {
      header: t("approvalInstances.column.bizKey"),
      cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.biz_key)}</code>,
    },
    {
      header: t("approvalInstances.column.originator"),
      cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.originator_user_id)}</code>,
    },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <span title={row.original.last_error || undefined}>
          <Badge tone={approvalStatusTone(row.original.status)}>{approvalStatusLabel(t, row.original.status)}</Badge>
        </span>
      ),
    },
    {
      header: t("approvalInstances.column.dingtalkInstance"),
      cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.dingtalk_process_instance_id)}</code>,
    },
    {
      header: t("approvalInstances.column.delivery"),
      cell: ({ row }) => <DeliveryCell t={t} row={row.original} actions={actions} />,
    },
    {
      header: t("approvalInstances.column.createdAt"),
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
  ];
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
          <TableRowActionButton type="button" disabled={actions.disabled} onClick={() => actions.onRedeliver(row)}>
            {t("approvalInstances.redeliver")}
          </TableRowActionButton>
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


function approvalStatusTone(status: string): BadgeTone {
  switch (status) {
    case "approved":
      return "evergreen";
    case "rejected":
    case "failed":
      return "signal";
    case "canceled":
      return "faint";
    default:
      // created / submitted 等推进中的状态用中性色。
      return "neutral";
  }
}

function stringValue(value: unknown): string {
  return typeof value === "string" && value !== "" ? value : "-";
}
