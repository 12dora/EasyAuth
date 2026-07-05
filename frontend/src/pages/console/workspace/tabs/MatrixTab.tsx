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
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { AppScopeItem, AuthorizationGroupGrantItem, AuthorizationGroupItem, ManagedScopePolicyItem, PermissionItem } from "../../../../lib/domain";
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
    { header: "授权组 Key", cell: ({ row }) => <code>{row.original.key}</code> },
    { header: "名称", accessorKey: "name" },
    { header: "类型", cell: ({ row }) => (row.original.kind === "role" ? "角色" : row.original.kind === "bundle" ? "权限包" : row.original.kind) },
    {
      header: "状态",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          <Badge tone={row.original.requestable ? "evergreen" : "neutral"}>{row.original.requestable ? "可申请" : "不可申请"}</Badge>
          <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge>
        </div>
      ),
    },
    {
      id: "actions",
      header: "操作",
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" onClick={() => {
            setSelectedKey(row.original.key);
            setForm({ ...row.original, description: row.original.description ?? "", grants: normalizeGrants(row.original.grants ?? []) });
            setGroupDialogOpen(true);
          }}>
            编辑
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
    { header: "授权项", cell: ({ row }) => `${row.original.permission} / ${row.original.scope}` },
    {
      header: "管理范围计算方式",
      cell: ({ row }) => {
        if (!isManagedUsersGrant(row.original)) {
          return "-";
        }
        return (
          <SelectInput
            aria-label={`${row.original.permission} / ${row.original.scope} 管理范围计算方式`}
            value={managedScopePolicyMode(row.original.managed_scope_policy)}
            onChange={(event) => updateGrantManagedScopePolicy(row.original, event.currentTarget.value, setForm)}
          >
            <option value="inherit">继承应用默认</option>
            <option value="override">按钉钉主管关系</option>
            <option value="disabled">不启用</option>
          </SelectInput>
        );
      },
    },
    {
      header: "有效策略",
      cell: ({ row }) => managedScopeEffectivePolicyLabel(row.original),
    },
    {
      header: "继承来源",
      cell: ({ row }) => managedScopeInheritedFromLabel(row.original),
    },
    {
      header: "健康状态",
      cell: ({ row }) => managedScopeHealthLabel(row.original),
    },
    { header: "状态", cell: ({ row }) => <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge> },
    {
      id: "actions",
      header: "操作",
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton
            type="button"
            variant={row.original.is_active ? "ghost-danger" : "ghost"}
            onClick={() => updateGrant(row.original, !row.original.is_active, setForm)}
          >
            {row.original.is_active ? "停用" : "启用"}
          </TableRowActionButton>
          <TableRowActionButton type="button" variant="ghost-danger" onClick={() => removeGrant(row.original, setForm)}>
            移除
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
        <h2 className="text-base font-semibold text-ink">授权组管理</h2>
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
          新建
        </Button>
      </div>
      {groupsQuery.error ? <StatusBanner tone="signal" title="授权组加载失败" message={(groupsQuery.error as Error).message} /> : null}
      {permissionsQuery.error ? <StatusBanner tone="signal" title="权限加载失败" message={(permissionsQuery.error as Error).message} /> : null}
      {scopesQuery.error ? <StatusBanner tone="signal" title="权限范围加载失败" message={(scopesQuery.error as Error).message} /> : null}
      {saveMutation.error ? <StatusBanner tone="signal" title="授权组保存失败" message={(saveMutation.error as Error).message} /> : null}
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
                <EmptyState title="暂无授权组" description="新建授权组后可为其配置权限授权。" />
              </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
        <TablePagination table={authorizationGroupTable} />
      </TableFrame>
      {groupDialogOpen ? (
        <Dialog title={selectedKey ? "编辑授权组" : "新建授权组"} size="xl" onClose={() => setGroupDialogOpen(false)} footer={
          <>
            <Button type="button" onClick={() => setGroupDialogOpen(false)}>取消</Button>
            <Button
              form="authorization-group-form"
              type="submit"
              variant="primary"
              icon={<Check size={16} />}
              disabled={!form.key || !form.name || saveMutation.isPending}
              loading={saveMutation.isPending}
            >
              保存
            </Button>
          </>
        }>
        <form id="authorization-group-form" className="space-y-4" onSubmit={(event) => {
          event.preventDefault();
          saveMutation.mutate();
        }}>
          <PanelSurface padding="lg" className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="授权组 key">
                <TextInput value={form.key} onChange={(event) => setForm((current) => ({ ...current, key: event.currentTarget.value }))} />
              </Field>
              <Field label="授权组名称">
                <TextInput value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.currentTarget.value }))} />
              </Field>
              <Field label="授权组类型">
                <SelectInput value={form.kind} onChange={(event) => setForm((current) => ({ ...current, kind: event.currentTarget.value }))}>
                  <option value="role">角色（role）</option>
                  <option value="bundle">权限包（bundle）</option>
                </SelectInput>
              </Field>
              <Field label="状态">
                <div className="flex flex-wrap gap-3">
                  <Button type="button" variant="ghost" onClick={() => setForm((current) => ({ ...current, requestable: !current.requestable }))}>
                    {form.requestable ? "设为不可申请" : "设为可申请"}
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setForm((current) => ({ ...current, is_active: !current.is_active }))}>
                    {form.is_active ? "停用" : "启用"}
                  </Button>
                </div>
              </Field>
            </div>
            <Field label="描述">
              <TextArea value={form.description ?? ""} onChange={(event) => setForm((current) => ({ ...current, description: event.currentTarget.value }))} />
            </Field>
          </PanelSurface>
          <PanelSurface padding="lg" className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
            <Field label="授权权限">
              <SelectInput value={grantPermission} onChange={(event) => setGrantPermission(event.currentTarget.value)}>
                {permissions.map((permission) => (
                  <option key={permission.key} value={permission.key}>{permission.key}</option>
                ))}
              </SelectInput>
            </Field>
            <Field label="授权范围">
              <SelectInput value={grantScope} onChange={(event) => setGrantScope(event.currentTarget.value)}>
                {scopeOptions.map((scope) => (
                  <option key={scope.key} value={scope.key}>{scope.key}</option>
                ))}
              </SelectInput>
            </Field>
            <Button type="button" icon={<Plus size={16} />} onClick={addGrant} disabled={!grantPermission || !grantScope}>
              添加授权项
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
                    暂无授权项，请先在上方添加
                  </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
            <TablePagination table={grantTable} />
          </TableFrame>
          <PanelSurface className="flex flex-wrap items-center justify-between gap-3 bg-paper-deep">
            <span className="min-w-0 text-sm text-ink-soft">展开后授权项预览：{form.grants.map((grant) => `${grant.permission} / ${grant.scope}`).join("，") || "-"}</span>
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

function managedScopePolicyMode(policy: ManagedScopePolicyItem | undefined): string {
  if (policy?.mode === "override" || policy?.mode === "disabled") {
    return policy.mode;
  }
  return "inherit";
}

function managedScopePolicyFromMode(mode: string): ManagedScopePolicyItem {
  if (mode === "override") {
    return { mode: "override", resolver: "dingtalk_manager_chain", enabled: true };
  }
  if (mode === "disabled") {
    return { mode: "disabled", resolver: "disabled", enabled: true };
  }
  return inheritManagedScopePolicy();
}

function managedScopeEffectivePolicyLabel(grant: AuthorizationGroupGrantItem): string {
  if (!isManagedUsersGrant(grant)) {
    return "-";
  }
  if (grant.effective_managed_scope_policy?.resolver === "dingtalk_manager_chain") {
    return "按钉钉主管关系";
  }
  return "必须配置管理范围计算方式后才能生效";
}

function managedScopeInheritedFromLabel(grant: AuthorizationGroupGrantItem): string {
  if (!isManagedUsersGrant(grant)) {
    return "-";
  }
  const inheritedFrom = grant.effective_managed_scope_policy?.inherited_from;
  if (inheritedFrom === "app_default") {
    return "应用默认";
  }
  if (grant.effective_managed_scope_policy?.source === "authorization_group_grant") {
    return "Grant 覆盖";
  }
  return "-";
}

function managedScopeHealthLabel(grant: AuthorizationGroupGrantItem): string {
  if (!isManagedUsersGrant(grant)) {
    return "-";
  }
  const status = grant.effective_managed_scope_policy?.health_status;
  if (status === "healthy") {
    return "健康";
  }
  if (status === "warning") {
    return "警告";
  }
  if (status === "blocked") {
    return "阻断";
  }
  if (status === "disabled") {
    return "不启用";
  }
  return grant.effective_managed_scope_policy?.health_message ?? "未配置";
}
