import {
  flexRender,
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
import { MONO_TEXT_CLASS } from "../../../components/ui/tableStyles";
import { useI18n } from "../../../i18n/I18nProvider";
import type { PersonRow } from "../../../lib/domain";
import type { Translator } from "../../../lib/status";
import type { HandoverKind } from "./consolePeopleModel";
import { personStatusLabel, personStatusTone } from "./lifecycleLabels";

export interface PeopleRowActions {
  onOpenHandover: (taskId: number) => void;
  onStart: (person: PersonRow, kind: HandoverKind) => void;
}

export function ConsolePeopleTable({
  people,
  isLoading,
  pageCount,
  totalItems,
  pagination,
  onPaginationChange,
  actions,
}: {
  people: PersonRow[];
  isLoading: boolean;
  pageCount: number;
  totalItems: number;
  pagination: PaginationState;
  onPaginationChange: OnChangeFn<PaginationState>;
  actions: PeopleRowActions;
}) {
  const { t } = useI18n();
  const table = useReactTable({
    data: people,
    columns: peopleColumns(t, actions),
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
              <EmptyState title={t("people.empty.title")} description={t("people.empty.description")} />
            </TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
      <TablePagination table={table} totalItems={totalItems} />
    </TableFrame>
  );
}

function peopleColumns(t: Translator, actions: PeopleRowActions): ColumnDef<PersonRow>[] {
  return [
    {
      header: t("people.column.name"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{row.original.name || row.original.user_id}</strong>
          <code className={MONO_TEXT_CLASS}>{row.original.user_id}</code>
        </div>
      ),
    },
    {
      header: t("people.column.department"),
      cell: ({ row }) => row.original.department || "-",
    },
    {
      header: t("people.column.email"),
      cell: ({ row }) => row.original.email || "-",
    },
    {
      header: t("common.status"),
      cell: ({ row }) => <Badge tone={personStatusTone(row.original.status)}>{personStatusLabel(t, row.original.status)}</Badge>,
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => <PeopleRowActionsCell person={row.original} actions={actions} />,
    },
  ];
}

function PeopleRowActionsCell({ person, actions }: { person: PersonRow; actions: PeopleRowActions }) {
  const { t } = useI18n();
  // 已有进行中的交接单(不限在职状态)直接进入交接, 避免重复建单的困惑。
  if (person.open_handover_task_id) {
    return (
      <TableRowActionLink
        href={`/console/lifecycle/handover-tasks/${person.open_handover_task_id}`}
        icon={<ArrowRight size={15} />}
        onClick={(event) => {
          event.preventDefault();
          actions.onOpenHandover(person.open_handover_task_id as number);
        }}
      >
        {t("people.goHandover")}
      </TableRowActionLink>
    );
  }
  if (person.status !== "active") {
    return null;
  }
  return (
    <>
      <TableRowActionButton type="button" onClick={() => actions.onStart(person, "offboard")}>
        {t("people.startOffboard")}
      </TableRowActionButton>
      <TableRowActionButton type="button" onClick={() => actions.onStart(person, "transfer")}>
        {t("people.startTransfer")}
      </TableRowActionButton>
    </>
  );
}
