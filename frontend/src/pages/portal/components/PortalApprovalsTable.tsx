import { flexRender, type Table } from "@tanstack/react-table";
import { RefreshCcw } from "lucide-react";
import { Fragment } from "react";

import { Button } from "../../../components/Button";
import { EmptyState } from "../../../components/ui/EmptyState";
import { PageState } from "../../../components/ui/PageState";
import { TablePagination } from "../../../components/ui/TablePagination";
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
} from "../../../components/ui/TablePrimitives";
import { useI18n } from "../../../i18n/I18nProvider";

import type { ApprovalTab, PortalApprovalRow } from "./portalApprovalTypes";

/** 列表整体加载失败(且无可展示行)时替代表格的重试态。 */
export function ApprovalsLoadFailure({
  message,
  isRetrying,
  onRetry,
}: {
  message: string;
  isRetrying: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <PageState
      tone="signal"
      title={t("portal.approvals.loadFailed")}
      description={message}
      action={
        <Button icon={<RefreshCcw size={16} />} loading={isRetrying} onClick={onRetry}>
          {t("common.retry")}
        </Button>
      }
    />
  );
}

export function PortalApprovalsTable({
  table,
  tab,
  isLoading,
  totalItems,
}: {
  table: Table<PortalApprovalRow>;
  tab: ApprovalTab;
  isLoading: boolean;
  totalItems: number;
}) {
  const { t } = useI18n();
  return (
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
          {isLoading ? (
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
      <TablePagination table={table} totalItems={totalItems} />
    </TableFrame>
  );
}
