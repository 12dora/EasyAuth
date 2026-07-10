import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../../../components/ui/TablePrimitives";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { TableActionCell, TableRowActionButton } from "../../../../components/ui/TableActions";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, SelectInput, TextArea, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useToast } from "../../../../components/ui/Toast";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { AppScopeItem, AuthorizationGroupGrantItem, AuthorizationGroupItem, ManagedScopePolicyItem, PermissionItem } from "../../../../lib/domain";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { Translator } from "../../../../lib/status";
import { buildAuthorizationGroupPayload, grantKey, normalizeGrants } from "../matrix/grantDraft";

type AuthorizationGroupForm = AuthorizationGroupItem;

const emptyGroupForm: AuthorizationGroupForm = {
  key: "",
  kind: "role",
  name: "",
  description: "",
  requestable: true,
  is_active: true,
  grants: [],
};

export function MatrixTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [selectedKey, setSelectedKey] = useState("");
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [form, setForm] = useState<AuthorizationGroupForm>(emptyGroupForm);
  const [grantPermission, setGrantPermission] = useState("");
  const [grantScope, setGrantScope] = useState("");
  const groupsQueryKey = ["console", "app", appKey, "authorization-groups"];

  const groupsQuery = useQuery({
    queryKey: groupsQueryKey,
    queryFn: () => apiRequest<ListPayload<AuthorizationGroupItem>>(`/console/api/v1/apps/${appKey}/authorization-groups`),
  });
  const permissionsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permissions"],
    queryFn: () => apiRequest<ListPayload<PermissionItem>>(`/console/api/v1/apps/${appKey}/permissions`),
  });
  const scopesQuery = useQuery({
    queryKey: ["console", "app", appKey, "scopes"],
    queryFn: () => apiRequest<ListPayload<AppScopeItem>>(`/console/api/v1/apps/${appKey}/scopes`),
  });

  const authorizationGroups = itemsFromPayload<AuthorizationGroupItem>(groupsQuery.data);
  const permissions = itemsFromPayload<PermissionItem>(permissionsQuery.data);
  const scopes = itemsFromPayload<AppScopeItem>(scopesQuery.data);
  const activeScopes = scopes.filter((scope) => scope.is_active);
  const scopeOptions = useMemo(
    () =>
      activeScopes.filter((scope) => {
        const permission = permissions.find((item) => item.key === grantPermission);
        return !permission?.supported_scopes?.length || permission.supported_scopes.includes(scope.key);
      }),
    [activeScopes, grantPermission, permissions],
  );

  useEffect(() => {
    if (!grantPermission && permissions[0]?.key) {
      setGrantPermission(permissions[0].key);
    }
  }, [grantPermission, permissions]);

  useEffect(() => {
    if (!grantScope && scopeOptions[0]?.key) {
      setGrantScope(scopeOptions[0].key);
    }
    if (grantScope && scopeOptions.length > 0 && !scopeOptions.some((scope) => scope.key === grantScope)) {
      setGrantScope(scopeOptions[0].key);
    }
  }, [grantScope, scopeOptions]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = buildAuthorizationGroupPayload(form);
      const method = selectedKey ? "PATCH" : "POST";
      const url = selectedKey
        ? `/console/api/v1/apps/${appKey}/authorization-groups/${selectedKey}`
        : `/console/api/v1/apps/${appKey}/authorization-groups`;
      return apiRequest(url, { method, body: payload });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupsQueryKey });
      setGroupDialogOpen(false);
      setSelectedKey("");
      setForm(emptyGroupForm);
    },
    onError: (error: Error) => {
      toast.error(t("console.matrix.saveFailed"), error.message);
    },
  });

  const addGrant = () => {
    if (!grantPermission || !grantScope) {
      return;
    }
    setForm((current) => {
      if (current.grants.some((grant) => grantKey(grant.permission, grant.scope) === grantKey(grantPermission, grantScope))) {
        return current;
      }
      return {
        ...current,
        grants: [...current.grants, {
          permission: grantPermission,
          scope: grantScope,
          is_active: true,
          ...(grantScope === "MANAGED_USERS" ? { managed_scope_policy: inheritManagedScopePolicy() } : {}),
        }],
      };
    });
  };
  const authorizationGroupColumns: ColumnDef<AuthorizationGroupItem>[] = [
    { header: t("console.matrix.column.key"), cell: ({ row }) => <code>{row.original.key}</code> },
    { header: t("common.name"), accessorKey: "name" },
    { header: t("common.type"), cell: ({ row }) => (row.original.kind === "role" ? t("common.role") : row.original.kind === "bundle" ? t("console.matrix.kindBundle") : row.original.kind) },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          <Badge tone={row.original.requestable ? "evergreen" : "neutral"}>{row.original.requestable ? t("console.matrix.requestable") : t("console.matrix.notRequestable")}</Badge>
          <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? t("common.enabled") : t("common.disabled")}</Badge>
        </div>
      ),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" onClick={() => {
            setSelectedKey(row.original.key);
            setForm({ ...row.original, description: row.original.description ?? "", grants: normalizeGrants(row.original.grants ?? []) });
            setGroupDialogOpen(true);
          }}>
            {t("common.edit")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
  const authorizationGroupTable = useReactTable({
    data: authorizationGroups,
    columns: authorizationGroupColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  const grantColumns: ColumnDef<AuthorizationGroupGrantItem>[] = [
    { header: t("console.matrix.grant.column.item"), cell: ({ row }) => `${row.original.permission} / ${row.original.scope}` },
    {
      header: t("console.matrix.grant.column.managedScope"),
      cell: ({ row }) => {
        if (!isManagedUsersGrant(row.original)) {
          return "-";
        }
        return (
          <SelectInput
            aria-label={t("console.matrix.grant.managedScopeAriaLabel", { permission: row.original.permission, scope: row.original.scope })}
            value={managedScopePolicyResolver(row.original.managed_scope_policy)}
            onChange={(event) => updateGrantManagedScopePolicy(row.original, event.currentTarget.value, setForm)}
          >
            <option value="inherit">{t("console.matrix.grant.policy.inherit")}</option>
            <option value="dingtalk_manager_chain">{t("console.matrix.grant.policy.override")}</option>
            <option value="easyauth_team">{t("console.managedScope.option.team")}</option>
            <option value="union">{t("console.managedScope.option.union")}</option>
            <option value="disabled">{t("console.matrix.grant.policy.disabled")}</option>
          </SelectInput>
        );
      },
    },
    {
      header: t("console.matrix.grant.column.effective"),
      cell: ({ row }) => managedScopeEffectivePolicyLabel(t, row.original),
    },
    {
      header: t("console.matrix.grant.column.inheritedFrom"),
      cell: ({ row }) => managedScopeInheritedFromLabel(t, row.original),
    },
    {
      header: t("console.matrix.grant.column.health"),
      cell: ({ row }) => managedScopeHealthLabel(t, row.original),
    },
    { header: t("common.status"), cell: ({ row }) => <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? t("common.enabled") : t("common.disabled")}</Badge> },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton
            type="button"
            variant={row.original.is_active ? "ghost-danger" : "ghost"}
            onClick={() => updateGrant(row.original, !row.original.is_active, setForm)}
          >
            {row.original.is_active ? t("common.disable") : t("common.enable")}
          </TableRowActionButton>
          <TableRowActionButton type="button" variant="ghost-danger" onClick={() => removeGrant(row.original, setForm)}>
            {t("common.remove")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
  const grantTable = useReactTable({
    data: form.grants,
    columns: grantColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{t("console.matrix.heading")}</h2>
        <Button
          type="button"
          variant="primary"
          icon={<Plus size={16} />}
          onClick={() => {
            setSelectedKey("");
            setForm(emptyGroupForm);
            setGroupDialogOpen(true);
          }}
        >
          {t("common.new")}
        </Button>
      </div>
      {groupsQuery.error ? <StatusBanner tone="signal" title={t("console.matrix.groupsLoadFailed")} message={(groupsQuery.error as Error).message} /> : null}
      {permissionsQuery.error ? <StatusBanner tone="signal" title={t("console.matrix.permissionsLoadFailed")} message={(permissionsQuery.error as Error).message} /> : null}
      {scopesQuery.error ? <StatusBanner tone="signal" title={t("console.matrix.scopesLoadFailed")} message={(scopesQuery.error as Error).message} /> : null}
      <TableFrame>
        <TableRoot>
          <TableHead>
            {authorizationGroupTable.getHeaderGroups().map((headerGroup) => (
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
            {groupsQuery.isLoading ? (
              <TableSkeletonRows columns={authorizationGroupTable.getAllLeafColumns().length} />
            ) : authorizationGroupTable.getRowModel().rows.length > 0 ? (
              authorizationGroupTable.getRowModel().rows.map((row) => (
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
              <TableEmptyRow colSpan={authorizationGroupTable.getAllLeafColumns().length}>
                <EmptyState title={t("console.matrix.groupsEmpty")} description={t("console.matrix.groupsEmptyDescription")} />
              </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
        <TablePagination table={authorizationGroupTable} totalItems={authorizationGroups.length} />
      </TableFrame>
      {groupDialogOpen ? (
        <Dialog title={selectedKey ? t("console.matrix.editTitle") : t("console.matrix.createTitle")} size="xl" onClose={() => setGroupDialogOpen(false)} footer={
          <>
            <Button type="button" onClick={() => setGroupDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button
              form="authorization-group-form"
              type="submit"
              variant="primary"
              icon={<Check size={16} />}
              disabled={!form.key || !form.name || saveMutation.isPending}
              loading={saveMutation.isPending}
            >
              {t("common.save")}
            </Button>
          </>
        }>
        <form id="authorization-group-form" className="space-y-4" onSubmit={(event) => {
          event.preventDefault();
          saveMutation.mutate();
        }}>
          <PanelSurface padding="lg" className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <Field label={t("console.matrix.field.key")}>
                <TextInput value={form.key} onChange={(event) => setForm((current) => ({ ...current, key: event.currentTarget.value }))} />
              </Field>
              <Field label={t("console.matrix.field.name")}>
                <TextInput value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.currentTarget.value }))} />
              </Field>
              <Field label={t("console.matrix.field.kind")}>
                <SelectInput value={form.kind} onChange={(event) => setForm((current) => ({ ...current, kind: event.currentTarget.value }))}>
                  <option value="role">{t("console.matrix.kindOption.role")}</option>
                  <option value="bundle">{t("console.matrix.kindOption.bundle")}</option>
                </SelectInput>
              </Field>
              <Field label={t("common.status")}>
                <div className="flex flex-wrap gap-3">
                  <Button type="button" variant="ghost" onClick={() => setForm((current) => ({ ...current, requestable: !current.requestable }))}>
                    {form.requestable ? t("console.matrix.setNotRequestable") : t("console.matrix.setRequestable")}
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setForm((current) => ({ ...current, is_active: !current.is_active }))}>
                    {form.is_active ? t("common.disable") : t("common.enable")}
                  </Button>
                </div>
              </Field>
            </div>
            <Field label={t("common.description")}>
              <TextArea value={form.description ?? ""} onChange={(event) => setForm((current) => ({ ...current, description: event.currentTarget.value }))} />
            </Field>
          </PanelSurface>
          <PanelSurface padding="lg" className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
            <Field label={t("console.matrix.field.grantPermission")}>
              <SelectInput value={grantPermission} onChange={(event) => setGrantPermission(event.currentTarget.value)}>
                {permissions.map((permission) => (
                  <option key={permission.key} value={permission.key}>{permission.key}</option>
                ))}
              </SelectInput>
            </Field>
            <Field label={t("console.matrix.field.grantScope")}>
              <SelectInput value={grantScope} onChange={(event) => setGrantScope(event.currentTarget.value)}>
                {scopeOptions.map((scope) => (
                  <option key={scope.key} value={scope.key}>{scope.key}</option>
                ))}
              </SelectInput>
            </Field>
            <Button type="button" icon={<Plus size={16} />} onClick={addGrant} disabled={!grantPermission || !grantScope}>
              {t("console.matrix.addGrant")}
            </Button>
          </PanelSurface>
          <TableFrame>
            <TableRoot>
              <TableHead>
                {grantTable.getHeaderGroups().map((headerGroup) => (
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
                {grantTable.getRowModel().rows.length > 0 ? (
                  grantTable.getRowModel().rows.map((row) => (
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
                  <TableEmptyRow colSpan={grantTable.getAllLeafColumns().length}>
                    {t("console.matrix.grant.empty")}
                  </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
            <TablePagination table={grantTable} totalItems={form.grants.length} />
          </TableFrame>
          <PanelSurface className="flex flex-wrap items-center justify-between gap-3 bg-paper-deep">
            <span className="min-w-0 text-sm text-ink-soft">{t("console.matrix.grantPreview", { value: form.grants.map((grant) => `${grant.permission} / ${grant.scope}`).join("，") || "-" })}</span>
          </PanelSurface>
        </form>
        </Dialog>
      ) : null}
    </section>
  );
}

function updateGrant(
  target: AuthorizationGroupGrantItem,
  isActive: boolean,
  setForm: React.Dispatch<React.SetStateAction<AuthorizationGroupForm>>,
) {
  const targetKey = grantKey(target.permission, target.scope);
  // 基于 updater 的 current.grants 计算, 避免批处理时用到过期快照相互覆盖(与 removeGrant 同一口径)。
  setForm((current) => ({
    ...current,
    grants: current.grants.map((grant) => (grantKey(grant.permission, grant.scope) === targetKey ? { ...grant, is_active: isActive } : grant)),
  }));
}

function updateGrantManagedScopePolicy(
  target: AuthorizationGroupGrantItem,
  mode: string,
  setForm: React.Dispatch<React.SetStateAction<AuthorizationGroupForm>>,
) {
  const targetKey = grantKey(target.permission, target.scope);
  setForm((current) => ({
    ...current,
    grants: current.grants.map((grant) =>
      grantKey(grant.permission, grant.scope) === targetKey
        ? { ...grant, managed_scope_policy: managedScopePolicyFromMode(mode) }
        : grant,
    ),
  }));
}

function removeGrant(
  target: AuthorizationGroupGrantItem,
  setForm: React.Dispatch<React.SetStateAction<AuthorizationGroupForm>>,
) {
  const targetKey = grantKey(target.permission, target.scope);
  setForm((current) => ({
    ...current,
    grants: current.grants.filter((grant) => grantKey(grant.permission, grant.scope) !== targetKey),
  }));
}

function isManagedUsersGrant(grant: AuthorizationGroupGrantItem): boolean {
  return grant.scope === "MANAGED_USERS";
}

function inheritManagedScopePolicy(): ManagedScopePolicyItem {
  return { mode: "inherit", resolver: null, enabled: true };
}

function managedScopePolicyResolver(policy: ManagedScopePolicyItem | undefined): string {
  if (policy?.mode === "disabled" || policy?.resolver === "disabled" || policy?.enabled === false) {
    return "disabled";
  }
  const resolver = policy?.resolver;
  if (resolver === "dingtalk_manager_chain" || resolver === "easyauth_team" || resolver === "union") {
    return resolver;
  }
  return "inherit";
}

function managedScopePolicyFromMode(resolver: string): ManagedScopePolicyItem {
  if (resolver === "dingtalk_manager_chain") {
    return { mode: "override", resolver, enabled: true };
  }
  if (resolver === "easyauth_team" || resolver === "union") {
    return { mode: resolver, resolver, enabled: true };
  }
  if (resolver === "disabled") {
    return { mode: "disabled", resolver: "disabled", enabled: true };
  }
  return inheritManagedScopePolicy();
}

function managedScopeEffectivePolicyLabel(t: Translator, grant: AuthorizationGroupGrantItem): string {
  if (!isManagedUsersGrant(grant)) {
    return "-";
  }
  const resolver = grant.effective_managed_scope_policy?.resolver;
  if (resolver === "dingtalk_manager_chain") {
    return t("console.matrix.grant.policy.override");
  }
  if (resolver === "easyauth_team") {
    return t("console.managedScope.option.team");
  }
  if (resolver === "union") {
    return t("console.managedScope.option.union");
  }
  if (resolver === "disabled") {
    return t("console.matrix.grant.policy.disabled");
  }
  return t("console.matrix.grant.effective.unconfigured");
}

function managedScopeInheritedFromLabel(t: Translator, grant: AuthorizationGroupGrantItem): string {
  if (!isManagedUsersGrant(grant)) {
    return "-";
  }
  const inheritedFrom = grant.effective_managed_scope_policy?.inherited_from;
  if (inheritedFrom === "app_default") {
    return t("console.matrix.grant.inheritedFrom.appDefault");
  }
  if (grant.effective_managed_scope_policy?.source === "authorization_group_grant") {
    return t("console.matrix.grant.inheritedFrom.grantOverride");
  }
  return "-";
}

function managedScopeHealthLabel(t: Translator, grant: AuthorizationGroupGrantItem): string {
  if (!isManagedUsersGrant(grant)) {
    return "-";
  }
  const status = grant.effective_managed_scope_policy?.health_status;
  if (status === "healthy") {
    return t("console.matrix.grant.health.healthy");
  }
  if (status === "warning") {
    return t("console.matrix.grant.health.warning");
  }
  if (status === "blocked") {
    return t("console.matrix.grant.health.blocked");
  }
  if (status === "disabled") {
    return t("console.matrix.grant.policy.disabled");
  }
  return grant.effective_managed_scope_policy?.health_message ?? t("console.matrix.grant.health.unconfigured");
}
