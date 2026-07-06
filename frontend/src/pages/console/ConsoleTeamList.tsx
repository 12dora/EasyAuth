import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Plus, RefreshCcw } from "lucide-react";
import { Fragment, type FormEvent } from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TableActionCell, TableRowActionButton, TableRowActionLink } from "../../components/ui/TableActions";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { useToast } from "../../components/ui/Toast";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject, ListPayload } from "../../lib/api";
import type { TeamPayload, TeamSummary } from "../../lib/domain";
import { formatDateTime } from "../../lib/status";

export function teamLeadersLabel(leaders: TeamSummary["leaders"] | undefined): string {
  const names = (leaders ?? []).map((leader) => leader.name || leader.user_id).filter(Boolean);
  return names.length > 0 ? names.join(", ") : "—";
}

export function ConsoleTeamList() {
  const { t } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TeamSummary | null>(null);
  const teamsQuery = useQuery({
    queryKey: ["console", "teams"],
    queryFn: () => apiRequest<ListPayload<TeamSummary>>("/console/api/v1/teams"),
  });
  const teams = itemsFromPayload<TeamSummary>(teamsQuery.data);
  const deleteMutation = useMutation({
    mutationFn: (team: TeamSummary) =>
      apiRequest(`/console/api/v1/teams/${team.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "teams"] });
      setDeleteTarget(null);
      toast.success(t("console.teams.deleteSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.teams.deleteFailed"), error.message);
    },
  });
  const createMutation = useMutation({
    mutationFn: (payload: TeamCreateFormPayload) =>
      apiRequest<TeamPayload>("/console/api/v1/teams", {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      void queryClient.invalidateQueries({ queryKey: ["console", "teams"] });
      setCreateDialogOpen(false);
      const teamId = payload.team?.id;
      if (teamId) {
        void navigate(`/console/teams/${teamId}`);
      }
    },
  });

  const columns: ColumnDef<TeamSummary>[] = [
    {
      header: t("console.teams.column.name"),
      cell: ({ row }) => <strong>{row.original.name}</strong>,
    },
    {
      header: t("console.teams.column.leaders"),
      cell: ({ row }) => <span>{teamLeadersLabel(row.original.leaders)}</span>,
    },
    {
      header: t("console.teams.column.memberCount"),
      cell: ({ row }) => row.original.member_count ?? 0,
    },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>
          {row.original.is_active ? t("common.enabled") : t("common.disabled")}
        </Badge>
      ),
    },
    {
      header: t("console.teams.column.createdAt"),
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionLink
            href={`/console/teams/${row.original.id}`}
            icon={<ArrowRight size={15} />}
            onClick={(event) => {
              event.preventDefault();
              void navigate(`/console/teams/${row.original.id}`);
            }}
          >
            {t("console.teams.view")}
          </TableRowActionLink>
          <TableRowActionButton type="button" variant="ghost-danger" onClick={() => setDeleteTarget(row.original)}>
            {t("common.delete")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
  const table = useReactTable({
    data: teams,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={t("console.teams.title")}
        description={t("console.teams.description")}
        actions={
          <>
            <Button icon={<RefreshCcw size={16} />} loading={teamsQuery.isFetching} onClick={() => void teamsQuery.refetch()}>
              {t("common.refresh")}
            </Button>
            <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={() => setCreateDialogOpen(true)}>
              {t("console.teams.create")}
            </Button>
          </>
        }
      />
      {teamsQuery.error && teams.length > 0 ? (
        <StatusBanner tone="signal" title={t("console.teams.loadFailed")} message={(teamsQuery.error as Error).message} />
      ) : null}
      {teamsQuery.error && teams.length === 0 ? (
        <PageState
          tone="signal"
          title={t("console.teams.loadFailed")}
          description={(teamsQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={teamsQuery.isFetching} onClick={() => void teamsQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <section className="space-y-3">
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
                {teamsQuery.isLoading ? (
                  <TableSkeletonRows columns={table.getAllLeafColumns().length} />
                ) : table.getRowModel().rows.length > 0 ? (
                  table.getRowModel().rows.map((row) => (
                    <TableRow key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        cell.column.id === "actions" ? (
                          <Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Fragment>
                        ) : (
                          <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                        )
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableEmptyRow colSpan={table.getAllLeafColumns().length}>
                    <EmptyState title={t("console.teams.empty.title")} description={t("console.teams.empty.description")} />
                  </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
          </TableFrame>
        </section>
      )}
      {createDialogOpen ? (
        <TeamCreateDialog
          errorMessage={createMutation.error ? (createMutation.error as Error).message : ""}
          isSubmitting={createMutation.isPending}
          onClose={() => setCreateDialogOpen(false)}
          onSubmit={(payload) => createMutation.mutate(payload)}
        />
      ) : null}
      {deleteTarget ? (
        <ConfirmDialog
          title={t("console.teams.deleteTitle")}
          message={t("console.teams.deleteMessage", { name: deleteTarget.name })}
          confirmLabel={t("common.delete")}
          confirming={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
          onClose={() => setDeleteTarget(null)}
        />
      ) : null}
    </>
  );
}

interface TeamCreateFormPayload {
  name: string;
  description: string;
}

function TeamCreateDialog({
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: TeamCreateFormPayload) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      return;
    }
    onSubmit({ name: normalizedName, description: description.trim() });
  };

  return (
    <Dialog
      title={t("console.teams.create")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="create-team-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.create")}
          </Button>
        </>
      }
    >
      <form id="create-team-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("common.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("common.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title={t("console.teams.createFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
