import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Compass, Plus, RefreshCcw } from "lucide-react";
import { Fragment, type FormEvent } from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TablePagination } from "../../components/ui/TablePagination";
import { TableActionCell, TableRowActionButton, TableRowActionLink } from "../../components/ui/TableActions";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";

import { AppKeyInput } from "../../components/AppKeyInput";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { UserMultiSelect } from "../../components/UserSelect";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import { generateAppKey } from "../../lib/appKey";
import type { AppListPayload, AppSummary } from "../../lib/domain";
import { formatDateTime, readinessLabel, readinessTone } from "../../lib/status";
import { safeJoin } from "./workspace/utils";

export function ConsoleAppList() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AppSummary | null>(null);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 20 });
  const appsQuery = useQuery({
    queryKey: ["console", "apps", pagination.pageIndex, pagination.pageSize],
    queryFn: () =>
      apiRequest<AppListPayload>(`/console/api/v1/apps?page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}`),
  });
  const apps = itemsFromPayload<AppSummary>(appsQuery.data);
  const createMutation = useMutation({
    mutationFn: (payload: AppCreateFormPayload) =>
      apiRequest<AppListPayload>("/console/api/v1/apps", {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
      const appKey = payload.app?.app_key;
      if (appKey) {
        void navigate(`/console/apps/${appKey}`);
      }
    },
  });
  const updateStatusMutation = useMutation({
    mutationFn: ({ appKey, isActive }: { appKey: string; isActive: boolean }) =>
      apiRequest(`/console/api/v1/apps/${appKey}`, {
        method: "PATCH",
        body: { is_active: isActive },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["console", "apps"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (app: AppSummary) =>
      apiRequest(`/console/api/v1/apps/${app.app_key}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
    },
  });

  const columns: ColumnDef<AppSummary>[] = [
    {
      header: t("appList.column.app"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{row.original.name}</strong>
          <code className={MONO_TEXT_CLASS}>{row.original.app_key}</code>
        </div>
      ),
    },
    {
      header: t("appList.column.owners"),
      cell: ({ row }) => <span>{safeJoin(row.original.owners)}</span>,
    },
    {
      header: t("appList.column.configuration"),
      cell: ({ row }) => (
        <Badge tone={readinessTone(row.original.configuration_status)}>
          {readinessLabel(t, row.original.configuration_status)}
        </Badge>
      ),
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
      header: t("common.updatedAt"),
      cell: ({ row }) => formatDateTime(row.original.updated_at),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton
            type="button"
            variant={row.original.is_active ? "ghost-danger" : "ghost"}
            disabled={updateStatusMutation.isPending}
            onClick={() => updateStatusMutation.mutate({ appKey: row.original.app_key, isActive: !row.original.is_active })}
          >
            {row.original.is_active ? t("common.disable") : t("common.enable")}
          </TableRowActionButton>
          <TableRowActionButton
            type="button"
            variant="ghost-danger"
            disabled={deleteMutation.isPending}
            onClick={() => setDeleteTarget(row.original)}
          >
            {t("common.delete")}
          </TableRowActionButton>
          {/* 已就绪的行以 invisible 占位保持每行操作按钮列对齐 */}
          <TableRowActionLink
            className={row.original.configuration_status === "ready" ? "invisible" : undefined}
            aria-hidden={row.original.configuration_status === "ready" || undefined}
            tabIndex={row.original.configuration_status === "ready" ? -1 : undefined}
            href={`/console/apps/new?app_key=${row.original.app_key}&step=catalog`}
            icon={<Compass size={15} />}
            onClick={(event) => {
              event.preventDefault();
              void navigate(`/console/apps/new?app_key=${row.original.app_key}&step=catalog`);
            }}
          >
            {t("appList.resumeOnboarding")}
          </TableRowActionLink>
          <TableRowActionLink
            href={`/console/apps/${row.original.app_key}`}
            icon={<ArrowRight size={15} />}
            onClick={(event) => {
              event.preventDefault();
              void navigate(`/console/apps/${row.original.app_key}`);
            }}
          >
            {t("common.enter")}
          </TableRowActionLink>
        </TableActionCell>
      ),
    },
  ];
  const table = useReactTable({
    data: apps,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: appsQuery.data?.pagination?.total_pages ?? 1,
    state: { pagination },
    onPaginationChange: setPagination,
  });

  return (
    <>
      <PageHeader
        eyebrow={t("appList.eyebrow")}
        title={t("appList.title")}
        description={t("appList.description")}
        actions={
          <>
            <Button icon={<RefreshCcw size={16} />} loading={appsQuery.isFetching} onClick={() => void appsQuery.refetch()}>
              {t("common.refresh")}
            </Button>
            <Button type="button" icon={<Plus size={16} />} onClick={() => setCreateDialogOpen(true)}>
              {t("appList.quickCreate")}
            </Button>
            <Button type="button" variant="primary" icon={<Compass size={16} />} onClick={() => void navigate("/console/apps/new")}>
              {t("appList.onboardingWizard")}
            </Button>
          </>
        }
      />
      {appsQuery.error && apps.length > 0 ? (
        <StatusBanner tone="signal" title={t("appList.loadFailed")} message={(appsQuery.error as Error).message} />
      ) : null}
      {appsQuery.error && apps.length === 0 ? (
        <PageState
          tone="signal"
          title={t("appList.loadFailed")}
          description={(appsQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={appsQuery.isFetching} onClick={() => void appsQuery.refetch()}>
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
                {appsQuery.isLoading ? (
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
                    <EmptyState title={t("appList.empty.title")} description={t("appList.empty.description")} />
                  </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
            <TablePagination table={table} totalItems={appsQuery.data?.pagination?.total_items ?? apps.length} />
          </TableFrame>
        </section>
      )}
      {createDialogOpen ? (
        <CreateAppDialog
          errorMessage={createMutation.error ? (createMutation.error as Error).message : ""}
          isSubmitting={createMutation.isPending}
          onClose={() => setCreateDialogOpen(false)}
          onSubmit={(payload) => createMutation.mutate(payload)}
        />
      ) : null}
      {deleteTarget ? (
        <ConfirmDialog
          title={`${t("common.delete")} ${deleteTarget.name}`}
          message={`${t("console.overview.field.appName")}: ${deleteTarget.name}; ${t("console.overview.field.appKey")}: ${deleteTarget.app_key}`}
          confirmLabel={t("common.delete")}
          confirming={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
          onClose={() => setDeleteTarget(null)}
        />
      ) : null}
    </>
  );
}

interface AppCreateFormPayload {
  app_key: string;
  name: string;
  description: string;
  owner_user_ids: string[];
  developer_user_ids: string[];
}

function CreateAppDialog({
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: AppCreateFormPayload) => void;
}) {
  const { t } = useI18n();
  const [appKey, setAppKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [ownerUserIds, setOwnerUserIds] = useState<string[]>([]);
  const [developerUserIds, setDeveloperUserIds] = useState<string[]>([]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit({
      app_key: appKey.trim(),
      name: name.trim(),
      description: description.trim(),
      owner_user_ids: ownerUserIds,
      developer_user_ids: developerUserIds,
    });
  };

  return (
    <Dialog
      title={t("appList.createDialog.title")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="create-app-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.create")}
          </Button>
        </>
      }
    >
      <form id="create-app-form" className="grid gap-4" onSubmit={submit}>
        <Field label="app_key">
          <AppKeyInput value={appKey} onChange={setAppKey} onGenerate={() => setAppKey(generateAppKey(name))} required />
        </Field>
        <Field label={t("appList.createDialog.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("appList.createDialog.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        <Field label={t("appList.createDialog.ownerIds")} hint={t("appList.createDialog.userIdsHint")}>
          <UserMultiSelect aria-label="Owner 用户 ID" value={ownerUserIds} onChange={setOwnerUserIds} />
        </Field>
        <Field label={t("appList.createDialog.developerIds")} hint={t("appList.createDialog.userIdsHint")}>
          <UserMultiSelect aria-label="Developer 用户 ID" value={developerUserIds} onChange={setDeveloperUserIds} />
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title={t("appList.createDialog.failed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
