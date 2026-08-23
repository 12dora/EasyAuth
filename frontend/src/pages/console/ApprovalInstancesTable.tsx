import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type OnChangeFn,
  type PaginationState,
} from "@tanstack/react-table";
import { Check } from "lucide-react";

import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/ui/EmptyState";
import { TableRowActionButton } from "../../components/ui/TableActions";
import { TablePagination } from "../../components/ui/TablePagination";
import {
  TableBody,
  TableCell,
  TableEmptyRow,
  TableFrame,
  TableHead,
  TableHeaderCell,
  TableRoot,
  TableRow,
  TableSkeletonRows,
} from "../../components/ui/TablePrimitives";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";
import { useI18n } from "../../i18n/I18nProvider";
import type { ApprovalInstanceRow } from "../../lib/domain";
import { approvalStatusLabel, formatDateTime } from "../../lib/status";
import type { BadgeTone, Translator } from "../../lib/status";

export interface RedeliverActions {
  isDisabled: (row: ApprovalInstanceRow) => boolean;
  onRedeliver: (row: ApprovalInstanceRow) => void;
}

export function ApprovalInstancesTable({
  rows,
  isLoading,
  pageCount,
  totalItems,
  pagination,
  onPaginationChange,
  actions,
}: {
  rows: ApprovalInstanceRow[];
  isLoading: boolean;
  pageCount: number;
  totalItems: number;
  pagination: PaginationState;
  onPaginationChange: OnChangeFn<PaginationState>;
  actions: RedeliverActions;
}) {
  const { t } = useI18n();
  const table = useReactTable({
    data: rows,
    columns: instanceColumns(t, actions),
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount,
    state: { pagination },
    onPaginationChange,
  });

  return (
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
          {isLoading ? (
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
      <TablePagination table={table} totalItems={totalItems} />
    </TableFrame>
  );
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
          <TableRowActionButton type="button" disabled={actions.isDisabled(row)} onClick={() => actions.onRedeliver(row)}>
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
