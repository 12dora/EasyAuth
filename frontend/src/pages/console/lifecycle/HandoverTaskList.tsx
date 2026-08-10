import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, RefreshCcw } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { SelectInput } from "../../../components/Field";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { PageState } from "../../../components/ui/PageState";
import { TableActionCell, TableRowActionButton, TableRowActionLink } from "../../../components/ui/TableActions";
import { DEFAULT_TABLE_PAGE_SIZE, TablePagination } from "../../../components/ui/TablePagination";
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
import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { ListPayload } from "../../../lib/api";
import type { HandoverTaskRow } from "../../../lib/domain";
import { formatDateTime } from "../../../lib/status";
import type { Translator } from "../../../lib/status";
import { daysLeftTone } from "../../../features/handover/surface";
import {
  handoverAssigneeStateLabel,
  handoverKindLabel,
  handoverTaskStatusLabel,
  handoverTaskStatusTone,
} from "./lifecycleLabels";

const TASK_STATUSES = ["pending", "in_progress", "completed", "cancelled"] as const;
const TASK_KINDS = ["offboard", "transfer", "pre_offboard", "reassign"] as const;
const ASSIGNEE_STATES = ["manager", "subject", "superuser_pool"] as const;

export function HandoverTaskList() {
  const { t } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [assigneeStateFilter, setAssigneeStateFilter] = useState("");
  const [blockedFilter, setBlockedFilter] = useState("");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: DEFAULT_TABLE_PAGE_SIZE });
  const [deleteTarget, setDeleteTarget] = useState<HandoverTaskRow | null>(null);

  const tasksQuery = useQuery({
    queryKey: [
      "console",
      "handover-tasks",
      statusFilter,
      kindFilter,
      assigneeStateFilter,
      blockedFilter,
      pagination.pageIndex,
      pagination.pageSize,
    ],
    queryFn: () => {
      const params = new URLSearchParams({
        status: statusFilter,
        kind: kindFilter,
        page: String(pagination.pageIndex + 1),
        page_size: String(pagination.pageSize),
      });
      if (assigneeStateFilter) {
        params.set("assignee_state", assigneeStateFilter);
      }
      if (blockedFilter) {
        params.set("blocked", blockedFilter);
      }
      return apiRequest<ListPayload<HandoverTaskRow>>(`/console/api/v1/lifecycle/handover-tasks?${params}`);
    },
  });
  const tasks = itemsFromPayload<HandoverTaskRow>(tasksQuery.data);
  const deleteMutation = useMutation({
    mutationFn: (task: HandoverTaskRow) =>
      apiRequest(`/console/api/v1/lifecycle/handover-tasks/${task.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "handover-tasks"] });
      setDeleteTarget(null);
      toast.success(t("handover.list.deleteSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("handover.list.deleteFailed"), error.message);
    },
  });
  const columns = taskColumns(
    t,
    (taskId) => void navigate(`/console/lifecycle/handover-tasks/${taskId}`),
    (task) => setDeleteTarget(task),
  );
  const table = useReactTable({
    data: tasks,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: tasksQuery.data?.pagination?.total_pages ?? 0,
    state: { pagination },
    onPaginationChange: setPagination,
  });

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={t("nav.console.handoverTasks")}
        description={t("handover.list.description")}
        actions={
          <Button icon={<RefreshCcw size={16} />} loading={tasksQuery.isFetching} onClick={() => void tasksQuery.refetch()}>
            {t("common.refresh")}
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SelectInput
          aria-label={t("handover.list.filter.status")}
          className="w-44"
          value={statusFilter}
          onChange={(event) => {
            setStatusFilter(event.currentTarget.value);
            setPagination((current) => ({ ...current, pageIndex: 0 }));
          }}
        >
          <option value="">{t("handover.list.filter.allStatuses")}</option>
          {TASK_STATUSES.map((status) => (
            <option key={status} value={status}>
              {handoverTaskStatusLabel(t, status)}
            </option>
          ))}
        </SelectInput>
        <SelectInput
          aria-label={t("handover.list.filter.kind")}
          className="w-44"
          value={kindFilter}
          onChange={(event) => {
            setKindFilter(event.currentTarget.value);
            setPagination((current) => ({ ...current, pageIndex: 0 }));
          }}
        >
          <option value="">{t("handover.list.filter.allKinds")}</option>
          {TASK_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {handoverKindLabel(t, kind)}
            </option>
          ))}
        </SelectInput>
        <SelectInput
          aria-label={t("handover.console.filter.assigneeState")}
          className="w-44"
          value={assigneeStateFilter}
          onChange={(event) => {
            setAssigneeStateFilter(event.currentTarget.value);
            setPagination((current) => ({ ...current, pageIndex: 0 }));
          }}
        >
          <option value="">{t("handover.console.filter.allAssigneeStates")}</option>
          {ASSIGNEE_STATES.map((state) => (
            <option key={state} value={state}>
              {handoverAssigneeStateLabel(t, state)}
            </option>
          ))}
        </SelectInput>
        <SelectInput
          aria-label={t("handover.console.filter.blockedAll")}
          className="w-44"
          value={blockedFilter}
          onChange={(event) => {
            setBlockedFilter(event.currentTarget.value);
            setPagination((current) => ({ ...current, pageIndex: 0 }));
          }}
        >
          <option value="">{t("handover.console.filter.blockedAll")}</option>
          <option value="true">{t("handover.console.filter.blockedYes")}</option>
          <option value="false">{t("handover.console.filter.blockedNo")}</option>
        </SelectInput>
      </div>
      {tasksQuery.error && tasks.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("handover.list.loadFailed")} message={(tasksQuery.error as Error).message} />
      ) : null}
      {tasksQuery.error && tasks.length === 0 ? (
        <PageState
          tone="signal"
          title={t("handover.list.loadFailed")}
          description={(tasksQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={tasksQuery.isFetching} onClick={() => void tasksQuery.refetch()}>
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
              {tasksQuery.isLoading ? (
                <TableSkeletonRows columns={table.getAllLeafColumns().length} />
              ) : table.getRowModel().rows.length > 0 ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) =>
                      cell.column.id === "actions" ? (
                        <TableActionCell key={cell.id}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableActionCell>
                      ) : (
                        <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                      ),
                    )}
                  </TableRow>
                ))
              ) : (
                <TableEmptyRow colSpan={table.getAllLeafColumns().length}>
                  <EmptyState title={t("handover.list.empty.title")} description={t("handover.list.empty.description")} />
                </TableEmptyRow>
              )}
            </TableBody>
          </TableRoot>
          <TablePagination table={table} totalItems={tasksQuery.data?.pagination?.total_items ?? 0} />
        </TableFrame>
      )}
      {deleteTarget ? (
        <ConfirmDialog
          title={t("handover.list.deleteTitle")}
          message={t("handover.list.deleteMessage", {
            name: deleteTarget.subject.name || deleteTarget.subject.user_id,
          })}
          confirmLabel={t("common.delete")}
          confirming={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
          onClose={() => setDeleteTarget(null)}
        />
      ) : null}
    </>
  );
}

function taskColumns(
  t: Translator,
  onOpen: (taskId: number) => void,
  onDelete: (task: HandoverTaskRow) => void,
): ColumnDef<HandoverTaskRow>[] {
  return [
    {
      header: t("handover.list.column.subject"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-0.5">
          <strong>{row.original.subject.name || row.original.subject.user_id}</strong>
          {row.original.subject.email ? <span className="text-caption text-ink-faint">{row.original.subject.email}</span> : null}
        </div>
      ),
    },
    {
      header: t("handover.list.column.kind"),
      cell: ({ row }) => (
        <div className="flex flex-wrap items-center gap-1">
          <span>{handoverKindLabel(t, row.original.kind)}</span>
          {row.original.blocked_app_count > 0 ? (
            <Badge tone="signal">{row.original.blocked_app_count}</Badge>
          ) : null}
          {row.original.escalation?.days_left != null ? (
            <Badge tone={daysLeftTone(row.original.escalation.days_left)}>{row.original.escalation.days_left}d</Badge>
          ) : null}
        </div>
      ),
    },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <Badge tone={handoverTaskStatusTone(row.original.status)}>{handoverTaskStatusLabel(t, row.original.status)}</Badge>
      ),
    },
    {
      header: t("handover.list.column.createdAt"),
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <>
          <TableRowActionLink
            href={`/console/lifecycle/handover-tasks/${row.original.id}`}
            icon={<ArrowRight size={15} />}
            onClick={(event) => {
              event.preventDefault();
              onOpen(row.original.id);
            }}
          >
            {t("handover.continue")}
          </TableRowActionLink>
          {row.original.allowed_actions?.includes("delete") ? (
            <TableRowActionButton type="button" variant="ghost-danger" onClick={() => onDelete(row.original)}>
              {t("common.delete")}
            </TableRowActionButton>
          ) : null}
        </>
      ),
    },
  ];
}
