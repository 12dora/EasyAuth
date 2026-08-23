import {
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type OnChangeFn,
  type PaginationState,
} from "@tanstack/react-table";
import { ArrowRight } from "lucide-react";

import { Badge } from "../../../components/Badge";
import { EmptyState } from "../../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton, TableRowActionLink } from "../../../components/ui/TableActions";
import { TableView } from "../../../components/ui/TableView";
import { daysLeftTone } from "../../../features/handover/surface";
import { useI18n } from "../../../i18n/I18nProvider";
import type { HandoverTaskRow } from "../../../lib/domain";
import { formatDateTime } from "../../../lib/status";
import type { Translator } from "../../../lib/status";
import { handoverKindLabel, handoverTaskStatusLabel, handoverTaskStatusTone } from "./lifecycleLabels";

export interface HandoverTaskRowActions {
  onOpen: (taskId: number) => void;
  onDelete: (task: HandoverTaskRow) => void;
}

export function HandoverTaskTable({
  tasks,
  isLoading,
  pageCount,
  totalItems,
  pagination,
  onPaginationChange,
  actions,
}: {
  tasks: HandoverTaskRow[];
  isLoading: boolean;
  pageCount: number;
  totalItems: number;
  pagination: PaginationState;
  onPaginationChange: OnChangeFn<PaginationState>;
  actions: HandoverTaskRowActions;
}) {
  const { t } = useI18n();
  const table = useReactTable({
    data: tasks,
    columns: taskColumns(t, actions),
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount,
    state: { pagination },
    onPaginationChange,
  });

  return (
    <TableView
      table={table}
      isLoading={isLoading}
      totalItems={totalItems}
      empty={<EmptyState title={t("handover.list.empty.title")} description={t("handover.list.empty.description")} />}
    />
  );
}

function taskColumns(t: Translator, actions: HandoverTaskRowActions): ColumnDef<HandoverTaskRow>[] {
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
        <TableActionCell>
          <TableRowActionLink
            href={`/console/lifecycle/handover-tasks/${row.original.id}`}
            icon={<ArrowRight size={15} />}
            onClick={(event) => {
              event.preventDefault();
              actions.onOpen(row.original.id);
            }}
          >
            {t("handover.continue")}
          </TableRowActionLink>
          {row.original.allowed_actions?.includes("delete") ? (
            <TableRowActionButton type="button" variant="ghost-danger" onClick={() => actions.onDelete(row.original)}>
              {t("common.delete")}
            </TableRowActionButton>
          ) : null}
        </TableActionCell>
      ),
    },
  ];
}
