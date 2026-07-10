import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, RefreshCcw } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field, SelectInput, TextArea, TextInput } from "../../../components/Field";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { EmptyState } from "../../../components/ui/EmptyState";
import { PageState } from "../../../components/ui/PageState";
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
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type { HandoverTaskPayload, PersonRow } from "../../../lib/domain";
import type { Translator } from "../../../lib/status";
import { personStatusLabel, personStatusTone } from "./lifecycleLabels";

const PEOPLE_QUERY_PREFIX = ["console", "people"];
const DEFAULT_PAGE_SIZE = 20;
const PERSON_STATUSES = ["active", "disabled", "departed"] as const;

type HandoverKind = "offboard" | "transfer";

interface HandoverStartTarget {
  person: PersonRow;
  kind: HandoverKind;
}

export function ConsolePeopleList() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE });
  const [startTarget, setStartTarget] = useState<HandoverStartTarget | null>(null);

  // 搜索输入去抖后生效, 避免每次按键都打后端。
  useEffect(() => {
    const timer = window.setTimeout(() => setSearchFilter(searchInput.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  // 过滤条件变化时回到第一页, 避免带着旧页码请求。
  useEffect(() => {
    setPagination((current) => (current.pageIndex === 0 ? current : { ...current, pageIndex: 0 }));
  }, [statusFilter, searchFilter]);

  const peopleQuery = useQuery({
    queryKey: [...PEOPLE_QUERY_PREFIX, statusFilter, searchFilter, pagination.pageIndex, pagination.pageSize],
    queryFn: () =>
      apiRequest<ListPayload<PersonRow>>(
        `/console/api/v1/users?page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}&status=${encodeURIComponent(statusFilter)}&q=${encodeURIComponent(searchFilter)}`,
      ),
  });
  const createTaskMutation = useMutation({
    mutationFn: ({ kind, person, reason }: HandoverStartTarget & { reason: string }) =>
      apiRequest<HandoverTaskPayload>("/console/api/v1/lifecycle/handover-tasks", {
        method: "POST",
        body: { kind, user_id: person.user_id, reason } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      setStartTarget(null);
      const taskId = payload.handover_task?.id;
      if (taskId) {
        void navigate(`/console/lifecycle/handover-tasks/${taskId}`);
      }
    },
  });

  const people = itemsFromPayload<PersonRow>(peopleQuery.data);
  const columns = peopleColumns(t, {
    onOpenHandover: (taskId) => void navigate(`/console/lifecycle/handover-tasks/${taskId}`),
    onStart: (person, kind) => {
      createTaskMutation.reset();
      setStartTarget({ person, kind });
    },
  });
  const table = useReactTable({
    data: people,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: peopleQuery.data?.pagination?.total_pages ?? 1,
    state: { pagination },
    onPaginationChange: setPagination,
  });

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={t("nav.console.people")}
        description={t("people.description")}
        actions={
          <Button icon={<RefreshCcw size={16} />} loading={peopleQuery.isFetching} onClick={() => void peopleQuery.refetch()}>
            {t("common.refresh")}
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SelectInput
          aria-label={t("people.filter.status")}
          className="w-44"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.currentTarget.value)}
        >
          <option value="">{t("people.filter.all")}</option>
          {PERSON_STATUSES.map((status) => (
            <option key={status} value={status}>
              {personStatusLabel(t, status)}
            </option>
          ))}
        </SelectInput>
        <TextInput
          aria-label={t("people.searchPlaceholder")}
          className="w-64"
          placeholder={t("people.searchPlaceholder")}
          autoComplete="off"
          value={searchInput}
          onChange={(event) => setSearchInput(event.currentTarget.value)}
        />
      </div>
      {peopleQuery.error && people.length > 0 ? (
        <StatusBanner tone="signal" title={t("people.loadFailed")} message={(peopleQuery.error as Error).message} />
      ) : null}
      {peopleQuery.error && people.length === 0 ? (
        <PageState
          tone="signal"
          title={t("people.loadFailed")}
          description={(peopleQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={peopleQuery.isFetching} onClick={() => void peopleQuery.refetch()}>
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
              {peopleQuery.isLoading ? (
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
          <TablePagination table={table} totalItems={peopleQuery.data?.pagination?.total_items ?? people.length} />
        </TableFrame>
      )}
      {startTarget ? (
        <HandoverStartDialog
          target={startTarget}
          errorMessage={createTaskMutation.error ? (createTaskMutation.error as Error).message : ""}
          isSubmitting={createTaskMutation.isPending}
          onClose={() => setStartTarget(null)}
          onSubmit={(reason) => createTaskMutation.mutate({ ...startTarget, reason })}
        />
      ) : null}
    </>
  );
}

interface PeopleRowActions {
  onOpenHandover: (taskId: number) => void;
  onStart: (person: PersonRow, kind: HandoverKind) => void;
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
      cell: ({ row }) => {
        const person = row.original;
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
      },
    },
  ];
}

function HandoverStartDialog({
  target,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  target: HandoverStartTarget;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const isOffboard = target.kind === "offboard";
  const personName = target.person.name || target.person.user_id;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit(reason.trim());
  };

  return (
    <Dialog
      title={isOffboard ? t("people.startDialog.offboardTitle") : t("people.startDialog.transferTitle")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="handover-start-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("people.startDialog.confirm")}
          </Button>
        </>
      }
    >
      <form id="handover-start-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">
          {isOffboard
            ? t("people.startDialog.offboardMessage", { name: personName })
            : t("people.startDialog.transferMessage", { name: personName })}
        </p>
        <Field label={t("people.startDialog.reason")} hint={t("people.startDialog.reasonHint")}>
          <TextArea rows={3} value={reason} onChange={(event) => setReason(event.currentTarget.value)} />
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title={t("people.startFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
