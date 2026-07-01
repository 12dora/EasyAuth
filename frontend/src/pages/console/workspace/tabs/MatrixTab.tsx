import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../../components/ui/TablePrimitives";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Field, SelectInput, TextArea, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { AppScopeItem, AuthorizationGroupGrantItem, AuthorizationGroupItem, PermissionItem } from "../../../../lib/domain";
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
  const [form, setForm] = useState<AuthorizationGroupForm>(emptyGroupForm);
  const [grantPermission, setGrantPermission] = useState("");
  const [grantScope, setGrantScope] = useState("");
  const groupsQueryKey = ["console", "app", appKey, "authorization-groups"];

  const groupsQuery = useQuery({
    queryKey: groupsQueryKey,
    queryFn: () => apiRequest<{ items?: AuthorizationGroupItem[] }>(`/console/api/v1/apps/${appKey}/authorization-groups`),
  });
  const permissionsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permissions"],
    queryFn: () => apiRequest<{ items?: PermissionItem[] }>(`/console/api/v1/apps/${appKey}/permissions`),
  });
  const scopesQuery = useQuery({
    queryKey: ["console", "app", appKey, "scopes"],
    queryFn: () => apiRequest<{ items?: AppScopeItem[] }>(`/console/api/v1/apps/${appKey}/scopes`),
  });

  const authorizationGroups = itemsFromPayload<AuthorizationGroupItem>(groupsQuery.data);
  const permissions = itemsFromPayload<PermissionItem>(permissionsQuery.data);
  const scopes = itemsFromPayload<AppScopeItem>(scopesQuery.data);
  const selectedGroup = authorizationGroups.find((group) => group.key === selectedKey) ?? authorizationGroups[0];
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
    if (!selectedGroup) {
      setForm(emptyGroupForm);
      return;
    }
    setSelectedKey(selectedGroup.key);
    setForm({ ...selectedGroup, description: selectedGroup.description ?? "", grants: normalizeGrants(selectedGroup.grants ?? []) });
  }, [selectedGroup?.key, groupsQuery.data]);

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
      const method = selectedGroup ? "PATCH" : "POST";
      const url = selectedGroup
        ? `/console/api/v1/apps/${appKey}/authorization-groups/${selectedGroup.key}`
        : `/console/api/v1/apps/${appKey}/authorization-groups`;
      return apiRequest(url, { method, body: payload });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupsQueryKey });
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
        grants: [...current.grants, { permission: grantPermission, scope: grantScope, is_active: true }],
      };
    });
  };
  const authorizationGroupColumns: ColumnDef<AuthorizationGroupItem>[] = [
    { header: "授权组 key", cell: ({ row }) => <code>{row.original.key}</code> },
    { header: "名称", accessorKey: "name" },
    { header: "类型", accessorKey: "kind" },
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
      header: "操作",
      cell: ({ row }) => (
        <Button onClick={() => setSelectedKey(row.original.key)}>
          编辑
        </Button>
      ),
    },
  ];
  const authorizationGroupTable = useReactTable({
    data: authorizationGroups,
    columns: authorizationGroupColumns,
    getCoreRowModel: getCoreRowModel(),
  });
  const grantColumns: ColumnDef<AuthorizationGroupGrantItem>[] = [
    { header: "Grant", cell: ({ row }) => `${row.original.permission} / ${row.original.scope}` },
    { header: "状态", cell: ({ row }) => <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge> },
    {
      header: "操作",
      cell: ({ row }) => (
        <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-2 text-sm text-ink-soft">
            <input
              type="checkbox"
              checked={row.original.is_active}
              onChange={(event) => updateGrant(form.grants, row.original, event.currentTarget.checked, setForm)}
            />{" "}
            启用
          </label>
          <Button size="sm" variant="ghost-danger" icon={<Trash2 size={16} />} onClick={() => removeGrant(row.original, setForm)}>
            移除
          </Button>
        </div>
      ),
    },
  ];
  const grantTable = useReactTable({
    data: form.grants,
    columns: grantColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">授权组管理</h2>
        <Button
          icon={<Plus size={16} />}
          onClick={() => {
            setSelectedKey("");
            setForm(emptyGroupForm);
          }}
        >
          新建授权组
        </Button>
      </div>
      {saveMutation.error ? <StatusBanner tone="signal" title="授权组保存失败" message={(saveMutation.error as Error).message} /> : null}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(28rem,1.15fr)]">
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
              {authorizationGroupTable.getRowModel().rows.length > 0 ? (
                authorizationGroupTable.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableEmptyRow colSpan={authorizationGroupTable.getAllLeafColumns().length}>
                    {groupsQuery.isLoading ? "加载中" : "暂无授权组"}
                  </TableEmptyRow>
              )}
            </TableBody>
          </TableRoot>
        </TableFrame>
        <div className="space-y-4">
          <div className="space-y-4 rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper p-5 shadow-sm">
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="授权组 key">
                <TextInput value={form.key} onChange={(event) => setForm((current) => ({ ...current, key: event.currentTarget.value }))} />
              </Field>
              <Field label="授权组名称">
                <TextInput value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.currentTarget.value }))} />
              </Field>
              <Field label="授权组类型">
                <SelectInput value={form.kind} onChange={(event) => setForm((current) => ({ ...current, kind: event.currentTarget.value }))}>
                  <option value="role">role</option>
                  <option value="bundle">bundle</option>
                </SelectInput>
              </Field>
              <Field label="状态">
                <div className="flex flex-wrap gap-3">
                  <label className="inline-flex items-center gap-2 text-sm text-ink-soft"><input type="checkbox" checked={form.requestable} onChange={(event) => setForm((current) => ({ ...current, requestable: event.currentTarget.checked }))} /> 可申请</label>
                  <label className="inline-flex items-center gap-2 text-sm text-ink-soft"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.currentTarget.checked }))} /> 启用</label>
                </div>
              </Field>
            </div>
            <Field label="描述">
              <TextArea value={form.description ?? ""} onChange={(event) => setForm((current) => ({ ...current, description: event.currentTarget.value }))} />
            </Field>
          </div>
          <div className="grid items-end gap-4 rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper p-5 shadow-sm md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
            <Field label="Grant Permission">
              <SelectInput value={grantPermission} onChange={(event) => setGrantPermission(event.currentTarget.value)}>
                {permissions.map((permission) => (
                  <option key={permission.key} value={permission.key}>{permission.key}</option>
                ))}
              </SelectInput>
            </Field>
            <Field label="Grant Scope">
              <SelectInput value={grantScope} onChange={(event) => setGrantScope(event.currentTarget.value)}>
                {scopeOptions.map((scope) => (
                  <option key={scope.key} value={scope.key}>{scope.key}</option>
                ))}
              </SelectInput>
            </Field>
            <Button icon={<Plus size={16} />} onClick={addGrant} disabled={!grantPermission || !grantScope}>
              添加 Grant
            </Button>
          </div>
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
                        <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableEmptyRow colSpan={grantTable.getAllLeafColumns().length}>
                      暂无 Grant
                    </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
          </TableFrame>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper-deep p-4">
            <span className="min-w-0 text-sm text-ink-soft">展开后 grants 预览：{form.grants.map((grant) => `${grant.permission} / ${grant.scope}`).join("，") || "-"}</span>
            <Button
              variant="primary"
              icon={<Check size={16} />}
              disabled={!form.key || !form.name || saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              保存授权组
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

function updateGrant(
  grants: AuthorizationGroupGrantItem[],
  target: AuthorizationGroupGrantItem,
  isActive: boolean,
  setForm: React.Dispatch<React.SetStateAction<AuthorizationGroupForm>>,
) {
  const targetKey = grantKey(target.permission, target.scope);
  setForm((current) => ({
    ...current,
    grants: grants.map((grant) => (grantKey(grant.permission, grant.scope) === targetKey ? { ...grant, is_active: isActive } : grant)),
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
