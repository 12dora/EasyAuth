import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { Fragment } from "react";
import { Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../../../components/ui/TablePrimitives";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton } from "../../../../components/ui/TableActions";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { SecretDialog } from "../../../../components/SecretDialog";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useToast } from "../../../../components/ui/Toast";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { AppCapabilityKey, CredentialItem } from "../../../../lib/domain";
import { credentialDisablePathSegment } from "../../../../lib/credentials";
import { useI18n } from "../../../../i18n/I18nProvider";
import { CreateCredentialForm } from "../credentials/CreateCredentialForm";
import { useCredentialsActions } from "../credentials/useCredentialsActions";
import { credentialKindLabel } from "../utils";

export function CredentialsTab({ appKey, canManage }: { appKey: string; canManage: boolean }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingCredential, setEditingCredential] = useState<CredentialItem | null>(null);
  const [editingCapabilities, setEditingCapabilities] = useState<AppCapabilityKey[]>([]);
  const credentialsQuery = useQuery({
    queryKey: ["console", "app", appKey, "credentials"],
    queryFn: () => apiRequest<ListPayload<CredentialItem>>(`/console/api/v1/apps/${appKey}/credentials`),
  });
  const credentials = itemsFromPayload<CredentialItem>(credentialsQuery.data);
  const capabilitiesMutation = useMutation({
    mutationFn: ({ credential, capabilities }: { credential: CredentialItem; capabilities: AppCapabilityKey[] }) =>
      apiRequest(`/console/api/v1/apps/${appKey}/credentials/${credentialDisablePathSegment(credential.kind)}/${credential.id}/capabilities`, {
        method: "PUT",
        body: { capabilities },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "credentials"] });
      setEditingCredential(null);
      toast.success(t("console.credentials.capabilitiesSaveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.credentials.capabilitiesSaveFailed"), error.message);
    },
  });
  const { createCredential, isCreating, rotateCredential, disableCredential, isCredentialPending, operationError, secretEntries, closeSecretDialog } =
    useCredentialsActions(appKey);
  // 创建/轮换/停用等操作失败时以 toast 反馈, 替代原先的页面内联横幅。
  useEffect(() => {
    if (operationError) {
      toast.error(t("console.credentials.operationFailed"), operationError.message);
    }
  }, [operationError, toast, t]);
  const credentialColumns: ColumnDef<CredentialItem>[] = [
    { header: t("common.name"), accessorKey: "name" },
    { header: t("common.type"), cell: ({ row }) => credentialKindLabel(row.original.kind) },
    {
      header: "client_id",
      cell: ({ row }) => (row.original.client_id ? <code>{row.original.client_id}</code> : "-"),
    },
    {
      id: "capabilities",
      header: t("console.credentials.capabilities"),
      cell: ({ row }) => (
        <div className="flex min-w-36 flex-wrap gap-1">
          {(row.original.capabilities ?? []).length > 0 ? (
            row.original.capabilities?.map((capability) => <Badge key={capability} tone="bond">{capability}</Badge>)
          ) : (
            <Badge tone="faint">{t("console.credentials.permissionOnly")}</Badge>
          )}
        </div>
      ),
    },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? t("common.enabled") : t("common.disabled")}</Badge>
      ),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          {canManage ? (
            <TableRowActionButton
              type="button"
              disabled={isCredentialPending(row.original)}
              onClick={() => {
                setEditingCredential(row.original);
                setEditingCapabilities(row.original.capabilities ?? []);
              }}
            >
              <Pencil size={13} aria-hidden="true" />
              {t("console.credentials.editCapabilities")}
            </TableRowActionButton>
          ) : null}
          {canManage && row.original.kind === "static_token" ? (
            <TableRowActionButton
              type="button"
              disabled={isCredentialPending(row.original)}
              onClick={() => rotateCredential(row.original)}
            >
              {t("console.credentials.rotate")}
            </TableRowActionButton>
          ) : null}
          {canManage ? (
            <TableRowActionButton
              type="button"
              variant="ghost-danger"
              disabled={isCredentialPending(row.original)}
              onClick={() => disableCredential(row.original)}
            >
              {t("console.credentials.disable")}
            </TableRowActionButton>
          ) : <span className="text-xs text-ink-faint">{t("console.integration.readOnlyMode")}</span>}
        </TableActionCell>
      ),
    },
  ];
  const credentialTable = useReactTable({
    data: credentials,
    columns: credentialColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-ink">{t("console.credentials.heading")}</h2>
          <p className="text-body leading-5 text-ink-soft">{t("console.credentials.description")}</p>
        </div>
        {canManage ? (
          <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={() => setCreateDialogOpen(true)}>
            {t("common.new")}
          </Button>
        ) : <Badge>{t("console.integration.readOnlyMode")}</Badge>}
      </div>
      <StatusBanner
        tone="bond"
        title={t("console.credentials.permissionBoundaryTitle")}
        message={t("console.credentials.permissionBoundaryDescription")}
      />
      {credentialsQuery.error ? (
        <StatusBanner tone="signal" title={t("console.credentials.loadFailed")} message={(credentialsQuery.error as Error).message} />
      ) : null}
      <TableFrame>
        <TableRoot>
          <TableHead>
            {credentialTable.getHeaderGroups().map((headerGroup) => (
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
            {credentialsQuery.isLoading ? (
              <TableSkeletonRows columns={credentialColumns.length} />
            ) : credentialTable.getRowModel().rows.length > 0 ? (
              credentialTable.getRowModel().rows.map((row) => (
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
              <TableEmptyRow colSpan={credentialColumns.length}>
                <EmptyState title={t("console.credentials.empty")} description={t("console.credentials.emptyDescription")} />
              </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
        <TablePagination table={credentialTable} totalItems={credentials.length} />
      </TableFrame>
      {createDialogOpen ? (
        <Dialog title={t("console.credentials.createTitle")} onClose={() => setCreateDialogOpen(false)}>
          <CreateCredentialForm
            isCreating={isCreating}
            onCreateCredential={async (kind, name, capabilities) => {
              await createCredential(kind, name, capabilities);
              setCreateDialogOpen(false);
            }}
          />
        </Dialog>
      ) : null}
      {secretEntries[0] ? (
        <SecretDialog
          title={t("console.credentials.secretTitle")}
          primaryLabel={secretEntries[0][0]}
          primaryValue={secretEntries[0][1]}
          secondaryLabel={secretEntries[1]?.[0]}
          secondaryValue={secretEntries[1]?.[1]}
          onClose={closeSecretDialog}
        />
      ) : null}
      {editingCredential ? (
        <Dialog title={t("console.credentials.editCapabilitiesTitle")} onClose={() => setEditingCredential(null)}>
          <div className="space-y-5">
            <p className="text-body leading-5 text-ink-soft">
              {t("console.credentials.editCapabilitiesDescription", { name: editingCredential.name })}
            </p>
            <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label={t("console.credentials.capabilities")}>
              {(["directory", "notify"] as const).map((capability) => (
                <label key={capability} className="flex items-center gap-2 border border-ink/12 bg-paper-soft px-3 py-2 text-body text-ink">
                  <input
                    type="checkbox"
                    checked={editingCapabilities.includes(capability)}
                    onChange={(event) => {
                      const checked = event.currentTarget.checked;
                      setEditingCapabilities((current) => checked
                        ? [...current, capability]
                        : current.filter((item) => item !== capability));
                    }}
                  />
                  <code>{capability}</code>
                </label>
              ))}
            </div>
            <StatusBanner tone="amber" title={t("console.credentials.capabilityWarningTitle")} message={t("console.credentials.capabilityWarningDescription")} />
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={() => setEditingCredential(null)}>{t("common.cancel")}</Button>
              <Button
                type="button"
                variant="primary"
                loading={capabilitiesMutation.isPending}
                onClick={() => capabilitiesMutation.mutate({ credential: editingCredential, capabilities: editingCapabilities })}
              >
                {t("console.credentials.saveCapabilities")}
              </Button>
            </div>
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}
