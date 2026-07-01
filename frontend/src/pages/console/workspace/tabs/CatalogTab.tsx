import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../../components/ui/TablePrimitives";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Field, SelectInput, TextArea, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import type { AppScopeItem, PermissionGroupItem, PermissionItem, PermissionTreePayload } from "../../../../lib/domain";
import { flattenGroups } from "../utils";

type PermissionGroupForm = {
  key: string;
  name: string;
  description: string;
  parent_key: string;
  display_order: number;
  is_active: boolean;
};

type ScopeForm = {
  key: string;
  name: string;
  description: string;
  display_order: number;
  is_active: boolean;
};

type PermissionForm = {
  key: string;
  name: string;
  description: string;
  group_key: string;
  supported_scopes: string;
  risk_level: string;
  is_active: boolean;
};

const emptyPermissionForm: PermissionForm = {
  key: "",
  name: "",
  description: "",
  group_key: "",
  supported_scopes: "GLOBAL",
  risk_level: "standard",
  is_active: true,
};

const emptyGroupForm: PermissionGroupForm = {
  key: "",
  name: "",
  description: "",
  parent_key: "",
  display_order: 0,
  is_active: true,
};

export function CatalogTab({ appKey }: { appKey: string }) {
  const queryClient = useQueryClient();
  const [permissionForm, setPermissionForm] = useState<PermissionForm>(emptyPermissionForm);
  const [editingPermissionKey, setEditingPermissionKey] = useState("");
  const [scopeForm, setScopeForm] = useState<ScopeForm>({ key: "", name: "", description: "", display_order: 0, is_active: true });
  const [editingScopeKey, setEditingScopeKey] = useState("");
  const [groupForm, setGroupForm] = useState<PermissionGroupForm>(emptyGroupForm);
  const [editingGroupKey, setEditingGroupKey] = useState("");
  const treeQuery = useQuery({
    queryKey: ["console", "app", appKey, "permission-tree"],
    queryFn: () => apiRequest<PermissionTreePayload>(`/console/api/v1/apps/${appKey}/permission-tree`),
  });
  const groupsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permission-groups"],
    queryFn: () => apiRequest<{ items?: PermissionGroupItem[] }>(`/console/api/v1/apps/${appKey}/permission-groups`),
  });
  const permissionsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permissions"],
    queryFn: () => apiRequest<{ items?: PermissionItem[] }>(`/console/api/v1/apps/${appKey}/permissions`),
  });
  const scopesQuery = useQuery({
    queryKey: ["console", "app", appKey, "scopes"],
    queryFn: () => apiRequest<{ items?: AppScopeItem[] }>(`/console/api/v1/apps/${appKey}/scopes`),
  });
  const groups = itemsFromPayload<PermissionGroupItem>(groupsQuery.data);
  const treeGroups = useMemo(() => flattenGroups(treeQuery.data?.groups ?? []), [treeQuery.data]);
  const permissions = itemsFromPayload<PermissionItem>(permissionsQuery.data);
  const scopes = itemsFromPayload<AppScopeItem>(scopesQuery.data);
  const savePermissionMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/apps/${appKey}/permissions${editingPermissionKey ? `/${editingPermissionKey}` : ""}`, {
        method: editingPermissionKey ? "PATCH" : "POST",
        body: permissionPayload(permissionForm),
      }),
    onSuccess: () => {
      setPermissionForm(emptyPermissionForm);
      setEditingPermissionKey("");
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "permissions"] });
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "permission-tree"] });
    },
  });
  const saveScopeMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/apps/${appKey}/scopes${editingScopeKey ? `/${editingScopeKey}` : ""}`, {
        method: editingScopeKey ? "PATCH" : "POST",
        body: { ...scopeForm } satisfies JsonObject,
      }),
    onSuccess: () => {
      setScopeForm({ key: "", name: "", description: "", display_order: 0, is_active: true });
      setEditingScopeKey("");
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "scopes"] });
    },
  });
  const saveGroupMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/apps/${appKey}/permission-groups${editingGroupKey ? `/${editingGroupKey}` : ""}`, {
        method: editingGroupKey ? "PATCH" : "POST",
        body: groupPayload(groupForm),
      }),
    onSuccess: () => {
      setGroupForm(emptyGroupForm);
      setEditingGroupKey("");
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "permission-groups"] });
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "permission-tree"] });
    },
  });
  const groupRows = treeGroups.length > 0 ? treeGroups : groups;
  const groupColumns: ColumnDef<PermissionGroupItem>[] = [
    { header: "权限分组", cell: ({ row }) => <code>{row.original.key}</code> },
    { header: "名称", accessorKey: "name" },
    { header: "层级", cell: ({ row }) => row.original.depth ?? "-" },
    { header: "权限数", cell: ({ row }) => row.original.permissions?.length ?? 0 },
    {
      header: "操作",
      cell: ({ row }) => (
        <Button onClick={() => editGroup(row.original, setGroupForm, setEditingGroupKey)}>
          编辑
        </Button>
      ),
    },
  ];
  const groupTable = useReactTable({
    data: groupRows,
    columns: groupColumns,
    getCoreRowModel: getCoreRowModel(),
  });
  const scopeColumns: ColumnDef<AppScopeItem>[] = [
    { header: "Scope", cell: ({ row }) => <code>{row.original.key}</code> },
    { header: "名称", accessorKey: "name" },
    { header: "排序", accessorKey: "display_order" },
    { header: "状态", cell: ({ row }) => <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge> },
    {
      header: "操作",
      cell: ({ row }) => (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => editScope(row.original, setScopeForm, setEditingScopeKey)}>编辑</Button>
          <Button size="sm" variant="ghost-danger" onClick={() => deactivateScope(row.original, setScopeForm, setEditingScopeKey)}>停用</Button>
        </div>
      ),
    },
  ];
  const scopeTable = useReactTable({
    data: scopes,
    columns: scopeColumns,
    getCoreRowModel: getCoreRowModel(),
  });
  const permissionColumns: ColumnDef<PermissionItem>[] = [
    { header: "Permission", cell: ({ row }) => <code>{row.original.key}</code> },
    { header: "名称", accessorKey: "name" },
    { header: "分组", cell: ({ row }) => row.original.group_key || "-" },
    { header: "支持 Scope", cell: ({ row }) => (row.original.supported_scopes ?? []).join("、") || "-" },
    { header: "风险级别", cell: ({ row }) => <Badge tone={row.original.risk_level === "high" ? "signal" : "neutral"}>{riskLevelLabel(row.original.risk_level)}</Badge> },
    {
      header: "操作",
      cell: ({ row }) => (
        <Button onClick={() => editPermission(row.original, setPermissionForm, setEditingPermissionKey)}>
          编辑
        </Button>
      ),
    },
  ];
  const permissionTable = useReactTable({
    data: permissions,
    columns: permissionColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <section className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        <TableFrame>
          <TableRoot>
            <TableHead>
              {groupTable.getHeaderGroups().map((headerGroup) => (
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
              {groupTable.getRowModel().rows.length > 0 ? (
                groupTable.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableEmptyRow colSpan={groupTable.getAllLeafColumns().length}>
                    {treeQuery.isLoading || groupsQuery.isLoading ? "加载中" : "暂无权限分组"}
                  </TableEmptyRow>
              )}
            </TableBody>
          </TableRoot>
        </TableFrame>
        <TableFrame>
          <TableRoot>
            <TableHead>
              {scopeTable.getHeaderGroups().map((headerGroup) => (
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
              {scopeTable.getRowModel().rows.length > 0 ? (
                scopeTable.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableEmptyRow colSpan={scopeTable.getAllLeafColumns().length}>
                    {scopesQuery.isLoading ? "加载中" : "暂无 scope"}
                  </TableEmptyRow>
              )}
            </TableBody>
          </TableRoot>
        </TableFrame>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <section className="space-y-4 rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper p-5 shadow-sm">
          <h2 className="text-base font-semibold text-ink">{editingScopeKey ? "编辑 Scope" : "新增 Scope"}</h2>
          <form className="grid gap-4" onSubmit={(event) => submit(event, () => saveScopeMutation.mutate())}>
            <Field label="Scope key">
              <TextInput value={scopeForm.key} onChange={(event) => setScopeForm((current) => ({ ...current, key: event.currentTarget.value }))} required />
            </Field>
            <Field label="名称">
              <TextInput value={scopeForm.name} onChange={(event) => setScopeForm((current) => ({ ...current, name: event.currentTarget.value }))} required />
            </Field>
            <Field label="描述">
              <TextArea value={scopeForm.description} onChange={(event) => setScopeForm((current) => ({ ...current, description: event.currentTarget.value }))} />
            </Field>
            <Button type="submit" icon={<Plus size={16} />} disabled={saveScopeMutation.isPending}>
              保存 Scope
            </Button>
          </form>
          {saveScopeMutation.error ? <StatusBanner tone="signal" title="Scope 保存失败" message={(saveScopeMutation.error as Error).message} /> : null}
        </section>

        <section className="space-y-4 rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper p-5 shadow-sm">
          <h2 className="text-base font-semibold text-ink">{editingGroupKey ? "编辑权限分组" : "新增权限分组"}</h2>
          <form className="grid gap-4" onSubmit={(event) => submit(event, () => saveGroupMutation.mutate())}>
            <Field label="分组 key">
              <TextInput value={groupForm.key} onChange={(event) => setGroupForm((current) => ({ ...current, key: event.currentTarget.value }))} required />
            </Field>
            <Field label="名称">
              <TextInput value={groupForm.name} onChange={(event) => setGroupForm((current) => ({ ...current, name: event.currentTarget.value }))} required />
            </Field>
            <Field label="上级分组">
              <SelectInput value={groupForm.parent_key} onChange={(event) => setGroupForm((current) => ({ ...current, parent_key: event.currentTarget.value }))}>
                <option value="">无</option>
                {groups.filter((group) => group.key !== groupForm.key).map((group) => (
                  <option key={group.key} value={group.key}>{group.name} ({group.key})</option>
                ))}
              </SelectInput>
            </Field>
            <Field label="描述">
              <TextArea value={groupForm.description} onChange={(event) => setGroupForm((current) => ({ ...current, description: event.currentTarget.value }))} />
            </Field>
            <Button type="submit" icon={<Plus size={16} />} disabled={saveGroupMutation.isPending || !groupForm.key || !groupForm.name}>
              保存权限分组
            </Button>
          </form>
          {saveGroupMutation.error ? <StatusBanner tone="signal" title="权限分组保存失败" message={(saveGroupMutation.error as Error).message} /> : null}
        </section>
      </div>

      <section className="space-y-4 rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper p-5 shadow-sm">
        <h2 className="text-base font-semibold text-ink">{editingPermissionKey ? "编辑 Permission" : "新增 Permission"}</h2>
        <form className="grid gap-4 md:grid-cols-2" onSubmit={(event) => submit(event, () => savePermissionMutation.mutate())}>
            <Field label="Permission key">
              <TextInput value={permissionForm.key} onChange={(event) => setPermissionForm((current) => ({ ...current, key: event.currentTarget.value }))} required />
            </Field>
            <Field label="名称">
              <TextInput value={permissionForm.name} onChange={(event) => setPermissionForm((current) => ({ ...current, name: event.currentTarget.value }))} required />
            </Field>
            <Field label="分组">
              <SelectInput value={permissionForm.group_key} onChange={(event) => setPermissionForm((current) => ({ ...current, group_key: event.currentTarget.value }))}>
                <option value="">不分组</option>
                {groups.map((group) => (
                  <option key={group.key} value={group.key}>{group.name} ({group.key})</option>
                ))}
              </SelectInput>
            </Field>
            <Field label="支持 Scope" hint="多个 scope 用逗号分隔。">
              <TextInput value={permissionForm.supported_scopes} onChange={(event) => setPermissionForm((current) => ({ ...current, supported_scopes: event.currentTarget.value }))} />
            </Field>
            <Field label="风险级别">
              <SelectInput value={permissionForm.risk_level} onChange={(event) => setPermissionForm((current) => ({ ...current, risk_level: event.currentTarget.value }))}>
                <option value="standard">standard</option>
                <option value="high">high</option>
              </SelectInput>
            </Field>
            <Field label="描述">
              <TextArea value={permissionForm.description} onChange={(event) => setPermissionForm((current) => ({ ...current, description: event.currentTarget.value }))} />
            </Field>
            <Button type="submit" icon={<Plus size={16} />} disabled={savePermissionMutation.isPending}>
              保存 Permission
            </Button>
          </form>
          {savePermissionMutation.error ? <StatusBanner tone="signal" title="Permission 保存失败" message={(savePermissionMutation.error as Error).message} /> : null}
      </section>

      <TableFrame>
        <TableRoot>
          <TableHead>
            {permissionTable.getHeaderGroups().map((headerGroup) => (
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
            {permissionTable.getRowModel().rows.length > 0 ? (
              permissionTable.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableEmptyRow colSpan={permissionTable.getAllLeafColumns().length}>
                  {permissionsQuery.isLoading ? "加载中" : "暂无权限"}
                </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
      </TableFrame>
    </section>
  );
}

function riskLevelLabel(value: string | undefined): string {
  if (value === "high") {
    return "高";
  }
  if (value === "standard" || !value) {
    return "标准";
  }
  return value;
}

function submit(event: FormEvent<HTMLFormElement>, action: () => void) {
  event.preventDefault();
  action();
}

function permissionPayload(form: PermissionForm): JsonObject {
  return {
    key: form.key.trim(),
    name: form.name.trim(),
    description: form.description.trim(),
    group_key: form.group_key || null,
    supported_scopes: form.supported_scopes.split(",").map((scope) => scope.trim()).filter(Boolean),
    risk_level: form.risk_level,
    is_active: form.is_active,
  };
}

function groupPayload(form: PermissionGroupForm): JsonObject {
  return {
    key: form.key.trim(),
    name: form.name.trim(),
    description: form.description.trim(),
    parent_key: form.parent_key || null,
    display_order: form.display_order,
    is_active: form.is_active,
  };
}

function editScope(
  scope: AppScopeItem,
  setScopeForm: (value: ScopeForm) => void,
  setEditingScopeKey: (value: string) => void,
) {
  setEditingScopeKey(scope.key);
  setScopeForm({
    key: scope.key,
    name: scope.name,
    description: scope.description ?? "",
    display_order: scope.display_order,
    is_active: scope.is_active,
  });
}

function deactivateScope(
  scope: AppScopeItem,
  setScopeForm: (value: ScopeForm) => void,
  setEditingScopeKey: (value: string) => void,
) {
  editScope({ ...scope, is_active: false }, setScopeForm, setEditingScopeKey);
}

function editGroup(
  group: PermissionGroupItem & { parent_key?: string; display_order?: number; is_active?: boolean },
  setGroupForm: (value: PermissionGroupForm) => void,
  setEditingGroupKey: (value: string) => void,
) {
  setEditingGroupKey(group.key);
  setGroupForm({
    key: group.key,
    name: group.name,
    description: group.description ?? "",
    parent_key: group.parent_key ?? "",
    display_order: group.display_order ?? 0,
    is_active: group.is_active !== false,
  });
}

function editPermission(
  permission: PermissionItem,
  setPermissionForm: (value: PermissionForm) => void,
  setEditingPermissionKey: (value: string) => void,
) {
  setEditingPermissionKey(permission.key);
  setPermissionForm({
    key: permission.key,
    name: permission.name,
    description: permission.description ?? "",
    group_key: permission.group_key ?? "",
    supported_scopes: (permission.supported_scopes ?? []).join(","),
    risk_level: permission.risk_level ?? "standard",
    is_active: permission.is_active !== false,
  });
}
